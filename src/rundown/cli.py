from __future__ import annotations

from dataclasses import asdict
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import startup
from .demo import demo_environment
from .doctor import DoctorReport, run_doctor
from .config import load_config
from .tui import RundownApp
from . import search_cli, inspect_cli, discovery_cli, memory_cli, automation_cli, scheduler_cli, research_cli, catalog_cli
from .cli_support import _config


app = typer.Typer(help="Browse → Read → Prepare → Export. Run rd with no command to open Rundown.", invoke_without_command=True)
console = Console()
search_cli.register(app)
inspect_cli.register(app)
discovery_cli.register(app)
memory_cli.register(app)
automation_cli.register(app)
scheduler_cli.register(app)
research_cli.register(app)
catalog_cli.register(app)


@app.callback()
def callback(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option("--config", "-c", help="Configuration for the default app launch.")] = None,
) -> None:
    """Open Rundown, or use an explicit command for automation."""
    if ctx.invoked_subcommand is not None:
        return
    if not startup.interactive_terminal():
        typer.echo(ctx.get_help())
        return
    try:
        problem = startup.launch(load_config(config))
    except (OSError, ValueError, sqlite3.Error) as exc:
        typer.echo(f"Could not open Rundown: {exc}. Run `rd doctor` to check your setup.", err=True)
        raise typer.Exit(1) from exc
    if problem:
        typer.echo(problem)
        raise typer.Exit(1)


@app.command("tui")
def tui(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    cfg = _config(config)
    RundownApp(cfg).run()


@app.command("demo")
def demo() -> None:
    """Explore sample research offline in a temporary, isolated catalog."""
    with demo_environment() as environment:
        RundownApp(environment.config, fetch_starred=environment.fetch_starred, demo_mode=True).run()


@app.command("doctor")
def doctor(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print structured diagnostics.")] = False,
    fix: Annotated[bool, typer.Option("--fix", help="Offer to run each available fix, such as `gh auth login`.")] = False,
) -> None:
    """Check installation, configuration, authentication and local catalog health."""
    if fix and json_output:
        raise typer.BadParameter("--fix is interactive and cannot be combined with --json.")
    report = run_doctor(config)
    if json_output:
        typer.echo(json.dumps({**asdict(report), "healthy": report.healthy}, indent=2))
        raise typer.Exit(report.exit_code)
    _print_doctor(report)
    if fix:
        fixes = [(item.name, item.fix_command) for item in report.checks
                 if item.status != "ok" and item.fix_command]
        if not fixes:
            console.print("No automatic fixes are available. Follow the Fix column above.")
        elif not startup.interactive_terminal():
            raise typer.BadParameter("--fix needs an interactive terminal.")
        else:
            ran = False
            for name, fix_command in fixes:
                if typer.confirm(f"Run `{' '.join(fix_command)}` to fix {name}?", default=True):
                    _run_fix(fix_command)
                    ran = True
            if ran:
                console.print("Checking again.")
                report = run_doctor(config)
                _print_doctor(report)
    raise typer.Exit(report.exit_code)


def _run_fix(command: tuple[str, ...]) -> None:
    subprocess.run(list(command), check=False)


def _print_doctor(report: DoctorReport) -> None:
    table = Table("Check", "Status", "Details", "Fix")
    for item in report.checks:
        table.add_row(Text(item.name), Text(item.status), Text(item.message), Text(item.fix or ""))
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
