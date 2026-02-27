from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.transcript")


@dataclass(frozen=True)
class TranscriptConfig:
    """
    Phase 10: keep transcription backend optional.

    If no backend is available in the environment, the extractor will be skipped.
    """

    language: Optional[str] = None


_MODEL_CACHE = None


class TranscriptExtractor(BaseExtractor):
    """
    PHASE 10: Optional fast transcription over context.audio_path (.wav).

    Returns:
      - transcript: string
    """

    def __init__(self, config: TranscriptConfig | None = None) -> None:
        self._config = config or TranscriptConfig()

    @property
    def name(self) -> str:
        return "transcript"

    @property
    def dependencies(self) -> List[str]:
        return ["audio"]

    @property
    def output_keys(self) -> List[str]:
        return ["transcript"]

    @property
    def is_critical(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.audio_path:
            return ExtractorResult.skipped("missing_audio_path")

        # Optional backend: faster-whisper (if installed). We do not add deps here.
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception:  # noqa: BLE001
            logger.warning(
                "whisper_missing_backend",
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.skipped("transcription_backend_not_available")

        try:
            global _MODEL_CACHE
            if _MODEL_CACHE is None:
                _MODEL_CACHE = WhisperModel("base", device="cpu", compute_type="int8")

            model = _MODEL_CACHE
            logger.debug(
                "whisper_invoked",
                extra={"reel_id": context.reel_id},
            )
            segments, _info = await asyncio.to_thread(
                model.transcribe,
                context.audio_path,
                language=self._config.language,
            )
            text_parts: List[str] = []
            for seg in segments:
                seg_text = getattr(seg, "text", None)
                if isinstance(seg_text, str) and seg_text.strip():
                    text_parts.append(seg_text.strip())
            transcript = " ".join(text_parts).strip()
            return ExtractorResult.success({"transcript": transcript})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Transcription failed: %s", exc)
            return ExtractorResult.failed(f"transcription_failed:{exc}")
