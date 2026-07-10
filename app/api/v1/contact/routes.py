from datetime import datetime, timezone

from flask import request
from flask_restx import Namespace, Resource, fields
from marshmallow import ValidationError

from app import db
from app.core.exceptions import APIError
from app.core.swagger_models import error_model
from app.core.validators import GetInTouchSchema
from app.models.get_in_touch import GetInTouchLead

ns = Namespace(
    "contact",
    description="Public contact endpoints for website lead capture.",
    path="/contact",
)

get_in_touch_input_model = ns.model("GetInTouchInput", {
    "name": fields.String(
        required=True,
        description="Contact full name.",
        example="Rajesh Malhotra",
    ),
    "email": fields.String(
        required=True,
        description="Contact email address.",
        example="rajesh@example.com",
    ),
    "mobile": fields.String(
        required=True,
        description="Contact mobile number, digits only.",
        example="9876543210",
    ),
    "message": fields.String(
        required=False,
        description="Optional message from the contact form.",
        example="I would like to know more about retirement planning.",
    ),
})

success_envelope_model = ns.model("ContactSuccessEnvelope", {
    "status": fields.String(required=True, example="success"),
    "data": fields.Raw(required=True),
    "timestamp": fields.String(required=True, example="2026-07-01T10:00:00+00:00"),
})


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def load_get_in_touch_schema(payload):
    try:
        return GetInTouchSchema().load(payload or {})
    except ValidationError as err:
        field = next(iter(err.messages), None)
        raise APIError(
            "INVALID_INPUT",
            str(err.messages),
            field=field,
            http_status=400,
        )


@ns.route("/get-in-touch")
class GetInTouch(Resource):
    @ns.doc(
        description=(
            "Saves a Get in Touch form submission as a lead. No API key "
            "required — intended for the public website contact form."
        ),
    )
    @ns.expect(get_in_touch_input_model, validate=True)
    @ns.response(201, "Lead created", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    def post(self):
        """Save Get in Touch form submission as a lead."""
        payload = load_get_in_touch_schema(request.get_json(silent=True) or {})

        lead = GetInTouchLead(
            name=payload["name"].strip(),
            email=payload["email"].strip().lower(),
            mobile=payload["mobile"],
            message=payload.get("message"),
        )
        db.session.add(lead)
        db.session.commit()

        return success_response(
            {
                "lead_id": str(lead.id),
                "name": lead.name,
                "email": lead.email,
                "mobile": lead.mobile,
                "message": lead.message,
                "submitted_at": lead.submitted_at.isoformat(),
            }
        ), 201
