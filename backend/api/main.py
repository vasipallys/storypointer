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
