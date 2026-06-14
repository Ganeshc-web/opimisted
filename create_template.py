"""Generate templates/report_template.docx with placeholder variables."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

PLACEHOLDERS = {
    "CLIENT INFORMATION": [
        "{{client_name}}",
        "{{client_age}}",
        "{{client_occupation}}",
        "{{client_company}}",
        "{{client_dob}}",
        "{{spouse_name}}",
        "{{spouse_age}}",
        "{{spouse_occupation}}",
        "{{spouse_company}}",
        "{{spouse_dob}}",
        "{{mobile}}",
        "{{email}}",
        "{{residential_address}}",
        "{{report_date}}",
        "{{assessment_id}}",
    ],
    "RETIREMENT CALCULATIONS": [
        "{{client_corpus}}",
        "{{client_pf_corpus}}",
        "{{client_net_corpus}}",
        "{{client_monthly_sip}}",
        "{{client_lump_sum}}",
        "{{client_retirement_age}}",
        "{{client_years_to_retirement}}",
        "{{client_expense_today}}",
        "{{client_expense_at_retirement}}",
        "{{spouse_corpus}}",
        "{{spouse_pf_corpus}}",
        "{{spouse_net_corpus}}",
        "{{spouse_monthly_sip}}",
        "{{spouse_lump_sum}}",
        "{{spouse_retirement_age}}",
        "{{spouse_years_to_retirement}}",
        "{{spouse_expense_today}}",
        "{{spouse_expense_at_retirement}}",
    ],
    "GOALS": [
        "{{goals_table}}",
    ],
    "INSURANCE": [
        "{{total_insurance_required}}",
    ],
    "RATES USED": [
        "{{inflation_pre}}",
        "{{roi_pre}}",
        "{{inflation_post}}",
        "{{roi_post}}",
        "{{calculated_at}}",
    ],
}


def add_section_heading(document: Document, text: str) -> None:
    heading = document.add_heading(text, level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT


def add_placeholder_paragraph(document: Document, placeholder: str) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(placeholder)
    run.font.size = Pt(11)


def build_template() -> Document:
    document = Document()

    title = document.add_heading("Retirement Planning Report — Wealth Wisdom", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    document.add_paragraph()

    for section_name, placeholders in PLACEHOLDERS.items():
        add_section_heading(document, f"{section_name}:")
        for placeholder in placeholders:
            add_placeholder_paragraph(document, placeholder)
        document.add_paragraph()

    return document


def main() -> None:
    output_path = Path(__file__).resolve().parent / "templates" / "report_template.docx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = build_template()
    document.save(output_path)
    print(f"Template created: {output_path}")


if __name__ == "__main__":
    main()
