"""Admin marketing email campaigns."""
import json
import os
import re
import tempfile
from typing import Any

from sqlalchemy import func

from app import db
from app.core.exceptions import APIError
from app.models.communication import CommunicationDetails
from app.services.email_service import send_campaign_email
from app.services.excel_service import MAX_UPLOAD_BYTES

MAX_CAMPAIGN_RECIPIENTS = 500
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_recipients(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise APIError(
                    "INVALID_INPUT",
                    "recipients must be a JSON array of email addresses.",
                    field="recipients",
                    http_status=400,
                ) from exc
            if not isinstance(parsed, list):
                raise APIError(
                    "INVALID_INPUT",
                    "recipients must be a JSON array of email addresses.",
                    field="recipients",
                    http_status=400,
                )
            items = parsed
        else:
            items = [part.strip() for part in text.split(",") if part.strip()]
    else:
        raise APIError(
            "INVALID_INPUT",
            "recipients must be a list or comma-separated string.",
            field="recipients",
            http_status=400,
        )

    normalized = []
    seen = set()
    for item in items:
        email = str(item).strip().lower()
        if not email:
            continue
        if not EMAIL_PATTERN.match(email):
            raise APIError(
                "INVALID_INPUT",
                f"Invalid email address: {item}",
                field="recipients",
                http_status=400,
            )
        if email not in seen:
            seen.add(email)
            normalized.append(email)
    return normalized


def consented_recipient_emails() -> list[str]:
    rows = (
        db.session.query(func.lower(CommunicationDetails.email))
        .filter(
            CommunicationDetails.consent.is_(True),
            CommunicationDetails.email.isnot(None),
            CommunicationDetails.email != "",
        )
        .distinct()
        .all()
    )
    return [row[0] for row in rows if row[0]]


def resolve_campaign_recipients(explicit: list[str]) -> list[str]:
    recipients = explicit or consented_recipient_emails()
    if not recipients:
        raise APIError(
            "INVALID_INPUT",
            "No recipients found. Provide recipients or ensure users have consent=true.",
            field="recipients",
            http_status=400,
        )
    if len(recipients) > MAX_CAMPAIGN_RECIPIENTS:
        raise APIError(
            "INVALID_INPUT",
            f"Maximum {MAX_CAMPAIGN_RECIPIENTS} recipients per campaign.",
            field="recipients",
            http_status=400,
        )
    return recipients


def read_campaign_attachments(file_storages) -> list[tuple[str, str]]:
    if not file_storages:
        return []

    total_size = 0
    saved: list[tuple[str, str]] = []
    temp_paths: list[str] = []

    try:
        for upload in file_storages:
            if not upload or not upload.filename:
                continue
            payload = upload.read()
            if not payload:
                continue
            total_size += len(payload)
            if total_size > MAX_UPLOAD_BYTES:
                raise APIError(
                    "INVALID_INPUT",
                    "Total attachment size exceeds 12MB limit.",
                    field="attachments",
                    http_status=400,
                )
            suffix = os.path.splitext(upload.filename)[1] or ".bin"
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            handle.write(payload)
            handle.close()
            temp_paths.append(handle.name)
            saved.append((handle.name, os.path.basename(upload.filename)))
        return saved
    except Exception:
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def cleanup_attachment_paths(paths: list[str]) -> None:
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


def send_marketing_campaign(
    *,
    subject: str,
    body: str,
    recipients: list[str],
    body_format: str = "html",
    attachments: list[tuple[str, str]] | None = None,
) -> dict:
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        raise APIError(
            "INVALID_INPUT",
            "subject is required.",
            field="subject",
            http_status=400,
        )
    if not body:
        raise APIError(
            "INVALID_INPUT",
            "body is required.",
            field="body",
            http_status=400,
        )

    resolved = resolve_campaign_recipients(recipients)
    attachment_paths = [path for path, _ in attachments or []]

    sent: list[str] = []
    failed: list[dict[str, str]] = []

    try:
        for email in resolved:
            try:
                send_campaign_email(
                    to_email=email,
                    subject=subject,
                    body=body,
                    body_format=body_format,
                    attachments=attachments,
                )
                sent.append(email)
            except APIError as exc:
                failed.append({"email": email, "error": exc.message})
    finally:
        cleanup_attachment_paths(attachment_paths)

    if not sent and failed:
        raise APIError(
            "INTERNAL_ERROR",
            failed[0]["error"],
            http_status=500,
        )

    return {
        "subject": subject,
        "sent_count": len(sent),
        "failed_count": len(failed),
        "sent_to": sent,
        "failed": failed,
        "attachment_count": len(attachments or []),
    }
