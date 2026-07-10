from datetime import datetime, timezone

from flask import request
from flask_restx import Namespace, Resource, fields

from app.core.formatters import fmt_display
from app.core.formulas import nps_table
from app.core.swagger_models import error_model
from app.middleware.auth import require_api_key

ns = Namespace(
    "nps",
    description="NPS (National Pension System) accumulation",
    path="/nps",
)

nps_input = ns.model(
    "NPSInput",
    {
        "current_nps_accum": fields.Float(
            required=True,
            description="Current NPS balance (₹)",
            example=0,
        ),
        "employer_nps_pm": fields.Float(
            required=True,
            description="Employer NPS contribution per month (₹)",
            example=5000,
        ),
        "self_nps_pm": fields.Float(
            required=True,
            description="Self NPS contribution per month (₹)",
            example=2000,
        ),
        "years_to_retirement": fields.Integer(
            required=True,
            description="Years to retirement",
            example=25,
        ),
    },
)

success_envelope_model = ns.model("NPSSuccessEnvelope", {
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


def get_payload():
    return request.get_json(silent=True) or {}


def fmt_table_rows(rows):
    return [
        {
            "year": row["Year"],
            "opening_display": fmt_display(row["Opening (₹)"]),
            "opening_raw": abs(row["Opening (₹)"]),
            "contribution_display": fmt_display(row["Contribution (₹)"]),
            "contribution_raw": abs(row["Contribution (₹)"]),
            "closing_display": fmt_display(row["Closing (₹)"]),
            "closing_raw": abs(row["Closing (₹)"]),
        }
        for row in rows
    ]


@ns.route("/accumulation")
class NPSAccumulation(Resource):
    @require_api_key
    @ns.doc(security="apikey")
    @ns.expect(nps_input, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        """Year-by-year NPS accumulation table with 5% annual contribution growth."""
        data = get_payload()
        rows, final_corpus = nps_table(
            current_nps_accum=data["current_nps_accum"],
            employer_nps_pm=data["employer_nps_pm"],
            self_nps_pm=data["self_nps_pm"],
            years_to_retirement=data["years_to_retirement"],
        )
        return success_response(
            {
                "final_corpus_display": fmt_display(final_corpus),
                "final_corpus_raw": abs(final_corpus),
                "table": fmt_table_rows(rows),
            }
        )


@ns.route("/corpus")
class NPSCorpus(Resource):
    @require_api_key
    @ns.doc(security="apikey")
    @ns.expect(nps_input, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        """Final NPS corpus at retirement only."""
        data = get_payload()
        _, final_corpus = nps_table(
            current_nps_accum=data["current_nps_accum"],
            employer_nps_pm=data["employer_nps_pm"],
            self_nps_pm=data["self_nps_pm"],
            years_to_retirement=data["years_to_retirement"],
        )
        return success_response(
            {
                "final_corpus_display": fmt_display(final_corpus),
                "final_corpus_raw": abs(final_corpus),
            }
        )
