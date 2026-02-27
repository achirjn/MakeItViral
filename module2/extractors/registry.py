from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Type

from module2.extractors.base import BaseExtractor


@dataclass
class ExtractorRegistry:
    """
    Minimal registry for loading and enumerating extractors by name.
    """

    _extractors: Dict[str, Type[BaseExtractor]] = field(default_factory=dict)

    def register(self, extractor_cls: Type[BaseExtractor]) -> None:
        instance = extractor_cls()
        name = instance.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Extractor instance must return a non-empty 'name'.")
        if name in self._extractors:
            raise ValueError(f"Extractor already registered: {name}")
        self._extractors[name] = extractor_cls

    def get(self, name: str) -> Type[BaseExtractor]:
        if name not in self._extractors:
            raise KeyError(f"Unknown extractor: {name}")
        return self._extractors[name]

    def all(self) -> List[BaseExtractor]:
        """
        Return instantiated extractor objects for DAG execution.
        """
        return [cls() for cls in self._extractors.values()]

    def register_many(self, extractor_classes: Iterable[Type[BaseExtractor]]) -> None:
        for cls in extractor_classes:
            self.register(cls)


def build_default_registry() -> ExtractorRegistry:
    """
    Convenience loader for the extractors implemented so far.
    """
    from module2.extractors.audio import AudioExtractor
    from module2.extractors.embedding import EmbeddingExtractor
    from module2.extractors.frame_sampler import FrameSamplerExtractor
    from module2.extractors.hook import HookExtractor
    from module2.extractors.llm_hook import LlmHookExtractor
    from module2.extractors.motion import MotionExtractor
    from module2.extractors.ocr import OcrExtractor
    from module2.extractors.transcript import TranscriptExtractor
    from module2.extractors.video_fetcher import VideoFetcherExtractor
    from module2.extractors.video_probe import VideoProbeExtractor

    reg = ExtractorRegistry()
    reg.register_many(
        [
            VideoFetcherExtractor,
            VideoProbeExtractor,
            FrameSamplerExtractor,
            MotionExtractor,
            OcrExtractor,
            AudioExtractor,
            TranscriptExtractor,
            HookExtractor,
            LlmHookExtractor,
            EmbeddingExtractor,
        ]
    )
    return reg
