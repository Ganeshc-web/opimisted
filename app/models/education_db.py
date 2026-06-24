import uuid

from app import db


class EducationProgram(db.Model):
    __tablename__ = "education_programs"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    level = db.Column(db.String(20), nullable=False)
    course_category = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    country_famous_for = db.Column(db.String(200), nullable=True)
    approx_cost_inr = db.Column(db.Float, nullable=False)
    duration = db.Column(db.String(50), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    living_cost_included = db.Column(db.Boolean, nullable=False, default=False)
    lifestyle_level = db.Column(db.String(100), nullable=True)
    inflation_rate = db.Column(db.Float, nullable=False)
