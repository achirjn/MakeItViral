# Module 2 Projection Engine and Remote Inference - Complete Line-by-Line Documentation

## Overview
The projection engine converts raw extractor outputs into meaningful scores and insights. Remote inference provides ML-powered analysis through external GPU services. This document explains both systems in detail.

---

## Projection Engine

### File: `module2/projections/engine.py`

#### Imports and Dependencies

```python
import math
from typing import Dict, List, Optional, Any

from module2.context import ExtractionContext
from module2.logging_config import get_logger
```

**Purpose**:
- `math`: Mathematical operations for score calculations
- `typing`: Type hints for better code documentation
- `ExtractionContext`: Access to extractor results
- `get_logger`: Structured logging

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger instance.

#### Constants and Configuration

```python
PROJECTION_VERSION = "v1"
```

**Purpose**: Version identifier for projection calculations. Used for cache invalidation and reprocessing detection.

```python
# Normalization constants based on empirical analysis
MOTION_NORMALIZATION_CEILING = 0.12
SCENE_CHANGE_NORMALIZATION_CEILING = 0.7
```

**Purpose**: Empirically determined maximum values for normalization. Prevents outliers from skewing scores.

```python
# Required and optional feature sets for projection calculation
REQUIRED_PROJECTION_FEATURES = {"hook_score", "motion"}
OPTIONAL_PROJECTION_FEATURES = {"llm_hook_score", "llm_hook_confidence", "embedding"}
```

**Purpose**: Feature classification for dependency resolution and adaptive execution.

#### Utility Functions

```python
def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamp a float value between min and max bounds."""
    return max(min_val, min(max_val, max_val))
```

**Purpose**: Utility function to constrain values to [0.0, 1.0] range.
**Parameters**:
- `value`: Input float value
- `min_val`: Minimum allowed value (default 0.0)
- `max_val`: Maximum allowed value (default 1.0)
**Returns**: Clamped float value

#### Main Projection Function

```python
def compute_projections(context: ExtractionContext) -> None:
    """Compute all projections from extractor results and store in context."""
```

**Purpose**: Main entry point for projection calculation.

**Parameters**:
- `context`: ExtractionContext containing all extractor results

**Returns**: None (results stored in context.intermediate_outputs)

```python
    logger.debug(
        "projections_started",
        extra={"reel_id": context.reel_id}
    )
```

**Purpose**: Log projection calculation start.

##### Stage 1: Extract Features

```python
    # Extract features from intermediate outputs with null safety
    def get_features(extractor_name: str) -> Dict[str, Any]:
        """Safely extract features from extractor result."""
        result = context.intermediate_outputs.get(extractor_name)
        if not result or result.status != "success":
            return {}
        return result.features or {}
```

**Purpose**: Helper function for safe feature extraction with null checks.

```python
    # Get required features
    motion_features = get_features("motion")
    hook_features = get_features("hook")
    
    # Get optional features
    llm_hook_features = get_features("llm_hook")
    embedding_features = get_features("embedding")
```

**Purpose**: Extract features from relevant extractors.

##### Stage 2: Calculate Base Scores

```python
    # Extract motion and scene change values
    motion_score_raw = motion_features.get("motion_score", 0.0)
    scene_change_rate_raw = motion_features.get("scene_change_rate", 0.0)
    hook_ocr_present = hook_features.get("hook_ocr_present", False)
```

**Purpose**: Extract raw values with defaults.

```python
    # Normalize motion and scene change scores
    motion_norm = clamp(motion_score_raw / MOTION_NORMALIZATION_CEILING)
    scene_change_norm = clamp(scene_change_rate_raw / SCENE_CHANGE_NORMALIZATION_CEILING)
    ocr_flag = 1.0 if hook_ocr_present else 0.0
```

**Purpose**: Normalize raw values to [0.0, 1.0] range.

```python
    # Calculate base scores using weighted formulas
    hook_score = 0.5 * motion_norm + 0.3 * scene_change_norm + 0.2 * ocr_flag
    pacing_score = 0.7 * scene_change_norm + 0.3 * motion_norm
    trend_score = scene_change_norm  # Placeholder for future trend intelligence
```

**Purpose**: Calculate base scores using empirically determined weights:
- Hook score: 50% motion, 30% scene change, 20% OCR
- Pacing score: 70% scene change, 30% motion
- Trend score: Currently just scene change (placeholder)

##### Stage 3: LLM Hook Fusion (if available)

```python
    # Check if LLM hook features are available
    llm_hook_score_raw = llm_hook_features.get("llm_hook_score")
    llm_hook_confidence_raw = llm_hook_features.get("llm_hook_confidence")
    
    if llm_hook_score_raw is not None:
        # Stage 3a: Calculate coverage confidence (30% weight)
        caption = context.metadata.get("caption", "")
        ocr_text = get_features("ocr").get("ocr_text", "")
        transcript_text = get_features("transcript").get("transcript", "")
        
        text_length = len(caption) + len(ocr_text) + len(transcript_text)
        coverage = clamp(text_length / 400.0)  # 400 chars = full coverage
```

**Purpose**: Calculate coverage confidence based on available text data.

```python
        # Stage 3b: Calculate agreement confidence (20% weight)
        agreement = 1.0 - abs(hook_score - llm_hook_score_raw)
```

**Purpose**: Calculate agreement between heuristic and LLM scores.

```python
        # Stage 3c: Calculate calibrated confidence
        llm_confidence = llm_hook_confidence_raw or 0.5  # Default if missing
        calibrated_confidence = 0.5 * llm_confidence + 0.3 * coverage + 0.2 * agreement
```

**Purpose**: Combine LLM confidence, coverage, and agreement into final confidence.

```python
        # Stage 3d: Calculate dynamic fusion weights
        w_llm = 0.4 + 0.4 * calibrated_confidence  # Range: 0.4 to 0.8
        w_heuristic = 1.0 - w_llm  # Complement weight
        
        # Stage 3e: Fuse scores
        final_hook_score = w_heuristic * hook_score + w_llm * llm_hook_score_raw
```

**Purpose**: Dynamically weight LLM vs heuristic based on confidence.

```python
        logger.debug(
            "llm_fusion_applied",
            extra={
                "reel_id": context.reel_id,
                "coverage": round(coverage, 3),
                "agreement": round(agreement, 3),
                "calibrated_confidence": round(calibrated_confidence, 3),
                "w_llm": round(w_llm, 3),
                "w_heuristic": round(w_heuristic, 3),
                "heuristic_hook": round(hook_score, 3),
                "llm_hook": round(llm_hook_score_raw, 3),
                "final_hook": round(final_hook_score, 3)
            }
        )
        
        hook_score = final_hook_score  # Use fused score
```

**Purpose**: Log fusion details and update hook score.

##### Stage 4: Calculate Overall Confidence

```python
    # Calculate confidence based on feature availability
    required_present = 0
    optional_present = 0
    
    # Check required features
    if motion_score_raw > 0:
        required_present += 1
    if scene_change_rate_raw > 0:
        required_present += 1
    
    # Check optional features
    if hook_ocr_present:
        optional_present += 1
    if llm_hook_score_raw is not None:
        optional_present += 1
    if embedding_features:
        optional_present += 1
```

**Purpose**: Count available features for confidence calculation.

```python
    # Calculate confidence score
    total_required = 2  # motion, scene_change
    total_optional = 3  # ocr, llm_hook, embedding
    
    confidence = (required_present + 0.5 * optional_present) / (total_required + 0.5 * total_optional)
    confidence = clamp(confidence)
```

**Purpose**: Calculate confidence as weighted average of feature availability.

##### Stage 5: Store Results

```python
    # Assemble projection results
    projections = {
        "hook_score": round(hook_score, 4),
        "pacing_score": round(pacing_score, 4),
        "trend_score": round(trend_score, 4),
        "confidence": round(confidence, 4),
        "projection_version": PROJECTION_VERSION,
        
        # Include intermediate values for debugging
        "motion_norm": round(motion_norm, 4),
        "scene_change_norm": round(scene_change_norm, 4),
        "ocr_flag": ocr_flag,
        
        # Include LLM fusion details if available
        "llm_hook_score": round(llm_hook_score_raw, 4) if llm_hook_score_raw is not None else None,
        "llm_confidence": round(llm_confidence, 4) if llm_hook_score_raw is not None else None,
        "fusion_weights": {
            "llm": round(w_llm, 4) if llm_hook_score_raw is not None else None,
            "heuristic": round(w_heuristic, 4) if llm_hook_score_raw is not None else None
        } if llm_hook_score_raw is not None else None
    }
```

**Purpose**: Create comprehensive projection dictionary with all calculated values.

```python
    # Store in context for persistence
    from module2.extractors.base import ExtractorResult
    context.intermediate_outputs["projections"] = ExtractorResult.success(projections)
```

**Purpose**: Store projections in context using same format as extractors.

```python
    logger.debug(
        "projections_computed",
        extra={
            "reel_id": context.reel_id,
            "hook_score": round(hook_score, 4),
            "pacing_score": round(pacing_score, 4),
            "trend_score": round(trend_score, 4),
            "confidence": round(confidence, 4)
        }
    )
```

**Purpose**: Log final projection scores.

---

## Remote Inference System

### File: `module2/remote_inference.py`

#### Imports and Dependencies

```python
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

import aiohttp
from module2.context import ExtractionContext
from module2.logging_config import get_logger
```

**Purpose**:
- `asyncio`: Asynchronous operations
- `json`: JSON serialization/deserialization
- `Path`: File system path handling
- `aiohttp`: Async HTTP client for API calls
- `ExtractionContext`: Access to video path and results storage
- `get_logger`: Structured logging

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger.

#### Configuration Constants

```python
# Remote inference service configuration
REMOTE_INFERENCE_URL = "http://localhost:8000/process_reel"
REQUEST_TIMEOUT = 300  # 5 minutes
MAX_RETRIES = 2
RETRY_DELAY = 5  # seconds
```

**Purpose**: Configuration for remote inference service:
- URL of Colab inference server
- Request timeout in seconds
- Maximum retry attempts
- Delay between retries

#### Main Remote Inference Function

```python
async def call_remote_inference(
    context: ExtractionContext,
    video_path: str
) -> Dict[str, Any]:
    """Call remote inference service with video file and return results."""
```

**Purpose**: Main function for remote inference calls.

**Parameters**:
- `context`: ExtractionContext for logging and result storage
- `video_path`: Path to video file to upload

**Returns**: Dictionary containing inference results

```python
    logger.info(
        "remote_inference_started",
        extra={"reel_id": context.reel_id}
    )
```

**Purpose**: Log inference start.

##### Request Preparation

```python
    # Validate video file exists
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
```

**Purpose**: Validate input file exists.

```python
    # Prepare request data
    data = aiohttp.FormData()
    data.add_field('reel_id', context.reel_id)
    
    # Add video file as multipart upload
    with open(video_file, 'rb') as f:
        data.add_field(
            'video',
            f,
            filename=video_file.name,
            content_type='video/mp4'
        )
```

**Purpose**: Prepare multipart form data:
- Add reel_id as form field
- Add video file as file upload
- Set proper content type

##### HTTP Request Execution

```python
    # Execute request with retries
    last_error = None
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(REMOTE_INFERENCE_URL, data=data) as response:
                    if response.status == 200:
                        # Parse successful response
                        response_text = await response.text()
                        result = json.loads(response_text)
                        
                        # Validate response structure
                        if not _validate_response(result):
                            raise ValueError("Invalid response structure")
                        
                        logger.info(
                            "remote_inference_completed",
                            extra={
                                "reel_id": context.reel_id,
                                "attempt": attempt + 1,
                                "text_dim": len(result.get("text_embedding", [])),
                                "clip_dim": len(result.get("clip_embedding", []))
                            }
                        )
                        
                        return result
                    else:
                        error_text = await response.text()
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=f"HTTP {response.status}: {error_text}"
                        )
```

**Purpose**: Execute HTTP POST request with retry logic:
- Create client session with timeout
- Send multipart data
- Handle successful responses
- Validate response structure
- Log success with dimensions

```python
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "remote_inference_attempt_failed",
                extra={
                    "reel_id": context.reel_id,
                    "attempt": attempt + 1,
                    "error": str(exc)
                }
            )
            
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                break
```

**Purpose**: Handle request failures with retries:
- Catch network, timeout, and JSON errors
- Log each failed attempt
- Wait between retries
- Break after max attempts

##### Error Handling

```python
    # All attempts failed
    logger.error(
        "remote_inference_failed",
        extra={
            "reel_id": context.reel_id,
            "total_attempts": MAX_RETRIES + 1,
            "final_error": str(last_error)
        }
    )
    
    raise RuntimeError(f"Remote inference failed after {MAX_RETRIES + 1} attempts: {last_error}")
```

**Purpose**: Log final failure and raise exception.

#### Response Validation

```python
def _validate_response(response: Dict[str, Any]) -> bool:
    """Validate remote inference response structure and content."""
```

**Purpose**: Validate response format and required fields.

**Parameters**:
- `response`: Parsed JSON response from inference service

**Returns**: Boolean indicating validity

```python
    # Check required top-level fields
    required_fields = ["transcript", "text_embedding", "clip_embedding"]
    for field in required_fields:
        if field not in response:
            logger.error(
                "response_missing_field",
                extra={"missing_field": field}
            )
            return False
```

**Purpose**: Validate required fields exist.

```python
    # Validate transcript
    transcript = response.get("transcript")
    if not isinstance(transcript, str):
        logger.error("response_invalid_transcript")
        return False
```

**Purpose**: Validate transcript is a string.

```python
    # Validate text embedding dimensions
    text_embedding = response.get("text_embedding")
    if not isinstance(text_embedding, list) or len(text_embedding) != 384:
        logger.error(
            "response_invalid_text_embedding",
            extra={"length": len(text_embedding) if isinstance(text_embedding, list) else "not_list"}
        )
        return False
```

**Purpose**: Validate text embedding is 384-dimensional list.

```python
    # Validate CLIP embedding dimensions
    clip_embedding = response.get("clip_embedding")
    if not isinstance(clip_embedding, list) or len(clip_embedding) != 768:
        logger.error(
            "response_invalid_clip_embedding",
            extra={"length": len(clip_embedding) if isinstance(clip_embedding, list) else "not_list"}
        )
        return False
```

**Purpose**: Validate CLIP embedding is 768-dimensional list.

```python
    # Validate embedding values are numeric
    for embedding, name in [(text_embedding, "text"), (clip_embedding, "clip")]:
        if not all(isinstance(x, (int, float)) for x in embedding):
            logger.error(
                "response_embedding_non_numeric",
                extra={"embedding_type": name}
            )
            return False
```

**Purpose**: Validate all embedding values are numeric.

```python
    return True
```

**Purpose**: All validations passed.

---

## Remote Inference Extractor

### File: `module2/extractors/remote_inference_extractor.py`

#### Imports and Dependencies

```python
from typing import List

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger
from module2.remote_inference import call_remote_inference
```

**Purpose**:
- `List`: Type hint for dependencies
- `ExtractionContext`: Access to video path and result storage
- `BaseExtractor`, `ExtractorResult`: Base classes
- `get_logger`: Structured logging
- `call_remote_inference`: Remote inference client

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger.

#### Extractor Implementation

```python
class RemoteInferenceExtractor(BaseExtractor):
    """Centralizes all remote inference calls into a single execution per reel."""
    
    @property
    def name(self) -> str:
        return "remote_inference"
```

**Purpose**: Unique identifier for DAG resolution.

```python
    @property
    def dependencies(self) -> List[str]:
        return ["video_fetcher"]  # Requires downloaded video
```

**Purpose**: Depends on video being downloaded first.

```python
    @property
    def output_keys(self) -> List[str]:
        return ["transcript", "text_embedding", "clip_embedding", "inference_version"]
```

**Purpose**: All remote inference results for downstream consumption.

```python
    @property
    def is_critical(self) -> bool:
        return True  # Critical for downstream extractors
```

**Purpose**: Critical - failure aborts pipeline.

```python
    @property
    def requires_gpu(self) -> bool:
        return True  # Indicates remote GPU usage
```

**Purpose**: Indicates GPU resource requirement.

```python
    async def run(self, context: ExtractionContext) -> ExtractorResult:
        """Execute remote inference and store results in context."""
```

**Purpose**: Main execution method.

```python
        try:
            # Validate video path exists
            if not context.video_path:
                return ExtractorResult.failed("missing_video_path")
```

**Purpose**: Input validation.

```python
            # Call remote inference service
            result = await call_remote_inference(context, context.video_path)
```

**Purpose**: Execute remote inference.

```python
            # Store results in context for downstream extractors
            context.transcript = result.get("transcript")
            context.transcript_confidence = result.get("transcript_confidence", 0.0)
            context.text_embedding = result.get("text_embedding")
            context.clip_embedding = result.get("clip_embedding")
            context.inference_version = result.get("inference_version", "v1")
```

**Purpose**: Store all results in context fields.

```python
            # Return success with all features
            features = {
                "transcript": context.transcript,
                "transcript_confidence": context.transcript_confidence,
                "text_embedding": context.text_embedding,
                "clip_embedding": context.clip_embedding,
                "inference_version": context.inference_version
            }
            
            return ExtractorResult.success(features)
            
        except Exception as exc:
            logger.error(
                "remote_inference_extractor_failed",
                extra={"reel_id": context.reel_id, "error": str(exc)}
            )
            return ExtractorResult.failed(f"remote_inference_error: {exc}")
```

**Purpose**: Error handling and result formatting.

---

## Integration Patterns

### 1. Projection Engine Integration
```python
# In worker.py after DAG execution
compute_projections(context)
```

### 2. Remote Inference Integration
```python
# In RemoteInferenceExtractor.run()
result = await call_remote_inference(context, context.video_path)
```

### 3. Result Storage
```python
# Both systems store results in context.intermediate_outputs
context.intermediate_outputs["projections"] = ExtractorResult.success(projections)
```

---

## Error Scenarios and Recovery

### 1. Projection Engine Errors
- **Missing Features**: Graceful degradation with defaults
- **Invalid Values**: Clamping and validation
- **Division by Zero**: Protected against in normalization

### 2. Remote Inference Errors
- **Network Failures**: Automatic retries with exponential backoff
- **Service Unavailable**: Clear error messages and logging
- **Invalid Responses**: Structure validation before processing

### 3. Integration Failures
- **Context Missing**: Defensive checks throughout
- **Dependency Failures**: Proper error propagation
- **Resource Exhaustion**: Timeouts and cleanup

---

## Performance Considerations

### 1. Projection Engine
- **Computational Complexity**: O(1) - simple arithmetic
- **Memory Usage**: Minimal - only stores results
- **Bottlenecks**: None identified

### 2. Remote Inference
- **Network Latency**: Main performance factor
- **File Upload Size**: Can be significant for large videos
- **Service Capacity**: Limited by remote GPU availability

### 3. Optimization Opportunities
- **Batch Processing**: Multiple reels in single request
- **Caching**: Cache inference results for identical content
- **Compression**: Compress video uploads

---

This documentation provides complete understanding of the projection engine and remote inference systems. Every function, parameter, and line of logic is explained to ensure proper operation and prevent surprises in production.
