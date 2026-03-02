from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from module2.extractors.base import ExtractorResult
from module2.cleanup import cleanup_context
from module2.context import ExtractionContext
from module2.job_fetcher import claim_next_reel, peek_next_reel_id
from module2.logging_config import get_logger
from module2.persistence import persist_from_context
from module2.planner import plan_adaptive_extractors, plan_baseline_extractors
from module2.projections.engine import PROJECTION_VERSION, compute_projections

from db.module2_models import ReelProjections


logger = get_logger("worker")

# ── Cooldown ──
_recent_skip_cache: dict[str, float] = {}
_SKIP_COOLDOWN_SECONDS = 30

# ── Runtime guards (Step 3-4) ──
_MAX_PROCESSING_SECONDS = 240
_MAX_VIDEO_FILE_MB = 500

# ── Projection version freeze (Step 5) ──
_LOCKED_PROJECTION_VERSION = PROJECTION_VERSION

# ── Periodic metrics (Step 6) ──
_METRICS_INTERVAL = 100
_metrics: dict[str, Any] = {
    "total_processed": 0,
    "total_failed": 0,
    "total_skipped": 0,
    "total_timeouts": 0,
    "total_heavy_activated": 0,
    "total_runtime_s": 0.0,
}


class ExtractorLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dependencies(self) -> List[str]: ...

    @property
    def output_keys(self) -> List[str]: ...

    @property
    def is_critical(self) -> bool: ...

    @property
    def requires_gpu(self) -> bool: ...

    async def run(self, context: ExtractionContext) -> ExtractorResult: ...


async def _run_extractor(
    extractor: ExtractorLike, context: ExtractionContext
) -> ExtractorResult:
    try:
        # Use auto-logging wrapper if available (BaseExtractor subclasses).
        runner = getattr(extractor, "run_with_logging", None) or extractor.run
        result = await runner(context)
        return result
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult.failed(str(exc))


async def execute_extractor_dag(
    context: ExtractionContext,
    extractors: Iterable[ExtractorLike],
) -> Dict[str, ExtractorResult]:
    """
    Custom async DAG executor:
    - respects declared dependencies
    - runs independent extractors concurrently via asyncio.gather
    - critical failure stops execution
    - optional failure is isolated (logged, pipeline continues)
    """
    rid = context.reel_id
    by_name: Dict[str, ExtractorLike] = {e.name: e for e in extractors}
    pending = set(by_name.keys())
    results: Dict[str, ExtractorResult] = {}

    logger.info("dag_started", extra={"reel_id": rid})

    while pending:
        ready: List[str] = []
        for name in list(pending):
            deps = by_name[name].dependencies or []
            if all(dep in results for dep in deps):
                ready.append(name)

        if not ready:
            # Dependency cycle or missing dependency declarations.
            raise RuntimeError(
                f"DAG resolution stalled; pending={sorted(pending)} results={sorted(results)}"
            )

        # If any dependency failed/skipped, dependent is skipped.
        runnable: List[str] = []
        for name in ready:
            deps = by_name[name].dependencies or []
            dep_statuses = [results[d].status for d in deps]
            if any(s != "success" for s in dep_statuses):
                results[name] = ExtractorResult(
                    status="skipped",
                    features={},
                    error="dependency_failed",
                )
                context.intermediate_outputs[name] = {
                    "status": results[name].status,
                    "features": results[name].features,
                    "error": results[name].error,
                }
                pending.remove(name)
            else:
                runnable.append(name)

        tasks = [_run_extractor(by_name[name], context) for name in runnable]
        task_results = await asyncio.gather(*tasks)

        for name, res in zip(runnable, task_results, strict=False):
            results[name] = res
            pending.remove(name)
            if res.status == "success":
                # Merge feature dict into intermediate outputs for downstream use.
                context.intermediate_outputs[name] = {
                    "status": res.status,
                    "features": dict(res.features or {}),
                    "error": res.error,
                }
            else:
                context.intermediate_outputs[name] = {
                    "status": res.status,
                    "features": {},
                    "error": res.error,
                }

            if res.status == "failed":
                if by_name[name].is_critical:
                    logger.error(
                        "critical_extractor_failed extractor=%s error=%s",
                        name,
                        res.error,
                        extra={"reel_id": rid},
                    )
                    raise RuntimeError(
                        f"Critical extractor failed: {name}: {res.error}"
                    )
                logger.warning(
                    "optional_extractor_failed extractor=%s error=%s",
                    name,
                    res.error,
                    extra={"reel_id": rid},
                )

    return results


async def run_once(
    session: Session,
    extractors: Iterable[ExtractorLike] | None = None,
) -> Optional[str]:
    """
    Phase-2 worker skeleton:
    - claims one ready_for_processing reel (row lock)
    - logs processing/completed/failed/retry (no DB lifecycle persistence)
    - executes DAG engine (extractors may be empty at this phase)
    - always cleans up ephemeral artifacts
    - 240s hard timeout (Step 3)
    - 500MB video size guard (Step 4)

    Returns processed reel_id, or None if no job available.
    """
    # Step 5: projection version freeze — fail fast on mismatch
    if PROJECTION_VERSION != _LOCKED_PROJECTION_VERSION:
        logger.critical(
            "projection_version_mismatch locked=%s current=%s",
            _LOCKED_PROJECTION_VERSION,
            PROJECTION_VERSION,
        )
        raise RuntimeError(
            f"Projection version changed mid-run: "
            f"{_LOCKED_PROJECTION_VERSION} -> {PROJECTION_VERSION}"
        )
    if extractors is None:
        raise RuntimeError("Extractor registry must be provided to worker")

    extractor_list = list(extractors)
    if not extractor_list:
        raise RuntimeError("Extractor registry is empty")

    # Pre-claim cooldown: peek candidate without locking.
    candidate_id = peek_next_reel_id(session)
    if candidate_id is None:
        return None

    now = time.monotonic()
    last_skip = _recent_skip_cache.get(candidate_id)
    if last_skip and (now - last_skip) < _SKIP_COOLDOWN_SECONDS:
        logger.debug("cooldown_skip_preclaim", extra={"reel_id": candidate_id})
        return None

    # Proceed with locking claim.
    reel = claim_next_reel(session)
    if reel is None:
        return None

    reel_id = str(reel.id)
    job_start = time.monotonic()
    logger.info("job_claimed", extra={"reel_id": reel_id})

    # Skip if already processed with current projection version.
    existing = session.get(ReelProjections, reel_id)
    if existing:
        if existing.projection_version == PROJECTION_VERSION:
            logger.info("already_processed_skip", extra={"reel_id": reel_id})
            _recent_skip_cache[reel_id] = time.monotonic()
            _metrics["total_skipped"] += 1
            return None
        else:
            # Step 8: re-run with different version
            logger.info(
                "reprocess_detected old_version=%s new_version=%s",
                existing.projection_version,
                PROJECTION_VERSION,
                extra={"reel_id": reel_id},
            )

    metadata = {
        "reel_url": reel.reel_url,
        "thumbnail_url": reel.thumbnail_url,
        "caption": reel.caption,
        "hashtags": reel.hashtags,
        "audio_name": reel.audio_name,
        "views": reel.views,
        "likes": reel.likes,
        "comments": reel.comments,
        "publish_time": reel.publish_time,
        "creator_id": str(reel.creator_id),
        "discovery_source": reel.discovery_source,
        "account_id": "test_account",
    }
    context = ExtractionContext.create(reel_id=reel_id, metadata=metadata)

    # Result variable to store return value
    result_reel_id = None

    # Atomic transaction: wrap entire reel processing
    try:
        logger.info("dag_started", extra={"reel_id": reel_id})

        # Phase A: baseline extractors for required projection features.
        baseline = plan_baseline_extractors(extractor_list)
        logger.info(
            "activation_plan_baseline extractors=%s",
            [e.name for e in baseline],
            extra={"reel_id": reel_id},
        )

        # Step 3: wrap DAG execution in hard timeout
        async def _run_pipeline() -> None:
            await execute_extractor_dag(context=context, extractors=baseline)

            # Step 4: artifact size guard — check video file only
            if context.video_path and os.path.isfile(context.video_path):
                size_mb = os.path.getsize(context.video_path) / (1024 * 1024)
                if size_mb > _MAX_VIDEO_FILE_MB:
                    logger.warning(
                        "video_size_exceeded size_mb=%.1f limit_mb=%d",
                        size_mb,
                        _MAX_VIDEO_FILE_MB,
                        extra={"reel_id": reel_id},
                    )
                    raise RuntimeError(
                        f"Video file too large: {size_mb:.0f}MB > {_MAX_VIDEO_FILE_MB}MB"
                    )

            # Phase B: adaptive heavy extractors based on heuristic signals.
            adaptive = plan_adaptive_extractors(extractor_list, context)
            # Fix 6: explicit dedup — never re-run baseline extractors
            baseline_names = {e.name for e in baseline}
            adaptive = [e for e in adaptive if e.name not in baseline_names]
            if adaptive:
                _metrics["total_heavy_activated"] += 1
                await execute_extractor_dag(context=context, extractors=adaptive)

        try:
            await asyncio.wait_for(
                _run_pipeline(),
                timeout=_MAX_PROCESSING_SECONDS,
            )
        except asyncio.TimeoutError:
            _metrics["total_timeouts"] += 1
            logger.error(
                "worker_timeout limit_s=%d",
                _MAX_PROCESSING_SECONDS,
                extra={"reel_id": reel_id},
            )
            # Mark as failed and let transaction rollback
            reel.ingestion_status = "FAILED"
            raise RuntimeError(f"Worker timeout after {_MAX_PROCESSING_SECONDS}s")

        # PART 4: Prevent Partial Persistence Check
        critical_extractors = [
            "video_fetcher",
            "video_probe",
            "frame_sampler",
            "embedding",
            "visual_embedding",
        ]
        failed_critical = []

        for extractor_name in critical_extractors:
            output = context.intermediate_outputs.get(extractor_name)
            if not output or output.get("status") != "success":
                failed_critical.append(extractor_name)

        if failed_critical:
            logger.critical(
                "critical_extractors_failed failed=%s",
                failed_critical,
                extra={"reel_id": reel_id},
            )
            reel.ingestion_status = "FAILED"
            raise RuntimeError(f"Critical extractors failed: {failed_critical}")

        compute_projections(context)
        logger.info("projections_computed", extra={"reel_id": reel_id})

        persist_from_context(session, context=context)
        logger.info("persistence_success", extra={"reel_id": reel_id})

        # Update ingestion status on success
        reel.ingestion_status = "COMPLETED"

        elapsed = time.monotonic() - job_start
        _metrics["total_processed"] += 1
        _metrics["total_runtime_s"] += elapsed

        # Step 6: periodic metrics
        total = _metrics["total_processed"]
        if total > 0 and total % _METRICS_INTERVAL == 0:
            avg_rt = _metrics["total_runtime_s"] / total
            logger.info(
                "worker_metrics",
                extra={
                    "total_processed": total,
                    "total_failed": _metrics["total_failed"],
                    "total_skipped": _metrics["total_skipped"],
                    "total_timeouts": _metrics["total_timeouts"],
                    "avg_runtime_s": round(avg_rt, 2),
                    "heavy_activation_rate": round(
                        _metrics["total_heavy_activated"] / total, 3
                    ),
                    "failure_rate": round(_metrics["total_failed"] / total, 3),
                },
            )

        logger.info(
            "job_completed duration_s=%.2f",
            elapsed,
            extra={"reel_id": reel_id},
        )

        session.commit()
        result_reel_id = reel_id

    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _metrics["total_failed"] += 1
        logger.error(
            "rollback_triggered error=%s",
            exc,
            extra={"reel_id": reel_id},
            exc_info=True,
        )

        # PART 6: Retry Cap Logic
        reel.retries += 1

        # Check if remote inference failed
        remote_failed = False
        remote_output = context.intermediate_outputs.get("_remote_inference")
        if remote_output and remote_output.get("status") == "failed":
            remote_failed = True

        if remote_failed and reel.retries >= 3:
            reel.ingestion_status = "FAILED"
            logger.error(
                "max_retries_exceeded retries=%d reel_id=%s",
                reel.retries,
                reel_id,
                extra={"reel_id": reel_id},
            )
        elif remote_failed:
            # Leave as READY_FOR_PROCESSING for retry
            reel.ingestion_status = "READY_FOR_PROCESSING"
            logger.warning(
                "remote_failure_will_retry retries=%d reel_id=%s",
                reel.retries,
                reel_id,
                extra={"reel_id": reel_id},
            )
        else:
            # Non-remote failure - mark as FAILED immediately
            reel.ingestion_status = "FAILED"

        raise

    finally:
        cleanup_context(context)
        logger.info("cleanup_completed", extra={"reel_id": reel_id})

    # Return the result after cleanup
    return result_reel_id


async def run_forever(
    session_factory,
    extractors: Iterable[ExtractorLike] | None = None,
    poll_interval_seconds: float = 1.0,
) -> None:
    """
    Polling loop. Caller owns event loop and process lifecycle.

    session_factory: callable returning a context manager yielding Session
      e.g. db.connection.get_session
    """
    while True:
        try:
            with session_factory() as session:
                job = await run_once(session=session, extractors=extractors)
                if job is None:
                    await asyncio.sleep(poll_interval_seconds)
        except Exception:  # noqa: BLE001
            logger.critical(
                "unexpected_worker_crash",
                exc_info=True,
            )
            await asyncio.sleep(poll_interval_seconds)


def verify_dataset_schema(session_factory) -> None:
    """
    Step 7: Startup self-test — verify hardening columns exist.
    Fail fast if schema is missing required columns.
    """
    try:
        with session_factory() as session:
            session.execute(
                sa_text(
                    "SELECT feature_coverage, extractor_failures "
                    "FROM reel_projections LIMIT 1"
                )
            )
    except Exception as exc:
        logger.critical(
            "dataset_schema_invalid error=%s",
            str(exc)[:120],
        )
        raise RuntimeError(
            "Dataset schema validation failed. "
            "Run db/migrations/003_dataset_hardening.sql first."
        ) from exc

    logger.info("module2_dataset_readiness: OK")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from db.connection import get_session
    from module2.extractors.registry import build_default_registry

    # Step 5: log frozen projection version
    logger.info(
        "projection_version_locked: %s",
        _LOCKED_PROJECTION_VERSION,
    )

    # Step 7: startup self-test
    verify_dataset_schema(get_session)

    registry = build_default_registry()
    print(
        f"Worker starting with {len(list(registry.all()))} extractors... (Ctrl+C to stop)"
    )
    asyncio.run(run_forever(session_factory=get_session, extractors=registry.all()))
