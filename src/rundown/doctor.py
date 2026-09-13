from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import AppConfig, load_config
from .harnesses import selected_harnesses

CheckStatus = Literal["ok", "warning", "error"]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str
    fix: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(check.status != "error" for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.healthy else 1


def _command_version(command: str) -> DoctorCheck:
    executable = shutil.which(command)
    if executable is None:
        return DoctorCheck(
            command,
            "error" if command == "git" else "warning",
            f"{command} is not installed or is not on PATH.",
            f"Install {command} and reopen the terminal.",
        )
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DoctorCheck(
            command,
            "error" if command == "git" else "warning",
            f"{command} is present but could not be executed.",
            f"Check the {command} installation and PATH.",
        )
    output = (result.stdout or result.stderr).strip().splitlines()
    if result.returncode != 0:
        return DoctorCheck(
            command,
            "error" if command == "git" else "warning",
            f"{command} returned exit code {result.returncode}.",
            f"Repair or reinstall {command}.",
        )
    return DoctorCheck(command, "ok", output[0] if output else f"{command} is available.")


def _github_check() -> DoctorCheck:
    executable = shutil.which("gh")
    if executable is None:
        return DoctorCheck(
            "GitHub authentication",
            "warning",
            "GitHub CLI is not installed, so star synchronization is unavailable.",
            "Install GitHub CLI, then run `gh auth login`.",
        )
    try:
        result = subprocess.run(
            [executable, "auth", "status"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DoctorCheck(
            "GitHub authentication",
            "warning",
            "GitHub authentication status could not be checked.",
            "Run `gh auth status`, then `gh auth login` if needed.",
        )
    if result.returncode != 0:
        return DoctorCheck(
            "GitHub authentication",
            "warning",
            "GitHub CLI is installed but is not authenticated.",
            "Run `gh auth login`.",
        )
    return DoctorCheck(
        "GitHub authentication",
        "ok",
        "GitHub CLI reports an authenticated account.",
    )


def _provider_check(config: AppConfig) -> DoctorCheck:
    selected = selected_harnesses(config.research)
    available = tuple(adapter.identifier for adapter in selected if shutil.which(adapter.executable))
    order = ", ".join(adapter.identifier for adapter in selected)
    if not available:
        return DoctorCheck(
            "Research provider", "warning" if config.research.provider == "auto" else "error",
            f"No configured research harness is installed. Order: {order}.",
            "Install and authenticate a configured harness; saved research still works.",
        )
    return DoctorCheck(
        "Research provider", "ok",
        f"Configured order: {order}. Available: {', '.join(available)}. "
        f"Requested model: {config.research.model or 'CLI default'}. Authentication was not probed.",
        "Run the selected provider's own auth-status command if generation fails.",
    )


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _database_check(config: AppConfig) -> DoctorCheck:
    database = config.database_path
    if not database.exists():
        parent = _nearest_existing_parent(database.parent)
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            return DoctorCheck(
                "Database",
                "error",
                f"Database does not exist and {parent} is not writable.",
                "Choose a writable paths.database location.",
            )
        return DoctorCheck(
            "Database",
            "warning",
            f"Database does not exist yet; Rundown can create it at {database}.",
        )
    if not database.is_file():
        return DoctorCheck(
            "Database",
            "error",
            f"Configured database path is not a file: {database}.",
            "Set paths.database to a SQLite file path.",
        )
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        return DoctorCheck(
            "Database",
            "error",
            f"SQLite could not read the database: {exc}.",
            "Restore the database from a backup or choose another paths.database file.",
        )
    if result is None or result[0] != "ok":
        return DoctorCheck(
            "Database",
            "error",
            "SQLite integrity_check did not return ok.",
            "Restore the database from a known-good backup.",
        )
    if not os.access(database, os.W_OK):
        return DoctorCheck(
            "Database",
            "error",
            f"Database is healthy but is not writable: {database}.",
            "Grant write access or choose a writable paths.database file.",
        )
    return DoctorCheck("Database", "ok", f"SQLite integrity check passed: {database}.")


def run_doctor(config_path: Path | None = None) -> DoctorReport:
    """Inspect local prerequisites without invoking an AI provider or exposing secrets."""

    python_ok = sys.version_info >= (3, 11)
    checks = [
        DoctorCheck(
            "Python",
            "ok" if python_ok else "error",
            f"Python {platform.python_version()} on {platform.system()} {platform.machine()}.",
            None if python_ok else "Install Python 3.11 or newer.",
        ),
        _command_version("git"),
        _command_version("gh"),
        _github_check(),
    ]
    if config_path is not None and not config_path.is_file():
        checks.append(
            DoctorCheck(
                "Configuration",
                "error",
                f"Configuration file does not exist: {config_path}.",
                "Pass an existing TOML file or omit --config to use defaults.",
            )
        )
        return DoctorReport(tuple(checks))
    try:
        config = load_config(config_path)
    except (OSError, ValueError) as exc:
        checks.append(
            DoctorCheck(
                "Configuration",
                "error",
                f"Configuration is invalid: {exc}.",
                "Correct the TOML syntax and reported setting.",
            )
        )
        return DoctorReport(tuple(checks))
    checks.extend(
        [
            DoctorCheck(
                "Configuration",
                "ok",
                f"Configuration loaded from {config_path or 'defaults/current directory'}.",
            ),
            _provider_check(config),
            _database_check(config),
        ]
    )
    return DoctorReport(tuple(checks))
