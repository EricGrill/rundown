import asyncio

from textual.widgets import DataTable, Input, Select, Static
from typer.testing import CliRunner

from rundown import categories, db
from rundown.cli import app
from rundown.config import AppConfig, PathSettings
from rundown.tui import RundownApp


def seed(config):
    repos = [
        db.RepoInput('owner/chat-agent', 'owner', 'chat-agent', 'https://github.com/owner/chat-agent', description='LLM agent', starred_at='2026-09-12'),
        db.RepoInput('owner/code-agent', 'owner', 'code-agent', 'https://github.com/owner/code-agent', description='AI coding agent', starred_at='2026-09-11'),
        db.RepoInput('owner/lazygit', 'owner', 'lazygit', 'https://github.com/owner/lazygit', description='Terminal UI for git commands', starred_at='2026-09-10'),
    ]
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        for repo in repos:
            db.upsert_repo(conn, repo)
    return repos


def test_classify_command_persists_five_categories_and_force(tmp_path):
    config_file = tmp_path / 'config.toml'
    database = tmp_path / 'app.sqlite'
    config_file.write_text(f'[paths]\ndatabase = "{database}"\n')
    config = AppConfig(root=tmp_path, paths=PathSettings(database=database))
    seed(config)
    runner = CliRunner()
    result = runner.invoke(app, ['classify', '-c', str(config_file)])
    assert result.exit_code == 0, result.output
    assert 'Classified 3 starred repositories into 5 categories.' in result.output
    for category in categories.CATEGORIES:
        assert category in result.output
    with db.session(database) as conn:
        assert db.get_repo(conn, 'owner/chat-agent')['category'] == 'AI & Agents'
        db.update_repo(conn, 'owner/chat-agent', category='Apps & Business')
    result = runner.invoke(app, ['classify', '-c', str(config_file)])
    assert result.exit_code == 0, result.output
    with db.session(database) as conn:
        assert db.get_repo(conn, 'owner/chat-agent')['category'] == 'Apps & Business'
    result = runner.invoke(app, ['classify', '--force', '-c', str(config_file)])
    assert result.exit_code == 0, result.output
    with db.session(database) as conn:
        assert db.get_repo(conn, 'owner/chat-agent')['category'] == 'AI & Agents'


def test_sync_command_classifies_new_stars(tmp_path, monkeypatch):
    config_file = tmp_path / 'config.toml'
    database = tmp_path / 'app.sqlite'
    config_file.write_text(f'[paths]\ndatabase = "{database}"\n')
    monkeypatch.setattr('rundown.cli.github.fetch_starred', lambda **kwargs: [
        db.RepoInput('owner/agent', 'owner', 'agent', 'https://github.com/owner/agent', description='LLM agent'),
    ])
    result = CliRunner().invoke(app, ['sync-stars', '-c', str(config_file)])
    assert result.exit_code == 0, result.output
    with db.session(database) as conn:
        assert db.get_repo(conn, 'owner/agent')['category'] == 'AI & Agents'


def test_category_keyboard_filter_combines_search_and_escape_clears(tmp_path):
    config = AppConfig(root=tmp_path, paths=PathSettings(database=tmp_path / 'app.sqlite'))
    repos = seed(config)

    async def run_test():
        tui = RundownApp(config, fetch_starred=lambda: repos)
        async with tui.run_test(size=(100, 30)) as pilot:
            await tui.workers.wait_for_complete()
            await pilot.pause()
            table = tui.query_one('#repos', DataTable)
            selector = tui.query_one('#category', Select)
            assert table.row_count == 3
            await pilot.press('f', 'down', 'enter')
            await pilot.pause()
            assert selector.value == 'AI & Agents'
            assert table.row_count == 2
            assert 'Category: AI & Agents' in str(tui.query_one('#detail', Static).render())
            tui.action_find()
            await pilot.press(*'chat', 'enter')
            await pilot.pause()
            assert table.row_count == 1
            assert tui.selected_full_name() == 'owner/chat-agent'
            selector.value = 'Infrastructure & Security'
            await pilot.pause()
            assert table.row_count == 0
            assert tui.selected_full_name() is None
            assert 'No matching repositories' in str(tui.query_one('#detail', Static).render())
            await pilot.press('escape')
            await pilot.pause()
            assert selector.value == 'all'
            assert tui.query_one('#search', Input).value == ''
            assert table.row_count == 3

    asyncio.run(run_test())


def test_category_filter_and_selection_survive_sync_and_reclassification(tmp_path):
    config = AppConfig(root=tmp_path, paths=PathSettings(database=tmp_path / 'app.sqlite'))
    repos = seed(config)

    async def run_test():
        tui = RundownApp(config, fetch_starred=lambda: repos)
        async with tui.run_test(size=(80, 24)) as pilot:
            await tui.workers.wait_for_complete()
            selector = tui.query_one('#category', Select)
            selector.value = 'AI & Agents'
            await pilot.pause()
            table = tui.query_one('#repos', DataTable)
            table.move_cursor(row=1)
            table.focus()
            await pilot.pause()
            assert tui.selected_full_name() == 'owner/code-agent'
            await pilot.press('enter', 'escape')
            await pilot.pause()
            assert selector.value == 'AI & Agents'
            repos.append(db.RepoInput('owner/new-agent', 'owner', 'new-agent', 'https://github.com/owner/new-agent', description='LLM agent', starred_at='2026-09-13'))
            tui.action_sync()
            await tui.workers.wait_for_complete()
            await pilot.pause()
            assert selector.value == 'AI & Agents'
            assert table.row_count == 3
            assert tui.selected_full_name() == 'owner/code-agent'
            assert table.get_row_at(0)[0] == 'owner/new-agent'
            tui.action_classify()
            await pilot.pause()
            assert selector.value == 'AI & Agents'
            assert tui.selected_full_name() == 'owner/code-agent'
            assert 'Classified 4 starred repositories' in str(tui.query_one('#status', Static).render())
            assert selector.region.right <= tui.size.width

    asyncio.run(run_test())


def test_cached_category_browsing_survives_another_database_writer(tmp_path):
    config = AppConfig(root=tmp_path, paths=PathSettings(database=tmp_path / 'app.sqlite'))
    seed(config)
    writer = db.connect(config.database_path)
    writer.execute('BEGIN IMMEDIATE')

    def offline():
        raise RuntimeError('Offline')

    async def run_test():
        tui = RundownApp(config, fetch_starred=offline)
        async with tui.run_test(size=(100, 30)) as pilot:
            await tui.workers.wait_for_complete()
            await pilot.pause()
            selector = tui.query_one('#category', Select)
            selector.value = 'AI & Agents'
            await pilot.pause()
            assert tui.query_one('#repos', DataTable).row_count == 2
            tui.action_classify()
            assert 'Database is busy' in str(tui.query_one('#status', Static).render())
            writer.rollback()
            tui.action_classify()
            assert 'Classified 3 starred repositories' in str(tui.query_one('#status', Static).render())
            with db.session(config.database_path) as conn:
                assert db.get_repo(conn, 'owner/chat-agent')['category'] == 'AI & Agents'

    try:
        asyncio.run(run_test())
    finally:
        writer.close()
