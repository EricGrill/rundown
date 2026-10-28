"""RundownApp mixin: research jobs queue, templates, catalog views, and history.

Methods here assume the mixed-in class also provides RundownApp's Textual App
behavior (query_one, push_screen, ...) and instance state (self.config,
self.rows, ...), so attribute access on self is intentionally not statically
verifiable from this file alone.
"""
# pyright: reportAttributeAccessIssue=false
from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import replace
from time import monotonic

from textual import work
from textual.widgets import Input, Markdown, Select, Static

from . import categories, db, history, preferences, research_workflow
from .cards import record_from_saved
from .catalog_ui import CatalogResult, CatalogScreen
from .db import init_db, session
from .history_ui import HistoryScreen
from .jobs import ResearchJob
from .jobs_ui import JobsScreen
from .processes import OperationCancelled, check_cancelled
from .template_ui import TemplateResult, TemplateScreen


class JobsMixin:
    def action_research_selected(self) -> None:
        full_name = self.selected_full_name()
        if full_name:
            action = "refresh" if full_name in self.research_errors else "research"
            self.enqueue_repo_action(action, full_name)

    def action_refresh_research(self) -> None:
        full_name = self.selected_full_name()
        if full_name:
            self.enqueue_repo_action("refresh", full_name)

    def action_edit_template(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        repo_id, name = row["id"], row["full_name"]
        cached = self.research_by_repo.get(repo_id)
        record = record_from_saved(cached["summary"], cached["card_json"]) if cached else None
        settings = self.effective_card_settings.get(repo_id, self.config.cards)

        def save(result: TemplateResult | None) -> None:
            if result is None:
                return
            try:
                with session(self.config.database_path) as conn:
                    conn.execute("PRAGMA busy_timeout = 100")
                    preferences.save_card_settings(conn, result.settings, repo_id if result.scope == "repo" else None)
                    if result.scope == "repo":
                        db.save_repo_card(conn, repo_id, view=result.settings.default_view)
            except (sqlite3.Error, ValueError) as exc:
                self.notify_result(f"Template not saved: {exc}")
                self.push_screen(TemplateScreen(result.settings, record, name), save)
                return
            self.load_rows(name)
            self.notify_result(f"Saved {'repository' if result.scope == 'repo' else 'global'} template. Shift+R applies audience and tone to new research.")

        self.push_screen(TemplateScreen(settings, record, name), save)

    def action_reset_template(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        try:
            with session(self.config.database_path) as conn:
                conn.execute("PRAGMA busy_timeout = 100")
                preferences.clear_card_override(conn, row["id"])
        except sqlite3.Error as exc:
            self.notify_result(f"Could not reset template: {exc}")
            return
        self.load_rows()
        self.notify_result("Repository now uses the global template.")

    def action_catalog_view(self) -> None:
        try:
            with session(self.config.database_path) as conn:
                named = preferences.list_named_views(conn)
        except (sqlite3.Error, ValueError) as exc:
            self.notify_result(f"Could not load saved views: {exc}")
            return

        def apply(result: CatalogResult | None) -> None:
            if result is None:
                return
            try:
                with session(self.config.database_path) as conn:
                    conn.execute("PRAGMA busy_timeout = 100")
                    if result.action == "save":
                        preferences.save_named_view(conn, result.view)
                    elif result.action == "delete" and result.view.name:
                        preferences.delete_named_view(conn, result.view.name)
            except (sqlite3.Error, ValueError) as exc:
                self.notify_result(f"Catalog view not saved: {exc}")
                self.push_screen(CatalogScreen(result.view, named, categories.CATEGORIES), apply)
                return
            self.catalog_view = replace(result.view, name=None) if result.action == "delete" else result.view
            search = self.query_one("#search", Input)
            category = self.query_one("#category", Select)
            with search.prevent(Input.Changed), category.prevent(Select.Changed):
                search.value = self.catalog_view.query
                category.value = self.catalog_view.category or "all"
            self.filter_rows()
            self.query_one("#repos").focus()
            self.notify_result(f"Catalog view {result.action}: {result.view.name or result.view.research_filter}")

        self.push_screen(CatalogScreen(self.catalog_view, named, categories.CATEGORIES), apply)

    def action_show_history(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        with session(self.config.database_path) as conn:
            reports = [dict(report) for report in history.research_history(conn, row["id"], include_failed=True)]
        self.push_screen(HistoryScreen(row["full_name"], history.format_research_history(reports)))

    def action_show_jobs(self) -> None:
        self.push_screen(JobsScreen(self.research_jobs, self.cancel_job, self.retry_job))

    def update_job_summary(self) -> None:
        if self._closing or not self.query("#job-summary"):
            return
        active = self.active_job
        queued = sum(job.state == "queued" for job in self.research_jobs)
        failed = sum(job.state == "failed" for job in self.research_jobs)
        state = f"{active.full_name} · {active.state} · {active.elapsed}" if active else "idle"
        prefix = "Demo · " if self.demo_mode else ""
        self.query_one("#job-summary", Static).update(f"{prefix}Jobs: {state} · {queued} queued · {failed} failed · j to inspect")

    def enqueue_repo_action(self, action: str, full_name: str) -> None:
        if self.demo_mode:
            self.notify_result("Demo uses saved example research. Live research is disabled; run rd tui for your catalog.")
            return
        if self._closing:
            return
        request = (action, full_name)
        if self.active_repo_action and full_name == self.active_repo_action[1]:
            self.notify_result(f"Research for {full_name} is already running.")
            return
        if any(name == full_name for _, name in self.repo_action_queue):
            self.notify_result(f"Research for {full_name} is already queued.")
            return
        self.research_jobs.append(ResearchJob(len(self.research_jobs) + 1, full_name, action))
        if self.repo_action_in_progress:
            self.repo_action_queue.append(request)
            self.load_rows()
            self.update_job_summary()
            self.notify_result(f"Queued research for {full_name} · position {len(self.repo_action_queue)}")
            return
        self.start_repo_action(action, full_name)

    def start_repo_action(self, action: str, full_name: str) -> None:
        job = next((item for item in reversed(self.research_jobs) if item.full_name == full_name and item.state == "queued"), None)
        if job is None:
            job = ResearchJob(len(self.research_jobs) + 1, full_name, action)
            self.research_jobs.append(job)
        job.started = monotonic()
        job.state = "researching"
        job.message = "Checking saved research."
        self.active_job = job
        self.repo_action_in_progress = True
        self.active_repo_action = (action, full_name)
        self.research_errors.pop(full_name, None)
        self.load_rows()
        self.update_job_summary()
        self.notify_result(f"Researching {full_name}… Saved results are reused; cloning is automatic when needed.")
        self.research_selected(full_name, force=action == "refresh", job=job)

    def start_next_repo_action(self) -> None:
        if not self._closing and not self.repo_action_in_progress and self.repo_action_queue:
            self.start_repo_action(*self.repo_action_queue.popleft())

    def cancel_job(self, job_id: int) -> None:
        job = next((item for item in self.research_jobs if item.id == job_id), None)
        if job is None or job.terminal:
            return
        job.cancel_event.set()
        if job.state == "queued":
            self.repo_action_queue = deque(request for request in self.repo_action_queue if request[1] != job.full_name)
            job.state = "cancelled"
            job.finished = monotonic()
            job.message = "Cancelled before starting."
        else:
            job.state = "cancelling"
            job.message = "Stopping the active operation; previous research is preserved."
        self.update_job_summary()
        self.load_rows()

    def retry_job(self, job_id: int) -> None:
        job = next((item for item in self.research_jobs if item.id == job_id), None)
        if job and job.state in {"failed", "cancelled"}:
            self.enqueue_repo_action("refresh", job.full_name)

    def update_job_stage(self, job_id: int, state: str, message: str) -> None:
        if self.active_job and self.active_job.id == job_id and not self.active_job.cancel_event.is_set():
            self.active_job.state = state
            self.active_job.message = message
            self.update_job_summary()

    def stop_jobs(self) -> None:
        self._closing = True
        for job in self.research_jobs:
            if not job.terminal:
                job.cancel_event.set()
        self.repo_action_queue.clear()

    async def action_quit(self) -> None:
        self.stop_jobs()
        self.exit()

    def on_unmount(self) -> None:
        self.stop_jobs()

    @work(thread=True, group="repo-action", exit_on_error=False)
    def research_selected(self, full_name: str, *, force: bool = False, job: ResearchJob | None = None) -> None:
        cancel_event = job.cancel_event if job else None

        def stage(state: str, message: str) -> None:
            check_cancelled(cancel_event)
            if job and not self._closing:
                self.app.call_from_thread(self.update_job_stage, job.id, state, message)

        try:
            check_cancelled(cancel_event)
            with session(self.config.database_path) as conn:
                init_db(conn)
                status, summary = research_workflow.research_repository(
                    self.config, conn, full_name, force=force,
                    cancel_event=cancel_event, on_stage=stage,
                )
                check_cancelled(cancel_event)
        except OperationCancelled:
            status, summary = "cancelled", "Cancelled. Previously saved research and host notes were preserved."
        except Exception as exc:
            status, summary = "failed", f"Research failed for {full_name}: {exc}"
        if not self._closing:
            self.app.call_from_thread(self.finish_research, full_name, status, summary, job.id if job else None)

    def finish_research(self, full_name: str, status: str, summary: str, job_id: int | None = None) -> None:
        if job_id is not None and (self.active_job is None or self.active_job.id != job_id):
            return
        if self.active_job:
            if self.active_job.cancel_event.is_set():
                status = "cancelled"
                summary = "Cancelled. Any research saved before cancellation remains available."
            self.active_job.state = "completed" if status in {"success", "cached"} else status
            self.active_job.finished = monotonic()
            self.active_job.message = summary if status in {"failed", "cancelled"} else "Saved research is ready to read."
        self.active_job = None
        self.repo_action_in_progress = False
        self.active_repo_action = None
        if status == "failed":
            self.research_errors[full_name] = summary
        else:
            self.research_errors.pop(full_name, None)
        self.load_rows()
        self.update_job_summary()
        self.notify_result(f"Research for {full_name}: {status}")
        if status == "failed":
            self.notify_result(f"Research for {full_name} failed. Select it and press Enter for details; r retries.")
        elif status != "cancelled" and self.selected_full_name() == full_name:
            self.query_one("#research-content", Markdown).update(summary)
        if self.repo_action_queue:
            self.call_after_refresh(self.start_next_repo_action)
