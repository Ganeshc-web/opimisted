import uuid

from app import db


class TourDestination(db.Model):
    __tablename__ = "tour_destinations"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country = db.Column(db.String(100), nullable=False)
    budget_inr = db.Column(db.Float, nullable=False)
    duration = db.Column(db.String(50), nullable=True)
    category = db.Column(db.String(100), nullable=True)
