import json
import signal

import pytest
import typer
from typer.testing import CliRunner

from rundown import scheduler_cli


@pytest.fixture
def app():
    app = typer.Typer()
    scheduler_cli.register(app)
    return app


@pytest.mark.parametrize("status,exit_code", [("success", 0), ("busy", 0), ("dry_run", 0), ("partial_failure", 1), ("sync_failed", 1), ("cancelled", 130)])
def test_run_preserves_outcomes_and_exit_codes(app, monkeypatch, status, exit_code):
    outcome = {"status": status, "selected": [], "results": [], "succeeded": 0, "failed": 0, "remaining": 0}
    monkeypatch.setattr(scheduler_cli, "run_scheduled_research", lambda *args, **kwargs: outcome)
    result = CliRunner().invoke(app, ["schedule", "run", "--json"])
    assert result.exit_code == exit_code, result.output
    output = json.loads(result.stdout)
    assert output["data"] == outcome
    assert output["ok"] == (exit_code == 0)


def test_sigterm_requests_cancellation_and_restores_handler(app, monkeypatch):
    original = signal.getsignal(signal.SIGTERM)

    def research(config, *, dry_run, cancel_event):
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
        assert cancel_event.is_set()
        return {"status": "cancelled", "results": []}

    monkeypatch.setattr(scheduler_cli, "run_scheduled_research", research)
    result = CliRunner().invoke(app, ["schedule", "run", "--json"])
    assert result.exit_code == 130
    assert signal.getsignal(signal.SIGTERM) == original


def test_sigterm_handler_restored_on_exception(app, monkeypatch):
    original = signal.getsignal(signal.SIGTERM)

    def research(*args, **kwargs):
        raise OSError("cannot open")

    monkeypatch.setattr(scheduler_cli, "run_scheduled_research", research)
    result = CliRunner().invoke(app, ["schedule", "run", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "operation_failed"
    assert signal.getsignal(signal.SIGTERM) == original


def test_dry_run_forwarded(app, monkeypatch):
    def research(config, *, dry_run, cancel_event):
        assert dry_run is True
        return {"status": "dry_run"}
    monkeypatch.setattr(scheduler_cli, "run_scheduled_research", research)
    assert CliRunner().invoke(app, ["schedule", "run", "--dry-run", "--json"]).exit_code == 0


@pytest.mark.parametrize("command,function", [("enable", "enable_service"), ("disable", "disable_service")])
def test_service_commands(app, monkeypatch, tmp_path, command, function):
    source = tmp_path / "config.toml"
    source.write_text("")
    calls = []
    monkeypatch.setattr(scheduler_cli, function, lambda *args: calls.append(args) or {"enabled": command == "enable"})
    result = CliRunner().invoke(app, ["schedule", command, "--config", str(source), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["enabled"] == (command == "enable")
    assert calls
    if command == "enable":
        assert calls[0][1] == source


def test_status_combines_queue_and_service(app, monkeypatch):
    monkeypatch.setattr(scheduler_cli, "scheduler_status", lambda config: {"remaining": 12})
    monkeypatch.setattr(scheduler_cli, "service_status", lambda config: {"enabled": True})
    result = CliRunner().invoke(app, ["schedule", "status", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"] == {"remaining": 12, "service": {"enabled": True}}


def test_missing_config_json_error(app, tmp_path):
    result = CliRunner().invoke(app, ["schedule", "run", "--config", str(tmp_path / "missing.toml"), "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_config"


@pytest.mark.parametrize("outcome,detail", [
    ({"status": "sync_failed", "error": "GitHub authentication token expired"}, "token expired"),
    ({"status": "partial_failure", "results": [{"full_name": "owner/repo", "summary": "Provider timed out"}]}, "Provider timed out"),
])
def test_plain_failures_show_actionable_details(app, monkeypatch, outcome, detail):
    monkeypatch.setattr(scheduler_cli, "run_scheduled_research", lambda *args, **kwargs: outcome)
    result = CliRunner().invoke(app, ["schedule", "run"])
    assert result.exit_code == 1
    assert detail in result.stdout
