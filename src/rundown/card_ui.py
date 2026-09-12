"""Native terminal presentation and editing for saved research cards."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Collapsible, Markdown, Static

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
