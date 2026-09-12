import sqlite3

import pytest

from rundown import db
from rundown.categories import CATEGORIES, classify_repo, classify_repos


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"full_name": "modelcontextprotocol/servers", "description": "MCP servers for AI agents"}, "AI & Agents"),
        ({"full_name": "astral-sh/ruff", "description": "A fast Python linter"}, "Developer Tools"),
        ({"full_name": "grafana/grafana", "description": "Observability and monitoring dashboards"}, "Infrastructure & Security"),
        ({"full_name": "obsidianmd/obsidian-releases", "description": "Knowledge base and notes"}, "Knowledge & Learning"),
        ({"full_name": "acme/invoicer", "description": "Accounting for small businesses"}, "Apps & Business"),
    ],
)
def test_classify_repo_covers_each_category(metadata, expected):
    assert classify_repo(**metadata) == expected


def test_classify_repo_uses_meaningful_fallback_with_absent_metadata():
    assert classify_repo("owner/mystery") == "Apps & Business"
    assert classify_repo("owner/mystery", None, None, None) == "Apps & Business"


def test_classify_repo_matches_whole_tokens_and_resolves_ties_deterministically():
    assert classify_repo("owner/mail-client") == "Apps & Business"
    assert classify_repo("owner/tool", "An AI CLI") == "AI & Agents"
    assert classify_repo("owner/tool", "RAG Git integration") == "AI & Agents"
    assert classify_repo("owner/tool", "RAG Git integration") == "AI & Agents"


def test_specific_knowledge_purpose_outweighs_supporting_ai_terms():
    assert classify_repo("owner/obsidian-ai", "AI plugin for Obsidian notes") == "Knowledge & Learning"


@pytest.mark.parametrize(
    ("full_name", "description", "expected"),
    [
        ("firstmate/firstmate", "Talk to one agent. Ship with a crew.", "AI & Agents"),
        ("orca/orca", "A fleet of parallel agents", "AI & Agents"),
        ("owner/models", "Use hosted LLMs from Python", "AI & Agents"),
        ("google/osv-scanner", "Vulnerability scanner", "Infrastructure & Security"),
        ("coollabsio/coolify", "Self-hostable PaaS alternative to Vercel", "Infrastructure & Security"),
        ("microsoft/vscode", "Visual Studio Code", "Developer Tools"),
    ],
)
def test_classify_repo_recognizes_common_repository_metadata(
    full_name, description, expected
):
    assert classify_repo(full_name, description) == expected


def test_init_db_migrates_legacy_repo_table_without_losing_data():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA.replace("    category TEXT,\n", ""))
    conn.execute(
        "INSERT INTO repos (full_name, owner, repo, url) VALUES (?, ?, ?, ?)",
        ("owner/legacy", "owner", "legacy", "https://github.com/owner/legacy"),
    )

    db.init_db(conn)
    db.init_db(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)")}
    assert "category" in columns
    assert conn.execute("SELECT full_name FROM repos").fetchone()["full_name"] == "owner/legacy"


def test_classify_repos_persists_is_idempotent_and_force_recomputes():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    fixtures = [
        ("owner/agent", "LLM agent", 1, 0),
        ("owner/archive", "Kubernetes deployment", 1, 1),
        ("owner/old", "Python linter", 1, 0),
        ("owner/unstarred", "Obsidian knowledge base", 0, 0),
    ]
    for full_name, description, starred, archived in fixtures:
        owner, repo = full_name.split("/")
        db.upsert_repo(
            conn,
            db.RepoInput(full_name, owner, repo, f"https://github.com/{full_name}", description=description, archived=bool(archived)),
        )
        conn.execute("UPDATE repos SET starred = ? WHERE full_name = ?", (starred, full_name))
    conn.execute("UPDATE repos SET category = 'Knowledge & Learning' WHERE full_name = 'owner/old'")
    conn.execute("UPDATE repos SET category = 'invalid' WHERE full_name = 'owner/archive'")

    counts = classify_repos(conn)
    assert counts == {
        "AI & Agents": 1,
        "Developer Tools": 0,
        "Infrastructure & Security": 1,
        "Knowledge & Learning": 1,
        "Apps & Business": 0,
    }
    assert db.get_repo(conn, "owner/unstarred")["category"] is None
    assert db.get_repo(conn, "owner/old")["category"] == "Knowledge & Learning"

    assert classify_repos(conn) == counts
    forced = classify_repos(conn, force=True)

    assert forced["Developer Tools"] == 1
    assert forced["Knowledge & Learning"] == 0
    assert db.get_repo(conn, "owner/old")["category"] == "Developer Tools"
    assert db.get_repo(conn, "owner/archive")["category"] == "Infrastructure & Security"


def test_categories_are_the_public_five_in_display_order():
    assert CATEGORIES == (
        "AI & Agents",
        "Developer Tools",
        "Infrastructure & Security",
        "Knowledge & Learning",
        "Apps & Business",
    )
