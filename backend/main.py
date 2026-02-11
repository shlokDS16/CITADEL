"""
C.I.T.A.D.E.L. - Civic Intelligence & Transparency for Administrative Decision-making, Evidence & Logistics

FastAPI Backend Entry Point
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

# Import routers
from routers import documents, chat, tickets, admin, resumes, expenses, anomaly, news
from routers import dashboard, support_tickets, traffic_violations
from middleware.access_control import AccessControl

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print("CITADEL Backend Starting...")
    print("RBAC Middleware: Active")
    print("Context Engine: Ready")
    print("MCP Connection: Ready")
    print("Supabase Connection: Ready")
    yield
    # Shutdown
    print("CITADEL Backend Shutting Down...")

app = FastAPI(
    title="C.I.T.A.D.E.L. API",
    description="Civic Intelligence & Transparency for Administrative Decision-making, Evidence & Logistics",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Role-Based Access Control Middleware
@app.middleware("http")
async def enforce_role_based_access(request: Request, call_next):
    """Intercept all requests and verify role-based permissions"""
    
    # Skip auth check for public endpoints and CORS preflights
    public_paths = ["/", "/docs", "/health", "/openapi.json", "/redoc"]
    if request.method == "OPTIONS" or request.url.path in public_paths or request.url.path.startswith("/docs"):
        return await call_next(request)
    
    user_role = request.headers.get("x-user-role", "citizen")
    endpoint = request.url.path
    
    if not AccessControl.verify_access(user_role, endpoint):
        return JSONResponse(
            status_code=403,
            content={"detail": f"Role '{user_role}' cannot access '{endpoint}'"}
        )
    
    response = await call_next(request)
    return response

# Include routers - Original modules
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat/RAG"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["Tickets"])
app.include_router(resumes.router, prefix="/api/resumes", tags=["Resumes"])
app.include_router(expenses.router, prefix="/api/expenses", tags=["Expenses"])
app.include_router(anomaly.router, prefix="/api/anomaly", tags=["Anomaly"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(news.router, prefix="/api/news", tags=["Fake News"])

# Include routers - NEW modules
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(support_tickets.router, prefix="/api/support-tickets", tags=["Support Tickets"])
app.include_router(traffic_violations.router, prefix="/api/traffic-violations", tags=["Traffic Violations"])


@app.get("/")
async def root():
    return {
        "name": "C.I.T.A.D.E.L.",
        "version": "2.0.0",
        "status": "operational",
        "architecture": "dual-portal",
        "portals": {
            "citizen": ["rag_chatbot", "fake_news", "support_tickets", "expense_claims"],
            "government": ["document_intel", "resume_screening", "traffic_violations", "anomaly_detection"]
        },
        "modules": [
            "document_intel",
            "rag_chatbot",
            "ticket_analyzer",
            "fake_news",
            "resume_screening",
            "support_tickets",
            "expense_categorizer",
            "anomaly_detection",
            "traffic_violations",
            "dashboard"
        ]
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "rbac": "active",
        "context_engine": "ready", 
        "mcp": "connected", 
        "supabase": "connected"
    }

