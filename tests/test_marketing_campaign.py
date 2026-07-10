import pytest
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config, config_map
from app.middleware.auth import hash_key
from app.models.api_key import APIKey
from app.models.assessment import AssessmentRecord
from app.models.communication import CommunicationDetails

ADMIN_KEY = "marketing-admin-key"
USER_KEY = "marketing-user-key"


class MarketingTestConfig(Config):
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
    config_map["marketing_test"] = MarketingTestConfig

    from run import create_app

    test_app = create_app("marketing_test")
    with test_app.app_context():
        db.create_all()
        db.session.add_all(
            [
                APIKey(
                    client_name="Admin",
                    key_hash=hash_key(ADMIN_KEY),
                    role="admin",
                    is_active=True,
                ),
                APIKey(
                    client_name="User",
                    key_hash=hash_key(USER_KEY),
                    role="user",
                    is_active=True,
                ),
            ]
        )
        assessment = AssessmentRecord(status="in_progress")
        db.session.add(assessment)
        db.session.flush()
        db.session.add(
            CommunicationDetails(
                assessment_id=assessment.id,
                mobile="9876543210",
                email="client@example.com",
                consent=True,
            )
        )
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_headers():
    return {"X-API-Key": ADMIN_KEY}



def test_marketing_recipients(client, admin_headers):
    response = client.get(
        "/api/v1/admin/marketing/recipients",
        headers=admin_headers,
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["data"]["count"] == 1
    assert body["data"]["recipients"] == ["client@example.com"]


def test_marketing_campaign_requires_admin(client):
    response = client.post(
        "/api/v1/admin/marketing/campaign",
        data={"subject": "Hello", "body": "Test"},
        headers={"X-API-Key": USER_KEY},
    )
    assert response.status_code == 403


def test_marketing_campaign_send(client, admin_headers, monkeypatch):
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs["to_email"])

    monkeypatch.setattr(
        "app.services.marketing_campaign_service.send_campaign_email",
        lambda **kwargs: sent.append(kwargs["to_email"]),
    )

    response = client.post(
        "/api/v1/admin/marketing/campaign",
        data={
            "subject": "Campaign Subject",
            "body": "<p>Hello clients</p>",
            "body_format": "html",
        },
        headers=admin_headers,
        content_type="multipart/form-data",
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["data"]["sent_count"] == 1
    assert sent == ["client@example.com"]


def test_marketing_campaign_explicit_recipients(client, admin_headers, monkeypatch):
    sent = []

    monkeypatch.setattr(
        "app.services.marketing_campaign_service.send_campaign_email",
        lambda **kwargs: sent.append(kwargs["to_email"]),
    )

    response = client.post(
        "/api/v1/admin/marketing/campaign",
        data={
            "subject": "Hello",
            "body": "Body copy",
            "recipients": '["alpha@example.com","beta@example.com"]',
        },
        headers=admin_headers,
        content_type="multipart/form-data",
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["data"]["sent_count"] == 2
    assert set(sent) == {"alpha@example.com", "beta@example.com"}
