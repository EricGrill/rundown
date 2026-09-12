"""Tests for the export module and related CLI commands."""
import json

import pytest
from typer.testing import CliRunner

from rundown import db, export, preferences
from rundown.cards import SECTION_TITLES
from rundown.cli import app
from rundown.config import AppConfig, CardSettings, CardTemplateSettings


runner = CliRunner()


def write_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "rundown.toml"
    config_file.write_text(
        """
[paths]
repo_root = "repos"
wiki_root = "wiki"
database = "data/app.sqlite"
logs = "logs"
exports = "exports"
""",
        encoding="utf-8",
    )
    return config_file


def seed_repos(database, with_card=False):
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/present-repo",
                owner="owner",
                repo="present-repo",
                url="https://github.com/owner/present-repo",
                description="A repo marked for presentation",
                language="Python",
                stars=500,
            ),
        )
        db.update_repo(conn, "owner/present-repo", decision="present", category="Developer Tools")
        if with_card:
            db.update_repo(
                conn,
                "owner/present-repo",
                hook="Fast and simple",
                who_for="Developers",
                problem="Slow builds",
                why_now="CI costs rising",
                demo_path="demo/example.mp4",
                notes="Great for monorepos",
            )

        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/shortlist-repo",
                owner="owner",
                repo="shortlist-repo",
                url="https://github.com/owner/shortlist-repo",
                description="A repo on the shortlist",
                language="Rust",
                stars=1200,
            ),
        )
        db.update_repo(conn, "owner/shortlist-repo", decision="shortlist", category="Infrastructure & Security")

        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/inbox-repo",
                owner="owner",
                repo="inbox-repo",
                url="https://github.com/owner/inbox-repo",
                description="A repo not yet reviewed",
                language="Go",
                stars=100,
            ),
        )


def test_format_repo_markdown_basic():
    class MockRow(dict):
        def __getitem__(self, key):
            return self.get(key)

    row = MockRow({
        "full_name": "owner/project",
        "description": "A great project",
        "url": "https://github.com/owner/project",
        "stars": 1000,
        "language": "Python",
        "category": "Developer Tools",
        "hook": None,
        "who_for": None,
        "problem": None,
        "why_now": None,
        "demo_path": None,
        "notes": None,
    })
    result = export.format_repo_markdown(row)
    assert "## owner/project" in result
    assert "A great project" in result
    assert "1,000 stars" in result
    assert "Python" in result
    assert "Developer Tools" in result
    assert "https://github.com/owner/project" in result


def test_format_repo_markdown_with_card():
    class MockRow(dict):
        def __getitem__(self, key):
            return self.get(key)

    row = MockRow({
        "full_name": "owner/project",
        "description": "A great project",
        "url": "https://github.com/owner/project",
        "stars": 500,
        "language": "Rust",
        "category": "AI & Agents",
        "hook": "10x faster",
        "who_for": "ML engineers",
        "problem": "Slow training",
        "why_now": "GPU costs",
        "demo_path": "demo/video.mp4",
        "notes": "Check the benchmarks",
    })
    result = export.format_repo_markdown(row)
    assert "**Hook:** 10x faster" in result
    assert "**For:** ML engineers" in result
    assert "**Problem:** Slow training" in result
    assert "**Why now:** GPU costs" in result
    assert "Demo: demo/video.mp4" in result
    assert "*Check the benchmarks*" in result


def test_generate_export_empty():
    result = export.generate_export([])
    assert "No repositories marked for presentation" in result


def test_list_repos_by_decision(tmp_path):
    database = tmp_path / "app.sqlite"
    seed_repos(database)

    with db.session(database) as conn:
        db.init_db(conn)
        present = db.list_repos_by_decision(conn, ["present"])
        shortlist = db.list_repos_by_decision(conn, ["shortlist"])
        both = db.list_repos_by_decision(conn, ["present", "shortlist"])

    assert len(present) == 1
    assert present[0]["full_name"] == "owner/present-repo"
    assert len(shortlist) == 1
    assert shortlist[0]["full_name"] == "owner/shortlist-repo"
    assert len(both) == 2


def test_export_to_file(tmp_path):
    database = tmp_path / "app.sqlite"
    output_path = tmp_path / "export.md"
    seed_repos(database, with_card=True)

    with db.session(database) as conn:
        db.init_db(conn)
        count = export.export_to_file(conn, output_path)

    assert count == 2
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "# Rundown Export" in content
    assert "owner/present-repo" in content
    assert "owner/shortlist-repo" in content
    assert "owner/inbox-repo" not in content
    assert "**Hook:** Fast and simple" in content


def test_card_export_uses_effective_template_manual_overrides_and_host_notes(tmp_path):
    database = tmp_path / "app.sqlite"
    output_path = tmp_path / "host.md"
    seed_repos(database, with_card=True)
    config = AppConfig(root=tmp_path)
    settings = CardSettings(
        host=CardTemplateSettings(
            sections=("why_now", "hook", "use_cases", "demo", "what_it_is"),
            word_limit=100,
        ),
    )
    card_json = json.dumps(
        {
            "schema_version": 1,
            "sections": {
                section_id: {
                    "hook": "Generated hook",
                    "what_it_is": "Generated explanation",
                    "use_cases": "Generated audience",
                    "why_now": "Generated urgency",
                    "demo": "Generated demo",
                }.get(section_id)
                for section_id in SECTION_TITLES
            },
        }
    )
    with db.session(database) as conn:
        db.init_db(conn)
        repo = db.get_repo(conn, "owner/present-repo")
        preferences.save_card_settings(conn, settings, repo["id"])
        db.save_repo_card(conn, repo["id"], view="host", host_notes="Ask about adoption.")
        db.insert_research_log(
            conn,
            repo["id"],
            "Repository Understanding",
            "generated",
            "success",
            card_json=card_json,
        )
        export.export_to_file(conn, output_path, ["present"], config=config)

    content = output_path.read_text(encoding="utf-8")
    assert content.index("### Why Now") < content.index("### Hook")
    assert "CI costs rising" in content and "Generated urgency" not in content
    assert "Fast and simple" in content and "Generated hook" not in content
    assert "**For:** Developers" in content and "**Problem:** Slow builds" in content
    assert "demo/example.mp4" in content and "Generated demo" not in content
    assert "Generated explanation" in content
    assert "### Host Notes\n\nAsk about adoption." in content
    assert "### Repository Notes\n\nGreat for monorepos" in content


def test_card_export_supports_explicit_research_view_and_legacy_markdown(tmp_path):
    database = tmp_path / "app.sqlite"
    output_path = tmp_path / "research.md"
    seed_repos(database)
    config = AppConfig(
        root=tmp_path,
        cards=CardSettings(
            research=CardTemplateSettings(
                sections=("risks", "what_it_is"),
                word_limit=100,
            )
        ),
    )
    legacy = "## What This Is\n\nA legacy explanation.\n\n## Limitations and Risks\n\nA legacy risk."
    with db.session(database) as conn:
        db.init_db(conn)
        repo = db.get_repo(conn, "owner/present-repo")
        db.insert_research_log(
            conn,
            repo["id"],
            "Repository Understanding",
            legacy,
            "success",
        )
        export.export_to_file(
            conn,
            output_path,
            ["present"],
            config=config,
            view="research",
        )

    content = output_path.read_text(encoding="utf-8")
    assert content.index("### Limitations and Risks") < content.index("### What This Is")
    assert "A legacy risk." in content
    assert "A legacy explanation." in content


def test_card_export_keeps_notes_when_research_is_empty(tmp_path):
    database = tmp_path / "app.sqlite"
    output_path = tmp_path / "empty.md"
    seed_repos(database, with_card=True)
    config = AppConfig(root=tmp_path)
    with db.session(database) as conn:
        db.init_db(conn)
        repo = db.get_repo(conn, "owner/present-repo")
        db.save_repo_card(conn, repo["id"], host_notes="Keep this host note.")
        export.export_to_file(conn, output_path, ["present"], config=config)

    content = output_path.read_text(encoding="utf-8")
    assert "Keep this host note." in content
    assert "Great for monorepos" in content
    assert "**For:** Developers" in content
    assert "**Problem:** Slow builds" in content


def test_research_export_preserves_manual_fields_omitted_by_template(tmp_path):
    database = tmp_path / "app.sqlite"
    output_path = tmp_path / "research-manual.md"
    seed_repos(database, with_card=True)
    with db.session(database) as conn:
        db.init_db(conn)
        export.export_to_file(
            conn,
            output_path,
            ["present"],
            config=AppConfig(root=tmp_path),
            view="research",
        )

    content = output_path.read_text(encoding="utf-8")
    assert "### Presentation Details" in content
    assert "**Hook:** Fast and simple" in content
    assert "Demo: demo/example.mp4" in content


def test_card_export_preview_keeps_full_section_in_disclosure(tmp_path):
    database = tmp_path / "app.sqlite"
    output_path = tmp_path / "full-section.md"
    seed_repos(database)
    config = AppConfig(
        root=tmp_path,
        cards=CardSettings(
            host=CardTemplateSettings(sections=("what_it_is",), word_limit=10)
        ),
    )
    full_text = " ".join(f"word-{index}" for index in range(25))
    card_json = json.dumps(
        {
            "schema_version": 1,
            "sections": {
                section_id: full_text if section_id == "what_it_is" else None
                for section_id in SECTION_TITLES
            },
        }
    )
    with db.session(database) as conn:
        db.init_db(conn)
        repo = db.get_repo(conn, "owner/present-repo")
        db.insert_research_log(
            conn,
            repo["id"],
            "Repository Understanding",
            "generated",
            "success",
            card_json=card_json,
        )
        export.export_to_file(conn, output_path, ["present"], config=config)

    content = output_path.read_text(encoding="utf-8")
    assert "<summary>Read full section</summary>" in content
    assert full_text in content


def test_export_cli_command(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    seed_repos(database)

    result = runner.invoke(app, ["export", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert "Exported 2 repositories" in result.output
    export_path = tmp_path / "exports" / "rundown-export.md"
    assert export_path.exists()


def test_export_cli_custom_output(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    seed_repos(database)
    custom_output = tmp_path / "custom" / "output.md"

    result = runner.invoke(app, ["export", "--config", str(config_file), "--output", str(custom_output)])

    assert result.exit_code == 0, result.output
    assert custom_output.exists()


def test_export_cli_filter_decision(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    seed_repos(database)

    result = runner.invoke(
        app,
        ["export", "--config", str(config_file), "--decision", "present"],
    )

    assert result.exit_code == 0, result.output
    assert "Exported 1 repositories" in result.output


def test_export_cli_no_repos(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/inbox",
                owner="owner",
                repo="inbox",
                url="https://github.com/owner/inbox",
            ),
        )

    result = runner.invoke(app, ["export", "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert "No repositories with decision" in result.output


@pytest.mark.parametrize("decision", ["present", "shortlist"])
def test_mark_present_and_shortlist(tmp_path, decision):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/project",
                owner="owner",
                repo="project",
                url="https://github.com/owner/project",
            ),
        )

    result = runner.invoke(
        app,
        ["mark", "owner/project", decision, "--config", str(config_file)],
    )

    assert result.exit_code == 0, result.output
    assert f"Marked owner/project as {decision}" in result.output
    with db.session(database) as conn:
        row = db.get_repo(conn, "owner/project")
        assert row["decision"] == decision


def test_card_command_sets_fields(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/project",
                owner="owner",
                repo="project",
                url="https://github.com/owner/project",
            ),
        )

    result = runner.invoke(
        app,
        [
            "card", "owner/project",
            "--hook", "Super fast",
            "--who-for", "Developers",
            "--config", str(config_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Updated card for owner/project" in result.output
    with db.session(database) as conn:
        row = db.get_repo(conn, "owner/project")
        assert row["hook"] == "Super fast"
        assert row["who_for"] == "Developers"


def test_card_command_requires_at_least_one_field(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/project",
                owner="owner",
                repo="project",
                url="https://github.com/owner/project",
            ),
        )

    result = runner.invoke(
        app,
        ["card", "owner/project", "--config", str(config_file)],
    )

    assert result.exit_code == 1
    assert "No card fields provided" in result.output


def test_card_command_unknown_repo(tmp_path):
    config_file = write_config(tmp_path)
    database = tmp_path / "data" / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)

    result = runner.invoke(
        app,
        ["card", "missing/project", "--hook", "Test", "--config", str(config_file)],
    )

    assert result.exit_code != 0
    assert "Unknown repository" in result.output


def test_db_card_fields_migration(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        stripped_schema = db.SCHEMA
        for field in ("hook", "who_for", "problem", "why_now", "demo_path"):
            stripped_schema = stripped_schema.replace(f"    {field} TEXT,\n", "")
        conn.executescript(stripped_schema)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
        assert "hook" not in columns

        db.init_db(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}

    for field in ("hook", "who_for", "problem", "why_now", "demo_path"):
        assert field in columns
