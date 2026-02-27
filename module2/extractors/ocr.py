from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger


logger = get_logger("extractor.ocr")


def _dedupe_text(text: str) -> str:
    """
    Deduplicate aggregated OCR output by unique non-empty lines (stable order).
    """
    lines = [re.sub(r"\s+", " ", ln.strip()) for ln in text.splitlines()]
    seen: set[str] = set()
    out: List[str] = []
    for ln in lines:
        if not ln:
            continue
        if ln in seen:
            continue
        seen.add(ln)
        out.append(ln)
    return "\n".join(out).strip()


@dataclass(frozen=True)
class OcrConfig:
    lang: str = "eng"


class OcrExtractor(BaseExtractor):
    """
    PHASE 9: OCR extractor using pytesseract over sampled frames.

    Returns:
      - ocr_text: aggregated, deduplicated text across frames
    """

    def __init__(self, config: OcrConfig | None = None) -> None:
        self._config = config or OcrConfig()

    @property
    def name(self) -> str:
        return "ocr"

    @property
    def dependencies(self) -> List[str]:
        return ["frame_sampler"]

    @property
    def output_keys(self) -> List[str]:
        return ["ocr_text"]

    @property
    def is_critical(self) -> bool:
        return False

    @property
    def requires_gpu(self) -> bool:
        return False

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        if not context.sampled_frames:
            return ExtractorResult.skipped("no_sampled_frames")

        try:
            import pytesseract  # type: ignore
        except Exception:  # noqa: BLE001
            logger.warning(
                "ocr_dependency_missing dep=pytesseract",
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.skipped("pytesseract_not_available")

        try:
            from PIL import Image  # type: ignore
        except Exception:  # noqa: BLE001
            logger.warning(
                "ocr_dependency_missing dep=Pillow",
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.skipped("pillow_not_available")

        logger.debug(
            "tesseract_invoked frame_count=%d",
            len(context.sampled_frames),
            extra={"reel_id": context.reel_id},
        )

        aggregated: List[str] = []

        for frame_path in context.sampled_frames:
            try:
                img = await asyncio.to_thread(Image.open, frame_path)
                text = await asyncio.to_thread(
                    pytesseract.image_to_string, img, lang=self._config.lang
                )
                if text:
                    aggregated.append(text)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ocr_frame_failure error=%s",
                    str(exc)[:80],
                    extra={"reel_id": context.reel_id},
                )
                continue

        if not aggregated:
            return ExtractorResult.success({"ocr_text": ""})

        deduped = _dedupe_text("\n".join(aggregated))
        return ExtractorResult.success({"ocr_text": deduped})
