import pytest
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config, config_map
from app.middleware.auth import hash_key
from app.models.api_key import APIKey
from app.models.testimonial import Testimonial

USER_KEY = "testimonials-user-key"
ADMIN_KEY = "testimonials-admin-key"


class TestimonialsTestConfig(Config):
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
    config_map["testimonials_test"] = TestimonialsTestConfig

    from run import create_app

    test_app = create_app("testimonials_test")
    with test_app.app_context():
        db.create_all()
        db.session.add_all(
            [
                APIKey(
                    client_name="User",
                    key_hash=hash_key(USER_KEY),
                    role="user",
                    is_active=True,
                ),
                APIKey(
                    client_name="Admin",
                    key_hash=hash_key(ADMIN_KEY),
                    role="admin",
                    is_active=True,
                ),
            ]
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


def create_testimonial(client, headers, **overrides):
    payload = {
        "client_name": "Aaditya Patel",
        "review_message": "Great planning experience.",
        "is_visible": False,
        "sort_order": 1,
        **overrides,
    }
    return client.post("/api/v1/admin/testimonials", json=payload, headers=headers)


def test_public_testimonials_empty(client):
    response = client.get("/api/v1/testimonials/")
    body = response.get_json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"] == []


def test_admin_testimonial_crud(client, admin_headers):
    create = create_testimonial(
        client,
        admin_headers,
        is_visible=True,
        avatar_url="https://cdn.example.com/a.jpg",
    )
    assert create.status_code == 201
    created = create.get_json()["data"]
    testimonial_id = created["id"]
    assert created["client_name"] == "Aaditya Patel"
    assert created["is_visible"] is True

    public = client.get("/api/v1/testimonials/")
    assert len(public.get_json()["data"]) == 1

    update = client.put(
        f"/api/v1/admin/testimonials/{testimonial_id}",
        json={"review_message": "Updated review text."},
        headers=admin_headers,
    )
    assert update.status_code == 200
    assert update.get_json()["data"]["review_message"] == "Updated review text."

    listing = client.get("/api/v1/admin/testimonials", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.get_json()["data"]) == 1

    detail = client.get(
        f"/api/v1/admin/testimonials/{testimonial_id}",
        headers=admin_headers,
    )
    assert detail.status_code == 200

    deleted = client.delete(
        f"/api/v1/admin/testimonials/{testimonial_id}",
        headers=admin_headers,
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["data"]["deleted"] is True


def test_max_three_visible_testimonials(client, admin_headers):
    for index in range(3):
        response = create_testimonial(
            client,
            admin_headers,
            client_name=f"Client {index}",
            review_message=f"Review {index}",
            is_visible=True,
            sort_order=index,
        )
        assert response.status_code == 201

    blocked = create_testimonial(
        client,
        admin_headers,
        client_name="Client 4",
        review_message="Should fail",
        is_visible=True,
        sort_order=4,
    )
    body = blocked.get_json()
    assert blocked.status_code == 400
    assert body["code"] == "INVALID_INPUT"
    assert "is_visible" in body["message"] or body.get("field") == "is_visible"


def test_cannot_hide_below_three_visible_when_enough_records(client, admin_headers):
    ids = []
    for index in range(4):
        response = create_testimonial(
            client,
            admin_headers,
            client_name=f"Visible {index}",
            review_message=f"Review {index}",
            is_visible=index < 3,
            sort_order=index,
        )
        assert response.status_code == 201
        if index < 3:
            ids.append(response.get_json()["data"]["id"])

    hide = client.put(
        f"/api/v1/admin/testimonials/{ids[0]}",
        json={"is_visible": False},
        headers=admin_headers,
    )
    body = hide.get_json()
    assert hide.status_code == 400
    assert body["code"] == "INVALID_INPUT"


def test_admin_testimonials_require_admin(client):
    response = client.get(
        "/api/v1/admin/testimonials",
        headers={"X-API-Key": USER_KEY},
    )
    body = response.get_json()
    assert response.status_code == 403
    assert body["code"] == "FORBIDDEN"
