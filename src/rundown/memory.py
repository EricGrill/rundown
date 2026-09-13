"""Append-only repository decisions for projects and agent handoffs."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import db
from .agent_io import AgentError, validate_limit


MAX_FULL_NAME_LENGTH = 255
MAX_PROJECT_LENGTH = 200
MAX_DECISION_LENGTH = 500
MAX_REASON_LENGTH = 4_000
MAX_EVIDENCE_LENGTH = 10_000
MAX_ACTOR_LENGTH = 200
EVIDENCE_LABEL = "caller-provided, not verified"


def ensure_memory_schema(conn: sqlite3.Connection) -> None:
    """Create decision memory only for an explicit write operation."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS repository_decisions (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL,
            project TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(repo_id) REFERENCES repos(id)
        );

        CREATE INDEX IF NOT EXISTS idx_repository_decisions_project_timestamp
            ON repository_decisions(project, timestamp DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_repository_decisions_repo_timestamp
            ON repository_decisions(repo_id, timestamp DESC, id DESC);
        """
    )


def _required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentError("invalid_input", f"{field} must be a nonblank string", 2)
    normalized = value.strip()
    if len(normalized) > maximum:
        raise AgentError(
            "invalid_input",
            f"{field} must be at most {maximum} characters",
            2,
        )
    return normalized


def _optional_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise AgentError("invalid_input", f"{field} must be a string", 2)
    normalized = value.strip()
    if len(normalized) > maximum:
        raise AgentError(
            "invalid_input",
            f"{field} must be at most {maximum} characters",
            2,
        )
    return normalized


def _known_repo(conn: sqlite3.Connection, full_name: object) -> sqlite3.Row:
    normalized = _required_text(full_name, "full_name", MAX_FULL_NAME_LENGTH)
    row = db.get_repo(conn, normalized)
    if row is None:
        raise AgentError("not_found", f"Unknown repository: {normalized}")
    return row


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "repo_id": row["repo_id"],
        "full_name": row["full_name"],
        "project": row["project"],
        "decision": row["decision"],
        "reason": row["reason"],
        "evidence": row["evidence"],
        "evidence_label": EVIDENCE_LABEL,
        "actor": row["actor"],
        "timestamp": row["timestamp"],
    }


def remember_repository(
    conn: sqlite3.Connection,
    full_name: str,
    *,
    project: str,
    decision: str,
    reason: str,
    evidence: str = "",
    actor: str = "user",
) -> dict[str, Any]:
    """Append a dated decision without changing repository or project-fit fields."""
    repo = _known_repo(conn, full_name)
    clean_project = _required_text(project, "project", MAX_PROJECT_LENGTH)
    clean_decision = _required_text(decision, "decision", MAX_DECISION_LENGTH)
    clean_reason = _required_text(reason, "reason", MAX_REASON_LENGTH)
    clean_evidence = _optional_text(evidence, "evidence", MAX_EVIDENCE_LENGTH)
    clean_actor = _required_text(actor, "actor", MAX_ACTOR_LENGTH)

    ensure_memory_schema(conn)
    cursor = conn.execute(
        """
        INSERT INTO repository_decisions (
            repo_id, project, decision, reason, evidence, actor, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repo["id"],
            clean_project,
            clean_decision,
            clean_reason,
            clean_evidence,
            clean_actor,
            db.now_utc(),
        ),
    )
    row = conn.execute(
        """
        SELECT repository_decisions.*, repos.full_name
        FROM repository_decisions
        JOIN repos ON repos.id = repository_decisions.repo_id
        WHERE repository_decisions.id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:  # Defensive: SQLite should always return the inserted row.
        raise AgentError("operation_failed", "Could not read the saved decision")
    return _record(row)


def recall_decisions(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    full_name: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read newest decisions without creating or migrating memory storage."""
    validate_limit(limit)
    clean_project = (
        _required_text(project, "project", MAX_PROJECT_LENGTH)
        if project is not None
        else None
    )
    repo_id: int | None = None
    clean_full_name: str | None = None
    if full_name is not None:
        repo = _known_repo(conn, full_name)
        repo_id = int(repo["id"])
        clean_full_name = str(repo["full_name"])

    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'repository_decisions'"
    ).fetchone()
    filters = {"project": clean_project, "full_name": clean_full_name}
    if table is None:
        return {"results": [], "count": 0, "limit": limit, "filters": filters, "has_more": False}

    clauses: list[str] = []
    parameters: list[object] = []
    if clean_project is not None:
        clauses.append("repository_decisions.project = ?")
        parameters.append(clean_project)
    if repo_id is not None:
        clauses.append("repository_decisions.repo_id = ?")
        parameters.append(repo_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT repository_decisions.*, repos.full_name
        FROM repository_decisions
        JOIN repos ON repos.id = repository_decisions.repo_id
        {where}
        ORDER BY repository_decisions.timestamp DESC, repository_decisions.id DESC
        LIMIT ?
        """,
        (*parameters, limit + 1),
    ).fetchall()
    results = [_record(row) for row in rows[:limit]]
    return {
        "results": results,
        "count": len(results),
        "limit": limit,
        "filters": filters,
        "has_more": len(rows) > limit,
    }


def search_decision_text(conn: sqlite3.Connection, repo_ids: list[int]) -> dict[int, str]:
    """Supply at most five recent, SQL-clipped decisions per search candidate."""
    if not repo_ids or not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='repository_decisions'"
    ).fetchone():
        return {}
    if len(repo_ids) > 100:
        raise ValueError("decision search batches must not exceed 100 repositories")
    placeholders = ",".join("?" for _ in repo_ids)
    rows = conn.execute(
        f"SELECT repo_id, substr(project,1,200) AS project, substr(decision,1,500) AS decision, "
        "substr(reason,1,2500) AS reason, substr(evidence,1,500) AS evidence "
        f"FROM repository_decisions d WHERE repo_id IN ({placeholders}) AND id IN ("
        "SELECT id FROM repository_decisions recent WHERE recent.repo_id=d.repo_id "
        "ORDER BY timestamp DESC,id DESC LIMIT 5) ORDER BY timestamp DESC,id DESC LIMIT 500",
        repo_ids,
    )
    texts: dict[int, str] = {}
    for row in rows:
        text = " ".join(f"{key}: {row[key]}" for key in ("project", "decision", "reason", "evidence"))
        repo_id = int(row["repo_id"])
        texts[repo_id] = (texts.get(repo_id, "") + "\n" + text)[:20_001]
    return texts
