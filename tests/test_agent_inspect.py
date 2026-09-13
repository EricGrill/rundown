import json
import sqlite3

import typer
from typer.testing import CliRunner

from rundown import db
from rundown.inspect_cli import register
from rundown.inspection import inspect_repository


def _catalog(tmp_path):
    database = tmp_path / "catalog.sqlite"
    conn = db.connect(database)
    db.init_db(conn)
    repo_id = db.upsert_repo(
        conn,
        db.RepoInput(
            "owner/project", "owner", "project", "https://github.com/owner/project",
            description="Useful toolkit", language="Python", last_pushed="2026-09-01T00:00:00+00:00",
        ),
    )
    return conn, database, repo_id


def test_inspection_separates_generated_human_project_and_staleness(tmp_path):
    conn, _, repo_id = _catalog(tmp_path)
    db.update_repo(conn, "owner/project", notes="Try this for the editor", hook="Fast setup")
    db.save_repo_card(conn, repo_id, host_notes="Ask about offline mode")
    db.upsert_project_mapping(conn, repo_id, "Editor", 90, "Matches the plugin model")
    provenance = json.dumps({"provider": "codex", "context_files": [{"path": "README.md", "sha256": "abc"}]})
    card = json.dumps({"schema_version": 1, "sections": {"what_it_is": "A toolkit", "risks": "Generated caveat"}})
    db.insert_research_log(conn, repo_id, "Repository Understanding", "ignored fallback", "success", card_json=card, provenance_json=provenance, timestamp="2026-08-01T00:00:00+00:00")
    conn.commit()

    packet = inspect_repository(conn, "owner/project", stale_days=30)
    assert packet["generated_research"]["record"]["sections"]["what_it_is"] == "A toolkit"
    assert packet["generated_research"]["source_kind"] == "generated"
    assert packet["source_references"]["verification"] == "unverified"
    assert packet["human_notes"]["repository_notes"] == "Try this for the editor"
    assert packet["human_notes"]["source_kind"] == "human"
    assert packet["project_mappings"][0]["project"] == "Editor"
    assert packet["staleness"]["stale"] is True
    assert "Repository activity is newer" in " ".join(packet["staleness"]["reasons"])
    conn.close()


def test_inspection_compact_truncates_and_full_preserves_legacy_text(tmp_path):
    conn, _, repo_id = _catalog(tmp_path)
    long_text = "legacy words " * 300
    db.insert_research_log(conn, repo_id, "Repository Understanding", long_text, "success")
    conn.commit()
    compact = inspect_repository(conn, "owner/project")
    complete = inspect_repository(conn, "owner/project", full=True)
    assert compact["truncation"]["truncated"] is True
    assert "generated_research.record.text" in compact["truncation"]["fields"]
    assert len(compact["generated_research"]["record"]["text"]) < len(long_text)
    assert complete["generated_research"]["record"]["text"] == long_text
    assert complete["truncation"]["truncated"] is False
    assert complete["truncation"]["max_total_text_chars"] == 1_000_000
    conn.close()


def test_inspect_cli_json_not_found_and_invalid_staleness(tmp_path):
    app = typer.Typer()
    register(app)
    app.command("noop")(lambda: None)
    config = tmp_path / "config.toml"
    config.write_text('[paths]\ndatabase = "missing.sqlite"\n', encoding="utf-8")

    missing = CliRunner().invoke(app, ["inspect", "owner/missing", "--json", "-c", str(config)])
    assert missing.exit_code == 1
    assert json.loads(missing.stdout)["error"]["code"] == "not_found"
    assert not (tmp_path / "missing.sqlite").exists()

    invalid = CliRunner().invoke(app, ["inspect", "owner/missing", "--stale-days", "0", "--json", "-c", str(config)])
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "invalid_input"


def test_inspection_reads_legacy_optional_columns(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE repos (id INTEGER PRIMARY KEY, full_name TEXT, description TEXT);"
        "CREATE TABLE research_logs (id INTEGER PRIMARY KEY, repo_id INTEGER, summary TEXT, status TEXT);"
        "INSERT INTO repos VALUES (1, 'legacy/repo', NULL);"
        "INSERT INTO research_logs VALUES (1, 1, 'Legacy report', 'success');"
    )
    packet = inspect_repository(conn, "legacy/repo")
    assert packet["generated_research"]["record"]["format"] == "legacy_markdown"
    assert packet["generated_research"]["provenance"] is None
    assert "generated_research.provenance" in packet["missing_information"]


def test_inspection_rejects_recursive_saved_json_without_crashing(tmp_path):
    conn, _, repo_id = _catalog(tmp_path)
    nested_card = '{"schema_version":1,"sections":{"what_it_is":' + "[" * 1100 + '"x"' + "]" * 1100 + "}}"
    nested_provenance = '{"child":' * 1100 + "{}" + "}" * 1100
    db.insert_research_log(
        conn, repo_id, "Repository Understanding", "Fallback legacy report", "success",
        card_json=nested_card, provenance_json=nested_provenance,
    )
    conn.commit()
    packet = inspect_repository(conn, "owner/project")
    assert packet["generated_research"]["record"]["text"] == "Fallback legacy report"
    assert packet["generated_research"]["provenance"] is None
    assert any("omitted" in message or "invalid" in message for message in packet["generated_research"]["diagnostics"])


def test_inspection_bounds_mappings_and_marks_invalid_activity_stale(tmp_path):
    conn, _, repo_id = _catalog(tmp_path)
    db.update_repo(conn, "owner/project", last_pushed="not-a-timestamp")
    for index in range(105):
        db.upsert_project_mapping(conn, repo_id, f"Project {index:03d}", index, "r" * 2_000)
    db.insert_research_log(
        conn, repo_id, "Repository Understanding", "Saved report", "success",
        timestamp="2026-09-12T00:00:00+00:00",
    )
    conn.commit()
    packet = inspect_repository(conn, "owner/project", stale_days=30)
    assert len(packet["project_mappings"]) == 100
    assert "project_mappings" in packet["truncation"]["fields"]
    assert packet["staleness"]["stale"] is True
    assert "freshness cannot be determined" in " ".join(packet["staleness"]["reasons"])
