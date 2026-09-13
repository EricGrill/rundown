"""CLI commands for append-only repository decision memory."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import db
from .agent_io import load_agent_config, read_catalog, run_command
from .memory import recall_decisions, remember_repository


def register(app: typer.Typer) -> None:
    @app.command("remember")
    def remember_command(
        full_name: str,
        project: Annotated[str, typer.Option("--project")],
        decision: Annotated[str, typer.Option("--decision")],
        reason: Annotated[str, typer.Option("--reason")],
        evidence: Annotated[str, typer.Option("--evidence")] = "",
        actor: Annotated[str, typer.Option("--actor")] = "user",
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Append a project decision and caller-provided evidence."""

        def operation() -> dict[str, object]:
            cfg = load_agent_config(config)
            with db.session(cfg.database_path) as conn:
                db.init_db(conn)
                return remember_repository(
                    conn,
                    full_name,
                    project=project,
                    decision=decision,
                    reason=reason,
                    evidence=evidence,
                    actor=actor,
                )

        run_command(operation, json_output)

    @app.command("recall")
    def recall_command(
        project: Annotated[str | None, typer.Option("--project")] = None,
        full_name: Annotated[str | None, typer.Option("--repo")] = None,
        limit: Annotated[int, typer.Option("--limit")] = 20,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Recall recent decisions without changing the local catalog."""

        def operation() -> dict[str, object]:
            cfg = load_agent_config(config)
            with read_catalog(cfg) as conn:
                return recall_decisions(
                    conn,
                    project=project,
                    full_name=full_name,
                    limit=limit,
                )

        run_command(operation, json_output)
