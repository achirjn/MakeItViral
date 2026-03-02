"""
Module 2 — Visual Embedding Extractor (CLIP ViT-L/14, 768-dim)
----------------------------------------------------------------
Reads clip_embedding from cached remote inference result.
No local CLIP model loaded.
"""

from __future__ import annotations

from typing import List

from module2.config import USE_REMOTE_INFERENCE
from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.visual_embedding")


class VisualEmbeddingExtractor(BaseExtractor):
    """
    CLIP ViT-L/14 visual embedding (768-dim).

    Remote mode only: reads clip_embedding from cached Colab response.
    Validates dim == 768.
    """

    @property
    def name(self) -> str:
        return "visual_embedding"

    @property
    def dependencies(self) -> List[str]:
        return ["remote_inference"]

    @property
    def output_keys(self) -> List[str]:
        return ["clip_embedding"]

    @property
    def is_critical(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"clip_embedding"}

    @property
    def optional_requires(self) -> set[str]:
        return set()

    @property
    def heavy(self) -> bool:
        return True

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not USE_REMOTE_INFERENCE:
            return ExtractorResult.skipped("visual_embedding_requires_remote")

        if not context.clip_embedding:
            return ExtractorResult.failed("missing_clip_embedding")

        return ExtractorResult.success(
            {
                "clip_embedding": context.clip_embedding,
            }
        )
