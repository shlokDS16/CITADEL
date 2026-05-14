"""
Document Intelligence — HTTP endpoints (APIRouter).

URL prefix: /api  (mounted in main.py)
- /api/v1/doc-intel/health
- /api/documents/...      (upload, queue, library, batch, actions, audit, edit)
- /api/templates/...      (CRUD, passport key)
- /api/dashboard/...      (stats, volume, by-type, top-uploaders, sla-distribution)

The router is intentionally THIN: parse → service.X(...) → return.
All business logic lives in service.py / templates.py / dashboard.py.
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.modules.document_intelligence import dashboard, schemas, service, templates

log = logging.getLogger("citadel.doc_intel.router")

router = APIRouter()


# ============================================================
# Health
# ============================================================
@router.get("/v1/doc-intel/health", tags=["doc-intel"])
async def health() -> dict:
    return {"status": "ok", "module": "document_intelligence", "phase": 6}


# ============================================================
# 1. UPLOAD & ANALYZE
# ============================================================
@router.post(
    "/documents/upload",
    tags=["documents"],
    response_model=schemas.UploadResponse,
    summary="Upload one or more documents — kicks off background processing",
)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="Files to upload (max 10 per batch)")],
    document_type: Annotated[str, Form()] = "auto_detect",
    language: Annotated[str, Form()] = "en",
    priority: Annotated[str, Form()] = "normal",
    detect_redact_pii: Annotated[bool, Form()] = False,
    signature_validation: Annotated[bool, Form()] = False,
    uploaded_by: Annotated[str, Form()] = "system",
):
    if not files:
        raise HTTPException(400, "No files supplied")

    payloads: list[tuple[bytes, str, str]] = []
    for f in files:
        content = await f.read()
        payloads.append((content, f.filename, f.content_type or "application/octet-stream"))

    try:
        result = service.upload_files(
            payloads,
            document_type=document_type,
            language=language,
            priority=priority,
            detect_redact_pii=detect_redact_pii,
            signature_validation=signature_validation,
            uploaded_by=uploaded_by,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        log.exception("upload failed")
        raise HTTPException(500, "Upload failed")

    # Schedule per-doc background processing (priority order: urgent first)
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    queue_items = sorted(
        [(d["id"], priority_order.get(priority, 2)) for d in result["documents"]],
        key=lambda x: x[1],
    )
    for db_id, _ in queue_items:
        background_tasks.add_task(service.process_document, db_id)

    return {
        "batch_id": result["batch_id"],
        "total": result["total"],
        "documents": [
            {"doc_id": d["doc_id"], "filename": d["filename"], "storage_path": d["storage_path"]}
            for d in result["documents"]
        ],
    }


@router.get(
    "/documents/batch/{batch_id}/results",
    tags=["documents"],
    summary="Per-batch processing results",
)
async def batch_results(batch_id: str):
    return service.get_batch_results(batch_id)


@router.get(
    "/documents/batch/{batch_id}/export",
    tags=["documents"],
    summary="Export batch results as CSV or JSON",
)
async def batch_export(batch_id: str, format: str = Query("csv", pattern="^(csv|json)$")):
    if format == "json":
        return service.get_batch_results(batch_id)
    csv_text = service.export_batch_csv(batch_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch_{batch_id}.csv"'},
    )


@router.get(
    "/documents/{doc_id}/audit",
    tags=["documents"],
    summary="Audit trail for a single document",
)
async def get_audit(doc_id: str):
    try:
        return service.get_audit_log(doc_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


# ---- Single-doc actions ----
@router.post("/documents/{doc_id}/approve", tags=["documents"])
async def approve_doc(doc_id: str, performed_by: str = Query("system")):
    return service.perform_action(doc_id, "approve", performed_by=performed_by)


@router.post("/documents/{doc_id}/reject", tags=["documents"])
async def reject_doc(doc_id: str, reason: str = Query(""), performed_by: str = Query("system")):
    return service.perform_action(doc_id, "reject", performed_by=performed_by, reason=reason)


@router.post("/documents/{doc_id}/archive", tags=["documents"])
async def archive_doc(doc_id: str, performed_by: str = Query("system")):
    return service.perform_action(doc_id, "archive", performed_by=performed_by)


@router.post("/documents/{doc_id}/reassign", tags=["documents"])
async def reassign_doc(
    background_tasks: BackgroundTasks,
    doc_id: str,
    performed_by: str = Query("system"),
):
    res = service.perform_action(doc_id, "reassign", performed_by=performed_by)
    if res.get("success"):
        # Re-run pipeline on the doc
        from app.database import get_supabase
        rec = get_supabase().table("documents").select("id").eq("doc_id", doc_id).single().execute().data
        if rec:
            background_tasks.add_task(service.process_document, rec["id"])
    return res


@router.delete(
    "/documents/{doc_id}",
    tags=["documents"],
    summary="Permanently delete a document — cascades to chunks, audit log, and storage",
)
async def delete_doc(doc_id: str, performed_by: str = Query("system")):
    res = service.delete_document(doc_id, performed_by=performed_by)
    if not res.get("success"):
        raise HTTPException(404, res.get("message") or "delete failed")
    return res


# ============================================================
# 2. QUEUE
# ============================================================
@router.get(
    "/documents/queue",
    tags=["queue"],
    summary="Pending review queue with filtering, sorting, pagination",
)
async def get_queue(
    search: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,           # noqa: A002 — matches the spec
    priority: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    per_page: int = 20,
):
    return service.list_queue(
        search=search, status=status, type_=type, priority=priority,
        sort_by=sort_by, sort_order=sort_order, page=page, per_page=per_page,
    )


@router.post(
    "/documents/bulk-action",
    tags=["queue"],
    response_model=schemas.BulkActionResponse,
    summary="Approve / reject / archive / reassign multiple documents",
)
async def bulk_action(
    payload: schemas.BulkActionRequest,
    background_tasks: BackgroundTasks,
):
    res = service.perform_bulk_action(
        doc_ids=payload.doc_ids,
        action=payload.action,
        performed_by=payload.performed_by or "system",
        reason=payload.reason,
    )
    # If reassign, re-run pipeline for each successful one
    if payload.action == "reassign":
        from app.database import get_supabase
        recs = get_supabase().table("documents").select("id, doc_id").in_("doc_id", payload.doc_ids).execute().data or []
        success_ids = {r["doc_id"] for r in res["results"] if r.get("success")}
        for r in recs:
            if r["doc_id"] in success_ids:
                background_tasks.add_task(service.process_document, r["id"])
    return res


# ============================================================
# 3. LIBRARY
# ============================================================
@router.get(
    "/documents/library",
    tags=["library"],
    summary="Archived documents only — searchable + filterable",
)
async def get_library(
    search: Optional[str] = None,
    type: Optional[str] = None,           # noqa: A002
    tag: Optional[str] = None,
    department: Optional[str] = None,
    view: str = Query("grid", pattern="^(grid|list)$"),
):
    return service.list_library(search=search, type_=type, tag=tag, department=department)


@router.post(
    "/documents/library/export",
    tags=["library"],
    summary="Stream a ZIP of selected (or all) archived documents",
)
async def export_library(payload: schemas.LibraryExportRequest):
    blob = service.export_library_zip(doc_ids=payload.doc_ids)
    if not blob:
        raise HTTPException(404, "No documents to export")
    from datetime import datetime, timezone
    name = f"citadel_archive_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ============================================================
# 4. TEMPLATES
# ============================================================
@router.get("/templates", tags=["templates"], summary="List all templates")
async def list_templates():
    return {"templates": templates.list_templates()}


@router.get("/templates/{template_id}", tags=["templates"])
async def get_template(template_id: str):
    tpl = templates.get_template(template_id)
    if not tpl:
        raise HTTPException(404, "template not found")
    return tpl


@router.post("/templates", tags=["templates"], summary="Create a custom template")
async def create_template(payload: schemas.TemplateCreateRequest):
    fields = [f.model_dump() for f in payload.fields]
    return templates.create_template(name=payload.name, document_type=payload.document_type, fields=fields)


@router.put("/templates/{template_id}", tags=["templates"])
async def update_template(template_id: str, payload: schemas.TemplateUpdateRequest):
    try:
        fields = [f.model_dump() for f in payload.fields] if payload.fields else None
        return templates.update_template(
            template_id=template_id, name=payload.name, fields=fields, passport_key=payload.passport_key,
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.post("/templates/{template_id}/clone", tags=["templates"])
async def clone_template(template_id: str, passport_key: Optional[str] = Query(None)):
    try:
        return templates.clone_template(template_id, passport_key=passport_key)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.post(
    "/templates/{template_id}/verify-access",
    tags=["templates"],
    response_model=schemas.TemplateAccessResponse,
)
async def verify_template_access(template_id: str, payload: schemas.TemplateAccessRequest):
    if not templates.template_requires_passport_key(template_id):
        return {"access_granted": True, "reason": "no passport key required"}
    granted = templates.check_any_user_passport_key(payload.passport_key)
    return {
        "access_granted": granted,
        "reason": None if granted else "invalid passport key",
    }


# ============================================================
# 5. EDIT
# ============================================================
@router.get(
    "/documents/{doc_id}/edit-view",
    tags=["edit"],
    summary="Editable view of a document — fields mapped to its template",
)
async def edit_view(doc_id: str):
    from app.database import get_supabase
    rec = (
        get_supabase().table("documents").select("*").eq("doc_id", doc_id).single()
        .execute().data
    )
    if not rec:
        raise HTTPException(404, "document not found")

    tpl = None
    if rec.get("template_id"):
        tpl = templates.get_template(rec["template_id"])
    if not tpl:
        # find a default template by document_type
        rows = (
            get_supabase().table("templates").select("*")
            .eq("document_type", rec["document_type"]).eq("is_system", False)
            .limit(1).execute().data or []
        )
        tpl = rows[0] if rows else None

    requires_pk = (
        rec.get("status") == "ARCHIVED" and rec.get("priority") == "urgent"
    ) or (tpl and tpl.get("is_system"))

    return {
        "doc_id": doc_id,
        "document_type": rec["document_type"],
        "template_id": tpl["id"] if tpl else None,
        "extracted_fields": rec.get("extracted_fields") or {},
        "template_fields": (tpl or {}).get("fields") or [],
        "extracted_text": rec.get("extracted_text"),
        "requires_passport_key": bool(requires_pk),
    }


@router.put(
    "/documents/{doc_id}/edit-save",
    tags=["edit"],
    summary="Save edits to a document — reindexes vectors automatically",
)
async def edit_save(doc_id: str, payload: schemas.EditSaveRequest):
    from app.database import get_supabase
    from app.modules.document_intelligence import indexer
    from app.utils import audit

    supa = get_supabase()
    rec = supa.table("documents").select("*").eq("doc_id", doc_id).single().execute().data
    if not rec:
        raise HTTPException(404, "document not found")

    # passport-key gate: archived + urgent
    requires_pk = rec.get("status") == "ARCHIVED" and rec.get("priority") == "urgent"
    if requires_pk:
        if not payload.passport_key or not templates.check_any_user_passport_key(payload.passport_key):
            raise HTTPException(403, "passport key required for edit on archived urgent doc")

    update: dict = {}
    if payload.fields:
        update["extracted_fields"] = payload.fields
    if payload.extracted_text is not None:
        update["extracted_text"] = payload.extracted_text
    if payload.title is not None:
        update["title"] = payload.title
    if payload.tags is not None:
        update["tags"] = payload.tags
    if payload.department is not None:
        update["department"] = payload.department

    if update:
        supa.table("documents").update(update).eq("id", rec["id"]).execute()

    audit.write_audit(
        rec["id"], audit.ACTION_EDITED,
        {"fields_changed": list((payload.fields or {}).keys()), "title_changed": payload.title is not None},
    )

    reindexed = False
    new_text = payload.extracted_text or rec.get("extracted_text")
    if new_text:
        try:
            indexer.reindex_document(
                document_id=rec["id"],
                text=new_text,
                document_type=rec["document_type"],
                tags=payload.tags or rec.get("tags") or [],
                department=payload.department or rec.get("department"),
            )
            reindexed = True
        except Exception as e:
            log.warning("re-index after edit failed: %s", e)

    return {"doc_id": doc_id, "saved": True, "reindexed": reindexed}


# ============================================================
# 6. DASHBOARD
# ============================================================
@router.get("/dashboard/stats", tags=["dashboard"])
async def dashboard_stats(period: str = Query("30d", pattern="^(7d|14d|30d|90d)$")):
    return dashboard.get_stats(period)


@router.get("/dashboard/volume", tags=["dashboard"])
async def dashboard_volume(period: str = Query("14d", pattern="^(7d|14d|30d|90d)$")):
    return dashboard.get_volume(period)


@router.get("/dashboard/by-type", tags=["dashboard"])
async def dashboard_by_type(period: str = Query("30d", pattern="^(7d|14d|30d|90d)$")):
    return dashboard.get_by_type(period)


@router.get("/dashboard/top-uploaders", tags=["dashboard"])
async def dashboard_top_uploaders(
    period: str = Query("30d", pattern="^(7d|14d|30d|90d)$"),
    limit: int = Query(5, ge=1, le=20),
):
    return dashboard.get_top_uploaders(period, limit=limit)


@router.get("/dashboard/sla-distribution", tags=["dashboard"])
async def dashboard_sla(period: str = Query("30d", pattern="^(7d|14d|30d|90d)$")):
    return dashboard.get_sla_distribution(period)
