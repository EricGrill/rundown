"""Keyboard-first editor for card templates backed by saved research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Select, Static

from .cards import CardRecord, HOST_SECTIONS, RESEARCH_SECTIONS, SECTION_TITLES, section_preview
from .config import CardSettings, CardTemplateSettings


@dataclass(frozen=True)
class TemplateResult:
    settings: CardSettings
    scope: Literal["global", "repo"]


PRESETS: dict[str, CardSettings] = {
    "discovery": CardSettings(
        default_view="host",
        audience="Developers discovering a useful repository",
        tone="Plain, concise, conversational",
        duration_seconds=60,
        host=CardTemplateSettings(("hook", "what_it_is", "why_now", "demo", "risks"), 45),
        research=CardTemplateSettings(RESEARCH_SECTIONS, 100),
    ),
    "deep_dive": CardSettings(
        default_view="research",
        audience="Technical developers evaluating implementation details",
        tone="Precise, technical, evidence-led",
        duration_seconds=300,
        host=CardTemplateSettings(HOST_SECTIONS, 90),
        research=CardTemplateSettings(RESEARCH_SECTIONS, 240),
    ),
    "live_demo": CardSettings(
        default_view="host",
        audience="Developers watching a live software demonstration",
        tone="Direct, energetic, practical",
        duration_seconds=180,
        host=CardTemplateSettings(
            ("hook", "what_it_is", "use_cases", "demo", "risks", "talking_points"), 75
        ),
        research=CardTemplateSettings(RESEARCH_SECTIONS, 140),
    ),
}


class TemplateScreen(ModalScreen[TemplateResult | None]):
    """Edit global or per-repository cards without invoking a provider."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]
    DEFAULT_CSS = """
    TemplateScreen { align: center middle; background: $background 70%; }
    #template-dialog { width: 94%; max-width: 120; height: 94%; border: solid $primary; background: $surface; padding: 1 2; }
    #template-title { height: auto; text-style: bold; }
    .template-hint { height: auto; color: $text-muted; margin-bottom: 1; }
    .template-row { height: auto; margin-bottom: 1; }
    .template-row > * { width: 1fr; margin-right: 1; }
    #template-body { height: 1fr; }
    #template-fields { width: 1fr; min-width: 42; padding-right: 1; }
    #template-preview-pane { width: 1fr; min-width: 36; border-left: solid $panel; padding-left: 2; }
    #template-preview { height: 1fr; }
    #template-section-list { height: auto; min-height: 3; color: $text-muted; margin-bottom: 1; }
    #template-error { height: auto; color: $error; }
    #template-actions { height: auto; align-horizontal: right; }
    #template-actions Button { margin-left: 1; }
    TemplateScreen.compact #template-dialog { width: 100%; height: 100%; padding: 0 1; }
    TemplateScreen.compact #template-body { layout: vertical; height: auto; }
    TemplateScreen.compact #template-fields { width: 100%; height: auto; padding-right: 0; }
    TemplateScreen.compact #template-preview-pane { width: 100%; height: 12; border-left: none; border-top: solid $panel; padding: 1 0 0 0; }
    TemplateScreen.compact .template-row { layout: vertical; }
    TemplateScreen.compact .template-row > * { width: 100%; margin-right: 0; }
    """

    def __init__(
        self,
        settings: CardSettings,
        record: CardRecord | None = None,
        repo_name: str | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.record = record
        self.repo_name = repo_name
        self._sections = {
            "host": list(settings.host.sections),
            "research": list(settings.research.sections),
        }
        self._word_limits = {
            "host": settings.host.word_limit,
            "research": settings.research.word_limit,
        }

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="template-dialog"):
            yield Static("Research card templates", id="template-title")
            yield Static(
                "Choose a preset or edit the profile. Preview uses saved research only. Ctrl+S saves · Esc cancels.",
                classes="template-hint",
            )
            with Horizontal(classes="template-row"):
                yield Select(
                    [("Custom", "custom"), ("60-second discovery", "discovery"), ("Technical deep dive", "deep_dive"), ("Live demo", "live_demo")],
                    value="custom",
                    id="template-preset",
                )
                yield Select(
                    [("Host brief", "host"), ("Research card", "research")],
                    value=self.settings.default_view,
                    id="template-view",
                )
                scope_options = [("Global default", "global")]
                if self.repo_name:
                    scope_options.append((f"Only {self.repo_name}", "repo"))
                yield Select(scope_options, value="repo" if self.repo_name else "global", id="template-scope")
            with Horizontal(id="template-body"):
                with VerticalScroll(id="template-fields"):
                    yield Static("Audience", classes="template-hint")
                    yield Input(self.settings.audience, placeholder="Audience", id="template-audience")
                    yield Static("Tone", classes="template-hint")
                    yield Input(self.settings.tone, placeholder="Tone", id="template-tone")
                    yield Static("Target seconds · Preview words per section", classes="template-hint")
                    with Horizontal(classes="template-row"):
                        yield Input(str(self.settings.duration_seconds), type="integer", placeholder="Duration seconds", id="template-duration")
                        yield Input(str(self._active_template().word_limit), type="integer", placeholder="Preview words", id="template-words")
                    yield Select(
                        [(title, section_id) for section_id, title in SECTION_TITLES.items()],
                        value=self._sections[self.settings.default_view][0],
                        id="template-section",
                    )
                    with Horizontal(classes="template-row"):
                        yield Button("Toggle", id="template-toggle")
                        yield Button("Move up", id="template-up")
                        yield Button("Move down", id="template-down")
                    yield Static(id="template-section-list")
                    yield Static(id="template-error")
                with Vertical(id="template-preview-pane"):
                    yield Static("Live preview", classes="template-hint")
                    yield Markdown(id="template-preview", open_links=False)
            with Horizontal(id="template-actions"):
                yield Button("Cancel", id="template-cancel")
                yield Button("Save template", id="template-save", variant="primary")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 90, "compact")
        self._refresh_sections()
        self._refresh_preview()
        self.query_one("#template-audience", Input).focus()

    def on_resize(self) -> None:
        self.set_class(self.size.width < 90, "compact")

    def _active_view(self) -> str:
        value = self.query_one("#template-view", Select).value
        return value if isinstance(value, str) and value in {"host", "research"} else self.settings.default_view

    def _active_template(self) -> CardTemplateSettings:
        return self.settings.host if self.settings.default_view == "host" else self.settings.research

    def _selected_section(self) -> str | None:
        value = self.query_one("#template-section", Select).value
        return value if isinstance(value, str) and value in SECTION_TITLES else None

    def _refresh_sections(self) -> None:
        view = self._active_view()
        lines = [f"{index + 1}. {SECTION_TITLES[item]}" for index, item in enumerate(self._sections[view])]
        self.query_one("#template-section-list", Static).update("\n".join(lines) or "No sections selected")
        self.query_one("#template-words", Input).value = str(self._word_limits[view])

    def _candidate(self) -> CardSettings:
        duration = int(self.query_one("#template-duration", Input).value)
        view = self._active_view()
        words = int(self.query_one("#template-words", Input).value)
        word_limits = {**self._word_limits, view: words}
        host = CardTemplateSettings(tuple(self._sections["host"]), word_limits["host"])
        research = CardTemplateSettings(
            tuple(self._sections["research"]), word_limits["research"]
        )
        return CardSettings(
            default_view=view,
            audience=self.query_one("#template-audience", Input).value,
            tone=self.query_one("#template-tone", Input).value,
            duration_seconds=duration,
            host=host,
            research=research,
        )

    def _refresh_preview(self) -> None:
        view = self._active_view()
        try:
            candidate = self._candidate()
        except (ValueError, TypeError):
            return
        template = candidate.host if view == "host" else candidate.research
        blocks: list[str] = []
        for section_id in template.sections:
            content = (
                self.record.sections.get(section_id, "")
                if self.record
                else "No saved research for this section."
            )
            blocks.append(f"## {SECTION_TITLES[section_id]}\n\n{section_preview(content or 'Unknown', template.word_limit)}")
        self.query_one("#template-preview", Markdown).update("\n\n".join(blocks))

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self.is_mounted:
            return
        if event.select.id == "template-preset" and event.value in PRESETS:
            self.settings = PRESETS[str(event.value)]
            self._sections = {
                "host": list(self.settings.host.sections),
                "research": list(self.settings.research.sections),
            }
            self._word_limits = {
                "host": self.settings.host.word_limit,
                "research": self.settings.research.word_limit,
            }
            self.query_one("#template-view", Select).value = self.settings.default_view
            self.query_one("#template-audience", Input).value = self.settings.audience
            self.query_one("#template-tone", Input).value = self.settings.tone
            self.query_one("#template-duration", Input).value = str(self.settings.duration_seconds)
        if event.select.id in {"template-preset", "template-view"}:
            self._refresh_sections()
            self._refresh_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.is_mounted:
            if event.input.id == "template-words":
                try:
                    self._word_limits[self._active_view()] = int(event.value)
                except ValueError:
                    pass
            self._refresh_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "template-cancel":
            self.action_cancel()
        elif button_id == "template-save":
            self.action_save()
        elif button_id in {"template-toggle", "template-up", "template-down"}:
            self._change_section(button_id)

    def _change_section(self, action: str) -> None:
        section = self._selected_section()
        if section is None:
            return
        items = self._sections[self._active_view()]
        if action == "template-toggle":
            if section in items:
                if len(items) == 1:
                    self.query_one("#template-error", Static).update("A template needs at least one section.")
                    return
                items.remove(section)
            else:
                items.append(section)
        elif section in items:
            index = items.index(section)
            target = index - 1 if action == "template-up" else index + 1
            if 0 <= target < len(items):
                items[index], items[target] = items[target], items[index]
        self.query_one("#template-error", Static).update("")
        self._refresh_sections()
        self._refresh_preview()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        try:
            settings = self._candidate()
        except (ValueError, TypeError) as error:
            self.query_one("#template-error", Static).update(str(error))
            return
        scope = self.query_one("#template-scope", Select).value
        self.dismiss(TemplateResult(settings, "repo" if scope == "repo" else "global"))
