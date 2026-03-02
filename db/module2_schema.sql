-- Module 2 tables (Feature Extraction pipeline)
-- Constraints:
-- - reel_id is PRIMARY KEY and FOREIGN KEY -> reels(id)
-- - No raw video/audio/frames persisted here
-- - model_versions JSONB tracks extractor/model versions per row

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS reel_features (
    reel_id UUID PRIMARY KEY REFERENCES reels(id) ON DELETE CASCADE,

    duration DOUBLE PRECISION,
    fps DOUBLE PRECISION,
    resolution VARCHAR(32),

    motion_score DOUBLE PRECISION,
    frame_entropy DOUBLE PRECISION,
    scene_change_rate DOUBLE PRECISION,

    object_tags TEXT[],
    emotion_vector JSONB,

    ocr_text TEXT,
    audio_energy DOUBLE PRECISION,
    speech_ratio DOUBLE PRECISION,
    transcript TEXT,

    hook_motion_score DOUBLE PRECISION,
    hook_scene_change_rate DOUBLE PRECISION,
    hook_ocr_present BOOLEAN,
    hook_signals JSONB,
    hook_recommendations JSONB,

    llm_hook_score DOUBLE PRECISION,
    llm_hook_signals JSONB,
    llm_hook_reasoning TEXT,
    llm_hook_confidence DOUBLE PRECISION,

    model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reel_audio_features (
    reel_id UUID PRIMARY KEY REFERENCES reels(id) ON DELETE CASCADE,

    tempo DOUBLE PRECISION,
    beat_strength DOUBLE PRECISION,
    speech_presence DOUBLE PRECISION,
    music_presence DOUBLE PRECISION,

    model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reel_text_features (
    reel_id UUID PRIMARY KEY REFERENCES reels(id) ON DELETE CASCADE,

    caption_keywords TEXT[],
    ocr_keywords TEXT[],
    transcript_keywords TEXT[],
    sentiment VARCHAR(64),
    intent VARCHAR(64),

    model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reel_projections (
    reel_id UUID PRIMARY KEY REFERENCES reels(id) ON DELETE CASCADE,

    hook_score DOUBLE PRECISION,
    pacing_score DOUBLE PRECISION,
    trend_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    projection_version VARCHAR(64) NOT NULL DEFAULT 'v1_mvp',
    feature_coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
    extractor_failures JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reel_embeddings (
    reel_id UUID PRIMARY KEY REFERENCES reels(id) ON DELETE CASCADE,

    embedding VECTOR(384) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    embedding_version VARCHAR(64) NOT NULL,
    text_bundle_hash VARCHAR(64) NOT NULL,
    clip_embedding VECTOR(768),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS reel_embeddings_embedding_idx
ON reel_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS reel_embeddings_clip_idx
ON reel_embeddings
USING ivfflat (clip_embedding vector_cosine_ops)
WITH (lists = 100);


