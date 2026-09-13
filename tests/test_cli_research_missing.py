from io import StringIO
from unittest.mock import patch

from rich.console import Console
from rich.live import Live as RichLive
from threading import Event
from typer.testing import CliRunner

from rundown import db
from rundown import cli
from rundown.cli import app


runner = CliRunner()


def configured_repos(tmp_path, repos):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "rundown.toml"
    config_file.write_text(
        """
[paths]
repo_root = "repos"
wiki_root = "wiki"
database = "data/app.sqlite"
logs = "logs"
exports = "exports"
""",
        encoding="utf-8",
    )
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        for full_name, starred_at in repos:
            owner, repo = full_name.split("/", 1)
            db.upsert_repo(
                conn,
                db.RepoInput(
                    full_name=full_name,
                    owner=owner,
                    repo=repo,
                    url=f"https://github.com/{full_name}",
                    starred_at=starred_at,
                ),
            )
    return config_file, database


def save_research(database, full_name, status="success", pass_type="Repository Understanding"):
    with db.session(database) as conn:
        row = db.get_repo(conn, full_name)
        db.insert_research_log(conn, row["id"], pass_type, "saved", status)


def invoke(config_file, *args):
    return runner.invoke(
        app,
        ["research-missing", "--config", str(config_file), *args],
    )


def render_live(live):
    output = StringIO()
    snapshot_console = Console(file=output, width=80, color_system=None)
    snapshot_console.print(live.get_renderable())
    return output.getvalue()


def test_single_research_uses_cancellable_workflow_and_reports_auto_clone(tmp_path):
    config_file, _ = configured_repos(
        tmp_path, [("owner/project", "2026-03-01")]
    )
    observed = {}

    def fake_clone(_config, _conn, _full_name, *, cancel_event):
        observed["clone_event"] = cancel_event
        return "cloned", "ready"

    def fake_research(_config, _conn, _full_name, *, cancel_event):
        observed["research_event"] = cancel_event
        return "success", "Fresh research"

    with (
        patch("rundown.cli.repo_ops.clone_repo", fake_clone),
        patch(
            "rundown.research_workflow.research.run_repository_research",
            fake_research,
        ),
    ):
        result = runner.invoke(
            app,
            ["research", "owner/project", "--config", str(config_file)],
        )

    assert result.exit_code == 0, result.output
    assert isinstance(observed["clone_event"], Event)
    assert observed["clone_event"] is observed["research_event"]
    assert "Research status: success" in result.output
    assert "Automatically cloned owner/project before research." in result.output


def test_single_research_sets_cancellation_event_on_keyboard_interrupt(tmp_path):
    config_file, _ = configured_repos(
        tmp_path, [("owner/project", "2026-03-01")]
    )
    observed = {}

    def interrupt(_config, _conn, _full_name, *, cancel_event):
        observed["event"] = cancel_event
        raise KeyboardInterrupt

    with patch(
        "rundown.cli.research_workflow.research_repository", interrupt
    ):
        result = runner.invoke(
            app,
            ["research", "owner/project", "--config", str(config_file)],
        )

    assert result.exit_code == 130
    assert observed["event"].is_set()
    assert "Research interrupted." in result.output


def test_skips_only_successful_repository_understanding_research(tmp_path):
    config_file, database = configured_repos(
        tmp_path,
        [
            ("saved/project", "2026-03-03T00:00:00Z"),
            ("failed/project", "2026-03-02T00:00:00Z"),
            ("readme/project", "2026-03-01T00:00:00Z"),
        ],
    )
    save_research(database, "saved/project")
    save_research(database, "saved/project", status="failed")
    save_research(database, "failed/project", status="failed")
    save_research(database, "readme/project", pass_type="README")
    cloned = []
    researched = []

    def fake_clone(_config, _conn, full_name, **_options):
        cloned.append(full_name)
        return "already_cloned", "ready"

    def fake_research(_config, _conn, full_name, **_options):
        researched.append(full_name)
        return "success", "done"

    with (
        patch("rundown.cli.repo_ops.clone_repo", fake_clone),
        patch("rundown.research_workflow.research.run_repository_research", fake_research),
    ):
        result = invoke(config_file)

    assert result.exit_code == 0, result.output
    assert cloned == ["failed/project", "readme/project"]
    assert researched == cloned
    assert "Succeeded: 2. Failed: 0." in result.output


def test_cached_status_counts_as_success(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [("cached/project", "2026-03-01")],
    )

    with (
        patch(
            "rundown.cli.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch(
            "rundown.research_workflow.research.run_repository_research",
            return_value=("cached", "saved result"),
        ),
    ):
        result = invoke(config_file)

    assert result.exit_code == 0, result.output
    assert "[1/1] Researching cached/project…" in result.output
    assert "Succeeded: 1. Failed: 0." in result.output


def test_limit_uses_newest_starred_order_with_name_tiebreaker(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [
            ("zeta/project", "2026-03-02T00:00:00Z"),
            ("beta/project", "2026-03-03T00:00:00Z"),
            ("alpha/project", "2026-03-03T00:00:00Z"),
        ],
    )
    researched = []

    with (
        patch(
            "rundown.cli.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch(
            "rundown.research_workflow.research.run_repository_research",
            side_effect=lambda _config, _conn, name, **_options: researched.append(name)
            or ("success", "done"),
        ),
    ):
        result = invoke(config_file, "--limit", "2")

    assert result.exit_code == 0, result.output
    assert researched == ["alpha/project", "beta/project"]


def test_dry_run_lists_selection_without_clone_or_research(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [("new/project", "2026-03-02"), ("old/project", "2026-03-01")],
    )

    with (
        patch("rundown.cli.Live") as live,
        patch("rundown.cli.repo_ops.clone_repo") as clone_repo,
        patch("rundown.research_workflow.research.run_repository_research") as run_research,
    ):
        result = invoke(config_file, "--dry-run", "--limit", "1")

    assert result.exit_code == 0, result.output
    assert "Would research 1 repositories:" in result.output
    assert "new/project" in result.output
    assert "old/project" not in result.output
    clone_repo.assert_not_called()
    run_research.assert_not_called()
    live.assert_not_called()


def test_zero_missing_reports_no_work(tmp_path):
    config_file, database = configured_repos(
        tmp_path,
        [("saved/project", "2026-03-01")],
    )
    save_research(database, "saved/project")

    with (
        patch("rundown.cli.Live") as live,
        patch("rundown.cli.repo_ops.clone_repo") as clone_repo,
        patch("rundown.research_workflow.research.run_repository_research") as run_research,
    ):
        result = invoke(config_file)

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "No repositories need research."
    clone_repo.assert_not_called()
    run_research.assert_not_called()
    live.assert_not_called()


def test_failure_continues_to_next_repository_and_exits_nonzero(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [("first/project", "2026-03-02"), ("second/project", "2026-03-01")],
    )
    researched = []

    def fake_research(_config, _conn, full_name, **_options):
        researched.append(full_name)
        if full_name == "first/project":
            return "failed", "agent failed"
        return "success", "done"

    with (
        patch(
            "rundown.cli.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch("rundown.research_workflow.research.run_repository_research", fake_research),
    ):
        result = invoke(config_file)

    assert result.exit_code == 1
    assert researched == ["first/project", "second/project"]
    assert "Research failed for first/project: agent failed" in result.output
    assert "Researched second/project." in result.output
    assert "Succeeded: 1. Failed: 1." in result.output


def test_later_exception_preserves_earlier_success_and_continues(tmp_path):
    config_file, database = configured_repos(
        tmp_path,
        [
            ("first/project", "2026-03-03"),
            ("second/project", "2026-03-02"),
            ("third/project", "2026-03-01"),
        ],
    )
    researched = []

    def fake_research(_config, conn, full_name, **_options):
        researched.append(full_name)
        row = db.get_repo(conn, full_name)
        if full_name == "second/project":
            raise RuntimeError("provider unavailable")
        db.insert_research_log(
            conn,
            row["id"],
            "Repository Understanding",
            f"research for {full_name}",
            "success",
        )
        return "success", "done"

    with (
        patch(
            "rundown.cli.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch("rundown.research_workflow.research.run_repository_research", fake_research),
    ):
        result = invoke(config_file)

    assert result.exit_code == 1
    assert researched == ["first/project", "second/project", "third/project"]
    assert "Research failed for second/project: provider unavailable" in result.output
    assert "Succeeded: 2. Failed: 1." in result.output
    with db.session(database) as conn:
        first = db.get_repo(conn, "first/project")
        third = db.get_repo(conn, "third/project")
        assert db.latest_successful_research(conn, first["id"]) is not None
        assert db.latest_successful_research(conn, third["id"]) is not None


def test_invalid_limit_is_rejected(tmp_path):
    config_file, _ = configured_repos(tmp_path, [])

    result = invoke(config_file, "--limit", "0")

    assert result.exit_code != 0
    assert "x>=1" in result.output


def test_clone_failure_skips_research_and_continues(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [("clone/fails", "2026-03-02"), ("clone/works", "2026-03-01")],
    )
    researched = []

    def fake_clone(_config, _conn, full_name, **_options):
        if full_name == "clone/fails":
            return "failed", "authentication required"
        return "cloned", "done"

    with (
        patch("rundown.cli.repo_ops.clone_repo", fake_clone),
        patch(
            "rundown.research_workflow.research.run_repository_research",
            side_effect=lambda _config, _conn, name, **_options: researched.append(name)
            or ("success", "done"),
        ),
    ):
        result = invoke(config_file)

    assert result.exit_code == 1
    assert researched == ["clone/works"]
    normalized_output = " ".join(result.output.split())
    assert "Research failed for clone/fails: Research stopped" in normalized_output
    assert "could not be cloned." in normalized_output
    assert "authentication required" in result.output
    assert "Succeeded: 1. Failed: 1." in result.output


def test_terminal_progress_shows_stages_counts_and_results_then_cleans_up(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [("first/project", "2026-03-02"), ("second/project", "2026-03-01")],
    )
    terminal_output = StringIO()
    terminal_console = Console(
        file=terminal_output,
        force_terminal=True,
        color_system="standard",
        width=80,
    )
    displays = []
    clone_snapshots = []
    research_snapshots = []

    def live_factory(renderable, **kwargs):
        kwargs.pop("refresh_per_second", None)
        live = RichLive(renderable, auto_refresh=False, **kwargs)
        displays.append(live)
        return live

    def fake_clone(_config, _conn, _full_name, **_options):
        clone_snapshots.append(render_live(displays[0]))
        return "already_cloned", "ready"

    def fake_research(_config, _conn, full_name, **_options):
        research_snapshots.append(render_live(displays[0]))
        if full_name == "first/project":
            return "failed", "provider unavailable"
        return "success", "done"

    with (
        patch.object(cli, "console", terminal_console),
        patch.object(cli, "Live", side_effect=live_factory),
        patch("rundown.cli.repo_ops.clone_repo", fake_clone),
        patch("rundown.research_workflow.research.run_repository_research", fake_research),
    ):
        result = invoke(config_file)

    assert result.exit_code == 1
    assert len(displays) == 1
    assert displays[0].is_started is False
    assert "Preparing clone · first/project" in clone_snapshots[0]
    assert "Researching · first/project" in research_snapshots[0]
    assert "0/2" in research_snapshots[0]
    assert "Preparing clone · second/project" in clone_snapshots[1]
    assert "Researching · second/project" in research_snapshots[1]
    assert "1/2" in research_snapshots[1]

    final_snapshot = render_live(displays[0])
    assert "2/2" in final_snapshot
    assert "1 saved · 1 failed" in final_snapshot
    assert "Research failed for first/project: provider unavailable" in terminal_output.getvalue()
    assert "Researched second/project." in terminal_output.getvalue()


def test_keyboard_interrupt_reports_partial_progress_and_commits_completed_work(tmp_path):
    config_file, database = configured_repos(
        tmp_path,
        [("first/project", "2026-03-02"), ("second/project", "2026-03-01")],
    )
    terminal_output = StringIO()
    terminal_console = Console(file=terminal_output, force_terminal=True, width=80)
    displays = []
    cancel_events = []

    def live_factory(renderable, **kwargs):
        kwargs.pop("refresh_per_second", None)
        live = RichLive(renderable, auto_refresh=False, **kwargs)
        displays.append(live)
        return live

    def fake_research(_config, conn, full_name, **options):
        cancel_events.append(options["cancel_event"])
        if full_name == "second/project":
            raise KeyboardInterrupt
        row = db.get_repo(conn, full_name)
        db.insert_research_log(
            conn,
            row["id"],
            "Repository Understanding",
            "saved before interruption",
            "success",
        )
        return "success", "done"

    with (
        patch.object(cli, "console", terminal_console),
        patch.object(cli, "Live", side_effect=live_factory),
        patch(
            "rundown.cli.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch("rundown.research_workflow.research.run_repository_research", fake_research),
    ):
        result = invoke(config_file)

    assert result.exit_code == 130
    assert len(cancel_events) == 2
    assert cancel_events[0] is cancel_events[1]
    assert cancel_events[1].is_set()
    assert displays[0].is_started is False
    plain_output = terminal_output.getvalue()
    assert "Research interrupted" in plain_output
    assert "Processed: 1/2" in plain_output
    with db.session(database) as conn:
        first = db.get_repo(conn, "first/project")
        second = db.get_repo(conn, "second/project")
        assert db.latest_successful_research(conn, first["id"]) is not None
        assert db.latest_successful_research(conn, second["id"]) is None


def test_non_terminal_output_is_plain_and_preserves_markup_like_errors(tmp_path):
    config_file, _ = configured_repos(
        tmp_path,
        [("failed/project", "2026-03-02"), ("cached/project", "2026-03-01")],
    )
    output = StringIO()
    plain_console = Console(file=output, force_terminal=False, width=80)

    def fake_research(_config, _conn, full_name, **_options):
        if full_name == "failed/project":
            return "failed", "provider returned [red]bad[/red] [bold]response[/bold]"
        return "cached", "saved result"

    with (
        patch.object(cli, "console", plain_console),
        patch.object(cli, "Live") as live,
        patch(
            "rundown.cli.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch("rundown.research_workflow.research.run_repository_research", fake_research),
    ):
        result = invoke(config_file)

    assert result.exit_code == 1
    text = output.getvalue()
    assert "\x1b[" not in text
    assert "[red]bad[/red]" in text
    assert "[bold]response[/bold]" in text
    assert "Reused saved research for cached/project." in text
    live.assert_not_called()
