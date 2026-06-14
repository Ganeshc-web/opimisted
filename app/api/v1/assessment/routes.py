from datetime import date, datetime

from flask import request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from app import db
from app.core.exceptions import APIError
from app.core.formulas import current_year, goal_calc, monthly_effective_rate
from app.core.validators import (
    CommunicationSchema,
    FamilySchema,
    GoalsListSchema,
    PersonalSchema,
)
from app.middleware.auth import require_api_key
from app.models.assessment import AssessmentRecord
from app.models.communication import CommunicationDetails
from app.models.family import Child, FamilyDetails
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.rate_config import RateConfig

ns = Namespace("assessment", description="Assessment flows", path="/assessment")


def success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
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


def get_assessment_or_404(assessment_id):
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
        "target_year": row.target_year,
        "today_cost": row.today_cost,
        "inflation_rate": row.inflation_rate,
        "future_cost": row.future_cost,
        "monthly_sip": row.monthly_sip,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
    }


@ns.route("/")
class AssessmentCreate(Resource):
    @require_api_key
    def post(self):
        record = AssessmentRecord(status="in_progress")
        db.session.add(record)
        db.session.commit()
        return success_response({"assessment_id": str(record.id)})


@ns.route("/<uuid:assessment_id>/flow1")
class AssessmentFlow1(Resource):
    @require_api_key
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
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
            comm.submitted_at = datetime.utcnow()
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

        record.flow1_submitted_at = datetime.utcnow()
        db.session.commit()
        return success_response(serialize_communication(comm))


@ns.route("/<uuid:assessment_id>/flow2")
class AssessmentFlow2(Resource):
    @require_api_key
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
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
            personal.submitted_at = datetime.utcnow()
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

        record.flow2_submitted_at = datetime.utcnow()
        db.session.commit()
        return success_response(serialize_personal(personal))


@ns.route("/<uuid:assessment_id>/flow3")
class AssessmentFlow3(Resource):
    @require_api_key
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        data = load_schema(FamilySchema(), request.get_json(silent=True))

        family = FamilyDetails.query.filter_by(assessment_id=assessment_id).first()
        if family:
            Child.query.filter_by(family_id=family.id).delete()
            family.number_of_children = data["number_of_children"]
            family.submitted_at = datetime.utcnow()
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
                full_name=child_data["full_name"],
                occupation=child_data.get("occupation"),
                financially_dependent=child_data.get("financially_dependent", True),
                date_of_birth=dob,
                calculated_age=calculated_age,
            )
            db.session.add(child)
            children.append(child)

        record.flow3_submitted_at = datetime.utcnow()
        db.session.commit()
        return success_response(serialize_family(family, children))


@ns.route("/<uuid:assessment_id>/flow4")
class AssessmentFlow4(Resource):
    @require_api_key
    def post(self, assessment_id):
        record = get_assessment_or_404(assessment_id)
        data = load_schema(GoalsListSchema(), request.get_json(silent=True))
        monthly_eff_pre = get_monthly_eff_pre()

        Goal.query.filter_by(assessment_id=assessment_id).delete()

        saved_goals = []
        for goal_data in data["goals"]:
            calc = goal_calc(
                goal_data["target_year"],
                goal_data["today_cost"],
                goal_data.get("inflation_rate", 0.06),
                monthly_eff_pre,
            )
            goal = Goal(
                assessment_id=assessment_id,
                category=goal_data["category"],
                goal_type=goal_data["goal_type"],
                target_year=goal_data["target_year"],
                today_cost=goal_data["today_cost"],
                inflation_rate=goal_data.get("inflation_rate", 0.06),
                future_cost=calc["future_cost"],
                monthly_sip=calc["monthly_inv"],
            )
            db.session.add(goal)
            saved_goals.append(goal)

        record.flow4_submitted_at = datetime.utcnow()
        db.session.commit()
        return success_response(
            {"goals": [serialize_goal(goal) for goal in saved_goals]}
        )


@ns.route("/<uuid:assessment_id>")
class AssessmentDetail(Resource):
    @require_api_key
    def get(self, assessment_id):
        record = get_assessment_or_404(assessment_id)

        flow1 = None
        if record.flow1_submitted_at:
            comm = CommunicationDetails.query.filter_by(
                assessment_id=assessment_id
            ).first()
            if comm:
                flow1 = serialize_communication(comm)

        flow2 = None
        if record.flow2_submitted_at:
            personal = PersonalDetails.query.filter_by(
                assessment_id=assessment_id
            ).first()
            if personal:
                flow2 = serialize_personal(personal)

        flow3 = None
        if record.flow3_submitted_at:
            family = FamilyDetails.query.filter_by(
                assessment_id=assessment_id
            ).first()
            if family:
                children = Child.query.filter_by(family_id=family.id).all()
                flow3 = serialize_family(family, children)

        flow4 = None
        if record.flow4_submitted_at:
            goals = Goal.query.filter_by(assessment_id=assessment_id).all()
            flow4 = {"goals": [serialize_goal(goal) for goal in goals]}

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
            }
        )
