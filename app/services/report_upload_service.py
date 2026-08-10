"""Persist frontend-generated PDF to S3 (or local) and email in one trigger."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from app import db
from app.core.exceptions import APIError
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.communication import CommunicationDetails
from app.models.personal import PersonalDetails
from app.models.report_log import ReportLog
from app.services.email_service import send_report_email
from app.services.report_service import report_download_basename, reports_folder
from app.services.s3_storage import (
    build_storage_key,
    content_type_for_format,
    is_storage_key,
    resolve_local_attachment_path,
    s3_enabled,
    upload_bytes,
)

MAX_FRONTEND_PDF_BYTES = 15 * 1024 * 1024
PDF_MAGIC = b"%PDF"


def _require_assessment_context(assessment_id):
    record = db.session.get(AssessmentRecord, assessment_id)
    if not record:
        raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

    personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
    comm = CommunicationDetails.query.filter_by(assessment_id=assessment_id).first()
    if not personal or not comm:
        raise APIError(
            "INVALID_INPUT",
            "Complete flows 1 and 2 before uploading a report.",
            http_status=400,
        )

    calc = (
        CalculationOutput.query.filter_by(assessment_id=assessment_id)
        .order_by(CalculationOutput.calculated_at.desc())
        .first()
    )
    if not calc:
        raise APIError(
            "INVALID_INPUT",
            "Run /calculate first before uploading a report.",
            http_status=400,
        )
    return record, personal, comm, calc


def _validate_pdf_bytes(pdf_bytes: bytes) -> None:
    if not pdf_bytes:
        raise APIError(
            "INVALID_INPUT",
            "PDF file is empty.",
            field="file",
            http_status=400,
        )
    if len(pdf_bytes) > MAX_FRONTEND_PDF_BYTES:
        raise APIError(
            "INVALID_INPUT",
            f"PDF must be at most {MAX_FRONTEND_PDF_BYTES // (1024 * 1024)} MB.",
            field="file",
            http_status=400,
        )
    if not pdf_bytes.startswith(PDF_MAGIC):
        raise APIError(
            "INVALID_INPUT",
            "Uploaded file must be a PDF.",
            field="file",
            http_status=400,
        )


def _unique_pdf_name(personal: PersonalDetails) -> str:
    stem = report_download_basename(personal)
    return f"{stem}_{uuid.uuid4().hex[:8]}.pdf"


def persist_frontend_pdf(assessment_id, personal: PersonalDetails, pdf_bytes: bytes) -> tuple[str, str]:
    """Save PDF bytes; return (storage_path_or_key, file_name)."""
    _validate_pdf_bytes(pdf_bytes)
    file_name = _unique_pdf_name(personal)

    if s3_enabled():
        storage_key = build_storage_key(str(assessment_id), file_name)
        upload_bytes(pdf_bytes, storage_key, content_type_for_format("pdf"))
        return storage_key, file_name

    folder = reports_folder()
    os.makedirs(folder, exist_ok=True)
    local_path = os.path.join(folder, f"{assessment_id}_{file_name}")
    with open(local_path, "wb") as handle:
        handle.write(pdf_bytes)
    return local_path, file_name


def upload_and_deliver_report(
    assessment_id,
    pdf_bytes: bytes,
    *,
    subject: str | None = None,
    body: str | None = None,
) -> dict:
    """
    One trigger: persist frontend PDF, create ReportLog, email when consent is set.
    No server-side PDF regeneration fallback.
    """
    _, personal, comm, calc = _require_assessment_context(assessment_id)
    file_path, file_name = persist_frontend_pdf(assessment_id, personal, pdf_bytes)

    log = ReportLog(
        assessment_id=assessment_id,
        calculation_id=calc.id,
        triggered_by="frontend_upload",
        file_name=file_name,
        file_path=file_path,
        format="pdf",
        generated_at=datetime.now(timezone.utc),
    )
    db.session.add(log)
    db.session.commit()

    result = {
        "report_id": str(log.id),
        "file_name": log.file_name,
        "format": log.format,
        "storage_key": file_path if is_storage_key(file_path) else None,
        "generated_at": log.generated_at.isoformat(),
        "delivery_mode": "saved",
        "email_sent": False,
    }

    if not comm.consent:
        result["message"] = "Report saved. Email skipped (no client consent)."
        return result

    attachment_path = resolve_local_attachment_path(file_path, file_name)
    try:
        email_result = send_report_email(
            personal,
            comm,
            attachment_path,
            file_name,
            subject=subject,
            body=body,
        )
    except APIError as exc:
        if exc.code == "EMAIL_QUOTA_EXCEEDED":
            result["message"] = "Report saved. Email skipped (daily quota exceeded)."
            result["email_error"] = exc.code
            return result
        raise
    finally:
        if attachment_path != file_path and os.path.exists(attachment_path):
            try:
                os.remove(attachment_path)
            except OSError:
                pass

    result.update(email_result or {})
    result["delivery_mode"] = "email"
    result["email_sent"] = True
    result["message"] = "Report saved and sent to your email."
    return result
