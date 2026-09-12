"""Native terminal presentation and editing for saved research cards."""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Markdown, Static, TextArea

from .cards import SECTION_TITLES, section_preview


class CardDisclosure(Collapsible):
    def scroll_visible(self, *args, **kwargs) -> None:
        # Restoring saved state must not jump the reader away from its header.
        if self.has_focus_within:
            super().scroll_visible(*args, **kwargs)


class CardSection(Vertical):
    DEFAULT_CSS = """
    CardSection { height: auto; border-top: solid $panel; padding-top: 1; margin-bottom: 1; }
    CardSection > .section-title { height: auto; color: $primary; text-style: bold; }
    CardSection Markdown { margin: 0; padding: 0; }
    CardSection Collapsible { padding: 0; margin: 0; border: none; }
    """

    def __init__(self, section_id: str, text: str, word_limit: int):
        super().__init__(id=f"card-{section_id}")
        self.section_id = section_id
        self.text = text
        self.word_limit = word_limit

    def compose(self) -> ComposeResult:
        yield Static(SECTION_TITLES[self.section_id], classes="section-title", markup=False)
        preview = section_preview(self.text, self.word_limit)
        yield Markdown(preview, open_links=False, classes="section-preview")
        if preview != self.text:
            with CardDisclosure(title="Read full section", collapsed=True):
                yield Markdown(self.text, open_links=False)


class CardSections(Vertical):
    DEFAULT_CSS = "CardSections { height: auto; }"
    entries: reactive[tuple[tuple[str, str, int], ...]] = reactive((), recompose=True)

    def compose(self) -> ComposeResult:
        for section_id, text, word_limit in self.entries:
            yield CardSection(section_id, text, word_limit)


class HostNotesScreen(ModalScreen[str | None]):
    """Cancel never writes; the app persists notes after an explicit save."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]
    DEFAULT_CSS = """
    HostNotesScreen { align: center middle; background: $background 70%; }
    #notes-dialog { width: 90%; max-width: 100; height: 85%; border: solid $primary; padding: 1 2; background: $surface; }
    #notes-title { height: auto; text-style: bold; margin-bottom: 1; }
    #notes-hint { height: auto; color: $text-muted; margin-bottom: 1; }
    #notes-text { height: 1fr; }
    #notes-actions { height: auto; margin-top: 1; align-horizontal: right; }
    #notes-actions Button { margin-left: 1; }
    """

    def __init__(self, full_name: str, notes: str):
        super().__init__()
        self.full_name = full_name
        self.notes = notes

    def compose(self) -> ComposeResult:
        with Vertical(id="notes-dialog"):
            yield Static(f"Host notes · {self.full_name}", id="notes-title", markup=False)
            yield Static("Your notes survive research refreshes. Ctrl+S saves · Esc cancels.", id="notes-hint")
            yield TextArea(self.notes, id="notes-text", soft_wrap=True)
            with Horizontal(id="notes-actions"):
                yield Button("Cancel", id="notes-cancel")
                yield Button("Save notes", id="notes-save", variant="primary")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(self.query_one(TextArea).text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "notes-save":
            self.action_save()
        elif event.button.id == "notes-cancel":
            self.action_cancel()
