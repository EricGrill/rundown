"""SQLite database operations for Rundown."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from .models import Repo, Status


SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    
    description TEXT,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    pushed_at TEXT,
    created_at TEXT,
    language TEXT,
    license TEXT,
    topics TEXT DEFAULT '[]',
    archived INTEGER DEFAULT 0,
    homepage TEXT,
    default_branch TEXT DEFAULT 'main',
    has_readme INTEGER DEFAULT 0,
    readme_length INTEGER DEFAULT 0,
    
    status TEXT DEFAULT 'inbox',
    present_score REAL DEFAULT 0.0,
    score_reason TEXT DEFAULT '',
    manual_boost INTEGER DEFAULT 0,
    
    hook TEXT DEFAULT '',
    who_for TEXT DEFAULT '',
    problem TEXT DEFAULT '',
    why_now TEXT DEFAULT '',
    demo_path TEXT DEFAULT '',
    flags TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    
    added_at TEXT,
    updated_at TEXT,
    starred_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_repos_status ON repos(status);
CREATE INDEX IF NOT EXISTS idx_repos_score ON repos(present_score DESC);
CREATE INDEX IF NOT EXISTS idx_repos_full_name ON repos(full_name);
"""


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_datetime(value: datetime | None) -> str | None:
    """Format datetime to ISO string."""
    if not value:
        return None
    return value.isoformat()


def _row_to_repo(row: sqlite3.Row) -> Repo:
    """Convert a database row to a Repo object."""
    return Repo(
        id=row["id"],
        full_name=row["full_name"],
        owner=row["owner"],
        name=row["name"],
        url=row["url"],
        description=row["description"],
        stars=row["stars"],
        forks=row["forks"],
        open_issues=row["open_issues"],
        pushed_at=_parse_datetime(row["pushed_at"]),
        created_at=_parse_datetime(row["created_at"]),
        language=row["language"],
        license=row["license"],
        topics=json.loads(row["topics"] or "[]"),
        archived=bool(row["archived"]),
        homepage=row["homepage"],
        default_branch=row["default_branch"],
        has_readme=bool(row["has_readme"]),
        readme_length=row["readme_length"],
        status=Status(row["status"]),
        present_score=row["present_score"],
        score_reason=row["score_reason"],
        manual_boost=row["manual_boost"],
        hook=row["hook"],
        who_for=row["who_for"],
        problem=row["problem"],
        why_now=row["why_now"],
        demo_path=row["demo_path"],
        flags=json.loads(row["flags"] or "[]"),
        notes=row["notes"],
        added_at=_parse_datetime(row["added_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
        starred_at=_parse_datetime(row["starred_at"]),
    )


class Database:
    """SQLite database for Rundown repos."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
    
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def upsert_repo(self, repo: Repo) -> Repo:
        """Insert or update a repo, returning the repo with its ID."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, status, manual_boost, hook, who_for, problem, why_now, demo_path, flags, notes FROM repos WHERE full_name = ?",
                (repo.full_name,)
            ).fetchone()
            
            if existing:
                conn.execute("""
                    UPDATE repos SET
                        owner = ?, name = ?, url = ?, description = ?, stars = ?,
                        forks = ?, open_issues = ?, pushed_at = ?, created_at = ?,
                        language = ?, license = ?, topics = ?, archived = ?,
                        homepage = ?, default_branch = ?, has_readme = ?, readme_length = ?,
                        present_score = ?, score_reason = ?, updated_at = ?,
                        starred_at = COALESCE(?, starred_at)
                    WHERE full_name = ?
                """, (
                    repo.owner, repo.name, repo.url, repo.description, repo.stars,
                    repo.forks, repo.open_issues, _format_datetime(repo.pushed_at),
                    _format_datetime(repo.created_at), repo.language, repo.license,
                    json.dumps(repo.topics), int(repo.archived), repo.homepage,
                    repo.default_branch, int(repo.has_readme), repo.readme_length,
                    repo.present_score, repo.score_reason, _format_datetime(datetime.now()),
                    _format_datetime(repo.starred_at), repo.full_name
                ))
                repo.id = existing["id"]
                repo.status = Status(existing["status"])
                repo.manual_boost = existing["manual_boost"]
                repo.hook = existing["hook"]
                repo.who_for = existing["who_for"]
                repo.problem = existing["problem"]
                repo.why_now = existing["why_now"]
                repo.demo_path = existing["demo_path"]
                repo.flags = json.loads(existing["flags"] or "[]")
                repo.notes = existing["notes"]
            else:
                cursor = conn.execute("""
                    INSERT INTO repos (
                        full_name, owner, name, url, description, stars, forks,
                        open_issues, pushed_at, created_at, language, license,
                        topics, archived, homepage, default_branch, has_readme,
                        readme_length, status, present_score, score_reason,
                        manual_boost, hook, who_for, problem, why_now, demo_path,
                        flags, notes, added_at, updated_at, starred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    repo.full_name, repo.owner, repo.name, repo.url, repo.description,
                    repo.stars, repo.forks, repo.open_issues,
                    _format_datetime(repo.pushed_at), _format_datetime(repo.created_at),
                    repo.language, repo.license, json.dumps(repo.topics), int(repo.archived),
                    repo.homepage, repo.default_branch, int(repo.has_readme),
                    repo.readme_length, repo.status.value, repo.present_score,
                    repo.score_reason, repo.manual_boost, repo.hook, repo.who_for,
                    repo.problem, repo.why_now, repo.demo_path, json.dumps(repo.flags),
                    repo.notes, _format_datetime(repo.added_at),
                    _format_datetime(repo.updated_at), _format_datetime(repo.starred_at)
                ))
                repo.id = cursor.lastrowid
        
        return repo
    
    def get_repo(self, full_name: str) -> Optional[Repo]:
        """Get a repo by full name."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM repos WHERE full_name = ?", (full_name,)
            ).fetchone()
            return _row_to_repo(row) if row else None
    
    def get_repo_by_id(self, repo_id: int) -> Optional[Repo]:
        """Get a repo by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM repos WHERE id = ?", (repo_id,)
            ).fetchone()
            return _row_to_repo(row) if row else None
    
    def list_repos(
        self,
        status: Optional[Status] = None,
        order_by: str = "present_score DESC",
    ) -> list[Repo]:
        """List repos, optionally filtered by status."""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    f"SELECT * FROM repos WHERE status = ? ORDER BY {order_by}",
                    (status.value,)
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM repos ORDER BY {order_by}"
                ).fetchall()
            return [_row_to_repo(row) for row in rows]
    
    def update_status(self, repo_id: int, status: Status) -> None:
        """Update repo status."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE repos SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, _format_datetime(datetime.now()), repo_id)
            )
    
    def update_card(
        self,
        repo_id: int,
        hook: str | None = None,
        who_for: str | None = None,
        problem: str | None = None,
        why_now: str | None = None,
        demo_path: str | None = None,
        flags: list[str] | None = None,
        notes: str | None = None,
    ) -> None:
        """Update card fields for a repo."""
        updates = []
        params = []
        
        if hook is not None:
            updates.append("hook = ?")
            params.append(hook)
        if who_for is not None:
            updates.append("who_for = ?")
            params.append(who_for)
        if problem is not None:
            updates.append("problem = ?")
            params.append(problem)
        if why_now is not None:
            updates.append("why_now = ?")
            params.append(why_now)
        if demo_path is not None:
            updates.append("demo_path = ?")
            params.append(demo_path)
        if flags is not None:
            updates.append("flags = ?")
            params.append(json.dumps(flags))
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        
        if updates:
            updates.append("updated_at = ?")
            params.append(_format_datetime(datetime.now()))
            params.append(repo_id)
            
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE repos SET {', '.join(updates)} WHERE id = ?",
                    params
                )
    
    def update_manual_boost(self, repo_id: int, boost: int) -> None:
        """Update manual boost for a repo."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE repos SET manual_boost = ?, updated_at = ? WHERE id = ?",
                (boost, _format_datetime(datetime.now()), repo_id)
            )
    
    def update_score(self, repo_id: int, score: float, reason: str) -> None:
        """Update score and reason for a repo."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE repos SET present_score = ?, score_reason = ?, updated_at = ? WHERE id = ?",
                (score, reason, _format_datetime(datetime.now()), repo_id)
            )
    
    def count_by_status(self) -> dict[Status, int]:
        """Count repos by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM repos GROUP BY status"
            ).fetchall()
            counts = {s: 0 for s in Status}
            for row in rows:
                counts[Status(row["status"])] = row["count"]
            return counts
    
    def delete_repo(self, repo_id: int) -> None:
        """Delete a repo."""
        with self._connect() as conn:
            conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
