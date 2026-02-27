from __future__ import annotations

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

    @classmethod
    def create(cls, reel_id: str, metadata: Dict[str, Any] | None = None) -> "ExtractionContext":
        tmp = tempfile.mkdtemp(prefix=f"reel_{reel_id}_")
        return cls(
            reel_id=reel_id,
            temp_dir=tmp,
            metadata=metadata or {},
        )

    def temp_path(self) -> Path:
        return Path(self.temp_dir)

