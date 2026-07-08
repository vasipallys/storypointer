"""SQLite persistence for projects, C4 models, and artifact links.

Standard-library sqlite3 keeps the storage layer dependency-free. Connections
are short-lived (one per operation) with WAL enabled, which is safe under the
app's low write concurrency.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_DIAGRAM_TYPES = (
    "architecture",
    "infrastructure",
    "architecture_beta",
    "block",
    "kanban",
    "packet",
    "sequence",
    "class",
    "state",
    "er",
    "requirement",
    "c4",
    "gantt",
    "journey",
    "timeline",
    "mindmap",
    "quadrant",
    "gitgraph",
    "pie",
    "xychart",
    "sankey",
    "radar",
    "treemap",
    "venn",
)
_DIAGRAM_TYPE_CHECK = ", ".join(f"'{diagram_type}'" for diagram_type in _DIAGRAM_TYPES)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  leads TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repo_links (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  url TEXT NOT NULL DEFAULT '',
  local_path TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT 'git',
  mode TEXT NOT NULL DEFAULT 'existing',
  default_branch TEXT NOT NULL DEFAULT 'main'
);
CREATE TABLE IF NOT EXISTS jira_links (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  instance_name TEXT NOT NULL,
  project_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS c4_elements (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK (level IN ('L1','L2','L3','L4')),
  kind TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  parent_id TEXT REFERENCES c4_elements(id) ON DELETE CASCADE,
  tech TEXT NOT NULL DEFAULT '',
  code_path TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  pos_x REAL,
  pos_y REAL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS c4_relations (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  target_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'sync'
);
CREATE TABLE IF NOT EXISTS artifact_links (
  id TEXT PRIMARY KEY,
  element_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  artifact_type TEXT NOT NULL,
  jira_issue_key TEXT,
  points INTEGER,
  spike_recommended INTEGER NOT NULL DEFAULT 0,
  split_recommended INTEGER NOT NULL DEFAULT 0,
  estimate_session_id TEXT,
  estimated_at TEXT,
  UNIQUE (element_id, artifact_type)
);
CREATE TABLE IF NOT EXISTS l1_agile_units (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  l1_element_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  unit_type TEXT NOT NULL CHECK (unit_type IN ('tribe','squad')),
  parent_unit_id TEXT REFERENCES l1_agile_units(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  mission TEXT NOT NULL DEFAULT '',
  lead_name TEXT NOT NULL DEFAULT '',
  capacity_fte REAL NOT NULL DEFAULT 0 CHECK (capacity_fte >= 0),
  target_velocity REAL NOT NULL DEFAULT 0 CHECK (target_velocity >= 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_plan_settings (
  l1_element_id TEXT PRIMARY KEY REFERENCES c4_elements(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  currency_code TEXT NOT NULL DEFAULT 'USD',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_team_members (
  id TEXT PRIMARY KEY,
  unit_id TEXT NOT NULL REFERENCES l1_agile_units(id) ON DELETE CASCADE,
  resource_staff_id TEXT REFERENCES resource_staff(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT '',
  skills TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  allocation_percent REAL NOT NULL DEFAULT 100 CHECK (allocation_percent >= 0 AND allocation_percent <= 100),
  monthly_cost REAL NOT NULL DEFAULT 0 CHECK (monthly_cost >= 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_work_items (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  l1_element_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  squad_id TEXT REFERENCES l1_agile_units(id) ON DELETE SET NULL,
  linked_element_id TEXT REFERENCES c4_elements(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','in_progress','at_risk','done')),
  allocation_percent REAL NOT NULL DEFAULT 100 CHECK (allocation_percent >= 0 AND allocation_percent <= 100),
  budget_cost REAL NOT NULL DEFAULT 0 CHECK (budget_cost >= 0),
  actual_cost REAL NOT NULL DEFAULT 0 CHECK (actual_cost >= 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_diagrams (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  l1_element_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  diagram_type TEXT NOT NULL CHECK (diagram_type IN ({_DIAGRAM_TYPE_CHECK})),
  title TEXT NOT NULL,
  mermaid_source TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_requirement_documents (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  l1_element_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','approved')),
  version INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_requirement_versions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES l1_requirement_documents(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  changed_by TEXT NOT NULL,
  change_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (document_id, version)
);
CREATE TABLE IF NOT EXISTS l1_requirement_comments (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES l1_requirement_documents(id) ON DELETE CASCADE,
  document_version INTEGER NOT NULL,
  parent_comment_id TEXT REFERENCES l1_requirement_comments(id) ON DELETE SET NULL,
  body TEXT NOT NULL,
  author TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','resolved')),
  acted_by TEXT,
  acted_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l1_requirement_audit (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES l1_requirement_documents(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_staff (
  id TEXT PRIMARY KEY,
  staff_code TEXT NOT NULL UNIQUE,
  staff_first_name TEXT NOT NULL,
  staff_last_name TEXT NOT NULL,
  staff_name TEXT NOT NULL DEFAULT '',
  staff_type TEXT NOT NULL DEFAULT 'Perm' CHECK (staff_type IN ('Perm','Contract')),
  staff_status TEXT NOT NULL DEFAULT 'Active' CHECK (staff_status IN ('Active','Inactive')),
  sub_status TEXT NOT NULL DEFAULT 'UnAllocated' CHECK (sub_status IN ('Allocated','UnAllocated','PartiallyAllocated')),
  tech_unit TEXT NOT NULL DEFAULT '',
  citizenship TEXT NOT NULL DEFAULT '',
  rank TEXT NOT NULL DEFAULT '',
  hr_role TEXT NOT NULL DEFAULT '',
  staff_start_date TEXT,
  staff_end_date TEXT,
  reporting_manager_id TEXT REFERENCES resource_staff(id) ON DELETE SET NULL,
  custom_values TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_lookups (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL CHECK (category IN ('tech_unit','rank','hr_role')),
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  UNIQUE (category, code)
);
CREATE TABLE IF NOT EXISTS resource_custom_fields (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  field_type TEXT NOT NULL DEFAULT 'text' CHECK (field_type IN ('text','number','date','select','boolean')),
  required INTEGER NOT NULL DEFAULT 0,
  options TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_staff_manager ON resource_staff(reporting_manager_id);
CREATE INDEX IF NOT EXISTS idx_resource_lookups_category ON resource_lookups(category);
CREATE INDEX IF NOT EXISTS idx_elements_project ON c4_elements(project_id);
CREATE INDEX IF NOT EXISTS idx_elements_parent ON c4_elements(parent_id);
CREATE INDEX IF NOT EXISTS idx_relations_project ON c4_relations(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_element ON artifact_links(element_id);
CREATE INDEX IF NOT EXISTS idx_l1_units_element ON l1_agile_units(l1_element_id);
CREATE INDEX IF NOT EXISTS idx_l1_members_unit ON l1_team_members(unit_id);
CREATE INDEX IF NOT EXISTS idx_l1_work_element ON l1_work_items(l1_element_id);
CREATE INDEX IF NOT EXISTS idx_l1_diagrams_element ON l1_diagrams(l1_element_id);
CREATE INDEX IF NOT EXISTS idx_l1_requirements_element ON l1_requirement_documents(l1_element_id);
CREATE INDEX IF NOT EXISTS idx_l1_requirement_versions_doc ON l1_requirement_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_l1_requirement_comments_doc ON l1_requirement_comments(document_id);
CREATE INDEX IF NOT EXISTS idx_l1_requirement_audit_doc ON l1_requirement_audit(document_id);
"""

_initialized: set[str] = set()


def db_path() -> Path:
    configured = os.getenv("STORYPOINTER_DB")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "storypointer.db"


def checkpoint_path() -> Path:
    return db_path().with_name("checkpoints.db")


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add missing columns to an existing table (lightweight forward migration)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _ensure_l1_diagram_type_check(conn: sqlite3.Connection) -> None:
    """Rebuild old l1_diagrams tables whose CHECK only allowed two diagram types."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'l1_diagrams'"
    ).fetchone()
    sql = row[0] if row else ""
    if not sql or all(f"'{diagram_type}'" in sql for diagram_type in _DIAGRAM_TYPES):
        return

    conn.execute("DROP INDEX IF EXISTS idx_l1_diagrams_element")
    conn.execute("ALTER TABLE l1_diagrams RENAME TO l1_diagrams_old")
    conn.execute(
        f"""CREATE TABLE l1_diagrams (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          l1_element_id TEXT NOT NULL REFERENCES c4_elements(id) ON DELETE CASCADE,
          diagram_type TEXT NOT NULL CHECK (diagram_type IN ({_DIAGRAM_TYPE_CHECK})),
          title TEXT NOT NULL,
          mermaid_source TEXT NOT NULL,
          metadata TEXT NOT NULL DEFAULT '{{}}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """INSERT INTO l1_diagrams
           (id, project_id, l1_element_id, diagram_type, title, mermaid_source, metadata, created_at, updated_at)
           SELECT id, project_id, l1_element_id, diagram_type, title, mermaid_source, metadata, created_at, updated_at
           FROM l1_diagrams_old"""
    )
    conn.execute("DROP TABLE l1_diagrams_old")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_l1_diagrams_element ON l1_diagrams(l1_element_id)")


_DEFAULT_RESOURCE_LOOKUPS = {
    "tech_unit": [("PLATFORM", "Platform"), ("DATA", "Data & Analytics"), ("MOBILE", "Mobile"), ("CLOUD", "Cloud & Infra")],
    "rank": [("A1", "Analyst"), ("SA", "Senior Analyst"), ("C", "Consultant"), ("SC", "Senior Consultant"), ("M", "Manager")],
    "hr_role": [("ENG", "Engineer"), ("QA", "QA Engineer"), ("BA", "Business Analyst"), ("PM", "Project Manager"), ("ARCH", "Architect")],
}


def _seed_resource_lookups(conn: sqlite3.Connection) -> None:
    """Populate the reference tables once so the staff form has defaults to pick from."""
    if conn.execute("SELECT 1 FROM resource_lookups LIMIT 1").fetchone():
        return
    for category, entries in _DEFAULT_RESOURCE_LOOKUPS.items():
        for code, label in entries:
            conn.execute(
                "INSERT INTO resource_lookups (id, category, code, label) VALUES (?, ?, ?, ?)",
                (uuid.uuid4().hex, category, code, label),
            )


def init_db(path: Path | None = None) -> None:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _ensure_columns(conn, "l1_diagrams", {"metadata": "TEXT NOT NULL DEFAULT '{}'"})
        _ensure_l1_diagram_type_check(conn)
        _ensure_columns(conn, "projects", {"leads": "TEXT NOT NULL DEFAULT '[]'"})
        _ensure_columns(conn, "l1_team_members", {"resource_staff_id": "TEXT REFERENCES resource_staff(id) ON DELETE SET NULL"})
        _seed_resource_lookups(conn)
    _initialized.add(str(target))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    target = db_path()
    if str(target) not in _initialized:
        init_db(target)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def new_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
