# Module 2 Worker - Complete Line-by-Line Documentation

## Overview
The worker is the core execution engine of Module 2. It claims reels, runs the extractor DAG, computes projections, and persists results. This document explains every function, parameter, and line of logic in detail.

---

## File: `module2/worker.py`

### Imports and Dependencies

```python
import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Iterable, List, Optional, Set
```

**Purpose**: Standard library imports for async operations, logging, timing, collections management, and type hints.

```python
from sqlalchemy import select
from sqlalchemy.orm import Session
```

**Purpose**: SQLAlchemy imports for database operations - `select` for queries, `Session` for database connection management.

```python
from module2.context import ExtractionContext, cleanup_context
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.extractors.registry import build_default_registry
from module2.job_fetcher import claim_next_reel
from module2.logging_config import get_logger
from module2.persistence import persist_from_context
from module2.planner import (
    plan_adaptive_extractors,
    plan_baseline_extractors,
    topo_sort_extractors,
)
from module2.projections.engine import compute_projections, PROJECTION_VERSION
```

**Purpose**: Internal module imports:
- `ExtractionContext`: Data structure holding job state and temporary data
- `cleanup_context`: Function to clean up temporary files
- `BaseExtractor`, `ExtractorResult`: Base classes for extractors
- `build_default_registry`: Function to get all registered extractors
- `claim_next_reel`: Function to claim a reel for processing
- `get_logger`: Structured logging function
- `persist_from_context`: Function to save results to database
- Planner functions: DAG planning and topological sorting
- `compute_projections`, `PROJECTION_VERSION`: Projection calculation and versioning

---

### Constants and Global State

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger instance using structured logging configuration.

```python
_SKIP_COOLDOWN_SECONDS = 30
```

**Purpose**: Cooldown period in seconds to prevent immediate re-claiming of recently skipped reels.

```python
_recent_skip_cache: dict[str, float] = {}
```

**Purpose**: In-memory cache tracking recently skipped reel IDs with their skip timestamps. Key: reel_id (str), Value: timestamp (float).

---

### Core Functions

#### `run_once()`

```python
async def run_once(
    session: Session,
    extractors: Iterable[ExtractorLike] | None = None,
) -> Optional[str]:
```

**Purpose**: Main worker function that processes exactly one reel from claim to cleanup.

**Parameters**:
- `session`: SQLAlchemy database session for transaction management
- `extractors`: Optional iterable of extractor instances. If None, uses default registry

**Returns**:
- `Optional[str]`: reel_id if processing completed successfully, None if no reel was claimed

**Line-by-line execution**:

```python
    """Process exactly one reel from claim to cleanup.
    
    Returns the reel_id if a job was processed, None if no job was available.
    """
```

**Purpose**: Docstring explaining function purpose and return value.

```python
    # Input validation: ensure we have extractors to run
    if extractors is None:
        extractors = build_default_registry()
```

**Purpose**: If no extractors provided, get the default registry containing all extractors.

```python
    extractor_list = list(extractors)
    if not extractor_list:
        raise RuntimeError("Extractor registry is empty")
```

**Purpose**: Convert to list and validate it's not empty. This prevents silent failures where no work would be done.

```python
    # Claim next available reel
    reel = claim_next_reel(session)
    if reel is None:
        return None
```

**Purpose**: Claim a reel with `READY_FOR_PROCESSING` status using row-level locking. Returns None if no reels available.

```python
    reel_id = str(reel.id)
    logger.info("job_claimed", extra={"reel_id": reel_id})
```

**Purpose**: Extract reel_id as string and log successful job claim with structured context.

```python
    # Cooldown check: skip if recently processed
    now = time.monotonic()
    last_skip = _recent_skip_cache.get(reel_id)
    if last_skip and (now - last_skip) < _SKIP_COOLDOWN_SECONDS:
        logger.info("cooldown_skip", extra={"reel_id": reel_id})
        return None
```

**Purpose**: Check cooldown cache to prevent tight loops where same reel gets repeatedly claimed and skipped. Uses monotonic time for reliable timing.

```python
    context: Optional[ExtractionContext] = None
    result_reel_id: Optional[str] = None
```

**Purpose**: Initialize variables for context and result. Context will hold temporary state, result_reel_id will be returned on success.

```python
    try:
        # Create extraction context with temporary directory
        context = ExtractionContext.create(reel_id, reel)
        logger.info("context_created", extra={"reel_id": reel_id})
```

**Purpose**: Create ExtractionContext which creates temp directory and copies reel metadata. This is where all temporary files will be stored.

```python
        # Check if already processed with current projection version
        from module2.persistence import _check_projection_version
        if _check_projection_version(session, reel_id):
            logger.info("already_processed_skip", extra={"reel_id": reel_id})
            _recent_skip_cache[reel_id] = now
            return None
```

**Purpose**: Check if reel was already processed with current projection version. If yes, skip and add to cooldown cache.

```python
        # Phase 1: Baseline extraction
        baseline_extractors = plan_baseline_extractors(extractor_list)
        logger.info("baseline_planned", extra={"reel_id": reel_id, "count": len(baseline_extractors)})
        
        await execute_extractor_dag(context, baseline_extractors)
        logger.info("baseline_completed", extra={"reel_id": reel_id})
```

**Purpose**: Plan and execute baseline extractors (always run). These are critical extractors needed for basic functionality.

```python
        # Phase 2: Adaptive extraction based on results
        adaptive_extractors = plan_adaptive_extractors(extractor_list, context)
        if adaptive_extractors:
            logger.info("adaptive_planned", extra={"reel_id": reel_id, "count": len(adaptive_extractors)})
            await execute_extractor_dag(context, adaptive_extractors)
            logger.info("adaptive_completed", extra={"reel_id": reel_id})
```

**Purpose**: Plan and run adaptive extractors based on baseline results. These are heavy extractors that only run if needed (e.g., LLM hook for certain hook scores).

```python
        # Compute projections from all extractor results
        compute_projections(context)
        logger.info("projections_computed", extra={"reel_id": reel_id})
```

**Purpose**: Calculate final scores (hook, pacing, trend) from extractor outputs using heuristic and LLM fusion.

```python
        # Persist all results to database
        persist_from_context(session, context, reel_id)
        logger.info("persistence_success", extra={"reel_id": reel_id})
```

**Purpose**: Save all features, projections, and embeddings to database tables using upserts.

```python
        # Mark as completed and commit transaction
        session.commit()
        result_reel_id = reel_id
        logger.info("job_completed", extra={"reel_id": reel_id})
```

**Purpose**: Commit database transaction and set return value. This is the success path.

```python
    except Exception as exc:
        # Rollback on any error
        session.rollback()
        logger.error("rollback_triggered", extra={"reel_id": reel_id}, exc_info=True)
        raise
```

**Purpose**: On any exception, rollback database changes and re-raise. `exc_info=True` includes full traceback in logs.

```python
    finally:
        # Always cleanup temporary files
        if context:
            cleanup_context(context)
            logger.info("cleanup_completed", extra={"reel_id": reel_id})
```

**Purpose**: Guaranteed cleanup of temporary files regardless of success or failure. This prevents disk space leaks.

```python
    return result_reel_id
```

**Purpose**: Return reel_id on success, None on failure or no reel available.

---

#### `execute_extractor_dag()`

```python
async def execute_extractor_dag(
    context: ExtractionContext,
    extractors: List[BaseExtractor],
) -> None:
```

**Purpose**: Execute a Directed Acyclic Graph (DAG) of extractors with proper dependency resolution and parallel execution.

**Parameters**:
- `context`: ExtractionContext containing job state and intermediate results
- `extractors`: List of extractor instances to execute

**Returns**: None (results stored in context.intermediate_outputs)

**Line-by-line execution**:

```python
    """Execute extractors in dependency order with parallel execution where possible."""
```

**Purpose**: Docstring explaining function purpose.

```python
    # Build lookup dictionary for extractor instances
    by_name = {extractor.name: extractor for extractor in extractors}
```

**Purpose**: Create dictionary mapping extractor names to instances for O(1) lookup during dependency resolution.

```python
    # Track which extractors are still pending
    pending: Set[str] = set(by_name.keys())
```

**Purpose**: Set of extractor names that haven't completed yet.

```python
    # Track completed extractors and their results
    completed: dict[str, ExtractorResult] = {}
```

**Purpose**: Dictionary mapping completed extractor names to their results.

```python
    logger.info("dag_started", extra={"reel_id": context.reel_id, "total_extractors": len(pending)})
```

**Purpose**: Log DAG execution start with total count for observability.

```python
    while pending:
        # Find extractors whose dependencies are satisfied
        ready = []
        for name in pending:
            extractor = by_name[name]
            deps_satisfied = all(
                dep in completed and completed[dep].status == "success"
                for dep in extractor.dependencies
            )
            if deps_satisfied:
                ready.append(name)
```

**Purpose**: Identify extractors ready to run by checking if all their dependencies completed successfully. This is the core dependency resolution logic.

```python
        if not ready:
            # Check for stalled DAG (circular dependencies or missing deps)
            stalled = ", ".join(sorted(pending))
            raise RuntimeError(f"DAG resolution stalled; pending=[{stalled}]")
```

**Purpose**: Error detection - if no extractors are ready but some are pending, there's likely a circular dependency or missing dependency.

```python
        # Separate runnable from skipped extractors
        runnable = []
        skipped = []
        for name in ready:
            extractor = by_name[name]
            # Check if any dependency failed or was skipped
            dep_failed = any(
                completed.get(dep, ExtractorResult.success({})).status != "success"
                for dep in extractor.dependencies
            )
            if dep_failed:
                skipped.append(name)
            else:
                runnable.append(name)
```

**Purpose**: Separate ready extractors into those that can run (all deps successful) vs those that should be skipped (any dep failed/skipped).

```python
        # Log skipped extractors
        for name in skipped:
            extractor = by_name[name]
            result = ExtractorResult.skipped("dependency_failed")
            completed[name] = result
            pending.remove(name)
            logger.info(
                "extractor_skipped",
                extra={
                    "reel_id": context.reel_id,
                    "extractor": name,
                    "reason": "dependency_failed"
                }
            )
```

**Purpose**: Mark extractors as skipped when dependencies failed and remove from pending set.

```python
        # Run runnable extractors in parallel
        if runnable:
            tasks = []
            for name in runnable:
                extractor = by_name[name]
                task = asyncio.create_task(
                    run_extractor_with_logging(context, extractor)
                )
                tasks.append((name, task))
```

**Purpose**: Create async tasks for all runnable extractors. This enables parallel execution of independent extractors.

```python
            # Wait for all tasks to complete
            for name, task in tasks:
                try:
                    result = await task
                    completed[name] = result
                    pending.remove(name)
                    
                    # Check for critical extractor failure
                    if result.status == "failed" and extractor.is_critical:
                        raise RuntimeError(f"Critical extractor {name} failed: {result.error}")
                        
                except Exception as exc:
                    # Handle unexpected exceptions
                    result = ExtractorResult.failed(str(exc))
                    completed[name] = result
                    pending.remove(name)
                    
                    if extractor.is_critical:
                        raise
```

**Purpose**: Wait for parallel tasks to complete, handle results, and check for critical failures. If a critical extractor fails, the entire DAG fails.

```python
    logger.info("dag_completed", extra={"reel_id": context.reel_id, "completed_count": len(completed)})
```

**Purpose**: Log DAG completion with final count for observability.

---

#### `run_extractor_with_logging()`

```python
async def run_extractor_with_logging(
    context: ExtractionContext,
    extractor: BaseExtractor,
) -> ExtractorResult:
```

**Purpose**: Wrapper function that runs an extractor with structured logging and error handling.

**Parameters**:
- `context`: ExtractionContext for the job
- `extractor`: Extractor instance to run

**Returns**: ExtractorResult with status, features, and optional error

**Line-by-line execution**:

```python
    """Run extractor with automatic logging and error handling."""
```

**Purpose**: Docstring.

```python
    start_time = time.monotonic()
    logger.debug(
        "extractor_start",
        extra={"reel_id": context.reel_id, "extractor": extractor.name}
    )
```

**Purpose**: Record start time and log extractor start at DEBUG level.

```python
    try:
        result = await extractor.run(context)
        duration = time.monotonic() - start_time
        
        if result.status == "success":
            logger.debug(
                "extractor_success",
                extra={
                    "reel_id": context.reel_id,
                    "extractor": extractor.name,
                    "feature_keys": list(result.features.keys()) if result.features else [],
                    "duration_s": round(duration, 3)
                }
            )
        elif result.status == "skipped":
            logger.debug(
                "extractor_skipped",
                extra={
                    "reel_id": context.reel_id,
                    "extractor": extractor.name,
                    "reason": result.error or "unknown",
                    "duration_s": round(duration, 3)
                }
            )
        else:  # failed
            logger.warning(
                "extractor_failed",
                extra={
                    "reel_id": context.reel_id,
                    "extractor": extractor.name,
                    "error": result.error or "unknown",
                    "duration_s": round(duration, 3)
                }
            )
```

**Purpose**: Run the extractor, calculate duration, and log result with appropriate level based on status. Only logs feature keys, not values (security).

```python
        # Store result in context for downstream extractors
        context.intermediate_outputs[extractor.name] = result
        return result
```

**Purpose**: Store result in context for dependency resolution and return the result.

```python
    except Exception as exc:
        duration = time.monotonic() - start_time
        logger.warning(
            "extractor_failed",
            extra={
                "reel_id": context.reel_id,
                "extractor": extractor.name,
                "error": str(exc),
                "duration_s": round(duration, 3)
            }
        )
        result = ExtractorResult.failed(str(exc))
        context.intermediate_outputs[extractor.name] = result
        return result
```

**Purpose**: Handle unexpected exceptions, log them, and return failed result. This ensures the DAG can continue if non-critical extractors fail.

---

## Key Design Patterns and Safety Mechanisms

### 1. Transaction Management
- All database operations within a single transaction
- Explicit `commit()` on success, `rollback()` on failure
- Prevents partial data persistence

### 2. Dependency Resolution
- Topological sorting ensures correct execution order
- Parallel execution of independent extractors
- Automatic skipping when dependencies fail

### 3. Error Isolation
- Non-critical extractor failures don't stop the pipeline
- Critical extractor failures abort the entire job
- Detailed error logging with context

### 4. Resource Management
- Guaranteed cleanup of temporary files in `finally` block
- Cooldown cache prevents tight loops
- Memory-efficient streaming of results

### 5. Observability
- Structured logging with reel_id context
- Performance metrics (duration, counts)
- Clear status indicators for debugging

---

## Common Failure Scenarios and Their Causes

### 1. "DAG resolution stalled"
- **Cause**: Circular dependencies or missing dependencies
- **Solution**: Check extractor dependency definitions

### 2. "Critical extractor failed"
- **Cause**: Essential component (video download, probe) failed
- **Solution**: Check logs for specific error, verify external dependencies

### 3. "Extractor registry is empty"
- **Cause**: No extractors registered or imported
- **Solution**: Verify extractor imports and registry setup

### 4. Timeout during execution
- **Cause**: Long-running operations (download, inference)
- **Solution**: Check network connectivity, external service status

---

## Performance Considerations

### 1. Parallel Execution
- Independent extractors run concurrently
- Maximum parallelism limited by I/O and CPU resources
- Consider async/await patterns for I/O-bound operations

### 2. Memory Usage
- Large video files and frame collections consume memory
- Cleanup happens after each job
- Monitor memory usage for large batches

### 3. Database Load
- Upserts can be heavy on high write loads
- Consider connection pooling for concurrent workers
- Index optimization for frequent queries

---

## Integration Points

### 1. Database Layer
- Uses SQLAlchemy ORM with PostgreSQL
- Requires proper transaction management
- Dependent on schema migrations

### 2. External Services
- Video download via yt-dlp
- Remote inference via HTTP API
- File system operations for temporary storage

### 3. Monitoring
- Structured logs for aggregation
- Performance metrics collection
- Error rate tracking

---

This documentation provides a complete understanding of the worker's execution flow, error handling, and operational characteristics. Each function's purpose, parameters, return values, and line-by-line logic is explained to prevent surprises in production.
