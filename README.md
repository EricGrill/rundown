# Rundown

Rundown turns GitHub stars into a searchable local catalog. It syncs repository metadata with the GitHub CLI, groups repositories into five broad categories, and saves AI-assisted research as Markdown alongside a SQLite index.

The TUI stays focused on browsing and research. Scoring, cloning, maintenance, decisions, and execution checks remain available as CLI commands.

## Requirements

- Python 3.11 or newer
- Git
- [GitHub CLI](https://cli.github.com/) authenticated with `gh auth login`
- At least one supported AI CLI, authenticated before research:
  - Claude Code: `claude auth login`
  - Gemini CLI: run `gemini` and complete its sign-in flow
  - Codex CLI: `codex login`

Rundown does not read an AI API key itself. It calls the selected CLI, which uses its own saved authentication and configured default model. See the [Codex non-interactive mode documentation](https://developers.openai.com/codex/noninteractive/) for details about the Codex execution mode used here.

## Install

From a checkout of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The CLI is available as `rundown` and its short alias `rd`.

Start the TUI:

```bash
rd tui
```

The TUI immediately loads any saved catalog, then syncs GitHub stars in the background. New repositories are categorized locally without an AI call.

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

The command shows overall progress, the current clone or research stage, elapsed time, and saved/failed counts. `Ctrl+C` stops the batch while keeping completed results. The batch skips repositories with any successful saved research. Researching a single repository from the TUI or `rd research` rechecks the source fingerprint and refreshes results when repository content or research-profile settings change.

Configure the provider in `config/rundown.toml`:

```toml
[research]
# auto tries Claude, then Gemini, then Codex
provider = "auto"
profile = "Describe the projects, languages, and constraints relevant to you."
```

Valid providers are `auto`, `claude`, `gemini`, and `codex`. Rundown does not override a model, so each CLI uses its configured default.

For local settings, copy the example and pass the private file explicitly:

```bash
cp config/rundown.toml config/rundown.local.toml
rd tui --config config/rundown.local.toml
```

`config/*.local.toml` is ignored by Git.

## Data and privacy

The default paths are relative to the configuration file's project root:

| Path | Contents |
| --- | --- |
| `data/` | SQLite catalog and research status |
| `repos/` | Local clones used for research |
| `wiki/` | Markdown repository pages and research |
| `logs/` | Research and execution logs |
| `exports/` | Generated exports |

These directories are ignored by Git. Excluding private repositories from future syncs does not remove private repositories previously imported into the local catalog. Star sync stores GitHub metadata locally. Public starred repositories are synced by default; set `include_private = true` under `[github]` only if you also want private repositories visible to your authenticated `gh` account.

Research sends the configured profile and preferences, the selected repository's GitHub metadata, a file tree up to three levels deep, its README, and supported root manifests to the selected AI CLI. Supported manifests include `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `requirements.txt`, Docker files, and `Makefile`. README and manifest files that are symlinks or resolve outside the clone are ignored.

The AI subprocess starts in an empty temporary directory and receives repository context through its prompt. Rundown requests read-only or tool-free operation, but user-level configuration and extensions installed for that CLI may still apply. Review the provider's data policy and your CLI configuration before researching private or sensitive repositories.

## Other CLI commands

Run `rd --help` for the full command list. Common commands include:

```bash
rd sync-stars
rd repos
rd research OWNER/REPOSITORY
rd classify
rd update-repos
```

`rd run OWNER/REPOSITORY` only detects and reports a possible startup command. It does not execute repository code unless you add `--execute`. Non-Docker commands also require `--allow-non-docker`.

Treat `--execute` as permission to run untrusted project code. Docker is preferred by the detector, but a container is not a security boundary: it may access networks, mounts, the Docker daemon, or host resources allowed by its configuration.

## Development

Run the test suite from the activated virtual environment:

```bash
python -m pytest -q
```

Current limitations:

- Classification and startup-command detection use local heuristics.
- Research quality, cost, and availability depend on the selected AI CLI and its account.
- TUI actions that open GitHub or Markdown files currently use the macOS `open` command.
- Alternate configuration files are loaded independently; they do not inherit values from `config/rundown.toml`.
