from pathlib import Path
from unittest.mock import patch

import tomllib

import rundown
from rundown import db
from rundown.demo import demo_environment, load_demo_repositories


def test_bundled_demo_repositories_are_public_and_stable():
    repositories = load_demo_repositories()

    assert [repo.full_name for repo in repositories] == [
        "Textualize/textual",
        "astral-sh/uv",
        "jesseduffield/lazygit",
    ]
    assert all(repo.url.startswith("https://github.com/") for repo in repositories)


def test_package_versions_match():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert rundown.__version__ == project["project"]["version"]


def test_demo_environment_is_temporary_seeded_and_offline(tmp_path):
    user_database = tmp_path / "data" / "rundown.sqlite"
    sentinel = b"real catalog stays untouched"
    user_database.parent.mkdir(parents=True)
    user_database.write_bytes(sentinel)

    with patch("rundown.github.fetch_starred") as live_fetch:
        with demo_environment() as environment:
            demo_database = environment.config.database_path
            assert demo_database != user_database
            assert demo_database.is_file()
            assert environment.fetch_starred() == load_demo_repositories()

            with db.session(demo_database) as conn:
                rows = db.list_repos(conn)
                assert len(rows) == 3
                assert all(row["status"] == "researched" for row in rows)
                research = db.latest_successful_research(conn, rows[0]["id"])
                assert research is not None
                assert research["agent_name"] == "rundown-demo"
                assert "## What This Is" in research["summary"]
                card = db.get_repo_card(conn, rows[0]["id"])
                assert card is not None
                assert card["host_notes"]

            temporary_root = environment.config.root

    live_fetch.assert_not_called()
    assert user_database.read_bytes() == sentinel
    assert not Path(temporary_root).exists()
