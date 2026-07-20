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

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.shared.filetype import assert_upload_kind
from app.shared.ratelimit import rate_limit
from app.modules.tickets import schemas, service, storage

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


# NOTE: /mine and /stats MUST stay above /{ticket_id} — FastAPI matches in
# declaration order, so a path param declared first would swallow them.
@router.get(
    "/v1/tickets/mine",
    response_model=schemas.TicketListOut,
    tags=[_TAG],
    summary="Citizen's own tickets",
    dependencies=[_RL_STD],
)
async def my_tickets(
    status: Optional[str] = Query(default=None, description="Comma-separated status filter"),
    category: Optional[str] = Query(default=None, description="Comma-separated category filter"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> schemas.TicketListOut:
    result = await run_in_threadpool(
        service.list_tickets, _actor(x_user_id), status, category, limit, offset
    )
    return schemas.TicketListOut(**result)


@router.get(
    "/v1/tickets/stats",
    response_model=schemas.TicketStatsOut,
    tags=[_TAG],
    summary="My-Tickets KPI strip — counts and mean resolution time",
    dependencies=[_RL_STD],
)
async def ticket_stats(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> schemas.TicketStatsOut:
    return schemas.TicketStatsOut(
        **await run_in_threadpool(service.ticket_stats, _actor(x_user_id))
    )


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


@router.post(
    "/v1/tickets/{ticket_id}/updates",
    response_model=schemas.TicketUpdateOut,
    status_code=201,
    tags=[_TAG],
    summary="Add a citizen comment to a ticket's timeline",
    dependencies=[_RL_STD],
)
async def add_update(
    ticket_id: str,
    payload: schemas.TicketUpdateIn,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> schemas.TicketUpdateOut:
    try:
        row = await run_in_threadpool(
            service.add_citizen_update, ticket_id, payload.text, _actor(x_user_id)
        )
        return schemas.TicketUpdateOut(**row)
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("add_update failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/v1/tickets/{ticket_id}/rate",
    response_model=schemas.TicketOut,
    tags=[_TAG],
    summary="Rate a resolved ticket 1-5",
    dependencies=[_RL_STD],
)
async def rate_ticket(ticket_id: str, payload: schemas.TicketRateIn) -> schemas.TicketOut:
    try:
        row = await run_in_threadpool(
            service.rate_ticket, ticket_id, payload.rating, payload.comment
        )
        return schemas.TicketOut(**row)
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        # Rating an unresolved ticket is a valid request in the wrong state.
        raise HTTPException(status_code=409, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("rate_ticket failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/v1/tickets/{ticket_id}/reopen",
    response_model=schemas.TicketOut,
    tags=[_TAG],
    summary=f"Reopen a resolved ticket within {service.REOPEN_WINDOW_DAYS} days",
    dependencies=[_RL_STD],
)
async def reopen_ticket(ticket_id: str, payload: schemas.TicketReopenIn) -> schemas.TicketOut:
    try:
        row = await run_in_threadpool(service.reopen_ticket, ticket_id, payload.reason)
        return schemas.TicketOut(**row)
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=409, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("reopen_ticket failed")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------
def _max_body(content_length: Optional[str] = Header(default=None)) -> None:
    """Reject an oversized upload from Content-Length *before* Starlette
    spools the multipart body to a temp file. Route dependencies resolve
    before the File() param, so this runs pre-buffer."""
    if content_length is None:
        return
    try:
        n = int(content_length)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid Content-Length")
    if n > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {settings.max_upload_bytes // (1024 * 1024)}MB limit",
        )


@router.post(
    "/v1/tickets/{ticket_id}/attachments",
    response_model=schemas.AttachmentOut,
    status_code=201,
    tags=[_TAG],
    summary="Attach a photo / video / voice note / file to a ticket",
    dependencies=[_RL_STD, Depends(_max_body)],
)
async def add_attachment(
    ticket_id: str,
    kind: str = Form(default="file", description="photo | video | voice | file"),
    file: UploadFile = File(...),
) -> schemas.AttachmentOut:
    kind = (kind or "file").strip().lower()
    if kind not in storage.EXT_ALLOWLIST:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of: {', '.join(sorted(storage.EXT_ALLOWLIST))}",
        )

    ext = storage.extension_of(file.filename)
    if ext not in storage.EXT_ALLOWLIST[kind]:
        raise HTTPException(
            status_code=415,
            detail=(
                f"extension {ext or '(none)'} not allowed for {kind}; "
                f"expected one of {', '.join(sorted(storage.EXT_ALLOWLIST[kind]))}"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {settings.max_upload_bytes // (1024 * 1024)}MB limit",
        )

    # Content sniff behind the extension gate — defeats a renamed payload
    # (e.g. an .exe uploaded as evidence.jpg). Raises 415 on mismatch.
    detected = assert_upload_kind(file.filename, content, storage.KIND_ALLOWLIST[kind])

    try:
        att = await run_in_threadpool(
            service.attach_file, ticket_id, kind, content, file.filename, detected
        )
        return schemas.AttachmentOut(**att)
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("attachment upload failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/v1/tickets/{ticket_id}/attachments/{att_id}",
    tags=[_TAG],
    summary="Pre-signed attachment download URL (5 min TTL)",
    dependencies=[_RL_STD],
)
async def attachment_url(ticket_id: str, att_id: str) -> dict[str, object]:
    url = await run_in_threadpool(service.attachment_download_url, ticket_id, att_id)
    if not url:
        raise HTTPException(status_code=404, detail="attachment not found")
    return {"download_url": url, "expires_in": storage.SIGNED_URL_TTL_SECONDS}
