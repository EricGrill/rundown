from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def wiki_path_for(wiki_root: Path, owner: str, repo: str) -> Path:
    return wiki_root / "repos" / f"{owner}__{repo}.md"


def render_template(row: sqlite3.Row, local_path: str = "") -> str:
    return f"""# {row['full_name']}

## Metadata

GitHub: {row['url']}
Local Path: {local_path}
Status: {row['status'] or ''}
Decision: {row['decision'] or ''}
Tags: {row['tags'] or ''}
Language: {row['language'] or ''}
Stars: {row['stars'] or ''}
Last Star Sync: {row['last_star_sync'] or ''}
Last Clone Sync: {row['last_clone_sync'] or ''}
Last Research Pass: {row['last_research_sync'] or ''}
Last Execution: {row['last_execution_sync'] or ''}

## What It Does

{row['description'] or ''}

## Why I Starred It

## Install / Run Notes

## Agent Research Notes

## Execution Results

## Relevance Score

## Project Fit

## Related

## Open Questions

## Decision Log
"""


def ensure_wiki_page(wiki_root: Path, row: sqlite3.Row) -> Path:
    path = wiki_path_for(wiki_root, row["owner"], row["repo"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(render_template(row, row["local_path"] or ""), encoding="utf-8")
    return path


def append_section(path: Path, heading: str, body: str) -> None:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n## {heading}: {timestamp}\n\n{body.rstrip()}\n")
