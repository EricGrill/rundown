from __future__ import annotations

import re
import sqlite3


CATEGORIES = (
    "AI & Agents",
    "Developer Tools",
    "Infrastructure & Security",
    "Knowledge & Learning",
    "Apps & Business",
)


# Higher weights represent a repository's purpose; lower weights represent supporting
# technology. This keeps, for example, an Obsidian AI plugin with knowledge tools while
# still recognizing a general-purpose LLM library as AI.
_SIGNALS: dict[str, dict[str, int]] = {
    "AI & Agents": {
        "artificial intelligence": 8,
        "large language model": 8,
        "foundation model": 8,
        "language model": 7,
        "machine learning": 7,
        "generative ai": 8,
        "ai agent": 9,
        "ai cli": 8,
        "agent": 6,
        "agents": 6,
        "agentic": 8,
        "llm": 7,
        "llms": 7,
        "claude": 7,
        "codex": 7,
        "openclaw": 7,
        "chatgpt": 7,
        "gemini": 7,
        "openai": 7,
        "ollama": 7,
        "langchain": 7,
        "mcp": 7,
        "rag": 6,
        "chatbot": 6,
        "inference": 6,
        "diffusion": 6,
        "tts": 6,
        "embedding": 5,
        "transformer": 5,
        "ai": 4,
    },
    "Developer Tools": {
        "developer tool": 9,
        "command line": 8,
        "source control": 8,
        "code editor": 8,
        "programming language": 7,
        "visual studio code": 9,
        "package manager": 8,
        "static analysis": 7,
        "harness engineering": 8,
        "git": 6,
        "github": 5,
        "vscode": 8,
        "cli": 6,
        "sdk": 6,
        "api": 4,
        "api client": 6,
        "compiler": 6,
        "debugger": 6,
        "linter": 6,
        "e2e": 6,
        "testing": 5,
        "test framework": 7,
        "framework": 4,
        "library": 3,
        "libraries": 3,
        "terminal": 5,
        "ide": 6,
    },
    "Infrastructure & Security": {
        "infrastructure as code": 10,
        "continuous integration": 8,
        "continuous deployment": 8,
        "reverse proxy": 8,
        "self hosted": 7,
        "self hostable": 7,
        "self hosting": 7,
        "zero trust": 8,
        "homelab": 9,
        "kubernetes": 8,
        "terraform": 8,
        "ansible": 8,
        "docker": 7,
        "deployment": 7,
        "devops": 7,
        "security": 7,
        "cybersecurity": 8,
        "vulnerability": 8,
        "vulnerabilities": 8,
        "authentication": 6,
        "authorization": 6,
        "firewall": 7,
        "networking": 6,
        "network": 6,
        "monitoring": 6,
        "observability": 6,
        "paas": 7,
        "vercel": 7,
        "netlify": 7,
        "heroku": 7,
        "bitwarden": 8,
        "vaultwarden": 8,
        "database": 4,
        "server": 4,
    },
    "Knowledge & Learning": {
        "knowledge base": 10,
        "personal knowledge": 10,
        "note taking": 9,
        "markdown editor": 9,
        "rss reader": 9,
        "spaced repetition": 9,
        "learning resource": 9,
        "awesome list": 9,
        "obsidian": 10,
        "paperless": 10,
        "ebook": 8,
        "calibre": 9,
        "cookbook": 7,
        "bookmark": 8,
        "wiki": 8,
        "documentation": 6,
        "learning": 7,
        "tutorial": 7,
        "course": 7,
        "education": 7,
        "notes": 6,
        "research paper": 7,
        "awesome": 7,
        "reading": 5,
    },
    "Apps & Business": {
        "customer relationship management": 9,
        "project management": 8,
        "e commerce": 8,
        "productivity": 6,
        "finance": 6,
        "accounting": 7,
        "analytics": 5,
        "dashboard": 5,
        "commerce": 6,
        "crm": 7,
        "saas": 6,
        "business": 5,
        "mobile app": 5,
        "web app": 4,
    },
}


def _normalize(value: str | None) -> str:
    """Return lowercase words separated by single spaces for boundary-safe matching."""
    return " ".join(re.findall(r"[a-z0-9]+", value.lower())) if value else ""


def classify_repo(
    full_name: str,
    description: str | None = None,
    language: str | None = None,
    tags: str | None = None,
) -> str:
    """Classify repository metadata into one stable, broad category."""
    text = " ".join(
        part for part in map(_normalize, (full_name, description, language, tags)) if part
    )
    padded = f" {text} "
    scores = {
        category: sum(
            weight for phrase, weight in signals.items() if f" {phrase} " in padded
        )
        for category, signals in _SIGNALS.items()
    }
    best = max(CATEGORIES, key=lambda category: scores[category])
    return best if scores[best] else "Apps & Business"


def classify_repos(conn: sqlite3.Connection, *, force: bool = False) -> dict[str, int]:
    """Persist categories for starred repositories and return their current totals."""
    placeholders = ", ".join("?" for _ in CATEGORIES)
    where = "starred = 1"
    params: tuple[str, ...] = ()
    if not force:
        where += f" AND (category IS NULL OR category NOT IN ({placeholders}))"
        params = CATEGORIES

    rows = conn.execute(
        f"SELECT full_name, description, language, tags FROM repos WHERE {where}", params
    ).fetchall()
    for row in rows:
        category = classify_repo(
            row["full_name"], row["description"], row["language"], row["tags"]
        )
        conn.execute(
            "UPDATE repos SET category = ? WHERE full_name = ?",
            (category, row["full_name"]),
        )

    counts: dict[str, int] = dict.fromkeys(CATEGORIES, 0)
    for row in conn.execute(
        "SELECT category, COUNT(*) AS count FROM repos WHERE starred = 1 GROUP BY category"
    ).fetchall():
        if row["category"] in counts:
            counts[row["category"]] = int(row["count"])
    return counts
