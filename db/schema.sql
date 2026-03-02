CREATE TABLE IF NOT EXISTS creators (
    id UUID PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    platform VARCHAR(50) NOT NULL DEFAULT 'instagram',
    followers BIGINT,
    category VARCHAR(255),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS reels (
    id UUID PRIMARY KEY,
    reel_url TEXT NOT NULL UNIQUE,
    thumbnail_url TEXT NOT NULL,
    caption TEXT,
    hashtags TEXT[],
    audio_name TEXT,
    views BIGINT,
    likes BIGINT,
    comments BIGINT,
    creator_id UUID NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
    publish_time TIMESTAMPTZ,
    has_engagement_metrics BOOLEAN NOT NULL DEFAULT FALSE,
    is_training_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_completeness_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    ingestion_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    discovery_source VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_reels_ingestion_status_valid
        CHECK (ingestion_status IN ('PENDING', 'READY_FOR_PROCESSING', 'COMPLETED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS ingestion_logs (
    id UUID PRIMARY KEY,
    reel_id UUID NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL,
    error_message TEXT,
    attempted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_ingestion_logs_status_valid
        CHECK (status IN ('success', 'failed', 'skipped', 'retry'))
);

