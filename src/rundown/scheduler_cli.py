"""Scheduled research commands with machine-readable outcomes."""
from pathlib import Path
import signal
from threading import Event
from typing import Annotated

import typer

from .agent_io import AgentError, emit, load_agent_config, run_command
from .scheduler import run_scheduled_research, scheduler_status
from .scheduler_service import disable_service, enable_service, service_status


def register(app: typer.Typer) -> None:
    schedule = typer.Typer(help="Automatically research starred repositories.", no_args_is_help=True)
    app.add_typer(schedule, name="schedule")

    @schedule.command("run")
    def run(
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Run one bounded batch, or preview the local queue with --dry-run."""
        def operation():
            cfg = load_agent_config(config)
            cancelled = Event()
            previous = signal.signal(signal.SIGTERM, lambda signum, frame: cancelled.set())
            try:
                result = run_scheduled_research(cfg, dry_run=dry_run, cancel_event=cancelled)
            finally:
                signal.signal(signal.SIGTERM, previous)
            status = result["status"]
            if status in {"partial_failure", "failed", "cancelled", "sync_failed"}:
                if not json_output:
                    emit(result, False)
                error = AgentError(status, "Scheduled research did not complete successfully; see data for outcomes.", 130 if status == "cancelled" else 1)
                emit(result, json_output, error)
                raise typer.Exit(error.exit_code)
            return result
        run_command(operation, json_output)

    @schedule.command("enable")
    def enable(
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Install the current catalog's macOS user scheduler and run at login."""
        run_command(lambda: enable_service(load_agent_config(config), config), json_output)

    @schedule.command("disable")
    def disable(
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Stop this catalog's scheduler while preserving research and catalog data."""
        run_command(lambda: disable_service(load_agent_config(config)), json_output)

    @schedule.command("status")
    def status(
        json_output: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    ) -> None:
        """Show this catalog's queue and installed service status."""
        def operation():
            cfg = load_agent_config(config)
            return {**scheduler_status(cfg), "service": service_status(cfg)}
        run_command(operation, json_output)
