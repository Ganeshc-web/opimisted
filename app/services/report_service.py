import os
import shutil
from datetime import datetime
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
import subprocess
import platform

from app.core.formatters import fmt_inr

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = str(PROJECT_ROOT / "templates" / "report_template.docx")
REPORTS_FOLDER = str(PROJECT_ROOT / "reports")


def replace_placeholders(doc: Document, replacements: dict) -> Document:
    """
    Replace all {{key}} placeholders in paragraphs, tables, headers, footers.
    Does not replace {{goals_table}} here — that is handled separately.
    """
    for para in doc.paragraphs:
        for key, value in replacements.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in para.text:
                for run in para.runs:
                    if placeholder in run.text:
                        run.text = run.text.replace(placeholder, str(value))

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for key, value in replacements.items():
                        placeholder = f"{{{{{key}}}}}"
                        if placeholder in para.text:
                            for run in para.runs:
                                if placeholder in run.text:
                                    run.text = run.text.replace(placeholder, str(value))
    return doc


def insert_goals_table(doc: Document, goals: list[dict]) -> Document:
    """
    Find {{goals_table}} paragraph and replace it with an actual Word table.
    Columns: Goal | Target Year | Today Cost | Future Cost | Monthly SIP
    """
    for i, para in enumerate(doc.paragraphs):
        if "{{goals_table}}" in para.text:
            para.text = ""
            table = doc.add_table(rows=1, cols=5)
            table.style = "Table Grid"
            headers = ["Goal", "Target Year", "Today's Cost", "Future Cost", "Monthly SIP"]
            hdr_cells = table.rows[0].cells
            for j, h in enumerate(headers):
                hdr_cells[j].text = h
                hdr_cells[j].paragraphs[0].runs[0].bold = True

            for g in goals:
                row_cells = table.add_row().cells
                row_cells[0].text = g.get("goal_type", "")
                row_cells[1].text = str(g.get("target_year", ""))
                row_cells[2].text = fmt_inr(g.get("today_cost", 0))
                row_cells[3].text = fmt_inr(g.get("future_cost", 0))
                row_cells[4].text = fmt_inr(g.get("monthly_sip", 0))

            para._element.addprevious(table._tbl)
            break
    return doc


def convert_to_pdf(docx_path: str) -> str:
    """
    Convert .docx to .pdf using docx2pdf.
    Returns path to generated PDF.
    """
    from docx2pdf import convert
    pdf_path = docx_path.replace(".docx", ".pdf")
    convert(docx_path, pdf_path)
    return pdf_path


def generate_report(assessment_id: str, calc: object, 
                    personal: object, comm: object,
                    goals: list) -> dict:
    """
    Main entry point. Fills template, converts to PDF, returns paths.
    assessment_id   — uuid string
    calc            — CalculationOutput model instance
    personal        — PersonalDetails model instance  
    comm            — CommunicationDetails model instance
    goals           — list of Goal model instances
    """
    os.makedirs(REPORTS_FOLDER, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"report_{assessment_id[:8]}_{timestamp}"
    docx_path = os.path.join(REPORTS_FOLDER, f"{file_name}.docx")
    
    replacements = {
        # Client
        "client_name":               personal.client_name or "",
        "client_age":                str(personal.client_age or ""),
        "client_occupation":         personal.client_occupation or "",
        "client_company":            personal.client_company or "",
        "client_dob":                str(personal.client_dob or ""),
        "spouse_name":               personal.spouse_name or "",
        "spouse_age":                str(personal.spouse_age or ""),
        "spouse_occupation":         personal.spouse_occupation or "",
        "spouse_company":            personal.spouse_company or "",
        "spouse_dob":                str(personal.spouse_dob or ""),
        "mobile":                    comm.mobile or "",
        "email":                     comm.email or "",
        "residential_address":       comm.residential_address or "",
        "report_date":               datetime.utcnow().strftime("%d %B %Y"),
        "assessment_id":             str(assessment_id),
        # Calculations
        "client_corpus":             fmt_inr(calc.client_corpus or 0),
        "client_pf_corpus":          fmt_inr(calc.client_pf_corpus or 0),
        "client_net_corpus":         fmt_inr(calc.client_net_corpus or 0),
        "client_monthly_sip":        fmt_inr(calc.client_monthly_sip or 0),
        "client_lump_sum":           fmt_inr(calc.client_lump_sum or 0),
        "spouse_corpus":             fmt_inr(calc.spouse_corpus or 0),
        "spouse_pf_corpus":          fmt_inr(calc.spouse_pf_corpus or 0),
        "spouse_net_corpus":         fmt_inr(calc.spouse_net_corpus or 0),
        "spouse_monthly_sip":        fmt_inr(calc.spouse_monthly_sip or 0),
        "spouse_lump_sum":           fmt_inr(calc.spouse_lump_sum or 0),
        "total_insurance_required":  fmt_inr(calc.total_insurance_required or 0),
        "total_goals_monthly_sip":   fmt_inr(calc.total_goals_monthly_sip or 0),
        # Rates
        "inflation_pre":             f"{(calc.monthly_eff_pre or 0.06) * 100:.1f}%",
        "roi_pre":                   "12.0%",
        "inflation_post":            "6.0%",
        "roi_post":                  "8.0%",
        "calculated_at":             calc.calculated_at.strftime("%d %B %Y %H:%M") if calc.calculated_at else "",
    }

    doc = Document(TEMPLATE_PATH)
    doc = replace_placeholders(doc, replacements)

    goals_data = [
        {
            "goal_type":   g.goal_type,
            "target_year": g.target_year,
            "today_cost":  g.today_cost or 0,
            "future_cost": g.future_cost or 0,
            "monthly_sip": g.monthly_sip or 0,
        }
        for g in goals
    ]
    doc = insert_goals_table(doc, goals_data)
    doc.save(docx_path)

    pdf_path = convert_to_pdf(docx_path)

    return {
        "file_name":  f"{file_name}.pdf",
        "docx_path":  docx_path,
        "pdf_path":   pdf_path,
    }
