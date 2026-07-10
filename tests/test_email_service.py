import os
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import APIError
from app.services.email_service import (
    maybe_send_report_email,
    send_report_email,
    send_test_email,
)


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


@patch("app.services.email_service.send_email_with_attachment")
def test_send_report_email_requires_consent(mock_send, personal):
    comm = MagicMock(consent=False, email="client@example.com")
    with pytest.raises(APIError) as exc:
        send_report_email(personal, comm, "/tmp/report.pdf", "report.pdf")
    assert exc.value.code == "FORBIDDEN"
    mock_send.assert_not_called()


@patch("app.services.email_service.reserve_report_email_slot", return_value=True)
@patch("app.services.email_service.send_email_with_attachment")
def test_send_report_email_success(mock_send, _mock_quota, personal, comm_with_consent):
    result = send_report_email(
        personal, comm_with_consent, "/tmp/report.pdf", "report.pdf"
    )
    mock_send.assert_called_once()
    assert result["sent_to"] == "client@example.com"
    assert result["attachment"] == "report.pdf"


@patch("app.services.email_service.send_email_with_attachment")
def test_maybe_send_skips_without_consent(mock_send, personal):
    comm = MagicMock(consent=False)
    assert maybe_send_report_email(personal, comm, "/tmp/r.pdf", "r.pdf") is None
    mock_send.assert_not_called()


@patch("app.services.email_service.send_report_email")
def test_maybe_send_returns_none_on_failure(mock_send, personal, comm_with_consent):
    mock_send.side_effect = APIError("INTERNAL_ERROR", "SMTP failed", http_status=500)
    assert (
        maybe_send_report_email(personal, comm_with_consent, "/tmp/r.pdf", "r.pdf")
        is None
    )


@patch("app.services.email_service.send_email_with_attachment")
def test_send_test_email(mock_send):
    os.environ["SMTP_USER"] = "info@wealthswisdom.com"
    os.environ["SMTP_PASSWORD"] = "test-password"
    recipient = send_test_email("test@example.com")
    assert recipient == "test@example.com"
    mock_send.assert_called_once()
