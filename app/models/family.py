import uuid
from datetime import datetime

from app import db


class FamilyDetails(db.Model):
    __tablename__ = "family_details"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    number_of_children = db.Column(db.Integer, default=0)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)


class Child(db.Model):
    __tablename__ = "child"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("family_details.id"), nullable=False
    )
    child_number = db.Column(db.Integer, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    occupation = db.Column(db.String(120), nullable=True)
    financially_dependent = db.Column(db.Boolean, default=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    calculated_age = db.Column(db.Integer, nullable=True)
