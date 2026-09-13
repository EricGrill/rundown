from __future__ import annotations

import sqlite3
import subprocess
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from time import monotonic

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

from . import categories, db, export, github, history, preferences, presentation, research_workflow
from .card_ui import CardDisclosure, CardSections
from .card_edit_ui import CardEditScreen
from .cards import record_from_saved
from .config import AppConfig
from .catalog import CatalogView, SORTS, filter_sort_repos
from .catalog_ui import CatalogResult, CatalogScreen
from .db import init_db, list_repos, session
from .export_ui import ExportRequest, ExportScreen, write_export_file
from .jobs import ResearchJob
from .jobs_ui import JobsScreen
from .processes import OperationCancelled, check_cancelled
from .history_ui import HistoryScreen
from .template_ui import TemplateResult, TemplateScreen


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
            yield "Edit card template", app.action_edit_template, "t · Presets, sections, preview and saved defaults."
            yield "Use global card template", app.action_reset_template, "Remove this repository's template override."
            yield "Research provenance and changes", app.action_show_history, "h · Sources, provider, commit and changes since the previous report."
            yield "Prepare card", app.action_prepare, "e · Edit your presentation overrides and notes together."
            yield "Export card", app.action_export_card, "x · Export the selected card or marked repositories to Markdown."
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
        yield "Research jobs", app.action_show_jobs, "j · Inspect progress, cancel a job, or retry a failure."
        yield "Catalog filters and saved views", app.action_catalog_view, "g · Filter by research status, sort, or save a named view."
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
    SUB_TITLE = "Browse · Read · Prepare · Export"
    COMMANDS = {RepositoryCommands}
    CSS = """
    #workflow-actions { height: 3; }
    #workflow-actions Button { width: 1fr; min-width: 12; }
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
    #card-context { height: auto; color: $text-muted; margin: 1 0; }
    #host-notes { height: auto; }
    #host-notes-panel, #full-research { height: auto; margin: 0 0 1 0; padding: 0; border: none; }
    #research-content { margin: 0; padding: 0; }
    #research-content MarkdownH2 { color: $text; text-style: bold; }
    #status { height: auto; max-height: 3; padding: 0 1; color: $text-muted; background: $surface; }
    #job-summary { height: auto; max-height: 2; padding: 0 1; color: $text-muted; }
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
        Binding("j", "show_jobs", "Jobs", show=False),
        Binding("e", "prepare", "Prepare", show=False),
        Binding("x", "export_card", "Export", show=False),
        Binding("t", "edit_template", "Templates", show=False),
        Binding("g", "catalog_view", "Views", show=False),
        Binding("h", "show_history", "History", show=False),
        Binding("ctrl+p", "command_palette", "Menu", priority=True),
        Binding("q", "quit", "Quit"),
        Binding("escape", "back_to_list", show=False),
        Binding("ctrl+r", "sync", show=False),
    ]

    def __init__(
        self,
        config: AppConfig,
        fetch_starred: Callable[[], list[db.RepoInput]] | None = None,
        *, demo_mode: bool = False,
    ):
        super().__init__()
        self.config = config
        self.demo_mode = demo_mode
        self.research_jobs: list[ResearchJob] = []
        self.active_job: ResearchJob | None = None
        self._closing = False
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
        self.effective_card_settings = {}
        self.catalog_view = CatalogView(sort=config.tui.default_sort if config.tui.default_sort in SORTS else "starred_at")

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="workflow-actions"):
            yield Button("Browse", id="workflow-browse")
            yield Button("Read · Enter", id="workflow-read", disabled=True)
            yield Button("Prepare · e", id="workflow-prepare", disabled=True)
            yield Button("Export · x", id="workflow-export", disabled=True)
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
                yield Static("", id="card-context", markup=False)
                yield CardSections(id="card-sections")
                yield Markdown(id="human-fields", open_links=False)
                with CardDisclosure(title="Host notes · n to edit", collapsed=True, id="host-notes-panel"):
                    yield Static("No host notes yet.", id="host-notes", markup=False)
                with CardDisclosure(title="Full research", collapsed=True, id="full-research"):
                    yield Markdown(id="research-content", open_links=False)
        yield Static("Jobs: none · j to inspect", id="job-summary", markup=False)
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
        self.update_job_summary()
        self.set_interval(1, self.update_job_summary)

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

    def action_browse(self) -> None:
        self.remove_class("reading")
        self.query_one("#repos", DataTable).focus()

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
            reports = [dict(report) for report in history.research_history(conn, row["id"])]
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
