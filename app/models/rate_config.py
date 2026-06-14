import uuid
from datetime import datetime

from app import db


class RateConfig(db.Model):
    __tablename__ = "rate_config"

    id = db.Column(db.Integer, primary_key=True)
    inflation_post = db.Column(db.Float, default=0.06)
    roi_post = db.Column(db.Float, default=0.08)
    inflation_pre = db.Column(db.Float, default=0.06)
    roi_pre = db.Column(db.Float, default=0.12)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    updated_by = db.Column(db.String(100), nullable=True)


class RateHistory(db.Model):
    __tablename__ = "rate_history"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_name = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Float, nullable=False)
    new_value = db.Column(db.Float, nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    changed_by = db.Column(db.String(100), nullable=False)
