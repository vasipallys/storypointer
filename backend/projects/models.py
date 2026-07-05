"""API models for projects and their repo/Jira links."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class RepoLinkCreate(BaseModel):
    url: str = ""
    local_path: str = ""
    provider: str = "git"
    mode: Literal["existing", "new"] = "existing"
    default_branch: str = "main"


class JiraLinkCreate(BaseModel):
    instance_name: str = Field(min_length=1)
    project_key: str = Field(min_length=1, max_length=50)
