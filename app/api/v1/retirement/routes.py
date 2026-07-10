from datetime import datetime, timezone

from flask import request
from flask_restx import Namespace, Resource, fields

from app.core.formatters import fmt_display, fmt_response
from app.core.formulas import full_corpus_calc
from app.core.swagger_models import error_model
from app.middleware.auth import require_api_key
from app.models.rate_config import RateConfig

ns = Namespace(
    "retirement",
    description="Retirement corpus calculation including EPF, NPS, and Superannuation",
    path="/retirement",
)

full_input = ns.model(
    "RetirementFullInput",
    {
        "annual_ret_reqd": fields.Float(
            required=True,
            description="Annual retirement expense requirement (₹)",
            example=600000,
        ),
        "current_age": fields.Integer(required=True, example=44),
        "retirement_age": fields.Integer(required=True, example=58),
        "epf_annual_total": fields.Float(required=True, example=167760),
        "current_epf_accum": fields.Float(required=True, example=1560000),
        "employer_nps_pm": fields.Float(
            required=False, default=0, description="Employer NPS per month (₹)"
        ),
        "self_nps_pm": fields.Float(
            required=False, default=0, description="Self NPS per month (₹)"
        ),
        "current_nps_accum": fields.Float(
            required=False, default=0, description="Current NPS balance (₹)"
        ),
        "sa_pm": fields.Float(
            required=False, default=0, description="Monthly SA contribution (₹)"
        ),
        "current_sa_accum": fields.Float(
            required=False, default=0, description="Current SA balance (₹)"
        ),
    },
)

success_envelope_model = ns.model("RetirementSuccessEnvelope", {
    "status": fields.String(required=True, example="success"),
    "data": fields.Raw(required=True),
    "timestamp": fields.String(required=True),
})


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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


@ns.route("/full")
class RetirementFull(Resource):
    @require_api_key
    @ns.doc(security="apikey")
    @ns.expect(full_input, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        """Full retirement corpus calc including EPF, NPS, and SA provisions."""
        data = request.get_json(silent=True) or {}
        rates = get_rates()

        calc = full_corpus_calc(
            annual_ret_reqd=data["annual_ret_reqd"],
            current_age=data["current_age"],
            retirement_age=data["retirement_age"],
            epf_annual_total=data["epf_annual_total"],
            current_epf_accum=data["current_epf_accum"],
            inflation_post=rates["inflation_post"],
            roi_post=rates["roi_post"],
            inflation_pre=rates["inflation_pre"],
            roi_pre=rates["roi_pre"],
            employer_nps_pm=data.get("employer_nps_pm", 0),
            self_nps_pm=data.get("self_nps_pm", 0),
            current_nps_accum=data.get("current_nps_accum", 0),
            sa_pm=data.get("sa_pm", 0),
            current_sa_accum=data.get("current_sa_accum", 0),
            pf_growth=rates["pf_growth"],
        )

        return success_response(
            {
                "corpus_display": fmt_display(calc["corpus"]),
                "corpus_raw": abs(calc["corpus"]),
                "pf_fv_display": fmt_display(calc["pf_fv"]),
                "pf_fv_raw": abs(calc["pf_fv"]),
                "nps_fv_display": fmt_display(calc["nps_fv"]),
                "nps_fv_raw": abs(calc["nps_fv"]),
                "sa_fv_display": fmt_display(calc["sa_fv"]),
                "sa_fv_raw": abs(calc["sa_fv"]),
                "total_existing_provision_display": fmt_display(
                    calc["total_existing_provision"]
                ),
                "total_existing_provision_raw": abs(calc["total_existing_provision"]),
                "net_corpus_display": fmt_display(calc["net_corpus"]),
                "net_corpus_raw": abs(calc["net_corpus"]),
                "monthly_investment_display": fmt_display(calc["monthly_investment"]),
                "monthly_investment_raw": abs(calc["monthly_investment"]),
                "lump_sum_display": fmt_display(calc["lump_sum"]),
                "lump_sum_raw": abs(calc["lump_sum"]),
                "corpus": fmt_response(calc["corpus"]),
                "pf_fv": fmt_response(calc["pf_fv"]),
                "nps_fv": fmt_response(calc["nps_fv"]),
                "sa_fv": fmt_response(calc["sa_fv"]),
                "total_existing_provision": fmt_response(calc["total_existing_provision"]),
                "net_corpus": fmt_response(calc["net_corpus"]),
                "monthly_investment": fmt_response(calc["monthly_investment"]),
                "lump_sum": fmt_response(calc["lump_sum"]),
                "years_to_retirement": calc["years_to_retirement"],
                "retirement_period": calc["retirement_period"],
            }
        )
