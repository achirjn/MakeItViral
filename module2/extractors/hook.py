from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass(frozen=True)
class HookConfig:
    """
    Deterministic MVP thresholds (tunable later).
    """

    high_motion_threshold: float = 0.08
    low_motion_threshold: float = 0.03
    fast_scene_change_threshold: float = 0.5  # changes per second
    ocr_min_chars: int = 15


class HookExtractor(BaseExtractor):
    """
    PHASE 11: Hook heuristic extractor (deterministic MVP).

    Uses:
    - motion intermediate output (required)
    - ocr intermediate output (optional)

    Returns a combined list of hook signals and recommendations.
    """

    def __init__(self, config: HookConfig | None = None) -> None:
        self._config = config or HookConfig()

    @property
    def name(self) -> str:
        return "hook"

    @property
    def dependencies(self) -> List[str]:
        # OCR is optional (Tier-2). We should not depend on it or we'd get skipped.
        return ["motion"]

    @property
    def output_keys(self) -> List[str]:
        return [
            "hook_signals",
            "hook_recommendations",
            "hook_motion_score",
            "hook_scene_change_rate",
            "hook_ocr_present",
        ]

    @property
    def is_critical(self) -> bool:
        return True

    @property
    def requires_gpu(self) -> bool:
        return False

    async def run(self, context: ExtractionContext) -> ExtractorResult:
        motion_entry = context.intermediate_outputs.get("motion") or {}
        motion_feats = motion_entry.get("features") if isinstance(motion_entry, dict) else None
        if not isinstance(motion_feats, dict):
            return ExtractorResult.failed("missing_motion_features")

        motion_score = motion_feats.get("motion_score")
        scene_change_rate = motion_feats.get("scene_change_rate")
        if not isinstance(motion_score, (int, float)) or not isinstance(scene_change_rate, (int, float)):
            return ExtractorResult.failed("invalid_motion_features")

        ocr_text = ""
        ocr_entry = context.intermediate_outputs.get("ocr") or {}
        if isinstance(ocr_entry, dict) and ocr_entry.get("status") == "success":
            ocr_feats = ocr_entry.get("features")
            if isinstance(ocr_feats, dict):
                ocr_text = _clean_text(str(ocr_feats.get("ocr_text") or ""))

        ocr_present = len(ocr_text) >= self._config.ocr_min_chars

        signals: List[str] = []
        recs: List[str] = []

        # Motion-based hook signals
        if motion_score >= self._config.high_motion_threshold:
            signals.append("high_motion_energy")
        elif motion_score <= self._config.low_motion_threshold:
            signals.append("low_motion_energy")
            recs.append("Add an early motion change (camera move, cut, gesture) in the first 1–2 seconds.")
        else:
            signals.append("moderate_motion_energy")

        if scene_change_rate >= self._config.fast_scene_change_threshold:
            signals.append("fast_scene_changes")
        else:
            signals.append("slow_scene_changes")
            recs.append("Consider 1 additional early cut to increase pacing in the hook window.")

        # OCR-based hook signals (optional)
        if ocr_present:
            signals.append("on_screen_text_present")
        else:
            signals.append("on_screen_text_absent_or_weak")
            recs.append("Add 3–6 words of on-screen text stating the payoff or claim.")

        # Keep deterministic and compact: dedupe recommendations while preserving order.
        seen: set[str] = set()
        recs_deduped: List[str] = []
        for r in recs:
            if r not in seen:
                seen.add(r)
                recs_deduped.append(r)

        return ExtractorResult.success(
            {
                "hook_signals": signals,
                "hook_recommendations": recs_deduped,
                "hook_motion_score": float(motion_score),
                "hook_scene_change_rate": float(scene_change_rate),
                "hook_ocr_present": bool(ocr_present),
            }
        )

