import hashlib
from functools import wraps
from flask import request, g
from app.models.api_key import APIKey
from app.core.exceptions import APIError
from app import db
from datetime import datetime

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_key = request.headers.get("X-API-Key")
        if not raw_key:
            raise APIError("INVALID_API_KEY", "API key is required.", http_status=401)
        key_hash = hash_key(raw_key)
        key_obj = APIKey.query.filter_by(key_hash=key_hash, is_active=True).first()
        if not key_obj:
            raise APIError("INVALID_API_KEY", "Invalid or inactive API key.", http_status=401)
        key_obj.last_used_at = datetime.utcnow()
        db.session.commit()
        g.api_key = key_obj
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_key = request.headers.get("X-API-Key")
        if not raw_key:
            raise APIError("INVALID_API_KEY", "API key is required.", http_status=401)
        key_hash = hash_key(raw_key)
        key_obj = APIKey.query.filter_by(key_hash=key_hash, is_active=True).first()
        if not key_obj:
            raise APIError("INVALID_API_KEY", "Invalid or inactive API key.", http_status=401)
        if key_obj.role != "admin":
            raise APIError("FORBIDDEN", "Admin access required.", http_status=403)
        key_obj.last_used_at = datetime.utcnow()
        db.session.commit()
        g.api_key = key_obj
        return f(*args, **kwargs)
    return decorated
