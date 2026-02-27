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
    seen: set[str] = set()

    def _add_reel(media_obj: Dict[str, Any]) -> None:
        code = media_obj.get("code") or media_obj.get("shortcode")
        if code and code not in seen:
            seen.add(code)
            reels.append(media_obj)

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            # 1. Base case: This dict *is* a media object (REST or raw)
            if "code" in obj or "shortcode" in obj:
                # But only if it actually looks like a media object and not a deeply nested config
                if "user" in obj or "owner" in obj or "caption" in obj:
                    _add_reel(obj)
                    return

            # 2. Base case: GraphQL edges
            if "edges" in obj and isinstance(obj["edges"], list):
                for edge in obj["edges"]:
                    if isinstance(edge, dict):
                        node = edge.get("node")
                        if isinstance(node, dict):
                            media = node.get("media")
                            if isinstance(media, dict):
                                _add_reel(media)
                            else:
                                _add_reel(node)
                # Don't return here, there might be other edge arrays parallel to this

            # Recursive step
            for v in obj.values():
                _walk(v)

        elif isinstance(obj, list):
            for i in obj:
                _walk(i)

    # Start walking from 'data' slightly deeper if it exists to save time, else from root
    _walk(payload.get("data") or payload)

    return reels


def _build_reel_data(raw: Dict[str, Any]) -> Dict[str, Any] | None:
    shortcode = raw.get("code") or raw.get("shortcode")
    if not shortcode:
        return None

    # REST shape: raw["user"]; GraphQL shape: raw["owner"]
    user = raw.get("user") or raw.get("owner") or {}
    username = user.get("username")
    if not username:
        return None

    # REST shape: image_versions2.candidates[0].url; GraphQL shape: display_url/thumbnail_src
    thumbnail_url = None
    image_versions = raw.get("image_versions2") or {}
    candidates = image_versions.get("candidates") or []
    if candidates:
        thumbnail_url = candidates[0].get("url")
    if not thumbnail_url:
        thumbnail_url = raw.get("display_url") or raw.get("thumbnail_src")
    if not thumbnail_url:
        return None

    # REST shape: caption.text; GraphQL shape: edge_media_to_caption.edges[0].node.text
    caption_text = None
    caption_obj = raw.get("caption") or {}
    if isinstance(caption_obj, dict):
        caption_text = caption_obj.get("text")
    if caption_text is None:
        edges = ((raw.get("edge_media_to_caption") or {}).get("edges") or [])
        if edges:
            node = (edges[0] or {}).get("node") or {}
            caption_text = node.get("text")

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

    # REST: view_count/like_count/comment_count; GraphQL: video_view_count + edges
    views = raw.get("view_count")
    if views is None:
        views = raw.get("video_view_count")

    likes = raw.get("like_count")
    if likes is None:
        likes = (raw.get("edge_liked_by") or {}).get("count")

    comments = raw.get("comment_count")
    if comments is None:
        comments = (raw.get("edge_media_to_comment") or {}).get("count")

    publish_time = raw.get("publish_time")
    if publish_time is None:
        publish_time_int = raw.get("taken_at") or raw.get("taken_at_timestamp")
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
        browser = context.browser
        try:
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

                    shortcode = raw_reel.get("code") or raw_reel.get("shortcode")
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
                logger.warning(
                    "Scraper finished scrolling but found 0 reels. The Instagram DOM or API response structure may have changed."
                )
        finally:
            try:
                await context.close()
            finally:
                if browser is not None:
                    await browser.close()
