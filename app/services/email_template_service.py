"""Admin-editable plain-text email templates for report delivery."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app import db
from app.core.exceptions import APIError
from app.models.email_template import EmailTemplate

REPORT_DELIVERY_KEY = "report_delivery"

PLACEHOLDERS = (
    "{{client_name}}",
    "{{attachment_name}}",
)

DEFAULT_REPORT_SUBJECT = "Your Wealth Wisdom Goal Analysis Report is Ready"

DEFAULT_REPORT_BODY = """Hello {{client_name}},

Greetings from Wealth Wisdom.

Thank you for trusting us with your financial goals. We are glad to share that your personalized Goal Analysis Report is ready.

Please find your report attached ({{attachment_name}}). It covers your goals, suggested investment directions, and planning insights based on the details you shared with us.

We hope this report helps you take the next step with clarity and confidence.

If you have any questions, feel free to reply to this email or write to us at info@wealthswisdom.com - we are happy to help.

Warm regards,
Team Wealth Wisdom
https://wealthswisdom.com
"""


def apply_placeholders(text: str, *, client_name: str, attachment_name: str) -> str:
    return (
        (text or "")
        .replace("{{client_name}}", client_name)
        .replace("{{attachment_name}}", attachment_name)
    )


def serialize_email_template(row: EmailTemplate) -> dict:
    body = row.body_plain or row.body_html or ""
    return {
        "id": str(row.id),
        "template_key": row.template_key,
        "name": row.name,
        "subject": row.subject,
        "body": body,
        "body_plain": body,
        "placeholders": list(PLACEHOLDERS),
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def ensure_report_email_template() -> EmailTemplate:
    """Create the report-delivery template with default copy if missing."""
    row = EmailTemplate.query.filter_by(template_key=REPORT_DELIVERY_KEY).first()
    if row:
        return row
    row = EmailTemplate(
        template_key=REPORT_DELIVERY_KEY,
        name="Report delivery",
        subject=DEFAULT_REPORT_SUBJECT,
        body_html=DEFAULT_REPORT_BODY,
        body_plain=DEFAULT_REPORT_BODY,
        updated_by="system",
    )
    db.session.add(row)
    db.session.commit()
    return row


def get_email_template(template_key: str) -> EmailTemplate:
    if template_key == REPORT_DELIVERY_KEY:
        return ensure_report_email_template()
    row = EmailTemplate.query.filter_by(template_key=template_key).first()
    if not row:
        raise APIError("NOT_FOUND", "Email template not found.", http_status=404)
    return row


def update_email_template(
    template_key: str,
    *,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    body_plain: Optional[str] = None,
    body_html: Optional[str] = None,
    name: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> EmailTemplate:
    row = get_email_template(template_key)
    if subject is not None:
        subject = subject.strip()
        if not subject:
            raise APIError(
                "INVALID_INPUT",
                "subject cannot be blank.",
                field="subject",
                http_status=400,
            )
        row.subject = subject

    # Prefer `body`, then body_plain, then body_html (legacy). Always store as plain text.
    text = body if body is not None else body_plain
    if text is None and body_html is not None:
        text = body_html
    if text is not None:
        text = text.strip()
        if not text:
            raise APIError(
                "INVALID_INPUT",
                "body cannot be blank.",
                field="body",
                http_status=400,
            )
        row.body_plain = text
        row.body_html = text

    if name is not None:
        name = name.strip()
        if name:
            row.name = name
    row.updated_by = updated_by
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return row


def reset_report_email_template(updated_by: Optional[str] = None) -> EmailTemplate:
    row = ensure_report_email_template()
    row.subject = DEFAULT_REPORT_SUBJECT
    row.body_html = DEFAULT_REPORT_BODY
    row.body_plain = DEFAULT_REPORT_BODY
    row.name = "Report delivery"
    row.updated_by = updated_by or "system"
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return row


def render_report_email_content(
    client_name: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> tuple[str, str]:
    """Load admin template (or defaults) and fill placeholders. Returns subject, plain body."""
    name = (client_name or "Client").strip() or "Client"
    file_label = (attachment_name or "Goal Analysis Report").strip() or "Goal Analysis Report"
    try:
        row = ensure_report_email_template()
        subject = apply_placeholders(
            row.subject, client_name=name, attachment_name=file_label
        )
        body = apply_placeholders(
            row.body_plain or row.body_html or DEFAULT_REPORT_BODY,
            client_name=name,
            attachment_name=file_label,
        )
        return subject, body
    except Exception:
        subject = apply_placeholders(
            DEFAULT_REPORT_SUBJECT, client_name=name, attachment_name=file_label
        )
        body = apply_placeholders(
            DEFAULT_REPORT_BODY, client_name=name, attachment_name=file_label
        )
        return subject, body
