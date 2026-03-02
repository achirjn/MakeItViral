from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.audio")


async def _run_subprocess(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class AudioConfig:
    ffmpeg_bin: str = "ffmpeg"
    sample_rate: int = 16000
    channels: int = 1


class AudioExtractor(BaseExtractor):
    """
    PHASE 10: Extract audio track from the downloaded video.

    - Writes a temporary WAV file into context.temp_dir
    - Sets context.audio_path for cleanup guarantee
    """

    def __init__(self, config: AudioConfig | None = None) -> None:
        self._config = config or AudioConfig()

    @property
    def name(self) -> str:
        return "audio"

    @property
    def dependencies(self) -> List[str]:
        # Locked DAG places audio extraction after frame sampling stage.
        return ["frame_sampler"]

    @property
    def output_keys(self) -> List[str]:
        return ["audio_path"]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"audio"}

    @property
    def requires(self) -> set[str]:
        return {"frames"}

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.video_path:
            return ExtractorResult.failed("missing_video_path")

        out_path = context.temp_path() / f"{context.reel_id}.wav"
        cmd = [
            self._config.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            context.video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(self._config.sample_rate),
            "-ac",
            str(self._config.channels),
            str(out_path),
        ]

        try:
            logger.debug(
                "audio_extraction_started",
                extra={"reel_id": context.reel_id},
            )
            await _run_subprocess(cmd)
        except FileNotFoundError:
            return ExtractorResult.failed("ffmpeg_not_found")
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip()
            return ExtractorResult.failed(f"ffmpeg_failed:{msg}")
        except Exception as exc:  # noqa: BLE001
            return ExtractorResult.failed(f"ffmpeg_error:{exc}")

        if not out_path.exists():
            return ExtractorResult.failed("audio_extract_failed:missing_output_file")

        context.audio_path = str(out_path)
        return ExtractorResult.success({"audio_path": context.audio_path})
