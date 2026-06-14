import uuid
from datetime import datetime

from app import db


class CalculationOutput(db.Model):
    __tablename__ = "calculation_output"

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
    client_net_corpus = db.Column(db.Float, nullable=False)
    client_monthly_sip = db.Column(db.Float, nullable=False)
    client_lump_sum = db.Column(db.Float, nullable=False)
    spouse_corpus = db.Column(db.Float, nullable=False)
    spouse_pf_corpus = db.Column(db.Float, nullable=False)
    spouse_net_corpus = db.Column(db.Float, nullable=False)
    spouse_monthly_sip = db.Column(db.Float, nullable=False)
    spouse_lump_sum = db.Column(db.Float, nullable=False)
    total_insurance_required = db.Column(db.Float, nullable=False)
    total_goals_monthly_sip = db.Column(db.Float, nullable=False)
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)
