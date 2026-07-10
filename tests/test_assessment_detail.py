"""Tests for assessment detail calculation + reports enrichment."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool

from app import cache, db
from app.config import Config, config_map
from app.middleware.auth import hash_key
from app.models.api_key import APIKey
from app.models.calculation import CalculationOutput
from app.models.rate_config import RateConfig
from app.models.report_log import ReportLog

USER_KEY = "assessment-detail-user-key"


class AssessmentDetailTestConfig(Config):
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
    config_map["assessment_detail_test"] = AssessmentDetailTestConfig
    from run import create_app

    test_app = create_app("assessment_detail_test")
    with test_app.app_context():
        db.create_all()
        cache.clear()
        db.session.add_all(
            [
                APIKey(
                    client_name="Detail User",
                    key_hash=hash_key(USER_KEY),
                    role="user",
                    is_active=True,
                ),
                RateConfig(
                    inflation_post=0.06,
                    roi_post=0.08,
                    inflation_pre=0.06,
                    roi_pre=0.12,
                    pf_growth=0.05,
                    updated_by="test",
                ),
            ]
        )
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()
        cache.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def headers():
    return {"X-API-Key": USER_KEY, "Content-Type": "application/json"}


def _complete_flows(client, headers):
    res = client.post("/api/v1/assessment/", headers=headers)
    assessment_id = res.get_json()["data"]["assessment_id"]
    assert (
        client.post(
            f"/api/v1/assessment/{assessment_id}/flow1",
            headers=headers,
            json={
                "mobile": "9876543210",
                "email": "client@example.com",
                "residential_address": "Mumbai",
                "consent": True,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/assessment/{assessment_id}/flow2",
            headers=headers,
            json={
                "client_name": "Test Client",
                "client_occupation": "Engineer",
                "client_designation": "Manager",
                "client_company": "Tech",
                "client_dob": "01/01/1990",
                "client_retirement_age": 60,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/assessment/{assessment_id}/flow3",
            headers=headers,
            json={"number_of_children": 0, "children": []},
        ).status_code
        == 200
    )
    flow4 = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        headers=headers,
        json={
            "goals": [
                {
                    "category": "lifestyle",
                    "goal_type": "Home Purchase",
                    "target_year": 2035,
                    "today_cost": 5000000,
                    "inflation_rate": 0.06,
                }
            ]
        },
    )
    assert flow4.status_code == 200, flow4.get_json()
    return assessment_id


def test_assessment_detail_without_calculate_has_null_calculation(client, headers):
    assessment_id = _complete_flows(client, headers)
    res = client.get(f"/api/v1/assessment/{assessment_id}", headers=headers)
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["calculation"] is None
    assert data["reports"] == []
    assert data["flow1"] is not None
    assert data["flow4"] is not None


def test_assessment_detail_includes_calculation_and_reports(client, headers, app):
    assessment_id = _complete_flows(client, headers)
    calc_res = client.post(
        f"/api/v1/calculate/{assessment_id}",
        headers=headers,
        json={
            "client_epf_annual": 33600,
            "client_epf_accum": 100000,
            "client_annual_ret_reqd": 1200000,
            "household_monthly": 30000,
        },
    )
    assert calc_res.status_code == 200, calc_res.get_json()

    with app.app_context():
        calc = CalculationOutput.query.filter_by(
            assessment_id=UUID(assessment_id)
        ).first()
        assert calc is not None
        db.session.add(
            ReportLog(
                assessment_id=UUID(assessment_id),
                calculation_id=calc.id,
                triggered_by="user",
                file_name="report_test.pdf",
                file_path="reports/report_test.pdf",
                format="pdf",
                generated_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()

    res = client.get(f"/api/v1/assessment/{assessment_id}", headers=headers)
    assert res.status_code == 200
    data = res.get_json()["data"]

    calc_payload = data["calculation"]
    assert calc_payload is not None
    assert "summary" in calc_payload
    assert "average_insurance_required" in calc_payload["summary"]
    assert "total_retirement_corpus_required" in calc_payload["summary"]
    assert "monthly_investment_required" in calc_payload["summary"]
    assert calc_payload["client"]["monthly_sip_required"]["raw"] >= 0
    assert calc_payload["client"]["total_required_corpus"]["inr"]
    assert calc_payload["spouse"] is None
    assert len(calc_payload["goals"]["items"]) == 1

    assert len(data["reports"]) == 1
    assert data["reports"][0]["file_name"] == "report_test.pdf"
    assert data["reports"][0]["report_id"]
