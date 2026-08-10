from datetime import datetime, timezone

from flask_restx import Namespace, Resource, fields

from app.models.service import Service
from app.services.service_service import list_visible_services, serialize_service

ns = Namespace(
    "services",
    description="Public services catalog for the client website and PDF.",
    path="/services",
)

service_public_model = ns.model(
    "PublicService",
    {
        "id": fields.String(required=True, example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
        "title": fields.String(required=True, example="Retirement Planning"),
        "description": fields.String(
            required=True,
            example="Personalized retirement corpus and SIP planning.",
        ),
        "icon_url": fields.String(
            required=False,
            example="https://cdn.example.com/icons/retirement.svg",
        ),
        "sort_order": fields.Integer(required=True, example=1),
    },
)

public_response_model = ns.model(
    "PublicServicesResponse",
    {
        "status": fields.String(required=True, example="success"),
        "data": fields.List(fields.Nested(service_public_model)),
        "timestamp": fields.String(required=True),
    },
)


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@ns.route("/")
class PublicServices(Resource):
    @ns.doc(
        description=(
            "Returns visible services for the public website / FE PDF content. "
            "No API key required."
        ),
    )
    @ns.response(200, "Success", public_response_model)
    def get(self):
        """List visible services."""
        rows = list_visible_services()
        return success_response(
            [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "description": item["description"],
                    "icon_url": item["icon_url"],
                    "sort_order": item["sort_order"],
                }
                for item in (serialize_service(row) for row in rows)
            ]
        )
