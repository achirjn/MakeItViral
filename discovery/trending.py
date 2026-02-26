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
    url = response.url.lower()
    if "instagram.com" not in url:
        return False

    reel_endpoints = [
        "/api/graphql",
        "/graphql/query",
        "/api/v1/clips/",
        "/api/v1/feed/reels_media/",
        "/api/v1/media/",
    ]
    return any(ep in url for ep in reel_endpoints)


def _extract_reels_from_payload(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    reels: list[Dict[str, Any]] = []

    data = payload.get("data") or {}
    clips = data.get("xdt_api__v1__clips__home__connection_v2") or {}

    edges = clips.get("edges") or []
    for edge in edges:
        node = edge.get("node") or {}
        media = node.get("media")
        if isinstance(media, dict):
            reels.append(media)

    return reels


def _build_reel_data(raw: Dict[str, Any]) -> Dict[str, Any] | None:
    shortcode = raw.get("code")
    if not shortcode:
        return None

    user = raw.get("user") or {}
    username = user.get("username")
    if not username:
        return None

    image_versions = raw.get("image_versions2") or {}
    candidates = image_versions.get("candidates") or []
    thumbnail_url = candidates[0].get("url") if candidates else None
    if not thumbnail_url:
        return None

    caption_obj = raw.get("caption") or {}
    caption_text = caption_obj.get("text")

    hashtags = []
    if isinstance(caption_text, str):
        hashtags = [
            token[1:]
            for token in caption_text.split()
            if token.startswith("#") and len(token) > 1
        ]

    clips_metadata = raw.get("clips_metadata") or {}
    music_info = clips_metadata.get("music_info") or {}
    music_asset = music_info.get("music_asset_info") or {}
    original_sound = clips_metadata.get("original_sound_info") or {}

    audio_name = music_asset.get("title") or original_sound.get("original_audio_title")

    views = raw.get("view_count")
    likes = raw.get("like_count")
    comments = raw.get("comment_count")
    publish_time_int = raw.get("taken_at")
    publish_time = None
    if publish_time_int:
        from datetime import datetime, timezone

        publish_time = datetime.fromtimestamp(publish_time_int, tz=timezone.utc)

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
            "verified": user.get("is_verified", False),
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
                logger.info("Intercepted valid JSON from: %s", response.url)

                # Dump safely to disk for inspection
                import json
                import time

                dump_file = f"payload_dump_{int(time.time()*1000)}.json"
                with open(dump_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                logger.info("Dumped payload to %s", dump_file)
            except Exception:  # noqa: BLE001
                return

            extracted_reels = _extract_reels_from_payload(payload)
            if extracted_reels:
                logger.info(
                    "Found %d reel objects in payload from %s",
                    len(extracted_reels),
                    response.url,
                )

            for raw_reel in extracted_reels:
                if success_count >= limit:
                    break

                reel_data = _build_reel_data(raw_reel)
                if reel_data is None:
                    logger.info("metadata_incomplete: unable to build reel_data")
                    continue

                shortcode = raw_reel.get("code")
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
                    if (
                        isinstance(status, IngestionLogStatus)
                        and status == IngestionLogStatus.FAILED
                    ):
                        logger.warning("ingestion_failure: %s", exc)
                    else:
                        logger.warning("ingestion_failure: %s", exc)

        page.on("response", handle_response)

        try:
            await page.goto(
                "https://www.instagram.com/reels/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
        except Exception as e:
            logger.warning("Goto timed out, but proceeding anyway: %s", e)

        await human_delay(3.0, 1.0)

        max_scrolls = 20
        for i in range(max_scrolls):
            if success_count >= limit:
                break

            logger.info(
                "Scroll %d/%d... (Found %d/%d reels so far)",
                i + 1,
                max_scrolls,
                success_count,
                limit,
            )

            await page.mouse.wheel(0, 1500)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            await human_delay(2.5, 1.0)

        if success_count == 0:
            logger.error(
                "Scraper finished scrolling but found 0 reels. The Instagram DOM or API response structure has likely changed."
            )
            raise RuntimeError(
                "Zero reels scraped. Check the debug logs to see if any valid JSON was intercepted."
            )
