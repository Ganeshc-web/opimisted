"""Preview the Wealth Wisdom PDF report template locally.

Usage:
  python scripts/preview_report.py

Outputs:
  reports/preview_report.html  — open in browser to check design
  reports/preview_report.pdf   — if WeasyPrint is installed
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.report_pdf_service import render_report_html, render_report_pdf

SAMPLE = {
    "client_name": "Rajesh Kumar",
    "client_age": 38,
    "client_occupation": "Software Engineer",
    "client_company": "TCS",
    "client_dob": "1990-03-15",
    "client_retirement_age": 60,
    "client_years_to_retirement": 22,
    "client_expense_today": "₹75,000",
    "client_expense_at_retirement": "₹2.85 L",
    "spouse_name": "Priya Kumar",
    "spouse_age": 35,
    "spouse_occupation": "Teacher",
    "spouse_company": "Delhi Public School",
    "spouse_dob": "1993-07-20",
    "spouse_retirement_age": 55,
    "spouse_years_to_retirement": 20,
    "spouse_expense_today": "₹50,000",
    "spouse_expense_at_retirement": "₹1.60 L",
    "mobile": "9876543210",
    "email": "rajesh@example.com",
    "residential_address": "Andheri West, Mumbai 400058",
    "report_date": "09 July 2026",
    "assessment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "client_corpus": "₹2.45 Cr",
    "client_pf_corpus": "₹85.00 L",
    "client_net_corpus": "₹1.60 Cr",
    "client_monthly_sip": "₹32,500",
    "client_lump_sum": "₹8.50 L",
    "spouse_corpus": "₹1.20 Cr",
    "spouse_pf_corpus": "₹12.00 L",
    "spouse_net_corpus": "₹1.08 Cr",
    "spouse_monthly_sip": "₹18,000",
    "spouse_lump_sum": "₹4.00 L",
    "total_insurance_required": "₹1.50 Cr",
    "total_goals_monthly_sip": "₹28,500",
    "inflation_pre": "6.0%",
    "roi_pre": "12.0%",
    "inflation_post": "6.0%",
    "roi_post": "8.0%",
    "calculated_at": "09 July 2026 17:30",
    "goals": [
        {
            "goal_type": "Home Purchase",
            "target_year": 2035,
            "today_cost": "₹50.00 L",
            "future_cost": "₹89.50 L",
            "monthly_sip": "₹15,200",
        },
        {
            "goal_type": "Child Graduation",
            "target_year": 2040,
            "today_cost": "₹25.00 L",
            "future_cost": "₹54.30 L",
            "monthly_sip": "₹8,400",
        },
    ],
    "has_spouse": True,
    "has_goals": True,
}


def main():
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    html_path = out_dir / "preview_report.html"
    pdf_path = out_dir / "preview_report.pdf"

    html = render_report_html(SAMPLE)
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML preview: {html_path}")
    print("  -> Open this file in Chrome/Edge to check the design.")

    if render_report_pdf(html, str(pdf_path)):
        print(f"PDF preview:  {pdf_path}")
        print("  -> Open this PDF to see final output.")
    else:
        print("PDF not created (install WeasyPrint for local PDF preview).")
        print("  pip install weasyprint")
        print("  On production Lightsail, PDF generation will work.")


if __name__ == "__main__":
    main()
