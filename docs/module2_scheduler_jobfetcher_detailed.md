# Module 2 Scheduler and Job Fetcher - Complete Line-by-Line Documentation

## Overview
The scheduler and job fetcher manage the transition of reels through processing states and handle job claiming with proper locking. This ensures reliable job distribution and prevents duplicate processing.

---

## Scheduler

### File: `module2/scheduler.py`

#### Imports and Dependencies

```python
import time
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from module2.logging_config import get_logger
```

**Purpose**:
- `time`: Time-based operations for scheduling intervals
- `List`, `Optional`: Type hints for better code documentation
- `select`, `update`: SQLAlchemy query and update operations
- `Session`: SQLAlchemy database session
- `get_logger`: Structured logging configuration

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger instance.

#### Configuration Constants

```python
# Scheduling configuration
BATCH_SIZE = 25  # Number of reels to process per scheduling run
SCHEDULE_INTERVAL = 60  # Seconds between scheduling runs
```

**Purpose**: Configuration for scheduling behavior:
- `BATCH_SIZE`: Limits database load per run
- `SCHEDULE_INTERVAL`: Prevents excessive database polling

#### Main Scheduling Function

```python
def schedule_pending_reels(session: Session) -> int:
    """Transition reels from PENDING to READY_FOR_PROCESSING status."""
```

**Purpose**: Main scheduler function that moves eligible reels to processing-ready state.

**Parameters**:
- `session`: SQLAlchemy database session for transaction management

**Returns**: Number of reels scheduled (int)

```python
    logger.info(
        "scheduler_started",
        extra={"batch_size": BATCH_SIZE}
    )
```

**Purpose**: Log scheduler start for observability.

##### Eligibility Query

```python
    # Query for reels that are ready for processing
    query = select(Reel).where(
        Reel.ingestion_status == "PENDING"
    ).where(
        Reel.thumbnail_url.isnot(None)
    ).where(
        Reel.creator_id.isnot(None)
    ).order_by(
        # Priority: highest engagement first
        (Reel.views + Reel.likes + Reel.comments * 0.001).desc()
    ).order_by(
        # Tie-breaker: newest first
        Reel.publish_time.desc().nulls_last()
    ).limit(BATCH_SIZE)
```

**Purpose**: Build query to find eligible reels:
- Status must be PENDING
- Must have thumbnail URL (indicates successful download)
- Must have creator ID (required for processing)
- Ordered by engagement score (views + likes + comments*0.001)
- Tie-breaker by publish time (newest first)
- Limited to batch size

```python
    # Execute query with row-level locking
    reels = session.execute(query).scalars().all()
```

**Purpose**: Execute query and get reel objects.

##### Status Update

```python
    if not reels:
        logger.info("scheduler_no_pending_reels")
        return 0
```

**Purpose**: Early return if no reels found.

```python
    # Update status to READY_FOR_PROCESSING
    reel_ids = [reel.id for reel in reels]
    
    update_stmt = (
        update(Reel)
        .where(Reel.id.in_(reel_ids))
        .where(Reel.ingestion_status == "PENDING")  # Double-check status
        .values(ingestion_status="READY_FOR_PROCESSING")
        .execution_options(synchronize_session="fetch")
    )
```

**Purpose**: Prepare update statement:
- Update only selected reel IDs
- Double-check status is still PENDING (prevents race conditions)
- Set status to READY_FOR_PROCESSING
- Synchronize session to reflect changes

```python
    result = session.execute(update_stmt)
    updated_count = result.rowcount
```

**Purpose**: Execute update and get count of affected rows.

```python
    session.commit()
```

**Purpose**: Commit transaction to make changes permanent.

```python
    logger.info(
        "scheduler_completed",
        extra={
            "reels_found": len(reels),
            "reels_updated": updated_count
        }
    )
```

**Purpose**: Log completion with statistics.

```python
    return updated_count
```

**Purpose**: Return number of reels actually updated.

#### Scheduling Loop Function

```python
def run_scheduler_loop(session_factory, stop_event):
    """Run the scheduler in a continuous loop until stop event is set."""
```

**Purpose**: Long-running scheduler loop for production deployment.

**Parameters**:
- `session_factory`: Function to create new database sessions
- `stop_event`: Threading event to signal graceful shutdown

**Returns**: None (runs until stopped)

```python
    logger.info(
        "scheduler_loop_started",
        extra={"interval": SCHEDULE_INTERVAL}
    )
```

**Purpose**: Log loop start.

```python
    while not stop_event.is_set():
        try:
            # Create fresh session for each iteration
            with session_factory() as session:
                scheduled_count = schedule_pending_reels(session)
                
                if scheduled_count > 0:
                    logger.info(
                        "scheduler_batch_completed",
                        extra={"scheduled_count": scheduled_count}
                    )
                
                # Wait for next iteration or stop signal
                stop_event.wait(SCHEDULE_INTERVAL)
                
        except Exception as exc:
            logger.error(
                "scheduler_error",
                extra={"error": str(exc)},
                exc_info=True
            )
            # Wait before retrying on error
            stop_event.wait(min(SCHEDULE_INTERVAL, 30))
```

**Purpose**: Main scheduling loop:
- Creates fresh session each iteration (prevents connection issues)
- Calls scheduler function
- Logs batch completion
- Waits for interval or stop signal
- Handles errors gracefully with shorter retry interval

```python
    logger.info("scheduler_loop_stopped")
```

**Purpose**: Log graceful shutdown.

---

## Job Fetcher

### File: `module2/job_fetcher.py`

#### Imports and Dependencies

```python
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from module2.logging_config import get_logger
```

**Purpose**:
- `Optional`: Type hint for nullable return values
- `select`, `update`: SQLAlchemy query and update operations
- `Session`: SQLAlchemy database session
- `get_logger`: Structured logging

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger.

#### Main Job Claiming Function

```python
def claim_next_reel(session: Session) -> Optional["Reel"]:
    """Claim the next available reel for processing with row-level locking."""
```

**Purpose**: Claim a single reel for processing, preventing duplicate claims.

**Parameters**:
- `session`: SQLAlchemy database session

**Returns**: Reel object if claim successful, None if no reels available

```python
    # Query for next available reel with row-level locking
    query = select(Reel).where(
        Reel.ingestion_status == "READY_FOR_PROCESSING"
    ).order_by(
        # Same priority ordering as scheduler
        (Reel.views + Reel.likes + Reel.comments * 0.001).desc()
    ).order_by(
        Reel.publish_time.desc().nulls_last()
    ).with_for_update(
        skip_locked=True  # Skip rows that are locked by other workers
    ).limit(1)
```

**Purpose**: Build query with row-level locking:
- Only reels ready for processing
- Same priority ordering as scheduler (consistency)
- `with_for_update(skip_locked=True)` prevents duplicate claims
- Limited to 1 reel per claim

```python
    # Execute query
    reel = session.execute(query).scalar_one_or_none()
```

**Purpose**: Execute query and get single reel or None.

```python
    if reel is None:
        logger.debug("job_fetcher_no_reels_available")
        return None
```

**Purpose**: Return None if no reels available.

```python
    # Update status to PROCESSING to prevent other workers from claiming
    update_stmt = (
        update(Reel)
        .where(Reel.id == reel.id)
        .where(Reel.ingestion_status == "READY_FOR_PROCESSING")  # Double-check
        .values(ingestion_status="PROCESSING")
    )
```

**Purpose**: Prepare update to claim the reel:
- Update only this specific reel
- Double-check status is still READY_FOR_PROCESSING
- Set status to PROCESSING

```python
    result = session.execute(update_stmt)
    
    if result.rowcount == 0:
        # Status changed between select and update (race condition)
        logger.warning(
            "job_fetcher_race_condition",
            extra={"reel_id": str(reel.id)}
        )
        session.rollback()
        return None
```

**Purpose**: Handle race condition:
- If rowcount is 0, status changed between select and update
- Rollback any changes
- Return None to try again

```python
    session.commit()
```

**Purpose**: Commit the status change.

```python
    logger.info(
        "job_claimed",
        extra={"reel_id": str(reel.id)}
    )
```

**Purpose**: Log successful claim.

```python
    return reel
```

**Purpose**: Return claimed reel object.

---

## Database Model Integration

### Reel Model Fields Used

```python
# Status field for state management
ingestion_status: str  # PENDING, READY_FOR_PROCESSING, PROCESSING, COMPLETED, FAILED

# Eligibility fields
thumbnail_url: Optional[str]  # Must exist for scheduling
creator_id: Optional[str]    # Must exist for scheduling

# Priority calculation fields
views: Optional[int]          # Engagement metric
likes: Optional[int]          # Engagement metric  
comments: Optional[int]       # Engagement metric
publish_time: Optional[datetime]  # Tie-breaker
```

**Purpose**: Database fields used by scheduler and job fetcher.

### Status Transitions

```python
# Normal flow
PENDING → READY_FOR_PROCESSING (scheduler)
READY_FOR_PROCESSING → PROCESSING (job fetcher)
PROCESSING → COMPLETED/FAILED (worker)

# Error handling
PROCESSING → READY_FOR_PROCESSING (worker timeout/retry)
```

**Purpose**: Valid status transitions and their triggers.

---

## Error Handling and Edge Cases

### 1. Database Connection Issues

```python
try:
    # Database operations
    scheduled_count = schedule_pending_reels(session)
except Exception as exc:
    logger.error("scheduler_error", extra={"error": str(exc)}, exc_info=True)
    # Wait before retrying
    stop_event.wait(min(SCHEDULE_INTERVAL, 30))
```

**Purpose**: Handle connection failures gracefully.

### 2. Race Conditions

```python
# Double-check status in update
.where(Reel.ingestion_status == "READY_FOR_PROCESSING")

# Check update result
if result.rowcount == 0:
    # Status changed between select and update
    session.rollback()
    return None
```

**Purpose**: Prevent processing already-claimed reels.

### 3. Lock Timeouts

```python
# Skip locked rows to prevent blocking
.with_for_update(skip_locked=True)
```

**Purpose**: Prevent workers from waiting on locked rows.

### 4. Empty Result Sets

```python
if not reels:
    logger.info("scheduler_no_pending_reels")
    return 0
```

**Purpose**: Handle case when no work is available.

---

## Performance Considerations

### 1. Database Load

```python
BATCH_SIZE = 25  # Limits per-run impact
SCHEDULE_INTERVAL = 60  # Prevents excessive polling
```

**Purpose**: Configuration to manage database load.

### 2. Index Usage

```python
# Recommended indexes for performance
CREATE INDEX idx_reels_ingestion_status ON reels(ingestion_status);
CREATE INDEX idx_reels_priority ON reels(views, likes, comments, publish_time);
CREATE INDEX idx_reels_creator ON reels(creator_id) WHERE creator_id IS NOT NULL;
```

**Purpose**: Database indexes for optimal query performance.

### 3. Connection Management

```python
# Fresh session per iteration
with session_factory() as session:
    scheduled_count = schedule_pending_reels(session)
```

**Purpose**: Prevent connection leaks and stale data.

### 4. Lock Contention

```python
# Skip locked rows to prevent blocking
.with_for_update(skip_locked=True)
```

**Purpose**: Allow multiple workers to run concurrently.

---

## Monitoring and Observability

### 1. Key Metrics

```python
# Scheduler metrics
reels_found: Number of eligible reels found
reels_updated: Number of reels actually updated
scheduler_duration: Time taken per scheduling run

# Job fetcher metrics
claims_successful: Number of successful job claims
claims_failed: Number of failed claims (race conditions)
claim_duration: Time taken per claim attempt
```

**Purpose**: Important metrics for monitoring system health.

### 2. Log Patterns

```python
# Scheduler logs
"scheduler_started" - Batch size
"scheduler_no_pending_reels" - No work available
"scheduler_completed" - Found vs updated counts
"scheduler_error" - Error details

# Job fetcher logs  
"job_claimed" - Successful claim with reel_id
"job_fetcher_no_reels_available" - No work available
"job_fetcher_race_condition" - Race condition detected
```

**Purpose**: Standardized log messages for monitoring.

### 3. Health Checks

```python
def check_scheduler_health(session: Session) -> dict:
    """Check scheduler health metrics."""
    
    # Count reels in each status
    pending_count = session.execute(
        select(func.count(Reel.id)).where(Reel.ingestion_status == "PENDING")
    ).scalar()
    
    ready_count = session.execute(
        select(func.count(Reel.id)).where(Reel.ingestion_status == "READY_FOR_PROCESSING")
    ).scalar()
    
    processing_count = session.execute(
        select(func.count(Reel.id)).where(Reel.ingestion_status == "PROCESSING")
    ).scalar()
    
    return {
        "pending_count": pending_count,
        "ready_count": ready_count,
        "processing_count": processing_count,
        "total_backlog": pending_count + ready_count
    }
```

**Purpose**: Health check function for monitoring.

---

## Integration Patterns

### 1. Worker Integration

```python
# In worker.py
reel = claim_next_reel(session)
if reel is None:
    return None  # No work available
```

**Purpose**: Worker claims job before processing.

### 2. Service Integration

```python
# In main service
scheduler_thread = threading.Thread(
    target=run_scheduler_loop,
    args=(session_factory, stop_event)
)
scheduler_thread.start()
```

**Purpose**: Run scheduler as background thread.

### 3. Monitoring Integration

```python
# In monitoring system
health_metrics = check_scheduler_health(session)
alert_if_backlog_too_large(health_metrics["total_backlog"])
```

**Purpose**: Monitor system health and alert on issues.

---

## Configuration and Tuning

### 1. Batch Size Tuning

```python
# Factors to consider:
# - Database capacity
# - Network latency to inference service
# - Worker processing time
# - Desired throughput vs latency tradeoff

BATCH_SIZE = 25  # Conservative default
# BATCH_SIZE = 100  # High throughput environment
# BATCH_SIZE = 5   # Resource-constrained environment
```

**Purpose**: Guidelines for tuning batch size.

### 2. Interval Tuning

```python
# Factors to consider:
# - Job arrival rate
# - Processing time per job
# - Database load tolerance
# - Desired responsiveness

SCHEDULE_INTERVAL = 60  # Default: 1 minute
# SCHEDULE_INTERVAL = 30  # More responsive
# SCHEDULE_INTERVAL = 300  # Less database load
```

**Purpose**: Guidelines for tuning scheduling interval.

### 3. Priority Formula

```python
# Current priority formula
priority = views + likes + comments * 0.001

# Alternative formulas:
# priority = views * 0.5 + likes * 0.3 + comments * 0.2
# priority = log(views + 1) + log(likes + 1) + log(comments + 1)
# priority = engagement_rate * views  # engagement_rate = (likes + comments) / views
```

**Purpose**: Options for priority calculation tuning.

---

## Security Considerations

### 1. SQL Injection Prevention

```python
# Use parameterized queries (SQLAlchemy does this automatically)
.where(Reel.ingestion_status == "PENDING")  # Safe
# .where(f"ingestion_status = '{status}'")  # UNSAFE - don't do this
```

**Purpose**: Prevent SQL injection through parameterized queries.

### 2. Privilege Escalation

```python
# Database user should have minimal required permissions:
# - SELECT on reels table
# - UPDATE on reels table (ingestion_status column only)
# - No DELETE, DROP, or administrative privileges
```

**Purpose**: Limit database user permissions.

### 3. Data Exposure

```python
# Logs don't contain sensitive data:
logger.info("job_claimed", extra={"reel_id": str(reel.id)})  # Safe
# logger.info("job_claimed", extra={"reel": reel.__dict__})  # UNSAFE
```

**Purpose**: Prevent sensitive data exposure in logs.

---

This documentation provides complete understanding of the scheduler and job fetcher systems. Every function, parameter, and line of logic is explained to ensure reliable job distribution and prevent duplicate processing in production.
