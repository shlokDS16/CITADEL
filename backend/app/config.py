"""
Centralized application settings.
All env-driven config goes through this Settings class — never read os.environ
directly elsewhere in the codebase.
"""
from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent  # .../CITADEL/backend


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- Supabase ----
    SUPABASE_URL: str = Field(..., description="https://<project-ref>.supabase.co")
    SUPABASE_ANON_KEY: str = Field(..., description="Public anon JWT")
    SUPABASE_SERVICE_ROLE_KEY: str = Field(..., description="Server-side JWT — full access")

    # ---- OCR Space ----
    OCR_SPACE_API_KEY: str = Field(..., description="ocr.space free-tier API key")
    OCR_SPACE_ENDPOINT: str = "https://api.ocr.space/parse/image"
    OCR_SPACE_MAX_REQUEST_MB: int = 1

    # ---- Groq (document classification) ----
    GROQ_API_KEY: str = Field(..., description="gsk_... primary key")
    #: Optional second key. When the primary returns 429/401/403 (daily
    #: token cap or disabled key), every Groq call transparently retries
    #: on this one. Same model — see app/shared/groq_failover.py.
    GROQ_API_KEY_2: str = Field("", description="gsk_... backup key (optional)")
    #: Current Groq flagship Llama; tuned against every module's prompts and
    #: reliable in JSON mode. `openai/gpt-oss-120b` is a newer/bigger option
    #: but a reasoning model (JSON-format risk) — swap here to A/B it.
    GROQ_CLASSIFIER_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_ENDPOINT: str = "https://api.groq.com/openai/v1/chat/completions"

    # ---- Gemini (cross-provider LLM fallback) ----
    #: Used by the RAG assistant + fake-news Layer-4 rationale when BOTH Groq
    #: keys are drained (100k tokens/day free cap). Exported to os.environ at
    #: startup so LiteLLM's gemini/* routing and the provider chains see it.
    GEMINI_API_KEY: str = Field("", description="AIza... Gemini API key (optional fallback)")

    # ---- Auth (Phase 3) ----
    JWT_SECRET: str = Field(..., description="HS256 signing secret — env only, never in code")
    JWT_ACCESS_MINUTES: int = 30
    JWT_REFRESH_DAYS: int = 14

    # ---- Server ----
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    CORS_ORIGINS: str = "http://127.0.0.1:8080,http://localhost:8080"

    # ---- Storage ----
    SUPABASE_BUCKET_DOCUMENTS: str = "documents"
    SUPABASE_BUCKET_PROCESSED: str = "processed"

    # ---- Limits ----
    MAX_UPLOAD_SIZE_MB: int = 10
    MAX_BATCH_SIZE: int = 10

    # ---- Rate limiting ----
    # Comma list of trusted reverse-proxy IPs / CIDRs. X-Forwarded-For is
    # honored ONLY when the socket peer is inside this set; otherwise the
    # real socket IP is used and XFF is ignored (prevents trivial IP
    # spoofing of the per-IP rate-limit backstop on a direct deployment).
    # Empty (default) = direct deploy, always use the socket peer.
    RL_TRUSTED_PROXIES: str = ""

    # ---- Embeddings ----
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384
    CHUNK_SIZE_TOKENS: int = 500
    CHUNK_OVERLAP_TOKENS: int = 50

    # ---- Resume Screening ----
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_DEFAULT_CHAT_ID: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    SUPABASE_BUCKET_RESUMES: str = "resumes"
    COST_PER_HIRE_RUPEES: int = 18000
    RESUME_AUTO_SHORTLIST_DEFAULT: float = 70.0

    # ---- Fake News Detector (Citizen Module 2) ----
    GOOGLE_FACTCHECK_API_KEY: str = Field("", description="Google Fact Check Tools API key (optional)")
    FN_MODELS_DIR: str = str(BACKEND_ROOT / "models")
    FN_ENABLE_HEAVY_MODELS: bool = True          # propaganda / NLI / deepfake
    FN_HIGH_RISK_THRESHOLD: float = 0.55         # escalate to LLM rationale above this risk
    FN_AUTO_VERDICT_CONFIDENCE: float = 0.80     # below → route to human review (HITL)
    FN_MODEL_FAKE: str = "vikram71198/distilroberta-base-finetuned-fake-news-detection"
    FN_MODEL_CLICKBAIT: str = "valurank/distilroberta-clickbait"
    FN_MODEL_PROPAGANDA: str = "QCRI/PropagandaTechniquesAnalysis-en-BERT"
    FN_MODEL_NLI: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    FN_MODEL_BIAS: str = "d4data/bias-detection-model"
    FN_MODEL_DEEPFAKE: str = "prithivMLmods/AI-vs-Deepfake-vs-Real-Siglip2"
    FN_MODEL_DEEPFAKE_FALLBACK: str = "dima806/deepfake_vs_real_image_detection"
    FN_FACTCHECK_FEEDS: str = (
        "https://factly.in/feed/,"
        "https://www.boomlive.in/fact-check/feed,"
        "https://www.altnews.in/feed/"
    )

    # --- derived helpers ---
    @property
    def fn_models_path(self) -> Path:
        return Path(self.FN_MODELS_DIR)

    @property
    def fn_factcheck_feed_list(self) -> list[str]:
        return [u.strip() for u in self.FN_FACTCHECK_FEEDS.split(",") if u.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def rl_trusted_proxy_nets(
        self,
    ) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for tok in self.RL_TRUSTED_PROXIES.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                nets.append(ipaddress.ip_network(tok, strict=False))
            except ValueError:
                continue
        return nets

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def ocr_max_request_bytes(self) -> int:
        return self.OCR_SPACE_MAX_REQUEST_MB * 1024 * 1024

    @field_validator("APP_ENV")
    @classmethod
    def _validate_env(cls, v: str) -> str:
        v = v.lower()
        if v not in {"development", "staging", "production"}:
            raise ValueError("APP_ENV must be development | staging | production")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — lazily loads .env on first call."""
    return Settings()


settings = get_settings()
