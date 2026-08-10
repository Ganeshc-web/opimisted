from datetime import datetime, timezone
from uuid import UUID

from flask import request
from flask_restx import Namespace, Resource, fields

from app import cache, db
from app.core.education_display import program_display_name
from app.core.exceptions import APIError
from app.core.formatters import fmt_response
from app.core.formulas import BEGIN, current_year, excel_FV, excel_PMT, monthly_effective_rate
from app.core.swagger_models import error_model
from app.middleware.auth import require_api_key
from app.models.education_db import EducationProgram
from app.models.rate_config import RateConfig

ns = Namespace(
    "education",
    description=(
        "Bidirectional lookup between education programs and costs. "
        "Search by course/country to get cost, search by budget to get "
        "matching programs, or project future education costs."
    ),
    path="/education",
)

education_query_model = ns.parser()
education_query_model.add_argument(
    "level",
    choices=("Graduation", "Post Graduation"),
    location="args",
    required=True,
    help="Graduation or Post Graduation",
)
education_query_model.add_argument("course_category", location="args", required=True)
education_query_model.add_argument("country", location="args", required=True)

budget_query_model = ns.parser()
budget_query_model.add_argument(
    "budget", type=float, location="args", required=True, help="Budget in INR"
)
budget_query_model.add_argument(
    "tolerance_percent",
    type=float,
    location="args",
    required=False,
    default=50,
    help="Allowed budget variance percentage",
)
budget_query_model.add_argument("page", type=int, location="args", default=1)
budget_query_model.add_argument("per_page", type=int, location="args", default=20)

project_cost_model = ns.model(
    "ProjectCostInput",
    {
        "program_id": fields.String(
            required=True,
            description="EducationProgram UUID returned by lookup endpoints.",
            example="f47ac10b-58cc-4372-a567-0e02b2c3d479",
        ),
        "target_year": fields.Integer(
            required=True,
            description="Future year when the education expense is expected.",
            example=2035,
        ),
    },
)

education_program_model = ns.model("EducationProgramResponse", {
    "id": fields.String(
        required=True,
        description="Education program UUID.",
        example="f47ac10b-58cc-4372-a567-0e02b2c3d479",
    ),
    "level": fields.String(
        required=True,
        description="Education level.",
        example="Post Graduation",
    ),
    "course_category": fields.String(
        required=True,
        description="Course category.",
        example="MBA",
    ),
    "country": fields.String(
        required=True,
        description="Country where the program is pursued.",
        example="USA",
    ),
    "institution_name": fields.String(
        required=False,
        description="Optional college name if provided in catalog (usually empty).",
        example=None,
    ),
    "display_name": fields.String(
        required=False,
        description="Name shown in UI/reports: course category + country.",
        example="Engineering, India",
    ),
    "country_famous_for": fields.String(
        required=False,
        description="Why the destination is popular for this program.",
        example="Top Business Schools",
    ),
    "approx_cost_inr": fields.Float(
        required=True,
        description="Approximate current cost in INR.",
        example=18000000,
    ),
    "duration": fields.String(
        required=False,
        description="Suggested program duration.",
        example="2 Years",
    ),
    "category": fields.String(
        required=False,
        description="Cost tier.",
        example="Premium",
    ),
    "living_cost_included": fields.Boolean(
        required=False,
        description="Whether living costs are included in approximate cost.",
        example=True,
    ),
    "lifestyle_level": fields.String(
        required=False,
        description="Lifestyle/career positioning label.",
        example="Global Corporate Exposure",
    ),
    "inflation_rate": fields.Float(
        required=True,
        description="Education inflation rate as a decimal.",
        example=0.08,
    ),
})

education_list_response_model = ns.model("EducationListResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.List(
        fields.Nested(education_program_model),
        required=True,
        description="Matching education programs.",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})

education_page_model = ns.model("EducationPaginatedData", {
    "items": fields.List(
        fields.Nested(education_program_model),
        required=True,
        description="Current page of matching education programs.",
    ),
    "total": fields.Integer(required=True, description="Total matching rows.", example=12),
    "total_pages": fields.Integer(required=True, description="Total pages available.", example=1),
    "page": fields.Integer(required=True, description="Current page number.", example=1),
    "per_page": fields.Integer(required=True, description="Rows per page.", example=20),
})

education_paginated_response_model = ns.model("EducationPaginatedResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Nested(
        education_page_model,
        required=True,
        description="Paginated education budget results.",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})

education_categories_data_model = ns.model("EducationCategoriesData", {
    "levels": fields.List(fields.String, required=True, description="Available education levels.", example=["Graduation", "Post Graduation"]),
    "course_categories": fields.List(fields.String, required=True, description="Available course categories.", example=["MBA", "Engineering"]),
    "countries": fields.List(fields.String, required=True, description="Available countries.", example=["India", "USA"]),
    "categories": fields.List(fields.String, required=True, description="Available cost tiers.", example=["Moderate", "Premium"]),
})

education_categories_response_model = ns.model("EducationCategoriesResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Nested(
        education_categories_data_model,
        required=True,
        description="Dropdown values for education search.",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})

money_model = ns.model("MoneyValue", {
    "display": fields.Float(required=True, description="Rounded value for display.", example=35982083.29),
    "raw": fields.Float(required=True, description="Full precision numeric value.", example=35982083.2878798),
    "inr": fields.String(required=True, description="Human-readable INR value.", example="₹3.60 Cr"),
})

education_projection_data_model = ns.model("EducationProjectionData", {
    "program_id": fields.String(required=True, description="Education program UUID.", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    "today_cost": fields.Nested(money_model, required=True, description="Current program cost."),
    "future_cost": fields.Nested(money_model, required=True, description="Inflation-adjusted future cost."),
    "years_from_now": fields.Integer(required=True, description="Years until target year.", example=9),
    "monthly_sip": fields.Nested(money_model, required=True, description="Required monthly SIP."),
})

education_projection_response_model = ns.model("EducationProjectionResponse", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Nested(education_projection_data_model, required=True, description="Projected education cost details."),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def serialize_program(program):
    return {
        "id": str(program.id),
        "level": program.level,
        "course_category": program.course_category,
        "country": program.country,
        "institution_name": program.institution_name,
        "display_name": program_display_name(program),
        "country_famous_for": program.country_famous_for,
        "approx_cost_inr": program.approx_cost_inr,
        "duration": program.duration,
        "category": program.category,
        "living_cost_included": program.living_cost_included,
        "lifestyle_level": program.lifestyle_level,
        "inflation_rate": program.inflation_rate,
    }


def get_monthly_eff_pre():
    config = RateConfig.query.first()
    roi_pre = config.roi_pre if config else 0.12
    return monthly_effective_rate(roi_pre)


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


def _pagination_args(default_per_page=20, max_per_page=100):
    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    per_page = min(
        max(request.args.get("per_page", default=default_per_page, type=int) or default_per_page, 1),
        max_per_page,
    )
    return page, per_page


def _paginated_programs(query, page, per_page):
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return success_response(
        {
            "items": [serialize_program(row) for row in pagination.items],
            "total": pagination.total,
            "total_pages": pagination.pages,
            "page": pagination.page,
            "per_page": pagination.per_page,
        }
    )


def _programs_for_budget(budget, tolerance_percent, page=1, per_page=20):
    lower = budget * (1 - tolerance_percent / 100)
    upper = budget * (1 + tolerance_percent / 100)

    query = EducationProgram.query.filter(
        EducationProgram.approx_cost_inr >= lower,
        EducationProgram.approx_cost_inr <= upper,
    )

    pagination = (
        query.order_by(db.func.abs(EducationProgram.approx_cost_inr - budget))
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    # If nothing sits in the band, return nearest programs by cost.
    if pagination.total == 0:
        pagination = (
            EducationProgram.query.order_by(
                db.func.abs(EducationProgram.approx_cost_inr - budget)
            ).paginate(page=page, per_page=per_page, error_out=False)
        )

    return success_response(
        {
            "items": [serialize_program(program) for program in pagination.items],
            "total": pagination.total,
            "total_pages": pagination.pages,
            "page": pagination.page,
            "per_page": pagination.per_page,
        }
    )


@ns.route("/cost")
class EducationCost(Resource):
    @require_api_key
    @ns.expect(education_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Forward lookup from education level, course category, and country "
            "to current cost metadata. Use this when the user already knows "
            "which program destination they want to evaluate."
        ),
    )
    @ns.param("level", "Education level.", type=str, required=True, _in="query", example="Post Graduation")
    @ns.param("course_category", "Course category to search.", type=str, required=True, _in="query", example="MBA")
    @ns.param("country", "Destination country.", type=str, required=True, _in="query", example="USA")
    @ns.response(200, "Success", education_list_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find education costs by level, course category, and country."""
        args = education_query_model.parse_args()
        programs = EducationProgram.query.filter_by(
            level=args["level"],
            course_category=args["course_category"],
            country=args["country"],
        ).all()

        return success_response(
            [
                {
                    "id": str(program.id),
                    "level": program.level,
                    "course_category": program.course_category,
                    "country": program.country,
                    "approx_cost_inr": program.approx_cost_inr,
                    "duration": program.duration,
                    "category": program.category,
                    "inflation_rate": program.inflation_rate,
                }
                for program in programs
            ]
        )


@ns.route("/bulk-cost")
class EducationBulkCost(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Bulk fetch cost metadata for up to 50 education program IDs in "
            "one request. The response preserves the order of requested IDs."
        ),
    )
    @ns.param("program_ids", "Comma-separated EducationProgram UUIDs; maximum 50.", type=str, required=True, _in="query", example="uuid1,uuid2,uuid3")
    @ns.response(200, "Success", education_list_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def get(self):
        """Find education costs for multiple program IDs."""
        program_ids = parse_bulk_ids(
            request.args.get("program_ids"), 50, "program_ids"
        )
        programs = EducationProgram.query.filter(
            EducationProgram.id.in_(program_ids)
        ).all()
        programs_by_id = {program.id: program for program in programs}

        for index, program_id in enumerate(program_ids):
            if program_id not in programs_by_id:
                raise APIError(
                    "NOT_FOUND",
                    f"Item {index} failed validation: education program not found",
                    field="program_ids",
                    http_status=404,
                )

        return success_response(
            [serialize_program(programs_by_id[program_id]) for program_id in program_ids]
        )


@ns.route("/options-for-budget")
class EducationOptionsForBudget(Resource):
    @require_api_key
    @ns.expect(budget_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Lookup by budget (alias of /education/budget). Returns matching "
            "course/country options within tolerance, or nearest options if "
            "the band is empty."
        ),
    )
    @ns.param("budget", "Target budget in INR.", type=float, required=True, _in="query", example=9000000)
    @ns.param("tolerance_percent", "Acceptable variance percentage.", type=float, required=False, default=50, _in="query", example=50)
    @ns.param("page", "Page number for paginated results.", type=int, required=False, default=1, _in="query", example=1)
    @ns.param("per_page", "Rows per page.", type=int, required=False, default=20, _in="query", example=20)
    @ns.response(200, "Success", education_paginated_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find education options that fit near a budget."""
        budget = request.args.get("budget", type=float)
        if budget is None or budget <= 0:
            raise APIError(
                "INVALID_INPUT",
                "budget must be a positive number.",
                field="budget",
                http_status=400,
            )

        tolerance_percent = request.args.get(
            "tolerance_percent", default=50, type=float
        )
        if tolerance_percent < 0:
            raise APIError(
                "INVALID_INPUT",
                "tolerance_percent cannot be negative.",
                field="tolerance_percent",
                http_status=400,
            )

        args = budget_query_model.parse_args()
        page = max(args.get("page") or 1, 1)
        per_page = max(args.get("per_page") or 20, 1)
        return _programs_for_budget(
            budget,
            tolerance_percent,
            page=page,
            per_page=per_page,
        )


@ns.route("/budget")
class EducationByBudget(Resource):
    @require_api_key
    @ns.expect(budget_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Lookup by budget: returns course/country options near the given "
            "budget. Same behavior as /education/options-for-budget."
        ),
    )
    @ns.param("budget", "Target budget in INR.", type=float, required=True, _in="query", example=9000000)
    @ns.param("tolerance_percent", "Acceptable variance percentage.", type=float, required=False, default=50, _in="query", example=50)
    @ns.param("page", "Page number for paginated results.", type=int, required=False, default=1, _in="query", example=1)
    @ns.param("per_page", "Rows per page.", type=int, required=False, default=20, _in="query", example=20)
    @ns.response(200, "Success", education_paginated_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find education options by budget."""
        return EducationOptionsForBudget().get()


@ns.route("/course-category")
class EducationByCourseCategory(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Lookup by course category: returns all country/cost options for "
            "that course (e.g. MBA, Engineering, MBBS)."
        ),
    )
    @ns.param("course_category", "Course category to search.", type=str, required=True, _in="query", example="MBA")
    @ns.param("page", "Page number.", type=int, required=False, default=1, _in="query", example=1)
    @ns.param("per_page", "Rows per page (max 100).", type=int, required=False, default=50, _in="query", example=50)
    @ns.response(200, "Success", education_paginated_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find education options by course category."""
        course_category = (request.args.get("course_category") or "").strip()
        if not course_category:
            raise APIError(
                "INVALID_INPUT",
                "course_category is required.",
                field="course_category",
                http_status=400,
            )

        page, per_page = _pagination_args(default_per_page=50)
        query = EducationProgram.query.filter(
            EducationProgram.course_category.ilike(course_category)
        ).order_by(
            EducationProgram.approx_cost_inr.asc(),
            EducationProgram.country.asc(),
        )
        return _paginated_programs(query, page, per_page)


@ns.route("/country")
class EducationByCountry(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Lookup by country: returns all course/cost options available "
            "in that country. Country match is case-insensitive and partial."
        ),
    )
    @ns.param("country", "Country search term.", type=str, required=True, _in="query", example="India")
    @ns.param("page", "Page number.", type=int, required=False, default=1, _in="query", example=1)
    @ns.param("per_page", "Rows per page (max 100).", type=int, required=False, default=50, _in="query", example=50)
    @ns.response(200, "Success", education_paginated_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """Find education options by country."""
        country = (request.args.get("country") or "").strip()
        if not country:
            raise APIError(
                "INVALID_INPUT",
                "country is required.",
                field="country",
                http_status=400,
            )

        page, per_page = _pagination_args(default_per_page=50)
        query = EducationProgram.query.filter(
            EducationProgram.country.ilike(f"%{country}%")
        ).order_by(
            EducationProgram.approx_cost_inr.asc(),
            EducationProgram.course_category.asc(),
        )
        return _paginated_programs(query, page, per_page)


@ns.route("/project-cost")
class EducationProjectCost(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Projects a selected education program's current cost into a "
            "future target year using the program's stored inflation rate, "
            "then computes the required monthly SIP using configured rates."
        ),
    )
    @ns.expect(project_cost_model, validate=True)
    @ns.response(200, "Success", education_projection_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self):
        """Project future education cost and required monthly SIP."""
        body = request.get_json(silent=True) or {}
        program_id = body.get("program_id")
        target_year = body.get("target_year")

        if not program_id or target_year is None:
            raise APIError(
                "INVALID_INPUT",
                "program_id and target_year are required.",
                http_status=400,
            )

        try:
            parsed_program_id = UUID(str(program_id))
            target_year = int(target_year)
        except (TypeError, ValueError):
            raise APIError(
                "INVALID_INPUT",
                "program_id must be a UUID and target_year must be an integer.",
                http_status=400,
            )

        program = db.session.get(EducationProgram, parsed_program_id)
        if not program:
            raise APIError("NOT_FOUND", "Education program not found.", http_status=404)

        years_from_now = target_year - current_year()
        if years_from_now <= 0:
            future_cost = 0.0
            monthly_sip = 0.0
        else:
            future_cost = excel_FV(
                program.inflation_rate, years_from_now, 0, -program.approx_cost_inr
            )
            monthly_sip = excel_PMT(
                get_monthly_eff_pre(), years_from_now * 12, 0, -future_cost, BEGIN
            )

        return success_response(
            {
                "program_id": str(program.id),
                "today_cost": fmt_response(program.approx_cost_inr),
                "future_cost": fmt_response(future_cost),
                "years_from_now": years_from_now,
                "monthly_sip": fmt_response(monthly_sip),
            }
        )


@ns.route("/programs")
class EducationProgramsList(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "List education programs for dropdowns. Optional course_category / "
            "country filters (level filter still accepted for catalog browsing). "
            "Prefer /course-category, /country, or /budget for the three main lookups."
        ),
    )
    @ns.param("level", "Graduation or Post Graduation.", type=str, required=False, _in="query")
    @ns.param("course_category", "Optional course category filter.", type=str, required=False, _in="query")
    @ns.param("country", "Optional case-insensitive country search.", type=str, required=False, _in="query")
    @ns.param("page", "Page number.", type=int, required=False, default=1, _in="query", example=1)
    @ns.param("per_page", "Rows per page (max 100).", type=int, required=False, default=50, _in="query", example=50)
    @ns.response(200, "Success", education_paginated_response_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def get(self):
        """List education programs."""
        page = max(request.args.get("page", default=1, type=int) or 1, 1)
        per_page = min(max(request.args.get("per_page", default=50, type=int) or 50, 1), 100)
        level = request.args.get("level")
        course_category = request.args.get("course_category")
        country = request.args.get("country")

        query = EducationProgram.query
        if level:
            query = query.filter(EducationProgram.level == level)
        if course_category:
            query = query.filter(EducationProgram.course_category == course_category)
        if country:
            query = query.filter(EducationProgram.country.ilike(f"%{country}%"))

        pagination = (
            query.order_by(
                EducationProgram.approx_cost_inr.asc(),
                EducationProgram.country.asc(),
            ).paginate(page=page, per_page=per_page, error_out=False)
        )
        return success_response(
            {
                "items": [serialize_program(row) for row in pagination.items],
                "total": pagination.total,
                "total_pages": pagination.pages,
                "page": pagination.page,
                "per_page": pagination.per_page,
            }
        )


@ns.route("/categories")
class EducationCategories(Resource):
    @cache.cached(timeout=3600, key_prefix="education:categories")
    @ns.doc(
        security=[],
        description=(
            "Public dropdown metadata for education planning screens. "
            "Returns distinct levels, course categories, countries, and "
            "cost tiers; cached for one hour because reference data changes rarely."
        ),
    )
    @ns.response(200, "Success", education_categories_response_model)
    def get(self):
        """List dropdown values for education planning."""
        levels = [
            row[0]
            for row in EducationProgram.query.with_entities(EducationProgram.level)
            .distinct()
            .order_by(EducationProgram.level)
            .all()
        ]
        course_categories = [
            row[0]
            for row in EducationProgram.query.with_entities(
                EducationProgram.course_category
            )
            .distinct()
            .order_by(EducationProgram.course_category)
            .all()
        ]
        countries = [
            row[0]
            for row in EducationProgram.query.with_entities(EducationProgram.country)
            .distinct()
            .order_by(EducationProgram.country)
            .all()
        ]
        categories = [
            row[0]
            for row in EducationProgram.query.with_entities(EducationProgram.category)
            .distinct()
            .order_by(EducationProgram.category)
            .all()
        ]

        return success_response(
            {
                "levels": levels,
                "course_categories": course_categories,
                "countries": countries,
                "categories": categories,
            }
        )
