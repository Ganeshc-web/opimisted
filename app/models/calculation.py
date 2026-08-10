import uuid
from datetime import datetime, timezone

from app import db


class CalculationOutput(db.Model):
    __tablename__ = "calculation_output"
    __table_args__ = (
        db.Index("ix_calculation_output_assessment_id", "assessment_id"),
    )

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    pf_monthly_rate = db.Column(db.Float, nullable=False)
    real_rate = db.Column(db.Float, nullable=False)
    real_rate_monthly = db.Column(db.Float, nullable=False)
    monthly_eff_pre = db.Column(db.Float, nullable=False)
    client_corpus = db.Column(db.Float, nullable=False)
    client_pf_corpus = db.Column(db.Float, nullable=False)
    client_provisions_made = db.Column(db.Float, nullable=False, default=0.0)
    client_net_corpus = db.Column(db.Float, nullable=False)
    client_monthly_sip = db.Column(db.Float, nullable=False)
    client_lump_sum = db.Column(db.Float, nullable=False)
    spouse_corpus = db.Column(db.Float, nullable=False)
    spouse_pf_corpus = db.Column(db.Float, nullable=False)
    spouse_provisions_made = db.Column(db.Float, nullable=False, default=0.0)
    spouse_net_corpus = db.Column(db.Float, nullable=False)
    spouse_monthly_sip = db.Column(db.Float, nullable=False)
    spouse_lump_sum = db.Column(db.Float, nullable=False)
    total_insurance_required = db.Column(db.Float, nullable=False)
    total_goals_monthly_sip = db.Column(db.Float, nullable=False)
    household_monthly = db.Column(db.Float, nullable=True)
    client_annual_ret_reqd = db.Column(db.Float, nullable=True)
    spouse_annual_ret_reqd = db.Column(db.Float, nullable=True)
    insurance_items = db.Column(db.JSON, nullable=True)
    inflation_pre = db.Column(db.Float, nullable=True)
    roi_pre = db.Column(db.Float, nullable=True)
    inflation_post = db.Column(db.Float, nullable=True)
    roi_post = db.Column(db.Float, nullable=True)
    calculated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
