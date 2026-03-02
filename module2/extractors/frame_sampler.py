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


logger = get_logger("extractor.frame_sampler")


async def _run_subprocess(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class FrameSamplerConfig:
    ffmpeg_bin: str = "ffmpeg"
    fps: float = 1.0
    max_frames: int = 60
    image_format: str = "jpg"


class FrameSamplerExtractor(BaseExtractor):
    """
    PHASE 6: Sample frames using ffmpeg.

    Writes frames under context.temp_dir and appends paths to context.sampled_frames.
    """

    def __init__(self, config: FrameSamplerConfig | None = None) -> None:
        self._config = config or FrameSamplerConfig()

    @property
    def name(self) -> str:
        return "frame_sampler"

    @property
    def dependencies(self) -> List[str]:
        return ["video_probe"]

    @property
    def output_keys(self) -> List[str]:
        return ["sampled_frames", "frame_count", "frame_dir"]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"frames"}

    @property
    def requires(self) -> set[str]:
        return {"probe"}

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.video_path:
            return ExtractorResult.failed("missing_video_path")

        frames_dir = context.temp_path() / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        out_pattern = frames_dir / f"frame_%05d.{self._config.image_format}"

        cmd = [
            self._config.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            context.video_path,
            "-vf",
            f"fps={self._config.fps}",
            "-frames:v",
            str(self._config.max_frames),
            str(out_pattern),
        ]

        try:
            logger.debug(
                "ffmpeg_sampling_started",
                extra={"reel_id": context.reel_id},
            )
            await _run_subprocess(cmd)
        except FileNotFoundError:
            return ExtractorResult.failed("ffmpeg_not_found")
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip()
            logger.error(
                "ffmpeg_sampling_failure error=%s",
                msg[:80],
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.failed(f"ffmpeg_failed:{msg}")
        except Exception as exc:  # noqa: BLE001
            return ExtractorResult.failed(f"ffmpeg_error:{exc}")

        frame_paths = sorted(
            str(p) for p in frames_dir.glob(f"*.{self._config.image_format}")
        )
        if not frame_paths:
            return ExtractorResult.failed("no_frames_extracted")

        # Critical requirement: append directly into context.sampled_frames for cleanup guarantee.
        context.sampled_frames.extend(frame_paths)

        return ExtractorResult.success(
            {
                "sampled_frames": frame_paths,
                "frame_count": len(frame_paths),
                "frame_dir": str(frames_dir),
            }
        )
