from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.video_probe")


def _parse_fraction(value: str) -> Optional[float]:
    """
    Parse ffprobe rate strings like "30000/1001" or "30/1".
    """
    if not value or not isinstance(value, str):
        return None
    if "/" not in value:
        try:
            return float(value)
        except Exception:  # noqa: BLE001
            return None
    num_s, den_s = value.split("/", 1)
    try:
        num = float(num_s)
        den = float(den_s)
        if den == 0:
            return None
        return num / den
    except Exception:  # noqa: BLE001
        return None


async def _run_subprocess(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class VideoProbeConfig:
    ffprobe_bin: str = "ffprobe"


class VideoProbeExtractor(BaseExtractor):
    """
    PHASE 5: Use ffprobe to extract duration, fps, resolution.
    """

    def __init__(self, config: VideoProbeConfig | None = None) -> None:
        self._config = config or VideoProbeConfig()

    @property
    def name(self) -> str:
        return "video_probe"

    @property
    def dependencies(self) -> List[str]:
        return ["video_fetcher"]

    @property
    def output_keys(self) -> List[str]:
        return [
            "duration",
            "fps",
            "resolution",
            "width",
            "height",
            "has_audio",
            "audio_codec",
            "audio_channels",
        ]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"probe"}

    @property
    def requires(self) -> set[str]:
        return {"video"}

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.video_path:
            return ExtractorResult.failed("missing_video_path")

        cmd = [
            self._config.ffprobe_bin,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            context.video_path,
        ]

        try:
            proc = await _run_subprocess(cmd)
        except FileNotFoundError:
            return ExtractorResult.failed("ffprobe_not_found")
        except subprocess.CalledProcessError as exc:
            msg = (exc.stderr or exc.stdout or "").strip()
            return ExtractorResult.failed(f"ffprobe_failed:{msg}")
        except Exception as exc:  # noqa: BLE001
            return ExtractorResult.failed(f"ffprobe_error:{exc}")

        try:
            payload: Dict[str, Any] = json.loads(proc.stdout or "{}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ffprobe JSON parse failed: %s", exc)
            return ExtractorResult.failed("ffprobe_invalid_json")

        streams = payload.get("streams") or []
        fmt = payload.get("format") or {}

        video_stream = None
        audio_stream = None
        for s in streams:
            if isinstance(s, dict) and s.get("codec_type") == "video":
                video_stream = s
                break

        for s in streams:
            if isinstance(s, dict) and s.get("codec_type") == "audio":
                audio_stream = s
                break

        if not isinstance(video_stream, dict):
            return ExtractorResult.failed("ffprobe_no_video_stream")

        width = video_stream.get("width")
        height = video_stream.get("height")

        has_audio = isinstance(audio_stream, dict)
        audio_codec = audio_stream.get("codec_name") if has_audio else None
        audio_channels = audio_stream.get("channels") if has_audio else None

        logger.info(
            "probe_audio has_audio=%s codec=%s channels=%s",
            has_audio,
            audio_codec,
            audio_channels,
            extra={"reel_id": context.reel_id},
        )

        fps = _parse_fraction(
            video_stream.get("avg_frame_rate") or ""
        ) or _parse_fraction(video_stream.get("r_frame_rate") or "")

        duration = None
        if isinstance(fmt, dict):
            duration = fmt.get("duration")
        if duration is None:
            duration = video_stream.get("duration")

        try:
            duration_f = float(duration) if duration is not None else None
        except Exception:  # noqa: BLE001
            duration_f = None

        if width is None or height is None or fps is None or duration_f is None:
            return ExtractorResult.failed("ffprobe_missing_required_fields")

        resolution = f"{width}x{height}"

        return ExtractorResult.success(
            {
                "duration": duration_f,
                "fps": float(fps),
                "resolution": resolution,
                "width": int(width),
                "height": int(height),
                "has_audio": has_audio,
                "audio_codec": audio_codec,
                "audio_channels": audio_channels,
            }
        )
