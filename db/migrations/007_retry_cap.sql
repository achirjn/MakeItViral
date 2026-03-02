-- Migration 007: Add Retry Cap for Worker Safety
-- ==============================================
-- Adds retry tracking to prevent infinite retries on failed reels

ALTER TABLE reels
ADD COLUMN IF NOT EXISTS retries INT DEFAULT 0;

-- Add index for performance on retry queries
CREATE INDEX IF NOT EXISTS idx_reels_retries ON reels(retries);
