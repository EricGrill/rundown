"""Shared repository research orchestration for CLI and TUI adapters."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from threading import Event

from . import db, preferences, repo_ops, research
from .config import AppConfig
from .processes import check_cancelled

StageCallback = Callable[[str, str], None]


def research_repository(
    config: AppConfig,
    conn: sqlite3.Connection,
    full_name: str,
    *,
    force: bool = False,
    cancel_event: Event | None = None,
    on_stage: StageCallback | None = None,
) -> tuple[str, str]:
    """Clone when needed and research one repository using effective card settings.

    The caller owns the connection transaction and presentation of exceptions.
    """
    check_cancelled(cancel_event)
    row = db.get_repo(conn, full_name)
    if row is None:
        raise ValueError(f"Unknown repository: {full_name}")

    effective_config = replace(
        config,
        cards=preferences.effective_cards(conn, config.cards, row["id"]),
    )
    if not force:
        cached = research.load_cached_repository_research(
            effective_config, conn, row
        )
        if cached is not None:
            check_cancelled(cancel_event)
            return "cached", cached

    if on_stage is not None:
        on_stage("cloning", "Preparing the local repository copy.")
    check_cancelled(cancel_event)
    clone_options = (
        {"cancel_event": cancel_event} if cancel_event is not None else {}
    )
    clone_status, clone_message = repo_ops.clone_repo(
        effective_config, conn, full_name, **clone_options
    )
    if clone_status == "failed":
        check_cancelled(cancel_event)
        return (
            "failed",
            "Research stopped because the repository could not be cloned."
            f"\n\n{clone_message}",
        )

    if on_stage is not None:
        on_stage("researching", "Generating research with the configured provider.")
    check_cancelled(cancel_event)
    if cancel_event is not None and force:
        status, summary = research.run_repository_research(
            effective_config,
            conn,
            full_name,
            force=True,
            cancel_event=cancel_event,
        )
    elif cancel_event is not None:
        status, summary = research.run_repository_research(
            effective_config, conn, full_name, cancel_event=cancel_event
        )
    elif force:
        status, summary = research.run_repository_research(
            effective_config, conn, full_name, force=True
        )
    else:
        status, summary = research.run_repository_research(
            effective_config, conn, full_name
        )
    check_cancelled(cancel_event)

    if clone_status == "cloned" and status != "cancelled":
        summary = f"Automatically cloned {full_name} before research.\n\n{summary}"
    return status, summary
