from flask import send_file, jsonify
from flask_restx import Namespace, Resource
from datetime import datetime
import os

from app import db
from app.models.assessment import AssessmentRecord
from app.models.calculation import CalculationOutput
from app.models.personal import PersonalDetails
from app.models.communication import CommunicationDetails
from app.models.goals import Goal
from app.models.report_log import ReportLog
from app.middleware.auth import require_api_key
from app.services.report_service import PROJECT_ROOT, generate_report
from app.core.exceptions import APIError

ns = Namespace("report", description="Report generation and download", path="/report")


@ns.route("/<uuid:assessment_id>/generate")
class ReportGenerate(Resource):
    @require_api_key
    def post(self, assessment_id):
        """Generate PDF report for an assessment."""

        record = db.session.get(AssessmentRecord, assessment_id)
        if not record:
            raise APIError("NOT_FOUND", "Assessment not found.", http_status=404)

        calc = CalculationOutput.query.filter_by(
            assessment_id=assessment_id
        ).order_by(CalculationOutput.calculated_at.desc()).first()
        if not calc:
            raise APIError("NOT_FOUND", 
                "Run /calculate first before generating report.", http_status=404)

        personal = PersonalDetails.query.filter_by(assessment_id=assessment_id).first()
        comm = CommunicationDetails.query.filter_by(assessment_id=assessment_id).first()
        goals = Goal.query.filter_by(assessment_id=assessment_id).all()

        if not personal or not comm:
            raise APIError("INVALID_INPUT", 
                "Complete flows 1 and 2 before generating report.", http_status=400)

        result = generate_report(str(assessment_id), calc, personal, comm, goals)

        log = ReportLog(
            assessment_id=assessment_id,
            calculation_id=calc.id,
            triggered_by="user",
            file_name=result["file_name"],
            file_path=result["pdf_path"],
            format="pdf",
            generated_at=datetime.utcnow(),
        )
        db.session.add(log)
        db.session.commit()

        return {
            "status": "success",
            "data": {
                "report_id":   str(log.id),
                "file_name":   result["file_name"],
                "generated_at": log.generated_at.isoformat(),
            },
            "timestamp": datetime.utcnow().isoformat()
        }


@ns.route("/<uuid:assessment_id>/download/<uuid:report_id>")
class ReportDownload(Resource):
    @require_api_key
    def get(self, assessment_id, report_id):
        """Download generated PDF report."""

        log = ReportLog.query.filter_by(
            id=report_id, assessment_id=assessment_id
        ).first()
        if not log:
            raise APIError("NOT_FOUND", "Report not found.", http_status=404)

        file_path = log.file_path
        if not os.path.isabs(file_path):
            file_path = os.path.join(str(PROJECT_ROOT), file_path)

        if not os.path.exists(file_path):
            raise APIError("NOT_FOUND", "Report file missing on server.", http_status=404)

        log.downloaded_at = datetime.utcnow()
        db.session.commit()

        return send_file(
            file_path,
            as_attachment=True,
            download_name=log.file_name,
            mimetype="application/pdf"
        )


@ns.route("/<uuid:assessment_id>/history")
class ReportHistory(Resource):
    @require_api_key
    def get(self, assessment_id):
        """List all generated reports for an assessment."""

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
            "timestamp": datetime.utcnow().isoformat()
        }
