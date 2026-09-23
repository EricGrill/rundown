from __future__ import annotations

from collections import deque
from collections.abc import Callable
from functools import partial
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Markdown,
    Select,
    Static,
)

from . import categories, db, github
from .card_ui import CardDisclosure, CardSections
from .config import AppConfig
from .catalog import CatalogView, SORTS
from .jobs import ResearchJob
from .tui_browse import BrowseMixin
from .tui_cards import CardsMixin
from .tui_jobs import JobsMixin


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


class RundownApp(JobsMixin, CardsMixin, BrowseMixin, App):
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
