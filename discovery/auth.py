from __future__ import annotations

import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Final

from playwright.async_api import BrowserContext, Page, Playwright


logger = logging.getLogger(__name__)

AUTH_STATE_DIR: Final[Path] = Path(__file__).parent / "auth_state"
AUTH_STATE_BASENAME: Final[str] = "instagram_{account_id}.json"


async def human_delay(base: float = 1.0, jitter: float = 0.5) -> None:
    """Sleep for a human-like random delay."""
    delay = max(0.0, random.normalvariate(base, jitter))
    await asyncio.sleep(delay)


async def retry_goto(
    page: Page,
    url: str,
    attempts: int = 3,
    base_delay: float = 2.0,
) -> None:
    """Navigate with simple retry and backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await page.goto(url, wait_until="networkidle")
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Navigation attempt %s to %s failed: %s",
                attempt,
                url,
                exc,
            )
            await asyncio.sleep(base_delay * attempt)
    raise RuntimeError(f"Failed to navigate to {url}") from last_exc


def _auth_state_path(account_id: str) -> Path:
    AUTH_STATE_DIR.mkdir(parents=True, exist_ok=True)
    filename = AUTH_STATE_BASENAME.format(account_id=account_id)
    return AUTH_STATE_DIR / filename


async def get_authenticated_context(
    playwright: Playwright,
    account_id: str = "default",
    headless: bool | None = None,
) -> BrowserContext:
    """
    Return an authenticated BrowserContext using persisted storageState.

    If no storage state exists for the given account_id, this will:
    - launch a visible browser window
    - navigate to Instagram login
    - wait for manual login
    - persist storageState for future runs
    """
    storage_path = _auth_state_path(account_id)
    browser = await playwright.chromium.launch(
        headless=headless if headless is not None else bool(os.getenv("PLAYWRIGHT_HEADLESS", "0") == "1")
    )

    if storage_path.exists():
        logger.info("Using existing Instagram auth state from %s", storage_path)
        context = await browser.new_context(storage_state=str(storage_path))
        return context

    logger.info("No auth state found, starting manual login flow at %s", storage_path)
    context = await browser.new_context()
    page = await context.new_page()
    await retry_goto(page, "https://www.instagram.com/accounts/login/")

    print(  # noqa: T201
        "\n[Instagram Login Required] Please log in manually in the opened browser window.\n"
        "After login completes and the feed loads, press Enter here to continue..."
    )
    input()  # block until user confirms login  # noqa: PLW1510

    await context.storage_state(path=str(storage_path))
    logger.info("Stored Instagram auth state at %s", storage_path)

    return context

