"""Parse admin spreadsheet uploads into full assessments (form Flows 1-4)."""
from __future__ import annotations

import io
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from marshmallow import ValidationError

from app import db
from app.core.exceptions import APIError
from app.core.formulas import current_year
from app.core.validators import (
    CHILD_GOAL_TYPES,
    LIFESTYLE_GOAL_TYPES,
    CommunicationSchema,
    PersonalSchema,
)
from app.models.assessment import AssessmentRecord
from app.models.communication import CommunicationDetails
from app.models.family import Child, FamilyDetails
from app.models.personal import PersonalDetails
from app.services.excel_service import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES
from app.services.s3_storage import persist_import_spreadsheet
from app.services.client_assessment_template import (
    build_client_assessment_template_bytes,
    client_field_label_map,
    goal_catalog_by_label,
)

MAX_IMPORT_ROWS = 100
MAX_GOALS_PER_CLIENT = 20

# Calculate body fields accepted on the Clients sheet (same as /calculate).
CALC_COLUMNS = [
    "client_epf_annual",
    "client_epf_accum",
    "client_annual_ret_reqd",
    "spouse_epf_annual",
    "spouse_epf_accum",
    "spouse_annual_ret_reqd",
    "household_monthly",
    "employer_nps_pm",
    "self_nps_pm",
    "current_nps_accum",
    "sa_pm",
    "current_sa_accum",
    "spouse_employer_nps_pm",
    "spouse_self_nps_pm",
    "spouse_current_nps_accum",
    "spouse_sa_pm",
    "spouse_current_sa_accum",
]

CLIENT_REQUIRED_FLOW1 = ("mobile", "email", "consent")
CLIENT_REQUIRED_FULL = CLIENT_REQUIRED_FLOW1 + (
    "client_name",
    "client_occupation",
    "client_designation",
    "client_company",
    "client_dob",
)

COLUMN_ALIASES = {
    "mobile": {"mobile", "phone", "client_mobile", "contact_mobile"},
    "email": {"email", "client_email", "contact_email"},
    "consent": {"consent", "email_consent", "marketing_consent"},
    "spouse_mobile": {"spouse_mobile", "spouse_phone"},
    "spouse_email": {"spouse_email"},
    "residential_address": {"residential_address", "address", "residential"},
    "client_name": {"client_name", "name", "full_name"},
    "client_occupation": {"client_occupation", "occupation"},
    "client_designation": {"client_designation", "designation"},
    "client_company": {"client_company", "company"},
    "client_dob": {"client_dob", "dob", "date_of_birth"},
    "client_retirement_age": {"client_retirement_age", "retirement_age"},
    "spouse_name": {"spouse_name"},
    "spouse_occupation": {"spouse_occupation"},
    "spouse_designation": {"spouse_designation"},
    "spouse_company": {"spouse_company"},
    "spouse_dob": {"spouse_dob"},
    "spouse_retirement_age": {"spouse_retirement_age"},
    "number_of_children": {"number_of_children", "children_count", "num_children"},
    "child_number": {"child_number", "child_no", "child_index"},
    "child_name": {"child_name", "full_name", "name"},
    "occupation": {"occupation", "child_occupation"},
    "financially_dependent": {"financially_dependent", "dependent"},
    "date_of_birth": {"date_of_birth", "dob", "child_dob"},
    "category": {"category", "goal_category"},
    "goal_type": {"goal_type", "type"},
    "goal_name": {"goal_name", "custom_goal_name", "other_goal_name"},
    "target_year": {"target_year", "year"},
    "today_cost": {"today_cost", "current_cost", "cost"},
    "inflation_rate": {"inflation_rate", "inflation"},
}
for col in CALC_COLUMNS:
    COLUMN_ALIASES[col] = {col}

IMPORT_TEMPLATE_SAMPLE_CLIENTS = [
    {
        "mobile": "9876543210",
        "email": "client@example.com",
        "consent": True,
        "spouse_mobile": "9876543211",
        "spouse_email": "spouse@example.com",
        "residential_address": "123 Main St, Mumbai",
        "client_name": "Rahul Sharma",
        "client_occupation": "Engineer",
        "client_designation": "Manager",
        "client_company": "Tech Corp",
        "client_dob": "01/01/1990",
        "client_retirement_age": 60,
        "spouse_name": "Priya Sharma",
        "spouse_occupation": "Teacher",
        "spouse_designation": "Senior Teacher",
        "spouse_company": "ABC School",
        "spouse_dob": "01/01/1995",
        "spouse_retirement_age": 55,
        "number_of_children": 1,
        "client_epf_annual": 33600,
        "client_epf_accum": 500000,
        "client_annual_ret_reqd": 1500000,
        "spouse_epf_annual": 7200,
        "spouse_epf_accum": 0,
        "spouse_annual_ret_reqd": 1000000,
        "household_monthly": 30000,
        # Optional NPS / Superannuation (same keys as POST /calculate)
        "employer_nps_pm": 5000,
        "self_nps_pm": 2000,
        "current_nps_accum": 150000,
        "sa_pm": 3000,
        "current_sa_accum": 200000,
        "spouse_employer_nps_pm": 0,
        "spouse_self_nps_pm": 0,
        "spouse_current_nps_accum": 0,
        "spouse_sa_pm": 0,
        "spouse_current_sa_accum": 0,
    }
]

IMPORT_TEMPLATE_SAMPLE_CHILDREN = [
    {
        "email": "client@example.com",
        "child_number": 1,
        "child_name": "Aarav Sharma",
        "occupation": "Student",
        "financially_dependent": True,
        "date_of_birth": "01/06/2010",
    }
]

IMPORT_TEMPLATE_SAMPLE_GOALS = [
    {
        "email": "client@example.com",
        "category": "child_goal",
        "goal_type": "Graduation",
        "goal_name": "",
        "child_number": 1,
        "target_year": 2035,
        "today_cost": 2500000,
        "inflation_rate": 0.08,
    },
    {
        "email": "client@example.com",
        "category": "lifestyle",
        "goal_type": "Home Purchase",
        "goal_name": "",
        "child_number": "",
        "target_year": 2030,
        "today_cost": 5000000,
        "inflation_rate": 0.06,
    },
    {
        "email": "client@example.com",
        "category": "lifestyle",
        "goal_type": "Other",
        "goal_name": "World Cup Trip",
        "child_number": "",
        "target_year": 2031,
        "today_cost": 500000,
        "inflation_rate": 0.06,
    },
]

# Backward-compatible name used by admin routes.
IMPORT_TEMPLATE_SAMPLE = IMPORT_TEMPLATE_SAMPLE_CLIENTS


def import_template_sheets() -> dict[str, list[dict[str, Any]]]:
    """Legacy dict form (tests / pandas). Prefer build_import_template_bytes()."""
    return {
        "Clients": IMPORT_TEMPLATE_SAMPLE_CLIENTS,
        "Children": IMPORT_TEMPLATE_SAMPLE_CHILDREN,
        "Goals": IMPORT_TEMPLATE_SAMPLE_GOALS,
    }


def build_import_template_bytes() -> bytes:
    """Client-friendly assessment workbook for admin → customer → upload."""
    return build_client_assessment_template_bytes(with_sample=True)


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _resolve_column(header: str, *, context: str = "client") -> str | None:
    normalized = _normalize_header(header)
    if not normalized:
        return None
    # Disambiguate "name" / "dob" by sheet context.
    if context == "child":
        if normalized in {"name", "full_name"}:
            return "child_name"
        if normalized in {"dob", "date_of_birth"}:
            return "date_of_birth"
        if normalized == "occupation":
            return "occupation"
    if context == "goal":
        if normalized in {"type", "goal_type"}:
            return "goal_type"
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
    text = re.sub(r"[^\d]", "", text)
    return text or None


def _normalize_email(value: Any) -> Any:
    text = _empty_to_none(value)
    if text is None:
        return None
    return str(text).strip().lower()


def _parse_bool(value: Any, row_label: str, field: str = "consent") -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise APIError(
            "INVALID_INPUT",
            f"{row_label}: {field} is required (true/false).",
            field=field,
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
        f"{row_label}: {field} must be true/false, got '{value}'.",
        field=field,
        http_status=400,
    )


def _parse_optional_bool(value: Any, default: bool = True) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip().lower()
    if text == "":
        return default
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


def _parse_date(value: Any, row_label: str, field: str) -> date | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(text).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    # Excel serial date as string
    try:
        serial = float(text)
        if serial > 20000:
            return date(1899, 12, 30) + timedelta(days=int(serial))
    except (TypeError, ValueError):
        pass
    raise APIError(
        "INVALID_INPUT",
        f"{row_label}: {field} must be DD/MM/YYYY, got '{value}'.",
        field=field,
        http_status=400,
    )


def _parse_int(value: Any, row_label: str, field: str, default=None):
    text = _empty_to_none(value)
    if text is None:
        return default
    try:
        return int(float(str(text).strip()))
    except (TypeError, ValueError) as exc:
        raise APIError(
            "INVALID_INPUT",
            f"{row_label}: {field} must be an integer, got '{value}'.",
            field=field,
            http_status=400,
        ) from exc


def _parse_float(value: Any, row_label: str, field: str, default=None):
    text = _empty_to_none(value)
    if text is None:
        return default
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise APIError(
            "INVALID_INPUT",
            f"{row_label}: {field} must be a number, got '{value}'.",
            field=field,
            http_status=400,
        ) from exc


def _map_columns(df: pd.DataFrame, *, context: str) -> dict[str, str]:
    column_map: dict[str, str] = {}
    for header in df.columns:
        canonical = _resolve_column(str(header), context=context)
        if canonical and canonical not in column_map:
            column_map[canonical] = header
    return column_map


def _cell(row, column_map: dict[str, str], key: str):
    header = column_map.get(key)
    if header is None:
        return None
    return row.get(header)


def _read_upload_bytes(file_storage) -> tuple[bytes, str, str]:
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
    return raw, filename, ext


def _normalize_sheet_key(name: str) -> str:
    text = str(name or "").strip().lower().replace("—", "-").replace("–", "-")
    return " ".join(text.split())


def _frames_from_raw(raw: bytes, ext: str) -> dict[str, pd.DataFrame]:
    if ext == ".csv":
        text = raw.decode("utf-8-sig", errors="replace")
        return {"Clients": pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)}

    excel = pd.ExcelFile(io.BytesIO(raw))
    frames: dict[str, pd.DataFrame] = {}
    for sheet_name in excel.sheet_names:
        key = _normalize_sheet_key(sheet_name)
        df = excel.parse(sheet_name, dtype=str, header=None)
        df = df.fillna("")
        if key in {
            "clients",
            "client",
            "sheet1",
            "your details",
            "about you",
            "client details",
            "client data",
        }:
            frames["Clients"] = df
        elif key in {"children", "child", "family"}:
            frames["Children"] = df
        elif key in {
            "goals",
            "goal",
            "needs",
            "needs and goals",
            "needs and goals estimation table",
        }:
            frames["Goals"] = df
        elif "Clients" not in frames and len(frames) == 0:
            frames["Clients"] = df
    if "Clients" not in frames:
        raise APIError(
            "INVALID_INPUT",
            "Spreadsheet must include a 'Your Details' or Clients sheet (or a single CSV).",
            field="file",
            http_status=400,
        )
    return frames


def _dataframe_has_header_row(df: pd.DataFrame, required_tokens: set[str]) -> bool:
    if df.empty:
        return False
    first = {_normalize_header(v) for v in df.iloc[0].tolist()}
    return bool(first & required_tokens)


def _promote_header_row(df: pd.DataFrame) -> pd.DataFrame:
    """Use first non-title row that looks like headers when present."""
    if df.empty:
        return df
    # Scan first few rows for a header-like line.
    for start in range(min(5, len(df))):
        values = [str(v).strip() for v in df.iloc[start].tolist()]
        lowered = {_normalize_header(v) for v in values if v}
        if {"email", "mobile", "field", "goal", "child", "full_name", "your_answer"} & lowered:
            header = [
                str(v).strip() if str(v).strip() else f"col_{i}"
                for i, v in enumerate(df.iloc[start].tolist())
            ]
            body = df.iloc[start + 1 :].copy()
            body.columns = header
            body = body.reset_index(drop=True)
            return body
    # Fallback: treat row 0 as header.
    header = [
        str(v).strip() if str(v).strip() else f"col_{i}"
        for i, v in enumerate(df.iloc[0].tolist())
    ]
    body = df.iloc[1:].copy()
    body.columns = header
    return body.reset_index(drop=True)


def _parse_vertical_client_sheet(df_raw: pd.DataFrame) -> dict[str, Any] | None:
    """Parse 'Your Details' Field | Your answer layout into one client payload."""
    label_map = client_field_label_map()
    field_col = None
    value_col = None
    start_row = 0
    for r in range(min(8, len(df_raw))):
        cells = [str(c).strip().lower() for c in df_raw.iloc[r].tolist()]
        for idx, cell in enumerate(cells):
            if cell in {"field", "details", "item"}:
                field_col = idx
            if cell in {"your answer", "answer", "value", "your answers"}:
                value_col = idx
        if field_col is not None and value_col is not None:
            start_row = r + 1
            break
    if field_col is None:
        return None

    values: dict[str, Any] = {}
    for r in range(start_row, len(df_raw)):
        if value_col is not None and field_col != value_col:
            label = str(df_raw.iloc[r, field_col]).strip()
            answer = df_raw.iloc[r, value_col]
        else:
            continue
        if not label or label.lower() in {"section", "field"}:
            continue
        key = _lookup_client_field_key(label, label_map)
        if key is None:
            continue
        values[key] = answer

    if not values.get("email") and not values.get("mobile"):
        return None
    return values


def _lookup_client_field_key(label: str, label_map: dict[str, str]) -> str | None:
    normalized = _normalize_sheet_key(label).replace("_", " ")
    if normalized in label_map:
        return label_map[normalized]
    if "(" in normalized:
        normalized = normalized.split("(", 1)[0].strip()
        if normalized in label_map:
            return label_map[normalized]
    # Strip trailing hints like "— you" / "- you"
    for sep in (" - ", " — ", " – "):
        if sep in normalized:
            base = normalized.split(sep, 1)[0].strip()
            if base in label_map:
                return label_map[base]
    return None


def _looks_like_vertical_client_sheet(df_raw: pd.DataFrame) -> bool:
    if _clients_already_headed(df_raw):
        return False
    flat = [str(v).strip().lower() for v in df_raw.values.flatten()[:50]]
    # Require the explicit client-form headers so tabular Clients sheets are not
    # mistaken for the vertical "Your Details" layout.
    return "field" in flat and "your answer" in flat


def _clients_already_headed(df: pd.DataFrame) -> bool:
    norms = {_normalize_header(str(c)) for c in df.columns}
    return bool(norms & {"email", "mobile", "consent"})


def _records_from_import_frames(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    clients_raw = frames["Clients"]
    if clients_raw.empty:
        raise APIError(
            "INVALID_INPUT",
            "Clients / Your Details sheet has no data.",
            field="file",
            http_status=400,
        )

    if _looks_like_vertical_client_sheet(clients_raw):
        vertical = _parse_vertical_client_sheet(clients_raw)
        if not vertical:
            raise APIError(
                "INVALID_INPUT",
                "Could not read Your Details. Fill Mobile, Email, Consent and try again.",
                field="file",
                http_status=400,
            )
        row_payload = _vertical_values_to_client_row(vertical, row_number=2)
        email = row_payload.get("email")
        children = _parse_children_sheet_flexible(
            frames.get("Children"), default_email=email
        )
        goals = _parse_goals_sheet_flexible(frames.get("Goals"), default_email=email)
        row_payload["children"] = children.get(email, []) if email else []
        if row_payload["children"] and not row_payload.get("number_of_children"):
            row_payload["number_of_children"] = len(row_payload["children"])
        row_payload["goals"] = goals.get(email, []) if email else []
        return _finalize_records([row_payload])

    clients_df = (
        clients_raw
        if _clients_already_headed(clients_raw)
        else _promote_header_row(clients_raw)
    )
    if clients_df.empty:
        raise APIError(
            "INVALID_INPUT",
            "Clients sheet has no data rows.",
            field="file",
            http_status=400,
        )

    column_map = _map_columns(clients_df, context="client")
    missing = [c for c in CLIENT_REQUIRED_FLOW1 if c not in column_map]
    if missing:
        raise APIError(
            "INVALID_INPUT",
            f"Missing required columns: {', '.join(missing)}. "
            f"Use the downloadable template (Your Details / Children / Goals), "
            f"or include mobile, email, consent on a Clients sheet.",
            field="file",
            http_status=400,
        )

    children_by_email = _parse_children_sheet_flexible(frames.get("Children"))
    goals_by_email = _parse_goals_sheet_flexible(frames.get("Goals"))

    records: list[dict[str, Any]] = []
    for index, row in clients_df.iterrows():
        parsed = _parse_client_row(row, column_map, int(index) + 2)
        if not parsed:
            continue
        email = parsed["email"]
        if email and email in children_by_email:
            parsed["children"] = children_by_email[email]
            if not parsed.get("number_of_children"):
                parsed["number_of_children"] = len(parsed["children"])
        else:
            parsed["children"] = []
        parsed["goals"] = goals_by_email.get(email, []) if email else []
        records.append(parsed)

    return _finalize_records(records)


def _finalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _vertical_values_to_client_row(values: dict[str, Any], row_number: int) -> dict[str, Any]:
    series = pd.Series(values)
    column_map = {key: key for key in values}
    return _parse_client_row(series, column_map, row_number)


def _read_upload_frames(file_storage) -> dict[str, pd.DataFrame]:
    raw, _filename, ext = _read_upload_bytes(file_storage)
    return _frames_from_raw(raw, ext)


def _parse_client_row(row, column_map: dict[str, str], row_number: int) -> dict[str, Any] | None:
    row_label = f"Clients row {row_number}"
    mobile = _normalize_mobile(_cell(row, column_map, "mobile"))
    email = _normalize_email(_cell(row, column_map, "email"))
    if not mobile and not email:
        return None

    if "consent" not in column_map:
        raise APIError(
            "INVALID_INPUT",
            f"{row_label}: consent column is required.",
            field="consent",
            http_status=400,
        )

    payload: dict[str, Any] = {
        "mobile": mobile,
        "email": email,
        "consent": _parse_bool(_cell(row, column_map, "consent"), row_label),
        "spouse_mobile": _normalize_mobile(_cell(row, column_map, "spouse_mobile")),
        "spouse_email": _normalize_email(_cell(row, column_map, "spouse_email")),
        "residential_address": _empty_to_none(_cell(row, column_map, "residential_address")),
    }

    # Personal / flow2
    for key in (
        "client_name",
        "client_occupation",
        "client_designation",
        "client_company",
        "spouse_name",
        "spouse_occupation",
        "spouse_designation",
        "spouse_company",
    ):
        payload[key] = _empty_to_none(_cell(row, column_map, key))

    payload["client_dob"] = _parse_date(
        _cell(row, column_map, "client_dob"), row_label, "client_dob"
    )
    payload["spouse_dob"] = _parse_date(
        _cell(row, column_map, "spouse_dob"), row_label, "spouse_dob"
    )
    payload["client_retirement_age"] = _parse_int(
        _cell(row, column_map, "client_retirement_age"), row_label, "client_retirement_age", 60
    )
    payload["spouse_retirement_age"] = _parse_int(
        _cell(row, column_map, "spouse_retirement_age"), row_label, "spouse_retirement_age", 55
    )
    payload["number_of_children"] = _parse_int(
        _cell(row, column_map, "number_of_children"), row_label, "number_of_children", 0
    ) or 0

    calc_inputs: dict[str, Any] = {}
    for key in CALC_COLUMNS:
        if key in column_map:
            parsed = _parse_float(_cell(row, column_map, key), row_label, key, None)
            if parsed is not None:
                calc_inputs[key] = parsed
    payload["calc_inputs"] = calc_inputs
    payload["_row_number"] = row_number

    has_personal = bool(payload.get("client_name"))
    payload["mode"] = "full" if has_personal else "flow1_only"
    return payload


def _parse_children_sheet(df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    return _parse_children_sheet_flexible(df)


def _parse_children_sheet_flexible(
    df: pd.DataFrame | None,
    *,
    default_email: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if df is None or df.empty:
        return {}

    # Raw sheet (no header) vs already-headed.
    if all(isinstance(c, (int, float)) or str(c).isdigit() for c in list(df.columns)[:3]):
        df = _promote_header_row(df)
    elif not ({_normalize_header(c) for c in df.columns} & {
        "email", "child", "child_name", "full_name", "name"
    }):
        df = _promote_header_row(df)

    column_map = _map_columns(df, context="child")
    # Friendly headers: Child | Full name | ...
    headers_norm = {_normalize_header(c): c for c in df.columns}
    if "child_name" not in column_map:
        for alias in ("full_name", "name", "full name", "child_name"):
            key = alias.replace(" ", "_")
            if key in headers_norm or alias in headers_norm:
                column_map["child_name"] = headers_norm.get(key) or headers_norm.get(alias)
                break
        # Column literally "Full name"
        for c in df.columns:
            if _normalize_header(c) in {"full_name", "name", "child_name"}:
                column_map["child_name"] = c
                break
    if "date_of_birth" not in column_map:
        for c in df.columns:
            if "birth" in _normalize_header(c) or _normalize_header(c) == "dob":
                column_map["date_of_birth"] = c
                break
    if "financially_dependent" not in column_map:
        for c in df.columns:
            if "dependent" in _normalize_header(c):
                column_map["financially_dependent"] = c
                break
    child_label_col = None
    for c in df.columns:
        if _normalize_header(c) in {"child", "child_label"}:
            child_label_col = c
            break

    if "child_name" not in column_map:
        raise APIError(
            "INVALID_INPUT",
            "Children sheet requires a Full name column.",
            field="child_name",
            http_status=400,
        )

    by_email: dict[str, list[dict[str, Any]]] = {}
    for index, row in df.iterrows():
        row_label = f"Children row {int(index) + 2}"
        email = _normalize_email(_cell(row, column_map, "email")) if "email" in column_map else None
        email = email or default_email
        if not email:
            # Skip empty trailing rows without failing the whole sheet.
            name_probe = _empty_to_none(_cell(row, column_map, "child_name"))
            if not name_probe:
                continue
            raise APIError(
                "INVALID_INPUT",
                "Children sheet needs an email column, or use the single-client "
                "Your Details template so children link automatically.",
                field="email",
                http_status=400,
            )

        name = _empty_to_none(_cell(row, column_map, "child_name"))
        if not name:
            continue

        child_number = _parse_int(
            _cell(row, column_map, "child_number"), row_label, "child_number", None
        )
        if child_number is None and child_label_col is not None:
            label = str(row.get(child_label_col) or "")
            match = re.search(r"(\d+)", label)
            if match:
                child_number = int(match.group(1))
        if child_number is None:
            child_number = len(by_email.get(email, [])) + 1

        by_email.setdefault(email, []).append(
            {
                "child_number": child_number,
                "child_name": name,
                "occupation": _empty_to_none(_cell(row, column_map, "occupation")),
                "financially_dependent": _parse_optional_bool(
                    _cell(row, column_map, "financially_dependent"), True
                ),
                "date_of_birth": _parse_date(
                    _cell(row, column_map, "date_of_birth"), row_label, "date_of_birth"
                ),
            }
        )
    return by_email


def _parse_goals_sheet(df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    return _parse_goals_sheet_flexible(df)


def _parse_goals_sheet_flexible(
    df: pd.DataFrame | None,
    *,
    default_email: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if df is None or df.empty:
        return {}

    catalog = goal_catalog_by_label()

    # Detect headed vs raw.
    col_norms = {_normalize_header(str(c)) for c in df.columns}
    if not (col_norms & {"goal", "goal_type", "category", "email", "target_year"}):
        df = _promote_header_row(df)

    column_map = _map_columns(df, context="goal")
    for c in df.columns:
        norm = _normalize_header(c)
        if norm == "goal" and "goal_type" not in column_map:
            column_map["goal_label"] = c
        if "target" in norm and "year" in norm:
            column_map["target_year"] = c
        if norm in {"current_cost_(rs)", "current_cost_rs", "current_cost", "today_cost", "cost"}:
            column_map["today_cost"] = c
        if "custom" in norm and "name" in norm:
            column_map["goal_name"] = c
        if norm == "goal_name":
            column_map["goal_name"] = c

    # Client-friendly labelled goals (no category column).
    if "goal_label" in column_map or (
        "category" not in column_map and any(
            _normalize_header(c) == "goal" for c in df.columns
        )
    ):
        if "goal_label" not in column_map:
            for c in df.columns:
                if _normalize_header(c) == "goal":
                    column_map["goal_label"] = c
                    break
        return _parse_labelled_goals(df, column_map, catalog, default_email=default_email)

    # Legacy admin format.
    missing = [c for c in ("category", "goal_type", "target_year") if c not in column_map]
    # email optional when default_email provided
    if "email" not in column_map and not default_email:
        missing.append("email")
    if missing:
        raise APIError(
            "INVALID_INPUT",
            f"Goals sheet missing columns: {', '.join(missing)}. "
            "Prefer the template Goals sheet (Goal / Target year / Current cost).",
            field="file",
            http_status=400,
        )

    by_email: dict[str, list[dict[str, Any]]] = {}
    for index, row in df.iterrows():
        row_label = f"Goals row {int(index) + 2}"
        email = _normalize_email(_cell(row, column_map, "email")) if "email" in column_map else None
        email = email or default_email
        if not email:
            continue
        category = str(_empty_to_none(_cell(row, column_map, "category")) or "").strip()
        goal_type = str(_empty_to_none(_cell(row, column_map, "goal_type")) or "").strip()
        target_year = _parse_int(_cell(row, column_map, "target_year"), row_label, "target_year")
        today_cost = _parse_float(_cell(row, column_map, "today_cost"), row_label, "today_cost")
        if today_cost is None or today_cost <= 0:
            continue
        inflation = _parse_float(
            _cell(row, column_map, "inflation_rate"), row_label, "inflation_rate", 0.06
        )
        child_number = _parse_int(
            _cell(row, column_map, "child_number"), row_label, "child_number", None
        )
        if category not in {"child_goal", "lifestyle"}:
            raise APIError(
                "INVALID_INPUT",
                f"{row_label}: category must be child_goal or lifestyle.",
                field="category",
                http_status=400,
            )
        allowed = CHILD_GOAL_TYPES if category == "child_goal" else LIFESTYLE_GOAL_TYPES
        goal_name = str(_empty_to_none(_cell(row, column_map, "goal_name")) or "").strip()
        if goal_type == "Other":
            if not goal_name:
                raise APIError(
                    "INVALID_INPUT",
                    f"{row_label}: goal_name is required when goal_type is Other.",
                    field="goal_name",
                    http_status=400,
                )
            goal_type = goal_name
        elif goal_type not in allowed:
            if not goal_type or len(goal_type) > 100:
                raise APIError(
                    "INVALID_INPUT",
                    f"{row_label}: goal_type must be one of {allowed}, or Other with goal_name.",
                    field="goal_type",
                    http_status=400,
                )
        by_email.setdefault(email, []).append(
            {
                "category": category,
                "goal_type": goal_type,
                "child_number": child_number,
                "target_year": target_year,
                "today_cost": today_cost,
                "inflation_rate": inflation or 0.06,
            }
        )
    for email, goals in by_email.items():
        if len(goals) > MAX_GOALS_PER_CLIENT:
            raise APIError(
                "INVALID_INPUT",
                f"Maximum {MAX_GOALS_PER_CLIENT} goals for {email}.",
                field="goals",
                http_status=400,
            )
    return by_email


def _parse_labelled_goals(
    df: pd.DataFrame,
    column_map: dict[str, str],
    catalog: dict[str, dict[str, Any]],
    *,
    default_email: str | None,
) -> dict[str, list[dict[str, Any]]]:
    by_email: dict[str, list[dict[str, Any]]] = {}
    for index, row in df.iterrows():
        row_label = f"Goals row {int(index) + 2}"
        label_raw = str(_empty_to_none(row.get(column_map["goal_label"])) or "").strip()
        if not label_raw:
            continue
        # Skip section banner rows.
        if label_raw.lower() in {
            "children's education and marriage goals",
            "other goals",
            "goal",
        }:
            continue

        today_cost = _parse_float(
            _cell(row, column_map, "today_cost") if "today_cost" in column_map else None,
            row_label,
            "today_cost",
            None,
        )
        if today_cost is None or today_cost <= 0:
            continue

        meta = catalog.get(_normalize_sheet_key(label_raw).replace("_", " "))
        if meta is None:
            # Allow free-text as lifestyle Other / custom name.
            meta = {
                "category": "lifestyle",
                "goal_type": "Other",
                "child_number": None,
                "inflation_rate": 0.06,
                "needs_custom_name": True,
                "label": label_raw,
            }

        email = None
        if "email" in column_map:
            email = _normalize_email(_cell(row, column_map, "email"))
        email = email or default_email
        if not email:
            raise APIError(
                "INVALID_INPUT",
                "Goals need a client email (Your Details) or an email column.",
                field="email",
                http_status=400,
            )

        target_year = _parse_int(
            _cell(row, column_map, "target_year") if "target_year" in column_map else None,
            row_label,
            "target_year",
        )
        custom = ""
        if "goal_name" in column_map:
            custom = str(_empty_to_none(_cell(row, column_map, "goal_name")) or "").strip()

        goal_type = meta["goal_type"]
        if meta.get("needs_custom_name") or goal_type == "Other":
            if not custom:
                known_labels = {row["label"] for row in catalog.values()}
                if label_raw not in known_labels and not label_raw.lower().startswith(
                    "child "
                ):
                    custom = label_raw
                else:
                    raise APIError(
                        "INVALID_INPUT",
                        f"{row_label}: write a Custom name for the Others goal.",
                        field="goal_name",
                        http_status=400,
                    )
            goal_type = custom

        by_email.setdefault(email, []).append(
            {
                "category": meta["category"],
                "goal_type": goal_type,
                "child_number": meta.get("child_number"),
                "target_year": target_year,
                "today_cost": today_cost,
                "inflation_rate": float(meta.get("inflation_rate") or 0.06),
            }
        )

    for email, goals in by_email.items():
        if len(goals) > MAX_GOALS_PER_CLIENT:
            raise APIError(
                "INVALID_INPUT",
                f"Maximum {MAX_GOALS_PER_CLIENT} goals for {email}.",
                field="goals",
                http_status=400,
            )
    return by_email


def parse_assessment_import_file(
    file_storage,
) -> tuple[list[dict[str, Any]], bytes, str]:
    """Parse upload into per-client payloads (flow1-only or full form)."""
    raw, filename, ext = _read_upload_bytes(file_storage)
    records = _records_from_import_frames(_frames_from_raw(raw, ext))
    return records, raw, filename


def validate_import_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate communication (+ personal when full mode)."""
    comm_schema = CommunicationSchema()
    personal_schema = PersonalSchema()
    validated = []
    for row in rows:
        row_number = row.get("_row_number", "?")
        try:
            comm = comm_schema.load(
                {
                    "mobile": row["mobile"],
                    "email": row["email"],
                    "consent": row["consent"],
                    "spouse_mobile": row.get("spouse_mobile"),
                    "spouse_email": row.get("spouse_email"),
                    "residential_address": row.get("residential_address"),
                }
            )
        except ValidationError as err:
            field = next(iter(err.messages), None)
            raise APIError(
                "INVALID_INPUT",
                f"Clients row {row_number} failed validation: {err.messages}",
                field=field,
                http_status=400,
            ) from err

        personal = None
        if row.get("mode") == "full":
            try:
                personal = personal_schema.load(
                    {
                        "client_name": row.get("client_name"),
                        "client_occupation": row.get("client_occupation"),
                        "client_designation": row.get("client_designation"),
                        "client_company": row.get("client_company"),
                        "client_dob": row["client_dob"].strftime("%d/%m/%Y")
                        if isinstance(row.get("client_dob"), date)
                        else row.get("client_dob"),
                        "spouse_name": row.get("spouse_name"),
                        "spouse_occupation": row.get("spouse_occupation"),
                        "spouse_designation": row.get("spouse_designation"),
                        "spouse_company": row.get("spouse_company"),
                        "spouse_dob": row["spouse_dob"].strftime("%d/%m/%Y")
                        if isinstance(row.get("spouse_dob"), date)
                        else row.get("spouse_dob"),
                        "client_retirement_age": row.get("client_retirement_age", 60),
                        "spouse_retirement_age": row.get("spouse_retirement_age", 55),
                    }
                )
            except ValidationError as err:
                field = next(iter(err.messages), None)
                raise APIError(
                    "INVALID_INPUT",
                    f"Clients row {row_number} personal details failed: {err.messages}",
                    field=field,
                    http_status=400,
                ) from err

            n = int(row.get("number_of_children") or 0)
            children = row.get("children") or []
            if n > 0 and len(children) == 0:
                raise APIError(
                    "INVALID_INPUT",
                    f"Clients row {row_number}: number_of_children={n} but Children sheet has no rows for this email.",
                    field="children",
                    http_status=400,
                )
            if children and len(children) != n and n > 0:
                raise APIError(
                    "INVALID_INPUT",
                    f"Clients row {row_number}: children count ({len(children)}) must match number_of_children ({n}).",
                    field="children",
                    http_status=400,
                )
            if children and n == 0:
                row["number_of_children"] = len(children)

        validated.append(
            {
                **row,
                "communication": comm,
                "personal": personal,
            }
        )
    return validated


def _age_from_dob(dob: date) -> int:
    return current_year() - dob.year


def bulk_create_assessments_from_flow1(assessments: list[dict[str, Any]]) -> list[str]:
    """Create assessment records with Flow 1 communication details only."""
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


def bulk_create_full_assessments(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Create assessments from full-form import rows; run calculate when possible."""
    from app.api.v1.assessment.routes import save_goals_bulk
    from app.api.v1.calculate.routes import execute_calculation

    submitted_at = datetime.now(timezone.utc)
    created_ids: list[str] = []
    calculated_ids: list[str] = []
    modes = {"full": 0, "flow1_only": 0}

    try:
        for row in rows:
            mode = row.get("mode") or "flow1_only"
            modes[mode] = modes.get(mode, 0) + 1
            record = AssessmentRecord(
                id=uuid.uuid4(),
                status="in_progress",
                flow1_submitted_at=submitted_at,
            )
            db.session.add(record)
            db.session.flush()

            comm_data = row["communication"]
            db.session.add(
                CommunicationDetails(
                    assessment_id=record.id,
                    mobile=comm_data["mobile"],
                    email=comm_data["email"],
                    spouse_mobile=comm_data.get("spouse_mobile"),
                    spouse_email=comm_data.get("spouse_email"),
                    residential_address=comm_data.get("residential_address"),
                    consent=comm_data["consent"],
                    submitted_at=submitted_at,
                )
            )

            if mode == "full" and row.get("personal"):
                personal_data = row["personal"]
                client_age = _age_from_dob(personal_data["client_dob"])
                spouse_age = (
                    _age_from_dob(personal_data["spouse_dob"])
                    if personal_data.get("spouse_dob")
                    else None
                )
                db.session.add(
                    PersonalDetails(
                        assessment_id=record.id,
                        client_name=personal_data["client_name"],
                        client_occupation=personal_data["client_occupation"],
                        client_designation=personal_data["client_designation"],
                        client_company=personal_data["client_company"],
                        client_dob=personal_data["client_dob"],
                        client_age=client_age,
                        spouse_name=personal_data.get("spouse_name"),
                        spouse_occupation=personal_data.get("spouse_occupation"),
                        spouse_designation=personal_data.get("spouse_designation"),
                        spouse_company=personal_data.get("spouse_company"),
                        spouse_dob=personal_data.get("spouse_dob"),
                        spouse_age=spouse_age,
                        client_retirement_age=personal_data.get("client_retirement_age", 60),
                        spouse_retirement_age=personal_data.get("spouse_retirement_age", 55),
                        submitted_at=submitted_at,
                    )
                )
                record.flow2_submitted_at = submitted_at

                children = row.get("children") or []
                n_children = int(row.get("number_of_children") or len(children) or 0)
                family = FamilyDetails(
                    assessment_id=record.id,
                    number_of_children=n_children,
                    submitted_at=submitted_at,
                )
                db.session.add(family)
                db.session.flush()
                record.flow3_submitted_at = submitted_at

                child_id_by_number: dict[int, uuid.UUID] = {}
                for child in children:
                    dob = child.get("date_of_birth")
                    calc_age = _age_from_dob(dob) if dob else None
                    child_row = Child(
                        family_id=family.id,
                        child_number=child["child_number"],
                        full_name=child["child_name"],
                        occupation=child.get("occupation"),
                        financially_dependent=child.get("financially_dependent", True),
                        date_of_birth=dob,
                        calculated_age=calc_age,
                    )
                    db.session.add(child_row)
                    db.session.flush()
                    child_id_by_number[int(child["child_number"])] = child_row.id

                goals_payload = []
                for goal in row.get("goals") or []:
                    item = {
                        "category": goal["category"],
                        "goal_type": goal["goal_type"],
                        "target_year": goal["target_year"],
                        "today_cost": goal["today_cost"],
                        "inflation_rate": goal.get("inflation_rate", 0.06),
                    }
                    child_number = goal.get("child_number")
                    if child_number is not None and goal["category"] == "child_goal":
                        child_id = child_id_by_number.get(int(child_number))
                        if not child_id:
                            raise APIError(
                                "INVALID_INPUT",
                                f"Goal for {comm_data['email']} references missing child_number={child_number}.",
                                field="child_number",
                                http_status=400,
                            )
                        item["child_id"] = child_id
                    goals_payload.append(item)

                save_goals_bulk(record.id, goals_payload, replace_existing=True)
                record.flow4_submitted_at = submitted_at

            created_ids.append(str(record.id))

        db.session.commit()

        # Map email -> calc inputs from validated rows
        calc_by_email = {
            r["communication"]["email"]: r.get("calc_inputs") or {}
            for r in rows
            if r.get("mode") == "full"
        }
        for assessment_id in created_ids:
            aid = uuid.UUID(assessment_id)
            personal = PersonalDetails.query.filter_by(assessment_id=aid).first()
            if not personal:
                continue
            comm = CommunicationDetails.query.filter_by(assessment_id=aid).first()
            body = calc_by_email.get(comm.email if comm else "", {})
            execute_calculation(aid, body)
            calculated_ids.append(assessment_id)

    except Exception:
        db.session.rollback()
        raise

    return {
        "created": len(created_ids),
        "assessment_ids": created_ids,
        "calculated": len(calculated_ids),
        "calculated_ids": calculated_ids,
        "flow1_only": modes.get("flow1_only", 0),
        "full": modes.get("full", 0),
    }


def import_assessments_from_upload(file_storage) -> dict[str, Any]:
    rows, raw, filename = parse_assessment_import_file(file_storage)
    validated = validate_import_rows(rows)
    import_id = str(uuid.uuid4())
    # If any row is full-form, use full importer for all (flow1-only rows still work).
    if any(r.get("mode") == "full" for r in validated):
        result = bulk_create_full_assessments(validated)
    else:
        assessment_ids = bulk_create_assessments_from_flow1(
            [r["communication"] for r in validated]
        )
        result = {
            "created": len(assessment_ids),
            "assessment_ids": assessment_ids,
            "calculated": 0,
            "calculated_ids": [],
            "flow1_only": len(assessment_ids),
            "full": 0,
        }
    result.update(persist_import_spreadsheet(raw, filename, import_id))
    return result
