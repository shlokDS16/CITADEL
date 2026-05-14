"""
Vector indexing — chunk text, embed, store in Supabase pgvector
(`document_chunks` table).

Embedding strategy:
  - Try to load `fastembed` (BAAI/bge-small-en-v1.5, 384 dims, ONNX).
  - If unavailable (Python 3.14 wheel landscape is sparse for ML libs as of 2026-05),
    fall back to a deterministic hashed-token embedding (HashEmbedder) so the
    indexing pipeline still ships. Same 384 dims, same DB schema, same calling
    convention — RAG module can hot-swap to a real model later by:
      1) installing fastembed (or sentence-transformers)
      2) re-running the embedder over existing chunks via `reindex_document(...)`

Public API:
  - chunk_text(text, size_tokens, overlap)  → list[str]
  - embed_chunks(chunks)                    → list[list[float]]   (384-dim each)
  - index_document(document_id, text, ...)  → int (chunks written)
  - reindex_document(document_id, text, ...) → int  (delete-then-index)
  - active_embedder_name()                  → str ("fastembed:..." | "hash-stub")
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache
from typing import Optional

from app.config import settings
from app.database import get_supabase

log = logging.getLogger("citadel.indexer")

EMBEDDING_DIM = settings.EMBEDDING_DIM   # 384


# ============================================================
# Embedding backends
# ============================================================
class HashEmbedder:
    """
    Deterministic hashed-bag-of-tokens embedding.

    Process: tokenize → for each token, derive 4 (hash, sign) pairs → bin into
    one of EMBEDDING_DIM buckets → ±1. Resulting vector is L2-normalized.

    Semantic quality is poor (no context, no co-occurrence learning) but the
    schema is correct and similarity between very-similar texts is non-zero.
    Fast, no deps, works everywhere.
    """
    name = "hash-stub-v1"
    _TOKEN_RE = re.compile(r"\w+", re.UNICODE)

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        tokens = self._TOKEN_RE.findall(text.lower())
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=16).digest()
            # 4 hash projections per token to spread signal across the vector
            for k in range(4):
                idx = int.from_bytes(digest[k*2:k*2+2], "big") % EMBEDDING_DIM
                sign = 1.0 if (digest[8 + k] & 1) == 0 else -1.0
                vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class FastEmbedAdapter:
    """Wraps fastembed.TextEmbedding to the same .embed(list[str]) → list[list[float]] API."""
    name = f"fastembed:{settings.EMBEDDING_MODEL}"

    def __init__(self):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]


@lru_cache(maxsize=1)
def _embedder():
    """Pick the best available embedder, log which one."""
    try:
        e = FastEmbedAdapter()
        log.info("Embedder: %s (real BGE)", e.name)
        return e
    except Exception as ex:
        log.warning(
            "fastembed unavailable (%s) — falling back to hash-stub embedder. "
            "RAG quality will be limited; install fastembed when py-rust-stemmers "
            "ships a Python 3.14 wheel, then run reindex_document(...) over chunks.",
            ex,
        )
        return HashEmbedder()


def active_embedder_name() -> str:
    return _embedder().name


# ============================================================
# Chunking
# ============================================================
def chunk_text(
    text: str,
    size_tokens: Optional[int] = None,
    overlap_tokens: Optional[int] = None,
) -> list[str]:
    """
    Token-approx chunking using whitespace. ~1 token ≈ 0.75 words for English.
    """
    if not text or not text.strip():
        return []
    size_tokens = size_tokens or settings.CHUNK_SIZE_TOKENS
    overlap_tokens = overlap_tokens or settings.CHUNK_OVERLAP_TOKENS

    words = text.split()
    if len(words) <= size_tokens:
        return [" ".join(words)]

    chunks: list[str] = []
    step = max(1, size_tokens - overlap_tokens)
    for i in range(0, len(words), step):
        window = words[i:i + size_tokens]
        if not window:
            break
        chunks.append(" ".join(window))
        if i + size_tokens >= len(words):
            break
    return chunks


# ============================================================
# Embedding
# ============================================================
def embed_chunks(chunks: list[str]) -> list[list[float]]:
    if not chunks:
        return []
    return _embedder().embed(chunks)


# ============================================================
# Persist into Supabase pgvector
# ============================================================
def _delete_existing_chunks(document_id: str) -> None:
    try:
        get_supabase().table("document_chunks").delete().eq("document_id", document_id).execute()
    except Exception as e:
        log.warning("Could not delete existing chunks for %s: %s", document_id, e)


def index_document(
    document_id: str,
    text: str,
    document_type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    department: Optional[str] = None,
    replace_existing: bool = False,
) -> int:
    """
    Chunk → embed → upsert into document_chunks. Returns chunks written.
    """
    if replace_existing:
        _delete_existing_chunks(document_id)

    chunks = chunk_text(text)
    if not chunks:
        log.info("No chunks for document %s (text empty)", document_id)
        return 0

    log.info("Embedding %d chunks for document %s", len(chunks), document_id)
    vectors = embed_chunks(chunks)

    rows = [
        {
            "document_id": document_id,
            "chunk_index": i,
            "chunk_text": c,
            "embedding": v,
            "document_type": document_type,
            "tags": tags or [],
            "department": department,
        }
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]

    try:
        get_supabase().table("document_chunks").insert(rows).execute()
        log.info("Indexed %d chunks for document %s using %s", len(rows), document_id, _embedder().name)
        return len(rows)
    except Exception as e:
        log.exception("Chunk insert failed for %s: %s", document_id, e)
        return 0


def reindex_document(document_id: str, text: str, **kwargs) -> int:
    """Convenience wrapper used after a doc is edited or reassigned."""
    return index_document(document_id, text, replace_existing=True, **kwargs)
