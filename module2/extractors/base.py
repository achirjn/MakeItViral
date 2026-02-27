from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from module2.context import ExtractionContext
from module2.logging_config import get_logger


_ext_logger = get_logger("extractor")


@dataclass(frozen=True)
class ExtractorResult:
    """
    Locked result schema:
      { status: success|failed|skipped, features: dict, error?: str }
    """

    status: str
    features: Dict[str, Any]
    error: Optional[str] = None

    @staticmethod
    def success(features: Dict[str, Any]) -> "ExtractorResult":
        return ExtractorResult(status="success", features=features, error=None)

    @staticmethod
    def failed(error: str) -> "ExtractorResult":
        return ExtractorResult(status="failed", features={}, error=error)

    @staticmethod
    def skipped(reason: str) -> "ExtractorResult":
        return ExtractorResult(status="skipped", features={}, error=reason)


class BaseExtractor(ABC):
    """
    Locked extractor interface contract.

    Extractors must not write to DB.
    The run_with_logging wrapper is the standard entry point used by the DAG
    executor. It transparently adds timing and structured log events around
    the concrete run() implementation without altering the extractor contract.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dependencies(self) -> List[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def output_keys(self) -> List[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_critical(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def requires_gpu(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def run(self, context: ExtractionContext) -> ExtractorResult:
        raise NotImplementedError

    async def run_with_logging(self, context: ExtractionContext) -> ExtractorResult:
        """Auto-logging wrapper. Logs start, result, and duration."""
        rid = context.reel_id
        ext_name = self.name

        _ext_logger.debug(
            "extractor_start extractor=%s",
            ext_name,
            extra={"reel_id": rid},
        )

        t0 = time.monotonic()
        result = await self.run(context)
        elapsed = time.monotonic() - t0

        if result.status == "success":
            feature_keys = sorted(result.features.keys()) if result.features else []
            _ext_logger.debug(
                "extractor_success extractor=%s feature_keys=%s duration_s=%.3f",
                ext_name,
                feature_keys,
                elapsed,
                extra={"reel_id": rid},
            )
        elif result.status == "skipped":
            _ext_logger.debug(
                "extractor_skipped extractor=%s reason=%s duration_s=%.3f",
                ext_name,
                result.error,
                elapsed,
                extra={"reel_id": rid},
            )
        elif result.status == "failed":
            _ext_logger.warning(
                "extractor_failed extractor=%s error=%s duration_s=%.3f",
                ext_name,
                result.error,
                elapsed,
                extra={"reel_id": rid},
            )

        return result
