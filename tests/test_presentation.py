import asyncio
import sqlite3

import pytest
from textual.app import App
from textual.widgets import Button, Select, Static, TextArea

from rundown import db
from rundown.card_edit_ui import CardEditScreen
from rundown.cards import CardRecord
from rundown.presentation import (
    PresentationDraft,
    draft_from_rows,
    effective_section,
    save_presentation_draft,
    supplemental_human_fields,
)


class ModalApp(App):
    def __init__(self, screen):
        super().__init__()
        self.modal = screen
        self.result = "pending"

    def on_mount(self):
        self.push_screen(self.modal, self._done)

    def _done(self, result):
        self.result = result


def seed_repo(conn):
    db.init_db(conn)
    return db.upsert_repo(
        conn,
        db.RepoInput("owner/project", "owner", "project", "https://github.com/owner/project"),
    )


def test_draft_save_and_reset_keep_generated_research_unchanged(tmp_path):
    database = tmp_path / "app.sqlite"
    record = CardRecord(sections={"hook": "Generated hook", "why_now": "Generated urgency"})
    with db.session(database) as conn:
        repo_id = seed_repo(conn)
        db.update_repo(conn, "owner/project", hook="Old override", notes="Old repo note")
        db.save_repo_card(conn, repo_id, host_notes="Old host note")
        db.insert_research_log(
            conn,
            repo_id,
            "Repository Understanding",
            "generated summary",
            "success",
            card_json=record.to_json(),
        )
        repo = db.get_repo(conn, "owner/project")
        draft = draft_from_rows(repo, db.get_repo_card(conn, repo_id))
        save_presentation_draft(
            conn,
            repo_id,
            PresentationDraft(
                hook="",
                who_for="Developers",
                why_now="Ship week",
                host_notes="Lead with the demo\n\n    keep indentation",
                repository_notes="Useful later",
            ),
        )
        saved_repo = db.get_repo(conn, "owner/project")
        saved_card = db.get_repo_card(conn, repo_id)
        research = db.latest_successful_research(conn, repo_id)

    assert draft.hook == "Old override"
    assert saved_repo["hook"] is None
    assert effective_section(saved_repo, record, "hook").content == "Generated hook"
    assert saved_repo["who_for"] == "Developers"
    assert saved_repo["why_now"] == "Ship week"
    assert saved_repo["notes"] == "Useful later"
    assert saved_card["host_notes"] == "Lead with the demo\n\n    keep indentation"
    assert research["card_json"] == record.to_json()


def test_presentation_save_is_atomic_when_card_write_fails(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        repo_id = seed_repo(conn)
        db.update_repo(conn, "owner/project", hook="Keep me")
        conn.execute(
            """
            CREATE TRIGGER reject_host_notes BEFORE INSERT ON repo_cards
            BEGIN SELECT RAISE(ABORT, 'blocked'); END
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="blocked"):
            save_presentation_draft(
                conn,
                repo_id,
                PresentationDraft(hook="Do not save", host_notes="Also do not save"),
            )
        assert db.get_repo(conn, "owner/project")["hook"] == "Keep me"
        assert db.get_repo_card(conn, repo_id) is None


def test_effective_sections_and_supplemental_fields_share_override_rules():
    row = {
        "hook": "Human hook",
        "who_for": "Hosts",
        "problem": None,
        "why_now": "Today",
        "demo_path": "demo.sh",
    }
    record = CardRecord(sections={"hook": "Generated hook", "use_cases": "Generated uses"})

    hook = effective_section(row, record, "hook")
    use_cases = effective_section(row, record, "use_cases")
    supplemental = supplemental_human_fields(row, hook.overridden_fields)

    assert hook.content == "Human hook" and hook.source == "human"
    assert use_cases.content == "**For:** Hosts"
    assert {field.name for field in supplemental} == {"who_for", "why_now", "demo_path"}


def test_card_editor_saves_all_fields_and_reset_only_clears_selected_override():
    async def run():
        draft = PresentationDraft(hook="Old hook", host_notes="Keep host notes")
        record = CardRecord(
            sections={"hook": "Generated hook", "use_cases": "Generated audience"}
        )
        app = ModalApp(CardEditScreen("owner/project", draft, record))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            assert "Generated source" in str(
                app.screen.query_one("#card-edit-generated-label", Static).render()
            )
            assert app.screen.query_one("#card-edit-generated", TextArea).read_only
            app.screen.query_one("#card-edit-reset", Button).press()
            await pilot.pause()
            app.screen.query_one("#card-edit-field", Select).value = "who_for"
            await pilot.pause()
            app.screen.query_one("#card-edit-override", TextArea).load_text("Live-coding viewers")
            await pilot.press("ctrl+s")
            await pilot.pause()

        assert isinstance(app.result, PresentationDraft)
        assert app.result.hook == ""
        assert app.result.who_for == "Live-coding viewers"
        assert app.result.host_notes == "Keep host notes"
        assert record.sections["hook"] == "Generated hook"

    asyncio.run(run())


def test_card_editor_cancel_discards_draft_and_host_notes_can_open_first():
    async def run():
        app = ModalApp(
            CardEditScreen(
                "owner/project",
                PresentationDraft(host_notes="Saved cue"),
                CardRecord(),
                initial_field="host_notes",
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.screen.has_class("compact")
            dialog = app.screen.query_one("#card-edit-dialog")
            assert dialog.region.x >= 0 and dialog.region.right <= 80
            assert dialog.region.y >= 0 and dialog.region.bottom <= 24
            assert app.screen.query_one("#card-edit-field", Select).value == "host_notes"
            assert "human-authored" in str(
                app.screen.query_one("#card-edit-generated-label", Static).render()
            )
            app.screen.query_one("#card-edit-override", TextArea).load_text("Unsaved cue")
            await pilot.press("escape")
            await pilot.pause()
        assert app.result is None

    asyncio.run(run())


def test_unknown_repository_does_not_create_orphan_card(tmp_path):
    with db.session(tmp_path / "app.sqlite") as conn:
        db.init_db(conn)
        with pytest.raises(LookupError):
            save_presentation_draft(conn, 404, PresentationDraft(host_notes="orphan"))
        assert conn.execute("SELECT COUNT(*) FROM repo_cards").fetchone()[0] == 0


def test_clearing_composite_field_preserves_sibling_and_uses_precise_label():
    async def run():
        app = ModalApp(CardEditScreen(
            "owner/project", PresentationDraft(who_for="Hosts", problem="Slow research"),
            CardRecord(sections={"use_cases": "Generated uses"}), initial_field="who_for",
        ))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            reset = app.screen.query_one("#card-edit-reset", Button)
            assert str(reset.label) == "Clear this override"
            reset.press()
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
        assert app.result.who_for == ""
        assert app.result.problem == "Slow research"
    asyncio.run(run())
