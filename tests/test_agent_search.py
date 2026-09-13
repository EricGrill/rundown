import json
import hashlib
import sqlite3

import typer
from typer.testing import CliRunner

from rundown import db
import rundown.search as search_module
from rundown.search import search_repositories
from rundown.search_cli import register


def _catalog(tmp_path):
    database = tmp_path / "catalog.sqlite"
    conn = db.connect(database)
    db.init_db(conn)
    return conn, database


def test_search_matches_out_of_order_typo_notes_and_research(tmp_path):
    conn, _ = _catalog(tmp_path)
    alpha = db.upsert_repo(conn, db.RepoInput("acme/queue", "acme", "queue", "https://github.com/acme/queue", description="Python background jobs", language="Python"))
    beta = db.upsert_repo(conn, db.RepoInput("acme/other", "acme", "other", "https://github.com/acme/other", description="Utilities"))
    db.update_repo(conn, "acme/other", notes="Works without Redis", problem="Schedule local tasks")
    db.insert_research_log(conn, alpha, "Repository Understanding", "Includes a durable worker pool.", "success", timestamp="2026-01-01T00:00:00+00:00")
    db.insert_research_log(conn, beta, "Repository Understanding", "Old irrelevant text", "success")
    db.insert_research_log(conn, beta, "Repository Understanding", "A redis-free background worker", "success", timestamp="2026-02-01T00:00:00+00:00")
    conn.commit()

    assert search_repositories(conn, "jobs pythn")["results"][0]["full_name"] == "acme/queue"
    note_result = search_repositories(conn, "without redis")["results"][0]
    assert note_result["full_name"] == "acme/other"
    assert "notes" in note_result["matched_fields"]
    assert search_repositories(conn, "durable worker")["results"][0]["generated_matches_unverified"] is True
    assert search_repositories(conn, "schedule tasks")["results"][0]["match_sources"] == [{"field": "problem", "source_kind": "human"}]
    assert search_repositories(conn, "unrelated-zebra")["results"] == []
    conn.close()


def test_exact_name_wins_and_query_limits_do_not_silently_drop_terms(tmp_path):
    conn, _ = _catalog(tmp_path)
    db.upsert_repo(conn, db.RepoInput("acme/queue", "acme", "queue", "https://github.com/acme/queue"))
    db.upsert_repo(conn, db.RepoInput("other/tool", "other", "tool", "https://github.com/other/tool", description="acme queue helper"))
    conn.commit()
    result = search_repositories(conn, "acme/queue")
    assert result["results"][0]["full_name"] == "acme/queue"
    assert result["corpus"]["candidate_cap_reached"] is False
    assert search_repositories(conn, "pythonlonggibberish")["results"] == []
    try:
        search_repositories(conn, " ".join(f"word{i}" for i in range(13)))
    except Exception as exc:
        assert getattr(exc, "code", None) == "invalid_input"
    else:
        raise AssertionError("long token query was accepted")
    conn.close()


def test_fuzzy_excerpt_centers_actual_word_and_matching_work_is_bounded(tmp_path, monkeypatch):
    conn, _ = _catalog(tmp_path)
    description = ("prefix " * 80) + "Python automation"
    db.upsert_repo(conn, db.RepoInput("acme/automation", "acme", "automation", "https://github.com/acme/automation", description=description))
    for index in range(3):
        noisy = " ".join(f"z{index}{item:04d}" for item in range(300))
        db.upsert_repo(conn, db.RepoInput(f"noise/repo{index}", "noise", f"repo{index}", f"https://github.com/noise/repo{index}", description=noisy))
    conn.commit()

    calls = 0
    original = search_module.SequenceMatcher

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(search_module, "SequenceMatcher", counted)
    result = search_repositories(conn, "pythn")
    assert "Python automation" in result["results"][0]["excerpts"]["description"]
    search_repositories(conn, "zzzz")
    assert calls <= 4 * 128
    conn.close()


def test_search_filters_project_archived_and_has_deterministic_ties(tmp_path):
    conn, _ = _catalog(tmp_path)
    ids = []
    for name in ("z/repo", "a/repo"):
        ids.append(db.upsert_repo(conn, db.RepoInput(name, name[0], "repo", f"https://github.com/{name}", description="terminal helper")))
    db.upsert_project_mapping(conn, ids[0], "Work", 80, "fit")
    db.update_repo(conn, "a/repo", archived=1)
    conn.commit()
    assert [r["full_name"] for r in search_repositories(conn, "terminal", include_archived=True)["results"]] == ["a/repo", "z/repo"]
    assert [r["full_name"] for r in search_repositories(conn, "terminal", project="Work")["results"]] == ["z/repo"]
    conn.close()


def test_search_cli_json_and_missing_catalog_are_machine_safe(tmp_path):
    app = typer.Typer()
    register(app)
    app.command("noop")(lambda: None)
    config = tmp_path / "config.toml"
    config.write_text('[paths]\ndatabase = "missing.sqlite"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["search", "python", "--json", "--config", str(config)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["results"] == []
    assert not (tmp_path / "missing.sqlite").exists()

    invalid = CliRunner().invoke(app, ["search", "python", "--limit", "0", "--json", "-c", str(config)])
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "invalid_input"


def test_search_handles_pre_migration_schema_and_read_only_cli_does_not_modify_db(tmp_path):
    database = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE repos (id INTEGER PRIMARY KEY, full_name TEXT, repo TEXT, description TEXT);"
        "INSERT INTO repos VALUES (1, 'old/tool', 'tool', 'Legacy terminal helper');"
    )
    conn.commit()
    assert search_repositories(conn, "terminal")["results"][0]["full_name"] == "old/tool"
    conn.close()

    before = hashlib.sha256(database.read_bytes()).hexdigest()
    config = tmp_path / "legacy.toml"
    config.write_text('[paths]\ndatabase = "legacy.sqlite"\n', encoding="utf-8")
    app = typer.Typer()
    register(app)
    app.command("noop")(lambda: None)
    result = CliRunner().invoke(app, ["search", "terminal", "--json", "-c", str(config)])
    assert result.exit_code == 0
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
