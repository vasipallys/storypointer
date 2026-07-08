"""Structured-output contracts for the agentic services.

These schemas are the contract between the agent prompts and the callers; the
mock provider builds valid instances of each for offline runs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---- Auto-staffing agent ------------------------------------------------

class StaffingAssignment(BaseModel):
    staff_id: str = Field(description="resource_staff_id of the person to assign")
    staff_name: str = ""
    squad_id: str = Field(description="id of the squad to place them in")
    squad_name: str = ""
    role: str = Field(default="", description="role this person plays in the squad")
    allocation_percent: float = Field(ge=0, le=100)
    reason: str = Field(default="", max_length=400)


class StaffingProposal(BaseModel):
    summary: str = Field(default="", max_length=1200)
    assignments: list[StaffingAssignment] = Field(default_factory=list)


# ---- Reporting narrative agent ------------------------------------------

class NarrativeOutput(BaseModel):
    headline: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=2000)
    highlights: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    recommendations: list[str] = Field(default_factory=list, max_length=8)


# ---- Requirements → stories decomposition -------------------------------

class ProposedStory(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    rationale: str = Field(default="", max_length=400)


class StoryDecomposition(BaseModel):
    summary: str = Field(default="", max_length=1200)
    stories: list[ProposedStory] = Field(default_factory=list, max_length=20)


# ---- C4-from-description scaffold ----------------------------------------

class ScaffoldElement(BaseModel):
    ref: str = Field(description="temporary id used to wire relations within this proposal")
    level: Literal["L1", "L2", "L3"]
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=1200)
    tech: str = Field(default="", max_length=200)
    parent_ref: str | None = Field(default=None, description="ref of the parent element, or null for L1")


class ScaffoldRelation(BaseModel):
    source_ref: str
    target_ref: str
    label: str = Field(default="", max_length=120)
    kind: str = Field(default="sync", max_length=40)


class C4Scaffold(BaseModel):
    summary: str = Field(default="", max_length=1200)
    elements: list[ScaffoldElement] = Field(default_factory=list, max_length=40)
    relations: list[ScaffoldRelation] = Field(default_factory=list, max_length=60)
