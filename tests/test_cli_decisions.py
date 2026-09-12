import pytest
from typer.testing import CliRunner

from rundown import db
from rundown.cli import app


runner = CliRunner()


def configured_repo(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "rundown.toml"
    config_file.write_text(
        """
[paths]
database = "data/app.sqlite"
""",
        encoding="utf-8",
    )
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/project",
                owner="owner",
                repo="project",
                url="https://github.com/owner/project",
            ),
        )
    return config_file, database


@pytest.mark.parametrize("decision", ["archived", "rejected", "fork", "integrate"])
def test_mark_records_status_and_decision(tmp_path, decision):
    config_file, database = configured_repo(tmp_path)

    result = runner.invoke(
        app,
        ["mark", "owner/project", decision, "--config", str(config_file)],
    )

    assert result.exit_code == 0, result.output
    assert f"Marked owner/project as {decision}." in result.output
    with db.session(database) as conn:
        row = db.get_repo(conn, "owner/project")
        assert row["status"] == decision
        assert row["decision"] == decision
        assert row["archived"] == 0


def test_mark_rejects_invalid_decision_without_mutation(tmp_path):
    config_file, database = configured_repo(tmp_path)

    result = runner.invoke(
        app,
        ["mark", "owner/project", "delete", "--config", str(config_file)],
    )

    assert result.exit_code != 0
    assert "Invalid value" in result.output
    with db.session(database) as conn:
        row = db.get_repo(conn, "owner/project")
        assert row["status"] == "new"
        assert row["decision"] is None


def test_mark_rejects_unknown_repository_without_mutation(tmp_path):
    config_file, database = configured_repo(tmp_path)

    result = runner.invoke(
        app,
        ["mark", "missing/project", "rejected", "--config", str(config_file)],
    )

    assert result.exit_code != 0
    assert "Unknown repository: missing/project" in result.output
    assert "to list known repositories" in result.output
    with db.session(database) as conn:
        assert db.get_repo(conn, "missing/project") is None
        row = db.get_repo(conn, "owner/project")
        assert row["status"] == "new"
        assert row["decision"] is None
