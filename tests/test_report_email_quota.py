from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config, config_map
from app.core.exceptions import APIError
from app.models.report_email_daily_count import ReportEmailDailyCount
from app.services.email_service import maybe_send_report_email, send_report_email
from app.services.report_email_quota import (
    can_send_report_email,
    daily_report_email_limit,
    quota_day,
    quota_remaining_today,
    release_report_email_slot,
    report_emails_sent_today,
    reserve_report_email_slot,
)


class QuotaTestConfig(Config):
    TESTING = True
    PROPAGATE_EXCEPTIONS = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    CACHE_TYPE = "SimpleCache"
    SMTP_USER = "info@wealthswisdom.com"
    SMTP_PASSWORD = "test-password"
    EMAIL_FROM = "info@wealthswisdom.com"


@pytest.fixture()
def app():
    config_map["quota_test"] = QuotaTestConfig

    from run import create_app

    test_app = create_app("quota_test")
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def comm_with_consent():
    comm = MagicMock()
    comm.consent = True
    comm.email = "client@example.com"
    return comm


@pytest.fixture()
def personal():
    p = MagicMock()
    p.client_name = "Test Client"
    return p


def test_daily_limit_defaults_to_499(app):
    with app.app_context():
        assert daily_report_email_limit() == 499


def test_reserve_and_count(app):
    with app.app_context():
        app.config["REPORT_EMAIL_DAILY_LIMIT"] = 2
        assert can_send_report_email() is True
        assert reserve_report_email_slot() is True
        assert report_emails_sent_today() == 1
        assert reserve_report_email_slot() is True
        assert report_emails_sent_today() == 2
        assert reserve_report_email_slot() is False
        assert quota_remaining_today() == 0


def test_release_slot(app):
    with app.app_context():
        app.config["REPORT_EMAIL_DAILY_LIMIT"] = 2
        assert reserve_report_email_slot() is True
        release_report_email_slot()
        assert report_emails_sent_today() == 0
        assert reserve_report_email_slot() is True


@patch("app.services.email_service.send_email_with_attachment")
def test_send_report_email_respects_quota(mock_send, app, personal, comm_with_consent):
    with app.app_context():
        app.config["REPORT_EMAIL_DAILY_LIMIT"] = 1
        assert reserve_report_email_slot() is True

        with pytest.raises(APIError) as exc:
            send_report_email(
                personal, comm_with_consent, "/tmp/report.pdf", "report.pdf"
            )
        assert exc.value.code == "EMAIL_QUOTA_EXCEEDED"
        mock_send.assert_not_called()


@patch("app.services.email_service.send_email_with_attachment")
def test_send_report_email_success_counts_slot(mock_send, app, personal, comm_with_consent):
    with app.app_context():
        app.config["REPORT_EMAIL_DAILY_LIMIT"] = 2
        result = send_report_email(
            personal, comm_with_consent, "/tmp/report.pdf", "report.pdf"
        )
        mock_send.assert_called_once()
        assert result["sent_to"] == "client@example.com"
        assert report_emails_sent_today() == 1


@patch("app.services.email_service.send_email_with_attachment")
def test_send_report_email_releases_slot_on_smtp_failure(
    mock_send, app, personal, comm_with_consent
):
    mock_send.side_effect = APIError("INTERNAL_ERROR", "SMTP failed", http_status=500)
    with app.app_context():
        app.config["REPORT_EMAIL_DAILY_LIMIT"] = 2
        with pytest.raises(APIError):
            send_report_email(
                personal, comm_with_consent, "/tmp/report.pdf", "report.pdf"
            )
        assert report_emails_sent_today() == 0


@patch("app.services.email_service.send_email_with_attachment")
def test_maybe_send_skips_when_quota_exceeded(
    mock_send, app, personal, comm_with_consent
):
    with app.app_context():
        app.config["REPORT_EMAIL_DAILY_LIMIT"] = 1
        db.session.add(
            ReportEmailDailyCount(day=quota_day(), count=1)
        )
        db.session.commit()

        result = maybe_send_report_email(
            personal, comm_with_consent, "/tmp/r.pdf", "r.pdf"
        )
        assert result is None
        mock_send.assert_not_called()
