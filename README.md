# CITADEL

**The AI operating system for a city.** A dual-portal municipal governance
platform: eight AI modules across a Government portal and a Citizen portal, one
civic brain. Built for Indian municipalities.

CITADEL reads documents, watches traffic, senses anomalies, answers citizens, and
routes every issue to the desk that can fix it. Every dashboard runs on live data,
behind real authentication, on a sealed data plane.

> Solo-built for the VIT AI Hackathon 2026, then hardened into a full platform:
> real JWT auth, an append-only audit trail, per-account Telegram alerts, an admin
> console, and a neo-brutalist marketing site. Open-sourced as a showcase.

---

## What's inside

**Government portal**
- **Document Intelligence** — OCR + NER + layout analysis with a redaction-aware PII pass.
- **Resume Screening** — semantic candidate matching with a fairness panel that blocks biased auto-decisions.
- **Traffic Violations** — live YOLOv11 detection to auto-drafted challans with annotated evidence, delivered over Telegram. Officers can select and delete incidents (footage removed from DB + storage; challans preserved).
- **Anomaly Monitoring** — real air/weather/flood/quake feeds scored against EPA/WHO/USGS thresholds on a live Leaflet map.

**Citizen portal**
- **AI Assistant** — a vectorless PageIndex reasoning RAG that answers civic questions in the citizen's own language, with traceable sources.
- **Fake News Detector** — a five-layer waterfall (heuristics → transformers → fact-check RAG + NLI → LLM) with honest uncertainty.
- **Support Tickets** — report an issue, AI classifies + routes it to the right department by priority; community upvotes bump priority.
- **Expense Categorizer** — receipt OCR + bank-statement import, layered classifier, anomaly flags, FY tax package.

**Platform**
- **Auth** — argon2id passwords, HS256 JWT with two portal issuers, rotating refresh tokens with theft detection, account lockout. Government and citizen self-signup.
- **Admin console** (gov_admin) — user management (roles / activate), append-only audit viewer, platform stats.
- **Telegram alerts** — any account can point alerts at its own Telegram (shared bot or its own), with an in-app credentials guide and a live test send.
- **Marketing site** — a neo-brutalist hero landing (`index.html`) with GSAP motion.

---

## Architecture

```
index.html            neo-brutalist marketing landing (static)
CITADEL.html          the app shell: portals, routing, dashboards
components.jsx        shared React components + apiFetch + auth session store
pages.jsx             all module screens + the admin console
styles.css            the single neo-brutalist stylesheet
config.js             deploy-time backend URL override (window.CITADEL_API_BASE)

backend/app/
  main.py             FastAPI app, routers, auth-policy middleware, lifespan loops
  core/               security (argon2/JWT), deps, policy middleware
  modules/            one folder per module (auth, admin, telegram, overview,
                      tickets, expenses, traffic_violations, anomaly_monitoring,
                      document_intelligence, resume, citizen_assistant, fake_news)
  shared/             ratelimit, filetype sniff, telegram_config
supabase/migrations/  the DB schema (apply in order)
```

- **Frontend**: standalone React 18 loaded from CDN with **in-browser Babel — no build step, no bundler.** The files above ARE the site. (A dead `src/` Vite tree exists in the repo history; ignore it.)
- **Backend**: FastAPI (Python 3.13 in Docker), local ML (torch CPU, YOLOv11, transformers, spaCy) + Groq LLM (primary, token-frugal), four background loops in the app lifespan.
- **Data**: Supabase (Postgres + storage). The public/anon data API is revoked — the backend (service-role) is the single enforced data path.

**Tech stack**

| Layer | Tech |
|---|---|
| Frontend | React 18 (in-browser Babel), GSAP, Leaflet, brutalist CSS |
| Backend | FastAPI, Python 3.13, Pydantic v2, httpx |
| Auth | argon2id, PyJWT (HS256), rotating refresh tokens |
| ML | YOLOv11 (ultralytics), transformers, sentence-transformers, scikit-learn, spaCy, PyMuPDF, VADER, PageIndex RAG |
| LLM | Groq (llama-3.3-70b) primary, cached per-merchant/claim |
| Data | Supabase (Postgres + Storage), pgvector |
| Deploy | Docker (backend on Render), static (frontend on Vercel) |

---

## Run locally

**Backend**
```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
cp .env.example .env        # fill in your keys (see the file's comments)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Frontend** (static, no build)
```bash
# from the repo root
python serve_frontend.py    # serves http://127.0.0.1:8080/CITADEL.html
# or any static server; index.html is the landing, CITADEL.html is the app
```

**Database**: create a Supabase project and apply `supabase/migrations/*.sql` in order
(via the Supabase SQL editor, or psycopg2 with `SUPABASE_DB_URL`).

**Demo logins** (seeded on first backend boot): government `rsd` / `citadel`
(admin), citizen `citizen` / `citizen`. Or sign up in-app on either portal.

---

## Deployment (Vercel frontend + Render backend + Supabase)

The backend is a long-lived ML process (multi-GB models + 4 background loops), so it
needs a **persistent container** — it cannot be serverless. The frontend is static.
That split is what this repo is configured for. Full rationale + alternatives
(Railway, Fly.io, Hugging Face Spaces, Hetzner) in [`docs/deployment.md`](docs/deployment.md).

### 1. Database — Supabase
1. Create a project at supabase.com. Note the URL, anon key, and service-role key
   (Project Settings → API), and the session-pooler connection string (Settings → Database).
2. Apply every file in `supabase/migrations/` in filename order via the SQL editor.
3. Create storage buckets: `documents`, `processed`, `resumes` (private), `incidents`
   (public). The `tickets` and `receipts` private buckets are auto-created on first use.

### 2. Backend — Render (Docker, via the included Blueprint)
1. Push this repo to GitHub (see below).
2. Render dashboard → **New → Blueprint** → connect the repo. It reads `render.yaml`
   (Docker web service, 2 GB Standard, Singapore, 10 GB disk for model cache, health
   check on `/api/v1/health`).
3. Fill the `sync:false` secrets in the Render dashboard from your `.env`:
   `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL`,
   `JWT_SECRET`, `GROQ_API_KEY`, `GROQ_API_KEY_2` (optional backup), `GEMINI_API_KEY` (optional fallback),
   `OCR_SPACE_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`,
   `GOOGLE_FACTCHECK_API_KEY`, and `CORS_ORIGINS` (your Vercel URL).
4. Deploy. First boot downloads ~3 GB of models to the disk (slow once, cached after).
   Note the service URL, e.g. `https://citadel-backend.onrender.com`.

### 3. Frontend — Vercel (static, no build)
1. Vercel → **Add New → Project** → import the repo.
2. Framework preset: **Other**. Build command: **empty**. Output directory: **`.`** (repo root).
   The site is plain HTML/JSX served as-is; there is nothing to build.
3. After the first deploy, set the backend URL. Edit `config.js`:
   ```js
   window.CITADEL_API_BASE = 'https://citadel-backend.onrender.com';
   ```
   Commit and redeploy (or set it via a Vercel rewrite / env-injected script).
4. `index.html` is the landing; `/CITADEL.html` is the app.
5. Add your `*.vercel.app` origin to the backend `CORS_ORIGINS`. (The backend already
   allow-lists `*.vercel.app` by regex, so preview URLs work automatically.)

### 4. Telegram in production
- Per-account setup (dashboard → Telegram Alerts) needs no infra.
- For the traffic inbound webhook (pay/dispute buttons), point it at the Render URL:
  `POST /api/traffic-violations/telegram/setup-webhook` once the backend is public.

> **Note:** do not deploy the frontend from the stale `.vercel_deploy/` snapshot — it
> predates most of the platform. Deploy from the repo root.

---

## Security posture

- Passwords argon2id; JWT issuers separated per portal; refresh tokens rotate with
  reuse/theft detection; 5-strike account lockout.
- Every government mutation writes to an append-only `audit_log` (UPDATE/DELETE
  revoked at the database).
- The public/anon PostgREST data API is fully revoked — the FastAPI backend is the
  only path to data, and it verifies a JWT on every non-public route (auth-policy
  middleware).
- PII is stripped before classification; attachments live in private buckets behind
  5-minute signed URLs; personal finance is scoped to the owner.

---

## License

MIT. Built for the VIT AI Hackathon 2026.
