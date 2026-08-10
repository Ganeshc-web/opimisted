"""Service catalog serialization helpers."""
from datetime import datetime, timezone

from app.models.service import Service


def serialize_service(row: Service) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "description": row.description,
        "icon_url": row.icon_url,
        "is_visible": row.is_visible,
        "sort_order": row.sort_order,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_all_services() -> list[Service]:
    return (
        Service.query.order_by(Service.sort_order.asc(), Service.created_at.asc()).all()
    )


def list_visible_services() -> list[Service]:
    return (
        Service.query.filter_by(is_visible=True)
        .order_by(Service.sort_order.asc(), Service.created_at.asc())
        .all()
    )


def touch_updated_at(row: Service) -> None:
    row.updated_at = datetime.now(timezone.utc)
