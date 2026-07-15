# Story Pointer — Complete Code Generation Specification

> **Purpose.** This document is a self-contained regeneration spec for the Story Pointer
> repository. It contains (a) a detailed architectural analysis, (b) every behavioral
> contract and invariant, and (c) the **complete, verbatim source of every file** needed
> to recreate the application with zero loss of functionality. Feed this document to a
> code generator (or a human) and follow it top-to-bottom: create each file at the path
> shown, with exactly the content shown, then run the Setup steps at the end.

---

## 1. Product overview

Story Pointer is an **evidence-led story-point estimator** for React/Spring delivery
teams in regulated (banking) environments. Instead of asking an LLM to guess a number,
it runs a **checkpointed LangGraph pipeline** that:

1. Scores 12 delivery factors (Low/Medium/High, each with evidence),
2. Identifies the 2–3 deciding drivers,
3. Compares the story against **six fixed calibration anchors** (no embeddings, no
   vector store, no retrieval — anchors are injected verbatim into the prompt),
4. Only then concludes a modified-Fibonacci point value (1, 2, 3, 5, 8, 13),
5. Writes a product-owner explanation, TL;DR, per-layer effort, person-day range,
6. Detects hidden work implied by acceptance criteria,
7. Assesses top-3 risks, assumptions, and spike need,
8. Recommends a split (a 13 is *always* split, with sized sub-stories).

**Core product invariant:** a point value is never shown without its explanation. The
backend emits the final result atomically only after `plain_language_why` **and** `tldr`
exist; the frontend `ResultCard` independently refuses to render a number without them.

Stories arrive from three sources: **manual entry**, **Jira** (multi-instance, Cloud v3
or Server/DC v2), or **spreadsheet upload** (CSV/XLS/XLSX with fuzzy column mapping).
Results stream to the browser over **Server-Sent Events**.

## 2. Technology stack (exact versions)

| Layer | Technology |
|---|---|
| Backend runtime | Python 3.11+ |
| API | FastAPI 0.115.12 + uvicorn[standard] 0.34.2 |
| Orchestration | langchain 0.3.25, langgraph 0.4.7 (StateGraph + MemorySaver) |
| LLM providers | langchain-openai 0.3.18, langchain-anthropic 0.3.13, langchain-google-genai 2.1.4, langchain-groq 0.3.2, langchain-mistralai 0.2.10 |
| Validation/config | pydantic 2.11.5, pydantic-settings 2.9.1, python-dotenv 1.1.0 |
| HTTP / files | httpx 0.28.1, python-multipart 0.0.20, pandas 2.2.3, openpyxl 3.1.5, xlrd 2.0.1, tenacity 9.1.2 |
| Backend tests | pytest 8.3.5, pytest-asyncio 0.26.0 |
| Frontend | React 19.1.0, react-dom 19.1.0, Vite 6.4.3, @vitejs/plugin-react 4.4.1, lucide-react 0.511.0 |
| Frontend tests | vitest 3.2.6, @testing-library/react 16.3.0, @testing-library/jest-dom 6.6.3, jsdom 26.1.0 |

Node.js 20+ is recommended. There is **one** `package.json` at the repository root; the
`frontend/` directory has no package.json of its own — every npm script passes
`--config frontend/vite.config.js`.

## 3. Repository layout

```
storypointer/
├── .claude/launch.json           # Claude Code dev-server launch config (tooling only)
├── .gitattributes
├── .gitignore                    # standard Node gitignore + python entries
├── README.md
├── package.json                  # root npm manifest (drives the frontend)
├── pytest.ini
├── requirements.txt
├── banking_jira_stories.csv          # OPTIONAL sample data (see §10)
├── banking_jira_stories_role_model.md# OPTIONAL reference doc (see §10)
├── img.png                           # OPTIONAL screenshot
├── backend/
│   ├── .env                      # local secrets — NEVER commit; copy from .env.example
│   ├── .env.example
│   ├── __init__.py
│   ├── anchors.py                # six fixed calibration stories (edit to tune team)
│   ├── config.py                 # typed env config + startup-safe validation
│   ├── models.py                 # shared API/domain Pydantic models
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py               # FastAPI app, SSE streaming, all routes
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── build.py              # StateGraph wiring + MemorySaver checkpointer
│   │   ├── nodes.py              # all node prompts + structured-output plumbing
│   │   └── state.py              # typed state + node output schemas
│   ├── ingest/
│   │   ├── __init__.py
│   │   └── excel.py              # CSV/XLS/XLSX parse, fuzzy mapping, template
│   ├── jira/
│   │   ├── __init__.py
│   │   ├── client.py             # httpx REST v3/v2 wrapper
│   │   ├── mapping.py            # ADF flattening + issue→Story mapping
│   │   └── registry.py           # named multi-instance registry
│   ├── llm/
│   │   ├── __init__.py
│   │   └── factory.py            # the ONLY provider-aware module
│   └── tests/
│       ├── __init__.py
│       ├── test_graph_routing.py
│       ├── test_ingest.py
│       ├── test_mapping.py
│       └── test_structured_output.py
└── frontend/
    ├── .env.example
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── main.jsx
        ├── styles.css            # entire design system in one file
        ├── test-setup.js
        ├── api/client.js         # fetch JSON helper + manual SSE consumer
        └── components/
            ├── BatchTable.jsx
            ├── ColumnMapper.jsx
            ├── EffortBar.jsx
            ├── ErrorCard.jsx
            ├── ExcelUpload.jsx
            ├── JiraBrowser.jsx
            ├── PipelineView.jsx
            ├── ResultCard.jsx
            ├── ResultCard.test.jsx
            ├── Scorecard.jsx
            ├── SourceSwitcher.jsx
            ├── StatusBadge.jsx
            └── StoryForm.jsx
```

`package-lock.json` files (root and `frontend/`) are regenerated by `npm install` and
are not reproduced here.

## 4. Architecture analysis

### 4.1 Backend module boundaries (deliberate design rules)

- **`backend/llm/factory.py` is the only module that knows provider names.** Every
  other module calls `get_llm()` / `get_structured_llm(schema)`. Adding an
  OpenAI-compatible provider requires zero code (set `LLM_PROVIDER=compatible` +
  `LLM_BASE_URL`); adding a native LangChain provider means installing its package and
  adding one name to `NATIVE_PROVIDERS`.
- **`backend/jira/registry.py` mirrors that boundary for Jira**: named instances are
  parsed from env at startup, credentials validate lazily on first use.
- **`backend/config.py`** collects *all* configuration errors into a
  `ConfigurationError(errors: list[str])` instead of failing fast one at a time. The
  FastAPI lifespan catches it and stores `app.state.configuration_errors` so the app
  **stays up**; `/health` reports the errors and estimate endpoints return 503 with the
  error list (`require_llm_config`). The UI renders the fix instead of a stack trace.
- **`backend/anchors.py`** is a plain Python list — the calibration knob. Editing it
  and restarting the API is the entire tuning workflow.
- **`backend/graph/nodes.py`** holds *all* prompts and node implementations;
  `backend/graph/state.py` holds *all* structured output schemas;
  `backend/graph/build.py` only wires edges.

### 4.2 The estimation graph

Nodes (in `build.py`), all async, state type `EstimationState` (TypedDict, `total=False`):

```
START → score_parameters → identify_drivers → compare_to_anchors → derive_points
derive_points --(conditional route_after_points)--> "escalate"  → spike_split_branch → write_plain_language_reasoning
                                              \--> "continue" → write_plain_language_reasoning
write_plain_language_reasoning → detect_hidden_tasks → assess_risks → recommend_split → END
```

- `derive_points` sets `escalation_required = (points == 13) or (uncertainty score == "High")`.
- `spike_split_branch` (registered node name; implementation `escalation_branch`) sets
  `spike_recommended=True` with a fixed reason.
- `assess_risks` **preserves** an already-triggered spike (`state or result` OR-merge).
- `recommend_split` **forces** `split_recommended=True` when points == 13.
- The graph is compiled once (`@lru_cache`) with `MemorySaver()` as checkpointer. The
  API passes `{"configurable": {"thread_id": session_id}}`, so re-posting the same
  `session_id` with a `refinement` string (e.g. "re-estimate assuming the rule engine
  is out of scope") continues the same thread.
- Every node appends an `AIMessage(name=node)` trace to `messages`
  (`Annotated[list[AnyMessage], add_messages]`).

### 4.3 Structured-output hardening (the most subtle code in the repo)

`nodes.py` contains defensive plumbing born from real free-tier provider failures
(Groq llama-3.1-8b-instant, 6000 TPM):

- `get_structured_llm` uses `with_structured_output(schema, include_raw=True)`; for
  **groq** specifically it uses `method="json_mode"` (avoids `tool_use_failed` errors
  on otherwise-valid tool args).
- `_schema_contract(schema)` renders a **plain-text field contract** (via
  `_annotation_contract` recursion over Pydantic annotations, handling `Literal`,
  `list`, `Union`/`types.UnionType`, nested `BaseModel`, min/max length metadata)
  instead of embedding a JSON Schema — because small models **echo** JSON Schemas back.
- `_parse_structured_result(schema, result)` is a worklist parser tolerating: the
  `{"raw","parsed","parsing_error"}` include_raw wrapper; `AIMessage.content` strings;
  markdown ` ```json ` fences; JSON strings; **arrays where the model echoed the schema
  first and the real object second** (reversed, so the last item is tried first);
  dicts that fail validation but contain the payload under `text`/`content`/`output`.
  On exhaustion it raises `ValueError` with the provider parsing error (truncated 500 chars).
- `_invoke` sends `SystemMessage(SYSTEM)` + a HumanMessage of
  `prompt + output contract + JSON context of selected state fields`, tries **twice**;
  on first failure it sleeps `_retry_delay` (which honors provider "try again in Xs"
  hints, capped 65 s, else `2**attempt`) and appends a corrective HumanMessage
  ("The prior output was invalid…"). Final failure raises
  `RuntimeError("The model could not produce valid {schema} output: …")`.
- `score_parameters` post-validates that **all 12 parameters** were scored exactly
  (set equality) and raises listing the omissions.

### 4.4 SSE protocol

`sse(event, data)` frames `event: {name}\ndata: {json}\n\n` (UTF-8 bytes),
`media_type="text/event-stream"`.

Single estimate (`POST /estimate`):

| event | data |
|---|---|
| `started` | `{session_id, title}` |
| `node` (×9 or ×8) | `{node, status: "completed"}` — progress only, no content |
| `result` | full public state (see below), emitted **atomically at the end** |
| `error` | `{code: "estimation_error", message, retryable: true}` |

Batch (`POST /estimate/batch`, `POST /upload/estimate`): `batch_started
{count, session_id, skipped}` → per story `item_started {index, title}`, `item_node
{index, node, status}`, `item_result {index, result}` or `item_error {index, ...}` →
final `batch_result {results, skipped}`. Batch item sessions are `f"{root}:{index}"`.
`stream_batch` re-parses `stream_story`'s byte frames by string prefix — keep that
implementation detail.

`public_result` strips `{"anchors", "messages", "escalation_required", "refinement"}`
from the state snapshot. Before emitting `result`, the server raises if
`plain_language_why` or `tldr` is missing ("The model returned points without the
required explanation").

### 4.5 REST API surface

| Method | Route | Purpose / notes |
|---|---|---|
| GET | `/health` | `{status: ok\|degraded, llm: {status, errors}, jira: {name: {status,message}}}` |
| GET | `/config` | `{llm: {provider, model}, jira_instances, jira_write_enabled}` — non-secret |
| GET | `/jira/instances` | `[{name, auth_type}]` |
| GET | `/jira/{instance}/project/{code}/issues` | query: `status`, `sprint`, `page_size` (1–100, default 50), `max_issues` (1–1000, default 500) |
| POST | `/upload/parse` | multipart file; 15 MB limit; returns columns/suggested_mapping/preview(20)/rows/row_count |
| GET | `/upload/template` | XLSX download, `Content-Disposition: attachment; filename="story-pointer-template.xlsx"` |
| POST | `/estimate` | body `EstimateRequest`; SSE stream |
| POST | `/estimate/batch` | body `BatchEstimateRequest` (1–100 stories); SSE stream |
| POST | `/upload/estimate` | body `UploadEstimateRequest` (rows + mapping); SSE stream |
| POST | `/jira/{instance}/{issue_key}/points` | 403 unless `JIRA_WRITE_ENABLED=true`; 400 unless `confirm=true` |

All errors use `{"error": {"code", "message", "details", "retryable"}}` via registered
exception handlers: `RequestValidationError`→422 `validation_error`; `HTTPException`
passthrough of dict detail; `JiraError`→502 if status ≥500/None else 400;
`UploadError`→400 `parse_error`. CORS allows configured origins, credentials,
GET/POST/OPTIONS, all headers.

### 4.6 Jira integration

- **Cloud** (`auth_type=cloud`): REST **v3**, `httpx.BasicAuth(email, api_token)`,
  search via `GET /rest/api/3/search/jql` with `nextPageToken` pagination
  (stop when no issues, `isLast is True`, or no token).
- **Server/DC** (`auth_type=server`): REST **v2**, `Authorization: Bearer <PAT>`,
  search via `GET /rest/api/2/search` with `startAt`/`total` pagination.
- JQL safety: project code must match `[A-Za-z][A-Za-z0-9_-]{0,49}`; `status`/`sprint`
  values get `"` escaped as `\"`; JQL is
  `project = "X" [AND status = "..."] [AND sprint = "..."] ORDER BY created DESC`.
- Requested fields: `summary, description, status, labels, components` + configured
  story-points field + configured AC field.
- `_request` retries once on 429/502/503/504 and on timeout/network errors; each
  attempt uses a fresh `httpx.AsyncClient(timeout=30)`. Non-retryable ≥400 raises
  `JiraError` with status and body detail.
- `health()` calls `GET myself`.
- `write_points` = `PUT issue/{key}` with `{"fields": {<points_field>: points}}`;
  raises if the instance has no points field configured.
- **Mapping** (`mapping.py`): `adf_to_text` recursively flattens Atlassian Document
  Format (dict `text` + `content` children, lists joined by `\n`) or passes plain
  strings through. `split_acceptance_criteria` uses the AC custom field if present,
  else regex-extracts an "Acceptance Criteria:"/Gherkin section from the description
  (`(?:acceptance criteria|given\s.+?when\s.+?then)\s*:?\s*(.+)`, IGNORECASE|DOTALL),
  splits on newlines/semicolons, strips list bullets/numbering
  (`^[\s*\-\d.)]+`). `issue_to_story` fills a `Story(source="jira",
  jira_instance=config.name)` with title fallback `summary → key → "Untitled Jira issue"`.

### 4.7 Spreadsheet ingestion

- `read_upload`: `.csv` via `pd.read_csv`, `.xlsx` via openpyxl engine, `.xls` via
  xlrd; `dtype=object`, `.fillna("")`; parse failures raise
  `UploadError("Could not parse {filename}: …")`; other suffixes raise
  `UploadError("Use a .csv, .xlsx, or .xls file")`.
- Fuzzy header mapping: `_score` normalizes headers (`[^a-z0-9]+`→space, lowercase);
  exact match = 1.0, substring either way = 0.9, else `SequenceMatcher.ratio()`.
  `suggest_mapping` greedily assigns the best-scoring unused column per target with a
  **0.55 acceptance threshold**. Targets and aliases:
  `title` [title, summary, story title, issue, name]; `user_story` [user story,
  description, story, details, requirement]; `acceptance_criteria` [acceptance
  criteria, acs, ac, criteria, conditions of satisfaction]; `technical_breakdown`
  [technical breakdown, technical notes, implementation, dev notes];
  `existing_points` [existing points, story points, points, sp, estimate].
- `dataframe_payload` returns **all rows** (JSON round-trip via
  `frame.to_json(orient="records", date_format="iso")`, `None`→`""`) plus a
  20-row preview, columns, suggestions, and `row_count`.
- `rows_to_stories`: requires a mapped title column; enumerates rows **starting at 2**
  (spreadsheet row numbers incl. header); blank titles are skipped and reported
  `{row, reason: "Title is blank"}` without failing the batch; existing points parse
  as float else `None`; AC cell strings split on newlines/semicolons via the `Story`
  validator.
- `template_workbook`: one-sheet ("Stories") XLSX with a single sample row, frozen
  header (`freeze_panes="A2"`), bold header font, column widths A:34 B:60 C:60 D:50 E:18.

### 4.8 Frontend architecture

- **No router, no state library.** `App.jsx` owns all state: `source`
  (manual|jira|upload), `config` + `health` (fetched in parallel on mount), `issues`,
  `upload`, `loading`, `steps` (completed node names), `pipelineTitle`, `result`
  (single result shown in `ResultCard`), `results` (batch), `error`, and an
  `AbortController` ref aborted on unmount.
- **`api/client.js`** implements SSE over `fetch` **POST** manually: reads the body
  stream, splits on blank lines (`/\r?\n\r?\n/`), keeps a partial-frame buffer, parses
  `event:`/`data:` lines, JSON-parses joined data, invokes `onEvent(event, data)`.
  `jsonRequest` throws `Error` with `.payload` from `body.error || body.detail || body`.
  Base URL from `VITE_API_BASE_URL` (default `http://localhost:8000`, trailing `/` stripped).
- **`PipelineView`** maps node names→labels in pipeline order and derives the
  "current" step as the first not-done label at index `steps.length`; sticky sidebar.
- **`ResultCard`** guards the core invariant (renders a refusal card if
  `plain_language_why`/`tldr` missing), shows SPLIT/SPIKE banner, points vs
  `existing_points` delta, Fibonacci scale (1 2 3 5 8 13 with passed/selected states),
  Markdown + JSON export via Blob download, gated "Write N to Jira" button
  (only when `writeEnabled && story.source === 'jira'`), and six `<details>` sections:
  Scorecard and drivers / Anchor comparison / Layer effort / Hidden sub-tasks / Risks
  and assumptions / Split recommendation.
- **`BatchTable`** sorts by title|points, exports CSV (quote-doubled), row click opens
  the full `ResultCard` for that item.
- **`ColumnMapper`** seeds from `suggested_mapping`, requires Title, caps selection at
  the first 100 rows (with a note for larger files), previews only mapped columns
  (cells truncated to 100 chars).
- **`JiraBrowser`** instance/project/status/sprint controls, checkbox selection,
  estimates selected issues via the generic batch endpoint.
- Jira write-back UX: `window.confirm("Write N points to KEY? This changes Jira.")`
  then `window.alert('Jira was updated.')`.
- **`styles.css`** is the whole design system: DM Sans body + Manrope display (Google
  Fonts import), paper/green palette (`--ink #17221e`, `--green #186149`, lime accent
  `#d8efb4`, dark header `#123d31`), 1240 px shell, sticky pipeline card, responsive
  breakpoints at 900 px and 620 px, `prefers-reduced-motion` support, `:focus-visible`
  outlines, `.sr-only` utility.

### 4.9 Configuration reference (backend/.env)

```
LLM_PROVIDER    one of: anthropic | google_genai | openai | groq | mistral   (native)
                or: moonshot | deepseek | openrouter | ollama | vllm | compatible (OpenAI-compatible; LLM_BASE_URL required)
LLM_MODEL       model id string
LLM_API_KEY     required (startup error if empty)
LLM_BASE_URL    required only for OpenAI-compatible providers
LLM_TEMPERATURE default 0.2 (settings default; .env.example ships 0), range 0–2
LLM_MAX_TOKENS  default 3000, range 128–100000
JIRA_INSTANCES  comma list of lowercase names, e.g. "prod,sandbox"
JIRA_WRITE_ENABLED  default false
JIRA_<NAME>_BASE_URL / AUTH_TYPE (cloud|server) / EMAIL (cloud only) /
JIRA_<NAME>_API_TOKEN / STORY_POINTS_FIELD / AC_FIELD   per instance
CORS_ORIGINS    default "http://localhost:5173,http://127.0.0.1:5173"
```

Frontend env (`frontend/.env`): `VITE_API_BASE_URL=http://localhost:8000`.

---

## 5. Complete source — root files

### 5.1 `package.json`

```json
{
  "name": "story-pointer-v2",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --config frontend/vite.config.js",
    "build": "vite build --config frontend/vite.config.js",
    "preview": "vite preview --config frontend/vite.config.js",
    "test": "vitest run --config frontend/vite.config.js"
  },
  "dependencies": {
    "@vitejs/plugin-react": "4.4.1",
    "lucide-react": "0.511.0",
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "vite": "6.4.3"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "6.6.3",
    "@testing-library/react": "16.3.0",
    "jsdom": "26.1.0",
    "vitest": "3.2.6"
  }
}
```

### 5.2 `requirements.txt`

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
langchain==0.3.25
langgraph==0.4.7
langchain-openai==0.3.18
langchain-anthropic==0.3.13
langchain-google-genai==2.1.4
langchain-groq==0.3.2
langchain-mistralai==0.2.10
pydantic==2.11.5
pydantic-settings==2.9.1
python-dotenv==1.1.0
python-multipart==0.0.20
httpx==0.28.1
pandas==2.2.3
openpyxl==3.1.5
xlrd==2.0.1
tenacity==9.1.2
pytest==8.3.5
pytest-asyncio==0.26.0
```

### 5.3 `pytest.ini`

```ini
[pytest]
asyncio_default_fixture_loop_scope = function
```

### 5.4 `.gitattributes`

```
# Auto detect text files and perform LF normalization
* text=auto
```

### 5.5 `.gitignore`

Use the standard GitHub **Node** `.gitignore` template (logs, `node_modules/`,
`dist`, coverage, `.env` variants, caches, etc.) and ensure it also ignores the Python
artifacts used here: `.venv/`, `__pycache__/`, `*.pyc`, and `backend/.env`.

### 5.6 `.claude/launch.json` (Claude Code tooling only — not required by the app)

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "frontend",
      "runtimeExecutable": "npm",
      "runtimeArgs": ["run", "web:dev"],
      "port": 5173
    },
    {
      "name": "frontend-preview",
      "runtimeExecutable": "npx",
      "runtimeArgs": ["cross-env", "VITE_API_BASE_URL=http://localhost:8001", "npm", "--workspace", "@storypointer/web", "run", "dev", "--", "--port", "5174", "--strictPort"],
      "port": 5174,
      "autoPort": false
    }
  ]
}
```

> Note: this file predates the current single-package layout (it references
> `web:dev` and an `@storypointer/web` workspace that no longer exist). The working
> dev command is `npm run dev`. Reproduce as-is for fidelity or update the first
> configuration's `runtimeArgs` to `["run", "dev"]`.

### 5.7 `README.md`

Recreate the README with these sections (full prose in the original; content summary —
all technical facts it states are already captured in §1–§4 and §11 of this spec):

- **Intro** — evidence-led estimator description (as §1).
- **Architecture** — frontend/backend/Jira/files/calibration bullets; SSE note that
  node events are progress-only and the final result is atomic.
- **Install** — PowerShell steps: create `.venv`, `pip install -r requirements.txt`,
  copy `backend\.env.example`→`backend\.env`, `npm install`, copy
  `frontend\.env.example`→`frontend\.env`; run `uvicorn backend.api.main:app --reload
  --port 8000` and `npm run dev`; open `http://localhost:5173`; checks:
  `pytest backend/tests -q`, `npm test`, `npm run build`.
- **Provider switches** — dotenv examples for Claude (`anthropic` /
  `claude-sonnet-4-6`), Gemini (`google_genai` / `gemini-2.0-flash`), Kimi/Moonshot
  (`moonshot` / `moonshot-v1-8k` / base URL `https://api.moonshot.ai/v1`); note that
  native integrations use `init_chat_model` and compatible ones share
  `ChatOpenAI(base_url=...)`; invalid config is checked at startup and surfaced via `/health`.
- **Jira configuration** — one-cloud-instance and add-a-server-instance dotenv
  examples (as `.env.example`); registry parses at startup, validates lazily; AC-field
  fallback; missing points field disables writes; write gating (env flag + per-issue
  confirmation + `confirm=true`).
- **Spreadsheet flow** — template download, any headers accepted, `/upload/parse`
  returns rows/columns/preview/suggestions, user must map Title, blank-title rows
  skipped and reported, AC cells split on newlines/semicolons.
- **Estimation method** — the 8 numbered pipeline steps and the refinement/thread_id note.
- **API** — the route table (§4.5) and the error envelope.
- **Calibration** — edit only `backend/anchors.py`; keep representative 3/5/8; restart API.
- **How to add a new LLM provider** — compatible vs native instructions.
- **How to add another Jira instance** — append name + env vars, restart.
- **How to find your Jira Story Points field id** — `GET /rest/api/3/field` (Cloud) or
  `/rest/api/2/field` (Server), find "Story Points", use its `id`.
- **Excel template & column mapping** — template link, mapping review, existing points
  are reference-only.

---

## 6. Complete source — backend

### 6.1 Package `__init__.py` files (one line each)

| File | Content |
|---|---|
| `backend/__init__.py` | `"""Story Pointer backend package."""` |
| `backend/api/__init__.py` | `"""HTTP API package."""` |
| `backend/graph/__init__.py` | `"""Estimation graph package."""` |
| `backend/ingest/__init__.py` | `"""File ingestion package."""` |
| `backend/jira/__init__.py` | `"""Jira integration package."""` |
| `backend/llm/__init__.py` | `"""LLM integration package."""` |
| `backend/tests/__init__.py` | `"""Backend unit tests."""` |

### 6.2 `backend/.env.example`

```dotenv
# --- LLM ---
# Native: anthropic | google_genai | openai | groq | mistral
# OpenAI-compatible: moonshot | deepseek | openrouter | ollama | vllm | compatible
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
LLM_API_KEY=
# Required for OpenAI-compatible providers:
# Moonshot: https://api.moonshot.ai/v1
# DeepSeek: https://api.deepseek.com/v1
# Ollama: http://localhost:11434/v1
# vLLM: http://localhost:8000/v1
LLM_BASE_URL=
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=3000

# --- Jira (multi-instance) ---
JIRA_INSTANCES=prod,sandbox
JIRA_WRITE_ENABLED=false

JIRA_PROD_BASE_URL=https://yourorg.atlassian.net
JIRA_PROD_AUTH_TYPE=cloud
JIRA_PROD_EMAIL=
JIRA_PROD_API_TOKEN=
JIRA_PROD_STORY_POINTS_FIELD=customfield_10016
JIRA_PROD_AC_FIELD=

JIRA_SANDBOX_BASE_URL=https://jira-sandbox.example.com
JIRA_SANDBOX_AUTH_TYPE=server
JIRA_SANDBOX_API_TOKEN=
JIRA_SANDBOX_STORY_POINTS_FIELD=customfield_10024
JIRA_SANDBOX_AC_FIELD=

# --- API ---
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 6.3 `backend/config.py`

```python
"""Typed environment configuration with startup-safe validation."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).with_name(".env")
load_dotenv(ENV_FILE)


class ConfigurationError(RuntimeError):
    """A user-actionable environment configuration error."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class LLMSettings(BaseModel):
    """Settings consumed exclusively by the LLM factory."""

    provider: str
    model: str
    api_key: SecretStr
    base_url: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=3000, ge=128, le=100_000)

    @field_validator("provider", "model")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()


class JiraInstanceSettings(BaseModel):
    """Configuration for one named Jira installation."""

    name: str
    base_url: str
    auth_type: Literal["cloud", "server"]
    api_token: SecretStr
    email: str | None = None
    story_points_field: str | None = None
    ac_field: str | None = None

    @field_validator("base_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.strip().rstrip("/")


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str | None = None
    llm_temperature: float = 0.2
    llm_max_tokens: int = 3000
    jira_instances: str = ""
    jira_write_enabled: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def llm(self) -> LLMSettings:
        try:
            return LLMSettings(
                provider=self.llm_provider,
                model=self.llm_model,
                api_key=self.llm_api_key,
                base_url=self.llm_base_url or None,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
            )
        except ValidationError as exc:
            raise ConfigurationError(
                [f"LLM_{'.'.join(map(str, error['loc'])).upper()}: {error['msg']}" for error in exc.errors()]
            ) from exc

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def jira_configs(self) -> dict[str, JiraInstanceSettings]:
        configs: dict[str, JiraInstanceSettings] = {}
        errors: list[str] = []
        for raw_name in self.jira_instances.split(","):
            name = raw_name.strip().lower()
            if not name:
                continue
            prefix = f"JIRA_{name.upper()}_"
            values = {
                "name": name,
                "base_url": os.getenv(prefix + "BASE_URL", ""),
                "auth_type": os.getenv(prefix + "AUTH_TYPE", "cloud").lower(),
                "email": os.getenv(prefix + "EMAIL") or None,
                "api_token": SecretStr(os.getenv(prefix + "API_TOKEN", "")),
                "story_points_field": os.getenv(prefix + "STORY_POINTS_FIELD") or None,
                "ac_field": os.getenv(prefix + "AC_FIELD") or None,
            }
            try:
                config = JiraInstanceSettings.model_validate(values)
                configs[name] = config
            except ValidationError as exc:
                errors.extend(f"{prefix}{error['loc'][0]}: {error['msg']}" for error in exc.errors())
        if errors:
            raise ConfigurationError(errors)
        return configs

    def validate_startup(self) -> None:
        errors: list[str] = []
        try:
            llm = self.llm
            if not llm.api_key.get_secret_value():
                errors.append("LLM_API_KEY is required")
        except ConfigurationError as exc:
            errors.extend(exc.errors)
        try:
            self.jira_configs()  # Parse names and auth types; credentials validate lazily.
        except ConfigurationError as exc:
            errors.extend(exc.errors)
        if errors:
            raise ConfigurationError(errors)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 6.4 `backend/models.py`

```python
"""Shared API and domain models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Story(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    user_story: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    technical_breakdown: str | None = None
    existing_points: float | None = None
    key: str | None = None
    status: str | None = None
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    source: Literal["manual", "jira", "upload"] = "manual"
    jira_instance: str | None = None

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def normalize_criteria(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.replace(";", "\n").splitlines() if part.strip()]
        return [str(part).strip() for part in value if str(part).strip()]


class EstimateRequest(BaseModel):
    story: Story
    session_id: str | None = None
    refinement: str | None = None


class BatchEstimateRequest(BaseModel):
    stories: list[Story] = Field(min_length=1, max_length=100)
    session_id: str | None = None


class UploadEstimateRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    mapping: dict[str, str | None]
    session_id: str | None = None


class JiraWriteRequest(BaseModel):
    points: int
    confirm: bool = False


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: Any | None = None
    retryable: bool = False
```

### 6.5 `backend/anchors.py`

```python
"""Deterministic calibration stories. Edit this file to tune team baselines."""

from __future__ import annotations

ANCHORS = [
    {
        "title": "Inline validation on a React payment form",
        "full_text": "Add client-side validation and accessible error summaries to an existing form.",
        "acceptance_criteria": ["Validate four existing fields", "Focus the first error", "Add component tests"],
        "points": 3,
        "rationale": "React-only, established patterns, no service or data changes, modest testing.",
    },
    {
        "title": "Add an entitlement-protected account preference",
        "full_text": "Add a preference in React and persist it through an existing Spring service endpoint.",
        "acceptance_criteria": ["Hide control without entitlement", "Persist and retrieve value", "Audit the change"],
        "points": 5,
        "rationale": "Small cross-stack change using known patterns with entitlement and audit coverage.",
    },
    {
        "title": "Search and filter an existing transaction endpoint",
        "full_text": "Add two indexed filters to an existing API and expose them in the transaction table.",
        "acceptance_criteria": ["Combine filters", "Preserve pagination", "Test query performance"],
        "points": 5,
        "rationale": "Cross-stack but bounded; some database and performance work, little domain uncertainty.",
    },
    {
        "title": "Cross-market eKYC status integration",
        "full_text": "Consume a vendor status API and show normalized eKYC states in two market journeys.",
        "acceptance_criteria": ["Map vendor states", "Apply market residency rules", "Audit transitions", "Handle timeouts"],
        "points": 8,
        "rationale": "Integration-heavy with regulatory rules, failure handling, audit, and multi-market tests.",
    },
    {
        "title": "Transaction-wide AI summary with audit",
        "full_text": "Generate and store a summary across transaction records with traceable model metadata.",
        "acceptance_criteria": ["Write atomically", "Record full audit metadata", "Redact sensitive data", "Support retry"],
        "points": 8,
        "rationale": "Broad Spring and data work with transactional consistency, compliance, and operational uncertainty.",
    },
    {
        "title": "New multi-market payment orchestration journey",
        "full_text": "Create a new UI journey and orchestration service spanning screening, limits, and posting systems.",
        "acceptance_criteria": ["Support three markets", "Compensate partial failures", "Enforce entitlements", "Full audit trail"],
        "points": 13,
        "rationale": "Multiple new layers and external dependencies with high uncertainty; should be split before delivery.",
    },
]
```

### 6.6 `backend/llm/factory.py`

```python
"""The only module that knows how provider names become chat models."""

from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from backend.config import ConfigurationError, get_settings

OPENAI_COMPATIBLE = {"moonshot", "deepseek", "openrouter", "ollama", "vllm", "compatible"}
NATIVE_PROVIDERS = {"anthropic", "google_genai", "openai", "groq", "mistral"}
SchemaT = TypeVar("SchemaT", bound=BaseModel)


def validate_factory_config() -> None:
    """Validate provider-specific settings without leaking conditionals elsewhere."""
    config = get_settings().llm
    provider = config.provider.lower()
    errors = []
    if provider not in OPENAI_COMPATIBLE | NATIVE_PROVIDERS:
        errors.append(f"Unsupported LLM_PROVIDER '{config.provider}'")
    if provider in OPENAI_COMPATIBLE and not config.base_url:
        errors.append(f"LLM_BASE_URL is required for provider '{config.provider}'")
    if errors:
        raise ConfigurationError(errors)


@lru_cache
def get_llm() -> BaseChatModel:
    """Build the configured chat model. No caller needs provider conditionals."""
    config = get_settings().llm
    provider = config.provider.lower()
    validate_factory_config()
    common = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "api_key": config.api_key.get_secret_value(),
        "max_retries": 1,
    }
    if provider in OPENAI_COMPATIBLE:
        return ChatOpenAI(**common, base_url=config.base_url)
    return init_chat_model(model_provider=provider, **common)


def get_structured_llm(schema: type[SchemaT]) -> Runnable:
    """Return a schema-constrained model using the provider's reliable mode."""
    config = get_settings().llm
    model = get_llm()
    if config.provider.lower() == "groq":
        # Groq JSON mode avoids tool_use_failed errors from otherwise-valid tool args.
        return model.with_structured_output(schema, method="json_mode", include_raw=True)
    return model.with_structured_output(schema, include_raw=True)
```

### 6.7 `backend/graph/state.py`

```python
"""Typed LangGraph state and structured node output contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

ScoreLevel = Literal["Low", "Medium", "High"]
PARAMETERS = [
    "complexity",
    "volume",
    "uncertainty",
    "react_scope",
    "spring_scope",
    "existing_code_scope",
    "dependencies",
    "nfrs",
    "testing",
    "compliance_audit",
    "familiarity",
    "dod_overhead",
]


class ParameterScore(BaseModel):
    parameter: Literal[
        "complexity", "volume", "uncertainty", "react_scope", "spring_scope",
        "existing_code_scope", "dependencies", "nfrs", "testing",
        "compliance_audit", "familiarity", "dod_overhead"
    ]
    score: ScoreLevel
    reason: str = Field(min_length=5, max_length=240)


class ScorecardOutput(BaseModel):
    scores: list[ParameterScore]


class DriversOutput(BaseModel):
    drivers: list[str] = Field(min_length=2, max_length=3)
    explanation: str


class AnchorComparisonOutput(BaseModel):
    comparison: str
    anchor_titles: list[str] = Field(min_length=1, max_length=3)


class PointsOutput(BaseModel):
    points: Literal[1, 2, 3, 5, 8, 13]
    derivation: str


class EffortRange(BaseModel):
    optimistic: float = Field(ge=0)
    likely: float = Field(ge=0)
    pessimistic: float = Field(ge=0)


class LayerEffort(BaseModel):
    react: str
    spring: str
    existing_code: str
    person_days: EffortRange


class PlainLanguageOutput(BaseModel):
    plain_language_why: str
    tldr: str
    effort: LayerEffort


class HiddenTask(BaseModel):
    task: str
    weight: str


class HiddenTasksOutput(BaseModel):
    hidden_tasks: list[HiddenTask]


class Risk(BaseModel):
    risk: str
    mitigation_or_assumption: str


class RisksOutput(BaseModel):
    risks: list[Risk] = Field(min_length=1, max_length=3)
    assumptions: list[str]
    spike_recommended: bool
    spike_reason: str | None = None


class SplitOutput(BaseModel):
    split_recommended: bool
    rationale: str
    proposed_stories: list[str] = Field(default_factory=list)


class EstimationState(TypedDict, total=False):
    story: dict[str, Any]
    anchors: list[dict[str, Any]]
    scorecard: list[dict[str, Any]]
    drivers: list[str]
    drivers_explanation: str
    anchor_comparison: str
    anchor_titles: list[str]
    points: int
    points_derivation: str
    plain_language_why: str
    tldr: str
    effort: dict[str, Any]
    hidden_tasks: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    assumptions: list[str]
    spike_recommended: bool
    spike_reason: str | None
    split_recommendation: dict[str, Any]
    escalation_required: bool
    refinement: str | None
    messages: Annotated[list[AnyMessage], add_messages]
```

### 6.8 `backend/graph/nodes.py`

```python
"""All estimation node prompts and implementations live here."""

from __future__ import annotations

import asyncio
import json
import re
import types
from typing import Any, Literal, TypeVar, Union, get_args, get_origin

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from backend.graph.state import (
    PARAMETERS,
    AnchorComparisonOutput,
    DriversOutput,
    EstimationState,
    HiddenTasksOutput,
    PlainLanguageOutput,
    PointsOutput,
    RisksOutput,
    ScorecardOutput,
    SplitOutput,
)
from backend.llm.factory import get_structured_llm

T = TypeVar("T", bound=BaseModel)

SYSTEM = """You are a senior full-stack agile estimator for a regulated bank.
The team builds React micro-frontends and Spring Boot microservices on OpenShift.
Be concrete, cautious, concise, and explain every judgment from the supplied evidence.
Never invent requirements. Use plain language and modified Fibonacci only."""


def _context(state: EstimationState, fields: tuple[str, ...]) -> str:
    return json.dumps(
        {field: state.get(field) for field in fields},
        indent=2,
        default=str,
    )


def _parse_structured_result(schema: type[T], result: Any) -> T:
    """Validate structured output, tolerating provider wrappers and JSON envelopes."""
    candidates: list[Any] = []
    parsing_error: Exception | None = None
    if isinstance(result, dict) and {"raw", "parsed", "parsing_error"} <= result.keys():
        if result["parsed"] is not None:
            candidates.append(result["parsed"])
        raw = result.get("raw")
        candidates.append(getattr(raw, "content", raw))
        parsing_error = result.get("parsing_error")
    else:
        candidates.append(result)

    while candidates:
        candidate = candidates.pop(0)
        if candidate is None:
            continue
        if isinstance(candidate, schema):
            return candidate
        if isinstance(candidate, str):
            text = candidate.strip()
            if text.startswith("```"):
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                candidates.insert(0, json.loads(text))
            except json.JSONDecodeError:
                continue
            continue
        if isinstance(candidate, list):
            # Some Groq models return [echoed_schema, actual_result]. Prefer the last item.
            candidates[0:0] = list(reversed(candidate))
            continue
        if isinstance(candidate, dict):
            try:
                return schema.model_validate(candidate)
            except Exception:
                for key in ("text", "content", "output"):
                    if key in candidate:
                        candidates.append(candidate[key])

    detail = str(parsing_error or "response did not contain a matching JSON object")
    raise ValueError(detail[:500])


def _annotation_contract(annotation: Any, indent: str = "") -> list[str]:
    """Describe a Pydantic annotation without emitting JSON the model can echo."""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return ["one of: " + ", ".join(repr(value) for value in args)]
    if origin is list:
        item = args[0] if args else Any
        description = _annotation_contract(item, indent + "  ")
        return ["array whose items are " + description[0], *description[1:]]
    if origin in {Union, types.UnionType}:
        non_null = [arg for arg in args if arg is not type(None)]
        if len(non_null) == 1:
            return _annotation_contract(non_null[0], indent)
        return [" or ".join(_annotation_contract(arg, indent)[0] for arg in non_null)]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        lines = [f"object `{annotation.__name__}` with fields:"]
        for name, field in annotation.model_fields.items():
            nested = _annotation_contract(field.annotation, indent + "  ")
            requirement = "required" if field.is_required() else "optional"
            lines.append(f"{indent}  - `{name}` ({requirement}): {nested[0]}")
            lines.extend(f"{indent}    {line}" for line in nested[1:])
        return lines
    names = {str: "string", int: "integer", float: "number", bool: "boolean", Any: "any JSON value"}
    return [names.get(annotation, getattr(annotation, "__name__", str(annotation)))]


def _schema_contract(schema: type[BaseModel]) -> str:
    """Create plain-text output instructions rather than an echoable JSON Schema."""
    lines = [
        f"Return one JSON object for `{schema.__name__}`. Do not return the schema itself.",
        "Fields:",
    ]
    for name, field in schema.model_fields.items():
        description = _annotation_contract(field.annotation)
        requirement = "required" if field.is_required() else "optional"
        constraints = []
        for item in field.metadata:
            if hasattr(item, "min_length"):
                constraints.append(f"minimum {item.min_length} items/characters")
            if hasattr(item, "max_length"):
                constraints.append(f"maximum {item.max_length} items/characters")
        suffix = f"; {', '.join(constraints)}" if constraints else ""
        lines.append(f"- `{name}` ({requirement}): {description[0]}{suffix}")
        lines.extend(f"  {line}" for line in description[1:])
    return "\n".join(lines)


def _retry_delay(error: Exception, attempt: int) -> float:
    """Honor provider retry hints, with a small fallback backoff."""
    match = re.search(r"try again in\s+([0-9.]+)s", str(error), flags=re.IGNORECASE)
    return min(float(match.group(1)) + 0.5, 65.0) if match else float(2 ** attempt)


async def _invoke(
    schema: type[T],
    prompt: str,
    state: EstimationState,
    context_fields: tuple[str, ...],
) -> T:
    model = get_structured_llm(schema)
    output_contract = _schema_contract(schema)
    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(
            content=(
                f"{prompt}\n\nReturn only one valid JSON object matching the contract exactly. "
                f"The response root must be an object, never an array. Do not use markdown "
                f"or function-call tags.\nOUTPUT CONTRACT:\n{output_contract}"
                f"\n\nCONTEXT:\n{_context(state, context_fields)}"
            )
        ),
    ]
    last_error: Exception | None = None
    for _ in range(2):
        try:
            result = await model.ainvoke(messages)
            return _parse_structured_result(schema, result)
        except Exception as exc:
            last_error = RuntimeError(str(exc)[:500])
            if len(messages) == 2:
                await asyncio.sleep(_retry_delay(exc, 0))
            messages.append(
                HumanMessage(content="The prior output was invalid. Return only schema-valid JSON with every required field.")
            )
    raise RuntimeError(f"The model could not produce valid {schema.__name__} output: {last_error}")


def _trace(node: str, summary: str) -> list[AIMessage]:
    return [AIMessage(content=summary, name=node)]


async def score_parameters(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        ScorecardOutput,
        f"Score exactly these 12 parameters once each as Low, Medium, or High, with a one-line evidence-based reason: {', '.join(PARAMETERS)}.",
        state,
        ("story", "refinement"),
    )
    found = {item.parameter for item in result.scores}
    if found != set(PARAMETERS):
        raise RuntimeError(f"Scorecard omitted parameters: {sorted(set(PARAMETERS) - found)}")
    scores = [item.model_dump() for item in result.scores]
    return {"scorecard": scores, "messages": _trace("score_parameters", "Scored all estimation parameters.")}


async def identify_drivers(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        DriversOutput,
        "Name the 2-3 scorecard parameters that genuinely decide the estimate. Explain why they dominate.",
        state,
        ("story", "scorecard"),
    )
    return {"drivers": result.drivers, "drivers_explanation": result.explanation, "messages": _trace("identify_drivers", "Identified the estimate drivers.")}


async def compare_to_anchors(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        AnchorComparisonOutput,
        "Compare explicitly with named fixed anchors and their points. Say bigger than, smaller than, or similar to each selected anchor and why.",
        state,
        ("story", "scorecard", "drivers", "anchors"),
    )
    return {"anchor_comparison": result.comparison, "anchor_titles": result.anchor_titles, "messages": _trace("compare_to_anchors", "Compared the story with calibration anchors.")}


async def derive_points(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        PointsOutput,
        "Conclude 1, 2, 3, 5, 8, or 13 strictly as a consequence of the scorecard, drivers, and anchor comparison. Defend the conclusion; do not guess.",
        state,
        ("story", "scorecard", "drivers", "anchor_comparison"),
    )
    uncertainty = next((item["score"] for item in state["scorecard"] if item["parameter"] == "uncertainty"), "Low")
    escalation = result.points == 13 or uncertainty == "High"
    return {"points": result.points, "points_derivation": result.derivation, "escalation_required": escalation, "messages": _trace("derive_points", "Derived a Fibonacci estimate from the evidence.")}


async def escalation_branch(state: EstimationState) -> dict[str, Any]:
    return {"spike_recommended": True, "spike_reason": "The estimate is 13 or uncertainty is high; reduce uncertainty before commitment.", "messages": _trace("spike_split_branch", "Flagged the story for spike/split treatment.")}


def route_after_points(state: EstimationState) -> str:
    return "escalate" if state.get("escalation_required") else "continue"


async def write_plain_language_reasoning(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        PlainLanguageOutput,
        "Write a 3-5 sentence 'Why this is an N' explanation for a product owner, naming drivers and an anchor in everyday terms. Also write a one-line TL;DR beginning with 'N -'. Provide React, Spring, existing-code effort and optimistic/likely/pessimistic person-days.",
        state,
        ("story", "drivers", "anchor_comparison", "points", "points_derivation"),
    )
    return {"plain_language_why": result.plain_language_why, "tldr": result.tldr, "effort": result.effort.model_dump(), "messages": _trace("write_plain_language_reasoning", "Explained the estimate in plain language.")}


async def detect_hidden_tasks(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        HiddenTasksOutput,
        "Surface sub-tasks implied by the acceptance criteria but easy to miss, especially audit, entitlement, data residency, cross-market, deployment, and testing work. For each, say why it adds weight. Return none when evidence does not imply any.",
        state,
        ("story", "scorecard", "points"),
    )
    return {"hidden_tasks": [item.model_dump() for item in result.hidden_tasks], "messages": _trace("detect_hidden_tasks", "Checked acceptance criteria for hidden work.")}


async def assess_risks(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        RisksOutput,
        "Give the top 3 concrete risks or unknowns and explicit assumptions. Recommend a spike when uncertainty is high. Preserve an already-triggered spike recommendation.",
        state,
        ("story", "scorecard", "points", "hidden_tasks", "spike_recommended"),
    )
    spike = state.get("spike_recommended", False) or result.spike_recommended
    reason = state.get("spike_reason") or result.spike_reason
    return {"risks": [item.model_dump() for item in result.risks], "assumptions": result.assumptions, "spike_recommended": spike, "spike_reason": reason, "messages": _trace("assess_risks", "Assessed risks, assumptions, and spike need.")}


async def recommend_split(state: EstimationState) -> dict[str, Any]:
    result = await _invoke(
        SplitOutput,
        "Recommend whether to split. A 13 must be split and must include proposed independently valuable sub-stories with suggested Fibonacci sizes in their text. Avoid splitting merely by technical layer.",
        state,
        ("story", "points", "drivers", "risks", "spike_recommended"),
    )
    if state.get("points") == 13:
        result.split_recommended = True
    return {"split_recommendation": result.model_dump(), "messages": _trace("recommend_split", "Completed the split recommendation.")}
```

### 6.9 `backend/graph/build.py`

```python
"""LangGraph StateGraph wiring and checkpointed compiled graph."""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.graph.nodes import (
    assess_risks,
    compare_to_anchors,
    derive_points,
    detect_hidden_tasks,
    escalation_branch,
    identify_drivers,
    recommend_split,
    route_after_points,
    score_parameters,
    write_plain_language_reasoning,
)
from backend.graph.state import EstimationState


@lru_cache
def get_estimation_graph():
    builder = StateGraph(EstimationState)
    builder.add_node("score_parameters", score_parameters)
    builder.add_node("identify_drivers", identify_drivers)
    builder.add_node("compare_to_anchors", compare_to_anchors)
    builder.add_node("derive_points", derive_points)
    builder.add_node("spike_split_branch", escalation_branch)
    builder.add_node("write_plain_language_reasoning", write_plain_language_reasoning)
    builder.add_node("detect_hidden_tasks", detect_hidden_tasks)
    builder.add_node("assess_risks", assess_risks)
    builder.add_node("recommend_split", recommend_split)

    builder.add_edge(START, "score_parameters")
    builder.add_edge("score_parameters", "identify_drivers")
    builder.add_edge("identify_drivers", "compare_to_anchors")
    builder.add_edge("compare_to_anchors", "derive_points")
    builder.add_conditional_edges(
        "derive_points",
        route_after_points,
        {"escalate": "spike_split_branch", "continue": "write_plain_language_reasoning"},
    )
    builder.add_edge("spike_split_branch", "write_plain_language_reasoning")
    builder.add_edge("write_plain_language_reasoning", "detect_hidden_tasks")
    builder.add_edge("detect_hidden_tasks", "assess_risks")
    builder.add_edge("assess_risks", "recommend_split")
    builder.add_edge("recommend_split", END)
    return builder.compile(checkpointer=MemorySaver())
```

### 6.10 `backend/api/main.py`

```python
"""FastAPI routes for streaming estimation, Jira, and spreadsheet ingestion."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.messages import HumanMessage

from backend.anchors import ANCHORS
from backend.config import ConfigurationError, get_settings
from backend.graph.build import get_estimation_graph
from backend.ingest.excel import UploadError, dataframe_payload, read_upload, rows_to_stories, template_workbook
from backend.jira.client import JiraError
from backend.jira.registry import get_jira_registry
from backend.llm.factory import validate_factory_config
from backend.models import (
    BatchEstimateRequest,
    ErrorPayload,
    EstimateRequest,
    JiraWriteRequest,
    Story,
    UploadEstimateRequest,
)


def error_response(code: str, message: str, status: int, *, details: Any = None, retryable: bool = False) -> JSONResponse:
    payload = ErrorPayload(code=code, message=message, details=details, retryable=retryable)
    return JSONResponse(status_code=status, content={"error": payload.model_dump()})


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        get_settings().validate_startup()
        validate_factory_config()
        app.state.configuration_errors = []
    except ConfigurationError as exc:
        # Keep diagnostics endpoints alive so the UI can render the startup error.
        app.state.configuration_errors = exc.errors
    yield


app = FastAPI(title="Story Pointer API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response("validation_error", "The request contains invalid fields.", 422, details=exc.errors())


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    return error_response(
        detail.get("code", "http_error"),
        detail.get("message", "The request could not be completed."),
        exc.status_code,
        details=detail.get("details"),
    )


@app.exception_handler(JiraError)
async def jira_error(_: Request, exc: JiraError) -> JSONResponse:
    status = 502 if exc.status is None or exc.status >= 500 else 400
    return error_response("jira_error", str(exc), status, retryable=exc.retryable)


@app.exception_handler(UploadError)
async def upload_error(_: Request, exc: UploadError) -> JSONResponse:
    return error_response("parse_error", str(exc), 400)


def require_llm_config(request: Request) -> None:
    errors = getattr(request.app.state, "configuration_errors", [])
    if errors:
        raise HTTPException(status_code=503, detail={"code": "configuration_error", "message": "LLM configuration is incomplete.", "details": errors})


def sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


def public_result(values: dict[str, Any]) -> dict[str, Any]:
    blocked = {"anchors", "messages", "escalation_required", "refinement"}
    return {key: value for key, value in values.items() if key not in blocked}


async def stream_story(story: Story, session_id: str, refinement: str | None = None) -> AsyncIterator[bytes]:
    graph = get_estimation_graph()
    config = {"configurable": {"thread_id": session_id}}
    initial = {
        "story": story.model_dump(),
        "anchors": ANCHORS,
        "refinement": refinement,
        "messages": [HumanMessage(content=refinement or f"Estimate: {story.title}")],
    }
    yield sse("started", {"session_id": session_id, "title": story.title})
    try:
        async for update in graph.astream(initial, config=config, stream_mode="updates"):
            node = next(iter(update))
            # Progress carries only completion and safe narrative summaries; the final event is atomic.
            yield sse("node", {"node": node, "status": "completed"})
        snapshot = await graph.aget_state(config)
        result = public_result(dict(snapshot.values))
        if not result.get("plain_language_why") or not result.get("tldr"):
            raise RuntimeError("The model returned points without the required explanation")
        yield sse("result", result)
    except Exception as exc:
        yield sse("error", {"code": "estimation_error", "message": str(exc), "retryable": True})


async def stream_batch(stories: list[Story], root_session: str, skipped: list[dict[str, Any]] | None = None) -> AsyncIterator[bytes]:
    yield sse("batch_started", {"count": len(stories), "session_id": root_session, "skipped": skipped or []})
    results = []
    for index, story in enumerate(stories):
        item_session = f"{root_session}:{index}"
        yield sse("item_started", {"index": index, "title": story.title})
        async for chunk in stream_story(story, item_session):
            text = chunk.decode()
            if text.startswith("event: result"):
                data = json.loads(text.split("data: ", 1)[1])
                results.append(data)
                yield sse("item_result", {"index": index, "result": data})
            elif text.startswith("event: node"):
                data = json.loads(text.split("data: ", 1)[1])
                yield sse("item_node", {"index": index, **data})
            elif text.startswith("event: error"):
                data = json.loads(text.split("data: ", 1)[1])
                yield sse("item_error", {"index": index, **data})
    yield sse("batch_result", {"results": results, "skipped": skipped or []})


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    errors = getattr(request.app.state, "configuration_errors", [])
    return {
        "status": "degraded" if errors else "ok",
        "llm": {"status": "configuration_error" if errors else "configured", "errors": errors},
        "jira": await get_jira_registry().health(),
    }


@app.get("/config")
async def active_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
        "jira_instances": get_jira_registry().list_instances(),
        "jira_write_enabled": settings.jira_write_enabled,
    }


@app.get("/jira/instances")
async def jira_instances() -> list[dict[str, str]]:
    return get_jira_registry().list_instances()


@app.get("/jira/{instance}/project/{code}/issues")
async def jira_issues(
    instance: str,
    code: str,
    status: str | None = None,
    sprint: str | None = None,
    page_size: int = Query(50, ge=1, le=100),
    max_issues: int = Query(500, ge=1, le=1000),
) -> list[dict[str, Any]]:
    stories = await get_jira_registry().get_client(instance).fetch_project_issues(
        code, status=status, sprint=sprint, page_size=page_size, max_issues=max_issues
    )
    return [story.model_dump() for story in stories]


@app.post("/upload/parse")
async def parse_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise UploadError("File exceeds the 15 MB upload limit")
    return dataframe_payload(read_upload(content, file.filename or "upload"))


@app.get("/upload/template")
async def upload_template() -> Response:
    return Response(
        template_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="story-pointer-template.xlsx"'},
    )


@app.post("/estimate")
async def estimate(payload: EstimateRequest, request: Request) -> StreamingResponse:
    require_llm_config(request)
    session = payload.session_id or str(uuid.uuid4())
    return StreamingResponse(stream_story(payload.story, session, payload.refinement), media_type="text/event-stream")


@app.post("/estimate/batch")
async def estimate_batch(payload: BatchEstimateRequest, request: Request) -> StreamingResponse:
    require_llm_config(request)
    session = payload.session_id or str(uuid.uuid4())
    return StreamingResponse(stream_batch(payload.stories, session), media_type="text/event-stream")


@app.post("/upload/estimate")
async def upload_estimate(payload: UploadEstimateRequest, request: Request) -> StreamingResponse:
    require_llm_config(request)
    stories, skipped = rows_to_stories(payload.rows, payload.mapping)
    if not stories:
        raise UploadError("No valid rows remain after mapping")
    session = payload.session_id or str(uuid.uuid4())
    return StreamingResponse(stream_batch(stories, session, skipped), media_type="text/event-stream")


@app.post("/jira/{instance}/{issue_key}/points")
async def write_jira_points(instance: str, issue_key: str, payload: JiraWriteRequest) -> dict[str, Any]:
    settings = get_settings()
    if not settings.jira_write_enabled:
        raise HTTPException(status_code=403, detail={"code": "write_disabled", "message": "Jira write-back is disabled by configuration."})
    if not payload.confirm:
        raise HTTPException(status_code=400, detail={"code": "confirmation_required", "message": "Set confirm=true after explicit user confirmation."})
    await get_jira_registry().get_client(instance).write_points(issue_key, payload.points)
    return {"status": "updated", "issue_key": issue_key, "points": payload.points}
```

### 6.11 `backend/jira/client.py`

```python
"""Small async Jira REST v3/v2 wrapper using httpx."""

from __future__ import annotations

import re
from typing import Any

import httpx

from backend.config import JiraInstanceSettings
from backend.jira.mapping import issue_to_story
from backend.models import Story


class JiraError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        self.status = status
        self.retryable = retryable
        super().__init__(message)


class JiraClient:
    """Read Jira issues and perform an explicitly gated points update."""

    def __init__(self, config: JiraInstanceSettings) -> None:
        self.config = config

    def _headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        token = self.config.api_token.get_secret_value()
        if self.config.auth_type == "cloud":
            return {"Accept": "application/json"}, httpx.BasicAuth(self.config.email or "", token)
        return {"Accept": "application/json", "Authorization": f"Bearer {token}"}, None

    @property
    def api_version(self) -> str:
        return "3" if self.config.auth_type == "cloud" else "2"

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers, auth = self._headers_and_auth()
        url = f"{self.config.base_url}/rest/api/{self.api_version}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=30, headers=headers, auth=auth) as client:
                    response = await client.request(method, url, **kwargs)
                if response.status_code >= 400:
                    detail = response.json() if "json" in response.headers.get("content-type", "") else response.text
                    retryable = response.status_code in {429, 502, 503, 504}
                    if retryable and attempt == 0:
                        continue
                    raise JiraError(
                        f"Jira returned {response.status_code}: {detail}",
                        status=response.status_code,
                        retryable=retryable,
                    )
                return response.json() if response.content else {}
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
        raise JiraError(f"Could not reach Jira: {last_error}", retryable=True)

    async def health(self) -> dict[str, Any]:
        try:
            await self._request("GET", "myself")
            return {"status": "ok", "message": "Connected"}
        except JiraError as exc:
            return {"status": "error", "message": str(exc), "retryable": exc.retryable}

    async def fetch_project_issues(
        self,
        project_code: str,
        *,
        status: str | None = None,
        sprint: str | None = None,
        page_size: int = 50,
        max_issues: int = 500,
    ) -> list[Story]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,49}", project_code):
            raise JiraError("Project code contains invalid characters")
        clauses = [f'project = "{project_code}"']
        if status:
            clauses.append(f'status = "{status.replace(chr(34), chr(92) + chr(34))}"')
        if sprint:
            clauses.append(f'sprint = "{sprint.replace(chr(34), chr(92) + chr(34))}"')
        jql = " AND ".join(clauses) + " ORDER BY created DESC"
        fields = ["summary", "description", "status", "labels", "components"]
        if self.config.story_points_field:
            fields.append(self.config.story_points_field)
        if self.config.ac_field:
            fields.append(self.config.ac_field)

        stories: list[Story] = []
        start_at = 0
        next_page_token: str | None = None
        while len(stories) < max_issues:
            size = min(page_size, max_issues - len(stories))
            params = {"jql": jql, "maxResults": size, "fields": ",".join(fields)}
            if self.config.auth_type == "cloud":
                if next_page_token:
                    params["nextPageToken"] = next_page_token
                payload = await self._request("GET", "search/jql", params=params)
            else:
                params["startAt"] = start_at
                payload = await self._request("GET", "search", params=params)
            issues = payload.get("issues") or []
            stories.extend(issue_to_story(issue, self.config) for issue in issues)
            start_at += len(issues)
            if self.config.auth_type == "cloud":
                next_page_token = payload.get("nextPageToken")
                if not issues or payload.get("isLast") is True or not next_page_token:
                    break
            elif not issues or start_at >= payload.get("total", 0):
                break
        return stories

    async def write_points(self, issue_key: str, points: int) -> None:
        field = self.config.story_points_field
        if not field:
            raise JiraError("Story Points field is not configured for this Jira instance")
        await self._request("PUT", f"issue/{issue_key}", json={"fields": {field: points}})
```

### 6.12 `backend/jira/mapping.py`

```python
"""Custom-field-aware Jira issue mapping in one tunable module."""

from __future__ import annotations

import re
from typing import Any

from backend.config import JiraInstanceSettings
from backend.models import Story


def adf_to_text(value: Any) -> str:
    """Flatten Jira Cloud Atlassian Document Format or accept plain server text."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (adf_to_text(item) for item in value)))
    if isinstance(value, dict):
        text = value.get("text", "")
        children = adf_to_text(value.get("content", []))
        return "\n".join(filter(None, (text, children)))
    return str(value)


def split_acceptance_criteria(value: Any, description: str) -> list[str]:
    text = adf_to_text(value).strip()
    if not text:
        match = re.search(
            r"(?:acceptance criteria|given\s.+?when\s.+?then)\s*:?\s*(.+)",
            description,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = match.group(1) if match else ""
    lines = re.split(r"(?:\r?\n|;)+", text)
    return [re.sub(r"^[\s*\-\d.)]+", "", line).strip() for line in lines if line.strip()]


def issue_to_story(issue: dict[str, Any], config: JiraInstanceSettings) -> Story:
    fields = issue.get("fields") or {}
    description = adf_to_text(fields.get("description"))
    ac_value = fields.get(config.ac_field) if config.ac_field else None
    points = fields.get(config.story_points_field) if config.story_points_field else None
    return Story(
        title=fields.get("summary") or issue.get("key") or "Untitled Jira issue",
        user_story=description,
        acceptance_criteria=split_acceptance_criteria(ac_value, description),
        existing_points=points,
        key=issue.get("key"),
        status=(fields.get("status") or {}).get("name"),
        labels=fields.get("labels") or [],
        components=[item.get("name", "") for item in fields.get("components") or [] if item.get("name")],
        source="jira",
        jira_instance=config.name,
    )
```

### 6.13 `backend/jira/registry.py`

```python
"""Named Jira instance registry, mirroring the LLM factory boundary."""

from __future__ import annotations

from functools import lru_cache

from backend.config import JiraInstanceSettings, get_settings
from backend.jira.client import JiraClient, JiraError


class JiraRegistry:
    def __init__(self, configs: dict[str, JiraInstanceSettings]) -> None:
        self.configs = configs
        self._clients: dict[str, JiraClient] = {}

    def list_instances(self) -> list[dict[str, str]]:
        return [{"name": item.name, "auth_type": item.auth_type} for item in self.configs.values()]

    def get_client(self, name: str) -> JiraClient:
        key = name.lower()
        if key not in self.configs:
            raise JiraError(f"Unknown Jira instance '{name}'")
        config = self.configs[key]
        missing = []
        if not config.base_url:
            missing.append("BASE_URL")
        if not config.api_token.get_secret_value():
            missing.append("API_TOKEN")
        if config.auth_type == "cloud" and not config.email:
            missing.append("EMAIL")
        if missing:
            raise JiraError(f"Jira instance '{name}' is missing: {', '.join(missing)}")
        if key not in self._clients:
            self._clients[key] = JiraClient(config)
        return self._clients[key]

    async def health(self) -> dict[str, dict]:
        results = {}
        for name in self.configs:
            try:
                results[name] = await self.get_client(name).health()
            except JiraError as exc:
                results[name] = {"status": "error", "message": str(exc), "retryable": False}
        return results


@lru_cache
def get_jira_registry() -> JiraRegistry:
    return JiraRegistry(get_settings().jira_configs())
```

### 6.14 `backend/ingest/excel.py`

```python
"""Excel/CSV detection, mapping, validation, and template generation."""

from __future__ import annotations

import io
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from backend.models import Story

TARGET_ALIASES = {
    "title": ["title", "summary", "story title", "issue", "name"],
    "user_story": ["user story", "description", "story", "details", "requirement"],
    "acceptance_criteria": ["acceptance criteria", "acs", "ac", "criteria", "conditions of satisfaction"],
    "technical_breakdown": ["technical breakdown", "technical notes", "implementation", "dev notes"],
    "existing_points": ["existing points", "story points", "points", "sp", "estimate"],
}


class UploadError(ValueError):
    pass


def _score(header: str, alias: str) -> float:
    clean_header = re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()
    if clean_header == alias:
        return 1.0
    if alias in clean_header or clean_header in alias:
        return 0.9
    return SequenceMatcher(None, clean_header, alias).ratio()


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    suggestions: dict[str, str | None] = {}
    used: set[str] = set()
    for target, aliases in TARGET_ALIASES.items():
        candidates = [(max(_score(column, alias) for alias in aliases), column) for column in columns if column not in used]
        score, column = max(candidates, default=(0.0, ""))
        suggestions[target] = column if score >= 0.55 else None
        if suggestions[target]:
            used.add(column)
    return suggestions


def read_upload(content: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(io.BytesIO(content), dtype=object).fillna("")
        if suffix in {".xlsx", ".xls"}:
            engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
            return pd.read_excel(io.BytesIO(content), dtype=object, engine=engine).fillna("")
    except Exception as exc:
        raise UploadError(f"Could not parse {filename}: {exc}") from exc
    raise UploadError("Use a .csv, .xlsx, or .xls file")


def dataframe_payload(frame: pd.DataFrame, preview_rows: int = 20) -> dict[str, Any]:
    columns = [str(column) for column in frame.columns]
    rows = json.loads(frame.to_json(orient="records", date_format="iso"))
    rows = [{key: "" if value is None else value for key, value in row.items()} for row in rows]
    return {
        "columns": columns,
        "suggested_mapping": suggest_mapping(columns),
        "preview": rows[:preview_rows],
        "rows": rows,
        "row_count": len(rows),
    }


def rows_to_stories(
    rows: list[dict[str, Any]], mapping: dict[str, str | None]
) -> tuple[list[Story], list[dict[str, Any]]]:
    title_column = mapping.get("title")
    if not title_column:
        raise UploadError("Map a source column to Title before estimating")
    stories: list[Story] = []
    skipped: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        title = str(row.get(title_column, "")).strip()
        if not title:
            skipped.append({"row": index, "reason": "Title is blank"})
            continue
        points_raw = row.get(mapping.get("existing_points") or "", "")
        try:
            points = float(points_raw) if str(points_raw).strip() else None
        except (TypeError, ValueError):
            points = None
        stories.append(
            Story(
                title=title,
                user_story=str(row.get(mapping.get("user_story") or "", "")).strip(),
                acceptance_criteria=row.get(mapping.get("acceptance_criteria") or "", ""),
                technical_breakdown=str(row.get(mapping.get("technical_breakdown") or "", "")).strip() or None,
                existing_points=points,
                source="upload",
            )
        )
    return stories, skipped


def template_workbook() -> bytes:
    frame = pd.DataFrame(
        [
            {
                "Title": "Add beneficiary confirmation",
                "User Story": "As a customer, I want to confirm beneficiary details before payment.",
                "Acceptance Criteria": "Show beneficiary name\nRecord confirmation in audit trail",
                "Technical Breakdown": "React confirmation panel; Spring audit event",
                "Existing Points": "",
            }
        ]
    )
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Stories")
        sheet = writer.book["Stories"]
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = cell.font.copy(bold=True)
        for column, width in {"A": 34, "B": 60, "C": 60, "D": 50, "E": 18}.items():
            sheet.column_dimensions[column].width = width
    return output.getvalue()
```

### 6.15 `backend/tests/test_graph_routing.py`

```python
from backend.graph.nodes import route_after_points


def test_high_uncertainty_or_thirteen_routes_to_escalation():
    assert route_after_points({"escalation_required": True}) == "escalate"
    assert route_after_points({"escalation_required": False}) == "continue"
```

### 6.16 `backend/tests/test_ingest.py`

```python
import pandas as pd

from backend.ingest.excel import dataframe_payload, rows_to_stories, suggest_mapping


def test_header_mapping_and_row_validation():
    mapping = suggest_mapping(["Summary", "Description", "Acceptance Criteria", "SP"])
    assert mapping == {
        "title": "Summary",
        "user_story": "Description",
        "acceptance_criteria": "Acceptance Criteria",
        "technical_breakdown": None,
        "existing_points": "SP",
    }
    rows = [
        {"Summary": "Valid", "Description": "As a user", "Acceptance Criteria": "One; Two", "SP": "5"},
        {"Summary": "", "Description": "Missing title", "Acceptance Criteria": "", "SP": "bad"},
    ]
    stories, skipped = rows_to_stories(rows, mapping)
    assert stories[0].acceptance_criteria == ["One", "Two"]
    assert stories[0].existing_points == 5
    assert skipped == [{"row": 3, "reason": "Title is blank"}]


def test_dataframe_payload_preserves_all_rows_and_limits_preview():
    payload = dataframe_payload(pd.DataFrame([{"Title": str(index)} for index in range(25)]))
    assert payload["row_count"] == 25
    assert len(payload["preview"]) == 20
    assert len(payload["rows"]) == 25
```

### 6.17 `backend/tests/test_mapping.py`

```python
from pydantic import SecretStr

from backend.config import JiraInstanceSettings
from backend.jira.mapping import adf_to_text, issue_to_story


def config():
    return JiraInstanceSettings(
        name="prod", base_url="https://example.atlassian.net", auth_type="cloud",
        email="a@example.com", api_token=SecretStr("secret"),
        story_points_field="customfield_1", ac_field="customfield_2",
    )


def test_adf_and_custom_fields_are_mapped():
    issue = {"key": "PAY-1", "fields": {
        "summary": "Confirm payment", "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Story body"}]}]},
        "customfield_1": 5, "customfield_2": "First\nSecond", "status": {"name": "Ready"},
        "labels": ["payments"], "components": [{"name": "UI"}],
    }}
    story = issue_to_story(issue, config())
    assert adf_to_text(issue["fields"]["description"]).strip() == "Story body"
    assert story.key == "PAY-1"
    assert story.existing_points == 5
    assert story.acceptance_criteria == ["First", "Second"]


def test_description_acceptance_criteria_fallback():
    issue = {"key": "PAY-2", "fields": {"summary": "Fallback", "description": "Context\nAcceptance Criteria:\n- Audit the change\n- Enforce entitlement"}}
    story = issue_to_story(issue, config().model_copy(update={"ac_field": None}))
    assert story.acceptance_criteria == ["Audit the change", "Enforce entitlement"]
```

### 6.18 `backend/tests/test_structured_output.py`

```python
from langchain_core.messages import AIMessage

from backend.graph.nodes import _parse_structured_result, _schema_contract
from backend.graph.state import DriversOutput


def test_parses_provider_raw_json_when_langchain_parser_failed():
    result = {
        "raw": AIMessage(content='{"drivers":["dependencies","uncertainty"],"explanation":"External integration determines the estimate."}'),
        "parsed": None,
        "parsing_error": ValueError("provider parser failed"),
    }
    parsed = _parse_structured_result(DriversOutput, result)
    assert parsed.drivers == ["dependencies", "uncertainty"]


def test_uses_actual_result_when_provider_echoes_schema_in_array():
    result = {
        "raw": AIMessage(content='[{"title":"DriversOutput"},{"drivers":["dependencies","testing"],"explanation":"Integration and verification dominate."}]'),
        "parsed": None,
        "parsing_error": ValueError("root should be an object"),
    }
    parsed = _parse_structured_result(DriversOutput, result)
    assert parsed.drivers == ["dependencies", "testing"]


def test_contract_is_plain_text_that_cannot_be_echoed_as_json_schema():
    contract = _schema_contract(DriversOutput)
    assert "`drivers` (required): array" in contract
    assert "minimum 2 items/characters" in contract
    assert '"properties"' not in contract
    assert not contract.lstrip().startswith("{")
```

---

## 7. Complete source — frontend

### 7.1 `frontend/.env.example`

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

### 7.2 `frontend/vite.config.js`

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react()],
  build: { outDir: '../dist', emptyOutDir: true },
  server: { port: 5173 },
  test: { environment: 'jsdom', setupFiles: './src/test-setup.js' },
})
```

### 7.3 `frontend/index.html`

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="Evidence-led agile story point estimation" />
    <title>Story Pointer</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

### 7.4 `frontend/src/main.jsx`

```jsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
```

### 7.5 `frontend/src/test-setup.js`

```js
import '@testing-library/jest-dom/vitest'
```

### 7.6 `frontend/src/api/client.js`

```js
const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

async function jsonRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body.error || body.detail || body
    const error = new Error(detail.message || `Request failed (${response.status})`)
    error.payload = detail
    throw error
  }
  return body
}

export async function consumeSSE(path, payload, onEvent, signal) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.error || body.detail || body
    const error = new Error(detail.message || `Request failed (${response.status})`)
    error.payload = detail
    throw error
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      let event = 'message'
      const data = []
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) data.push(line.slice(5).trim())
      }
      if (data.length) onEvent(event, JSON.parse(data.join('\n')))
    }
    if (done) break
  }
}

export const api = {
  config: () => jsonRequest('/config'),
  health: () => jsonRequest('/health'),
  jiraInstances: () => jsonRequest('/jira/instances'),
  jiraIssues: (instance, project, filters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value))
    return jsonRequest(`/jira/${encodeURIComponent(instance)}/project/${encodeURIComponent(project)}/issues?${query}`)
  },
  parseUpload: async (file) => {
    const form = new FormData()
    form.append('file', file)
    return jsonRequest('/upload/parse', { method: 'POST', body: form })
  },
  estimate: (story, onEvent, signal, sessionId, refinement) =>
    consumeSSE('/estimate', { story, session_id: sessionId, refinement }, onEvent, signal),
  estimateBatch: (stories, onEvent, signal) =>
    consumeSSE('/estimate/batch', { stories }, onEvent, signal),
  estimateUpload: (rows, mapping, onEvent, signal) =>
    consumeSSE('/upload/estimate', { rows, mapping }, onEvent, signal),
  writePoints: (instance, key, points) =>
    jsonRequest(`/jira/${encodeURIComponent(instance)}/${encodeURIComponent(key)}/points`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points, confirm: true }),
    }),
  templateUrl: `${API_BASE}/upload/template`,
}
```

### 7.7 `frontend/src/App.jsx`

```jsx
import { BrainCircuit, ChevronRight, CircleHelp, Server } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from './api/client'
import BatchTable from './components/BatchTable'
import ColumnMapper from './components/ColumnMapper'
import ErrorCard from './components/ErrorCard'
import ExcelUpload from './components/ExcelUpload'
import JiraBrowser from './components/JiraBrowser'
import PipelineView from './components/PipelineView'
import ResultCard from './components/ResultCard'
import SourceSwitcher from './components/SourceSwitcher'
import StatusBadge from './components/StatusBadge'
import StoryForm from './components/StoryForm'

export default function App() {
  const [source, setSource] = useState('manual')
  const [config, setConfig] = useState(null)
  const [health, setHealth] = useState(null)
  const [issues, setIssues] = useState([])
  const [upload, setUpload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState([])
  const [pipelineTitle, setPipelineTitle] = useState('')
  const [result, setResult] = useState(null)
  const [results, setResults] = useState([])
  const [error, setError] = useState(null)
  const controller = useRef(null)

  useEffect(() => {
    Promise.all([api.config(), api.health()]).then(([nextConfig, nextHealth]) => { setConfig(nextConfig); setHealth(nextHealth) }).catch(setError)
    return () => controller.current?.abort()
  }, [])

  const begin = () => { setLoading(true); setError(null); setResult(null); setResults([]); setSteps([]); controller.current = new AbortController() }
  const end = () => setLoading(false)
  const onSingleEvent = (event, data) => {
    if (event === 'started') setPipelineTitle(data.title)
    if (event === 'node') setSteps((current) => [...current, data.node])
    if (event === 'result') setResult(data)
    if (event === 'error') setError(new Error(data.message))
  }
  const estimateOne = async (story) => { begin(); try { await api.estimate(story, onSingleEvent, controller.current.signal) } catch (err) { setError(err) } finally { end() } }
  const onBatchEvent = (event, data) => {
    if (event === 'item_started') { setPipelineTitle(data.title); setSteps([]) }
    if (event === 'item_node') setSteps((current) => [...current, data.node])
    if (event === 'item_result') setResults((current) => [...current, data.result])
    if (event === 'item_error' || event === 'error') setError(new Error(data.message))
  }
  const estimateBatch = async (stories) => { begin(); try { await api.estimateBatch(stories, onBatchEvent, controller.current.signal) } catch (err) { setError(err) } finally { end() } }
  const fetchJira = async (instance, project, filters) => { setError(null); setLoading(true); try { setIssues(await api.jiraIssues(instance, project, filters)) } catch (err) { setError(err) } finally { end() } }
  const parseFile = async (file) => { setError(null); setLoading(true); try { setUpload(await api.parseUpload(file)) } catch (err) { setError(err) } finally { end() } }
  const estimateUpload = async (rows, mapping) => { begin(); try { await api.estimateUpload(rows, mapping, onBatchEvent, controller.current.signal) } catch (err) { setError(err) } finally { end() } }
  const writePoints = async (item) => { if (!window.confirm(`Write ${item.points} points to ${item.story.key}? This changes Jira.`)) return; try { await api.writePoints(item.story.jira_instance, item.story.key, item.points); window.alert('Jira was updated.') } catch (err) { setError(err) } }

  const jiraStatuses = health?.jira ? Object.entries(health.jira) : []
  const configurationError = health?.llm?.errors?.length
    ? new Error(`Backend configuration: ${health.llm.errors.join('; ')}`)
    : null
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#top" aria-label="Story Pointer home"><span><BrainCircuit size={23} /></span><div><strong>Story Pointer</strong><small>Evidence-led estimation</small></div></a><div className="system-status"><div className="model-badge"><Server size={15} /><span>{config ? (config.llm.provider ? `${config.llm.provider} · ${config.llm.model}` : 'LLM not configured') : 'Checking model...'}</span></div>{jiraStatuses.map(([name, value]) => <StatusBadge key={name} status={value.status}>{name}</StatusBadge>)}</div></header>
    <main id="top"><section className="hero"><div><span className="eyebrow">Defensible by design</span><h1>A point is only useful when<br />everyone understands <em>why.</em></h1><p>Score the real work, calibrate it against your team’s anchors, and share a conclusion a product owner can grasp in five seconds.</p></div><div className="method-card"><CircleHelp size={20} /><div><strong>How it works</strong><ol><li>Score 12 delivery factors</li><li>Find the true drivers</li><li>Compare fixed anchors</li><li>Conclude, never guess</li></ol></div></div></section>
      <SourceSwitcher value={source} onChange={(value) => { setSource(value); setError(null) }} />
      <ErrorCard error={error || configurationError} />
      <div className="workspace">
        <div>{source === 'manual' && <StoryForm onSubmit={estimateOne} disabled={loading} />}{source === 'jira' && <JiraBrowser instances={config?.jira_instances || []} issues={issues} onFetch={fetchJira} onEstimate={estimateBatch} loading={loading} />}{source === 'upload' && (upload ? <ColumnMapper upload={upload} onEstimate={estimateUpload} loading={loading} /> : <ExcelUpload onUpload={parseFile} templateUrl={api.templateUrl} loading={loading} />)}</div>
        <PipelineView steps={steps} active={loading} title={pipelineTitle} />
      </div>
      {results.length > 0 && <BatchTable results={results} onSelect={setResult} />}
      {result && <ResultCard result={result} writeEnabled={config?.jira_write_enabled} onWrite={writePoints} />}
      {!loading && !result && !results.length && <div className="empty-hint"><span>1</span> Add the story <ChevronRight /><span>2</span> Watch the reasoning build <ChevronRight /><span>3</span> Share the justified estimate</div>}
    </main>
    <footer><span>Story Pointer · Reasoning before numbers</span><span>Active model: {config?.llm?.provider || '—'} / {config?.llm?.model || '—'}</span></footer>
  </div>
}
```

### 7.8 `frontend/src/components/StoryForm.jsx`

```jsx
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

const empty = { title: '', user_story: '', acceptance_criteria: [''], technical_breakdown: '', source: 'manual' }

export default function StoryForm({ onSubmit, disabled }) {
  const [story, setStory] = useState(empty)
  const set = (field, value) => setStory((current) => ({ ...current, [field]: value }))
  const setCriterion = (index, value) => set('acceptance_criteria', story.acceptance_criteria.map((item, i) => i === index ? value : item))
  const submit = (event) => {
    event.preventDefault()
    onSubmit({ ...story, acceptance_criteria: story.acceptance_criteria.filter((item) => item.trim()) })
  }
  return (
    <form className="input-card" onSubmit={submit}>
      <div className="section-heading"><div><span className="eyebrow">One story</span><h2>Describe the work</h2></div></div>
      <label>Title<input required value={story.title} onChange={(event) => set('title', event.target.value)} placeholder="What outcome are we delivering?" /></label>
      <label>User story<textarea required rows="3" value={story.user_story} onChange={(event) => set('user_story', event.target.value)} placeholder="As a..., I want..., so that..." /></label>
      <fieldset>
        <legend>Acceptance criteria</legend>
        <div className="criteria-list">
          {story.acceptance_criteria.map((criterion, index) => (
            <div className="criterion" key={index}>
              <span>{index + 1}</span>
              <input value={criterion} onChange={(event) => setCriterion(index, event.target.value)} placeholder="Observable condition of success" />
              <button type="button" className="icon-button" aria-label={`Remove criterion ${index + 1}`} disabled={story.acceptance_criteria.length === 1} onClick={() => set('acceptance_criteria', story.acceptance_criteria.filter((_, i) => i !== index))}><Trash2 size={16} /></button>
            </div>
          ))}
        </div>
        <button type="button" className="text-button" onClick={() => set('acceptance_criteria', [...story.acceptance_criteria, ''])}><Plus size={16} /> Add criterion</button>
      </fieldset>
      <label>Technical breakdown <span className="optional">Optional</span><textarea rows="2" value={story.technical_breakdown} onChange={(event) => set('technical_breakdown', event.target.value)} placeholder="Known services, components, migrations, or constraints" /></label>
      <button className="button primary" disabled={disabled}>Build justified estimate</button>
    </form>
  )
}
```

### 7.9 `frontend/src/components/JiraBrowser.jsx`

```jsx
import { Download, Search } from 'lucide-react'
import { useState } from 'react'

export default function JiraBrowser({ instances, issues, onFetch, onEstimate, loading }) {
  const [instance, setInstance] = useState('')
  const [project, setProject] = useState('')
  const [status, setStatus] = useState('')
  const [sprint, setSprint] = useState('')
  const [selected, setSelected] = useState(new Set())
  const activeInstance = instance || instances[0]?.name || ''
  const toggle = (index) => setSelected((current) => {
    const next = new Set(current)
    next.has(index) ? next.delete(index) : next.add(index)
    return next
  })
  const selectedStories = issues.filter((_, index) => selected.has(index))
  return (
    <section className="input-card">
      <div className="section-heading"><div><span className="eyebrow">Connected work</span><h2>Browse a Jira project</h2></div></div>
      <div className="form-grid jira-controls">
        <label>Instance<select value={activeInstance} onChange={(event) => setInstance(event.target.value)}>{instances.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.auth_type})</option>)}</select></label>
        <label>Project code<input value={project} onChange={(event) => setProject(event.target.value.toUpperCase())} placeholder="PAY" /></label>
        <label>Status <span className="optional">Optional</span><input value={status} onChange={(event) => setStatus(event.target.value)} placeholder="Ready for refinement" /></label>
        <label>Sprint <span className="optional">Optional</span><input value={sprint} onChange={(event) => setSprint(event.target.value)} placeholder="Sprint 24" /></label>
      </div>
      <button className="button secondary" disabled={!activeInstance || !project || loading} onClick={() => onFetch(activeInstance, project, { status, sprint })}><Search size={17} /> Fetch issues</button>
      {issues.length > 0 && <>
        <div className="table-wrap"><table className="select-table"><thead><tr><th><span className="sr-only">Select</span></th><th>Key</th><th>Summary</th><th>Status</th><th>Existing</th></tr></thead>
          <tbody>{issues.map((issue, index) => <tr key={issue.key || index}><td><input type="checkbox" aria-label={`Select ${issue.title}`} checked={selected.has(index)} onChange={() => toggle(index)} /></td><td className="mono">{issue.key}</td><td>{issue.title}</td><td>{issue.status || 'Unknown'}</td><td>{issue.existing_points ?? '—'}</td></tr>)}</tbody></table></div>
        <button className="button primary" disabled={!selected.size || loading} onClick={() => onEstimate(selectedStories)}><Download size={17} /> Estimate selected ({selected.size})</button>
      </>}
    </section>
  )
}
```

### 7.10 `frontend/src/components/ExcelUpload.jsx`

```jsx
import { Download, FileSpreadsheet, UploadCloud } from 'lucide-react'
import { useRef, useState } from 'react'

export default function ExcelUpload({ onUpload, templateUrl, loading }) {
  const input = useRef(null)
  const [dragging, setDragging] = useState(false)
  const pick = (files) => files?.[0] && onUpload(files[0])
  return (
    <section className="input-card">
      <div className="section-heading"><div><span className="eyebrow">Many stories</span><h2>Import a spreadsheet</h2></div><a className="text-button" href={templateUrl}><Download size={16} /> Template</a></div>
      <div className={`drop-zone ${dragging ? 'dragging' : ''}`} role="button" tabIndex="0" onKeyDown={(event) => (event.key === 'Enter' || event.key === ' ') && input.current?.click()} onClick={() => input.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); pick(event.dataTransfer.files) }}>
        <UploadCloud size={32} aria-hidden="true" /><strong>Drop Excel or CSV here</strong><span>or choose a file up to 15 MB</span>
        <input ref={input} hidden type="file" accept=".csv,.xlsx,.xls" disabled={loading} onChange={(event) => pick(event.target.files)} />
      </div>
      <p className="help"><FileSpreadsheet size={15} /> Headers can be anything. You will map them on the next screen.</p>
    </section>
  )
}
```

### 7.11 `frontend/src/components/ColumnMapper.jsx`

```jsx
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

const fields = [
  ['title', 'Title', true], ['user_story', 'User story', false], ['acceptance_criteria', 'Acceptance criteria', false],
  ['technical_breakdown', 'Technical breakdown', false], ['existing_points', 'Existing points', false],
]

export default function ColumnMapper({ upload, onEstimate, loading }) {
  const [mapping, setMapping] = useState(upload.suggested_mapping)
  const selectableRows = upload.rows.slice(0, 100)
  const [selected, setSelected] = useState(() => new Set(selectableRows.map((_, index) => index)))
  useEffect(() => { setMapping(upload.suggested_mapping); setSelected(new Set(upload.rows.slice(0, 100).map((_, index) => index))) }, [upload])
  const previewColumns = useMemo(() => Object.values(mapping).filter(Boolean), [mapping])
  const toggle = (index) => setSelected((current) => { const next = new Set(current); next.has(index) ? next.delete(index) : next.add(index); return next })
  const selectedRows = selectableRows.filter((_, index) => selected.has(index))
  return (
    <section className="input-card mapping-card">
      <div className="section-heading"><div><span className="eyebrow">{upload.row_count} rows detected</span><h2>Match your columns</h2></div><CheckCircle2 className="success-icon" /></div>
      <div className="mapping-grid">
        {fields.map(([key, label, required]) => <div className="mapping-row" key={key}><span>{label}{required && <b> Required</b>}</span><ArrowRight size={16} /><select value={mapping[key] || ''} onChange={(event) => setMapping((current) => ({ ...current, [key]: event.target.value || null }))}><option value="">Not mapped</option>{upload.columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></div>)}
      </div>
      <div className="preview-toolbar"><span>Select stories to estimate (maximum 100)</span><button className="text-button" onClick={() => setSelected(selected.size ? new Set() : new Set(selectableRows.map((_, index) => index)))}>{selected.size ? 'Clear selection' : 'Select all'}</button></div>
      <div className="table-wrap mapping-preview"><table className="preview-table"><thead><tr><th><span className="sr-only">Select</span></th>{previewColumns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{selectableRows.map((row, index) => <tr key={index}><td><input type="checkbox" aria-label={`Select row ${index + 2}`} checked={selected.has(index)} onChange={() => toggle(index)} /></td>{previewColumns.map((column) => <td key={column}>{String(row[column] ?? '').slice(0, 100)}</td>)}</tr>)}</tbody></table></div>
      {upload.row_count > 100 && <p className="help">Showing the first 100 rows. Split larger files into batches of 100 for reliable progress.</p>}
      <button className="button primary" disabled={!mapping.title || !selected.size || loading} onClick={() => onEstimate(selectedRows, mapping)}>Estimate selected ({selected.size})</button>
    </section>
  )
}
```

### 7.12 `frontend/src/components/PipelineView.jsx`

```jsx
import { Check, Circle, LoaderCircle } from 'lucide-react'

const labels = {
  score_parameters: 'Score parameters', identify_drivers: 'Identify drivers', compare_to_anchors: 'Compare anchors',
  derive_points: 'Derive points', spike_split_branch: 'Spike / split check', write_plain_language_reasoning: 'Write plain-language why',
  detect_hidden_tasks: 'Find hidden work', assess_risks: 'Assess risks', recommend_split: 'Recommend split',
}

export default function PipelineView({ steps, active = true, title }) {
  if (!active && !steps.length) return null
  return (
    <section className="pipeline-card" aria-live="polite">
      <div><span className="eyebrow">Live reasoning</span><h2>{title || 'Building the estimate'}</h2></div>
      <div className="pipeline-steps">
        {Object.entries(labels).map(([key, label]) => {
          const done = steps.includes(key)
          const current = !done && Object.keys(labels)[steps.length] === key
          return <div className={`pipeline-step ${done ? 'done' : current ? 'current' : ''}`} key={key}>{done ? <Check size={15} /> : current ? <LoaderCircle size={15} className="spin" /> : <Circle size={12} />}<span>{label}</span></div>
        })}
      </div>
    </section>
  )
}
```

### 7.13 `frontend/src/components/ResultCard.jsx`

```jsx
import { AlertTriangle, Anchor, Braces, ChevronDown, Download, GitFork, ShieldAlert, Target } from 'lucide-react'
import Scorecard from './Scorecard'
import EffortBar from './EffortBar'

const fibonacci = [1, 2, 3, 5, 8, 13]

function Detail({ title, icon: Icon, children, open = false }) {
  return <details className="result-detail" open={open}><summary><span><Icon size={18} />{title}</span><ChevronDown size={18} /></summary><div className="detail-body">{children}</div></details>
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url)
}

function markdown(result) {
  return `# ${result.story.title}\n\n## ${result.points} points\n\n**${result.tldr}**\n\n${result.plain_language_why}\n\n## Anchor comparison\n${result.anchor_comparison}\n\n## Risks\n${result.risks.map((item) => `- ${item.risk}: ${item.mitigation_or_assumption}`).join('\n')}\n`
}

export default function ResultCard({ result, writeEnabled, onWrite }) {
  if (!result?.plain_language_why || !result?.tldr) return <div className="error-card">An estimate was withheld because its required explanation is missing.</div>
  const story = result.story || {}
  const split = result.split_recommendation || {}
  return (
    <article className="result-card">
      {(split.split_recommended || result.spike_recommended) && <div className="recommend-banner"><AlertTriangle size={18} /><strong>{split.split_recommended ? 'SPLIT' : 'SPIKE'} recommended</strong><span>{split.split_recommended ? split.rationale : result.spike_reason}</span></div>}
      <header className="result-headline">
        <div className="points-block"><span>Story points</span><strong>{result.points}</strong>{story.existing_points != null && <small>was {story.existing_points} <b>{result.points - story.existing_points > 0 ? '+' : ''}{result.points - story.existing_points}</b></small>}</div>
        <div className="headline-copy"><span className="eyebrow">{story.key ? `${story.key} · ` : ''}{story.title}</span><h2>{result.tldr}</h2><p>{result.plain_language_why}</p></div>
      </header>
      <div className="fib-scale" aria-label={`Fibonacci scale, ${result.points} selected`}>{fibonacci.map((point) => <span className={point === result.points ? 'selected' : point < result.points ? 'passed' : ''} key={point}>{point}</span>)}</div>
      <div className="result-actions"><button className="text-button" onClick={() => download(`${story.key || 'estimate'}.md`, markdown(result), 'text/markdown')}><Download size={15} /> Markdown</button><button className="text-button" onClick={() => download(`${story.key || 'estimate'}.json`, JSON.stringify(result, null, 2), 'application/json')}><Braces size={15} /> JSON</button>{writeEnabled && story.source === 'jira' && <button className="button secondary small" onClick={() => onWrite(result)}>Write {result.points} to Jira</button>}</div>
      <div className="details-stack">
        <Detail title="Scorecard and drivers" icon={Target}><p className="callout"><strong>What drives this:</strong> {result.drivers_explanation}</p><Scorecard scores={result.scorecard} drivers={result.drivers} /></Detail>
        <Detail title="Calibration anchor comparison" icon={Anchor}><p>{result.anchor_comparison}</p><p className="muted">Point derivation: {result.points_derivation}</p></Detail>
        <Detail title="Layer effort and range" icon={Target}><EffortBar effort={result.effort} /></Detail>
        <Detail title={`Hidden sub-tasks (${result.hidden_tasks?.length || 0})`} icon={ShieldAlert}>{result.hidden_tasks?.length ? <ul className="reason-list">{result.hidden_tasks.map((item, index) => <li key={index}><strong>{item.task}</strong><span>{item.weight}</span></li>)}</ul> : <p>No hidden work was evidenced in the criteria.</p>}</Detail>
        <Detail title="Risks and assumptions" icon={AlertTriangle}><ul className="reason-list">{result.risks?.map((item, index) => <li key={index}><strong>{item.risk}</strong><span>{item.mitigation_or_assumption}</span></li>)}</ul><h4>Assumptions</h4><ul>{result.assumptions?.map((item, index) => <li key={index}>{item}</li>)}</ul></Detail>
        <Detail title="Split recommendation" icon={GitFork}><p>{split.rationale}</p>{split.proposed_stories?.length > 0 && <ol>{split.proposed_stories.map((item, index) => <li key={index}>{item}</li>)}</ol>}</Detail>
      </div>
    </article>
  )
}
```

### 7.14 `frontend/src/components/ResultCard.test.jsx`

```jsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ResultCard from './ResultCard'

const complete = {
  points: 5,
  tldr: '5 - bounded cross-stack work using known patterns.',
  plain_language_why: 'This is a 5 because it changes the form and its existing service. It is similar to our preference anchor.',
  story: { title: 'Preference', source: 'manual' },
  scorecard: [], drivers: [], drivers_explanation: '', anchor_comparison: 'Similar to the preference anchor.',
  points_derivation: 'Bounded, known cross-stack work.', effort: null, hidden_tasks: [], risks: [], assumptions: [],
  split_recommendation: { split_recommended: false, rationale: 'Keep together.', proposed_stories: [] },
}

describe('ResultCard', () => {
  it('withholds a number when its explanation is absent', () => {
    render(<ResultCard result={{ ...complete, plain_language_why: '' }} />)
    expect(screen.queryByText('5')).not.toBeInTheDocument()
    expect(screen.getByText(/withheld/)).toBeInTheDocument()
  })

  it('renders points with the headline reason', () => {
    render(<ResultCard result={complete} />)
    expect(screen.getByText('5', { selector: '.points-block > strong' })).toBeInTheDocument()
    expect(screen.getByText(complete.tldr)).toBeInTheDocument()
  })
})
```

### 7.15 `frontend/src/components/Scorecard.jsx`

```jsx
const display = (value) => value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())

export default function Scorecard({ scores = [], drivers = [] }) {
  return <div className="table-wrap"><table className="scorecard"><thead><tr><th>Parameter</th><th>Score</th><th>Why</th></tr></thead><tbody>{scores.map((item) => <tr key={item.parameter}><td>{display(item.parameter)}{drivers.includes(item.parameter) && <span className="driver-badge">Driver</span>}</td><td><span className={`score-chip ${item.score.toLowerCase()}`}>{item.score}</span></td><td>{item.reason}</td></tr>)}</tbody></table></div>
}
```

### 7.16 `frontend/src/components/EffortBar.jsx`

```jsx
export default function EffortBar({ effort }) {
  if (!effort) return null
  const days = effort.person_days
  const max = Math.max(days.pessimistic, 1)
  return <div className="effort"><div className="layer-grid"><div><span>React</span><p>{effort.react}</p></div><div><span>Spring</span><p>{effort.spring}</p></div><div><span>Existing code</span><p>{effort.existing_code}</p></div></div><div className="effort-scale"><div className="effort-track"><span style={{ width: `${(days.optimistic / max) * 100}%` }} /><i style={{ left: `${(days.likely / max) * 100}%` }} /></div><div className="effort-labels"><span>{days.optimistic}d optimistic</span><strong>{days.likely}d likely</strong><span>{days.pessimistic}d pessimistic</span></div></div></div>
}
```

### 7.17 `frontend/src/components/BatchTable.jsx`

```jsx
import { ArrowDownUp, Download } from 'lucide-react'
import { useMemo, useState } from 'react'

export default function BatchTable({ results, onSelect }) {
  const [sort, setSort] = useState('title')
  const sorted = useMemo(() => [...results].sort((a, b) => sort === 'points' ? a.points - b.points : (a.story?.title || '').localeCompare(b.story?.title || '')), [results, sort])
  const exportCsv = () => {
    const rows = [['Item', 'Points', 'Why', 'Split'], ...sorted.map((result) => [result.story.title, result.points, result.tldr, result.split_recommendation?.split_recommended ? 'Yes' : 'No'])]
    const csv = rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const link = document.createElement('a'); link.href = url; link.download = 'story-estimates.csv'; link.click(); URL.revokeObjectURL(url)
  }
  return <section className="batch-card"><div className="section-heading"><div><span className="eyebrow">Batch complete</span><h2>{results.length} justified estimates</h2></div><div className="result-actions"><button className="text-button" onClick={() => setSort(sort === 'points' ? 'title' : 'points')}><ArrowDownUp size={15} /> Sort by {sort === 'points' ? 'title' : 'points'}</button><button className="text-button" onClick={exportCsv}><Download size={15} /> Export all</button></div></div><div className="table-wrap"><table className="batch-table"><thead><tr><th>Item</th><th>Estimate and reason</th><th>Action</th></tr></thead><tbody>{sorted.map((result, index) => <tr key={result.story.key || index}><td><strong>{result.story.key || result.story.title}</strong><span>{result.story.key && result.story.title}</span></td><td><div className="batch-estimate"><b>{result.points}</b><span>{result.tldr}</span>{result.split_recommendation?.split_recommended && <i>SPLIT</i>}</div></td><td><button className="text-button" onClick={() => onSelect(result)}>Open reasoning</button></td></tr>)}</tbody></table></div></section>
}
```

### 7.18 `frontend/src/components/SourceSwitcher.jsx`

```jsx
import { FileSpreadsheet, Keyboard, PanelsTopLeft } from 'lucide-react'

const options = [
  { id: 'jira', label: 'From Jira', Icon: PanelsTopLeft },
  { id: 'manual', label: 'Manual entry', Icon: Keyboard },
  { id: 'upload', label: 'Upload Excel / CSV', Icon: FileSpreadsheet },
]

export default function SourceSwitcher({ value, onChange }) {
  return (
    <div className="source-switcher" role="tablist" aria-label="Story source">
      {options.map(({ id, label, Icon }) => (
        <button key={id} role="tab" aria-selected={value === id} className={value === id ? 'active' : ''} onClick={() => onChange(id)}>
          <Icon size={18} aria-hidden="true" />{label}
        </button>
      ))}
    </div>
  )
}
```

### 7.19 `frontend/src/components/StatusBadge.jsx`

```jsx
export default function StatusBadge({ status = 'unknown', children }) {
  const tone = ['ok', 'configured', 'completed'].includes(status) ? 'good' : status === 'running' ? 'busy' : 'bad'
  return <span className={`status-badge ${tone}`}><span aria-hidden="true" />{children || status}</span>
}
```

### 7.20 `frontend/src/components/ErrorCard.jsx`

```jsx
import { AlertCircle, RotateCcw } from 'lucide-react'

export default function ErrorCard({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="error-card" role="alert">
      <AlertCircle size={20} aria-hidden="true" />
      <div><strong>Something needs attention</strong><p>{error.message || String(error)}</p></div>
      {onRetry && <button className="button secondary small" onClick={onRetry}><RotateCcw size={15} /> Retry</button>}
    </div>
  )
}
```

### 7.21 `frontend/src/styles.css`

```css
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');

:root { font-family: 'DM Sans', sans-serif; color: #17221e; background: #f3f5ef; font-synthesis: none; --ink:#17221e; --muted:#68736e; --line:#dfe4dc; --paper:#fff; --green:#186149; --lime:#d8efb4; --amber:#e5a938; --red:#bd4b3d; }
* { box-sizing: border-box; }
body { margin:0; min-width:320px; min-height:100vh; }
button,input,textarea,select { font:inherit; }
button,a { -webkit-tap-highlight-color:transparent; }
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,[tabindex]:focus-visible { outline:3px solid #8ac5ad; outline-offset:2px; }
.app-shell { min-height:100vh; }
.topbar { height:76px; padding:0 max(28px,calc((100vw - 1240px)/2)); background:#123d31; color:#fff; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #315c50; }
.brand { color:inherit; text-decoration:none; display:flex; align-items:center; gap:11px; }
.brand>span { width:41px;height:41px;display:grid;place-items:center;background:#d8efb4;color:#174b3a;border-radius:12px; }
.brand div { display:flex; flex-direction:column; }
.brand strong { font:700 17px 'Manrope'; letter-spacing:-.02em; }
.brand small { color:#b7cdc4; font-size:11px; }
.system-status { display:flex; gap:10px; align-items:center; }
.model-badge,.status-badge { border:1px solid #487166; border-radius:999px; display:inline-flex; align-items:center; gap:7px; padding:7px 10px; color:#dbe8e3; font-size:12px; }
.status-badge>span { width:7px;height:7px;border-radius:50%;background:#d6a740; }.status-badge.good>span{background:#9bd27a}.status-badge.bad>span{background:#ef796b}.status-badge.busy>span{background:#e5a938}
main { max-width:1240px; margin:auto; padding:64px 28px 90px; }
.hero { display:grid; grid-template-columns:1fr 320px; gap:60px; align-items:end; margin-bottom:46px; }
.eyebrow { display:block; color:#4f655d; font-size:11px; font-weight:800; letter-spacing:.13em; text-transform:uppercase; margin-bottom:9px; }
h1,h2,h3 { font-family:'Manrope'; margin:0; letter-spacing:-.035em; }
h1 { font-size:clamp(37px,5vw,61px); line-height:1.06; max-width:790px; } h1 em{color:#27795e;font-style:normal}
.hero>div>p { color:var(--muted); font-size:17px; line-height:1.65; max-width:680px; margin:20px 0 0; }
.method-card { padding:22px; background:#e7eddf; border:1px solid #d6ddce; display:flex; align-items:flex-start; gap:13px; border-radius:15px; }
.method-card svg { color:#27795e; flex:none; }.method-card strong{font-family:'Manrope'}.method-card ol{margin:12px 0 0;padding-left:20px;color:#53615b;font-size:13px;line-height:1.8}
.source-switcher { background:#e2e7de; border-radius:13px; padding:5px; display:grid; grid-template-columns:repeat(3,1fr); margin-bottom:24px; }
.source-switcher button { border:0;background:transparent;padding:13px 17px;border-radius:9px;color:#65706a;font-weight:650;display:flex;align-items:center;justify-content:center;gap:8px;cursor:pointer; }
.source-switcher button.active { background:#fff;color:#174d3d;box-shadow:0 2px 10px #2d3e3510; }
.workspace { display:grid; grid-template-columns:minmax(0,1fr) 330px; gap:24px; align-items:start; }
.input-card,.pipeline-card,.result-card,.batch-card { background:var(--paper);border:1px solid var(--line);border-radius:17px;box-shadow:0 9px 30px rgba(30,50,40,.05); }
.input-card { padding:29px; }.pipeline-card{padding:25px;position:sticky;top:20px}.batch-card{padding:29px;margin-top:24px}.result-card{margin-top:24px;overflow:hidden}
.section-heading { display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px }.section-heading h2,.pipeline-card h2{font-size:22px}.section-heading .eyebrow{margin-bottom:5px}
label,legend { display:block;font-size:13px;font-weight:700;color:#3d4b45;margin-bottom:18px } fieldset{border:0;padding:0;margin:0}legend{margin-bottom:10px}
input,textarea,select { width:100%;margin-top:7px;border:1px solid #ced6ce;border-radius:9px;padding:11px 12px;background:#fbfcfa;color:var(--ink);transition:.2s border-color; }
textarea { resize:vertical;line-height:1.5 } input:hover,textarea:hover,select:hover{border-color:#9eada4}.optional{font-weight:400;color:#89938e;margin-left:3px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 15px}.criteria-list{display:flex;flex-direction:column;gap:8px;margin-bottom:8px}.criterion{display:grid;grid-template-columns:25px 1fr 34px;align-items:center;gap:7px}.criterion>span{width:25px;height:25px;border-radius:50%;background:#e4eee6;color:#27634f;display:grid;place-items:center;font-size:12px;font-weight:800}.criterion input{margin:0}.icon-button{border:0;background:transparent;color:#748078;display:grid;place-items:center;cursor:pointer}.icon-button:disabled{opacity:.3}
.button,.text-button { border:0;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:7px;font-weight:700 }.button{padding:11px 16px;border-radius:9px}.button.primary{background:#17624a;color:#fff}.button.primary:hover{background:#104b39}.button.secondary{background:#edf2ec;color:#205542;border:1px solid #dce5de}.button.small{padding:8px 11px;font-size:12px}.button:disabled{opacity:.48;cursor:not-allowed}.text-button{padding:6px;background:transparent;color:#287057;text-decoration:none;font-size:13px}.success-icon{color:#398563}
.drop-zone{border:1.5px dashed #9db1a4;border-radius:13px;min-height:230px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;color:#65736d;cursor:pointer;background:#fafbf9}.drop-zone svg{color:#3a8067}.drop-zone strong{color:#31423b}.drop-zone.dragging{background:#edf6ee;border-color:#398563}.help{display:flex;align-items:center;gap:6px;color:#7b8681;font-size:12px}
.mapping-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px 18px;margin-bottom:22px}.mapping-row{display:grid;grid-template-columns:1fr 16px 1fr;align-items:center;gap:7px;font-size:13px}.mapping-row>span{font-weight:650}.mapping-row b{font-size:9px;text-transform:uppercase;color:#a24b3e}.mapping-row select{margin:0}
.preview-toolbar{display:flex;align-items:center;justify-content:space-between;color:#66736c;font-size:12px}.mapping-preview{max-height:360px;border:1px solid #e4e9e3;border-radius:9px;margin-bottom:14px}.mapping-preview thead{position:sticky;top:0;z-index:1}.mapping-preview input{width:auto;margin:0}
.table-wrap{max-width:100%;overflow:auto}.select-table,.preview-table,.scorecard,.batch-table{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0 20px}.select-table th,.select-table td,.preview-table th,.preview-table td,.scorecard th,.scorecard td,.batch-table th,.batch-table td{border-bottom:1px solid #e8ece7;text-align:left;padding:11px 10px;vertical-align:top}.select-table th,.preview-table th,.scorecard th,.batch-table th{color:#758079;font-size:10px;text-transform:uppercase;letter-spacing:.08em;background:#fafbf9}.select-table input{width:auto;margin:0}.mono{font-family:monospace;color:#2a6752}
.pipeline-steps{display:flex;flex-direction:column;margin-top:20px}.pipeline-step{display:flex;align-items:center;gap:10px;color:#a1aaa5;font-size:13px;position:relative;padding:8px 0}.pipeline-step:before{content:"";position:absolute;left:7px;top:-8px;height:16px;border-left:1px solid #dce2dd}.pipeline-step:first-child:before{display:none}.pipeline-step.done{color:#286c53}.pipeline-step.done svg{background:#d9eed9;border-radius:50%;padding:2px}.pipeline-step.current{color:#263c33;font-weight:700}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.error-card{border:1px solid #e4b3ac;background:#fff5f3;color:#77372f;border-radius:12px;padding:14px 16px;display:flex;align-items:flex-start;gap:10px;margin-bottom:18px}.error-card p{margin:4px 0 0;color:#97584f}.error-card .button{margin-left:auto}
.recommend-banner{display:grid;grid-template-columns:20px auto 1fr;gap:8px 10px;align-items:center;padding:12px 24px;background:#fff2cf;color:#704e0f;border-bottom:1px solid #f1dda4;font-size:13px}.recommend-banner span{color:#866828}
.result-headline{display:grid;grid-template-columns:190px 1fr;gap:35px;padding:35px 40px 28px;background:#153f34;color:#fff}.points-block{border-right:1px solid #3c6258;display:flex;flex-direction:column;justify-content:center}.points-block>span{text-transform:uppercase;letter-spacing:.11em;color:#b8ccc4;font-size:10px;font-weight:800}.points-block>strong{font:800 76px/.95 'Manrope';color:#d9efb8}.points-block small{margin-top:11px;color:#b8ccc4}.points-block small b{margin-left:5px;color:#efc36d}.headline-copy{display:flex;flex-direction:column;justify-content:center}.headline-copy .eyebrow{color:#a9c3ba}.headline-copy h2{font-size:23px;line-height:1.35}.headline-copy p{color:#d6e3de;line-height:1.65;margin:13px 0 0;max-width:780px}
.fib-scale{display:flex;align-items:center;justify-content:center;gap:0;padding:18px 40px;background:#f7f9f5;border-bottom:1px solid var(--line)}.fib-scale span{width:46px;height:30px;border-top:3px solid #d5ddd5;text-align:center;padding-top:7px;color:#9aa39e;font-size:11px;font-weight:800}.fib-scale span.passed{border-color:#8bb9a5;color:#568572}.fib-scale span.selected{border-color:#1c6c50;color:#fff;background:#1c6c50;border-radius:0 0 7px 7px}
.result-actions{display:flex;gap:8px;justify-content:flex-end;align-items:center;padding:10px 24px}.details-stack{border-top:1px solid var(--line)}.result-detail{border-bottom:1px solid var(--line)}.result-detail summary{list-style:none;display:flex;align-items:center;justify-content:space-between;padding:17px 29px;cursor:pointer;font-weight:700}.result-detail summary::-webkit-details-marker{display:none}.result-detail summary span{display:flex;align-items:center;gap:9px}.result-detail summary span svg{color:#32785f}.result-detail summary>svg{transition:transform .2s}.result-detail[open] summary>svg{transform:rotate(180deg)}.detail-body{padding:0 29px 25px;color:#48574f;line-height:1.6}.detail-body p{margin-top:0}.callout{padding:13px;background:#eef4eb;border-left:3px solid #5d957d;border-radius:5px}.muted{color:#748078}
.score-chip{font-size:10px;font-weight:800;text-transform:uppercase;padding:4px 7px;border-radius:999px}.score-chip.low{color:#26674e;background:#dff0df}.score-chip.medium{color:#785514;background:#f9eabf}.score-chip.high{color:#933f34;background:#f8dcd7}.driver-badge{font-size:8px;text-transform:uppercase;letter-spacing:.06em;color:#286b52;background:#e0eee4;padding:3px 5px;border-radius:4px;margin-left:7px}.reason-list{list-style:none;padding:0}.reason-list li{display:flex;flex-direction:column;padding:9px 0;border-bottom:1px solid #edf0ec}.reason-list span{color:#6c7872;font-size:13px}
.layer-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.layer-grid div{background:#f5f7f3;padding:13px;border-radius:8px}.layer-grid span{font-size:10px;text-transform:uppercase;font-weight:800;color:#507264}.layer-grid p{margin:5px 0 0;font-size:13px}.effort-scale{margin-top:24px}.effort-track{height:9px;background:#e5e9e3;border-radius:8px;position:relative}.effort-track span{display:block;height:100%;background:linear-gradient(90deg,#7db997,#e4bb58);border-radius:8px}.effort-track i{position:absolute;top:-5px;width:3px;height:19px;background:#263d33}.effort-labels{display:flex;justify-content:space-between;font-size:11px;color:#78827d;margin-top:8px}
.batch-table td:first-child{display:flex;flex-direction:column;min-width:180px}.batch-table td:first-child span{font-size:12px;color:#758079}.batch-estimate{display:grid;grid-template-columns:36px 1fr auto;gap:10px;align-items:center;min-width:410px}.batch-estimate b{font:800 23px 'Manrope';color:#1c664d}.batch-estimate i{font-style:normal;font-size:9px;color:#795814;background:#f8e9bb;border-radius:4px;padding:3px 5px}
.empty-hint{display:flex;align-items:center;justify-content:center;gap:10px;color:#7b8781;font-size:12px;margin-top:34px}.empty-hint span{width:24px;height:24px;display:grid;place-items:center;background:#dfe7de;color:#346b55;border-radius:50%;font-weight:800}.empty-hint svg{width:14px}
footer{border-top:1px solid #d9ded7;max-width:1240px;margin:auto;padding:22px 28px 35px;color:#7c8681;font-size:11px;display:flex;justify-content:space-between}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:900px){.system-status .status-badge{display:none}.hero{grid-template-columns:1fr}.method-card{display:none}.workspace{grid-template-columns:1fr}.pipeline-card{position:static}.result-headline{grid-template-columns:145px 1fr}.mapping-grid{grid-template-columns:1fr}}
@media(max-width:620px){main{padding:42px 15px 70px}.topbar{padding:0 15px}.model-badge{max-width:180px;overflow:hidden;white-space:nowrap}.source-switcher button{font-size:0}.source-switcher button svg{width:21px;height:21px}.input-card,.batch-card{padding:20px}.form-grid,.layer-grid{grid-template-columns:1fr}.result-headline{grid-template-columns:1fr;padding:27px}.points-block{border-right:0;border-bottom:1px solid #3c6258;padding-bottom:20px}.points-block>strong{font-size:61px}.headline-copy h2{font-size:19px}.recommend-banner{grid-template-columns:20px 1fr}.recommend-banner span{grid-column:1/-1}.empty-hint{display:none}.result-actions{flex-wrap:wrap}footer{flex-direction:column;gap:5px}.jira-controls{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
```

---

## 8. Behavioral invariants checklist (verify after regeneration)

1. **Explanation-before-number**: `/estimate` never emits `result` without
   `plain_language_why` and `tldr`; `ResultCard` renders a refusal card without them.
2. **All 12 parameters scored** or the node raises listing omissions.
3. **13 ⇒ escalation branch ⇒ spike recommended ⇒ split forced**; High uncertainty
   alone also triggers the spike branch.
4. **Refinement**: same `session_id` + `refinement` continues the checkpointed thread.
5. **Jira write-back is triple-gated**: env flag, `confirm=true` in the request body,
   and a browser confirm dialog; the write button only appears for Jira-sourced
   results when writes are enabled.
6. **Startup never crashes on bad config**: `/health` and `/config` stay available;
   estimate endpoints 503 with the error list.
7. **Provider strings never leave the factory** (and Groq's json_mode special case
   never leaves `get_structured_llm`).
8. **Uploads**: 15 MB cap, Title mapping required, blank-title rows reported not
   fatal, at most 100 stories per batch request, template downloads as
   `story-pointer-template.xlsx`.
9. **Error envelope** everywhere: `{"error": {code, message, details, retryable}}`.
10. **SSE node events carry no content** — only node name + status; state internals
    (`anchors`, `messages`, `escalation_required`, `refinement`) never reach the client.

## 9. Setup, run, verify

```powershell
# from the repository root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env    # then fill LLM_API_KEY etc.
npm install
Copy-Item frontend\.env.example frontend\.env

# terminal 1 — API
.\.venv\Scripts\Activate.ps1
uvicorn backend.api.main:app --reload --port 8000

# terminal 2 — UI
npm run dev        # http://localhost:5173

# checks
pytest backend/tests -q     # 8 tests
npm test                    # 2 vitest tests (ResultCard)
npm run build               # outputs to ./dist
```

Smoke test without a UI: `GET http://localhost:8000/health` should return
`status: ok` (or `degraded` with actionable `llm.errors`), and
`POST /estimate` with `{"story": {"title": "Test", "user_story": "As a user..."}}`
should stream `started` → nine `node` events → one `result`.

## 10. Optional repository assets (not required for functionality)

- **`banking_jira_stories.csv`** — sample batch-upload data: 60 banking user stories
  (471 physical lines due to multiline quoted cells) with columns
  `Title, User Story, Acceptance Criteria, Technical Breakdown, Existing Points`;
  titles follow the pattern `DB-001: Biometric Login`, ACs in Given/When/Then form.
  Useful for demoing the upload flow; regenerate with any similar sample set.
- **`banking_jira_stories_role_model.md`** — an 878-line reference document
  describing the role model behind those sample stories.
- **`img.png`** — application screenshot used for documentation.

## 11. Known quirks preserved for fidelity

- `backend/ingest/excel.py` imports `BinaryIO` unused; `nodes.py` accepts an unused
  `attempt` semantics in `_retry_delay` (always called with 0). Harmless.
- `.claude/launch.json` references npm scripts from an earlier monorepo layout
  (see §5.6 note); the real dev command is `npm run dev`.
- `stream_batch` re-parses its own SSE byte frames by string prefix rather than
  passing structured objects — intentional simplicity, keep as-is.
- `existing_points` arrives as float; the headline delta `result.points -
  story.existing_points` can therefore render a fractional delta.
- Frontend fonts load from Google Fonts at runtime (network required for the exact
  typography; the UI degrades to system sans-serif offline).

*Generated 2026-07-15 from commit `e19fb28` ("storyetimator").*
