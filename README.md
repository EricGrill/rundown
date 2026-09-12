# Rundown

Local-first CLI/TUI to rank and present your best GitHub repos with clear metrics.

**Rundown** turns starred (and added) GitHub repos into a ranked presentation queue: pick what's worth showing, why, and export a rundown.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- **Sync stars** — Import your GitHub starred repos via `gh` CLI
- **Add repos** — Manually add any repo by URL or `owner/repo`
- **Score repos** — Automatic 0-100 score with explainable reasons
- **Triage workflow** — Categorize repos: inbox → shortlist → present → hold → skip
- **Rich TUI** — Interactive terminal interface for browsing and editing
- **Card system** — Add presentation notes: hook, audience, problem, timing
- **Export** — Generate presentation-ready Markdown

## Installation

### With uv (recommended)

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/rundown.git
cd rundown

# Install with uv
uv pip install -e .

# Or run directly
uv run rundown --help
```

### With pip

```bash
pip install -e .
```

### Prerequisites

- Python 3.11+
- [GitHub CLI](https://cli.github.com/) (`gh`) — for syncing stars and fetching metadata

```bash
# Install gh CLI (macOS)
brew install gh

# Authenticate
gh auth login
```

## Quick Start

```bash
# 1. Sync your starred repos
rundown sync-stars

# 2. Launch the TUI to browse and triage
rundown

# 3. Set repos to "present" status, fill in cards
# (use keyboard shortcuts in TUI)

# 4. Export your rundown
rundown export -o rundown.md
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `rundown` / `rundown tui` | Launch interactive TUI |
| `rundown sync-stars` | Sync starred repos from GitHub |
| `rundown add <repo>` | Add a repo (owner/repo or URL) |
| `rundown list [-s status]` | List repos in database |
| `rundown show <repo>` | Show repo details |
| `rundown status <repo> <status>` | Set repo status |
| `rundown boost <repo> <-10..+10>` | Adjust manual score boost |
| `rundown score` | Recalculate all scores |
| `rundown export [-s status] [-o file]` | Export to Markdown |
| `rundown stats` | Show database statistics |
| `rundown config` | Show current configuration |

### Examples

```bash
# Add a specific repo
rundown add https://github.com/astral-sh/uv
rundown add astral-sh/ruff

# List shortlisted repos
rundown list --status shortlist

# Export only repos marked "present"
rundown export --status present -o show-notes.md

# Export all repos
rundown export --all -o full-catalog.md

# Boost a repo's score
rundown boost astral-sh/uv 5
```

## TUI Keyboard Shortcuts

### Navigation

| Key | Action |
|-----|--------|
| `↑`/`↓` or `j`/`k` | Move selection |
| `Home`/`End` | Jump to first/last |
| `PgUp`/`PgDn` | Page up/down |

### Status Changes

| Key | Status |
|-----|--------|
| `i` | inbox |
| `s` | shortlist |
| `p` | present |
| `h` | hold |
| `x` | skip |

### Actions

| Key | Action |
|-----|--------|
| `Enter` | View details |
| `e` | Edit card |
| `o` | Open in browser |
| `r` | Refresh data |
| `+`/`-` | Boost score ±1 |
| `=` | Reset boost to 0 |

### Filtering

| Key | Action |
|-----|--------|
| `/` | Focus search |
| `1` | Filter: inbox |
| `2` | Filter: shortlist |
| `3` | Filter: present |
| `4` | Filter: hold |
| `5` | Filter: skip |
| `0` | Show all |

### Other

| Key | Action |
|-----|--------|
| `?` | Toggle help |
| `q` | Quit |

## Workflow

```
┌─────────────────────────────────────────────────────────┐
│                      RUNDOWN WORKFLOW                    │
└─────────────────────────────────────────────────────────┘

   ┌──────────┐     ┌───────────┐     ┌─────────┐
   │  GitHub  │────▶│   inbox   │────▶│shortlist│
   │  Stars   │     │  (triage) │     │ (maybe) │
   └──────────┘     └───────────┘     └─────────┘
         │                │                 │
         │                │                 │
         ▼                ▼                 ▼
   ┌──────────┐     ┌───────────┐     ┌─────────┐
   │   add    │     │   skip    │     │ present │──▶ EXPORT
   │ (manual) │     │ (archive) │     │ (show!) │
   └──────────┘     └───────────┘     └─────────┘
                          │
                          ▼
                    ┌───────────┐
                    │   hold    │
                    │  (later)  │
                    └───────────┘
```

1. **Sync** — `rundown sync-stars` imports your GitHub stars
2. **Browse** — Launch TUI, sort by score, review candidates
3. **Triage** — Mark repos: shortlist promising ones, skip the rest
4. **Curate** — For shortlisted repos, decide: present or hold
5. **Annotate** — Fill in card fields (hook, audience, problem, why now)
6. **Export** — Generate Markdown for your presentation

## Scoring

Each repo gets a **present_score** from 0-100, calculated from multiple factors:

| Factor | Default Weight | Description |
|--------|---------------|-------------|
| `freshness` | 30 | Recency of last push (exponential decay) |
| `description_quality` | 20 | Length and presence of description |
| `readme_signal` | 15 | README exists and its size |
| `stars_normalized` | 10 | Star count (log scale) |
| `topics_count` | 10 | Number of repository topics |
| `has_license` | 5 | Whether repo has a license |
| `low_issues_ratio` | 5 | Low open issues relative to stars |
| `manual_boost` | 5× | Your manual adjustment (-10 to +10) |
| `archived_penalty` | -50 | Penalty for archived repos |

The score includes an explainable `score_reason` showing top factors:

```
freshness(+28): 5d ago | description(+18): 120 chars | stars(+8): 5,421★
```

### Customizing Weights

Edit `~/.config/rundown/config.toml`:

```toml
[weights]
freshness = 30.0
description_quality = 20.0
readme_signal = 15.0
stars_normalized = 10.0
topics_count = 10.0
has_license = 5.0
low_issues_ratio = 5.0
manual_boost_multiplier = 5.0
archived_penalty = -50.0
freshness_half_life_days = 180
```

Then recalculate: `rundown score`

## Card Fields

When preparing repos for presentation, fill in these card fields:

| Field | Purpose |
|-------|---------|
| **hook** | One-liner pitch — what makes this interesting? |
| **who_for** | Target audience |
| **problem** | Pain point it addresses |
| **why_now** | Why is it relevant/trending now? |
| **demo_path** | URL or local path to demo |
| **flags** | Tags like `trending`, `sponsor`, `beta`, `warning` |
| **notes** | Your personal notes for the presentation |

## Data Storage

- **Database**: `~/.local/share/rundown/rundown.db` (SQLite)
- **Config**: `~/.config/rundown/config.toml` (TOML)

On Windows, these use `%LOCALAPPDATA%\rundown\` instead.

## Safety

**Rundown does not execute any code from the repositories it indexes.**

- No cloning of repos
- No running of scripts or build systems
- No execution of untrusted code
- Read-only metadata fetching via GitHub API

This is a presentation/triage tool, not a security research or code execution tool.

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=rundown
```

## License

MIT
