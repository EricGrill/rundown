# Rundown

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Turn your GitHub stars into an organized, searchable catalog with AI-powered research.**

Rundown syncs your starred repositories, organizes them into five categories, and uses Claude, Gemini, or Codex CLIs to generate research summaries—all stored locally in SQLite and Markdown.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Rundown                                        Browse · Research · Read     │
├───────────────────────────────────────────┬──────────────────────────────────┤
│  Find a repository…                       │ astral-sh/uv                     │
│  ┌─────────────────────────────────────┐  │                                  │
│  │ All categories               ▾      │  │ An extremely fast Python package │
│  └─────────────────────────────────────┘  │ and project manager, written in  │
│  42 of 128 repositories · newest first    │ Rust.                            │
│  ─────────────────────────────────────────│                                  │
│  astral-sh/uv              Saved          │ Added: 2026-09-01 · Python       │
│  pydantic/pydantic         Saved          │ Category: Developer Tools        │
│  textualize/textual        Not researched │ Local copy: Cloned               │
│  charmbracelet/bubbletea   Saved          │                                  │
│  anthropics/anthropic-sdk  Saved          │ Saved research · 2026-09-10      │
│  langchain-ai/langchain    Not researched │                                  │
├───────────────────────────────────────────┴──────────────────────────────────┤
│ Select a repo · r researches · Enter reads · Ctrl+P opens the menu           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Sync stars** from GitHub using the `gh` CLI
- **Auto-categorize** into AI & Agents, Developer Tools, Infrastructure & Security, Knowledge & Learning, or Apps & Business
- **AI research** via Claude Code, Gemini CLI, or Codex CLI—your choice
- **Browse and filter** in a keyboard-driven TUI
- **Export** repositories marked for presentation to Markdown
- **Local-first**: all data stays on your machine

## Requirements

- Python 3.11 or newer
- Git
- [GitHub CLI](https://cli.github.com/) authenticated with `gh auth login`
- At least one supported AI CLI, authenticated before research:
  - Claude Code: `claude auth login`
  - Gemini CLI: run `gemini` and complete its sign-in flow
  - Codex CLI: `codex login`

## Install

From a checkout of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The CLI is available as `rundown` and its short alias `rd`.

## Quick start

```bash
# Sync your GitHub stars
rd sync-stars

# Browse in the TUI
rd tui

# Research a specific repository (optional)
rd research OWNER/REPO

# Mark repositories for presentation
rd mark astral-sh/uv present
rd mark pydantic/pydantic shortlist

# Export presentation-ready Markdown
rd export
```

## TUI keys

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select a repository |
| `Enter` | Read its details and saved research |
| `r` | Research it; cloning happens automatically when needed |
| `/` | Search names and descriptions |
| `f` | Filter by category |
| `Ctrl+P` | Open the full action menu |
| `Esc` | Return to the list or clear filters |
| `q` | Quit |

The five categories are **AI & Agents**, **Developer Tools**, **Infrastructure & Security**, **Knowledge & Learning**, and **Apps & Business**.

## Research repositories

Preview the repositories that do not have saved research:

```bash
rd research-missing --dry-run
```

Research a bounded batch, newest star first:

```bash
rd research-missing --limit 10
```

The command shows overall progress, the current clone or research stage, elapsed time, and saved/failed counts. `Ctrl+C` stops the batch while keeping completed results.

Configure the provider in `config/rundown.toml`:

```toml
[research]
# auto tries Claude, then Gemini, then Codex
provider = "auto"
profile = "Describe the projects, languages, and constraints relevant to you."
```

Valid providers are `auto`, `claude`, `gemini`, and `codex`. Rundown does not override a model, so each CLI uses its configured default.

## Export for presentation

Mark repositories you want to present:

```bash
rd mark astral-sh/uv present
rd mark pydantic/pydantic shortlist
```

Add optional card fields for richer exports:

```bash
rd card astral-sh/uv \
  --hook "10x faster than pip" \
  --who-for "Python developers" \
  --problem "Slow package installs" \
  --why-now "Growing dependency trees"
```

Generate presentation-ready Markdown:

```bash
rd export                          # Exports present + shortlist repos
rd export --decision present       # Only present
rd export --output slides.md       # Custom output path
```

## Privacy and security

Rundown is designed for local-first privacy:

- **No API keys stored**: Rundown never reads or stores AI API keys. Authentication is delegated entirely to `gh auth login` and your AI CLI (`claude`, `gemini`, or `codex`).
- **Local configuration**: Copy `config/rundown.toml` to `config/rundown.local.toml` for personal settings—it's gitignored.
- **All data stays local**: The SQLite catalog, cloned repos, wiki pages, and logs are stored in local directories that are gitignored.

| Path | Contents |
| --- | --- |
| `data/` | SQLite catalog and research status |
| `repos/` | Local clones used for research |
| `wiki/` | Markdown repository pages and research |
| `logs/` | Research and execution logs |
| `exports/` | Generated exports |

Research sends repository metadata and content excerpts to your configured AI CLI. Review the provider's data policy before researching private repositories.

## Other CLI commands

Run `rd --help` for the full command list. Common commands include:

```bash
rd sync-stars          # Sync stars from GitHub
rd repos               # List all repositories
rd research OWNER/REPO # Research a single repository
rd classify            # Reclassify all repositories
rd update-repos        # Update local clones
rd mark REPO DECISION  # archived, rejected, fork, integrate, present, shortlist
rd card REPO --hook .. # Set presentation card fields
rd export              # Export marked repositories
```

`rd run OWNER/REPOSITORY` only detects and reports a possible startup command. It does not execute repository code unless you add `--execute`. Non-Docker commands also require `--allow-non-docker`.

## Development

Run the test suite from the activated virtual environment:

```bash
python -m pytest -q
```

## License

MIT License. See [LICENSE](LICENSE) for details.
