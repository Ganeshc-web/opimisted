"""Backend-owned investment summary: per-goal rows plus retirement, and the total.

The report PDF summary page and the frontend thank-you page must show the same
numbers, so both read this instead of adding up rows themselves.
"""
from uuid import UUID

from app.core.formatters import fmt_response
from app.models.calculation import CalculationOutput
from app.models.goals import Goal
from app.models.personal import PersonalDetails


def _as_uuid(value):
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _goals_data_for_assessment(assessment_id) -> list[dict]:
    from app.services.report_service import _children_for_assessment, _first_name

    children = _children_for_assessment(assessment_id)
    numbers_by_id = {child.id: child.child_number for child in children}
    names_by_id = {child.id: _first_name(child.full_name) for child in children}

    return [
        {
            "category": goal.category,
            "goal_type": goal.goal_type,
            "child_id": getattr(goal, "child_id", None),
            "child_number": numbers_by_id.get(getattr(goal, "child_id", None)),
            "child_name": names_by_id.get(getattr(goal, "child_id", None), ""),
            "target_year": goal.target_year,
            "today_cost": goal.today_cost or 0,
            "future_cost": goal.future_cost or 0,
            "monthly_sip": goal.monthly_sip or 0,
        }
        for goal in Goal.query.filter_by(assessment_id=assessment_id).all()
    ]


def build_investment_summary(assessment_id, calc=None, personal=None) -> dict:
    """Investment summary rows and totals for an assessment.

    Rows match the report's summary page: one row per funded goal plus client and
    spouse retirement. The total includes retirement.
    """
    from app.services.summary_docx_service import _monthly_amount, build_summary_rows

    assessment_id = _as_uuid(assessment_id)

    if calc is None:
        calc = (
            CalculationOutput.query.filter_by(assessment_id=assessment_id)
            .order_by(CalculationOutput.calculated_at.desc())
            .first()
        )
    if personal is None:
        personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()

    goals_data = _goals_data_for_assessment(assessment_id)
    rows, total = build_summary_rows(goals_data, calc=calc, personal=personal)

    client_retirement = _monthly_amount(getattr(calc, "client_monthly_sip", None))
    spouse_retirement = _monthly_amount(getattr(calc, "spouse_monthly_sip", None))
    retirement_total = client_retirement + spouse_retirement
    goals_total = sum(
        _monthly_amount(row.get("monthly_sip"))
        for row in rows
        if not row.get("is_retirement")
    )

    return {
        "rows": [
            {
                "goal": row.get("goal") or "",
                "target_year": row.get("target_year") or "",
                "is_retirement": bool(row.get("is_retirement")),
                "monthly_investment": fmt_response(
                    _monthly_amount(row.get("monthly_sip"))
                ),
            }
            for row in rows
        ],
        "goals_monthly_investment": fmt_response(goals_total),
        "retirement_monthly_investment": fmt_response(retirement_total),
        "client_retirement_monthly_investment": fmt_response(client_retirement),
        "spouse_retirement_monthly_investment": fmt_response(spouse_retirement),
        "total_monthly_investment": fmt_response(total),
    }
