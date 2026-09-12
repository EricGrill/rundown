# Rundown

> **Turn your GitHub stars into a ranked presentation queue.**  
> Pick what's worth showing, explain why, and export a rundown.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-101%20passed-brightgreen.svg)](#testing)

---

## What It Does

Rundown is a **local-first CLI + TUI** for triaging GitHub repos. Sync your stars, score them automatically, shortlist the gems, add presentation notes, and export a polished rundown.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Rundown                                                    09:30 AM         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Search repos...                              [All     ▾]                    │
├──────────────────────────────────────────┬──────────────────────────────────┤
│ Score │ Repository            │ Status   │ astral-sh/uv                     │
│───────┼───────────────────────┼──────────│                                  │
│  94   │ astral-sh/uv          │ present  │ An extremely fast Python package │
│  92   │ pydantic/pydantic     │ present  │ and project manager, in Rust.    │
│  88   │ textualize/textual    │ shortlist│                                  │
│  85   │ charmbracelet/bubbles │ shortlist│ Score: 94/100                    │
│  78   │ anthropic/cookbook    │ inbox    │ freshness(+30) | stars(+10)      │
│  72   │ ollama/ollama         │ inbox    │                                  │
│  65   │ jqlang/jq             │ hold     │ Status: present                  │
│  45   │ BurntSushi/ripgrep    │ skip     │                                  │
│                                          │ Card                             │
│                                          │ Hook: Fastest Python pkg manager │
│                                          │ For: Python devs tired of pip    │
│                                          │ Problem: pip is painfully slow   │
│                                          │                                  │
│                                          │ Keys: i/s/p/h/x e o +/-          │
├──────────────────────────────────────────┴──────────────────────────────────┤
│ Total: 8 │ inbox: 2 │ shortlist: 2 │ present: 2 │ hold: 1 │ skip: 1         │
├─────────────────────────────────────────────────────────────────────────────┤
│ ? Help  r Refresh  o Open  e Edit  q Quit                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# Install with uv (recommended)
git clone https://github.com/EricGrill/rundown.git
cd rundown
uv pip install -e .

# Or with pip
pip install -e .

# Sync your GitHub stars (requires gh CLI)
rundown sync-stars

# Launch the TUI
rundown

# Export repos marked "present" to Markdown
rundown export -o my-rundown.md
```

**Prerequisites:** Python 3.11+ and [GitHub CLI](https://cli.github.com/) (`gh auth login`)

---

## Commands

| Command | Description |
|---------|-------------|
| `rundown` | Launch interactive TUI |
| `rundown sync-stars` | Import your GitHub stars |
| `rundown add <repo>` | Add a repo by URL or `owner/repo` |
| `rundown list [-s status]` | List repos (filter by status) |
| `rundown show <repo>` | Show repo details |
| `rundown status <repo> <status>` | Set status |
| `rundown boost <repo> <±N>` | Adjust score boost (-10 to +10) |
| `rundown score` | Recalculate all scores |
| `rundown export [-s status] [-o file]` | Export to Markdown |
| `rundown stats` | Show statistics |
| `rundown config` | Show configuration |

Alias: `rd` works the same as `rundown`.

---

## TUI Keybindings

### Navigation
| Key | Action |
|-----|--------|
| `↑`/`↓` `j`/`k` | Move selection |
| `Home` / `End` | Jump to first/last |
| `PgUp` / `PgDn` | Page up/down |
| `/` | Focus search |

### Status (human triage only)
| Key | Status | Meaning |
|-----|--------|---------|
| `i` | **inbox** | Unreviewed |
| `s` | **shortlist** | Worth considering |
| `p` | **present** | Will show this |
| `h` | **hold** | Maybe later |
| `x` | **skip** | Not interested |

### Actions
| Key | Action |
|-----|--------|
| `e` | Edit card (hook, audience, problem, etc.) |
| `o` | Open in browser |
| `r` | Refresh from database |
| `+` / `-` | Boost score ±1 |
| `=` | Reset boost to 0 |
| `1-5` | Filter by status |
| `0` | Show all |
| `?` | Help |
| `q` | Quit |

---

## Scoring

Each repo gets a **0–100 score** with an explainable breakdown:

```
freshness(+28): 5d ago | description(+18): 120 chars | stars(+8): 5,421★
```

### Score Weights

| Factor | Weight | What It Measures |
|--------|-------:|------------------|
| **Freshness** | 30 | Days since last push (exponential decay, 180d half-life) |
| **Description** | 20 | Length and presence of repo description |
| **README** | 15 | README exists and its size |
| **Stars** | 10 | Star count (log scale, so 10→100→1000 all matter) |
| **Topics** | 10 | Number of GitHub topics/tags |
| **License** | 5 | Has an OSI license |
| **Issues ratio** | 5 | Low open issues relative to stars |
| **Manual boost** | 5× | Your adjustment (−10 to +10) |
| **Archived** | −50 | Penalty for archived repos |

Customize weights in `~/.config/rundown/config.toml`:

```toml
[weights]
freshness = 30.0
description_quality = 20.0
readme_signal = 15.0
stars_normalized = 10.0
# ... edit as needed
```

Then run `rundown score` to recalculate.

---

## Card Fields

When preparing repos for presentation, fill in these fields:

| Field | Purpose |
|-------|---------|
| **hook** | One-liner pitch — what makes this interesting? |
| **who_for** | Target audience |
| **problem** | Pain point it solves |
| **why_now** | Why is it relevant now? |
| **demo_path** | URL or path to a demo |
| **flags** | Tags: `trending`, `sponsor`, `beta`, `warning` |
| **notes** | Your personal notes |

---

## Example Export

```bash
rundown export --status present -o show-notes.md
```

**Output** ([full example](docs/demo-export.md)):

```markdown
## [astral-sh/uv](https://github.com/astral-sh/uv)

**The fastest Python package manager — 10-100x faster than pip**

Rust | ⭐ 89,000 | 📄 Apache-2.0

**Who's it for:** Python developers tired of slow installs
**Problem:** pip/poetry/pipenv are painfully slow
**Why now:** Just hit 1.0 stable, production ready

📊 Score: **94**/100 — freshness(+30): 0d ago | description(+20) | stars(+10)
```

---

## Demo Data

Try it without syncing your stars:

```bash
python samples/demo_data.py
rundown tui
```

This loads well-known public repos for demo/screenshot purposes.

---

## Security & Privacy

**Rundown is local-first with no telemetry.**

| Principle | Implementation |
|-----------|----------------|
| **No tokens in code** | Auth is delegated to `gh auth login` only |
| **No code execution** | Never clones, runs, or executes repo code |
| **Local database** | SQLite stored at `~/.local/share/rundown/rundown.db` |
| **No network** | Only calls GitHub API via `gh` CLI |
| **No telemetry** | Zero analytics, tracking, or phone-home |

Your starred repos and personal notes stay on your machine.

---

## Data Locations

| File | Path |
|------|------|
| Database | `~/.local/share/rundown/rundown.db` |
| Config | `~/.config/rundown/config.toml` |

Windows uses `%LOCALAPPDATA%\rundown\` instead.

---

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=rundown
```

### Testing

101 tests covering scoring, database, export, and parsing:

```
============================= 101 passed in 0.17s ==============================
```

---

## License

[MIT](LICENSE) — Use it however you want.

---

## Why "Rundown"?

A **rundown** is a quick briefing on what matters. This tool helps you prep that briefing from your GitHub stars: score, triage, annotate, export.

Built for anyone who stars repos faster than they can remember them.
