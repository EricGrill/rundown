import asyncio
import threading
from unittest.mock import patch

from textual.command import CommandList, CommandPalette
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input, Markdown, Static

from rundown import db
from rundown.config import AppConfig, GithubSettings, PathSettings
from rundown.tui import RundownApp


def test_tui_github_sync_uses_private_repository_setting(tmp_path):
    config = AppConfig(
        root=tmp_path,
        github=GithubSettings(include_private=True),
    )

    with patch("rundown.tui.github.fetch_starred", return_value=[]) as fetch:
        app = RundownApp(config)
        assert app.fetch_starred() == []

    fetch.assert_called_once_with(include_private=True)


def test_empty_tui_syncs_github_stars_without_blocking_startup(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    starred = db.RepoInput(
        full_name="owner/project",
        owner="owner",
        repo="project",
        url="https://github.com/owner/project",
        language="Python",
        stars=900,
        description="A useful project for testing the catalog.",
        starred_at="2026-07-20T14:30:00Z",
    )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [starred])
        async with app.run_test(size=(120, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            table = app.query_one("#repos", DataTable)
            assert table.row_count == 1
            assert len(app.rows) == 1
            assert app.rows[0]["full_name"] == "owner/project"
            assert table.get_row("owner/project")[1] == "Not researched"
            detail = str(app.query_one("#detail", Static).render())
            assert "A useful project for testing the catalog." in detail
            assert "Added: 2026-07-20" in detail
            assert "Synced 1 starred repositories" in str(
                app.query_one("#status", Static).render()
            )

    asyncio.run(run_test())

    with db.session(config.database_path) as conn:
        assert db.get_repo(conn, "owner/project") is not None


def test_tui_defaults_to_newest_added_first(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                "aaa-old/project",
                "aaa-old",
                "project",
                "https://github.com/aaa-old/project",
                starred_at="2020-01-01T00:00:00Z",
            ),
        )
        db.upsert_repo(
            conn,
            db.RepoInput(
                "zzz-new/project",
                "zzz-new",
                "project",
                "https://github.com/zzz-new/project",
                starred_at="2026-01-01T00:00:00Z",
            ),
        )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#repos", DataTable)
            assert table.get_row_at(0)[0] == "zzz-new/project"

    asyncio.run(run_test())


def test_tui_has_focused_two_column_catalog_and_reader(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
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

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(140, 30)):
            table = app.query_one("#repos", DataTable)
            assert [str(column.label) for column in table.columns.values()] == [
                "Repository",
                "Research",
            ]
            assert app.query_one("#detail", Static)._render_markup is False
            assert app.query_one("#status", Static)._render_markup is False
            assert app.query_one("#reader", VerticalScroll)
            assert app.query_one("#research-content", Markdown).source == ""

    asyncio.run(run_test())


def test_search_filters_name_and_description_then_researches_visible_repo(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for full_name, description in [
            ("alpha/web", "A frontend toolkit"),
            ("beta/service", "A searchable database service"),
        ]:
            owner, repo = full_name.split("/")
            local_path = config.repo_root / owner / repo
            local_path.mkdir(parents=True)
            db.upsert_repo(
                conn,
                db.RepoInput(
                    full_name,
                    owner,
                    repo,
                    f"https://github.com/{full_name}",
                    description=description,
                ),
            )
            db.update_repo(conn, full_name, local_path=str(local_path))

    researched = []

    def fake_research(_config, _conn, full_name):
        researched.append(full_name)
        return "success", "## Result\n\nFiltered research result."

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        with (
            patch(
                "rundown.tui.research.load_cached_repository_research",
                return_value=None,
            ),
            patch(
                "rundown.tui.repo_ops.clone_repo",
                return_value=("already_cloned", "Already cloned."),
            ),
            patch(
                "rundown.tui.research.run_repository_research",
                fake_research,
            ),
        ):
            async with app.run_test(size=(140, 30)) as pilot:
                await pilot.press("/")
                await pilot.press(*"database")

                search = app.query_one("#search", Input)
                table = app.query_one("#repos", DataTable)
                assert search.value == "database"
                assert table.row_count == 1
                assert table.get_row_at(0)[0] == "beta/service"

                await pilot.press("enter")
                assert table.has_focus
                await pilot.press("r")
                await app.workers.wait_for_complete()
                await pilot.pause()

                assert researched == ["beta/service"]
                assert (
                    app.query_one("#research-content", Markdown).source
                    == "## Result\n\nFiltered research result."
                )

    asyncio.run(run_test())


def test_find_read_and_escape_move_focus_without_losing_context(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                "alpha/project",
                "alpha",
                "project",
                "https://github.com/alpha/project",
            ),
        )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(100, 30)) as pilot:
            search = app.query_one("#search", Input)
            table = app.query_one("#repos", DataTable)
            reader = app.query_one("#reader", VerticalScroll)

            await pilot.press("/")
            assert search.has_focus
            await pilot.press(*"alpha")
            await pilot.press("escape")
            assert search.value == ""
            assert table.has_focus

            await pilot.press("enter")
            assert reader.has_focus
            await pilot.press("escape")
            assert table.has_focus
            assert "alpha/project" in str(app.query_one("#detail", Static).render())

    asyncio.run(run_test())


def test_removed_action_letters_do_not_trigger_repo_operations(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
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

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        with (
            patch("rundown.tui.repo_ops.clone_repo") as clone_repo,
            patch("rundown.tui.research.run_repository_research") as run_research,
            patch("rundown.tui.subprocess.run") as run_external,
        ):
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.press("c", "u", "s", "a", "x", "f", "i", "e", "w", "o")
                await pilot.pause()

                clone_repo.assert_not_called()
                run_research.assert_not_called()
                run_external.assert_not_called()
                assert app.active_repo_action is None
                assert not app.repo_action_queue

    asyncio.run(run_test())


def test_command_palette_is_curated_filterable_and_invokes_find(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
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

    async def wait_for_palette_results(app, pilot):
        for _ in range(100):
            await asyncio.sleep(0.02)
            await pilot.pause()
            command_list = app.screen.query_one(CommandList)
            if command_list.option_count:
                return command_list
        raise AssertionError("command palette results did not load")

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(140, 35)) as pilot:
            await pilot.press("ctrl+p")
            command_list = await wait_for_palette_results(app, pilot)
            prompts = {
                str(command_list.get_option_at_index(index).prompt).splitlines()[0]
                for index in range(command_list.option_count)
            }
            assert prompts == {
                "Classify starred repositories",
                "Filter by category",
                "Find repositories",
                "Open repository on GitHub",
                "Quit",
                "Read selected repository",
                "Research selected repository",
                "Sync GitHub stars",
            }

            await pilot.press(*"sync github")
            command_list = await wait_for_palette_results(app, pilot)
            assert command_list.option_count == 1
            assert (
                str(command_list.get_option_at_index(0).prompt)
                .splitlines()[0]
                == "Sync GitHub stars"
            )
            await pilot.press("escape")
            assert not CommandPalette.is_open(app)

            await pilot.press("ctrl+p")
            await wait_for_palette_results(app, pilot)
            await pilot.press(*"find repositories")
            await wait_for_palette_results(app, pilot)
            await pilot.press("enter")
            await pilot.pause()

            assert not CommandPalette.is_open(app)
            assert app.query_one("#search", Input).has_focus

    asyncio.run(run_test())


def test_compact_read_mode_expands_and_scrolls_reader_then_returns_to_list(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    long_summary = "# Saved research\n\n" + "\n\n".join(
        f"## Section {index}\n\nDetails for section {index}." for index in range(40)
    )
    with db.session(config.database_path) as conn:
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
        db.insert_research_log(
            conn,
            repo_id,
            "Repository Understanding",
            long_summary,
            "success",
        )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(80, 24)) as pilot:
            table = app.query_one("#repos", DataTable)
            reader = app.query_one("#reader", VerticalScroll)
            catalog = app.query_one("#catalog")
            initial_reader_height = reader.size.height

            assert app.has_class("compact")
            await pilot.press("enter")
            await pilot.pause()

            assert app.has_class("reading")
            assert reader.has_focus
            assert catalog.styles.display == "none"
            assert reader.size.height > initial_reader_height

            await pilot.press("pagedown")
            await pilot.pause()
            assert reader.scroll_y > 0

            await pilot.press("escape")
            await pilot.pause()
            assert not app.has_class("reading")
            assert catalog.styles.display != "none"
            assert table.has_focus

    asyncio.run(run_test())


def test_research_key_preserves_selected_repo_after_sorted_reload(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for full_name, starred_at in [
            ("old/project", "2020-01-01T00:00:00Z"),
            ("new/project", "2026-01-01T00:00:00Z"),
        ]:
            owner, repo = full_name.split("/")
            db.upsert_repo(
                conn,
                db.RepoInput(
                    full_name,
                    owner,
                    repo,
                    f"https://github.com/{full_name}",
                    starred_at=starred_at,
                ),
            )
        cloned_path = config.repo_root / "new" / "project"
        cloned_path.mkdir(parents=True)
        db.update_repo(conn, "new/project", local_path=str(cloned_path))

    researched = []

    def fake_research(_config, _conn, full_name):
        researched.append(full_name)
        return "success", "Research completed."

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        with patch("rundown.tui.research.run_repository_research", fake_research):
            async with app.run_test(size=(140, 30)) as pilot:
                table = app.query_one("#repos", DataTable)
                table.move_cursor(row=0)
                await pilot.press("r")
                await app.workers.wait_for_complete()
                await pilot.pause()

                assert researched == ["new/project"]
                assert table.get_row_at(table.cursor_row)[0] == "new/project"
                assert (
                    app.query_one("#research-content", Markdown).source
                    == "Research completed."
                )
                assert "Research for new/project: success" in str(
                    app.query_one("#status", Static).render()
                )

    asyncio.run(run_test())


def test_two_research_jobs_run_in_queue_order_and_preserve_selection(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for full_name, starred_at in [
            ("old/project", "2020-01-01T00:00:00Z"),
            ("new/project", "2026-01-01T00:00:00Z"),
        ]:
            owner, repo = full_name.split("/")
            local_path = config.repo_root / owner / repo
            local_path.mkdir(parents=True)
            db.upsert_repo(
                conn,
                db.RepoInput(
                    full_name,
                    owner,
                    repo,
                    f"https://github.com/{full_name}",
                    starred_at=starred_at,
                ),
            )
            db.update_repo(conn, full_name, local_path=str(local_path))

    research_calls = []
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()

    def fake_research(_config, _conn, full_name):
        research_calls.append(full_name)
        if full_name == "new/project":
            first_started.set()
            release_first.wait(timeout=5)
        else:
            second_started.set()
            release_second.wait(timeout=5)
        return "success", f"Researched {full_name}."

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        with (
            patch(
                "rundown.tui.research.load_cached_repository_research",
                return_value=None,
            ),
            patch(
                "rundown.tui.repo_ops.clone_repo",
                return_value=("already_cloned", "Already cloned."),
            ),
            patch(
                "rundown.tui.research.run_repository_research",
                fake_research,
            ),
        ):
            try:
                async with app.run_test(size=(140, 30)) as pilot:
                    table = app.query_one("#repos", DataTable)
                    table.move_cursor(row=0)
                    await pilot.press("r")
                    assert await asyncio.to_thread(first_started.wait, 5)

                    table.move_cursor(row=1)
                    await pilot.press("r")
                    await pilot.pause()

                    assert app.active_repo_action == ("research", "new/project")
                    assert list(app.repo_action_queue) == [
                        ("research", "old/project")
                    ]
                    assert table.get_row("new/project")[1] == "Researching"
                    assert table.get_row("old/project")[1] == "Queued #1"

                    release_first.set()
                    assert await asyncio.to_thread(second_started.wait, 5)
                    await pilot.pause()

                    assert table.get_row_at(table.cursor_row)[0] == "old/project"
                    assert "old/project" in str(
                        app.query_one("#detail", Static).render()
                    )
                    assert (
                        app.query_one("#research-content", Markdown).source == ""
                    )

                    release_second.set()
                    await app.workers.wait_for_complete()
                    await pilot.pause()

                    assert research_calls == ["new/project", "old/project"]
                    assert table.get_row_at(table.cursor_row)[0] == "old/project"
                    assert (
                        app.query_one("#research-content", Markdown).source
                        == "Researched old/project."
                    )
            finally:
                release_first.set()
                release_second.set()

    asyncio.run(run_test())


def test_long_research_failure_stays_in_reader_without_overwriting_selection(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for full_name, starred_at in [
            ("other/project", "2020-01-01T00:00:00Z"),
            ("failed/project", "2026-01-01T00:00:00Z"),
        ]:
            owner, repo = full_name.split("/")
            repo_id = db.upsert_repo(
                conn,
                db.RepoInput(
                    full_name,
                    owner,
                    repo,
                    f"https://github.com/{full_name}",
                    starred_at=starred_at,
                ),
            )
            if full_name == "failed/project":
                db.insert_research_log(
                    conn,
                    repo_id,
                    "Repository Understanding",
                    "## Earlier result\n\nUseful saved context.",
                    "success",
                )

    long_error = "# Research failed\n\n" + "\n\n".join(
        f"Diagnostic line {index}: provider output was unavailable."
        for index in range(60)
    )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(80, 24)) as pilot:
            table = app.query_one("#repos", DataTable)
            content = app.query_one("#research-content", Markdown)
            reader = app.query_one("#reader", VerticalScroll)

            table.move_cursor(row=1)
            await pilot.pause()
            assert table.get_row_at(table.cursor_row)[0] == "other/project"
            assert content.source == ""

            app.repo_action_in_progress = True
            app.active_repo_action = ("research", "failed/project")
            app.finish_research("failed/project", "failed", long_error)
            await pilot.pause()

            status = str(app.query_one("#status", Static).render())
            assert "Research for failed/project failed" in status
            assert "Diagnostic line 59" not in status
            assert len(status) < 180
            assert table.get_row_at(table.cursor_row)[0] == "other/project"
            assert content.source == ""

            table.move_cursor(row=0)
            await pilot.pause()
            assert "Diagnostic line 59" in content.source
            assert "Previously saved research" in content.source
            assert "Useful saved context." in content.source

            reader.focus()
            await pilot.press("pagedown")
            await pilot.pause()
            assert reader.scroll_y > 0

            table.focus()
            table.move_cursor(row=1)
            await pilot.pause()
            assert content.source == ""
            table.move_cursor(row=0)
            await pilot.pause()
            assert "Diagnostic line 59" in content.source
            assert "Useful saved context." in content.source

    asyncio.run(run_test())


def test_cached_research_skips_clone_and_research_agent(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
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
        db.insert_research_log(
            conn,
            repo_id,
            "Repository Understanding",
            "## What This Is\n\nCached without extra work.",
            "success",
        )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        with (
            patch("rundown.tui.repo_ops.clone_repo") as clone_repo,
            patch(
                "rundown.tui.research.run_repository_research"
            ) as run_research,
        ):
            async with app.run_test(size=(140, 30)) as pilot:
                await pilot.press("r")
                await app.workers.wait_for_complete()
                await pilot.pause()

                clone_repo.assert_not_called()
                run_research.assert_not_called()
                assert (
                    app.query_one("#research-content", Markdown).source
                    == "## What This Is\n\nCached without extra work."
                )
                assert "Research for owner/project: cached" in str(
                    app.query_one("#status", Static).render()
                )

    asyncio.run(run_test())


def test_research_auto_clones_before_readme_analysis(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
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

    calls = []

    def fake_clone(_config, conn, full_name):
        calls.append(("clone", full_name))
        target = config.repo_root / "owner" / "project"
        target.mkdir(parents=True)
        db.update_repo(conn, full_name, local_path=str(target), status="cloned")
        return "cloned", "Clone completed."

    def fake_research(_config, _conn, full_name):
        calls.append(("research", full_name))
        return "success", "README analyzed."

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        with (
            patch("rundown.tui.repo_ops.clone_repo", fake_clone),
            patch("rundown.tui.research.run_repository_research", fake_research),
        ):
            async with app.run_test(size=(140, 30)) as pilot:
                await pilot.press("r")
                await app.workers.wait_for_complete()
                await pilot.pause()

                assert calls == [
                    ("clone", "owner/project"),
                    ("research", "owner/project"),
                ]
                detail = str(app.query_one("#detail", Static).render())
                assert "Local copy: Cloned" in detail
                research_content = app.query_one("#research-content", Markdown).source
                assert "Automatically cloned owner/project before research" in research_content
                assert "README analyzed." in research_content

    asyncio.run(run_test())


def test_tui_displays_cached_research_after_restart(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
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
        db.insert_research_log(
            conn,
            repo_id,
            "Repository Understanding",
            "## What This Is\n\nA cached explanation of this repository.",
            "success",
            source_fingerprint="abc123",
        )

    async def run_test():
        app = RundownApp(config, fetch_starred=lambda: [])
        async with app.run_test(size=(140, 30)):
            table = app.query_one("#repos", DataTable)
            assert table.get_row("owner/project")[1] == "Saved"
            detail = str(app.query_one("#detail", Static).render())
            assert "Saved research" in detail
            assert (
                app.query_one("#research-content", Markdown).source
                == "## What This Is\n\nA cached explanation of this repository."
            )

    asyncio.run(run_test())


def test_tui_shows_actionable_error_when_github_sync_fails(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )

    def fail_sync():
        raise RuntimeError("GitHub CLI is not authenticated")

    async def run_test():
        app = RundownApp(config, fetch_starred=fail_sync)
        async with app.run_test(size=(120, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            status = str(app.query_one("#status", Static).render())
            assert "GitHub sync failed" in status
            assert "gh auth login" in status
            assert app.sync_in_progress is False

    asyncio.run(run_test())


def test_cached_tui_syncs_in_background_and_preserves_filtered_selection(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for name, date in [("owner/old", "2020-01-01"), ("owner/new", "2026-01-01")]:
            db.upsert_repo(conn, db.RepoInput(
                name, "owner", name.split("/")[1], f"https://github.com/{name}",
                starred_at=date,
            ))
    started = threading.Event()
    release = threading.Event()
    fetch_count = []

    def fetch_stars():
        fetch_count.append(1)
        started.set()
        if not release.wait(timeout=10):
            raise RuntimeError("Test did not release background sync")
        return [db.RepoInput(
            "owner/newest", "owner", "newest", "https://github.com/owner/newest",
            starred_at="2026-09-12",
        )]

    async def run_test():
        app = RundownApp(config, fetch_starred=fetch_stars)
        async with app.run_test(size=(120, 30)) as pilot:
            try:
                table = app.query_one("#repos", DataTable)
                assert table.row_count == 2
                assert await asyncio.to_thread(started.wait, 2)
                assert app.sync_in_progress
                # Cached data remains interactive while the network request is blocked.
                await pilot.press("down", "/", *"old", "enter")
                assert app.selected_full_name() == "owner/old"
                assert table.row_count == 1
                release.set()
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert len(app.rows) == 3
                assert app.query_one("#search", Input).value == "old"
                assert app.selected_full_name() == "owner/old"
                assert table.row_count == 1
                assert not app.sync_in_progress
                assert fetch_count == [1]
            finally:
                release.set()

    asyncio.run(run_test())


def test_startup_sync_failure_keeps_cached_repositories_available(tmp_path):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(conn, db.RepoInput(
            "owner/cached", "owner", "cached", "https://github.com/owner/cached",
        ))

    def fail_sync():
        raise RuntimeError("Network unavailable")

    async def run_test():
        app = RundownApp(config, fetch_starred=fail_sync)
        async with app.run_test(size=(120, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#repos", DataTable).row_count == 1
            assert app.selected_full_name() == "owner/cached"
            assert "owner/cached" in str(app.query_one("#detail", Static).render())
            assert "Network unavailable" in str(app.query_one("#status", Static).render())
            assert not app.sync_in_progress

    asyncio.run(run_test())
