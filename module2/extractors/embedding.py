from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from module2.config import USE_REMOTE_INFERENCE
from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.embedding")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_VERSION = "1"
EMBEDDING_VERSION = "v1_mvp_embedding"



@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = EMBEDDING_MODEL_NAME
    model_version: str = EMBEDDING_MODEL_VERSION
    embedding_version: str = EMBEDDING_VERSION


class EmbeddingExtractor(BaseExtractor):
    """
    Text embedding extractor (384-dim MiniLM).

    Remote mode only: reads text_embedding from cached Colab response.
    No local sentence-transformers loading.
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self._config = config or EmbeddingConfig()

    @property
    def name(self) -> str:
        return "embedding"

    @property
    def dependencies(self) -> List[str]:
        return ["remote_inference"]

    @property
    def output_keys(self) -> List[str]:
        return [
            "embedding",
            "embedding_model_name",
            "embedding_model_version",
            "embedding_version",
            "text_bundle_hash",
        ]

    @property
    def is_critical(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    @property
    def produces(self) -> set[str]:
        return {"embedding"}

    @property
    def optional_requires(self) -> set[str]:
        return {"ocr", "transcript"}

    @property
    def heavy(self) -> bool:
        return True

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not USE_REMOTE_INFERENCE:
            return ExtractorResult.failed("remote_inference_disabled")

        if not context.text_embedding:
            return ExtractorResult.failed("missing_text_embedding")

        # Build deterministic hash from all text sources
        caption = (context.metadata.get("caption") or "").strip()
        hashtags = context.metadata.get("hashtags") or []
        if isinstance(hashtags, list):
            hashtags_txt = " ".join(
                f"#{h}" for h in hashtags if isinstance(h, str) and h.strip()
            )
        else:
            hashtags_txt = ""

        ocr_txt = ""
        ocr_entry = context.intermediate_outputs.get("ocr") or {}
        if isinstance(ocr_entry, dict) and ocr_entry.get("status") == "success":
            feats = ocr_entry.get("features")
            if isinstance(feats, dict):
                ocr_txt = str(feats.get("ocr_text") or "").strip()

        transcript_entry = context.intermediate_outputs.get("transcript") or {}
        transcript_feats = transcript_entry.get("features") or {}
        transcript = transcript_feats.get("transcript", "")
        
        sections = [
            "[CAPTION]",
            caption,
            "[HASHTAGS]",
            hashtags_txt,
            "[OCR]",
            ocr_txt,
            "[TRANSCRIPT]",
            transcript,
        ]
        text_bundle = "\n".join(sections).strip()
        bundle_hash = hashlib.sha256(text_bundle.encode("utf-8")).hexdigest()

        logger.info(
            "embedding_from_context dim=%d hash=%s version=%s",
            len(context.text_embedding),
            bundle_hash[:12],
            context.inference_version,
            extra={"reel_id": context.reel_id},
        )

        return ExtractorResult.success(
            {
                "embedding": context.text_embedding,
                "embedding_model_name": self._config.model_name,
                "embedding_model_version": self._config.model_version,
                "embedding_version": self._config.embedding_version,
                "text_bundle_hash": bundle_hash,
            }
        )

