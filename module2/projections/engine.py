from __future__ import annotations

from typing import Any, Dict

from module2.context import ExtractionContext
from module2.logging_config import get_logger


PROJECTION_VERSION = "v1"
VECTOR_VERSION = "v1_embedding_miniLM_384"

REQUIRED_PROJECTION_FEATURES: set[str] = {
    "hook_score",
    "motion_score",
}

OPTIONAL_PROJECTION_FEATURES: set[str] = {
    "llm_hook_score",
    "llm_hook_confidence",
    "embedding",
}

logger = get_logger("projection")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def compute_projections(context: ExtractionContext) -> None:
    """
    Phase 12: compute-only projection engine.

    - Reads canonical signals from motion + hook intermediate outputs.
    - Computes hook_score, pacing_score, trend_score, confidence.
    - Never fails on missing inputs; reduces confidence accordingly.
    - Writes results into context.intermediate_outputs["projections"].
    """
    rid = context.reel_id

    motion_entry: Dict[str, Any] = context.intermediate_outputs.get("motion") or {}
    motion_feats = (
        motion_entry.get("features") if isinstance(motion_entry, dict) else None
    )
    if not isinstance(motion_feats, dict):
        motion_feats = {}

    hook_entry: Dict[str, Any] = context.intermediate_outputs.get("hook") or {}
    hook_feats = hook_entry.get("features") if isinstance(hook_entry, dict) else None
    if not isinstance(hook_feats, dict):
        hook_feats = {}

    motion_score = motion_feats.get("motion_score")
    scene_change_rate = motion_feats.get("scene_change_rate")
    hook_ocr_present = hook_feats.get("hook_ocr_present")

    logger.debug(
        "heuristic_signals motion_score=%s scene_change_rate=%s ocr_flag=%s",
        motion_score,
        scene_change_rate,
        hook_ocr_present,
        extra={"reel_id": rid},
    )

    # Presence tracking for confidence.
    present_required = 0
    present_optional = 0

    if isinstance(motion_score, (int, float)):
        present_required += 1
        m_norm = _clamp01(motion_score / 0.12)
    else:
        m_norm = 0.0

    if isinstance(scene_change_rate, (int, float)):
        present_required += 1
        s_norm = _clamp01(scene_change_rate / 0.7)
    else:
        s_norm = 0.0

    t_flag = bool(hook_ocr_present) if isinstance(hook_ocr_present, bool) else False
    if isinstance(hook_ocr_present, bool):
        present_optional += 1
    t_norm = 1.0 if t_flag else 0.0

    # Hook projection.
    hook_score = 0.5 * m_norm + 0.3 * s_norm + 0.2 * t_norm
    hook_score = _clamp01(hook_score)

    # LLM hook blending (Phase 14).
    llm_entry = context.intermediate_outputs.get("llm_hook")
    llm_features = (llm_entry or {}).get("features") or {}

    llm_hook_score = llm_features.get("llm_hook_score")
    llm_conf_raw = llm_features.get("llm_hook_confidence")

    if isinstance(llm_hook_score, (int, float)):
        L = max(0.0, min(1.0, float(llm_hook_score)))

        logger.debug(
            "llm_signals llm_hook_score=%.4f llm_confidence_raw=%s",
            L,
            llm_conf_raw,
            extra={"reel_id": rid},
        )

        # ---------- coverage confidence ----------
        metadata = context.metadata or {}
        caption = metadata.get("caption") or ""

        ocr_entry = context.intermediate_outputs.get("ocr")
        ocr_text = ((ocr_entry or {}).get("features") or {}).get("ocr_text", "")

        transcript_entry = context.intermediate_outputs.get("transcript")
        transcript_text = ((transcript_entry or {}).get("features") or {}).get(
            "transcript", ""
        )

        text_len = len(caption) + len(ocr_text) + len(transcript_text)
        coverage = max(0.0, min(1.0, text_len / 400.0))

        # ---------- agreement confidence ----------
        agreement = 1.0 - abs(hook_score - L)
        agreement = max(0.0, min(1.0, agreement))

        # ---------- calibrated confidence ----------
        if isinstance(llm_conf_raw, (int, float)):
            C_llm = max(0.0, min(1.0, float(llm_conf_raw)))
        else:
            C_llm = 0.5

        C = 0.5 * C_llm + 0.3 * coverage + 0.2 * agreement
        C = max(0.0, min(1.0, C))

        logger.debug(
            "calibrated_confidence coverage=%.4f agreement=%.4f final_confidence=%.4f",
            coverage,
            agreement,
            C,
            extra={"reel_id": rid},
        )

        # ---------- dynamic weights ----------
        w_L = 0.4 + 0.4 * C
        w_H = 1.0 - w_L

        logger.debug(
            "fusion_weights w_H=%.4f w_L=%.4f",
            w_H,
            w_L,
            extra={"reel_id": rid},
        )

        hook_score = w_H * hook_score + w_L * L
        hook_score = max(0.0, min(1.0, hook_score))

    # Pacing projection.
    pacing_score = 0.7 * s_norm + 0.3 * m_norm
    pacing_score = _clamp01(pacing_score)

    # Trend placeholder.
    trend_score = s_norm

    # Confidence calculation.
    required_count = 2  # motion_score, scene_change_rate
    optional_count = 1  # hook_ocr_present
    numerator = present_required + 0.5 * present_optional
    denominator = required_count + 0.5 * optional_count
    confidence = _clamp01(numerator / denominator) if denominator > 0 else 0.0

    logger.debug(
        "final_scores hook=%.4f pacing=%.4f trend=%.4f confidence=%.4f",
        hook_score,
        pacing_score,
        trend_score,
        confidence,
        extra={"reel_id": rid},
    )

    context.intermediate_outputs["projections"] = {
        "status": "success",
        "features": {
            "hook_score": hook_score,
            "pacing_score": pacing_score,
            "trend_score": trend_score,
            "confidence": confidence,
            "projection_version": PROJECTION_VERSION,
        },
        "error": None,
    }
