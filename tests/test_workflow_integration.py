import asyncio
from unittest.mock import patch

from textual.widgets import Input, Select, Static
from typer.testing import CliRunner

from rundown import db, preferences
from rundown.cli import app as cli
from rundown.config import AppConfig
from rundown.doctor import DoctorCheck, DoctorReport
from rundown.template_ui import TemplateScreen
from rundown.tui import RundownApp


def seed(config):
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(conn, db.RepoInput("owner/tool", "owner", "tool", "https://github.com/owner/tool"))
        db.insert_research_log(conn, repo_id, "Repository Understanding", "## What This Is\nUseful saved evidence.", "success")
        db.save_repo_card(conn, repo_id, host_notes="Human cue stays intact.")
    return repo_id


def test_template_and_named_view_work_from_tui_shortcuts(tmp_path):
    config = AppConfig(root=tmp_path)
    repo_id = seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with patch("rundown.research_workflow.research.run_repository_research") as generate:
            async with app.run_test(size=(100, 35)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("t")
                assert isinstance(app.screen, TemplateScreen)
                app.screen.query_one("#template-duration", Input).value = "60"
                app.screen.query_one("#template-audience", Input).value = "Podcast listeners"
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert len(app.screen_stack) == 1
                assert "60 seconds" in str(app.query_one("#card-context", Static).render())
                with db.session(config.database_path) as conn:
                    assert preferences.effective_cards(conn, config.cards, repo_id).audience == "Podcast listeners"
                    assert db.get_repo_card(conn, repo_id)["host_notes"] == "Human cue stays intact."

                await pilot.press("g")
                app.screen.query_one("#catalog-name", Input).value = "Ready to read"
                app.screen.query_one("#catalog-filter", Select).value = "researched"
                app.screen.query_one("#catalog-sort", Select).value = "research_date"
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert app.catalog_view.name == "Ready to read"
                assert app.selected_full_name() == "owner/tool"
                assert app.query_one("#repos").has_focus
                with db.session(config.database_path) as conn:
                    assert preferences.get_named_view(conn, "Ready to read").sort == "research_date"
                await pilot.press("h")
                assert "legacy" in str(app.screen.query_one("#history-content", Static).render())
                await pilot.press("escape")
                generate.assert_not_called()

    asyncio.run(run())


def test_tui_template_changes_feed_research_and_cli_export(tmp_path):
    config = AppConfig(root=tmp_path)
    repo_id = seed(config)
    from dataclasses import replace
    settings = replace(config.cards, audience="Host audience", duration_seconds=60)
    with db.session(config.database_path) as conn:
        preferences.save_card_settings(conn, settings, repo_id)
        db.update_repo(conn, "owner/tool", decision="present", hook="Human opening")

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with (
            patch("rundown.research_workflow.repo_ops.clone_repo", return_value=("already_cloned", "ready")),
            patch("rundown.research_workflow.research.run_repository_research", return_value=("success", "saved")) as generate,
        ):
            async with app.run_test(size=(120, 35)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("R")
                await app.workers.wait_for_complete()
                assert generate.call_args.args[0].cards.audience == "Host audience"
                assert generate.call_args.kwargs["force"] is True

    asyncio.run(run())
    output = tmp_path / "show.md"
    with patch("rundown.cli._config", return_value=config):
        result = CliRunner().invoke(cli, ["export", "--view", "host", "--output", str(output)])
    assert result.exit_code == 0, result.output
    content = output.read_text()
    assert "Human opening" in content
    assert "Human cue stays intact." in content
    assert "Useful saved evidence." in content


def test_doctor_cli_json_and_failure_exit_without_side_effects():
    report = DoctorReport((DoctorCheck("Config", "error", "Invalid configuration", "Fix the TOML file"),))
    with patch("rundown.cli.run_doctor", return_value=report), patch("rundown.cli._config") as config:
        result = CliRunner().invoke(cli, ["doctor", "--json"])
    assert result.exit_code == 1
    assert '"healthy": false' in result.output
    config.assert_not_called()


def test_demo_cli_uses_temporary_offline_catalog():
    roots = []
    with patch("rundown.cli.RundownApp") as app:
        app.side_effect = lambda config, **kwargs: roots.append(config.root) or type("DemoApp", (), {"run": lambda self: None})()
        result = CliRunner().invoke(cli, ["demo"])
        assert result.exit_code == 0, result.output
        assert app.call_args.kwargs["demo_mode"] is True
    assert len(roots) == 1 and not roots[0].exists()


def test_prepare_read_export_share_human_overrides_and_preserve_selection(tmp_path):
    from textual.widgets import Button, Markdown, TextArea
    from rundown.card_edit_ui import CardEditScreen
    from rundown.export_ui import ExportScreen

    config = AppConfig(root=tmp_path)
    repo_id = seed(config)
    with db.session(config.database_path) as conn:
        db.update_repo(conn, "owner/tool", decision="present")
        db.upsert_repo(conn, db.RepoInput("other/repo", "other", "repo", "https://example.com/repo"))

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#search", Input).value = "tool"
            await pilot.pause()
            app.query_one("#repos").focus()
            await pilot.press("enter")
            assert len(app.screen_stack) == 1
            assert app.query_one("#reader").has_focus
            await pilot.press("e")
            assert isinstance(app.screen, CardEditScreen)
            app.screen.query_one("#card-edit-override", TextArea).load_text("My human opening")
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.selected_full_name() == "owner/tool"
            assert app.query_one("#search", Input).value == "tool"
            assert app.query_one("#card-hook Markdown", Markdown).source == "My human opening"
            app.action_export_card()
            await pilot.pause()
            assert isinstance(app.screen, ExportScreen)
            output = tmp_path / "selected.md"
            app.screen.query_one("#export-path", Input).value = str(output)
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert "My human opening" in output.read_text()
            assert "Human cue stays intact." in output.read_text()
            assert "other/repo" not in output.read_text()
            app.action_export_card()
            await pilot.pause()
            marked = tmp_path / "marked.md"
            app.screen.query_one("#export-path", Input).value = str(marked)
            app.screen.query_one("#export-scope", Select).value = "marked"
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert "My human opening" in marked.read_text()
            assert app.selected_full_name() == "owner/tool"
            assert app.query_one("#search", Input).value == "tool"
            app.action_prepare()
            await pilot.pause()
            app.screen.query_one("#card-edit-reset", Button).press()
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert "Unknown" in app.query_one("#card-hook Markdown", Markdown).source
        with db.session(config.database_path) as conn:
            assert db.get_repo(conn, "owner/tool")["hook"] is None
            assert db.get_repo_card(conn, repo_id)["host_notes"] == "Human cue stays intact."
    asyncio.run(run())
