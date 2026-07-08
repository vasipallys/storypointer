"""Agentic AI endpoints. All require a configured LLM (503 otherwise, like estimation)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.ai import agents
from backend.ai.schemas import ProposedStory, ScaffoldElement, ScaffoldRelation, StaffingAssignment
from backend.api.streaming import require_llm_config
from backend.c4 import store as c4_store
from backend.planning import store as planning_store
from backend.projects.store import NotFoundError
from backend.reporting import service as reporting_service

router = APIRouter(tags=["ai"])


def _guard(operation: Any) -> Any:
    try:
        return operation()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc
    except (planning_store.PlanningValidationError, c4_store.C4ValidationError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid", "message": str(exc)}) from exc


# ---- request bodies -----------------------------------------------------

class ApplyStaffing(BaseModel):
    assignments: list[StaffingAssignment] = Field(default_factory=list)


class DecomposeRequest(BaseModel):
    guidance: str = Field(default="", max_length=2000)


class ApplyStories(BaseModel):
    stories: list[ProposedStory] = Field(default_factory=list, max_length=30)


class ScaffoldRequest(BaseModel):
    description: str = Field(min_length=1, max_length=8000)


class ApplyScaffold(BaseModel):
    elements: list[ScaffoldElement] = Field(default_factory=list, max_length=60)
    relations: list[ScaffoldRelation] = Field(default_factory=list, max_length=80)


# ---- auto-staffing ------------------------------------------------------

@router.post("/projects/{project_id}/l1/{l1_element_id}/ai/staffing")
async def suggest_staffing(project_id: str, l1_element_id: str, request: Request) -> dict[str, Any]:
    require_llm_config(request)
    proposal = await agents.propose_staffing(project_id, l1_element_id)
    return proposal.model_dump()


@router.post("/projects/{project_id}/ai/staffing/apply")
async def apply_staffing(project_id: str, payload: ApplyStaffing) -> dict[str, Any]:
    return _guard(lambda: agents.apply_staffing(project_id, [a.model_dump() for a in payload.assignments]))


# ---- reporting narrative ------------------------------------------------

@router.post("/reporting/narrative")
async def reporting_narrative(request: Request) -> dict[str, Any]:
    require_llm_config(request)
    narrative = await agents.generate_narrative(reporting_service.overview())
    return narrative.model_dump()


# ---- requirements → stories ---------------------------------------------

@router.post("/projects/{project_id}/c4/elements/{element_id}/ai/decompose")
async def decompose(project_id: str, element_id: str, payload: DecomposeRequest, request: Request) -> dict[str, Any]:
    require_llm_config(request)
    element = _guard(lambda: c4_store.get_element(project_id, element_id))
    if element["level"] == "L4":
        raise HTTPException(status_code=400, detail={"code": "not_decomposable", "message": "L4 tasks are already the lowest level."})
    result = await agents.decompose_element(project_id, element_id, payload.guidance)
    return result.model_dump()


@router.post("/projects/{project_id}/c4/elements/{element_id}/ai/decompose/apply")
async def apply_decompose(project_id: str, element_id: str, payload: ApplyStories) -> dict[str, Any]:
    return _guard(lambda: agents.apply_decomposition(project_id, element_id, [s.model_dump() for s in payload.stories]))


# ---- C4 scaffold --------------------------------------------------------

@router.post("/projects/{project_id}/c4/ai/scaffold")
async def scaffold(project_id: str, payload: ScaffoldRequest, request: Request) -> dict[str, Any]:
    require_llm_config(request)
    result = await agents.scaffold_c4(project_id, payload.description)
    return result.model_dump()


@router.post("/projects/{project_id}/c4/ai/scaffold/apply")
async def apply_scaffold(project_id: str, payload: ApplyScaffold) -> dict[str, Any]:
    return _guard(lambda: agents.apply_scaffold(project_id, payload.model_dump()))
