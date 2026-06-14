import uuid
from datetime import datetime

from app import db


class ReportLog(db.Model):
    __tablename__ = "report_log"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    calculation_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("calculation_output.id"), nullable=False
    )
    triggered_by = db.Column(db.String(100), default="user")
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    format = db.Column(db.String(10), default="pdf")
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    downloaded_at = db.Column(db.DateTime, nullable=True)
