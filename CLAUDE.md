# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Story Pointer: an evidence-led story-point estimator (modified Fibonacci 1/2/3/5/8/13) for React/Spring teams. FastAPI backend runs a checkpointed LangGraph pipeline and streams progress over SSE; React 19 + Vite frontend (Material 3 shell) consumes the stream. Stories come from a form, Jira, a spreadsheet upload, or — via the project workspace — from L3 components of an interactive C4 model whose points roll up to epics and initiatives.

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

python scripts/seed_demo.py                    # seed a demo project + C4 model

# tests
pytest backend/tests -q                        # backend
pytest backend/tests/test_mapping.py -q        # one file
pytest backend/tests/test_graph_routing.py::test_name -q   # one test
npm test                                       # frontend (vitest run)
npm run build                                  # production build to dist/
```

Frontend scripts live in the root `package.json` but pass `--config frontend/vite.config.js`; there is no separate frontend package.json workflow.

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

Single-page app in `frontend/src/App.jsx` with a source switcher (form / Jira browser / Excel upload). `frontend/src/api/client.js` wraps fetch + SSE parsing. Components are flat under `frontend/src/components/`; tests colocate as `*.test.jsx` (jsdom + Testing Library, setup in `frontend/src/test-setup.js`).
