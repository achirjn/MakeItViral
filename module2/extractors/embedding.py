from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.embedding")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_VERSION = "1"
EMBEDDING_VERSION = "v1_mvp_embedding"

_MODEL_CACHE = None


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = EMBEDDING_MODEL_NAME
    model_version: str = EMBEDDING_MODEL_VERSION
    embedding_version: str = EMBEDDING_VERSION


class EmbeddingExtractor(BaseExtractor):
    """
    PHASE 13: Multimodal text embedding extractor using sentence-transformers all-MiniLM-L6-v2 (384-dim).

    - No DAG dependencies: runs whenever scheduled, reads whatever signals exist.
    - Lazy-loads sentence-transformers at runtime (not import time).
    - Singleton model prevents repeated loading across worker jobs.
    - Skips encoding if text_bundle_hash is unchanged from a previous run.
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self._config = config or EmbeddingConfig()

    @property
    def name(self) -> str:
        return "embedding"

    @property
    def dependencies(self) -> List[str]:
        # No dependencies: embedding runs independently and reads whatever
        # intermediate outputs are available at execution time.
        return []

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

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        # --- Build text bundle from available signals ---
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

        transcript_txt = ""
        tr_entry = context.intermediate_outputs.get("transcript") or {}
        if isinstance(tr_entry, dict) and tr_entry.get("status") == "success":
            feats_t = tr_entry.get("features")
            if isinstance(feats_t, dict):
                transcript_txt = str(feats_t.get("transcript") or "").strip()

        sections = [
            "[CAPTION]",
            caption,
            "[HASHTAGS]",
            hashtags_txt,
            "[OCR]",
            ocr_txt,
            "[TRANSCRIPT]",
            transcript_txt,
        ]
        text_bundle = "\n".join(sections).strip()

        # --- Deterministic hash (always computed, even for empty bundles) ---
        bundle_hash = hashlib.sha256(text_bundle.encode("utf-8")).hexdigest()

        # --- Pre-encoding cache: skip if hash + model version unchanged ---
        existing_emb = context.intermediate_outputs.get("_prev_embedding") or {}
        if isinstance(existing_emb, dict):
            if (
                existing_emb.get("text_bundle_hash") == bundle_hash
                and existing_emb.get("model_name") == self._config.model_name
                and existing_emb.get("model_version") == self._config.model_version
                and existing_emb.get("embedding_version")
                == self._config.embedding_version
            ):
                return ExtractorResult.skipped("embedding_unchanged")

        # --- Lazy import ---
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception:  # noqa: BLE001
            return ExtractorResult.skipped("sentence_transformers_not_available")

        # --- Singleton model loading ---
        global _MODEL_CACHE
        if _MODEL_CACHE is None:
            _MODEL_CACHE = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        model = _MODEL_CACHE

        # --- Encode ---
        emb = await asyncio.to_thread(
            model.encode, text_bundle, normalize_embeddings=False
        )
        embedding_list = [float(x) for x in emb.tolist()]

        return ExtractorResult.success(
            {
                "embedding": embedding_list,
                "embedding_model_name": self._config.model_name,
                "embedding_model_version": self._config.model_version,
                "embedding_version": self._config.embedding_version,
                "text_bundle_hash": bundle_hash,
                "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                "model_version": "v1",
                "embedding_version": "v1",
            }
        )
