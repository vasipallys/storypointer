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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_elements_project ON c4_elements(project_id);
CREATE INDEX IF NOT EXISTS idx_elements_parent ON c4_elements(parent_id);
CREATE INDEX IF NOT EXISTS idx_relations_project ON c4_relations(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_element ON artifact_links(element_id);
"""

_initialized: set[str] = set()


def db_path() -> Path:
    configured = os.getenv("STORYPOINTER_DB")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "storypointer.db"


def checkpoint_path() -> Path:
    return db_path().with_name("checkpoints.db")


def init_db(path: Path | None = None) -> None:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
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
