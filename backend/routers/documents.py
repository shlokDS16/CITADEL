"""
Documents Router - Document Intelligence API endpoints
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import Optional
from uuid import UUID

from services.document_intel import (
    upload_document, get_document, search_documents
)

router = APIRouter()


@router.post("/upload")
async def upload_doc(
    file: UploadFile = File(...),
    doc_type: str = "auto",
    source_tier: str = "demo"
):
    """Upload and process a document"""
    try:
        content = await file.read()
        # Mock user ID for demo
        uploader_id = UUID("00000000-0000-0000-0000-000000000001")
        
        result = await upload_document(
            file_content=content,
            filename=file.filename,
            doc_type=doc_type,
            source_tier=source_tier,
            uploader_id=uploader_id
        )
        return {"success": True, "document": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}")
async def get_doc(document_id: UUID):
    """Get document by ID"""
    doc = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/search")
async def search_docs(query: str, limit: int = 5):
    """Search documents using semantic search"""
    results = await search_documents(query, limit)
    return {"query": query, "results": results}
