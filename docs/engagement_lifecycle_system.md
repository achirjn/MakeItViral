# Engagement Lifecycle System Documentation

## Overview

The Engagement Lifecycle System is a dataset management layer that tracks the stability and suitability of reels for training based on their engagement metrics and age. This system ensures that only reels with stable engagement patterns are used for model training, improving dataset quality and model reliability.

## Architecture

### Components

1. **Database Schema** (`db/migrations/006_engagement_lifecycle.sql`)
2. **ORM Models** (`db/models.py` - Reel model extensions)
3. **Stability Evaluator** (`module2/engagement_lifecycle.py`)
4. **Refresh Job** (`module2/engagement_updater.py`)
5. **Planner Integration** (`module2/planner.py`)

### Data Flow

```
Reel Ingestion → Engagement Tracking → Stability Evaluation → Training Eligibility
     ↓                ↓                    ↓                     ↓
  Basic Data    Lifecycle Fields    Status Updates     Dataset Filtering
```

## Database Schema

### New Fields Added to `reels` Table

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `engagement_last_updated_at` | TIMESTAMP | NULL | Last time engagement metrics were evaluated |
| `engagement_fetch_attempts` | INT | 0 | Number of times engagement was attempted to be fetched |
| `engagement_status` | VARCHAR(20) | 'missing' | Current stability status of the reel |
| `is_active_for_training` | BOOLEAN | TRUE | Whether reel is eligible for training datasets |
| `stability_score` | FLOAT | 0.0 | Numerical stability score (0.0-1.0) |

### Performance Indexes

- `idx_reels_engagement_status` - For filtering by status
- `idx_reels_engagement_last_updated` - For time-based queries
- `idx_reels_active_for_training` - For training dataset selection

### Engagement Status Values

| Status | Description | Training Eligible | Stability Score |
|--------|-------------|-------------------|-----------------|
| `missing` | No engagement data ever collected | ❌ No | 0.0 |
| `unstable` | Engagement data exists but shows high volatility | ❌ No | 0.2-0.5 |
| `stable` | Engagement data exists and shows consistent patterns | ✅ Yes | 1.0 |
| `unavailable` | Engagement data cannot be fetched (private, deleted, etc.) | ❌ No | 0.0 |

## Stability Evaluation Logic

### Core Function: `evaluate_engagement_stability(reel)`

The stability evaluator implements a rule-based system that determines reel suitability based on age and engagement data availability.

#### Evaluation Rules

1. **Missing Engagement Data**
   - **Condition**: `views IS NULL OR likes IS NULL`
   - **Action**: Set status to "missing", training=False, score=0.0
   - **Rationale**: Without engagement metrics, cannot assess stability

2. **Very Recent Reels** (< 3 days)
   - **Condition**: `age_days < 3`
   - **Action**: Set status to "unstable", training=False, score=0.2
   - **Rationale**: Engagement patterns still developing, too volatile

3. **Mature Reels** (≥ 5 days)
   - **Condition**: `age_days >= 5`
   - **Action**: Set status to "stable", training=True, score=1.0
   - **Rationale**: Engagement patterns stabilized, reliable for training

4. **Intermediate Age** (3-4 days)
   - **Condition**: `3 <= age_days < 5`
   - **Action**: Set status to "unstable", training=False, score=0.5
   - **Rationale**: Transition period, not yet stable enough

#### Age Calculation

```python
age_days = (datetime.utcnow() - reel.publish_time).days
```

#### Field Updates

The evaluator updates all lifecycle fields atomically:

```python
reel.engagement_status = computed_status
reel.is_active_for_training = training_eligibility
reel.stability_score = computed_score
reel.engagement_last_updated_at = datetime.utcnow()
reel.engagement_fetch_attempts += 1
```

## Refresh Job System

### Core Function: `refresh_engagement_metrics(session)`

The refresh job periodically updates engagement metrics for all reels and evaluates their stability.

#### Job Characteristics

- **Scope**: Processes all reels in the database
- **Transaction**: Single database transaction with commit/rollback
- **Error Handling**: Individual reel errors don't stop batch processing
- **Logging**: Comprehensive progress tracking and error reporting
- **Performance**: Progress logging every 100 reels

#### Execution Flow

1. **Initialization**
   - Start database session
   - Query all reels
   - Initialize counters

2. **Batch Processing**
   - For each reel:
     - Update `engagement_last_updated_at`
     - Increment `engagement_fetch_attempts`
     - Call stability evaluator
     - Handle individual errors gracefully

3. **Completion**
   - Commit all changes
   - Log final statistics
   - Rollback on critical errors

#### Logging Structure

```python
# Job start
logger.info("engagement_refresh_started")

# Progress (every 100 reels)
logger.debug("engagement_refresh_progress processed=%d")

# Individual reel updates (from evaluator)
logger.info("engagement_status_stable_mature reel_id=%s age_days=%d")

# Job completion
logger.info("engagement_refresh_completed total=%d updated=%d errors=%d")

# Error handling
logger.error("engagement_refresh_error reel_id=%s error=%s")
```

## Integration Points

### Planner Integration

The planner has been modified to ensure embeddings always run in baseline:

```python
_BASELINE_EXTRAS: set[str] = {"audio", "embedding", "clip_embedding"}
```

This ensures:
- Complete multimodal dataset coverage
- Consistent feature availability for stability evaluation
- No adaptive activation dependencies

### Transcript Extractor Dependencies

Transcript extractor now depends on video instead of audio:

```python
@property
def dependencies(self) -> List[str]:
    return ["video_fetcher"]

@property
def requires(self) -> set[str]:
    return {"video"}
```

This aligns with remote inference architecture where the Colab server downloads video directly.

## Usage Examples

### Basic Stability Evaluation

```python
from db.models import Reel
from module2.engagement_lifecycle import evaluate_engagement_stability

# Get a reel
reel = session.query(Reel).first()

# Evaluate stability
evaluate_engagement_stability(reel)

# Check results
print(f"Status: {reel.engagement_status}")
print(f"Training Eligible: {reel.is_active_for_training}")
print(f"Stability Score: {reel.stability_score}")
```

### Batch Refresh Job

```python
from db.connection import get_session
from module2.engagement_updater import refresh_engagement_metrics

# Run refresh job
with get_session() as session:
    refresh_engagement_metrics(session)
```

### Query Training-Eligible Reels

```python
from db.models import Reel

# Get stable reels for training
stable_reels = session.query(Reel).filter(
    Reel.engagement_status == 'stable',
    Reel.is_active_for_training == True
).all()

print(f"Found {len(stable_reels)} training-eligible reels")
```

## Monitoring and Observability

### Key Metrics to Monitor

1. **Status Distribution**
   - Percentage of reels in each engagement status
   - Trends over time
   - Bottlenecks in dataset preparation

2. **Age Distribution**
   - Reels by age categories
   - Time to stability
   - Fresh content velocity

3. **Error Rates**
   - Engagement fetch failures
   - Evaluation errors
   - System health indicators

### Sample Queries

```sql
-- Status distribution
SELECT 
    engagement_status,
    COUNT(*) as count,
    AVG(stability_score) as avg_score
FROM reels 
GROUP BY engagement_status;

-- Age vs Status correlation
SELECT 
    CASE 
        WHEN AGE(NOW(), publish_time) < INTERVAL '3 days' THEN '0-3'
        WHEN AGE(NOW(), publish_time) < INTERVAL '5 days' THEN '3-5'
        ELSE '5+'
    END as age_group,
    engagement_status,
    COUNT(*) as count
FROM reels 
GROUP BY age_group, engagement_status
ORDER BY age_group, engagement_status;

-- Training eligibility over time
SELECT 
    DATE_TRUNC('day', engagement_last_updated_at) as date,
    SUM(CASE WHEN is_active_for_training THEN 1 ELSE 0 END) as eligible,
    COUNT(*) as total
FROM reels 
WHERE engagement_last_updated_at IS NOT NULL
GROUP BY DATE_TRUNC('day', engagement_last_updated_at)
ORDER BY date;
```

## Configuration and Tuning

### Stability Thresholds

Current thresholds can be adjusted in `engagement_lifecycle.py`:

```python
# Age thresholds
YOUNG_REEL_DAYS = 3      # Below this = unstable
MATURE_REEL_DAYS = 5     # Above this = stable

# Stability scores
MISSING_SCORE = 0.0
YOUNG_SCORE = 0.2
INTERMEDIATE_SCORE = 0.5
MATURE_SCORE = 1.0
```

### Refresh Frequency

The refresh job should be scheduled based on:

- **Content velocity**: How fast new content is added
- **Engagement volatility**: How quickly metrics change
- **Resource constraints**: Database load considerations

Recommended frequencies:
- **High-velocity feeds**: Every 1-2 hours
- **Medium-velocity feeds**: Every 6-12 hours
- **Low-velocity feeds**: Daily

## Future Enhancements

### Planned Improvements

1. **Growth Rate Analysis**
   - Calculate engagement velocity (likes/views per day)
   - Detect viral patterns
   - Predict future stability

2. **Content Quality Scoring**
   - Combine engagement with content features
   - Multi-dimensional quality assessment
   - Adaptive threshold tuning

3. **Creator-Level Analysis**
   - Track creator consistency
   - Creator reputation scoring
   - Cross-reel pattern detection

4. **Automated Threshold Tuning**
   - ML-based threshold optimization
   - A/B testing framework
   - Performance feedback loops

### Extension Points

The system is designed for easy extension:

- **Custom evaluators**: Implement different stability algorithms
- **Additional metrics**: Add new engagement dimensions
- **Status transitions**: Define more granular status states
- **Integration hooks**: Connect with external data sources

## Troubleshooting

### Common Issues

1. **Stuck in "missing" status**
   - Check engagement data ingestion
   - Verify data pipeline connectivity
   - Review fetch attempt counts

2. **High error rates in refresh job**
   - Check database connectivity
   - Verify reel data integrity
   - Review log files for patterns

3. **Performance issues**
   - Add database indexes
   - Optimize batch sizes
   - Consider parallel processing

### Debugging Tools

```python
# Check reel status details
reel = session.query(Reel).filter(Reel.id == reel_id).first()
print(f"Status: {reel.engagement_status}")
print(f"Last Updated: {reel.engagement_last_updated_at}")
print(f"Fetch Attempts: {reel.engagement_fetch_attempts}")
print(f"Age: {(datetime.utcnow() - reel.publish_time).days} days")

# Manual stability evaluation
from module2.engagement_lifecycle import evaluate_engagement_stability
evaluate_engagement_stability(reel)
session.commit()
```

## Conclusion

The Engagement Lifecycle System provides a robust foundation for dataset quality management in the AI Reel Intelligence Engine. By systematically evaluating engagement stability and managing training eligibility, it ensures that models are trained on high-quality, reliable data while maintaining flexibility for future enhancements.

The modular design allows for easy integration with existing systems and provides clear extension points for advanced features as the platform evolves.
