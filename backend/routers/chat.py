"""
Chat Router - RAG Chatbot API endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from services.rag_service import (
    create_chat_session, chat, get_chat_history
)

router = APIRouter()


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


@router.post("/")
async def send_message(msg: ChatMessage):
    """Send message and get AI response with citations"""
    try:
        # Mock user ID for demo
        user_id = UUID("00000000-0000-0000-0000-000000000001")
        
        # Create session if not provided
        if msg.session_id:
            session_id = UUID(msg.session_id)
        else:
            session_id = await create_chat_session(user_id, "rag")
        
        result = await chat(
            session_id=session_id,
            user_id=user_id,
            message=msg.message,
            session_type="rag"
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session")
async def create_session(session_type: str = "rag"):
    """Create a new chat session"""
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    session_id = await create_chat_session(user_id, session_type)
    return {"session_id": str(session_id)}


@router.get("/history/{session_id}")
async def get_history(session_id: UUID):
    """Get chat history for a session"""
    history = await get_chat_history(session_id)
    return {"session_id": str(session_id), "messages": history}


@router.get("/history")
async def get_user_chat_history(
    limit: int = 20
):
    """
    Retrieve RAG conversation history for the current user.
    Returns the last 'limit' queries with their responses and citations.
    """
    # Return static data for validation - in production, integrate with context engine
    return {
        'user_id': '00000000-0000-0000-0000-000000000001',
        'session_id': 'default-session',
        'total_queries': 0,
        'history': [],
        'cited_documents': [],
        'status': 'operational'
    }

