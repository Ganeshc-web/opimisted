from flask import g, request
from flask_restx import Namespace, Resource
from datetime import datetime
from marshmallow import ValidationError

from app import db
from app.models.rate_config import RateConfig, RateHistory
from app.middleware.auth import require_api_key, require_admin
from app.core.validators import RateUpdateSchema
from app.core.exceptions import APIError

ns = Namespace("rates", description="Rate configuration", path="/rates")


@ns.route("/")
class Rates(Resource):

    @require_api_key
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
                "updated_at":     config.updated_at.isoformat(),
                "updated_by":     config.updated_by,
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    @require_admin
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
                    changed_at=datetime.utcnow(),
                    changed_by=str(g.api_key.client_name)
                )
                db.session.add(history)
                setattr(config, field, new_val)

        config.updated_at = datetime.utcnow()
        config.updated_by = str(g.api_key.client_name)
        db.session.commit()

        return {
            "status": "updated",
            "data": {
                "inflation_post": config.inflation_post,
                "roi_post":       config.roi_post,
                "inflation_pre":  config.inflation_pre,
                "roi_pre":        config.roi_pre,
                "updated_at":     config.updated_at.isoformat(),
            },
            "timestamp": datetime.utcnow().isoformat()
        }


@ns.route("/history")
class RatesHistory(Resource):

    @require_admin
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
            "timestamp": datetime.utcnow().isoformat()
        }
