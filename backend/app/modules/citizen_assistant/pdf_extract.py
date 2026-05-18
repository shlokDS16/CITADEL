"""
Key-less, local PDF text extraction.

The OCR.Space free tier caps file size (~1 MB) and pages (a few) — useless
for a 100-page document. PyMuPDF (fitz, already a project dependency)
extracts text from digital PDFs **locally, no API key, no page limit, in
well under a second for hundreds of pages**. That extracted text is then
shaped into markdown so PageIndex builds its tree over it — exactly the
"extraction -> chunks -> PageIndex, LLM only for organising" design the
user asked for. No model/API key touches the raw PDF content.

Scanned/image-only PDFs have no embedded text; we detect those pages and
report them rather than silently returning nothing (no local OCR engine
is installed, and we deliberately avoid the metered OCR API for big PDFs).
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("citadel.citizen_assistant.pdf_extract")

# A page with fewer than this many extracted chars is treated as
# image/scanned (no real embedded text layer).
_LOW_TEXT_CHARS = 25


def extract_pdf_local(content: bytes, filename: str = "document.pdf") -> dict[str, Any]:
    """
    Returns:
      ok            bool   — any usable text found
      markdown      str    — '# doc' + '## Page N' + page text (PageIndex-ready)
      text          str    — plain concatenation
      page_count    int
      text_pages    int    — pages with a real text layer
      low_text_pages list[int] — 1-based pages that look scanned/empty
      method        str    — 'pymupdf'
      note          str    — guidance when some/all pages are image-only
    Never raises.
    """
    try:
        import fitz  # PyMuPDF
    except Exception as e:
        log.error("PyMuPDF unavailable: %s", e)
        return {"ok": False, "markdown": "", "text": "", "page_count": 0,
                "text_pages": 0, "low_text_pages": [], "method": "none",
                "note": "PDF text engine unavailable on the server."}

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        log.warning("PDF open failed for %s: %s", filename, e)
        return {"ok": False, "markdown": "", "text": "", "page_count": 0,
                "text_pages": 0, "low_text_pages": [], "method": "pymupdf",
                "note": f"Could not open the PDF ({e})."}

    page_count = doc.page_count
    md_parts = [f"# {filename}", ""]
    plain_parts: list[str] = []
    low_text_pages: list[int] = []
    text_pages = 0

    for i in range(page_count):
        try:
            page = doc.load_page(i)
            txt = page.get_text("text") or ""
        except Exception as e:
            txt = ""
            log.debug("page %d extract failed: %s", i + 1, e)
        txt = txt.strip()
        if len(txt) < _LOW_TEXT_CHARS:
            low_text_pages.append(i + 1)
            continue
        text_pages += 1
        md_parts.append(f"## Page {i + 1}")
        md_parts.append(txt)
        md_parts.append("")
        plain_parts.append(txt)

    try:
        doc.close()
    except Exception:
        pass

    text = "\n".join(plain_parts).strip()
    ok = bool(text)
    note = ""
    if low_text_pages and text_pages:
        note = (f"{len(low_text_pages)} of {page_count} page(s) appear to be "
                f"scanned/image-only and were skipped (no embedded text).")
    elif low_text_pages and not text_pages:
        note = ("This PDF appears to be fully scanned/image-based with no "
                "selectable text, so it can't be read without OCR. Please "
                "upload a text-based PDF (or individual page images).")

    return {
        "ok": ok,
        "markdown": "\n".join(md_parts) if ok else "",
        "text": text,
        "page_count": page_count,
        "text_pages": text_pages,
        "low_text_pages": low_text_pages,
        "method": "pymupdf",
        "note": note,
    }
