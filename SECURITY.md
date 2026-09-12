# Security Policy

## Reporting vulnerabilities

If you discover a security vulnerability in Rundown, please report it privately through [GitHub Security Advisories](https://github.com/EricGrill/rundown/security/advisories/new).

**Do not open a public issue for security vulnerabilities**, especially if they involve credential exposure or could be exploited before a fix is available.

For less sensitive concerns, open a regular issue and label it appropriately.

## What Rundown does and does not do

### Rundown never:

- Stores or reads API keys (authentication is delegated to `gh`, `claude`, `gemini`, and `codex` CLIs)
- Collects telemetry or usage data
- Phones home or contacts any server except through the CLIs you invoke
- Executes repository code unless you explicitly run `rd run --execute --allow-non-docker`

### Rundown trusts these local tools:

| Tool | Purpose | When invoked |
| --- | --- | --- |
| `git` | Clone and update repositories | `sync-stars`, `research`, `update-repos` |
| `gh` | GitHub API access for star sync | `sync-stars` |
| `claude` / `gemini` / `codex` | Research generation | `research`, `research-missing` |

Rundown invokes these as subprocesses with arguments constructed from repository metadata. It does not inject credentials, override model configuration, or parse CLI output beyond structured research responses.

### Local data storage

All data stays on your machine in gitignored directories:

| Path | Contents |
| --- | --- |
| `data/` | SQLite catalog (repositories, research, preferences, notes) |
| `repos/` | Local clones used for research context |
| `wiki/` | Markdown repository pages and research exports |
| `logs/` | Research and execution logs |
| `exports/` | Generated presentation exports |
| `config/rundown.local.toml` | Personal configuration (gitignored) |

### Research content

Research generation sends repository metadata and content excerpts (README, code samples) to your configured AI CLI. The AI provider's data policy applies. Review that policy before researching private repositories.

Generated research may include hallucinated citations or inaccurate claims—it is not independently verified evidence.

## Scope

This policy covers the Rundown CLI and TUI. It does not cover:

- The AI CLI tools themselves (`claude`, `gemini`, `codex`)
- The GitHub CLI (`gh`)
- Your AI provider's data handling
- Repositories you choose to clone or research

## Supported versions

Security fixes are applied to the latest release. There is no long-term support for older versions.
