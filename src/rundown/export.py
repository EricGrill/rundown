"""Export presentation-ready Markdown for repositories marked for presentation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

from . import db
from .cards import SECTION_TITLES, CardRecord, record_from_saved, section_preview
from .config import AppConfig, CardSettings
from .preferences import effective_cards


CARD_FIELDS = ("hook", "who_for", "problem", "why_now", "demo_path", "notes")
EXPORT_DECISIONS = ("present", "shortlist")


def format_repo_markdown(row: sqlite3.Row) -> str:
    """Format a single repository as presentation-ready Markdown."""
    lines = [f"## {row['full_name']}", ""]

    if row["description"]:
        lines.extend([row["description"], ""])

    if row["hook"]:
        lines.extend([f"**Hook:** {row['hook']}", ""])

    if row["who_for"]:
        lines.extend([f"**For:** {row['who_for']}", ""])

    if row["problem"]:
        lines.extend([f"**Problem:** {row['problem']}", ""])

    if row["why_now"]:
        lines.extend([f"**Why now:** {row['why_now']}", ""])

    metrics = []
    if row["stars"]:
        metrics.append(f"{row['stars']:,} stars")
    if row["language"]:
        metrics.append(row["language"])
    if row["category"]:
        metrics.append(row["category"])
    if metrics:
        lines.extend([" · ".join(metrics), ""])

    lines.append(f"GitHub: {row['url']}")

    if row["demo_path"]:
        lines.append(f"Demo: {row['demo_path']}")

    if row["notes"]:
        lines.extend(["", f"*{row['notes']}*"])

    lines.append("")
    return "\n".join(lines)


def _value(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _manual_section(row, section_id: str) -> str | None:
    if section_id == "hook" and _value(row, "hook"):
        return str(row["hook"])
    if section_id == "use_cases":
        parts = []
        if _value(row, "who_for"):
            parts.append(f"**For:** {row['who_for']}")
        if _value(row, "problem"):
            parts.append(f"**Problem:** {row['problem']}")
        return "\n\n".join(parts) or None
    if section_id == "why_now" and _value(row, "why_now"):
        return str(row["why_now"])
    if section_id == "demo" and _value(row, "demo_path"):
        return f"Demo: {row['demo_path']}"
    return None


def _manual_fields_for_section(row, section_id: str) -> set[str]:
    fields = {
        "hook": ("hook",),
        "use_cases": ("who_for", "problem"),
        "why_now": ("why_now",),
        "demo": ("demo_path",),
    }.get(section_id, ())
    return {field for field in fields if _value(row, field)}


def _section_content(content: str, word_limit: int) -> str:
    preview = section_preview(content, word_limit)
    if preview == content.strip():
        return preview
    return "\n".join(
        [
            preview,
            "",
            "<details>",
            "<summary>Read full section</summary>",
            "",
            content.strip(),
            "",
            "</details>",
        ]
    )


def format_card_markdown(
    row: sqlite3.Row,
    record: CardRecord,
    *,
    view: str,
    settings: CardSettings,
    host_notes: str = "",
) -> str:
    """Format one repository using a selected card template."""
    if view not in {"host", "research"}:
        raise ValueError("Export view must be 'host' or 'research'")
    template = settings.host if view == "host" else settings.research
    lines = [f"## {row['full_name']}", ""]
    if row["description"]:
        lines.extend([str(row["description"]), ""])

    metrics = []
    if row["stars"]:
        metrics.append(f"{row['stars']:,} stars")
    if row["language"]:
        metrics.append(str(row["language"]))
    if row["category"]:
        metrics.append(str(row["category"]))
    if metrics:
        lines.extend([" · ".join(metrics), ""])
    lines.extend([f"GitHub: {row['url']}", ""])

    rendered_sections = 0
    rendered_manual_fields: set[str] = set()
    for section_id in template.sections:
        content = _manual_section(row, section_id)
        if content is not None:
            rendered_manual_fields.update(_manual_fields_for_section(row, section_id))
        else:
            content = record.sections.get(section_id, "").strip()
        if not content:
            continue
        rendered = _section_content(content, template.word_limit)
        lines.extend([f"### {SECTION_TITLES[section_id]}", "", rendered, ""])
        rendered_sections += 1

    if record.legacy_text.strip():
        heading = "Original Research Report" if rendered_sections else "Full Research"
        lines.extend([f"### {heading}", "", record.legacy_text.strip(), ""])
    supplemental = []
    labels = {
        "hook": "**Hook:**",
        "who_for": "**For:**",
        "problem": "**Problem:**",
        "why_now": "**Why now:**",
        "demo_path": "Demo:",
    }
    for field, label in labels.items():
        value = _value(row, field)
        if value and field not in rendered_manual_fields:
            supplemental.append(f"{label} {value}")
    if supplemental:
        lines.extend(["### Presentation Details", "", "\n\n".join(supplemental), ""])
    if host_notes.strip():
        lines.extend(["### Host Notes", "", host_notes.strip(), ""])
    if _value(row, "notes"):
        lines.extend(["### Repository Notes", "", str(row["notes"]).strip(), ""])
    return "\n".join(lines)


def generate_export(
    rows: list[sqlite3.Row],
    *,
    research_by_repo: dict[int, sqlite3.Row] | None = None,
    cards_by_repo: dict[int, sqlite3.Row] | None = None,
    views_by_repo: dict[int, str] | None = None,
    settings_by_repo: dict[int, CardSettings] | None = None,
) -> str:
    """Generate complete export Markdown for multiple repositories."""
    if not rows:
        return "# Export\n\nNo repositories marked for presentation.\n"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Rundown Export",
        "",
        f"*Generated {timestamp}*",
        "",
        f"**{len(rows)} repositories**",
        "",
        "---",
        "",
    ]

    for row in rows:
        repo_id = int(row["id"]) if _value(row, "id") is not None else -1
        saved_research = (research_by_repo or {}).get(repo_id)
        settings = (settings_by_repo or {}).get(repo_id)
        if settings is None:
            lines.append(format_repo_markdown(row))
        else:
            saved_card = (cards_by_repo or {}).get(repo_id)
            view = (views_by_repo or {}).get(repo_id, settings.default_view)
            record = (
                record_from_saved(
                    str(saved_research["summary"] or ""),
                    _value(saved_research, "card_json"),
                )
                if saved_research is not None
                else CardRecord()
            )
            host_notes = str(_value(saved_card, "host_notes") or "")
            lines.append(
                format_card_markdown(
                    row,
                    record,
                    view=view,
                    settings=settings,
                    host_notes=host_notes,
                )
            )
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def iter_export_rows(
    conn: sqlite3.Connection,
    decisions: list[str] | None = None,
) -> Iterator[sqlite3.Row]:
    """Yield rows eligible for export."""
    if decisions is None:
        decisions = list(EXPORT_DECISIONS)
    for row in db.list_repos_by_decision(conn, decisions):
        yield row


def export_to_file(
    conn: sqlite3.Connection,
    output_path: Path,
    decisions: list[str] | None = None,
    *,
    config: AppConfig | None = None,
    view: str | None = None,
) -> int:
    """Export presentation-ready Markdown to a file. Returns count of exported repos."""
    rows = list(iter_export_rows(conn, decisions))
    if view is not None and view not in {"host", "research"}:
        raise ValueError("Export view must be 'host' or 'research'")
    if config is None:
        content = generate_export(rows)
    else:
        latest = db.latest_successful_research_by_repo(conn)
        cards_by_repo: dict[int, sqlite3.Row] = {}
        views_by_repo: dict[int, str] = {}
        settings_by_repo: dict[int, CardSettings] = {}
        for row in rows:
            repo_id = int(row["id"])
            settings = effective_cards(conn, config.cards, repo_id)
            settings_by_repo[repo_id] = settings
            saved_card = db.get_repo_card(conn, repo_id)
            if saved_card is not None:
                cards_by_repo[repo_id] = saved_card
            views_by_repo[repo_id] = (
                view
                or (_value(saved_card, "view") if saved_card is not None else None)
                or settings.default_view
            )
        content = generate_export(
            rows,
            research_by_repo=latest,
            cards_by_repo=cards_by_repo,
            views_by_repo=views_by_repo,
            settings_by_repo=settings_by_repo,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return len(rows)
