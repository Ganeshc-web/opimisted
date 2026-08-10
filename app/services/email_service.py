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
    *,
    body_format: str = "plain",
    plain_body: Optional[str] = None,
) -> None:
    filename = attachment_name or os.path.basename(attachment_path)
    send_campaign_email(
        to_email=to_email,
        subject=subject,
        body=body,
        body_format=body_format,
        plain_body=plain_body,
        attachments=[(attachment_path, filename)],
    )


def send_campaign_email(
    to_email: str,
    subject: str,
    body: str,
    *,
    body_format: str = "plain",
    plain_body: Optional[str] = None,
    attachments: Optional[list[tuple[str, str]]] = None,
) -> None:
    """Send a campaign/report message with optional file attachments."""
    host, port, user, password, from_addr = _smtp_config()
    is_html = (body_format or "").lower() == "html"

    msg = MIMEMultipart("mixed")
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = subject

    if is_html and plain_body:
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(plain_body, "plain", "utf-8"))
        alternative.attach(MIMEText(body, "html", "utf-8"))
        msg.attach(alternative)
    else:
        subtype = "html" if is_html else "plain"
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
        ) from exc
    except (TimeoutError, OSError, ConnectionError) as exc:
        raise APIError(
            "INTERNAL_ERROR",
            f"SMTP connection failed: {exc}",
            http_status=500,
        ) from exc


def default_report_email_content(
    client_name: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> tuple[str, str]:
    """Return subject and plain-text body for report delivery.

    Prefers the admin-editable DB template; falls back to built-in defaults.
    """
    from app.services.email_template_service import render_report_email_content

    return render_report_email_content(client_name, attachment_name)


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
    """Send report to client email with plain-text template + PDF. Requires consent."""
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
        getattr(personal, "client_name", None),
        attachment_name,
    )
    subject = (subject or "").strip() or default_subject
    email_body = (body or "").strip() or default_body

    last_error: APIError | None = None
    for attempt in range(2):
        try:
            send_email_with_attachment(
                to_email=comm.email,
                subject=subject,
                body=email_body,
                attachment_path=attachment_path,
                attachment_name=attachment_name,
                body_format="plain",
            )
            last_error = None
            break
        except APIError as exc:
            last_error = exc
            # Retry once on transient SMTP/connection failures.
            if attempt == 0 and exc.code == "INTERNAL_ERROR":
                continue
            if check_quota:
                release_report_email_slot()
            raise
    if last_error is not None:
        if check_quota:
            release_report_email_slot()
        raise last_error

    return {
        "sent_to": comm.email,
        "subject": subject,
        "attachment": attachment_name,
        "body_format": "plain",
    }


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
