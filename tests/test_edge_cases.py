import time
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool

from app import cache, db
from app.config import Config, config_map
from app.core.formulas import current_year
from app.middleware.auth import hash_key
from app.models.api_key import APIKey
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.communication import CommunicationDetails
from app.models.education_db import EducationProgram
from app.models.goals import Goal
from app.models.rate_config import RateConfig
from app.models.report_log import ReportLog
from app.models.tour_db import TourDestination

USER_KEY = "edge-user-key"
ADMIN_KEY = "edge-admin-key"
REVOKED_KEY = "edge-revoked-key"


class EdgeCaseTestConfig(Config):
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
    config_map["edge_test"] = EdgeCaseTestConfig

    from run import create_app

    test_app = create_app("edge_test")
    with test_app.app_context():
        db.create_all()
        cache.clear()
        seed_reference_rows()
        yield test_app
        db.session.remove()
        db.drop_all()
        cache.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_headers():
    return {"X-API-Key": USER_KEY}


@pytest.fixture()
def admin_headers():
    return {"X-API-Key": ADMIN_KEY}


def seed_reference_rows():
    db.session.add_all(
        [
            APIKey(
                client_name="Edge User",
                key_hash=hash_key(USER_KEY),
                role="user",
                is_active=True,
            ),
            APIKey(
                client_name="Edge Admin",
                key_hash=hash_key(ADMIN_KEY),
                role="admin",
                is_active=True,
            ),
            APIKey(
                client_name="Revoked User",
                key_hash=hash_key(REVOKED_KEY),
                role="user",
                is_active=False,
            ),
            RateConfig(
                inflation_post=0.06,
                roi_post=0.08,
                inflation_pre=0.06,
                roi_pre=0.12,
                updated_by="test",
            ),
            EducationProgram(
                level="Post Graduation",
                course_category="MBA",
                country="Canada",
                country_famous_for="Affordable Global MBA",
                approx_cost_inr=9_000_000,
                duration="2 Years",
                category="Premium",
                living_cost_included=True,
                lifestyle_level="Balanced Global Career",
                inflation_rate=0.08,
            ),
            EducationProgram(
                level="Post Graduation",
                course_category="MBA",
                country="USA",
                country_famous_for="Top Business Schools",
                approx_cost_inr=18_000_000,
                duration="2 Years",
                category="Premium",
                living_cost_included=True,
                lifestyle_level="Global Corporate Exposure",
                inflation_rate=0.08,
            ),
            TourDestination(
                country="Japan",
                budget_inr=380_000,
                duration="7-10 Days",
                category="Premium Experience",
            ),
            TourDestination(
                country="Malaysia",
                budget_inr=150_000,
                duration="5-7 Days",
                category="Budget Friendly",
            ),
        ]
    )
    db.session.commit()


def user_headers(raw_key=USER_KEY):
    return {"X-API-Key": raw_key}


def assert_error_response(response, expected_status, expected_code=None, expected_field=None):
    assert response.status_code == expected_status
    body = response.get_json()
    assert isinstance(body, dict)
    assert body["status"] == "error"
    assert "message" in body
    assert "request_id" in body
    if expected_code:
        assert body["code"] == expected_code
    if expected_field:
        assert body["field"] == expected_field


def assert_success_response(response, expected_status=200):
    assert response.status_code == expected_status
    body = response.get_json()
    assert isinstance(body, dict)
    assert body["status"] == "success"
    assert "data" in body
    assert "timestamp" in body
    return body


def create_assessment(client, headers):
    response = client.post("/api/v1/assessment/", headers=headers)
    body = assert_success_response(response)
    return body["data"]["assessment_id"]


def valid_flow1_payload(**overrides):
    payload = {
        "mobile": "9876543210",
        "email": "client@example.com",
        "spouse_mobile": "9876543211",
        "spouse_email": "spouse@example.com",
        "residential_address": "123 Main St",
        "consent": True,
    }
    payload.update(overrides)
    return payload


def valid_flow2_payload(**overrides):
    payload = {
        "client_name": "Test Client",
        "client_occupation": "Engineer",
        "client_designation": "Manager",
        "client_company": "Test Co",
        "client_dob": "01/01/1990",
        "client_retirement_age": 60,
        "spouse_name": "Test Spouse",
        "spouse_occupation": "Teacher",
        "spouse_designation": "Teacher",
        "spouse_company": "School",
        "spouse_dob": "01/01/1992",
        "spouse_retirement_age": 55,
    }
    payload.update(overrides)
    return payload


def valid_flow3_payload(**overrides):
    payload = {
        "number_of_children": 1,
        "children": [
            {
                "child_number": 1,
                "full_name": "Child One",
                "occupation": "Student",
                "financially_dependent": True,
                "date_of_birth": "01/01/2015",
            }
        ],
    }
    payload.update(overrides)
    return payload


def valid_flow4_payload(**overrides):
    payload = {
        "goals": [
            {
                "category": "child_goal",
                "goal_type": "Graduation",
                "target_year": current_year() + 10,
                "today_cost": 2_500_000,
                "inflation_rate": 0.08,
            }
        ]
    }
    payload.update(overrides)
    return payload


def complete_minimum_assessment(client, headers):
    assessment_id = create_assessment(client, headers)
    client.post(
        f"/api/v1/assessment/{assessment_id}/flow1",
        json=valid_flow1_payload(),
        headers=headers,
    )
    client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(),
        headers=headers,
    )
    return assessment_id


@pytest.mark.parametrize(
    ("endpoint", "payload_factory", "missing_field"),
    [
        ("flow1", valid_flow1_payload, "mobile"),
        ("flow1", valid_flow1_payload, "email"),
        ("flow1", valid_flow1_payload, "consent"),
        ("flow2", valid_flow2_payload, "client_name"),
        ("flow2", valid_flow2_payload, "client_occupation"),
        ("flow2", valid_flow2_payload, "client_designation"),
        ("flow2", valid_flow2_payload, "client_company"),
        ("flow2", valid_flow2_payload, "client_dob"),
        ("flow3", valid_flow3_payload, "number_of_children"),
        ("flow4", valid_flow4_payload, "goals"),
    ],
)
def test_flow_missing_required_fields_return_invalid_input(
    client, auth_headers, endpoint, payload_factory, missing_field
):
    assessment_id = create_assessment(client, auth_headers)
    payload = payload_factory()
    payload.pop(missing_field)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/{endpoint}",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", missing_field)


def test_calculate_without_personal_details_returns_not_found(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={},
        headers=auth_headers,
    )

    assert_error_response(response, 404, "NOT_FOUND")


def test_flow4_empty_goals_list_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json={"goals": []},
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")


@pytest.mark.parametrize(
    ("dob", "reason"),
    [
        (f"01/01/{current_year()}", "current_age below minimum 18"),
        (f"01/01/{current_year() - 150}", "current_age above maximum 80"),
    ],
)
def test_client_age_boundaries_return_invalid_input(client, auth_headers, dob, reason):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_dob=dob),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "client_dob")
    assert reason


def test_retirement_age_must_be_greater_than_current_age(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    age = current_year() - 1990

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_retirement_age=age),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "client_retirement_age")
    assert (
        "client_retirement_age must be greater than current age."
        in response.get_json()["message"]
    )


@pytest.mark.parametrize("today_cost", [0, -50_000])
def test_goal_today_cost_must_be_positive(client, auth_headers, today_cost):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["today_cost"] = today_cost

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")


def test_extremely_high_goal_cost_is_accepted_and_documented(client, auth_headers):
    """No max today_cost is defined, so very large costs should calculate successfully."""
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["today_cost"] = 999_999_999_999

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["goals"][0]["future_cost"] > 999_999_999_999


@pytest.mark.parametrize("inflation_rate", [0, 1.5])
def test_goal_inflation_rate_boundaries(client, auth_headers, inflation_rate):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["inflation_rate"] = inflation_rate

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")


def test_goal_target_year_current_year_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["target_year"] = current_year()

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")
    assert "target_year must be in the future" in response.get_json()["message"]


def test_goal_target_year_past_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["target_year"] = current_year() - 5

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")


def test_years_to_retirement_zero_is_graceful_not_server_error(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    age = current_year() - 1990
    client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_retirement_age=age),
        headers=auth_headers,
    )

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={},
        headers=auth_headers,
    )

    assert response.status_code != 500
    assert response.get_json()["status"] in {"success", "error"}


def test_calculate_with_zero_epf_values(client, auth_headers):
    assessment_id = complete_minimum_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={"client_epf_annual": 0, "client_epf_accum": 0},
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["client"]["pf_corpus"]["raw"] == 0


def test_calculate_with_null_epf_values(client, auth_headers):
    assessment_id = complete_minimum_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={},
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["client"]["pf_corpus"]["raw"] >= 0


def test_calculate_with_negative_household_monthly(client, auth_headers):
    assessment_id = complete_minimum_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={"household_monthly": -5000},
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "household_monthly")


def test_calculate_with_extremely_high_annual_ret_reqd(client, auth_headers):
    """No cap is currently defined, so very large retirement needs should calculate."""
    assessment_id = complete_minimum_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={"client_annual_ret_reqd": 999_999_999_999},
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["client"]["corpus"]["raw"] > 999_999_999_999


def test_calculate_missing_personal_required_fields_for_calc(client, auth_headers):
    assessment_id = complete_minimum_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/calculate/{assessment_id}",
        json={"client_annual_ret_reqd": None},
        headers=auth_headers,
    )

    assert response.status_code in {400, 404}
    assert response.get_json()["status"] == "error"


def test_mobile_with_letters_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow1",
        json=valid_flow1_payload(mobile="98abc54321"),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "mobile")


def test_mobile_too_short_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow1",
        json=valid_flow1_payload(mobile="123"),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "mobile")


def test_invalid_email_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow1",
        json=valid_flow1_payload(email="invalid-email"),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "email")


@pytest.mark.parametrize("client_name", ["", "   "])
def test_blank_client_name_returns_invalid_input(client, auth_headers, client_name):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_name=client_name),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "client_name")


def test_sql_injection_text_is_stored_as_literal(client, auth_headers, app):
    assessment_id = create_assessment(client, auth_headers)
    injection = "Robert'); DROP TABLE assessment_record;--"

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_name=injection),
        headers=auth_headers,
    )
    assert_success_response(response)

    detail = client.get(f"/api/v1/assessment/{assessment_id}", headers=auth_headers)
    body = assert_success_response(detail)
    assert body["data"]["flow2"]["client_name"] == injection

    with app.app_context():
        assert AssessmentRecord.query.count() == 1


def test_future_date_of_birth_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_dob=f"01/01/{current_year() + 1}"),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "client_dob")


def test_date_of_birth_age_over_100_returns_invalid_input_or_warning(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_dob=f"01/01/{current_year() - 101}"),
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert_error_response(response, 400, "INVALID_INPUT", "client_dob")


@pytest.mark.parametrize("date_string", ["32/13/2025", "2025-01-01"])
def test_malformed_or_mismatched_date_returns_invalid_input(
    client, auth_headers, date_string
):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow2",
        json=valid_flow2_payload(client_dob=date_string),
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "client_dob")


def test_flow3_zero_children(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow3",
        json={"number_of_children": 0, "children": []},
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["number_of_children"] == 0
    assert body["data"]["children"] == []


def test_flow3_negative_children(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow3",
        json={"number_of_children": -1, "children": []},
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "number_of_children")


def test_nonexistent_assessment_id_returns_not_found(client, auth_headers):
    response = client.get(
        "/api/v1/assessment/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )

    assert_error_response(response, 404, "NOT_FOUND")


def test_invalid_assessment_uuid_format_returns_invalid_input(client, auth_headers):
    response = client.get("/api/v1/assessment/not-a-uuid", headers=auth_headers)

    assert_error_response(response, 400, "INVALID_INPUT")


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        (
            "/api/v1/education/project-cost",
            {
                "program_id": "00000000-0000-0000-0000-000000000000",
                "target_year": current_year() + 5,
            },
        ),
        (
            "/api/v1/tour/project-cost",
            {
                "destination_id": "00000000-0000-0000-0000-000000000000",
                "target_year": current_year() + 5,
            },
        ),
    ],
)
def test_nonexistent_reference_ids_return_not_found(
    client, auth_headers, endpoint, payload
):
    response = client.post(endpoint, json=payload, headers=auth_headers)

    assert_error_response(response, 404, "NOT_FOUND")


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": ""}, {"X-API-Key": "random"}])
def test_invalid_api_keys_return_unauthorized(client, headers):
    response = client.get("/api/v1/rates/", headers=headers)

    assert_error_response(response, 401, "INVALID_API_KEY")


def test_user_key_calling_admin_endpoint_returns_forbidden(client, auth_headers):
    response = client.put(
        "/api/v1/rates/",
        json={"roi_pre": 0.11},
        headers=auth_headers,
    )

    assert_error_response(response, 403, "FORBIDDEN")


def test_revoked_key_returns_unauthorized(client):
    response = client.get("/api/v1/rates/", headers=user_headers(REVOKED_KEY))

    assert_error_response(response, 401, "INVALID_API_KEY")


def test_flow1_duplicate_submission_updates_existing_row(client, auth_headers, app):
    assessment_id = create_assessment(client, auth_headers)

    first = client.post(
        f"/api/v1/assessment/{assessment_id}/flow1",
        json=valid_flow1_payload(mobile="9876543210"),
        headers=auth_headers,
    )
    second = client.post(
        f"/api/v1/assessment/{assessment_id}/flow1",
        json=valid_flow1_payload(mobile="9876543219"),
        headers=auth_headers,
    )

    assert_success_response(first)
    assert_success_response(second)
    with app.app_context():
        rows = CommunicationDetails.query.filter_by(
            assessment_id=UUID(assessment_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].mobile == "9876543219"


def test_calculate_twice_creates_two_outputs_and_report_uses_latest(
    client, auth_headers, app, monkeypatch
):
    assessment_id = complete_minimum_assessment(client, auth_headers)

    first = client.post(f"/api/v1/calculate/{assessment_id}", json={}, headers=auth_headers)
    second = client.post(f"/api/v1/calculate/{assessment_id}", json={}, headers=auth_headers)
    assert_success_response(first)
    assert_success_response(second)

    with app.app_context():
        outputs = CalculationOutput.query.filter_by(
            assessment_id=UUID(assessment_id)
        ).all()
        assert len(outputs) == 2
        latest = CalculationOutput.query.filter_by(
            assessment_id=UUID(assessment_id)
        ).order_by(CalculationOutput.calculated_at.desc()).first()

    def fake_generate_report(assessment_id_str, calc, personal, comm, goals):
        assert calc.id == latest.id
        return {
            "file_name": f"report_{assessment_id_str}.pdf",
            "pdf_path": f"reports/report_{assessment_id_str}.pdf",
        }

    monkeypatch.setattr(
        "app.api.v1.report.routes.generate_report",
        fake_generate_report,
    )

    response = client.post(
        f"/api/v1/report/{assessment_id}/generate",
        headers=auth_headers,
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["status"] == "processing"
    job_id = body["data"]["job_id"]

    for _ in range(20):
        status = client.get(
            f"/api/v1/report/{assessment_id}/status/{job_id}",
            headers=auth_headers,
        )
        status_body = status.get_json()
        if status_body["status"] != "processing":
            break
        time.sleep(0.05)

    assert status_body["status"] == "success"
    with app.app_context():
        log = ReportLog.query.filter_by(assessment_id=UUID(assessment_id)).first()
        assert log.calculation_id == latest.id


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/education/options-for-budget",
        "/api/v1/tour/destinations-for-budget",
    ],
)
@pytest.mark.parametrize("budget", [0, -100])
def test_budget_zero_or_negative_returns_invalid_input(
    client, auth_headers, endpoint, budget
):
    response = client.get(f"{endpoint}?budget={budget}", headers=auth_headers)

    assert_error_response(response, 400, "INVALID_INPUT", "budget")


def test_tour_project_cost_zero_travellers(client, auth_headers, app):
    with app.app_context():
        destination_id = str(TourDestination.query.filter_by(country="Japan").first().id)

    response = client.post(
        "/api/v1/tour/project-cost",
        json={
            "destination_id": destination_id,
            "target_year": current_year() + 5,
            "travellers": 0,
        },
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT")


def test_tour_project_cost_negative_travellers(client, auth_headers, app):
    with app.app_context():
        destination_id = str(TourDestination.query.filter_by(country="Japan").first().id)

    response = client.post(
        "/api/v1/tour/project-cost",
        json={
            "destination_id": destination_id,
            "target_year": current_year() + 5,
            "travellers": -2,
        },
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT")


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/education/options-for-budget",
        "/api/v1/tour/destinations-for-budget",
    ],
)
def test_tolerance_percent_negative(client, auth_headers, endpoint):
    response = client.get(
        f"{endpoint}?budget=150000&tolerance_percent=-10",
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "tolerance_percent")


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/education/options-for-budget",
        "/api/v1/tour/destinations-for-budget",
    ],
)
def test_low_budget_with_no_matches_returns_empty_list(client, auth_headers, endpoint):
    response = client.get(
        f"{endpoint}?budget=1&tolerance_percent=100",
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


def test_education_tolerance_zero_returns_exact_matches(client, auth_headers):
    response = client.get(
        "/api/v1/education/options-for-budget?budget=9000000&tolerance_percent=0",
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["approx_cost_inr"] == 9_000_000


def test_tour_tolerance_zero_returns_exact_matches(client, auth_headers):
    response = client.get(
        "/api/v1/tour/destinations-for-budget?budget=150000&tolerance_percent=0",
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["budget_inr"] == 150_000


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/education/options-for-budget?budget=9000000&tolerance_percent=100",
        "/api/v1/tour/destinations-for-budget?budget=150000&tolerance_percent=100",
    ],
)
def test_tolerance_hundred_returns_wide_range(client, auth_headers, endpoint):
    response = client.get(endpoint, headers=auth_headers)

    body = assert_success_response(response)
    assert body["data"]["total"] >= 1


def test_assessment_bulk_creates_records_and_communications(
    client, auth_headers, app
):
    response = client.post(
        "/api/v1/assessment/bulk",
        json={
            "assessments": [
                valid_flow1_payload(email="bulk1@example.com"),
                valid_flow1_payload(email="bulk2@example.com"),
            ]
        },
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assessment_ids = body["data"]["assessment_ids"]
    assert len(assessment_ids) == 2

    with app.app_context():
        assert (
            CommunicationDetails.query.filter(
                CommunicationDetails.assessment_id.in_(
                    [UUID(assessment_id) for assessment_id in assessment_ids]
                )
            ).count()
            == 2
        )


def test_assessment_bulk_limit_returns_invalid_input(client, auth_headers):
    response = client.post(
        "/api/v1/assessment/bulk",
        json={"assessments": [valid_flow1_payload() for _ in range(101)]},
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "assessments")
    assert "Maximum 100 items per bulk request" in response.get_json()["message"]


def test_assessment_bulk_invalid_item_rolls_back_all_records(
    client, auth_headers, app
):
    with app.app_context():
        before = AssessmentRecord.query.count()

    response = client.post(
        "/api/v1/assessment/bulk",
        json={
            "assessments": [
                valid_flow1_payload(email="valid@example.com"),
                valid_flow1_payload(email="invalid-email"),
            ]
        },
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "email")
    assert "Item 1 failed validation" in response.get_json()["message"]
    with app.app_context():
        assert AssessmentRecord.query.count() == before


def create_assessment_with_child(client, headers, child_name):
    assessment_id = create_assessment(client, headers)
    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow3",
        json={
            "number_of_children": 1,
            "children": [
                {
                    "child_number": 1,
                    "full_name": child_name,
                    "occupation": "Student",
                    "financially_dependent": True,
                    "date_of_birth": "01/01/2015",
                }
            ],
        },
        headers=headers,
    )
    body = assert_success_response(response)
    return assessment_id, body["data"]["children"][0]["id"]


def test_goal_child_id_must_belong_to_same_assessment(client, auth_headers):
    _, other_child_id = create_assessment_with_child(
        client, auth_headers, "Other Assessment Child"
    )
    target_assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["child_id"] = other_child_id

    response = client.post(
        f"/api/v1/assessment/{target_assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "child_id")


def test_goal_child_id_nonexistent_returns_not_found(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["child_id"] = "00000000-0000-0000-0000-000000000000"

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/goals/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 404, "NOT_FOUND", "child_id")


def test_goal_category_invalid_value_rejected(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["category"] = "vacation"

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")


def test_goal_inflation_rate_omitted_defaults_safely(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0].pop("inflation_rate")

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    body = assert_success_response(response)
    goal = body["data"]["goals"][0]
    assert goal["inflation_rate"] == 0.06
    assert goal["future_cost"] is not None


def test_goal_target_year_unreasonably_far(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    payload = valid_flow4_payload()
    payload["goals"][0]["target_year"] = 9999

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")


def test_duplicate_goal_same_type_and_year(client, auth_headers, app):
    assessment_id = create_assessment(client, auth_headers)
    goal = valid_flow4_payload()["goals"][0]
    payload = {"goals": [goal, dict(goal)]}

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/goals/bulk",
        json=payload,
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert len(body["data"]["goals"]) == 2
    with app.app_context():
        assert Goal.query.filter_by(assessment_id=UUID(assessment_id)).count() == 2


def test_goal_education_program_id_must_exist(client, auth_headers, app):
    assessment_id = create_assessment(client, auth_headers)
    with app.app_context():
        program = EducationProgram.query.filter_by(country="Canada").first()
        program_id = str(program.id)

    payload = valid_flow4_payload()
    payload["goals"][0].pop("today_cost")
    payload["goals"][0].pop("inflation_rate")
    payload["goals"][0]["education_program_id"] = program_id
    first_response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )
    first_body = assert_success_response(first_response)
    first_goal = first_body["data"]["goals"][0]
    assert first_goal["education_program_id"] == program_id
    assert first_goal["today_cost"] == program.approx_cost_inr
    assert first_goal["inflation_rate"] == program.inflation_rate

    payload["goals"][0]["education_program_id"] = (
        "00000000-0000-0000-0000-000000000000"
    )
    second_response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )
    assert_error_response(second_response, 404, "NOT_FOUND", "education_program_id")


def test_goal_tour_destination_id_must_exist(client, auth_headers, app):
    assessment_id = create_assessment(client, auth_headers)
    with app.app_context():
        destination = TourDestination.query.filter_by(country="Japan").first()
        destination_id = str(destination.id)

    payload = valid_flow4_payload()
    payload["goals"][0].pop("today_cost")
    payload["goals"][0]["tour_destination_id"] = destination_id
    first_response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )
    first_body = assert_success_response(first_response)
    first_goal = first_body["data"]["goals"][0]
    assert first_goal["tour_destination_id"] == destination_id
    assert first_goal["today_cost"] == destination.budget_inr

    payload["goals"][0]["tour_destination_id"] = (
        "00000000-0000-0000-0000-000000000000"
    )
    second_response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json=payload,
        headers=auth_headers,
    )
    assert_error_response(second_response, 404, "NOT_FOUND", "tour_destination_id")


def test_goals_bulk_creates_goals_and_flow4_reuses_same_behavior(
    client, auth_headers, app
):
    assessment_id = create_assessment(client, auth_headers)
    payload = {
        "goals": [
            {
                "category": "child_goal",
                "goal_type": "Graduation",
                "target_year": current_year() + 10,
                "today_cost": 1_000_000,
                "inflation_rate": 0.08,
            },
            {
                "category": "lifestyle",
                "goal_type": "Foreign Tour",
                "target_year": current_year() + 5,
                "today_cost": 500_000,
                "inflation_rate": 0.06,
            },
        ]
    }

    bulk_response = client.post(
        f"/api/v1/assessment/{assessment_id}/goals/bulk",
        json=payload,
        headers=auth_headers,
    )
    bulk_body = assert_success_response(bulk_response)
    assert len(bulk_body["data"]["goals"]) == 2

    flow4_response = client.post(
        f"/api/v1/assessment/{assessment_id}/flow4",
        json={"goals": [payload["goals"][0]]},
        headers=auth_headers,
    )
    flow4_body = assert_success_response(flow4_response)
    assert len(flow4_body["data"]["goals"]) == 1

    with app.app_context():
        assert Goal.query.filter_by(assessment_id=UUID(assessment_id)).count() == 1


def test_goals_bulk_limit_returns_invalid_input(client, auth_headers):
    assessment_id = create_assessment(client, auth_headers)
    goal = valid_flow4_payload()["goals"][0]

    response = client.post(
        f"/api/v1/assessment/{assessment_id}/goals/bulk",
        json={"goals": [goal for _ in range(51)]},
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "goals")
    assert "Maximum 50 items per bulk request" in response.get_json()["message"]


def test_education_bulk_cost_returns_multiple_programs(client, auth_headers, app):
    with app.app_context():
        program_ids = [
            str(program.id)
            for program in EducationProgram.query.order_by(
                EducationProgram.country
            ).all()
        ]

    response = client.get(
        f"/api/v1/education/bulk-cost?program_ids={','.join(program_ids)}",
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert [item["id"] for item in body["data"]] == program_ids


def test_education_bulk_cost_limit_returns_invalid_input(client, auth_headers):
    ids = ",".join(["00000000-0000-0000-0000-000000000000"] * 51)

    response = client.get(
        f"/api/v1/education/bulk-cost?program_ids={ids}",
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "program_ids")
    assert "Maximum 50 items per bulk request" in response.get_json()["message"]


def test_tour_bulk_budget_returns_multiple_destinations(client, auth_headers, app):
    with app.app_context():
        destination_ids = [
            str(destination.id)
            for destination in TourDestination.query.order_by(
                TourDestination.country
            ).all()
        ]

    response = client.get(
        f"/api/v1/tour/bulk-budget?destination_ids={','.join(destination_ids)}",
        headers=auth_headers,
    )

    body = assert_success_response(response)
    assert [item["id"] for item in body["data"]] == destination_ids


def test_tour_bulk_budget_limit_returns_invalid_input(client, auth_headers):
    ids = ",".join(["00000000-0000-0000-0000-000000000000"] * 51)

    response = client.get(
        f"/api/v1/tour/bulk-budget?destination_ids={ids}",
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "destination_ids")
    assert "Maximum 50 items per bulk request" in response.get_json()["message"]


def test_report_bulk_generate_returns_jobs_and_polling_completes(
    client, auth_headers, monkeypatch
):
    assessment_id = complete_minimum_assessment(client, auth_headers)
    calculate = client.post(
        f"/api/v1/calculate/{assessment_id}", json={}, headers=auth_headers
    )
    assert_success_response(calculate)

    def fake_generate_report(assessment_id_str, calc, personal, comm, goals):
        return {
            "file_name": f"bulk_report_{assessment_id_str}.pdf",
            "pdf_path": f"reports/bulk_report_{assessment_id_str}.pdf",
        }

    monkeypatch.setattr(
        "app.api.v1.report.routes.generate_report",
        fake_generate_report,
    )

    response = client.post(
        "/api/v1/report/bulk-generate",
        json={"assessment_ids": [assessment_id]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "processing"
    assert len(body["data"]["jobs"]) == 1
    job_id = body["data"]["jobs"][0]["job_id"]

    for _ in range(20):
        status = client.get(
            f"/api/v1/report/{assessment_id}/status/{job_id}",
            headers=auth_headers,
        )
        status_body = status.get_json()
        if status_body["status"] != "processing":
            break
        time.sleep(0.05)

    assert status_body["status"] == "success"


def test_report_bulk_generate_invalid_item_returns_error_before_jobs(
    client, auth_headers
):
    response = client.post(
        "/api/v1/report/bulk-generate",
        json={"assessment_ids": ["not-a-uuid"]},
        headers=auth_headers,
    )

    assert_error_response(response, 400, "INVALID_INPUT", "assessment_ids")
    assert "Item 0 failed validation" in response.get_json()["message"]
