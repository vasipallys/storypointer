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
