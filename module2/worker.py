from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Iterable, List, Optional, Protocol

from sqlalchemy.orm import Session

from module2.extractors.base import ExtractorResult
from module2.cleanup import cleanup_context
from module2.context import ExtractionContext
from module2.job_fetcher import claim_next_reel
from module2.logging_config import get_logger
from module2.persistence import persist_from_context
from module2.projections.engine import compute_projections


logger = get_logger("worker")


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

    Returns processed reel_id, or None if no job available.
    """
    if extractors is None:
        raise RuntimeError("Extractor registry must be provided to worker")

    extractor_list = list(extractors)
    if not extractor_list:
        raise RuntimeError("Extractor registry is empty")

    reel = claim_next_reel(session)
    if reel is None:
        return None

    reel_id = str(reel.id)
    job_start = time.monotonic()
    logger.info("job_claimed", extra={"reel_id": reel_id})

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

    views = metadata.get("views")
    likes = metadata.get("likes")
    has_engagement = views is not None and likes is not None

    heavy_extractors = {"ocr", "transcript", "embedding", "llm_hook"}

    if not has_engagement:
        extractor_list = [
            e
            for e in extractor_list
            if getattr(e, "name", None) not in heavy_extractors
        ]

    try:
        logger.info("dag_started", extra={"reel_id": reel_id})

        await execute_extractor_dag(context=context, extractors=extractor_list)

        compute_projections(context)
        logger.info("projections_computed", extra={"reel_id": reel_id})

        persist_from_context(session, context=context)
        logger.info("persistence_success", extra={"reel_id": reel_id})

        session.commit()  # releases row lock / ends transaction cleanly

        elapsed = time.monotonic() - job_start
        logger.info(
            "job_completed duration_s=%.2f",
            elapsed,
            extra={"reel_id": reel_id},
        )
        return reel_id

    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.error(
            "rollback_triggered error=%s",
            exc,
            extra={"reel_id": reel_id},
            exc_info=True,
        )
        raise

    finally:
        cleanup_context(context)
        logger.info("cleanup_completed", extra={"reel_id": reel_id})


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


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from db.connection import get_session
    from module2.extractors.registry import build_default_registry

    registry = build_default_registry()
    print(
        f"Worker starting with {len(list(registry.all()))} extractors... (Ctrl+C to stop)"
    )
    asyncio.run(run_forever(session_factory=get_session, extractors=registry.all()))
