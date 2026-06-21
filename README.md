# Story Pointer

Story Pointer is an evidence-led story-point estimator for React/Spring teams in regulated environments. It uses a checkpointed LangGraph pipeline to score delivery factors, identify drivers, compare fixed calibration stories, and only then conclude a modified-Fibonacci estimate. Every number is returned and rendered with a one-line summary and a plain-language explanation.

## Architecture

- **Frontend:** React 19, Vite, functional components, responsive accessible UI, incremental SSE consumption.
- **Backend:** FastAPI, Pydantic, LangChain chat-model abstraction, LangGraph `StateGraph` with `MemorySaver`.
- **Jira:** direct `httpx` integration. Jira Cloud uses REST v3 with Basic auth; Server/Data Center uses REST v2 with Bearer PAT auth. Reads use the documented search resource and writes use `PUT /issue/{issueKey}`.
- **Files:** pandas reads CSV/XLS/XLSX, `openpyxl` reads/writes XLSX, and `xlrd` supports legacy XLS.
- **Calibration:** six fixed stories in `backend/anchors.py`; no embeddings, vector store, or retrieval.

The API streams [Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html) (`text/event-stream`). Node events contain progress only. A final result is emitted atomically after both required explanations exist, so a point value is never shown alone.

## Install

Python 3.11+ and Node.js 20+ are recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env
npm install
Copy-Item frontend\.env.example frontend\.env
```

Edit `backend/.env`, then run both processes from the repository root:

```powershell
# terminal 1
.\.venv\Scripts\Activate.ps1
uvicorn backend.api.main:app --reload --port 8000

# terminal 2
npm run dev
```

Open `http://localhost:5173`. Useful checks:

```powershell
pytest backend/tests -q
npm test
npm run build
```

## Provider switches

Only `backend/.env` changes. Provider and model strings do not appear in application code outside `backend/llm/factory.py`.

**Claude**

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=your-anthropic-key
LLM_BASE_URL=
```

**Gemini**

```dotenv
LLM_PROVIDER=google_genai
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=your-google-key
LLM_BASE_URL=
```

**Kimi / Moonshot**

```dotenv
LLM_PROVIDER=moonshot
LLM_MODEL=moonshot-v1-8k
LLM_API_KEY=your-moonshot-key
LLM_BASE_URL=https://api.moonshot.ai/v1
```

Native integrations use LangChain `init_chat_model(model=..., model_provider=...)`. Moonshot, DeepSeek, OpenRouter, Ollama, vLLM, and generic compatible endpoints share `ChatOpenAI(base_url=...)`. Temperature, maximum output tokens, key, and base URL all come from the environment. Invalid LLM configuration is checked during application startup; diagnostics remain available through `/health` so the UI can show the fix instead of a stack trace.

## Jira configuration

One cloud instance:

```dotenv
JIRA_INSTANCES=prod
JIRA_PROD_BASE_URL=https://yourorg.atlassian.net
JIRA_PROD_AUTH_TYPE=cloud
JIRA_PROD_EMAIL=developer@example.com
JIRA_PROD_API_TOKEN=your-cloud-api-token
JIRA_PROD_STORY_POINTS_FIELD=customfield_10016
JIRA_PROD_AC_FIELD=
```

Add a Server/Data Center instance without changing code:

```dotenv
JIRA_INSTANCES=prod,sandbox
JIRA_SANDBOX_BASE_URL=https://jira-sandbox.example.com
JIRA_SANDBOX_AUTH_TYPE=server
JIRA_SANDBOX_API_TOKEN=your-personal-access-token
JIRA_SANDBOX_STORY_POINTS_FIELD=customfield_10024
JIRA_SANDBOX_AC_FIELD=customfield_10401
```

The registry parses named instances at startup and validates credentials only when each instance is used. Missing AC fields fall back to extracting an Acceptance Criteria section from the description. Missing Story Points fields leave the reference value empty and disable writes for that instance.

Jira is read-only unless `JIRA_WRITE_ENABLED=true`. Even then, the UI asks for per-issue confirmation and the endpoint rejects requests unless `confirm=true`; estimates are never written automatically.

## Spreadsheet flow

Download `/upload/template` or use the link in the upload screen. Any CSV, XLS, or XLSX header names are accepted. `/upload/parse` returns all rows, detected columns, a 20-row preview, and fuzzy suggestions. The UI requires the user to map Title and lets them override every suggestion before estimation. Blank-title rows are skipped and reported without failing the batch; AC cells split on newlines or semicolons.

## Estimation method

The backend runs these graph nodes in order:

1. Score complexity, volume, uncertainty, React scope, Spring scope, existing-code scope, dependencies, NFRs, testing, compliance/audit, familiarity, and DoD overhead as Low/Medium/High with evidence.
2. Identify the two or three deciding drivers.
3. Compare explicitly with the fixed anchors and their points.
4. Derive 1, 2, 3, 5, 8, or 13 from that evidence.
5. Write the product-owner explanation, TL;DR, layer effort, and person-day range.
6. Detect hidden work in acceptance criteria.
7. Assess three risks, assumptions, and spike need.
8. Recommend a split; a 13 always includes proposed sized sub-stories.

After derivation, a 13 or High uncertainty takes the conditional spike/split branch. `MemorySaver` uses the supplied session ID as `thread_id`, so a caller can submit a refinement such as “re-estimate assuming the rule engine is out of scope” with the same session ID.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | LLM configuration and per-Jira health |
| GET | `/config` | Non-secret active configuration |
| GET | `/jira/instances` | Named Jira instances and auth types |
| GET | `/jira/{instance}/project/{code}/issues` | Paginated JQL project fetch with status/sprint filters |
| POST | `/upload/parse` | Detect and preview spreadsheet columns |
| POST | `/upload/estimate` | Map rows and stream sequential estimates |
| GET | `/upload/template` | Download XLSX template |
| POST | `/estimate` | Stream one checkpointed estimate or refinement |
| POST | `/estimate/batch` | Stream sequential per-story progress and results |
| POST | `/jira/{instance}/{issueKey}/points` | Explicitly confirmed, gated write-back |

Errors use `{ "error": { "code", "message", "details", "retryable" } }`. Streaming failures use the same fields in an `error` or `item_error` event.

## Calibration

Edit only `backend/anchors.py`. Each anchor contains a title, full text, ACs, final points, and rationale. Keep a representative 3, 5, and 8, and prefer completed team work whose scope is well understood. Restart the API after editing; anchors are injected into every comparison without retrieval.

## How to add a new LLM provider

For an OpenAI-compatible service, set `LLM_PROVIDER=compatible`, its model, key, and `LLM_BASE_URL`; no code change is needed. For a new native LangChain provider, install its integration package and add its `model_provider` name to `NATIVE_PROVIDERS` in `backend/llm/factory.py`. Keep every provider conditional inside that factory.

## How to add another Jira instance

Append a lowercase name to `JIRA_INSTANCES`, then add the corresponding `JIRA_<NAME>_BASE_URL`, `AUTH_TYPE`, credentials, `STORY_POINTS_FIELD`, and optional `AC_FIELD`. Restart the API; the instance appears in the selector and health panel automatically.

## How to find your Jira Story Points field id

As a Jira administrator, request `GET /rest/api/3/field` on Cloud or `GET /rest/api/2/field` on Server/Data Center, authenticate as configured, and find the object whose name is “Story Points”. Use its `id` (for example `customfield_10016`), not its display name. Team-managed projects can use a different field ID, so verify it in the target instance/project.

## Excel template & column mapping

Use the **Template** link in Upload mode. Upload the completed workbook, review the suggested mapping, map Title plus any available story/AC/technical/points columns, inspect the preview, and estimate. The original existing-points value is reference-only and is shown beside the justified estimate.
