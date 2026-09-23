"""CLI commands for building, curating, marking, and exporting the catalog."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import categories, db, execution, export, github, repo_ops, scoring, wiki
from .agent_catalog import catalog_repositories
from .agent_io import load_agent_config, read_catalog, run_command
from .cli_support import _config, _conn

console = Console()


class RepoDecision(str, Enum):
    archived = "archived"
    rejected = "rejected"
    fork = "fork"
    integrate = "integrate"
    present = "present"
    shortlist = "shortlist"


def register(app: typer.Typer) -> None:
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
        json_output: Annotated[bool, typer.Option("--json", help="Print a bounded machine-readable catalog.")] = False,
        limit: Annotated[int, typer.Option("--limit", help="Maximum repositories in JSON output (1–100).")] = 100,
    ) -> None:
        if json_output:
            def operation():
                with read_catalog(load_agent_config(config)) as conn:
                    return catalog_repositories(conn, project=project, include_archived=include_archived, limit=limit)
            run_command(operation, True)
            return
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
