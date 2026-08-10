from datetime import datetime, timezone
from functools import wraps

from flask import g, request

from app import cache, db
from app.core.exceptions import APIError
from app.core.security import hash_key
from app.models.api_key import APIKey
from app.services.api_key_service import USER_RATE_LIMIT_PER_MIN, key_status


def _minute_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


def _enforce_rate_limit(key_obj: APIKey) -> None:
    if key_obj.role == "admin":
        return
    if key_status(key_obj) != "Active":
        return

    cache_key = f"api_key_rate:{key_obj.id}:{_minute_bucket()}"
    count = cache.get(cache_key) or 0
    if count >= USER_RATE_LIMIT_PER_MIN:
        raise APIError(
            "RATE_LIMIT_EXCEEDED",
            f"Rate limit exceeded ({USER_RATE_LIMIT_PER_MIN} requests per minute).",
            http_status=429,
        )
    cache.set(cache_key, count + 1, timeout=60)


def _authenticate(raw_key: str) -> APIKey:
    key_hash = hash_key(raw_key)
    key_obj = APIKey.query.filter_by(key_hash=key_hash).first()
    if not key_obj:
        raise APIError("INVALID_API_KEY", "Invalid or inactive API key.", http_status=401)

    status = key_status(key_obj)
    if status == "Expired":
        raise APIError("INVALID_API_KEY", "API key has expired.", http_status=401)
    if status == "Revoked":
        raise APIError("INVALID_API_KEY", "Invalid or inactive API key.", http_status=401)

    _enforce_rate_limit(key_obj)
    key_obj.last_used_at = datetime.now(timezone.utc)
    key_obj.request_count = (key_obj.request_count or 0) + 1
    db.session.commit()
    return key_obj


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_key = request.headers.get("X-API-Key")
        if not raw_key:
            raise APIError("INVALID_API_KEY", "API key is required.", http_status=401)
        g.api_key = _authenticate(raw_key)
        return f(*args, **kwargs)

    return decorated


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_key = request.headers.get("X-API-Key")
        if not raw_key:
            raise APIError("INVALID_API_KEY", "API key is required.", http_status=401)
        key_obj = _authenticate(raw_key)
        if key_obj.role != "admin":
            raise APIError("FORBIDDEN", "Admin access required.", http_status=403)
        g.api_key = key_obj
        return f(*args, **kwargs)

    return decorated
