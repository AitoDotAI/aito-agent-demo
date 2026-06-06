# Aito demo template (`aito-agent-demo`)

A starter skeleton that follows every convention `aito-demo-server` enforces. Copy this folder to a new repo, adjust the name + content, push to GitHub, and add one entry to `aito-demo-server/demos.config.yaml`. From scratch to a hosted `<name>.aito.ai` demo in well under an hour.

## What's in the box

**Code (backend):**
- **`pyproject.toml`** — Python 3.12 + uv. FastAPI / uvicorn / httpx / python-dotenv. Dev: pytest + pytest-httpx + booktest.
- **`src/app.py`** — minimal FastAPI app. Has:
  - `GET /health` — cheap liveness probe (returns `{"ok": true}`)
  - `GET /api/health` — Aito-connectivity readiness probe (returns `aito_url`, `aito_connected`)
  - `GET /api/schema` — pass-through to Aito's `/schema` (linked from AitoPanel)
  - `GET /api/example` — hello-world that lists Aito tables
  - Middleware that surfaces `X-Aito-Ms` / `X-Aito-Calls` / `X-Aito-Ops` headers (the topbar LatencyBadge reads these)
  - `StaticFiles(html=True)` mount at `/` serving `frontend/out/` (production = one process)
- **`src/aito_client.py`** — slim sync Aito client. `predict()`, `match()`, `search()`, `get_schema()`, `check_connectivity()`. Records `last_call` for latency middleware.
- **`src/config.py`** — loads `AITO_API_URL` + `AITO_API_KEY` from env. Fails loudly if missing.

**Code (frontend):**
- **`frontend/`** — Next.js 16 + React 19. Configured for static export in production; dev uses next-dev + backend proxy.
- **`frontend/components/shell/`** — `TopBar`, `Nav`, `AitoPanel` (the canonical context/side pane — collapsible right panel showing live query + response time + stats), `ErrorState`, `Analytics`, `LatencyBadge`.
- **`frontend/components/prediction/`** — `PredictionBadge`, `ConfidenceBar`, `WhyTooltip`, `PredictedField`, `WhyCards`, `LiftHint`. The reusable "show a prediction with confidence + explanation" UI.
- **`frontend/lib/api.ts`** — `apiFetch` wrapper (emits latency events for LatencyBadge, throws `ApiError` on non-200), `confClass`, `fmtAmount`.
- **`frontend/lib/aito.ts`** — *optional* browser-side Aito client for direct-from-browser pattern (rare; usually browser → FastAPI → Aito).
- **`frontend/lib/types.ts`** — `Alternative`, `WhyFactor`, `AitoPanelConfig`, etc.
- **`frontend/lib/analytics.ts`** — Amplitude + GA4 init from `NEXT_PUBLIC_AMPLITUDE_KEY` / `NEXT_PUBLIC_GA4_MEASUREMENT_ID`.
- **`frontend/public/`** — `aito-logo.svg`, `aito-favicon.svg`, `aito-panel-bg.png` (background image used by AitoPanel).

**Operational:**
- **`do`** — wrapper for all common workflows. `./do help` for the list.
- **`.env.example`** — the env contract.
- **`shell.nix`** — Nix dev shell (Python 3.12 + uv + Node 20 + Playwright + dev tools). `nix-shell` to enter; auto-runs `uv sync` and loads `.env`.

**Tests:**
- **`tests/test_health.py`** — plain pytest (no Aito).
- **`book/test_01_aito_schema_book.py`** — booktest snapshot example (Aito-dependent; replays from `books/` on subsequent runs).
- **`booktest.ini`** — booktest config.

**Screenshots / regression:**
- **`frontend/scripts/screenshot-teaser.cjs`** — renders `assets/teaser.html` → `assets/teaser.png` (1200×630, the size the landing page wants).
- **`frontend/scripts/screenshot-pages.cjs`** — desktop full-page screenshots of given paths (regression baseline).
- **`frontend/scripts/inspect-mobile.cjs`** — iPhone-sized screenshots for layout review.

**Docs:**
- **`README.md`** (this file) — bootstrap workflow.
- **`CLAUDE.md`** — agent instructions: platform conventions, common pitfalls, where to start.
- **`CHEATSHEET.md`** — Aito query cookbook (predict / match / search / multi-tenant / common where clauses).
- **`CHECKLIST.md`** — pre-launch checklist covering code, branding, analytics, product sheet, deploy.

**Assets:**
- **`assets/teaser.html`** — source for the teaser image (edit visually, regenerate the PNG).
- **`assets/teaser.png`** — the actual file consumed by the platform's landing page (regenerate via `./do screenshot-teaser`).
- **`assets/README.md`** — what the platform expects.

## Bootstrap workflow

```bash
# 1. Copy and rename
cp -r /home/arau/episto/src/aito-demo-server/template /home/arau/episto/src/aito-<NAME>-demo
cd /home/arau/episto/src/aito-<NAME>-demo

# 2. Find & replace the placeholder name
#    (search for HELLO, hello-demo, predictive-agent, etc.)
grep -rl "HELLO\|hello-demo\|predictive-agent" . --exclude-dir=node_modules --exclude-dir=.venv

# 3. Generate lockfiles so the platform's `--frozen` install works
uv lock
cd frontend && npm install && cd ..

# 4. Replace assets/teaser.png with your own (1200×630 ish, dark navy bg, purple accent)

# 5. git init, commit, push to github.com/AitoDotAI/aito-<NAME>-demo
git init && git add -A && git commit -m "Initial commit from aito-agent-demo template"
gh repo create AitoDotAI/aito-<NAME>-demo --private --source=. --push

# 6. In aito-demo-server, add the yaml entry
cd /home/arau/episto/src/aito-demo-server
./do add-demo <NAME>           # appends a scaffold to demos.config.yaml
# edit the new entry: set source.repo, ref: main (or a SHA), and teaser copy

# 7. Validate + smoke build locally
./do check
./do build                      # ~5-10 min cold
./do up                         # http://localhost:8080 — your demo at Host: <NAME>.aito.ai

# 8. Deploy via aito-azure
cd /home/arau/episto/src/aito-azure
./do deploy-demos               # pushes to ACR + updates the unified Web App
```

## What you'd typically replace

- **`src/app.py`** — add your own `@app.get("/api/...")` routes. The `/health` and `/api/health` routes can stay verbatim; the StaticFiles mount must remain the LAST thing in the file (it shadows everything else at `/`).
- **`src/config.py`** — extend if your demo needs more env vars. Keep the fail-loud pattern.
- **`frontend/app/page.tsx`** — your UI.
- **`pyproject.toml`** — add any additional Python deps you need.
- **`frontend/package.json`** — add any additional JS deps you need.
- **`assets/teaser.html`** — design your teaser, then `./do screenshot-teaser` to regenerate the PNG.
- **`README.md`** — replace this file with one for your specific demo.
- **`CLAUDE.md`** — trim sections you don't need, add demo-specific guidance.
- **`book/test_01_aito_schema_book.py`** — adapt to test your demo's actual queries (use as a pattern; add more `book/test_NN_*.py` files for each capability you want snapshot-tested).
- **`tests/test_health.py`** — add unit tests for any pure logic in your routes.

Walk **`CHECKLIST.md`** before declaring done.

## What you should NOT change (without a good reason)

- **`frontend/next.config.ts`** — the `output: "export"` + dev rewrite pattern is what lets the platform run you as a single uvicorn process. Diverging means you need `extra_processes` in `demos.config.yaml` and the operator complexity that comes with that.
- **`src/app.py`'s StaticFiles mount line** — the platform expects `frontend/out/` to be served at `/` from the same uvicorn process as `/api/*`.
- **`/health` endpoint** — nginx in the platform's container proxies `<demo>.aito.ai/health` to this route; if it 404s, monitoring breaks.
- **Env var names** — `AITO_API_URL` + `AITO_API_KEY` is the canonical pair the platform's `env:` block remaps from per-demo secrets (`AITO_<DEMO_NAME>_API_URL`). Picking different names means adjusting the yaml.

## Local development

```bash
./do install     # uv sync + npm install
./do dev         # runs uvicorn (backend) + next dev (frontend) on separate ports
                 # frontend proxies /api/* to backend; hot-reload on both
```

In dev, the frontend (UI) listens on `4100` (configurable via `FRONTEND_PORT`) and the backend on `4101` (configurable via `BACKEND_PORT`) — picked in the 4100+ range to avoid common local port conflicts. The next.config.ts proxy rewrite is dev-only — production builds skip it and FastAPI serves both `/api/*` and the static UI from the single `PORT` the platform assigns.

## Where this lives

This template is committed inside `aito-demo-server/template/` rather than as a separate repo. Rationale: the platform's conventions evolve over time (env-var naming, `/health` shape, Next.js output config) and co-locating the template means a single PR updates both the platform and the canonical example. New demo repos are forks-by-copy from this folder, not git clones from a separate template repo.

If you change the platform conventions, update this template in the same PR.
