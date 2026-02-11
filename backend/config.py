# C.I.T.A.D.E.L. Backend Configuration
import os
from dotenv import load_dotenv

load_dotenv()

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mkhsdcxvwitndyfqtaqq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Google AI Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyDSewl6MhI_g--eyjFOjORt3pjM43YcUZ4")

# Model Configuration
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-mpnet-base-v2")
EMBEDDING_DIMENSION = 768
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")  # Validated model name
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434")

# Confidence Thresholds (from gemini.md)
CONFIDENCE_THRESHOLD_LOW = 0.60  # Mandatory human review
CONFIDENCE_THRESHOLD_HIGH = 0.80  # Auto-accept (except enforcement)

# Rate Limits
RATE_LIMIT_CITIZEN = 60  # requests per minute
RATE_LIMIT_ANONYMOUS = 10  # requests per hour
CHAT_SESSION_MAX_MESSAGES = 50

# Service Timeouts
SERVICE_TIMEOUT_SECONDS = 30

# MCP Configuration
MCP_ENABLED = os.getenv("MCP_ENABLED", "true").lower() == "true"
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:8001")

# Feature Flags
ENABLE_PII_DETECTION = True
ENABLE_ACTIVE_LEARNING = True
REQUIRE_HITL_FOR_ENFORCEMENT = True
