"""Textual TUI for Rundown."""

import subprocess
import sys
import webbrowser
from datetime import datetime

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TextArea,
    Button,
    Select,
)
from textual.message import Message

from .config import Config
from .database import Database
from .models import Repo, Status
from .scoring import calculate_score


class EditCardScreen(ModalScreen[dict | None]):
    """Modal screen for editing card fields."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]
    
    def __init__(self, repo: Repo):
        super().__init__()
        self.repo = repo
    
    def compose(self) -> ComposeResult:
        with Container(id="edit-dialog"):
            yield Label(f"Edit Card: {self.repo.full_name}", id="edit-title")
            
            yield Label("Hook (one-liner pitch):")
            yield Input(value=self.repo.hook, id="hook-input", placeholder="What makes this interesting?")
            
            yield Label("Who's it for:")
            yield Input(value=self.repo.who_for, id="who-for-input", placeholder="Target audience")
            
            yield Label("Problem it solves:")
            yield Input(value=self.repo.problem, id="problem-input", placeholder="Pain point addressed")
            
            yield Label("Why now:")
            yield Input(value=self.repo.why_now, id="why-now-input", placeholder="Timing/relevance")
            
            yield Label("Demo path:")
            yield Input(value=self.repo.demo_path, id="demo-path-input", placeholder="URL or local path")
            
            yield Label("Flags (comma-separated):")
            yield Input(value=", ".join(self.repo.flags), id="flags-input", placeholder="warning, beta, sponsor")
            
            yield Label("Notes:")
            yield TextArea(self.repo.notes, id="notes-input")
            
            with Horizontal(id="edit-buttons"):
                yield Button("Save (Ctrl+S)", variant="primary", id="save-btn")
                yield Button("Cancel (Esc)", id="cancel-btn")
    
    def action_cancel(self) -> None:
        self.dismiss(None)
    
    def action_save(self) -> None:
        self._do_save()
    
    @on(Button.Pressed, "#save-btn")
    def on_save_pressed(self) -> None:
        self._do_save()
    
    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self) -> None:
        self.dismiss(None)
    
    def _do_save(self) -> None:
        hook = self.query_one("#hook-input", Input).value
        who_for = self.query_one("#who-for-input", Input).value
        problem = self.query_one("#problem-input", Input).value
        why_now = self.query_one("#why-now-input", Input).value
        demo_path = self.query_one("#demo-path-input", Input).value
        flags_str = self.query_one("#flags-input", Input).value
        notes = self.query_one("#notes-input", TextArea).text
        
        flags = [f.strip() for f in flags_str.split(",") if f.strip()]
        
        self.dismiss({
            "hook": hook,
            "who_for": who_for,
            "problem": problem,
            "why_now": why_now,
            "demo_path": demo_path,
            "flags": flags,
            "notes": notes,
        })


class HelpScreen(ModalScreen):
    """Help screen showing keybindings."""
    
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]
    
    def compose(self) -> ComposeResult:
        help_text = """
[bold cyan]Rundown Keyboard Shortcuts[/bold cyan]

[bold]Navigation[/bold]
  [yellow]↑/↓, j/k[/yellow]     Move selection up/down
  [yellow]Home/End[/yellow]     Jump to first/last
  [yellow]PgUp/PgDn[/yellow]    Page up/down

[bold]Status Changes[/bold]
  [yellow]i[/yellow]            Set to [magenta]inbox[/magenta]
  [yellow]s[/yellow]            Set to [green]shortlist[/green]
  [yellow]p[/yellow]            Set to [cyan]present[/cyan]
  [yellow]h[/yellow]            Set to [yellow]hold[/yellow]
  [yellow]x[/yellow]            Set to [red]skip[/red]

[bold]Actions[/bold]
  [yellow]Enter[/yellow]        View details
  [yellow]e[/yellow]            Edit card
  [yellow]o[/yellow]            Open in browser
  [yellow]r[/yellow]            Refresh data
  [yellow]+/-[/yellow]          Boost score +1/-1
  [yellow]=[/yellow]            Reset boost to 0

[bold]Filtering[/bold]
  [yellow]/[/yellow]            Focus search
  [yellow]1-5[/yellow]          Filter by status
  [yellow]0[/yellow]            Show all

[bold]Other[/bold]
  [yellow]?[/yellow]            Toggle this help
  [yellow]q[/yellow]            Quit

Press [yellow]Esc[/yellow] or [yellow]q[/yellow] to close this help.
"""
        with Container(id="help-dialog"):
            yield Static(help_text, id="help-content")


class RundownApp(App):
    """The main Rundown TUI application."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    Header {
        background: #1e3a5f;
        color: #e0e0e0;
    }
    
    Footer {
        background: #1a1a2e;
    }
    
    #main-container {
        layout: horizontal;
    }
    
    #list-panel {
        width: 60%;
        height: 100%;
        border: tall #3a506b;
        background: #0f0f1a;
    }
    
    #detail-panel {
        width: 40%;
        height: 100%;
        border: tall #3a506b;
        background: #16162a;
        padding: 1 2;
    }
    
    #status-bar {
        height: 1;
        background: #1a1a2e;
        color: #a0a0a0;
        padding: 0 1;
    }
    
    #search-container {
        height: 3;
        padding: 0 1;
        background: #0f0f1a;
    }
    
    #search-input {
        width: 1fr;
        background: #1a1a2e;
        border: tall #3a506b;
    }
    
    #search-input:focus {
        border: tall #5bc0be;
    }
    
    #filter-status {
        width: 22;
        margin-left: 1;
        background: #1a1a2e;
    }
    
    DataTable {
        height: 1fr;
        background: #0f0f1a;
    }
    
    DataTable > .datatable--header {
        background: #1e3a5f;
        color: #e0e0e0;
        text-style: bold;
    }
    
    DataTable > .datatable--cursor {
        background: #3a506b;
        color: #ffffff;
    }
    
    DataTable > .datatable--hover {
        background: #252545;
    }
    
    #detail-content {
        height: 1fr;
        overflow-y: auto;
        padding: 0;
    }
    
    .detail-section {
        margin-bottom: 1;
    }
    
    .detail-label {
        color: #6fffe9;
    }
    
    .detail-value {
        color: #e0e0e0;
    }
    
    .score-high {
        color: #5bc0be;
        text-style: bold;
    }
    
    .score-medium {
        color: #ffc857;
    }
    
    .score-low {
        color: #e63946;
    }
    
    #edit-dialog {
        width: 80;
        height: auto;
        max-height: 90%;
        background: #16162a;
        border: thick #5bc0be;
        padding: 1 2;
    }
    
    #edit-dialog Label {
        margin-top: 1;
        margin-bottom: 0;
        color: #6fffe9;
    }
    
    #edit-dialog Input {
        width: 100%;
        background: #1a1a2e;
        border: tall #3a506b;
    }
    
    #edit-dialog Input:focus {
        border: tall #5bc0be;
    }
    
    #edit-dialog TextArea {
        height: 5;
        width: 100%;
        background: #1a1a2e;
        border: tall #3a506b;
    }
    
    #edit-dialog TextArea:focus {
        border: tall #5bc0be;
    }
    
    #edit-title {
        text-style: bold;
        color: #5bc0be;
        margin-bottom: 1;
    }
    
    #edit-buttons {
        margin-top: 2;
        height: 3;
        align: center middle;
    }
    
    #edit-buttons Button {
        margin: 0 1;
    }
    
    Button {
        background: #3a506b;
        color: #e0e0e0;
        border: none;
    }
    
    Button:hover {
        background: #5bc0be;
        color: #0f0f1a;
    }
    
    Button.-primary {
        background: #5bc0be;
        color: #0f0f1a;
        text-style: bold;
    }
    
    #help-dialog {
        width: 65;
        height: auto;
        max-height: 85%;
        background: #16162a;
        border: thick #6fffe9;
        padding: 2;
    }
    
    #help-content {
        height: auto;
        color: #e0e0e0;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("?", "help", "Help"),
        Binding("r", "refresh", "Refresh"),
        Binding("o", "open_browser", "Open"),
        Binding("e", "edit_card", "Edit"),
        Binding("i", "status_inbox", "Inbox", show=False),
        Binding("s", "status_shortlist", "Shortlist", show=False),
        Binding("p", "status_present", "Present", show=False),
        Binding("h", "status_hold", "Hold", show=False),
        Binding("x", "status_skip", "Skip", show=False),
        Binding("plus", "boost_up", "+Boost", show=False),
        Binding("minus", "boost_down", "-Boost", show=False),
        Binding("equals", "boost_reset", "=Reset", show=False),
        Binding("slash", "focus_search", "Search"),
        Binding("1", "filter_inbox", show=False),
        Binding("2", "filter_shortlist", show=False),
        Binding("3", "filter_present", show=False),
        Binding("4", "filter_hold", show=False),
        Binding("5", "filter_skip", show=False),
        Binding("0", "filter_all", show=False),
    ]
    
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.db = Database(config.db_path)
        self.repos: list[Repo] = []
        self.filtered_repos: list[Repo] = []
        self.selected_repo: Repo | None = None
        self.filter_status: Status | None = None
        self.search_query: str = ""
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Horizontal(id="search-container"):
            yield Input(placeholder="Search repos...", id="search-input")
            yield Select(
                [(s.value.title(), s.value) for s in [None] + list(Status)],
                value=Select.BLANK,
                prompt="All",
                id="filter-status",
                allow_blank=True,
            )
        
        with Horizontal(id="main-container"):
            with Vertical(id="list-panel"):
                yield DataTable(id="repo-table", cursor_type="row")
            
            with Vertical(id="detail-panel"):
                yield Static("Select a repo to view details", id="detail-content")
        
        yield Static("", id="status-bar")
        yield Footer()
    
    def on_mount(self) -> None:
        self.title = "Rundown"
        self.sub_title = "Rank and present your best repos"
        
        table = self.query_one("#repo-table", DataTable)
        table.add_column("Score", width=6)
        table.add_column("Repository", width=30)
        table.add_column("Status", width=10)
        table.add_column("Language", width=12)
        table.add_column("Stars", width=8)
        table.add_column("Pushed", width=10)
        
        self._load_repos()
        self._update_table()
    
    def _load_repos(self) -> None:
        self.repos = self.db.list_repos(order_by="present_score DESC")
        self._apply_filters()
    
    def _apply_filters(self) -> None:
        repos = self.repos
        
        if self.filter_status:
            repos = [r for r in repos if r.status == self.filter_status]
        
        if self.search_query:
            q = self.search_query.lower()
            repos = [
                r for r in repos
                if q in r.full_name.lower()
                or q in (r.description or "").lower()
                or q in (r.language or "").lower()
                or any(q in t.lower() for t in r.topics)
            ]
        
        self.filtered_repos = repos
    
    def _update_table(self) -> None:
        table = self.query_one("#repo-table", DataTable)
        table.clear()
        
        for repo in self.filtered_repos:
            score_text = Text(f"{repo.present_score:.0f}")
            if repo.present_score >= 70:
                score_text.stylize("bold green")
            elif repo.present_score >= 40:
                score_text.stylize("yellow")
            else:
                score_text.stylize("red")
            
            status_text = Text(repo.status.value)
            status_colors = {
                Status.INBOX: "white",
                Status.SHORTLIST: "green",
                Status.PRESENT: "cyan bold",
                Status.HOLD: "yellow",
                Status.SKIP: "red dim",
            }
            status_text.stylize(status_colors.get(repo.status, "white"))
            
            pushed = ""
            if repo.pushed_at:
                days = (datetime.now() - repo.pushed_at.replace(tzinfo=None)).days
                if days == 0:
                    pushed = "today"
                elif days == 1:
                    pushed = "yesterday"
                elif days < 30:
                    pushed = f"{days}d ago"
                elif days < 365:
                    pushed = f"{days // 30}mo ago"
                else:
                    pushed = f"{days // 365}y ago"
            
            table.add_row(
                score_text,
                repo.full_name,
                status_text,
                repo.language or "-",
                f"{repo.stars:,}" if repo.stars else "-",
                pushed,
                key=str(repo.id),
            )
        
        self._update_status_bar()
    
    def _update_status_bar(self) -> None:
        counts = self.db.count_by_status()
        total = sum(counts.values())
        
        parts = [f"Total: {total}"]
        for status in Status:
            count = counts[status]
            if count > 0:
                parts.append(f"{status.value}: {count}")
        
        if self.filter_status:
            parts.append(f"[Filter: {self.filter_status.value}]")
        if self.search_query:
            parts.append(f"[Search: {self.search_query}]")
        
        status_bar = self.query_one("#status-bar", Static)
        status_bar.update(" | ".join(parts))
    
    def _update_detail(self) -> None:
        detail = self.query_one("#detail-content", Static)
        
        if not self.selected_repo:
            detail.update("Select a repo to view details")
            return
        
        repo = self.selected_repo
        lines = []
        
        lines.append(f"[bold cyan]{repo.full_name}[/bold cyan]")
        if repo.description:
            lines.append(f"[italic]{repo.description}[/italic]")
        lines.append("")
        
        score_color = "green" if repo.present_score >= 70 else "yellow" if repo.present_score >= 40 else "red"
        lines.append(f"[bold]Score:[/bold] [{score_color}]{repo.present_score:.0f}[/{score_color}]/100")
        if repo.manual_boost:
            lines.append(f"  [dim]Manual boost: {repo.manual_boost:+d}[/dim]")
        lines.append(f"[dim]{repo.score_reason}[/dim]")
        lines.append("")
        
        status_colors = {
            Status.INBOX: "white",
            Status.SHORTLIST: "green",
            Status.PRESENT: "cyan",
            Status.HOLD: "yellow",
            Status.SKIP: "red",
        }
        sc = status_colors.get(repo.status, "white")
        lines.append(f"[bold]Status:[/bold] [{sc}]{repo.status.value}[/{sc}]")
        lines.append("")
        
        lines.append("[bold]Metrics[/bold]")
        if repo.language:
            lines.append(f"  Language: {repo.language}")
        lines.append(f"  Stars: {repo.stars:,}")
        lines.append(f"  Forks: {repo.forks:,}")
        lines.append(f"  Issues: {repo.open_issues}")
        if repo.license:
            lines.append(f"  License: {repo.license}")
        if repo.archived:
            lines.append("  [red]⚠️ Archived[/red]")
        if repo.topics:
            lines.append(f"  Topics: {', '.join(repo.topics[:5])}")
        lines.append("")
        
        if any([repo.hook, repo.who_for, repo.problem, repo.why_now, repo.demo_path, repo.notes]):
            lines.append("[bold]Card[/bold]")
            if repo.hook:
                lines.append(f"  [cyan]Hook:[/cyan] {repo.hook}")
            if repo.who_for:
                lines.append(f"  [cyan]Who for:[/cyan] {repo.who_for}")
            if repo.problem:
                lines.append(f"  [cyan]Problem:[/cyan] {repo.problem}")
            if repo.why_now:
                lines.append(f"  [cyan]Why now:[/cyan] {repo.why_now}")
            if repo.demo_path:
                lines.append(f"  [cyan]Demo:[/cyan] {repo.demo_path}")
            if repo.flags:
                lines.append(f"  [cyan]Flags:[/cyan] {', '.join(repo.flags)}")
            if repo.notes:
                lines.append(f"  [cyan]Notes:[/cyan] {repo.notes}")
        else:
            lines.append("[dim]No card info yet. Press [bold]e[/bold] to edit.[/dim]")
        
        lines.append("")
        lines.append("[dim]Keys: i/s/p/h/x=status  e=edit  o=open  +/-=boost[/dim]")
        
        detail.update("\n".join(lines))
    
    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key:
            repo_id = int(event.row_key.value)
            self.selected_repo = self.db.get_repo_by_id(repo_id)
            self._update_detail()
    
    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key:
            repo_id = int(event.row_key.value)
            self.selected_repo = self.db.get_repo_by_id(repo_id)
            self._update_detail()
    
    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value
        self._apply_filters()
        self._update_table()
    
    @on(Select.Changed, "#filter-status")
    def on_filter_changed(self, event: Select.Changed) -> None:
        if event.value == Select.BLANK:
            self.filter_status = None
        else:
            self.filter_status = Status(event.value)
        self._apply_filters()
        self._update_table()
    
    def action_help(self) -> None:
        self.push_screen(HelpScreen())
    
    def action_refresh(self) -> None:
        self._load_repos()
        self._update_table()
        if self.selected_repo:
            self.selected_repo = self.db.get_repo_by_id(self.selected_repo.id)
            self._update_detail()
        self.notify("Refreshed")
    
    def action_open_browser(self) -> None:
        if self.selected_repo:
            url = self.selected_repo.github_url
            try:
                webbrowser.open(url)
                self.notify(f"Opening {url}")
            except Exception:
                self.notify(f"Could not open browser", severity="error")
    
    def action_edit_card(self) -> None:
        if not self.selected_repo:
            self.notify("No repo selected", severity="warning")
            return
        
        def on_edit_complete(result: dict | None) -> None:
            if result and self.selected_repo:
                self.db.update_card(
                    self.selected_repo.id,
                    hook=result["hook"],
                    who_for=result["who_for"],
                    problem=result["problem"],
                    why_now=result["why_now"],
                    demo_path=result["demo_path"],
                    flags=result["flags"],
                    notes=result["notes"],
                )
                self.selected_repo = self.db.get_repo_by_id(self.selected_repo.id)
                self._update_detail()
                self.notify("Card updated")
        
        self.push_screen(EditCardScreen(self.selected_repo), on_edit_complete)
    
    def _set_status(self, status: Status) -> None:
        if not self.selected_repo:
            self.notify("No repo selected", severity="warning")
            return
        
        old_status = self.selected_repo.status
        self.db.update_status(self.selected_repo.id, status)
        self.selected_repo.status = status
        self._load_repos()
        self._update_table()
        self._update_detail()
        self.notify(f"{self.selected_repo.name}: {old_status.value} → {status.value}")
    
    def action_status_inbox(self) -> None:
        self._set_status(Status.INBOX)
    
    def action_status_shortlist(self) -> None:
        self._set_status(Status.SHORTLIST)
    
    def action_status_present(self) -> None:
        self._set_status(Status.PRESENT)
    
    def action_status_hold(self) -> None:
        self._set_status(Status.HOLD)
    
    def action_status_skip(self) -> None:
        self._set_status(Status.SKIP)
    
    def _adjust_boost(self, delta: int) -> None:
        if not self.selected_repo:
            self.notify("No repo selected", severity="warning")
            return
        
        new_boost = max(-10, min(10, self.selected_repo.manual_boost + delta))
        self.db.update_manual_boost(self.selected_repo.id, new_boost)
        
        self.selected_repo.manual_boost = new_boost
        score, reason = calculate_score(self.selected_repo, self.config.weights)
        self.db.update_score(self.selected_repo.id, score, reason)
        self.selected_repo.present_score = score
        self.selected_repo.score_reason = reason
        
        self._load_repos()
        self._update_table()
        self._update_detail()
        self.notify(f"Boost: {new_boost:+d}, Score: {score:.0f}")
    
    def action_boost_up(self) -> None:
        self._adjust_boost(1)
    
    def action_boost_down(self) -> None:
        self._adjust_boost(-1)
    
    def action_boost_reset(self) -> None:
        if not self.selected_repo:
            return
        self.selected_repo.manual_boost = 0
        self._adjust_boost(0)
    
    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()
    
    def action_filter_inbox(self) -> None:
        self._set_filter(Status.INBOX)
    
    def action_filter_shortlist(self) -> None:
        self._set_filter(Status.SHORTLIST)
    
    def action_filter_present(self) -> None:
        self._set_filter(Status.PRESENT)
    
    def action_filter_hold(self) -> None:
        self._set_filter(Status.HOLD)
    
    def action_filter_skip(self) -> None:
        self._set_filter(Status.SKIP)
    
    def action_filter_all(self) -> None:
        self._set_filter(None)
    
    def _set_filter(self, status: Status | None) -> None:
        self.filter_status = status
        select = self.query_one("#filter-status", Select)
        select.value = status.value if status else Select.BLANK
        self._apply_filters()
        self._update_table()


def run_tui(config: Config) -> None:
    """Run the Rundown TUI."""
    app = RundownApp(config)
    app.run()
