"""Modal catalog view editor."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from .catalog import CatalogView, RESEARCH_FILTERS, SORTS


@dataclass(frozen=True)
class CatalogResult:
    view: CatalogView
    action: Literal["apply", "save", "delete"] = "apply"


class CatalogScreen(ModalScreen[CatalogResult | None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save_named", "Save view", priority=True),
        Binding("ctrl+enter", "apply", "Apply", priority=True),
    ]
    DEFAULT_CSS = """
    CatalogScreen { align: center middle; background: $background 70%; }
    #catalog-dialog { width: 90%; max-width: 92; height: 90%; border: solid $primary; padding: 1 2; background: $surface; }
    #catalog-title { height: auto; text-style: bold; }
    .catalog-hint { height: auto; color: $text-muted; margin-bottom: 1; }
    .catalog-row { height: auto; margin-bottom: 1; }
    .catalog-row > * { width: 1fr; margin-right: 1; }
    #catalog-error { height: auto; color: $error; }
    #catalog-actions { height: auto; align-horizontal: right; }
    #catalog-actions Button { margin-left: 1; }
    CatalogScreen.compact #catalog-dialog { width: 100%; height: 100%; padding: 0 1; }
    CatalogScreen.compact .catalog-row { layout: vertical; }
    CatalogScreen.compact .catalog-row > * { width: 100%; margin-right: 0; }
    CatalogScreen.compact #catalog-actions { align-horizontal: left; }
    """

    def __init__(
        self,
        view: CatalogView,
        named_views: Sequence[CatalogView] = (),
        categories: Sequence[str] = (),
    ):
        super().__init__()
        self.view = view
        self.named_views = tuple(named_views)
        all_categories = set(categories)
        if view.category:
            all_categories.add(view.category)
        all_categories.update(item.category for item in named_views if item.category)
        self.categories = tuple(sorted(all_categories, key=str.casefold))

    def compose(self) -> ComposeResult:
        named_options = [(item.name or "", item.name or "") for item in self.named_views]
        with VerticalScroll(id="catalog-dialog"):
            yield Static("Catalog view", id="catalog-title")
            yield Static(
                "Filter and sort saved data locally. Ctrl+Enter applies · Ctrl+S saves · Esc cancels.",
                classes="catalog-hint",
            )
            with Horizontal(classes="catalog-row"):
                yield Select(named_options, prompt="Load named view", id="catalog-named")
                yield Input(self.view.name or "", placeholder="View name", id="catalog-name")
            yield Input(self.view.query, placeholder="Search repositories", id="catalog-query")
            with Horizontal(classes="catalog-row"):
                yield Select(
                    [("All categories", "")]
                    + [(category, category) for category in self.categories],
                    value=self.view.category or "",
                    id="catalog-category",
                )
                yield Select(
                    [(value.replace("_", " ").title(), value) for value in RESEARCH_FILTERS],
                    value=self.view.research_filter,
                    id="catalog-filter",
                )
            yield Static("Sort order · Stale after this many days (or when repository changes)", classes="catalog-hint")
            with Horizontal(classes="catalog-row"):
                yield Select(
                    [(value.replace("_", " ").title(), value) for value in SORTS],
                    value=self.view.sort,
                    id="catalog-sort",
                )
                yield Input(str(self.view.stale_days), type="integer", placeholder="Stale after days", id="catalog-stale")
            yield Static(id="catalog-error")
            with Horizontal(id="catalog-actions"):
                yield Button("Delete named", id="catalog-delete", disabled=not bool(self.view.name))
                yield Button("Save named", id="catalog-save")
                yield Button("Apply", id="catalog-apply", variant="primary")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 90, "compact")
        self.query_one("#catalog-query", Input).focus()

    def on_resize(self) -> None:
        self.set_class(self.size.width < 90, "compact")

    def _candidate(self) -> CatalogView:
        category = self.query_one("#catalog-category", Select).value
        name = self.query_one("#catalog-name", Input).value.strip() or None
        return CatalogView(
            name=name,
            query=self.query_one("#catalog-query", Input).value,
            category=str(category) if category else None,
            research_filter=str(self.query_one("#catalog-filter", Select).value),
            sort=str(self.query_one("#catalog-sort", Select).value),
            stale_days=int(self.query_one("#catalog-stale", Input).value),
        )

    def _load(self, view: CatalogView) -> None:
        self.query_one("#catalog-name", Input).value = view.name or ""
        self.query_one("#catalog-query", Input).value = view.query
        self.query_one("#catalog-category", Select).value = view.category or ""
        self.query_one("#catalog-filter", Select).value = view.research_filter
        self.query_one("#catalog-sort", Select).value = view.sort
        self.query_one("#catalog-stale", Input).value = str(view.stale_days)
        self.query_one("#catalog-delete", Button).disabled = False

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "catalog-named" and isinstance(event.value, str):
            selected = next((item for item in self.named_views if item.name == event.value), None)
            if selected:
                self._load(selected)

    def _dismiss(self, action: Literal["apply", "save", "delete"]) -> None:
        try:
            view = self._candidate()
            if action in {"save", "delete"} and view.name is None:
                raise ValueError("Enter a name before saving or deleting a view.")
        except (ValueError, TypeError) as error:
            self.query_one("#catalog-error", Static).update(str(error))
            return
        self.dismiss(CatalogResult(view, action))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save_named(self) -> None:
        self._dismiss("save")

    def action_apply(self) -> None:
        self._dismiss("apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "catalog-apply":
            self._dismiss("apply")
        elif event.button.id == "catalog-save":
            self._dismiss("save")
        elif event.button.id == "catalog-delete":
            self._dismiss("delete")
