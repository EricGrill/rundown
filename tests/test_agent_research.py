import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from rundown import db
from rundown.cli import app
from rundown.config import AppConfig
from rundown.processes import OperationCancelled


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = AppConfig(root=tmp_path)
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        db.upsert_repo(conn, db.RepoInput('a/b', 'a', 'b', 'https://github.com/a/b'))
    return config


@pytest.mark.parametrize('status,code', [('success', 0), ('cached', 0), ('failed', 1), ('cancelled', 130)])
def test_json_research_outcomes_and_force(catalog, status, code):
    with patch('rundown.cli.research_workflow.research_repository', return_value=(status, 'detail')) as call:
        result = CliRunner().invoke(app, ['research', 'a/b', '--force', '--json'])
    assert result.exit_code == code, result.output
    data = json.loads(result.stdout)
    assert data['ok'] is (code == 0)
    assert data['data']['status'] == status
    assert call.call_args.kwargs['force'] is True


@pytest.mark.parametrize('failure', [KeyboardInterrupt(), OperationCancelled('cancel')])
def test_cancellation_has_machine_error(catalog, failure):
    with patch('rundown.cli.research_workflow.research_repository', side_effect=failure):
        result = CliRunner().invoke(app, ['research', 'a/b', '--json'])
    assert result.exit_code == 130
    assert json.loads(result.stdout)['error']['code'] == 'cancelled'


def test_unknown_research_never_creates_catalog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch('rundown.cli.research_workflow.research_repository') as call:
        result = CliRunner().invoke(app, ['research', 'a/b', '--json'])
    assert result.exit_code == 1
    assert json.loads(result.stdout)['error']['code'] == 'not_found'
    call.assert_not_called()
    assert list(tmp_path.iterdir()) == []
