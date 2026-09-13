"""CLI adapter for cached repository inspection."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .agent_io import load_agent_config, read_catalog, run_command
from .inspection import inspect_repository


def register(app: typer.Typer) -> None:
    @app.command("inspect")
    def inspect_command(
        full_name: str,
        full: Annotated[bool, typer.Option("--full")] = False,
        stale_days: Annotated[int, typer.Option("--stale-days")] = 30,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Read cached metadata, research, notes, and project fit as one packet."""

        def operation():
            cfg = load_agent_config(config)
            with read_catalog(cfg) as conn:
                return inspect_repository(conn, full_name, full=full, stale_days=stale_days)

        run_command(operation, json_output)
