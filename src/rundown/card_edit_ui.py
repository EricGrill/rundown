"""One keyboard-first editor for human-authored card content."""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static, TextArea

from .cards import CardRecord
from .presentation import (
    FIELD_LABELS,
    FIELD_SECTIONS,
    PRESENTATION_FIELDS,
    PresentationDraft,
    replace_draft_field,
)


class CardEditScreen(ModalScreen[PresentationDraft | None]):
    """Edit overrides and notes without changing generated research."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]
    DEFAULT_CSS = """
    CardEditScreen { align: center middle; background: $background 70%; }
    #card-edit-dialog { width: 94%; max-width: 112; height: 92%; border: solid $primary; background: $surface; padding: 1 2; }
    #card-edit-title { height: auto; text-style: bold; }
    .card-edit-hint { height: auto; color: $text-muted; margin-bottom: 1; }
    #card-edit-body { height: 1fr; }
    #card-edit-human, #card-edit-source { width: 1fr; min-width: 32; }
    #card-edit-human { padding-right: 1; }
    #card-edit-source { border-left: solid $panel; padding-left: 2; }
    #card-edit-override, #card-edit-generated { height: 1fr; }
    #card-edit-reset { margin-top: 1; }
    #card-edit-actions { height: auto; align-horizontal: right; margin-top: 1; }
    #card-edit-actions Button { margin-left: 1; }
    CardEditScreen.compact #card-edit-dialog { width: 100%; height: 100%; padding: 0 1; }
    CardEditScreen.compact #card-edit-body { layout: vertical; height: auto; }
    CardEditScreen.compact #card-edit-human, CardEditScreen.compact #card-edit-source { width: 100%; min-width: 0; height: 13; padding: 0; }
    CardEditScreen.compact #card-edit-source { border-left: none; border-top: solid $panel; padding-top: 1; }
    """

    def __init__(
        self,
        full_name: str,
        draft: PresentationDraft,
        record: CardRecord,
        *,
        initial_field: str = "hook",
    ):
        super().__init__()
        if initial_field not in PRESENTATION_FIELDS:
            raise ValueError(f"Unknown presentation field: {initial_field}")
        self.full_name = full_name
        self.draft = draft
        self.record = record
        self._active_field = initial_field

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="card-edit-dialog"):
            yield Static(f"Prepare card · {self.full_name}", id="card-edit-title", markup=False)
            yield Static(
                "Your overrides are saved separately from generated research. Ctrl+S saves · Esc cancels.",
                classes="card-edit-hint",
            )
            yield Static("Field", classes="card-edit-hint")
            yield Select(
                [(FIELD_LABELS[name], name) for name in PRESENTATION_FIELDS],
                value=self._active_field,
                id="card-edit-field",
            )
            with Horizontal(id="card-edit-body"):
                with Vertical(id="card-edit-human"):
                    yield Static(id="card-edit-override-label", classes="card-edit-hint")
                    yield TextArea(id="card-edit-override", soft_wrap=True)
                    yield Button("Reset this override", id="card-edit-reset")
                with Vertical(id="card-edit-source"):
                    yield Static(id="card-edit-generated-label", classes="card-edit-hint")
                    yield TextArea(
                        id="card-edit-generated",
                        soft_wrap=True,
                        read_only=True,
                        show_cursor=False,
                    )
            with Horizontal(id="card-edit-actions"):
                yield Button("Cancel", id="card-edit-cancel")
                yield Button("Save card", id="card-edit-save", variant="primary")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 90, "compact")
        self._show_field(self._active_field)
        self.query_one("#card-edit-override", TextArea).focus()

    def on_resize(self) -> None:
        self.set_class(self.size.width < 90, "compact")

    def _store_active_field(self) -> None:
        value = self.query_one("#card-edit-override", TextArea).text
        self.draft = replace_draft_field(self.draft, self._active_field, value)

    def _show_field(self, name: str) -> None:
        self._active_field = name
        label = FIELD_LABELS[name]
        human_label = "Your notes" if name in {"host_notes", "repository_notes"} else "Your override"
        self.query_one("#card-edit-override-label", Static).update(f"{human_label} · {label}")
        self.query_one("#card-edit-override", TextArea).load_text(getattr(self.draft, name))

        section_id = FIELD_SECTIONS.get(name)
        generated = self.record.sections.get(section_id, "").strip() if section_id else ""
        if section_id:
            source_label = f"Generated source · {label} (read-only)"
            generated = generated or "No generated source is available for this field."
        else:
            source_label = f"{label} is human-authored"
            generated = "This notes field has no generated source."
        self.query_one("#card-edit-generated-label", Static).update(source_label)
        self.query_one("#card-edit-generated", TextArea).load_text(generated)

        reset = self.query_one("#card-edit-reset", Button)
        reset.label = ("Clear these notes" if name in {"host_notes", "repository_notes"}
                       else "Clear this override" if name in {"who_for", "problem"}
                       else "Reset to generated")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "card-edit-field" or not isinstance(event.value, str):
            return
        if event.value == self._active_field:
            return
        self._store_active_field()
        self._show_field(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "card-edit-reset":
            self.draft = replace_draft_field(self.draft, self._active_field, "")
            self.query_one("#card-edit-override", TextArea).load_text("")
            self.query_one("#card-edit-override", TextArea).focus()
        elif event.button.id == "card-edit-save":
            self.action_save()
        elif event.button.id == "card-edit-cancel":
            self.action_cancel()

    def action_save(self) -> None:
        self._store_active_field()
        self.dismiss(self.draft)

    def action_cancel(self) -> None:
        self.dismiss(None)
