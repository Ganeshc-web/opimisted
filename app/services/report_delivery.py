"""Resolve report files and regenerate when missing (ephemeral /tmp or Lightsail disk)."""
import os
from datetime import datetime, timezone

from app import db
from app.core.exceptions import APIError
from app.models.calculation import CalculationOutput
from app.models.communication import CommunicationDetails
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.report_log import ReportLog
from app.services.report_service import PROJECT_ROOT, generate_report
from app.services.s3_storage import (
    is_storage_key,
    object_exists,
    object_size_bytes,
    s3_enabled,
)


def resolve_report_path(file_path: str) -> str:
    if not file_path or is_storage_key(file_path):
        return file_path
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(str(PROJECT_ROOT), file_path)


def report_mimetype(fmt: str) -> str:
    normalized = (fmt or "").lower()
    if normalized == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if normalized == "html":
        return "text/html"
    return "application/pdf"


def report_is_available(file_path: str) -> bool:
    if is_storage_key(file_path):
        return object_exists(file_path)
    local_path = resolve_report_path(file_path)
    return bool(local_path and os.path.exists(local_path))


def report_size_bytes(file_path: str):
    if is_storage_key(file_path):
        return object_size_bytes(file_path)
    local_path = resolve_report_path(file_path)
    try:
        return os.path.getsize(local_path)
    except OSError:
        return None


def _load_report_context(assessment_id):
    calc = (
        CalculationOutput.query.filter_by(assessment_id=assessment_id)
        .order_by(CalculationOutput.calculated_at.desc())
        .first()
    )
    if not calc:
        raise APIError(
            "NOT_FOUND",
            "Calculation not found. Run /calculate before downloading report.",
            http_status=404,
        )

    personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
    comm = CommunicationDetails.query.filter_by(assessment_id=assessment_id).first()
    goals = Goal.query.filter_by(assessment_id=assessment_id).all()

    if not personal or not comm:
        raise APIError(
            "NOT_FOUND",
            "Complete flows 1 and 2 before downloading report.",
            http_status=404,
        )

    return calc, personal, comm, goals


def regenerate_report_for_log(log: ReportLog) -> dict:
    calc, personal, comm, goals = _load_report_context(log.assessment_id)
    result = generate_report(str(log.assessment_id), calc, personal, comm, goals)

    send_path = result.get("attach_path") or result["docx_path"]
    download_name = result.get("attach_name") or result["file_name"]
    fmt = "pdf" if result.get("pdf_path") else "docx"
    if is_storage_key(send_path):
        fmt = "pdf" if download_name.lower().endswith(".pdf") else "docx"

    log.file_path = send_path
    log.file_name = download_name
    log.format = fmt
    log.calculation_id = calc.id
    log.generated_at = datetime.now(timezone.utc)
    db.session.commit()

    delivery = {
        "file_path": send_path if not is_storage_key(send_path) else None,
        "storage_key": send_path if is_storage_key(send_path) else result.get("storage_key"),
        "file_name": download_name,
        "format": fmt,
    }
    return delivery


def ensure_report_file(log: ReportLog, *, regenerate: bool = True) -> dict:
    """
    Return delivery metadata for a ReportLog row.
    Regenerates the report when the stored artifact is missing.
    """
    file_path = log.file_path or ""

    if is_storage_key(file_path) and object_exists(file_path):
        return {
            "storage_key": file_path,
            "file_name": log.file_name,
            "format": log.format or "pdf",
        }

    local_path = resolve_report_path(file_path)
    if local_path and os.path.exists(local_path):
        return {
            "file_path": local_path,
            "file_name": log.file_name,
            "format": log.format or "pdf",
        }

    if not regenerate:
        if s3_enabled() and is_storage_key(file_path):
            raise APIError("NOT_FOUND", "Report file missing in S3.", http_status=404)
        raise APIError("NOT_FOUND", "Report file missing on server.", http_status=404)

    return regenerate_report_for_log(log)
