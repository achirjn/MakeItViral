"""
Colab GPU Inference Server — Whisper-large + MiniLM-384 + CLIP ViT-L/14
========================================================================
Run in Google Colab with GPU runtime.

Install:
    !pip install fastapi uvicorn pyngrok torch torchvision torchaudio
    !pip install openai-whisper sentence-transformers
    !pip install git+https://github.com/openai/CLIP.git

Start:
    uvicorn colab_inference_server:app --host 0.0.0.0 --port 8000
    # Then expose with ngrok
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("colab_inference")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Module2 GPU Inference", version="1.0")

INFERENCE_VERSION = "whisper_large_minilm_clip_v1"

# ---------------------------------------------------------------------------
# Model globals (loaded once at startup)
# ---------------------------------------------------------------------------
_whisper_model = None
_minilm_model = None
_clip_model = None
_clip_preprocess = None
_device = None


@app.on_event("startup")
def load_models() -> None:
    global _whisper_model, _minilm_model, _clip_model, _clip_preprocess, _device

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Device: %s", _device)

    if torch.cuda.is_available():
        mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        logger.info("GPU memory: %.1f GB", mem)

    # Whisper-large
    import whisper  # type: ignore

    logger.info("Loading Whisper-large...")
    _whisper_model = whisper.load_model("large", device=_device)
    logger.info("Whisper-large loaded")

    # MiniLM (sentence-transformers, 384-dim)
    from sentence_transformers import SentenceTransformer  # type: ignore

    logger.info("Loading MiniLM...")
    _minilm_model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2", device=str(_device)
    )
    logger.info("MiniLM loaded")

    # CLIP ViT-L/14
    import clip  # type: ignore

    logger.info("Loading CLIP ViT-L/14...")
    _clip_model, _clip_preprocess = clip.load("ViT-L/14", device=_device)
    logger.info("CLIP ViT-L/14 loaded")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ProcessRequest(BaseModel):
    reel_id: str
    video_url: str


class ProcessResponse(BaseModel):
    reel_id: str
    transcript: str
    transcript_confidence: float
    text_embedding: list[float]
    text_dim: int
    clip_embedding: list[float]
    clip_dim: int
    audio_duration: float
    processing_time: float
    inference_version: str


class ErrorResponse(BaseModel):
    reel_id: str
    error: str
    inference_version: str


# ---------------------------------------------------------------------------
# Helper: download video
# ---------------------------------------------------------------------------


def _download_video(url: str, dest_dir: str) -> str:
    """Download video to temp directory. Returns file path."""
    video_path = os.path.join(dest_dir, "video.mp4")
    # Use yt-dlp for robust downloading
    try:
        import yt_dlp  # type: ignore

        ydl_opts = {
            "outtmpl": video_path,
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception:
        # Fallback: direct HTTP download
        import urllib.request

        urllib.request.urlretrieve(url, video_path)

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video download failed: {url}")
    return video_path


def _extract_audio(video_path: str, dest_dir: str) -> str:
    """Extract audio to WAV using ffmpeg."""
    audio_path = os.path.join(dest_dir, "audio.wav")

    print("FILE SIZE:", os.path.getsize(video_path))
    with open(video_path, "rb") as f:
        head = f.read(64)
    print("HEADER_64:", head)
    print("HAS_FTYP:", b"ftyp" in head)

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                audio_path,
                "-y",
            ],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print("FFMPEG_STDERR:")
        stderr = (e.stderr or b"").decode(errors="ignore")
        print(stderr)

        if (
            "does not contain any stream" in stderr
            or "matches no streams" in stderr
            or "Stream map" in stderr
        ):
            subprocess.run(
                [
                    "ffmpeg",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=16000:cl=mono",
                    "-t",
                    "1",
                    audio_path,
                    "-y",
                ],
                capture_output=True,
                check=True,
            )
            return audio_path
        raise
    return audio_path


def _sample_frames(video_path: str, dest_dir: str, n_frames: int = 10) -> list[str]:
    """Sample N uniform frames from video using ffmpeg."""
    import cv2  # type: ignore

    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []

    indices = np.linspace(0, total_frames - 1, n_frames, dtype=int)
    frame_paths: list[str] = []

    for i, idx in enumerate(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:
            fp = os.path.join(dest_dir, f"frame_{i:03d}.jpg")
            cv2.imwrite(fp, frame)
            frame_paths.append(fp)

    cap.release()
    return frame_paths


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@app.post("/process_reel", response_model=ProcessResponse)
async def process_reel(
    reel_id: str = Form(...),
    file: UploadFile = File(...),
):
    t0 = time.time()
    logger.info("request_started reel_id=%s", reel_id)

    tmp_dir = tempfile.mkdtemp(prefix=f"colab_{reel_id[:8]}_")

    try:
        # 1. Persist uploaded video
        video_path = os.path.join(tmp_dir, "video.mp4")
        with open(video_path, "wb") as f:
            f.write(await file.read())

        # 2. Extract audio
        audio_path = _extract_audio(video_path, tmp_dir)

        # 3. Whisper transcription
        with torch.no_grad():
            result = _whisper_model.transcribe(audio_path, language=None)

        transcript = result.get("text", "").strip()
        # Approximate confidence from avg log-prob of segments
        segments = result.get("segments", [])
        if segments:
            avg_logprob = sum(s.get("avg_logprob", -1.0) for s in segments) / len(
                segments
            )
            # Convert log-prob to approximate 0-1 confidence
            transcript_confidence = round(min(1.0, max(0.0, 1.0 + avg_logprob)), 3)
        else:
            transcript_confidence = 0.0

        audio_duration = result.get("duration", 0.0) or 0.0

        # 4. MiniLM text embedding (384-dim)
        with torch.no_grad():
            text_emb = _minilm_model.encode(
                transcript if transcript else "[EMPTY]",
                normalize_embeddings=False,
            )
        text_embedding = [float(x) for x in text_emb.tolist()]

        # 5. CLIP visual embedding (768-dim)
        import clip  # type: ignore
        from PIL import Image  # type: ignore

        frame_paths = _sample_frames(video_path, tmp_dir, n_frames=10)

        if frame_paths:
            frame_tensors = []
            for fp in frame_paths:
                img = Image.open(fp).convert("RGB")
                frame_tensors.append(_clip_preprocess(img))

            batch = torch.stack(frame_tensors).to(_device)

            with torch.no_grad():
                frame_features = _clip_model.encode_image(batch)

            # Mean pool across frames
            clip_vec = frame_features.mean(dim=0).cpu().numpy()
            clip_embedding = [float(x) for x in clip_vec.tolist()]
        else:
            # No frames — zero vector
            clip_embedding = [0.0] * 768

        elapsed = round(time.time() - t0, 2)
        logger.info(
            "request_success reel_id=%s duration=%.2fs transcript_len=%d",
            reel_id,
            elapsed,
            len(transcript),
        )

        return ProcessResponse(
            reel_id=reel_id,
            transcript=transcript,
            transcript_confidence=transcript_confidence,
            text_embedding=text_embedding,
            text_dim=len(text_embedding),
            clip_embedding=clip_embedding,
            clip_dim=len(clip_embedding),
            audio_duration=round(audio_duration, 2),
            processing_time=elapsed,
            inference_version=INFERENCE_VERSION,
        )

    except Exception as exc:
        elapsed = round(time.time() - t0, 2)
        logger.error(
            "request_failed reel_id=%s duration=%.2fs error=%s",
            reel_id,
            elapsed,
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=500,
            detail={
                "reel_id": reel_id,
                "error": str(exc)[:200],
                "inference_version": INFERENCE_VERSION,
            },
        )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
