"""Shared machine-output and read-only catalog boundaries for agent commands."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator

import typer

from . import db
from .config import AppConfig, load_config


class AgentError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def load_agent_config(path: Path | None = None) -> AppConfig:
    if path is not None and not path.is_file():
        raise AgentError("invalid_config", f"Configuration does not exist: {path}", 2)
    return load_config(path)


@contextmanager
def read_catalog(config: AppConfig) -> Iterator[sqlite3.Connection]:
    """Never create files or migrate a user's database to answer a query."""
    path = config.database_path
    if path.exists():
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    else:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
    try:
        conn.execute("PRAGMA query_only = ON")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)")}
        if not {"id", "full_name"}.issubset(columns):
            raise AgentError("incompatible_catalog", "Catalog is missing required repos.id/full_name columns.")
        yield conn
    finally:
        conn.close()


def envelope(data: Any = None, error: AgentError | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": error is None,
        "data": data,
        "error": {"code": error.code, "message": str(error)} if error else None,
    }


def emit(data: Any, json_output: bool, error: AgentError | None = None) -> None:
    if json_output:
        typer.echo(json.dumps(envelope(data, error), ensure_ascii=False))
    elif error:
        typer.echo(f"{error.code}: {error}", err=True)
    else:
        # Plain JSON is also a readable, lossless default for inspection packets.
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def run_command(operation: Callable[[], Any], json_output: bool) -> None:
    try:
        data = operation()
    except AgentError as exc:
        emit(None, json_output, exc)
        raise typer.Exit(exc.exit_code) from exc
    except (ValueError, TypeError) as exc:
        emit(None, json_output, AgentError("invalid_input", str(exc), 2))
        raise typer.Exit(2) from exc
    except (OSError, sqlite3.Error) as exc:
        emit(None, json_output, AgentError("operation_failed", str(exc)))
        raise typer.Exit(1) from exc
    except KeyboardInterrupt as exc:
        emit(None, json_output, AgentError("cancelled", "Operation cancelled.", 130))
        raise typer.Exit(130) from exc
    emit(data, json_output)


def validate_limit(limit: int, maximum: int = 100) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise AgentError("invalid_input", f"limit must be between 1 and {maximum}", 2)
