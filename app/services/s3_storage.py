"""S3 persistence for generated report files."""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from typing import Optional

from app.core.exceptions import APIError

S3_URI_PREFIX = "s3:"


def s3_enabled() -> bool:
    return bool(os.environ.get("AWS_S3_BUCKET"))


def is_storage_key(path: Optional[str]) -> bool:
    return bool(path and path.startswith(S3_URI_PREFIX))


def build_storage_key(assessment_id: str, file_name: str) -> str:
    prefix = os.environ.get("AWS_S3_REPORT_PREFIX", "reports").strip("/")
    safe_name = os.path.basename(file_name)
    return f"{S3_URI_PREFIX}{prefix}/{assessment_id}/{safe_name}"


def storage_key_to_object_key(storage_key: str) -> str:
    if not is_storage_key(storage_key):
        return storage_key
    return storage_key[len(S3_URI_PREFIX) :]


@lru_cache(maxsize=1)
def _s3_client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    kwargs = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs)


def _bucket_name() -> str:
    bucket = os.environ.get("AWS_S3_BUCKET")
    if not bucket:
        raise APIError(
            "CONFIG_ERROR",
            "AWS_S3_BUCKET is not configured.",
            http_status=500,
        )
    return bucket


def upload_local_file(local_path: str, storage_key: str, content_type: str) -> str:
    if not os.path.exists(local_path):
        raise APIError("NOT_FOUND", "Report file missing before S3 upload.", http_status=404)

    object_key = storage_key_to_object_key(storage_key)
    with open(local_path, "rb") as handle:
        _s3_client().put_object(
            Bucket=_bucket_name(),
            Key=object_key,
            Body=handle,
            ContentType=content_type,
        )
    return storage_key


def upload_bytes(body: bytes, storage_key: str, content_type: str) -> str:
    object_key = storage_key_to_object_key(storage_key)
    _s3_client().put_object(
        Bucket=_bucket_name(),
        Key=object_key,
        Body=body,
        ContentType=content_type,
    )
    return storage_key


def build_import_storage_key(import_id: str, file_name: str) -> str:
    prefix = os.environ.get("AWS_S3_IMPORT_PREFIX", "imports").strip("/")
    safe_name = os.path.basename(file_name) or "upload.bin"
    return f"{S3_URI_PREFIX}{prefix}/{import_id}/{safe_name}"


def content_type_for_spreadsheet(file_name: str) -> str:
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext == ".csv":
        return "text/csv"
    if ext == ".xls":
        return "application/vnd.ms-excel"
    if ext in {".xlsx", ".xlsm"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "application/octet-stream"


def persist_import_spreadsheet(
    raw: bytes,
    file_name: str,
    import_id: str,
) -> dict:
    """Upload admin import spreadsheet to S3 when configured."""
    if not s3_enabled():
        return {}

    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = os.path.basename(file_name) or "upload.bin"
    storage_key = build_import_storage_key(import_id, f"{timestamp}_{base}")

    upload_bytes(raw, storage_key, content_type_for_spreadsheet(file_name))

    return {
        "import_id": import_id,
        "import_storage_key": storage_key,
        "import_file_name": base,
    }


def download_bytes(storage_key: str) -> bytes:
    from botocore.exceptions import ClientError

    object_key = storage_key_to_object_key(storage_key)
    try:
        response = _s3_client().get_object(Bucket=_bucket_name(), Key=object_key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise APIError("NOT_FOUND", "Report file missing in S3.", http_status=404) from exc
        raise APIError(
            "INTERNAL_ERROR",
            f"Failed to download report from S3: {exc}",
            http_status=500,
        ) from exc
    except Exception as exc:
        raise APIError(
            "INTERNAL_ERROR",
            f"Failed to download report from S3: {exc}",
            http_status=500,
        ) from exc
    return response["Body"].read()


def object_exists(storage_key: str) -> bool:
    if not s3_enabled() or not is_storage_key(storage_key):
        return False
    object_key = storage_key_to_object_key(storage_key)
    try:
        _s3_client().head_object(Bucket=_bucket_name(), Key=object_key)
        return True
    except Exception:
        return False


def object_size_bytes(storage_key: str) -> Optional[int]:
    if not s3_enabled() or not is_storage_key(storage_key):
        return None
    object_key = storage_key_to_object_key(storage_key)
    try:
        response = _s3_client().head_object(Bucket=_bucket_name(), Key=object_key)
        return int(response.get("ContentLength") or 0)
    except Exception:
        return None


def content_type_for_format(fmt: str) -> str:
    if (fmt or "").lower() == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/pdf"


def persist_report_files(result: dict, assessment_id: str) -> dict:
    """Upload generated report artifact to S3 when configured."""
    if not s3_enabled():
        return result

    attach_local = result.get("attach_path") or result.get("docx_path")
    attach_name = result.get("attach_name") or os.path.basename(attach_local or "report.docx")
    # Prefer unique on-disk basename for the S3 object; keep attach_name for downloads.
    storage_basename = (
        os.path.basename(attach_local) if attach_local else attach_name
    )
    fmt = "pdf" if result.get("pdf_path") else "docx"
    storage_key = build_storage_key(assessment_id, storage_basename)

    upload_local_file(
        attach_local,
        storage_key,
        content_type_for_format(fmt),
    )

    result["storage_key"] = storage_key
    result["attach_path"] = storage_key
    result["attach_name"] = attach_name

    for path_key in ("docx_path", "pdf_path"):
        local_path = result.get(path_key)
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass

    return result


def resolve_local_attachment_path(storage_key_or_path: str, download_name: str) -> str:
    """Return a local filesystem path for email attachments."""
    if not is_storage_key(storage_key_or_path):
        return storage_key_or_path

    suffix = os.path.splitext(download_name)[1] or ".bin"
    payload = download_bytes(storage_key_or_path)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(payload)
    handle.close()
    return handle.name
