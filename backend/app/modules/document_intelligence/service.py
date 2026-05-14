"""
Service layer — all business logic for Document Intelligence.

Routers stay thin: parse → call service → format response.
Services orchestrate: validate → call pipeline modules + utils → write to DB → audit.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from app.config import settings
from app.database import get_supabase
from app.modules.document_intelligence import classifier, extractor, indexer, ocr, pii, signature
from app.utils import audit, doc_id, storage

log = logging.getLogger("citadel.doc_intel.service")

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}

# ============================================================
# UPLOAD
# ============================================================
def upload_files(
    files: list[tuple[bytes, str, str]],   # (content, filename, mime_type)
    document_type: str = "auto_detect",
    language: str = "en",
    priority: str = "normal",
    detect_redact_pii: bool = False,
    signature_validation: bool = False,
    uploaded_by: str = "system",
) -> dict[str, Any]:
    """
    Validate + persist + create DB rows. Returns batch_id + per-doc storage paths.
    Caller is responsible for scheduling background processing for each doc id.
    """
    if not files:
        raise ValueError("No files supplied")
    if len(files) > settings.MAX_BATCH_SIZE:
        raise ValueError(f"Too many files. Max {settings.MAX_BATCH_SIZE} per batch")

    batch_id = uuid4()
    supa = get_supabase()
    created: list[dict[str, str]] = []

    for content, filename, mime in files:
        # ---- validate ----
        if mime not in ALLOWED_MIME:
            raise ValueError(f"Unsupported file type: {mime} ({filename})")
        if len(content) > settings.max_upload_bytes:
            raise ValueError(f"File too large: {filename} ({len(content)/1024/1024:.1f}MB)")

        # ---- store original ----
        path, _ = storage.upload_original(content, filename)

        # ---- DB row ----
        new_doc_id = doc_id.generate_doc_id()
        row = {
            "doc_id": new_doc_id,
            "batch_id": str(batch_id),
            "filename": filename,
            "original_filename": filename,
            "document_type": document_type,            # may be 'auto_detect' until pipeline resolves
            "status": "PROCESSING",
            "priority": priority,
            "language": language,
            "pii_enabled": detect_redact_pii,
            "signature_enabled": signature_validation,
            "uploaded_by": uploaded_by,
            "file_size_bytes": len(content),
            "mime_type": mime,
            "storage_path": path,
        }
        ins = supa.table("documents").insert(row).execute()
        if not ins.data:
            raise RuntimeError(f"Failed to insert {filename}")
        db_id = ins.data[0]["id"]

        audit.write_audit(
            document_id=db_id,
            action=audit.ACTION_UPLOADED,
            details={"filename": filename, "size_bytes": len(content), "batch_id": str(batch_id)},
            performed_by=uploaded_by,
        )

        created.append({"doc_id": new_doc_id, "filename": filename, "storage_path": path, "id": db_id})

    return {"batch_id": batch_id, "documents": created, "total": len(created)}


# ============================================================
# BACKGROUND PIPELINE
# ============================================================
def process_document(db_id: str) -> None:
    """
    Full text-extraction + classification + PII + signature + index pipeline.
    Runs in a FastAPI BackgroundTasks worker (single-process, in-thread).
    Never raises — all errors become DB status='REJECTED' + audit entry.
    """
    supa = get_supabase()
    try:
        row = supa.table("documents").select("*").eq("id", db_id).single().execute().data
    except Exception as e:
        log.exception("process_document: cannot find db_id=%s: %s", db_id, e)
        return

    doc_pk = row["id"]
    doc_alias = row["doc_id"]
    storage_path = row["storage_path"]
    mime = row["mime_type"]
    declared_type = row["document_type"]
    language = row["language"] or "en"
    pii_enabled = bool(row["pii_enabled"])
    sig_enabled = bool(row["signature_enabled"])

    log.info("processing %s (%s, %s)", doc_alias, mime, language)

    try:
        content = storage.download_bytes(settings.SUPABASE_BUCKET_DOCUMENTS, storage_path)
    except Exception as e:
        log.exception("download failed for %s", doc_alias)
        _fail_doc(doc_pk, doc_alias, f"download_failed: {e}")
        return

    # ---- 1. Extract text ----
    extraction = _extract(content, mime, language)
    if not extraction["text"]:
        _fail_doc(doc_pk, doc_alias, "no text could be extracted")
        return

    # ---- 2. Classification ----
    if declared_type == "auto_detect":
        cls = classifier.classify_document(extraction["text"])
        resolved_type = cls.document_type
        detected_type = cls.document_type
    else:
        resolved_type = declared_type
        detected_type = None

    audit.write_audit(doc_pk, audit.ACTION_CLASSIFIED, {"document_type": resolved_type})

    # ---- 3. PII ----
    pii_results: dict[str, Any] = {}
    redacted_text: Optional[str] = None
    pii_count_total = 0
    if pii_enabled:
        pii_results = pii.detect_pii(extraction["text"])
        pii_count_total = pii.total_pii_count(pii_results)
        redacted_text = pii.redact_text(extraction["text"], pii_results)
        audit.write_audit(
            doc_pk, audit.ACTION_PII_DETECTED,
            {"types": list(pii_results.keys()), "total": pii_count_total},
        )

    # ---- 4. Signature ----
    sig_status: Optional[str] = None
    if sig_enabled:
        try:
            if mime == "application/pdf":
                sig_status = signature.detect_signature_in_pdf(content)
            elif mime in {"image/jpeg", "image/png"}:
                sig_status = signature.detect_signature_in_image(content)
            else:
                sig_status = "not_found"
            audit.write_audit(doc_pk, audit.ACTION_SIGNATURE_DETECTED, {"status": sig_status})
        except Exception as e:
            log.warning("signature detection failed for %s: %s", doc_alias, e)
            sig_status = "unclear"

    # ---- 5. Tags (lightweight) ----
    tags = _generate_tags(resolved_type, extraction["text"])

    # ---- 6. Confidence — combine extractor + classifier ----
    confidence = round((extraction["confidence"] + classifier_confidence(declared_type, resolved_type)) / 2, 2)

    # ---- 7. Update document row ----
    update = {
        "status": "PENDING_REVIEW",
        "document_type": resolved_type,
        "detected_type": detected_type,
        "confidence": confidence,
        "extracted_text": extraction["text"],
        "redacted_text": redacted_text,
        "pii_results": pii_results,
        "pii_count": pii_count_total,
        "signature_status": sig_status,
        "tags": tags,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    supa.table("documents").update(update).eq("id", doc_pk).execute()
    audit.write_audit(doc_pk, audit.ACTION_PROCESSED, {"confidence": confidence})

    # ---- 8. Vector index for future RAG ----
    try:
        n = indexer.index_document(
            document_id=doc_pk,
            text=extraction["text"],
            document_type=resolved_type,
            tags=tags,
            department=row.get("department"),
        )
        audit.write_audit(doc_pk, audit.ACTION_INDEXED, {"chunks": n})
    except Exception as e:
        log.warning("indexing failed for %s: %s", doc_alias, e)


def _extract(content: bytes, mime: str, language: str) -> dict:
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        r = extractor.extract_docx(content)
        return {"text": r.text, "confidence": r.confidence, "page_count": r.page_count}

    if mime == "application/pdf":
        r = extractor.extract_pdf_digital(content)
        if r.source == "pdf-digital" and r.text:
            return {"text": r.text, "confidence": r.confidence, "page_count": r.page_count}
        # fallback to OCR
        ocr_r = ocr.ocr_pdf(content, language=language)
        return {"text": ocr_r.text, "confidence": ocr_r.confidence, "page_count": ocr_r.page_count}

    if mime in {"image/jpeg", "image/png"}:
        ocr_r = ocr.ocr_image(content, language=language)
        return {"text": ocr_r.text, "confidence": ocr_r.confidence, "page_count": 1}

    return {"text": "", "confidence": 0.0, "page_count": 0}


def classifier_confidence(declared: str, resolved: str) -> float:
    """If user declared a specific type, trust them at 95. Auto-detect uses 90."""
    if declared != "auto_detect":
        return 95.0
    return 90.0  # tuned with classifier output method later


def _generate_tags(doc_type: str, text: str) -> list[str]:
    """Cheap tag generation — doc type + month/year + a few civic keywords."""
    tags: list[str] = [doc_type]

    now = datetime.now(timezone.utc)
    tags.extend([f"q{(now.month - 1)//3 + 1}", str(now.year)])

    keywords = [
        ("finance", ["invoice", "payment", "amount", "rupees", "rs.", "gst"]),
        ("legal",   ["agreement", "court", "affidavit", "deponent", "jurisdiction"]),
        ("infra",   ["road", "bridge", "construction", "ward", "zone"]),
        ("hr",      ["resume", "candidate", "salary", "appointment"]),
        ("permit",  ["permit", "permission", "authority", "license"]),
    ]
    lower = text.lower()[:5000]
    for tag, kws in keywords:
        if any(kw in lower for kw in kws):
            tags.append(tag)
    return list(dict.fromkeys(tags))   # preserves order, dedupes


def _fail_doc(db_id: str, doc_alias: str, reason: str) -> None:
    log.error("Failing %s: %s", doc_alias, reason)
    get_supabase().table("documents").update(
        {"status": "REJECTED", "rejected_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", db_id).execute()
    audit.write_audit(db_id, audit.ACTION_FAILED, {"reason": reason})


# ============================================================
# RESULTS / EXPORT
# ============================================================
def get_batch_results(batch_id: str) -> dict[str, Any]:
    rows = (
        get_supabase().table("documents")
        .select("*").eq("batch_id", batch_id).execute().data or []
    )
    if not rows:
        return {
            "batch_id": batch_id, "total_processed": 0, "successful": 0, "failed": 0,
            "avg_confidence": 0, "pii_found_total": 0, "documents": [],
        }

    successful = sum(1 for r in rows if r["status"] in {"PENDING_REVIEW", "APPROVED", "ARCHIVED"})
    failed = sum(1 for r in rows if r["status"] == "REJECTED")
    confidences = [r["confidence"] for r in rows if r.get("confidence") is not None]
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0
    pii_total = sum(int(r.get("pii_count") or 0) for r in rows)

    docs = [
        {
            "doc_id": r["doc_id"],
            "filename": r["filename"],
            "document_type": r["document_type"],
            "confidence": r.get("confidence"),
            "status": r["status"],
            "pii_results": r.get("pii_results") or {},
            "signature_status": r.get("signature_status"),
            "tags": r.get("tags") or [],
            "extracted_text_preview": (r.get("extracted_text") or "")[:200],
        }
        for r in rows
    ]

    return {
        "batch_id": batch_id,
        "total_processed": len(rows),
        "successful": successful,
        "failed": failed,
        "avg_confidence": avg_conf,
        "pii_found_total": pii_total,
        "documents": docs,
    }


def export_batch_csv(batch_id: str) -> str:
    import csv
    res = get_batch_results(batch_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "doc_id", "filename", "document_type", "confidence", "status",
        "pii_count", "signature_status", "tags",
    ])
    for d in res["documents"]:
        writer.writerow([
            d["doc_id"], d["filename"], d["document_type"],
            d.get("confidence") or "", d["status"],
            sum(v.get("count", 0) for v in d.get("pii_results", {}).values()),
            d.get("signature_status") or "",
            ";".join(d.get("tags") or []),
        ])
    return buf.getvalue()


# ============================================================
# AUDIT LOG
# ============================================================
def get_audit_log(doc_alias: str) -> dict[str, Any]:
    supa = get_supabase()
    docs = supa.table("documents").select("id").eq("doc_id", doc_alias).execute().data or []
    if not docs:
        raise LookupError(f"document {doc_alias!r} not found")
    db_id = docs[0]["id"]
    entries = (
        supa.table("audit_log").select("*")
        .eq("document_id", db_id).order("created_at", desc=False).execute().data or []
    )
    return {"doc_id": doc_alias, "entries": entries}


# ============================================================
# ACTIONS
# ============================================================
ACTION_TO_STATUS = {
    "approve": ("APPROVED", "approved_at", audit.ACTION_APPROVED),
    "reject":  ("REJECTED", "rejected_at", audit.ACTION_REJECTED),
    "archive": ("ARCHIVED", "archived_at", audit.ACTION_ARCHIVED),
    # "reassign" is special — handled below
}


def perform_action(
    doc_alias: str,
    action: str,
    performed_by: str = "system",
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """One-doc state transition — approve | reject | archive | reassign."""
    supa = get_supabase()

    rec = supa.table("documents").select("*").eq("doc_id", doc_alias).single().execute().data
    if not rec:
        return {"doc_id": doc_alias, "action": action, "new_status": "REJECTED", "success": False, "message": "not found"}

    if action == "reassign":
        update = {
            "status": "PROCESSING",
            "approved_at": None,
            "archived_at": None,
            "rejected_at": None,
            "processed_at": None,
            "extracted_text": None,
            "redacted_text": None,
            "pii_results": None,
            "pii_count": 0,
            "signature_status": None,
            "tags": [],
            "confidence": None,
        }
        supa.table("documents").update(update).eq("id", rec["id"]).execute()
        audit.write_audit(rec["id"], audit.ACTION_REASSIGNED, {"reason": reason}, performed_by=performed_by)
        # Caller (router) is responsible for scheduling process_document(id) in BG
        return {"doc_id": doc_alias, "action": action, "new_status": "PROCESSING", "success": True}

    if action not in ACTION_TO_STATUS:
        return {"doc_id": doc_alias, "action": action, "new_status": rec["status"], "success": False, "message": "unknown action"}

    new_status, ts_field, audit_action = ACTION_TO_STATUS[action]
    now_iso = datetime.now(timezone.utc).isoformat()
    supa.table("documents").update({"status": new_status, ts_field: now_iso}).eq("id", rec["id"]).execute()
    audit.write_audit(rec["id"], audit_action, {"reason": reason}, performed_by=performed_by)
    return {"doc_id": doc_alias, "action": action, "new_status": new_status, "success": True}


def perform_bulk_action(
    doc_ids: list[str], action: str, performed_by: str = "system", reason: Optional[str] = None
) -> dict[str, Any]:
    if action == "delete":
        results = [delete_document(d, performed_by) for d in doc_ids]
    else:
        results = [perform_action(d, action, performed_by, reason) for d in doc_ids]
    return {
        "requested": len(doc_ids),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
    }


# ============================================================
# DELETE — hard delete with cascade
# ============================================================
def delete_document(doc_alias: str, performed_by: str = "system") -> dict[str, Any]:
    """
    Hard delete a document. Cascades:
      - removes original from storage bucket `documents`
      - removes processed file from `processed` (if any)
      - DB cascades remove document_chunks (ON DELETE CASCADE)
      - DB cascades remove audit_log (ON DELETE CASCADE)
    """
    supa = get_supabase()
    rec = supa.table("documents").select("*").eq("doc_id", doc_alias).single().execute().data
    if not rec:
        return {"doc_id": doc_alias, "action": "delete", "new_status": "REJECTED", "success": False, "message": "not found"}

    # Best-effort storage cleanup (don't fail the whole delete if storage is gone)
    try:
        if rec.get("storage_path"):
            storage.delete_object(settings.SUPABASE_BUCKET_DOCUMENTS, rec["storage_path"])
    except Exception as e:
        log.warning("delete: original storage cleanup failed for %s: %s", doc_alias, e)
    try:
        if rec.get("processed_storage_path"):
            storage.delete_object(settings.SUPABASE_BUCKET_PROCESSED, rec["processed_storage_path"])
    except Exception as e:
        log.warning("delete: processed storage cleanup failed for %s: %s", doc_alias, e)

    # DB delete (cascades to document_chunks + audit_log via FK ON DELETE CASCADE)
    supa.table("documents").delete().eq("id", rec["id"]).execute()

    log.info("Document %s permanently deleted by %s", doc_alias, performed_by)
    return {"doc_id": doc_alias, "action": "delete", "new_status": "DELETED", "success": True}


# ============================================================
# QUEUE (Phase 4)
# ============================================================
def list_queue(
    search: Optional[str] = None,
    status: Optional[str] = None,
    type_: Optional[str] = None,
    priority: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    per_page: int = 20,
) -> dict[str, Any]:
    supa = get_supabase()
    q = supa.table("documents").select("*", count="exact")

    if status:
        q = q.eq("status", status.upper())
    if type_:
        q = q.eq("document_type", type_.lower())
    if priority:
        q = q.eq("priority", priority.lower())
    if search:
        # case-insensitive partial match on filename
        q = q.ilike("filename", f"%{search}%")

    if sort_by not in {"created_at", "priority", "confidence"}:
        sort_by = "created_at"
    q = q.order(sort_by, desc=(sort_order.lower() == "desc"))

    page = max(1, page)
    per_page = min(100, max(1, per_page))
    start = (page - 1) * per_page
    end = start + per_page - 1
    q = q.range(start, end)

    res = q.execute()
    rows = res.data or []
    total = res.count or len(rows)

    items = [_to_summary(r) for r in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def _to_summary(r: dict) -> dict:
    """Shape a db row into the queue/library summary view."""
    created = r.get("created_at")
    if isinstance(created, str):
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            created_dt = None
    else:
        created_dt = created
    time_ago = _humanize_delta(created_dt) if created_dt else None

    return {
        "doc_id": r["doc_id"],
        "filename": r["filename"],
        "document_type": r["document_type"],
        "status": r["status"],
        "priority": r["priority"],
        "confidence": r.get("confidence"),
        "language": r.get("language", "en"),
        "tags": r.get("tags") or [],
        "department": r.get("department"),
        "title": r.get("title"),
        "uploaded_by": r.get("uploaded_by"),
        "file_size_bytes": r.get("file_size_bytes"),
        "mime_type": r.get("mime_type"),
        "created_at": r["created_at"],
        "processed_at": r.get("processed_at"),
        "approved_at": r.get("approved_at"),
        "archived_at": r.get("archived_at"),
        "rejected_at": r.get("rejected_at"),
        "sla_breached": _is_sla_breached(r),
        "time_ago": time_ago,
        "pii_count": int(r.get("pii_count") or 0),
        "pii_results": r.get("pii_results") or {},
        "signature_status": r.get("signature_status"),
    }


def _humanize_delta(dt: datetime) -> str:
    delta = datetime.now(timezone.utc) - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
    s = int(delta.total_seconds())
    if s < 60: return f"{s} sec"
    if s < 3600: return f"{s // 60} min"
    if s < 86400: return f"{s // 3600} hr"
    return f"{s // 86400} day"


def _is_sla_breached(r: dict) -> bool:
    if r["status"] in {"APPROVED", "ARCHIVED", "REJECTED"}:
        return False
    created = r.get("created_at")
    if not created:
        return False
    if isinstance(created, str):
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            return False
    if not created.tzinfo:
        created = created.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - created
    thresholds = {
        "urgent": timedelta(minutes=15),
        "high":   timedelta(hours=1),
        "normal": timedelta(hours=4),
        "low":    timedelta(hours=24),
    }
    return age > thresholds.get(r["priority"], timedelta(days=999))


# ============================================================
# LIBRARY (Phase 4)
# ============================================================
def list_library(
    search: Optional[str] = None,
    type_: Optional[str] = None,
    tag: Optional[str] = None,
    department: Optional[str] = None,
) -> dict[str, Any]:
    supa = get_supabase()
    q = supa.table("documents").select("*", count="exact").eq("status", "ARCHIVED")
    if type_:
        q = q.eq("document_type", type_.lower())
    if department:
        q = q.eq("department", department)
    if tag:
        q = q.contains("tags", [tag])
    if search:
        q = q.or_(f"filename.ilike.%{search}%,title.ilike.%{search}%")
    q = q.order("archived_at", desc=True)
    res = q.execute()
    rows = res.data or []

    items: list[dict] = []
    for r in rows:
        size_b = int(r.get("file_size_bytes") or 0)
        item = {
            "doc_id": r["doc_id"],
            "document_type": r["document_type"],
            "title": r.get("title"),
            "filename": r["filename"],
            "file_size": _format_size(size_b),
            "file_size_bytes": size_b,
            "tags": r.get("tags") or [],
            "department": r.get("department"),
            "archived_at": r.get("archived_at"),
            "mime_type": r.get("mime_type"),
            "status": r["status"],
            "priority": r.get("priority", "normal"),
            "confidence": r.get("confidence"),
            "uploaded_by": r.get("uploaded_by"),
            "pii_results": r.get("pii_results") or {},
            "pii_count": int(r.get("pii_count") or 0),
            "signature_status": r.get("signature_status"),
        }
        # Pre-signed download URL (5 min)
        path = r.get("storage_path")
        if path:
            try:
                item["storage_url"] = storage.signed_url(settings.SUPABASE_BUCKET_DOCUMENTS, path)
            except Exception as e:
                log.warning("signed_url failed for %s: %s", r["doc_id"], e)
                item["storage_url"] = None
        items.append(item)
    return {"items": items, "total": res.count or len(rows)}


def export_library_zip(doc_ids: Optional[list[str]] = None, max_docs: int = 100) -> bytes:
    """Build an in-memory ZIP of the requested archived docs."""
    supa = get_supabase()
    q = supa.table("documents").select("*").eq("status", "ARCHIVED")
    if doc_ids:
        q = q.in_("doc_id", doc_ids)
    q = q.order("archived_at", desc=True).limit(max_docs)
    rows = q.execute().data or []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            try:
                blob = storage.download_bytes(settings.SUPABASE_BUCKET_DOCUMENTS, r["storage_path"])
                safe_name = f"{r['doc_id']}_{r['filename']}"
                zf.writestr(safe_name, blob)

                if r.get("extracted_text"):
                    zf.writestr(f"{r['doc_id']}_extracted.txt", r["extracted_text"])
            except Exception as e:
                log.warning("zip include failed for %s: %s", r["doc_id"], e)
    return buf.getvalue()


def _format_size(b: int) -> str:
    if b < 1024: return f"{b} B"
    if b < 1024 * 1024: return f"{b / 1024:.1f} KB"
    return f"{b / 1024 / 1024:.1f} MB"
