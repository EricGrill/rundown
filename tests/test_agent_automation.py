from datetime import datetime, timedelta, timezone
import json
import sqlite3
from threading import Event
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from rundown import db
from rundown.agent_io import AgentError, read_catalog
from rundown.automation import project_digest, refresh_candidates, refresh_repositories
from rundown.automation_cli import register
from rundown.config import AppConfig


@pytest.fixture
def catalog(tmp_path):
    config = AppConfig(root=tmp_path)
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        ids = {}
        for name in ('a/missing', 'b/stale', 'c/fresh', 'd/archived'):
            ids[name] = db.upsert_repo(conn, db.RepoInput(name, name[0], name.split('/')[1],
                                                       f'https://github.com/{name}'))
        db.insert_research_log(conn, ids['b/stale'], 'Repository Understanding', 'Old finding', 'success',
                               timestamp=(datetime.now(timezone.utc)-timedelta(days=60)).isoformat())
        db.insert_research_log(conn, ids['c/fresh'], 'Repository Understanding', 'Fresh finding', 'success')
        db.update_repo(conn, 'd/archived', status='archived')
        db.upsert_project_mapping(conn, ids['b/stale'], 'app', 90, 'Useful')
    return config


def test_selection_dry_run_is_bounded_local_and_project_filtered(catalog):
    before = catalog.database_path.read_bytes()
    with patch('rundown.automation.research_workflow.research_repository') as research:
        result = refresh_repositories(catalog, dry_run=True)
        filtered = refresh_repositories(catalog, dry_run=True, project='app')
    assert [item['full_name'] for item in result['selected']] == ['a/missing', 'b/stale']
    assert [item['full_name'] for item in filtered['selected']] == ['b/stale']
    research.assert_not_called()
    assert catalog.database_path.read_bytes() == before
    assert not catalog.wiki_root.exists()
    with read_catalog(catalog) as conn:
        assert len(refresh_candidates(conn, limit=1)) == 1
        with pytest.raises(AgentError):
            refresh_candidates(conn, limit=51)
        with pytest.raises(AgentError):
            refresh_candidates(conn, stale_days=0)


def test_partial_failure_commits_completed_reports_and_forces_stale(catalog):
    forces = []
    def generate(cfg, conn, full_name, *, force, cancel_event):
        forces.append(force)
        if full_name == 'b/stale':
            return 'failed', 'provider unavailable'
        row = db.get_repo(conn, full_name)
        db.insert_research_log(conn, row['id'], 'Repository Understanding', 'New finding', 'success')
        return 'success', 'Saved'
    with patch('rundown.automation.research_workflow.research_repository', side_effect=generate):
        report = refresh_repositories(catalog)
    assert report['status'] == 'partial_failure'
    assert report['succeeded'] == 1 and report['failed'] == 1
    assert forces == [False, True]
    with read_catalog(catalog) as conn:
        row = db.get_repo(conn, 'a/missing')
        assert db.latest_successful_research(conn, row['id'])['summary'] == 'New finding'
        row = db.get_repo(conn, 'b/stale')
        assert db.latest_successful_research(conn, row['id'])['summary'] == 'Old finding'


def test_cancellation_preserves_completed_work_and_stops_next_item(catalog):
    event = Event()
    def generate(cfg, conn, full_name, **kwargs):
        row = db.get_repo(conn, full_name)
        db.insert_research_log(conn, row['id'], 'Repository Understanding', 'Completed', 'success')
        event.set()
        return 'success', 'Saved'
    with patch('rundown.automation.research_workflow.research_repository', side_effect=generate) as call:
        report = refresh_repositories(catalog, cancel_event=event)
    assert call.call_count == 1
    assert report['cancelled'] and report['succeeded'] == 1 and report['remaining'] == 1
    with read_catalog(catalog) as conn:
        row = db.get_repo(conn, 'a/missing')
        assert db.latest_successful_research(conn, row['id'])['summary'] == 'Completed'


def test_digest_uses_saved_fit_and_marks_stale(catalog):
    before = catalog.database_path.read_bytes()
    with read_catalog(catalog) as conn:
        digest = project_digest(conn, project='app')
    assert digest['results'][0]['full_name'] == 'b/stale'
    assert digest['results'][0]['next_action'] == 'research'
    assert digest['results'][0]['summary_source'] == 'generated_research_unverified'
    assert not digest['network_used']
    assert catalog.database_path.read_bytes() == before


def test_cli_dry_run_digest_and_failure_exit(catalog, monkeypatch):
    monkeypatch.chdir(catalog.root)
    app = typer.Typer()
    register(app)
    runner = CliRunner()
    with patch('rundown.automation.research_workflow.research_repository') as call:
        for args in (['refresh', '--dry-run', '--json'], ['digest', '--json']):
            result = runner.invoke(app, args)
            assert result.exit_code == 0, result.output
            assert json.loads(result.stdout)['ok']
    call.assert_not_called()
    with patch('rundown.automation.research_workflow.research_repository', return_value=('failed', 'error')):
        result = runner.invoke(app, ['refresh', '--json'])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert not payload['ok'] and payload['data']['failed'] == 2
    with patch('rundown.automation.research_workflow.research_repository', side_effect=KeyboardInterrupt()):
        result = runner.invoke(app, ['refresh', '--json'])
    assert result.exit_code == 130, result.output
    assert json.loads(result.stdout)['data']['cancelled']


def test_missing_catalog_refresh_does_not_create_directories(tmp_path):
    config = AppConfig(root=tmp_path)
    report = refresh_repositories(config)
    assert report['selected'] == []
    assert list(tmp_path.iterdir()) == []


def test_refresh_candidate_query_never_reads_large_research_bodies(catalog):
    with db.session(catalog.database_path) as conn:
        repo = db.get_repo(conn, 'b/stale')
        db.insert_research_log(
            conn, repo['id'], 'Repository Understanding', 'x' * 500_000, 'success',
            timestamp=(datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
        )
    statements = []
    with read_catalog(catalog) as conn:
        conn.set_trace_callback(statements.append)

        def deny_large_columns(action, _arg1, column, _database, _trigger):
            if action == sqlite3.SQLITE_READ and column in {'summary', 'card_json', 'provenance_json'}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(deny_large_columns)
        selected = refresh_candidates(conn)
    assert [item['full_name'] for item in selected] == ['a/missing', 'b/stale']
    selects = [statement.casefold() for statement in statements if statement.lstrip().upper().startswith('SELECT')]
    assert selects and all('select *' not in statement for statement in selects)


def test_refresh_treats_invalid_activity_timestamp_as_stale(catalog):
    with db.session(catalog.database_path) as conn:
        db.update_repo(conn, 'c/fresh', last_pushed='not-a-timestamp')
    with read_catalog(catalog) as conn:
        selected = refresh_candidates(conn)
    assert [item['full_name'] for item in selected] == ['a/missing', 'b/stale', 'c/fresh']


def test_refresh_handles_legacy_optional_columns_and_tables():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE repos (id INTEGER PRIMARY KEY, full_name TEXT, last_pushed TEXT);"
        "CREATE TABLE research_logs (id INTEGER PRIMARY KEY, repo_id INTEGER);"
        "INSERT INTO repos VALUES (1, 'a/missing', NULL), (2, 'b/legacy', NULL);"
        "INSERT INTO research_logs VALUES (1, 2);"
    )
    assert refresh_candidates(conn) == [
        {'full_name': 'a/missing', 'reason': 'missing', 'research_timestamp': None},
        {'full_name': 'b/legacy', 'reason': 'stale', 'research_timestamp': None},
    ]
    assert refresh_candidates(conn, project='absent') == []
