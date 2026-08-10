from flask import g, request
from flask_restx import Namespace, Resource, fields
from datetime import datetime, timezone
from marshmallow import ValidationError

from app import cache, db
from app.models.rate_config import RateConfig, RateHistory
from app.middleware.auth import require_api_key, require_admin
from app.core.validators import RateUpdateSchema
from app.core.exceptions import APIError
from app.core.swagger_models import error_model

ns = Namespace(
    "rates",
    description=(
        "Inflation and return-rate configuration used by retirement, "
        "goal, education, and tour projections. User keys can read rates; "
        "admin keys can update rates and inspect history."
    ),
    path="/rates",
)

rate_data_model = ns.model("RateData", {
    "inflation_post": fields.Float(
        required=True,
        description="Post-retirement annual inflation rate as a decimal.",
        example=0.06,
    ),
    "roi_post": fields.Float(
        required=True,
        description="Post-retirement annual return rate as a decimal.",
        example=0.08,
    ),
    "inflation_pre": fields.Float(
        required=True,
        description="Pre-retirement annual inflation rate as a decimal.",
        example=0.06,
    ),
    "roi_pre": fields.Float(
        required=True,
        description="Pre-retirement annual return rate as a decimal.",
        example=0.12,
    ),
    "pf_growth": fields.Float(
        required=True,
        description="Yearly growth in PF/NPS/SA contribution as a decimal (e.g. 0.05 = 5%).",
        example=0.05,
    ),
    "updated_at": fields.String(
        required=True,
        description="UTC timestamp when rates were last changed.",
        example="2026-06-27T13:30:00+00:00",
    ),
    "updated_by": fields.String(
        required=False,
        description="Client/admin name that last updated the rates.",
        example="Admin",
    ),
})

rates_response_model = ns.model("RatesResponse", {
    "status": fields.String(
        required=True,
        description="Response status.",
        example="success",
    ),
    "data": fields.Nested(
        rate_data_model,
        required=True,
        description="Current configured planning rates.",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})

rate_update_model = ns.model("RateUpdateInput", {
    "inflation_post": fields.Float(
        required=False,
        description="New post-retirement inflation rate as a decimal.",
        example=0.06,
    ),
    "roi_post": fields.Float(
        required=False,
        description="New post-retirement return rate as a decimal.",
        example=0.08,
    ),
    "inflation_pre": fields.Float(
        required=False,
        description="New pre-retirement inflation rate as a decimal.",
        example=0.06,
    ),
    "roi_pre": fields.Float(
        required=False,
        description="New pre-retirement return rate as a decimal.",
        example=0.12,
    ),
    "pf_growth": fields.Float(
        required=False,
        description="Yearly PF contribution growth rate as a decimal.",
        example=0.05,
    ),
})

rate_history_item_model = ns.model("RateHistoryItem", {
    "field": fields.String(
        required=True,
        description="Rate field that changed.",
        example="roi_pre",
    ),
    "old_value": fields.Float(
        required=True,
        description="Previous value before update.",
        example=0.11,
    ),
    "new_value": fields.Float(
        required=True,
        description="New configured value.",
        example=0.12,
    ),
    "changed_at": fields.String(
        required=True,
        description="UTC timestamp when the change was made.",
        example="2026-06-27T13:30:00+00:00",
    ),
    "changed_by": fields.String(
        required=True,
        description="Admin client name responsible for the change.",
        example="Admin",
    ),
})

rate_history_response_model = ns.model("RateHistoryResponse", {
    "status": fields.String(
        required=True,
        description="Response status.",
        example="success",
    ),
    "data": fields.List(
        fields.Nested(rate_history_item_model),
        required=True,
        description="Chronological audit entries for rate changes.",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})


@ns.route("/")
class Rates(Resource):

    @require_api_key
    @cache.cached(timeout=3600, key_prefix="rates:get")
    @ns.doc(
        security="apikey",
        description=(
            "Returns the current inflation and return assumptions used by "
            "all planning calculations. Results are cached for one hour and "
            "invalidated whenever an admin updates rates."
        ),
    )
    @ns.response(200, "Success", rates_response_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Get current inflation and ROI rates."""
        config = RateConfig.query.first()
        if not config:
            # seed defaults if table is empty
            config = RateConfig()
            db.session.add(config)
            db.session.commit()

        return {
            "status": "success",
            "data": {
                "inflation_post": config.inflation_post,
                "roi_post":       config.roi_post,
                "inflation_pre":  config.inflation_pre,
                "roi_pre":        config.roi_pre,
                "pf_growth":      config.pf_growth if config.pf_growth is not None else 0.05,
                "updated_at":     config.updated_at.isoformat(),
                "updated_by":     config.updated_by,
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Admin-only endpoint to update one or more planning rates. "
            "Each changed field is written to rate history and the cached "
            "GET /rates response is invalidated after commit."
        ),
    )
    @ns.expect(rate_update_model, validate=True)
    @ns.response(200, "Success", rates_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Insufficient permissions", error_model)
    def put(self):
        """Update one or more rates. Admin only."""
        try:
            data = RateUpdateSchema().load(request.get_json() or {})
        except ValidationError as e:
            raise APIError("INVALID_INPUT", str(e.messages), http_status=400)

        if not data:
            raise APIError("INVALID_INPUT", 
                "Provide at least one rate to update.", http_status=400)

        config = RateConfig.query.first()
        if not config:
            config = RateConfig()
            db.session.add(config)

        for field, new_val in data.items():
            old_val = getattr(config, field)
            if old_val != new_val:
                history = RateHistory(
                    field_name=field,
                    old_value=old_val,
                    new_value=new_val,
                    changed_at=datetime.now(timezone.utc),
                    changed_by=str(g.api_key.client_name)
                )
                db.session.add(history)
                setattr(config, field, new_val)

        config.updated_at = datetime.now(timezone.utc)
        config.updated_by = str(g.api_key.client_name)
        db.session.commit()
        cache.clear()

        return {
            "status": "updated",
            "data": {
                "inflation_post": config.inflation_post,
                "roi_post":       config.roi_post,
                "inflation_pre":  config.inflation_pre,
                "roi_pre":        config.roi_pre,
                "pf_growth":      config.pf_growth if config.pf_growth is not None else 0.05,
                "updated_at":     config.updated_at.isoformat(),
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@ns.route("/history")
class RatesHistory(Resource):

    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Admin-only audit endpoint returning every rate change, newest "
            "first. Use this to inspect historical configuration changes."
        ),
    )
    @ns.response(200, "Success", rate_history_response_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Insufficient permissions", error_model)
    def get(self):
        """Full audit log of every rate change. Admin only."""
        logs = RateHistory.query.order_by(
            RateHistory.changed_at.desc()
        ).all()

        return {
            "status": "success",
            "data": [
                {
                    "field":      h.field_name,
                    "old_value":  h.old_value,
                    "new_value":  h.new_value,
                    "changed_at": h.changed_at.isoformat(),
                    "changed_by": h.changed_by,
                }
                for h in logs
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
