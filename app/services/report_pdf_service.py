"""Render designed HTML report templates to PDF."""
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates" / "report"
HTML_TEMPLATE = "report.html"


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_report_html(context: dict) -> str:
    template = _jinja_env().get_template(HTML_TEMPLATE)
    return template.render(**context)


def render_report_pdf(html: str, pdf_path: str) -> bool:
    """Convert rendered HTML to PDF. Returns True on success."""
    try:
        from weasyprint import HTML

        HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(pdf_path)
        return os.path.exists(pdf_path)
    except Exception:
        return False


def try_render_pdf_report(context: dict, pdf_path: str) -> bool:
    if not TEMPLATE_DIR.joinpath(HTML_TEMPLATE).exists():
        return False
    html = render_report_html(context)
    return render_report_pdf(html, pdf_path)
