"""
PageIndex engine bridge.

Vendors the self-hosted PageIndex repo (cloned to backend/.vendor_pageindex)
and drives it with Groq via LiteLLM — the project's primary LLM. We use
PageIndex's MARKDOWN mode (`md_to_tree`): our knowledge corpus is authored
as clean `#`-structured markdown, which PageIndex turns into a faithful
hierarchical tree (node_id / title / summary / text), no chunking, no
vectors.

Trees are expensive to build (LLM summaries per node) so each corpus file
is built once and cached to .citizen_index/<name>.json, keyed by a hash
of the markdown. A background prebuild keeps the first user query instant.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from app.config import settings

log = logging.getLogger("citadel.citizen_assistant.pageindex")

# ---- vendor bridge -------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parents[3]          # .../backend
_VENDOR = _BACKEND_DIR / ".vendor_pageindex"
_PAGEINDEX_REPO = "https://github.com/VectifyAI/PageIndex.git"


def _ensure_vendor() -> bool:
    """
    Self-heal: the self-hosted PageIndex repo is git-ignored (50 MB
    third-party source). If it's missing on a fresh checkout, clone it
    once so the module provisions itself with zero manual setup.
    """
    if (_VENDOR / "pageindex").exists():
        return True
    try:
        import subprocess
        log.info("PageIndex vendor missing — cloning %s …", _PAGEINDEX_REPO)
        subprocess.run(
            ["git", "clone", "--depth", "1", _PAGEINDEX_REPO, str(_VENDOR)],
            check=True, capture_output=True, timeout=180,
        )
        return (_VENDOR / "pageindex").exists()
    except Exception as e:
        log.error("PageIndex auto-clone failed (%s). Citizen Assistant "
                  "knowledge RAG will be unavailable until vendored.", e)
        return False


_ensure_vendor()
if str(_VENDOR) not in sys.path and _VENDOR.exists():
    sys.path.insert(0, str(_VENDOR))

# Groq key must be visible to LiteLLM (it auto-reads GROQ_API_KEY for
# `groq/` models). settings already loaded it from .env.
if settings.GROQ_API_KEY and not os.getenv("GROQ_API_KEY"):
    os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY

# LiteLLM model id — Groq provider routing. Override via env if needed.
PI_MODEL = os.getenv("CITIZEN_PI_MODEL", f"groq/{settings.GROQ_CLASSIFIER_MODEL}")

_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_INDEX_DIR = _BACKEND_DIR / ".citizen_index"
_INDEX_DIR.mkdir(exist_ok=True)

_TREES: dict[str, dict[str, Any]] = {}      # corpus_name -> tree dict
_TREES_LOCK = threading.Lock()
_BUILD_STARTED = False


def _md_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cache_path(name: str) -> Path:
    return _INDEX_DIR / f"{name}.json"


async def _build_one(md_file: Path) -> Optional[dict[str, Any]]:
    """Build (or load cached) PageIndex tree for a single markdown file."""
    try:
        from pageindex import md_to_tree
    except Exception as e:  # pragma: no cover
        log.error("PageIndex import failed: %s", e)
        return None

    name = md_file.stem
    md_text = md_file.read_text(encoding="utf-8")
    h = _md_hash(md_text)
    cp = _cache_path(name)

    if cp.exists():
        try:
            cached = json.loads(cp.read_text(encoding="utf-8"))
            if cached.get("_md_hash") == h:
                log.info("PageIndex tree cache hit: %s", name)
                return cached
        except Exception:
            pass

    log.info("Building PageIndex tree for %s (Groq) …", name)
    try:
        # if_add_node_text='yes' embeds section bodies into the tree so the
        # reasoner can answer straight from the tree (no PDF page lookups).
        tree = await md_to_tree(
            str(md_file),
            if_add_node_summary="yes",
            summary_token_threshold=200,   # PageIndex crashes if left None
            if_add_node_id="yes",
            if_add_node_text="yes",
            if_add_doc_description="yes",
            model=PI_MODEL,
        )
    except Exception as e:
        log.error("md_to_tree failed for %s: %s", name, e)
        return None

    payload = {
        "_md_hash": h,
        "corpus": name,
        "doc_description": (tree.get("doc_description") if isinstance(tree, dict) else None),
        "structure": (tree.get("structure") if isinstance(tree, dict) else tree),
    }
    try:
        cp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("tree cache write failed for %s: %s", name, e)
    return payload


async def _build_all_async() -> None:
    if not _KNOWLEDGE_DIR.exists():
        log.warning("knowledge dir missing: %s", _KNOWLEDGE_DIR)
        return
    md_files = sorted(_KNOWLEDGE_DIR.glob("*.md"))
    for mf in md_files:
        payload = await _build_one(mf)
        if payload:
            with _TREES_LOCK:
                _TREES[mf.stem] = payload
    log.info("Citizen Assistant: %d knowledge trees ready", len(_TREES))


def start_background_build() -> None:
    """Kick off tree building in a daemon thread (called from lifespan)."""
    global _BUILD_STARTED
    if _BUILD_STARTED:
        return
    _BUILD_STARTED = True

    def _runner():
        try:
            asyncio.run(_build_all_async())
        except Exception as e:
            log.error("Citizen Assistant background build failed: %s", e)

    threading.Thread(target=_runner, name="citizen-pageindex-build", daemon=True).start()
    log.info("Citizen Assistant: background PageIndex build started")


def trees_ready() -> bool:
    with _TREES_LOCK:
        return len(_TREES) > 0


def get_trees() -> dict[str, dict[str, Any]]:
    with _TREES_LOCK:
        return dict(_TREES)


def corpus_catalog() -> list[dict[str, Any]]:
    """Lightweight list of loaded corpora + top-level sections (for the UI)."""
    out: list[dict[str, Any]] = []
    for name, payload in get_trees().items():
        struct = payload.get("structure") or []
        if isinstance(struct, dict):
            struct = struct.get("nodes") or [struct]
        out.append({
            "corpus": name,
            "description": payload.get("doc_description") or "",
            "sections": [n.get("title") for n in (struct or []) if isinstance(n, dict)][:24],
        })
    return out


async def build_ephemeral_tree(md_text: str, name: str = "uploaded") -> Optional[dict[str, Any]]:
    """
    Build a one-off tree for an uploaded (OCR'd) document. Not cached to
    the corpus — lives only for this request.
    """
    try:
        from pageindex import md_to_tree
    except Exception as e:
        log.error("PageIndex import failed: %s", e)
        return None
    tmp = _INDEX_DIR / f"_ephemeral_{_md_hash(md_text)}.md"
    try:
        tmp.write_text(md_text, encoding="utf-8")
        tree = await md_to_tree(
            str(tmp),
            if_add_node_summary="yes",
            summary_token_threshold=200,   # PageIndex crashes if left None
            if_add_node_id="yes",
            if_add_node_text="yes",
            if_add_doc_description="yes",
            model=PI_MODEL,
        )
        return {
            "corpus": name,
            "doc_description": (tree.get("doc_description") if isinstance(tree, dict) else None),
            "structure": (tree.get("structure") if isinstance(tree, dict) else tree),
        }
    except Exception as e:
        log.error("ephemeral tree build failed: %s", e)
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
