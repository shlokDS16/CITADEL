"""
Receipt OCR + field extraction.

OCR engine: the shared document_intelligence OCR (OCR.Space for images —
the free-tier key already in .env). The spec imagined PaddleOCR +
LayoutLMv3; neither is installed, both are gigabytes, and OCR.Space
already reads retail receipts adequately. What matters for an expense is
merchant / total / tax / date — extracted here with rules tuned to Indian
retail receipts, each field carrying its own confidence so the UI can put
the citizen in the loop (status 'review' → confirm/edit → expense).

Line-item extraction is BEST-EFFORT and honestly so: flat OCR text loses
column alignment, so items parse only when a "name  qty  price" shape
survives. The mock's Items count comes from whatever parses; zero items
never blocks the total.

Storage: private `receipts` bucket (financial PII — data-handling.md),
uuid object keys, 5-min signed URLs — the same discipline as tickets.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

log = logging.getLogger("citadel.expenses.receipts")

BUCKET = "receipts"
SIGNED_URL_TTL_SECONDS = 300

# --------------------------------------------------------------------------
# Storage (mirrors tickets/storage.py discipline)
# --------------------------------------------------------------------------


def _client():  # noqa: ANN202
    from app.database import get_supabase

    return get_supabase()


def ensure_bucket() -> tuple[bool, Optional[str]]:
    """Create the private receipts bucket if missing. Idempotent."""
    try:
        sb = _client()
        for b in sb.storage.list_buckets():
            name = getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None)
            if name == BUCKET:
                public = getattr(b, "public", None)
                if public is None and isinstance(b, dict):
                    public = b.get("public")
                if public:
                    return False, f"bucket '{BUCKET}' is PUBLIC — receipts are financial PII"
                return True, None
        sb.storage.create_bucket(BUCKET, options={
            "public": False,
            "file_size_limit": 10 * 1024 * 1024,
            "allowed_mime_types": ["image/jpeg", "image/png", "image/webp", "image/heic"],
        })
        log.info("created private bucket %s", BUCKET)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"storage unreachable: {e}"


def upload(citizen_id: str, content: bytes, ext: str, content_type: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{citizen_id}/{day}/{uuid.uuid4()}{ext}"
    _client().storage.from_(BUCKET).upload(
        path=key, file=content,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return key


def signed_url(storage_path: str, ttl: int = SIGNED_URL_TTL_SECONDS) -> Optional[str]:
    if not storage_path:
        return None
    try:
        res = _client().storage.from_(BUCKET).create_signed_url(storage_path, ttl)
    except Exception as e:  # noqa: BLE001
        log.warning("signed_url failed: %s", e)
        return None
    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    return getattr(res, "signed_url", None)


def remove(storage_path: str) -> None:
    try:
        _client().storage.from_(BUCKET).remove([storage_path])
    except Exception as e:  # noqa: BLE001
        log.warning("storage remove failed: %s", e)


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
def run_ocr(content: bytes, filename: str) -> tuple[str, float, str]:
    """(raw_text, confidence 0..1, engine). Empty text on failure — the
    receipt still lands in 'review' for fully-manual entry."""
    try:
        from app.modules.document_intelligence.ocr import ocr_image

        result = ocr_image(content, filename=filename)
        if result.error:
            log.warning("OCR error: %s", result.error)
            return "", 0.0, "ocr_space:error"
        return result.text or "", round((result.confidence or 0) / 100.0, 3), "ocr_space"
    except Exception as e:  # noqa: BLE001
        log.warning("OCR bridge failed: %s", e)
        return "", 0.0, "unavailable"


# --------------------------------------------------------------------------
# Field extraction — Indian retail receipt heuristics
# --------------------------------------------------------------------------
_AMOUNT = r"(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.\d{1,2})?)"
_RE_TOTAL = re.compile(
    r"(?:grand\s*total|net\s*(?:amount|payable)|total\s*(?:amount|payable)?|amount\s*payable|bill\s*amount)"
    r"\s*[:\-]?\s*" + _AMOUNT, re.IGNORECASE)
_RE_SUBTOTAL = re.compile(r"(?:sub\s*[- ]?total|subtotal)\s*[:\-]?\s*" + _AMOUNT, re.IGNORECASE)
_RE_TAX = re.compile(
    r"(?:[cs]gst|igst|gst|tax(?:es)?|vat)\s*(?:@?\s*\d{1,2}(?:\.\d+)?\s*%)?\s*[:\-]?\s*" + _AMOUNT,
    re.IGNORECASE)
_RE_DATE = re.compile(
    r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b|"
    r"\b(\d{4})-(\d{2})-(\d{2})\b", re.IGNORECASE)
_RE_GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]{2}\b")
_RE_ITEM = re.compile(
    r"^([A-Za-z][A-Za-z0-9 .&\-']{2,40}?)\s{2,}(\d{1,2})\s{2,}" + _AMOUNT + r"\s*$")
# lines that are never a merchant name
_HEADER_NOISE = re.compile(
    r"tax\s*invoice|invoice|receipt|bill|gstin|cash\s*memo|original|duplicate|"
    r"phone|tel[:\s]|www\.|@|thank", re.IGNORECASE)


def _to_paise(num: str) -> Optional[int]:
    try:
        return int(round(float(num.replace(",", "")) * 100))
    except (TypeError, ValueError):
        return None


def _find_amount(rx: re.Pattern[str], text: str, take_max: bool = False) -> Optional[int]:
    hits = [p for m in rx.finditer(text) if (p := _to_paise(m.group(1))) is not None]
    if not hits:
        return None
    return max(hits) if take_max else hits[-1]


def _find_date(text: str) -> Optional[date]:
    for m in _RE_DATE.finditer(text):
        try:
            if m.group(4):  # ISO
                d = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
            else:
                dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if yy < 100:
                    yy += 2000
                if mm > 12 and dd <= 12:  # US-ordered slip
                    dd, mm = mm, dd
                d = date(yy, mm, dd)
            if date(2000, 1, 1) <= d <= date.today():
                return d
        except ValueError:
            continue
    return None


def _find_merchant(text: str) -> Optional[str]:
    """First plausible non-noise line near the top — receipts print the
    shop name first, before the address/GSTIN block."""
    for line in text.splitlines()[:8]:
        s = line.strip()
        if not (3 <= len(s) <= 60):
            continue
        if _HEADER_NOISE.search(s) or _RE_GSTIN.search(s):
            continue
        letters = sum(ch.isalpha() for ch in s)
        if letters < max(3, len(s) * 0.4):
            continue
        return s[:128]
    return None


def _find_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = _RE_ITEM.match(line.rstrip())
        if not m:
            continue
        total = _to_paise(m.group(3))
        qty = int(m.group(2))
        if total is None or qty <= 0:
            continue
        items.append({
            "name": m.group(1).strip()[:255],
            "qty": qty,
            "unit_price_paise": total // qty if qty else total,
            "line_total_paise": total,
        })
        if len(items) >= 50:
            break
    return items


def parse_fields(raw_text: str) -> dict[str, Any]:
    """Extract structured fields from flat OCR text. Every miss is a None,
    never a guess — the citizen confirms in review."""
    if not raw_text or not raw_text.strip():
        return {"merchant": None, "subtotal_paise": None, "tax_paise": None,
                "total_paise": None, "purchase_date": None, "items": []}

    total = _find_amount(_RE_TOTAL, raw_text, take_max=True)
    subtotal = _find_amount(_RE_SUBTOTAL, raw_text)
    # tax lines repeat (CGST + SGST) — sum distinct hits instead of last-wins
    tax_hits = [p for m in _RE_TAX.finditer(raw_text)
                if (p := _to_paise(m.group(1))) is not None]
    tax = sum(tax_hits) if tax_hits else None

    # arithmetic sanity: if subtotal + tax ≈ some larger amount in the text
    # and "total" grabbed a per-line value, prefer subtotal + tax
    if subtotal and tax and total and abs((subtotal + tax) - total) > max(100, total * 0.02):
        if subtotal + tax > total:
            total = subtotal + tax

    items = _find_items(raw_text)
    # No monetary signal anywhere → this text is not a receipt; claiming a
    # "merchant" from it would be a phantom field the citizen then trusts.
    monetary = any(v is not None for v in (total, subtotal, tax)) or bool(items)
    return {
        "merchant": _find_merchant(raw_text) if monetary else None,
        "subtotal_paise": subtotal,
        "tax_paise": tax,
        "total_paise": total,
        "purchase_date": _find_date(raw_text) if monetary else None,
        "items": items,
    }
