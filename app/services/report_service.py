import os
import subprocess
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from docx import Document

from app.services.report_context import build_report_context
from app.services.report_pdf_service import render_report_html, try_render_pdf_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = str(PROJECT_ROOT / "templates" / "report_template.docx")


def reports_folder() -> str:
    """Writable folder for generated reports (Lightsail disk or local dev)."""
    from flask import current_app, has_app_context

    if has_app_context():
        folder = current_app.config.get("REPORTS_FOLDER", "reports/")
    else:
        folder = os.environ.get("REPORTS_FOLDER", "reports/")
    folder = str(folder).strip()
    if folder.startswith(("/", "\\")) or (len(folder) > 1 and folder[1] == ":"):
        return folder
    return str(PROJECT_ROOT / folder)


def replace_placeholders(doc: Document, replacements: dict) -> Document:
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
    from app.core.formatters import fmt_inr

    for para in doc.paragraphs:
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


def try_convert_docx_to_pdf(docx_path: str) -> Optional[str]:
    pdf_path = docx_path.replace(".docx", ".pdf")

    if platform.system() == "Windows":
        try:
            from docx2pdf import convert

            convert(docx_path, pdf_path)
            return pdf_path if os.path.exists(pdf_path) else None
        except Exception:
            return None

    try:
        out_dir = os.path.dirname(docx_path) or "."
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                out_dir,
                docx_path,
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        if os.path.exists(pdf_path):
            return pdf_path
    except Exception:
        pass

    return None


def _docx_template_usable() -> bool:
    path = Path(TEMPLATE_PATH)
    return path.is_file() and path.stat().st_size > 0


def _save_html_fallback(context: dict, html_path: str) -> None:
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(render_report_html(context))


def _generate_docx_fallback(context: dict, docx_path: str, goals: list) -> None:
    if not _docx_template_usable():
        raise FileNotFoundError(f"Report template not found: {TEMPLATE_PATH}")

    doc = Document(TEMPLATE_PATH)
    doc = replace_placeholders(doc, context)
    goals_raw = [
        {
            "goal_type": g.goal_type,
            "target_year": g.target_year,
            "today_cost": g.today_cost or 0,
            "future_cost": g.future_cost or 0,
            "monthly_sip": g.monthly_sip or 0,
        }
        for g in goals
    ]
    doc = insert_goals_table(doc, goals_raw)
    doc.save(docx_path)


def generate_report(
    assessment_id: str,
    calc: object,
    personal: object,
    comm: object,
    goals: list,
) -> dict:
    """
    Generate a designed PDF report for production.
    Primary: HTML template → PDF (WeasyPrint).
    Fallback: DOCX template → LibreOffice/Word PDF.
    """
    os.makedirs(reports_folder(), exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"report_{assessment_id[:8]}_{timestamp}"
    pdf_path = os.path.join(reports_folder(), f"{file_name}.pdf")
    docx_path = os.path.join(reports_folder(), f"{file_name}.docx")
    html_path = os.path.join(reports_folder(), f"{file_name}.html")

    context = build_report_context(assessment_id, calc, personal, comm, goals)

    pdf_created = try_render_pdf_report(context, pdf_path)
    if not pdf_created:
        pdf_path = None

    if not pdf_path and _docx_template_usable():
        _generate_docx_fallback(context, docx_path, goals)
        pdf_path = try_convert_docx_to_pdf(docx_path) or None

    if pdf_path and os.path.exists(pdf_path):
        attach_path = pdf_path
        attach_name = f"{file_name}.pdf"
    elif os.path.exists(docx_path):
        attach_path = docx_path
        attach_name = f"{file_name}.docx"
    else:
        _save_html_fallback(context, html_path)
        attach_path = html_path
        attach_name = f"{file_name}.html"

    result = {
        "file_name": attach_name,
        "docx_path": docx_path if os.path.exists(docx_path) else None,
        "pdf_path": pdf_path,
        "attach_path": attach_path,
        "attach_name": attach_name,
    }

    from app.services.s3_storage import persist_report_files

    return persist_report_files(result, str(assessment_id))
