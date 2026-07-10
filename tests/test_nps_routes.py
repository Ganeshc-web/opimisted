import pytest
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config, config_map
from app.middleware.auth import hash_key
from app.models.api_key import APIKey
from app.models.rate_config import RateConfig

USER_KEY = "nps-test-user-key"


class NPSTestConfig(Config):
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
    config_map["nps_test"] = NPSTestConfig

    from run import create_app

    test_app = create_app("nps_test")
    with test_app.app_context():
        db.create_all()
        db.session.add(
            APIKey(
                client_name="User",
                key_hash=hash_key(USER_KEY),
                role="user",
                is_active=True,
            )
        )
        db.session.add(
            RateConfig(
                inflation_post=0.06,
                roi_post=0.08,
                inflation_pre=0.06,
                roi_pre=0.12,
                pf_growth=0.05,
                updated_by="test",
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
def auth_headers():
    return {"X-API-Key": USER_KEY}


def test_nps_accumulation_endpoint(client, auth_headers):
    response = client.post(
        "/api/v1/nps/accumulation",
        headers=auth_headers,
        json={
            "current_nps_accum": 0,
            "employer_nps_pm": 5000,
            "self_nps_pm": 2000,
            "years_to_retirement": 3,
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert len(body["data"]["table"]) == 3
    assert body["data"]["final_corpus_raw"] > 0


def test_superannuation_corpus_endpoint(client, auth_headers):
    response = client.post(
        "/api/v1/superannuation/corpus",
        headers=auth_headers,
        json={
            "current_sa_accum": 700000,
            "sa_pm": 6000,
            "years_to_retirement": 14,
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["final_corpus_raw"] > 700000


def test_retirement_full_includes_nps_and_sa(client, auth_headers):
    response = client.post(
        "/api/v1/retirement/full",
        headers=auth_headers,
        json={
            "annual_ret_reqd": 600000,
            "current_age": 44,
            "retirement_age": 58,
            "epf_annual_total": 13980 * 12,
            "current_epf_accum": 1560000,
            "sa_pm": 6000,
            "current_sa_accum": 700000,
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["sa_fv_raw"] > 0
    assert body["data"]["total_existing_provision_raw"] > 0
