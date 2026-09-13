import json
import sqlite3

import pytest
import typer
from typer.testing import CliRunner

from rundown import db
from rundown.agent_io import AgentError
from rundown.memory import (
    MAX_DECISION_LENGTH,
    MAX_EVIDENCE_LENGTH,
    MAX_PROJECT_LENGTH,
    MAX_REASON_LENGTH,
    recall_decisions,
    remember_repository,
)
from rundown.memory_cli import register


def seed(conn: sqlite3.Connection) -> int:
    db.init_db(conn)
    return db.upsert_repo(
        conn,
        db.RepoInput(
            full_name="owner/project",
            owner="owner",
            repo="project",
            url="https://github.com/owner/project",
        ),
    )


def test_memory_is_append_only_newest_first_and_filterable():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    seed(conn)

    first = remember_repository(
        conn,
        "owner/project",
        project="app-one",
        decision="adopt",
        reason="Small API",
        evidence="README example",
        actor="agent-a",
    )
    second = remember_repository(
        conn,
        "owner/project",
        project="app-two",
        decision="reject",
        reason="Requires a server",
    )
    third = remember_repository(
        conn,
        "owner/project",
        project="app-one",
        decision="reconsider",
        reason="New release",
    )

    recalled = recall_decisions(conn)
    assert [item["id"] for item in recalled["results"]] == [third["id"], second["id"], first["id"]]
    assert recalled["results"][2]["evidence_label"] == "caller-provided, not verified"
    assert [item["decision"] for item in recall_decisions(conn, project="app-one")["results"]] == [
        "reconsider",
        "adopt",
    ]
    assert recall_decisions(conn, full_name="owner/project", limit=1)["results"] == [
        recalled["results"][0]
    ]


def test_recall_missing_table_is_empty_and_does_not_create_it():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    seed(conn)

    result = recall_decisions(conn)

    assert result["results"] == []
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'repository_decisions'"
    ).fetchone() is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"project": " "}, "project must be a nonblank string"),
        ({"decision": ""}, "decision must be a nonblank string"),
        ({"reason": "\n"}, "reason must be a nonblank string"),
        ({"actor": " "}, "actor must be a nonblank string"),
        ({"project": "p" * (MAX_PROJECT_LENGTH + 1)}, "project must be at most"),
        ({"decision": "d" * (MAX_DECISION_LENGTH + 1)}, "decision must be at most"),
        ({"reason": "r" * (MAX_REASON_LENGTH + 1)}, "reason must be at most"),
        ({"evidence": "e" * (MAX_EVIDENCE_LENGTH + 1)}, "evidence must be at most"),
    ],
)
def test_remember_validates_blank_and_bounded_fields(overrides, message):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    seed(conn)
    values = {
        "project": "app",
        "decision": "adopt",
        "reason": "Good fit",
        "evidence": "",
        "actor": "user",
        **overrides,
    }

    with pytest.raises(AgentError, match=message) as raised:
        remember_repository(conn, "owner/project", **values)

    assert raised.value.code == "invalid_input"
    assert raised.value.exit_code == 2


def test_memory_rejects_unknown_repository():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    seed(conn)

    with pytest.raises(AgentError, match="Unknown repository") as raised:
        remember_repository(
            conn,
            "missing/project",
            project="app",
            decision="adopt",
            reason="Good fit",
        )

    assert raised.value.code == "not_found"


def test_sync_and_research_writes_preserve_memory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    repo_id = seed(conn)
    saved = remember_repository(
        conn,
        "owner/project",
        project="app",
        decision="adopt",
        reason="Good fit",
    )

    db.upsert_repo(
        conn,
        db.RepoInput(
            full_name="owner/project",
            owner="owner",
            repo="project",
            url="https://github.com/owner/project",
            stars=42,
        ),
    )
    db.insert_research_log(conn, repo_id, "initial", "Research summary", "success")

    assert recall_decisions(conn)["results"][0] == saved


def test_recall_cli_reads_without_creating_a_missing_database(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "rundown.toml"
    config.write_text('[paths]\ndatabase = "missing/catalog.sqlite"\n', encoding="utf-8")
    database = tmp_path / "missing" / "catalog.sqlite"
    app = typer.Typer()
    register(app)

    result = CliRunner().invoke(app, ["recall", "--json", "--config", str(config)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["results"] == []
    assert not database.exists()


def test_recall_cli_does_not_migrate_an_existing_catalog(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "rundown.toml"
    config.write_text('[paths]\ndatabase = "data/catalog.sqlite"\n', encoding="utf-8")
    database = tmp_path / "data" / "catalog.sqlite"
    with db.session(database) as conn:
        seed(conn)
    app = typer.Typer()
    register(app)

    result = CliRunner().invoke(app, ["recall", "--json", "--config", str(config)])

    assert result.exit_code == 0, result.output
    with db.session(database) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'repository_decisions'"
        ).fetchone() is None


def test_remember_cli_emits_envelope_and_recall_reads_it(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "rundown.toml"
    config.write_text('[paths]\ndatabase = "data/catalog.sqlite"\n', encoding="utf-8")
    database = tmp_path / "data" / "catalog.sqlite"
    with db.session(database) as conn:
        seed(conn)
    app = typer.Typer()
    register(app)
    runner = CliRunner()

    remembered = runner.invoke(
        app,
        [
            "remember",
            "owner/project",
            "--project",
            "demo",
            "--decision",
            "adopt",
            "--reason",
            "Useful",
            "--json",
            "--config",
            str(config),
        ],
    )
    recalled = runner.invoke(
        app,
        ["recall", "--repo", "owner/project", "--json", "--config", str(config)],
    )

    assert remembered.exit_code == 0, remembered.output
    assert json.loads(remembered.stdout)["data"]["decision"] == "adopt"
    assert recalled.exit_code == 0, recalled.output
    assert json.loads(recalled.stdout)["data"]["count"] == 1
