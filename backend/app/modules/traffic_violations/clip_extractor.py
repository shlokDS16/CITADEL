"""
Extract short MP4 clips around violation moments using OpenCV.

We use cv2 (already a dependency) rather than ffmpeg — no extra binaries to
ship. Quality is "good enough" for evidence review; Phase 6 may swap to a
real video toolchain if cluster encoding becomes a need.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import cv2

log = logging.getLogger("citadel.traffic_violations.clip")


def extract_clip(
    src_video: str,
    center_seconds: float,
    out_path: str,
    duration: float = 3.0,
    max_dim: int = 1280,
) -> Optional[str]:
    """
    Cut a `duration`-second clip centred on `center_seconds` from `src_video`,
    saving as MP4 (H.264 if available, else mp4v fallback) to `out_path`.
    Downscales to `max_dim` on the long edge to keep file size reasonable.
    Returns out_path on success, None on failure.
    """
    if not os.path.exists(src_video):
        log.warning("clip: missing source %s", src_video)
        return None

    cap = cv2.VideoCapture(src_video)
    if not cap.isOpened():
        log.warning("clip: cv2 could not open %s", src_video)
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if w == 0 or h == 0:
        cap.release()
        return None

    # downscale target
    if max(w, h) > max_dim:
        if w >= h:
            new_w = max_dim
            new_h = int(h * (max_dim / w))
        else:
            new_h = max_dim
            new_w = int(w * (max_dim / h))
    else:
        new_w, new_h = w, h
    # ensure even dims for encoders
    new_w -= new_w % 2
    new_h -= new_h % 2

    half = duration / 2.0
    start_sec = max(0.0, center_seconds - half)
    end_sec = min((total_frames / fps) if total_frames else (center_seconds + half), center_seconds + half)

    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # Try H.264 first (avc1) — falls back to mp4v if unavailable.
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (new_w, new_h))
    if not writer.isOpened():
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (new_w, new_h))
    if not writer.isOpened():
        log.warning("clip: VideoWriter could not open %s", out_path)
        cap.release()
        return None

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    cur = start_frame
    written = 0
    while cur < end_frame:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if (new_w, new_h) != (w, h):
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        writer.write(frame)
        cur += 1
        written += 1

    cap.release()
    writer.release()

    if written == 0:
        try:
            os.remove(out_path)
        except Exception:
            pass
        return None

    return out_path


def extract_frame(src_video: str, at_seconds: float) -> Optional[bytes]:
    """Grab a single JPEG-encoded frame at `at_seconds`. Returns bytes or None."""
    cap = cv2.VideoCapture(src_video)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(at_seconds * fps))
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    ok2, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return jpeg.tobytes() if ok2 else None
