import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config, config_map
from app.middleware.auth import hash_key
from app.models.api_key import APIKey
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.communication import CommunicationDetails
from app.models.get_in_touch import GetInTouchLead
from app.models.personal import PersonalDetails
from app.models.rate_config import RateConfig
from app.models.report_log import ReportLog

USER_KEY = "admin-test-user-key"
ADMIN_KEY = "admin-test-admin-key"


class AdminTestConfig(Config):
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
    config_map["admin_test"] = AdminTestConfig

    from run import create_app

    test_app = create_app("admin_test")
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


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_headers():
    return {"X-API-Key": ADMIN_KEY}


@pytest.fixture()
def user_headers():
    return {"X-API-Key": USER_KEY}


def seed_assessment_with_report():
    record = AssessmentRecord(
        status="in_progress",
        flow1_submitted_at=datetime.now(timezone.utc),
        flow4_submitted_at=datetime.now(timezone.utc),
    )
    db.session.add(record)
    db.session.flush()

    db.session.add(
        CommunicationDetails(
            assessment_id=record.id,
            mobile="9876543210",
            email="client@example.com",
            consent=True,
        )
    )
    db.session.add(
        PersonalDetails(
            assessment_id=record.id,
            client_name="Test Client",
            client_occupation="Engineer",
            client_designation="Manager",
            client_company="Test Co",
            client_dob=datetime(1990, 1, 1).date(),
            client_age=36,
        )
    )

    calc = CalculationOutput(
        assessment_id=record.id,
        pf_monthly_rate=0.01,
        real_rate=0.05,
        real_rate_monthly=0.004,
        monthly_eff_pre=0.009,
        client_corpus=1000000,
        client_pf_corpus=500000,
        client_net_corpus=500000,
        client_monthly_sip=10000,
        client_lump_sum=0,
        spouse_corpus=0,
        spouse_pf_corpus=0,
        spouse_net_corpus=0,
        spouse_monthly_sip=0,
        spouse_lump_sum=0,
        total_insurance_required=5000000,
        total_goals_monthly_sip=15000,
    )
    db.session.add(calc)
    db.session.flush()

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(b"PK fake docx")
        file_path = tmp.name

    log = ReportLog(
        assessment_id=record.id,
        calculation_id=calc.id,
        file_name="report_test.docx",
        file_path=file_path,
        format="docx",
        generated_at=datetime.now(timezone.utc),
    )
    db.session.add(log)
    db.session.commit()
    return record, log, file_path


def seed_in_progress_assessment():
    record = AssessmentRecord(
        status="in_progress",
        flow1_submitted_at=datetime.now(timezone.utc),
        flow4_submitted_at=datetime.now(timezone.utc),
    )
    db.session.add(record)
    db.session.flush()
    db.session.add(
        CommunicationDetails(
            assessment_id=record.id,
            mobile="9000000000",
            email="freelead@example.com",
            consent=True,
        )
    )
    db.session.add(
        PersonalDetails(
            assessment_id=record.id,
            client_name="Free Lead User",
            client_occupation="Engineer",
            client_designation="Manager",
            client_company="Test Co",
            client_dob=datetime(1990, 1, 1).date(),
            client_age=36,
        )
    )
    db.session.commit()
    return record


def test_get_in_touch_creates_lead(client):
    response = client.post(
        "/api/v1/contact/get-in-touch",
        json={
            "name": "Website Lead",
            "email": "lead@example.com",
            "mobile": "9123456789",
            "message": "Interested in planning",
        },
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["email"] == "lead@example.com"


def test_admin_leads_users_and_assessments(client, admin_headers, app):
    with app.app_context():
        seed_assessment_with_report()
        seed_in_progress_assessment()
        db.session.add(
            GetInTouchLead(
                name="Form Lead",
                email="form@example.com",
                mobile="9111111111",
            )
        )
        db.session.commit()

    leads = client.get("/api/v1/admin/leads", headers=admin_headers).get_json()
    assert leads["data"]["total"] == 3
    assert leads["data"]["per_page"] == 100

    users = client.get("/api/v1/admin/users", headers=admin_headers).get_json()
    assert users["data"]["total"] == 3

    assessments = client.get(
        "/api/v1/admin/assessments", headers=admin_headers
    ).get_json()
    assert assessments["data"]["total"] == 1
    assert assessments["data"]["items"][0]["download_path"]


def test_admin_search_and_pagination(client, admin_headers, app):
    with app.app_context():
        seed_assessment_with_report()

    response = client.get(
        "/api/v1/admin/assessments?search=test&per_page=1&page=1",
        headers=admin_headers,
    )
    body = response.get_json()["data"]
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["per_page"] == 1


def test_admin_assessments_requires_admin(client, user_headers, app):
    with app.app_context():
        seed_assessment_with_report()

    response = client.get("/api/v1/admin/assessments", headers=user_headers)
    assert response.status_code == 403


def test_admin_reports_list_and_download(client, admin_headers, app):
    with app.app_context():
        _, log, _file_path = seed_assessment_with_report()
        report_id = str(log.id)

    list_response = client.get("/api/v1/admin/reports", headers=admin_headers)
    assert list_response.status_code == 200
    items = list_response.get_json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Test Client"
    assert items[0]["file_available"] is True
    assert list_response.get_json()["data"]["per_page"] == 100

    download_response = client.get(
        f"/api/v1/admin/reports/{report_id}/download",
        headers=admin_headers,
    )
    assert download_response.status_code == 200
    assert download_response.data


def test_admin_report_download_regenerates_missing_file(
    client, admin_headers, app, monkeypatch
):
    with app.app_context():
        _, log, file_path = seed_assessment_with_report()
        report_id = str(log.id)
        os.remove(file_path)

    def fake_generate_report(assessment_id, calc, personal, comm, goals):
        handle = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        handle.write(b"PK regenerated docx")
        handle.close()
        regen_path = handle.name
        return {
            "file_name": "report_regen.docx",
            "docx_path": regen_path,
            "pdf_path": None,
            "attach_path": regen_path,
            "attach_name": "report_regen.docx",
        }

    monkeypatch.setattr(
        "app.services.report_delivery.generate_report",
        fake_generate_report,
    )

    download_response = client.get(
        f"/api/v1/admin/reports/{report_id}/download",
        headers=admin_headers,
    )
    assert download_response.status_code == 200
    assert download_response.data == b"PK regenerated docx"
