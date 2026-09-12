from unittest.mock import patch

import pytest

from rundown import db, execution
from rundown.config import AppConfig


@pytest.mark.parametrize("local_path", [None, "", "missing-clone", "regular-file"])
def test_execution_requires_a_cloned_directory(tmp_path, monkeypatch, local_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "regular-file").write_text("not a directory", encoding="utf-8")
    config = AppConfig(root=tmp_path)
    config.ensure_directories()
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(conn, db.RepoInput(
            full_name="example/project", owner="example", repo="project",
            url="https://github.com/example/project",
        ))
        db.update_repo(conn, "example/project", local_path=local_path)
        with (
            patch.object(execution.subprocess, "run") as run,
            pytest.raises(ValueError, match="not cloned locally"),
        ):
            execution.run_repo(config, conn, "example/project", execute=True)
        run.assert_not_called()
