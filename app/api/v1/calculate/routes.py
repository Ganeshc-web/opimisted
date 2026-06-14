from datetime import datetime

from flask import request
from flask_restx import Namespace, Resource

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
from app.middleware.auth import require_api_key
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.rate_config import RateConfig

ns = Namespace("calculate", description="Run calculations", path="/calculate")

REQUEST_DEFAULTS = {
    "client_epf_annual": 33600,
    "client_epf_accum": 0,
    "client_annual_ret_reqd": 1500000,
    "spouse_epf_annual": 7200,
    "spouse_epf_accum": 0,
    "spouse_annual_ret_reqd": 1000000,
    "household_monthly": 30000,
}


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_rates():
    config = RateConfig.query.first()
    if config:
        return {
            "inflation_post": config.inflation_post,
            "roi_post": config.roi_post,
            "inflation_pre": config.inflation_pre,
            "roi_pre": config.roi_pre,
        }
    return {
        "inflation_post": 0.06,
        "roi_post": 0.08,
        "inflation_pre": 0.06,
        "roi_pre": 0.12,
    }


def get_body():
    payload = request.get_json(silent=True) or {}
    return {key: payload.get(key, default) for key, default in REQUEST_DEFAULTS.items()}


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
        "net_corpus": 0.0,
        "monthly_investment": 0.0,
        "lump_sum": 0.0,
        "pf_table": [],
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


def fmt_pf_table(rows):
    return [
        {
            "Year": row["Year"],
            "Opening (₹)": fmt_response(row["Opening (₹)"]),
            "Contribution (₹)": fmt_response(row["Contribution (₹)"]),
            "Closing (₹)": fmt_response(row["Closing (₹)"]),
        }
        for row in rows
    ]


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
        "net_corpus": fmt_response(calc["net_corpus"]),
        "monthly_sip": fmt_response(calc["monthly_investment"]),
        "lump_sum": fmt_response(calc["lump_sum"]),
        "pf_table": fmt_pf_table(calc["pf_table"]),
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


@ns.route("/<uuid:assessment_id>")
class CalculateAssessment(Resource):
    @require_api_key
    def post(self, assessment_id):
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
            calculated_at=datetime.utcnow(),
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
