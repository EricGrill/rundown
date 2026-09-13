"""Build bounded, read-only repository handoff packets for agents."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Mapping

from .agent_io import AgentError
from .memory import recall_decisions
from .cards import CardRecord, record_from_saved


_COMPACT_TEXT_CHARS = 1_200
_COMPACT_SECTION_CHARS = 800
_COMPACT_TOTAL_TEXT_CHARS = 50_000
_FULL_TOTAL_TEXT_CHARS = 1_000_000
_MAX_STALE_DAYS = 3650
_MAX_MAPPINGS = 100
_MAX_JSON_DEPTH = 20
_MAX_JSON_ITEMS = 2_000
_COMPACT_PROVENANCE_CHARS = 10_000
_FULL_PROVENANCE_CHARS = 100_000


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bounded(text: Any, limit: int, path: str, truncated: list[str], *, full: bool) -> str:
    value = "" if text is None else str(text)
    if full or len(value) <= limit:
        return value
    truncated.append(path)
    return value[: limit - 1].rstrip() + "…"


def _enforce_total_text_cap(value: Any, budget: list[int], path: str, truncated: list[str]) -> Any:
    if isinstance(value, str):
        if len(value) <= budget[0]:
            budget[0] -= len(value)
            return value
        available = max(0, budget[0] - 1)
        budget[0] = 0
        truncated.append(path)
        return value[:available].rstrip() + ("…" if available else "")
    if isinstance(value, dict):
        return {
            key: _enforce_total_text_cap(item, budget, f"{path}.{key}" if path else str(key), truncated)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _enforce_total_text_cap(item, budget, f"{path}.{index}", truncated)
            for index, item in enumerate(value)
        ]
    return value


def _selected_text(column: str, columns: set[str]) -> str:
    return f"substr({column}, 1, ?) AS {column}" if column in columns else f"NULL AS {column}"


def _repo(conn: sqlite3.Connection, full_name: str, text_limit: int) -> sqlite3.Row | None:
    columns = _columns(conn, "repos")
    text_fields = (
        "full_name", "owner", "repo", "description", "url", "language", "last_pushed",
        "starred_at", "category", "tags", "decision", "score_reason", "status", "notes",
        "hook", "who_for", "problem", "why_now", "demo_path",
    )
    scalar_fields = ("id", "stars", "forks", "open_issues", "archived", "starred", "relevance_score")
    selected = [_selected_text(field, columns) for field in text_fields]
    selected.extend(field if field in columns else f"NULL AS {field}" for field in scalar_fields)
    params: list[Any] = [text_limit + 1 for field in text_fields if field in columns]
    params.append(full_name)
    return conn.execute(
        f"SELECT {', '.join(selected)} FROM repos WHERE full_name = ? LIMIT 1", params
    ).fetchone()


def _latest_research(
    conn: sqlite3.Connection,
    repo_id: int,
    *,
    text_limit: int,
) -> sqlite3.Row | None:
    columns = _columns(conn, "research_logs")
    if not {"id", "repo_id", "status", "summary"}.issubset(columns):
        return None
    pass_filter = "AND pass_type = 'Repository Understanding'" if "pass_type" in columns else ""
    selected = ["id", "repo_id"]
    params: list[Any] = []
    for field, limit in (
        ("summary", text_limit),
        ("card_json", _FULL_TOTAL_TEXT_CHARS),
        (
            "provenance_json",
            _FULL_PROVENANCE_CHARS
            if text_limit == _FULL_TOTAL_TEXT_CHARS
            else _COMPACT_PROVENANCE_CHARS,
        ),
        ("timestamp", _COMPACT_TEXT_CHARS),
        ("agent_name", _COMPACT_TEXT_CHARS),
        ("pass_type", _COMPACT_TEXT_CHARS),
    ):
        selected.append(_selected_text(field, columns))
        if field in columns:
            params.append(limit + 1)
    params.append(repo_id)
    return conn.execute(
        f"""
        SELECT {", ".join(selected)} FROM research_logs
        WHERE repo_id = ? AND status = 'success' {pass_filter}
        ORDER BY id DESC LIMIT 1
        """,
        params,
    ).fetchone()


def _card(
    conn: sqlite3.Connection, repo_id: int, *, text_limit: int
) -> Mapping[str, Any] | None:
    columns = _columns(conn, "repo_cards")
    if "repo_id" not in columns:
        return None
    selected = ["repo_id"]
    params: list[Any] = []
    if "host_notes" in columns:
        selected.append("substr(host_notes, 1, ?) AS host_notes")
        params.append(text_limit + 1)
    else:
        selected.append("NULL AS host_notes")
    params.append(repo_id)
    row = conn.execute(
        f"SELECT {', '.join(selected)} FROM repo_cards WHERE repo_id = ?", params
    ).fetchone()
    return dict(row) if row else None


def _mappings(
    conn: sqlite3.Connection,
    repo_id: int,
    *,
    full: bool,
    truncated: list[str],
) -> list[dict[str, Any]]:
    columns = _columns(conn, "project_mappings")
    if not {"repo_id", "project_name"}.issubset(columns):
        return []
    project_limit = 1_000 if full else 200
    reason_limit = 8_000 if full else 300
    selected = ["substr(project_name, 1, ?) AS project_name"]
    params: list[Any] = [project_limit + 1]
    selected.append("fit_score" if "fit_score" in columns else "NULL AS fit_score")
    if "reason" in columns:
        selected.append("substr(reason, 1, ?) AS reason")
        params.append(reason_limit + 1)
    else:
        selected.append("NULL AS reason")
    params.extend((repo_id, _MAX_MAPPINGS + 1))
    rows = conn.execute(
        f"SELECT {', '.join(selected)} FROM project_mappings WHERE repo_id = ? "
        "ORDER BY project_name COLLATE NOCASE LIMIT ?",
        params,
    ).fetchall()
    if len(rows) > _MAX_MAPPINGS:
        truncated.append("project_mappings")
    return [
        {
            "project": _bounded(
                _value(row, "project_name"), project_limit,
                f"project_mappings.{index}.project", truncated, full=False,
            ),
            "fit_score": _value(row, "fit_score"),
            "reason": _bounded(
                _value(row, "reason", ""),
                reason_limit,
                f"project_mappings.{index}.reason",
                truncated,
                full=False,
            ),
        }
        for index, row in enumerate(rows[:_MAX_MAPPINGS])
    ]


def _safe_provenance(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not raw:
        return None, None
    try:
        value = json.loads(str(raw))
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return None, "Saved provenance JSON is invalid and was omitted."
    if not isinstance(value, dict):
        return None, "Saved provenance JSON is not an object and was omitted."
    stack: list[tuple[Any, int]] = [(value, 0)]
    items = 0
    while stack:
        item, depth = stack.pop()
        items += 1
        if depth > _MAX_JSON_DEPTH or items > _MAX_JSON_ITEMS:
            return None, "Saved provenance JSON exceeds safe structure limits and was omitted."
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value, None


def _staleness(repo: Mapping[str, Any], research: Any, stale_days: int) -> dict[str, Any]:
    if research is None:
        return {
            "state": "missing",
            "stale": False,
            "threshold_days": stale_days,
            "reasons": ["No successful saved research."],
        }
    researched_at = _timestamp(_value(research, "timestamp"))
    raw_pushed_at = repo.get("last_pushed")
    pushed_at = _timestamp(raw_pushed_at)
    reasons: list[str] = []
    if researched_at is None:
        reasons.append("Research timestamp is missing or invalid.")
    else:
        if datetime.now(timezone.utc) - researched_at > timedelta(days=stale_days):
            reasons.append(f"Research is older than {stale_days} days.")
        if pushed_at is not None and pushed_at > researched_at:
            reasons.append("Repository activity is newer than the saved research.")
        if isinstance(raw_pushed_at, str) and raw_pushed_at.strip() and pushed_at is None:
            reasons.append("Repository activity timestamp is invalid; freshness cannot be determined.")
    return {
        "state": "stale" if reasons else "current",
        "stale": bool(reasons),
        "threshold_days": stale_days,
        "researched_at": _value(research, "timestamp"),
        "repository_last_pushed": repo.get("last_pushed"),
        "reasons": reasons,
    }


def inspect_repository(
    conn: sqlite3.Connection,
    full_name: str,
    *,
    full: bool = False,
    stale_days: int = 30,
) -> dict[str, Any]:
    """Return one cached repository packet without filesystem or provider access."""
    if not isinstance(full_name, str) or not full_name.strip():
        raise AgentError("invalid_input", "repository name must not be blank", 2)
    if isinstance(stale_days, bool) or not isinstance(stale_days, int) or not 1 <= stale_days <= _MAX_STALE_DAYS:
        raise AgentError("invalid_input", f"stale_days must be between 1 and {_MAX_STALE_DAYS}", 2)
    if not {"id", "full_name"}.issubset(_columns(conn, "repos")):
        raise AgentError("not_found", f"Repository is not in the catalog: {full_name}")
    text_limit = _FULL_TOTAL_TEXT_CHARS if full else _COMPACT_TEXT_CHARS
    row = _repo(conn, full_name.strip(), text_limit)
    if row is None:
        raise AgentError("not_found", f"Repository is not in the catalog: {full_name.strip()}")

    repo = dict(row)
    repo_id = int(repo["id"])
    research = _latest_research(conn, repo_id, text_limit=text_limit)
    card = _card(conn, repo_id, text_limit=text_limit)
    truncated: list[str] = []

    metadata_fields = (
        "full_name", "owner", "repo", "description", "url", "language", "stars",
        "forks", "open_issues", "last_pushed", "starred_at", "archived", "starred",
        "category", "tags", "decision", "relevance_score", "score_reason", "status",
    )
    metadata = {"source_kind": "metadata", **{key: repo.get(key) for key in metadata_fields if key in repo}}
    for key in ("description", "tags", "score_reason"):
        if key in metadata:
            metadata[key] = _bounded(metadata[key], _COMPACT_TEXT_CHARS, f"metadata.{key}", truncated, full=full)

    generated: dict[str, Any]
    source_references: dict[str, Any]
    provenance: dict[str, Any] | None = None
    diagnostics: list[str] = []
    if research is None:
        generated = {
            "source_kind": "generated",
            "available": False,
            "record": None,
            "provenance": None,
            "diagnostics": [],
        }
        source_references = {
            "source_kind": "generated",
            "verification": "unavailable",
            "notice": "No successful generated research is saved.",
            "items": [],
        }
    else:
        summary = str(_value(research, "summary", ""))
        saved_card = _value(research, "card_json")
        card_source = str(saved_card) if saved_card else None
        if card_source and len(card_source) > _FULL_TOTAL_TEXT_CHARS:
            truncated.append("generated_research.card_json")
            diagnostics.append("Saved card JSON exceeds the 1000000-character parsing limit; used summary fallback.")
            card_source = None
        try:
            record = record_from_saved(summary, card_source)
            if card_source and record.legacy_text:
                diagnostics.append("Saved card JSON is invalid; used summary fallback.")
        except (RecursionError, TypeError, ValueError):
            diagnostics.append("Saved card JSON is invalid; used summary fallback.")
            try:
                record = record_from_saved(summary, None)
            except (RecursionError, TypeError, ValueError):
                diagnostics.append("Saved summary is invalid structured data; preserved as legacy text.")
                record = CardRecord(legacy_text=summary)
        if record.legacy_text:
            research_record: dict[str, Any] = {
                "format": "legacy_markdown",
                "text": _bounded(record.legacy_text, _COMPACT_TEXT_CHARS, "generated_research.record.text", truncated, full=full),
            }
        else:
            research_record = {
                "format": "structured",
                "schema_version": record.schema_version,
                "sections": {
                    key: _bounded(value, _COMPACT_SECTION_CHARS, f"generated_research.record.sections.{key}", truncated, full=full)
                    for key, value in record.sections.items()
                    if value.strip()
                },
            }
        raw_provenance = _value(research, "provenance_json")
        provenance_limit = (
            _FULL_PROVENANCE_CHARS if full else _COMPACT_PROVENANCE_CHARS
        )
        if raw_provenance and len(str(raw_provenance)) > provenance_limit:
            truncated.append("generated_research.provenance")
            diagnostics.append("Saved provenance JSON exceeded the inspection text limit and was omitted.")
            provenance = None
        else:
            provenance, provenance_diagnostic = _safe_provenance(raw_provenance)
            if provenance_diagnostic:
                diagnostics.append(provenance_diagnostic)
        generated = {
            "source_kind": "generated",
            "available": True,
            "timestamp": _value(research, "timestamp"),
            "agent_name": _value(research, "agent_name"),
            "pass_type": _value(research, "pass_type"),
            "record": research_record,
            "provenance": provenance,
            "diagnostics": diagnostics,
        }
        raw_references = provenance.get("context_files", []) if provenance else []
        references = raw_references if isinstance(raw_references, list) else []
        source_references = {
            "source_kind": "generated",
            "verification": "unverified",
            "notice": "Generated research references supplied repository context; Rundown did not independently verify its claims.",
            "items": references,
        }

    human_notes = {
        "source_kind": "human",
        "repository_notes": _bounded(repo.get("notes"), _COMPACT_TEXT_CHARS, "human_notes.repository_notes", truncated, full=full),
        "host_notes": _bounded((card or {}).get("host_notes"), _COMPACT_TEXT_CHARS, "human_notes.host_notes", truncated, full=full),
        "card_overrides": {
            key: _bounded(repo.get(key), _COMPACT_TEXT_CHARS, f"human_notes.card_overrides.{key}", truncated, full=full)
            for key in ("hook", "who_for", "problem", "why_now", "demo_path")
            if repo.get(key)
        },
    }
    mappings = _mappings(
        conn, repo_id, full=full, truncated=truncated
    )
    missing: list[str] = []
    if not repo.get("description"):
        missing.append("metadata.description")
    if not repo.get("language"):
        missing.append("metadata.language")
    if research is None:
        missing.append("generated_research")
    elif provenance is None:
        missing.append("generated_research.provenance")
    if not source_references["items"]:
        missing.append("source_references.items")
    if not human_notes["repository_notes"] and not human_notes["host_notes"] and not human_notes["card_overrides"]:
        missing.append("human_notes")

    packet = {
        "repository": repo["full_name"],
        "mode": "full" if full else "compact",
        "metadata": metadata,
        "staleness": _staleness(repo, research, stale_days),
        "missing_information": missing,
        "human_notes": human_notes,
        "generated_research": generated,
        "source_references": source_references,
        "project_mappings": mappings,
        "decision_memory": recall_decisions(conn, full_name=full_name.strip(), limit=20 if full else 5),
    }
    total_limit = _FULL_TOTAL_TEXT_CHARS if full else _COMPACT_TOTAL_TEXT_CHARS
    packet = _enforce_total_text_cap(packet, [total_limit], "", truncated)
    packet["truncation"] = {
        "truncated": bool(truncated),
        "fields": list(dict.fromkeys(truncated)),
        "max_total_text_chars": total_limit,
        "hint": (
            "Run inspect with --full for more saved text; full output is capped at 1000000 text characters."
            if truncated and not full
            else "Full output reached its 1000000-character safety cap."
            if truncated
            else None
        ),
    }
    return packet
