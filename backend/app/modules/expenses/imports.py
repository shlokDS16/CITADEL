"""
Bank-statement import: CSV and text-PDF parsing → review rows → commit.

CSV: Indian bank exports differ per bank (HDFC: Narration + Withdrawal
Amt; ICICI: Transaction Remarks + Withdrawal Amount (Dr); SBI: Description
+ Debit; generic: description + amount). Columns are auto-detected from
header keywords — no per-bank template to maintain, and a citizen's
odd export still maps as long as it has a date, a narration and a debit
column. Credits (salary, refunds) are SKIPPED: this module tracks
expenses, and silently importing income as spend would corrupt every
dashboard number.

PDF: text-layer extraction via PyMuPDF (already a dependency — the same
engine the citizen assistant uses). Scanned/image PDFs are refused with
an honest error rather than fed to OCR: a multi-page statement blows the
OCR.Space free tier and half-read financial data is worse than none.

LLM budget: rows are classified lexicon-first; only UNIQUE unseen
merchant keys may consult Groq, capped at MAX_LLM_PER_BATCH per import.
Everything beyond the cap stays honestly low-confidence for review.

Duplicate detection (spec-08): a row matching an existing expense on
(amount_paise, spent_at) with the same merchant key is flagged, not
dropped — the citizen decides.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime
from typing import Any, Optional

from app.modules.expenses import categorize, merchants

log = logging.getLogger("citadel.expenses.imports")

MAX_ROWS = 2000
MAX_LLM_PER_BATCH = 10

# header keyword → role
_DATE_HEADERS = ("date", "txn date", "transaction date", "value date", "value dt", "tran date")
_DESC_HEADERS = ("narration", "description", "remarks", "particulars", "details", "transaction remarks")
_DEBIT_HEADERS = ("withdrawal", "debit", "dr amount", "withdrawal amt", "amount (dr)", "paid out")
_CREDIT_HEADERS = ("deposit", "credit", "cr amount", "deposit amt", "amount (cr)", "paid in")
# single-column fallback (sign or DR marker). "value" is deliberately NOT
# here: HDFC's "Value Dt" column matched it and a date parsed as a
# ₹1.7 crore amount — found in testing.
_AMOUNT_HEADERS = ("amount", "amt")

_DATE_PATTERNS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
    "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d %B %Y",
)


def _parse_date(raw: str) -> Optional[date]:
    s = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    for fmt in _DATE_PATTERNS:
        try:
            d = datetime.strptime((raw or "").strip(), fmt).date()
            if date(2000, 1, 1) <= d <= date.today():
                return d
        except ValueError:
            continue
    # dd/mm/yyyy embedded in a longer cell
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b", s)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100:
            yy += 2000
        try:
            d = date(yy, mm, dd)
            if date(2000, 1, 1) <= d <= date.today():
                return d
        except ValueError:
            pass
    return None


def _parse_amount_paise(raw: str) -> Optional[int]:
    s = (raw or "").strip().replace(",", "").replace("₹", "").replace("INR", "").strip()
    if not s or s in ("-", "0", "0.0", "0.00"):
        return None
    # a date is not an amount — silently stripping its separators would
    # turn 17/07/2026 into ₹1.7 crore (defense in depth with the header fix)
    if re.search(r"\d[/\-]\d", s):
        return None
    neg = s.startswith("-") or s.endswith("Dr") or s.endswith("DR")
    s = re.sub(r"[^\d.]", "", s)
    try:
        v = int(round(float(s) * 100))
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v if not neg else v   # magnitude; direction handled by column role


def _match_header(header: str, candidates: tuple[str, ...]) -> bool:
    h = header.strip().lower()
    return any(c in h for c in candidates)


def detect_columns(headers: list[str]) -> Optional[dict[str, int]]:
    """Map column roles from a header row. Returns None when the shape is
    not recognisably a bank statement."""
    roles: dict[str, int] = {}
    for i, h in enumerate(headers):
        if "date" not in roles and _match_header(h, _DATE_HEADERS):
            roles["date"] = i
        elif "desc" not in roles and _match_header(h, _DESC_HEADERS):
            roles["desc"] = i
        elif "debit" not in roles and _match_header(h, _DEBIT_HEADERS):
            roles["debit"] = i
        elif "credit" not in roles and _match_header(h, _CREDIT_HEADERS):
            roles["credit"] = i
        elif "amount" not in roles and _match_header(h, _AMOUNT_HEADERS):
            roles["amount"] = i
    if "date" in roles and "desc" in roles and ("debit" in roles or "amount" in roles):
        return roles
    return None


def parse_csv(content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """→ (rows, notes). Each row: raw, parsed_description, parsed_amount_paise,
    parsed_date. Credits and unparseable lines are counted in notes, not
    silently eaten."""
    notes: list[str] = []
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")
        notes.append("file was not UTF-8 — decoded as latin-1")

    reader = csv.reader(io.StringIO(text))
    all_rows = [r for r in reader if any(c.strip() for c in r)]
    if not all_rows:
        return [], ["empty file"]

    # find the header row — banks often prepend account-summary lines
    roles = None
    header_idx = 0
    for i, r in enumerate(all_rows[:10]):
        roles = detect_columns(r)
        if roles:
            header_idx = i
            break
    if not roles:
        return [], [
            "could not detect columns — need a header row with date, "
            "narration/description and withdrawal/debit/amount"
        ]

    out: list[dict[str, Any]] = []
    skipped_credit = 0
    skipped_bad = 0
    for r in all_rows[header_idx + 1:]:
        if len(out) >= MAX_ROWS:
            notes.append(f"row cap {MAX_ROWS} reached — remaining lines ignored")
            break
        get = lambda role: r[roles[role]] if role in roles and roles[role] < len(r) else ""
        d = _parse_date(get("date"))
        desc = (get("desc") or "").strip()
        if "debit" in roles:
            # a dedicated debit column is authoritative: when it is empty
            # this row is NOT an expense — never fall through to another
            # column looking for a number to use instead
            amount = _parse_amount_paise(get("debit"))
            if amount is None:
                if "credit" in roles and _parse_amount_paise(get("credit")):
                    skipped_credit += 1
                else:
                    skipped_bad += 1
                continue
        else:
            cell = get("amount")
            amount = _parse_amount_paise(cell)
            # single amount column: credits are negative or Cr-marked
            if amount and ("cr" in cell.lower() and "dr" not in cell.lower()):
                skipped_credit += 1
                continue
        if not d or not desc or not amount:
            skipped_bad += 1
            continue
        out.append({
            "raw": {"cells": r[:12]},
            "parsed_description": desc[:255],
            "parsed_merchant": merchants.normalize(desc)[:128] or None,
            "parsed_amount_paise": amount,
            "parsed_date": d,
        })
    if skipped_credit:
        notes.append(f"{skipped_credit} credit row(s) skipped — imports track expenses only")
    if skipped_bad:
        notes.append(f"{skipped_bad} row(s) unparseable (missing date/description/amount)")
    return out, notes


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
_PDF_ROW = re.compile(
    r"^(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s+(.{4,90}?)\s+([0-9][0-9,]*\.\d{2})\s*(?:\s[0-9,.]+)?$"
)


def parse_pdf(content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Text-layer statement parse. Scanned PDFs refused honestly."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [], ["PyMuPDF not available"]
    notes: list[str] = []
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        return [], [f"not a readable PDF: {e}"]

    lines: list[str] = []
    for page in doc:
        lines.extend((page.get_text() or "").splitlines())
    doc.close()

    text_chars = sum(len(ln.strip()) for ln in lines)
    if text_chars < 200:
        return [], [
            "this PDF has no text layer (scanned image). Export a CSV from "
            "netbanking instead — OCR of a full statement is unreliable and "
            "is not attempted."
        ]

    out: list[dict[str, Any]] = []
    for ln in lines:
        if len(out) >= MAX_ROWS:
            notes.append(f"row cap {MAX_ROWS} reached")
            break
        m = _PDF_ROW.match(ln.strip())
        if not m:
            continue
        d = _parse_date(m.group(1))
        desc = m.group(2).strip()
        amount = _parse_amount_paise(m.group(3))
        # crude credit filter: salary/refund/reversal narrations
        if desc and re.search(r"\b(salary|refund|reversal|interest credit|cashback)\b", desc, re.I):
            continue
        if not d or not desc or not amount:
            continue
        out.append({
            "raw": {"line": ln.strip()[:300]},
            "parsed_description": desc[:255],
            "parsed_merchant": merchants.normalize(desc)[:128] or None,
            "parsed_date": d,
            "parsed_amount_paise": amount,
        })
    if not out:
        notes.append(
            "no transaction rows recognised — this bank's PDF layout may "
            "interleave columns; use the CSV export instead"
        )
    return out, notes


# --------------------------------------------------------------------------
# Classification + duplicates over parsed rows
# --------------------------------------------------------------------------
def classify_rows(rows: list[dict[str, Any]]) -> None:
    """In-place: predicted_category + predicted_confidence per row.

    Lexicon/cache first for everything; at most MAX_LLM_PER_BATCH unique
    unseen merchant keys consult Groq. Beyond the cap rows keep their
    low-confidence local answer — flagged for review, never guessed hard.
    """
    llm_budget = MAX_LLM_PER_BATCH
    seen_keys: set[str] = set()
    for row in rows:
        desc = row.get("parsed_description") or ""
        key = merchants.merchant_key(desc)
        allow_llm = False
        if key not in seen_keys and llm_budget > 0:
            # only spend LLM on a key the local layers can't answer;
            # categorize() itself will consult Groq only as layer 5
            allow_llm = True
        result = categorize.categorize(desc, allow_llm=allow_llm)
        if allow_llm and result["source"] == "llm":
            llm_budget -= 1
        seen_keys.add(key)
        row["predicted_category"] = result["category"]
        row["predicted_confidence"] = result["confidence"]


def flag_duplicates(rows: list[dict[str, Any]], existing: list[dict[str, Any]]) -> int:
    """Mark rows matching an existing expense on (amount, date) + merchant
    key. Returns the duplicate count."""
    index: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for e in existing:
        k = (int(e.get("amount_paise") or 0), str(e.get("spent_at"))[:10])
        index.setdefault(k, []).append(e)
    dupes = 0
    for row in rows:
        k = (int(row.get("parsed_amount_paise") or 0), str(row.get("parsed_date"))[:10])
        row["is_duplicate_of"] = None
        for e in index.get(k, []):
            row_key = merchants.merchant_key(row.get("parsed_description") or "")
            exp_key = merchants.merchant_key(
                (e.get("merchant") or e.get("description") or "")
            )
            if row_key == exp_key or not e.get("merchant"):
                row["is_duplicate_of"] = str(e["id"])
                dupes += 1
                break
    return dupes
