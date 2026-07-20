"""
Support Tickets — HTTP endpoints.

Mounted in app/main.py with prefix="/api"; spec-07 base path is
/api/v1/tickets (versioned per api-conventions.md). Routers stay thin:
parse → call service → return.

Classification does blocking I/O (Groq HTTP + VADER), so the routes that
classify run it via run_in_threadpool rather than blocking the event loop
— the same lesson the citizen_assistant module learned (context.md §6.4).

Auth: there is none yet (Phase 3). Actor identity is read from X-User-Id /
X-User-Role by the convention traffic and anomaly already use, and is NOT
enforced server-side. Do not mistake these headers for authentication.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from app.shared.ratelimit import rate_limit
from app.modules.tickets import schemas, service

log = logging.getLogger("citadel.tickets.router")
router = APIRouter()

_TAG = "support-tickets"

# Classification calls an external LLM → the tight ML budget from
# security-baseline.md. Reads get the standard budget.
_RL_CLASSIFY = Depends(rate_limit("tickets:classify", 10, 60))
_RL_STD = Depends(rate_limit("tickets:std", 60, 60))


def _actor(x_user_id: Optional[str]) -> Optional[str]:
    """Actor uuid from the header, if it looks like one.

    Phase 3 replaces this with a verified JWT subject. Until then a
    non-uuid value (e.g. the hardcoded 'rsd' login) is treated as no
    identity rather than being written into a uuid column.
    """
    if not x_user_id:
        return None
    from uuid import UUID

    try:
        return str(UUID(x_user_id))
    except (ValueError, AttributeError, TypeError):
        return None


@router.get(
    "/v1/tickets/health",
    response_model=schemas.HealthResponse,
    tags=[_TAG],
    summary="Liveness/readiness — tables, classifier mode, per-department queue depth",
)
async def health() -> schemas.HealthResponse:
    try:
        return schemas.HealthResponse(**service.health())
    except Exception as e:  # noqa: BLE001
        log.exception("tickets health failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/v1/tickets/templates",
    response_model=list[schemas.TicketTemplateOut],
    tags=[_TAG],
    summary="Quick-start ticket templates",
    dependencies=[_RL_STD],
)
async def templates() -> list[schemas.TicketTemplateOut]:
    rows = await run_in_threadpool(service.list_templates)
    return [schemas.TicketTemplateOut(**r) for r in rows]


@router.post(
    "/v1/tickets/preview",
    response_model=schemas.TicketPreviewOut,
    tags=[_TAG],
    summary="AI pre-analysis without submitting — category, department, priority, SLA",
    dependencies=[_RL_CLASSIFY],
)
async def preview(payload: schemas.TicketPreviewIn) -> schemas.TicketPreviewOut:
    if not (payload.subject or payload.description):
        raise HTTPException(status_code=400, detail="subject or description required")
    try:
        result = await run_in_threadpool(service.preview, payload)
        return schemas.TicketPreviewOut(**result)
    except Exception as e:  # noqa: BLE001
        log.exception("ticket preview failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/v1/tickets",
    response_model=schemas.TicketCreateOut,
    status_code=201,
    tags=[_TAG],
    summary="Create a ticket (classified + routed on submit)",
    dependencies=[_RL_CLASSIFY],
)
async def create_ticket(
    payload: schemas.TicketCreateIn,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> schemas.TicketCreateOut:
    try:
        result = await run_in_threadpool(service.create_ticket, payload, _actor(x_user_id))
        return schemas.TicketCreateOut(
            ticket=schemas.TicketOut(**result["ticket"]),
            preview=schemas.TicketPreviewOut(**result["preview"]),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("ticket create failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/v1/tickets/{ticket_id}",
    response_model=schemas.TicketOut,
    tags=[_TAG],
    summary="Ticket detail with timeline and attachments",
    dependencies=[_RL_STD],
)
async def get_ticket(ticket_id: str) -> schemas.TicketOut:
    row = await run_in_threadpool(service.get_ticket, ticket_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id} not found")
    return schemas.TicketOut(**row)
