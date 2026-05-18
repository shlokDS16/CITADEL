"""
Multi-modal forensics — deepfake / AI-generated image & video detection.

Image: HF image classifier (pipeline.image_forensics) + EXIF inspection
(missing camera metadata / AI-tool software strings are real signals).
Video: sample frames with OpenCV, score each, aggregate.

Never raises — degrades to ``available=False`` so the waterfall continues.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile

from app.modules.fake_news import pipeline as ml

log = logging.getLogger("citadel.fake_news.media_forensics")

_AI_TOOLS = ("photoshop", "gimp", "lightroom", "stable diffusion", "midjourney",
             "dall-e", "dalle", "firefly", "generative", "ai ", "gan",
             "diffusion", "comfyui", "leonardo")
_VIDEO_EXT = (".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".gif")
_MAX_FRAMES = 8


def is_video(filename: str, content: bytes) -> bool:
    if filename and filename.lower().endswith(_VIDEO_EXT):
        return True
    return content[4:12] in (b"ftypmp4", b"ftypisom", b"ftypM4V ") or \
        content[:4] in (b"\x1aE\xdf\xa3",)        # mp4/mkv magic


def _exif(content: bytes) -> dict:
    try:
        from PIL import ExifTags, Image

        img = Image.open(io.BytesIO(content))
        ex = getattr(img, "_getexif", lambda: None)() or {}
        tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
        make = str(tags.get("Make", "") or "").strip()
        model = str(tags.get("Model", "") or "").strip()
        software = str(tags.get("Software", "") or "").strip()
        dt = str(tags.get("DateTimeOriginal") or tags.get("DateTime") or "")
        flags: list[str] = []
        if not ex:
            flags.append("No EXIF metadata (common in AI-generated or "
                          "metadata-stripped images)")
        elif not (make or model):
            flags.append("EXIF present but no camera make/model")
        if software and any(t in software.lower() for t in _AI_TOOLS):
            flags.append(f"Created/edited with: {software}")
        return {"has_exif": bool(ex),
                "camera": (f"{make} {model}".strip() or None),
                "software": software or None, "datetime": dt or None,
                "flags": flags}
    except Exception as e:  # noqa: BLE001
        return {"has_exif": False, "flags": [], "error": str(e)}


def _verdict(fabricated: float) -> tuple[str, float]:
    if fabricated >= 0.85:
        return "FAKE", 0.90
    if fabricated >= 0.60:
        return "LIKELY_FAKE", 0.75
    if fabricated >= 0.40:
        return "UNCERTAIN", 0.50
    if fabricated >= 0.20:
        return "LIKELY_REAL", 0.62
    return "REAL", 0.82


def analyze_image(content: bytes) -> dict:
    fr = ml.image_forensics(content)
    exif = _exif(content)
    if not fr.get("available"):
        return {"available": False, "kind": "image", "exif": exif,
                "reason": fr.get("error") or fr.get("reason")}
    fab = float(fr["fabricated"])
    verdict, conf = _verdict(fab)
    flags = list(exif.get("flags", []))
    if fr["ai_generated"] >= 0.5:
        flags.append(f"Likely AI-generated image ({int(fr['ai_generated']*100)}%)")
    if fr["deepfake"] >= 0.5:
        flags.append(f"Possible deepfake / face manipulation "
                     f"({int(fr['deepfake']*100)}%)")
    if fab < 0.2 and not flags:
        flags.append("No manipulation signals — consistent with an authentic photo")
    return {"available": True, "kind": "image", "forensics": fr, "exif": exif,
            "fabricated": fab, "verdict": verdict, "confidence": conf,
            "red_flags": flags}


def analyze_video(content: bytes, filename: str = "video.mp4") -> dict:
    # Unique temp path — concurrent uploads of equal size must not collide.
    fd, tmp = tempfile.mkstemp(prefix="fn_vid_", suffix=".bin")
    try:
        import cv2

        with os.fdopen(fd, "wb") as f:
            f.write(content)
        cap = cv2.VideoCapture(tmp)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            cap.release()
            return {"available": False, "kind": "video",
                    "reason": "could not decode video"}
        idxs = [int(total * i / (_MAX_FRAMES + 1))
                for i in range(1, _MAX_FRAMES + 1)]
        fabs: list[float] = []
        per: list[dict] = []
        for fi in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, frame = cap.read()
            if not ok:
                continue
            okj, buf = cv2.imencode(".jpg", frame)
            if not okj:
                continue
            fr = ml.image_forensics(buf.tobytes())
            if fr.get("available"):
                fabs.append(float(fr["fabricated"]))
                per.append({"frame": fi, "fabricated": fr["fabricated"]})
        cap.release()
        if not fabs:
            return {"available": False, "kind": "video",
                    "reason": "no analyzable frames"}
        mean = sum(fabs) / len(fabs)
        mx = max(fabs)
        frac = sum(1 for f in fabs if f >= 0.6) / len(fabs)
        agg = round(0.5 * mean + 0.3 * mx + 0.2 * frac, 4)
        verdict, conf = _verdict(agg)
        flags: list[str] = []
        if agg >= 0.6:
            flags.append(f"{int(frac*100)}% of sampled frames show "
                         f"manipulation signals")
        return {"available": True, "kind": "video",
                "frames_analyzed": len(fabs), "fabricated": agg,
                "mean": round(mean, 4), "max": round(mx, 4),
                "verdict": verdict, "confidence": conf,
                "per_frame": per, "red_flags": flags}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "kind": "video",
                "reason": f"video analysis failed: {e}"}
    finally:
        try:
            os.remove(tmp)
        except Exception:  # noqa: BLE001
            pass


def analyze_media(content: bytes, filename: str = "") -> dict:
    """Dispatch to image or video forensics by sniffed type."""
    if is_video(filename, content):
        return analyze_video(content, filename or "video.mp4")
    return analyze_image(content)
