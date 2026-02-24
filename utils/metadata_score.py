from __future__ import annotations

from typing import Any, Mapping


THUMBNAIL_WEIGHT = 0.24
CREATOR_WEIGHT = 0.12
VIEWS_WEIGHT = 0.18
LIKES_WEIGHT = 0.18
AUDIO_WEIGHT = 0.08
CAPTION_WEIGHT = 0.12
HASHTAGS_WEIGHT = 0.05
COMMENTS_WEIGHT = 0.04
PUBLISH_TIME_WEIGHT = 0.01

_TOTAL_WEIGHT = (
    THUMBNAIL_WEIGHT
    + CREATOR_WEIGHT
    + VIEWS_WEIGHT
    + LIKES_WEIGHT
    + AUDIO_WEIGHT
    + CAPTION_WEIGHT
    + HASHTAGS_WEIGHT
    + COMMENTS_WEIGHT
    + PUBLISH_TIME_WEIGHT
)


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return True


def compute_metadata_score(reel_data: Mapping[str, Any]) -> float:
    """
    Compute a weighted metadata completeness score for a reel.

    Expected reel_data keys:
    - thumbnail_url
    - creator (mapping with at least username) or creator_username
    - views
    - likes
    - audio_name
    - caption
    - hashtags (iterable)
    - comments
    - publish_time
    """
    score = 0.0

    thumbnail_present = _is_present(reel_data.get("thumbnail_url"))
    if thumbnail_present:
        score += THUMBNAIL_WEIGHT

    creator_info = reel_data.get("creator") or {}
    creator_username = None
    if isinstance(creator_info, Mapping):
        creator_username = creator_info.get("username")
    if creator_username is None:
        creator_username = reel_data.get("creator_username")
    if _is_present(creator_username):
        score += CREATOR_WEIGHT

    if _is_present(reel_data.get("views")):
        score += VIEWS_WEIGHT

    if _is_present(reel_data.get("likes")):
        score += LIKES_WEIGHT

    if _is_present(reel_data.get("audio_name")):
        score += AUDIO_WEIGHT

    if _is_present(reel_data.get("caption")):
        score += CAPTION_WEIGHT

    if _is_present(reel_data.get("hashtags")):
        score += HASHTAGS_WEIGHT

    if _is_present(reel_data.get("comments")):
        score += COMMENTS_WEIGHT

    if _is_present(reel_data.get("publish_time")):
        score += PUBLISH_TIME_WEIGHT

    # Guard against minor weight drift; clamp to [0, 1.0].
    if _TOTAL_WEIGHT > 0:
        score = min(score / _TOTAL_WEIGHT, 1.0)

    return float(score)

