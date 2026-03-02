from __future__ import annotations

from typing import List

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.remote_inference import call_remote_inference
from module2.logging_config import get_logger

logger = get_logger("extractor.remote_inference")


class RemoteInferenceExtractor(BaseExtractor):
    @property
    def name(self) -> str:
        return "remote_inference"

    @property
    def dependencies(self) -> List[str]:
        return ["video_fetcher"]  # optionally add "video_probe"

    @property
    def output_keys(self) -> List[str]:
        return [
            "transcript",
            "text_embedding",
            "clip_embedding",
            "inference_version",
        ]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def produces(self) -> set[str]:
        return {"inference"}

    @property
    def requires_gpu(self) -> bool:
        return True

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.video_path:
            return ExtractorResult.failed("missing_video_path")

        logger.info(
            "remote_inference_started",
            extra={"reel_id": context.reel_id},
        )

        result = await call_remote_inference(context, context.video_path)

        if not result:
            return ExtractorResult.failed("remote_inference_failed")

        context.transcript = result.get("transcript")
        context.text_embedding = result.get("text_embedding")
        context.clip_embedding = result.get("clip_embedding")
        context.inference_version = result.get("inference_version")

        logger.info(
            "remote_inference_completed",
            extra={
                "reel_id": context.reel_id,
                "text_dim": len(context.text_embedding or []),
                "clip_dim": len(context.clip_embedding or []),
            },
        )

        return ExtractorResult.success(
            {
                "transcript": context.transcript,
                "text_embedding": context.text_embedding,
                "clip_embedding": context.clip_embedding,
                "inference_version": context.inference_version,
            }
        )
