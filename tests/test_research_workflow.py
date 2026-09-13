import sqlite3
from dataclasses import replace
from threading import Event
from unittest.mock import patch

import pytest

from rundown import db, preferences
from rundown.config import AppConfig, PathSettings
from rundown.processes import OperationCancelled
from rundown.research_workflow import research_repository


def configured_repo(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(
            database=tmp_path / "data" / "app.sqlite",
            repo_root=tmp_path / "repos",
        ),
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    repo_id = db.upsert_repo(
        conn,
        db.RepoInput(
            "owner/project",
            "owner",
            "project",
            "https://github.com/owner/project",
        ),
    )
    return config, conn, repo_id


def test_cached_research_uses_effective_settings_before_clone(tmp_path):
    config, conn, repo_id = configured_repo(tmp_path)
    saved = replace(config.cards, audience="Saved audience")
    preferences.save_card_settings(conn, saved, repo_id)
    conn.commit()
    conn.execute("BEGIN")

    with (
        patch(
            "rundown.research_workflow.research.load_cached_repository_research",
            return_value="Saved research",
        ) as load_cached,
        patch("rundown.research_workflow.repo_ops.clone_repo") as clone,
        patch(
            "rundown.research_workflow.research.run_repository_research"
        ) as generate,
    ):
        result = research_repository(config, conn, "owner/project")

    assert result == ("cached", "Saved research")
    assert load_cached.call_args.args[0].cards == saved
    clone.assert_not_called()
    generate.assert_not_called()
    assert conn.in_transaction
    conn.rollback()
    conn.close()


def test_research_reports_stages_and_forwards_force_and_cancellation(tmp_path):
    config, conn, repo_id = configured_repo(tmp_path)
    saved = replace(config.cards, tone="Saved tone")
    preferences.save_card_settings(conn, saved, repo_id)
    event = Event()
    stages = []

    with (
        patch("rundown.research_workflow.repo_ops.clone_repo") as clone,
        patch(
            "rundown.research_workflow.research.run_repository_research",
            return_value=("success", "Fresh research"),
        ) as generate,
        patch(
            "rundown.research_workflow.research.load_cached_repository_research"
        ) as load_cached,
    ):
        clone.return_value = ("cloned", "ready")
        result = research_repository(
            config,
            conn,
            "owner/project",
            force=True,
            cancel_event=event,
            on_stage=lambda state, message: stages.append((state, message)),
        )

    load_cached.assert_not_called()
    effective_config = clone.call_args.args[0]
    assert effective_config.cards == saved
    clone.assert_called_once_with(
        effective_config, conn, "owner/project", cancel_event=event
    )
    generate.assert_called_once_with(
        effective_config,
        conn,
        "owner/project",
        cancel_event=event,
        force=True,
    )
    assert stages == [
        ("cloning", "Preparing the local repository copy."),
        ("researching", "Generating research with the configured provider."),
    ]
    assert result == (
        "success",
        "Automatically cloned owner/project before research.\n\nFresh research",
    )
    conn.close()


def test_default_options_are_not_forwarded_to_existing_functions(tmp_path):
    config, conn, _ = configured_repo(tmp_path)
    with (
        patch(
            "rundown.research_workflow.research.load_cached_repository_research",
            return_value=None,
        ),
        patch(
            "rundown.research_workflow.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ) as clone,
        patch(
            "rundown.research_workflow.research.run_repository_research",
            return_value=("success", "Fresh research"),
        ) as generate,
    ):
        result = research_repository(config, conn, "owner/project")

    effective_config = clone.call_args.args[0]
    clone.assert_called_once_with(effective_config, conn, "owner/project")
    generate.assert_called_once_with(effective_config, conn, "owner/project")
    assert result == ("success", "Fresh research")
    conn.close()


def test_clone_failure_is_returned_without_running_provider(tmp_path):
    config, conn, _ = configured_repo(tmp_path)
    with (
        patch(
            "rundown.research_workflow.research.load_cached_repository_research",
            return_value=None,
        ),
        patch(
            "rundown.research_workflow.repo_ops.clone_repo",
            return_value=("failed", "GitHub CLI unavailable"),
        ),
        patch(
            "rundown.research_workflow.research.run_repository_research"
        ) as generate,
    ):
        result = research_repository(config, conn, "owner/project")

    assert result == (
        "failed",
        "Research stopped because the repository could not be cloned.\n\n"
        "GitHub CLI unavailable",
    )
    generate.assert_not_called()
    conn.close()


def test_cancellation_before_or_after_research_is_not_converted_to_failure(tmp_path):
    config, conn, _ = configured_repo(tmp_path)
    event = Event()
    event.set()
    with patch("rundown.research_workflow.repo_ops.clone_repo") as clone:
        with pytest.raises(OperationCancelled):
            research_repository(
                config, conn, "owner/project", cancel_event=event
            )
    clone.assert_not_called()

    event.clear()

    def cancel_after_research(*_args, **_kwargs):
        event.set()
        return "success", "Should not be returned"

    with (
        patch(
            "rundown.research_workflow.research.load_cached_repository_research",
            return_value=None,
        ),
        patch(
            "rundown.research_workflow.repo_ops.clone_repo",
            return_value=("already_cloned", "ready"),
        ),
        patch(
            "rundown.research_workflow.research.run_repository_research",
            side_effect=cancel_after_research,
        ),
    ):
        with pytest.raises(OperationCancelled):
            research_repository(
                config, conn, "owner/project", cancel_event=event
            )
    conn.close()
