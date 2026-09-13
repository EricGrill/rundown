import json
import sqlite3

import pytest
from typer.testing import CliRunner

from rundown import db
from rundown.agent_io import AgentError, read_catalog
from rundown.cli import app
from rundown.config import AppConfig, PathSettings


def test_read_catalog_missing_and_incompatible_are_not_mutated(tmp_path):
    cfg = AppConfig(root=tmp_path)
    with read_catalog(cfg) as conn:
        assert conn.execute('SELECT COUNT(*) FROM repos').fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO repos(full_name,owner,repo,url) VALUES('a/b','a','b','url')")
    assert not list(tmp_path.iterdir())
    path = tmp_path / 'wrong.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE something_else(id INTEGER)')
    conn.close()
    before = path.read_bytes()
    with pytest.raises(AgentError, match='required'):
        with read_catalog(AppConfig(root=tmp_path, paths=PathSettings(database=path))):
            pass
    assert path.read_bytes() == before


def test_repos_json_reads_project_without_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig(root=tmp_path)
    with db.session(cfg.database_path) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(conn, db.RepoInput('a/b', 'a', 'b', 'https://github.com/a/b'))
        db.upsert_project_mapping(conn, repo_id, 'app', 80, 'Fits')
    before = cfg.database_path.read_bytes()
    result = CliRunner().invoke(app, ['repos', '--json', '--project', 'app', '--limit', '1'])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['data']['results'][0]['full_name'] == 'a/b'
    assert cfg.database_path.read_bytes() == before
    assert not cfg.wiki_root.exists()


def test_invalid_config_and_limit_are_machine_readable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for args, code in [(['repos', '--json', '--limit', '0'], 'invalid_input'),
                       (['search', 'python', '--json', '-c', 'missing.toml'], 'invalid_config')]:
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 2
        assert json.loads(result.stdout)['error']['code'] == code
    assert list(tmp_path.iterdir()) == []


def test_read_catalog_includes_committed_wal_data(tmp_path):
    path = tmp_path / 'wal.sqlite'
    writer = sqlite3.connect(path)
    writer.execute('PRAGMA journal_mode=WAL')
    writer.execute('CREATE TABLE repos(id INTEGER PRIMARY KEY, full_name TEXT)')
    writer.commit()
    writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    writer.execute("INSERT INTO repos(full_name) VALUES('a/committed')")
    writer.commit()
    try:
        with read_catalog(AppConfig(root=tmp_path, paths=PathSettings(database=path))) as conn:
            assert conn.execute('SELECT full_name FROM repos').fetchone()[0] == 'a/committed'
            with pytest.raises(sqlite3.OperationalError):
                conn.execute('DELETE FROM repos')
        assert writer.execute('SELECT COUNT(*) FROM repos').fetchone()[0] == 1
    finally:
        writer.close()


def test_catalog_listing_supports_legacy_optional_columns(tmp_path):
    from rundown.agent_catalog import catalog_repositories
    path = tmp_path / 'legacy.sqlite'
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE repos(id INTEGER PRIMARY KEY, full_name TEXT, description TEXT)')
    conn.execute('INSERT INTO repos VALUES(1,?,?)', ('a/b', 'x' * 5000))
    conn.commit()
    result = catalog_repositories(conn, limit=1)
    assert len(result['results'][0]['description']) == 1200
    assert result['results'][0]['projects'] == []
    assert catalog_repositories(conn, project='missing')['results'] == []
    conn.close()
