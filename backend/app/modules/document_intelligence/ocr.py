"""
OCR.space integration with automatic page-splitting for the 1MB free-tier limit.

Public API:
  - ocr_image(content, language)  → OCRResult
  - ocr_pdf(content,   language)  → OCRResult     (auto-splits pages if >1MB)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import settings
from app.modules.document_intelligence.extractor import split_pdf_pages

log = logging.getLogger("citadel.ocr")

# Map our 3-option language codes → OCR.space codes
LANG_MAP = {
    "en": "eng",
    "hi": "hin",
    "en+hin": "eng+hin",
    "en+hi": "eng+hin",
}


@dataclass
class OCRResult:
    text: str
    confidence: float                # 0..100, weighted-avg word confidence (heuristic)
    pages: list[str] = field(default_factory=list)
    page_count: int = 0
    error: Optional[str] = None


def _post_to_ocr_space(file_bytes: bytes, filename: str, language: str, timeout: int = 60) -> dict:
    """Single multipart POST to OCR.space."""
    files = {"file": (filename, file_bytes, _mime_for(filename))}
    data = {
        "apikey": settings.OCR_SPACE_API_KEY,
        "language": language,
        "isOverlayRequired": "true",   # need word positions for confidence calc
        "scale": "true",
        "OCREngine": "2",              # newer engine, better for non-English
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(settings.OCR_SPACE_ENDPOINT, files=files, data=data)
    r.raise_for_status()
    return r.json()


def _mime_for(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        return "image/jpeg"
    if name.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def _parse_response(body: dict) -> tuple[str, float]:
    """
    Pull text + a confidence proxy from the OCR.space response.
    OCR.space doesn't directly expose word confidence in the free tier — we
    proxy via the ratio of words that have valid Word entries in the overlay.
    Real-world: a clean scan returns ~100% recognized words.
    """
    if body.get("IsErroredOnProcessing"):
        msg = body.get("ErrorMessage")
        if isinstance(msg, list):
            msg = "; ".join(msg)
        raise RuntimeError(f"OCR.space error: {msg}")

    parsed = body.get("ParsedResults") or []
    if not parsed:
        return "", 0.0

    parts: list[str] = []
    word_total = 0
    word_with_text = 0

    for pr in parsed:
        text = pr.get("ParsedText") or ""
        parts.append(text)

        overlay = pr.get("TextOverlay") or {}
        for line in overlay.get("Lines") or []:
            for w in line.get("Words") or []:
                word_total += 1
                if (w.get("WordText") or "").strip():
                    word_with_text += 1

    text_joined = "\n".join(parts).strip()
    if word_total == 0:
        # No overlay data — treat presence of text as low-medium confidence
        confidence = 70.0 if text_joined else 0.0
    else:
        confidence = round(100 * word_with_text / word_total, 2)
    return text_joined, confidence


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------
def ocr_image(content: bytes, language: str = "en", filename: str = "image.png") -> OCRResult:
    """OCR a single image (PNG / JPEG)."""
    lang = LANG_MAP.get(language, "eng")
    try:
        body = _post_to_ocr_space(content, filename, lang)
        text, conf = _parse_response(body)
        return OCRResult(text=text, confidence=conf, pages=[text], page_count=1)
    except Exception as e:
        log.exception("OCR image failed")
        return OCRResult(text="", confidence=0.0, error=str(e))


def ocr_pdf(content: bytes, language: str = "en") -> OCRResult:
    """OCR a PDF — sends as one request when small, page-by-page when >1MB."""
    lang = LANG_MAP.get(language, "eng")
    max_bytes = settings.ocr_max_request_bytes

    # Single shot path if it fits
    if len(content) <= max_bytes:
        try:
            body = _post_to_ocr_space(content, "doc.pdf", lang)
            text, conf = _parse_response(body)
            # rough page split on form-feed; OCR.space sometimes returns it
            page_chunks = text.split("\f") if text else [""]
            return OCRResult(
                text=text,
                confidence=conf,
                pages=page_chunks,
                page_count=len(page_chunks),
            )
        except Exception as e:
            log.exception("Single-shot PDF OCR failed; falling through to split path")
            log.info("error: %s", e)

    # Per-page fallback
    try:
        page_blobs = split_pdf_pages(content, max_bytes_per_page=max_bytes)
        pages: list[str] = []
        confidences: list[float] = []
        for i, blob in enumerate(page_blobs, start=1):
            ext = "pdf" if blob[:4] == b"%PDF" else "png"
            mime_filename = f"page_{i}.{ext}"
            try:
                body = _post_to_ocr_space(blob, mime_filename, lang)
                text, conf = _parse_response(body)
            except Exception as e:
                log.warning("OCR page %d failed: %s", i, e)
                text, conf = "", 0.0
            pages.append(text)
            confidences.append(conf)

        joined = "\n".join(pages).strip()
        avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        return OCRResult(text=joined, confidence=avg_conf, pages=pages, page_count=len(pages))
    except Exception as e:
        log.exception("PDF page-split OCR failed")
        return OCRResult(text="", confidence=0.0, error=str(e))
