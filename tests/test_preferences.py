import sqlite3
from dataclasses import replace

from rundown.catalog import CatalogView
from rundown.config import CardSettings
from rundown.preferences import (
    clear_card_override,
    delete_named_view,
    effective_cards,
    get_named_view,
    list_named_views,
    load_card_settings,
    save_card_settings,
    save_named_view,
)


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_card_preferences_precedence_and_clear_override():
    conn = connection()
    base = CardSettings(audience="Config")
    global_saved = replace(base, audience="Global")
    repo_saved = replace(base, audience="Repository")

    assert effective_cards(conn, base, 42).audience == "Config"
    save_card_settings(conn, global_saved)
    assert effective_cards(conn, base, 42).audience == "Global"
    save_card_settings(conn, repo_saved, 42)
    assert effective_cards(conn, base, 42).audience == "Repository"
    clear_card_override(conn, 42)
    assert effective_cards(conn, base, 42).audience == "Global"


def test_bulk_card_preferences_use_one_effective_profile_per_repo():
    conn = connection()
    base = CardSettings(audience="Config")
    save_card_settings(conn, replace(base, audience="Global"))
    save_card_settings(conn, replace(base, audience="Repository"), 2)

    loaded = load_card_settings(conn, base, [1, 2, 2])

    assert loaded[1].audience == "Global"
    assert loaded[2].audience == "Repository"


def test_schema_initialization_does_not_commit_caller_transaction():
    conn = connection()
    conn.execute("CREATE TABLE sentinel(value TEXT)")
    conn.commit()
    conn.execute("INSERT INTO sentinel VALUES ('uncommitted')")

    effective_cards(conn, CardSettings())
    conn.rollback()

    assert conn.execute("SELECT * FROM sentinel").fetchall() == []


def test_named_view_crud_is_case_insensitive_and_round_trips():
    conn = connection()
    saved = CatalogView(
        name="Recording",
        query="terminal",
        category="Developer Tools",
        research_filter="stale",
        sort="research_date",
        stale_days=14,
    )
    save_named_view(conn, saved)

    loaded = get_named_view(conn, "recording")
    assert loaded == saved
    assert list_named_views(conn) == [saved]

    save_named_view(conn, replace(saved, name="recording", query="tui"))
    assert len(list_named_views(conn)) == 1
    updated = get_named_view(conn, "RECORDING")
    assert updated is not None
    assert updated.query == "tui"
    delete_named_view(conn, "Recording")
    assert list_named_views(conn) == []
