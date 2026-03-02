# Module 2: Feature Extraction Pipeline Architecture

## Goal
Module 2 converts ingested Instagram reels into multimodal intelligence features and projections.
**Crucial Constraint:** Raw video and intermediate artifacts must remain strictly ephemeral and be deleted as soon as processing completes.

## High-Level Pipeline
```
Scheduler (Polling)
  → Worker (Row-Lock Claim)
    → Engagement Filter (strip heavy extractors if no metrics)
    → ExtractionContext (temp dir creation)
      → Extractor DAG (async parallel execution, 10 extractors)
        → Projection Engine (heuristic + LLM fusion)
        → Persistence (upsert features, projections, embeddings)
      → Cleanup (delete all ephemeral files)
```

---

## 1. The Scheduler (`module2/scheduler.py`)
The scheduler is a **stateless DB polling loop** that transitions Reels from `PENDING` → `READY_FOR_PROCESSING`. It does NOT own any job state — it only writes a status column and exits.

### Eligibility Requirements:
- `ingestion_status = 'PENDING'`
- `thumbnail_url IS NOT NULL`
- `creator_id IS NOT NULL`

### Priority Score (computed at DB level):
```sql
priority = COALESCE(likes, 0) + COALESCE(comments, 0) + COALESCE(views, 0) * 0.001
```
Ties broken by `publish_time DESC NULLS LAST`.

### Safety:
- Uses PostgreSQL `FOR UPDATE SKIP LOCKED` to prevent any two concurrent schedulers from selecting the same row simultaneously.
- `batch_size = 25`, `schedule_interval = 60 seconds`.

---

## 2. The Worker (`module2/worker.py`)

### Input Validation
Before any database interaction, the worker validates that:
1. The `extractors` argument is not `None` → raises `RuntimeError("Extractor registry must be provided to worker")`
2. The materialized `extractor_list` is not empty → raises `RuntimeError("Extractor registry is empty")`

This prevents accidental runs with no extractors from silently claiming and wasting reels.

### Job Claiming (`module2/job_fetcher.py`)
- Queries for one reel with `ingestion_status = 'READY_FOR_PROCESSING'`.
- Same `FOR UPDATE SKIP LOCKED` prevents any two workers from claiming the same row.
- Orders by the same priority score formula as the Scheduler.

### Engagement-Based Filtering (Phase 9 Patch)
After building the metadata dict and before executing the DAG, the worker checks:
```python
has_engagement = views is not None and likes is not None
```
If the reel has **no engagement data**, it strips out the "heavy" extractors to save compute:
```python
heavy_extractors = {"ocr", "transcript", "embedding", "llm_hook"}
```
These 4 extractors are expensive (Tesseract OCR, Whisper transcription, sentence-transformer encoding, OpenAI API call) and not worth running on reels without engagement signals. The remaining extractors (video fetch, probe, frame sampling, motion, audio, hook heuristics) still run.

### Execution Flow (`run_once`):
```
1. Validate extractors (not None, not empty)
2. claim_next_reel()          → row-locked reel object
3. Cooldown check             → skip if reel_id was skipped < 30s ago (in-memory cache)
4. Completion gating          → query reel_projections; skip if projection_version == current
5. Build metadata dict        → includes account_id="test_account"
6. ExtractionContext.create() → temp dir created
7. Engagement filter          → strip heavy extractors if no views/likes
8. execute_extractor_dag()    → all eligible extractors run
9. compute_projections()      → heuristic + LLM fusion scoring
10. persist_from_context()    → upsert features + projections + embeddings
11. session.commit()          → release row lock
12. [finally] cleanup_context() → delete temp dir, video, audio, frames
```

### Completion Gating (Projection-Version Based):
After claiming a reel, the worker queries `reel_projections` for the claimed `reel_id`. If a row exists **and** its `projection_version` matches the current `PROJECTION_VERSION` constant (currently `"v1"`), the worker logs `already_processed_skip` and returns without running the DAG.

This means:
- Each reel is processed **exactly once** per projection version.
- Bumping `PROJECTION_VERSION` in `engine.py` automatically triggers reprocessing of all reels.
- No schema changes are needed — `projection_version` already exists in `reel_projections`.

### Cooldown Skip Optimization:
To prevent tight reclaim loops where the same reel is repeatedly claimed and immediately skipped, the worker maintains an **in-memory ephemeral cache** (`_recent_skip_cache`) of recently skipped reel IDs.

- When a reel is skipped via completion gating, its `reel_id` is cached with the current monotonic timestamp.
- On subsequent claims within `_SKIP_COOLDOWN_SECONDS` (30s), the worker returns immediately with a DEBUG `cooldown_skip` log.
- The cache resets naturally on worker restart (no DB state).
- After the cooldown window expires, the reel is rechecked normally.

### Failure Semantics:
- Any critical extractor failure raises immediately → `session.rollback()` → `cleanup_context()`.
- Non-critical extractor failures are isolated and logged; the pipeline continues.

---

## 3. The Extraction Context (`module2/context.py`)
The `ExtractionContext` is a dataclass that lives for the duration of one worker job.

| Field | Purpose |
|---|---|
| `reel_id` | UUID of reel being processed |
| `temp_dir` | OS temp directory (unique per job) |
| `video_path` | Path to downloaded `.mp4` file |
| `audio_path` | Path to extracted `.wav` file |
| `sampled_frames` | List of paths to extracted `.jpg` frame files |
| `metadata` | Snapshot of reel's Module 1 DB metadata (includes `account_id`) |
| `intermediate_outputs` | All extractor results, keyed by extractor name |
| `model_versions` | Version tags attached to each feature row |
| `transcript` | Shared remote inference result: Whisper transcription |
| `transcript_confidence` | Shared remote inference result: transcript confidence score |
| `text_embedding` | Shared remote inference result: MiniLM 384-dim vector |
| `clip_embedding` | Shared remote inference result: CLIP 768-dim vector |
| `inference_version` | Shared remote inference result: version identifier |

### Cleanup (`module2/cleanup.py`):
`cleanup_context()` is called inside the worker's `finally:` block unconditionally. It:
1. Deletes every frame in `sampled_frames` array
2. Deletes `audio_path`
3. Deletes `video_path`
4. Force-removes the entire `temp_dir` with `shutil.rmtree`

This guarantees zero artifact persistence regardless of success or failure.

---

## 4. The Extractor DAG (`module2/worker.py → execute_extractor_dag`)

A custom `asyncio`-native DAG executor. No external libraries (Airflow, Celery, Prefect) used.

### Execution Algorithm:
1. Build a `by_name` dict of all registered extractors.
2. Maintain a `pending` set of extractor names.
3. Each cycle: identify all extractors with every dependency satisfied → `ready` list.
4. Check if any dependency `failed` or `skipped` → immediately mark this extractor as `skipped` too.
5. Run all remaining `runnable` extractors concurrently via `asyncio.gather`.
6. If any critical extractor returns `failed`, raise `RuntimeError` to abort the entire job.
7. Repeat until `pending` is empty.

### Dependency Graph (Phase 14):
```
video_fetcher (critical)
├── video_probe (critical)
├── remote_inference (critical)
│   ├── embedding (optional)
│   ├── visual_embedding (optional)
│   └── transcript (optional)
├── frame_sampler (critical)
│   ├── motion (critical)
│   │   └── hook (critical)
│   │       └── llm_hook (optional)    ← Phase 14
│   ├── ocr (optional)
│   └── audio (critical)
│       └── transcript (optional)  ← now depends on remote_inference
```

---

## 5. The Extractor Base Interface (`module2/extractors/base.py`)

Every extractor inherits from `BaseExtractor` and must implement:

| Property / Method | Type | Purpose |
|---|---|---|
| `name` | `@property → str` | Unique DAG identifier |
| `dependencies` | `@property → List[str]` | Names of required preceding extractors |
| `output_keys` | `@property → List[str]` | Feature keys this extractor returns |
| `is_critical` | `@property → bool` | If `True`, failure aborts the entire pipeline |
| `requires_gpu` | `@property → bool` | Flag for future GPU scheduling |
| `run(context)` | `async → ExtractorResult` | Core logic |

`ExtractorResult` is a frozen dataclass with `status` (`success`/`failed`/`skipped`), `features` dict, and optional `error` string.

**Strict rule: Extractors NEVER write to the database directly.**

---

## 6. Extractor Implementations (Phases 4–11)

### Phase 4 — Video Fetcher (`extractors/video_fetcher.py`)
- Reads the authenticated Playwright `storageState.json` from Module 1 (`discovery/auth_state/`).
- Converts Playwright JSON cookies to a **Netscape cookie file format** (tab-delimited).
- Passes that cookie file to `yt-dlp`, bypassing Instagram's CDN 403 blocks.
- Writes the `.mp4` to `context.temp_dir` and sets `context.video_path`.
- `is_critical = True`

### Phase 5 — Video Probe (`extractors/video_probe.py`)
- Runs `ffprobe` as an async subprocess.
- Parses the JSON output to extract `duration`, `fps` (handling fractional rate strings like `30000/1001`), `resolution`, `width`, `height`.
- Returns these as features. `is_critical = True`.

### Phase 6 — Frame Sampler (`extractors/frame_sampler.py`)
- Runs `ffmpeg` to extract 1 frame per second from the video (max 60 frames).
- Writes frames as `.jpg` into `context.temp_dir/frames/`.
- **Critically:** appends every frame path directly to `context.sampled_frames` — this is the mechanism by which `cleanup_context` can delete them.
- `is_critical = True`

### Phase 8 — Motion Extractor (`extractors/motion.py`)
- Pipes all sampled frames back through `ffmpeg` into a `rawvideo` byte stream (scaled to 160px wide, grayscale).
- Uses sequential pattern (`frame_%05d.jpg`) matching `frame_sampler`'s output naming — avoids `-pattern_type glob` which is unsupported on Windows ffmpeg builds.
- Computes absolute pixel difference between consecutive frames entirely in pure Python (no OpenCV/NumPy).
- Returns `motion_score` (mean normalized diff) and `scene_change_rate` (changes/second).
- Validates `video_probe` intermediate output has `status == "success"` before reading features.
- `is_critical = True`

### Phase 9 — OCR Extractor (`extractors/ocr.py`)
- Lazy-loads `pytesseract` and `Pillow` inside `run()` — if not installed, returns `status=skipped` (not failed).
- Runs Tesseract OCR over each frame asynchronously via `asyncio.to_thread`.
- Aggregates all text, deduplicates identical lines using a stable-order hash.
- Returns `ocr_text`. `is_critical = False`

### Phase 10 — Audio Extractor (`extractors/audio.py`) + Transcript (`extractors/transcript.py`)
- **Audio:** `ffmpeg` strips the audio track into a 16kHz mono `.wav` file. Sets `context.audio_path`.
- **Transcript:** Lazy-loads `faster-whisper`. If not installed → `status=skipped`. Uses a module-level `_MODEL_CACHE` singleton: the WhisperModel (`base`, CPU, `int8`) is loaded once and reused across all worker jobs. Returns `transcript` string.
- `audio` is `is_critical = True`; `transcript` is `is_critical = False`.

### Phase 11 — Hook Heuristics (`extractors/hook.py`)
- Reads `motion_score`/`scene_change_rate` from `motion` intermediate outputs (required).
- Optionally reads `ocr_text` from `ocr` intermediate outputs (not a DAG dependency; checked if present).
- Uses deterministic thresholds to generate `hook_signals` (list of tags) and `hook_recommendations` (actionable text strings).
- Returns `hook_signals`, `hook_recommendations`, `hook_motion_score`, `hook_scene_change_rate`, `hook_ocr_present`.
- `is_critical = True`

---

## 7. LLM Hook Extractor (`module2/extractors/llm_hook.py`) — Phase 14

The LLM hook extractor sends a structured prompt to OpenAI's API to get an AI-powered hook quality evaluation that complements the deterministic heuristic analysis from Phase 11.

### Input Gathering:
The extractor reads 5 signals from the context:
| Signal | Source |
|---|---|
| `caption` | `context.metadata["caption"]` |
| `hashtags` | `context.metadata["hashtags"]`, space-joined |
| `ocr_text` | `ocr` intermediate output features (if available) |
| `transcript` | `transcript` intermediate output features (if available) |
| `hook_signals` | `hook` intermediate output features (heuristic signals) |

### Prompt Architecture:
- **System prompt:** Instructs the model to act as a "short-form video hook analyst", evaluating whether the first 3 seconds create curiosity, emotional pull, or value promise. Requires strict JSON output.
- **User prompt:** A labeled multi-section text block with `[CAPTION]`, `[HASHTAGS]`, `[OCR]`, `[TRANSCRIPT]`, `[HEURISTIC SIGNALS]` sections.

### LLM Configuration:
| Parameter | Value |
|---|---|
| Model | `gpt-5-mini` |
| API | OpenAI Responses API (`client.responses.create`) |
| Temperature | 0 (deterministic) |
| Max output tokens | 300 |
| Response parsing | `response.output_text` → `json.loads()` |

### Lazy Import:
`from openai import OpenAI` is imported inside `run()`. If the package is not installed → `status=skipped("llm_not_available")`.

### Output Features:
| Key | Type | Description |
|---|---|---|
| `llm_hook_score` | `float [0–1]` | Overall hook effectiveness score |
| `llm_hook_signals` | `list[str]` | Detected patterns (e.g. `"curiosity_gap"`, `"bold_claim"`, `"pattern_interrupt"`) |
| `llm_hook_reasoning` | `str` | 1–2 sentence explanation of the score |
| `llm_hook_confidence` | `float [0–1]` | LLM's self-assessed confidence in the evaluation |

### DAG Properties:
- `dependencies = ["hook"]` — waits for heuristic signals before calling the LLM.
- `is_critical = False` — pipeline continues without LLM analysis if OpenAI unavailable.
- Part of `heavy_extractors` set → skipped for reels without engagement data.

### Error Handling:
- LLM API failure → `failed("llm_error: ...")`
- Invalid JSON response → `failed("llm_invalid_json")`
- All float scores are clamped to `[0.0, 1.0]` after parsing.

---

## 8. Projection Engine (`module2/projections/engine.py`)

`compute_projections(context)` is a **pure compute function** that runs after the DAG completes and **before** persistence.

### Stage 1: Heuristic Score Computation

#### Inputs (from `intermediate_outputs`):
| Signal | Source Extractor |
|---|---|
| `motion_score` | `motion` |
| `scene_change_rate` | `motion` |
| `hook_ocr_present` | `hook` |

#### Normalization:
- `motion_norm = clamp(motion_score / 0.12)` — 0.12 is the normalization ceiling.
- `scene_change_norm = clamp(scene_change_rate / 0.7)` — 0.7 is the normalization ceiling.
- `ocr_flag = 1.0 if hook_ocr_present is True else 0.0` — presence validated with `isinstance(bool)`.

#### Base Scores (all clamped to [0.0, 1.0]):
```
hook_score   = 0.5 × motion_norm + 0.3 × scene_change_norm + 0.2 × ocr_flag
pacing_score = 0.7 × scene_change_norm + 0.3 × motion_norm
trend_score  = scene_change_norm  (placeholder for future trend intelligence)
```

### Stage 2: LLM Hook Fusion (Phase 14)

If the `llm_hook` extractor ran successfully, the projection engine blends the LLM's hook score with the heuristic hook score using a **3-factor calibrated confidence** system.

#### Step 1 — Coverage Confidence (30% weight):
Measures how much text data was available for the LLM to analyze:
```python
text_len = len(caption) + len(ocr_text) + len(transcript_text)
coverage = clamp(text_len / 400.0)
```
A reel with 400+ characters of combined text gets `coverage = 1.0`. A reel with zero text gets `coverage = 0.0`. This down-weights the LLM when it had sparse input.

#### Step 2 — Agreement Confidence (20% weight):
Measures how closely the LLM and heuristic scores agree:
```python
agreement = 1.0 - abs(heuristic_hook_score - llm_hook_score)
```
If both agree (e.g., both say 0.8), `agreement ≈ 1.0`. If they wildly disagree (e.g., 0.2 vs 0.9), `agreement ≈ 0.3`. This reduces the LLM's influence when it contradicts the deterministic analysis.

#### Step 3 — Calibrated Confidence:
```python
C_llm = llm_hook_confidence  # LLM's self-reported confidence (default 0.5 if missing)
C = 0.5 × C_llm + 0.3 × coverage + 0.2 × agreement
```

#### Step 4 — Dynamic Weight Fusion:
```python
w_LLM = 0.4 + 0.4 × C    # LLM weight ranges from 0.4 (low confidence) to 0.8 (high confidence)
w_heuristic = 1.0 - w_LLM  # Heuristic weight is the complement

final_hook_score = w_heuristic × heuristic_hook_score + w_LLM × llm_hook_score
```

**Key behavior:** When the LLM is confident, has lots of text, and agrees with the heuristic → it gets up to 80% weight. When it's unsure, has sparse text, or disagrees → it gets only 40% weight.

If `llm_hook` did not run (skipped/failed), the heuristic score is used unchanged.

### Stage 3: Confidence Score
```
confidence = (required_present + 0.5 × optional_present) / (2 + 0.5 × 1)
```
Required signals: `motion_score`, `scene_change_rate` (count=2). Optional: `hook_ocr_present` (count=1, validated with `isinstance(bool)`).

Results are written to `context.intermediate_outputs["projections"]` along with `projection_version` (currently `"v1"`).

### Defensive Access Pattern:
All extractor feature reads use the null-safe pattern:
```python
entry = context.intermediate_outputs.get("<extractor_name>")
features = (entry or {}).get("features") or {}
```
This guarantees the projection engine **never crashes** when optional extractors are skipped, failed, or return `features: None`. If an optional extractor's output is missing, the engine falls back gracefully (e.g., heuristic-only hook score, zero coverage).

---

## 9. Remote Inference Extractor (`module2/extractors/remote_inference_extractor.py`) — Phase 15

The remote inference extractor centralizes all Colab GPU calls into a **single execution per reel**. It performs Whisper transcription, MiniLM text embedding, and CLIP visual embedding in one multipart upload, then stores results in `ExtractionContext` for downstream extractors to consume.

### Dependencies
- `dependencies = ["video_fetcher"]` — waits for local video download.
- `is_critical = True` — failure aborts the pipeline.
- `requires_gpu = True` — indicates remote GPU usage.

### Execution Flow
1. Validates `context.video_path` exists.
2. Calls `call_remote_inference(context, context.video_path)` with multipart upload.
3. Stores results in `ExtractionContext` fields:
   - `context.transcript`
   - `context.text_embedding`
   - `context.clip_embedding`
   - `context.inference_version`
4. Returns `ExtractorResult.success` with all four keys.

### Output Keys
- `transcript`
- `text_embedding`
- `clip_embedding`
- `inference_version`

### Logging
- `remote_inference_started` with `reel_id`
- `remote_inference_completed` with `reel_id`, `text_dim`, `clip_dim`

---
`persist_from_context()` is the **only** place DB writes happen in Module 2.

### Algorithm:
1. Iterates over `context.intermediate_outputs`.
2. Collects every `features` dict from extractors where `status == 'success'`.
3. Merges all features into a single flat dict (`features_flat`).
4. Calls 5 separate upsert operations:

| Target | Table | Logic |
|---|---|---|
| Core features + hook + LLM hook | `reel_features` | Standard COALESCE upsert |
| audio features | `reel_audio_features` | Standard COALESCE upsert |
| Text features | `reel_text_features` | Standard COALESCE upsert |
| Projections | `reel_projections` | COALESCE upsert (from `projections` entry) |
| Embeddings | `reel_embeddings` | Conditional upsert with WHERE guard |

### Idempotency:
Every upsert uses `ON CONFLICT DO UPDATE SET col = COALESCE(EXCLUDED.col, existing_col)`. This means:
- If a column has a new value → update it.
- If the new value is `NULL` (feature skipped) → **keep the old value**.
- `updated_at` is bumped via `func.now()` when at least one logical column is being updated.

### Embedding Safety:
The embedding upsert does **not** use fallback constants. It extracts all 5 required fields from the extractor's features dict. If any is `None`, the entire embedding upsert is skipped. This prevents partial or corrupted embedding rows.

---

## 11. Database Schema (Module 2)

All tables use `reel_id` as both `PRIMARY KEY` and `FOREIGN KEY → reels(id) ON DELETE CASCADE`.

### `reel_features`
Core video + ML features including hook heuristics and LLM analysis:

| Column Group | Columns |
|---|---|
| Video metadata | `duration`, `fps`, `resolution` |
| Motion analysis | `motion_score`, `frame_entropy`, `scene_change_rate` |
| Future ML | `object_tags` (TEXT[]), `emotion_vector` (JSONB) |
| Text/Audio | `ocr_text`, `audio_energy`, `speech_ratio`, `transcript` |
| Heuristic hook (Phase 11) | `hook_motion_score`, `hook_scene_change_rate`, `hook_ocr_present`, `hook_signals`, `hook_recommendations` |
| LLM hook (Phase 14) | `llm_hook_score`, `llm_hook_signals`, `llm_hook_reasoning`, `llm_hook_confidence` |

### `reel_audio_features`
`tempo`, `beat_strength`, `speech_presence`, `music_presence`

### `reel_text_features`
`caption_keywords`, `ocr_keywords`, `transcript_keywords`, `sentiment`, `intent`

### `reel_projections`
`hook_score`, `pacing_score`, `trend_score`, `confidence`, `projection_version` (default: `v1_mvp`)

### `reel_embeddings`
`embedding` (VECTOR(384) via pgvector), `model_name`, `model_version`, `embedding_version`, `text_bundle_hash`

The `pgvector` extension is enabled via `CREATE EXTENSION IF NOT EXISTS vector;` at the top of `module2_schema.sql`.

---

## 12. Extractor Registry (`module2/extractors/registry.py`)

The `ExtractorRegistry` is the single loader that maps extractor classes to the worker.

- `register(cls)` — validates and stores the class, using an instantiated probe to read `name`.
- `all()` — returns **fresh instances** of every registered extractor (not classes).
- `build_default_registry()` — registers all 10 implemented extractors:

| Order | Extractor | Phase |
|---|---|---|
| 1 | `VideoFetcherExtractor` | 4 |
| 2 | `VideoProbeExtractor` | 5 |
| 3 | `FrameSamplerExtractor` | 6 |
| 4 | `MotionExtractor` | 8 |
| 5 | `OcrExtractor` | 9 |
| 6 | `AudioExtractor` | 10 |
| 7 | `RemoteInferenceExtractor` | 15 |
| 8 | `TranscriptExtractor` | 10 |
| 9 | `HookExtractor` | 11 |
| 10 | `LlmHookExtractor` | 14 |
| 11 | `EmbeddingExtractor` | 13 |
| 12 | `VisualEmbeddingExtractor` | 13 |

---

## 13. Singleton Model Caching

Three extractors use heavy ML models that are expensive to load. Each uses a module-level `_MODEL_CACHE` singleton pattern:

| Extractor | Model | Cache Variable |
|---|---|---|
| `TranscriptExtractor` | `faster-whisper` base model (int8) | `transcript.py::_MODEL_CACHE` |
| `EmbeddingExtractor` | `sentence-transformers/all-MiniLM-L6-v2` | `embedding.py::_MODEL_CACHE` |
| `LlmHookExtractor` | OpenAI client (stateless) | No cache needed |

The pattern is:
```python
_MODEL_CACHE = None

# inside run():
global _MODEL_CACHE
if _MODEL_CACHE is None:
    _MODEL_CACHE = HeavyModel(...)
model = _MODEL_CACHE
```
Models are loaded on first use and persist for the lifetime of the Python process.

---

## 14. Outstanding Items
- **`IngestionStatus` enum**: Missing `PROCESSING` and `COMPLETED` values — currently log-only.
- **`ingestion_service.py`**: Still uses legacy SQLAlchemy 1.x `session.query()` API.
- **`requirements.txt`**: Missing `sentence-transformers`, `pgvector`, and `openai`.
- **`OPENAI_API_KEY`**: Required environment variable for Phase 14 LLM hook — not yet documented in `.env`.
- **`LOG_LEVEL`**: Optional environment variable (default `INFO`) to control log verbosity. Set to `DEBUG` for full extractor/projection tracing.

---

## 15. Observability & Logging (`module2/logging_config.py`)

All Module 2 components use a centralized structured logging system. No raw `logging.getLogger(__name__)` calls — every module uses `get_logger(name)`.

### Configuration:
| Parameter | Value |
|---|---|
| Root logger | `module2` (no propagation to Python root) |
| Handler | `StreamHandler(sys.stdout)` |
| Default level | `INFO` |
| Override | `LOG_LEVEL` env var (e.g. `DEBUG`) |
| Format | `timestamp | LEVEL | module | reel_id=X | message` |

### Context Injection:
A `_ReelContextFilter` is attached to the handler. If a log record does not include `reel_id` in its `extra` dict, the filter injects `reel_id=-` automatically. This ensures every log line is always parseable with the same format.

### Log Levels by Component:

#### Worker (`module2.worker`)
| Level | Event | Details |
|---|---|---|
| INFO | `job_claimed` | reel_id |
| INFO | `dag_started` | reel_id |
| INFO | `projections_computed` | reel_id |
| INFO | `persistence_success` | reel_id |
| INFO | `job_completed` | reel_id, duration_s |
| INFO | `cleanup_completed` | reel_id |
| WARNING | `optional_extractor_failed` | extractor name, error |
| ERROR | `critical_extractor_failed` | extractor name, error |
| ERROR | `rollback_triggered` | error, full traceback |
| CRITICAL | `unexpected_worker_crash` | full traceback |

#### Extractor Base Auto-Logging (`module2.extractor`)
The `run_with_logging()` wrapper on `BaseExtractor` automatically logs around every extractor's `run()`:

| Level | Event | Details |
|---|---|---|
| DEBUG | `extractor_start` | extractor name |
| DEBUG | `extractor_success` | extractor name, **feature keys only** (never values), duration_s |
| DEBUG | `extractor_skipped` | extractor name, reason, duration_s |
| WARNING | `extractor_failed` | extractor name, error, duration_s |

The DAG executor calls `run_with_logging()` instead of `run()` via `getattr` fallback, keeping the `ExtractorLike` protocol unchanged.

#### External Tool Extractors
| Extractor | Level | Event |
|---|---|---|
| `video_fetcher` | DEBUG | `yt_dlp_invoked` |
| `video_fetcher` | ERROR | `yt_dlp_failure` |
| `frame_sampler` | DEBUG | `ffmpeg_sampling_started` |
| `frame_sampler` | ERROR | `ffmpeg_sampling_failure` (truncated to 80 chars) |
| `audio` | DEBUG | `audio_extraction_started` |
| `transcript` | DEBUG | `whisper_invoked` |
| `transcript` | WARNING | `whisper_missing_backend` |
| `ocr` | DEBUG | `tesseract_invoked` (with frame_count) |
| `ocr` | WARNING | `ocr_dependency_missing` (dep name) |
| `ocr` | WARNING | `ocr_frame_failure` (error truncated, no file paths) |

#### LLM Hook (`module2.extractor.llm_hook`)
| Level | Event | Details |
|---|---|---|
| DEBUG | `llm_call_started` | input_length |
| DEBUG | `llm_response_received` | output_length, duration_s |
| WARNING | `llm_invalid_json` | output_length, duration_s |
| ERROR | `llm_call_failed` | error (truncated), duration_s |

**Never logged:** prompts, reasoning text, transcript, OCR text.

#### Projection Engine (`module2.projection`)
| Level | Event | Details |
|---|---|---|
| DEBUG | `heuristic_signals` | motion_score, scene_change_rate, ocr_flag |
| DEBUG | `llm_signals` | llm_hook_score, llm_confidence_raw |
| DEBUG | `calibrated_confidence` | coverage, agreement, final_confidence |
| DEBUG | `fusion_weights` | w_H, w_L |
| DEBUG | `final_scores` | hook, pacing, trend, confidence |

#### Persistence (`module2.persistence`)
| Level | Event | Details |
|---|---|---|
| DEBUG | `feature_keys_persisted` | count, key names (never values) |
| DEBUG | `projection_keys_persisted` | key names |
| DEBUG | `embedding_persisted` | boolean only |
| ERROR | `upsert_failure` | table name, error (truncated) |

#### Neighbor Similarity (`module2.projection.neighbor`)
| Level | Event | Details |
|---|---|---|
| DEBUG | `neighbor_query_started` | k |
| DEBUG | `neighbor_count` | count, avg_similarity |
| ERROR | `similarity_query_failed` | error (truncated) |

#### Cleanup (`module2.cleanup`)
| Level | Event | Details |
|---|---|---|
| DEBUG | `cleanup_started` | — |
| DEBUG | `frame_count_removed` | count |
| DEBUG | `audio_removed` | boolean |
| DEBUG | `video_removed` | boolean |
| DEBUG | `temp_dir_removed` | boolean |
| WARNING | `cleanup_partial_failure` | type (file/dir), error |

### Security Rules (enforced across all components):
- ❌ Never log cookie paths
- ❌ Never log embedding vectors
- ❌ Never log LLM prompts or reasoning text
- ❌ Never log raw video/audio/frame artifacts or file paths
- ❌ Never log full feature value payloads
- ✅ Always include `reel_id` in every log record
- ✅ Truncate long text to 80 characters maximum
- ✅ Log only feature **key names**, not values

---

## 16. Neighbor Similarity (`module2/projections/neighbor_similarity.py`)

`fetch_embedding_neighbors(session, reel_id, embedding_vector, k=5)` retrieves the k nearest reels by cosine similarity using pgvector's `<=>` operator.

### Query:
```sql
SELECT r.id, 1 - (e.embedding <=> :embedding) AS similarity,
       r.views, r.likes, r.comments
FROM reel_embeddings e
JOIN reels r ON r.id = e.reel_id
WHERE r.id != :reel_id
ORDER BY e.embedding <=> :embedding
LIMIT :k
```

### Returns:
List of dicts: `{ similarity: float, views: int, likes: int, comments: int }`

### Safety:
- If `embedding_vector is None` → returns `[]`.
- Any exception is caught and returns `[]` (failure-isolated — trend intelligence is optional).
- Never logs embedding vectors.

---

## 17. Feature Gating & Activation Planner (`module2/planner.py`)

The pipeline uses **demand-driven DAG execution**: heavy extractors only run when their outputs are needed by the projection engine.

### Extractor Metadata

`BaseExtractor` provides 4 non-abstract metadata properties (safe defaults for backward compatibility):

| Property | Type | Default | Purpose |
|---|---|---|---|
| `produces` | `set[str]` | `set()` | Logical feature names this extractor produces |
| `requires` | `set[str]` | `set()` | Features required before this extractor can run |
| `optional_requires` | `set[str]` | `set()` | Features used if available, not required |
| `heavy` | `bool` | `False` | True for expensive extractors (ML, API calls) |

### Extractor Feature Graph

| Extractor | `produces` | `requires` | `optional_requires` | `heavy` |
|---|---|---|---|---|
| `video_fetcher` | `video` | — | — | ✗ |
| `video_probe` | `probe` | `video` | — | ✗ |
| `frame_sampler` | `frames` | `probe` | — | ✗ |
| `motion` | `motion` | `frames` | — | ✗ |
| `hook` | `hook_score` | `motion` | `ocr` | ✗ |
| `audio` | `audio` | `frames` | — | ✗ |
| `ocr` | `ocr` | `frames` | — | ✓ |
| `remote_inference` | `inference` | `video` | — | ✓ |
| `transcript` | `transcript` | `inference` | — | ✓ |
| `llm_hook` | `llm_hook_score`, `llm_hook_confidence` | `hook_score` | `ocr`, `transcript` | ✓ |
| `embedding` | `embedding` | `inference` | `ocr`, `transcript` | ✓ |
| `visual_embedding` | `clip_embedding` | `inference` | — | ✓ |

### Projection Demand Constants (`engine.py`)

```python
REQUIRED_PROJECTION_FEATURES = {"hook_score", "motion"}
OPTIONAL_PROJECTION_FEATURES = {"llm_hook_score", "llm_hook_confidence", "embedding"}
```

### Two-Phase Execution

**Phase A — Baseline:** Backward-propagates `REQUIRED_PROJECTION_FEATURES` + `_BASELINE_EXTRAS` through extractor graph → activates `video_fetcher → video_probe → frame_sampler → motion → hook` + `remote_inference` (always runs due to baseline extras).

**Phase B — Adaptive:** After baseline executes, heuristic signals determine which heavy extractors to activate:

| Heuristic Signal | Demanded Features | Activated Extractors |
|---|---|---|
| Hook score in gray zone [0.25, 0.75] | `llm_hook_score`, `llm_hook_confidence` | `llm_hook` |
| Reel has engagement metrics (views + likes) | `embedding` | `embedding` |

Phase B extractors are backward-propagated and topologically sorted. Only extractors not already in baseline are executed.

### Planner API

```python
plan_baseline_extractors(extractors) -> list     # Phase A
plan_adaptive_extractors(extractors, context) -> list  # Phase B (minus baseline)
topo_sort_extractors(extractors) -> list         # Kahn's algorithm
```

### Worker Integration

```
baseline = plan_baseline_extractors(extractors)
await execute_extractor_dag(context, baseline)

adaptive = plan_adaptive_extractors(extractors, context)
if adaptive:
    await execute_extractor_dag(context, adaptive)
```

Replaces the legacy `heavy_extractors` engagement filter.

---

## 18. Dataset Hardening (15K Run Safety)

Safety and integrity guarantees for large-scale dataset collection.

### Schema Additions
- `feature_coverage JSONB NOT NULL DEFAULT '{}'` — records per-extractor success/fail/skip.
- `extractor_failures JSONB NOT NULL DEFAULT '{}'` — records error messages for failed extractors.
- Migration: `db/migrations/003_dataset_hardening.sql` (must run before worker start).

### Runtime Guards
- **240s hard timeout** per reel (`asyncio.wait_for`). On timeout: rollback, cleanup, no partial persistence.
- **500MB video size limit**. After download: check file size, skip if exceeded.

### Projection Version Freeze
- `_LOCKED_PROJECTION_VERSION` captured at module load.
- Every `run_once` asserts no mid-run mutation. Mismatch → `RuntimeError` (fail fast).
- Startup log: `projection_version_locked: v1`

### Periodic Metrics
Every 100 reels, structured `worker_metrics` log with: `total_processed`, `total_failed`, `total_skipped`, `total_timeouts`, `avg_runtime_s`, `heavy_activation_rate`, `failure_rate`.

### Startup Self-Test
`verify_dataset_schema()` executes `SELECT feature_coverage, extractor_failures FROM reel_projections LIMIT 1`. Missing columns → `RuntimeError` with migration instructions.

### Safe Re-run
- Same `projection_version` → `already_processed_skip` (existing behavior).
- Different `projection_version` → `reprocess_detected` log, full reprocessing.
- Coverage and failures fully overwritten on re-run (no COALESCE).

---

## 19. Outstanding Items
- **`IngestionStatus` enum**: Missing `PROCESSING` and `COMPLETED` values — currently log-only.
- **`ingestion_service.py`**: Still uses legacy SQLAlchemy 1.x `session.query()` API.
- **`OPENAI_API_KEY`**: Required environment variable for Phase 14 LLM hook — not yet documented in `.env`.
- **`LOG_LEVEL`**: Optional environment variable (default `INFO`) — set to `DEBUG` for extractor tracing.
- **`scheduler.py`**: Still uses raw `logging.getLogger(__name__)` — not yet migrated to `get_logger`.
