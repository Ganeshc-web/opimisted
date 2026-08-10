"""Testimonial visibility rules and serialization."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app import db
from app.core.exceptions import APIError
from app.models.testimonial import Testimonial

# Visible testimonials must always be 0, 3, 6, 9, 12, … (admin and public match).
VISIBLE_GROUP_SIZE = 3


def visible_count(exclude_id: Optional[UUID] = None) -> int:
    query = Testimonial.query.filter_by(is_visible=True)
    if exclude_id is not None:
        query = query.filter(Testimonial.id != exclude_id)
    return query.count()


def assert_visible_count_allowed(count: int) -> None:
    if count < 0 or count % VISIBLE_GROUP_SIZE != 0:
        raise APIError(
            "INVALID_INPUT",
            "Visible testimonials must be a multiple of "
            f"{VISIBLE_GROUP_SIZE} (0, 3, 6, 9, 12, …). "
            f"Resulting visible count would be {count}. "
            "Use PUT /api/v1/admin/testimonials/visibility to set a full group at once.",
            field="is_visible",
            http_status=400,
        )


def assert_can_set_visible(testimonial: Optional[Testimonial], new_visible: bool) -> None:
    """Resulting visible count must stay a multiple of 3."""
    if new_visible:
        current = visible_count(exclude_id=testimonial.id if testimonial else None)
        already_visible = testimonial is not None and testimonial.is_visible
        resulting = current if already_visible else current + 1
        assert_visible_count_allowed(resulting)
        return

    if testimonial is None or not testimonial.is_visible:
        return

    resulting = visible_count(exclude_id=testimonial.id)
    assert_visible_count_allowed(resulting)


def assert_can_delete(testimonial: Testimonial) -> None:
    if not testimonial.is_visible:
        return
    resulting = visible_count(exclude_id=testimonial.id)
    assert_visible_count_allowed(resulting)


def set_visible_ids(visible_ids: list) -> list[Testimonial]:
    """
    Replace the visible set with exactly these IDs.
    Length must be a multiple of 3 (including 0).
    """
    parsed: list[UUID] = []
    for index, raw in enumerate(visible_ids or []):
        try:
            parsed.append(UUID(str(raw)))
        except (TypeError, ValueError) as exc:
            raise APIError(
                "INVALID_INPUT",
                f"visible_ids[{index}] must be a valid UUID.",
                field="visible_ids",
                http_status=400,
            ) from exc

    # Deduplicate while preserving order
    unique_ids: list[UUID] = []
    seen = set()
    for item in parsed:
        if item not in seen:
            seen.add(item)
            unique_ids.append(item)

    assert_visible_count_allowed(len(unique_ids))

    if unique_ids:
        found = Testimonial.query.filter(Testimonial.id.in_(unique_ids)).all()
        found_ids = {row.id for row in found}
        missing = [str(i) for i in unique_ids if i not in found_ids]
        if missing:
            raise APIError(
                "NOT_FOUND",
                f"Testimonial(s) not found: {', '.join(missing)}",
                field="visible_ids",
                http_status=404,
            )

    rows = Testimonial.query.all()
    visible_set = set(unique_ids)
    for row in rows:
        row.is_visible = row.id in visible_set
        touch_updated_at(row)
    db.session.commit()

    return (
        Testimonial.query.filter_by(is_visible=True)
        .order_by(Testimonial.sort_order.asc(), Testimonial.created_at.asc())
        .all()
    )


def list_public_testimonials() -> list[Testimonial]:
    """All visible testimonials (admin enforces multiples of 3)."""
    return (
        Testimonial.query.filter_by(is_visible=True)
        .order_by(Testimonial.sort_order.asc(), Testimonial.created_at.asc())
        .all()
    )


def serialize_testimonial(row: Testimonial) -> dict:
    return {
        "id": str(row.id),
        "client_name": row.client_name,
        "review_message": row.review_message,
        "avatar_url": row.avatar_url,
        "is_visible": row.is_visible,
        "sort_order": row.sort_order,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def touch_updated_at(row: Testimonial) -> None:
    row.updated_at = datetime.now(timezone.utc)
