import uuid
from datetime import date, datetime, timezone

from flask import request
from flask_restx import Namespace, Resource, fields
from marshmallow import ValidationError

from app import db
from app.core.exceptions import APIError
from app.core.formulas import current_year, goal_calc, monthly_effective_rate
from app.core.swagger_models import error_model
from app.core.validators import (
    CommunicationSchema,
    FamilySchema,
    GoalSchema,
    GoalsListSchema,
    PersonalSchema,
)
from app.middleware.auth import require_api_key
from app.services.assessment_detail_service import (
    serialize_calculation_for_assessment,
    serialize_reports_for_assessment,
)
from app.services.assessment_import_service import bulk_create_assessments_from_flow1
from app.models.assessment import AssessmentRecord
from app.models.communication import CommunicationDetails
from app.models.education_db import EducationProgram
from app.models.family import Child, FamilyDetails
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.rate_config import RateConfig
from app.models.tour_db import TourDestination

ns = Namespace(
    "assessment",
    description=(
        "Multi-step assessment intake for financial planning. Create an "
        "assessment, submit communication, personal, family, and goal details, "
        "then retrieve the full assembled assessment."
    ),
    path="/assessment",
)

success_envelope_model = ns.model("AssessmentSuccessEnvelope", {
    "status": fields.String(required=True, description="Response status.", example="success"),
    "data": fields.Raw(required=True, description="Endpoint-specific response payload.", example={"assessment_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"}),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})

communication_input_model = ns.model("CommunicationInput", {
    "mobile": fields.String(required=True, description="Primary mobile number, digits only.", example="9876543210"),
    "email": fields.String(required=True, description="Primary email address.", example="client@example.com"),
    "spouse_mobile": fields.String(required=False, description="Optional spouse mobile number.", example="9876543211"),
    "spouse_email": fields.String(required=False, description="Optional spouse email address.", example="spouse@example.com"),
    "residential_address": fields.String(required=False, description="Residential mailing address.", example="123 Main St, Mumbai"),
    "consent": fields.Boolean(required=True, description="Whether the client consented to data processing.", example=True),
})

bulk_assessment_input_model = ns.model("BulkAssessmentInput", {
    "assessments": fields.List(
        fields.Nested(communication_input_model),
        required=True,
        description="Communication payloads to create as new assessments; maximum 100.",
        example=[
            {
                "mobile": "9876543210",
                "email": "client@example.com",
                "spouse_mobile": "9876543211",
                "spouse_email": "spouse@example.com",
                "residential_address": "123 Main St, Mumbai",
                "consent": True,
            }
        ],
    ),
})

personal_input_model = ns.model("PersonalInput", {
    "client_name": fields.String(required=True, description="Client full name.", example="Yogesh Taori"),
    "client_occupation": fields.String(required=True, description="Client occupation.", example="Engineer"),
    "client_designation": fields.String(required=True, description="Client designation.", example="Manager"),
    "client_company": fields.String(required=True, description="Client employer/company.", example="Tech Corp"),
    "client_dob": fields.String(required=True, description="Client date of birth in DD/MM/YYYY format.", example="01/01/1990"),
    "client_retirement_age": fields.Integer(required=False, description="Client target retirement age.", example=60),
    "spouse_name": fields.String(required=False, description="Spouse full name.", example="Spouse Name"),
    "spouse_occupation": fields.String(required=False, description="Spouse occupation.", example="Teacher"),
    "spouse_designation": fields.String(required=False, description="Spouse designation.", example="Senior Teacher"),
    "spouse_company": fields.String(required=False, description="Spouse employer/company.", example="School"),
    "spouse_dob": fields.String(required=False, description="Spouse date of birth in DD/MM/YYYY format.", example="01/01/1995"),
    "spouse_retirement_age": fields.Integer(required=False, description="Spouse target retirement age.", example=55),
})

child_input_model = ns.model("ChildInput", {
    "child_number": fields.Integer(required=True, description="Child sequence number.", example=1),
    "child_name": fields.String(required=False, description="Child display name (saved to DB). Prefer this over full_name.", example="Aarav"),
    "full_name": fields.String(required=False, description="Legacy alias for child_name.", example="Aarav"),
    "occupation": fields.String(required=False, description="Child occupation or student status.", example="Student"),
    "financially_dependent": fields.Boolean(required=False, description="Whether the child is financially dependent.", example=True),
    "date_of_birth": fields.String(required=False, description="Child date of birth in DD/MM/YYYY format.", example="01/06/2010"),
})

family_input_model = ns.model("FamilyInput", {
    "number_of_children": fields.Integer(
        required=True,
        description="Total number of children (0 or more). Must equal length of children array.",
        example=2,
    ),
    "children": fields.List(
        fields.Nested(child_input_model),
        required=False,
        description="Child detail rows; length must match number_of_children.",
        example=[
            {
                "child_number": 1,
                "child_name": "Aarav",
                "occupation": "Student",
                "financially_dependent": True,
                "date_of_birth": "01/06/2010",
            }
        ],
    ),
})

goal_input_model = ns.model("GoalInput", {
    "category": fields.String(
        required=True,
        description="Goal category: child_goal or lifestyle.",
        example="lifestyle",
    ),
    "goal_type": fields.String(
        required=True,
        description=(
            "Standard type for the category, or Other for a custom goal. "
            "Child: Graduation | Post Graduation | Marriage | Other. "
            "Lifestyle: Home Purchase | Car Purchase | Home Renovation | Holiday Home | "
            "Foreign Tour | Family Gifting | Charity | Child Birth Expenses | "
            "Big Purchases | Estate For Children | Other. "
            "When Other, also send goal_name — that name is what gets saved in goal_type."
        ),
        example="Other",
    ),
    "goal_name": fields.String(
        required=False,
        description=(
            "Custom goal label. Required when goal_type is Other. "
            "Saved as goal_type in the response/DB (goal_name is not returned)."
        ),
        example="World Cup Trip",
    ),
    "child_id": fields.String(required=False, description="Optional child UUID to associate with the goal.", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    "education_program_id": fields.String(required=False, description="Optional education program UUID to link and auto-fill cost metadata.", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    "tour_destination_id": fields.String(required=False, description="Optional tour destination UUID to link and auto-fill cost metadata.", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    "target_year": fields.Integer(required=True, description="Future target year for this goal.", example=2030),
    "today_cost": fields.Float(required=False, description="Current cost of the goal in INR.", example=500000),
    "inflation_rate": fields.Float(required=False, description="Annual inflation assumption as a decimal.", example=0.06),
})

goals_input_model = ns.model("GoalsInput", {
    "goals": fields.List(
        fields.Nested(goal_input_model),
        required=True,
        description="Goal rows to save; maximum 50 for bulk endpoint. Empty list allowed.",
        example=[
            {
                "category": "child_goal",
                "goal_type": "Graduation",
                "target_year": 2035,
                "today_cost": 2500000,
                "inflation_rate": 0.08,
            },
            {
                "category": "lifestyle",
                "goal_type": "Other",
                "goal_name": "World Cup Trip",
                "target_year": 2030,
                "today_cost": 500000,
                "inflation_rate": 0.06,
            },
        ],
    ),
})


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def load_schema(schema, payload):
    try:
        return schema.load(payload or {})
    except ValidationError as err:
        field = next(iter(err.messages), None)
        raise APIError(
            "INVALID_INPUT",
            str(err.messages),
            field=field,
            http_status=400,
        )


def load_bulk_schema_item(schema, payload, index):
    try:
        return schema.load(payload or {})
    except ValidationError as err:
        field = next(iter(err.messages), None)
        raise APIError(
            "INVALID_INPUT",
            f"Item {index} failed validation: {err.messages}",
            field=field,
            http_status=400,
        )


def validate_bulk_size(items, max_items, label):
    if not isinstance(items, list):
        raise APIError(
            "INVALID_INPUT",
            f"{label} must be a list.",
            field=label,
            http_status=400,
        )
    if len(items) > max_items:
        raise APIError(
            "INVALID_INPUT",
            f"Maximum {max_items} items per bulk request",
            field=label,
            http_status=400,
        )


def parse_uuid_param(value, field_name):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise APIError(
            "INVALID_INPUT",
            f"{field_name} must be a valid UUID.",
            field=field_name,
            http_status=400,
        )


def get_assessment_or_404(assessment_id):
    assessment_id = parse_uuid_param(assessment_id, "assessment_id")
    record = db.session.get(AssessmentRecord, assessment_id)
    if not record:
        raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)
    return record


def get_monthly_eff_pre():
    config = RateConfig.query.first()
    roi_pre = config.roi_pre if config else 0.12
    return monthly_effective_rate(roi_pre)


def age_from_dob(dob: date) -> int:
    return current_year() - dob.year


def serialize_communication(row):
    return {
        "id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "mobile": row.mobile,
        "email": row.email,
        "spouse_mobile": row.spouse_mobile,
        "spouse_email": row.spouse_email,
        "residential_address": row.residential_address,
        "consent": row.consent,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


def serialize_personal(row):
    return {
        "id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "client_name": row.client_name,
        "client_occupation": row.client_occupation,
        "client_designation": row.client_designation,
        "client_company": row.client_company,
        "client_dob": row.client_dob.isoformat(),
        "client_age": row.client_age,
        "spouse_name": row.spouse_name,
        "spouse_occupation": row.spouse_occupation,
        "spouse_designation": row.spouse_designation,
        "spouse_company": row.spouse_company,
        "spouse_dob": row.spouse_dob.isoformat() if row.spouse_dob else None,
        "spouse_age": row.spouse_age,
        "client_retirement_age": row.client_retirement_age,
        "spouse_retirement_age": row.spouse_retirement_age,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


def serialize_child(row):
    return {
        "id": str(row.id),
        "family_id": str(row.family_id),
        "child_number": row.child_number,
        "child_name": row.full_name,
        "full_name": row.full_name,
        "occupation": row.occupation,
        "financially_dependent": row.financially_dependent,
        "date_of_birth": row.date_of_birth.isoformat() if row.date_of_birth else None,
        "calculated_age": row.calculated_age,
    }


def serialize_family(row, children):
    return {
        "id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "number_of_children": row.number_of_children,
        "children": [serialize_child(child) for child in children],
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


def serialize_goal(row):
    return {
        "id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "category": row.category,
        "goal_type": row.goal_type,
        "child_id": str(row.child_id) if row.child_id else None,
        "education_program_id": (
            str(row.education_program_id) if row.education_program_id else None
        ),
        "tour_destination_id": (
            str(row.tour_destination_id) if row.tour_destination_id else None
        ),
        "target_year": row.target_year,
        "today_cost": row.today_cost,
        "inflation_rate": row.inflation_rate,
        "future_cost": row.future_cost,
        "monthly_sip": row.monthly_sip,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


def build_goal_objects(assessment_id, goals_data):
    monthly_eff_pre = get_monthly_eff_pre()
    goals = []

    for goal_data in goals_data:
        calc = goal_calc(
            goal_data["target_year"],
            goal_data["today_cost"],
            goal_data.get("inflation_rate", 0.06),
            monthly_eff_pre,
        )
        goals.append(
            Goal(
                assessment_id=assessment_id,
                category=goal_data["category"],
                goal_type=goal_data["goal_type"],
                child_id=goal_data.get("child_id"),
                education_program_id=goal_data.get("education_program_id"),
                tour_destination_id=goal_data.get("tour_destination_id"),
                target_year=goal_data["target_year"],
                today_cost=goal_data["today_cost"],
                inflation_rate=goal_data.get("inflation_rate", 0.06),
                future_cost=calc["future_cost"],
                monthly_sip=calc["monthly_inv"],
            )
        )

    return goals


def validate_goal_child_ids(assessment_id, goals_data):
    for goal_data in goals_data:
        child_id = goal_data.get("child_id")
        if not child_id:
            continue

        child = db.session.get(Child, child_id)
        if not child:
            raise APIError(
                "NOT_FOUND",
                "child_id does not exist.",
                field="child_id",
                http_status=404,
            )

        family = db.session.get(FamilyDetails, child.family_id)
        if not family or str(family.assessment_id) != str(assessment_id):
            raise APIError(
                "INVALID_INPUT",
                "child_id does not belong to this assessment.",
                field="child_id",
                http_status=400,
            )


def apply_goal_reference_defaults(goals_data):
    for goal_data in goals_data:
        education_program_id = goal_data.get("education_program_id")
        if education_program_id:
            program = db.session.get(EducationProgram, education_program_id)
            if not program:
                raise APIError(
                    "NOT_FOUND",
                    "education_program_id does not exist.",
                    field="education_program_id",
                    http_status=404,
                )
            if not goal_data.get("today_cost"):
                goal_data["today_cost"] = program.approx_cost_inr
            if not goal_data.get("inflation_rate"):
                goal_data["inflation_rate"] = program.inflation_rate

        tour_destination_id = goal_data.get("tour_destination_id")
        if tour_destination_id:
            destination = db.session.get(TourDestination, tour_destination_id)
            if not destination:
                raise APIError(
                    "NOT_FOUND",
                    "tour_destination_id does not exist.",
                    field="tour_destination_id",
                    http_status=404,
                )
            if not goal_data.get("today_cost"):
                goal_data["today_cost"] = destination.budget_inr

        if not goal_data.get("today_cost"):
            raise APIError(
                "INVALID_INPUT",
                "today_cost is required when no reference cost is available.",
                field="today_cost",
                http_status=400,
            )
        if not goal_data.get("inflation_rate"):
            goal_data["inflation_rate"] = 0.06


def save_goals_bulk(assessment_id, goals_data, replace_existing=True):
    validate_bulk_size(goals_data, 50, "goals")
    validated_goals = [
        load_bulk_schema_item(GoalSchema(), item, index)
        for index, item in enumerate(goals_data)
    ]
    validate_goal_child_ids(assessment_id, validated_goals)
    apply_goal_reference_defaults(validated_goals)

    if replace_existing:
        Goal.query.filter_by(assessment_id=assessment_id).delete()

    saved_goals = build_goal_objects(assessment_id, validated_goals)
    db.session.add_all(saved_goals)
    return saved_goals


@ns.route("/")
class AssessmentCreate(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Creates a new empty assessment record and returns its UUID. "
            "Use the returned assessment_id to submit flow1 through flow4."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        record = AssessmentRecord(status="in_progress")
        db.session.add(record)
        db.session.commit()
        return success_response({"assessment_id": str(record.id)})


@ns.route("/bulk")
class AssessmentBulkCreate(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Creates up to 100 assessment records with flow1 communication "
            "details in a single all-or-nothing transaction."
        ),
    )
    @ns.expect(bulk_assessment_input_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    def post(self):
        payload = request.get_json(silent=True) or {}
        assessments = payload.get("assessments", [])
        validate_bulk_size(assessments, 100, "assessments")

        validated_assessments = [
            load_bulk_schema_item(CommunicationSchema(), item, index)
            for index, item in enumerate(assessments)
        ]

        assessment_ids = bulk_create_assessments_from_flow1(validated_assessments)
        return success_response({"assessment_ids": assessment_ids})


@ns.route("/<string:assessment_id>/flow1")
class AssessmentFlow1(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Creates or updates communication details for an assessment. "
            "Submitting this flow again updates the existing row rather than "
            "creating a duplicate."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.expect(communication_input_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        assessment_id = record.id
        data = load_schema(CommunicationSchema(), request.get_json(silent=True))

        comm = CommunicationDetails.query.filter_by(
            assessment_id=assessment_id
        ).first()
        if comm:
            comm.mobile = data["mobile"]
            comm.email = data["email"]
            comm.spouse_mobile = data.get("spouse_mobile")
            comm.spouse_email = data.get("spouse_email")
            comm.residential_address = data.get("residential_address")
            comm.consent = data["consent"]
            comm.submitted_at = datetime.now(timezone.utc)
        else:
            comm = CommunicationDetails(
                assessment_id=assessment_id,
                mobile=data["mobile"],
                email=data["email"],
                spouse_mobile=data.get("spouse_mobile"),
                spouse_email=data.get("spouse_email"),
                residential_address=data.get("residential_address"),
                consent=data["consent"],
            )
            db.session.add(comm)

        record.flow1_submitted_at = datetime.now(timezone.utc)
        db.session.commit()
        return success_response(serialize_communication(comm))


@ns.route("/<string:assessment_id>/flow2")
class AssessmentFlow2(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Creates or updates personal and spouse details for an assessment. "
            "Ages are derived from DOB and retirement ages must be greater "
            "than current ages."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.expect(personal_input_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        assessment_id = record.id
        data = load_schema(PersonalSchema(), request.get_json(silent=True))

        client_age = age_from_dob(data["client_dob"])
        spouse_age = None
        if data.get("spouse_dob"):
            spouse_age = age_from_dob(data["spouse_dob"])

        personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
        if personal:
            personal.client_name = data["client_name"]
            personal.client_occupation = data["client_occupation"]
            personal.client_designation = data["client_designation"]
            personal.client_company = data["client_company"]
            personal.client_dob = data["client_dob"]
            personal.client_age = client_age
            personal.spouse_name = data.get("spouse_name")
            personal.spouse_occupation = data.get("spouse_occupation")
            personal.spouse_designation = data.get("spouse_designation")
            personal.spouse_company = data.get("spouse_company")
            personal.spouse_dob = data.get("spouse_dob")
            personal.spouse_age = spouse_age
            personal.client_retirement_age = data.get("client_retirement_age", 60)
            personal.spouse_retirement_age = data.get("spouse_retirement_age", 55)
            personal.submitted_at = datetime.now(timezone.utc)
        else:
            personal = PersonalDetails(
                assessment_id=assessment_id,
                client_name=data["client_name"],
                client_occupation=data["client_occupation"],
                client_designation=data["client_designation"],
                client_company=data["client_company"],
                client_dob=data["client_dob"],
                client_age=client_age,
                spouse_name=data.get("spouse_name"),
                spouse_occupation=data.get("spouse_occupation"),
                spouse_designation=data.get("spouse_designation"),
                spouse_company=data.get("spouse_company"),
                spouse_dob=data.get("spouse_dob"),
                spouse_age=spouse_age,
                client_retirement_age=data.get("client_retirement_age", 60),
                spouse_retirement_age=data.get("spouse_retirement_age", 55),
            )
            db.session.add(personal)

        record.flow2_submitted_at = datetime.now(timezone.utc)
        db.session.commit()
        return success_response(serialize_personal(personal))


@ns.route("/<string:assessment_id>/flow3")
class AssessmentFlow3(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Creates or replaces family details and child rows for an "
            "assessment. Existing child rows are replaced when the flow is resubmitted."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.expect(family_input_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        assessment_id = record.id
        data = load_schema(FamilySchema(), request.get_json(silent=True))

        family = FamilyDetails.query.filter_by(assessment_id=assessment_id).first()
        if family:
            Child.query.filter_by(family_id=family.id).delete()
            family.number_of_children = data["number_of_children"]
            family.submitted_at = datetime.now(timezone.utc)
        else:
            family = FamilyDetails(
                assessment_id=assessment_id,
                number_of_children=data["number_of_children"],
            )
            db.session.add(family)
            db.session.flush()

        children = []
        for child_data in data.get("children", []):
            calculated_age = None
            dob = child_data.get("date_of_birth")
            if dob:
                calculated_age = age_from_dob(dob)

            child = Child(
                family_id=family.id,
                child_number=child_data["child_number"],
                full_name=child_data["child_name"],
                occupation=child_data.get("occupation"),
                financially_dependent=child_data.get("financially_dependent", True),
                date_of_birth=dob,
                calculated_age=calculated_age,
            )
            db.session.add(child)
            children.append(child)

        record.flow3_submitted_at = datetime.now(timezone.utc)
        db.session.commit()
        return success_response(serialize_family(family, children))


@ns.route("/<string:assessment_id>/flow4")
class AssessmentFlow4(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Creates or replaces financial goals for an assessment. "
            "Empty goals list is allowed (skip goals). "
            "For a custom goal: send goal_type=Other with goal_name "
            "(e.g. World Cup Trip). The custom name is saved as goal_type "
            "in the response. Uses the same path as /goals/bulk."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.expect(goals_input_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        assessment_id = record.id
        data = load_schema(GoalsListSchema(), request.get_json(silent=True))
        saved_goals = save_goals_bulk(assessment_id, data["goals"])

        record.flow4_submitted_at = datetime.now(timezone.utc)
        db.session.commit()
        return success_response(
            {"goals": [serialize_goal(goal) for goal in saved_goals]}
        )


@ns.route("/<string:assessment_id>/goals/bulk")
class AssessmentGoalsBulk(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Bulk creates up to 50 goals for an assessment in one transaction. "
            "All goals are validated before insertion; any invalid item rolls "
            "back the entire request. Custom goals: goal_type=Other + goal_name; "
            "saved goal_type becomes the entered name."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.expect(goals_input_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        assessment_id = record.id
        payload = request.get_json(silent=True) or {}
        goals = payload.get("goals", [])
        saved_goals = save_goals_bulk(assessment_id, goals)

        record.flow4_submitted_at = datetime.now(timezone.utc)
        db.session.commit()
        return success_response(
            {"goals": [serialize_goal(goal) for goal in saved_goals]}
        )


@ns.route("/<string:assessment_id>")
class AssessmentDetail(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Returns a full assessment snapshot including submitted flow "
            "data. When /calculate has been run, also includes calculation "
            "summary (insurance, corpus, SIP, etc.) for admin View Details. "
            "When reports exist, includes a reports list."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def get(self, assessment_id):
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")
        record = (
            db.session.execute(
                db.select(AssessmentRecord)
                .options(
                    db.joinedload(AssessmentRecord.communication),
                    db.joinedload(AssessmentRecord.personal),
                    db.joinedload(AssessmentRecord.family).joinedload(
                        FamilyDetails.children
                    ),
                    db.joinedload(AssessmentRecord.goals),
                )
                .where(AssessmentRecord.id == assessment_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if not record:
            raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

        flow1 = None
        if record.flow1_submitted_at:
            comm = record.communication
            if comm:
                flow1 = serialize_communication(comm)

        flow2 = None
        if record.flow2_submitted_at:
            personal = record.personal
            if personal:
                flow2 = serialize_personal(personal)

        flow3 = None
        if record.flow3_submitted_at:
            family = record.family
            if family:
                flow3 = serialize_family(family, family.children)

        flow4 = None
        if record.flow4_submitted_at:
            flow4 = {"goals": [serialize_goal(goal) for goal in record.goals]}

        calculation = serialize_calculation_for_assessment(record.id)
        reports = serialize_reports_for_assessment(record.id)

        return success_response(
            {
                "assessment_id": str(record.id),
                "status": record.status,
                "flow1_submitted_at": (
                    record.flow1_submitted_at.isoformat()
                    if record.flow1_submitted_at
                    else None
                ),
                "flow2_submitted_at": (
                    record.flow2_submitted_at.isoformat()
                    if record.flow2_submitted_at
                    else None
                ),
                "flow3_submitted_at": (
                    record.flow3_submitted_at.isoformat()
                    if record.flow3_submitted_at
                    else None
                ),
                "flow4_submitted_at": (
                    record.flow4_submitted_at.isoformat()
                    if record.flow4_submitted_at
                    else None
                ),
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
                "flow1": flow1,
                "flow2": flow2,
                "flow3": flow3,
                "flow4": flow4,
                "calculation": calculation,
                "reports": reports,
            }
        )
