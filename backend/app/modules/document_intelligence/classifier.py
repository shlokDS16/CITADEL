"""
Document type classification.

Primary: Groq `llama-3.3-70b-versatile` (15ms tested) for instruction-following.
Fallback: deterministic keyword heuristics (used when API fails or returns
          something outside the allowed enum).

Returns one of:
  invoice | contract | id_document | government_permit | tender_notice |
  permit | report | receipt | affidavit | certificate
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings
from app.shared import groq_failover

log = logging.getLogger("citadel.classifier")

ALLOWED_TYPES = {
    "invoice", "contract", "id_document", "government_permit", "tender_notice",
    "permit", "report", "receipt", "affidavit", "certificate",
}

SYSTEM_PROMPT = (
    "You are a document classifier. Classify the following document text into "
    "exactly one of these categories: invoice, contract, id_document, "
    "government_permit, tender_notice, permit, report, receipt, affidavit, "
    "certificate. Return ONLY the category name in lowercase, nothing else."
)

# Keyword fallback (case-insensitive, prioritized — first match wins).
KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("invoice",          ["invoice", "tax invoice", "bill no", "total amount", "gst no", "gstin"]),
    ("contract",         ["agreement", "this agreement", "party of the first part", "whereas", "hereinafter"]),
    ("tender_notice",    ["tender", "request for proposal", "rfp", "bid submission", "earnest money"]),
    ("government_permit",["government of", "ministry of", "approved by competent authority", "official seal"]),
    ("id_document",      ["aadhaar", "pan card", "voter id", "passport no", "driving licence", "uidai"]),
    ("permit",           ["permit no", "permit number", "permission granted", "authorized by"]),
    ("receipt",          ["receipt no", "received from", "amount received", "payment receipt"]),
    ("affidavit",        ["affidavit", "deponent", "sworn before", "i hereby solemnly affirm"]),
    ("certificate",      ["certificate", "this is to certify", "certified that", "registration no"]),
]


@dataclass
class ClassificationResult:
    document_type: str
    confidence: float           # 0..1
    method: str                 # "groq" | "keyword" | "default"
    raw_response: str = ""


def _classify_via_groq(text_excerpt: str, timeout: int = 15) -> ClassificationResult | None:
    try:
        r = groq_failover.post_chat(
            {
                "model": settings.GROQ_CLASSIFIER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text_excerpt},
                ],
                "temperature": 0,
                "max_tokens": 12,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
        content = (body.get("choices", [{}])[0].get("message", {}).get("content") or "").strip().lower()
        # Sometimes the model adds a period or quotes
        content = content.strip(" .'\"`\n")
        if content in ALLOWED_TYPES:
            return ClassificationResult(
                document_type=content,
                confidence=0.92,
                method="groq",
                raw_response=content,
            )
        log.warning("Groq returned unrecognized type: %r", content)
        return ClassificationResult(
            document_type="report",
            confidence=0.40,
            method="groq",
            raw_response=content,
        )
    except Exception as e:
        log.warning("Groq classification failed: %s", e)
        return None


def _classify_via_keywords(text: str) -> ClassificationResult:
    lower = text.lower()
    for doc_type, kws in KEYWORD_MAP:
        for kw in kws:
            if kw in lower:
                return ClassificationResult(
                    document_type=doc_type,
                    confidence=0.65,
                    method="keyword",
                    raw_response=kw,
                )
    return ClassificationResult(document_type="report", confidence=0.30, method="default", raw_response="")


def classify_document(text: str, max_words: int = 500) -> ClassificationResult:
    """Public entry point — tries Groq first, falls back to keywords."""
    if not text or not text.strip():
        return ClassificationResult(document_type="report", confidence=0.10, method="default")

    excerpt = " ".join(text.split()[:max_words])

    via_api = _classify_via_groq(excerpt)
    if via_api and via_api.confidence >= 0.50:
        return via_api

    fallback = _classify_via_keywords(excerpt)
    if via_api and via_api.method == "groq" and fallback.confidence > via_api.confidence:
        # Keyword agreed with itself stronger than the LLM's low-conf guess
        return fallback
    return via_api or fallback
