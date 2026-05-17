"""
Citizen Assistant — HTTP endpoints. Prefix /api (mounted in main.py)

  GET  /api/v1/citizen/health
  GET  /api/citizen/knowledge          corpus catalog (for the UI)
  POST /api/citizen/chat               {query, history[], language?, allow_web}
  POST /api/citizen/chat/upload        multipart: file + query + ...
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.modules.citizen_assistant import schemas, service

log = logging.getLogger("citadel.citizen_assistant.router")
router = APIRouter()


@router.get("/v1/citizen/health", response_model=schemas.HealthResponse,
            tags=["citizen-assistant"])
async def health():
    return service.health()


@router.get("/citizen/knowledge", response_model=schemas.CatalogResponse,
            tags=["citizen-assistant"])
async def knowledge():
    try:
        return service.catalog()
    except Exception as e:
        log.exception("catalog failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/citizen/chat", response_model=schemas.ChatResponse,
             tags=["citizen-assistant"])
async def chat(body: schemas.ChatRequest):
    # The pipeline is fully synchronous (LiteLLM sync client + PageIndex).
    # Run it in a worker thread so the blocking Groq calls never collide
    # with the running asyncio event loop (that collision was returning
    # empty completions → "couldn't compose an answer").
    from starlette.concurrency import run_in_threadpool
    try:
        hist = [t.model_dump() for t in (body.history or [])]
        return await run_in_threadpool(
            service.chat, body.query, hist, body.language, body.allow_web,
        )
    except Exception as e:
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")


@router.post("/citizen/chat/upload", response_model=schemas.ChatResponse,
             tags=["citizen-assistant"])
async def chat_upload(
    file: UploadFile = File(...),
    query: str = Form(""),
    history: str = Form("[]"),
    language: Optional[str] = Form(None),
    allow_web: bool = Form(True),
):
    from starlette.concurrency import run_in_threadpool
    try:
        content = await file.read()
        try:
            hist = json.loads(history) if history else []
        except Exception:
            hist = []
        return await run_in_threadpool(
            service.chat_with_file, query, content, file.filename or "upload",
            hist, language, allow_web,
        )
    except Exception as e:
        log.exception("chat_upload failed")
        raise HTTPException(status_code=500, detail=f"Upload chat failed: {e}")
