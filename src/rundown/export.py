"""Export presentation-ready Markdown for repositories marked for presentation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import os
from tempfile import NamedTemporaryFile
from typing import Iterator

from . import db
from .cards import SECTION_TITLES, CardRecord, record_from_saved, section_preview
from .config import AppConfig, CardSettings
from .preferences import effective_cards
from .presentation import effective_section, row_value, supplemental_human_fields


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
        effective = effective_section(row, record, section_id)
        content = effective.content
        rendered_manual_fields.update(effective.overridden_fields)
        if not content:
            continue
        rendered = _section_content(content, template.word_limit)
        lines.extend([f"### {SECTION_TITLES[section_id]}", "", rendered, ""])
        rendered_sections += 1

    if record.legacy_text.strip():
        heading = "Original Research Report" if rendered_sections else "Full Research"
        lines.extend([f"### {heading}", "", record.legacy_text.strip(), ""])
    labels = {
        "hook": "**Hook:**",
        "who_for": "**For:**",
        "problem": "**Problem:**",
        "why_now": "**Why now:**",
        "demo_path": "Demo:",
    }
    supplemental = [
        f"{labels[field.name]} {field.value}"
        for field in supplemental_human_fields(row, rendered_manual_fields)
    ]
    if supplemental:
        lines.extend(["### Presentation Details", "", "\n\n".join(supplemental), ""])
    if host_notes.strip():
        lines.extend(["### Host Notes", "", host_notes.strip(), ""])
    if row_value(row, "notes"):
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
        repo_id = int(row["id"]) if row_value(row, "id") is not None else -1
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
                    row_value(saved_research, "card_json"),
                )
                if saved_research is not None
                else CardRecord()
            )
            host_notes = str(row_value(saved_card, "host_notes") or "")
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


def build_export(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    *,
    config: AppConfig | None = None,
    view: str | None = None,
) -> str:
    """Build an export for explicit rows without choosing or writing a path."""
    if view is not None and view not in {"host", "research"}:
        raise ValueError("Export view must be 'host' or 'research'")
    if config is None:
        return generate_export(rows)

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
        saved_view = row_value(saved_card, "view")
        views_by_repo[repo_id] = view or (saved_view if saved_view in {"host", "research"} else settings.default_view)
    return generate_export(
        rows,
        research_by_repo=latest,
        cards_by_repo=cards_by_repo,
        views_by_repo=views_by_repo,
        settings_by_repo=settings_by_repo,
    )


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
    content = build_export(conn, rows, config=config, view=view)
    write_export_file(output_path, content, overwrite=True,
                      protected_path=config.database_path if config else None)
    return len(rows)


def write_export_file(path: Path, content: str, *, overwrite: bool = False,
                      allowed_root: Path | None = None, protected_path: Path | None = None) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Choose a regular file path; export does not replace symbolic links.")
    resolved = path.resolve()
    if allowed_root is not None and not resolved.is_relative_to(allowed_root.resolve()):
        raise ValueError("Demo exports must stay inside the temporary demo directory.")
    if protected_path is not None and resolved == protected_path.resolve():
        raise ValueError("Choose an export file, not the Rundown database.")
    if path.exists() and not path.is_file():
        raise ValueError("Choose a file path, not a directory.")
    if path.exists() and not overwrite:
        raise FileExistsError("This file exists. Choose a new name or enable Replace existing file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        if overwrite:
            os.replace(temporary, path)
        else:
            # Install the complete file atomically, without replacing a file
            # another writer created after validation.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
