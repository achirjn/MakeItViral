import json
import time
from typing import List

from .base import BaseExtractor, ExtractorResult

from module2.logging_config import get_logger


logger = get_logger("extractor.llm_hook")


class LlmHookExtractor(BaseExtractor):

    @property
    def name(self) -> str:
        return "llm_hook"

    @property
    def dependencies(self) -> List[str]:
        return ["hook"]

    @property
    def is_critical(self) -> bool:
        return False

    @property
    def output_keys(self) -> List[str]:
        return [
            "llm_hook_score",
            "llm_hook_signals",
            "llm_hook_reasoning",
            "llm_hook_confidence",
        ]

    @property
    def requires_gpu(self) -> bool:
        return False

    async def run(self, context):

        # ---------- Gather inputs ----------
        metadata = context.metadata or {}
        caption = metadata.get("caption") or ""
        hashtags = " ".join(metadata.get("hashtags") or [])

        ocr_entry = context.intermediate_outputs.get("ocr", {})
        ocr_text = (ocr_entry.get("features") or {}).get("ocr_text", "")

        transcript_entry = context.intermediate_outputs.get("transcript", {})
        transcript_text = (transcript_entry.get("features") or {}).get("transcript", "")

        hook_entry = context.intermediate_outputs.get("hook", {})
        hook_features = hook_entry.get("features") or {}
        hook_signals = hook_features.get("hook_signals") or []

        # ---------- Lazy import LLM ----------
        try:
            from openai import OpenAI
        except Exception:
            return ExtractorResult.skipped("llm_not_available")

        client = OpenAI()

        # ---------- Prompt ----------
        system_prompt = (
            "You are a short-form video hook analyst. "
            "Evaluate whether the first 3 seconds create curiosity, emotional pull, or value promise. "
            "Return strict JSON only."
        )

        user_prompt = f"""
[CAPTION]
{caption}

[HASHTAGS]
{hashtags}

[OCR]
{ocr_text}

[TRANSCRIPT]
{transcript_text}

[HEURISTIC SIGNALS]
{hook_signals}
"""

        input_length = len(user_prompt)

        # ---------- Call LLM ----------
        logger.debug(
            "llm_call_started input_length=%d",
            input_length,
            extra={"reel_id": context.reel_id},
        )

        t0 = time.monotonic()
        try:
            response = client.responses.create(
                model="gpt-5-mini",
                temperature=0,
                max_output_tokens=300,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error(
                "llm_call_failed error=%s duration_s=%.3f",
                str(e)[:80],
                elapsed,
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.failed(f"llm_error: {str(e)}")

        elapsed = time.monotonic() - t0

        # ---------- Parse response ----------
        try:
            text = response.output_text
            data = json.loads(text)
        except Exception:
            logger.warning(
                "llm_invalid_json output_length=%d duration_s=%.3f",
                len(text) if text else 0,
                elapsed,
                extra={"reel_id": context.reel_id},
            )
            return ExtractorResult.failed("llm_invalid_json")

        output_length = len(text) if text else 0
        logger.debug(
            "llm_response_received output_length=%d duration_s=%.3f",
            output_length,
            elapsed,
            extra={"reel_id": context.reel_id},
        )

        # ---------- Validate ----------
        hook_score = float(data.get("hook_score", 0.0))
        signals = data.get("signals") or []
        reasoning = data.get("reasoning") or ""
        confidence = float(data.get("confidence", 0.0))

        # ---------- Clamp ----------
        hook_score = max(0.0, min(1.0, hook_score))
        confidence = max(0.0, min(1.0, confidence))

        # ---------- Return ----------
        return ExtractorResult.success(
            {
                "llm_hook_score": hook_score,
                "llm_hook_signals": signals,
                "llm_hook_reasoning": reasoning,
                "llm_hook_confidence": confidence,
            }
        )
