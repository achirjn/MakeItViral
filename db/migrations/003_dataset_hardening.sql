-- Migration: Dataset hardening for 15K reel collection
-- Safe for existing rows (ADD COLUMN IF NOT EXISTS + defaults)
-- No table rewrite required

ALTER TABLE reel_projections
  ADD COLUMN IF NOT EXISTS feature_coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS extractor_failures JSONB NOT NULL DEFAULT '{}'::jsonb;
