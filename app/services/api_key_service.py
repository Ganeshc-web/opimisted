"""Admin API key management and request auditing."""
import secrets
from datetime import datetime, timezone

from sqlalchemy import or_

from app import db
from app.core.exceptions import APIError
from app.core.security import hash_key
from app.models.api_key import APIKey

USER_RATE_LIMIT_LABEL = "1,000/min"
ADMIN_RATE_LIMIT_LABEL = "Unlimited"
USER_RATE_LIMIT_PER_MIN = 1000


def _now():
    return datetime.now(timezone.utc)


def _normalize_role(role: str) -> str:
    value = (role or "user").strip().lower()
    if value not in {"user", "admin"}:
        raise APIError(
            "INVALID_INPUT",
            "role must be user or admin.",
            field="role",
            http_status=400,
        )
    return value


def _role_label(role: str) -> str:
    return "Admin" if role == "admin" else "Standard User"


def _rate_limit_label(role: str) -> str:
    return ADMIN_RATE_LIMIT_LABEL if role == "admin" else USER_RATE_LIMIT_LABEL


def _display_token(row: APIKey) -> str:
    if row.key_prefix and row.key_suffix:
        return f"{row.key_prefix}...{row.key_suffix}"
    digest = row.key_hash or ""
    if len(digest) >= 20:
        return f"{digest[:12]}...{digest[-8:]}"
    return digest[:12] + "..." if digest else "unknown"


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def key_status(row: APIKey) -> str:
    expires = _as_utc(row.expires_at)
    if expires and expires < _now():
        return "Expired"
    if not row.is_active:
        return "Revoked"
    return "Active"


def serialize_api_key(row: APIKey) -> dict:
    return {
        "id": str(row.id),
        "api_key_token": _display_token(row),
        "client_name": row.client_name,
        "role": row.role,
        "role_label": _role_label(row.role),
        "request_count": row.request_count or 0,
        "rate_limit": _rate_limit_label(row.role),
        "last_connection": (
            row.last_used_at.isoformat() if row.last_used_at else None
        ),
        "status": key_status(row),
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def create_api_key(
    *,
    client_name: str,
    role: str = "user",
    expires_at: datetime | None = None,
) -> tuple[APIKey, str]:
    name = (client_name or "").strip()
    if not name:
        raise APIError(
            "INVALID_INPUT",
            "client_name is required.",
            field="client_name",
            http_status=400,
        )

    normalized_role = _normalize_role(role)
    raw_key = secrets.token_hex(32)
    row = APIKey(
        client_name=name,
        key_hash=hash_key(raw_key),
        key_prefix=raw_key[:12],
        key_suffix=raw_key[-8:],
        role=normalized_role,
        is_active=True,
        request_count=0,
        expires_at=expires_at,
    )
    db.session.add(row)
    db.session.commit()
    return row, raw_key


def list_api_keys(*, search: str | None = None) -> list[dict]:
    query = APIKey.query.order_by(APIKey.created_at.desc())
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                db.func.lower(APIKey.client_name).like(term),
                db.func.lower(APIKey.role).like(term),
                db.func.lower(APIKey.key_prefix).like(term),
                db.func.lower(APIKey.key_suffix).like(term),
            )
        )
    return [serialize_api_key(row) for row in query.all()]


def get_api_key_or_404(key_id) -> APIKey:
    row = db.session.get(APIKey, key_id)
    if not row:
        raise APIError("NOT_FOUND", "API key not found.", http_status=404)
    return row


def revoke_api_key(key_id, *, current_key_id=None) -> dict:
    row = get_api_key_or_404(key_id)
    if current_key_id and row.id == current_key_id:
        raise APIError(
            "INVALID_INPUT",
            "You cannot revoke the API key used for this request.",
            http_status=400,
        )
    if key_status(row) == "Expired":
        raise APIError(
            "INVALID_INPUT",
            "Expired API keys cannot be revoked.",
            http_status=400,
        )
    row.is_active = False
    db.session.commit()
    return serialize_api_key(row)


def activate_api_key(key_id) -> dict:
    row = get_api_key_or_404(key_id)
    if key_status(row) == "Expired":
        raise APIError(
            "INVALID_INPUT",
            "Expired API keys cannot be reactivated.",
            http_status=400,
        )
    row.is_active = True
    db.session.commit()
    return serialize_api_key(row)


def record_api_key_usage(key_obj: APIKey) -> None:
    key_obj.last_used_at = _now()
    key_obj.request_count = (key_obj.request_count or 0) + 1
    db.session.commit()
