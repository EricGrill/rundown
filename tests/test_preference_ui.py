import asyncio

from textual.app import App
from textual.widgets import Input, Markdown, Select, Static

from rundown.cards import CardRecord
from rundown.catalog import CatalogView
from rundown.catalog_ui import CatalogResult, CatalogScreen
from rundown.config import CardSettings
from rundown.template_ui import PRESETS, TemplateResult, TemplateScreen


class ModalApp(App):
    def __init__(self, screen):
        super().__init__()
        self.modal = screen
        self.result = "pending"

    def on_mount(self):
        self.push_screen(self.modal, self._done)

    def _done(self, result):
        self.result = result


def test_template_preset_live_preview_and_keyboard_save():
    async def run():
        record = CardRecord(sections={"hook": "Saved hook", "what_it_is": "Saved description"})
        app = ModalApp(TemplateScreen(CardSettings(), record, "owner/project"))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.screen.has_class("compact")
            app.screen.query_one("#template-preset", Select).value = "discovery"
            await pilot.pause()
            assert app.screen.query_one("#template-duration", Input).value == "60"
            assert "Saved hook" in app.screen.query_one("#template-preview", Markdown).source
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.result, TemplateResult)
            assert app.result.scope == "repo"
            assert app.result.settings == PRESETS["discovery"]

    asyncio.run(run())


def test_template_cancel_and_invalid_values_do_not_dismiss():
    async def invalid():
        app = ModalApp(TemplateScreen(CardSettings()))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.screen.query_one("#template-duration", Input).value = "2"
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.result == "pending"
            assert "between 15 and 3600" in str(app.screen.query_one("#template-error", Static).render())
            await pilot.press("escape")
            await pilot.pause()
            assert app.result is None

    asyncio.run(invalid())


def test_catalog_load_named_view_and_keyboard_save():
    async def run():
        named = CatalogView(name="Show", query="tui", research_filter="stale", sort="research_date", stale_days=7)
        app = ModalApp(CatalogScreen(CatalogView(), [named], ["Developer Tools"]))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.screen.has_class("compact")
            app.screen.query_one("#catalog-named", Select).value = "Show"
            await pilot.pause()
            assert app.screen.query_one("#catalog-query", Input).value == "tui"
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.result == CatalogResult(named, "save")

    asyncio.run(run())


def test_catalog_rejects_bad_stale_days_then_cancels():
    async def run():
        app = ModalApp(CatalogScreen(CatalogView()))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.screen.query_one("#catalog-stale", Input).value = "0"
            await pilot.press("ctrl+enter")
            await pilot.pause()
            assert app.result == "pending"
            assert "between 1 and 3650" in str(app.screen.query_one("#catalog-error", Static).render())
            await pilot.press("escape")
            await pilot.pause()
            assert app.result is None

    asyncio.run(run())
