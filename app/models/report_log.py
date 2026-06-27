import uuid
from datetime import datetime, timezone

from app import db


class ReportLog(db.Model):
    __tablename__ = "report_log"
    __table_args__ = (
        db.Index("ix_report_log_assessment_id", "assessment_id"),
    )

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
    generated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    downloaded_at = db.Column(db.DateTime, nullable=True)
