import uuid
from datetime import datetime

from app import db


class PersonalDetails(db.Model):
    __tablename__ = "personal_details"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    client_name = db.Column(db.String(120), nullable=False)
    client_occupation = db.Column(db.String(120), nullable=False)
    client_designation = db.Column(db.String(120), nullable=False)
    client_company = db.Column(db.String(120), nullable=False)
    client_dob = db.Column(db.Date, nullable=False)
    client_age = db.Column(db.Integer, nullable=False)
    spouse_name = db.Column(db.String(120), nullable=True)
    spouse_occupation = db.Column(db.String(120), nullable=True)
    spouse_designation = db.Column(db.String(120), nullable=True)
    spouse_company = db.Column(db.String(120), nullable=True)
    spouse_dob = db.Column(db.Date, nullable=True)
    spouse_age = db.Column(db.Integer, nullable=True)
    client_retirement_age = db.Column(db.Integer, default=60, nullable=False)
    spouse_retirement_age = db.Column(db.Integer, default=55, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
