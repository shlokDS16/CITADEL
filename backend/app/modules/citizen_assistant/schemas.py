"""Pydantic models for the Citizen Assistant."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ChatTurn(BaseModel):
    role: str                          # 'user' | 'bot'
    text: str


class ChatRequest(BaseModel):
    query: str
    history: list[ChatTurn] = []
    language: Optional[str] = None     # override; else auto-detected
    allow_web: bool = True


class SourceRef(BaseModel):
    corpus: str
    section: Optional[str] = None
    node_id: Optional[str] = None
    url: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    language: str
    bcp47: str                         # for browser speech output
    restricted: bool = False
    reasoning: list[str] = []
    sources: list[SourceRef] = []
    used_web: bool = False
    confidence: int = 0
    ocr: Optional[dict[str, Any]] = None   # present when a file was uploaded


class HealthResponse(BaseModel):
    status: str
    trees_ready: bool
    corpora: int
    model: str


class CatalogResponse(BaseModel):
    ready: bool
    catalog: list[dict[str, Any]]
