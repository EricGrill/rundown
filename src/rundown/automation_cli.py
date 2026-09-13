"""Noninteractive automation commands and local MCP transport."""
from pathlib import Path
from typing import Annotated

import typer

from .agent_io import AgentError, emit, load_agent_config, read_catalog, run_command
from .automation import project_digest, refresh_repositories


def register(app: typer.Typer) -> None:
    @app.command('digest')
    def digest(
        project: Annotated[str | None, typer.Option()] = None,
        limit: Annotated[int, typer.Option()] = 5,
        stale_days: Annotated[int, typer.Option()] = 30,
        json_output: Annotated[bool, typer.Option('--json')] = False,
        config: Annotated[Path | None, typer.Option('--config', '-c')] = None,
    ) -> None:
        """Read a local digest ranked by saved project fit and relevance."""
        def operation():
            with read_catalog(load_agent_config(config)) as conn:
                return project_digest(conn, project=project, limit=limit, stale_days=stale_days)
        run_command(operation, json_output)

    @app.command('refresh')
    def refresh(
        project: Annotated[str | None, typer.Option()] = None,
        limit: Annotated[int, typer.Option()] = 10,
        stale_days: Annotated[int, typer.Option()] = 30,
        dry_run: Annotated[bool, typer.Option()] = False,
        json_output: Annotated[bool, typer.Option('--json')] = False,
        config: Annotated[Path | None, typer.Option('--config', '-c')] = None,
    ) -> None:
        """Research at most 50 missing/stale repos; use --dry-run to preview locally."""
        def operation():
            result = refresh_repositories(load_agent_config(config), limit=limit, project=project,
                                          stale_days=stale_days, dry_run=dry_run)
            if result['status'] in {'cancelled', 'partial_failure'}:
                error = AgentError(result['status'], 'See per-repository outcomes in data.results.',
                                   130 if result['cancelled'] else 1)
                emit(result, json_output, error)
                raise typer.Exit(error.exit_code)
            return result
        run_command(operation, json_output)

    @app.command('mcp')
    def mcp(config: Annotated[Path | None, typer.Option('--config', '-c')] = None) -> None:
        """Serve local read-only tools over MCP stdio (stdout is protocol only)."""
        from .mcp_server import serve
        try:
            cfg = load_agent_config(config)
        except (AgentError, ValueError, OSError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        serve(cfg)
