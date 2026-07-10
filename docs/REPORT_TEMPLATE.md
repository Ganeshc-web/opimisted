# Report PDF Template

Production reports are **designed PDFs** with static branding/layout and **dynamic client values**.

## How it works

```
templates/report/report.html   ← design this (HTML + CSS)
        ↓
Jinja2 fills {{ variables }} with assessment data
        ↓
WeasyPrint renders HTML → PDF (Lightsail)
        ↓
PDF uploaded to S3 → admin download / client email
```

**Edit `templates/report/report.html`** — not Word, not a raw PDF file.

- **Static:** colours, logo, fonts, section layout, tables, footer (hard-coded HTML/CSS)
- **Dynamic:** `{{ client_name }}`, `{% for g in goals %}`, etc.

Fallback if WeasyPrint unavailable: legacy `report_template.docx` → LibreOffice.

---

## Customise the design

Open `templates/report/report.html` in any code editor.

| Change | Where |
|--------|--------|
| Colours / fonts | `<style>` block at top |
| Logo | Add `<img src="logo.png">` in `.header` (put image in `templates/report/`) |
| Section order | Rearrange HTML blocks |
| Hide spouse section | Already wrapped in `{% if has_spouse %}` |
| Add new field | Add to `report_context.py` + use in HTML |

---

## Dynamic variables (Jinja2)

All variables from `build_report_context()` in `app/services/report_context.py`:

`client_name`, `client_age`, `client_corpus`, `client_monthly_sip`, `goals` (list), `total_insurance_required`, `inflation_pre`, etc.

Goals loop example (already in template):

```html
{% for g in goals %}
  <tr>
    <td>{{ g.goal_type }}</td>
    <td>{{ g.target_year }}</td>
    ...
  </tr>
{% endfor %}
```

---

## Test locally

```bash
pip install weasyprint
python -c "from app.services.report_pdf_service import render_report_html; print('ok')"
```

On Windows, WeasyPrint may need extra setup — production on Lightsail is the target.

---

## Lightsail dependencies

```bash
sudo apt install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev
pip install weasyprint
```

---

## Who uses this PDF

- Admin **Reports Log** download
- Admin **Users & Assessments** PDF button
- Client report email / download

Same template for all.
