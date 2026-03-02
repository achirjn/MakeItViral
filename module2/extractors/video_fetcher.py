from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from yt_dlp import YoutubeDL

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.video_fetcher")


def _storage_state_path(account_id: str) -> Path:
    # Locked source-of-truth for auth state reuse (Module-1).
    return Path("discovery") / "auth_state" / f"instagram_{account_id}.json"


def _write_netscape_cookies(
    storage_state_json_path: Path, cookie_file_path: Path
) -> None:
    """
    Convert Playwright storageState cookies -> Netscape cookies.txt for yt-dlp.
    """
    data = json.loads(storage_state_json_path.read_text(encoding="utf-8"))
    cookies = data.get("cookies") or []

    lines: List[str] = [
        "# Netscape HTTP Cookie File",
        "# This file is generated automatically. Do not edit.",
    ]

    for c in cookies:
        domain = c.get("domain") or ""
        name = c.get("name") or ""
        value = c.get("value") or ""
        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"

        # Include subdomains if cookie is set for a parent domain.
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"

        expires = c.get("expires")
        try:
            expires_int = int(expires) if expires not in (None, -1) else 0
        except Exception:  # noqa: BLE001
            expires_int = 0

        if not (domain and name):
            continue

        # domain \t include_subdomains \t path \t secure \t expires \t name \t value
        lines.append(
            "\t".join(
                [
                    domain,
                    include_subdomains,
                    path,
                    secure,
                    str(expires_int),
                    name,
                    value,
                ]
            )
        )

    cookie_file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class VideoFetcherExtractor(BaseExtractor):
    """
    PHASE 4: Download reel video using authenticated cookies from Module-1 Playwright storageState.
    Stores the temporary video path in context.video_path. Does not persist video.
    """

    @property
    def name(self) -> str:
        return "video_fetcher"

    @property
    def dependencies(self) -> List[str]:
        return []

    @property
    def output_keys(self) -> List[str]:
        return ["video_path", "video_download_seconds"]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"video"}

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        reel_url = (context.metadata.get("reel_url") or "").strip()
        if not reel_url:
            return ExtractorResult.failed("missing_reel_url")

        account_id = (
            context.metadata.get("account_id") or "default"
        ).strip() or "default"
        storage_state = _storage_state_path(account_id)
        if not storage_state.exists():
            return ExtractorResult.failed(f"missing_auth_state:{storage_state}")

        tmp_dir = context.temp_path()
        tmp_dir.mkdir(parents=True, exist_ok=True)

        cookies_path = tmp_dir / f"cookies_{account_id}.txt"
        _write_netscape_cookies(storage_state, cookies_path)

        out_template = tmp_dir / f"{context.reel_id}_%(playlist_index)s.%(ext)s"

        start = time.time()

        logger.info(
            "video_download_started",
            extra={"reel_id": context.reel_id},
        )
        try:
            ydl_opts: Dict[str, Any] = {
                "outtmpl": str(out_template),
                "format": "bv*+ba/b",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
            }

            def _download() -> None:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([reel_url])

            await asyncio.to_thread(_download)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "yt_dlp_failure error=%s",
                exc,
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.failed(f"download_failed:{exc}")

        downloaded_files = list(tmp_dir.glob(f"{context.reel_id}_*.mp4"))

        if not downloaded_files:
            return ExtractorResult.failed("download_failed:missing_output_file")

        # Take first video if multiple (carousel case)
        context.video_path = str(downloaded_files[0])
        elapsed = time.time() - start

        logger.info(
            "video_download_finished elapsed_s=%.3f path=%s",
            elapsed,
            context.video_path,
            extra={"reel_id": context.reel_id},
        )

        return ExtractorResult.success(
            {
                "video_path": context.video_path,
                "video_download_seconds": elapsed,
            }
        )
