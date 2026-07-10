import uuid

from datetime import datetime, timezone



from app import db





class Testimonial(db.Model):

    __tablename__ = "testimonials"



    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    client_name = db.Column(db.String(120), nullable=False)

    review_message = db.Column(db.Text, nullable=False)

    avatar_url = db.Column(db.String(500), nullable=True)

    is_visible = db.Column(db.Boolean, default=False, nullable=False)

    sort_order = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(

        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False

    )

    updated_at = db.Column(

        db.DateTime,

        default=lambda: datetime.now(timezone.utc),

        onupdate=lambda: datetime.now(timezone.utc),

        nullable=False,

    )


