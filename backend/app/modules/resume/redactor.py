"""
Bias-mitigation redactor.

Given the candidate's full text + per-job bias_flags, return a redacted version
that strips the configured sensitive attributes BEFORE scoring/Groq culture-fit.

Each redaction pass is independent and idempotent. Defaults are conservative
(redact gender + age + name; keep location since location_score depends on it).
"""
from __future__ import annotations

import hashlib
import re

# Common gendered tokens (English; basic Indian salutation set)
GENDER_PRONOUNS = re.compile(
    r"\b(he|she|him|her|his|hers|himself|herself)\b",
    re.IGNORECASE,
)
GENDER_TITLES = re.compile(
    r"\b(Mr\.?|Mrs\.?|Ms\.?|Miss|Mister|Sir|Madam|Shri|Smt\.?|Kumari|Master)\b",
    re.IGNORECASE,
)
GENDERED_ORG_HINTS = re.compile(
    r"\b(women in [a-z]+|girls? who [a-z]+|society of women [a-z]+|men's [a-z]+ club)\b",
    re.IGNORECASE,
)

# Year patterns (4-digit 19xx/20xx years used in dates)
YEAR_RANGE = re.compile(r"\b(19|20)\d{2}\s*[-–to]+\s*(19|20)\d{2}\b")
YEAR_SINGLE = re.compile(r"\b(19|20)\d{2}\b")
DOB_LINE = re.compile(r"(date of birth|dob|d\.o\.b\.)\s*[:\-]?\s*[\d/.\-]+", re.IGNORECASE)
AGE_PHRASE = re.compile(r"\bage\s*[:\-]?\s*\d{1,3}\b", re.IGNORECASE)

# Indian phone, email, GST regexes (reuse from doc-intel pii.py mental model)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
INDIAN_PHONE = re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b")

# Indian zip codes (PIN: 6 digits)
PIN_CODE = re.compile(r"\b\d{6}\b")


def _name_token(text: str) -> str:
    """Pseudonymize a name to a stable Candidate-XXXX placeholder."""
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=4).hexdigest().upper()
    return f"Candidate-{digest}"


def redact_gender(text: str, name: str | None = None) -> str:
    text = GENDER_PRONOUNS.sub("they", text)
    text = GENDER_TITLES.sub("[honorific]", text)
    text = GENDERED_ORG_HINTS.sub("[organization]", text)
    if name and name in text:
        text = text.replace(name, _name_token(name))
    return text


def redact_age(text: str) -> str:
    text = DOB_LINE.sub("[date of birth]", text)
    text = AGE_PHRASE.sub("[age redacted]", text)
    text = YEAR_RANGE.sub("[date range]", text)
    text = YEAR_SINGLE.sub("[YEAR]", text)
    return text


def redact_location(text: str, location_words: list[str] | None = None) -> str:
    text = PIN_CODE.sub("[PIN]", text)
    if location_words:
        for w in location_words:
            if w and len(w) > 2:
                text = re.sub(r"\b" + re.escape(w) + r"\b", "[location]", text, flags=re.IGNORECASE)
    return text


def redact_name(text: str, name: str | None) -> str:
    if not name:
        return text
    placeholder = _name_token(name)
    return text.replace(name, placeholder)


def redact_text(
    text: str,
    parsed_resume: dict | None,
    bias_flags: dict,
) -> str:
    """Apply all redactions per the bias_flags. Order matters."""
    if not text:
        return ""
    out = text
    parsed = parsed_resume or {}
    name = parsed.get("name")
    loc = parsed.get("location") or {}
    location_words = [loc.get("city"), loc.get("state")]

    if bias_flags.get("redact_name", True):
        out = redact_name(out, name)
    if bias_flags.get("redact_gender", True):
        out = redact_gender(out, name)
    if bias_flags.get("redact_age", True):
        out = redact_age(out)
    if bias_flags.get("redact_location", False):
        out = redact_location(out, location_words)

    return out
