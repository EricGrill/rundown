from typer.testing import CliRunner

from rundown import db
from rundown.cli import app


runner = CliRunner()


def write_config(tmp_path):
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
    return config_file


def seed_repo(database):
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/project",
                owner="owner",
                repo="project",
                url="https://github.com/owner/project",
                language="Python",
                stars=900,
            ),
        )


def test_help_exits_successfully():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sync-stars" in result.output


def test_sync_stars_uses_private_repository_setting(tmp_path, monkeypatch):
    config_file = write_config(tmp_path)
    with config_file.open("a", encoding="utf-8") as stream:
        stream.write("\n[github]\ninclude_private = true\n")
    calls = []

    def fetch_starred(*, include_private=False):
        calls.append(include_private)
        return []

    monkeypatch.setattr("rundown.cli.github.fetch_starred", fetch_starred)

    result = runner.invoke(app, ["sync-stars", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert calls == [True]


def test_ensure_wiki_and_score_commands(tmp_path):
    config_file = write_config(tmp_path)
    seed_repo(tmp_path / "data" / "app.sqlite")

    result = runner.invoke(app, ["ensure-wiki", "--config", str(config_file)])
    assert result.exit_code == 0, result.output
    assert "Ensured 1 wiki pages" in result.output
    assert (tmp_path / "wiki" / "repos" / "owner__project.md").exists()

    score = runner.invoke(app, ["score", "--config", str(config_file)])
    assert score.exit_code == 0, score.output
    assert "Scored 1 repositories" in score.output

    alias = runner.invoke(app, ["wiki", "--config", str(config_file)])
    assert alias.exit_code == 0, alias.output
    assert "Ensured 1 wiki pages" in alias.output


def test_project_fit_and_project_filter(tmp_path):
    config_file = write_config(tmp_path)
    seed_repo(tmp_path / "data" / "app.sqlite")

    mapped = runner.invoke(
        app,
        [
            "project-fit",
            "owner/project",
            "Example App",
            "--score",
            "88",
            "--reason",
            "manual test mapping",
            "--config",
            str(config_file),
        ],
    )
    assert mapped.exit_code == 0, mapped.output

    listed = runner.invoke(app, ["repos", "--project", "Example App", "--config", str(config_file)])
    assert listed.exit_code == 0, listed.output
    assert "owner/project" in listed.output
    assert "Example App" in listed.output


def test_rediscover_outputs_queue(tmp_path):
    config_file = write_config(tmp_path)
    seed_repo(tmp_path / "data" / "app.sqlite")

    result = runner.invoke(app, ["rediscover", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert "Rediscovery Queue" in result.output
    assert "owner/project" in result.output
