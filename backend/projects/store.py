"""CRUD for projects, repo links, and Jira links."""

from __future__ import annotations

from typing import Any

from backend.projects.models import JiraLinkCreate, ProjectCreate, RepoLinkCreate
from backend.storage.db import connect, new_id, rows_to_dicts, utc_now


class NotFoundError(LookupError):
    pass


def create_project(payload: ProjectCreate) -> dict[str, Any]:
    project = {
        "id": new_id(),
        "name": payload.name,
        "description": payload.description,
        "created_at": utc_now(),
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description, created_at) VALUES (:id, :name, :description, :created_at)",
            project,
        )
    return get_project(project["id"])


def list_projects() -> list[dict[str, Any]]:
    with connect() as conn:
        projects = rows_to_dicts(conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall())
        for project in projects:
            project.update(_links(conn, project["id"]))
            counts = conn.execute(
                """SELECT
                     SUM(CASE WHEN level = 'L3' THEN 1 ELSE 0 END) AS stories,
                     SUM(CASE WHEN level = 'L3' AND id IN (
                       SELECT element_id FROM artifact_links WHERE points IS NOT NULL
                     ) THEN 1 ELSE 0 END) AS estimated
                   FROM c4_elements WHERE project_id = ?""",
                (project["id"],),
            ).fetchone()
            project["story_count"] = counts["stories"] or 0
            project["estimated_count"] = counts["estimated"] or 0
    return projects


def get_project(project_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Project '{project_id}' was not found")
        project = dict(row)
        project.update(_links(conn, project_id))
    return project


def delete_project(project_id: str) -> None:
    with connect() as conn:
        deleted = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount
    if not deleted:
        raise NotFoundError(f"Project '{project_id}' was not found")


def add_repo_link(project_id: str, payload: RepoLinkCreate) -> dict[str, Any]:
    get_project(project_id)
    record = {"id": new_id(), "project_id": project_id, **payload.model_dump()}
    with connect() as conn:
        conn.execute(
            """INSERT INTO repo_links (id, project_id, url, local_path, provider, mode, default_branch)
               VALUES (:id, :project_id, :url, :local_path, :provider, :mode, :default_branch)""",
            record,
        )
    return record


def add_jira_link(project_id: str, payload: JiraLinkCreate) -> dict[str, Any]:
    get_project(project_id)
    record = {"id": new_id(), "project_id": project_id, **payload.model_dump()}
    record["instance_name"] = record["instance_name"].lower()
    with connect() as conn:
        conn.execute(
            "INSERT INTO jira_links (id, project_id, instance_name, project_key) VALUES (:id, :project_id, :instance_name, :project_key)",
            record,
        )
    return record


def _links(conn: Any, project_id: str) -> dict[str, Any]:
    return {
        "repos": rows_to_dicts(conn.execute("SELECT * FROM repo_links WHERE project_id = ?", (project_id,)).fetchall()),
        "jira": rows_to_dicts(conn.execute("SELECT * FROM jira_links WHERE project_id = ?", (project_id,)).fetchall()),
    }
