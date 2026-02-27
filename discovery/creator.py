from __future__ import annotations

import logging
from typing import Any, Dict, Set

from playwright.async_api import Response, async_playwright
from sqlalchemy.orm import Session

from discovery.auth import get_authenticated_context, human_delay
from ingestion.ingestion_service import Ingestor

from .trending import _build_reel_data, _extract_reels_from_payload, _is_reels_response


logger = logging.getLogger(__name__)


async def discover_creator_reels(
    session: Session,
    username: str,
    limit: int = 50,
    account_id: str = "default",
) -> None:
    """
    Discover reels for a specific creator and ingest them.
    """
    handle = username.lstrip("@").strip()
    if not handle:
        raise ValueError("username must be a non-empty string.")

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

                    shortcode = raw_reel.get("code") or raw_reel.get("shortcode")
                    if not shortcode:
                        logger.info("metadata_incomplete: missing shortcode")
                        continue

                    if shortcode in seen_shortcodes:
                        logger.info("dedupe_skip: shortcode=%s", shortcode)
                        continue

                    reel_data["discovery_source"] = f"creator:{handle}"

                    try:
                        Ingestor(session).ingest(reel_data)
                        seen_shortcodes.add(shortcode)
                        success_count += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("ingestion_failure: %s", exc)

            page.on("response", handle_response)

            try:
                await page.goto(
                    f"https://www.instagram.com/{handle}/reels/",
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
        finally:
            try:
                await context.close()
            finally:
                if browser is not None:
                    await browser.close()
