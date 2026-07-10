"""Build shared context for report templates (HTML PDF and DOCX fallback)."""
from datetime import datetime, timezone

from app.core.formatters import fmt_inr
from app.core.formulas import excel_FV
from app.models.rate_config import RateConfig


def _rate_snapshot(calc: object) -> dict:
    if getattr(calc, "inflation_pre", None) is not None:
        return {
            "inflation_pre": calc.inflation_pre,
            "roi_pre": calc.roi_pre if calc.roi_pre is not None else 0.12,
            "inflation_post": calc.inflation_post if calc.inflation_post is not None else 0.06,
            "roi_post": calc.roi_post if calc.roi_post is not None else 0.08,
        }

    config = RateConfig.query.first()
    if config:
        return {
            "inflation_pre": config.inflation_pre,
            "roi_pre": config.roi_pre,
            "inflation_post": config.inflation_post,
            "roi_post": config.roi_post,
        }

    return {
        "inflation_pre": 0.06,
        "roi_pre": 0.12,
        "inflation_post": 0.06,
        "roi_post": 0.08,
    }


def _years_to_retirement(age, retirement_age) -> int | None:
    if age is None or retirement_age is None:
        return None
    return max(retirement_age - age, 0)


def _expense_placeholders(annual_ret_reqd, years_to_retirement, inflation_pre) -> tuple[str, str]:
    if not annual_ret_reqd or years_to_retirement is None:
        return "", ""
    expense_today_pm = annual_ret_reqd / 12
    expense_at_ret_pm = excel_FV(inflation_pre, years_to_retirement, 0, expense_today_pm)
    return fmt_inr(expense_today_pm), fmt_inr(expense_at_ret_pm)


def build_report_context(
    assessment_id: str,
    calc: object,
    personal: object,
    comm: object,
    goals: list,
) -> dict:
    """Context for Jinja HTML/PDF template and legacy DOCX placeholders."""
    rates = _rate_snapshot(calc)
    client_years = _years_to_retirement(
        personal.client_age, personal.client_retirement_age
    )
    spouse_years = _years_to_retirement(
        personal.spouse_age, personal.spouse_retirement_age
    )
    client_expense_today, client_expense_at_retirement = _expense_placeholders(
        getattr(calc, "client_annual_ret_reqd", None),
        client_years,
        rates["inflation_pre"],
    )
    spouse_expense_today, spouse_expense_at_retirement = _expense_placeholders(
        getattr(calc, "spouse_annual_ret_reqd", None),
        spouse_years,
        rates["inflation_pre"],
    )

    goals_rows = [
        {
            "goal_type": g.goal_type,
            "target_year": g.target_year,
            "today_cost": fmt_inr(g.today_cost or 0),
            "future_cost": fmt_inr(g.future_cost or 0),
            "monthly_sip": fmt_inr(g.monthly_sip or 0),
        }
        for g in goals
    ]

    has_spouse = bool(personal.spouse_name or personal.spouse_age)

    return {
        "client_name": personal.client_name or "",
        "client_age": personal.client_age or "",
        "client_occupation": personal.client_occupation or "",
        "client_company": personal.client_company or "",
        "client_dob": str(personal.client_dob or ""),
        "client_retirement_age": personal.client_retirement_age or "",
        "client_years_to_retirement": client_years if client_years is not None else "",
        "client_expense_today": client_expense_today,
        "client_expense_at_retirement": client_expense_at_retirement,
        "spouse_name": personal.spouse_name or "",
        "spouse_age": personal.spouse_age or "",
        "spouse_occupation": personal.spouse_occupation or "",
        "spouse_company": personal.spouse_company or "",
        "spouse_dob": str(personal.spouse_dob or ""),
        "spouse_retirement_age": personal.spouse_retirement_age or "",
        "spouse_years_to_retirement": spouse_years if spouse_years is not None else "",
        "spouse_expense_today": spouse_expense_today,
        "spouse_expense_at_retirement": spouse_expense_at_retirement,
        "mobile": comm.mobile or "",
        "email": comm.email or "",
        "residential_address": comm.residential_address or "",
        "report_date": datetime.now(timezone.utc).strftime("%d %B %Y"),
        "assessment_id": str(assessment_id),
        "client_corpus": fmt_inr(calc.client_corpus or 0),
        "client_pf_corpus": fmt_inr(calc.client_pf_corpus or 0),
        "client_net_corpus": fmt_inr(calc.client_net_corpus or 0),
        "client_monthly_sip": fmt_inr(calc.client_monthly_sip or 0),
        "client_lump_sum": fmt_inr(calc.client_lump_sum or 0),
        "spouse_corpus": fmt_inr(calc.spouse_corpus or 0),
        "spouse_pf_corpus": fmt_inr(calc.spouse_pf_corpus or 0),
        "spouse_net_corpus": fmt_inr(calc.spouse_net_corpus or 0),
        "spouse_monthly_sip": fmt_inr(calc.spouse_monthly_sip or 0),
        "spouse_lump_sum": fmt_inr(calc.spouse_lump_sum or 0),
        "total_insurance_required": fmt_inr(calc.total_insurance_required or 0),
        "total_goals_monthly_sip": fmt_inr(calc.total_goals_monthly_sip or 0),
        "inflation_pre": f"{rates['inflation_pre'] * 100:.1f}%",
        "roi_pre": f"{rates['roi_pre'] * 100:.1f}%",
        "inflation_post": f"{rates['inflation_post'] * 100:.1f}%",
        "roi_post": f"{rates['roi_post'] * 100:.1f}%",
        "calculated_at": (
            calc.calculated_at.strftime("%d %B %Y %H:%M") if calc.calculated_at else ""
        ),
        "goals": goals_rows,
        "has_spouse": has_spouse,
        "has_goals": len(goals_rows) > 0,
    }
