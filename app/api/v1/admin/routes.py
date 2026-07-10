import os
import uuid
from datetime import datetime, timezone
from io import BytesIO

from flask import g, request, send_file
from flask_restx import Namespace, Resource, fields
from marshmallow import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app import db
from app.core.exceptions import APIError
from app.core.swagger_models import error_model
from app.core.validators import (
    ApiKeyCreateSchema,
    TestimonialSchema,
    TestimonialUpdateSchema,
)
from app.middleware.auth import require_admin
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.communication import CommunicationDetails
from app.models.get_in_touch import GetInTouchLead
from app.models.goals import Goal
from app.models.personal import PersonalDetails
from app.models.report_log import ReportLog
from app.models.testimonial import Testimonial
from app.services.excel_service import (
    rows_to_xlsx_bytes,
    sheets_to_xlsx_bytes,
)
from app.services.assessment_import_service import (
    IMPORT_TEMPLATE_SAMPLE,
    import_assessments_from_upload,
)
from app.services.report_delivery import (
    ensure_report_file,
    report_is_available,
    report_size_bytes,
)
from app.services.report_http import send_stored_report
from app.services.marketing_campaign_service import (
    consented_recipient_emails,
    normalize_recipients,
    read_campaign_attachments,
    send_marketing_campaign,
)
from app.services.api_key_service import (
    activate_api_key,
    create_api_key,
    list_api_keys,
    revoke_api_key,
    serialize_api_key,
)
from app.services.testimonial_service import (
    assert_can_delete,
    assert_can_set_visible,
    serialize_testimonial,
    touch_updated_at,
)

ns = Namespace(
    "admin",
    description=(
        "Admin-only endpoints for the executive dashboard: leads, unique "
        "users, completed assessments, and generated reports."
    ),
    path="/admin",
)

list_query_model = ns.parser()
list_query_model.add_argument(
    "page", type=int, location="args", default=1, help="Page number (default 1)"
)
list_query_model.add_argument(
    "per_page",
    type=int,
    location="args",
    default=100,
    help="Rows per page (default 100, max 100)",
)
list_query_model.add_argument(
    "from_date",
    type=str,
    location="args",
    required=False,
    help="Filter from created date (YYYY-MM-DD, inclusive)",
)
list_query_model.add_argument(
    "to_date",
    type=str,
    location="args",
    required=False,
    help="Filter to created date (YYYY-MM-DD, inclusive)",
)
list_query_model.add_argument(
    "search",
    type=str,
    location="args",
    required=False,
    help="Search by name (case-insensitive partial match)",
)

success_envelope_model = ns.model("AdminSuccessEnvelope", {
    "status": fields.String(required=True, example="success"),
    "data": fields.Raw(required=True),
    "timestamp": fields.String(required=True, example="2026-07-01T10:00:00+00:00"),
})


def success_response(data):
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


def iso_or_none(value):
    return value.isoformat() if value else None


def parse_date_param(value, field_name):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise APIError(
            "INVALID_INPUT",
            f"{field_name} must be in YYYY-MM-DD format.",
            field=field_name,
            http_status=400,
        )


def parse_list_filters():
    from_date = parse_date_param(request.args.get("from_date"), "from_date")
    to_date = parse_date_param(request.args.get("to_date"), "to_date")
    if from_date and to_date and from_date > to_date:
        raise APIError(
            "INVALID_INPUT",
            "from_date cannot be after to_date.",
            field="from_date",
            http_status=400,
        )

    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    per_page = request.args.get("per_page", default=100, type=int) or 100
    per_page = min(max(per_page, 1), 100)
    search = (request.args.get("search") or "").strip().lower()
    return from_date, to_date, page, per_page, search


def to_date_value(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def datetime_in_created_range(value, from_date, to_date):
    if value is None:
        return False
    record_date = to_date_value(value)
    if from_date and record_date < from_date:
        return False
    if to_date and record_date > to_date:
        return False
    return True


def matches_name_search(name, search):
    if not search:
        return True
    if not name:
        return False
    return search in name.lower()


def paginate_items(items, page, per_page):
    total = len(items)
    if total == 0:
        return {
            "items": [],
            "total": 0,
            "total_pages": 0,
            "page": page,
            "per_page": per_page,
        }

    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    return {
        "items": items[start : start + per_page],
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "per_page": per_page,
    }


def download_path(report_id):
    if not report_id:
        return None
    return f"/api/v1/admin/reports/{report_id}/download"


def flatten_export_row(row):
    return {
        "name": row.get("name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "assessment_id": row.get("assessment_id"),
        "created_at": row.get("created_at"),
        "report_id": row.get("report_id"),
        "download_path": row.get("download_path"),
        "source": row.get("source"),
        "lead_id": row.get("lead_id"),
    }


def send_xlsx_export(rows, download_name):
    payload = rows_to_xlsx_bytes([flatten_export_row(r) for r in rows])
    return send_file(
        BytesIO(payload),
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_assessment_export_rows(assessment_id):
    record = db.session.get(AssessmentRecord, assessment_id)
    if not record:
        raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

    personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
    comm = CommunicationDetails.query.filter_by(assessment_id=assessment_id).first()
    calc = (
        CalculationOutput.query.filter_by(assessment_id=assessment_id)
        .order_by(CalculationOutput.calculated_at.desc())
        .first()
    )
    goals = Goal.query.filter_by(assessment_id=assessment_id).all()
    report = (
        ReportLog.query.filter_by(assessment_id=assessment_id)
        .order_by(ReportLog.generated_at.desc())
        .first()
    )

    summary = {
        "assessment_id": str(assessment_id),
        "client_name": personal.client_name if personal else None,
        "email": comm.email if comm else None,
        "phone": comm.mobile if comm else None,
        "consent": comm.consent if comm else None,
        "client_age": personal.client_age if personal else None,
        "client_retirement_age": personal.client_retirement_age if personal else None,
        "report_id": str(report.id) if report else None,
        "report_file": report.file_name if report else None,
        "calculated_at": iso_or_none(calc.calculated_at) if calc else None,
        "client_corpus": calc.client_corpus if calc else None,
        "client_monthly_sip": calc.client_monthly_sip if calc else None,
        "total_insurance_required": calc.total_insurance_required if calc else None,
    }

    sheets = {
        "Summary": [summary],
        "Goals": [
            {
                "goal_type": g.goal_type,
                "target_year": g.target_year,
                "today_cost": g.today_cost,
                "future_cost": g.future_cost,
                "monthly_sip": g.monthly_sip,
            }
            for g in goals
        ],
    }

    payload = sheets_to_xlsx_bytes(sheets)
    return payload, f"assessment-{str(assessment_id)[:8]}.xlsx"


def admin_row(
    *,
    name,
    email,
    phone,
    assessment_id,
    created_at,
    report_id=None,
    source=None,
    lead_id=None,
    extra=None,
):
    row = {
        "name": name,
        "email": email,
        "phone": phone,
        "assessment_id": assessment_id,
        "created_at": iso_or_none(created_at),
        "report_id": report_id,
        "download_path": download_path(report_id),
    }
    if source:
        row["source"] = source
    if lead_id:
        row["lead_id"] = lead_id
    if extra:
        row.update(extra)
    return row


def latest_reports_by_assessment():
    subq = (
        db.session.query(
            ReportLog.assessment_id,
            func.max(ReportLog.generated_at).label("max_generated_at"),
        )
        .group_by(ReportLog.assessment_id)
        .subquery()
    )
    rows = (
        db.session.query(ReportLog)
        .join(
            subq,
            (ReportLog.assessment_id == subq.c.assessment_id)
            & (ReportLog.generated_at == subq.c.max_generated_at),
        )
        .all()
    )
    return {row.assessment_id: row for row in rows}


def load_assessment_context():
    records = (
        db.session.execute(
            db.select(AssessmentRecord).order_by(AssessmentRecord.created_at.desc())
        )
        .scalars()
        .all()
    )

    assessment_ids = [record.id for record in records]
    comm_by_assessment = {}
    personal_by_assessment = {}

    if assessment_ids:
        for comm in CommunicationDetails.query.filter(
            CommunicationDetails.assessment_id.in_(assessment_ids)
        ).all():
            comm_by_assessment[comm.assessment_id] = comm

        for personal in PersonalDetails.query.filter(
            PersonalDetails.assessment_id.in_(assessment_ids)
        ).all():
            personal_by_assessment[personal.assessment_id] = personal

    latest_report = latest_reports_by_assessment()
    return records, comm_by_assessment, personal_by_assessment, latest_report


def build_lead_rows(records, comm_by_assessment, personal_by_assessment, latest_report):
    rows = []

    for record in records:
        if not record.flow1_submitted_at:
            continue

        comm = comm_by_assessment.get(record.id)
        personal = personal_by_assessment.get(record.id)
        report = latest_report.get(record.id)
        name = personal.client_name if personal else None

        rows.append(
            admin_row(
                name=name,
                email=comm.email if comm else None,
                phone=comm.mobile if comm else None,
                assessment_id=str(record.id),
                created_at=record.created_at,
                report_id=str(report.id) if report else None,
                source="assessment",
                extra={
                    "flow4_submitted_at": iso_or_none(record.flow4_submitted_at),
                    "report_generated": report is not None,
                },
            )
        )

    for lead in GetInTouchLead.query.order_by(GetInTouchLead.submitted_at.desc()).all():
        rows.append(
            admin_row(
                name=lead.name,
                email=lead.email,
                phone=lead.mobile,
                assessment_id=None,
                created_at=lead.submitted_at,
                source="get_in_touch",
                lead_id=str(lead.id),
                extra={"report_generated": False},
            )
        )

    rows.sort(key=lambda row: row["created_at"] or "", reverse=True)
    return rows


def build_unique_user_rows(records, comm_by_assessment, personal_by_assessment, latest_report):
    users = {}

    for record in records:
        comm = comm_by_assessment.get(record.id)
        if not comm or not comm.email:
            continue

        email_key = comm.email.strip().lower()
        personal = personal_by_assessment.get(record.id)
        report = latest_report.get(record.id)
        name = personal.client_name if personal else None
        created_at = record.created_at

        if email_key not in users:
            users[email_key] = admin_row(
                name=name,
                email=comm.email,
                phone=comm.mobile,
                assessment_id=str(record.id),
                created_at=created_at,
                report_id=str(report.id) if report else None,
            )
            continue

        existing = users[email_key]
        if created_at and (
            not existing["created_at"]
            or created_at.isoformat() < existing["created_at"]
        ):
            existing["created_at"] = iso_or_none(created_at)

        if name and not existing["name"]:
            existing["name"] = name
        if comm.mobile and not existing["phone"]:
            existing["phone"] = comm.mobile

        if report:
            existing["assessment_id"] = str(record.id)
            existing["report_id"] = str(report.id)
            existing["download_path"] = download_path(str(report.id))
            if name:
                existing["name"] = name

    for lead in GetInTouchLead.query.all():
        if not lead.email:
            continue

        email_key = lead.email.strip().lower()
        if email_key not in users:
            users[email_key] = admin_row(
                name=lead.name,
                email=lead.email,
                phone=lead.mobile,
                assessment_id=None,
                created_at=lead.submitted_at,
            )
            continue

        existing = users[email_key]
        if lead.submitted_at and (
            not existing["created_at"]
            or lead.submitted_at.isoformat() < existing["created_at"]
        ):
            existing["created_at"] = iso_or_none(lead.submitted_at)
        if lead.name and not existing["name"]:
            existing["name"] = lead.name
        if lead.mobile and not existing["phone"]:
            existing["phone"] = lead.mobile

    rows = list(users.values())
    rows.sort(key=lambda row: row["created_at"] or "", reverse=True)
    return rows


def build_completed_assessment_rows(
    records, comm_by_assessment, personal_by_assessment, latest_report
):
    rows = []

    for record in records:
        report = latest_report.get(record.id)
        if not report:
            continue

        comm = comm_by_assessment.get(record.id)
        personal = personal_by_assessment.get(record.id)

        rows.append(
            admin_row(
                name=personal.client_name if personal else None,
                email=comm.email if comm else None,
                phone=comm.mobile if comm else None,
                assessment_id=str(record.id),
                created_at=record.created_at,
                report_id=str(report.id),
            )
        )

    rows.sort(key=lambda row: row["created_at"] or "", reverse=True)
    return rows


def apply_list_filters(rows, from_date, to_date, search):
    filtered = []
    for row in rows:
        created_at = row.get("created_at")
        created_dt = (
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_at
            else None
        )
        if not datetime_in_created_range(created_dt, from_date, to_date):
            continue
        if not matches_name_search(row.get("name"), search):
            continue
        filtered.append(row)
    return filtered


@ns.route("/leads")
class AdminLeadsList(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Paginated leads list. Includes Flow 1 assessments and "
            "get-in-touch submissions. Filter by created date; search by name."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """List all leads for the admin panel."""
        from_date, to_date, page, per_page, search = parse_list_filters()
        records, comm_map, personal_map, report_map = load_assessment_context()
        rows = build_lead_rows(records, comm_map, personal_map, report_map)
        rows = apply_list_filters(rows, from_date, to_date, search)
        return success_response(paginate_items(rows, page, per_page))


@ns.route("/users")
class AdminUsersList(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Paginated unique users by email. Filter by earliest created "
            "date; search by name."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """List unique users for the admin panel."""
        from_date, to_date, page, per_page, search = parse_list_filters()
        records, comm_map, personal_map, report_map = load_assessment_context()
        rows = build_unique_user_rows(records, comm_map, personal_map, report_map)
        rows = apply_list_filters(rows, from_date, to_date, search)
        return success_response(paginate_items(rows, page, per_page))


@ns.route("/assessments")
class AdminAssessmentsList(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Paginated completed assessments only (report generated). "
            "Filter by created date; search by name."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """List completed assessments for the admin panel."""
        from_date, to_date, page, per_page, search = parse_list_filters()
        records, comm_map, personal_map, report_map = load_assessment_context()
        rows = build_completed_assessment_rows(
            records, comm_map, personal_map, report_map
        )
        rows = apply_list_filters(rows, from_date, to_date, search)
        return success_response(paginate_items(rows, page, per_page))


def file_size_bytes(file_path):
    return report_size_bytes(file_path)


@ns.route("/reports")
class AdminReportsList(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(
        security="apikey",
        description=(
            "Paginated list of all generated reports. Search by user name; "
            "filter by report generated date (created date for reports)."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """List all generated reports for admin panel."""
        from_date, to_date, page, per_page, search = parse_list_filters()
        Personal = aliased(PersonalDetails)

        rows = (
            db.session.query(ReportLog, Personal)
            .outerjoin(Personal, Personal.assessment_id == ReportLog.assessment_id)
            .order_by(ReportLog.generated_at.desc())
            .all()
        )

        items = []
        for log, personal in rows:
            user_name = personal.client_name if personal else None
            if not matches_name_search(user_name, search):
                continue
            if not datetime_in_created_range(log.generated_at, from_date, to_date):
                continue

            file_path = log.file_path
            items.append(
                {
                    "name": user_name,
                    "email": None,
                    "phone": None,
                    "assessment_id": str(log.assessment_id),
                    "created_at": iso_or_none(log.generated_at),
                    "report_id": str(log.id),
                    "download_path": download_path(str(log.id)),
                    "file_name": log.file_name,
                    "format": log.format,
                    "file_size_bytes": file_size_bytes(file_path),
                    "file_available": report_is_available(file_path),
                }
            )

        return success_response(paginate_items(items, page, per_page))


@ns.route("/reports/<string:report_id>/download")
class AdminReportDownload(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description="Download any generated report by report_id. Admin only.",
    )
    @ns.param(
        "report_id",
        "ReportLog UUID.",
        type=str,
        required=True,
        _in="path",
        example="f47ac10b-58cc-4372-a567-0e02b2c3d479",
    )
    @ns.response(200, "Report file download")
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    @ns.response(404, "Resource not found", error_model)
    def get(self, report_id):
        """Download a generated report. Admin only."""
        report_id = parse_uuid_param(report_id, "report_id")
        log = db.session.get(ReportLog, report_id)
        if not log:
            raise APIError("NOT_FOUND", "Report not found.", http_status=404)

        delivery = ensure_report_file(log)

        log.downloaded_at = datetime.now(timezone.utc)
        db.session.commit()

        return send_stored_report(delivery)


@ns.route("/users/export")
class AdminUsersExport(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(security="apikey", description="Export users list as Excel.")
    def get(self):
        from_date, to_date, _, _, search = parse_list_filters()
        records, comm_map, personal_map, report_map = load_assessment_context()
        rows = build_unique_user_rows(records, comm_map, personal_map, report_map)
        rows = apply_list_filters(rows, from_date, to_date, search)
        return send_xlsx_export(rows, "users-export.xlsx")


@ns.route("/leads/export")
class AdminLeadsExport(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(security="apikey", description="Export leads list as Excel.")
    def get(self):
        from_date, to_date, _, _, search = parse_list_filters()
        records, comm_map, personal_map, report_map = load_assessment_context()
        rows = build_lead_rows(records, comm_map, personal_map, report_map)
        rows = apply_list_filters(rows, from_date, to_date, search)
        return send_xlsx_export(rows, "leads-export.xlsx")


@ns.route("/assessments/export")
class AdminAssessmentsExport(Resource):
    @require_admin
    @ns.expect(list_query_model)
    @ns.doc(security="apikey", description="Export completed assessments as Excel.")
    def get(self):
        from_date, to_date, _, _, search = parse_list_filters()
        records, comm_map, personal_map, report_map = load_assessment_context()
        rows = build_completed_assessment_rows(
            records, comm_map, personal_map, report_map
        )
        rows = apply_list_filters(rows, from_date, to_date, search)
        return send_xlsx_export(rows, "assessments-export.xlsx")


@ns.route("/assessments/<string:assessment_id>/export")
class AdminAssessmentExport(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description="Export one assessment summary + goals as Excel.",
    )
    def get(self, assessment_id):
        assessment_id = parse_uuid_param(assessment_id, "assessment_id")
        payload, filename = build_assessment_export_rows(assessment_id)
        return send_file(
            BytesIO(payload),
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def _handle_assessment_upload():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise APIError(
            "INVALID_INPUT",
            "Multipart field 'file' is required.",
            field="file",
            http_status=400,
        )
    return import_assessments_from_upload(upload)


@ns.route("/upload/convert-pdf")
class AdminUploadConvertPdf(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Legacy admin upload URL used by wealth-admin frontend. "
            "Imports client rows as Flow 1 assessments (not PDF conversion)."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def post(self):
        """Bulk import assessments (compat route for admin Excel Upload page)."""
        result = _handle_assessment_upload()
        return success_response(result)


@ns.route("/upload/import-assessments")
class AdminUploadImportAssessments(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Bulk import client records from CSV/XLS/XLSX and create Flow 1 "
            "assessments (max 100 rows). Required columns: mobile, email, consent."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def post(self):
        """Upload spreadsheet and spawn assessments in batch."""
        result = _handle_assessment_upload()
        return success_response(result)


@ns.route("/upload/import-template")
class AdminUploadImportTemplate(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description="Download sample Excel template for bulk assessment import.",
    )
    @ns.response(200, "Excel template download")
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """Sample template with required Flow 1 columns."""
        payload = rows_to_xlsx_bytes(
            IMPORT_TEMPLATE_SAMPLE,
            sheet_name="Clients",
        )
        return send_file(
            BytesIO(payload),
            as_attachment=True,
            download_name="assessment-import-template.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


testimonial_input_model = ns.model(
    "TestimonialInput",
    {
        "client_name": fields.String(required=True, example="Aaditya Patel"),
        "review_message": fields.String(
            required=True,
            example="The automated assessment builder helped me plan retirement.",
        ),
        "avatar_url": fields.String(
            required=False,
            example="https://cdn.example.com/avatars/aaditya.jpg",
        ),
        "is_visible": fields.Boolean(required=False, default=False, example=True),
        "sort_order": fields.Integer(required=False, default=0, example=1),
    },
)

testimonial_update_model = ns.model(
    "TestimonialUpdateInput",
    {
        "client_name": fields.String(required=False, example="Aaditya Patel"),
        "review_message": fields.String(required=False),
        "avatar_url": fields.String(required=False),
        "is_visible": fields.Boolean(required=False),
        "sort_order": fields.Integer(required=False),
    },
)


def load_testimonial_schema(schema_cls, payload):
    try:
        return schema_cls().load(payload or {})
    except ValidationError as err:
        field = next(iter(err.messages), None)
        raise APIError(
            "INVALID_INPUT",
            str(err.messages),
            field=field,
            http_status=400,
        )


def get_testimonial_or_404(testimonial_id):
    row = db.session.get(Testimonial, testimonial_id)
    if not row:
        raise APIError("NOT_FOUND", "Testimonial not found.", http_status=404)
    return row


@ns.route("/testimonials")
class AdminTestimonialsList(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description="List all testimonials for admin management (visible and hidden).",
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """List all testimonials."""
        rows = (
            Testimonial.query.order_by(
                Testimonial.sort_order.asc(),
                Testimonial.created_at.desc(),
            ).all()
        )
        return success_response([serialize_testimonial(row) for row in rows])

    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Create a testimonial. At most 3 may be visible on the website; "
            "when 3+ records exist, at least 3 must stay visible."
        ),
    )
    @ns.expect(testimonial_input_model, validate=True)
    @ns.response(201, "Created", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def post(self):
        """Create a testimonial."""
        data = load_testimonial_schema(
            TestimonialSchema, request.get_json(silent=True)
        )
        is_visible = bool(data.get("is_visible", False))
        assert_can_set_visible(None, is_visible)

        row = Testimonial(
            client_name=data["client_name"].strip(),
            review_message=data["review_message"].strip(),
            avatar_url=data.get("avatar_url"),
            is_visible=is_visible,
            sort_order=int(data.get("sort_order") or 0),
        )
        db.session.add(row)
        db.session.commit()
        return success_response(serialize_testimonial(row)), 201


@ns.route("/testimonials/<string:testimonial_id>")
class AdminTestimonialDetail(Resource):
    @require_admin
    @ns.doc(security="apikey", description="Get one testimonial by id.")
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(404, "Not found", error_model)
    def get(self, testimonial_id):
        """Get testimonial details."""
        row = get_testimonial_or_404(parse_uuid_param(testimonial_id, "testimonial_id"))
        return success_response(serialize_testimonial(row))

    @require_admin
    @ns.doc(
        security="apikey",
        description="Update testimonial fields and visibility.",
    )
    @ns.expect(testimonial_update_model, validate=True)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(404, "Not found", error_model)
    def put(self, testimonial_id):
        """Update a testimonial."""
        testimonial_id = parse_uuid_param(testimonial_id, "testimonial_id")
        row = get_testimonial_or_404(testimonial_id)
        data = load_testimonial_schema(
            TestimonialUpdateSchema, request.get_json(silent=True)
        )
        if not data:
            raise APIError(
                "INVALID_INPUT",
                "Provide at least one field to update.",
                http_status=400,
            )

        if "is_visible" in data:
            assert_can_set_visible(row, bool(data["is_visible"]))

        if "client_name" in data:
            row.client_name = data["client_name"].strip()
        if "review_message" in data:
            row.review_message = data["review_message"].strip()
        if "avatar_url" in data:
            row.avatar_url = data["avatar_url"]
        if "is_visible" in data:
            row.is_visible = bool(data["is_visible"])
        if "sort_order" in data:
            row.sort_order = int(data["sort_order"])

        touch_updated_at(row)
        db.session.commit()
        return success_response(serialize_testimonial(row))

    @require_admin
    @ns.doc(
        security="apikey",
        description="Delete a testimonial. Cannot delete if it would drop visible count below 3.",
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(404, "Not found", error_model)
    def delete(self, testimonial_id):
        """Delete a testimonial."""
        testimonial_id = parse_uuid_param(testimonial_id, "testimonial_id")
        row = get_testimonial_or_404(testimonial_id)
        assert_can_delete(row)
        payload = serialize_testimonial(row)
        db.session.delete(row)
        db.session.commit()
        return success_response({"deleted": True, "testimonial": payload})


@ns.route("/marketing/recipients")
class AdminMarketingRecipients(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "List distinct user emails with marketing consent for campaign targeting."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    def get(self):
        """Emails available for marketing campaigns."""
        recipients = consented_recipient_emails()
        return success_response(
            {
                "count": len(recipients),
                "recipients": recipients,
            }
        )


@ns.route("/marketing/campaign")
class AdminMarketingCampaign(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Send a marketing email campaign via SMTP. "
            "Multipart form: subject, body, optional recipients (JSON array or "
            "comma-separated), optional body_format (html|plain), optional file "
            "attachments (max 12MB total). If recipients omitted, sends to all "
            "users with consent=true."
        ),
    )
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(500, "SMTP or config error", error_model)
    def post(self):
        """Dispatch a marketing email campaign."""
        subject = request.form.get("subject", "")
        body = request.form.get("body", "")
        body_format = (request.form.get("body_format") or "html").strip().lower()
        if body_format not in {"html", "plain"}:
            raise APIError(
                "INVALID_INPUT",
                "body_format must be html or plain.",
                field="body_format",
                http_status=400,
            )

        recipients = normalize_recipients(request.form.get("recipients"))
        uploads = []
        for key in ("attachments", "files", "file"):
            uploads.extend(request.files.getlist(key))

        attachments = read_campaign_attachments(uploads)
        result = send_marketing_campaign(
            subject=subject,
            body=body,
            recipients=recipients,
            body_format=body_format,
            attachments=attachments,
        )
        return success_response(result)


api_key_create_model = ns.model(
    "ApiKeyCreateInput",
    {
        "client_name": fields.String(
            required=True,
            description="Label for the key owner or integration.",
            example="Website Client",
        ),
        "role": fields.String(
            required=False,
            description="user (Standard User) or admin.",
            example="user",
        ),
        "expires_at": fields.String(
            required=False,
            description="Optional ISO-8601 expiry timestamp.",
            example="2027-01-01T00:00:00+00:00",
        ),
    },
)

api_keys_query = ns.parser()
api_keys_query.add_argument(
    "search",
    type=str,
    location="args",
    required=False,
    help="Search by key token prefix/suffix, role, or client name.",
)


@ns.route("/api-keys")
class AdminApiKeys(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description="List API keys with request volume and connection audit data.",
    )
    @ns.expect(api_keys_query)
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def get(self):
        """List API keys for the access log dashboard."""
        args = api_keys_query.parse_args()
        items = list_api_keys(search=args.get("search"))
        return success_response({"items": items, "count": len(items)})

    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Generate a new API key. The full token is returned once in "
            "api_key_plaintext — store it immediately."
        ),
    )
    @ns.expect(api_key_create_model, validate=True)
    @ns.response(201, "Created", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    def post(self):
        """Create a new API key."""
        data = load_testimonial_schema(
            ApiKeyCreateSchema, request.get_json(silent=True)
        )
        expires_at = data.get("expires_at")
        row, raw_key = create_api_key(
            client_name=data["client_name"],
            role=data.get("role", "user"),
            expires_at=expires_at,
        )
        payload = serialize_api_key(row)
        payload["api_key_plaintext"] = raw_key
        return success_response(payload), 201


@ns.route("/api-keys/<string:key_id>/revoke")
class AdminApiKeyRevoke(Resource):
    @require_admin
    @ns.doc(security="apikey", description="Revoke an active API key.")
    @ns.param("key_id", "API key UUID.", type=str, required=True, _in="path")
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    @ns.response(404, "Not found", error_model)
    def put(self, key_id):
        """Revoke an API key."""
        key_id = parse_uuid_param(key_id, "key_id")
        current_id = getattr(g.api_key, "id", None)
        return success_response(
            revoke_api_key(key_id, current_key_id=current_id)
        )


@ns.route("/api-keys/<string:key_id>/activate")
class AdminApiKeyActivate(Resource):
    @require_admin
    @ns.doc(security="apikey", description="Reactivate a revoked API key.")
    @ns.param("key_id", "API key UUID.", type=str, required=True, _in="path")
    @ns.response(200, "Success", success_envelope_model)
    @ns.response(400, "Invalid input", error_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Admin access required", error_model)
    @ns.response(404, "Not found", error_model)
    def put(self, key_id):
        """Activate a revoked API key."""
        key_id = parse_uuid_param(key_id, "key_id")
        return success_response(activate_api_key(key_id))
