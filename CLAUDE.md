# CITADEL — Claude Operating Manual

> **Project**: C.I.T.A.D.E.L. — Centralized Intelligence & Technology Administration Dashboard for Enhanced Living
> **Status**: Frontend complete (neo-brutalist, mock-driven). Backend rebuild in progress.
> **Stack**: React 18 (in-browser Babel) · FastAPI (planned) · Python ML stack · SQLite/Postgres TBD

---

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Only touch what's necessary. No side effects with new bugs.

---

## Project-Specific Context

### Architecture (current state)
- **Frontend** (root files): `CITADEL.html`, `components.jsx`, `pages.jsx`, `styles.css`, `tweaks-panel.jsx`
  - Standalone React 18 with in-browser Babel — **NO build step**, **NO bundler**
  - Components attach to `window` for cross-file access
  - Neo-brutalist theme: 3px borders, 6px hard shadows, 0 radius, gold/red/cyan/green palette
  - All data is currently mocked inside the JSX files
- **Backend** (`backend/`): legacy code — being rebuilt from scratch
- **Eight modules**:
  - **Government**: Document Intelligence · Resume Screening · Traffic Violations · Anomaly Monitoring
  - **Citizen**: RAG Chatbot · Fake News Detector · Support Tickets · Expense Categorizer

### Hard Rules
1. **NEVER** introduce a build step (Vite/Webpack) for the frontend without explicit approval. Standalone HTML stays standalone.
2. **NEVER** alter the neo-brutalist visual language (borders, shadows, palette, fonts). Cosmetic decisions go through `ui-ux-pro-max` skill.
3. **NEVER** wire real backend calls into the frontend until the relevant module's API contract is signed off in `docs/module-specs/`.
4. **ALWAYS** keep the mock data in `pages.jsx` working — backend is opt-in via a flag, not a replacement.
5. **ALWAYS** consult `.claude/rules/` for the conventions of the surface you're touching.

### Specialist Skills (auto-invoke when relevant)
- `anthropic-skills:master-backend-builder` — for any backend work (FastAPI, schemas, services, deployment)
- `anthropic-skills:ui-ux-pro-max` (or `userSettings:ui-ux-pro-max`) — for any UI/UX decision
- `engineering:code-review` — before declaring a non-trivial change done
- `engineering:debug` — when behavior diverges from expected
- `design:accessibility-review` — before shipping any new screen

### Specialist Subagents (in `.claude/agents/`)
- `backend-architect` — designs FastAPI module boundaries and data flow
- `ml-pipeline-engineer` — builds inference pipelines for the 8 ML modules
- `api-contract-validator` — ensures frontend mocks and backend responses match shape-by-shape
- `security-auditor` — reviews PII handling, RBAC for gov vs. citizen, auth surfaces
- `frontend-mock-curator` — keeps mock data realistic and matched to backend contracts

### Slash Commands (in `.claude/commands/`)
- `/scaffold-module <name>` — scaffold a backend module from its frontend mock
- `/connect-frontend <module>` — wire a backend endpoint to its frontend module behind a flag
- `/contract-check <module>` — diff frontend mock shapes against backend response schemas
- `/seed-mocks <module>` — generate realistic mock data for a module
- `/module-status` — table of where each of the 8 modules stands (mock / contract / backend / wired / tested)
- `/pre-backend-checklist` — run the readiness checklist before touching a new module

### Reference Docs
- `docs/architecture.md` — system overview and module map
- `docs/backend-blueprint.md` — planned FastAPI structure
- `docs/module-specs/` — one spec per module, cross-referenced to frontend mocks

---

## Session Start Ritual
1. Read `tasks/todo.md` to see what's in flight
2. Skim `tasks/lessons.md` for patterns from prior corrections
3. Confirm working directory is `C:\Users\Shlok\Downloads\CITADEL\`
4. Confirm the local server is up (or start it: `python -m http.server 8080`)
