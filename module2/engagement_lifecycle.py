"""
Module 2 — Engagement Lifecycle Evaluator
=========================================
Evaluates engagement stability and updates reel lifecycle status.

This module handles dataset management logic for engagement tracking,
determining which reels are suitable for training based on age and
engagement data availability.
"""

from __future__ import annotations

from typing import Any

from module2.logging_config import get_logger


logger = get_logger("engagement_lifecycle")


def evaluate_engagement_stability(reel: Any) -> None:
    """
    Updates engagement lifecycle fields on a reel object.
    
    Updates:
        reel.engagement_status
        reel.stability_score  
        reel.is_active_for_training
    
    Note: Does NOT update engagement_last_updated_at or engagement_fetch_attempts
    These are managed by the engagement_updater to prevent double incrementing.
    
    Rules:
    1. If views OR likes is NULL: status="missing", training=False, score=0.0
    2. If age_days < 3: status="unstable", training=False, score=0.2
    3. If age_days >= 5: status="stable", training=True, score=1.0
    4. Otherwise: status="unstable", training=False, score=0.5
    """
    # Note: engagement_fetch_attempts and engagement_last_updated_at 
    # are managed by engagement_updater to prevent double incrementing
    
    # Rule 1: Check engagement data availability
    if not hasattr(reel, 'views') or not hasattr(reel, 'likes'):
        logger.warning(
            "engagement_evaluation_missing_fields reel_id=%s",
            getattr(reel, 'id', 'unknown'),
            extra={"reel_id": getattr(reel, 'id', None)}
        )
        return
    
    if reel.views is None or reel.likes is None:
        old_status = getattr(reel, 'engagement_status', 'unknown')
        reel.engagement_status = "missing"
        reel.is_active_for_training = False
        reel.stability_score = 0.0
        
        logger.info(
            "engagement_status_missing reel_id=%s views=%s likes=%s old_status=%s",
            getattr(reel, 'id', 'unknown'),
            reel.views,
            reel.likes,
            old_status,
            extra={"reel_id": getattr(reel, 'id', None)}
        )
        return
    
    # Rule 2: Compute reel age
    if not hasattr(reel, 'publish_time') or reel.publish_time is None:
        logger.warning(
            "engagement_evaluation_no_publish_time reel_id=%s",
            getattr(reel, 'id', 'unknown'),
            extra={"reel_id": getattr(reel, 'id', None)}
        )
        # Default to unstable if no publish time
        old_status = getattr(reel, 'engagement_status', 'unknown')
        reel.engagement_status = "unstable"
        reel.is_active_for_training = False
        reel.stability_score = 0.2
        
        logger.info(
            "engagement_status_no_publish_time reel_id=%s status=unstable",
            getattr(reel, 'id', 'unknown'),
            extra={"reel_id": getattr(reel, 'id', None)}
        )
        return
    
    # Import datetime only when needed for age calculation
    from datetime import datetime
    age_days = (datetime.utcnow() - reel.publish_time).days
    old_status = getattr(reel, 'engagement_status', 'unknown')
    
    # Rule 3: Very recent reels (< 3 days) are unstable
    if age_days < 3:
        reel.engagement_status = "unstable"
        reel.is_active_for_training = False
        reel.stability_score = 0.2
        
        logger.info(
            "engagement_status_unstable_young reel_id=%s age_days=%d views=%s likes=%s old_status=%s",
            getattr(reel, 'id', 'unknown'),
            age_days,
            reel.views,
            reel.likes,
            old_status,
            extra={"reel_id": getattr(reel, 'id', None)}
        )
        return
    
    # Rule 4: Mature reels (>= 5 days) are stable
    if age_days >= 5:
        reel.engagement_status = "stable"
        reel.is_active_for_training = True
        reel.stability_score = 1.0
        
        logger.info(
            "engagement_status_stable_mature reel_id=%s age_days=%d views=%s likes=%s old_status=%s",
            getattr(reel, 'id', 'unknown'),
            age_days,
            reel.views,
            reel.likes,
            old_status,
            extra={"reel_id": getattr(reel, 'id', None)}
        )
        return
    
    # Rule 5: Intermediate age (3-4 days) are unstable but not missing
    reel.engagement_status = "unstable"
    reel.is_active_for_training = False
    reel.stability_score = 0.5
    
    logger.info(
        "engagement_status_unstable_intermediate reel_id=%s age_days=%d views=%s likes=%s old_status=%s",
        getattr(reel, 'id', 'unknown'),
        age_days,
        reel.views,
        reel.likes,
        old_status,
        extra={"reel_id": getattr(reel, 'id', None)}
    )
