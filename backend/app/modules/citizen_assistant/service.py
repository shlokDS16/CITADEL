"""
Citizen Assistant — service layer.

Orchestrates the answer pipeline:
  detect language -> (OCR file -> ephemeral tree) -> PageIndex reasoning
  retrieval (+ live facts + web improvisation) -> language-matched answer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.modules.citizen_assistant import (
    language as lang_mod,
    ocr_bridge,
    pageindex_engine,
    retrieval,
)

log = logging.getLogger("citadel.citizen_assistant.service")


def health() -> dict[str, Any]:
    trees = pageindex_engine.get_trees()
    return {
        "status": "ok",
        "trees_ready": pageindex_engine.trees_ready(),
        "corpora": len(trees),
        "model": pageindex_engine.PI_MODEL,
    }


def catalog() -> dict[str, Any]:
    return {
        "ready": pageindex_engine.trees_ready(),
        "catalog": pageindex_engine.corpus_catalog(),
    }


def _resolve_language(query: str, override: Optional[str]) -> dict[str, Any]:
    if override and override.strip() and override.strip().lower() != "auto":
        from app.modules.citizen_assistant.language import _mk
        return _mk(override.strip())
    return lang_mod.detect(query)


def chat(query: str, history: Optional[list[dict]] = None,
         language: Optional[str] = None, allow_web: bool = True) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {
            "answer": "Please type a question.", "language": "English",
            "bcp47": "en-IN", "restricted": False, "reasoning": [],
            "sources": [], "used_web": False, "confidence": 0,
        }
    lang = _resolve_language(q, language)
    result = retrieval.answer(
        q, language=lang["language"], history=history or [], allow_web=allow_web,
    )
    result["language"] = lang["language"]
    result["bcp47"] = lang["bcp47"]
    return result


def chat_with_file(query: str, content: bytes, filename: str,
                   history: Optional[list[dict]] = None,
                   language: Optional[str] = None,
                   allow_web: bool = True) -> dict[str, Any]:
    """Pipeline: OCR -> ephemeral PageIndex tree -> reasoning answer."""
    q = (query or "").strip() or "Please summarise this document and tell me what I should do."
    lang = _resolve_language(q, language)

    ocr_res = ocr_bridge.extract(content, filename)
    if not ocr_res.get("ok"):
        return {
            "answer": f"I couldn't read that file: {ocr_res.get('error') or 'unknown error'}. "
                      "Please upload a clearer PDF or image (max size per the OCR limit).",
            "language": lang["language"], "bcp47": lang["bcp47"],
            "restricted": False, "reasoning": ["OCR failed"], "sources": [],
            "used_web": False, "confidence": 20, "ocr": ocr_res,
        }

    try:
        eph = asyncio.run(
            pageindex_engine.build_ephemeral_tree(ocr_res["markdown"], name="uploaded")
        )
    except RuntimeError:
        # if an event loop is already running in this thread, use a fresh one
        loop = asyncio.new_event_loop()
        try:
            eph = loop.run_until_complete(
                pageindex_engine.build_ephemeral_tree(ocr_res["markdown"], name="uploaded")
            )
        finally:
            loop.close()
    except Exception as e:
        log.warning("ephemeral tree failed: %s", e)
        eph = None

    result = retrieval.answer(
        q, language=lang["language"], history=history or [],
        uploaded_tree=eph, allow_web=allow_web,
    )
    result["language"] = lang["language"]
    result["bcp47"] = lang["bcp47"]
    result["ocr"] = {
        "ok": True,
        "filename": filename,
        "confidence": ocr_res.get("confidence"),
        "page_count": ocr_res.get("page_count"),
        "chars": len(ocr_res.get("text") or ""),
    }
    return result
