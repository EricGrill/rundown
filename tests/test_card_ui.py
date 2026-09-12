import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest
from textual.widgets import Collapsible, Markdown, Select, Static, TextArea

from rundown import cards, db
from rundown.card_ui import CardSections, HostNotesScreen
from rundown.config import AppConfig, CardTemplateSettings
from rundown.tui import RundownApp


def seed(config, *, summary=None):
    record = cards.CardRecord(sections={key: f"Finding about {key}." for key in cards.SECTION_TITLES})
    record.sections['hook'] = 'A concise opening line for the host.'
    record.sections['sources'] = '- README.md: Overview (supplied repository context)'
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(conn, db.RepoInput('owner/project', 'owner', 'project', 'https://github.com/owner/project'))
        db.insert_research_log(conn, repo_id, 'Repository Understanding', summary or record.to_markdown(), 'success', card_json=None if summary else record.to_json())
    return repo_id


def test_switch_views_is_local_and_persists_per_repo(tmp_path):
    config = AppConfig(root=tmp_path)
    repo_id = seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with patch('rundown.tui.research.run_repository_research') as generate:
            async with app.run_test(size=(140, 40)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert app.card_view == 'host'
                assert app.query_one('#card-hook Markdown', Markdown).source == 'A concise opening line for the host.'
                await pilot.press('v')
                await pilot.pause()
                assert app.card_view == 'research'
                assert app.query_one('#card-how_it_works Markdown', Markdown).source == 'Finding about how_it_works.'
                assert not app.query('#card-hook')
                with db.session(config.database_path) as conn:
                    assert db.get_repo_card(conn, repo_id)['view'] == 'research'
                app.load_rows()
                await pilot.pause()
                assert app.query_one('#card-view', Select).value == 'research'
                generate.assert_not_called()
        restarted = RundownApp(config, fetch_starred=list)
        async with restarted.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert restarted.card_view == 'research'

    asyncio.run(run())


def test_notes_save_cancel_and_research_refresh_are_independent(tmp_path):
    config = AppConfig(root=tmp_path)
    repo_id = seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(120, 35)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press('n')
            assert isinstance(app.screen, HostNotesScreen)
            app.screen.query_one(TextArea).load_text('Mention the demo first.\nDo not lose this cue.')
            await pilot.press('ctrl+s')
            await pilot.pause()
            with db.session(config.database_path) as conn:
                assert db.get_repo_card(conn, repo_id)['host_notes'] == 'Mention the demo first.\nDo not lose this cue.'
                db.insert_research_log(conn, repo_id, 'Repository Understanding', '## What This Is\nFresh findings.', 'success')
            app.load_rows()
            await pilot.pause()
            assert 'Do not lose this cue.' in str(app.query_one('#host-notes', Static).render())
            app.query_one('#repos').focus()
            await pilot.press('n')
            app.screen.query_one(TextArea).load_text('Discard this edit.')
            await pilot.press('escape')
            with db.session(config.database_path) as conn:
                assert 'Do not lose this cue.' in db.get_repo_card(conn, repo_id)['host_notes']
            assert not isinstance(app.screen, HostNotesScreen)

    asyncio.run(run())


def test_legacy_content_is_preserved_and_missing_host_fields_are_explicit(tmp_path):
    config = AppConfig(root=tmp_path)
    original = '## What This Is\nA useful existing report.\n\n## Unusual heading\nKeep this rare finding.'
    seed(config, summary=original)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.query_one('#research-content', Markdown).source == original
            assert 'Unknown' in app.query_one('#card-hook Markdown', Markdown).source
            assert 'A useful existing report.' in app.query_one('#card-what_it_is Markdown', Markdown).source
            disclosure = app.query_one('#full-research', Collapsible)
            disclosure.collapsed = False
            await pilot.pause()
            assert app.query_one('#research-content').display
            assert 'Not rehearsed'.casefold() in str(app.query_one('#card-context', Static).render()).casefold()

    asyncio.run(run())


def test_configured_section_order_and_expansion_preserve_full_text(tmp_path):
    config = AppConfig(root=tmp_path)
    config = replace(config, cards=replace(config.cards, host=CardTemplateSettings(sections=('risks', 'what_it_is'), word_limit=10)))
    text = ' '.join(f'word{index}' for index in range(80))
    seed(config, summary=f'## What This Is\n{text}\n\n## Limitations and Risks\nA caveat.')

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            body = app.query_one(CardSections)
            assert [entry[0] for entry in body.entries] == ['risks', 'what_it_is']
            section = app.query_one('#card-what_it_is')
            assert len(section.query_one('.section-preview', Markdown).source.split()) < 80
            full = section.query_one(Collapsible)
            full.collapsed = False
            await pilot.pause()
            assert full.query_one(Markdown).source == text

    asyncio.run(run())


def test_empty_catalog_has_no_stale_card_or_notes(tmp_path):
    config = AppConfig(root=tmp_path)
    seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press('slash', *'no-such-repository')
            await pilot.pause()
            assert not app.query_one(CardSections).entries
            assert app.query_one('#card-toolbar').disabled
            assert app.query_one('#research-content', Markdown).source == ''
            assert 'No repository' in str(app.query_one('#host-notes', Static).render())

    asyncio.run(run())


def test_explicit_refresh_bypasses_cache_and_preserves_notes(tmp_path):
    config = AppConfig(root=tmp_path)
    repo_id = seed(config)
    with db.session(config.database_path) as conn:
        db.save_repo_card(conn, repo_id, host_notes='Keep my introduction.')

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with (
            patch('rundown.tui.research.load_cached_repository_research') as cached,
            patch('rundown.tui.repo_ops.clone_repo', return_value=('already_cloned', 'ready')),
            patch('rundown.tui.research.run_repository_research', return_value=('success', 'Fresh research')) as generate,
        ):
            async with app.run_test(size=(140, 35)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press('R')
                await app.workers.wait_for_complete()
                await pilot.pause()
                cached.assert_not_called()
                assert generate.call_args.kwargs['force'] is True
                assert not generate.call_args.kwargs['cancel_event'].is_set()
                with db.session(config.database_path) as conn:
                    assert db.get_repo_card(conn, repo_id)['host_notes'] == 'Keep my introduction.'

    asyncio.run(run())


def test_saved_notes_do_not_scroll_reader_away_from_header(tmp_path):
    config = AppConfig(root=tmp_path)
    repo_id = seed(config)
    with db.session(config.database_path) as conn:
        db.save_repo_card(conn, repo_id, host_notes='A saved cue at the end of the card.')

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(80, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            reader = app.query_one('#reader')
            assert reader.scroll_y == 0
            await pilot.press('enter')
            await pilot.pause()
            assert reader.scroll_y == 0
            assert app.query_one('#card-view').region.width > 0
            await pilot.press('pagedown')
            await pilot.pause()
            assert reader.scroll_y > 0

    asyncio.run(run())


def test_note_save_error_retains_draft_for_retry(tmp_path):
    import sqlite3

    config = AppConfig(root=tmp_path)
    repo_id = seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press('n')
            app.screen.query_one(TextArea).load_text('Keep this unsaved draft.')
            with patch('rundown.tui.db.save_repo_card', side_effect=sqlite3.OperationalError('database is locked')):
                await pilot.press('ctrl+s')
                await pilot.pause()
                assert isinstance(app.screen, HostNotesScreen)
                assert app.screen.query_one(TextArea).text == 'Keep this unsaved draft.'
            await pilot.press('ctrl+s')
            await pilot.pause()
            with db.session(config.database_path) as conn:
                assert db.get_repo_card(conn, repo_id)['host_notes'] == 'Keep this unsaved draft.'

    asyncio.run(run())


@pytest.mark.parametrize("legacy_schema", [False, True])
def test_notes_only_save_preserves_configured_research_default(tmp_path, legacy_schema):
    config = AppConfig(root=tmp_path)
    config = replace(config, cards=replace(config.cards, default_view='research'))
    if legacy_schema:
        with db.session(config.database_path) as conn:
            conn.execute("CREATE TABLE repo_cards (repo_id INTEGER PRIMARY KEY, view TEXT NOT NULL DEFAULT 'host', host_notes TEXT NOT NULL DEFAULT '')")
    seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(120, 35)) as pilot:
            await app.workers.wait_for_complete()
            assert app.card_view == 'research'
            await pilot.press('n')
            app.screen.query_one(TextArea).load_text('Keep the research view.')
            await pilot.press('ctrl+s')
            await pilot.pause()
            app.load_rows()
            await pilot.pause()
            assert app.card_view == 'research'
        restarted = RundownApp(config, fetch_starred=list)
        async with restarted.run_test(size=(120, 35)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert restarted.card_view == 'research'

    asyncio.run(run())


def test_retry_after_failed_refresh_does_not_return_old_cache(tmp_path):
    config = AppConfig(root=tmp_path)
    seed(config)

    async def run():
        app = RundownApp(config, fetch_starred=list)
        with (
            patch('rundown.tui.research.load_cached_repository_research') as cached,
            patch('rundown.tui.repo_ops.clone_repo', return_value=('already_cloned', 'ready')),
            patch('rundown.tui.research.run_repository_research', side_effect=[('failed', 'Provider unavailable.'), ('success', 'New findings.')]) as generate,
        ):
            async with app.run_test(size=(140, 35)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press('R')
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert 'owner/project' in app.research_errors
                await pilot.press('r')
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert generate.call_count == 2
                assert all(call.kwargs['force'] is True for call in generate.call_args_list)
                cached.assert_not_called()
                assert not app.research_errors

    asyncio.run(run())


def test_section_expansion_is_keyboard_accessible(tmp_path):
    config = AppConfig(root=tmp_path)
    config = replace(config, cards=replace(config.cards, host=CardTemplateSettings(sections=('what_it_is',), word_limit=10)))
    seed(config, summary='## What This Is\n' + ' '.join(f'word{i}' for i in range(80)))

    async def run():
        app = RundownApp(config, fetch_starred=list)
        async with app.run_test(size=(100, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            full = app.query_one('#card-what_it_is Collapsible', Collapsible)
            title = full.query_one('CollapsibleTitle')
            for _ in range(15):
                await pilot.press('tab')
                if title.has_focus:
                    break
            assert title.has_focus
            assert full.collapsed
            await pilot.press('enter')
            await pilot.pause()
            assert not full.collapsed
            await pilot.press('enter')
            await pilot.pause()
            assert full.collapsed

    asyncio.run(run())
