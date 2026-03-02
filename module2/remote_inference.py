"""
Module 2 — Remote Inference Client
------------------------------------
Single HTTP call per reel to Colab GPU server.
Caches result in context.intermediate_outputs["_remote_inference"].
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from module2.config import (
    INFERENCE_VERSION,
    REMOTE_INFERENCE_URL,
    REMOTE_TIMEOUT_SECONDS,
)
from module2.logging_config import get_logger


logger = get_logger("remote_inference")

# Context key for cached result
_REMOTE_KEY = "_remote_inference"


async def call_remote_inference(
    context: Any,
    video_url: str,
) -> dict | None:
    """
    Call the Colab inference server for a single reel.

    - Caches result in context.intermediate_outputs["_remote_inference"]
    - Guard: if result already cached, returns it without calling again.
    - On failure: returns None, logs error.

    Returns the parsed response dict or None.
    """
    # Guard: do NOT call again if already cached
    existing = context.intermediate_outputs.get(_REMOTE_KEY)
    if existing is not None:
        logger.debug(
            "remote_inference_cached_hit",
            extra={"reel_id": context.reel_id},
        )
        return existing if isinstance(existing, dict) else None

    reel_id = context.reel_id

    logger.info(
        "remote_request_started url=%s",
        REMOTE_INFERENCE_URL,
        extra={"reel_id": reel_id},
    )

    t0 = time.monotonic()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REMOTE_TIMEOUT_SECONDS, connect=30.0)
        ) as client:
            local_video_path = getattr(context, "video_path", None)
            if isinstance(local_video_path, str) and os.path.isfile(local_video_path):
                with open(local_video_path, "rb") as f:
                    resp = await client.post(
                        REMOTE_INFERENCE_URL,
                        data={
                            "reel_id": reel_id,
                        },
                        files={
                            "file": ("video.mp4", f, "video/mp4"),
                        },
                    )
            else:
                resp = await client.post(
                    REMOTE_INFERENCE_URL,
                    json={
                        "reel_id": reel_id,
                        "video_url": video_url,
                    },
                )

        elapsed = round(time.monotonic() - t0, 2)

        if resp.status_code != 200:
            error_detail = resp.text[:200]
            logger.error(
                "remote_request_failed status=%d reason=%s duration=%.2f",
                resp.status_code,
                error_detail,
                elapsed,
                extra={"reel_id": reel_id},
            )
            context.intermediate_outputs[_REMOTE_KEY] = {
                "status": "failed",
                "failure_type": "http_error",
                "error": f"HTTP {resp.status_code}: {error_detail}",
            }
            return None

        data = resp.json()

        # Basic JSON validation first
        if not isinstance(data, dict):
            raise ValueError("invalid_json_object")

        # Strict schema validation
        required_keys = [
            "transcript",
            "transcript_confidence",
            "text_embedding",
            "text_dim",
            "clip_embedding",
            "clip_dim",
            "inference_version",
        ]

        for key in required_keys:
            if key not in data:
                raise ValueError(f"missing_key:{key}")

        # Strict dimension validation
        if data["text_dim"] != 384:
            raise ValueError("invalid_text_dim")

        if data["clip_dim"] != 768:
            raise ValueError("invalid_clip_dim")

        if not isinstance(data["text_embedding"], list) or len(data["text_embedding"]) != 384:
            raise ValueError("invalid_text_embedding_vector")

        if not isinstance(data["clip_embedding"], list) or len(data["clip_embedding"]) != 768:
            raise ValueError("invalid_clip_embedding_vector")

        if not all(isinstance(x, (int, float)) for x in data["text_embedding"]):
            raise ValueError("text_embedding_non_numeric")

        if not all(isinstance(x, (int, float)) for x in data["clip_embedding"]):
            raise ValueError("clip_embedding_non_numeric")

        # Store inference version in context model_versions
        if hasattr(context, 'model_versions'):
            context.model_versions["remote_inference"] = data.get("inference_version")

        logger.info(
            "remote_request_success duration=%.2fs "
            "transcript_len=%d text_dim=%d clip_dim=%d "
            "inference_version=%s",
            elapsed,
            len(data.get("transcript") or ""),
            data.get("text_dim", 0),
            data.get("clip_dim", 0),
            data.get("inference_version", "unknown"),
            extra={"reel_id": reel_id},
        )

        # Cache in context
        context.intermediate_outputs[_REMOTE_KEY] = data
        return data

    except ValueError as ve:
        elapsed = round(time.monotonic() - t0, 2)
        failure_type = "schema_error"
        if "dim" in str(ve):
            failure_type = "dim_error"
        
        logger.error(
            "remote_request_failed reason=%s duration=%.2f error=%s",
            failure_type,
            elapsed,
            str(ve)[:120],
            extra={"reel_id": reel_id},
        )
        context.intermediate_outputs[_REMOTE_KEY] = {
            "status": "failed",
            "failure_type": failure_type,
            "error": str(ve)[:200],
        }
        return None

    except httpx.TimeoutException:
        elapsed = round(time.monotonic() - t0, 2)
        logger.error(
            "remote_request_failed reason=timeout duration=%.2f limit=%d",
            elapsed,
            REMOTE_TIMEOUT_SECONDS,
            extra={"reel_id": reel_id},
        )
        context.intermediate_outputs[_REMOTE_KEY] = {
            "status": "failed",
            "failure_type": "timeout",
            "error": f"timeout after {REMOTE_TIMEOUT_SECONDS}s",
        }
        return None

    except Exception as exc:  # noqa: BLE001
        elapsed = round(time.monotonic() - t0, 2)
        logger.error(
            "remote_request_failed reason=%s duration=%.2f",
            str(exc)[:120],
            elapsed,
            extra={"reel_id": reel_id},
        )
        context.intermediate_outputs[_REMOTE_KEY] = {
            "status": "failed",
            "failure_type": "http_error" if "http" in str(exc).lower() else "unknown_error",
            "error": str(exc)[:200],
        }
        return None
