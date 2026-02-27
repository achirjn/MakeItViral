from __future__ import annotations

from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from db.models import IngestionStatus, Reel


def claim_next_reel(session: Session) -> Optional[Reel]:
    """
    Claim the next reel ready for processing using row-level locking.

    This does NOT persist worker lifecycle state (Phase 2 requirement).
    Locking ensures that concurrent workers do not claim the same row while
    the current transaction is open.
    """
    likes = func.coalesce(Reel.likes, 0)
    comments = func.coalesce(Reel.comments, 0)
    views = func.coalesce(Reel.views, 0)
    priority = likes + comments + (views * 0.001)

    stmt = (
        select(Reel)
        .where(Reel.ingestion_status == IngestionStatus.READY_FOR_PROCESSING.value)
        .order_by(desc(priority), desc(Reel.publish_time).nullslast())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return session.execute(stmt).scalars().one_or_none()

