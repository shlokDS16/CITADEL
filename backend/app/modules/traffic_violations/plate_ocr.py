"""
License plate OCR — wraps the existing Document Intelligence OCR Space helper.

Strategy:
  - Caller passes a frame + a vehicle bbox (xyxy).
  - We crop the lower portion of the bbox (where the plate likely lives).
  - JPEG-encode the crop, send to OCR Space.
  - Apply a regex / cleanup pass to normalize text to Indian plate format.

Returns: plate text + confidence (0-1).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import cv2
import numpy as np

from app.modules.document_intelligence.ocr import ocr_image

log = logging.getLogger("citadel.traffic_violations.plate_ocr")

# Loose match for Indian plates: AA-NN-AA-NNNN or AANN-AA-NNNN with optional dashes/spaces
_PLATE_PATTERNS = [
    re.compile(r"[A-Z]{2}[\s\-]?\d{1,2}[\s\-]?[A-Z]{1,3}[\s\-]?\d{1,4}"),
    re.compile(r"[A-Z]{2}\d{2}[A-Z]{2}\d{4}"),
    re.compile(r"[A-Z0-9]{6,12}"),  # very loose fallback
]


def _clean(raw: str) -> str:
    """Strip non-plate chars and normalize spacing → DASH form."""
    s = (raw or "").upper()
    # remove anything that isn't letter/digit/dash/space
    s = re.sub(r"[^A-Z0-9\s\-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _match_plate(text: str) -> Optional[str]:
    cleaned = _clean(text)
    for pat in _PLATE_PATTERNS:
        m = pat.search(cleaned)
        if m:
            t = m.group(0)
            # normalize internal whitespace to dashes
            t = re.sub(r"\s+", "-", t)
            # collapse repeated dashes
            t = re.sub(r"-+", "-", t)
            return t
    return None


def read_plate_from_bbox(
    frame: np.ndarray,
    bbox_xyxy: tuple[int, int, int, int],
) -> tuple[Optional[str], float]:
    """
    Crop the bottom-third of `bbox_xyxy` (most likely plate region for cars,
    full bbox for motorcycles / small vehicles), JPEG-encode, send to OCR.
    Returns (plate_text, confidence_0_to_1).
    """
    x1, y1, x2, y2 = [int(v) for v in bbox_xyxy]
    h = max(1, y2 - y1)
    w = max(1, x2 - x1)

    # bottom 40% of the vehicle bbox usually contains the plate
    crop_y1 = y1 + int(h * 0.55)
    crop_y2 = y2
    crop_x1 = max(0, x1 - 4)
    crop_x2 = min(frame.shape[1], x2 + 4)

    if crop_y2 - crop_y1 < 20 or crop_x2 - crop_x1 < 40:
        # tiny detection — skip OCR
        return None, 0.0

    crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
    if crop.size == 0:
        return None, 0.0

    # upscale small crops for better OCR
    if crop.shape[1] < 200:
        scale = 200 / crop.shape[1]
        new_w = 200
        new_h = max(60, int(crop.shape[0] * scale))
        crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    ok, jpeg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        return None, 0.0

    try:
        result = ocr_image(jpeg.tobytes(), language="en", filename="plate.jpg")
    except Exception as e:
        log.warning("OCR Space call failed: %s", e)
        return None, 0.0

    plate = _match_plate(result.text or "")
    if not plate:
        return None, max(0.0, min(1.0, result.confidence or 0.0))

    return plate, max(0.0, min(1.0, result.confidence or 0.7))
