-- Migration 006: Engagement Lifecycle Tracking
-- ==========================================
-- Adds engagement lifecycle management fields to reels table
-- This supports dataset management logic for engagement stability tracking

ALTER TABLE reels
ADD COLUMN IF NOT EXISTS engagement_last_updated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS engagement_fetch_attempts INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS engagement_status VARCHAR(20) DEFAULT 'missing',
ADD COLUMN IF NOT EXISTS is_active_for_training BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS stability_score FLOAT DEFAULT 0.0;

-- Add index for performance on engagement queries
CREATE INDEX IF NOT EXISTS idx_reels_engagement_status ON reels(engagement_status);
CREATE INDEX IF NOT EXISTS idx_reels_engagement_last_updated ON reels(engagement_last_updated_at);
CREATE INDEX IF NOT EXISTS idx_reels_active_for_training ON reels(is_active_for_training);
