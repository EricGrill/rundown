"""Keyboard-accessible job inspection without interrupting background work."""
from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from .jobs import ResearchJob


class JobsScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Back", priority=True),
        Binding("c", "cancel_job", "Cancel job"),
        Binding("r", "retry_job", "Retry"),
    ]
    DEFAULT_CSS = """
    JobsScreen { align: center middle; background: $background 70%; }
    #jobs-dialog { width: 94%; max-width: 130; height: 90%; border: solid $primary; padding: 1; }
    #jobs-title, #jobs-hint { height: auto; }
    #jobs-table { height: 1fr; min-height: 4; }
    #job-detail { height: auto; max-height: 5; overflow-y: auto; margin: 1 0; }
    #jobs-actions { height: 3; }
    #jobs-actions Button { min-width: 12; margin-right: 1; }
    """

    def __init__(self, jobs: list[ResearchJob], cancel: Callable[[int], None], retry: Callable[[int], None]):
        super().__init__()
        self.jobs = jobs
        self.cancel_job = cancel
        self.retry_job = retry

    def compose(self) -> ComposeResult:
        with Vertical(id="jobs-dialog"):
            yield Static("Research jobs", id="jobs-title", markup=False)
            yield Static("c cancels selected job · r retries · Esc returns to browsing", id="jobs-hint", markup=False)
            yield DataTable(id="jobs-table", cursor_type="row")
            yield Static("No jobs yet. Select a repository and press r to research it.", id="job-detail", markup=False)
            with Horizontal(id="jobs-actions"):
                yield Button("Cancel job", id="job-cancel")
                yield Button("Retry", id="job-retry")
                yield Button("Back", id="jobs-close")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Repository", "State", "Elapsed")
        table.focus()
        self.refresh_jobs()
        self.set_interval(0.25, self.refresh_jobs)

    def selected_job(self) -> ResearchJob | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return self.jobs[table.cursor_row]

    def refresh_jobs(self) -> None:
        table = self.query_one(DataTable)
        for job in self.jobs:
            key = str(job.id)
            values = (job.full_name, job.state, job.elapsed)
            if key not in table.rows:
                table.add_row(*values, key=key)
            else:
                for column, value in zip(table.columns, values):
                    table.update_cell(key, column, value)
        self.refresh_selection()

    def refresh_selection(self) -> None:
        job = self.selected_job()
        self.query_one("#job-cancel", Button).disabled = job is None or job.terminal or job.cancel_event.is_set()
        self.query_one("#job-retry", Button).disabled = job is None or job.state not in {"failed", "cancelled"}
        if job:
            self.query_one("#job-detail", Static).update(f"{job.full_name} · {job.state}\n{job.message}")

    def on_data_table_row_highlighted(self) -> None:
        self.refresh_selection()

    def action_cancel_job(self) -> None:
        job = self.selected_job()
        if job:
            self.cancel_job(job.id)
            self.refresh_jobs()

    def action_retry_job(self) -> None:
        job = self.selected_job()
        if job:
            self.retry_job(job.id)
            self.refresh_jobs()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "job-cancel":
            self.action_cancel_job()
        elif event.button.id == "job-retry":
            self.action_retry_job()
        else:
            self.action_close()
