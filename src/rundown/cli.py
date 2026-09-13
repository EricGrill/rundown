from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
from datetime import timedelta
from enum import Enum
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
from rich.table import Table
from rich.text import Text

from . import categories, db, execution, export, github, history, repo_ops, research_workflow, scoring, wiki
from . import startup
from .demo import demo_environment
from .doctor import run_doctor
from .config import AppConfig, load_config
from .tui import RundownApp


app = typer.Typer(help="Browse → Read → Prepare → Export. Run rd with no command to open Rundown.", invoke_without_command=True)
console = Console()


class RepoDecision(str, Enum):
    archived = "archived"
    rejected = "rejected"
    fork = "fork"
    integrate = "integrate"
    present = "present"
    shortlist = "shortlist"


def _config(config: Path | None) -> AppConfig:
    loaded = load_config(config)
    loaded.ensure_directories()
    return loaded


def _conn(config: AppConfig):
    return db.session(config.database_path)


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


@app.command("sync-stars")
def sync_stars(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    mark_unstarred: Annotated[bool, typer.Option("--mark-unstarred")] = False,
) -> None:
    cfg = _config(config)
    repos = github.fetch_starred(include_private=cfg.github.include_private)
    with _conn(cfg) as conn:
        db.init_db(conn)
        for repo in repos:
            db.upsert_repo(conn, repo)
        unstarred = db.mark_unstarred_missing(conn, {repo.full_name for repo in repos}) if mark_unstarred else 0
        categories.classify_repos(conn)
    console.print(f"Synced {len(repos)} starred repositories. Marked unstarred: {unstarred}.")


@app.command("classify")
def classify(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    force: Annotated[bool, typer.Option("--force", help="Recompute existing categories.")] = False,
) -> None:
    """Classify saved starred repos into five categories locally, without AI calls."""
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        counts = categories.classify_repos(conn, force=force)
    console.print(f"Classified {sum(counts.values())} starred repositories into 5 categories.")
    for category, count in counts.items():
        console.print(f"  {category}: {count}")


@app.command("clone-missing")
def clone_missing(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        cloned, failed = repo_ops.clone_missing(cfg, conn)
    console.print(f"Cloned {cloned} repositories. Failed: {failed}.")


@app.command("update-repos")
def update_repos(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        updated, failed = repo_ops.update_repos(cfg, conn)
    console.print(f"Updated {updated} repositories. Failed: {failed}.")


@app.command("update")
def update_alias(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    update_repos(config)


@app.command("ensure-wiki")
def ensure_wiki(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    cfg = _config(config)
    count = 0
    with _conn(cfg) as conn:
        db.init_db(conn)
        for row in db.list_repos(conn, include_archived=True):
            path = wiki.ensure_wiki_page(cfg.wiki_root, row)
            db.update_repo(conn, row["full_name"], wiki_path=str(path))
            count += 1
    console.print(f"Ensured {count} wiki pages.")


@app.command("wiki")
def wiki_alias(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    ensure_wiki(config)


@app.command("research")
def research_repo(
    full_name: str,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    cfg = _config(config)
    cancel_event = Event()
    try:
        with _conn(cfg) as conn:
            db.init_db(conn)
            status, summary = research_workflow.research_repository(
                cfg, conn, full_name, cancel_event=cancel_event
            )
    except KeyboardInterrupt:
        cancel_event.set()
        console.print("Research interrupted.")
        raise typer.Exit(code=130) from None
    console.print(f"Research status: {status}")
    console.print(summary)


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


@app.command("run")
def run_repo(
    full_name: str,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    execute: Annotated[bool, typer.Option("--execute", help="Run detected safe command instead of dry-run detection.")] = False,
    allow_non_docker: Annotated[
        bool,
        typer.Option(
            "--allow-non-docker",
            help="Permit explicit execution of detected non-Docker commands after reviewing the command.",
        ),
    ] = False,
) -> None:
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        status, notes = execution.run_repo(
            cfg,
            conn,
            full_name,
            execute=execute,
            allow_non_docker=allow_non_docker,
        )
    console.print(f"Execution status: {status}")
    console.print(notes)


@app.command("score")
def score(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        count = scoring.recalculate_scores(cfg, conn)
    console.print(f"Scored {count} repositories.")


@app.command("project-fit")
def project_fit(
    full_name: str,
    project: str,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    fit_score: Annotated[int, typer.Option("--score", min=0, max=100)] = 50,
    reason: Annotated[str, typer.Option("--reason")] = "Manual project fit assignment.",
) -> None:
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        row = db.get_repo(conn, full_name)
        if row is None:
            raise typer.BadParameter(f"Unknown repository: {full_name}")
        db.upsert_project_mapping(conn, row["id"], project, fit_score, reason)
    console.print(f"Mapped {full_name} to {project} with fit score {fit_score}.")


@app.command("mark")
def mark_repo(
    full_name: str,
    decision: Annotated[
        RepoDecision,
        typer.Argument(
            help=(
                "Decision label. 'present' and 'shortlist' mark repos for export. "
                "'fork' and 'integrate' record intent only; "
                "they do not modify the repository on GitHub."
            )
        ),
    ],
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Record an archive, rejection, fork, or integration decision."""
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        if db.get_repo(conn, full_name) is None:
            raise typer.BadParameter(
                f"Unknown repository: {full_name}. Run `rd repos` to list known repositories.",
                param_hint="FULL_NAME",
            )
        db.update_repo(conn, full_name, status=decision.value, decision=decision.value)
    console.print(f"Marked {full_name} as {decision.value}.")


@app.command("repos")
def list_repository_rows(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    include_archived: Annotated[bool, typer.Option("--include-archived")] = False,
) -> None:
    cfg = _config(config)
    table = Table(title="Repositories")
    table.add_column("Name", no_wrap=True)
    for column in ["Score", "Status", "Language", "Updated", "Decision", "Decay"]:
        table.add_column(column)
    table.add_column("Projects", no_wrap=True)
    with _conn(cfg) as conn:
        db.init_db(conn)
        if project:
            rows = conn.execute(
                """
                SELECT repos.*, GROUP_CONCAT(project_mappings.project_name, ', ') AS projects
                FROM repos
                JOIN project_mappings ON project_mappings.repo_id = repos.id
                WHERE project_mappings.project_name = ?
                GROUP BY repos.id
                ORDER BY project_mappings.fit_score DESC, relevance_score DESC
                """,
                (project,),
            ).fetchall()
        else:
            rows = db.list_repos(conn, include_archived=include_archived)
    for row in rows:
        table.add_row(
            row["full_name"],
            str(row["relevance_score"] or 0),
            row["status"] or "",
            row["language"] or "",
            row["last_pushed"] or "",
            row["decision"] or "",
            str(row["decay_score"] or 0),
            row["projects"] or "",
        )
    console.print(table)


@app.command("decay")
def decay(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    score(config)


@app.command("rediscover")
def rediscover(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    cfg = _config(config)
    table = Table(title="Rediscovery Queue")
    table.add_column("Name", no_wrap=True)
    table.add_column("Score", justify="right")
    table.add_column("Decay", justify="right")
    table.add_column("Status")
    table.add_column("Decision")
    with _conn(cfg) as conn:
        db.init_db(conn)
        rows = conn.execute(
            """
            SELECT * FROM repos
            WHERE archived = 0 AND (decay_score >= 40 OR decision IS NULL OR decision = '')
            ORDER BY decay_score DESC, relevance_score DESC, full_name ASC
            """
        ).fetchall()
    for row in rows:
        table.add_row(
            row["full_name"],
            str(row["relevance_score"] or 0),
            str(row["decay_score"] or 0),
            row["status"] or "",
            row["decision"] or "",
        )
    console.print(table)


@app.command("card")
def set_card(
    full_name: str,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    hook: Annotated[str | None, typer.Option("--hook", help="One-line pitch for the repository.")] = None,
    who_for: Annotated[str | None, typer.Option("--who-for", help="Target audience.")] = None,
    problem: Annotated[str | None, typer.Option("--problem", help="Problem it solves.")] = None,
    why_now: Annotated[str | None, typer.Option("--why-now", help="Why it's relevant now.")] = None,
    demo_path: Annotated[str | None, typer.Option("--demo-path", help="Path to demo file or URL.")] = None,
    notes: Annotated[str | None, typer.Option("--notes", help="Additional notes.")] = None,
) -> None:
    """Set presentation card fields for a repository."""
    cfg = _config(config)
    fields = {
        k: v for k, v in [
            ("hook", hook),
            ("who_for", who_for),
            ("problem", problem),
            ("why_now", why_now),
            ("demo_path", demo_path),
            ("notes", notes),
        ] if v is not None
    }
    if not fields:
        console.print("No card fields provided. Use --hook, --who-for, --problem, --why-now, --demo-path, or --notes.")
        raise typer.Exit(code=1)
    with _conn(cfg) as conn:
        db.init_db(conn)
        if db.get_repo(conn, full_name) is None:
            raise typer.BadParameter(f"Unknown repository: {full_name}")
        db.update_repo(conn, full_name, **fields)
    console.print(f"Updated card for {full_name}: {', '.join(fields.keys())}")


@app.command("export")
def export_repos(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path. Defaults to exports/rundown-export.md."),
    ] = None,
    decision: Annotated[
        list[str] | None,
        typer.Option("--decision", "-d", help="Decision values to include (default: present, shortlist)."),
    ] = None,
    view: Annotated[str | None, typer.Option("--view", help="host or research; defaults to each repository's saved view.")] = None,
) -> None:
    """Export presentation-ready Markdown for repositories marked present or shortlist."""
    cfg = _config(config)
    if view is not None and view not in {"host", "research"}:
        raise typer.BadParameter("Choose host or research.", param_hint="--view")
    decisions: list[str] = decision if decision else list(export.EXPORT_DECISIONS)
    output_path = output if output else cfg.exports_root / "rundown-export.md"
    with _conn(cfg) as conn:
        db.init_db(conn)
        count = export.export_to_file(conn, output_path, decisions, config=cfg, view=view)
    if count:
        console.print(f"Exported {count} repositories to {output_path}")
    else:
        console.print(f"No repositories with decision in {decisions}. Use `rd mark OWNER/REPO present` to mark repos for export.")


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
) -> None:
    """Check installation, configuration, authentication and local catalog health."""
    report = run_doctor(config)
    if json_output:
        typer.echo(json.dumps({**asdict(report), "healthy": report.healthy}, indent=2))
    else:
        table = Table("Check", "Status", "Details", "Fix")
        for item in report.checks:
            table.add_row(Text(item.name), Text(item.status), Text(item.message), Text(item.fix or ""))
        console.print(table)
    raise typer.Exit(report.exit_code)


@app.command("research-history")
def research_history(
    full_name: str,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Include complete stored provenance and the last two successful reports.")] = False,
) -> None:
    """Show research sources and changes since the previous successful report."""
    cfg = _config(config)
    with _conn(cfg) as conn:
        db.init_db(conn)
        row = db.get_repo(conn, full_name)
        if row is None:
            raise typer.BadParameter(f"Unknown repository: {full_name}")
        reports = [dict(report) for report in history.research_history(conn, row["id"])]
    if json_output:
        typer.echo(json.dumps([dict(report) for report in reports], indent=2))
    else:
        console.print(Text(history.format_research_history(reports)))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
