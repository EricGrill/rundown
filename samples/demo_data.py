#!/usr/bin/env python3
"""Load demo data into Rundown for testing and screenshots.

This creates a sample database with well-known public repos
for demonstration purposes. No personal data or private repos.

Usage:
    python samples/demo_data.py
    rundown list
    rundown tui
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rundown.config import Config
from rundown.database import Database
from rundown.models import Repo, Status
from rundown.scoring import calculate_score


DEMO_REPOS = [
    {
        "full_name": "astral-sh/uv",
        "description": "An extremely fast Python package and project manager, written in Rust.",
        "stars": 89000,
        "forks": 3500,
        "open_issues": 2300,
        "language": "Rust",
        "license": "Apache-2.0",
        "topics": ["python", "packaging", "rust", "uv"],
        "pushed_days_ago": 0,
        "status": Status.PRESENT,
        "hook": "The fastest Python package manager — 10-100x faster than pip",
        "who_for": "Python developers tired of slow installs",
        "problem": "pip/poetry/pipenv are painfully slow",
        "why_now": "Just hit 1.0 stable, production ready",
    },
    {
        "full_name": "pydantic/pydantic",
        "description": "Data validation using Python type hints.",
        "stars": 82000,
        "forks": 6200,
        "open_issues": 450,
        "language": "Python",
        "license": "MIT",
        "topics": ["python", "validation", "pydantic", "typing"],
        "pushed_days_ago": 1,
        "status": Status.PRESENT,
        "hook": "Data validation that just works with type hints",
        "who_for": "Anyone building APIs or data pipelines",
        "problem": "Manual validation is tedious and error-prone",
        "why_now": "V2 is a complete rewrite, much faster",
    },
    {
        "full_name": "textualize/textual",
        "description": "The lean application framework for Python. Build sophisticated user interfaces with a simple Python API.",
        "stars": 37000,
        "forks": 1100,
        "open_issues": 180,
        "language": "Python",
        "license": "MIT",
        "topics": ["python", "tui", "terminal", "textual", "rich", "cli"],
        "pushed_days_ago": 3,
        "status": Status.SHORTLIST,
        "hook": "Build beautiful terminal UIs in Python",
        "who_for": "CLI developers who want rich interfaces",
        "problem": "Terminal UIs are hard to build well",
        "why_now": "Mature enough for production apps",
    },
    {
        "full_name": "charmbracelet/bubbletea",
        "description": "A powerful little TUI framework.",
        "stars": 45000,
        "forks": 1400,
        "open_issues": 95,
        "language": "Go",
        "license": "MIT",
        "topics": ["go", "golang", "tui", "terminal", "elm-architecture"],
        "pushed_days_ago": 2,
        "status": Status.SHORTLIST,
        "hook": "The Elm Architecture for terminal apps",
        "who_for": "Go developers building CLI tools",
        "problem": "TUIs in Go were clunky before this",
    },
    {
        "full_name": "anthropics/anthropic-cookbook",
        "description": "A collection of notebooks/recipes showcasing some fun and effective ways of using Claude.",
        "stars": 12000,
        "forks": 1500,
        "open_issues": 45,
        "language": "Jupyter Notebook",
        "license": "MIT",
        "topics": ["claude", "llm", "ai", "cookbook", "examples"],
        "pushed_days_ago": 5,
        "status": Status.INBOX,
    },
    {
        "full_name": "ollama/ollama",
        "description": "Get up and running with Llama 3.3, Mistral, Gemma 2, and other large language models.",
        "stars": 120000,
        "forks": 9500,
        "open_issues": 1800,
        "language": "Go",
        "license": "MIT",
        "topics": ["llm", "ai", "ollama", "local", "llama"],
        "pushed_days_ago": 0,
        "status": Status.INBOX,
    },
    {
        "full_name": "jqlang/jq",
        "description": "Command-line JSON processor.",
        "stars": 31000,
        "forks": 1700,
        "open_issues": 420,
        "language": "C",
        "license": "MIT",
        "topics": ["json", "cli", "jq", "filter"],
        "pushed_days_ago": 14,
        "status": Status.HOLD,
        "notes": "Classic tool, maybe mention in passing",
    },
    {
        "full_name": "BurntSushi/ripgrep",
        "description": "ripgrep recursively searches directories for a regex pattern while respecting your gitignore.",
        "stars": 51000,
        "forks": 2100,
        "open_issues": 150,
        "language": "Rust",
        "license": "MIT",
        "topics": ["rust", "cli", "search", "grep", "regex"],
        "pushed_days_ago": 30,
        "status": Status.SKIP,
        "notes": "Already covered this one before",
    },
]


def load_demo_data():
    """Load demo repos into the database."""
    config = Config.load()
    db = Database(config.db_path)
    
    now = datetime.now(timezone.utc)
    
    for data in DEMO_REPOS:
        pushed_at = now - timedelta(days=data.get("pushed_days_ago", 0))
        created_at = now - timedelta(days=365)
        
        repo = Repo(
            full_name=data["full_name"],
            owner=data["full_name"].split("/")[0],
            name=data["full_name"].split("/")[1],
            url=f"https://github.com/{data['full_name']}",
            description=data.get("description"),
            stars=data.get("stars", 0),
            forks=data.get("forks", 0),
            open_issues=data.get("open_issues", 0),
            pushed_at=pushed_at,
            created_at=created_at,
            language=data.get("language"),
            license=data.get("license"),
            topics=data.get("topics", []),
            archived=False,
            has_readme=True,
            readme_length=5000,
            status=data.get("status", Status.INBOX),
            hook=data.get("hook", ""),
            who_for=data.get("who_for", ""),
            problem=data.get("problem", ""),
            why_now=data.get("why_now", ""),
            notes=data.get("notes", ""),
            added_at=now,
            updated_at=now,
        )
        
        score, reason = calculate_score(repo, config.weights)
        repo.present_score = score
        repo.score_reason = reason
        
        db.upsert_repo(repo)
        print(f"  ✓ {repo.full_name} ({repo.status.value}, score={score:.0f})")
    
    print(f"\nLoaded {len(DEMO_REPOS)} demo repos into {config.db_path}")
    print("Run 'rundown list' or 'rundown tui' to see them!")


if __name__ == "__main__":
    print("Loading demo data...\n")
    load_demo_data()
