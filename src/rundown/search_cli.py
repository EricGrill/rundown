"""CLI adapter for local agent search."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .agent_io import load_agent_config, read_catalog, run_command
from .search import search_repositories


def register(app: typer.Typer) -> None:
    @app.command("search")
    def search_command(
        query: str,
        limit: Annotated[int, typer.Option("--limit")] = 5,
        project: Annotated[str | None, typer.Option("--project")] = None,
        include_archived: Annotated[bool, typer.Option("--include-archived")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Search saved repositories, notes, and cached research locally."""

        def operation():
            cfg = load_agent_config(config)
            with read_catalog(cfg) as conn:
                return search_repositories(
                    conn,
                    query,
                    limit=limit,
                    project=project,
                    include_archived=include_archived,
                )

        run_command(operation, json_output)
