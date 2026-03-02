# Module 2 Context and Cleanup - Complete Line-by-Line Documentation

## Overview
The ExtractionContext and cleanup system manage temporary state and resources for each processing job. This ensures proper isolation between jobs and prevents resource leaks.

---

## Extraction Context

### File: `module2/context.py`

#### Imports and Dependencies

```python
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
```

**Purpose**:
- `os`: Operating system interface for file operations
- `tempfile`: Temporary file and directory creation
- `time`: Time-based operations for unique directory naming
- `dataclass`: For creating structured data containers
- `Path`: Object-oriented file system paths
- `typing`: Type hints for better code documentation

```python
from sqlalchemy.orm import Session
```

**Purpose**: SQLAlchemy Session for database operations.

```python
from module2.logging_config import get_logger
```

**Purpose**: Structured logging configuration.

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger instance.

#### ExtractionContext Dataclass

```python
@dataclass
class ExtractionContext:
    """Context object that holds all state for a single reel processing job."""
```

**Purpose**: Central data structure for job state management.

##### Core Fields

```python
    reel_id: str
```

**Purpose**: Unique identifier for the reel being processed. Used throughout logging and database operations.

```python
    temp_dir: Path
```

**Purpose**: Path to temporary directory where all files (video, audio, frames) are stored. Created per job for isolation.

```python
    video_path: Optional[str] = None
```

**Purpose**: Path to downloaded video file. Set by video_fetcher extractor.

```python
    audio_path: Optional[str] = None
```

**Purpose**: Path to extracted audio file. Set by audio extractor.

```python
    sampled_frames: List[str] = field(default_factory=list)
```

**Purpose**: List of paths to extracted frame files. Populated by frame_sampler extractor. `default_factory=list` ensures each instance gets its own list.

```python
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Purpose**: Copy of reel metadata from database (caption, hashtags, etc.). `default_factory=dict` ensures each instance gets its own dictionary.

##### Remote Inference Fields

```python
    transcript: Optional[str] = None
```

**Purpose**: Whisper transcription result from remote inference. Set by RemoteInferenceExtractor.

```python
    transcript_confidence: float = 0.0
```

**Purpose**: Confidence score for transcription. Range 0.0-1.0.

```python
    text_embedding: Optional[List[float]] = None
```

**Purpose**: MiniLM text embedding vector (384 dimensions). Set by RemoteInferenceExtractor.

```python
    clip_embedding: Optional[List[float]] = None
```

**Purpose**: CLIP visual embedding vector (768 dimensions). Set by RemoteInferenceExtractor.

```python
    inference_version: Optional[str] = None
```

**Purpose**: Version identifier for remote inference results. Used for cache invalidation.

##### Processing State Fields

```python
    intermediate_outputs: Dict[str, "ExtractorResult"] = field(default_factory=dict)
```

**Purpose**: Results from all executed extractors. Key is extractor name, value is ExtractorResult. Used for dependency resolution and projection computation.

```python
    model_versions: Dict[str, str] = field(default_factory=dict)
```

**Purpose**: Version information for models used (e.g., embedding model version). Stored with features for reproducibility.

#### Class Methods

```python
    @classmethod
    def create(cls, reel_id: str, reel_obj: Any) -> "ExtractionContext":
        """Create a new ExtractionContext with temporary directory and metadata."""
```

**Purpose**: Factory method to create properly initialized context.

**Parameters**:
- `reel_id`: Unique identifier string
- `reel_obj`: Database reel object containing metadata

**Returns**: Fully initialized ExtractionContext

```python
        # Create unique temporary directory with timestamp
        timestamp = int(time.time())
        temp_dir_name = f"reel_{reel_id}_{timestamp}"
        temp_dir = Path(tempfile.gettempdir()) / temp_dir_name
        temp_dir.mkdir(parents=True, exist_ok=True)
```

**Purpose**: Create timestamped temporary directory:
- Uses current Unix timestamp for uniqueness
- Creates in system temp directory
- `parents=True` creates parent directories if needed
- `exist_ok=True` prevents race conditions

```python
        logger.debug(
            "temp_dir_created",
            extra={
                "reel_id": reel_id,
                "temp_dir": str(temp_dir)
            }
        )
```

**Purpose**: Log directory creation for debugging.

```python
        # Extract metadata from reel object
        metadata = {}
        if hasattr(reel_obj, 'caption'):
            metadata['caption'] = reel_obj.caption
        if hasattr(reel_obj, 'hashtags'):
            metadata['hashtags'] = reel_obj.hashtags
        if hasattr(reel_obj, 'video_url'):
            metadata['video_url'] = reel_obj.video_url
        if hasattr(reel_obj, 'thumbnail_url'):
            metadata['thumbnail_url'] = reel_obj.thumbnail_url
        if hasattr(reel_obj, 'views'):
            metadata['views'] = reel_obj.views
        if hasattr(reel_obj, 'likes'):
            metadata['likes'] = reel_obj.likes
        if hasattr(reel_obj, 'comments'):
            metadata['comments'] = reel_obj.comments
        if hasattr(reel_obj, 'creator_id'):
            metadata['creator_id'] = str(reel_obj.creator_id)
        if hasattr(reel_obj, 'publish_time'):
            metadata['publish_time'] = reel_obj.publish_time.isoformat() if reel_obj.publish_time else None
```

**Purpose**: Extract relevant metadata from database object:
- Uses `hasattr()` to handle different object types
- Converts complex types to simple formats
- Ensures all metadata is JSON-serializable
- Handles None values gracefully

```python
        # Create context instance
        return cls(
            reel_id=reel_id,
            temp_dir=temp_dir,
            metadata=metadata
        )
```

**Purpose**: Return initialized context instance.

---

## Cleanup System

### File: `module2/cleanup.py`

#### Imports and Dependencies

```python
import os
import shutil
from pathlib import Path
from typing import List

from module2.context import ExtractionContext
from module2.logging_config import get_logger
```

**Purpose**:
- `os`: File system operations
- `shutil`: High-level file operations (directory removal)
- `Path`: Object-oriented file system paths
- `List`: Type hint for collections
- `ExtractionContext`: Type being cleaned up
- `get_logger`: Structured logging

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger.

#### Main Cleanup Function

```python
def cleanup_context(context: ExtractionContext) -> None:
    """Clean up all temporary files and directories for a processing job."""
```

**Purpose**: Main cleanup function that removes all temporary resources.

**Parameters**:
- `context`: ExtractionContext containing paths to clean

**Returns**: None

```python
    if not context:
        return
```

**Purpose**: Early return if context is None (defensive programming).

```python
    reel_id = context.reel_id
    temp_dir = context.temp_dir
```

**Purpose**: Extract commonly used values for logging.

```python
    logger.debug(
        "cleanup_started",
        extra={"reel_id": reel_id}
    )
```

**Purpose**: Log cleanup start for observability.

```python
    # Cleanup counters for logging
    frames_removed = 0
    audio_removed = False
    video_removed = False
    temp_dir_removed = False
```

**Purpose**: Initialize counters for cleanup reporting.

##### Frame Cleanup

```python
    # Remove all sampled frames
    if context.sampled_frames:
        for frame_path in context.sampled_frames:
            try:
                frame_file = Path(frame_path)
                if frame_file.exists():
                    frame_file.unlink()
                    frames_removed += 1
            except Exception as exc:
                logger.warning(
                    "frame_cleanup_failed",
                    extra={
                        "reel_id": reel_id,
                        "frame_path": frame_path,
                        "error": str(exc)
                    }
                )
```

**Purpose**: Remove all frame files:
- Iterates through `context.sampled_frames` list
- Uses Path.unlink() for file deletion
- Counts successful removals
- Logs failures but continues cleanup
- Defensive: checks file exists before deletion

##### Audio File Cleanup

```python
    # Remove audio file if it exists
    if context.audio_path:
        try:
            audio_file = Path(context.audio_path)
            if audio_file.exists():
                audio_file.unlink()
                audio_removed = True
        except Exception as exc:
            logger.warning(
                "audio_cleanup_failed",
                extra={
                    "reel_id": reel_id,
                    "audio_path": context.audio_path,
                    "error": str(exc)
                }
            )
```

**Purpose**: Remove extracted audio file:
- Checks if audio_path is set
- Uses Path.unlink() for deletion
- Logs success/failure separately
- Continues cleanup even if audio removal fails

##### Video File Cleanup

```python
    # Remove video file if it exists
    if context.video_path:
        try:
            video_file = Path(context.video_path)
            if video_file.exists():
                video_file.unlink()
                video_removed = True
        except Exception as exc:
            logger.warning(
                "video_cleanup_failed",
                extra={
                    "reel_id": reel_id,
                    "video_path": context.video_path,
                    "error": str(exc)
                }
            )
```

**Purpose**: Remove downloaded video file:
- Similar pattern to audio cleanup
- Critical cleanup to free disk space
- Video files are typically largest

##### Temporary Directory Cleanup

```python
    # Remove temporary directory and any remaining contents
    if temp_dir and temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
            temp_dir_removed = True
        except Exception as exc:
            logger.warning(
                "temp_dir_cleanup_failed",
                extra={
                    "reel_id": reel_id,
                    "temp_dir": str(temp_dir),
                    "error": str(exc)
                }
            )
```

**Purpose**: Remove entire temporary directory:
- Uses `shutil.rmtree()` for recursive directory removal
- Removes any files missed by individual cleanup
- Most important cleanup step
- Logs failure but doesn't raise exception

##### Cleanup Summary Logging

```python
    # Log cleanup summary
    logger.debug(
        "cleanup_completed",
        extra={
            "reel_id": reel_id,
            "frames_removed": frames_removed,
            "audio_removed": audio_removed,
            "video_removed": video_removed,
            "temp_dir_removed": temp_dir_removed
        }
    )
```

**Purpose**: Log detailed cleanup summary:
- Shows what was successfully cleaned
- Helps identify cleanup issues
- Useful for disk space monitoring

---

## Context Usage Patterns

### 1. Creation and Initialization
```python
# In worker.py
context = ExtractionContext.create(reel_id, reel)
```

### 2. Path Management
```python
# In video_fetcher.py
context.video_path = str(downloaded_path)

# In frame_sampler.py
context.sampled_frames.append(str(frame_path))
```

### 3. Result Storage
```python
# In extractors
context.intermediate_outputs[extractor.name] = result
```

### 4. Metadata Access
```python
# In extractors
caption = context.metadata.get("caption", "")
hashtags = context.metadata.get("hashtags", [])
```

### 5. Remote Inference Results
```python
# In RemoteInferenceExtractor
context.transcript = result["transcript"]
context.text_embedding = result["text_embedding"]
context.clip_embedding = result["clip_embedding"]
```

---

## Cleanup Integration Points

### 1. Worker Integration
```python
# In worker.py finally block
finally:
    if context:
        cleanup_context(context)
```

### 2. Error Handling
- Cleanup runs regardless of success/failure
- Individual cleanup failures don't stop overall cleanup
- All cleanup operations are logged

### 3. Resource Management
- Prevents disk space leaks
- Ensures file handles are released
- Maintains isolation between jobs

---

## Error Scenarios and Recovery

### 1. Missing Files
- **Scenario**: File path exists but file doesn't
- **Recovery**: Check exists() before deletion
- **Logging**: Warning with file path and error

### 2. Permission Errors
- **Scenario**: Insufficient permissions to delete
- **Recovery**: Log warning, continue cleanup
- **Impact**: May leave some files behind

### 3. Directory Not Empty
- **Scenario**: rmtree fails due to locked files
- **Recovery**: Log warning, manual cleanup may be needed
- **Monitoring**: Watch temp directory size

### 4. Context is None
- **Scenario**: Cleanup called with None context
- **Recovery**: Early return, no cleanup needed
- **Prevention**: Defensive programming

---

## Performance Considerations

### 1. Disk I/O
- Cleanup involves many file system operations
- Consider async cleanup for large frame counts
- Monitor disk space during cleanup

### 2. Error Handling Overhead
- Try/catch blocks for each file operation
- Logging overhead for cleanup failures
- Balance between thoroughness and performance

### 3. Memory Usage
- Context holds lists of file paths
- Large frame counts consume memory
- Consider streaming cleanup for very large jobs

---

## Security Considerations

### 1. Path Traversal
- All paths are validated before use
- Temporary directory creation is controlled
- No user-controlled paths in cleanup

### 2. File Permissions
- Cleanup respects file permissions
- No escalation of privileges
- Safe deletion of temporary files

### 3. Information Disclosure
- Log messages don't contain file contents
- Only paths and counts are logged
- No sensitive data in cleanup logs

---

## Monitoring and Debugging

### 1. Cleanup Metrics
- Track frames removed per job
- Monitor temporary directory size
- Alert on cleanup failures

### 2. Debug Logging
- Enable DEBUG level for detailed cleanup info
- Check cleanup counters in logs
- Verify temp directory is empty after cleanup

### 3. Health Checks
- Periodic temp directory cleanup
- Monitor disk space usage
- Check for orphaned files

---

This documentation provides complete understanding of the context and cleanup systems. Every function, parameter, and line of logic is explained to ensure proper operation and prevent resource leaks in production.
