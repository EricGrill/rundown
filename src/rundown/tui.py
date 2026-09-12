from __future__ import annotations

import sqlite3
import subprocess
from collections import deque
from collections.abc import Callable
from functools import partial
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Collapsible,
    DataTable,
    Footer,
    Header,
    Input,
    Markdown,
    Select,
    Static,
)

from . import categories, db, github, repo_ops, research
from .card_ui import CardDisclosure, CardSections, HostNotesScreen
from .cards import record_from_saved
from .config import AppConfig
from .db import init_db, list_repos, session


class RepositoryTable(DataTable):
    BINDINGS = [Binding("enter", "select_cursor", "Read")]


class RepositoryCommands(Provider):
    """The small set of actions that support browsing and research."""

    def commands(self):
        app = self.app
        assert isinstance(app, RundownApp)
        if app.selected_full_name():
            yield "Research selected repository", app.action_research_selected, "r · Reuse saved research or research this repo; clones automatically."
            yield "Refresh selected research", app.action_refresh_research, "Shift+R · Generate fresh research and fill missing card fields."
            yield "Switch research card view", app.action_switch_card, "v · Switch between Host brief and Research card using saved results."
            yield "Edit host notes", app.action_edit_host_notes, "n · Save your own notes independently of generated research."
            yield "Read selected repository", app.action_read_selected, "Enter · Focus the reader; use arrows or Page Down to scroll."
            yield "Open repository on GitHub", app.action_open_github, "Open the selected repository in your browser."
            row = app.selected_row()
            if row is not None and row["wiki_path"] and Path(row["wiki_path"]).is_file():
                yield "Open saved research file", app.action_open_wiki, "Open the existing Markdown wiki page."
        if app.selected_full_name():
            yield "Mark for presentation", app.action_mark_present, "p · Mark this repository for export."
        yield "Find repositories", app.action_find, "/ · Filter the list by repository name or description."
        yield "Filter by category", app.action_filter_category, "f · Choose one of five categories or show all repositories."
        yield "Classify starred repositories", app.action_classify, "Recompute the five categories locally, without AI calls."
        if not app.sync_in_progress:
            yield "Sync GitHub stars", app.action_sync, "Refresh your saved repository list from GitHub."
        yield "Quit", app.action_quit, "q · Close Rundown."

    async def discover(self) -> Hits:
        for label, action, help_text in self.commands():
            yield DiscoveryHit(label, action, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for label, action, help_text in self.commands():
            score = matcher.match(label)
            if score:
                yield Hit(score, matcher.highlight(label), action, help=help_text)


class RundownApp(App):
    TITLE = "Rundown"
    SUB_TITLE = "Browse · Research · Read"
    COMMANDS = {RepositoryCommands}
    CSS = """
    #body { height: 1fr; }
    #catalog { width: 46%; min-width: 36; }
    #search { margin: 0 1; }
    #category { margin: 0 1; }
    #catalog-title { height: 1; padding: 0 1; color: $text-muted; }
    #repos { height: 1fr; }
    #reader { width: 54%; padding: 1 2; border-left: solid $panel; }
    #reader:focus { border-left: solid $primary; }
    #detail { height: auto; margin-bottom: 1; }
    #card-toolbar { height: auto; }
    #card-view { width: 1fr; }
    #edit-notes { min-width: 14; width: auto; }
    #card-context { height: auto; color: $text-muted; margin: 1 0; }
    #host-notes { height: auto; }
    #host-notes-panel, #full-research { height: auto; margin: 0 0 1 0; padding: 0; border: none; }
    #research-content { margin: 0; padding: 0; }
    #research-content MarkdownH2 { color: $text; text-style: bold; }
    #status { height: auto; max-height: 3; padding: 0 1; color: $text-muted; background: $surface; }
    .compact #body { layout: vertical; }
    .compact #catalog { width: 100%; height: 45%; min-width: 0; }
    .compact #reader { width: 100%; height: 1fr; border-left: none; border-top: solid $panel; padding: 0 1; }
    .compact #reader:focus { border-top: solid $primary; }
    .compact.reading #catalog { display: none; }
    """
    BINDINGS = [
        Binding("slash", "find", "Find", key_display="/"),
        Binding("f", "filter_category", "Category"),
        Binding("enter", "read_selected", "Read"),
        Binding("r", "research_selected", "Research"),
        Binding("p", "mark_present", "Present"),
        Binding("R", "refresh_research", "Refresh", show=False),
        Binding("v", "switch_card", "View"),
        Binding("n", "edit_host_notes", "Notes", show=False),
        Binding("ctrl+p", "command_palette", "Menu", priority=True),
        Binding("q", "quit", "Quit"),
        Binding("escape", "back_to_list", show=False),
        Binding("ctrl+r", "sync", show=False),
    ]

    def __init__(
        self,
        config: AppConfig,
        fetch_starred: Callable[[], list[db.RepoInput]] | None = None,
    ):
        super().__init__()
        self.config = config
        self.fetch_starred = fetch_starred or (
            lambda: github.fetch_starred(
                include_private=self.config.github.include_private
            )
        )
        self.rows = []
        self.rows_by_full_name = {}
        self.research_by_repo = {}
        self.research_errors: dict[str, str] = {}
        self.sync_in_progress = False
        self.repo_action_in_progress = False
        self.active_repo_action: tuple[str, str] | None = None
        self.repo_action_queue: deque[tuple[str, str]] = deque()
        self.detail_full_name: str | None = None
        self.card_preferences: dict[int, dict] = {}
        self.card_view = config.cards.default_view

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="catalog"):
                yield Input(placeholder="Find a repository…", id="search")
                yield Select(
                    [("All categories", "all"), *((name, name) for name in categories.CATEGORIES)],
                    value="all", allow_blank=False, id="category",
                    tooltip="Filter by category · f",
                )
                yield Static("Repositories · newest first", id="catalog-title", markup=False)
                yield RepositoryTable(id="repos")
            with VerticalScroll(id="reader", can_focus=True):
                yield Static("Select a repository", id="detail", markup=False)
                with Horizontal(id="card-toolbar"):
                    yield Select([("Host brief", "host"), ("Research card", "research")],
                                 value=self.card_view, allow_blank=False, id="card-view",
                                 tooltip="Switch card view · v")
                    yield Button("Host notes", id="edit-notes", tooltip="Edit host notes · n")
                yield Static("", id="card-context", markup=False)
                yield CardSections(id="card-sections")
                with CardDisclosure(title="Host notes · n to edit", collapsed=True, id="host-notes-panel"):
                    yield Static("No host notes yet.", id="host-notes", markup=False)
                with CardDisclosure(title="Full research", collapsed=True, id="full-research"):
                    yield Markdown(id="research-content", open_links=False)
        yield Static("Select a repo · r researches · Enter reads · Ctrl+P opens the menu", id="status", markup=False)
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.set_class(self.size.width < 100, "compact")
        table = self.query_one("#repos", DataTable)
        table.cursor_type = "row"
        table.add_column("Repository", key="name", width=self.name_column_width())
        table.add_column("Research", key="research", width=16)
        self.load_rows()
        table.focus()
        for selector in self.query(Select):
            self.watch(selector, "expanded", partial(self.return_from_dropdown, selector), init=False)
        self.action_sync()

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

    def on_resize(self) -> None:
        self.set_class(self.size.width < 100, "compact")
        table = self.query_one("#repos", DataTable)
        if table.columns:
            table.columns[next(iter(table.columns))].width = self.name_column_width()
            table.refresh(layout=True)

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
            self.rows = list_repos(conn)
            self.research_by_repo = db.latest_successful_research_by_repo(conn)
            self.card_preferences = {
                int(preference["repo_id"]): dict(preference)
                for preference in conn.execute("SELECT * FROM repo_cards")
            }
        self.rows = [dict(row) for row in self.rows]
        for row in self.rows:
            if row["starred"] and row["category"] not in categories.CATEGORIES:
                row["category"] = categories.classify_repo(
                    row["full_name"], row["description"], row["language"], row["tags"],
                )
        self.rows.sort(key=lambda row: row["starred_at"] or "", reverse=True)
        self.rows_by_full_name = {row["full_name"]: row for row in self.rows}
        self.filter_rows(selected_full_name)

    def filter_rows(self, selected_full_name: str | None = None) -> None:
        table = self.query_one("#repos", DataTable)
        selected_full_name = selected_full_name or self.selected_full_name()
        query = self.query_one("#search", Input).value.strip().casefold()
        category = self.query_one("#category", Select).value
        visible = [
            row for row in self.rows
            if query in f"{row['full_name']} {row['description'] or ''}".casefold()
            and (category == "all" or row["category"] == category)
        ]
        with table.prevent(DataTable.RowHighlighted, DataTable.RowSelected):
            table.clear()
            for row in visible:
                table.add_row(row["full_name"], self.research_status(row), key=row["full_name"])
            names = [row["full_name"] for row in visible]
            if selected_full_name in names:
                table.move_cursor(row=names.index(selected_full_name))
            elif visible:
                table.move_cursor(row=0)
        self.query_one("#catalog-title", Static).update(f"{len(visible)} of {len(self.rows)} repositories · newest first")
        if visible:
            self.show_detail(self.selected_full_name())
        else:
            self.detail_full_name = None
            self.query_one("#detail", Static).update("No matching repositories.\n\nChange your search or category; press Esc to clear both filters." if self.rows else "No repositories yet.\n\nSync your GitHub stars from the menu.")
            self.query_one("#research-content", Markdown).update("")
            self.query_one("#card-sections", CardSections).entries = ()
            self.query_one("#card-context", Static).update("")
            self.query_one("#host-notes", Static).update("No repository selected.")
            self.query_one("#card-toolbar").disabled = True

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
            self.query_one("#search", Input).value = ""
            self.query_one("#category", Select).value = "all"
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
        self.card_view = preference.get("view") or self.config.cards.default_view
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
        if error:
            self.query_one("#full-research", Collapsible).collapsed = False

    def render_card(self, row, cached, *, changed_repo: bool = False) -> None:
        summary = str(cached["summary"] or "") if cached else ""
        # sqlite3.Row membership searches values, so explicitly inspect column keys.
        card_json = cached["card_json"] if cached and "card_json" in cached.keys() else None  # noqa: SIM118
        record = record_from_saved(summary, card_json)
        template = getattr(self.config.cards, self.card_view)
        missing = "Unknown from the available research."
        self.query_one("#card-sections", CardSections).entries = tuple(
            (section_id, record.sections.get(section_id) or missing, template.word_limit)
            for section_id in template.sections
        ) if cached else ()
        if self.card_view == "host":
            context = (
                f"Target: {self.config.cards.duration_seconds} seconds · Demo not rehearsed\n"
                f"Audience: {self.config.cards.audience}"
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
        row = self.selected_row()
        if row is None:
            return
        repo_id, full_name = row["id"], row["full_name"]
        view = self.card_view
        notes = self.card_preferences.get(repo_id, {}).get("host_notes", "")

        def save_notes(value: str | None) -> None:
            if value is None:
                return
            try:
                with session(self.config.database_path) as conn:
                    conn.execute("PRAGMA busy_timeout = 100")
                    db.save_repo_card(conn, repo_id, view=view, host_notes=value)
            except sqlite3.Error as exc:
                self.notify_result(f"Could not save notes: {exc}. Your draft is still open; retry Save or cancel.")
                self.push_screen(HostNotesScreen(full_name, value), save_notes)
                return
            self.card_preferences.setdefault(repo_id, {})["host_notes"] = value
            self.card_preferences[repo_id]["view"] = view
            if self.selected_full_name() == full_name:
                self.query_one("#host-notes", Static).update(value or "No host notes yet.")
                self.query_one("#host-notes-panel", Collapsible).collapsed = not bool(value)
            self.notify_result(f"Host notes saved for {full_name}.")

        self.push_screen(HostNotesScreen(full_name, notes), save_notes)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-notes":
            self.action_edit_host_notes()

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

    def action_open_wiki(self) -> None:
        row = self.selected_row()
        if row is not None and row["wiki_path"] and Path(row["wiki_path"]).is_file():
            self.open_external(row["wiki_path"], "saved research")

    def action_open_github(self) -> None:
        row = self.selected_row()
        if row is not None:
            self.open_external(row["url"], "GitHub")

    def open_external(self, target: str, label: str) -> None:
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

    def action_research_selected(self) -> None:
        full_name = self.selected_full_name()
        if full_name:
            action = "refresh" if full_name in self.research_errors else "research"
            self.enqueue_repo_action(action, full_name)

    def action_refresh_research(self) -> None:
        full_name = self.selected_full_name()
        if full_name:
            self.enqueue_repo_action("refresh", full_name)

    def enqueue_repo_action(self, action: str, full_name: str) -> None:
        request = (action, full_name)
        if self.active_repo_action and full_name == self.active_repo_action[1]:
            self.notify_result(f"Research for {full_name} is already running.")
            return
        if any(name == full_name for _, name in self.repo_action_queue):
            self.notify_result(f"Research for {full_name} is already queued.")
            return
        if self.repo_action_in_progress:
            self.repo_action_queue.append(request)
            self.load_rows()
            self.notify_result(f"Queued research for {full_name} · position {len(self.repo_action_queue)}")
            return
        self.start_repo_action(action, full_name)

    def start_repo_action(self, action: str, full_name: str) -> None:
        self.repo_action_in_progress = True
        self.active_repo_action = (action, full_name)
        self.research_errors.pop(full_name, None)
        self.load_rows()
        self.notify_result(f"Researching {full_name}… Saved results are reused; cloning is automatic when needed.")
        self.research_selected(full_name, force=action == "refresh")

    def start_next_repo_action(self) -> None:
        if self.repo_action_queue:
            self.start_repo_action(*self.repo_action_queue.popleft())

    @work(thread=True, group="repo-action", exit_on_error=False)
    def research_selected(self, full_name: str, *, force: bool = False) -> None:
        clone_status = "already_cloned"
        try:
            with session(self.config.database_path) as conn:
                init_db(conn)
                row = db.get_repo(conn, full_name)
                if row is None:
                    raise ValueError(f"Unknown repository: {full_name}")
                cached = None if force else research.load_cached_repository_research(
                    self.config,
                    conn,
                    row,
                )
                if cached is not None:
                    self.app.call_from_thread(
                        self.finish_research,
                        full_name,
                        "cached",
                        cached,
                    )
                    return
                clone_status, clone_message = repo_ops.clone_repo(
                    self.config,
                    conn,
                    full_name,
                )
                if clone_status == "failed":
                    self.app.call_from_thread(
                        self.finish_research,
                        full_name,
                        "failed",
                        f"Research stopped because the repository could not be cloned.\n\n{clone_message}",
                    )
                    return
                if force:
                    status, summary = research.run_repository_research(self.config, conn, full_name, force=True)
                else:
                    status, summary = research.run_repository_research(self.config, conn, full_name)
        except Exception as exc:
            status, summary = "failed", f"Research failed for {full_name}: {exc}"
        if clone_status == "cloned":
            summary = f"Automatically cloned {full_name} before research.\n\n{summary}"
        self.app.call_from_thread(
            self.finish_research,
            full_name,
            status,
            summary,
        )

    def finish_research(self, full_name: str, status: str, summary: str) -> None:
        self.repo_action_in_progress = False
        self.active_repo_action = None
        if status == "failed":
            self.research_errors[full_name] = summary
        else:
            self.research_errors.pop(full_name, None)
        self.load_rows()
        self.notify_result(f"Research for {full_name}: {status}")
        if status == "failed":
            self.notify_result(f"Research for {full_name} failed. Select it and press Enter for details; r retries.")
        elif self.selected_full_name() == full_name:
            self.query_one("#research-content", Markdown).update(summary)
        if self.repo_action_queue:
            self.call_after_refresh(self.start_next_repo_action)
