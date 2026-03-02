# Module 2 Persistence Layer and Database Models - Complete Line-by-Line Documentation

## Overview
The persistence layer handles all database operations for storing extractor results, projections, and embeddings. This document explains the database models, persistence logic, and every line of code in detail.

---

## Database Models

### File: `db/models.py`

#### Imports and Dependencies

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, 
    Integer, String, Text, JSON, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base
```

**Purpose**:
- `datetime`: Date and time handling
- `Optional`: Type hints for nullable fields
- SQLAlchemy imports: Column types, constraints, UUID support, relationships
- `declarative_base`: Base class for ORM models

```python
Base = declarative_base()
```

**Purpose**: Base class for all ORM models.

#### Creator Model

```python
class Creator(Base):
    """Instagram creator/account information."""
    __tablename__ = "creators"
```

**Purpose**: Model for Instagram account/creator data.

##### Primary Key

```python
    id = Column(UUID(as_uuid=True), primary_key=True)
```

**Purpose**: Primary key using UUID for uniqueness and security.

##### Profile Information

```python
    username = Column(String(100), nullable=False, unique=True, index=True)
    full_name = Column(String(200))
    bio = Column(Text)
    profile_pic_url = Column(String(500))
    verified = Column(Boolean, default=False)
    followers_count = Column(Integer)
    following_count = Column(Integer)
    posts_count = Column(Integer)
```

**Purpose**: Creator profile fields:
- `username`: Unique identifier for the account
- `full_name`: Display name
- `bio`: Account biography
- `profile_pic_url`: Profile image URL
- `verified`: Verification badge status
- `followers_count`, `following_count`, `posts_count`: Social metrics

##### Timestamps

```python
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

**Purpose**: Audit timestamps:
- `created_at`: When record was created
- `updated_at`: Last update time (auto-updated)

##### Relationships

```python
    reels = relationship("Reel", back_populates="creator", cascade="all, delete-orphan")
```

**Purpose**: One-to-many relationship to reels:
- `back_populates`: Two-way relationship
- `cascade`: Operations propagate to child reels
- `delete-orphan`: Delete reels when creator is deleted

#### Reel Model

```python
class Reel(Base):
    """Instagram reel/video information."""
    __tablename__ = "reels"
```

**Purpose**: Model for individual Instagram reels.

##### Primary Key and Foreign Key

```python
    id = Column(UUID(as_uuid=True), primary_key=True)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("creators.id"), nullable=False, index=True)
```

**Purpose**: 
- `id`: Primary key for reel
- `creator_id`: Foreign key to creators table with index

##### Content Information

```python
    shortcode = Column(String(100), nullable=False, unique=True, index=True)
    caption = Column(Text)
    hashtags = Column(JSON)  # List of hashtag strings
    video_url = Column(String(500))
    thumbnail_url = Column(String(500))
    duration = Column(Float)  # Video duration in seconds
```

**Purpose**: Reel content fields:
- `shortcode`: Instagram unique identifier
- `caption`: Video caption text
- `hashtags`: JSON array of hashtags
- `video_url`: Direct video URL
- `thumbnail_url`: Thumbnail image URL
- `duration`: Video length in seconds

##### Engagement Metrics

```python
    views = Column(Integer)
    likes = Column(Integer)
    comments = Column(Integer)
    shares = Column(Integer)
    saves = Column(Integer)
```

**Purpose**: Engagement metrics for priority calculation and analysis.

##### Timestamps and Status

```python
    publish_time = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ingestion_status = Column(
        String(20),
        default="PENDING",
        nullable=False,
        index=True
    )
```

**Purpose**: 
- `publish_time`: When reel was published on Instagram
- `scraped_at`: When reel was scraped
- `ingestion_status`: Processing status with index

##### Status Constraints

```python
    __table_args__ = (
        CheckConstraint(
            "ingestion_status IN ('PENDING', 'READY_FOR_PROCESSING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="valid_ingestion_status"
        ),
    )
```

**Purpose**: Database constraint ensuring only valid status values.

##### Relationships

```python
    creator = relationship("Creator", back_populates="reels")
    
    # Feature relationships
    features = relationship("ReelFeatures", back_populates="reel", uselist=False, cascade="all, delete-orphan")
    audio_features = relationship("ReelAudioFeatures", back_populates="reel", uselist=False, cascade="all, delete-orphan")
    text_features = relationship("ReelTextFeatures", back_populates="reel", uselist=False, cascade="all, delete-orphan")
    projections = relationship("ReelProjections", back_populates="reel", uselist=False, cascade="all, delete-orphan")
    embeddings = relationship("ReelEmbeddings", back_populates="reel", uselist=False, cascade="all, delete-orphan")
```

**Purpose**: Relationships to feature tables:
- `creator`: Back to creator model
- Feature tables: One-to-one with cascade delete
- `uselist=False`: Single record per reel

---

## Feature Tables

### File: `db/models.py` (continued)

#### ReelFeatures Model

```python
class ReelFeatures(Base):
    """Core video and ML features including hook analysis."""
    __tablename__ = "reel_features"
```

**Purpose**: Main feature table for video metadata and analysis results.

##### Primary Key

```python
    reel_id = Column(UUID(as_uuid=True), ForeignKey("reels.id"), primary_key=True)
```

**Purpose**: Primary key and foreign key to reels table.

##### Video Metadata

```python
    # Video metadata from video_probe
    duration = Column(Float)
    fps = Column(Float)
    resolution = Column(String(20))  # e.g., "1920x1080"
    width = Column(Integer)
    height = Column(Integer)
```

**Purpose**: Basic video information from ffprobe.

##### Motion Analysis

```python
    # Motion analysis from motion extractor
    motion_score = Column(Float)
    frame_entropy = Column(Float)
    scene_change_rate = Column(Float)
```

**Purpose**: Motion-based features for hook analysis.

##### Text and Audio Features

```python
    # Text features
    ocr_text = Column(Text)
    audio_energy = Column(Float)
    speech_ratio = Column(Float)
    transcript = Column(Text)
```

**Purpose**: Text and audio analysis results.

##### Hook Analysis

```python
    # Hook heuristics (Phase 11)
    hook_motion_score = Column(Float)
    hook_scene_change_rate = Column(Float)
    hook_ocr_present = Column(Boolean)
    hook_signals = Column(JSON)  # List of signal tags
    hook_recommendations = Column(JSON)  # List of recommendation strings
```

**Purpose**: Heuristic hook analysis results.

##### LLM Hook Analysis

```python
    # LLM hook analysis (Phase 14)
    llm_hook_score = Column(Float)
    llm_hook_signals = Column(JSON)
    llm_hook_reasoning = Column(Text)
    llm_hook_confidence = Column(Float)
```

**Purpose**: AI-powered hook analysis results.

##### Future ML Features

```python
    # Future ML features (placeholders)
    object_tags = Column(JSON)  # Detected objects
    emotion_vector = Column(JSON)  # Emotion classification
```

**Purpose**: Reserved fields for future ML capabilities.

##### Metadata

```python
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

**Purpose**: Audit timestamps.

##### Relationship

```python
    reel = relationship("Reel", back_populates="features")
```

**Purpose**: Back-reference to reel model.

#### ReelAudioFeatures Model

```python
class ReelAudioFeatures(Base):
    """Audio-specific features extracted from video."""
    __tablename__ = "reel_audio_features"
    
    reel_id = Column(UUID(as_uuid=True), ForeignKey("reels.id"), primary_key=True)
    
    # Audio analysis features
    tempo = Column(Float)  # Beats per minute
    beat_strength = Column(Float)  # Rhythm clarity
    speech_presence = Column(Boolean)  # Speech detected
    music_presence = Column(Boolean)  # Music detected
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    reel = relationship("Reel", back_populates="audio_features")
```

**Purpose**: Audio analysis features for rhythm and content detection.

#### ReelTextFeatures Model

```python
class ReelTextFeatures(Base):
    """Text analysis features from caption, OCR, and transcript."""
    __tablename__ = "reel_text_features"
    
    reel_id = Column(UUID(as_uuid=True), ForeignKey("reels.id"), primary_key=True)
    
    # Text analysis features
    caption_keywords = Column(JSON)  # Extracted keywords
    ocr_keywords = Column(JSON)  # OCR text keywords
    transcript_keywords = Column(JSON)  # Transcript keywords
    sentiment = Column(String(20))  # Positive/negative/neutral
    intent = Column(String(50))  # Content intent classification
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    reel = relationship("Reel", back_populates="text_features")
```

**Purpose**: Text analysis and NLP features.

#### ReelProjections Model

```python
class ReelProjections(Base):
    """Final projection scores and confidence metrics."""
    __tablename__ = "reel_projections"
    
    reel_id = Column(UUID(as_uuid=True), ForeignKey("reels.id"), primary_key=True)
    
    # Main projection scores
    hook_score = Column(Float)  # Overall hook effectiveness
    pacing_score = Column(Float)  # Pacing quality
    trend_score = Column(Float)  # Trend potential
    
    # Confidence and metadata
    confidence = Column(Float)  # Overall confidence in projections
    projection_version = Column(String(20), default="v1", nullable=False)
    
    # Dataset hardening fields
    feature_coverage = Column(JSON, default=dict)  # Per-extractor success tracking
    extractor_failures = Column(JSON, default=dict)  # Error messages
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    reel = relationship("Reel", back_populates="projections")
```

**Purpose**: Final calculated scores and metadata.

#### ReelEmbeddings Model

```python
class ReelEmbeddings(Base):
    """Text and visual embeddings for similarity search."""
    __tablename__ = "reel_embeddings"
    
    reel_id = Column(UUID(as_uuid=True), ForeignKey("reels.id"), primary_key=True)
    
    # Embedding vectors
    embedding = Column(String)  # pgvector format string
    model_name = Column(String(100), nullable=False)  # e.g., "all-MiniLM-L6-v2"
    model_version = Column(String(20), nullable=False)  # e.g., "v1.0.0"
    embedding_version = Column(String(20), nullable=False)  # e.g., "v1"
    text_bundle_hash = Column(String(64))  # SHA-256 hash of input text
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    reel = relationship("Reel", back_populates="embeddings")
```

**Purpose**: Vector embeddings for similarity search and analysis.

---

## Persistence Layer

### File: `module2/persistence.py`

#### Imports and Dependencies

```python
from typing import Dict, Any, Optional

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from module2.context import ExtractionContext
from module2.logging_config import get_logger
from module2.projections.engine import PROJECTION_VERSION
```

**Purpose**:
- Type hints for better documentation
- SQLAlchemy operations for database queries
- ExtractionContext for accessing results
- Structured logging
- Projection version constant

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger.

#### Main Persistence Function

```python
def persist_from_context(session: Session, context: ExtractionContext, reel_id: str) -> None:
    """Persist all extractor results and projections to database."""
```

**Purpose**: Main function to save all processing results.

**Parameters**:
- `session`: SQLAlchemy database session
- `context`: ExtractionContext with all results
- `reel_id`: Reel identifier for database operations

**Returns**: None

```python
    logger.debug(
        "persistence_started",
        extra={"reel_id": reel_id}
    )
```

**Purpose**: Log persistence start.

##### Feature Collection

```python
    # Collect all successful extractor features
    features_flat = {}
    for extractor_name, result in context.intermediate_outputs.items():
        if result.status == "success" and result.features:
            features_flat.update(result.features)
```

**Purpose**: Flatten all successful extractor features into single dictionary.

##### Core Features Persistence

```python
    # Persist core features
    _persist_core_features(session, reel_id, features_flat, context)
```

**Purpose**: Save main feature table data.

##### Audio Features Persistence

```python
    # Persist audio features if available
    if "tempo" in features_flat or "beat_strength" in features_flat:
        _persist_audio_features(session, reel_id, features_flat)
```

**Purpose**: Save audio analysis results if present.

##### Text Features Persistence

```python
    # Persist text features if available
    if any(key in features_flat for key in ["caption_keywords", "ocr_keywords", "sentiment"]):
        _persist_text_features(session, reel_id, features_flat)
```

**Purpose**: Save text analysis results if present.

##### Projections Persistence

```python
    # Persist projections if available
    projection_result = context.intermediate_outputs.get("projections")
    if projection_result and projection_result.status == "success":
        _persist_projections(session, reel_id, projection_result.features, context)
```

**Purpose**: Save calculated projection scores.

##### Embeddings Persistence

```python
    # Persist embeddings if available
    embedding_result = context.intermediate_outputs.get("embedding")
    if embedding_result and embedding_result.status == "success":
        _persist_embeddings(session, reel_id, embedding_result.features)
```

**Purpose**: Save text embeddings for similarity search.

```python
    logger.debug(
        "persistence_completed",
        extra={
            "reel_id": reel_id,
            "feature_keys": list(features_flat.keys())
        }
    )
```

**Purpose**: Log completion with feature summary.

#### Core Features Persistence

```python
def _persist_core_features(session: Session, reel_id: str, features: Dict[str, Any], context: ExtractionContext) -> None:
    """Persist core video and ML features."""
```

**Purpose**: Save main feature table with comprehensive data.

```python
    # Build update data dictionary
    update_data = {}
    
    # Video metadata
    for key in ["duration", "fps", "resolution", "width", "height"]:
        if key in features:
            update_data[key] = features[key]
```

**Purpose**: Extract video metadata fields.

```python
    # Motion analysis
    for key in ["motion_score", "frame_entropy", "scene_change_rate"]:
        if key in features:
            update_data[key] = features[key]
```

**Purpose**: Extract motion analysis fields.

```python
    # Text and audio
    for key in ["ocr_text", "audio_energy", "speech_ratio", "transcript"]:
        if key in features:
            update_data[key] = features[key]
```

**Purpose**: Extract text and audio fields.

```python
    # Hook heuristics
    for key in ["hook_motion_score", "hook_scene_change_rate", "hook_ocr_present"]:
        if key in features:
            update_data[key] = features[key]
    
    if "hook_signals" in features:
        update_data["hook_signals"] = features["hook_signals"]
    if "hook_recommendations" in features:
        update_data["hook_recommendations"] = features["hook_recommendations"]
```

**Purpose**: Extract hook analysis results.

```python
    # LLM hook analysis
    for key in ["llm_hook_score", "llm_hook_confidence"]:
        if key in features:
            update_data[key] = features[key]
    
    if "llm_hook_signals" in features:
        update_data["llm_hook_signals"] = features["llm_hook_signals"]
    if "llm_hook_reasoning" in features:
        update_data["llm_hook_reasoning"] = features["llm_hook_reasoning"]
```

**Purpose**: Extract LLM analysis results.

```python
    # Future ML features (placeholders)
    for key in ["object_tags", "emotion_vector"]:
        if key in features:
            update_data[key] = features[key]
```

**Purpose**: Extract future ML features.

```python
    # Execute upsert with COALESCE fallback
    if update_data:
        _execute_upsert(
            session=session,
            table="reel_features",
            reel_id=reel_id,
            update_data=update_data
        )
```

**Purpose**: Execute database upsert with collected data.

#### Audio Features Persistence

```python
def _persist_audio_features(session: Session, reel_id: str, features: Dict[str, Any]) -> None:
    """Persist audio-specific features."""
```

**Purpose**: Save audio analysis results.

```python
    audio_features = {}
    
    # Extract audio-specific fields
    for key in ["tempo", "beat_strength", "speech_presence", "music_presence"]:
        if key in features:
            audio_features[key] = features[key]
```

**Purpose**: Extract audio analysis fields.

```python
    if audio_features:
        _execute_upsert(
            session=session,
            table="reel_audio_features",
            reel_id=reel_id,
            update_data=audio_features
        )
```

**Purpose**: Execute upsert for audio features.

#### Text Features Persistence

```python
def _persist_text_features(session: Session, reel_id: str, features: Dict[str, Any]) -> None:
    """Persist text analysis features."""
```

**Purpose**: Save text analysis results.

```python
    text_features = {}
    
    # Extract text analysis fields
    for key in ["caption_keywords", "ocr_keywords", "transcript_keywords", "sentiment", "intent"]:
        if key in features:
            text_features[key] = features[key]
```

**Purpose**: Extract text analysis fields.

```python
    if text_features:
        _execute_upsert(
            session=session,
            table="reel_text_features",
            reel_id=reel_id,
            update_data=text_features
        )
```

**Purpose**: Execute upsert for text features.

#### Projections Persistence

```python
def _persist_projections(session: Session, reel_id: str, projection_features: Dict[str, Any], context: ExtractionContext) -> None:
    """Persist projection scores and metadata."""
```

**Purpose**: Save calculated projection scores.

```python
    # Extract main projection scores
    projection_data = {}
    
    for key in ["hook_score", "pacing_score", "trend_score", "confidence"]:
        if key in projection_features:
            projection_data[key] = projection_features[key]
```

**Purpose**: Extract main projection scores.

```python
    # Always include projection version
    projection_data["projection_version"] = projection_features.get("projection_version", PROJECTION_VERSION)
```

**Purpose**: Ensure version is always saved.

```python
    # Build feature coverage and failure tracking
    feature_coverage = {}
    extractor_failures = {}
    
    for extractor_name, result in context.intermediate_outputs.items():
        feature_coverage[extractor_name] = result.status
        
        if result.status == "failed" and result.error:
            extractor_failures[extractor_name] = result.error
    
    projection_data["feature_coverage"] = feature_coverage
    projection_data["extractor_failures"] = extractor_failures
```

**Purpose**: Track extractor success/failure for debugging.

```python
    _execute_upsert(
        session=session,
        table="reel_projections",
        reel_id=reel_id,
        update_data=projection_data
    )
```

**Purpose**: Execute upsert for projections.

#### Embeddings Persistence

```python
def _persist_embeddings(session: Session, reel_id: str, embedding_features: Dict[str, Any]) -> None:
    """Persist text embeddings with version tracking."""
```

**Purpose**: Save embeddings with conditional upsert logic.

```python
    # Validate all required fields are present
    required_fields = ["embedding", "model_name", "model_version", "embedding_version", "text_bundle_hash"]
    
    if not all(field in embedding_features for field in required_fields):
        logger.warning(
            "embedding_persistence_skipped",
            extra={
                "reel_id": reel_id,
                "missing_fields": [f for f in required_fields if f not in embedding_features]
            }
        )
        return
```

**Purpose**: Validate all required embedding fields are present.

```python
    # Check if embedding should be updated (version-based)
    existing = session.execute(
        select(ReelEmbeddings).where(ReelEmbeddings.reel_id == reel_id)
    ).scalar_one_or_none()
    
    should_update = False
    if existing is None:
        should_update = True  # New record
    else:
        # Check if any version fields changed
        if (existing.model_name != embedding_features["model_name"] or
            existing.model_version != embedding_features["model_version"] or
            existing.embedding_version != embedding_features["embedding_version"] or
            existing.text_bundle_hash != embedding_features["text_bundle_hash"]):
            should_update = True
```

**Purpose**: Determine if embedding needs updating based on version changes.

```python
    if should_update:
        _execute_upsert(
            session=session,
            table="reel_embeddings",
            reel_id=reel_id,
            update_data=embedding_features
        )
        
        logger.debug(
            "embedding_persisted",
            extra={"reel_id": reel_id, "updated": should_update}
        )
    else:
        logger.debug(
            "embedding_unchanged",
            extra={"reel_id": reel_id}
        )
```

**Purpose**: Update embedding if needed, otherwise skip.

#### Generic Upsert Function

```python
def _execute_upsert(session: Session, table: str, reel_id: str, update_data: Dict[str, Any]) -> None:
    """Execute a COALESCE-based upsert operation."""
```

**Purpose**: Generic upsert with COALESCE fallback logic.

```python
    # Build column assignments with COALESCE
    assignments = []
    for column, value in update_data.items():
        assignments.append(f"{column} = COALESCE(EXCLUDED.{column}, {column})")
```

**Purpose**: Create COALESCE assignments to preserve existing data.

```python
    # Build SQL statement
    columns = ", ".join(update_data.keys())
    values = ", ".join([f":{key}" for key in update_data.keys()])
    assignment_clause = ", ".join(assignments)
    
    sql = f"""
        INSERT INTO {table} (reel_id, {columns})
        VALUES (:reel_id, {values})
        ON CONFLICT (reel_id) DO UPDATE SET
            {assignment_clause},
            updated_at = CURRENT_TIMESTAMP
    """
```

**Purpose**: Build parameterized upsert SQL.

```python
    # Add reel_id to parameters
    params = {"reel_id": reel_id}
    params.update(update_data)
```

**Purpose**: Combine reel_id with update data.

```python
    try:
        session.execute(sql, params)
        logger.debug(
            "upsert_successful",
            extra={
                "reel_id": reel_id,
                "table": table,
                "columns": list(update_data.keys())
            }
        )
    except Exception as exc:
        logger.error(
            "upsert_failure",
            extra={
                "reel_id": reel_id,
                "table": table,
                "error": str(exc)
            }
        )
        raise
```

**Purpose**: Execute upsert with error handling and logging.

#### Projection Version Check

```python
def _check_projection_version(session: Session, reel_id: str) -> bool:
    """Check if reel already has projections with current version."""
```

**Purpose**: Prevent reprocessing with same projection version.

```python
    existing = session.execute(
        select(ReelProjections.projection_version)
        .where(ReelProjections.reel_id == reel_id)
    ).scalar_one_or_none()
    
    return existing == PROJECTION_VERSION
```

**Purpose**: Return True if current version already exists.

---

## Database Schema and Migrations

### Schema Creation

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Core tables
CREATE TABLE creators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(200),
    bio TEXT,
    profile_pic_url VARCHAR(500),
    verified BOOLEAN DEFAULT FALSE,
    followers_count INTEGER,
    following_count INTEGER,
    posts_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    creator_id UUID NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
    shortcode VARCHAR(100) UNIQUE NOT NULL,
    caption TEXT,
    hashtags JSON,
    video_url VARCHAR(500),
    thumbnail_url VARCHAR(500),
    duration FLOAT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    publish_time TIMESTAMP,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ingestion_status VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
    
    CONSTRAINT valid_ingestion_status 
        CHECK (ingestion_status IN ('PENDING', 'READY_FOR_PROCESSING', 'PROCESSING', 'COMPLETED', 'FAILED'))
);

-- Feature tables
CREATE TABLE reel_features (
    reel_id UUID PRIMARY KEY REFERENCES reels(id) ON DELETE CASCADE,
    duration FLOAT,
    fps FLOAT,
    resolution VARCHAR(20),
    width INTEGER,
    height INTEGER,
    motion_score FLOAT,
    frame_entropy FLOAT,
    scene_change_rate FLOAT,
    ocr_text TEXT,
    audio_energy FLOAT,
    speech_ratio FLOAT,
    transcript TEXT,
    hook_motion_score FLOAT,
    hook_scene_change_rate FLOAT,
    hook_ocr_present BOOLEAN,
    hook_signals JSON,
    hook_recommendations JSON,
    llm_hook_score FLOAT,
    llm_hook_signals JSON,
    llm_hook_reasoning TEXT,
    llm_hook_confidence FLOAT,
    object_tags JSON,
    emotion_vector JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_reels_ingestion_status ON reels(ingestion_status);
CREATE INDEX idx_reels_creator_id ON reels(creator_id);
CREATE INDEX idx_reels_shortcode ON reels(shortcode);
CREATE INDEX idx_reels_priority ON reels(views, likes, comments, publish_time);
```

**Purpose**: Complete database schema with indexes.

---

## Performance and Optimization

### 1. Index Strategy

```python
# Critical indexes for performance
INGESTION_STATUS_INDEX = "CREATE INDEX CONCURRENTLY idx_reels_ingestion_status ON reels(ingestion_status);"
CREATOR_INDEX = "CREATE INDEX CONCURRENTLY idx_reels_creator_id ON reels(creator_id);"
PRIORITY_INDEX = "CREATE INDEX CONCURRENTLY idx_reels_priority ON reels((views + likes + comments), publish_time);"
```

**Purpose**: Essential indexes for query performance.

### 2. Upsert Optimization

```python
# Use COALESCE to preserve existing data
"column = COALESCE(EXCLUDED.column, column)"
```

**Purpose**: Prevent overwriting existing data with NULL values.

### 3. Connection Pooling

```python
# Recommended connection pool settings
engine = create_engine(
    DATABASE_URL,
    pool_size=20,           # Base connection pool
    max_overflow=30,         # Additional connections under load
    pool_pre_ping=True,      # Validate connections
    pool_recycle=3600        # Recycle connections hourly
)
```

**Purpose**: Optimize database connection management.

### 4. Batch Operations

```python
# Process multiple reels in transaction
with session.begin():
    for reel_data in reel_batch:
        persist_from_context(session, reel_data.context, reel_data.reel_id)
```

**Purpose**: Batch operations for better performance.

---

## Error Handling and Recovery

### 1. Transaction Rollback

```python
try:
    persist_from_context(session, context, reel_id)
    session.commit()
except Exception as exc:
    session.rollback()
    logger.error("persistence_failed", extra={"reel_id": reel_id, "error": str(exc)})
    raise
```

**Purpose**: Ensure atomic operations.

### 2. Constraint Violations

```python
# Handle unique constraint violations
try:
    session.execute(upsert_sql)
except IntegrityError as exc:
    if "unique constraint" in str(exc):
        logger.warning("duplicate_reel", extra={"reel_id": reel_id})
    else:
        raise
```

**Purpose**: Handle database constraint violations.

### 3. Connection Failures

```python
# Retry logic for connection issues
for attempt in range(3):
    try:
        with session_factory() as session:
            persist_from_context(session, context, reel_id)
            break
    except OperationalError as exc:
        if attempt == 2:
            raise
        time.sleep(2 ** attempt)  # Exponential backoff
```

**Purpose**: Handle temporary connection issues.

---

## Security Considerations

### 1. SQL Injection Prevention

```python
# Use parameterized queries
session.execute(sql, {"reel_id": reel_id, "value": data})
# NOT: session.execute(f"UPDATE table SET column = {value} WHERE reel_id = {reel_id}")
```

**Purpose**: Prevent SQL injection through parameterization.

### 2. Data Validation

```python
# Validate data before persistence
if not isinstance(embedding, list) or len(embedding) != 384:
    raise ValueError("Invalid embedding dimensions")
```

**Purpose**: Ensure data integrity.

### 3. Access Control

```python
# Database user permissions
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;
-- No DELETE or DROP permissions
```

**Purpose**: Limit database user permissions.

---

This documentation provides complete understanding of the persistence layer and database models. Every table, field, function, and line of logic is explained to ensure reliable data storage and prevent data corruption in production.
