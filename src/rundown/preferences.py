"""Additive SQLite persistence for card templates and catalog views."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from .catalog import CatalogView
from .config import CardSettings, CardTemplateSettings


def ensure_preferences_schema(conn: sqlite3.Connection) -> None:
    # Individual statements preserve the caller's transaction boundary.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS card_preferences (
            scope TEXT PRIMARY KEY,
            settings_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_views (
            name TEXT PRIMARY KEY COLLATE NOCASE,
            view_json TEXT NOT NULL
        )
        """
    )


def _card_json(settings: CardSettings) -> str:
    return json.dumps(asdict(settings), separators=(",", ":"), sort_keys=True)


def _decode_cards(source: str) -> CardSettings:
    value = json.loads(source)
    if not isinstance(value, dict):
        raise ValueError("saved card settings must be an object")
    host = value.get("host")
    research = value.get("research")
    if not isinstance(host, dict) or not isinstance(research, dict):
        raise ValueError("saved card settings require host and research templates")
    return CardSettings(
        default_view=value.get("default_view", "host"),
        audience=value.get("audience", ""),
        tone=value.get("tone", ""),
        duration_seconds=value.get("duration_seconds", 0),
        host=CardTemplateSettings(tuple(host.get("sections", ())), host.get("word_limit", 0)),
        research=CardTemplateSettings(
            tuple(research.get("sections", ())), research.get("word_limit", 0)
        ),
    )


def effective_cards(
    conn: sqlite3.Connection, base: CardSettings, repo_id: int | None = None
) -> CardSettings:
    """Resolve repo override > saved global > config.

    Reading does not mutate preferences; the only possible write is additive,
    idempotent table initialization for databases created by older versions.
    """
    ensure_preferences_schema(conn)
    row = conn.execute(
        "SELECT settings_json FROM card_preferences WHERE scope = 'global'"
    ).fetchone()
    effective = _decode_cards(row[0]) if row else base
    if repo_id is not None:
        row = conn.execute(
            "SELECT settings_json FROM card_preferences WHERE scope = ?",
            (f"repo:{repo_id}",),
        ).fetchone()
        if row:
            effective = _decode_cards(row[0])
    return effective


def load_card_settings(
    conn: sqlite3.Connection,
    base: CardSettings,
    repo_ids: list[int] | tuple[int, ...],
) -> dict[int, CardSettings]:
    """Load all effective profiles in one query after additive schema initialization."""
    ensure_preferences_schema(conn)
    ids = tuple(dict.fromkeys(repo_ids))
    if not ids:
        return {}
    scopes = ("global", *(f"repo:{repo_id}" for repo_id in ids))
    placeholders = ",".join("?" for _ in scopes)
    rows = conn.execute(
        f"SELECT scope, settings_json FROM card_preferences WHERE scope IN ({placeholders})",
        scopes,
    ).fetchall()
    saved = {str(row[0]): _decode_cards(row[1]) for row in rows}
    global_settings = saved.get("global", base)
    return {
        repo_id: saved.get(f"repo:{repo_id}", global_settings) for repo_id in ids
    }


def save_card_settings(
    conn: sqlite3.Connection,
    settings: CardSettings,
    repo_id: int | None = None,
) -> None:
    ensure_preferences_schema(conn)
    if repo_id is not None and repo_id <= 0:
        raise ValueError("repo_id must be positive")
    scope = "global" if repo_id is None else f"repo:{repo_id}"
    conn.execute(
        "INSERT INTO card_preferences(scope, settings_json) VALUES (?, ?) "
        "ON CONFLICT(scope) DO UPDATE SET settings_json = excluded.settings_json",
        (scope, _card_json(settings)),
    )


def clear_card_override(conn: sqlite3.Connection, repo_id: int) -> None:
    ensure_preferences_schema(conn)
    conn.execute("DELETE FROM card_preferences WHERE scope = ?", (f"repo:{repo_id}",))


def _view_json(view: CatalogView) -> str:
    value = asdict(view)
    value.pop("name", None)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _decode_view(source: str, name: str) -> CatalogView:
    value = json.loads(source)
    if not isinstance(value, dict):
        raise ValueError("saved catalog view must be an object")
    return CatalogView(name=name, **value)


def list_named_views(conn: sqlite3.Connection) -> list[CatalogView]:
    """Return saved views; only missing-table initialization can write."""
    ensure_preferences_schema(conn)
    rows = conn.execute("SELECT name, view_json FROM catalog_views ORDER BY name COLLATE NOCASE").fetchall()
    return [_decode_view(row[1], row[0]) for row in rows]


def get_named_view(conn: sqlite3.Connection, name: str) -> CatalogView | None:
    """Return one saved view; only missing-table initialization can write."""
    ensure_preferences_schema(conn)
    row = conn.execute(
        "SELECT name, view_json FROM catalog_views WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return _decode_view(row[1], row[0]) if row else None


def save_named_view(conn: sqlite3.Connection, view: CatalogView) -> None:
    ensure_preferences_schema(conn)
    if view.name is None:
        raise ValueError("named catalog view requires a name")
    name = view.name.strip()
    conn.execute(
        "INSERT INTO catalog_views(name, view_json) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET view_json = excluded.view_json",
        (name, _view_json(view)),
    )


def delete_named_view(conn: sqlite3.Connection, name: str) -> None:
    ensure_preferences_schema(conn)
    conn.execute("DELETE FROM catalog_views WHERE name = ? COLLATE NOCASE", (name,))
