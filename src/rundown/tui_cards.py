"""RundownApp mixin: card editing, export, GitHub sync, and marking repositories.

Methods here assume the mixed-in class also provides RundownApp's Textual App
behavior (query_one, push_screen, ...) and instance state (self.config,
self.rows, ...), so attribute access on self is intentionally not statically
verifiable from this file alone.
"""
# pyright: reportAttributeAccessIssue=false
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from textual import work
from textual.containers import VerticalScroll
from textual.widgets import Select

from . import categories, db, export, presentation
from .card_edit_ui import CardEditScreen
from .cards import record_from_saved
from .db import init_db, session
from .export_ui import ExportRequest, ExportScreen, write_export_file


class CardsMixin:
    def action_switch_card(self) -> None:
        if self.selected_row() is not None:
            self.set_card_view("research" if self.card_view == "host" else "host")

    def set_card_view(self, view: str) -> None:
        row = self.selected_row()
        if row is None or view == self.card_view:
            return
        try:
            with session(self.config.database_path) as conn:
                conn.execute("PRAGMA busy_timeout = 100")
                db.save_repo_card(conn, row["id"], view=view)
        except sqlite3.Error as exc:
            self.notify_result(f"Could not save card view: {exc}. Try again.")
            selector = self.query_one("#card-view", Select)
            with selector.prevent(Select.Changed):
                selector.value = self.card_view
            return
        self.card_preferences.setdefault(row["id"], {})["view"] = view
        self.show_detail(row["full_name"])
        self.query_one("#reader", VerticalScroll).scroll_home(animate=False)

    def action_edit_host_notes(self) -> None:
        self.open_card_editor(initial_field="host_notes")

    def open_card_editor(self, *, initial_field: str = "hook") -> None:
        row = self.selected_row()
        if row is None:
            return
        repo_id, full_name = row["id"], row["full_name"]
        view = self.card_view
        cached = self.research_by_repo.get(repo_id)
        record = record_from_saved(str(cached["summary"] or "") if cached else "",
                                   cached["card_json"] if cached else None)
        draft = presentation.draft_from_rows(row, self.card_preferences.get(repo_id))

        def save_card(value: presentation.PresentationDraft | None) -> None:
            if value is None:
                return
            try:
                with session(self.config.database_path) as conn:
                    conn.execute("PRAGMA busy_timeout = 100")
                    conn.execute("BEGIN")
                    presentation.save_presentation_draft(conn, repo_id, value)
                    db.save_repo_card(conn, repo_id, view=view)
            except (sqlite3.Error, LookupError) as exc:
                self.notify_result(f"Could not save card: {exc}. Your draft is still open; retry Save or cancel.")
                self.push_screen(CardEditScreen(full_name, value, record, initial_field=initial_field), save_card)
                return
            self.load_rows()
            self.notify_result(f"Card saved for {full_name}.")

        self.push_screen(CardEditScreen(full_name, draft, record, initial_field=initial_field), save_card)

    def action_prepare(self) -> None:
        self.open_card_editor()

    def action_export_card(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        name = row["full_name"]
        selected_view = self.card_view

        def submit(request: ExportRequest) -> str:
            try:
                with session(self.config.database_path) as conn:
                    current = db.get_repo(conn, name)
                    rows = ([current] if current is not None else []) if request.scope == "selected" else list(export.iter_export_rows(conn))
                    if not rows:
                        raise ValueError("No repositories to export. Mark a repository for presentation with p.")
                    content = export.build_export(conn, rows, config=self.config, view=selected_view if request.scope == "selected" else None)
            except sqlite3.Error as exc:
                raise ValueError(f"Could not read the catalog: {exc}") from exc
            path = write_export_file(request.path, content, overwrite=request.overwrite,
                                     allowed_root=self.config.root if self.demo_mode else None,
                                     protected_path=self.config.database_path)
            return f"Exported {len(rows)} {'repository' if len(rows) == 1 else 'repositories'} to {path}"

        def done(message: str | None) -> None:
            if message:
                self.notify_result(message)

        self.push_screen(ExportScreen(name, self.config.exports_root / "rundown-export.md", submit, demo_mode=self.demo_mode), done)

    def action_sync(self) -> None:
        if self.sync_in_progress:
            self.notify_result("A GitHub star sync is already in progress.")
            return
        self.sync_in_progress = True
        self.notify_result("Loading starred repositories from GitHub…")
        self.sync_stars()

    @work(thread=True, exclusive=True, group="github-sync", exit_on_error=False)
    def sync_stars(self) -> None:
        try:
            repos = self.fetch_starred()
            with session(self.config.database_path) as conn:
                init_db(conn)
                for repo in repos:
                    db.upsert_repo(conn, repo)
                categories.classify_repos(conn)
        except Exception as exc:
            self.app.call_from_thread(self.finish_sync, None, str(exc))
            return
        self.app.call_from_thread(self.finish_sync, len(repos), None)

    def finish_sync(self, count: int | None, error: str | None) -> None:
        self.sync_in_progress = False
        if error is not None:
            self.notify_result(f"GitHub sync failed: {error}. Authenticate with `gh auth login`, then use Menu → Sync GitHub stars to retry.")
            return
        self.load_rows()
        self.notify_result(f"Synced {count} starred repositories." if self.rows else "GitHub returned no starred repositories. Star a repo on GitHub, then use Menu → Sync GitHub stars.")

    def action_open_wiki(self) -> None:
        row = self.selected_row()
        if row is not None and row["wiki_path"] and Path(row["wiki_path"]).is_file():
            self.open_external(row["wiki_path"], "saved research")

    def action_open_github(self) -> None:
        row = self.selected_row()
        if row is not None:
            self.open_external(row["url"], "GitHub")

    def open_external(self, target: str, label: str) -> None:
        if self.demo_mode:
            self.notify_result("External links are disabled in the offline demo.")
            return
        try:
            subprocess.run(["open", target], check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            self.notify_result(f"Could not open {label}: {exc}")
        else:
            self.notify_result(f"Opened {label}: {target}")

    def action_mark_present(self) -> None:
        full_name = self.selected_full_name()
        if full_name:
            with session(self.config.database_path) as conn:
                init_db(conn)
                row = db.get_repo(conn, full_name)
                if row is None:
                    self.notify_result(f"Unknown repository: {full_name}")
                    return
                current = row["decision"]
                if current == "present":
                    db.update_repo(conn, full_name, decision=None, status="new")
                    self.notify_result(f"Unmarked {full_name} from presentation.")
                else:
                    db.update_repo(conn, full_name, decision="present", status="present")
                    self.notify_result(f"Marked {full_name} for presentation. Run `rd export` to generate Markdown.")
            self.load_rows()
