from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY,
    full_name TEXT UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    language TEXT,
    stars INTEGER,
    forks INTEGER,
    open_issues INTEGER,
    last_pushed TEXT,
    starred_at TEXT,
    archived INTEGER DEFAULT 0,
    starred INTEGER DEFAULT 1,
    local_path TEXT,
    wiki_path TEXT,
    status TEXT DEFAULT 'new',
    relevance_score INTEGER DEFAULT 0,
    score_reason TEXT,
    decay_score INTEGER DEFAULT 0,
    last_star_sync TEXT,
    last_clone_sync TEXT,
    last_research_sync TEXT,
    last_opened TEXT,
    last_execution_sync TEXT,
    tags TEXT,
    decision TEXT,
    category TEXT,
    notes TEXT,
    hook TEXT,
    who_for TEXT,
    problem TEXT,
    why_now TEXT,
    demo_path TEXT
);

CREATE TABLE IF NOT EXISTS research_logs (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    pass_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    output_path TEXT,
    summary TEXT,
    agent_name TEXT,
    status TEXT,
    error TEXT,
    source_fingerprint TEXT,
    card_json TEXT,
    provenance_json TEXT,
    FOREIGN KEY(repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS repo_cards (
    repo_id INTEGER PRIMARY KEY,
    view TEXT,
    host_notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    startup_time REAL,
    port INTEGER,
    runtime_type TEXT,
    command TEXT,
    log_path TEXT,
    notes TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS project_mappings (
    id INTEGER PRIMARY KEY,
    project_name TEXT NOT NULL,
    repo_id INTEGER NOT NULL,
    fit_score INTEGER DEFAULT 0,
    reason TEXT,
    UNIQUE(project_name, repo_id),
    FOREIGN KEY(repo_id) REFERENCES repos(id)
);
"""


@dataclass(frozen=True)
class RepoInput:
    full_name: str
    owner: str
    repo: str
    url: str
    description: str | None = None
    language: str | None = None
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    last_pushed: str | None = None
    starred_at: str | None = None
    archived: bool = False


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(database: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(database)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
    if "starred_at" not in columns:
        conn.execute("ALTER TABLE repos ADD COLUMN starred_at TEXT")
    if "category" not in columns:
        conn.execute("ALTER TABLE repos ADD COLUMN category TEXT")
    research_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(research_logs)").fetchall()
    }
    if "source_fingerprint" not in research_columns:
        conn.execute("ALTER TABLE research_logs ADD COLUMN source_fingerprint TEXT")
    for card_field in ("hook", "who_for", "problem", "why_now", "demo_path"):
        if card_field not in columns:
            conn.execute(f"ALTER TABLE repos ADD COLUMN {card_field} TEXT")
    if "card_json" not in research_columns:
        conn.execute("ALTER TABLE research_logs ADD COLUMN card_json TEXT")
    if "provenance_json" not in research_columns:
        conn.execute("ALTER TABLE research_logs ADD COLUMN provenance_json TEXT")
    from .preferences import ensure_preferences_schema

    ensure_preferences_schema(conn)


def upsert_repo(conn: sqlite3.Connection, repo: RepoInput) -> int:
    timestamp = now_utc()
    conn.execute(
        """
        INSERT INTO repos (
            full_name, owner, repo, description, url, language, stars, forks,
            open_issues, last_pushed, starred_at, archived, starred, status, last_star_sync
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'new', ?)
        ON CONFLICT(full_name) DO UPDATE SET
            owner = excluded.owner,
            repo = excluded.repo,
            description = excluded.description,
            url = excluded.url,
            language = excluded.language,
            stars = excluded.stars,
            forks = excluded.forks,
            open_issues = excluded.open_issues,
            last_pushed = excluded.last_pushed,
            starred_at = excluded.starred_at,
            archived = excluded.archived,
            starred = 1,
            last_star_sync = excluded.last_star_sync
        """,
        (
            repo.full_name,
            repo.owner,
            repo.repo,
            repo.description,
            repo.url,
            repo.language,
            repo.stars,
            repo.forks,
            repo.open_issues,
            repo.last_pushed,
            repo.starred_at,
            int(repo.archived),
            timestamp,
        ),
    )
    row = conn.execute("SELECT id FROM repos WHERE full_name = ?", (repo.full_name,)).fetchone()
    return int(row["id"])


def mark_unstarred_missing(conn: sqlite3.Connection, synced_full_names: set[str]) -> int:
    rows = conn.execute("SELECT full_name FROM repos WHERE starred = 1").fetchall()
    missing = [row["full_name"] for row in rows if row["full_name"] not in synced_full_names]
    if not missing:
        return 0
    placeholders = ",".join("?" for _ in missing)
    conn.execute(f"UPDATE repos SET starred = 0 WHERE full_name IN ({placeholders})", missing)
    return len(missing)


def list_repos(conn: sqlite3.Connection, include_archived: bool = False) -> list[sqlite3.Row]:
    where = "" if include_archived else "WHERE archived = 0 AND status != 'archived'"
    return conn.execute(
        f"""
        SELECT repos.*, GROUP_CONCAT(project_mappings.project_name, ', ') AS projects
        FROM repos
        LEFT JOIN project_mappings ON project_mappings.repo_id = repos.id
        {where}
        GROUP BY repos.id
        ORDER BY relevance_score DESC, stars DESC, full_name ASC
        """
    ).fetchall()


def get_repo(conn: sqlite3.Connection, full_name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM repos WHERE full_name = ?", (full_name,)).fetchone()


def update_repo(conn: sqlite3.Connection, full_name: str, **fields: Any) -> None:
    if not fields:
        return
    invalid = set(fields) - {row["name"] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
    if invalid:
        raise ValueError(f"Unknown repo fields: {', '.join(sorted(invalid))}")
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE repos SET {assignments} WHERE full_name = ?",
        [*fields.values(), full_name],
    )


def insert_research_log(
    conn: sqlite3.Connection,
    repo_id: int,
    pass_type: str,
    summary: str,
    status: str,
    output_path: str | None = None,
    error: str | None = None,
    agent_name: str = "rundown",
    source_fingerprint: str | None = None,
    card_json: str | None = None,
    provenance_json: str | None = None,
    timestamp: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO research_logs (
            repo_id, pass_type, timestamp, output_path, summary, agent_name, status, error,
            source_fingerprint, card_json, provenance_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repo_id,
            pass_type,
            timestamp or now_utc(),
            output_path,
            summary,
            agent_name,
            status,
            error,
            source_fingerprint,
            card_json,
            provenance_json,
        ),
    )


def get_repo_card(conn: sqlite3.Connection, repo_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM repo_cards WHERE repo_id = ?",
        (repo_id,),
    ).fetchone()


def save_repo_card(
    conn: sqlite3.Connection,
    repo_id: int,
    *,
    view: str | None = None,
    host_notes: str | None = None,
) -> None:
    if view is not None and view not in {"host", "research"}:
        raise ValueError("Card view must be 'host' or 'research'")
    if view is None and host_notes is None:
        return
    if view is not None and host_notes is not None:
        conn.execute(
            """
            INSERT INTO repo_cards (repo_id, view, host_notes)
            VALUES (?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET
                view = excluded.view,
                host_notes = excluded.host_notes
            """,
            (repo_id, view, host_notes),
        )
    elif view is not None:
        conn.execute(
            """
            INSERT INTO repo_cards (repo_id, view)
            VALUES (?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET view = excluded.view
            """,
            (repo_id, view),
        )
    else:
        updated = conn.execute(
            "UPDATE repo_cards SET host_notes = ? WHERE repo_id = ?",
            (host_notes, repo_id),
        )
        if updated.rowcount:
            return
        view_column = next(
            row for row in conn.execute("PRAGMA table_info(repo_cards)") if row["name"] == "view"
        )
        initial_view = "host" if view_column["notnull"] else None
        conn.execute(
            """
            INSERT INTO repo_cards (repo_id, view, host_notes)
            VALUES (?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET host_notes = excluded.host_notes
            """,
            (repo_id, initial_view, host_notes),
        )


def latest_successful_research(
    conn: sqlite3.Connection,
    repo_id: int,
    pass_type: str = "Repository Understanding",
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM research_logs
        WHERE repo_id = ? AND pass_type = ? AND status = 'success'
        ORDER BY id DESC
        LIMIT 1
        """,
        (repo_id, pass_type),
    ).fetchone()


def latest_successful_research_history(
    conn: sqlite3.Connection,
    repo_id: int,
    *,
    limit: int = 2,
    pass_type: str = "Repository Understanding",
) -> list[sqlite3.Row]:
    if limit < 1:
        return []
    return conn.execute(
        """
        SELECT * FROM research_logs
        WHERE repo_id = ? AND pass_type = ? AND status = 'success'
        ORDER BY id DESC
        LIMIT ?
        """,
        (repo_id, pass_type, limit),
    ).fetchall()


def latest_successful_research_by_repo(
    conn: sqlite3.Connection,
    pass_type: str = "Repository Understanding",
) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT research_logs.*
        FROM research_logs
        JOIN (
            SELECT repo_id, MAX(id) AS latest_id
            FROM research_logs
            WHERE pass_type = ? AND status = 'success'
            GROUP BY repo_id
        ) latest ON latest.latest_id = research_logs.id
        """,
        (pass_type,),
    ).fetchall()
    return {int(row["repo_id"]): row for row in rows}


def insert_execution_log(
    conn: sqlite3.Connection,
    repo_id: int,
    status: str,
    runtime_type: str,
    command: str,
    log_path: str | None,
    notes: str,
    startup_time: float | None = None,
    port: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO execution_logs (
            repo_id, status, startup_time, port, runtime_type, command, log_path, notes, timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (repo_id, status, startup_time, port, runtime_type, command, log_path, notes, now_utc()),
    )


def has_successful_execution(conn: sqlite3.Connection, repo_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM execution_logs WHERE repo_id = ? AND status = 'success' LIMIT 1",
        (repo_id,),
    ).fetchone()
    return row is not None


def list_repos_by_decision(
    conn: sqlite3.Connection, decisions: list[str], include_archived: bool = False
) -> list[sqlite3.Row]:
    """List repositories with specific decision values, ordered for presentation."""
    placeholders = ",".join("?" for _ in decisions)
    where_parts = [f"decision IN ({placeholders})"]
    if not include_archived:
        where_parts.append("archived = 0")
    where_clause = " AND ".join(where_parts)
    return conn.execute(
        f"""
        SELECT * FROM repos
        WHERE {where_clause}
        ORDER BY relevance_score DESC, stars DESC, full_name ASC
        """,
        decisions,
    ).fetchall()


def upsert_project_mapping(
    conn: sqlite3.Connection, repo_id: int, project_name: str, fit_score: int, reason: str
) -> None:
    conn.execute(
        """
        INSERT INTO project_mappings (project_name, repo_id, fit_score, reason)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(project_name, repo_id) DO UPDATE SET
            fit_score = excluded.fit_score,
            reason = excluded.reason
        """,
        (project_name, repo_id, fit_score, reason),
    )
