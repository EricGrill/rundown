from types import SimpleNamespace
from unittest.mock import patch

from rundown import db, repo_ops
from rundown.config import AppConfig, PathSettings


def test_clone_repo_updates_local_catalog(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(
            repo_root=tmp_path / "repos",
            database=tmp_path / "data" / "app.sqlite",
            logs=tmp_path / "logs",
        ),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                "owner/project",
                "owner",
                "project",
                "https://github.com/owner/project",
            ),
        )
        completed = SimpleNamespace(returncode=0, stdout="Cloned.", stderr="")
        with patch("rundown.repo_ops.subprocess.run", return_value=completed) as run:
            status, message = repo_ops.clone_repo(config, conn, "owner/project")
        row = db.get_repo(conn, "owner/project")

    assert status == "cloned"
    assert message == "Cloned."
    assert row["local_path"] == str(config.repo_root / "owner" / "project")
    assert row["status"] == "cloned"
    run.assert_called_once_with(
        [
            "gh",
            "repo",
            "clone",
            "owner/project",
            str(config.repo_root / "owner" / "project"),
        ],
        text=True,
        capture_output=True,
    )
