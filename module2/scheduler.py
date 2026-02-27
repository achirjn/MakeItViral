from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import Select, desc, func, select, update
from sqlalchemy.orm import Session

from db.models import IngestionStatus, Reel


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerConfig:
    batch_size: int = 25
    schedule_interval_seconds: int = 60
    views_weight: float = 0.001


def _eligible_reels_query(config: SchedulerConfig) -> Select:
    likes = func.coalesce(Reel.likes, 0)
    comments = func.coalesce(Reel.comments, 0)
    views = func.coalesce(Reel.views, 0)
    priority = likes + comments + (views * config.views_weight)

    return (
        select(Reel.id)
        .where(Reel.ingestion_status == IngestionStatus.PENDING.value)
        .where(Reel.thumbnail_url.is_not(None))
        .where(Reel.creator_id.is_not(None))
        .order_by(desc(priority), desc(Reel.publish_time).nullslast())
        .limit(config.batch_size)
        .with_for_update(skip_locked=True)
    )


def schedule_once(
    session: Session, config: SchedulerConfig = SchedulerConfig()
) -> list[str]:
    """
    Select eligible reels and transition:
      pending -> ready_for_processing

    Returns a list of scheduled reel_id values.
    """
    reel_ids = session.execute(_eligible_reels_query(config)).scalars().all()
    if not reel_ids:
        return []

    session.execute(
        update(Reel)
        .where(Reel.id.in_(reel_ids))
        .values(ingestion_status=IngestionStatus.READY_FOR_PROCESSING.value)
    )
    session.commit()

    return [str(rid) for rid in reel_ids]


def run_forever(
    session_factory,
    config: SchedulerConfig = SchedulerConfig(),
) -> None:
    """
    Stateless polling loop. The caller owns process lifecycle.

    session_factory: callable returning a context manager yielding Session
      e.g. db.connection.get_session
    """
    while True:
        with session_factory() as session:
            scheduled = schedule_once(session=session, config=config)
            if scheduled:
                logger.info("Scheduled %d reels: %s", len(scheduled), scheduled)
        time.sleep(config.schedule_interval_seconds)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from db.connection import get_session

    print("Scheduler starting... (Ctrl+C to stop)")
    run_forever(session_factory=get_session)
