from datetime import datetime
from uuid import UUID

from flask import request
from flask_restx import Namespace, Resource, fields

from app.core.exceptions import APIError
from app.core.formatters import fmt_response
from app.core.formulas import BEGIN, current_year, excel_FV, excel_PMT, monthly_effective_rate
from app.middleware.auth import require_api_key
from app.models.education_db import EducationProgram
from app.models.rate_config import RateConfig

ns = Namespace("education", description="Education cost planning", path="/education")

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
    "level",
    choices=("Graduation", "Post Graduation"),
    location="args",
    required=False,
)
budget_query_model.add_argument(
    "tolerance_percent",
    type=float,
    location="args",
    required=False,
    default=15,
    help="Allowed budget variance percentage",
)

project_cost_model = ns.model(
    "ProjectCostInput",
    {
        "program_id": fields.String(required=True),
        "target_year": fields.Integer(required=True, example=2035),
    },
)


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    }


def serialize_program(program):
    return {
        "id": str(program.id),
        "level": program.level,
        "course_category": program.course_category,
        "country": program.country,
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


@ns.route("/cost")
class EducationCost(Resource):
    @require_api_key
    @ns.expect(education_query_model)
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


@ns.route("/options-for-budget")
class EducationOptionsForBudget(Resource):
    @require_api_key
    @ns.expect(budget_query_model)
    def get(self):
        """Find education options that fit near a budget."""
        args = budget_query_model.parse_args()
        budget = args["budget"]
        tolerance_percent = args["tolerance_percent"] or 15

        lower = budget * (1 - tolerance_percent / 100)
        upper = budget * (1 + tolerance_percent / 100)

        query = EducationProgram.query.filter(
            EducationProgram.approx_cost_inr >= lower,
            EducationProgram.approx_cost_inr <= upper,
        )
        if args.get("level"):
            query = query.filter(EducationProgram.level == args["level"])

        programs = query.all()
        programs.sort(key=lambda program: abs(program.approx_cost_inr - budget))

        return success_response([serialize_program(program) for program in programs])


@ns.route("/project-cost")
class EducationProjectCost(Resource):
    @require_api_key
    @ns.expect(project_cost_model)
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

        program = EducationProgram.query.get(parsed_program_id)
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


@ns.route("/categories")
class EducationCategories(Resource):
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
