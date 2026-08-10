"""Send stored reports from local disk or S3."""
from io import BytesIO

from flask import send_file

from app.services.report_delivery import report_mimetype
from app.services.s3_storage import download_bytes, is_storage_key


def send_stored_report(delivery: dict):
    file_name = delivery["file_name"]
    fmt = delivery.get("format") or "pdf"
    mimetype = report_mimetype(fmt)

    storage_key = delivery.get("storage_key")
    file_path = delivery.get("file_path")

    if storage_key and is_storage_key(storage_key):
        payload = download_bytes(storage_key)
        return send_file(
            BytesIO(payload),
            as_attachment=True,
            download_name=file_name,
            mimetype=mimetype,
        )

    return send_file(
        file_path,
        as_attachment=True,
        download_name=file_name,
        mimetype=mimetype,
    )
