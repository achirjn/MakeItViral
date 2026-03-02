from __future__ import annotations

import uuid
from typing import Any, Dict, Mapping, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.module2_models import (
    ReelAudioFeatures,
    ReelEmbeddings,
    ReelFeatures,
    ReelProjections,
    ReelTextFeatures,
)
from module2.context import ExtractionContext
from module2.logging_config import get_logger


logger = get_logger("persistence")


def _uuid(reel_id: str) -> uuid.UUID:
    return uuid.UUID(reel_id)


def _coalesce_update(stmt, model_cls, columns: list[str]) -> dict:
    """
    Non-destructive upsert:
      col = COALESCE(EXCLUDED.col, table.col)
    """
    set_map: dict = {}
    for col in columns:
        set_map[col] = func.coalesce(
            getattr(stmt.excluded, col), getattr(model_cls, col)
        )
    # Only bump updated_at when at least one logical column is being updated.
    if set_map:
        set_map["updated_at"] = func.now()
    return set_map


def upsert_reel_features(
    session: Session,
    *,
    reel_id: str,
    features: Mapping[str, Any],
    model_versions: Optional[Mapping[str, Any]] = None,
) -> None:
    values: Dict[str, Any] = {
        "reel_id": _uuid(reel_id),
        "duration": features.get("duration"),
        "fps": features.get("fps"),
        "resolution": features.get("resolution"),
        "motion_score": features.get("motion_score"),
        "frame_entropy": features.get("frame_entropy"),
        "scene_change_rate": features.get("scene_change_rate"),
        "object_tags": features.get("object_tags"),
        "emotion_vector": features.get("emotion_vector"),
        "ocr_text": features.get("ocr_text"),
        "audio_energy": features.get("audio_energy"),
        "speech_ratio": features.get("speech_ratio"),
        "transcript": features.get("transcript"),
        "hook_motion_score": features.get("hook_motion_score"),
        "hook_scene_change_rate": features.get("hook_scene_change_rate"),
        "hook_ocr_present": features.get("hook_ocr_present"),
        "hook_signals": features.get("hook_signals"),
        "hook_recommendations": features.get("hook_recommendations"),
        "llm_hook_score": features.get("llm_hook_score"),
        "llm_hook_signals": features.get("llm_hook_signals"),
        "llm_hook_reasoning": features.get("llm_hook_reasoning"),
        "llm_hook_confidence": features.get("llm_hook_confidence"),
    }
    if model_versions is not None:
        values["model_versions"] = dict(model_versions)

    stmt = insert(ReelFeatures).values(**values)
    update_cols = [
        "duration",
        "fps",
        "resolution",
        "motion_score",
        "frame_entropy",
        "scene_change_rate",
        "object_tags",
        "emotion_vector",
        "ocr_text",
        "audio_energy",
        "speech_ratio",
        "transcript",
        "hook_motion_score",
        "hook_scene_change_rate",
        "hook_ocr_present",
        "hook_signals",
        "hook_recommendations",
        "llm_hook_score",
        "llm_hook_signals",
        "llm_hook_reasoning",
        "llm_hook_confidence",
    ]
    if model_versions is not None:
        update_cols.append("model_versions")
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReelFeatures.reel_id],
        set_=_coalesce_update(stmt, ReelFeatures, update_cols),
    )
    session.execute(stmt)


def upsert_reel_audio_features(
    session: Session,
    *,
    reel_id: str,
    features: Mapping[str, Any],
    model_versions: Optional[Mapping[str, Any]] = None,
) -> None:
    # audio_name intentionally excluded (exists on Module-1 reels table).
    values: Dict[str, Any] = {
        "reel_id": _uuid(reel_id),
        "tempo": features.get("tempo"),
        "beat_strength": features.get("beat_strength"),
        "speech_presence": features.get("speech_presence"),
        "music_presence": features.get("music_presence"),
    }
    if model_versions is not None:
        values["model_versions"] = dict(model_versions)

    stmt = insert(ReelAudioFeatures).values(**values)
    update_cols = [
        "tempo",
        "beat_strength",
        "speech_presence",
        "music_presence",
    ]
    if model_versions is not None:
        update_cols.append("model_versions")
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReelAudioFeatures.reel_id],
        set_=_coalesce_update(stmt, ReelAudioFeatures, update_cols),
    )
    session.execute(stmt)


def upsert_reel_text_features(
    session: Session,
    *,
    reel_id: str,
    features: Mapping[str, Any],
    model_versions: Optional[Mapping[str, Any]] = None,
) -> None:
    values: Dict[str, Any] = {
        "reel_id": _uuid(reel_id),
        "caption_keywords": features.get("caption_keywords"),
        "ocr_keywords": features.get("ocr_keywords"),
        "transcript_keywords": features.get("transcript_keywords"),
        "sentiment": features.get("sentiment"),
        "intent": features.get("intent"),
    }
    if model_versions is not None:
        values["model_versions"] = dict(model_versions)

    stmt = insert(ReelTextFeatures).values(**values)
    update_cols = [
        "caption_keywords",
        "ocr_keywords",
        "transcript_keywords",
        "sentiment",
        "intent",
    ]
    if model_versions is not None:
        update_cols.append("model_versions")
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReelTextFeatures.reel_id],
        set_=_coalesce_update(stmt, ReelTextFeatures, update_cols),
    )
    session.execute(stmt)


def persist_from_context(
    session: Session,
    *,
    context: ExtractionContext,
    model_versions: Optional[Mapping[str, Any]] = None,
) -> None:
    """
    Centralized persistence entrypoint.

    - Non-destructive upsert: never overwrites existing values with NULL.
    - No commit/rollback: caller controls transaction boundary.
    """
    features_flat: Dict[str, Any] = {}
    for _, entry in (context.intermediate_outputs or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "success":
            continue
        feats = entry.get("features")
        if isinstance(feats, dict):
            features_flat.update(feats)

    rid = context.reel_id

    try:
        upsert_reel_features(
            session, reel_id=rid, features=features_flat, model_versions=model_versions
        )
        feature_keys_present = [k for k, v in features_flat.items() if v is not None]
        logger.debug(
            "feature_keys_persisted count=%d keys=%s",
            len(feature_keys_present),
            feature_keys_present,
            extra={"reel_id": rid},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "upsert_failure table=reel_features error=%s",
            str(exc)[:80],
            extra={"reel_id": rid},
        )
        raise

    try:
        upsert_reel_audio_features(
            session, reel_id=rid, features=features_flat, model_versions=model_versions
        )
        upsert_reel_text_features(
            session, reel_id=rid, features=features_flat, model_versions=model_versions
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "upsert_failure table=audio_or_text error=%s",
            str(exc)[:80],
            extra={"reel_id": rid},
        )
        raise

    projections_entry = context.intermediate_outputs.get("projections") or {}
    if (
        isinstance(projections_entry, dict)
        and projections_entry.get("status") == "success"
    ):
        proj_feats = projections_entry.get("features")
        if isinstance(proj_feats, dict):
            # Build feature_coverage: logical feature → produced (bool)
            feature_coverage: dict[str, Any] = {}
            for ext_name, entry in (context.intermediate_outputs or {}).items():
                if ext_name == "projections" or ext_name.startswith("_"):
                    continue
                if not isinstance(entry, dict):
                    continue
                status = entry.get("status")
                # True only if extractor ran and succeeded
                feature_coverage[ext_name] = status == "success"

            # Part 12: track remote inference version
            if hasattr(context, 'model_versions') and "remote_inference" in context.model_versions:
                feature_coverage["remote_inference_version"] = context.model_versions[
                    "remote_inference"
                ]

            # Build extractor_failures: only failed (not skipped) extractors
            extractor_failures: dict[str, str] = {}
            for ext_name, entry in (context.intermediate_outputs or {}).items():
                if ext_name == "projections" or ext_name.startswith("_"):
                    continue
                if not isinstance(entry, dict):
                    continue
                if entry.get("status") == "failed":
                    extractor_failures[ext_name] = str(entry.get("error") or "unknown")[
                        :200
                    ]

            values = {
                "reel_id": _uuid(rid),
                "hook_score": proj_feats.get("hook_score"),
                "pacing_score": proj_feats.get("pacing_score"),
                "trend_score": proj_feats.get("trend_score"),
                "confidence": proj_feats.get("confidence"),
                "projection_version": proj_feats.get("projection_version"),
                "feature_coverage": feature_coverage,
                "extractor_failures": extractor_failures,
            }
            stmt = insert(ReelProjections).values(**values)
            # COALESCE for projection scores; FULL OVERWRITE for coverage/failures
            coalesce_cols = [
                "hook_score",
                "pacing_score",
                "trend_score",
                "confidence",
                "projection_version",
            ]
            set_map = _coalesce_update(stmt, ReelProjections, coalesce_cols)
            # Full overwrite on re-run (not COALESCE)
            set_map["feature_coverage"] = stmt.excluded.feature_coverage
            set_map["extractor_failures"] = stmt.excluded.extractor_failures
            stmt = stmt.on_conflict_do_update(
                index_elements=[ReelProjections.reel_id],
                set_=set_map,
            )
            session.execute(stmt)
            logger.debug(
                "projection_keys_persisted keys=%s coverage_count=%d failures=%s",
                sorted(proj_feats.keys()),
                sum(1 for v in feature_coverage.values() if v),
                list(extractor_failures.keys()) or "none",
                extra={"reel_id": rid},
            )

    # Upsert embeddings if present.
    # Safety: only persist when the extractor provides all required metadata.
    # No fallback constants — if any key is missing, skip entirely.
    embedding_entry = context.intermediate_outputs.get("embedding") or {}
    if isinstance(embedding_entry, dict) and embedding_entry.get("status") == "success":
        emb_feats = embedding_entry.get("features")
        if isinstance(emb_feats, dict):
            emb_model_name = emb_feats.get("embedding_model_name")
            emb_model_version = emb_feats.get("embedding_model_version")
            emb_version = emb_feats.get("embedding_version")
            emb_hash = emb_feats.get("text_bundle_hash")
            emb_vector = emb_feats.get("embedding")

            # All five fields are required for a valid embedding row.
            if all(
                v is not None
                for v in (
                    emb_model_name,
                    emb_model_version,
                    emb_version,
                    emb_hash,
                    emb_vector,
                )
            ):
                # Read clip_embedding from visual_embedding extractor (if present)
                clip_vector = None
                ve_entry = context.intermediate_outputs.get("visual_embedding") or {}
                if isinstance(ve_entry, dict) and ve_entry.get("status") == "success":
                    ve_feats = ve_entry.get("features")
                    if isinstance(ve_feats, dict):
                        clip_vector = ve_feats.get("clip_embedding")

                values = {
                    "reel_id": _uuid(rid),
                    "embedding": emb_vector,
                    "model_name": emb_model_name,
                    "model_version": emb_model_version,
                    "embedding_version": emb_version,
                    "text_bundle_hash": emb_hash,
                }
                if clip_vector is not None:
                    values["clip_embedding"] = clip_vector

                stmt = insert(ReelEmbeddings).values(**values)
                update_cols = [
                    "embedding",
                    "model_name",
                    "model_version",
                    "embedding_version",
                    "text_bundle_hash",
                ]
                set_map = _coalesce_update(stmt, ReelEmbeddings, update_cols)
                # clip_embedding: full overwrite (always recomputed)
                if clip_vector is not None:
                    set_map["clip_embedding"] = stmt.excluded.clip_embedding

                stmt = stmt.on_conflict_do_update(
                    index_elements=[ReelEmbeddings.reel_id],
                    set_=set_map,
                )
                session.execute(stmt)
                logger.debug(
                    "embedding_persisted=True embedding_dim=%d clip_dim=%d",
                    len(emb_vector) if isinstance(emb_vector, list) else 0,
                    len(clip_vector) if isinstance(clip_vector, list) else 0,
                    extra={"reel_id": rid},
                )
