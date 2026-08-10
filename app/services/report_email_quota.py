"""Daily cap on automated client report emails."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.report_email_daily_count import ReportEmailDailyCount

DEFAULT_DAILY_LIMIT = 499


def _config_value(key: str, default):
    if has_app_context():
        return current_app.config.get(key, default)
    return default


def daily_report_email_limit() -> int:
    raw = _config_value("REPORT_EMAIL_DAILY_LIMIT", DEFAULT_DAILY_LIMIT)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DAILY_LIMIT


def quota_day() -> date:
    tz_name = _config_value("REPORT_EMAIL_QUOTA_TZ", "Asia/Kolkata")
    try:
        tz = ZoneInfo(str(tz_name))
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def _get_or_create_row(day: date) -> ReportEmailDailyCount:
    row = db.session.get(ReportEmailDailyCount, day)
    if row is not None:
        return row

    row = ReportEmailDailyCount(day=day, count=0)
    db.session.add(row)
    try:
        db.session.flush()
        return row
    except IntegrityError:
        db.session.rollback()
        row = db.session.get(ReportEmailDailyCount, day)
        if row is None:
            raise
        return row


def report_emails_sent_today() -> int:
    row = db.session.get(ReportEmailDailyCount, quota_day())
    return row.count if row else 0


def can_send_report_email() -> bool:
    return report_emails_sent_today() < daily_report_email_limit()


def quota_remaining_today() -> int:
    return max(0, daily_report_email_limit() - report_emails_sent_today())


def reserve_report_email_slot() -> bool:
    """Reserve one daily report-email slot. Returns False when limit is reached."""
    day = quota_day()
    limit = daily_report_email_limit()
    row = _get_or_create_row(day)
    if row.count >= limit:
        return False
    row.count += 1
    db.session.commit()
    return True


def release_report_email_slot() -> None:
    """Return a reserved slot after a failed SMTP send."""
    day = quota_day()
    row = db.session.get(ReportEmailDailyCount, day)
    if row and row.count > 0:
        row.count -= 1
        db.session.commit()
