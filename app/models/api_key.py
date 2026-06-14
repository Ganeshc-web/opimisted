import uuid
from datetime import datetime

from app import db


class APIKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash = db.Column(db.String(64), unique=True, nullable=False)
    client_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default="user")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)
