"""Explicit local export with safe creation and optional replacement."""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static

from .export import write_export_file as write_export_file


@dataclass(frozen=True)
class ExportRequest:
    scope: str
    path: Path
    overwrite: bool = False




class ExportScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "export", "Export", priority=True),
    ]
    DEFAULT_CSS = """
    ExportScreen { align: center middle; background: $background 70%; }
    #export-dialog { width: 90%; max-width: 100; height: auto; max-height: 95%; padding: 1 2; border: solid $primary; background: $surface; }
    #export-dialog Static { height: auto; margin-bottom: 1; }
    #export-dialog Select, #export-dialog Input { margin-bottom: 1; }
    #export-actions { height: auto; align-horizontal: right; }
    #export-error { color: $error; }
    """

    def __init__(self, full_name: str, path: Path, submit: Callable[[ExportRequest], str], *, demo_mode: bool = False):
        super().__init__()
        self.full_name = full_name
        self.path = path
        self.submit = submit
        self.demo_mode = demo_mode

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="export-dialog"):
            yield Static("Export Markdown", markup=False)
            yield Static("Includes your card layout, presentation edits and host notes. Ctrl+S exports · Esc cancels.")
            yield Select([(f"Selected: {self.full_name}", "selected"), ("Marked: present + shortlist", "marked")], value="selected", allow_blank=False, id="export-scope")
            yield Static("Output file")
            yield Input(str(self.path), id="export-path")
            yield Checkbox("Replace existing file", value=False, id="export-overwrite")
            if self.demo_mode:
                yield Static("Demo exports are temporary and disappear when the demo closes.")
            yield Static("", id="export-error", markup=False)
            with Horizontal(id="export-actions"):
                yield Button("Cancel", id="export-cancel")
                yield Button("Export", id="export-save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#export-path", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_export(self) -> None:
        raw_path = self.query_one("#export-path", Input).value.strip()
        try:
            if not raw_path:
                raise ValueError("Enter an output file path.")
            result = self.submit(ExportRequest(
                str(self.query_one("#export-scope", Select).value), Path(raw_path),
                self.query_one("#export-overwrite", Checkbox).value,
            ))
        except (OSError, ValueError) as exc:
            self.query_one("#export-error", Static).update(str(exc))
            return
        self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-save":
            self.action_export()
        elif event.button.id == "export-cancel":
            self.action_cancel()
