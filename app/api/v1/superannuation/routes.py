from datetime import datetime, timezone

from flask import request
from flask_restx import Namespace, Resource, fields

from app.core.formatters import fmt_display
from app.core.formulas import sa_table
from app.core.swagger_models import error_model
from app.middleware.auth import require_api_key

ns = Namespace(
    "superannuation",
    description="Superannuation (SA) accumulation",
    path="/superannuation",
)

sa_input = ns.model(
    "SAInput",
    {
        "current_sa_accum": fields.Float(
            required=True,
            description="Current SA balance (₹)",
            example=700000,
        ),
        "sa_pm": fields.Float(
            required=True,
            description="Monthly SA contribution (₹)",
            example=6000,
        ),
        "years_to_retirement": fields.Integer(
            required=True,
            description="Years to retirement",
            example=14,
        ),
    },
)

success_envelope_model = ns.model("SASuccessEnvelope", {
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
class SAAccumulation(Resource):
    @require_api_key
    @ns.doc(security="apikey")
    @ns.expect(sa_input, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        """Year-by-year Superannuation accumulation table with 5% annual contribution growth."""
        data = get_payload()
        rows, final_corpus = sa_table(
            current_sa_accum=data["current_sa_accum"],
            sa_pm=data["sa_pm"],
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
class SACorpus(Resource):
    @require_api_key
    @ns.doc(security="apikey")
    @ns.expect(sa_input, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        """Final Superannuation corpus at retirement only."""
        data = get_payload()
        _, final_corpus = sa_table(
            current_sa_accum=data["current_sa_accum"],
            sa_pm=data["sa_pm"],
            years_to_retirement=data["years_to_retirement"],
        )
        return success_response(
            {
                "final_corpus_display": fmt_display(final_corpus),
                "final_corpus_raw": abs(final_corpus),
            }
        )
