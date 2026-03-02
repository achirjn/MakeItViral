"""
Module 2 — Remote Inference Configuration
------------------------------------------
Central config for remote GPU inference via Colab.
"""

from __future__ import annotations

# When True, transcript + embedding extractors use remote Colab endpoint.
# When False, extractors fall back to local inference (if available).
USE_REMOTE_INFERENCE = True

# Colab ngrok endpoint. Update this when a new Colab session starts.
REMOTE_INFERENCE_URL = "https://semaj-bicompact-reggie.ngrok-free.dev/process_reel"

# Hard timeout for remote HTTP call.
REMOTE_TIMEOUT_SECONDS = 240

INFERENCE_VERSION = "whisper_large_minilm_clip_v1"
