from __future__ import annotations

import os
import shutil
from pathlib import Path

from module2.context import ExtractionContext
from module2.logging_config import get_logger


logger = get_logger("cleanup")


def _safe_remove_file(path: str | None, reel_id: str) -> bool:
    if not path:
        return False
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cleanup_partial_failure type=file error=%s",
            str(exc)[:80],
            extra={"reel_id": reel_id},
        )
    return False


def _safe_remove_dir(path: str | None, reel_id: str) -> bool:
    if not path:
        return False
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cleanup_partial_failure type=dir error=%s",
            str(exc)[:80],
            extra={"reel_id": reel_id},
        )
    return False


def cleanup_context(context: ExtractionContext) -> None:
    """
    Cleanup guarantee: always attempt to delete ephemeral artifacts.
    """
    rid = context.reel_id
    logger.debug("cleanup_started", extra={"reel_id": rid})

    frame_count = 0
    for frame_path in list(context.sampled_frames):
        if _safe_remove_file(frame_path, rid):
            frame_count += 1
    logger.debug(
        "frame_count_removed=%d",
        frame_count,
        extra={"reel_id": rid},
    )

    audio_removed = _safe_remove_file(context.audio_path, rid)
    logger.debug(
        "audio_removed=%s",
        audio_removed,
        extra={"reel_id": rid},
    )

    video_removed = _safe_remove_file(context.video_path, rid)
    logger.debug(
        "video_removed=%s",
        video_removed,
        extra={"reel_id": rid},
    )

    temp_removed = _safe_remove_dir(context.temp_dir, rid)
    logger.debug(
        "temp_dir_removed=%s",
        temp_removed,
        extra={"reel_id": rid},
    )
