# Story Pointer

Story Pointer is an evidence-led story-point estimator for React/Spring teams in regulated environments. It uses a checkpointed LangGraph pipeline to score delivery factors, identify drivers, compare fixed calibration stories, and only then conclude a modified-Fibonacci estimate. Every number is returned and rendered with a one-line summary and a plain-language explanation.

Around that estimator sits a **project workspace**: create a project, link a code repo and a Jira project, model the system as an interactive **C4 diagram** (Material 3 UI, React Flow canvas), estimate the L3 components as stories with the architecture as evidence, and watch points roll up deterministically to epics (L2) and initiatives (L1).

## Architecture

- **Frontend:** React 19, Vite, Material 3 shell, React Flow C4 canvas, `react-markdown`/GFM requirement documents, Mermaid rendering, and incremental SSE consumption.
- **Backend:** FastAPI, Pydantic, LangChain chat-model abstraction, LangGraph `StateGraph` with a durable `AsyncSqliteSaver` checkpointer (falls back to `MemorySaver`).
- **Persistence:** stdlib SQLite in `data/storypointer.db` for projects, C4 elements/relations, artifact links, L1 teams, costed work plans, Mermaid diagrams, versioned requirements, comments, approvals, and immutable audit events; `data/checkpoints.db` for LangGraph sessions. Override with `STORYPOINTER_DB`.
- **Jira:** direct `httpx` integration. Jira Cloud uses REST v3 with Basic auth; Server/Data Center uses REST v2 with Bearer PAT auth. Reads use the documented search resource, writes use `PUT /issue/{issueKey}` and `POST /issue`.
- **Files:** pandas reads CSV/XLS/XLSX, `openpyxl` reads/writes XLSX, `xlrd` supports legacy XLS, and `python-docx`/`python-pptx` generate requirement exports with rendered Mermaid images.
- **Calibration:** six fixed stories in `backend/anchors.py`; no embeddings, vector store, or retrieval.

## C4 model ↔ Agile artifacts

| C4 level | Agile artifact | Estimation |
|---|---|---|
| L1 System context | Theme / initiative | Roll-up of child epics |
| L2 Container | Epic | Roll-up of child stories |
| L3 Component | Story / feature | Estimated directly by the pipeline |
| L4 Code | Task / sub-task / PR | Seeded from detected hidden tasks |

Cross-cutting artifacts tag elements instead of parenting them: bugs (L3+L4), tech debt (L2+L3), architecture flows (L2+L3). A 13-point estimate's split proposal seeds sibling L3 stories; hidden tasks seed L4 children — both arrive with a `proposed` status and stay out of the roll-up until accepted.

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

Open `http://localhost:5173`. Seed sample projects:

```powershell
python scripts\seed_demo.py      # small: 1 system, 3 containers, 4 stories
python scripts\seed_banking.py   # detailed retail-banking structure: 33 elements across L1-L4
```

Useful checks:

```powershell
pytest backend/tests -q
npm test
npm run build
```

## Run modes: web and desktop

Story Pointer supports two runtimes that share the same React/FastAPI codebase:

- **Web mode**: run FastAPI and Vite in separate terminals for browser access.
- **Desktop mode**: run the same UI inside Electron. Electron starts a local FastAPI process, stores SQLite data under the user's app-data folder, and points the UI to that local API at runtime.

Web development:

```powershell
# terminal 1
.\.venv\Scripts\Activate.ps1
uvicorn backend.api.main:app --reload --port 8000

# terminal 2
npm run dev
```

Electron development:

```powershell
npm run desktop:dev
```

Desktop packaging requires PyInstaller for the backend executable:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-desktop.txt

# Windows installer + portable EXE
npm run desktop:build:win

# macOS DMG + zip (run this on macOS)
npm run desktop:build:mac
```

Desktop builds are written to `release/`. On first desktop launch, Electron creates a user-editable `backend.env` from `desktop/backend.env.example`; it defaults to `LLM_PROVIDER=mock` so the app opens offline. Set `STORYPOINTER_EXTERNAL_API_URL` before launching Electron if you want the desktop shell to use an already-running API instead of starting its own local backend.

## Project workspace flow

1. **Projects home** lists project cards; the **＋ New project** FAB opens a wizard (basics → repo → Jira → seed). Every step after the name is skippable. **Quick estimate** keeps the original form/Jira/spreadsheet flow, also available inside each project.
2. **Seeding**: link a local checkout path and *Scan repo into C4* proposes L2 containers and L3 components from the code layout; *Import Jira issues* creates proposed L3 stories from the linked Jira project. Both are idempotent.
3. **C4 canvas and inspector**: click any node to inspect it. Selecting an **L1 node keeps the canvas open** and adds an operating-plan summary to the sidebar alongside its description and Jira actions; choose **More details** to open that exact initiative's full L1 plan. Double-click L1-L3 nodes to drill into their children, drag between nodes to draw a relation, and drag nodes to persist their positions.
4. **L1 plan — Requirements**: create multiple detailed Markdown documents for the selected initiative. Use Edit, Split, or Preview mode; insert or directly edit fenced Mermaid blocks; use the heading outline to navigate; and save each material change as a new immutable version with a change summary. Enter the contributor/reviewer name in **Working as** so edits and decisions are attributable.
5. **Requirements review and export**: add comments against the current document version, approve/resolve/reopen each comment, submit a document for review, approve it, or revoke approval. Any later content edit creates a new version and returns the document to Draft. The Audit panel retains version, comment, and review events. Export a saved version to Word or PowerPoint; Mermaid is rendered into the Office file while its source remains in the versioned Markdown (and is included as editable definition text in Word).
6. **L1 plan — Tribes & squads**: open it from an L1 sidebar's **More details** button or from the navigation rail, choose an initiative, then use the default **Hierarchy** view to define tribes with nested squads. Assign leads and missions, set FTE capacity and target velocity, and add people with roles, skills, location, allocation, and monthly loaded cost. Direct tribe members are optional and represent only tribe-level leadership or shared roles; delivery members belong inside squads. The header rolls up squad count, allocated FTE, people, and team run-rate.
7. **L1 plan — Work & cost**: create dated work packages, assign a squad, optionally link the work to an L2-L4 C4 element, and track allocation, approved budget, actual cost, delivery status, at-risk count, and remaining budget. Select the reporting currency in the plan header.
8. **L1 plan — Architecture**: create architecture or infrastructure views from Mermaid templates. Edit Mermaid source beside the live SVG preview, correct syntax errors before saving, keep multiple named diagrams, and export a rendered SVG.
9. **Inspector and estimation**: edit an L2-L4 description (the estimation evidence), then *Estimate* — the LangGraph pipeline streams live with the element's parent chain, relations, and code path injected as `c4_context`. *Refine* reuses the same checkpointed session. Accept or delete proposed elements, tag bugs, and link or create Jira issues.
10. **Roll-up** shows initiative → epic → story → task with deterministic point sums, spike/split flags, and *Estimate all pending* for sequential batch estimation.

The audit actor is an application-level identity label because this repository does not provide authentication. Connect the actor field to your SSO/session identity before treating the audit record as identity-assured compliance evidence.

## Provider switches

Only `backend/.env` changes. Provider and model strings do not appear in application code outside `backend/llm/factory.py`.

**Mock (offline — no key, no network)**

```dotenv
LLM_PROVIDER=mock
LLM_MODEL=mock
LLM_API_KEY=
```

Mock mode returns deterministic, schema-valid estimates derived from a hash of the story title (same story → same points; a 13 exercises the spike/split branch and split proposals). Every output is clearly labeled "Mock". Use it for demos, UI development, and trying the C4 workspace without a provider account or rate limits.

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
| POST/GET | `/projects` | Create / list projects |
| GET/DELETE | `/projects/{id}` | Project detail with links / cascade delete |
| POST | `/projects/{id}/repos`, `/projects/{id}/jira` | Link a repo or a Jira project |
| GET | `/projects/{id}/c4/graph` | Full C4 model (elements + relations + artifacts) |
| POST/PATCH/DELETE | `/projects/{id}/c4/elements[/{eid}]` | C4 element CRUD (parent must be one level up) |
| POST/DELETE | `/projects/{id}/c4/relations[/{rid}]` | C4 relation CRUD |
| POST | `/projects/{id}/c4/elements/{eid}/tag` | Tag cross-cutting bug / tech_debt / arch_flow |
| POST | `/projects/{id}/c4/import/repo-scan` | Propose (and optionally apply) elements from a local repo |
| POST | `/projects/{id}/c4/import/jira` | Import Jira issues as proposed stories |
| POST | `/projects/{id}/elements/{eid}/estimate` | Stream an estimate with `c4_context` evidence (L3/L4 only) |
| POST | `/projects/{id}/elements/{eid}/artifact` | Link or create (gated) the mapped Jira issue |
| GET | `/projects/{id}/rollup` | Deterministic initiative→epic→story roll-up with flags |
| GET/PATCH | `/projects/{id}/l1/{eid}/plan` | Read the complete L1 operating plan / update reporting currency |
| POST/PATCH/DELETE | `/projects/{id}/l1/{eid}/units`, `/projects/{id}/l1/units/{uid}` | Tribe and squad CRUD |
| POST/PATCH/DELETE | `/projects/{id}/l1/units/{uid}/members`, `/projects/{id}/l1/members/{mid}` | Team-member CRUD |
| POST/PATCH/DELETE | `/projects/{id}/l1/{eid}/work`, `/projects/{id}/l1/work/{wid}` | Costed work-package CRUD |
| POST/PATCH/DELETE | `/projects/{id}/l1/{eid}/diagrams`, `/projects/{id}/l1/diagrams/{did}` | Editable Mermaid diagram CRUD |
| GET/POST | `/projects/{id}/l1/{eid}/requirements` | List / create Markdown requirement documents |
| GET/PATCH | `/projects/{id}/l1/requirements/{rid}` | Read document, versions, comments, and audit / save a conflict-checked new version |
| GET | `/projects/{id}/l1/requirements/{rid}/versions/{version}` | Read an immutable historical version |
| POST/PATCH | `/projects/{id}/l1/requirements/{rid}/comments`, `/projects/{id}/l1/requirements/comments/{cid}` | Add a version-linked comment / approve, resolve, or reopen it |
| POST | `/projects/{id}/l1/requirements/{rid}/review` | Submit, approve, or revoke document approval |
| POST | `/projects/{id}/l1/requirements/{rid}/export/{docx\|pptx}` | Generate an Office export with client-rendered Mermaid PNG data |

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
