"""Excel export and spreadsheet-to-PDF conversion for admin panel."""
import csv
import io
import os
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

from app.core.exceptions import APIError

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def rows_to_xlsx_bytes(rows: list[dict[str, Any]], sheet_name: str = "Export") -> bytes:
    """Convert list-of-dicts to an Excel workbook in memory."""
    return sheets_to_xlsx_bytes({sheet_name: rows})


def sheets_to_xlsx_bytes(sheets: dict[str, list[dict[str, Any]]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            pd.DataFrame(rows or []).to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buffer.seek(0)
    return buffer.read()


def _read_spreadsheet(file_storage) -> dict[str, list[list[Any]]]:
    filename = file_storage.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise APIError(
            "INVALID_INPUT",
            "Only CSV, XLS, and XLSX files are supported.",
            field="file",
            http_status=400,
        )

    raw = file_storage.read()
    if not raw:
        raise APIError("INVALID_INPUT", "Uploaded file is empty.", field="file", http_status=400)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise APIError(
            "INVALID_INPUT",
            "File exceeds 12MB limit.",
            field="file",
            http_status=400,
        )

    if ext == ".csv":
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        return {"Sheet1": [row for row in reader]}

    excel = pd.ExcelFile(io.BytesIO(raw))
    sheets: dict[str, list[list[Any]]] = {}
    for sheet_name in excel.sheet_names:
        df = excel.parse(sheet_name)
        df = df.fillna("")
        rows = [df.columns.astype(str).tolist()] + df.astype(str).values.tolist()
        sheets[sheet_name] = rows
    return sheets


def _sheet_to_table(rows: list[list[Any]]) -> Table | None:
    if not rows:
        return None
    cleaned = []
    for row in rows:
        cleaned.append([str(cell) if cell is not None else "" for cell in row])
    max_cols = max((len(r) for r in cleaned), default=0)
    if max_cols == 0:
        return None
    normalized = [r + [""] * (max_cols - len(r)) for r in cleaned]
    table = Table(normalized, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2B7FFF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def spreadsheet_to_pdf_bytes(file_storage) -> tuple[bytes, str]:
    """Convert uploaded spreadsheet to a simple tabular PDF."""
    sheets = _read_spreadsheet(file_storage)
    filename = file_storage.filename or "upload"
    out_name = f"{os.path.splitext(filename)[0]}.pdf"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), title=out_name)
    styles = getSampleStyleSheet()
    story = []

    for index, (sheet_name, rows) in enumerate(sheets.items()):
        if index > 0:
            story.append(PageBreak())
        story.append(Paragraph(sheet_name, styles["Heading2"]))
        table = _sheet_to_table(rows)
        if table is None:
            story.append(Paragraph("(empty sheet)", styles["Normal"]))
        else:
            story.append(table)

    if not story:
        raise APIError("INVALID_INPUT", "Spreadsheet has no readable data.", http_status=400)

    doc.build(story)
    buffer.seek(0)
    return buffer.read(), out_name
