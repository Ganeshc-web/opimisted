import uuid
from datetime import datetime, timezone

from app import db


class FamilyDetails(db.Model):
    __tablename__ = "family_details"
    __table_args__ = (
        db.Index("ix_family_details_assessment_id", "assessment_id"),
    )

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    number_of_children = db.Column(db.Integer, default=0)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    children = db.relationship("Child")


class Child(db.Model):
    __tablename__ = "child"
    __table_args__ = (
        db.Index("ix_child_family_id", "family_id"),
    )

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
