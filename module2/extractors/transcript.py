from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from module2.config import USE_REMOTE_INFERENCE
from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.transcript")



@dataclass(frozen=True)
class TranscriptConfig:
    language: Optional[str] = None


class TranscriptExtractor(BaseExtractor):
    """
    Transcription extractor.

    Remote mode only: reads transcript from cached Colab response.
    No local model loading.
    """

    def __init__(self, config: TranscriptConfig | None = None) -> None:
        self._config = config or TranscriptConfig()

    @property
    def name(self) -> str:
        return "transcript"

    @property
    def dependencies(self) -> List[str]:
        return ["remote_inference"]

    @property
    def output_keys(self) -> List[str]:
        return ["transcript", "transcript_confidence"]

    @property
    def is_critical(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"transcript"}

    @property
    def requires(self) -> set[str]:
        return {"video"}

    @property
    def heavy(self) -> bool:
        return True

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not USE_REMOTE_INFERENCE:
            return ExtractorResult.failed("remote_inference_disabled")

        if not context.transcript:
            return ExtractorResult.failed("missing_transcript")

        confidence = getattr(context, "transcript_confidence", 0.0)

        logger.info(
            "transcript_from_context len=%d confidence=%.3f version=%s",
            len(context.transcript),
            confidence,
            context.inference_version,
            extra={"reel_id": context.reel_id},
        )

        return ExtractorResult.success(
            {
                "transcript": context.transcript,
                "transcript_confidence": confidence,
            }
        )

