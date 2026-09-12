# Install and upgrade Rundown

Rundown requires Python 3.11 or newer, Git, and GitHub CLI for star synchronization. Research generation also needs an authenticated Claude, Gemini, or Codex CLI. The offline demo and previously saved research do not need those services.

## Install from GitHub

Use `uv` for an isolated command installation:

```console
uv tool install git+https://github.com/EricGrill/rundown.git
rd doctor
rd demo
```

The equivalent `pipx` command is:

```console
pipx install git+https://github.com/EricGrill/rundown.git
rd doctor
```

## Upgrade

```console
uv tool upgrade rundown
```

For `pipx`, run `pipx upgrade rundown`. Rundown applies additive SQLite schema updates when it opens an existing catalog. Back up `data/rundown.sqlite` before moving between major versions.

## Develop and verify

```console
uv venv
uv pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check src tests scripts
.venv/bin/pyright --pythonpath .venv/bin/python
.venv/bin/python scripts/capture_tui.py
.venv/bin/python -m build
.venv/bin/python scripts/verify_release.py dist
```

The demo fixture is bundled in the wheel. `rd demo` uses a temporary database and never reads the normal catalog, calls GitHub, clones repositories, or invokes an AI provider.

When an intentional TUI change has been visually reviewed, refresh the committed SVG baselines and README screenshots with `python scripts/capture_tui.py --update-baselines --png`. The default command compares twelve wide, compact, and modal views against those baselines and never changes files.

## Publish a GitHub release

1. Confirm the version matches in `pyproject.toml` and `src/rundown/__init__.py`.
2. Run the full verification commands above and install the built wheel in a clean environment.
3. Commit the release, then create and push an annotated tag such as `v0.2.0`.
4. The release workflow verifies the tag, rebuilds the artifacts, and creates the GitHub release with the wheel and source distribution.

No PyPI account is required. GitHub is the release artifact host.
