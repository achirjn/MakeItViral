from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.motion")


async def _run_subprocess(cmd: List[str]) -> subprocess.CompletedProcess[bytes]:
    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        check=True,
        capture_output=True,
    )


def _bytes_abs_diff_sum(a: bytes, b: bytes) -> int:
    # Scaled-down frames make this cheap enough in pure Python.
    return sum((x - y) if x >= y else (y - x) for x, y in zip(a, b, strict=False))


@dataclass(frozen=True)
class MotionConfig:
    ffmpeg_bin: str = "ffmpeg"
    downscale_width: int = 160
    scene_change_threshold: float = 0.15


class MotionExtractor(BaseExtractor):
    """
    PHASE 8: Motion extractor.

    Computes:
    - motion_score: mean normalized frame-diff energy across sampled frames
    - scene_change_rate: scene_change_count / duration_seconds (fallback per-frame rate)
    """

    def __init__(self, config: MotionConfig | None = None) -> None:
        self._config = config or MotionConfig()

    @property
    def name(self) -> str:
        return "motion"

    @property
    def dependencies(self) -> List[str]:
        return ["frame_sampler"]

    @property
    def output_keys(self) -> List[str]:
        return ["motion_score", "scene_change_rate"]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.sampled_frames:
            return ExtractorResult.failed("missing_sampled_frames")

        probe_entry = context.intermediate_outputs.get("video_probe")
        if not isinstance(probe_entry, dict) or probe_entry.get("status") != "success":
            return ExtractorResult.failed("missing_video_probe_features")

        probe_features = probe_entry.get("features")
        if not isinstance(probe_features, dict):
            return ExtractorResult.failed("missing_video_probe_features")

        in_w = probe_features.get("width")
        in_h = probe_features.get("height")
        duration = probe_features.get("duration")
        if not isinstance(in_w, int) or not isinstance(in_h, int):
            return ExtractorResult.failed("missing_resolution_for_motion")

        # Maintain aspect ratio and keep even height.
        out_w = max(2, int(self._config.downscale_width))
        out_h = int(round(out_w * in_h / in_w))
        if out_h % 2 == 1:
            out_h += 1
        out_h = max(2, out_h)

        frames_dir = Path(context.sampled_frames[0]).parent
        ext = Path(context.sampled_frames[0]).suffix.lstrip(".") or "jpg"
        # Use sequential pattern matching frame_sampler's output naming.
        # Avoids -pattern_type glob which is unsupported on Windows ffmpeg builds.
        seq_pattern = str(frames_dir / f"frame_%05d.{ext}")

        cmd = [
            self._config.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            seq_pattern,
            "-vf",
            f"scale={out_w}:{out_h},format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]

        try:
            proc = await _run_subprocess(cmd)
        except FileNotFoundError:
            return ExtractorResult.failed("ffmpeg_not_found")
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or b"").decode(errors="ignore").strip()
            return ExtractorResult.failed(f"ffmpeg_failed:{msg}")
        except Exception as exc:  # noqa: BLE001
            return ExtractorResult.failed(f"ffmpeg_error:{exc}")

        raw = proc.stdout or b""
        frame_size = out_w * out_h
        if frame_size <= 0:
            return ExtractorResult.failed("invalid_frame_size")

        frame_count = len(raw) // frame_size
        if frame_count < 2:
            return ExtractorResult.failed("insufficient_frames_for_motion")

        diffs: List[float] = []
        prev = raw[0:frame_size]
        for i in range(1, frame_count):
            cur = raw[i * frame_size : (i + 1) * frame_size]
            diff_sum = _bytes_abs_diff_sum(prev, cur)
            diff_norm = diff_sum / (frame_size * 255.0)
            diffs.append(float(diff_norm))
            prev = cur

        motion_score = sum(diffs) / len(diffs) if diffs else 0.0
        scene_changes = sum(
            1 for d in diffs if d >= self._config.scene_change_threshold
        )

        scene_change_rate: float
        duration_f: Optional[float] = None
        try:
            duration_f = float(duration) if duration is not None else None
        except Exception:  # noqa: BLE001
            duration_f = None

        if duration_f and duration_f > 0:
            scene_change_rate = scene_changes / duration_f
        else:
            scene_change_rate = scene_changes / max(1, len(diffs))

        return ExtractorResult.success(
            {
                "motion_score": float(motion_score),
                "scene_change_rate": float(scene_change_rate),
            }
        )
