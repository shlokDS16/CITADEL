"""
OCR bridge.

Step 1 of the answer pipeline for uploaded files. Reuses the project's
existing OCR.Space wrapper (document_intelligence.ocr) — the OCR API the
user said is "already provided". Extracted text is shaped into light
markdown so PageIndex can build an ephemeral tree over it.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("citadel.citizen_assistant.ocr_bridge")

_PDF_EXT = (".pdf",)
_IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")


def extract(content: bytes, filename: str) -> dict[str, Any]:
    """
    OCR a citizen-uploaded file. Returns
        {ok, text, markdown, confidence, page_count, error}
    Never raises.
    """
    from app.modules.document_intelligence import ocr as di_ocr

    name = (filename or "upload").lower()

    # ---- PDF: key-less LOCAL extraction first (PyMuPDF) ----
    # No API key, no page/size cap → a 100-page PDF is read in <1s.
    # We only fall back to the metered OCR API for image-only PDFs, and
    # only if they're small enough for its free tier.
    if name.endswith(_PDF_EXT):
        from app.modules.citizen_assistant import pdf_extract
        px = pdf_extract.extract_pdf_local(content, filename or "document.pdf")
        if px.get("ok"):
            return {
                "ok": True,
                "text": px["text"],
                "markdown": px["markdown"],
                "confidence": 99.0,                     # exact text layer, not OCR
                "page_count": px["page_count"],
                "error": None,
                "method": "pymupdf-local",
                "note": px.get("note", ""),
                "text_pages": px.get("text_pages"),
                "low_text_pages": px.get("low_text_pages"),
            }
        # Image-only / scanned PDF with no text layer. Try the OCR API
        # only when it's within the free tier (else return guidance).
        try:
            import app.config as _cfg
            max_mb = getattr(_cfg.settings, "OCR_SPACE_MAX_REQUEST_MB", 1)
        except Exception:
            max_mb = 1
        if len(content) > max_mb * 1024 * 1024:
            return {"ok": False, "text": "", "markdown": "", "confidence": 0.0,
                    "page_count": px.get("page_count", 0),
                    "error": px.get("note") or
                    "This PDF has no selectable text and is too large for the "
                    "free OCR tier. Please upload a text-based PDF."}
        # small scanned PDF → fall through to OCR.Space below

    try:
        if name.endswith(_PDF_EXT):
            res = di_ocr.ocr_pdf(content)
        else:
            res = di_ocr.ocr_image(content, filename=filename or "image.png")
    except Exception as e:
        log.warning("OCR failed for %s: %s", filename, e)
        return {"ok": False, "text": "", "markdown": "", "confidence": 0.0,
                "page_count": 0, "error": str(e)}

    if getattr(res, "error", None):
        return {"ok": False, "text": "", "markdown": "", "confidence": 0.0,
                "page_count": 0, "error": res.error}

    text = (res.text or "").strip()
    if not text:
        return {"ok": False, "text": "", "markdown": "", "confidence": 0.0,
                "page_count": 0, "error": "No readable text found in the file."}

    # Shape into markdown so PageIndex md_to_tree gets real headings:
    # one H1 for the doc, an H2 per OCR page.
    pages = getattr(res, "pages", None) or [text]
    md_parts = [f"# Uploaded Document: {filename}", ""]
    for i, pg in enumerate(pages, 1):
        pg = (pg or "").strip()
        if not pg:
            continue
        md_parts.append(f"## Page {i}")
        md_parts.append(pg)
        md_parts.append("")
    markdown = "\n".join(md_parts)

    return {
        "ok": True,
        "text": text,
        "markdown": markdown,
        "confidence": float(getattr(res, "confidence", 0.0) or 0.0),
        "page_count": int(getattr(res, "page_count", len(pages)) or len(pages)),
        "error": None,
    }
