"""
CITADEL backend — FastAPI app entry point.

Run from `backend/` directory:
    uvicorn app.main:app --reload --port 8000

Visit:
    http://127.0.0.1:8000/api/v1/health
    http://127.0.0.1:8000/api/v1/docs   (OpenAPI Swagger)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.modules.document_intelligence import router as doc_intel_router
from app.modules.resume import router as resume_router
from app.modules.traffic_violations import router as traffic_router
from app.modules.anomaly_monitoring import router as anomaly_router
from app.modules.citizen_assistant import router as citizen_router
from app.modules.fake_news import router as fake_news_router
from app.modules.tickets import router as tickets_router

# ---- logging ----
logging.basicConfig(
    level=logging.INFO if settings.APP_ENV != "production" else logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("citadel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("CITADEL backend v%s booting in %s mode", __version__, settings.APP_ENV)
    log.info("CORS origins: %s", settings.cors_origin_list)
    log.info("Groq classifier: %s", settings.GROQ_CLASSIFIER_MODEL)

    # Start the Traffic Violations snapshot-detection pre-warm loop (Phase 3++).
    # Keeps /snapshots/detect responses instant by refreshing the cache every 30s.
    try:
        from app.modules.traffic_violations.service import start_background_detection
        start_background_detection()
    except Exception as e:
        log.warning("Failed to start background detection: %s", e)

    # Start the Anomaly Monitoring live-feed refresh loop (Module 4).
    try:
        from app.modules.anomaly_monitoring.service import start_background_refresh
        start_background_refresh()
    except Exception as e:
        log.warning("Failed to start anomaly refresh: %s", e)

    # Prebuild Citizen Assistant PageIndex trees (Citizen Module 1) so the
    # first chat is instant.
    try:
        from app.modules.citizen_assistant.pageindex_engine import start_background_build
        start_background_build()
    except Exception as e:
        log.warning("Failed to start citizen assistant build: %s", e)

    # Fake News Detector (Citizen M2) — seed credibility KB + fact-check
    # feed refresh loop (<=6h). Degrades if Supabase tables are absent.
    try:
        from app.modules.fake_news.service import start_background_feed_refresh
        start_background_feed_refresh()
    except Exception as e:
        log.warning("Failed to start fake-news feed refresh: %s", e)

    yield
    try:
        from app.modules.traffic_violations.service import stop_background_detection
        stop_background_detection()
    except Exception:
        pass
    try:
        from app.modules.anomaly_monitoring.service import stop_background_refresh
        stop_background_refresh()
    except Exception:
        pass
    try:
        from app.modules.fake_news.service import stop_background_feed_refresh
        stop_background_feed_refresh()
    except Exception:
        pass
    log.info("CITADEL backend shutting down")


app = FastAPI(
    title="CITADEL API",
    description="Civic intelligence platform — backend services",
    version=__version__,
    docs_url="/api/v1/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/api/v1/redoc" if settings.APP_ENV != "production" else None,
    openapi_url="/api/v1/openapi.json" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Hosted frontend (Vercel) → this backend (often via an ngrok tunnel):
    # allow any *.vercel.app origin so preview + production deploy URLs work
    # without re-listing each one. Scoped to vercel.app, not a wildcard.
    allow_origin_regex=r"https://[a-z0-9-]+\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "Content-Disposition"],
)


# ---- module routers ----
app.include_router(doc_intel_router, prefix="/api", tags=["document-intelligence"])
app.include_router(resume_router,    prefix="/api", tags=["resume-screening"])
app.include_router(traffic_router,   prefix="/api", tags=["traffic-violations"])
app.include_router(anomaly_router,   prefix="/api", tags=["anomaly-monitoring"])
app.include_router(citizen_router,   prefix="/api", tags=["citizen-assistant"])
app.include_router(fake_news_router, prefix="/api", tags=["fake-news"])
app.include_router(tickets_router,   prefix="/api", tags=["support-tickets"])


# ---- root: friendly landing JSON so visiting `/` doesn't 404 ----
@app.get("/", tags=["meta"], summary="Backend landing — lists the useful URLs")
async def root() -> dict:
    return {
        "name": "CITADEL Backend",
        "version": __version__,
        "env": settings.APP_ENV,
        "docs": "/api/v1/docs",
        "openapi": "/api/v1/openapi.json",
        "health": "/api/v1/health",
        "modules": {
            "document_intelligence": {
                "health":    "/api/v1/doc-intel/health",
                "upload":    "POST /api/documents/upload",
                "queue":     "GET  /api/documents/queue",
                "library":   "GET  /api/documents/library",
                "templates": "GET  /api/templates",
                "dashboard": "GET  /api/dashboard/stats",
            },
        },
    }


# ---- root health (cheap liveness probe) ----
@app.get("/api/v1/health", tags=["meta"])
async def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.APP_ENV,
        "module": "citadel-backend",
    }


# ---- exception fallback ----
@app.exception_handler(Exception)
async def unhandled_exception(request, exc: Exception):
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Please retry; if it persists, contact support.",
            }
        },
    )
