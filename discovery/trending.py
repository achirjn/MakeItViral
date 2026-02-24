from __future__ import annotations

import logging
from typing import Any, Dict, Set

from playwright.async_api import Response, async_playwright
from sqlalchemy.orm import Session

from db.models import IngestionLogStatus
from discovery.auth import get_authenticated_context, human_delay
from ingestion.ingestion_service import Ingestor


logger = logging.getLogger(__name__)


def _is_reels_response(response: Response) -> bool:
    url = response.url
    return "instagram.com" in url and ("reels" in url or "clips" in url or "graphql" in url)


def _extract_reels_from_payload(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    """
    Best-effort extraction of reel-like objects from Instagram JSON.
    The exact structure may evolve; this function should be adapted as needed.
    """
    reels: list[Dict[str, Any]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if obj.get("__typename") in {"GraphVideo", "XDTGraphVideo"} or "shortcode" in obj:
                reels.append(obj)
            for value in obj.values():
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)
    return reels


def _build_reel_data(raw: Dict[str, Any]) -> Dict[str, Any] | None:
    shortcode = raw.get("shortcode")
    if not shortcode:
        return None

    owner = raw.get("owner") or {}
    username = owner.get("username")
    if not username:
        return None

    thumbnail_url = raw.get("display_url") or raw.get("thumbnail_src")
    if not thumbnail_url:
        return None

    caption_edges = (
        (raw.get("edge_media_to_caption") or {}).get("edges")
        or []
    )
    caption_text = None
    if caption_edges:
        first = caption_edges[0].get("node") or {}
        caption_text = first.get("text")

    hashtags: list[str] = []
    if isinstance(caption_text, str):
        hashtags = [
            token[1:]
            for token in caption_text.split()
            if token.startswith("#") and len(token) > 1
        ]

    audio_name = raw.get("accessibility_caption") or None

    views = raw.get("video_view_count")
    likes = (raw.get("edge_liked_by") or {}).get("count")
    comments = (raw.get("edge_media_to_comment") or {}).get("count")

    publish_time = raw.get("taken_at_timestamp")

    reel_data: Dict[str, Any] = {
        "reel_url": f"https://www.instagram.com/reel/{shortcode}/",
        "thumbnail_url": thumbnail_url,
        "caption": caption_text,
        "hashtags": hashtags or None,
        "audio_name": audio_name,
        "views": views,
        "likes": likes,
        "comments": comments,
        "publish_time": publish_time,
        "creator": {
            "username": username,
            "followers": None,
            "verified": owner.get("is_verified", False),
            "category": None,
        },
        "discovery_source": "trending",
    }
    return reel_data


async def discover_trending(
    session: Session,
    limit: int = 50,
    account_id: str = "default",
) -> None:
    """
    Discover trending reels on Instagram and ingest them.
    """
    seen_shortcodes: Set[str] = set()
    success_count = 0

    async with async_playwright() as p:
        context = await get_authenticated_context(p, account_id=account_id)
        page = await context.new_page()

        async def handle_response(response: Response) -> None:
            nonlocal success_count

            if success_count >= limit:
                return
            if not _is_reels_response(response):
                return

            try:
                payload = await response.json()
            except Exception:  # noqa: BLE001
                return

            for raw_reel in _extract_reels_from_payload(payload):
                if success_count >= limit:
                    break

                reel_data = _build_reel_data(raw_reel)
                if reel_data is None:
                    logger.info("metadata_incomplete: unable to build reel_data")
                    continue

                shortcode = raw_reel.get("shortcode")
                if not shortcode:
                    logger.info("metadata_incomplete: missing shortcode")
                    continue

                if shortcode in seen_shortcodes:
                    logger.info("dedupe_skip: shortcode=%s", shortcode)
                    continue

                try:
                    Ingestor(session).ingest(reel_data)
                    seen_shortcodes.add(shortcode)
                    success_count += 1
                except Exception as exc:  # noqa: BLE001
                    status = getattr(exc, "status", None)
                    if isinstance(status, IngestionLogStatus) and status == IngestionLogStatus.FAILED:
                        logger.warning("ingestion_failure: %s", exc)
                    else:
                        logger.warning("ingestion_failure: %s", exc)

        page.on("response", handle_response)

        await page.goto("https://www.instagram.com/reels/explore/")
        await human_delay(2.0, 0.5)

        max_scrolls = 20
        for _ in range(max_scrolls):
            if success_count >= limit:
                break
            await page.mouse.wheel(0, 1200)
            await human_delay(2.0, 0.8)

