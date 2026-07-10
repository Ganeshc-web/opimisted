"""Parse admin spreadsheet uploads and bulk-create Flow 1 assessments."""
import csv
import io
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from marshmallow import ValidationError

from app import db
from app.core.exceptions import APIError
from app.core.validators import CommunicationSchema
from app.models.assessment import AssessmentRecord
from app.models.communication import CommunicationDetails
from app.services.excel_service import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES

MAX_IMPORT_ROWS = 100

IMPORT_TEMPLATE_COLUMNS = [
    "mobile",
    "email",
    "consent",
    "spouse_mobile",
    "spouse_email",
    "residential_address",
]

IMPORT_TEMPLATE_SAMPLE = [
    {
        "mobile": "9876543210",
        "email": "client@example.com",
        "consent": True,
        "spouse_mobile": "9876543211",
        "spouse_email": "spouse@example.com",
        "residential_address": "123 Main St, Mumbai",
    },
    {
        "mobile": "9123456780",
        "email": "client2@example.com",
        "consent": False,
        "spouse_mobile": "",
        "spouse_email": "",
        "residential_address": "",
    },
]

COLUMN_ALIASES = {
    "mobile": {"mobile", "phone", "client_mobile", "contact_mobile"},
    "email": {"email", "client_email", "contact_email"},
    "consent": {"consent", "email_consent", "marketing_consent"},
    "spouse_mobile": {"spouse_mobile", "spouse_phone"},
    "spouse_email": {"spouse_email"},
    "residential_address": {"residential_address", "address", "residential"},
}


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _resolve_column(header: str) -> str | None:
    normalized = _normalize_header(header)
    if not normalized:
        return None
    for canonical, aliases in COLUMN_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return None


def _empty_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return None if text == "" else text


def _normalize_mobile(value: Any) -> Any:
    text = _empty_to_none(value)
    if text is None:
        return None
    text = str(text).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _normalize_email(value: Any) -> Any:
    text = _empty_to_none(value)
    if text is None:
        return None
    return str(text).strip().lower()


def _parse_bool(value: Any, row_number: int) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise APIError(
            "INVALID_INPUT",
            f"Row {row_number}: consent is required (true/false).",
            field="consent",
            http_status=400,
        )
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise APIError(
        "INVALID_INPUT",
        f"Row {row_number}: consent must be true/false, got '{value}'.",
        field="consent",
        http_status=400,
    )


def _read_upload_dataframe(file_storage) -> pd.DataFrame:
    filename = file_storage.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise APIError(
            "INVALID_INPUT",
            "Only CSV, XLS, and XLSX files are supported.",
            field="file",
            http_status=400,
        )

    raw = file_storage.read()
    if not raw:
        raise APIError("INVALID_INPUT", "Uploaded file is empty.", field="file", http_status=400)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise APIError(
            "INVALID_INPUT",
            "File exceeds 12MB limit.",
            field="file",
            http_status=400,
        )

    if ext == ".csv":
        text = raw.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)

    return pd.read_excel(io.BytesIO(raw), dtype=str, keep_default_na=False)


def parse_assessment_import_file(file_storage) -> list[dict[str, Any]]:
    """Read first sheet/CSV and map rows to Flow 1 communication payloads."""
    df = _read_upload_dataframe(file_storage)
    if df.empty:
        raise APIError(
            "INVALID_INPUT",
            "Spreadsheet has no data rows.",
            field="file",
            http_status=400,
        )

    column_map: dict[str, str] = {}
    for header in df.columns:
        canonical = _resolve_column(header)
        if canonical and canonical not in column_map:
            column_map[canonical] = header

    missing = [col for col in ("mobile", "email", "consent") if col not in column_map]
    if missing:
        raise APIError(
            "INVALID_INPUT",
            f"Missing required columns: {', '.join(missing)}. "
            f"Expected headers like mobile, email, consent.",
            field="file",
            http_status=400,
        )

    records: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        row_number = int(index) + 2
        payload = {
            "mobile": _normalize_mobile(row.get(column_map["mobile"])),
            "email": _normalize_email(row.get(column_map["email"])),
            "consent": _parse_bool(row.get(column_map["consent"]), row_number),
        }
        for optional in ("spouse_mobile", "spouse_email", "residential_address"):
            if optional in column_map:
                raw = row.get(column_map[optional])
                if optional in {"spouse_mobile"}:
                    payload[optional] = _normalize_mobile(raw)
                elif optional == "spouse_email":
                    payload[optional] = _normalize_email(raw)
                else:
                    payload[optional] = _empty_to_none(raw)

        if not payload["mobile"] and not payload["email"]:
            continue

        records.append(payload)

    if not records:
        raise APIError(
            "INVALID_INPUT",
            "No client rows found after the header row.",
            field="file",
            http_status=400,
        )
    if len(records) > MAX_IMPORT_ROWS:
        raise APIError(
            "INVALID_INPUT",
            f"Maximum {MAX_IMPORT_ROWS} client rows per upload.",
            field="file",
            http_status=400,
        )
    return records


def validate_import_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    schema = CommunicationSchema()
    validated = []
    for index, row in enumerate(rows):
        try:
            validated.append(schema.load(row))
        except ValidationError as err:
            field = next(iter(err.messages), None)
            raise APIError(
                "INVALID_INPUT",
                f"Row {index + 2} failed validation: {err.messages}",
                field=field,
                http_status=400,
            ) from err
    return validated


def bulk_create_assessments_from_flow1(
    assessments: list[dict[str, Any]],
) -> list[str]:
    """Create assessment records with Flow 1 communication details."""
    if len(assessments) > MAX_IMPORT_ROWS:
        raise APIError(
            "INVALID_INPUT",
            f"Maximum {MAX_IMPORT_ROWS} items per bulk request",
            field="assessments",
            http_status=400,
        )

    submitted_at = datetime.now(timezone.utc)
    records: list[AssessmentRecord] = []
    communications: list[CommunicationDetails] = []

    for data in assessments:
        record = AssessmentRecord(
            id=uuid.uuid4(),
            status="in_progress",
            flow1_submitted_at=submitted_at,
        )
        records.append(record)
        communications.append(
            CommunicationDetails(
                assessment_id=record.id,
                mobile=data["mobile"],
                email=data["email"],
                spouse_mobile=data.get("spouse_mobile"),
                spouse_email=data.get("spouse_email"),
                residential_address=data.get("residential_address"),
                consent=data["consent"],
                submitted_at=submitted_at,
            )
        )

    try:
        db.session.add_all(records + communications)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return [str(record.id) for record in records]


def import_assessments_from_upload(file_storage) -> dict[str, Any]:
    rows = parse_assessment_import_file(file_storage)
    validated = validate_import_rows(rows)
    assessment_ids = bulk_create_assessments_from_flow1(validated)
    return {
        "created": len(assessment_ids),
        "assessment_ids": assessment_ids,
    }
