"""RundownApp mixin: repository catalog listing, filtering, and detail/card rendering.

Methods here assume the mixed-in class also provides RundownApp's Textual App
behavior (query_one, push_screen, ...) and instance state (self.config,
self.rows, ...), so attribute access on self is intentionally not statically
verifiable from this file alone.
"""
# pyright: reportAttributeAccessIssue=false
from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.widgets import Button, Collapsible, DataTable, Input, Markdown, Select, Static

from . import categories, db, preferences, presentation
from .card_ui import CardSections
from .cards import record_from_saved
from .catalog import CatalogView, filter_sort_repos
from .db import init_db, list_repos, session

if TYPE_CHECKING:
    from .config import AppConfig


class BrowseMixin:
    # Declared for type checking only; set by RundownApp.__init__.
    config: "AppConfig"

    def on_resize(self) -> None:
        self.set_class(self.size.width < 100, "compact")
        table = self.query_one("#repos", DataTable)
        if table.columns:
            table.columns[next(iter(table.columns))].width = self.name_column_width()
            table.refresh(layout=True)

    def return_from_dropdown(self, selector: Select, expanded: bool) -> None:
        if expanded:
            return

        def restore_focus() -> None:
            # Select restores its own focus when it closes. Hand navigation back
            # after that update, without stealing focus from a click elsewhere.
            if not selector.expanded and selector.has_focus_within:
                target = "#repos" if selector.id == "category" else "#reader"
                self.query_one(target).focus()

        self.call_after_refresh(restore_focus)

    def name_column_width(self) -> int:
        catalog_width = self.size.width if self.size.width < 100 else int(self.size.width * .46)
        return max(12, catalog_width - 23)

    def load_rows(self, selected_full_name: str | None = None) -> None:
        selected_full_name = selected_full_name or self.selected_full_name()
        with session(self.config.database_path) as conn:
            init_db(conn)
            # Research may hold a write transaction. Keep cached browsing responsive.
            conn.execute("PRAGMA busy_timeout = 100")
            try:
                categories.classify_repos(conn)
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
                conn.rollback()
            self.rows = [dict(row) for row in list_repos(conn)]
            self.research_by_repo = {key: dict(row) for key, row in db.latest_successful_research_by_repo(conn).items()}
            self.card_preferences = {
                int(preference["repo_id"]): dict(preference)
                for preference in conn.execute("SELECT * FROM repo_cards")
            }
            self.effective_card_settings = preferences.load_card_settings(conn, self.config.cards, [row["id"] for row in self.rows])
        for row in self.rows:
            if row["starred"] and row["category"] not in categories.CATEGORIES:
                row["category"] = categories.classify_repo(
                    row["full_name"], row["description"], row["language"], row["tags"],
                )
        self.rows.sort(key=lambda row: row["starred_at"] or "", reverse=True)
        self.rows_by_full_name = {row["full_name"]: row for row in self.rows}
        self.filter_rows(selected_full_name)
        self.update_workflow_actions()

    def update_workflow_actions(self) -> None:
        row = self.selected_row()
        for action in ("read", "prepare", "export"):
            self.query_one(f"#workflow-{action}", Button).disabled = row is None
        button = self.query_one("#workflow-read", Button)
        if row and row["id"] not in self.research_by_repo:
            button.label = "Research · r"
        else:
            button.label = "Read · Enter"

    def filter_rows(self, selected_full_name: str | None = None) -> None:
        table = self.query_one("#repos", DataTable)
        selected_full_name = selected_full_name or self.selected_full_name()
        query = self.query_one("#search", Input).value.strip().casefold()
        category = self.query_one("#category", Select).value
        self.catalog_view = replace(self.catalog_view, query=query, category=None if category == "all" else str(category))
        visible = filter_sort_repos(self.rows, self.research_by_repo, self.catalog_view)
        with table.prevent(DataTable.RowHighlighted, DataTable.RowSelected):
            table.clear()
            for row in visible:
                table.add_row(row["full_name"], self.research_status(row), key=row["full_name"])
            names = [row["full_name"] for row in visible]
            if selected_full_name in names:
                table.move_cursor(row=names.index(selected_full_name))
            elif visible:
                table.move_cursor(row=0)
        view_label = self.catalog_view.name or self.catalog_view.research_filter.replace("_", " ")
        sort_label = "newest first" if self.catalog_view.sort == "starred_at" else self.catalog_view.sort.replace("_", " ")
        self.query_one("#catalog-title", Static).update(f"{len(visible)} of {len(self.rows)} · {view_label} · {sort_label} · g views")
        if visible:
            self.show_detail(self.selected_full_name())
        else:
            self.detail_full_name = None
            self.query_one("#detail", Static).update("No matching repositories.\n\nChange your search or category; press Esc to clear both filters." if self.rows else "No repositories yet.\n\nSync your GitHub stars from the menu.")
            self.query_one("#research-content", Markdown).update("")
            self.query_one("#card-sections", CardSections).entries = ()
            self.query_one("#card-context", Static).update("")
            self.query_one("#host-notes", Static).update("No repository selected.")
            self.query_one("#human-fields", Markdown).update("")
            self.query_one("#card-toolbar").disabled = True
        self.update_workflow_actions()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.filter_rows()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#repos", DataTable).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "category":
            self.filter_rows()
        elif (
            event.select.id == "card-view"
            and event.value in ("host", "research")
            and event.value == event.select.value
        ):
            self.set_card_view(str(event.value))

    def action_filter_category(self) -> None:
        self.remove_class("reading")
        selector = self.query_one("#category", Select)
        selector.focus()
        selector.action_show_overlay()

    def action_classify(self) -> None:
        try:
            with session(self.config.database_path) as conn:
                conn.execute("PRAGMA busy_timeout = 100")
                init_db(conn)
                counts = categories.classify_repos(conn, force=True)
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            self.notify_result("Database is busy with another job. Retry Classify starred repositories when it finishes.")
            return
        self.load_rows()
        self.notify_result(f"Classified {sum(counts.values())} starred repositories into 5 categories. Press f to filter.")

    def action_find(self) -> None:
        self.remove_class("reading")
        self.query_one("#search", Input).focus()

    def action_back_to_list(self) -> None:
        was_reading = self.has_class("reading")
        self.remove_class("reading")
        if not was_reading:
            self.catalog_view = CatalogView()
            self.query_one("#search", Input).value = ""
            self.query_one("#category", Select).value = "all"
            self.filter_rows()
        self.query_one("#repos", DataTable).focus()

    def action_read_selected(self) -> None:
        if self.selected_full_name():
            self.add_class("reading")
            self.query_one("#reader", VerticalScroll).focus()

    @staticmethod
    def format_date(value: str | None) -> str:
        return value[:10] if value else "Unknown"

    @staticmethod
    def is_cloned(row) -> bool:
        return bool(row["local_path"]) and Path(row["local_path"]).exists()

    def queued_position(self, action: str, full_name: str) -> int | None:
        for position, request in enumerate(self.repo_action_queue, start=1):
            if request == (action, full_name):
                return position
        return None

    def research_status(self, row) -> str:
        full_name = row["full_name"]
        if self.active_repo_action and self.active_repo_action[1] == full_name:
            return "Researching"
        position = self.queued_position("research", full_name) or self.queued_position("refresh", full_name)
        if position is not None:
            return f"Queued #{position}"
        if full_name in self.research_errors:
            return "Failed · retry r"
        return "Saved" if row["id"] in self.research_by_repo else "Not researched"

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value == self.selected_full_name():
            self.show_detail(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.show_detail(event.row_key.value)
        self.action_read_selected()

    def show_detail(self, key: str | None) -> None:
        row = self.selected_row(key)
        if row is None:
            return
        reader = self.query_one("#reader", VerticalScroll)
        changed_repo = key != self.detail_full_name
        if changed_repo:
            reader.scroll_home(animate=False)
        self.detail_full_name = key
        self.query_one("#card-toolbar").disabled = False
        preference = self.card_preferences.get(row["id"], {})
        settings = self.effective_card_settings.get(row["id"], self.config.cards)
        saved_view = preference.get("view")
        self.card_view = saved_view if saved_view in {"host", "research"} else settings.default_view
        selector = self.query_one("#card-view", Select)
        with selector.prevent(Select.Changed):
            selector.value = self.card_view
        cached = self.research_by_repo.get(row["id"])
        lines = [row["full_name"], row["description"] or "No description provided.", "", f"Added: {self.format_date(row['starred_at'])} · {row['language'] or 'Language not listed'}"]
        lines.append(f"Category: {row['category'] or 'Not classified'}")
        lines.append("Local copy: Cloned" if self.is_cloned(row) else "Local copy: Not cloned · created automatically when needed")
        if cached:
            lines.append(f"Saved research · {self.format_date(cached['timestamp'])}")
        else:
            lines.extend(["", "Not researched yet. Press r to learn what this repo does and why you might use it.", "Research uses your configured AI provider; saved results are reused."])
        self.query_one("#detail", Static).update("\n".join(lines))
        summary = cached["summary"] if cached else ""
        error = self.research_errors.get(row["full_name"])
        if error:
            previous = f"\n\n---\n\n## Previously saved research\n\n{summary}" if summary else ""
            summary = f"## Research failed\n\n{error}\n\nPress r to retry.{previous}"
        content = self.query_one("#research-content", Markdown)
        if content.source != summary:
            content.update(summary)
        self.render_card(row, cached, changed_repo=changed_repo)
        self.update_workflow_actions()
        if error:
            self.query_one("#full-research", Collapsible).collapsed = False

    def render_card(self, row, cached, *, changed_repo: bool = False) -> None:
        summary = str(cached["summary"] or "") if cached else ""
        # sqlite3.Row membership searches values, so explicitly inspect column keys.
        card_json = cached["card_json"] if cached and "card_json" in cached.keys() else None  # noqa: SIM118
        record = record_from_saved(summary, card_json)
        settings = self.effective_card_settings.get(row["id"], self.config.cards)
        template = getattr(settings, self.card_view)
        missing = "Unknown from the available research."
        entries = []
        rendered_fields: set[str] = set()
        for section_id in template.sections:
            section = presentation.effective_section(row, record, section_id)
            if cached or section.content:
                entries.append((section_id, section.content or missing, template.word_limit))
                rendered_fields.update(section.overridden_fields)
        self.query_one("#card-sections", CardSections).entries = tuple(entries)
        extra = [f"### {field.label} (your override)\n\n{field.value}"
                 for field in presentation.supplemental_human_fields(row, rendered_fields)]
        if row["notes"]:
            extra.append(f"### Repository notes\n\n{row['notes']}")
        self.query_one("#human-fields", Markdown).update("\n\n".join(extra))
        if self.card_view == "host":
            context = (
                f"Target: {settings.duration_seconds} seconds · Demo not rehearsed\n"
                f"Audience: {settings.audience}"
            )
        else:
            context = "Research card · Expand long sections for the complete findings."
        if cached:
            context += "\nGenerated research · Source references are not independently verified."
            if not card_json and self.card_view == "host":
                context += "\nOlder report · Shift+R can generate the missing show details."
        else:
            context += "\nResearch this repository to populate the card."
        self.query_one("#card-context", Static).update(context)
        notes = self.card_preferences.get(row["id"], {}).get("host_notes", "")
        self.query_one("#host-notes", Static).update(notes or "No host notes yet. Press n to add your own cues.")
        if changed_repo:
            self.query_one("#host-notes-panel", Collapsible).collapsed = not bool(notes)
            # Unrecognized legacy reports stay visible instead of becoming empty cards.
            self.query_one("#full-research", Collapsible).collapsed = bool(record.sections) or not bool(summary)

    def selected_row(self, key: str | None = None):
        if key is None:
            table = self.query_one("#repos", DataTable)
            if not table.row_count:
                return None
            key = str(table.get_row_at(table.cursor_row)[0])
        return self.rows_by_full_name.get(key)

    def selected_full_name(self) -> str | None:
        row = self.selected_row()
        return row["full_name"] if row is not None else None

    def notify_result(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def action_browse(self) -> None:
        self.remove_class("reading")
        self.query_one("#repos", DataTable).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workflow-browse":
            self.action_browse()
        elif event.button.id == "workflow-read":
            row = self.selected_row()
            if row and row["id"] not in self.research_by_repo:
                self.action_research_selected()
            else:
                self.action_read_selected()
        elif event.button.id == "workflow-prepare":
            self.action_prepare()
        elif event.button.id == "workflow-export":
            self.action_export_card()
