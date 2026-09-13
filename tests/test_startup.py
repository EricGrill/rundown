import asyncio
from unittest.mock import Mock, patch

from typer.testing import CliRunner
from textual.widgets import Button

from rundown import db, startup
from rundown.cli import app
from rundown.config import AppConfig


def test_bare_command_in_pipe_prints_help_without_setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch.object(startup, "launch") as launch:
        result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert "Browse" in result.output
    launch.assert_not_called()
    assert not (tmp_path / "data").exists()


def test_interactive_bare_command_dispatches_config(tmp_path):
    with patch.object(startup, "interactive_terminal", return_value=True), patch.object(startup, "launch", return_value=None) as launch:
        result = CliRunner().invoke(app, [])
    assert result.exit_code == 0, result.output
    launch.assert_called_once()


def test_existing_catalog_opens_without_onboarding_or_auth_probe(tmp_path):
    config = AppConfig(root=tmp_path)
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(conn, db.RepoInput("owner/repo", "owner", "repo", "https://example.com/repo"))
    with patch("rundown.tui.RundownApp") as tui, patch.object(startup, "WelcomeApp") as welcome, patch.object(startup, "github_setup_problem") as auth:
        assert startup.launch(config) is None
    tui.assert_called_once_with(config)
    welcome.assert_not_called()
    auth.assert_not_called()


def test_demo_first_run_never_creates_personal_catalog_or_calls_auth(tmp_path):
    config = AppConfig(root=tmp_path)
    with patch.object(startup.WelcomeApp, "run", return_value="demo"), patch("rundown.tui.RundownApp") as tui, patch.object(startup, "github_setup_problem") as auth:
        assert startup.launch(config) is None
    assert tui.call_args.kwargs["demo_mode"] is True
    assert not tui.call_args.args[0].database_path.exists()
    assert not config.database_path.exists()
    auth.assert_not_called()


def test_connect_shows_only_required_guidance_and_does_not_create_data(tmp_path):
    config = AppConfig(root=tmp_path)
    with patch.object(startup.WelcomeApp, "run", return_value="connect"), patch.object(startup.shutil, "which", return_value=None), patch("rundown.tui.RundownApp") as tui:
        assert "Install GitHub CLI" in startup.launch(config)
    tui.assert_not_called()
    assert not config.database_path.exists()


def test_connect_authenticated_account_opens_catalog(tmp_path):
    config = AppConfig(root=tmp_path)
    with patch.object(startup.WelcomeApp, "run", return_value="connect"), patch.object(startup.shutil, "which", return_value="gh"), patch.object(startup.subprocess, "run", return_value=Mock(returncode=0)) as auth, patch("rundown.tui.RundownApp") as tui:
        assert startup.launch(config) is None
    assert auth.call_args.args[0] == ["gh", "auth", "status"]
    tui.assert_called_once_with(config)


def test_welcome_keyboard_at_compact_size():
    async def run():
        welcome = startup.WelcomeApp()
        async with welcome.run_test(size=(80, 24)) as pilot:
            welcome.query_one("#demo", Button).focus()
            await pilot.press("enter")
        assert welcome.return_value == "demo"
    asyncio.run(run())
