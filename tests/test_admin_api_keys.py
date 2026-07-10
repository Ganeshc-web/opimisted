import pytest
from sqlalchemy.pool import StaticPool

from app import cache, db
from app.config import Config, config_map
from app.middleware.auth import hash_key
from app.models.api_key import APIKey

ADMIN_KEY = "api-keys-admin-key"
USER_KEY = "api-keys-user-key"
REVOKED_KEY = "api-keys-revoked-key"


class ApiKeysTestConfig(Config):
    TESTING = True
    PROPAGATE_EXCEPTIONS = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    CACHE_TYPE = "SimpleCache"


@pytest.fixture()
def app():
    config_map["api_keys_test"] = ApiKeysTestConfig

    from run import create_app

    test_app = create_app("api_keys_test")
    with test_app.app_context():
        db.create_all()
        db.session.add_all(
            [
                APIKey(
                    client_name="Admin",
                    key_hash=hash_key(ADMIN_KEY),
                    key_prefix=ADMIN_KEY[:12],
                    key_suffix=ADMIN_KEY[-8:],
                    role="admin",
                    is_active=True,
                    request_count=10,
                ),
                APIKey(
                    client_name="Website",
                    key_hash=hash_key(USER_KEY),
                    key_prefix=USER_KEY[:12],
                    key_suffix=USER_KEY[-8:],
                    role="user",
                    is_active=True,
                    request_count=120,
                ),
                APIKey(
                    client_name="Old Client",
                    key_hash=hash_key(REVOKED_KEY),
                    key_prefix=REVOKED_KEY[:12],
                    key_suffix=REVOKED_KEY[-8:],
                    role="user",
                    is_active=False,
                    request_count=304,
                ),
            ]
        )
        db.session.commit()
        cache.clear()
        yield test_app
        db.session.remove()
        db.drop_all()
        cache.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_headers():
    return {"X-API-Key": ADMIN_KEY}


def test_list_api_keys(client, admin_headers):
    response = client.get("/api/v1/admin/api-keys", headers=admin_headers)
    body = response.get_json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["count"] == 3
    first = body["data"]["items"][0]
    assert "api_key_token" in first
    assert first["role_label"] in {"Admin", "Standard User"}
    assert first["rate_limit"] in {"Unlimited", "1,000/min"}


def test_list_api_keys_search(client, admin_headers):
    response = client.get(
        "/api/v1/admin/api-keys?search=website",
        headers=admin_headers,
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["data"]["count"] == 1
    assert body["data"]["items"][0]["client_name"] == "Website"


def test_create_api_key(client, admin_headers):
    response = client.post(
        "/api/v1/admin/api-keys",
        json={"client_name": "Partner App", "role": "user"},
        headers=admin_headers,
    )
    body = response.get_json()
    assert response.status_code == 201
    assert body["data"]["api_key_plaintext"]
    assert body["data"]["status"] == "Active"
    assert body["data"]["role"] == "user"


def test_revoke_and_activate_api_key(client, admin_headers, app):
    with app.app_context():
        user_row = APIKey.query.filter_by(client_name="Website").first()

    revoke = client.put(
        f"/api/v1/admin/api-keys/{user_row.id}/revoke",
        headers=admin_headers,
    )
    assert revoke.status_code == 200
    assert revoke.get_json()["data"]["status"] == "Revoked"

    blocked = client.get("/api/v1/rates/", headers={"X-API-Key": USER_KEY})
    assert blocked.status_code == 401

    activate = client.put(
        f"/api/v1/admin/api-keys/{user_row.id}/activate",
        headers=admin_headers,
    )
    assert activate.status_code == 200
    assert activate.get_json()["data"]["status"] == "Active"

    allowed = client.get("/api/v1/rates/", headers={"X-API-Key": USER_KEY})
    assert allowed.status_code == 200


def test_cannot_revoke_current_admin_key(client, admin_headers, app):
    with app.app_context():
        admin_row = APIKey.query.filter_by(client_name="Admin").first()

    response = client.put(
        f"/api/v1/admin/api-keys/{admin_row.id}/revoke",
        headers=admin_headers,
    )
    assert response.status_code == 400


def test_user_cannot_access_api_keys(client, app):
    response = client.get(
        "/api/v1/admin/api-keys",
        headers={"X-API-Key": USER_KEY},
    )
    assert response.status_code == 403
