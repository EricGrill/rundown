from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from . import db
from .cards import CardRecord, SECTION_TITLES
from .config import AppConfig, GithubSettings, PathSettings, ResearchSettings


@dataclass(frozen=True)
class DemoEnvironment:
    """An isolated catalog and offline star source for the demo TUI."""

    config: AppConfig
    fetch_starred: Callable[[], list[db.RepoInput]]


def _fixture_rows() -> list[dict[str, Any]]:
    resource = files("rundown.demo_data").joinpath("repositories.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("demo repository fixture must be a JSON array")
    return value


def _repo_input(row: dict[str, Any]) -> db.RepoInput:
    full_name = str(row["full_name"])
    owner, repo = full_name.split("/", 1)
    return db.RepoInput(
        full_name=full_name,
        owner=owner,
        repo=repo,
        url=str(row["url"]),
        description=row.get("description"),
        language=row.get("language"),
        stars=row.get("stars"),
        forks=row.get("forks"),
        open_issues=row.get("open_issues"),
        last_pushed=row.get("last_pushed"),
        starred_at=row.get("starred_at"),
        archived=bool(row.get("archived", False)),
    )


def load_demo_repositories() -> list[db.RepoInput]:
    """Return fresh repository values from the bundled public fixture."""

    return [_repo_input(row) for row in _fixture_rows()]


def _seed_demo(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for row, repo in zip(rows, map(_repo_input, rows), strict=True):
            repo_id = db.upsert_repo(conn, repo)
            db.update_repo(
                conn,
                repo.full_name,
                category=row.get("category"),
                decision=row.get("decision"),
                relevance_score=int(row.get("relevance_score", 0)),
                status="researched",
                last_research_sync="2026-09-01T12:00:00+00:00",
            )
            raw_sections = row["sections"]
            sections = {
                section_id: str(raw_sections.get(section_id, ""))
                for section_id in SECTION_TITLES
            }
            record = CardRecord(sections=sections)
            db.insert_research_log(
                conn,
                repo_id,
                "Repository Understanding",
                record.to_markdown(),
                "success",
                agent_name="rundown-demo",
                source_fingerprint="bundled-demo-fixture-v1",
                card_json=record.to_json(),
            )
            db.save_repo_card(
                conn,
                repo_id,
                view=str(row.get("card_view", "host")),
                host_notes=str(row.get("host_notes", "")),
            )


@contextmanager
def demo_environment() -> Iterator[DemoEnvironment]:
    """Yield a fully seeded, temporary environment that never uses user data."""

    rows = _fixture_rows()
    repositories = [_repo_input(row) for row in rows]
    with TemporaryDirectory(prefix="rundown-demo-") as directory:
        root = Path(directory)
        config = AppConfig(
            root=root,
            paths=PathSettings(
                repo_root=Path("repos"),
                wiki_root=Path("wiki"),
                database=Path("data/demo.sqlite"),
                logs=Path("logs"),
                exports=Path("exports"),
            ),
            github=GithubSettings(use_gh_cli=False, include_private=False),
            research=ResearchSettings(provider="auto"),
        )
        config.ensure_directories()
        _seed_demo(config, rows)
        yield DemoEnvironment(config=config, fetch_starred=lambda: list(repositories))
