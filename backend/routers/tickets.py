"""
Tickets Router - Ticket Analyzer API endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from services.ticket_service import (
    create_ticket, get_ticket, get_ticket_queue,
    update_ticket_status, assign_ticket
)

router = APIRouter()


class TicketCreate(BaseModel):
    title: str
    description: str


class TicketUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class TicketAssign(BaseModel):
    assignee_id: str


@router.post("/")
async def create_new_ticket(ticket: TicketCreate):
    """Create a new ticket with AI classification"""
    try:
        submitter_id = UUID("00000000-0000-0000-0000-000000000001")
        result = await create_ticket(
            title=ticket.title,
            description=ticket.description,
            submitter_id=submitter_id
        )
        return {"success": True, "ticket": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
async def get_queue(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50
):
    """Get ticket queue for operators"""
    tickets = await get_ticket_queue(status=status, priority=priority, limit=limit)
    return {"tickets": tickets}


@router.get("/{ticket_id}")
async def get_single_ticket(ticket_id: UUID):
    """Get ticket by ID"""
    ticket = await get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.patch("/{ticket_id}/status")
async def update_status(ticket_id: UUID, update: TicketUpdate):
    """Update ticket status"""
    try:
        user_id = UUID("00000000-0000-0000-0000-000000000001")
        result = await update_ticket_status(
            ticket_id=ticket_id,
            new_status=update.status,
            updated_by=user_id,
            notes=update.notes
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{ticket_id}/assign")
async def assign_to_operator(ticket_id: UUID, assign: TicketAssign):
    """Assign ticket to operator"""
    try:
        user_id = UUID("00000000-0000-0000-0000-000000000001")
        result = await assign_ticket(
            ticket_id=ticket_id,
            assignee_id=UUID(assign.assignee_id),
            assigned_by=user_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
