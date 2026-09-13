# Rundown

[![CI](https://github.com/EricGrill/rundown/actions/workflows/ci.yml/badge.svg)](https://github.com/EricGrill/rundown/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Turn your GitHub stars into an organized, searchable catalog with AI-powered research.**

Rundown syncs your starred repositories, organizes them into five categories, and uses Claude, Gemini, or Codex CLIs to generate research summaries—all stored locally in SQLite and Markdown.

## Features

- **Sync stars** from GitHub using the `gh` CLI
- **Auto-categorize** into AI & Agents, Developer Tools, Infrastructure & Security, Knowledge & Learning, or Apps & Business
- **AI research** via Claude Code, Gemini CLI, Codex CLI, isolated OpenCode, or a trusted custom command
- **Browse → Read → Prepare → Export** in one keyboard-driven TUI
- **Prepare show cards** with generated research and clearly separated human edits
- **Export** the selected repository or repositories marked for presentation to Markdown
- **Local-first**: all data stays on your machine

## TUI preview

Captured from the running TUI with a sample catalog of public repositories.

Browse repositories and read their details side by side:

![Rundown TUI showing a repository catalog with Textual selected and its details in the reader](docs/images/tui-catalog.png)

Press `/` to filter repositories by name or description:

![Rundown TUI filtering the catalog to uv and showing its repository details](docs/images/tui-search.png)

Press `Ctrl+P` to open the searchable action menu:

![Rundown command menu with actions for research, reading, filtering, classification, and syncing](docs/images/tui-menu.png)

Prepare overrides beside the generated source, then export a selected card or marked repositories:

![Rundown unified card editor showing an editable hook beside read-only generated research](docs/images/tui-prepare.png)

![Rundown export dialog with scope, file path, and explicit overwrite choice](docs/images/tui-export.png)

## Requirements

- Python 3.11 or newer
- Git
- [GitHub CLI](https://cli.github.com/) authenticated with `gh auth login`
- At least one supported AI CLI, authenticated before research:
  - Claude Code: `claude auth login`
  - Gemini CLI: run `gemini` and complete its sign-in flow
  - Codex CLI: `codex login`
  - OpenCode: explicit `provider/model` and its API key in the environment; personal OAuth/config files are not loaded. See [research harnesses](docs/research-harnesses.md).

## Install

From a checkout of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The CLI is available as `rundown` and its short alias `rd`. Run either command with no arguments in an interactive terminal to open the app.

## Try it offline

```bash
rd demo
```

Explore bundled sample research in a temporary, isolated catalog. No GitHub login, AI provider, network access, or personal catalog is needed. Demo changes disappear on exit. See the [install and upgrade guide](docs/install.md) for isolated `uv` and `pipx` installations and versioned releases.

## Quick start

```bash
# Open Rundown
rd

# Or open the offline sample catalog
rd demo

# Research a specific repository (optional)
rd research OWNER/REPO

# Mark repositories for presentation
rd mark astral-sh/uv present
rd mark pydantic/pydantic shortlist

# Export presentation-ready Markdown
rd export
```

On an empty first run, choose **Try demo** for the isolated sample catalog or **Connect GitHub** to use your stars. Rundown uses an existing authenticated `gh` session when available and otherwise shows the exact setup command. Existing catalogs open directly. Scripts and automation can keep using explicit commands such as `rd sync-stars`, `rd research`, and `rd export`; a no-argument noninteractive invocation prints guidance instead of opening a TUI.

![Rundown first-run screen offering an offline demo or GitHub connection](docs/images/tui-welcome.png)

The main screen follows four steps: **Browse** a repository, **Read** its saved research, **Prepare** the human parts of its card, then **Export** it. The contextual action row shows those steps for the selected repository. Maintenance and less common actions remain in `Ctrl+P`.

## TUI keys

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select a repository |
| `Enter` | Read its details and saved research |
| `r` | Research it; cloning happens automatically when needed |
| `Shift+R` | Refresh research, bypassing the saved result |
| `v` | Switch between Host brief and Research card |
| `p` | Toggle whether this repository is marked for presentation |
| `e` | Prepare the card: edit presentation fields and notes together |
| `x` | Export the selected repository or all marked repositories |
| `n` | Open the same card editor directly at Host notes |
| `t` | Edit card templates and preview saved research |
| `g` | Research filters, sorting, and named catalog views |
| `j` | Research jobs, cancellation, and retry |
| `h` | Research provenance and changes |
| `/` | Search names and descriptions |
| `f` | Filter by category |
| `Ctrl+P` | Open the full action menu |
| `Esc` | Return to the list or clear filters |
| `q` | Quit |

The five categories are **AI & Agents**, **Developer Tools**, **Infrastructure & Security**, **Knowledge & Learning**, and **Apps & Business**.

## Research cards

Choose **Host brief** for a short show segment or **Research card** for deeper evaluation. Press `v` or use the view selector. The chosen view is remembered for each repository, and switching uses saved research without calling an AI provider.

Sections have distinct headings, Markdown bullets, and short previews. Expand **Read full section** for a long finding, or **Full research** to see the complete original report. Use `Tab` to reach disclosure controls and `Enter` to toggle them. Older Markdown reports remain readable; unavailable fields show **Unknown**. `Shift+R` generates a fresh report when you want new show details.

The screenshots below show the running TUI with illustrative research from the offline demo:

![Rundown Host brief with a hook, talking points, and a segment time target](docs/images/tui-host-brief.png)

![Rundown Research card with structured findings and expandable detail](docs/images/tui-research-card.png)

Press `e` to prepare the selected card in one place. Choose **Hook**, **Who it is for**, **Problem**, **Why now**, **Demo path**, **Host notes**, or **Repository notes**. The editor places your writable value beside its read-only generated source. **Reset to generated** clears only the selected override; it never changes research or unrelated notes. `Ctrl+S` saves every human field together, while `Esc` discards the draft. Press `n` to open this same editor directly at **Host notes**. Human edits survive syncs, view changes, and research refreshes.

Press `t` to choose **Quick overview**, **Deep research**, or **Show segment**, then set the target duration. Open **Customize** for audience, tone, default card, section visibility/order, preview length, and global or repository scope. The live preview always uses saved research and never calls a provider. `Ctrl+S` saves; `Esc` cancels. Repository templates override saved global settings, which override TOML defaults. **Use global card template** in the action menu removes a repository override.

![Rundown template chooser with preset and duration controls, live preview, and collapsed Customize options](docs/images/tui-template.png)

You can also configure defaults in `config/rundown.local.toml`:

```toml
[cards]
default_view = "host" # host or research
audience = "Developers exploring useful repositories"
tone = "Plain, concise, conversational"
duration_seconds = 90 # target, not measured runtime

[cards.host]
sections = ["hook", "what_it_is", "talking_points", "demo", "risks", "recommendation", "sources"]
word_limit = 60 # per-section preview; full text remains available

[cards.research]
sections = ["what_it_is", "use_cases", "how_it_works", "strengths", "risks", "setup", "questions", "recommendation", "sources"]
word_limit = 120
```

Start with `rd tui --config config/rundown.local.toml`. Section lists set both visibility and order. Changing view, section order, or preview length only changes presentation. Audience, tone, and duration affect future generated content; use `Shift+R` to refresh an existing report with those settings. Per-repository view choices override `default_view`.

Available sections: `what_it_is`, `analogy`, `use_cases`, `personal_fit`, `interest`, `how_it_works`, `practical_uses`, `strengths`, `risks`, `setup`, `maturity`, `questions`, `recommendation`, `hook`, `why_now`, `talking_points`, `demo`, and `sources`. Lists must be nonempty, contain unique known IDs, and use preview limits of 10–1,000 words. Segment targets range from 15 to 3,600 seconds.

New research is validated as a versioned record of named fields and also exported as Markdown. Existing research history is retained. Card preferences and host notes live in the same local SQLite catalog; host notes are not sent to the research provider.

The TUI, `rd research`, and `rd research-missing` use the same research workflow. It checks the saved cache first, clones only when research is actually needed, resolves the same effective template, and uses the same force-refresh and cancellation rules. This keeps interactive and batch results consistent; completed results remain saved if a later batch item is cancelled.

## Catalog views and research jobs

Press `g` to combine search/category with researched, unresearched, stale, shortlisted, or presentation-ready filters. Sort by starred date, relevance, stars, or research date. Stale means the saved research exceeds the configured age, has no usable timestamp, or predates repository changes; repositories without research use the separate unresearched filter. Name a view and press `Ctrl+S` to save it, or `Ctrl+Enter` to apply without saving. `Esc` cancels the editor. In the catalog, `Esc` clears filters; returning from the reader preserves them.

Press `j` to inspect queued, cloning, researching, completed, failed, cancelling, and cancelled jobs with elapsed time. Select a job and press `c` to cancel or `r` to retry a failed/cancelled job. Active cancellation terminates the current subprocess before the next job starts; prior research and notes remain. Closing Rundown cancels its jobs. Job history lasts for the current session.

## Research provenance and changes

Press `h` to inspect the latest two successful reports, their provenance, and section-level before/after differences:

```bash
rd research-history OWNER/REPO
rd research-history OWNER/REPO --json
```

New reports record the actual provider, source commit and dirty state captured before generation, context file hashes, timestamp, prompt version, and schema version. Older reports show unavailable provenance as unknown. This describes the context provided to the model; generated citations are not independently verified evidence.

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

Harness selectors are `auto`, `claude`, `gemini`, `codex`, `opencode`, and explicitly configured custom names. The default automatic order remains Claude, Gemini, Codex. Use `research.fallback` to change it and optional `research.model` for supported model overrides. Existing harnesses retain their configured defaults when model is omitted; isolated OpenCode requires an explicit model. See [research harness configuration, safety, and provenance](docs/research-harnesses.md) and [compatibility testing](docs/harness-testing.md).

## Export for presentation

Press `x` in the TUI to export either the selected repository or all repositories marked `present` or `shortlist`. Choose the output path explicitly. Rundown refuses to replace an existing file until **Replace existing file** is enabled, then reports the exported count and path.

Mark repositories you want to present:

```bash
rd mark astral-sh/uv present
rd mark pydantic/pydantic shortlist
```

Add optional human-authored presentation fields. Exports use your effective card template and saved view, apply these overrides, and include host notes:

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
rd export --view host              # Override saved views with Host brief
rd export --view research          # Export Research cards
```

Manual fields omitted by the template remain under **Presentation Details**. Long sections include expandable full text, and legacy Markdown reports remain available in full.

## Check your setup

```bash
rd doctor
rd doctor --json
```

Diagnostics check Python, Git, GitHub CLI/authentication, provider commands, configuration, and existing SQLite integrity without generating research or creating a catalog. Provider authentication is not probed; missing optional tools appear as warnings so offline browsing remains usable.

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

Run checks from the activated development environment:

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m pyright --pythonpath .venv/bin/python
python scripts/capture_tui.py
python -m build
python scripts/verify_release.py dist
```

CI checks Linux and macOS on Python 3.11 and 3.14, compares twelve deterministic TUI snapshots, and installs the built wheel in a clean environment. After reviewing an intentional visual change, use `python scripts/capture_tui.py --update-baselines --png` to refresh SVG baselines and README images from the offline fixture.

See the [delivery roadmap](docs/implementation-roadmap.md) and [release instructions](docs/install.md).

## License

MIT License. See [LICENSE](LICENSE) for details.
