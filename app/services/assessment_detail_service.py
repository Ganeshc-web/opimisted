"""Enrich assessment detail with calculation and report summaries for admin View Details."""
from uuid import UUID

from app.core.formatters import fmt_response
from app.core.formulas import excel_FV
from app.models.calculation import CalculationOutput
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.report_log import ReportLog
from app.services.investment_summary_service import build_investment_summary


def _as_uuid(value):
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _years_to_retirement(age, retirement_age) -> int | None:
    if age is None or retirement_age is None:
        return None
    return max(int(retirement_age) - int(age), 0)


def _expense_pair(annual_ret_reqd, years_to_retirement, inflation_pre):
    if not annual_ret_reqd or years_to_retirement is None:
        return None, None
    expense_today_pm = float(annual_ret_reqd) / 12.0
    inflation = float(inflation_pre) if inflation_pre is not None else 0.06
    expense_at_ret_pm = excel_FV(inflation, years_to_retirement, 0, expense_today_pm)
    return fmt_response(expense_today_pm), fmt_response(expense_at_ret_pm)


def _person_retirement_block(
    *,
    name: str | None,
    age,
    retirement_age,
    annual_ret_reqd,
    inflation_pre,
    corpus,
    pf_corpus,
    net_corpus,
    monthly_sip,
    lump_sum,
) -> dict:
    years = _years_to_retirement(age, retirement_age)
    expense_today, expense_at_ret = _expense_pair(
        annual_ret_reqd, years, inflation_pre
    )
    return {
        "name": name or "",
        "age": age,
        "retirement_age": retirement_age,
        "years_to_retirement": years,
        "monthly_expense_today": expense_today,
        "inflation_adjusted_expense": expense_at_ret,
        "total_required_corpus": fmt_response(corpus or 0),
        "projected_pf_corpus": fmt_response(pf_corpus or 0),
        "corpus_deficit_gap": fmt_response(net_corpus or 0),
        "monthly_sip_required": fmt_response(monthly_sip or 0),
        "lump_sum_alternative": fmt_response(lump_sum or 0),
    }


def _format_stored_insurance_items(raw_items) -> list[dict]:
    """Normalize CalculationOutput.insurance_items JSON for API responses."""
    if not raw_items:
        return []
    formatted = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        if "need" in row and "pv" in row:
            formatted.append(row)
            continue
        formatted.append(
            {
                "need": row.get("Need") or row.get("need") or "",
                "years": int(row.get("Years") if row.get("Years") is not None else row.get("years") or 0),
                "amount": fmt_response(
                    float(row.get("Amount (₹)") or row.get("amount") or 0)
                ),
                "type": row.get("Type") or row.get("type") or "",
                "pv": fmt_response(float(row.get("PV (₹)") or row.get("pv") or 0)),
            }
        )
    return formatted


def serialize_calculation_for_assessment(assessment_id) -> dict | None:
    """Latest calculation snapshot for admin View Details, PDF, and FE Excel."""
    assessment_id = _as_uuid(assessment_id)
    calc = (
        CalculationOutput.query.filter_by(assessment_id=assessment_id)
        .order_by(CalculationOutput.calculated_at.desc())
        .first()
    )
    if not calc:
        return None

    personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
    has_spouse = bool(
        personal
        and (personal.spouse_name or personal.spouse_age or personal.spouse_dob)
    )

    client_block = _person_retirement_block(
        name=getattr(personal, "client_name", None) if personal else None,
        age=getattr(personal, "client_age", None) if personal else None,
        retirement_age=(
            getattr(personal, "client_retirement_age", None) if personal else None
        ),
        annual_ret_reqd=calc.client_annual_ret_reqd,
        inflation_pre=calc.inflation_pre,
        corpus=calc.client_corpus,
        pf_corpus=calc.client_pf_corpus,
        net_corpus=calc.client_net_corpus,
        monthly_sip=calc.client_monthly_sip,
        lump_sum=calc.client_lump_sum,
    )

    spouse_block = None
    if has_spouse:
        spouse_block = _person_retirement_block(
            name=getattr(personal, "spouse_name", None),
            age=getattr(personal, "spouse_age", None),
            retirement_age=getattr(personal, "spouse_retirement_age", None),
            annual_ret_reqd=calc.spouse_annual_ret_reqd,
            inflation_pre=calc.inflation_pre,
            corpus=calc.spouse_corpus,
            pf_corpus=calc.spouse_pf_corpus,
            net_corpus=calc.spouse_net_corpus,
            monthly_sip=calc.spouse_monthly_sip,
            lump_sum=calc.spouse_lump_sum,
        )

    total_corpus = (calc.client_corpus or 0) + (
        (calc.spouse_corpus or 0) if has_spouse else 0
    )
    total_monthly_sip = abs(calc.client_monthly_sip or 0) + (
        abs(calc.spouse_monthly_sip or 0) if has_spouse else 0
    )

    goals = Goal.query.filter_by(assessment_id=assessment_id).all()
    goal_items = [
        {
            "goal_type": g.goal_type,
            "category": g.category,
            "child_id": str(g.child_id) if g.child_id else None,
            "target_year": g.target_year,
            "today_cost": fmt_response(g.today_cost or 0),
            "future_cost": fmt_response(g.future_cost or 0),
            "monthly_sip": fmt_response(abs(g.monthly_sip or 0)),
        }
        for g in goals
    ]

    investment_summary = build_investment_summary(
        assessment_id, calc=calc, personal=personal
    )

    insurance_items = _format_stored_insurance_items(calc.insurance_items)

    return {
        "calculation_id": str(calc.id),
        "calculated_at": calc.calculated_at.isoformat() if calc.calculated_at else None,
        "summary": {
            "average_insurance_required": fmt_response(
                calc.total_insurance_required or 0
            ),
            "total_retirement_corpus_required": fmt_response(total_corpus),
            # Retirement SIPs only (legacy thank-you card); prefer total_monthly_investment.
            "monthly_investment_required": fmt_response(total_monthly_sip),
            "total_goals_monthly_sip": fmt_response(calc.total_goals_monthly_sip or 0),
            "total_monthly_investment": investment_summary["total_monthly_investment"],
        },
        "inputs": {
            "household_monthly": fmt_response(calc.household_monthly or 0),
            "client_annual_ret_reqd": fmt_response(calc.client_annual_ret_reqd or 0),
            "spouse_annual_ret_reqd": fmt_response(calc.spouse_annual_ret_reqd or 0),
        },
        "client": client_block,
        "spouse": spouse_block,
        "goals": {
            "items": goal_items,
            "total_monthly_sip": fmt_response(calc.total_goals_monthly_sip or 0),
        },
        "investment_summary": investment_summary,
        "insurance": {
            "total_required": fmt_response(calc.total_insurance_required or 0),
            "items": insurance_items,
        },
        "rates": {
            "inflation_pre": calc.inflation_pre,
            "roi_pre": calc.roi_pre,
            "inflation_post": calc.inflation_post,
            "roi_post": calc.roi_post,
        },
    }


def serialize_reports_for_assessment(assessment_id) -> list[dict]:
    assessment_id = _as_uuid(assessment_id)
    rows = (
        ReportLog.query.filter_by(assessment_id=assessment_id)
        .order_by(ReportLog.generated_at.desc())
        .all()
    )
    return [
        {
            "report_id": str(row.id),
            "file_name": row.file_name,
            "format": row.format,
            "triggered_by": row.triggered_by,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "downloaded_at": (
                row.downloaded_at.isoformat() if row.downloaded_at else None
            ),
        }
        for row in rows
    ]
