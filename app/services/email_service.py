import os
import smtplib
import tempfile
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from flask import current_app, has_app_context

from app.core.exceptions import APIError
from app.services.report_email_quota import (
    release_report_email_slot,
    reserve_report_email_slot,
)


def _config_value(key: str, default=None):
    if has_app_context():
        return current_app.config.get(key, default)
    return os.environ.get(key, default)


def _smtp_config():
    host = _config_value("SMTP_HOST", "smtp.gmail.com")
    port_raw = _config_value("SMTP_PORT", "587")
    user = _config_value("SMTP_USER")
    password = _config_value("SMTP_PASSWORD")

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise APIError(
            "CONFIG_ERROR",
            "SMTP_PORT must be an integer.",
            http_status=500,
        )

    if not user or not password:
        raise APIError(
            "CONFIG_ERROR",
            "SMTP_USER and SMTP_PASSWORD must be set.",
            http_status=500,
        )

    from_addr = _config_value("EMAIL_FROM") or user
    return host, port, user, password, from_addr


def send_email_with_attachment(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str,
    attachment_name: Optional[str] = None,
) -> None:
    filename = attachment_name or os.path.basename(attachment_path)
    send_campaign_email(
        to_email=to_email,
        subject=subject,
        body=body,
        attachments=[(attachment_path, filename)],
    )


def send_campaign_email(
    to_email: str,
    subject: str,
    body: str,
    *,
    body_format: str = "plain",
    attachments: Optional[list[tuple[str, str]]] = None,
) -> None:
    """Send a campaign message with optional file attachments."""
    host, port, user, password, from_addr = _smtp_config()
    subtype = "html" if (body_format or "").lower() == "html" else "plain"

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, subtype, "utf-8"))

    for attachment_path, attachment_name in attachments or []:
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_name}"',
        )
        msg.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to_email], msg.as_string())
    except smtplib.SMTPException as exc:
        raise APIError(
            "INTERNAL_ERROR",
            f"SMTP send failed: {exc}",
            http_status=500,
        )


def default_report_email_content(client_name: Optional[str] = None) -> tuple[str, str]:
    name = client_name or "Client"
    subject = "Your Financial Planning Report"
    body = f"Dear {name},\n\nPlease find your report attached.\n"
    return subject, body


def send_report_email(
    personal,
    comm,
    attachment_path: str,
    attachment_name: str,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    *,
    check_quota: bool = True,
) -> dict:
    """Send report to client email. Requires consent."""
    if not comm.consent:
        raise APIError(
            "FORBIDDEN",
            "Client consent is required to send the report via email.",
            http_status=403,
        )

    if check_quota and not reserve_report_email_slot():
        raise APIError(
            "EMAIL_QUOTA_EXCEEDED",
            "Daily report email limit reached. Please download your report instead.",
            http_status=429,
        )

    default_subject, default_body = default_report_email_content(
        getattr(personal, "client_name", None)
    )
    subject = (subject or default_subject).strip()
    body = (body or default_body).strip()

    try:
        send_email_with_attachment(
            to_email=comm.email,
            subject=subject,
            body=body,
            attachment_path=attachment_path,
            attachment_name=attachment_name,
        )
    except APIError:
        if check_quota:
            release_report_email_slot()
        raise
    return {"sent_to": comm.email, "subject": subject, "attachment": attachment_name}


def maybe_send_report_email(
    personal,
    comm,
    attachment_path: str,
    attachment_name: str,
    subject: Optional[str] = None,
    body: Optional[str] = None,
) -> Optional[dict]:
    """Send report email when consent is given; log and continue on failure."""
    if not comm or not comm.consent:
        return None
    try:
        return send_report_email(
            personal, comm, attachment_path, attachment_name, subject, body
        )
    except APIError as exc:
        if exc.code == "EMAIL_QUOTA_EXCEEDED":
            if has_app_context():
                current_app.logger.info("Report email skipped: daily quota reached.")
            return None
        if has_app_context():
            current_app.logger.warning("Report email not sent: %s", exc.message)
        return None


def send_test_email(to_email: Optional[str] = None) -> str:
    """Send a simple SMTP test message with a small attachment."""
    recipient = to_email or _config_value("TEST_EMAIL") or _config_value("SMTP_USER")
    if not recipient:
        raise APIError(
            "CONFIG_ERROR",
            "Set SMTP_USER or pass a recipient email.",
            http_status=500,
        )

    with tempfile.NamedTemporaryFile(
        suffix=".txt", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write("SMTP test attachment from Financial API.\n")
        attachment_path = f.name

    try:
        send_email_with_attachment(
            to_email=recipient,
            subject="Test Email - Financial API",
            body=(
                "If you received this email, SMTP is configured correctly.\n\n"
                "Report emails are sent on /api/v1/report/{id}/generate when consent is true."
            ),
            attachment_path=attachment_path,
            attachment_name="smtp_test.txt",
        )
    finally:
        os.unlink(attachment_path)

    return recipient
