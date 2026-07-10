from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Lock, Semaphore
import uuid

from flask import current_app, request, send_file
from flask_restx import Namespace, Resource, fields

from app import db
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.personal import PersonalDetails
from app.models.communication import CommunicationDetails
from app.models.goals import Goal
from app.models.report_log import ReportLog
from app.middleware.auth import require_api_key
from app.services.report_delivery import ensure_report_file
from app.services.report_http import send_stored_report
from app.services.report_service import PROJECT_ROOT, generate_report
from app.services.s3_storage import is_storage_key, resolve_local_attachment_path
from app.services.email_service import maybe_send_report_email, send_report_email
from app.core.exceptions import APIError
from app.core.swagger_models import error_model

ns = Namespace(
    "report",
    description=(
        "Asynchronous PDF report generation, job status polling, report "
        "download, and report history for completed assessments."
    ),
    path="/report",
)

report_response_model = ns.model("ReportResponse", {
    "status": fields.String(required=True, description="Response status.", example="processing"),
    "data": fields.Raw(required=True, description="Endpoint-specific report payload."),
    "timestamp": fields.String(required=True, description="UTC timestamp for the response.", example="2026-06-27T13:30:00+00:00"),
})

bulk_report_input_model = ns.model("BulkReportGenerateInput", {
    "assessment_ids": fields.List(
        fields.String(required=True, description="Assessment UUID.", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
        required=True,
        description="Assessment UUIDs to generate reports for; maximum 100.",
        example=["f47ac10b-58cc-4372-a567-0e02b2c3d479"],
    ),
})
REPORT_EXECUTOR = ThreadPoolExecutor(max_workers=5)
REPORT_GENERATION_SEMAPHORE = Semaphore(5)
REPORT_JOBS = {}
REPORT_JOBS_LOCK = Lock()


def report_success_response(data):
    return {
        "status": "success",
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def parse_uuid_param(value, field_name):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise APIError(
            "INVALID_INPUT",
            f"{field_name} must be a valid UUID.",
            field=field_name,
            http_status=400,
        )


def run_report_job(app, job_id, assessment_id):
    with app.app_context():
        try:
            calc = CalculationOutput.query.filter_by(
                assessment_id=assessment_id
            ).order_by(CalculationOutput.calculated_at.desc()).first()
            if not calc:
                return {
                    "status": "failed",
                    "message": "Run /calculate first before generating report.",
                }

            personal = PersonalDetails.query.filter_by(
                assessment_id=assessment_id
            ).first()
            comm = CommunicationDetails.query.filter_by(
                assessment_id=assessment_id
            ).first()
            goals = Goal.query.filter_by(assessment_id=assessment_id).all()

            if not personal or not comm:
                return {
                    "status": "failed",
                    "message": "Complete flows 1 and 2 before generating report.",
                }

            with REPORT_GENERATION_SEMAPHORE:
                result = generate_report(str(assessment_id), calc, personal, comm, goals)

            file_path = result.get("attach_path") or result["docx_path"]
            file_name = result["attach_name"]
            fmt = "pdf" if result.get("pdf_path") else "docx"
            if is_storage_key(file_path):
                fmt = "pdf" if file_name.lower().endswith(".pdf") else "docx"

            log = ReportLog(
                assessment_id=assessment_id,
                calculation_id=calc.id,
                triggered_by="user",
                file_name=file_name,
                file_path=file_path,
                format=fmt,
                generated_at=datetime.now(timezone.utc),
            )
            db.session.add(log)
            db.session.commit()

            if comm.consent:
                attachment_path = resolve_local_attachment_path(file_path, file_name)
                try:
                    maybe_send_report_email(
                        personal, comm, attachment_path, file_name
                    )
                finally:
                    if attachment_path != file_path and os.path.exists(attachment_path):
                        try:
                            os.remove(attachment_path)
                        except OSError:
                            pass

            return {
                "status": "completed",
                "job_id": job_id,
                "report_id": str(log.id),
                "file_name": log.file_name,
                "generated_at": log.generated_at.isoformat(),
            }
        except Exception as exc:
            db.session.rollback()
            return {
                "status": "failed",
                "job_id": job_id,
                "message": str(exc),
            }


def validate_bulk_size(items, max_items, label):
    if not isinstance(items, list):
        raise APIError(
            "INVALID_INPUT",
            f"{label} must be a list.",
            field=label,
            http_status=400,
        )
    if len(items) > max_items:
        raise APIError(
            "INVALID_INPUT",
            f"Maximum {max_items} items per bulk request",
            field=label,
            http_status=400,
        )


def submit_report_job(app, assessment_id):
    job_id = str(uuid.uuid4())
    future = REPORT_EXECUTOR.submit(run_report_job, app, job_id, assessment_id)
    with REPORT_JOBS_LOCK:
        REPORT_JOBS[job_id] = {
            "assessment_id": assessment_id,
            "future": future,
            "submitted_at": datetime.now(timezone.utc),
        }
    return job_id


def generate_and_deliver_report(assessment_id):
    """Generate report; email client when consent is true, else return file."""
    assessment_id = parse_uuid_param(assessment_id, "assessment_id")

    record = db.session.get(AssessmentRecord, assessment_id)
    if not record:
        raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

    calc = CalculationOutput.query.filter_by(
        assessment_id=assessment_id
    ).order_by(CalculationOutput.calculated_at.desc()).first()
    if not calc:
        raise APIError(
            "INVALID_INPUT",
            "Run /calculate first before generating report.",
            http_status=400,
        )

    personal = PersonalDetails.query.filter_by(
        assessment_id=assessment_id
    ).first()
    comm = CommunicationDetails.query.filter_by(
        assessment_id=assessment_id
    ).first()
    goals = Goal.query.filter_by(assessment_id=assessment_id).all()

    if not personal or not comm:
        raise APIError(
            "INVALID_INPUT",
            "Complete flows 1 and 2 before generating report.",
            http_status=400,
        )

    with REPORT_GENERATION_SEMAPHORE:
        result = generate_report(str(assessment_id), calc, personal, comm, goals)

    send_path = result.get("attach_path") or result["docx_path"]
    download_name = result.get("attach_name") or result["file_name"]
    if result.get("pdf_path"):
        fmt = "pdf"
    elif download_name.lower().endswith(".docx"):
        fmt = "docx"
    elif download_name.lower().endswith(".html"):
        fmt = "html"
    else:
        fmt = "pdf"
    if is_storage_key(send_path):
        fmt = "pdf" if download_name.lower().endswith(".pdf") else "docx"

    log = ReportLog(
        assessment_id=assessment_id,
        calculation_id=calc.id,
        triggered_by="user",
        file_name=download_name,
        file_path=send_path,
        format=fmt,
        generated_at=datetime.now(timezone.utc),
    )
    db.session.add(log)
    db.session.commit()

    if comm.consent:
        attachment_path = resolve_local_attachment_path(send_path, download_name)
        try:
            email_result = send_report_email(
                personal, comm, attachment_path, download_name
            )
        except APIError as exc:
            if exc.code != "EMAIL_QUOTA_EXCEEDED":
                raise
            email_result = None
        finally:
            if attachment_path != send_path and os.path.exists(attachment_path):
                try:
                    os.remove(attachment_path)
                except OSError:
                    pass
        if email_result:
            return report_success_response(
                {
                    "message": "Report sent to your email.",
                    "delivery_mode": "email",
                    "report_id": str(log.id),
                    "format": log.format,
                    "generated_at": log.generated_at.isoformat(),
                    **email_result,
                }
            )

    return send_stored_report(
        {
            "storage_key": send_path if is_storage_key(send_path) else None,
            "file_path": send_path if not is_storage_key(send_path) else None,
            "file_name": download_name,
            "format": fmt,
        }
    )


@ns.route("/<string:assessment_id>/generate")
class ReportGenerate(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Generates the report. If the client gave email consent, the report is "
            "sent directly to their email (Flow 1 email) and a JSON confirmation is "
            "returned. After the daily email cap (499 by default), consenting clients "
            "receive a file download instead. Without consent, the report file is "
            "returned as a download."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.response(200, "Accepted for processing", report_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        """Generate report and deliver via email or file download."""
        return generate_and_deliver_report(assessment_id)


@ns.route("/<string:assessment_id>/download")
class ReportDownloadTrigger(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Same as /generate: sends the report directly to the client's email "
            "when consent is true (until the daily email cap is reached, then "
            "returns a file download); otherwise returns the file download."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path")
    @ns.response(200, "Email sent or file download", report_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        """Download button: email report to client when consent is given."""
        return generate_and_deliver_report(assessment_id)


@ns.route("/bulk-generate")
class ReportBulkGenerate(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Starts asynchronous PDF report generation for multiple assessments. "
            "All IDs are validated before any jobs are submitted; conversions run "
            "with at most five concurrent workers."
        ),
    )
    @ns.expect(bulk_report_input_model, validate=True)
    @ns.response(200, "Accepted for processing", report_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self):
        """Generate PDF reports for multiple assessments."""
        payload = request.get_json(silent=True) or {}
        assessment_ids = payload.get("assessment_ids", [])
        validate_bulk_size(assessment_ids, 100, "assessment_ids")

        parsed_ids = []
        for index, assessment_id in enumerate(assessment_ids):
            try:
                parsed_ids.append(uuid.UUID(str(assessment_id)))
            except (TypeError, ValueError):
                raise APIError(
                    "INVALID_INPUT",
                    f"Item {index} failed validation: invalid assessment_id",
                    field="assessment_ids",
                    http_status=400,
                )

        existing_ids = {
            row[0]
            for row in db.session.execute(
                db.select(AssessmentRecord.id).where(AssessmentRecord.id.in_(parsed_ids))
            ).all()
        }
        for index, assessment_id in enumerate(parsed_ids):
            if assessment_id not in existing_ids:
                raise APIError(
                    "NOT_FOUND",
                    f"Item {index} failed validation: assessment not found",
                    field="assessment_ids",
                    http_status=404,
                )

        app = current_app._get_current_object()
        jobs = [
            {
                "assessment_id": str(assessment_id),
                "job_id": submit_report_job(app, assessment_id),
            }
            for assessment_id in parsed_ids
        ]

        return {
            "status": "processing",
            "data": {"jobs": jobs},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@ns.route("/<string:assessment_id>/status/<string:job_id>")
class ReportStatus(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Polls an asynchronous report generation job. Returns processing "
            "while the job is running, success when completed, or failed if "
            "generation raised an error."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.param("job_id", "Report generation job UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.response(200, "Success or still processing", report_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    @ns.response(500, "Report generation failed", error_model)
    def get(self, assessment_id, job_id):
        """Poll a background report generation job."""
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")
        with REPORT_JOBS_LOCK:
            job = REPORT_JOBS.get(job_id)

        if not job or job["assessment_id"] != assessment_id:
            raise APIError("NOT_FOUND", "Report job not found.", http_status=404)

        future = job["future"]
        if not future.done():
            return {
                "status": "processing",
                "data": {
                    "job_id": job_id,
                    "assessment_id": str(assessment_id),
                    "submitted_at": job["submitted_at"].isoformat(),
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        result = future.result()
        if result["status"] == "failed":
            return {
                "status": "failed",
                "data": result,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, 500

        return report_success_response(result)


@ns.route("/<string:assessment_id>/download/<string:report_id>")
class ReportDownload(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Downloads a generated report. On first download, if the client gave "
            "email consent and the daily email cap has not been reached, the report "
            "is also sent to their email."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.param("report_id", "ReportLog UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.response(200, "PDF file download")
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def get(self, assessment_id, report_id):
        """Download generated PDF report."""
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")
        report_id = parse_uuid_param(report_id, "report_id")

        log = ReportLog.query.filter_by(
            id=report_id, assessment_id=assessment_id
        ).first()
        if not log:
            raise APIError("NOT_FOUND", "Report not found.", http_status=404)

        delivery = ensure_report_file(log)

        personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
        comm = CommunicationDetails.query.filter_by(assessment_id=assessment_id).first()
        first_download = log.downloaded_at is None

        if first_download and personal and comm and comm.consent:
            attachment_path = resolve_local_attachment_path(
                log.file_path, delivery["file_name"]
            )
            try:
                maybe_send_report_email(
                    personal, comm, attachment_path, delivery["file_name"]
                )
            finally:
                if attachment_path != log.file_path and os.path.exists(attachment_path):
                    try:
                        os.remove(attachment_path)
                    except OSError:
                        pass

        log.downloaded_at = datetime.now(timezone.utc)
        db.session.commit()

        return send_stored_report(delivery)


@ns.route("/<string:assessment_id>/history")
class ReportHistory(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description=(
            "Lists generated reports for an assessment, newest first. Use this "
            "to find report IDs for download."
        ),
    )
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path", example="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    @ns.response(200, "Success", report_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(404, "Resource not found", error_model)
    def get(self, assessment_id):
        """List all generated reports for an assessment."""
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")

        logs = ReportLog.query.filter_by(
            assessment_id=assessment_id
        ).order_by(ReportLog.generated_at.desc()).all()

        return {
            "status": "success",
            "data": [
                {
                    "report_id":     str(l.id),
                    "file_name":     l.file_name,
                    "format":        l.format,
                    "generated_at":  l.generated_at.isoformat(),
                    "downloaded_at": l.downloaded_at.isoformat() if l.downloaded_at else None,
                }
                for l in logs
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


send_email_input_model = ns.model("ReportSendEmailInput", {
    "subject": fields.String(
        required=False,
        description="Email subject. If omitted, a default subject is used.",
        example="Your Financial Planning Report",
    ),
    "body": fields.String(
        required=False,
        description="Email body (plain text). If omitted, a default body is used.",
        example="Dear Client, Please find your report attached.",
    ),
})


@ns.route("/<string:assessment_id>/send-email")
class ReportSendEmail(Resource):
    @require_api_key
    @ns.doc(
        security="apikey",
        description="Generates (if needed) and emails the report as an attachment via SMTP.",
    )
    @ns.expect(send_email_input_model, validate=True)
    @ns.param("assessment_id", "Assessment UUID.", type=str, required=True, _in="path")
    @ns.response(200, "Email sent", report_response_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Consent missing", error_model)
    @ns.response(404, "Resource not found", error_model)
    def post(self, assessment_id):
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")

        record = db.session.get(AssessmentRecord, assessment_id)
        if not record:
            raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

        comm = CommunicationDetails.query.filter_by(assessment_id=assessment_id).first()
        personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
        if not personal or not comm:
            raise APIError(
                "INVALID_INPUT",
                "Complete flows 1 and 2 before sending email.",
                http_status=400,
            )

        if not comm.consent:
            raise APIError(
                "FORBIDDEN",
                "Client consent is required to send the report via email.",
                http_status=403,
            )

        calc = CalculationOutput.query.filter_by(
            assessment_id=assessment_id
        ).order_by(CalculationOutput.calculated_at.desc()).first()
        if not calc:
            raise APIError(
                "INVALID_INPUT",
                "Run /calculate first before generating report.",
                http_status=400,
            )

        goals = Goal.query.filter_by(assessment_id=assessment_id).all()

        payload = request.get_json(silent=True) or {}

        with REPORT_GENERATION_SEMAPHORE:
            result = generate_report(str(assessment_id), calc, personal, comm, goals)

        attach_path = result.get("attach_path") or result.get("docx_path")
        attach_name = result.get("attach_name") or result.get("file_name")

        if not attach_path:
            raise APIError(
                "NOT_FOUND",
                "Report file missing on server.",
                http_status=404,
            )
        if not is_storage_key(attach_path) and not os.path.exists(attach_path):
            raise APIError(
                "NOT_FOUND",
                "Report file missing on server.",
                http_status=404,
            )

        attachment_path = resolve_local_attachment_path(attach_path, attach_name)
        try:
            email_result = send_report_email(
                personal,
                comm,
                attachment_path,
                attach_name,
                subject=payload.get("subject"),
                body=payload.get("body"),
            )
        finally:
            if attachment_path != attach_path and os.path.exists(attachment_path):
                try:
                    os.remove(attachment_path)
                except OSError:
                    pass

        fmt = "pdf" if attach_name.lower().endswith(".pdf") else "docx"
        log = ReportLog(
            assessment_id=assessment_id,
            calculation_id=calc.id,
            triggered_by="email",
            file_name=attach_name,
            file_path=attach_path,
            format=fmt,
            generated_at=datetime.now(timezone.utc),
        )
        db.session.add(log)
        db.session.commit()

        return report_success_response(
            {
                **email_result,
                "format": fmt,
                "report_id": str(log.id),
                "generated_at": log.generated_at.isoformat(),
            }
        )
