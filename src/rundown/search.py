"""Deterministic, read-only search over a Rundown catalog."""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import sqlite3
from typing import Any, Collection

from .agent_io import AgentError, validate_limit


_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_MAX_QUERY_CHARS = 500
_MAX_QUERY_TOKENS = 12
_MAX_FIELD_CHARS = 20_000
_MAX_REPOSITORIES = 20_000
_MAX_TOKENS_PER_FIELD = 400
_MAX_TOKENS_PER_REPOSITORY = 4_000
_MAX_CANDIDATE_CHECKS_PER_TERM = 128
_MAX_FUZZY_COMPARISONS_PER_REPOSITORY = 128
_MAX_FUZZY_COMPARISONS_PER_SEARCH = 50_000
_EXCERPT_CHARS = 220

_FIELD_WEIGHTS = {
    "full_name": 10.0,
    "repo": 9.0,
    "description": 6.0,
    "tags": 6.0,
    "language": 4.0,
    "category": 4.0,
    "notes": 5.0,
    "host_notes": 5.0,
    "hook": 5.0,
    "who_for": 5.0,
    "problem": 5.0,
    "why_now": 5.0,
    "demo_path": 4.0,
    "research": 3.0,
}


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


def _tokens(value: str, *, limit: int = 2500) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(value[:_MAX_FIELD_CHARS])][
        :limit
    ]


def _token_similarity(
    query: str,
    candidate: str,
    repo_fuzzy_budget: list[int],
    search_fuzzy_budget: list[int],
) -> tuple[float, bool]:
    if query == candidate:
        return 1.0, False
    if candidate.startswith(query) and len(query) >= 2:
        return 0.84 + 0.12 * (len(query) / len(candidate)), False
    if len(query) >= 3 and query in candidate:
        return 0.76, False
    if min(len(query), len(candidate)) >= 4 and min(len(query), len(candidate)) / max(len(query), len(candidate)) >= 0.65:
        if repo_fuzzy_budget[0] == 0 or search_fuzzy_budget[0] == 0:
            return 0.0, True
        repo_fuzzy_budget[0] -= 1
        search_fuzzy_budget[0] -= 1
        ratio = SequenceMatcher(None, query, candidate, autojunk=False).ratio()
        if ratio >= 0.72:
            return ratio * 0.72, False
    return 0.0, False


def _token_index(
    fields: dict[str, str],
) -> tuple[dict[str, str], dict[str, list[str]], bool]:
    """Map each bounded token to its highest-weight source field."""
    index: dict[str, str] = {}
    buckets: dict[str, list[str]] = {}
    capped = False
    for field, text in fields.items():
        tokens = _tokens(text, limit=_MAX_TOKENS_PER_FIELD + 1)
        if len(tokens) > _MAX_TOKENS_PER_FIELD:
            capped = True
        for token in tokens[:_MAX_TOKENS_PER_FIELD]:
            existing = index.get(token)
            if existing is not None:
                if _FIELD_WEIGHTS[field] > _FIELD_WEIGHTS[existing]:
                    index[token] = field
                continue
            if len(index) >= _MAX_TOKENS_PER_REPOSITORY:
                capped = True
                continue
            index[token] = field
            buckets.setdefault(token[0], []).append(token)
    return index, buckets, capped


def _excerpt(text: str, terms: list[str]) -> str:
    clean = " ".join(text.split())
    folded = clean.casefold()
    positions = [folded.find(term) for term in terms]
    found = [position for position in positions if position >= 0]
    center = min(found) if found else 0
    start = max(0, center - 60)
    end = min(len(clean), start + _EXCERPT_CHARS)
    prefix = "…" if start else ""
    suffix = "…" if end < len(clean) else ""
    return f"{prefix}{clean[start:end].strip()}{suffix}"


def _latest_research(
    conn: sqlite3.Connection,
    repo_ids: Collection[int] | None = None,
    *,
    text_cap: int | None = None,
) -> dict[int, sqlite3.Row]:
    columns = _columns(conn, "research_logs")
    required = {"id", "repo_id", "summary", "status"}
    if not required.issubset(columns):
        return {}
    pass_filter = "AND pass_type = 'Repository Understanding'" if "pass_type" in columns else ""
    selected = ["logs.id", "logs.repo_id"]
    selected.append(
        "substr(logs.summary, 1, ?) AS summary" if text_cap is not None else "logs.summary"
    )
    selected.append("logs.timestamp" if "timestamp" in columns else "NULL AS timestamp")
    params_prefix: list[Any] = [text_cap + 1] if text_cap is not None else []
    chunks: list[list[int] | None]
    if repo_ids is None:
        chunks = [None]
    else:
        ids = sorted(set(repo_ids))
        if not ids:
            return {}
        chunks = [ids[index : index + 500] for index in range(0, len(ids), 500)]
    rows: list[sqlite3.Row] = []
    for chunk in chunks:
        id_filter = ""
        params = list(params_prefix)
        if chunk is not None:
            placeholders = ",".join("?" for _ in chunk)
            id_filter = f"AND repo_id IN ({placeholders})"
            params.extend(chunk)
        rows.extend(
            conn.execute(
                f"""
                SELECT {", ".join(selected)} FROM research_logs logs
                JOIN (
                    SELECT repo_id, MAX(id) AS latest_id FROM research_logs
                    WHERE status = 'success' {pass_filter} {id_filter}
                    GROUP BY repo_id
                ) latest ON latest.latest_id = logs.id
                """,
                params,
            ).fetchall()
        )
    return {int(row["repo_id"]): row for row in rows}


def _host_notes(conn: sqlite3.Connection, repo_ids: Collection[int]) -> dict[int, str]:
    if not {"repo_id", "host_notes"}.issubset(_columns(conn, "repo_cards")):
        return {}
    ids = sorted(set(repo_ids))
    notes: dict[int, str] = {}
    for index in range(0, len(ids), 500):
        chunk = ids[index : index + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT repo_id, substr(host_notes, 1, ?) AS host_notes "
            f"FROM repo_cards WHERE repo_id IN ({placeholders})",
            (_MAX_FIELD_CHARS + 1, *chunk),
        )
        notes.update({int(row["repo_id"]): str(row["host_notes"] or "") for row in rows})
    return notes


def _repo_rows(
    conn: sqlite3.Connection,
    columns: set[str],
    *,
    project: str | None,
    include_archived: bool,
) -> tuple[list[sqlite3.Row], bool]:
    text_fields = tuple(
        field for field in _FIELD_WEIGHTS if field not in {"host_notes", "research"}
    )
    scalar_fields = ("id", "stars", "archived", "status")
    selected: list[str] = []
    params: list[Any] = []
    for field in text_fields:
        if field in columns:
            selected.append(f"substr({field}, 1, ?) AS {field}")
            params.append(_MAX_FIELD_CHARS + 1)
        else:
            selected.append(f"NULL AS {field}")
    for field in scalar_fields:
        selected.append(field if field in columns else f"NULL AS {field}")

    where: list[str] = []
    if not include_archived:
        if "archived" in columns:
            where.append("COALESCE(archived, 0) = 0")
        if "status" in columns:
            where.append("COALESCE(status, '') != 'archived'")
    if project is not None:
        if not project.strip():
            raise AgentError("invalid_input", "project must not be blank", 2)
        mapping_columns = _columns(conn, "project_mappings")
        if not {"repo_id", "project_name"}.issubset(mapping_columns):
            return [], False
        where.append(
            "EXISTS (SELECT 1 FROM project_mappings mappings "
            "WHERE mappings.repo_id = repos.id AND mappings.project_name = ?)"
        )
        params.append(project)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(_MAX_REPOSITORIES + 1)
    rows = conn.execute(
        f"SELECT {', '.join(selected)} FROM repos {clause} "
        "ORDER BY full_name COLLATE NOCASE, id LIMIT ?",
        params,
    ).fetchall()
    return rows[:_MAX_REPOSITORIES], len(rows) > _MAX_REPOSITORIES


def search_repositories(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 5,
    project: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Search local metadata, notes, and the latest successful research.

    Matches are lexical and typo tolerant. Research text is generated and therefore
    treated as an unverified match source rather than proof that a constraint is met.
    """
    validate_limit(limit)
    if not isinstance(query, str) or not query.strip():
        raise AgentError("invalid_input", "query must not be blank", 2)
    if len(query) > _MAX_QUERY_CHARS:
        raise AgentError("invalid_input", f"query must be at most {_MAX_QUERY_CHARS} characters", 2)
    query_text = query.strip()
    query_tokens = list(dict.fromkeys(_tokens(query_text, limit=_MAX_QUERY_TOKENS + 1)))
    if not query_tokens:
        raise AgentError("invalid_input", "query must contain searchable words", 2)
    if len(query_tokens) > _MAX_QUERY_TOKENS:
        raise AgentError("invalid_input", f"query must contain at most {_MAX_QUERY_TOKENS} unique words", 2)

    repo_columns = _columns(conn, "repos")
    if not {"id", "full_name"}.issubset(repo_columns):
        return _response(query_text, project, include_archived, limit, [], scanned=0, capped=False)

    rows, corpus_capped = _repo_rows(
        conn, repo_columns, project=project, include_archived=include_archived
    )
    candidate_ids = [int(row["id"]) for row in rows]
    research = _latest_research(conn, candidate_ids, text_cap=_MAX_FIELD_CHARS)
    notes = _host_notes(conn, candidate_ids)
    results: list[dict[str, Any]] = []
    search_fuzzy_budget = [_MAX_FUZZY_COMPARISONS_PER_SEARCH]
    matching_budget_exhausted = False
    truncated_text_fields = 0
    truncated_token_indexes = 0
    for row in rows:
        data = dict(row)
        repo_id = int(data["id"])
        archived = bool(data.get("archived", 0)) or data.get("status") == "archived"
        latest = research.get(repo_id)
        raw_fields = {
            "full_name": str(data.get("full_name") or ""),
            "repo": str(data.get("repo") or ""),
            "description": str(data.get("description") or ""),
            "tags": str(data.get("tags") or ""),
            "language": str(data.get("language") or ""),
            "category": str(data.get("category") or ""),
            "notes": str(data.get("notes") or ""),
            "hook": str(data.get("hook") or ""),
            "who_for": str(data.get("who_for") or ""),
            "problem": str(data.get("problem") or ""),
            "why_now": str(data.get("why_now") or ""),
            "demo_path": str(data.get("demo_path") or ""),
            "host_notes": notes.get(repo_id, ""),
            "research": str(_value(latest, "summary", "")) if latest else "",
        }
        indexed_text_truncated = sorted(
            name for name, text in raw_fields.items() if len(text) > _MAX_FIELD_CHARS
        )
        truncated_text_fields += len(indexed_text_truncated)
        fields = {name: text[:_MAX_FIELD_CHARS] for name, text in raw_fields.items()}
        token_index, token_buckets, token_cap_reached = _token_index(fields)
        truncated_token_indexes += int(token_cap_reached)
        matched_fields: set[str] = set()
        matched_terms: dict[str, list[str]] = {}
        score = 0.0
        repo_fuzzy_budget = [_MAX_FUZZY_COMPARISONS_PER_REPOSITORY]
        for term in query_tokens:
            best = (0.0, "", "")
            exact_field = token_index.get(term)
            if exact_field is not None:
                best = (_FIELD_WEIGHTS[exact_field], exact_field, term)
            else:
                bucket = token_buckets.get(term[0], [])
                candidates = bucket[:_MAX_CANDIDATE_CHECKS_PER_TERM]
                if len(bucket) > _MAX_CANDIDATE_CHECKS_PER_TERM:
                    matching_budget_exhausted = True
                for actual in candidates:
                    name = token_index[actual]
                    similarity, exhausted = _token_similarity(
                        term, actual, repo_fuzzy_budget, search_fuzzy_budget
                    )
                    matching_budget_exhausted = matching_budget_exhausted or exhausted
                    weighted = similarity * _FIELD_WEIGHTS[name]
                    if weighted > best[0]:
                        best = (weighted, name, actual)
            if best[0] == 0:
                break
            score += best[0]
            matched_fields.add(best[1])
            matched_terms.setdefault(best[1], []).append(best[2])
        else:
            folded_query = query_text.casefold()
            for name in tuple(matched_fields):
                text = fields[name]
                if folded_query in text.casefold():
                    score += _FIELD_WEIGHTS[name] * 0.5
                    matched_fields.add(name)
                    matched_terms.setdefault(name, []).extend(query_tokens)
            if query_text.casefold() == fields["full_name"].casefold():
                score += 100.0
            kinds = {
                name: ("generated" if name == "research" else "human" if name in {"notes", "host_notes", "hook", "who_for", "problem", "why_now", "demo_path"} else "metadata")
                for name in sorted(matched_fields)
            }
            excerpts = {
                name: _excerpt(fields[name], matched_terms.get(name, query_tokens))
                for name in sorted(matched_fields)
                if fields[name]
            }
            results.append(
                {
                    "full_name": data["full_name"],
                    "description": data.get("description"),
                    "language": data.get("language"),
                    "stars": data.get("stars"),
                    "archived": archived,
                    "score": round(score, 3),
                    "matched_fields": sorted(matched_fields),
                    "match_sources": [
                        {"field": name, "source_kind": kinds[name]}
                        for name in sorted(matched_fields)
                    ],
                    "excerpts": excerpts,
                    "indexed_text_truncated": indexed_text_truncated,
                    "indexed_token_cap_reached": token_cap_reached,
                    "research_timestamp": _value(latest, "timestamp") if latest else None,
                    "generated_matches_unverified": "research" in matched_fields,
                }
            )

    results.sort(key=lambda item: (-item["score"], str(item["full_name"]).casefold()))
    return _response(
        query_text, project, include_archived, limit, results[:limit],
        scanned=len(rows), capped=corpus_capped,
        matching_budget_exhausted=matching_budget_exhausted,
        truncated_text_fields=truncated_text_fields,
        truncated_token_indexes=truncated_token_indexes,
    )


def _response(
    query: str,
    project: str | None,
    include_archived: bool,
    limit: int,
    results: list[dict[str, Any]],
    *,
    scanned: int,
    capped: bool,
    matching_budget_exhausted: bool = False,
    truncated_text_fields: int = 0,
    truncated_token_indexes: int = 0,
) -> dict[str, Any]:
    return {
        "query": query,
        "method": {
            "name": "local_lexical_typo",
            "semantic": False,
            "order_independent": True,
            "generated_research_is_unverified": True,
            "limits": {
                "max_query_chars": _MAX_QUERY_CHARS,
                "max_query_tokens": _MAX_QUERY_TOKENS,
                "max_repositories": _MAX_REPOSITORIES,
                "max_chars_per_field": _MAX_FIELD_CHARS,
                "max_tokens_per_field": _MAX_TOKENS_PER_FIELD,
                "max_tokens_per_repository": _MAX_TOKENS_PER_REPOSITORY,
                "max_candidate_checks_per_term": _MAX_CANDIDATE_CHECKS_PER_TERM,
                "max_fuzzy_comparisons_per_repository": _MAX_FUZZY_COMPARISONS_PER_REPOSITORY,
                "max_fuzzy_comparisons_per_search": _MAX_FUZZY_COMPARISONS_PER_SEARCH,
            },
        },
        "corpus": {
            "repositories_scanned": scanned,
            "candidate_cap_reached": capped,
            "matching_budget_exhausted": matching_budget_exhausted,
            "text_fields_truncated": truncated_text_fields,
            "token_indexes_truncated": truncated_token_indexes,
        },
        "filters": {"project": project, "include_archived": include_archived},
        "limit": limit,
        "count": len(results),
        "results": results,
    }
