import os
from unittest.mock import patch

from app.services.s3_storage import (
    S3_URI_PREFIX,
    build_storage_key,
    is_storage_key,
    persist_report_files,
    storage_key_to_object_key,
)


def test_build_storage_key():
    key = build_storage_key("abc-123", "report_abc.pdf")
    assert key == f"{S3_URI_PREFIX}reports/abc-123/report_abc.pdf"
    assert is_storage_key(key)
    assert storage_key_to_object_key(key) == "reports/abc-123/report_abc.pdf"


@patch.dict(os.environ, {"AWS_S3_BUCKET": "wealth-reports"}, clear=False)
@patch("app.services.s3_storage.upload_local_file")
def test_persist_report_files_uploads_and_replaces_path(mock_upload, tmp_path):
    local_file = tmp_path / "report.docx"
    local_file.write_bytes(b"PK docx")

    result = {
        "docx_path": str(local_file),
        "pdf_path": None,
        "attach_path": str(local_file),
        "attach_name": "report_test.docx",
    }

    updated = persist_report_files(result, "assessment-1")

    mock_upload.assert_called_once()
    assert updated["attach_path"].startswith(S3_URI_PREFIX)
    assert is_storage_key(updated["attach_path"])


def test_persist_report_files_skips_without_bucket(tmp_path):
    local_file = tmp_path / "report.docx"
    local_file.write_bytes(b"PK docx")
    result = {
        "attach_path": str(local_file),
        "attach_name": "report_test.docx",
    }

    env = os.environ.copy()
    env.pop("AWS_S3_BUCKET", None)
    with patch.dict(os.environ, env, clear=True):
        updated = persist_report_files(result, "assessment-1")

    assert updated["attach_path"] == str(local_file)
