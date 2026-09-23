"""CLI commands for researching repositories: single, batch, and history."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
import json
import sqlite3
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Annotated

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

from . import db, history, research_workflow
from .agent_io import AgentError, emit, load_agent_config, read_catalog, run_command
from .cli_support import _config, _conn
from .processes import OperationCancelled

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("research")
    def research_repo(
        full_name: str,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
        json_output: Annotated[bool, typer.Option("--json", help="Print structured research outcome.")] = False,
        force: Annotated[bool, typer.Option("--force", help="Refresh even when saved research matches.")] = False,
    ) -> None:
        def operation():
            cfg = load_agent_config(config)
            with read_catalog(cfg) as conn:
                if db.get_repo(conn, full_name) is None:
                    raise AgentError("not_found", f"Unknown repository: {full_name}")
            cfg.ensure_directories()
            cancel_event = Event()
            try:
                with _conn(cfg) as conn:
                    db.init_db(conn)
                    if force:
                        status, summary = research_workflow.research_repository(
                            cfg, conn, full_name, cancel_event=cancel_event, force=True
                        )
                    else:
                        status, summary = research_workflow.research_repository(
                            cfg, conn, full_name, cancel_event=cancel_event
                        )
            except (KeyboardInterrupt, OperationCancelled) as exc:
                cancel_event.set()
                raise AgentError("cancelled", "Research interrupted.", 130) from exc
            result = {"full_name": full_name, "status": status, "summary": summary[:20000],
                      "summary_truncated": len(summary) > 20000}
            if status not in {"success", "cached"}:
                error = AgentError("cancelled" if status == "cancelled" else "research_failed",
                                   summary[:2000], 130 if status == "cancelled" else 1)
                emit(result, json_output, error)
                raise typer.Exit(error.exit_code)
            if not json_output:
                console.print(f"Research status: {status}")
                console.print(summary)
            return result
        if json_output:
            run_command(operation, True)
        else:
            try:
                operation()
            except (AgentError, OSError, ValueError, sqlite3.Error) as exc:
                error = exc if isinstance(exc, AgentError) else AgentError("operation_failed", str(exc))
                emit(None, False, error)
                raise typer.Exit(error.exit_code) from exc

    @app.command("research-missing")
    def research_missing(
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
        limit: Annotated[
            int | None,
            typer.Option("--limit", min=1, help="Research at most this many repositories."),
        ] = None,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="List repositories without cloning or using the configured AI provider."),
        ] = False,
    ) -> None:
        """Research active repositories with no saved success using the configured AI."""
        cfg = _config(config)
        with _conn(cfg) as conn:
            db.init_db(conn)
            rows = sorted(db.list_repos(conn), key=lambda row: row["full_name"])
            rows.sort(key=lambda row: row["starred_at"] or "", reverse=True)
            researched_repo_ids = db.latest_successful_research_by_repo(conn)
            missing = [row for row in rows if row["id"] not in researched_repo_ids]

        selected = missing[:limit] if limit is not None else missing
        if dry_run:
            if not selected:
                console.print("No repositories need research.")
                return
            console.print(f"Would research {len(selected)} repositories:")
            for row in selected:
                console.print(row["full_name"])
            return

        if not selected:
            console.print("No repositories need research.")
            return

        saved_count = len(rows) - len(missing)
        console.print(Panel(
            f"{len(selected)} queued · {saved_count} already researched · "
            f"{len(missing) - len(selected)} outside this batch\n"
            "Newest first · clones automatically · Ctrl+C stops; completed research stays saved",
            title="Research missing", border_style="cyan",
        ))
        overall = Progress(
            TextColumn("Processed"), BarColumn(), MofNCompleteColumn(),
            TimeElapsedColumn(), TextColumn("{task.fields[results]}", markup=False),
            console=console, auto_refresh=False,
        )
        stage = Progress(
            SpinnerColumn(), TextColumn("{task.description}", markup=False),
            TimeElapsedColumn(), console=console, auto_refresh=False,
        )
        batch_task = overall.add_task("Batch", total=len(selected), results="0 saved · 0 failed")
        stage_task = stage.add_task("Starting…", total=None)
        display = (
            Live(Group(overall, stage), console=console, refresh_per_second=4, transient=True)
            if console.is_terminal else nullcontext()
        )
        succeeded = failed = 0
        interrupted = False
        cancel_event = Event()
        started = monotonic()
        try:
            with display:
                for position, row in enumerate(selected, start=1):
                    full_name = row["full_name"]
                    stage.reset(stage_task, description=f"Preparing clone · {full_name}")
                    if not console.is_terminal:
                        console.print(f"[{position}/{len(selected)}] Preparing clone {full_name}…", markup=False)
                    try:
                        with _conn(cfg) as conn:
                            db.init_db(conn)
                            def report_stage(state: str, _message: str) -> None:
                                if state == "researching":
                                    stage.reset(stage_task, description=f"Researching · {full_name}")
                                    if not console.is_terminal:
                                        console.print(f"[{position}/{len(selected)}] Researching {full_name}…", markup=False)
                            status, summary = research_workflow.research_repository(
                                cfg,
                                conn,
                                full_name,
                                cancel_event=cancel_event,
                                on_stage=report_stage,
                            )
                    except Exception as exc:
                        status, summary = "failed", str(exc)

                    if status in {"success", "cached"}:
                        succeeded += 1
                        message = (
                            f"Reused saved research for {full_name}." if status == "cached"
                            else f"Researched {full_name}."
                        )
                        console.print(f"✓ {message}", style="green", markup=False, highlight=False)
                    else:
                        failed += 1
                        console.print(
                            f"✗ Research failed for {full_name}: {summary}",
                            style="red", markup=False, highlight=False,
                        )
                    overall.update(
                        batch_task, advance=1,
                        results=f"{succeeded} saved · {failed} failed",
                    )
        except KeyboardInterrupt:
            cancel_event.set()
            interrupted = True

        heading = "Research interrupted" if interrupted else "Research complete"
        elapsed = timedelta(seconds=int(monotonic() - started))
        summary_text = (
            f"{heading}. Succeeded: {succeeded}. Failed: {failed}.\n"
            f"Processed: {succeeded + failed}/{len(selected)} · Elapsed: {elapsed}"
        )
        if interrupted or failed:
            summary_text += "\nRun research-missing again to retry unfinished repositories."
        console.print(Panel(
            Text(summary_text), border_style="yellow" if interrupted else "red" if failed else "green",
        ))
        if interrupted:
            raise typer.Exit(code=130)
        if failed:
            raise typer.Exit(code=1)

    @app.command("research-history")
    def research_history(
        full_name: str,
        config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
        json_output: Annotated[bool, typer.Option("--json", help="Include stored provenance, two recent failures and two successful reports.")] = False,
    ) -> None:
        """Show research sources and changes since the previous successful report."""
        cfg = _config(config)
        with _conn(cfg) as conn:
            db.init_db(conn)
            row = db.get_repo(conn, full_name)
            if row is None:
                raise typer.BadParameter(f"Unknown repository: {full_name}")
            reports = [dict(report) for report in history.research_history(conn, row["id"], include_failed=True)]
        if json_output:
            typer.echo(json.dumps([dict(report) for report in reports], indent=2))
        else:
            console.print(Text(history.format_research_history(reports)))
