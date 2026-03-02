"""
Module 2 — Engagement Refresh Job
==================================
Periodically updates engagement metrics and evaluates stability.

This module handles the dynamic updating of engagement lifecycle fields
for reels that need engagement data refreshes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from module2.engagement_lifecycle import evaluate_engagement_stability
from module2.logging_config import get_logger


logger = get_logger("engagement_updater")


def refresh_engagement_metrics(session: Session) -> None:
    """
    Updates engagement metrics for all reels and evaluates stability.
    
    For each reel:
        - update engagement_last_updated_at
        - increment engagement_fetch_attempts  
        - call evaluate_engagement_stability(reel)
    
    Args:
        session: SQLAlchemy database session
        
    Returns:
        None (commits changes to database)
    """
    from db.models import Reel
    
    now = datetime.utcnow()
    updated_count = 0
    error_count = 0
    
    logger.info(
        "engagement_refresh_started",
        extra={"reel_id": None}
    )
    
    try:
        # Query all reels for engagement refresh with batch processing
        reels = session.query(Reel).yield_per(500)
        
        logger.info(
            "engagement_refresh_processing_started",
            extra={"reel_id": None}
        )
        
        for reel in reels:
            try:
                # Update engagement tracking fields
                reel.engagement_last_updated_at = now
                reel.engagement_fetch_attempts += 1
                
                # Evaluate stability based on current data
                evaluate_engagement_stability(reel)
                
                updated_count += 1
                
                if updated_count % 100 == 0:
                    logger.debug(
                        "engagement_refresh_progress processed=%d",
                        updated_count,
                        extra={"reel_id": reel.id}
                    )
                    
            except Exception as exc:
                error_count += 1
                logger.error(
                    "engagement_refresh_error reel_id=%s error=%s",
                    reel.id,
                    str(exc)[:120],
                    extra={"reel_id": reel.id}
                )
                # Continue processing other reels
                continue
        
        # Commit all changes
        session.commit()
        
        logger.info(
            "engagement_refresh_completed updated=%d errors=%d",
            updated_count,
            error_count,
            extra={"reel_id": None}
        )
        
    except Exception as exc:
        session.rollback()
        logger.error(
            "engagement_refresh_failed error=%s",
            str(exc)[:120],
            extra={"reel_id": None}
        )
        raise
