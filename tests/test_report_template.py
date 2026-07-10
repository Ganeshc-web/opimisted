from unittest.mock import MagicMock

from app.services.report_context import build_report_context
from app.services.report_pdf_service import render_report_html


def test_build_report_context_includes_goals():
    personal = MagicMock(
        client_name="Rajesh Kumar",
        client_age=35,
        client_occupation="Engineer",
        client_company="TCS",
        client_dob="1990-01-15",
        client_retirement_age=60,
        spouse_name=None,
        spouse_age=None,
        spouse_occupation=None,
        spouse_company=None,
        spouse_dob=None,
        spouse_retirement_age=55,
    )
    comm = MagicMock(
        mobile="9876543210",
        email="rajesh@example.com",
        residential_address="Mumbai",
    )
    calc = MagicMock(
        client_corpus=5000000,
        client_pf_corpus=1000000,
        client_net_corpus=4000000,
        client_monthly_sip=25000,
        client_lump_sum=500000,
        spouse_corpus=0,
        spouse_pf_corpus=0,
        spouse_net_corpus=0,
        spouse_monthly_sip=0,
        spouse_lump_sum=0,
        total_insurance_required=20000000,
        total_goals_monthly_sip=15000,
        client_annual_ret_reqd=1200000,
        spouse_annual_ret_reqd=0,
        inflation_pre=0.06,
        roi_pre=0.12,
        inflation_post=0.06,
        roi_post=0.08,
        calculated_at=None,
    )
    goal = MagicMock(
        goal_type="Home Purchase",
        target_year=2035,
        today_cost=5000000,
        future_cost=8000000,
        monthly_sip=12000,
    )

    ctx = build_report_context("abcd1234-5678-90ab-cdef-1234567890ab", calc, personal, comm, [goal])

    assert ctx["client_name"] == "Rajesh Kumar"
    assert ctx["has_goals"] is True
    assert len(ctx["goals"]) == 1
    assert "₹" in ctx["client_corpus"]


def test_render_report_html_produces_pdf_content():
    ctx = {
        "client_name": "Test Client",
        "client_age": 40,
        "client_occupation": "Doctor",
        "client_company": "Apollo",
        "client_dob": "1985-05-20",
        "client_retirement_age": 60,
        "client_years_to_retirement": 20,
        "client_expense_today": "₹50,000",
        "client_expense_at_retirement": "₹1.60 L",
        "spouse_name": "",
        "spouse_age": "",
        "spouse_occupation": "",
        "spouse_company": "",
        "spouse_dob": "",
        "spouse_retirement_age": "",
        "spouse_years_to_retirement": "",
        "spouse_expense_today": "",
        "spouse_expense_at_retirement": "",
        "mobile": "9999999999",
        "email": "test@example.com",
        "residential_address": "Delhi",
        "report_date": "09 July 2026",
        "assessment_id": "test-id",
        "client_corpus": "₹2.00 Cr",
        "client_pf_corpus": "₹50.00 L",
        "client_net_corpus": "₹1.50 Cr",
        "client_monthly_sip": "₹25,000",
        "client_lump_sum": "₹5.00 L",
        "spouse_corpus": "₹0",
        "spouse_pf_corpus": "₹0",
        "spouse_net_corpus": "₹0",
        "spouse_monthly_sip": "₹0",
        "spouse_lump_sum": "₹0",
        "total_insurance_required": "₹1.00 Cr",
        "total_goals_monthly_sip": "₹10,000",
        "inflation_pre": "6.0%",
        "roi_pre": "12.0%",
        "inflation_post": "6.0%",
        "roi_post": "8.0%",
        "calculated_at": "09 July 2026 12:00",
        "goals": [],
        "has_spouse": False,
        "has_goals": False,
    }
    html = render_report_html(ctx)
    assert "Financial Planning Report" in html
    assert "Test Client" in html
    assert "Wealth Wisdom" in html
