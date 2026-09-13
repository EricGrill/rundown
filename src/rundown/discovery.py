"""Explicit, bounded public GitHub discovery; never generates research."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from datetime import datetime
from typing import Any

from . import db
from .agent_io import AgentError, validate_limit


def validate_repository_name(full_name: str) -> None:
    if not isinstance(full_name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,99}/[A-Za-z0-9_.-]{1,100}", full_name
    ) or full_name.split("/")[-1] in {".", ".."}:
        raise AgentError("invalid_input", "Use a GitHub OWNER/REPO name.", 2)


def _github_json(endpoint: str, fields: dict[str, str] | None = None) -> dict[str, Any]:
    command = ["gh", "api", "--method", "GET", endpoint,
               "--header", "Accept: application/vnd.github+json"]
    for name, value in (fields or {}).items():
        command.extend(["-f", f"{name}={value}"])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        raise AgentError("github_unavailable", "Install GitHub CLI and run gh auth login.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AgentError("github_timeout", "GitHub request exceeded 30 seconds; retry later.") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or "GitHub request failed."
        raise AgentError("github_error", detail[:2000])
    if len(completed.stdout) > 4_000_000:
        raise AgentError("github_response", "GitHub response exceeded the 4 MB parsing limit.")
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, RecursionError) as exc:
        raise AgentError("github_response", "GitHub returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise AgentError("github_response", "GitHub returned an unexpected response shape.")
    return payload


def _repository(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or item.get("private") is not False or item.get("visibility") != "public":
        raise AgentError("github_response", "Expected public repository metadata.")
    name = item.get("full_name")
    if not isinstance(name, str):
        raise AgentError("github_response", "GitHub returned an invalid repository name.")
    try:
        validate_repository_name(name)
    except AgentError as exc:
        raise AgentError("github_response", "GitHub returned an invalid repository name.") from exc
    if not isinstance(item.get("archived"), bool):
        raise AgentError("github_response", "GitHub returned invalid archive metadata.")
    stars = item.get("stargazers_count")
    if isinstance(stars, bool) or not isinstance(stars, int) or not 0 <= stars <= 2**63 - 1:
        raise AgentError("github_response", "GitHub returned an invalid star count.")
    for field in ("description", "language", "pushed_at"):
        if item.get(field) is not None and not isinstance(item[field], str):
            raise AgentError("github_response", f"GitHub returned invalid {field} metadata.")
        if item.get(field) is not None and len(item[field]) > (20_000 if field == "description" else 100):
            raise AgentError("github_response", f"GitHub returned oversized {field} metadata.")
    if item.get("pushed_at") is not None:
        try:
            datetime.fromisoformat(item["pushed_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgentError("github_response", "GitHub returned an invalid activity timestamp.") from exc
    return {
        "full_name": name, "url": f"https://github.com/{name}",
        "description": item.get("description"), "language": item.get("language"),
        "stars": stars, "last_pushed": item.get("pushed_at"),
        "archived": item["archived"], "source": "github",
    }


def discover_repositories(
    conn: sqlite3.Connection, query: str, *, limit: int = 5,
    sort: str = "best-fit", include_saved: bool = False,
) -> dict[str, Any]:
    validate_limit(limit)
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise AgentError("invalid_input", "query must contain 1–500 characters.", 2)
    if sort not in {"best-fit", "stars", "updated"}:
        raise AgentError("invalid_input", "sort must be best-fit, stars, or updated.", 2)
    # Public-only is an invariant even if the caller supplies contrary qualifiers.
    if re.search(r"\b(?:is|visibility):(?:private|internal)\b", query, flags=re.IGNORECASE):
        raise AgentError("invalid_input", "Discovery only supports public repositories.", 2)
    effective_query = f"{query.strip()} is:public"
    if "archived:" not in query.casefold():
        effective_query += " archived:false"
    fields = {"q": effective_query, "per_page": "100", "page": "1"}
    if sort != "best-fit":
        fields.update(sort=sort, order="desc")
    payload = _github_json("search/repositories", fields)
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > 100:
        raise AgentError("github_response", "GitHub search did not return a bounded items array.")
    total = payload.get("total_count")
    incomplete = payload.get("incomplete_results")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0 or not isinstance(incomplete, bool):
        raise AgentError("github_response", "GitHub returned invalid search completeness metadata.")
    candidates = [_repository(item) for item in items]
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)")}
    star_column = "starred" if "starred" in columns else "0 AS starred"
    placeholders = ",".join("?" for _ in candidates)
    known = {str(row["full_name"]).casefold(): bool(row["starred"])
             for row in conn.execute(
                 f"SELECT full_name, {star_column} FROM repos WHERE lower(full_name) IN ({placeholders})",
                 [repo["full_name"].casefold() for repo in candidates],
             )} if candidates else {}
    results = []
    seen: set[str] = set()
    for position, repo in enumerate(candidates, 1):
        key = repo["full_name"].casefold()
        if key in seen:
            continue
        seen.add(key)
        in_catalog = key in known
        if in_catalog and not include_saved:
            continue
        repo.update(in_catalog=in_catalog, starred=known.get(key, False),
                    github_rank=position, match_basis="GitHub keyword search; suitability unverified")
        results.append(repo)
        if len(results) == limit:
            break
    return {"query": query, "effective_query": effective_query, "sort": sort,
            "results": results, "total_count": total, "incomplete_results": incomplete,
            "candidates_examined": len(items), "candidate_limit": 100,
            "more_candidates_available": total > len(items), "fetched_at": db.now_utc()}


def fetch_public_repository(full_name: str) -> dict[str, Any]:
    validate_repository_name(full_name)
    repo = _repository(_github_json(f"repos/{full_name}"))
    if repo["full_name"].casefold() != full_name.casefold():
        raise AgentError("repository_renamed", f"Repository now resolves to {repo['full_name']}; add that name explicitly.")
    return repo


def import_repository(conn: sqlite3.Connection, repo: dict[str, Any]) -> dict[str, Any]:
    name = repo["full_name"]
    existing = conn.execute("SELECT full_name FROM repos WHERE lower(full_name) = lower(?)", (name,)).fetchone()
    if existing:
        return {"full_name": existing["full_name"], "status": "already_saved", "github_star_changed": False}
    owner, short_name = name.split("/", 1)
    conn.execute(
        "INSERT INTO repos (full_name, owner, repo, url, description, language, stars, last_pushed, archived, starred) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (name, owner, short_name, repo["url"], repo.get("description"), repo.get("language"),
         repo.get("stars"), repo.get("last_pushed"), int(repo["archived"])),
    )
    return {"full_name": name, "status": "added", "github_star_changed": False}
