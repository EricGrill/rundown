"""CLI adapters for explicit public discovery and catalog import."""
from pathlib import Path
from typing import Annotated

import typer

from . import db
from .agent_io import load_agent_config, read_catalog, run_command
from .discovery import discover_repositories, fetch_public_repository, import_repository


def register(app: typer.Typer) -> None:
    @app.command("discover")
    def discover(
        query: str,
        limit: Annotated[int, typer.Option()] = 5,
        sort: Annotated[str, typer.Option()] = "best-fit",
        include_saved: Annotated[bool, typer.Option()] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Search public GitHub metadata; does not save or research results."""
        def operation():
            with read_catalog(load_agent_config(config)) as conn:
                return discover_repositories(conn, query, limit=limit, sort=sort, include_saved=include_saved)
        run_command(operation, json_output)

    @app.command("add")
    def add(
        full_name: str,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Import public metadata locally without starring on GitHub."""
        def operation():
            cfg = load_agent_config(config)
            # Validate/fetch before creating any local files.
            repo = fetch_public_repository(full_name)
            with db.session(cfg.database_path) as conn:
                db.init_db(conn)
                return import_repository(conn, repo)
        run_command(operation, json_output)
