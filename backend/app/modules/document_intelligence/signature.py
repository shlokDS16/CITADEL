"""
Signature detection via OpenCV contour analysis.

Algorithm:
  1. Convert page → grayscale → binary threshold (inverted, signatures are dark on light).
  2. Find external contours.
  3. Filter for "signature-like" shapes:
       - aspect ratio between 2:1 and 8:1 (signatures are wide-ish)
       - area > 500 px
       - bounding box height between 20px and 200px
       - not a perfectly horizontal/vertical line (filter dividers)
  4. If ≥1 candidate found  → 'detected'
     If exactly 0 contours      → 'not_found'
     If contours but none qualify → 'unclear'
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Literal

import cv2
import numpy as np
from PIL import Image

from app.modules.document_intelligence.extractor import render_last_page_png

log = logging.getLogger("citadel.signature")

SignatureStatus = Literal["detected", "not_found", "unclear"]

MIN_AREA = 500
MIN_AR = 2.0           # aspect ratio (w/h) lower bound
MAX_AR = 8.0
MIN_HEIGHT = 20
MAX_HEIGHT = 200
LINE_RATIO_TOLERANCE = 0.05   # bounding box "filled" ratio — too low = it's a line


def _classify_contour(c: np.ndarray) -> bool:
    x, y, w, h = cv2.boundingRect(c)
    if w * h == 0:
        return False
    if h < MIN_HEIGHT or h > MAX_HEIGHT:
        return False
    ar = w / h
    if ar < MIN_AR or ar > MAX_AR:
        return False
    area = cv2.contourArea(c)
    if area < MIN_AREA:
        return False
    fill_ratio = area / (w * h)
    if fill_ratio < LINE_RATIO_TOLERANCE:
        return False     # likely a divider line
    return True


def _detect_in_image(png_bytes: bytes, scope: Literal["bottom", "all"] = "bottom") -> SignatureStatus:
    img = np.array(Image.open(BytesIO(png_bytes)).convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    if scope == "bottom":
        h = gray.shape[0]
        gray = gray[int(h * 0.75):, :]   # bottom 25%
    if gray.size == 0:
        return "not_found"

    # adaptive threshold to handle varied scan brightness
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return "not_found"

    sig_like = [c for c in contours if _classify_contour(c)]
    if sig_like:
        return "detected"

    # contours present but none signature-like → unclear (might be a stamp / handwritten note)
    if any(cv2.contourArea(c) > 200 for c in contours):
        return "unclear"
    return "not_found"


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------
def detect_signature_in_pdf(pdf_bytes: bytes) -> SignatureStatus:
    """Render the LAST page of the PDF then run signature detection on bottom 25%."""
    try:
        png = render_last_page_png(pdf_bytes, dpi=150)
        return _detect_in_image(png, scope="bottom")
    except Exception as e:
        log.exception("signature detection (PDF) failed: %s", e)
        return "unclear"


def detect_signature_in_image(image_bytes: bytes) -> SignatureStatus:
    """For uploaded JPEG/PNG: scan the bottom 25% of the image."""
    try:
        return _detect_in_image(image_bytes, scope="bottom")
    except Exception as e:
        log.exception("signature detection (image) failed: %s", e)
        return "unclear"
