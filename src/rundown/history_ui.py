from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class HistoryScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Back", priority=True)]
    DEFAULT_CSS = """
    HistoryScreen { align: center middle; background: $background 70%; }
    #history-dialog { width: 94%; max-width: 130; height: 90%; border: solid $primary; padding: 1 2; }
    #history-title { height: auto; text-style: bold; }
    #history-scroll { height: 1fr; }
    #history-content { height: auto; }
    #history-close { height: 3; }
    """

    def __init__(self, full_name: str, content: str):
        super().__init__()
        self.full_name = full_name
        self.content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="history-dialog"):
            yield Static(f"Research history · {self.full_name}", id="history-title", markup=False)
            with VerticalScroll(id="history-scroll"):
                yield Static(self.content, id="history-content", markup=False)
            yield Button("Back", id="history-close")

    def on_mount(self) -> None:
        self.query_one("#history-scroll").focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_close()
