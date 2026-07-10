from datetime import datetime, timezone
import uuid

from flask import request
from flask_restx import Namespace, Resource, fields

from app import db
from app.core.exceptions import APIError
from app.core.formatters import fmt_response
from app.core.formulas import (
    PF_MONTHLY_RATE,
    build_insurance_rows,
    compute_all_goals,
    full_corpus_calc,
    monthly_effective_rate,
    real_rate,
)
from app.core.swagger_models import error_model
from app.middleware.auth import require_api_key
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.rate_config import RateConfig

ns = Namespace(
    "calculate",
    description=(
        "Runs retirement, EPF, goal, and insurance calculations for a "
        "completed assessment. Retirement ages are read from saved "
        "PersonalDetails."
    ),
    path="/calculate",
)

calculate_input_model = ns.model("CalculateInput", {
    "client_epf_annual": fields.Float(required=False, description="Client annual EPF contribution.", example=33600),
    "client_epf_accum": fields.Float(required=False, description="Client existing EPF balance.", example=1039997),
    "client_annual_ret_reqd": fields.Float(required=False, description="Client annual retirement expense requirement.", example=1500000),
    "spouse_epf_annual": fields.Float(required=False, description="Spouse annual EPF contribution.", example=7200),
    "spouse_epf_accum": fields.Float(required=False, description="Spouse existing EPF balance.", example=0),
    "spouse_annual_ret_reqd": fields.Float(required=False, description="Spouse annual retirement expense requirement.", example=1000000),
    "household_monthly": fields.Float(required=False, description="Current monthly household expense for insurance need.", example=30000),
    "employer_nps_pm": fields.Float(required=False, description="Employer NPS per month (₹).", example=0),
    "self_nps_pm": fields.Float(required=False, description="Self NPS per month (₹).", example=0),
    "current_nps_accum": fields.Float(required=False, description="Current NPS balance (₹).", example=0),
    "sa_pm": fields.Float(required=False, description="Monthly SA contribution (₹).", example=0),
    "current_sa_accum": fields.Float(required=False, description="Current SA balance (₹).", example=0),
    "spouse_employer_nps_pm": fields.Float(required=False, description="Spouse employer NPS per month (₹).", example=0),
    "spouse_self_nps_pm": fields.Float(required=False, description="Spouse self NPS per month (₹).", example=0),
    "spouse_current_nps_accum": fields.Float(required=False, description="Spouse current NPS balance (₹).", example=0),
    "spouse_sa_pm": fields.Float(required=False, description="Spouse monthly SA contribution (₹).", example=0),
    "spouse_current_sa_accum": fields.Float(required=False, description="Spouse current SA balance (₹).", example=0),
})

calculate_response_model = ns.model("CalculateResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Raw(required=True, description="Full calculation payload including corpus, goals, and insurance outputs."),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})

REQUEST_DEFAULTS = {
    "client_epf_annual": 33600,
    "client_epf_accum": 0,
    "client_annual_ret_reqd": 1500000,
    "spouse_epf_annual": 7200,
    "spouse_epf_accum": 0,
    "spouse_annual_ret_reqd": 1000000,
    "household_monthly": 30000,
    "employer_nps_pm": 0,
    "self_nps_pm": 0,
    "current_nps_accum": 0,
    "sa_pm": 0,
    "current_sa_accum": 0,
    "spouse_employer_nps_pm": 0,
    "spouse_self_nps_pm": 0,
    "spouse_current_nps_accum": 0,
    "spouse_sa_pm": 0,
    "spouse_current_sa_accum": 0,
}


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def parse_uuid_param(value, field_name):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise APIError(
            "INVALID_INPUT",
            f"{field_name} must be a valid UUID.",
            field=field_name,
            http_status=400,
        )


def get_rates():
    config = RateConfig.query.first()
    if config:
        return {
            "inflation_post": config.inflation_post,
            "roi_post": config.roi_post,
            "inflation_pre": config.inflation_pre,
            "roi_pre": config.roi_pre,
            "pf_growth": config.pf_growth if config.pf_growth is not None else 0.05,
        }
    return {
        "inflation_post": 0.06,
        "roi_post": 0.08,
        "inflation_pre": 0.06,
        "roi_pre": 0.12,
        "pf_growth": 0.05,
    }


def get_body():
    payload = request.get_json(silent=True) or {}
    return {key: payload.get(key, default) for key, default in REQUEST_DEFAULTS.items()}


def validate_non_negative_monetary_fields(data):
    for field_name in (
        "household_monthly",
        "client_epf_annual",
        "client_epf_accum",
        "spouse_epf_annual",
        "spouse_epf_accum",
        "employer_nps_pm",
        "self_nps_pm",
        "current_nps_accum",
        "sa_pm",
        "current_sa_accum",
        "spouse_employer_nps_pm",
        "spouse_self_nps_pm",
        "spouse_current_nps_accum",
        "spouse_sa_pm",
        "spouse_current_sa_accum",
    ):
        value = data.get(field_name)
        if value is not None and value < 0:
            raise APIError(
                "INVALID_INPUT",
                f"{field_name} cannot be negative.",
                field=field_name,
                http_status=400,
            )


def empty_corpus_calc():
    return {
        "real_rate": 0.0,
        "real_rate_monthly": 0.0,
        "retirement_period": 0,
        "expenses_today_pm": 0.0,
        "years_to_retirement": 0,
        "expenses_at_retirement_pm": 0.0,
        "corpus": 0.0,
        "pf_fv": 0.0,
        "nps_fv": 0.0,
        "sa_fv": 0.0,
        "total_existing_provision": 0.0,
        "net_corpus": 0.0,
        "monthly_investment": 0.0,
        "lump_sum": 0.0,
        "pf_table": [],
        "nps_table": [],
        "sa_table": [],
    }


def goals_to_formula_input(goals):
    return [
        {
            "Goal": goal.goal_type,
            "Target Year": goal.target_year,
            "Current Cost (₹)": goal.today_cost,
            "Inflation": goal.inflation_rate,
        }
        for goal in goals
    ]


def fmt_accumulation_table(rows):
    return [
        {
            "Year": row["Year"],
            "Opening (₹)": fmt_response(row["Opening (₹)"]),
            "Contribution (₹)": fmt_response(row["Contribution (₹)"]),
            "Closing (₹)": fmt_response(row["Closing (₹)"]),
        }
        for row in rows
    ]


def fmt_pf_table(rows):
    return fmt_accumulation_table(rows)


def fmt_corpus_calc(calc):
    return {
        "real_rate": calc["real_rate"],
        "real_rate_monthly": calc["real_rate_monthly"],
        "retirement_period": calc["retirement_period"],
        "years_to_retirement": calc["years_to_retirement"],
        "expenses_today_pm": fmt_response(calc["expenses_today_pm"]),
        "expenses_at_retirement_pm": fmt_response(calc["expenses_at_retirement_pm"]),
        "corpus": fmt_response(calc["corpus"]),
        "pf_corpus": fmt_response(calc["pf_fv"]),
        "nps_corpus": fmt_response(calc["nps_fv"]),
        "sa_corpus": fmt_response(calc["sa_fv"]),
        "total_existing_provision": fmt_response(calc["total_existing_provision"]),
        "net_corpus": fmt_response(calc["net_corpus"]),
        "monthly_sip": fmt_response(calc["monthly_investment"]),
        "lump_sum": fmt_response(calc["lump_sum"]),
        "pf_table": fmt_pf_table(calc["pf_table"]),
        "nps_table": fmt_accumulation_table(calc.get("nps_table", [])),
        "sa_table": fmt_accumulation_table(calc.get("sa_table", [])),
    }


def fmt_goal_row(row):
    return {
        "goal": row["Goal"],
        "target_year": row["Target Year"],
        "current_cost": fmt_response(row["current_cost"]),
        "inflation_rate": row["Inflation"],
        "years_from_now": row["years_from_now"],
        "future_cost": fmt_response(row["future_cost"]),
        "monthly_sip": fmt_response(row["monthly_inv"]),
    }


def fmt_insurance_row(row):
    return {
        "need": row["Need"],
        "years": row["Years"],
        "amount": fmt_response(row["Amount (₹)"]),
        "type": row["Type"],
        "pv": fmt_response(row["PV (₹)"]),
    }


@ns.route("/<string:assessment_id>")
class CalculateAssessment(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Runs the full financial planning calculation for an assessment. "
            "Requires saved PersonalDetails; optional body fields override "
            "calculation defaults for EPF, retirement expense, and household expense."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.expect(calculate_input_model, validate=True)
    @ns.response(200, "Success", calculate_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    @ns.response(422, "Calculation error", error_model)
    def post(self, assessment_id):
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")
        assessment = db.session.get(AssessmentRecord, assessment_id)
        if not assessment:
            raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

        personal = PersonalDetails.query.filter_by(
            assessment_id=assessment_id
        ).first()
        if not personal:
            raise APIError(
                "NOT_FOUND",
                "Personal details not found for this assessment.",
                http_status=404,
            )

        body = get_body()
        validate_non_negative_monetary_fields(body)
        rates = get_rates()
        rr = real_rate(rates["roi_post"], rates["inflation_post"])
        monthly_eff_pre = monthly_effective_rate(rates["roi_pre"])

        try:
            client_calc = full_corpus_calc(
                body["client_annual_ret_reqd"],
                personal.client_age,
                personal.client_retirement_age,
                body["client_epf_annual"],
                body["client_epf_accum"],
                rates["inflation_post"],
                rates["roi_post"],
                rates["inflation_pre"],
                rates["roi_pre"],
                employer_nps_pm=body["employer_nps_pm"],
                self_nps_pm=body["self_nps_pm"],
                current_nps_accum=body["current_nps_accum"],
                sa_pm=body["sa_pm"],
                current_sa_accum=body["current_sa_accum"],
                pf_growth=rates["pf_growth"],
            )

            has_spouse = bool(personal.spouse_name or personal.spouse_dob)
            if has_spouse and personal.spouse_age is not None:
                spouse_calc = full_corpus_calc(
                    body["spouse_annual_ret_reqd"],
                    personal.spouse_age,
                    personal.spouse_retirement_age,
                    body["spouse_epf_annual"],
                    body["spouse_epf_accum"],
                    rates["inflation_post"],
                    rates["roi_post"],
                    rates["inflation_pre"],
                    rates["roi_pre"],
                    employer_nps_pm=body["spouse_employer_nps_pm"],
                    self_nps_pm=body["spouse_self_nps_pm"],
                    current_nps_accum=body["spouse_current_nps_accum"],
                    sa_pm=body["spouse_sa_pm"],
                    current_sa_accum=body["spouse_current_sa_accum"],
                    pf_growth=rates["pf_growth"],
                )
            else:
                spouse_calc = empty_corpus_calc()

            goal_rows = Goal.query.filter_by(assessment_id=assessment_id).all()
            goal_results, total_goals_monthly_sip = compute_all_goals(
                goals_to_formula_input(goal_rows),
                monthly_eff_pre,
            )

            insurance_rows, total_insurance = build_insurance_rows(
                client_calc["years_to_retirement"],
                spouse_calc["years_to_retirement"],
                body["household_monthly"],
                body["client_annual_ret_reqd"],
                body["spouse_annual_ret_reqd"] if has_spouse else 0.0,
                goal_results,
                rr,
                rates["roi_post"],
            )
        except Exception as exc:
            raise APIError(
                "CALCULATION_ERROR",
                f"Calculation failed: {exc}",
                http_status=422,
            ) from exc

        output = CalculationOutput(
            assessment_id=assessment_id,
            pf_monthly_rate=PF_MONTHLY_RATE,
            real_rate=rr,
            real_rate_monthly=client_calc["real_rate_monthly"],
            monthly_eff_pre=monthly_eff_pre,
            client_corpus=client_calc["corpus"],
            client_pf_corpus=client_calc["pf_fv"],
            client_net_corpus=client_calc["net_corpus"],
            client_monthly_sip=client_calc["monthly_investment"],
            client_lump_sum=client_calc["lump_sum"],
            spouse_corpus=spouse_calc["corpus"],
            spouse_pf_corpus=spouse_calc["pf_fv"],
            spouse_net_corpus=spouse_calc["net_corpus"],
            spouse_monthly_sip=spouse_calc["monthly_investment"],
            spouse_lump_sum=spouse_calc["lump_sum"],
            total_insurance_required=total_insurance,
            total_goals_monthly_sip=total_goals_monthly_sip,
            client_annual_ret_reqd=body["client_annual_ret_reqd"],
            spouse_annual_ret_reqd=body["spouse_annual_ret_reqd"] if has_spouse else 0.0,
            inflation_pre=rates["inflation_pre"],
            roi_pre=rates["roi_pre"],
            inflation_post=rates["inflation_post"],
            roi_post=rates["roi_post"],
            calculated_at=datetime.now(timezone.utc),
        )
        db.session.add(output)
        db.session.commit()

        response_data = {
            "calculation_id": str(output.id),
            "assessment_id": str(assessment_id),
            "calculated_at": output.calculated_at.isoformat(),
            "rates": {
                "pf_monthly_rate": PF_MONTHLY_RATE,
                "real_rate": rr,
                "real_rate_monthly": client_calc["real_rate_monthly"],
                "monthly_eff_pre": monthly_eff_pre,
                "inflation_post": rates["inflation_post"],
                "roi_post": rates["roi_post"],
                "inflation_pre": rates["inflation_pre"],
                "roi_pre": rates["roi_pre"],
            },
            "client": fmt_corpus_calc(client_calc),
            "spouse": fmt_corpus_calc(spouse_calc) if has_spouse else None,
            "goals": {
                "items": [fmt_goal_row(row) for row in goal_results],
                "total_monthly_sip": fmt_response(total_goals_monthly_sip),
            },
            "insurance": {
                "items": [fmt_insurance_row(row) for row in insurance_rows],
                "total_required": fmt_response(total_insurance),
            },
        }

        return success_response(response_data)
