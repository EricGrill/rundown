from __future__ import annotations

import json
import sqlite3
from difflib import unified_diff
from typing import Any, Mapping, Sequence

from . import db
from .cards import SECTION_TITLES, record_from_saved


def research_history(
    conn: sqlite3.Connection,
    repo_id: int,
    *,
    limit: int = 2,
) -> list[sqlite3.Row]:
    return db.latest_successful_research_history(conn, repo_id, limit=limit)


def parse_provenance(row: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        raw = row["provenance_json"]
    except (KeyError, IndexError):
        return None
    if not raw:
        return None
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def compare_research_rows(
    newer: Mapping[str, Any],
    older: Mapping[str, Any],
) -> dict[str, tuple[str, ...]] | None:
    new_record = record_from_saved(str(newer["summary"] or ""), newer["card_json"])
    old_record = record_from_saved(str(older["summary"] or ""), older["card_json"])
    if not new_record.sections and not old_record.sections:
        return None

    added: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    for section_id in SECTION_TITLES:
        new_text = new_record.sections.get(section_id, "").strip()
        old_text = old_record.sections.get(section_id, "").strip()
        if new_text == old_text:
            continue
        if new_text and not old_text:
            added.append(section_id)
        elif old_text and not new_text:
            removed.append(section_id)
        else:
            updated.append(section_id)
    return {
        "added": tuple(added),
        "updated": tuple(updated),
        "removed": tuple(removed),
    }


def _titles(section_ids: Sequence[str]) -> str:
    return ", ".join(SECTION_TITLES[section_id] for section_id in section_ids)


def _context_file_label(item: Mapping[str, Any]) -> str | None:
    path = item.get("path")
    if not path:
        return None
    details: list[str] = []
    sha256 = item.get("sha256")
    if sha256:
        details.append(f"sha256 {str(sha256)[:12]}…")
    captured_chars = item.get("captured_chars")
    if isinstance(captured_chars, int):
        details.append(f"{captured_chars} chars")
    truncated = item.get("truncated")
    if truncated is True:
        details.append("truncated")
    elif truncated is False:
        details.append("complete")
    return f"{path} ({', '.join(details)})" if details else str(path)


def _section_diffs(
    newer: Mapping[str, Any],
    older: Mapping[str, Any],
    changes: Mapping[str, Sequence[str]],
) -> list[str]:
    new_record = record_from_saved(str(newer["summary"] or ""), newer["card_json"])
    old_record = record_from_saved(str(older["summary"] or ""), older["card_json"])
    blocks: list[str] = []
    changed_ids = [
        section_id
        for section_id in SECTION_TITLES
        if any(section_id in changes[label] for label in ("added", "updated", "removed"))
    ]
    for section_id in changed_ids:
        title = SECTION_TITLES[section_id]
        before = old_record.sections.get(section_id, "").strip().splitlines()
        after = new_record.sections.get(section_id, "").strip().splitlines()
        diff = "\n".join(
            unified_diff(
                before,
                after,
                fromfile=f"previous/{title}",
                tofile=f"latest/{title}",
                lineterm="",
            )
        )
        if diff:
            blocks.extend(["", diff])
    return blocks


def format_research_history(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "Research history: unavailable."

    latest = rows[0]
    provenance = parse_provenance(latest)
    lines = [f"Latest research: {latest['timestamp'] or 'unknown time'}"]
    if provenance is None:
        lines.append("Provenance: unknown (legacy research).")
    else:
        provider = provenance.get("provider") or "unknown"
        commit = provenance.get("git_commit") or "unknown"
        if commit != "unknown":
            commit = str(commit)[:12]
        dirty = provenance.get("working_tree_dirty")
        worktree = (
            "dirty; captured file hashes may differ from the commit"
            if dirty is True
            else "clean"
            if dirty is False
            else "unknown"
        )
        files = provenance.get("context_files")
        file_names = (
            [
                label
                for item in files
                if isinstance(item, dict)
                if (label := _context_file_label(item)) is not None
            ]
            if isinstance(files, list)
            else []
        )
        lines.extend(
            [
                f"Provider: {provider}",
                f"Generated: {provenance.get('generated_at') or latest['timestamp'] or 'unknown'}",
                f"Repository commit: {commit}",
                f"Working tree: {worktree}",
                f"Prompt version: {provenance.get('prompt_version') or 'unknown'}",
                f"Card schema version: {provenance.get('schema_version') or 'unknown'}",
                "Context files: " + (", ".join(file_names) if file_names else "none captured"),
                "Source references: generated from supplied repository context; not independently verified.",
            ]
        )

    if len(rows) < 2:
        lines.append("Changes: no earlier successful research to compare.")
        return "\n".join(lines)

    changes = compare_research_rows(rows[0], rows[1])
    if changes is None:
        lines.append("Changes: unknown for legacy unstructured research.")
        return "\n".join(lines)
    if not any(changes.values()):
        lines.append("Changes: no section changes.")
        return "\n".join(lines)
    for label in ("added", "updated", "removed"):
        if changes[label]:
            lines.append(f"{label.title()} sections: {_titles(changes[label])}")
    lines.extend(_section_diffs(rows[0], rows[1], changes))
    return "\n".join(lines)
