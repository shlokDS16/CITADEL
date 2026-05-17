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
    try:
        hist = [t.model_dump() for t in (body.history or [])]
        return service.chat(
            body.query, history=hist,
            language=body.language, allow_web=body.allow_web,
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
    try:
        content = await file.read()
        try:
            hist = json.loads(history) if history else []
        except Exception:
            hist = []
        return service.chat_with_file(
            query, content, file.filename or "upload",
            history=hist, language=language, allow_web=allow_web,
        )
    except Exception as e:
        log.exception("chat_upload failed")
        raise HTTPException(status_code=500, detail=f"Upload chat failed: {e}")
