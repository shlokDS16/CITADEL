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
