from datetime import datetime, timezone
from uuid import UUID

from flask import request
from flask_restx import Namespace, Resource, fields

from app import cache, db
from app.core.exceptions import APIError
from app.core.formatters import fmt_response
from app.core.formulas import BEGIN, current_year, excel_FV, excel_PMT, monthly_effective_rate
from app.core.swagger_models import error_model
from app.middleware.auth import require_api_key
from app.models.rate_config import RateConfig
from app.models.tour_db import TourDestination

ns = Namespace(
    "tour",
    description=(
        "Bidirectional lookup between foreign tour destinations and budgets. "
        "Search by country to get estimated budget, search by budget to get "
        "matching destinations, or project future tour costs."
    ),
    path="/tour",
)

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
destinations_budget_model.add_argument("page", type=int, location="args", default=1)
destinations_budget_model.add_argument("per_page", type=int, location="args", default=20)

project_cost_model = ns.model(
    "TourProjectCostInput",
    {
        "destination_id": fields.String(
            required=True,
            description="TourDestination UUID returned by lookup endpoints.",
            example="f47ac10b-58cc-4372-a567-0e02b2c3d479",
        ),
        "target_year": fields.Integer(
            required=True,
            description="Future year when the tour is planned.",
            example=2030,
        ),
        "travellers": fields.Integer(
            required=False,
            description="Number of travellers sharing this trip budget.",
            default=1,
            example=2,
        ),
    },
)

tour_destination_model = ns.model(
    "TourDestination",
    {
        "id": fields.String(
            required=True,
            description="Tour destination UUID.",
            example="f47ac10b-58cc-4372-a567-0e02b2c3d479",
        ),
        "country": fields.String(
            required=True,
            description="Destination country.",
            example="Japan",
        ),
        "budget_inr": fields.Float(
            required=True,
            description="Approximate current trip budget in INR.",
            example=380000,
        ),
        "duration": fields.String(
            required=False,
            description="Suggested trip duration.",
            example="7-10 Days",
        ),
        "category": fields.String(
            required=False,
            description="Destination category.",
            example="Premium Experience",
        ),
    },
)

tour_list_response_model = ns.model("TourListResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.List(
        fields.Nested(tour_destination_model),
        required=True,
        description="Matching tour destinations.",
    ),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})

tour_page_model = ns.model("TourPaginatedData", {
    "items": fields.List(fields.Nested(tour_destination_model), required=True, description="Current page of matching destinations."),
    "total": fields.Integer(required=True, description="Total matching rows.", example=4),
    "total_pages": fields.Integer(required=True, description="Total pages available.", example=1),
    "page": fields.Integer(required=True, description="Current page number.", example=1),
    "per_page": fields.Integer(required=True, description="Rows per page.", example=20),
})

tour_paginated_response_model = ns.model("TourPaginatedResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Nested(tour_page_model, required=True, description="Paginated tour budget results."),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})

money_model = ns.model("TourMoneyValue", {
    "display": fields.Float(required=True, description="Rounded value for display.", example=959482.49),
    "raw": fields.Float(required=True, description="Full precision numeric value.", example=959482.4896),
    "inr": fields.String(required=True, description="Human-readable INR value.", example="₹9.59 L"),
})

tour_projection_data_model = ns.model("TourProjectionData", {
    "destination_id": fields.String(required=True, description="Tour destination UUID.", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    "today_cost": fields.Nested(money_model, required=True, description="Current trip cost after traveller multiplier."),
    "future_cost": fields.Nested(money_model, required=True, description="Inflation-adjusted future trip cost."),
    "years_from_now": fields.Integer(required=True, description="Years until target year.", example=4),
    "monthly_sip": fields.Nested(money_model, required=True, description="Required monthly SIP."),
    "travellers": fields.Integer(required=True, description="Traveller count used in calculation.", example=2),
})

tour_projection_response_model = ns.model("TourProjectionResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Nested(tour_projection_data_model, required=True, description="Projected tour cost details."),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})

tour_categories_model = ns.model(
    "TourCategories",
    {
        "categories": fields.List(
            fields.String,
            required=True,
            description="Distinct destination categories.",
            example=["Budget Friendly", "Premium Experience"],
        ),
    },
)


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


def parse_bulk_ids(raw_ids, max_items, label):
    if not raw_ids:
        raise APIError(
            "INVALID_INPUT",
            f"{label} query parameter is required.",
            field=label,
            http_status=400,
        )

    id_values = [value.strip() for value in raw_ids.split(",") if value.strip()]
    if len(id_values) > max_items:
        raise APIError(
            "INVALID_INPUT",
            f"Maximum {max_items} items per bulk request",
            field=label,
            http_status=400,
        )

    parsed_ids = []
    for index, value in enumerate(id_values):
        try:
            parsed_ids.append(UUID(value))
        except (TypeError, ValueError):
            raise APIError(
                "INVALID_INPUT",
                f"Item {index} failed validation: invalid UUID",
                field=label,
                http_status=400,
            )

    return parsed_ids


@ns.route("/budget")
class TourBudget(Resource):
    @require_api_key
    @ns.expect(budget_lookup_model)
    @ns.marshal_list_with(tour_destination_model, code=200, envelope="data")
    @ns.doc(
        security="apikey",
        description=(
            "Forward lookup from a country search term to matching tour "
            "destination budgets. Country matching is case-insensitive and partial."
        ),
    )
    @ns.param("country", "Case-insensitive country search term.", type=str, required=True, _in="query", example="Japan")
    @ns.response(200, "Success", tour_destination_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find tour budget by country."""
        args = budget_lookup_model.parse_args()
        destinations = TourDestination.query.filter(
            TourDestination.country.ilike(f"%{args['country']}%")
        ).all()

        return [serialize_destination(destination) for destination in destinations]


@ns.route("/bulk-budget")
class TourBulkBudget(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Bulk fetch budget metadata for up to 50 tour destination IDs "
            "in one request. The response preserves the order of requested IDs."
        ),
    )
    @ns.param("destination_ids", "Comma-separated TourDestination UUIDs; maximum 50.", type=str, required=True, _in="query", example="uuid1,uuid2,uuid3")
    @ns.response(200, "Success", tour_list_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def get(self):
        """Find tour budgets for multiple destination IDs."""
        destination_ids = parse_bulk_ids(
            request.args.get("destination_ids"), 50, "destination_ids"
        )
        destinations = TourDestination.query.filter(
            TourDestination.id.in_(destination_ids)
        ).all()
        destinations_by_id = {
            destination.id: destination for destination in destinations
        }

        for index, destination_id in enumerate(destination_ids):
            if destination_id not in destinations_by_id:
                raise APIError(
                    "NOT_FOUND",
                    f"Item {index} failed validation: tour destination not found",
                    field="destination_ids",
                    http_status=404,
                )

        return success_response(
            [
                serialize_destination(destinations_by_id[destination_id])
                for destination_id in destination_ids
            ]
        )


@ns.route("/destinations-for-budget")
class TourDestinationsForBudget(Resource):
    @require_api_key
    @ns.expect(destinations_budget_model)
    @ns.doc(
        security="apikey",
        description=(
            "Reverse lookup from a target tour budget to matching countries. "
            "Results are constrained by tolerance percentage and sorted by "
            "closest budget match first."
        ),
    )
    @ns.param("budget", "Target budget in INR.", type=float, required=True, _in="query", example=150000)
    @ns.param("category", "Optional destination category filter.", type=str, required=False, _in="query", example="Budget Friendly")
    @ns.param("tolerance_percent", "Acceptable variance percentage.", type=float, required=False, default=15, _in="query", example=15)
    @ns.param("page", "Page number for paginated results.", type=int, required=False, default=1, _in="query", example=1)
    @ns.param("per_page", "Rows per page.", type=int, required=False, default=20, _in="query", example=20)
    @ns.response(200, "Success", tour_paginated_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find tour destinations that fit near a budget."""
        budget = request.args.get("budget", type=float)
        if budget is None or budget <= 0:
            raise APIError(
                "INVALID_INPUT",
                "budget must be a positive number.",
                field="budget",
                http_status=400,
            )

        tolerance_percent = request.args.get(
            "tolerance_percent", default=15, type=float
        )
        if tolerance_percent < 0:
            raise APIError(
                "INVALID_INPUT",
                "tolerance_percent cannot be negative.",
                field="tolerance_percent",
                http_status=400,
            )

        args = destinations_budget_model.parse_args()
        page = max(args.get("page") or 1, 1)
        per_page = max(args.get("per_page") or 20, 1)

        lower = budget * (1 - tolerance_percent / 100)
        upper = budget * (1 + tolerance_percent / 100)

        query = TourDestination.query.filter(
            TourDestination.budget_inr >= lower,
            TourDestination.budget_inr <= upper,
        )
        if args.get("category"):
            query = query.filter(TourDestination.category == args["category"])

        pagination = (
            query.order_by(db.func.abs(TourDestination.budget_inr - budget))
            .paginate(page=page, per_page=per_page, error_out=False)
        )

        return success_response(
            {
                "items": [
                    serialize_destination(destination)
                    for destination in pagination.items
                ],
                "total": pagination.total,
                "total_pages": pagination.pages,
                "page": pagination.page,
                "per_page": pagination.per_page,
            }
        )


@ns.route("/project-cost")
class TourProjectCost(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Projects a selected tour destination budget into a future "
            "target year, multiplying current budget by traveller count and "
            "using configured pre-retirement inflation for projections."
        ),
    )
    @ns.expect(project_cost_model, validate=True)
    @ns.response(200, "Success", tour_projection_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
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

        destination = db.session.get(TourDestination, parsed_destination_id)
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
    @cache.cached(timeout=3600, key_prefix="tour:categories")
    @ns.marshal_with(tour_categories_model, code=200, envelope="data")
    @ns.doc(
        security=[],
        description=(
            "Public dropdown metadata for tour planning screens. Returns "
            "distinct destination category values and is cached for one hour."
        ),
    )
    @ns.response(200, "Success", tour_categories_model)
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
