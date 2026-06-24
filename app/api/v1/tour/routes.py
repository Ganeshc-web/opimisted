from datetime import datetime
from uuid import UUID

from flask import request
from flask_restx import Namespace, Resource, fields

from app.core.exceptions import APIError
from app.core.formatters import fmt_response
from app.core.formulas import BEGIN, current_year, excel_FV, excel_PMT, monthly_effective_rate
from app.middleware.auth import require_api_key
from app.models.rate_config import RateConfig
from app.models.tour_db import TourDestination

ns = Namespace("tour", description="Foreign tour planning", path="/tour")

budget_lookup_model = ns.parser()
budget_lookup_model.add_argument(
    "country",
    location="args",
    required=True,
    help="Case-insensitive partial country match",
)

destinations_budget_model = ns.parser()
destinations_budget_model.add_argument(
    "budget", type=float, location="args", required=True, help="Budget in INR"
)
destinations_budget_model.add_argument("category", location="args", required=False)
destinations_budget_model.add_argument(
    "tolerance_percent",
    type=float,
    location="args",
    required=False,
    default=15,
    help="Allowed budget variance percentage",
)

project_cost_model = ns.model(
    "TourProjectCostInput",
    {
        "destination_id": fields.String(required=True),
        "target_year": fields.Integer(required=True, example=2030),
        "travellers": fields.Integer(required=False, default=1, example=2),
    },
)

tour_destination_model = ns.model(
    "TourDestination",
    {
        "id": fields.String,
        "country": fields.String,
        "budget_inr": fields.Float,
        "duration": fields.String,
        "category": fields.String,
    },
)

tour_categories_model = ns.model(
    "TourCategories",
    {
        "categories": fields.List(fields.String),
    },
)


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    }


def serialize_destination(destination):
    return {
        "id": str(destination.id),
        "country": destination.country,
        "budget_inr": destination.budget_inr,
        "duration": destination.duration,
        "category": destination.category,
    }


def get_rates():
    config = RateConfig.query.first()
    if config:
        return {
            "inflation_pre": config.inflation_pre,
            "roi_pre": config.roi_pre,
        }
    return {
        "inflation_pre": 0.06,
        "roi_pre": 0.12,
    }


@ns.route("/budget")
class TourBudget(Resource):
    @require_api_key
    @ns.expect(budget_lookup_model)
    @ns.marshal_list_with(tour_destination_model, code=200, envelope="data")
    def get(self):
        """Find tour budget by country."""
        args = budget_lookup_model.parse_args()
        destinations = TourDestination.query.filter(
            TourDestination.country.ilike(f"%{args['country']}%")
        ).all()

        return [serialize_destination(destination) for destination in destinations]


@ns.route("/destinations-for-budget")
class TourDestinationsForBudget(Resource):
    @require_api_key
    @ns.expect(destinations_budget_model)
    @ns.marshal_list_with(tour_destination_model, code=200, envelope="data")
    def get(self):
        """Find tour destinations that fit near a budget."""
        args = destinations_budget_model.parse_args()
        budget = args["budget"]
        tolerance_percent = args["tolerance_percent"] or 15

        lower = budget * (1 - tolerance_percent / 100)
        upper = budget * (1 + tolerance_percent / 100)

        query = TourDestination.query.filter(
            TourDestination.budget_inr >= lower,
            TourDestination.budget_inr <= upper,
        )
        if args.get("category"):
            query = query.filter(TourDestination.category == args["category"])

        destinations = query.all()
        destinations.sort(
            key=lambda destination: abs(destination.budget_inr - budget)
        )

        return [serialize_destination(destination) for destination in destinations]


@ns.route("/project-cost")
class TourProjectCost(Resource):
    @require_api_key
    @ns.expect(project_cost_model)
    def post(self):
        """Project future tour cost and required monthly SIP."""
        body = request.get_json(silent=True) or {}
        destination_id = body.get("destination_id")
        target_year = body.get("target_year")
        travellers = body.get("travellers", 1)

        if not destination_id or target_year is None:
            raise APIError(
                "INVALID_INPUT",
                "destination_id and target_year are required.",
                http_status=400,
            )

        try:
            parsed_destination_id = UUID(str(destination_id))
            target_year = int(target_year)
            travellers = int(travellers)
        except (TypeError, ValueError):
            raise APIError(
                "INVALID_INPUT",
                "destination_id must be a UUID, target_year and travellers must be integers.",
                http_status=400,
            )

        if travellers < 1:
            raise APIError(
                "INVALID_INPUT",
                "travellers must be at least 1.",
                http_status=400,
            )

        destination = TourDestination.query.get(parsed_destination_id)
        if not destination:
            raise APIError("NOT_FOUND", "Tour destination not found.", http_status=404)

        rates = get_rates()
        today_cost = destination.budget_inr * travellers
        years_from_now = target_year - current_year()
        if years_from_now <= 0:
            future_cost = 0.0
            monthly_sip = 0.0
        else:
            future_cost = excel_FV(
                rates["inflation_pre"], years_from_now, 0, -today_cost
            )
            monthly_sip = excel_PMT(
                monthly_effective_rate(rates["roi_pre"]),
                years_from_now * 12,
                0,
                -future_cost,
                BEGIN,
            )

        return success_response(
            {
                "destination_id": str(destination.id),
                "today_cost": fmt_response(today_cost),
                "future_cost": fmt_response(future_cost),
                "years_from_now": years_from_now,
                "monthly_sip": fmt_response(monthly_sip),
                "travellers": travellers,
            }
        )


@ns.route("/categories")
class TourCategories(Resource):
    @ns.marshal_with(tour_categories_model, code=200, envelope="data")
    def get(self):
        """List dropdown values for tour categories."""
        categories = [
            row[0]
            for row in TourDestination.query.with_entities(TourDestination.category)
            .distinct()
            .order_by(TourDestination.category)
            .all()
        ]

        return {"categories": categories}
