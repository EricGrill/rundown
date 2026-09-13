"""End-to-end contracts for agents using Rundown without the TUI."""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from rundown import (
    automation_cli,
    db,
    discovery_cli,
    inspect_cli,
    memory_cli,
    search_cli,
)
from rundown.config import load_config


def _agent_app() -> typer.Typer:
    app = typer.Typer()
    for module in (search_cli, inspect_cli, discovery_cli, memory_cli, automation_cli):
        module.register(app)
    return app


def _config_file(tmp_path):
    config = tmp_path / "config" / "rundown.toml"
    config.parent.mkdir()
    config.write_text('[paths]\ndatabase = "data/catalog.sqlite"\n', encoding="utf-8")
    return config


def _github_repository() -> dict[str, object]:
    return {
        "full_name": "acme/queue",
        "private": False,
        "visibility": "public",
        "archived": False,
        "description": "A durable Python background queue",
        "language": "Python",
        "stargazers_count": 12_345,
        "pushed_at": "2026-09-01T00:00:00Z",
    }


def _github_response(command, **_kwargs):
    repository = _github_repository()
    payload = (
        {"items": [repository], "total_count": 1, "incomplete_results": False}
        if "search/repositories" in command
        else repository
    )
    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")


def _invoke_json(runner: CliRunner, app: typer.Typer, args: list[str]) -> dict[str, object]:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["error"] is None
    return payload["data"]


def _seed_repository(config_file, *, with_project: bool = False) -> int:
    config = load_config(config_file)
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(
            conn,
            db.RepoInput(
                "acme/queue",
                "acme",
                "queue",
                "https://github.com/acme/queue",
                description="A durable Python background queue",
                language="Python",
                stars=12_345,
            ),
        )
        if with_project:
            db.upsert_project_mapping(conn, repo_id, "nova", 92, "Fits local task execution")
        return repo_id


def test_discovery_requires_explicit_add_before_local_search_finds_repository(tmp_path):
    config_file = _config_file(tmp_path)
    database = tmp_path / "data" / "catalog.sqlite"
    runner = CliRunner()
    app = _agent_app()

    with patch("rundown.discovery.subprocess.run", side_effect=_github_response):
        discovered = _invoke_json(
            runner,
            app,
            ["discover", "python background queue", "--json", "-c", str(config_file)],
        )
        assert discovered["results"][0]["full_name"] == "acme/queue"
        assert discovered["results"][0]["in_catalog"] is False
        assert not database.exists()

        added = _invoke_json(
            runner,
            app,
            ["add", "acme/queue", "--json", "-c", str(config_file)],
        )

    assert added == {
        "full_name": "acme/queue",
        "status": "added",
        "github_star_changed": False,
    }
    with db.session(database) as conn:
        assert db.get_repo(conn, "acme/queue")["starred"] == 0

    found = _invoke_json(
        runner,
        _agent_app(),
        ["search", "durable queue", "--json", "-c", str(config_file)],
    )
    assert [item["full_name"] for item in found["results"]] == ["acme/queue"]


def test_decision_memory_is_recalled_inspected_and_searched_after_reopen(tmp_path):
    config_file = _config_file(tmp_path)
    _seed_repository(config_file, with_project=True)
    runner = CliRunner()

    remembered = _invoke_json(
        runner,
        _agent_app(),
        [
            "remember",
            "acme/queue",
            "--project",
            "nova",
            "--decision",
            "adopt",
            "--reason",
            "Works without a Redis service",
            "--evidence",
            "README documents an embedded backend",
            "--actor",
            "integration-agent",
            "--json",
            "-c",
            str(config_file),
        ],
    )
    assert remembered["decision"] == "adopt"

    with (
        patch("rundown.discovery.subprocess.run") as github,
        patch("rundown.research_workflow.research_repository") as provider,
    ):
        recalled = _invoke_json(
            runner,
            _agent_app(),
            ["recall", "--project", "nova", "--json", "-c", str(config_file)],
        )
        inspected = _invoke_json(
            runner,
            _agent_app(),
            ["inspect", "acme/queue", "--json", "-c", str(config_file)],
        )
        found = _invoke_json(
            runner,
            _agent_app(),
            ["search", "without redis", "--json", "-c", str(config_file)],
        )

    assert recalled["count"] == 1
    assert inspected["decision_memory"]["results"][0]["reason"] == "Works without a Redis service"
    assert inspected["project_mappings"][0]["fit_score"] == 92
    assert found["results"][0]["full_name"] == "acme/queue"
    assert "decision_memory" in found["results"][0]["matched_fields"]
    assert {"field": "decision_memory", "source_kind": "decision_memory"} in found["results"][0]["match_sources"]
    github.assert_not_called()
    provider.assert_not_called()


def test_refresh_research_is_persisted_for_later_digest_and_inspection(tmp_path):
    config_file = _config_file(tmp_path)
    _seed_repository(config_file, with_project=True)
    runner = CliRunner()

    def save_research(config, conn, full_name, **_kwargs):
        repo = db.get_repo(conn, full_name)
        db.insert_research_log(
            conn,
            repo["id"],
            "Repository Understanding",
            "Durable local task execution with an embedded backend.",
            "success",
        )
        return "success", "Saved generated research"

    with patch(
        "rundown.automation.research_workflow.research_repository",
        side_effect=save_research,
    ) as provider:
        refreshed = _invoke_json(
            runner,
            _agent_app(),
            ["refresh", "--project", "nova", "--json", "-c", str(config_file)],
        )

    assert refreshed["status"] == "success"
    assert refreshed["succeeded"] == 1
    provider.assert_called_once()

    with patch("rundown.research_workflow.research_repository") as provider:
        digest = _invoke_json(
            runner,
            _agent_app(),
            ["digest", "--project", "nova", "--json", "-c", str(config_file)],
        )
        inspected = _invoke_json(
            runner,
            _agent_app(),
            ["inspect", "acme/queue", "--json", "-c", str(config_file)],
        )

    assert digest["results"][0]["summary"].startswith("Durable local task execution")
    assert digest["results"][0]["next_action"] == "inspect"
    assert digest["network_used"] is False
    assert inspected["generated_research"]["record"]["text"].startswith(
        "Durable local task execution"
    )
    provider.assert_not_called()


def test_agent_commands_return_machine_safe_errors_without_creating_catalog(tmp_path):
    config_file = _config_file(tmp_path)
    database = tmp_path / "data" / "catalog.sqlite"
    result = CliRunner().invoke(
        _agent_app(),
        ["search", "queue", "--limit", "0", "--json", "-c", str(config_file)],
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "ok": False,
        "data": None,
        "error": {"code": "invalid_input", "message": "limit must be between 1 and 100"},
    }
    assert not database.exists()


def test_real_cli_serves_mcp_lifecycle_over_stdio_without_opening_tui(tmp_path):
    config_file = _config_file(tmp_path)
    database = tmp_path / "data" / "catalog.sqlite"
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]

    completed = subprocess.run(
        [sys.executable, "-m", "rundown.cli", "mcp", "-c", str(config_file)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["result"]["serverInfo"]["name"] == "rundown"
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == {
        "search_saved",
        "inspect_repo",
        "recall_decisions",
        "project_digest",
    }
    assert not database.exists()
