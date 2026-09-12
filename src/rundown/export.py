"""Export presentation-ready Markdown for repositories marked for presentation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

from . import db


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


def generate_export(rows: list[sqlite3.Row]) -> str:
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
        lines.append(format_repo_markdown(row))
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
) -> int:
    """Export presentation-ready Markdown to a file. Returns count of exported repos."""
    rows = list(iter_export_rows(conn, decisions))
    content = generate_export(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return len(rows)
