from __future__ import annotations

import logging
from typing import Any, Dict, Set

from playwright.async_api import Response, async_playwright
from sqlalchemy.orm import Session

from discovery.auth import get_authenticated_context, human_delay
from ingestion.ingestion_service import Ingestor

from .trending import _build_reel_data, _extract_reels_from_payload, _is_reels_response


logger = logging.getLogger(__name__)


async def discover_hashtag(
    session: Session,
    hashtag: str,
    limit: int = 50,
    account_id: str = "default",
) -> None:
    """
    Discover reels for a given hashtag and ingest them.
    """
    tag = hashtag.lstrip("#")
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
                payload: Dict[str, Any] = await response.json()
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

                reel_data["discovery_source"] = f"hashtag:{tag}"

                try:
                    Ingestor(session).ingest(reel_data)
                    seen_shortcodes.add(shortcode)
                    success_count += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ingestion_failure: %s", exc)

        page.on("response", handle_response)

        await page.goto(f"https://www.instagram.com/explore/tags/{tag}/")
        await human_delay(2.0, 0.5)

        max_scrolls = 20
        for _ in range(max_scrolls):
            if success_count >= limit:
                break
            await page.mouse.wheel(0, 1200)
            await human_delay(2.0, 0.8)

