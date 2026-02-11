"""
Support Tickets Router for C.I.T.A.D.E.L.
Citizen-facing ticket submission and tracking.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from services.support_ticket_analyzer import get_ticket_analyzer
from services.context_engine import get_context_engine, CitizenContext
from middleware.access_control import verify_role

router = APIRouter()


class TicketSubmission(BaseModel):
    title: str
    description: str
    contact_email: Optional[str] = None


class TicketResponse(BaseModel):
    ticket_id: str
    category: str
    priority: str
    urgency: str
    suggested_response: str
    route_to_department: str
    estimated_sla_hours: int
    requires_escalation: bool
    status: str


@router.post("/submit", response_model=TicketResponse)
async def submit_ticket(
    request: Request,
    ticket: TicketSubmission,
    auth: dict = Depends(verify_role)
):
    """Submit and analyze a new support ticket (citizens only)"""
    
    analyzer = get_ticket_analyzer()
    context_engine = get_context_engine()
    
    # Analyze ticket
    analysis = await analyzer.analyze_ticket(
        title=ticket.title,
        description=ticket.description,
        user_id=auth['user_id'],
        contact_email=ticket.contact_email
    )
    
    # Update citizen context
    try:
        session_id = request.headers.get('x-session-id')
        context = await context_engine.get_context(auth['user_id'], session_id, auth['role'])
        if isinstance(context, CitizenContext):
            await context_engine.add_ticket(context, analysis['ticket_id'], analysis['category'])
    except Exception:
        pass  # Context update is non-critical
    
    return TicketResponse(**analysis)


@router.get("/my-tickets")
async def get_my_tickets(auth: dict = Depends(verify_role)):
    """Get all tickets submitted by the current user"""
    
    analyzer = get_ticket_analyzer()
    tickets = await analyzer.get_user_tickets(auth['user_id'])
    
    return {
        "total": len(tickets),
        "tickets": tickets
    }


@router.get("/status/{ticket_id}")
async def get_ticket_status(
    ticket_id: str,
    auth: dict = Depends(verify_role)
):
    """Get status of a specific ticket"""
    
    analyzer = get_ticket_analyzer()
    ticket = await analyzer.get_ticket_status(ticket_id, auth['user_id'])
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return ticket


@router.get("/categories")
async def get_categories():
    """Get available ticket categories"""
    
    analyzer = get_ticket_analyzer()
    
    return {
        "categories": list(analyzer.CATEGORIES.keys()),
        "departments": analyzer.DEPARTMENT_ROUTING
    }
