"""A small, non-mutating first-run choice before opening the catalog."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from .config import AppConfig


def provider_summary(config: AppConfig) -> str:
    """Say which research provider will receive repository context, without calling it."""
    from .doctor import ready_providers

    try:
        available, _blocked = ready_providers(config)
    except ValueError:
        return "Research provider settings are invalid. Run `rd doctor` for details."
    first, *rest = available or ("",)
    if not first:
        return ("No research provider is installed yet. Browsing and demo work without one. "
                "Install Claude Code, Gemini CLI or Codex CLI to generate research.")
    others = f" Also installed: {', '.join(rest)}." if rest else ""
    return (f"Research will use {first}, which receives repository context when you research.{others} "
            "Change it with [research].provider in config/rundown.toml.")


class WelcomeApp(App[str | None]):
    TITLE = "Rundown"
    BINDINGS = [Binding("escape", "quit", "Quit")]
    CSS = """
    Screen { align: center middle; }
    #welcome { width: 90%; max-width: 76; height: auto; max-height: 95%; padding: 1 2; border: solid $primary; }
    #welcome Static { height: auto; margin-bottom: 1; }
    #welcome Button { width: 100%; margin-bottom: 1; }
    """

    def __init__(self, provider_note: str | None = None) -> None:
        super().__init__()
        self.provider_note = provider_note

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="welcome"):
            yield Static("Welcome to Rundown", markup=False)
            yield Static("Browse a repository, read its research, prepare your card, and export it.")
            yield Button("Try demo · offline sample catalog", id="demo", variant="primary")
            yield Button("Connect GitHub · use your starred repositories", id="connect")
            yield Static("Demo changes are temporary. GitHub connection uses your existing gh login. Esc closes.")
            if self.provider_note:
                yield Static(self.provider_note, id="provider", markup=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"demo", "connect"}:
            self.exit(event.button.id)


def interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def has_catalog(database: Path) -> bool:
    """Check for existing data without creating a database or applying migrations."""
    if not database.exists():
        return False
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='repos'").fetchone() is None:
            return False
        return conn.execute("SELECT 1 FROM repos LIMIT 1").fetchone() is not None


def github_setup_problem() -> str | None:
    executable = shutil.which("gh")
    if executable is None:
        return "Install GitHub CLI from https://cli.github.com/, run `gh auth login`, then run `rd` again."
    try:
        result = subprocess.run([executable, "auth", "status"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "GitHub login could not be checked. Run `gh auth status`, then run `rd` again."
    if result.returncode:
        return "Connect GitHub with `gh auth login`, then run `rd` again. You can also use `rd demo` offline."
    return None


def launch(config: AppConfig) -> str | None:
    # Imports stay local so startup can be checked without starting the main app.
    from .demo import demo_environment
    from .tui import RundownApp

    if has_catalog(config.database_path):
        config.ensure_directories()
        RundownApp(config).run()
        return None
    choice = WelcomeApp(provider_summary(config)).run()
    if choice == "demo":
        with demo_environment() as environment:
            RundownApp(environment.config, fetch_starred=environment.fetch_starred, demo_mode=True).run()
    elif choice == "connect":
        problem = github_setup_problem()
        if problem:
            return problem
        config.ensure_directories()
        RundownApp(config).run()
    return None
