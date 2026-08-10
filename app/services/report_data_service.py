"""Full JSON payload for frontend-generated PDF and Excel reports."""
from app.core.exceptions import APIError
from app.models.assessment import AssessmentRecord
from app.models.service import Service
from app.models.testimonial import Testimonial
from app.services.assessment_detail_service import serialize_calculation_for_assessment
from app.services.investment_summary_service import build_investment_summary
from app.services.service_service import serialize_service
from app.services.testimonial_service import serialize_testimonial


def build_report_data(assessment_id) -> dict:
    """Assessment flows + calculation + investment summary + services/testimonials.

    Same payload powers FE PDF and FE Excel downloads — backend returns JSON only;
    the browser builds the file.
    """
    from app.api.v1.assessment.routes import (
        serialize_communication,
        serialize_family,
        serialize_goal,
        serialize_personal,
    )

    record = AssessmentRecord.query.filter_by(id=assessment_id).first()
    if not record:
        raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

    flow1 = None
    if record.flow1_submitted_at and record.communication:
        flow1 = serialize_communication(record.communication)

    flow2 = None
    if record.flow2_submitted_at and record.personal:
        flow2 = serialize_personal(record.personal)

    flow3 = None
    if record.flow3_submitted_at and record.family:
        flow3 = serialize_family(record.family, record.family.children)

    flow4 = None
    if record.flow4_submitted_at:
        flow4 = {"goals": [serialize_goal(goal) for goal in record.goals]}

    services = [
        serialize_service(row)
        for row in Service.query.order_by(
            Service.sort_order.asc(), Service.created_at.asc()
        ).all()
    ]
    testimonials = [
        serialize_testimonial(row)
        for row in Testimonial.query.order_by(
            Testimonial.sort_order.asc(), Testimonial.created_at.asc()
        ).all()
    ]

    calculation = serialize_calculation_for_assessment(record.id)
    investment_summary = (
        calculation.get("investment_summary")
        if calculation
        else build_investment_summary(record.id)
    )

    return {
        "assessment_id": str(record.id),
        "status": record.status,
        "flow1": flow1,
        "flow2": flow2,
        "flow3": flow3,
        "flow4": flow4,
        "calculation": calculation,
        "investment_summary": investment_summary,
        "services": services,
        "testimonials": testimonials,
    }
