# CITADEL Deployment

Researched 2026-07-21. TL;DR: **your current architecture is already the right one.**
Frontend as static files on Vercel, the heavy ML backend as a Docker container on
Render, Supabase for DB + storage. This doc validates that, ranks the alternatives
for your specific goals, and flags the one thing that will bite you.

## Why the backend cannot be serverless

The backend is not a normal web app. It is a long-lived process that:

- loads multi-GB local model weights (torch CPU, YOLOv11, transformers, spaCy, SigLIP2)
- runs 4 background loops from the FastAPI lifespan (traffic detection pre-warm,
  anomaly open-data refresh every 120s, PageIndex tree build, fake-news feed refresh)
- caches ~3 GB of downloaded models on disk that must survive restarts

Serverless (Vercel Functions, AWS Lambda, Cloud Run scaled-to-zero) breaks all three:
size limits, cold starts on every request, and background loops that stop the moment
the function returns. So the backend needs a **persistent container with a disk**, and
the frontend, which is just static HTML + in-browser Babel, needs nothing more than a
static host. That split is exactly what your `render.yaml` + Vercel setup does.

## The recommendation (what you already have, confirmed best)

| Layer | Host | Why |
|---|---|---|
| Frontend (`index.html` landing, `CITADEL.html` app, jsx/css) | **Vercel** (or Cloudflare Pages) | Static, free, global CDN, custom domain, instant. |
| Backend (FastAPI + ML) | **Render** Web Service (Docker) | Persistent container, native disk for model cache, background loops run in-process, fixed predictable price, health checks. Your `render.yaml` is already correct. |
| DB + storage + buckets | **Supabase** (already hosted) | Keep it. Nothing to move. |
| Telegram | Backend's own public HTTPS URL | Replaces ngrok in production (see below). |

Your `render.yaml` is well done: Docker runtime, Standard plan (2 GB), Singapore region
(closest to India + Supabase), a 10 GB persistent disk mounted at `/data` for
`HF_HOME`/`FN_MODELS_DIR`, health check on `/api/v1/health`, and secrets as `sync:false`.
The Dockerfile pins Python 3.13 + torch CPU (avoids 2 GB of CUDA). No changes needed to
ship.

## Alternatives worth knowing (ranked for YOUR goals)

You are a student, budget-conscious, and using this to attract job / government /
enterprise interest. Against that:

1. **Render (current)** — best predictability and simplicity. Fixed monthly price
   (~$25 Standard/2 GB; bump to Pro/4 GB if the deepfake SigLIP2 model OOMs). Native
   background workers + disks. Stay here unless price bites.
2. **Railway** — the strongest alternative. Cheaper for typical solo workloads,
   near-zero-config from a GitHub repo or your Dockerfile, one-click volumes and
   Postgres, deploys in ~2 minutes. If Render's flat fee feels steep for a demo that
   is idle most of the time, Railway's usage-based billing usually wins.
3. **Fly.io** — most control and lowest latency (runs the container in Singapore/Mumbai
   near your users), persistent volumes, can scale to bigger machines later. Costs a
   CLI + `fly.toml` learning curve. Pick this if you outgrow Render's RAM or want
   multi-region.
4. **Hugging Face Spaces (Docker SDK)** — a genuinely good *showcase* host for a
   job-seeking ML project: free CPU tier, one-click GPU upgrade, and an audience that
   already speaks ML. Caveat: the free tier sleeps on inactivity (your background loops
   pause) and it is demo-grade, not production. Great as a second, public "try it" link
   alongside the real Render deploy.
5. **Cheapest always-on**: a **Hetzner** CAX (ARM) / CPX VPS with Docker + Caddy for
   automatic HTTPS is the best cost-per-RAM for an always-on heavy backend, or
   **Oracle Cloud Free Tier** (Ampere ARM, up to 24 GB RAM free forever) if you are
   willing to self-manage. Most control, least hand-holding.

Do NOT put the backend on Vercel/Netlify/Lambda/Workers — they are serverless and
cannot host this process (see above). Vercel stays frontend-only.

## Critical: the stale `.vercel_deploy/` bundle

`.vercel_deploy/` is a snapshot of the frontend from **2026-06-23**, before all of
Phases 0-6. If you redeploy the frontend from it you will ship the OLD site: no new
hero landing, no admin console, no Telegram setup, no live dashboards, none of this
session's work. **Deploy the frontend from the current repo root instead**, and either
delete `.vercel_deploy/` or regenerate it from the root files.

The frontend files that must ship (repo root): `index.html` (marketing landing, the
default route), `CITADEL.html` (the app), `pages.jsx`, `components.jsx`, `styles.css`,
`tweaks-panel.jsx`, `config.js`, and `CITADEL.html`'s CDN deps (loaded from unpkg/jsdelivr).

## Concrete steps

**Backend (Render):**
1. Render dashboard → New → Blueprint → connect this repo. It reads `render.yaml`.
2. Fill the `sync:false` secrets from `backend/.env`: `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL`, `JWT_SECRET`,
   `GROQ_API_KEY`, `GROQ_API_KEY_2` (optional backup), `GEMINI_API_KEY` (optional fallback),
   `OCR_SPACE_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`,
   `GOOGLE_FACTCHECK_API_KEY`, and set `CORS_ORIGINS` to your Vercel URL.
3. First boot downloads ~3 GB of models to `/data` (slow once, cached after).
4. Note the service URL, e.g. `https://citadel-backend.onrender.com`.

**Frontend (Vercel):**
1. Import the repo. Framework preset: **Other** (no build step). Output = repo root.
2. Set `config.js` so `window.CITADEL_API_BASE` points at the Render URL from above
   (this is the one line that connects frontend to backend).
3. Deploy. `index.html` is the landing; `/CITADEL.html` is the app.
4. Add the resulting `*.vercel.app` origin to the backend `CORS_ORIGINS` (the backend
   already allow-lists `*.vercel.app` via regex, so preview URLs work automatically).

**Telegram in production:**
- The per-account setup (dashboard → Telegram Alerts) needs no infra; it uses the Bot
  API directly.
- For the traffic inbound webhook (pay/dispute buttons), point it at the Render URL
  instead of ngrok: `POST /api/traffic-violations/telegram/setup-webhook` once the
  backend is public.

**Supabase:** already hosted. Apply the migrations in `supabase/migrations/` to any new
project (see Phase 0.1 note — the CLI link is blocked locally by Device Guard, so apply
them via the SQL editor or the psycopg2 helper).
