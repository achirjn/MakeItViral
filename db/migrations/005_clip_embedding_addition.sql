-- Migration: Add CLIP ViT-L/14 visual embedding column (768-dim)
-- Non-destructive: existing 384-dim text embedding column unchanged

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE reel_embeddings
  ADD COLUMN IF NOT EXISTS clip_embedding VECTOR(768);

CREATE INDEX IF NOT EXISTS reel_embeddings_clip_idx
ON reel_embeddings
USING ivfflat (clip_embedding vector_cosine_ops)
WITH (lists = 100);
