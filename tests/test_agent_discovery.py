import json
import sqlite3
import subprocess
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from rundown import db
from rundown.agent_io import AgentError
from rundown.discovery import discover_repositories, fetch_public_repository, import_repository
from rundown.discovery_cli import register


def repository(name="owner/tool", **changes):
    return {"full_name": name, "private": False, "visibility": "public", "archived": False,
            "description": "search tool", "language": "Python", "stargazers_count": 100,
            "pushed_at": "2026-09-01T00:00:00Z", **changes}


@pytest.fixture
def conn():
    value = sqlite3.connect(":memory:")
    value.row_factory = sqlite3.Row
    db.init_db(value)
    yield value
    value.close()


def response(items, **extra):
    return subprocess.CompletedProcess([], 0, json.dumps({"items": items, "total_count": len(items),
                                                       "incomplete_results": False, **extra}), "")


def test_discovery_is_bounded_get_excludes_saved_and_explains_results(conn):
    db.upsert_repo(conn, db.RepoInput("owner/saved", "owner", "saved", "https://github.com/owner/saved"))
    before = conn.total_changes
    with patch("rundown.discovery.subprocess.run", return_value=response(
        [repository("OWNER/saved"), repository()], incomplete_results=True, total_count=200
    )) as call:
        result = discover_repositories(conn, "search language:Python", limit=1, sort="stars")
    args = call.call_args.args[0]
    assert args[:5] == ["gh", "api", "--method", "GET", "search/repositories"]
    assert "q=search language:Python is:public archived:false" in args
    assert "sort=stars" in args and "per_page=100" in args
    assert call.call_args.kwargs["timeout"] == 30
    assert result["results"][0]["full_name"] == "owner/tool"
    assert result["results"][0]["github_rank"] == 2
    assert result["incomplete_results"] and result["more_candidates_available"]
    assert conn.total_changes == before


@pytest.mark.parametrize("query,limit,sort", [("", 5, "stars"), ("a", 0, "stars"),
                                               ("a", 101, "stars"), ("a", 5, "wrong"),
                                               ("is:private", 5, "stars")])
def test_invalid_requests_do_not_call_github(conn, query, limit, sort):
    with patch("rundown.discovery.subprocess.run") as call, pytest.raises(AgentError):
        discover_repositories(conn, query, limit=limit, sort=sort)
    call.assert_not_called()


@pytest.mark.parametrize("result,code", [
    (subprocess.CompletedProcess([], 1, "", "HTTP 403: rate limit exceeded"), "github_error"),
    (subprocess.CompletedProcess([], 0, "not json", ""), "github_response"),
    (subprocess.CompletedProcess([], 0, "[]", ""), "github_response"),
    (response([repository(private=True)]), "github_response"),
    (response([repository(stargazers_count="bad")]), "github_response"),
    (response([repository()], incomplete_results="no"), "github_response"),
])
def test_github_failures_are_structured(conn, result, code):
    with patch("rundown.discovery.subprocess.run", return_value=result), pytest.raises(AgentError) as exc:
        discover_repositories(conn, "search")
    assert exc.value.code == code


def test_timeout_and_missing_gh(conn):
    for failure, code in [(subprocess.TimeoutExpired("gh", 30), "github_timeout"),
                          (FileNotFoundError(), "github_unavailable")]:
        with patch("rundown.discovery.subprocess.run", side_effect=failure), pytest.raises(AgentError) as exc:
            discover_repositories(conn, "search")
        assert exc.value.code == code


def test_add_preserves_human_data_and_does_not_star(conn):
    with patch("rundown.discovery._github_json", return_value=repository()):
        metadata = fetch_public_repository("owner/tool")
    assert import_repository(conn, metadata)["status"] == "added"
    row = db.get_repo(conn, "owner/tool")
    assert row["starred"] == 0 and row["last_star_sync"] is None
    db.update_repo(conn, "owner/tool", notes="personal", decision="rejected")
    db.insert_research_log(conn, row["id"], "Repository Understanding", "evidence", "success")
    assert import_repository(conn, metadata)["status"] == "already_saved"
    row = db.get_repo(conn, "owner/tool")
    assert row["notes"] == "personal" and row["decision"] == "rejected"
    assert db.latest_successful_research(conn, row["id"])["summary"] == "evidence"


@pytest.mark.parametrize("name", ["../tool", "owner/..", "--help", "owner/tool/extra"])
def test_unsafe_repository_names_never_reach_subprocess(name):
    with patch("rundown.discovery.subprocess.run") as call, pytest.raises(AgentError):
        fetch_public_repository(name)
    call.assert_not_called()


def test_renamed_repo_requires_explicit_new_name():
    with patch("rundown.discovery._github_json", return_value=repository("new/tool")), pytest.raises(AgentError) as exc:
        fetch_public_repository("old/tool")
    assert exc.value.code == "repository_renamed"


def test_discovery_cli_missing_catalog_is_nonmutating(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = typer.Typer()
    register(app)
    with patch("rundown.discovery.subprocess.run", return_value=response([repository()])):
        result = CliRunner().invoke(app, ["discover", "search", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"]
    assert list(tmp_path.iterdir()) == []
    with patch("rundown.discovery.subprocess.run", side_effect=FileNotFoundError()):
        result = CliRunner().invoke(app, ["add", "owner/tool", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "github_unavailable"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('raw', ['{"a":' * 10000 + '0' + '}' * 10000, 'x' * 4_000_001])
def test_recursive_or_oversized_remote_json_is_reported(conn, raw):
    with patch('rundown.discovery.subprocess.run', return_value=subprocess.CompletedProcess([], 0, raw, '')):
        with pytest.raises(AgentError) as exc:
            discover_repositories(conn, 'search')
    assert exc.value.code == 'github_response'


@pytest.mark.parametrize('changes', [{'stargazers_count': 2**63}, {'description': 'x' * 20001},
                                      {'pushed_at': 'not-a-date'}])
def test_import_rejects_malformed_metadata_before_sqlite(conn, changes):
    with patch('rundown.discovery._github_json', return_value=repository(**changes)):
        with pytest.raises(AgentError) as exc:
            fetch_public_repository('owner/tool')
    assert exc.value.code == 'github_response'


def test_star_sync_promotes_imported_candidate_without_losing_notes(conn):
    with patch('rundown.discovery._github_json', return_value=repository()):
        import_repository(conn, fetch_public_repository('owner/tool'))
    db.update_repo(conn, 'owner/tool', notes='keep')
    db.mark_unstarred_missing(conn, set())
    assert db.get_repo(conn, 'owner/tool')['starred'] == 0
    db.upsert_repo(conn, db.RepoInput('owner/tool', 'owner', 'tool', 'https://github.com/owner/tool'))
    row = db.get_repo(conn, 'owner/tool')
    assert row['starred'] == 1 and row['notes'] == 'keep'


@pytest.mark.parametrize("visibility", ["internal", "private", None])
def test_only_explicitly_public_visibility_can_be_imported(visibility):
    with patch("rundown.discovery._github_json", return_value=repository(visibility=visibility)):
        with pytest.raises(AgentError):
            fetch_public_repository("owner/tool")
