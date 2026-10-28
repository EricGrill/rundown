import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rundown import db, github, scheduler
from rundown.agent_io import AgentError
from rundown.config import AppConfig, SchedulerSettings, load_config
from rundown.processes import OperationCancelled


fetch_starred = github.fetch_starred
research_repository = scheduler.research_workflow.research_repository


@pytest.fixture
def config(tmp_path):
    return AppConfig(root=tmp_path, scheduler=SchedulerSettings(batch_size=2, sync_stars=False))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(github, "fetch_starred", Mock(side_effect=AssertionError("Unexpected network")))
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", Mock(side_effect=AssertionError("Unexpected provider")))


def repo(name):
    return db.RepoInput(f"owner/{name}", "owner", name, f"https://github.com/owner/{name}")


def seed(config, *names):
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for name in names:
            db.upsert_repo(conn, repo(name))


def save_success(config, conn, name, **kwargs):
    row = db.get_repo(conn, name)
    db.insert_research_log(conn, row["id"], "Repository Understanding", "Research", "success")
    return "success", "Research"


def test_selection_covers_all_stars_but_excludes_archived_unstarred_and_any_prior_success(config):
    seed(config, "fresh", "shortlisted", "archived", "hidden", "removed", "researched", "failed", "other-pass")
    with db.session(config.database_path) as conn:
        for name, fields in [
            ("shortlisted", {"status": "shortlisted"}), ("archived", {"archived": 1}),
            ("hidden", {"status": "archived"}), ("removed", {"starred": 0}),
        ]:
            db.update_repo(conn, f"owner/{name}", **fields)
        researched = db.get_repo(conn, "owner/researched")["id"]
        db.insert_research_log(conn, researched, "Repository Understanding", "Old success", "success", timestamp="2000-01-01", source_fingerprint="stale")
        db.insert_research_log(conn, researched, "Repository Understanding", "New failure", "failed")
        db.insert_research_log(conn, db.get_repo(conn, "owner/failed")["id"], "Repository Understanding", "Failure", "failed")
        db.insert_research_log(conn, db.get_repo(conn, "owner/other-pass")["id"], "Other pass", "Unrelated", "success")
    preview = scheduler.run_scheduled_research(replace(config, scheduler=SchedulerSettings(batch_size=50)), dry_run=True)
    assert {item["full_name"] for item in preview["selected"]} == {"owner/fresh", "owner/shortlisted", "owner/failed", "owner/other-pass"}


@pytest.mark.parametrize("existing", [False, True])
def test_preview_and_status_do_not_create_or_modify_files(config, existing):
    if existing:
        seed(config, "fresh")
    before = {p.relative_to(config.root): p.read_bytes() for p in config.root.rglob("*") if p.is_file()}
    assert scheduler.scheduler_status(config)["pending"] == int(existing)
    assert scheduler.run_scheduled_research(config, dry_run=True)["status"] == "dry_run"
    after = {p.relative_to(config.root): p.read_bytes() for p in config.root.rglob("*") if p.is_file()}
    assert after == before
    github.fetch_starred.assert_not_called()
    scheduler.research_workflow.research_repository.assert_not_called()


def test_bounded_batches_make_progress_across_runs(config, monkeypatch):
    seed(config, "a", "b", "c", "d", "e")
    research = Mock(side_effect=save_success)
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    reports = [scheduler.run_scheduled_research(config) for _ in range(3)]
    assert [r["succeeded"] for r in reports] == [2, 2, 1]
    assert [r["remaining"] for r in reports] == [3, 1, 0]
    assert [call.args[2] for call in research.call_args_list] == [f"owner/{c}" for c in "abcde"]
    assert scheduler.scheduler_status(config)["pending"] == 0


def test_failed_prefix_cools_down_without_blocking_later_repositories(config, monkeypatch):
    seed(config, "a", "b", "c")
    def research(config, conn, name, **kwargs):
        if name != "owner/c":
            return "failed", "Provider unavailable"
        return save_success(config, conn, name)
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    first = scheduler.run_scheduled_research(config)
    assert first["status"] == "partial_failure"
    assert first["failed"] == 2
    second = scheduler.run_scheduled_research(config)
    assert [item["full_name"] for item in second["selected"]] == ["owner/c"]
    assert second["succeeded"] == 1
    assert scheduler.scheduler_status(config)["deferred"] == 2
    path = config.database_path.with_suffix(".sqlite.scheduler.json")
    state = json.loads(path.read_text())
    state["retries"] = {name: 0 for name in state["retries"]}
    path.write_text(json.dumps(state))
    assert scheduler.scheduler_status(config)["next_batch"] == ["owner/a", "owner/b"]


@pytest.mark.parametrize("failure", [OperationCancelled("Cancelled"), RuntimeError("Provider crashed")])
def test_previous_repository_commit_survives_later_cancellation_or_error(config, monkeypatch, failure):
    seed(config, "a", "b")
    event = Event()
    def research(config, conn, name, **kwargs):
        assert kwargs["cancel_event"] is event
        if name == "owner/b":
            raise failure
        return save_success(config, conn, name)
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    report = scheduler.run_scheduled_research(config, cancel_event=event)
    assert report["status"] == ("cancelled" if isinstance(failure, OperationCancelled) else "partial_failure")
    with db.session(config.database_path) as conn:
        assert db.latest_successful_research(conn, db.get_repo(conn, "owner/a")["id"]) is not None
        assert db.latest_successful_research(conn, db.get_repo(conn, "owner/b")["id"]) is None


def test_pre_cancelled_run_does_not_sync_or_research(config):
    event = Event()
    event.set()
    result = scheduler.run_scheduled_research(replace(config, scheduler=SchedulerSettings()), cancel_event=event)
    assert result["status"] == "cancelled"
    assert not config.database_path.exists()
    github.fetch_starred.assert_not_called()
    scheduler.research_workflow.research_repository.assert_not_called()


def test_sync_adds_new_stars_and_retains_removed_repository_notes_and_research(config, monkeypatch):
    seed(config, "removed")
    with db.session(config.database_path) as conn:
        db.update_repo(conn, "owner/removed", notes="Keep my notes")
        save_success(config, conn, "owner/removed")
    fetch = Mock(return_value=[repo("new")])
    monkeypatch.setattr(github, "fetch_starred", fetch)
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", save_success)
    report = scheduler.run_scheduled_research(replace(config, scheduler=SchedulerSettings()))
    assert report["synced"] == 1
    assert [item["full_name"] for item in report["selected"]] == ["owner/new"]
    with db.session(config.database_path) as conn:
        old = db.get_repo(conn, "owner/removed")
        assert old["starred"] == 0
        assert old["notes"] == "Keep my notes"
        assert db.latest_successful_research(conn, old["id"])["summary"] == "Research"
        assert db.get_repo(conn, "owner/new")["starred"] == 1


def test_sync_failure_stops_research_without_altering_catalog(config, monkeypatch):
    seed(config, "a")
    before = config.database_path.read_bytes()
    monkeypatch.setattr(github, "fetch_starred", Mock(side_effect=github.GithubCliError("offline")))
    report = scheduler.run_scheduled_research(replace(config, scheduler=SchedulerSettings()))
    assert report["status"] == "sync_failed"
    assert config.database_path.read_bytes() == before
    scheduler.research_workflow.research_repository.assert_not_called()


def test_overlapping_run_is_busy_and_lock_is_released_after_provider_error(config, monkeypatch):
    seed(config, "a")
    nested = []
    def research(*args, **kwargs):
        nested.append(scheduler.run_scheduled_research(config))
        raise RuntimeError("provider crashed")
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    assert scheduler.run_scheduled_research(config)["status"] == "partial_failure"
    assert nested[0]["status"] == "busy"
    assert nested[0]["selected"] == []
    assert scheduler.run_scheduled_research(config)["status"] == "success"


@pytest.mark.parametrize("content", ["broken", '[]', '{"version": 2}', '{"version": 1, "retries": {"a": true}}', '{"version": 1, "retries": {"a": NaN}}'])
def test_malformed_persistent_state_fails_closed(config, content):
    seed(config, "a")
    path = config.database_path.with_suffix(".sqlite.scheduler.json")
    path.write_text(content)
    with pytest.raises(AgentError, match="Cannot read"):
        scheduler.run_scheduled_research(config)
    assert path.read_text() == content
    github.fetch_starred.assert_not_called()
    scheduler.research_workflow.research_repository.assert_not_called()


def test_scheduler_config_defaults_and_toml_round_trip(tmp_path):
    assert SchedulerSettings() == SchedulerSettings(interval_minutes=60, batch_size=10, retry_hours=24, sync_stars=True)
    path = tmp_path / "rundown.toml"
    path.write_text("[scheduler]\ninterval_minutes=15\nbatch_size=3\nretry_hours=8\nsync_stars=false\n")
    assert load_config(path).scheduler == SchedulerSettings(15, 3, 8, False)


@pytest.mark.parametrize("field, invalid", [("interval_minutes", 0), ("interval_minutes", 10081), ("batch_size", 0), ("batch_size", 51), ("batch_size", True), ("retry_hours", 721), ("retry_hours", 1.5), ("sync_stars", "true")])
def test_scheduler_settings_reject_invalid_values(field, invalid):
    with pytest.raises(ValueError, match=field):
        SchedulerSettings(**{field: invalid})


@pytest.mark.parametrize("content", ['scheduler="hourly"', '[scheduler]\nunknown=1', '[scheduler]\nbatch_size="10"'])
def test_scheduler_config_rejects_malformed_toml_settings(tmp_path, content):
    path = tmp_path / "rundown.toml"
    path.write_text(content)
    with pytest.raises(ValueError, match="scheduler"):
        load_config(path)


def test_cancellable_github_auth_and_fetch_have_timeouts(monkeypatch):
    event = Event()
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(github.shutil, "which", lambda name: "/mock/gh")
    monkeypatch.setattr(github, "run_command", run)
    assert fetch_starred(cancel_event=event) == []
    assert [call.args[0][:2] for call in run.call_args_list] == [["gh", "auth"], ["gh", "api"]]
    assert [call.kwargs["timeout"] for call in run.call_args_list] == [30, 120]
    assert all(call.kwargs["cancel_event"] is event for call in run.call_args_list)


def test_cancellation_after_fetch_leaves_catalog_unchanged(config, monkeypatch):
    seed(config, "existing")
    before = config.database_path.read_bytes()
    event = Event()

    def fetch(**kwargs):
        assert kwargs["cancel_event"] is event
        event.set()
        return [repo("new")]

    monkeypatch.setattr(github, "fetch_starred", fetch)
    report = scheduler.run_scheduled_research(
        replace(config, scheduler=SchedulerSettings()), cancel_event=event
    )
    assert report["status"] == "cancelled"
    assert config.database_path.read_bytes() == before
    scheduler.research_workflow.research_repository.assert_not_called()


def test_sync_database_error_rolls_back_import_and_unstarring(config, monkeypatch):
    seed(config, "existing")
    monkeypatch.setattr(github, "fetch_starred", Mock(return_value=[repo("new")]))
    monkeypatch.setattr(scheduler.categories, "classify_repos", Mock(side_effect=RuntimeError("classification failed")))
    report = scheduler.run_scheduled_research(replace(config, scheduler=SchedulerSettings()))
    assert report["status"] == "sync_failed"
    with db.session(config.database_path) as conn:
        assert db.get_repo(conn, "owner/existing")["starred"] == 1
        assert db.get_repo(conn, "owner/new") is None
    scheduler.research_workflow.research_repository.assert_not_called()


@pytest.mark.parametrize("cancel_during", ["auth", "api"])
def test_cancellable_github_propagates_process_cancellation(monkeypatch, cancel_during):
    event = Event()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == cancel_during:
            raise OperationCancelled("stopped")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(github.shutil, "which", lambda name: "/mock/gh")
    monkeypatch.setattr(github, "run_command", run)
    with pytest.raises(OperationCancelled, match="stopped"):
        fetch_starred(cancel_event=event)
    assert len(commands) == (1 if cancel_during == "auth" else 2)


def test_due_retries_follow_unattempted_then_oldest_retry(config, monkeypatch):
    seed(config, "a", "b", "c", "d")
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", Mock(return_value=("failed", "offline")))
    first = scheduler.run_scheduled_research(config)
    assert [item["full_name"] for item in first["selected"]] == ["owner/a", "owner/b"]
    path = config.database_path.with_suffix(".sqlite.scheduler.json")
    state = json.loads(path.read_text())
    # Both retries are due; b was attempted before a despite catalog ordering.
    state["retries"] = {"owner/a": 200, "owner/b": 100}
    path.write_text(json.dumps(state))
    assert scheduler.scheduler_status(config)["next_batch"] == ["owner/c", "owner/d"]
    research = Mock(side_effect=save_success)
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    second = scheduler.run_scheduled_research(config)
    assert [item["full_name"] for item in second["selected"]] == ["owner/c", "owner/d"]
    third = scheduler.run_scheduled_research(config)
    assert [item["full_name"] for item in third["selected"]] == ["owner/b", "owner/a"]
    assert scheduler.scheduler_status(config)["pending"] == 0


def test_provider_stage_releases_database_write_lock_for_other_operations(config, monkeypatch):
    import sqlite3

    seed(config, "a")

    def research(config, conn, name, **kwargs):
        db.update_repo(conn, name, local_path="/mock/cloned/repository")
        kwargs["on_stage"]("researching", "Generating research")
        with sqlite3.connect(config.database_path, timeout=0) as other:
            assert other.execute("SELECT local_path FROM repos WHERE full_name = ?", (name,)).fetchone()[0] == "/mock/cloned/repository"
            other.execute("UPDATE repos SET notes = ? WHERE full_name = ?", ("Edited during research", name))
        return save_success(config, conn, name)

    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    result = scheduler.run_scheduled_research(config)
    assert result["status"] == "success", result["results"]
    assert result["succeeded"] == 1
    with db.session(config.database_path) as conn:
        assert db.get_repo(conn, "owner/a")["notes"] == "Edited during research"


def test_status_reports_live_run_lock_while_provider_is_running(config, monkeypatch):
    seed(config, "a")
    observed = []

    def research(config, conn, name, **kwargs):
        observed.append(scheduler.scheduler_status(config))
        return save_success(config, conn, name)

    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research)
    assert scheduler.run_scheduled_research(config)["status"] == "success"
    assert observed[0]["running"] is True
    assert observed[0]["last_run"]["status"] == "running"
    assert scheduler.scheduler_status(config)["running"] is False


def test_status_marks_unlocked_incomplete_run_interrupted_without_rewriting_state(config, monkeypatch):
    seed(config, "a")
    monkeypatch.setattr(scheduler.research_workflow, "research_repository", save_success)
    scheduler.run_scheduled_research(config)
    path = config.database_path.with_suffix(".sqlite.scheduler.json")
    state = json.loads(path.read_text())
    state["last_run"] = {"status": "running", "current_repo": "owner/a"}
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    status = scheduler.scheduler_status(config)
    assert status["running"] is False
    assert status["last_run"]["status"] == "interrupted"
    assert path.read_bytes() == before


def test_clone_timeout_cleans_staging_defers_failed_repo_and_continues_batch(config, monkeypatch):
    import subprocess
    from pathlib import Path

    from rundown import repo_ops, research

    seed(config, "a", "b")
    commands = []
    stages = []

    def clone(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == config.execution.timeout_seconds
        assert isinstance(kwargs["cancel_event"], Event)
        staged = Path(command[-1])
        stages.append(staged.parent)
        (staged / ".git").mkdir(parents=True)
        if command[3] == "owner/a":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="cloned", stderr="")

    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research_repository)
    monkeypatch.setattr(repo_ops, "run_command", clone)
    monkeypatch.setattr(research, "load_cached_repository_research", Mock(return_value=None))
    provider = Mock(side_effect=save_success)
    monkeypatch.setattr(research, "run_repository_research", provider)
    report = scheduler.run_scheduled_research(config)
    assert report["status"] == "partial_failure"
    assert report["failed"] == 1
    assert report["succeeded"] == 1
    assert [command[3] for command in commands] == ["owner/a", "owner/b"]
    assert not (config.repo_root / "owner" / "a").exists()
    assert (config.repo_root / "owner" / "b" / ".git").exists()
    assert all(not path.exists() for path in stages)
    assert provider.call_args.args[2] == "owner/b"
    assert provider.call_count == 1
    assert scheduler.scheduler_status(config)["deferred"] == 1
    assert scheduler.scheduler_status(config)["next_batch"] == []


def test_background_research_preserves_archive_and_notes_saved_during_provider_call(config, monkeypatch):
    from rundown import research
    from rundown.cards import SECTION_TITLES

    seed(config, "a")
    local = config.repo_root / "owner" / "a"
    local.mkdir(parents=True)
    (local / "README.md").write_text("# A test repository")
    with db.session(config.database_path) as conn:
        db.update_repo(conn, "owner/a", local_path=str(local))

    def generate(*args, **kwargs):
        with db.session(config.database_path) as conn:
            db.update_repo(conn, "owner/a", status="archived", notes="Archived during research")
        return json.dumps({"schema_version": 1, "sections": {
            section: f"Finding for {section}" for section in SECTION_TITLES
        }})

    monkeypatch.setattr(scheduler.research_workflow, "research_repository", research_repository)
    monkeypatch.setattr(research, "generate_repository_research", generate)
    result = scheduler.run_scheduled_research(config)
    assert result["succeeded"] == 1
    with db.session(config.database_path) as conn:
        row = db.get_repo(conn, "owner/a")
        assert row["status"] == "archived"
        assert row["notes"] == "Archived during research"
        assert db.latest_successful_research(conn, row["id"]) is not None
