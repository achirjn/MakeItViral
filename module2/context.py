from __future__ import annotations

from datetime import datetime
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ExtractionContext:
    reel_id: str

    # Ephemeral artifacts (must be cleaned up)
    temp_dir: str
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    sampled_frames: List[str] = field(default_factory=list)

    # Metadata snapshot + intermediate extractor outputs
    metadata: Dict[str, Any] = field(default_factory=dict)
    intermediate_outputs: Dict[str, Any] = field(default_factory=dict)
    model_versions: Dict[str, str] = field(default_factory=dict)

    # Shared remote inference results (populated by RemoteInferenceExtractor)
    transcript: Optional[str] = None
    transcript_confidence: Optional[float] = None
    text_embedding: Optional[List[float]] = None
    clip_embedding: Optional[List[float]] = None
    inference_version: Optional[str] = None

    @classmethod
    def create(cls, reel_id: str, metadata: Dict[str, Any] | None = None) -> "ExtractionContext":
        repo_root = Path(__file__).resolve().parents[1]
        base_dir = repo_root / "temp_downloads"
        base_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = base_dir / f"reel_{reel_id}_{timestamp}"
        tmp_dir = candidate

        counter = 1
        while tmp_dir.exists():
            counter += 1
            tmp_dir = base_dir / f"reel_{reel_id}_{timestamp}_{counter}"

        tmp_dir.mkdir(parents=True, exist_ok=False)
        tmp = str(tmp_dir)
        return cls(
            reel_id=reel_id,
            temp_dir=tmp,
            metadata=metadata or {},
        )

    def temp_path(self) -> Path:
        return Path(self.temp_dir)

