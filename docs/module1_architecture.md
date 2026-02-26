# Module 1: Discovery & Ingestion Architecture

This document outlines the architecture, data models, and business logic for Module 1 of the AI Reel Intelligence Engine.

## Objective
The primary responsibility of Module 1 is to discover Instagram Reels via Playwright scrapers and securely ingest their metadata into a PostgreSQL database.

**Crucial Constraints:**
- Raw videos are **never** downloaded or stored.
- `reel_url` strictly stores the Instagram permalink (e.g., `https://www.instagram.com/reel/XYZ123/`), not the CDN URL.
- No feature extraction or embedding generation occurs in this module.

## Technology Stack
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy 2.0 (Synchronous)
- **Scraping:** Playwright (Python)
- **Language:** Python 3.10+

## Database Schema (SQLAlchemy Models)

### `Creator` (`creators` table)
Stores information about the creator of a Reel.
- `id`: UUID (Primary Key)
- `username`: String (Unique)
- `platform`: String (Default: 'instagram')
- `followers`: BigInteger (Nullable)
- `category`: String (Nullable)
- `verified`: Boolean (Default: False)
- `created_at`: DateTime

### `Reel` (`reels` table)
Stores metadata for a scraped Reel.
- `id`: UUID (Primary Key)
- `reel_url`: Text (Unique, enforces Instagram permalink format)
- `thumbnail_url`: Text
- `caption`: Text (Nullable)
- `hashtags`: Array of Strings (Nullable)
- `audio_name`: Text (Nullable)
- `views`: BigInteger (Nullable)
- `likes`: BigInteger (Nullable)
- `comments`: BigInteger (Nullable)
- `creator_id`: UUID (Foreign Key to `creators.id`)
- `publish_time`: DateTime (Nullable)
- `has_engagement_metrics`: Boolean
- `is_training_eligible`: Boolean
- `metadata_completeness_score`: Float
- `ingestion_status`: String (Default: 'pending')
- `discovery_source`: String (Nullable)
- `created_at`: DateTime

### `IngestionLog` (`ingestion_logs` table)
Tracks the success or failure of reel ingestion attempts.
- `id`: UUID (Primary Key)
- `reel_id`: UUID (Foreign Key to `reels.id`)
- `status`: String (Enum: success, failed, skipped, retry)
- `error_message`: Text (Nullable)
- `attempted_at`: DateTime

## Ingestion Logic & Architectural Decisions

### 1. Metadata Completeness Score
The score represents how complete the metadata payload is, guiding whether the Reel is a good candidate for future training or analysis. 
*Note: `reel_url` is strictly required for ingestion and therefore excluded from the weight calculation.*

**Weights:**
- Thumbnail: `0.24`
- Creator Info: `0.12`
- Views: `0.18`
- Likes: `0.18`
- Audio Name: `0.08`
- Caption: `0.12`
- Hashtags: `0.05`
- Comments: `0.04`
- Publish Time: `0.01`

**Engagement Rules:**
- `has_engagement_metrics`: Evaluates to `True` **only if both** `views` and `likes` are present.
- `is_training_eligible`: Strictly mirrors the value of `has_engagement_metrics`. If we don't have engagement data, we cannot train on it.

### 2. Deduplication & Conflicts (Behavior B)
When the Ingestion Service processes a Reel whose `reel_url` already exists in the database:
- The system **updates** all mutable fields (e.g., views, likes, comments, caption, hashtags, thumbnail, etc.).
- The completeness score and engagement flags are **recalculated**.
- A new `IngestionLog` entry with `status="success"` is recorded.

### 3. Ingestion Status (Behavior C)
All successfully ingested Reels are inserted with `ingestion_status = "pending"`. Module 1 does **not** transition this status. A downstream orchestration module or worker will transition the status to `"ready_for_processing"` after verifying eligibility.

## Discovery Strategy (Playwright)
Discovery scripts (`trending.py`, `hashtag.py`, `keyword.py`, `creator.py`) are independent Playwright scripts.
- They utilize a shared authenticated session state (`auth.py` / `storageState.json`).
- They primarily rely on **Network Interception** (`page.on("response")`) to capture precise metrics directly from Instagram's background APIs (`/api/v1/feed/reels_media/`, `/api/graphql`, `xdt_api__v1__clips__home__connection_v2`).
- Extracted dictionaries are parsed and normalized (e.g., converting Unix integer timestamps to PostgreSQL `timezone.utc` objects) before being passed directly to `ingestion_service.py` for processing.
