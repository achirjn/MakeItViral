# Module 2 Extractors - Complete Line-by-Line Documentation

## Overview
Extractors are the core processing units in Module 2. Each extractor performs a specific task (video download, OCR, transcription, etc.) and follows a strict interface. This document explains every extractor in detail.

---

## Base Extractor Framework

### File: `module2/extractors/base.py`

#### Imports and Dependencies

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
```

**Purpose**: 
- `ABC`, `abstractmethod`: For creating abstract base classes
- `dataclass`: For creating immutable result objects
- `typing`: Type hints for better code documentation

#### ExtractorResult Dataclass

```python
@dataclass(frozen=True)
class ExtractorResult:
    """Immutable result object returned by all extractors."""
    status: str  # "success", "failed", "skipped"
    features: Optional[Dict[str, Any]]  # Feature dictionary
    error: Optional[str] = None  # Error message if failed
```

**Purpose**: Standardized result format for all extractors.

**Fields**:
- `status`: String indicating execution result
- `features`: Dictionary of extracted features (key-value pairs)
- `error`: Optional error message for failed/skipped extractors

**Class Methods**:

```python
    @classmethod
    def success(cls, features: Dict[str, Any]) -> "ExtractorResult":
        """Create a successful result."""
        return cls(status="success", features=features)
```

**Purpose**: Factory method for successful results.
**Parameters**: `features` - Dictionary of extracted features
**Returns**: ExtractorResult with status="success"

```python
    @classmethod
    def failed(cls, error: str) -> "ExtractorResult":
        """Create a failed result."""
        return cls(status="failed", features=None, error=error)
```

**Purpose**: Factory method for failed results.
**Parameters**: `error` - Error message describing failure
**Returns**: ExtractorResult with status="failed"

```python
    @classmethod
    def skipped(cls, reason: str) -> "ExtractorResult":
        """Create a skipped result."""
        return cls(status="skipped", features=None, error=reason)
```

**Purpose**: Factory method for skipped results.
**Parameters**: `reason` - Reason why extractor was skipped
**Returns**: ExtractorResult with status="skipped"

#### BaseExtractor Abstract Class

```python
class BaseExtractor(ABC):
    """Abstract base class for all extractors."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this extractor."""
        pass
```

**Purpose**: Abstract property for unique extractor identification.
**Returns**: String name used in DAG and logging

```python
    @property
    @abstractmethod
    def dependencies(self) -> List[str]:
        """List of extractor names this extractor depends on."""
        pass
```

**Purpose**: Abstract property for dependency declaration.
**Returns**: List of extractor names that must complete successfully before this one runs

```python
    @property
    @abstractmethod
    def output_keys(self) -> List[str]:
        """List of feature keys this extractor produces."""
        pass
```

**Purpose**: Abstract property for output specification.
**Returns**: List of feature keys that will be in the features dictionary

```python
    @property
    def is_critical(self) -> bool:
        """Whether failure of this extractor should abort the pipeline."""
        return False
```

**Purpose**: Default implementation - extractors are non-critical unless overridden.
**Returns**: Boolean indicating if failure should abort entire job

```python
    @property
    def requires_gpu(self) -> bool:
        """Whether this extractor requires GPU resources."""
        return False
```

**Purpose**: Default implementation - extractors don't require GPU unless overridden.
**Returns**: Boolean for future GPU scheduling

```python
    @property
    def produces(self) -> set[str]:
        """Set of logical feature names this extractor produces."""
        return set()
```

**Purpose**: Default implementation for feature production tracking.
**Returns**: Set of feature names for planner dependency resolution

```python
    @property
    def requires(self) -> set[str]:
        """Set of logical features this extractor requires."""
        return set()
```

**Purpose**: Default implementation for feature requirements.
**Returns**: Set of required feature names for planner

```python
    @property
    def optional_requires(self) -> set[str]:
        """Set of optional features this extractor can use if available."""
        return set()
```

**Purpose**: Default implementation for optional feature requirements.
**Returns**: Set of optional feature names

```python
    @property
    def heavy(self) -> bool:
        """Whether this extractor is computationally expensive."""
        return False
```

**Purpose**: Default implementation for cost classification.
**Returns**: Boolean indicating if extractor is resource-intensive

```python
    @abstractmethod
    async def run(self, context: "ExtractionContext") -> ExtractorResult:
        """Run the extractor and return results."""
        pass
```

**Purpose**: Abstract method for extractor execution.
**Parameters**: `context` - ExtractionContext containing job state and intermediate results
**Returns**: ExtractorResult with status, features, and optional error

---

## Individual Extractor Implementations

### 1. Video Fetcher Extractor

#### File: `module2/extractors/video_fetcher.py`

```python
import asyncio
import os
import tempfile
from pathlib import Path
from typing import List

import yt_dlp
from sqlalchemy.orm import Session

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger
```

**Purpose**: Download Instagram reels using yt-dlp with authentication cookies.

```python
logger = get_logger(__name__)
```

**Purpose**: Module-level logger.

```python
class VideoFetcherExtractor(BaseExtractor):
    """Downloads Instagram reels using yt-dlp with authentication."""
    
    @property
    def name(self) -> str:
        return "video_fetcher"
```

**Purpose**: Unique identifier for DAG resolution.

```python
    @property
    def dependencies(self) -> List[str]:
        return []  # No dependencies - runs first
```

**Purpose**: No dependencies - can run immediately.

```python
    @property
    def output_keys(self) -> List[str]:
        return ["video_path"]  # Path to downloaded video file
```

**Purpose**: Specifies what features this extractor produces.

```python
    @property
    def is_critical(self) -> bool:
        return True  # Pipeline cannot continue without video
```

**Purpose**: Critical extractor - failure aborts the job.

```python
    async def run(self, context: ExtractionContext) -> ExtractorResult:
        """Download video using yt-dlp with Instagram authentication."""
```

**Purpose**: Main execution method.

```python
        try:
            # Get video URL from metadata
            video_url = context.metadata.get("video_url")
            if not video_url:
                return ExtractorResult.failed("missing_video_url")
```

**Purpose**: Validate input - video URL must be present in metadata.

```python
            # Create cookie file from auth state
            cookie_file = await self._create_cookie_file(context)
            if not cookie_file:
                return ExtractorResult.failed("failed_to_create_cookies")
```

**Purpose**: Create Netscape cookie file from Playwright authentication state.

```python
            # Configure yt-dlp options
            ydl_opts = {
                "format": "best[height<=720][ext=mp4]/best[ext=mp4]/best",
                "outtmpl": str(context.temp_dir / "video.%(ext)s"),
                "cookiefile": cookie_file,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
            }
```

**Purpose**: yt-dlp configuration:
- Format: Best quality up to 720p, MP4 preferred
- Output template: Save to temp directory
- Cookie file: For authentication
- No playlist: Single video only
- Quiet mode: Reduce output noise

```python
            # Run yt-dlp in thread to avoid blocking event loop
            logger.debug("yt_dlp_invoked", extra={"reel_id": context.reel_id})
            
            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=True)
                    return info
            
            info = await asyncio.to_thread(download)
```

**Purpose**: Run yt-dlp in separate thread to avoid blocking async event loop.

```python
            # Find downloaded file
            video_files = list(context.temp_dir.glob("video.*"))
            if not video_files:
                return ExtractorResult.failed("no_video_file_found")
            
            video_path = video_files[0]
            context.video_path = str(video_path)
```

**Purpose**: Locate downloaded file and store path in context.

```python
            logger.info(
                "video_downloaded",
                extra={
                    "reel_id": context.reel_id,
                    "file_size": video_path.stat().st_size,
                    "duration": info.get("duration")
                }
            )
```

**Purpose**: Log successful download with metadata.

```python
            return ExtractorResult.success({"video_path": context.video_path})
            
        except Exception as exc:
            logger.error(
                "yt_dlp_failure",
                extra={"reel_id": context.reel_id, "error": str(exc)}
            )
            return ExtractorResult.failed(f"yt_dlp_error: {exc}")
```

**Purpose**: Error handling with logging.

```python
        finally:
            # Clean up cookie file
            if 'cookie_file' in locals() and cookie_file and os.path.exists(cookie_file):
                os.unlink(cookie_file)
```

**Purpose**: Security cleanup - remove temporary cookie file.

```python
    async def _create_cookie_file(self, context: ExtractionContext) -> str:
        """Create Netscape cookie file from Playwright auth state."""
```

**Purpose**: Helper method to convert Playwright cookies to yt-dlp format.

```python
        try:
            # Path to Playwright auth state
            auth_state_path = Path("discovery/auth_state/storage_state.json")
            if not auth_state_path.exists():
                logger.warning(
                    "auth_state_missing",
                    extra={"reel_id": context.reel_id}
                )
                return ""
```

**Purpose**: Check for authentication state file.

```python
            # Load auth state
            import json
            with open(auth_state_path, "r") as f:
                auth_state = json.load(f)
```

**Purpose**: Load Playwright authentication state.

```python
            # Create temporary cookie file
            cookie_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt")
            cookie_file.write("# Netscape HTTP Cookie File\n")
            cookie_file.write("# This is a generated file! Do not edit.\n\n")
```

**Purpose**: Create temporary file with Netscape header.

```python
            # Convert Playwright cookies to Netscape format
            for cookie in auth_state.get("cookies", []):
                if cookie.get("domain", "").endswith("instagram.com"):
                    line = f"{cookie.get('domain', '')}\t"
                    line += f"{'TRUE' if cookie.get('domain', '').startswith('.') else 'FALSE'}\t"
                    line += f"{cookie.get('path', '/')}\t"
                    line += f"{'TRUE' if cookie.get('secure', False) else 'FALSE'}\t"
                    line += f"{cookie.get('expires', 0) or 0}\t"
                    line += f"{cookie.get('name', '')}\t"
                    line += f"{cookie.get('value', '')}\n"
                    cookie_file.write(line)
```

**Purpose**: Convert each cookie to Netscape format:
- Domain
- Flag for subdomains
- Path
- Secure flag
- Expiration timestamp
- Name
- Value

```python
            cookie_file.close()
            return cookie_file.name
            
        except Exception as exc:
            logger.error(
                "cookie_creation_failed",
                extra={"reel_id": context.reel_id, "error": str(exc)}
            )
            return ""
```

**Purpose**: Error handling for cookie creation.

---

### 2. Video Probe Extractor

#### File: `module2/extractors/video_probe.py`

```python
import asyncio
import json
from typing import List

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger

logger = get_logger(__name__)
```

**Purpose**: Extract video metadata using ffprobe.

```python
class VideoProbeExtractor(BaseExtractor):
    """Extract video metadata using ffprobe."""
    
    @property
    def name(self) -> str:
        return "video_probe"
```

**Purpose**: Unique identifier.

```python
    @property
    def dependencies(self) -> List[str]:
        return ["video_fetcher"]  # Requires downloaded video
```

**Purpose**: Depends on video being downloaded first.

```python
    @property
    def output_keys(self) -> List[str]:
        return ["duration", "fps", "resolution", "width", "height"]
```

**Purpose**: Metadata fields this extractor produces.

```python
    @property
    def is_critical(self) -> bool:
        return True  # Critical for downstream processing
```

**Purpose**: Critical - other extractors need this metadata.

```python
    async def run(self, context: ExtractionContext) -> ExtractorResult:
        """Extract video metadata using ffprobe."""
```

**Purpose**: Main execution method.

```python
        try:
            # Validate video path exists
            if not context.video_path:
                return ExtractorResult.failed("missing_video_path")
            
            video_path = Path(context.video_path)
            if not video_path.exists():
                return ExtractorResult.failed("video_file_not_found")
```

**Purpose**: Input validation.

```python
            # Run ffprobe command
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(video_path)
            ]
```

**Purpose**: ffprobe command configuration:
- Quiet mode: suppress noise
- JSON output: easy parsing
- Show format: container info
- Show streams: audio/video track info

```python
            logger.debug(
                "ffprobe_invoked",
                extra={"reel_id": context.reel_id}
            )
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
```

**Purpose**: Execute ffprobe asynchronously and capture output.

```python
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "unknown error"
                return ExtractorResult.failed(f"ffprobe_error: {error_msg}")
```

**Purpose**: Check for execution errors.

```python
            # Parse JSON output
            probe_data = json.loads(stdout.decode())
            
            # Extract format information
            format_info = probe_data.get("format", {})
            duration_str = format_info.get("duration")
            
            # Convert duration to float
            duration = float(duration_str) if duration_str else 0.0
```

**Purpose**: Parse duration from format information.

```python
            # Find video stream
            video_stream = None
            for stream in probe_data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break
```

**Purpose**: Locate the video stream for metadata extraction.

```python
            if not video_stream:
                return ExtractorResult.failed("no_video_stream_found")
```

**Purpose**: Validate video stream exists.

```python
            # Extract video dimensions
            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))
            resolution = f"{width}x{height}"
```

**Purpose**: Extract resolution information.

```python
            # Extract FPS (handle various formats)
            fps_str = video_stream.get("r_frame_rate", "0/1")
            if "/" in fps_str:
                numerator, denominator = fps_str.split("/")
                fps = float(numerator) / float(denominator) if float(denominator) != 0 else 0.0
            else:
                fps = float(fps_str)
```

**Purpose**: Parse FPS which can be in fraction format (e.g., "30000/1001").

```python
            features = {
                "duration": duration,
                "fps": fps,
                "resolution": resolution,
                "width": width,
                "height": height
            }
```

**Purpose**: Assemble feature dictionary.

```python
            logger.debug(
                "video_probed",
                extra={
                    "reel_id": context.reel_id,
                    "duration": duration,
                    "fps": fps,
                    "resolution": resolution
                }
            )
            
            return ExtractorResult.success(features)
            
        except Exception as exc:
            logger.error(
                "ffprobe_failure",
                extra={"reel_id": context.reel_id, "error": str(exc)}
            )
            return ExtractorResult.failed(f"ffprobe_error: {exc}")
```

**Purpose**: Error handling and logging.

---

### 3. Frame Sampler Extractor

#### File: `module2/extractors/frame_sampler.py`

```python
import asyncio
from pathlib import Path
from typing import List

from module2.context import ExtractionContext
from module2.extractors.base import BaseExtractor, ExtractorResult
from module2.logging_config import get_logger

logger = get_logger(__name__)
```

**Purpose**: Extract frames from video for analysis.

```python
class FrameSamplerExtractor(BaseExtractor):
    """Extract frames from video at 1 fps using ffmpeg."""
    
    @property
    def name(self) -> str:
        return "frame_sampler"
```

**Purpose**: Unique identifier.

```python
    @property
    def dependencies(self) -> List[str]:
        return ["video_probe"]  # Requires video metadata
```

**Purpose**: Depends on video probe for duration information.

```python
    @property
    def output_keys(self) -> List[str]:
        return ["frame_count", "frame_paths"]  # Number and paths of extracted frames
```

**Purpose**: Output specification.

```python
    @property
    def is_critical(self) -> bool:
        return True  # Critical for motion and OCR analysis
```

**Purpose**: Critical for downstream visual analysis.

```python
    async def run(self, context: ExtractionContext) -> ExtractorResult:
        """Extract frames from video at 1 fps using ffmpeg."""
```

**Purpose**: Main execution method.

```python
        try:
            # Validate video path
            if not context.video_path:
                return ExtractorResult.failed("missing_video_path")
            
            video_path = Path(context.video_path)
            if not video_path.exists():
                return ExtractorResult.failed("video_file_not_found")
```

**Purpose**: Input validation.

```python
            # Get video duration from probe results
            probe_result = context.intermediate_outputs.get("video_probe")
            if not probe_result or probe_result.status != "success":
                return ExtractorResult.failed("video_probe_failed")
            
            duration = probe_result.features.get("duration", 0.0)
            if duration <= 0:
                return ExtractorResult.failed("invalid_duration")
```

**Purpose**: Get duration from video probe results.

```python
            # Calculate frame count (1 fps, max 60 frames)
            frame_count = min(int(duration) + 1, 60)
            
            # Create frames directory
            frames_dir = context.temp_dir / "frames"
            frames_dir.mkdir(exist_ok=True)
```

**Purpose**: Calculate frame count and create output directory.

```python
            # Configure ffmpeg command
            output_pattern = frames_dir / "frame_%05d.jpg"
            cmd = [
                "ffmpeg",
                "-i", str(video_path),
                "-vf", f"fps=1,scale=640:-1",  # 1 fps, max width 640
                "-frames:v", str(frame_count),
                "-y",  # Overwrite output files
                str(output_pattern)
            ]
```

**Purpose**: ffmpeg configuration:
- Input: video file
- Video filter: 1 fps, scale to 640px width
- Frame limit: calculated frame count
- Overwrite: replace existing files

```python
            logger.debug(
                "ffmpeg_sampling_started",
                extra={
                    "reel_id": context.reel_id,
                    "frame_count": frame_count
                }
            )
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
```

**Purpose**: Execute ffmpeg asynchronously.

```python
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "unknown error"
                return ExtractorResult.failed(f"ffmpeg_error: {error_msg}")
```

**Purpose**: Check for ffmpeg errors.

```python
            # Collect frame paths
            frame_paths = []
            for i in range(1, frame_count + 1):
                frame_path = frames_dir / f"frame_{i:05d}.jpg"
                if frame_path.exists():
                    frame_paths.append(str(frame_path))
                    context.sampled_frames.append(str(frame_path))  # Add to context for cleanup
```

**Purpose**: Collect existing frame paths and add to context for cleanup.

```python
            if not frame_paths:
                return ExtractorResult.failed("no_frames_extracted")
```

**Purpose**: Validate that frames were actually extracted.

```python
            features = {
                "frame_count": len(frame_paths),
                "frame_paths": frame_paths
            }
```

**Purpose**: Assemble feature dictionary.

```python
            logger.debug(
                "frames_extracted",
                extra={
                    "reel_id": context.reel_id,
                    "extracted_count": len(frame_paths),
                    "requested_count": frame_count
                }
            )
            
            return ExtractorResult.success(features)
            
        except Exception as exc:
            logger.error(
                "ffmpeg_sampling_failure",
                extra={"reel_id": context.reel_id, "error": str(exc)}
            )
            return ExtractorResult.failed(f"ffmpeg_error: {exc}")
```

**Purpose**: Error handling and logging.

---

## Common Extractor Patterns

### 1. Input Validation
All extractors follow this pattern:
```python
if not context.video_path:
    return ExtractorResult.failed("missing_video_path")
```

### 2. Dependency Checking
Extractors verify upstream results:
```python
dep_result = context.intermediate_outputs.get("dependency_name")
if not dep_result or dep_result.status != "success":
    return ExtractorResult.failed("dependency_failed")
```

### 3. Async Execution
I/O operations use asyncio to avoid blocking:
```python
process = await asyncio.create_subprocess_exec(*cmd, ...)
stdout, stderr = await process.communicate()
```

### 4. Error Handling
Consistent error logging and result format:
```python
except Exception as exc:
    logger.error("operation_failed", extra={"reel_id": context.reel_id, "error": str(exc)})
    return ExtractorResult.failed(f"operation_error: {exc}")
```

### 5. Feature Dictionary
Standardized feature output:
```python
features = {"key1": value1, "key2": value2}
return ExtractorResult.success(features)
```

---

## Extractor Registry and Dependencies

### Registration Process
1. Each extractor inherits from `BaseExtractor`
2. Implements required abstract properties and methods
3. Registered in `module2/extractors/registry.py`
4. Dependencies declared in `dependencies` property
5. DAG executor resolves execution order

### Dependency Resolution
- Circular dependencies cause DAG stall errors
- Failed dependencies cause downstream extractors to be skipped
- Critical failures abort entire job
- Non-critical failures are isolated

### Performance Considerations
- Parallel execution of independent extractors
- Async I/O for external processes
- Memory management through context cleanup
- Resource-intensive operations marked as `heavy=True`

---

This documentation provides complete understanding of each extractor's purpose, implementation, and integration patterns. Every line of code is explained to prevent surprises in production environments.
