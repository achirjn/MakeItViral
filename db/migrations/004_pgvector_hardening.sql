-- Migration: pgvector production hardening
-- Safe for existing rows

-- 1.1 Ensure pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 1.2 Make embedding column NOT NULL (set empty vector for any existing NULLs first)
UPDATE reel_embeddings
SET embedding = ARRAY_FILL(0, ARRAY[384])::vector
WHERE embedding IS NULL;

ALTER TABLE reel_embeddings
  ALTER COLUMN embedding SET NOT NULL;

-- 1.3 Add IVFFLAT index (cosine similarity)
CREATE INDEX IF NOT EXISTS reel_embeddings_embedding_idx
ON reel_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
