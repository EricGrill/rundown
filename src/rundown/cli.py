"""Rundown CLI powered by Typer."""

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from . import __version__
from .config import Config
from .database import Database
from .export import export_markdown
from .github import (
    check_gh_auth,
    fetch_repo_metadata,
    fetch_starred_repos,
    parse_repo_identifier,
    GitHubError,
)
from .models import Repo, Status
from .scoring import calculate_score

app = typer.Typer(
    name="rundown",
    help="Local-first CLI/TUI to rank and present your best GitHub repos.",
    no_args_is_help=False,
)
console = Console()


def _get_config() -> Config:
    """Load configuration."""
    return Config.load()


def _get_db(config: Config) -> Database:
    """Get database instance."""
    return Database(config.db_path)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", "-v", help="Show version and exit")
    ] = False,
):
    """Rundown: rank and present your best GitHub repos."""
    if version:
        rprint(f"[bold]rundown[/bold] {__version__}")
        raise typer.Exit()
    
    if ctx.invoked_subcommand is None:
        from .tui import run_tui
        config = _get_config()
        run_tui(config)


@app.command("tui")
def tui_command():
    """Launch the interactive TUI."""
    from .tui import run_tui
    config = _get_config()
    run_tui(config)


@app.command("sync-stars")
def sync_stars(
    limit: Annotated[
        int, typer.Option("--limit", "-l", help="Maximum repos to sync")
    ] = 500,
):
    """Sync starred repositories from GitHub."""
    config = _get_config()
    db = _get_db(config)
    
    if not check_gh_auth():
        console.print("[red]Error:[/red] gh CLI not authenticated. Run: gh auth login")
        raise typer.Exit(1)
    
    with console.status("[bold green]Fetching starred repos..."):
        try:
            starred = fetch_starred_repos(limit=limit)
        except GitHubError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
    
    console.print(f"Found [bold]{len(starred)}[/bold] starred repos")
    
    added = 0
    updated = 0
    
    with console.status("[bold green]Syncing to database..."):
        for meta, starred_at in starred:
            existing = db.get_repo(meta.full_name)
            repo = Repo.from_metadata(meta, starred_at)
            
            score, reason = calculate_score(repo, config.weights)
            repo.present_score = score
            repo.score_reason = reason
            
            db.upsert_repo(repo)
            
            if existing:
                updated += 1
            else:
                added += 1
    
    console.print(f"[green]✓[/green] Added {added}, updated {updated} repos")
    
    counts = db.count_by_status()
    total = sum(counts.values())
    console.print(f"[dim]Total: {total} repos in database[/dim]")


@app.command("add")
def add_repo(
    identifier: Annotated[
        str, typer.Argument(help="Repository (owner/repo or GitHub URL)")
    ],
):
    """Add a repository to the database."""
    config = _get_config()
    db = _get_db(config)
    
    try:
        owner, name = parse_repo_identifier(identifier)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    
    full_name = f"{owner}/{name}"
    existing = db.get_repo(full_name)
    
    with console.status(f"[bold green]Fetching {full_name}..."):
        try:
            meta = fetch_repo_metadata(owner, name)
        except GitHubError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
    
    repo = Repo.from_metadata(meta)
    score, reason = calculate_score(repo, config.weights)
    repo.present_score = score
    repo.score_reason = reason
    
    db.upsert_repo(repo)
    
    action = "Updated" if existing else "Added"
    console.print(f"[green]✓[/green] {action} [bold]{full_name}[/bold]")
    console.print(f"  Score: [bold]{score:.0f}[/bold]/100")
    console.print(f"  {reason}")


@app.command("score")
def recalculate_scores():
    """Recalculate scores for all repos."""
    config = _get_config()
    db = _get_db(config)
    
    repos = db.list_repos()
    
    if not repos:
        console.print("[yellow]No repos in database.[/yellow] Run: rundown sync-stars")
        raise typer.Exit(0)
    
    with console.status(f"[bold green]Scoring {len(repos)} repos..."):
        for repo in repos:
            score, reason = calculate_score(repo, config.weights)
            db.update_score(repo.id, score, reason)
    
    console.print(f"[green]✓[/green] Recalculated scores for {len(repos)} repos")


@app.command("list")
def list_repos(
    status: Annotated[
        Optional[str], typer.Option("--status", "-s", help="Filter by status")
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", "-l", help="Maximum repos to show")
    ] = 20,
):
    """List repos in the database."""
    config = _get_config()
    db = _get_db(config)
    
    filter_status = None
    if status:
        try:
            filter_status = Status(status.lower())
        except ValueError:
            valid = ", ".join(s.value for s in Status)
            console.print(f"[red]Error:[/red] Invalid status. Valid: {valid}")
            raise typer.Exit(1)
    
    repos = db.list_repos(status=filter_status)[:limit]
    
    if not repos:
        console.print("[yellow]No repos found.[/yellow]")
        raise typer.Exit(0)
    
    table = Table(title="Rundown")
    table.add_column("Repo", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Status", style="magenta")
    table.add_column("Language")
    table.add_column("Stars", justify="right")
    
    for repo in repos:
        table.add_row(
            repo.full_name,
            f"{repo.present_score:.0f}",
            repo.status.value,
            repo.language or "-",
            f"{repo.stars:,}" if repo.stars else "-",
        )
    
    console.print(table)
    
    if len(repos) == limit:
        total = len(db.list_repos(status=filter_status))
        if total > limit:
            console.print(f"[dim]Showing {limit} of {total} repos[/dim]")


@app.command("show")
def show_repo(
    identifier: Annotated[
        str, typer.Argument(help="Repository name or full_name")
    ],
):
    """Show details for a repository."""
    config = _get_config()
    db = _get_db(config)
    
    repo = db.get_repo(identifier)
    if not repo:
        repos = db.list_repos()
        matches = [r for r in repos if identifier.lower() in r.full_name.lower()]
        if len(matches) == 1:
            repo = matches[0]
        elif matches:
            console.print(f"[yellow]Multiple matches:[/yellow]")
            for r in matches[:10]:
                console.print(f"  {r.full_name}")
            raise typer.Exit(1)
        else:
            console.print(f"[red]Error:[/red] Repo not found: {identifier}")
            raise typer.Exit(1)
    
    _print_repo_detail(repo)


def _print_repo_detail(repo: Repo) -> None:
    """Print detailed repo info."""
    lines = []
    lines.append(f"[bold cyan]{repo.full_name}[/bold cyan]")
    lines.append(f"[link={repo.github_url}]{repo.github_url}[/link]")
    lines.append("")
    
    if repo.description:
        lines.append(f"[italic]{repo.description}[/italic]")
        lines.append("")
    
    lines.append(f"[bold]Score:[/bold] {repo.present_score:.0f}/100")
    lines.append(f"[dim]{repo.score_reason}[/dim]")
    lines.append("")
    
    lines.append(f"[bold]Status:[/bold] {repo.status.value}")
    if repo.manual_boost:
        lines.append(f"[bold]Manual boost:[/bold] {repo.manual_boost:+d}")
    lines.append("")
    
    meta_lines = []
    if repo.language:
        meta_lines.append(f"Language: {repo.language}")
    meta_lines.append(f"Stars: {repo.stars:,}")
    meta_lines.append(f"Forks: {repo.forks:,}")
    meta_lines.append(f"Open issues: {repo.open_issues}")
    if repo.license:
        meta_lines.append(f"License: {repo.license}")
    if repo.archived:
        meta_lines.append("[red]⚠️ Archived[/red]")
    lines.append("  ".join(meta_lines))
    
    if repo.topics:
        lines.append("")
        lines.append(f"[dim]Topics: {', '.join(repo.topics)}[/dim]")
    
    if any([repo.hook, repo.who_for, repo.problem, repo.why_now]):
        lines.append("")
        lines.append("[bold]Card:[/bold]")
        if repo.hook:
            lines.append(f"  Hook: {repo.hook}")
        if repo.who_for:
            lines.append(f"  Who for: {repo.who_for}")
        if repo.problem:
            lines.append(f"  Problem: {repo.problem}")
        if repo.why_now:
            lines.append(f"  Why now: {repo.why_now}")
        if repo.demo_path:
            lines.append(f"  Demo: {repo.demo_path}")
        if repo.flags:
            lines.append(f"  Flags: {', '.join(repo.flags)}")
        if repo.notes:
            lines.append(f"  Notes: {repo.notes}")
    
    panel = Panel("\n".join(lines), expand=False)
    console.print(panel)


@app.command("status")
def set_status(
    identifier: Annotated[str, typer.Argument(help="Repository name")],
    status: Annotated[str, typer.Argument(help="New status")],
):
    """Set status for a repository."""
    config = _get_config()
    db = _get_db(config)
    
    try:
        new_status = Status(status.lower())
    except ValueError:
        valid = ", ".join(s.value for s in Status)
        console.print(f"[red]Error:[/red] Invalid status. Valid: {valid}")
        raise typer.Exit(1)
    
    repo = db.get_repo(identifier)
    if not repo:
        repos = db.list_repos()
        matches = [r for r in repos if identifier.lower() in r.full_name.lower()]
        if len(matches) == 1:
            repo = matches[0]
        else:
            console.print(f"[red]Error:[/red] Repo not found: {identifier}")
            raise typer.Exit(1)
    
    old_status = repo.status
    db.update_status(repo.id, new_status)
    console.print(f"[green]✓[/green] {repo.full_name}: {old_status.value} → {new_status.value}")


@app.command("boost")
def set_boost(
    identifier: Annotated[str, typer.Argument(help="Repository name")],
    boost: Annotated[int, typer.Argument(help="Boost value (-10 to +10)")],
):
    """Set manual boost for a repository."""
    config = _get_config()
    db = _get_db(config)
    
    if not -10 <= boost <= 10:
        console.print("[red]Error:[/red] Boost must be between -10 and +10")
        raise typer.Exit(1)
    
    repo = db.get_repo(identifier)
    if not repo:
        repos = db.list_repos()
        matches = [r for r in repos if identifier.lower() in r.full_name.lower()]
        if len(matches) == 1:
            repo = matches[0]
        else:
            console.print(f"[red]Error:[/red] Repo not found: {identifier}")
            raise typer.Exit(1)
    
    db.update_manual_boost(repo.id, boost)
    
    repo.manual_boost = boost
    score, reason = calculate_score(repo, config.weights)
    db.update_score(repo.id, score, reason)
    
    console.print(f"[green]✓[/green] {repo.full_name}: boost={boost:+d}, score={score:.0f}")


@app.command("export")
def export_cmd(
    status: Annotated[
        Optional[str], typer.Option("--status", "-s", help="Filter by status (default: present)")
    ] = "present",
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Output file path")
    ] = None,
    all_statuses: Annotated[
        bool, typer.Option("--all", "-a", help="Export all repos regardless of status")
    ] = False,
    no_scores: Annotated[
        bool, typer.Option("--no-scores", help="Exclude score details")
    ] = False,
):
    """Export repos to presentation-ready Markdown."""
    config = _get_config()
    db = _get_db(config)
    
    filter_status = None
    if not all_statuses and status:
        try:
            filter_status = Status(status.lower())
        except ValueError:
            valid = ", ".join(s.value for s in Status)
            console.print(f"[red]Error:[/red] Invalid status. Valid: {valid}")
            raise typer.Exit(1)
    
    repos = db.list_repos(status=filter_status)
    
    if not repos:
        console.print("[yellow]No repos to export.[/yellow]")
        raise typer.Exit(0)
    
    title = "Rundown"
    if filter_status:
        title = f"Rundown — {filter_status.value.title()}"
    
    content = export_markdown(
        repos,
        output=output,
        title=title,
        include_scores=not no_scores,
    )
    
    if output:
        console.print(f"[green]✓[/green] Exported {len(repos)} repos to {output}")
    else:
        console.print(content)


@app.command("stats")
def stats():
    """Show database statistics."""
    config = _get_config()
    db = _get_db(config)
    
    counts = db.count_by_status()
    total = sum(counts.values())
    
    if total == 0:
        console.print("[yellow]No repos in database.[/yellow] Run: rundown sync-stars")
        raise typer.Exit(0)
    
    console.print(f"[bold]Total repos:[/bold] {total}")
    console.print()
    
    table = Table(title="By Status")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    table.add_column("", justify="right")
    
    for status in Status:
        count = counts[status]
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 5) if pct > 0 else ""
        table.add_row(status.value, str(count), f"{bar} {pct:.0f}%")
    
    console.print(table)
    
    repos = db.list_repos()
    if repos:
        languages = {}
        for repo in repos:
            lang = repo.language or "Unknown"
            languages[lang] = languages.get(lang, 0) + 1
        
        console.print()
        top_langs = sorted(languages.items(), key=lambda x: -x[1])[:5]
        console.print("[bold]Top languages:[/bold]")
        for lang, count in top_langs:
            console.print(f"  {lang}: {count}")


@app.command("config")
def show_config():
    """Show current configuration."""
    config = _get_config()
    
    console.print(f"[bold]Config file:[/bold] {config.config_path}")
    console.print(f"[bold]Database:[/bold] {config.db_path}")
    console.print()
    console.print("[bold]Score weights:[/bold]")
    console.print(f"  freshness: {config.weights.freshness}")
    console.print(f"  description_quality: {config.weights.description_quality}")
    console.print(f"  readme_signal: {config.weights.readme_signal}")
    console.print(f"  stars_normalized: {config.weights.stars_normalized}")
    console.print(f"  topics_count: {config.weights.topics_count}")
    console.print(f"  has_license: {config.weights.has_license}")
    console.print(f"  low_issues_ratio: {config.weights.low_issues_ratio}")
    console.print(f"  manual_boost_multiplier: {config.weights.manual_boost_multiplier}")
    console.print(f"  archived_penalty: {config.weights.archived_penalty}")
    console.print(f"  freshness_half_life_days: {config.weights.freshness_half_life_days}")


if __name__ == "__main__":
    app()
