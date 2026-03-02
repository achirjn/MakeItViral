from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from db.models import (
    IngestionLog,
    IngestionLogStatus,
    Reel,
)
from utils.creator_resolver import resolve_creator
from utils.metadata_score import compute_metadata_score


class Ingestor:
    """
    Handles ingestion of a single reel dictionary into the database.

    Responsibilities:
    - Validate minimum required fields.
    - Normalize and enforce Instagram reel permalink format.
    - Resolve (upsert) creator.
    - Insert or update Reel (behavior 1-B).
    - Create IngestionLog entries (success; partial failure logging when possible).
    - Leave ingestion_status as 'PENDING' (behavior 2-C).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest(self, reel_data: Mapping[str, Any]) -> Reel:
        """
        Ingest a single reel payload.

        Expected top-level keys (minimum for success):
        - reel_url
        - thumbnail_url
        - creator: { username, platform?, followers?, category?, verified? }

        Optional keys:
        - caption
        - hashtags
        - audio_name
        - views
        - likes
        - comments
        - publish_time
        - discovery_source
        """
        reel: Optional[Reel] = None

        try:
            normalized_url = self._normalize_reel_url(reel_data.get("reel_url"))
            thumbnail_url = self._require_non_empty(
                reel_data.get("thumbnail_url"), "thumbnail_url"
            )

            creator_info = reel_data.get("creator") or {}
            creator_username = (creator_info.get("username") or "").strip()
            if not creator_username:
                raise ValueError("creator.username is required for ingestion.")

            creator = resolve_creator(
                self.session,
                {
                    "username": creator_username,
                    "platform": creator_info.get("platform"),
                    "followers": creator_info.get("followers"),
                    "category": creator_info.get("category"),
                    "verified": creator_info.get("verified"),
                },
            )

            reel = (
                self.session.query(Reel)
                .filter(Reel.reel_url == normalized_url)
                .one_or_none()
            )

            if reel is None:
                reel = Reel(
                    reel_url=normalized_url,
                    thumbnail_url=thumbnail_url,
                    caption=reel_data.get("caption"),
                    hashtags=reel_data.get("hashtags"),
                    audio_name=reel_data.get("audio_name"),
                    views=reel_data.get("views"),
                    likes=reel_data.get("likes"),
                    comments=reel_data.get("comments"),
                    creator_id=creator.id,
                    publish_time=reel_data.get("publish_time"),
                    has_engagement_metrics=self._has_engagement_metrics(reel_data),
                    # ingestion_status stays default 'PENDING' in this module
                    is_training_eligible=False,
                    metadata_completeness_score=compute_metadata_score(reel_data),
                    discovery_source=reel_data.get("discovery_source"),
                )
                self.session.add(reel)
            else:
                reel.thumbnail_url = thumbnail_url
                reel.caption = reel_data.get("caption")
                reel.hashtags = reel_data.get("hashtags")
                reel.audio_name = reel_data.get("audio_name")
                reel.views = reel_data.get("views")
                reel.likes = reel_data.get("likes")
                reel.comments = reel_data.get("comments")
                reel.creator_id = creator.id
                reel.publish_time = reel_data.get("publish_time")
                reel.has_engagement_metrics = self._has_engagement_metrics(reel_data)
                reel.metadata_completeness_score = compute_metadata_score(reel_data)
                reel.discovery_source = reel_data.get("discovery_source")

            self.session.flush()

            log = IngestionLog(
                reel_id=reel.id,
                status=IngestionLogStatus.SUCCESS.value,
                error_message=None,
            )
            self.session.add(log)

            self.session.commit()
            self.session.refresh(reel)
            return reel

        except Exception as exc:  # noqa: BLE001
            self.session.rollback()

            if reel is not None and reel.id is not None:
                fail_log = IngestionLog(
                    reel_id=reel.id,
                    status=IngestionLogStatus.FAILED.value,
                    error_message=str(exc),
                )
                self.session.add(fail_log)
                self.session.commit()

            raise

    @staticmethod
    def _require_non_empty(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required and must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _has_engagement_metrics(reel_data: Mapping[str, Any]) -> bool:
        return any(
            reel_data.get(key) is not None
            for key in ("views", "likes", "comments")
        )

    @staticmethod
    def _normalize_reel_url(raw_url: Any) -> str:
        """
        Ensure the reel_url is stored as:
        https://www.instagram.com/reel/{shortcode}/
        """
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise ValueError("reel_url is required and must be a non-empty string.")

        parsed = urlparse(raw_url.strip())

        if parsed.scheme not in ("http", "https"):
            raise ValueError("reel_url must use http or https scheme.")

        if parsed.netloc not in ("www.instagram.com", "instagram.com"):
            raise ValueError("reel_url must be an Instagram URL.")

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2 or path_parts[0] != "reel":
            raise ValueError("reel_url must point to an Instagram reel.")

        shortcode = path_parts[1]
        if not shortcode:
            raise ValueError("reel_url must contain a valid reel shortcode.")

        normalized = f"https://www.instagram.com/reel/{shortcode}/"
        return normalized

