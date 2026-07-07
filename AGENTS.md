# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project

Story Pointer: an evidence-led story-point estimator (modified Fibonacci 1/2/3/5/8/13) for React/Spring teams. FastAPI backend runs a checkpointed LangGraph pipeline and streams progress over SSE; React 19 + Vite frontend (Material 3 shell) consumes the stream. Stories come from a form, Jira, a spreadsheet upload, or — via the project workspace — from L3 components of an interactive C4 model whose points roll up to epics and initiatives. Each L1 initiative can also carry an operating plan (teams, cost, schedule, architecture diagrams).

## Commands

Run everything from the repository root. Python 3.11+, Node 20+.

```powershell
# setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env   # then fill in LLM_* keys
npm install
Copy-Item frontend\.env.example frontend\.env

# run (two terminals)
uvicorn backend.api.main:app --reload --port 8000
npm run dev                                    # Vite on http://localhost:5173

python scripts/seed_demo.py                    # small demo project + C4 model
python scripts/seed_banking.py                 # richer multi-level banking sample

# tests
pytest backend/tests -q                        # backend
pytest backend/tests/test_mapping.py -q        # one file
pytest backend/tests/test_l1_planning.py::test_full_operating_plan_and_cost_metrics -q   # one test
npm test                                       # frontend (vitest run, all files)
npm test -- InspectorPanel                     # frontend, one file by name
npm run build                                  # production build to dist/

# desktop (Electron) — see the Desktop section below
npm run desktop:dev                            # hot-reload Vite + Electron shell, backend runs from source
python -m pip install -r requirements-desktop.txt   # adds PyInstaller for bundling
npm run desktop:build:win                      # NSIS installer + portable exe into release/
npm run desktop:build:mac                      # dmg + zip
```

Frontend scripts live in the root `package.json` but pass `--config frontend/vite.config.js`; there is no separate frontend package.json workflow.

`LLM_PROVIDER=mock` in `backend/.env` runs the full pipeline offline with no API key (deterministic, hash-based points) — use it for local UI work and demos.

`AGENTS.md` is a near-verbatim mirror of this file for Codex; keep the two in sync when editing architecture notes.

## Architecture

### Estimation pipeline (the core)

- `backend/graph/build.py` — wires the LangGraph `StateGraph`: score_parameters → identify_drivers → compare_to_anchors → derive_points → (conditional `spike_split_branch` when points == 13 or uncertainty is High) → write_plain_language_reasoning → detect_hidden_tasks → assess_risks → recommend_split. Compiled with `MemorySaver`; the caller's `session_id` becomes the `thread_id`, which is what makes refinements ("re-estimate assuming X") work against a prior run.
- `backend/graph/state.py` — the `EstimationState` TypedDict plus one Pydantic output schema per node (`ScorecardOutput`, `PointsOutput`, etc.). These schemas are the contract between prompts and state.
- `backend/graph/nodes.py` — all node prompts and implementations. Contains `_parse_structured_result`, which tolerates provider quirks (raw/parsed envelopes, markdown-fenced JSON, Groq list echoes) — structured-output bugs are usually fixed there, not in the nodes.

### Project workspace and C4 model

- Persistence is stdlib SQLite ([backend/storage/db.py](backend/storage/db.py)) at `data/storypointer.db` (override: `STORYPOINTER_DB` env var); LangGraph checkpoints go to `data/checkpoints.db` via `AsyncSqliteSaver`, installed in the API lifespan through [backend/graph/checkpoint.py](backend/graph/checkpoint.py) — tests and bare imports fall back to `MemorySaver`.
- `backend/projects/` (CRUD + repo/Jira links) and `backend/c4/` (elements, relations, artifact links, imports, roll-up) follow store/service/router layering. Level rules: an element's parent must be exactly one level up; L1→initiative, L2→epic, L3→story, L4→task (`ARTIFACT_FOR_LEVEL` in [backend/c4/models.py](backend/c4/models.py)); cross-cutting bug/tech_debt/arch_flow artifacts tag elements at allowed levels.
- Estimation of an element (L3/L4 only) builds a `Story` with `c4_context` (parent chain, relations, code path — see `element_to_story` in [backend/c4/service.py](backend/c4/service.py)) and reuses `stream_story` from [backend/api/streaming.py](backend/api/streaming.py) with an `on_result` callback that persists points and seeds proposed L4 tasks (from `hidden_tasks`) and sibling L3 stories (from split recommendations). Roll-ups are deterministic sums — never LLM output; `proposed` elements are excluded.
- SSE helpers live in `backend/api/streaming.py` (not `main.py`) so the C4 router can import them without a circular import.

### L1 operating plans (`backend/planning/`)

- Each **L1 element** can carry an operating plan: agile units (tribes → squads), team members, scheduled/costed work items, and mermaid architecture/infrastructure diagrams — all in the `l1_*` tables in [backend/storage/db.py](backend/storage/db.py). Same store/router layering as the other modules; the router mounts under `/projects/{id}/l1/...` in [backend/planning/router.py](backend/planning/router.py).
- Invariants enforced in [backend/planning/store.py](backend/planning/store.py): a plan attaches only to an L1 element; a squad's parent must be a tribe in the same plan; a work item's `linked_element_id` must be an L2–L4 descendant of that L1, and its `squad_id` a squad in the same plan; `end_date >= start_date`.
- `get_plan` returns the plan plus **deterministically computed** `metrics` (people, allocated FTE, monthly run-rate, planned/actual cost + variance, at-risk work) — no LLM involvement. Money is presentation-only; the stored `currency_code` (per-L1 `l1_plan_settings`) just labels it.

### Desktop app (`desktop/`, Electron + PyInstaller)

- The same web build and FastAPI backend ship as a self-contained desktop app; no code forks. `desktop/electron/main.cjs` is the Electron main process: it starts the backend, waits on `/health`, then loads the UI (dev server URL when `ELECTRON_DEV_SERVER_URL` is set, otherwise `dist/index.html`).
- **Backend launch is dual-mode** ([main.cjs](desktop/electron/main.cjs) `backendCommand`): packaged builds run the bundled PyInstaller exe from `process.resourcesPath/backend`; unpackaged (`desktop:dev`) runs `python -m desktop.backend_launcher` from the repo. `backend_launcher.py` just calls `uvicorn.run(..., reload=False)` on host/port from `STORYPOINTER_API_*`.
- **Port handling**: prefers `8765`, reuses an already-healthy instance on it, else picks a random free port — so a dev backend and the desktop app coexist. A single-instance lock prevents duplicate windows.
- **The UI never bakes in the API URL.** Electron injects the resolved base via `additionalArguments`; `preload.cjs` exposes it as `window.storyPointer.apiBaseUrl`, and [client.js](frontend/src/api/client.js) prefers that over `VITE_API_BASE_URL`. Desktop data is per-user: `STORYPOINTER_DB` and the backend env file live under Electron's `userData` dir, seeded from `desktop/backend.env.example` on first run.
- **Bundling** ([scripts/build-backend-bundle.mjs](scripts/build-backend-bundle.mjs)) runs PyInstaller against `desktop/pyinstaller/storypointer-api.spec` → `desktop/backend-dist/`; the spec lists provider/langgraph/docx/pptx packages as `hiddenimports` (PyInstaller can't see dynamic imports, so **a new LLM provider or optional dep must be added there** or it's missing at runtime). `desktop:prepare` chains icon gen + web build + backend bundle before `electron-builder` (config in `package.json` `build`).

### Strict module boundaries

- `backend/llm/factory.py` is the **only** module allowed to know provider names. Native LangChain providers go in `NATIVE_PROVIDERS` (via `init_chat_model`); OpenAI-compatible endpoints (Moonshot, DeepSeek, Ollama, …) share `ChatOpenAI(base_url=...)` via `OPENAI_COMPATIBLE`. Groq gets `json_mode` structured output. `LLM_PROVIDER=mock` (`OFFLINE_PROVIDERS`) needs no API key and routes structured calls to the deterministic [backend/llm/mock.py](backend/llm/mock.py) — points come from a hash of the story title, so tests and demos are stable and offline. The API-key requirement is provider-specific and lives in `validate_factory_config`, not `config.py`. Adding a provider means editing the factory only.
- `backend/jira/registry.py` mirrors that boundary for Jira: `JIRA_INSTANCES=prod,sandbox` env names expand to `JIRA_<NAME>_*` variables parsed in `backend/config.py`. Cloud instances use REST v3 + Basic auth (email + token); Server/DC uses REST v2 + Bearer PAT (`backend/jira/client.py`). Instance names/auth are validated at startup, credentials lazily on first use.
- `backend/anchors.py` holds six fixed calibration stories injected into every comparison prompt — no embeddings or retrieval. Calibration changes are edits to this file plus an API restart.

### API behavior (`backend/api/main.py`)

- All estimation routes stream SSE. `node` events are progress-only; the final `result` event is emitted atomically and the server raises if `plain_language_why` or `tldr` is missing — a point value must never appear without its explanation.
- Startup config errors don't crash the app: `lifespan` stashes them in `app.state.configuration_errors`, `/health` reports them, and estimation routes return 503 via `require_llm_config`.
- All errors (HTTP and in-stream) use the shape `{ "error": { code, message, details, retryable } }`.
- Jira write-back is triple-gated: `JIRA_WRITE_ENABLED=true` env, `confirm=true` on the request, and per-issue confirmation in the UI.

### Configuration

All backend config comes from `backend/.env` (loaded by `backend/config.py`, typed via pydantic-settings). Frontend reads only `VITE_API_BASE_URL` from `frontend/.env`. Provider/model strings must not appear in application code outside the LLM factory.

### Frontend

- `frontend/src/App.jsx` is a small state-based router (no router lib): `home` → `wizard` → `project`, plus a standalone `quick`. [ProjectWorkspace](frontend/src/screens/ProjectWorkspace.jsx) hosts the nav-rail tabs — **canvas / L1 plan / rollup / quick / overview**. Top-level screens live in `frontend/src/screens/`.
- The C4 canvas (`frontend/src/c4/`) is React Flow (`@xyflow/react`): [C4Canvas.jsx](frontend/src/c4/C4Canvas.jsx) with an [InspectorPanel](frontend/src/c4/InspectorPanel.jsx) side panel. Estimation runs in a **modal** ([EstimateDialog.jsx](frontend/src/c4/EstimateDialog.jsx)), not inline — it streams the pipeline then shows the full `ResultCard`; results are cached per element so "View reasoning" reopens without re-running.
- L1 planning UI is in `frontend/src/planning/` (teams, work/cost, mermaid diagram studio), opened from the L1 plan tab or the inspector's "More details" on an L1 node.
- The original single-story flow (form / Jira browser / Excel upload) is now the **Quick estimate** screen ([QuickEstimate.jsx](frontend/src/screens/QuickEstimate.jsx)); its building blocks stay in `frontend/src/components/`.
- `frontend/src/api/client.js` wraps every endpoint plus `consumeSSE` for streaming. Material 3 styling lives in [frontend/src/md3.css](frontend/src/md3.css) (the workspace shell) alongside the older `styles.css` (estimation components). Tests colocate as `*.test.jsx` (jsdom + Testing Library, setup in `frontend/src/test-setup.js`).
