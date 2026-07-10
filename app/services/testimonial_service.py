"""Testimonial visibility rules and serialization."""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app import db
from app.core.exceptions import APIError
from app.models.testimonial import Testimonial

MAX_VISIBLE_TESTIMONIALS = 3
MIN_VISIBLE_TESTIMONIALS = 3


def visible_count(exclude_id: Optional[UUID] = None) -> int:
    query = Testimonial.query.filter_by(is_visible=True)
    if exclude_id is not None:
        query = query.filter(Testimonial.id != exclude_id)
    return query.count()


def total_count() -> int:
    return Testimonial.query.count()


def assert_can_set_visible(testimonial: Optional[Testimonial], new_visible: bool) -> None:
    """Enforce max 3 visible and min 3 visible when enough records exist."""
    if new_visible:
        current_visible = visible_count(
            exclude_id=testimonial.id if testimonial else None
        )
        already_visible = testimonial is not None and testimonial.is_visible
        if not already_visible and current_visible >= MAX_VISIBLE_TESTIMONIALS:
            raise APIError(
                "INVALID_INPUT",
                f"At most {MAX_VISIBLE_TESTIMONIALS} testimonials can be visible on the website.",
                field="is_visible",
                http_status=400,
            )
        return

    if testimonial is None or not testimonial.is_visible:
        return

    remaining_visible = visible_count(exclude_id=testimonial.id)
    total = total_count()
    if total >= MIN_VISIBLE_TESTIMONIALS and remaining_visible < MIN_VISIBLE_TESTIMONIALS:
        raise APIError(
            "INVALID_INPUT",
            f"At least {MIN_VISIBLE_TESTIMONIALS} testimonials must remain visible on the website.",
            field="is_visible",
            http_status=400,
        )


def assert_can_delete(testimonial: Testimonial) -> None:
    if not testimonial.is_visible:
        return
    remaining_visible = visible_count(exclude_id=testimonial.id)
    total = total_count()
    if total >= MIN_VISIBLE_TESTIMONIALS and remaining_visible < MIN_VISIBLE_TESTIMONIALS:
        raise APIError(
            "INVALID_INPUT",
            f"Cannot delete a visible testimonial while fewer than "
            f"{MIN_VISIBLE_TESTIMONIALS} would remain visible. Hide or replace it first.",
            http_status=400,
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
