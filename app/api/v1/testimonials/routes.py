from datetime import datetime, timezone

from flask_restx import Namespace, Resource, fields

from app.models.testimonial import Testimonial
from app.services.testimonial_service import MAX_VISIBLE_TESTIMONIALS, serialize_testimonial

ns = Namespace(
    "testimonials",
    description="Public testimonials for the client website.",
    path="/testimonials",
)

testimonial_public_model = ns.model(
    "PublicTestimonial",
    {
        "id": fields.String(required=True, example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
        "client_name": fields.String(required=True, example="Aaditya Patel"),
        "review_message": fields.String(
            required=True,
            example="The automated assessment builder helped me plan retirement.",
        ),
        "avatar_url": fields.String(
            required=False,
            example="https://cdn.example.com/avatars/aaditya.jpg",
        ),
        "sort_order": fields.Integer(required=True, example=1),
    },
)

public_response_model = ns.model(
    "PublicTestimonialsResponse",
    {
        "status": fields.String(required=True, example="success"),
        "data": fields.List(fields.Nested(testimonial_public_model)),
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
class PublicTestimonials(Resource):
    @ns.doc(
        description=(
            "Returns up to 3 visible testimonials for the public website. "
            "No API key required."
        ),
    )
    @ns.response(200, "Success", public_response_model)
    def get(self):
        """List visible testimonials for the website (max 3)."""
        rows = (
            Testimonial.query.filter_by(is_visible=True)
            .order_by(Testimonial.sort_order.asc(), Testimonial.created_at.asc())
            .limit(MAX_VISIBLE_TESTIMONIALS)
            .all()
        )
        return success_response([serialize_testimonial(row) for row in rows])
