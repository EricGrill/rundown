"""Shared presentation overrides for cards, editors, and exports."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from typing import Any, Literal

from .cards import CardRecord


PRESENTATION_FIELDS = (
    "hook",
    "who_for",
    "problem",
    "why_now",
    "demo_path",
    "host_notes",
    "repository_notes",
)

FIELD_LABELS = {
    "hook": "Hook",
    "who_for": "Who it is for",
    "problem": "Problem",
    "why_now": "Why now",
    "demo_path": "Demo path",
    "host_notes": "Host notes",
    "repository_notes": "Repository notes",
}

FIELD_SECTIONS: dict[str, str] = {
    "hook": "hook",
    "who_for": "use_cases",
    "problem": "use_cases",
    "why_now": "why_now",
    "demo_path": "demo",
}

SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "hook": ("hook",),
    "use_cases": ("who_for", "problem"),
    "why_now": ("why_now",),
    "demo": ("demo_path",),
}


@dataclass(frozen=True)
class PresentationDraft:
    hook: str = ""
    who_for: str = ""
    problem: str = ""
    why_now: str = ""
    demo_path: str = ""
    host_notes: str = ""
    repository_notes: str = ""


@dataclass(frozen=True)
class EffectiveSection:
    content: str
    overridden_fields: frozenset[str]
    source: Literal["human", "generated"]


@dataclass(frozen=True)
class HumanField:
    name: str
    label: str
    value: str


def row_value(row: object | None, key: str) -> Any:
    """Read dict-like and sqlite rows without requiring one concrete row type."""
    if row is None:
        return None
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None


def draft_from_rows(repo_row: object, card_row: object | None = None) -> PresentationDraft:
    """Load all existing human-authored card fields into one editable value."""
    return PresentationDraft(
        hook=str(row_value(repo_row, "hook") or ""),
        who_for=str(row_value(repo_row, "who_for") or ""),
        problem=str(row_value(repo_row, "problem") or ""),
        why_now=str(row_value(repo_row, "why_now") or ""),
        demo_path=str(row_value(repo_row, "demo_path") or ""),
        host_notes=str(row_value(card_row, "host_notes") or ""),
        repository_notes=str(row_value(repo_row, "notes") or ""),
    )


def save_presentation_draft(
    conn: sqlite3.Connection,
    repo_id: int,
    draft: PresentationDraft,
) -> None:
    """Atomically save every human-authored presentation field."""
    savepoint = "rundown_presentation_edit"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        updated = conn.execute(
            """
            UPDATE repos
            SET hook = ?, who_for = ?, problem = ?, why_now = ?, demo_path = ?, notes = ?
            WHERE id = ?
            """,
            (
                draft.hook if draft.hook.strip() else None,
                draft.who_for if draft.who_for.strip() else None,
                draft.problem if draft.problem.strip() else None,
                draft.why_now if draft.why_now.strip() else None,
                draft.demo_path if draft.demo_path.strip() else None,
                draft.repository_notes if draft.repository_notes.strip() else None,
                repo_id,
            ),
        )
        if updated.rowcount != 1:
            raise LookupError(f"Repository id {repo_id} does not exist")
        conn.execute(
            """
            INSERT INTO repo_cards (repo_id, host_notes)
            VALUES (?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET host_notes = excluded.host_notes
            """,
            (repo_id, draft.host_notes),
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def manual_section(row: object, section_id: str) -> tuple[str | None, frozenset[str]]:
    """Return the legacy manual override for a generated card section."""
    present = frozenset(
        field for field in SECTION_FIELDS.get(section_id, ()) if row_value(row, field)
    )
    if not present:
        return None, present
    if section_id == "hook":
        return str(row_value(row, "hook")), present
    if section_id == "use_cases":
        parts = []
        if row_value(row, "who_for"):
            parts.append(f"**For:** {row_value(row, 'who_for')}")
        if row_value(row, "problem"):
            parts.append(f"**Problem:** {row_value(row, 'problem')}")
        return "\n\n".join(parts), present
    if section_id == "why_now":
        return str(row_value(row, "why_now")), present
    if section_id == "demo":
        return f"Demo: {row_value(row, 'demo_path')}", present
    return None, frozenset()


def effective_section(row: object, record: CardRecord, section_id: str) -> EffectiveSection:
    """Resolve a section consistently for TUI reading and Markdown exports."""
    manual, overridden = manual_section(row, section_id)
    if manual is not None:
        return EffectiveSection(manual, overridden, "human")
    return EffectiveSection(record.sections.get(section_id, "").strip(), frozenset(), "generated")


def supplemental_human_fields(
    row: object,
    rendered_fields: set[str] | frozenset[str],
) -> tuple[HumanField, ...]:
    """Keep overrides visible when their mapped section is omitted by a template."""
    result = []
    for name in ("hook", "who_for", "problem", "why_now", "demo_path"):
        value = row_value(row, name)
        if value and name not in rendered_fields:
            result.append(HumanField(name, FIELD_LABELS[name], str(value)))
    return tuple(result)


def replace_draft_field(draft: PresentationDraft, name: str, value: str) -> PresentationDraft:
    """Return a draft with one validated field replaced."""
    if name not in PRESENTATION_FIELDS:
        raise ValueError(f"Unknown presentation field: {name}")
    values = {field.name: getattr(draft, field.name) for field in fields(PresentationDraft)}
    values[name] = value
    return PresentationDraft(**values)
