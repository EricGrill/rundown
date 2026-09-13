import asyncio
from unittest.mock import Mock, patch

from textual.app import App
from textual.widgets import DataTable, Static

from rundown import db
from rundown.config import AppConfig, PathSettings
from rundown.jobs import ResearchJob
from rundown.jobs_ui import JobsScreen
from rundown.tui import RundownApp


class JobsApp(App):
    def __init__(self, screen):
        super().__init__()
        self.jobs_screen = screen

    def on_mount(self):
        self.push_screen(self.jobs_screen)


def config_with_repos(tmp_path, *names):
    config = AppConfig(
        root=tmp_path,
        paths=PathSettings(database=tmp_path / "data" / "app.sqlite"),
    )
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for full_name in names:
            owner, name = full_name.split("/", 1)
            db.upsert_repo(
                conn,
                db.RepoInput(full_name, owner, name, f"https://github.com/{full_name}"),
            )
    return config


def test_queue_cancel_does_not_start_next_until_active_finishes(tmp_path):
    config = config_with_repos(tmp_path, "owner/one", "owner/two")

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with patch.object(RundownApp, "research_selected") as launch:
            async with app.run_test(size=(100, 30)) as pilot:
                await app.workers.wait_for_complete()
                app.enqueue_repo_action("research", "owner/one")
                app.enqueue_repo_action("research", "owner/two")
                first = app.active_job
                assert first is not None
                assert [item.full_name for item in app.research_jobs] == ["owner/one", "owner/two"]
                launch.assert_called_once()

                app.cancel_job(first.id)
                assert first.state == "cancelling"
                assert app.repo_action_in_progress
                assert list(app.repo_action_queue) == [("research", "owner/two")]
                launch.assert_called_once()

                app.finish_research("owner/one", "cancelled", "Stopped", first.id)
                await pilot.pause()
                assert app.active_job is not None
                assert app.active_job.full_name == "owner/two"
                assert launch.call_count == 2

    asyncio.run(run())


def test_queued_cancellation_removes_only_that_request(tmp_path):
    config = config_with_repos(tmp_path, "owner/one", "owner/two", "owner/three")

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with patch.object(RundownApp, "research_selected"):
            async with app.run_test(size=(100, 30)):
                await app.workers.wait_for_complete()
                for name in ("owner/one", "owner/two", "owner/three"):
                    app.enqueue_repo_action("research", name)
                queued = next(job for job in app.research_jobs if job.full_name == "owner/two")
                app.cancel_job(queued.id)
                assert queued.state == "cancelled"
                assert list(app.repo_action_queue) == [("research", "owner/three")]
                assert app.active_job is not None
                assert app.active_job.full_name == "owner/one"

    asyncio.run(run())


def test_retry_creates_fresh_refresh_job(tmp_path):
    config = config_with_repos(tmp_path, "owner/one")

    async def run():
        app = RundownApp(config, fetch_starred=list)
        failed = ResearchJob(1, "owner/one", state="failed", message="provider failed")
        app.research_jobs.append(failed)
        with patch.object(RundownApp, "research_selected") as launch:
            async with app.run_test(size=(100, 30)):
                await app.workers.wait_for_complete()
                app.retry_job(failed.id)
                assert app.active_job is not None
                assert app.active_job.id == 2
                assert app.active_job.action == "refresh"
                assert app.active_job.cancel_event is not failed.cancel_event
                assert launch.call_args.kwargs["force"] is True

    asyncio.run(run())


def test_jobs_modal_tracks_live_updates_and_actions():
    async def run():
        jobs = [ResearchJob(1, "owner/one")]
        cancel = Mock()
        retry = Mock()
        screen = JobsScreen(jobs, cancel, retry)
        app = JobsApp(screen)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 1
            jobs[0].state = "failed"
            jobs[0].message = "Provider unavailable"
            screen.refresh_jobs()
            assert table.get_row("1")[1] == "failed"
            assert "Provider unavailable" in str(app.screen.query_one("#job-detail", Static).render())
            await pilot.press("r")
            retry.assert_called_once_with(1)
            jobs.append(ResearchJob(2, "owner/two"))
            screen.refresh_jobs()
            assert table.row_count == 2
            table.move_cursor(row=1)
            await pilot.press("c")
            cancel.assert_called_once_with(2)

    asyncio.run(run())


def test_unmount_cancels_active_and_queued_jobs(tmp_path):
    config = config_with_repos(tmp_path, "owner/one", "owner/two")
    app = RundownApp(config, fetch_starred=list)

    async def run():
        with patch.object(RundownApp, "research_selected"):
            async with app.run_test(size=(100, 30)):
                await app.workers.wait_for_complete()
                app.enqueue_repo_action("research", "owner/one")
                app.enqueue_repo_action("research", "owner/two")
                assert not app._closing

    asyncio.run(run())
    assert app._closing
    assert all(job.cancel_event.is_set() for job in app.research_jobs)
    assert list(app.repo_action_queue) == []


def test_demo_blocks_research_and_refresh(tmp_path):
    config = config_with_repos(tmp_path, "owner/demo")

    async def run():
        app = RundownApp(config, fetch_starred=list, demo_mode=True)
        with patch.object(RundownApp, "research_selected") as launch:
            async with app.run_test(size=(100, 30)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("r", "R")
                await pilot.pause()
                assert app.research_jobs == []
                launch.assert_not_called()
                assert "Live research is disabled" in str(app.query_one("#status", Static).render())

    asyncio.run(run())


def test_demo_blocks_external_open(tmp_path):
    config = config_with_repos(tmp_path, "owner/demo")

    async def run():
        app = RundownApp(config, fetch_starred=list, demo_mode=True)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            with patch("rundown.tui.subprocess.run") as external:
                app.action_open_github()
                await pilot.pause()
                external.assert_not_called()
                assert "disabled in the offline demo" in str(app.query_one("#status", Static).render())

    asyncio.run(run())


def test_cancelled_job_cannot_be_reported_completed(tmp_path):
    config = config_with_repos(tmp_path, "owner/one")

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with patch.object(RundownApp, "research_selected"):
            async with app.run_test():
                await app.workers.wait_for_complete()
                app.enqueue_repo_action("research", "owner/one")
                job = app.active_job
                app.cancel_job(job.id)
                app.finish_research("owner/one", "cached", "Saved result", job.id)
                assert job.state == "cancelled"
                assert "cancelled" in str(app.query_one("#status", Static).render())

    asyncio.run(run())


def test_cancel_during_cache_lookup_rolls_back_transaction(tmp_path):
    config = config_with_repos(tmp_path, "owner/one")

    async def run():
        app = RundownApp(config, fetch_starred=list)

        def cached(_config, conn, row):
            conn.execute("UPDATE repos SET description = 'unsaved' WHERE id = ?", (row["id"],))
            app.active_job.cancel_event.set()
            return "Cached research"

        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            with patch("rundown.research_workflow.research.load_cached_repository_research", side_effect=cached):
                app.enqueue_repo_action("research", "owner/one")
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert app.research_jobs[0].state == "cancelled"
            with db.session(config.database_path) as conn:
                assert db.get_repo(conn, "owner/one")["description"] != "unsaved"

    asyncio.run(run())
