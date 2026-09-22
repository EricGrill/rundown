# Install and upgrade Rundown

Rundown requires Python 3.11 or newer, Git, and GitHub CLI for star synchronization. Live research needs a configured supported harness: Claude, Gemini, Codex, isolated OpenCode, or a trusted custom command. See [harness configuration and restrictions](research-harnesses.md). The offline demo and previously saved research do not need those services.

## Install with Homebrew

```console
brew install ericgrill/tap/rundown
rd demo
```

The formula installs Rundown in its own Python environment and pulls in GitHub CLI.

## Install from PyPI

The PyPI distribution is named `gh-rundown` because `rundown` is taken. The commands are still `rundown` and `rd`.

```console
uv tool install gh-rundown
rd demo
```

With `pipx`, run `pipx install gh-rundown`. PyPI packages are published from the first release after 0.2.0.

## Install from GitHub

Use this for the latest unreleased code:

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
brew upgrade rundown        # Homebrew
uv tool upgrade gh-rundown  # uv
pipx upgrade gh-rundown     # pipx
```

Installs made before the `gh-rundown` rename are registered under the old name. Reinstall once with `uv tool uninstall rundown && uv tool install gh-rundown`. Rundown applies additive SQLite schema updates when it opens an existing catalog. Back up `data/rundown.sqlite` before moving between major versions.

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

When an intentional TUI change has been visually reviewed, refresh the committed SVG baselines and README screenshots with `python scripts/capture_tui.py --update-baselines --png`. The default command compares the committed wide, compact, and modal views against those baselines and never changes them.

## Publish a release

1. Confirm the version matches in `pyproject.toml` and `src/rundown/__init__.py`.
2. Run the full verification commands above and install the built wheel in a clean environment.
3. Commit the release, then create and push an annotated tag such as `v0.3.0`.
4. The release workflow verifies the tag, rebuilds the artifacts, creates the GitHub release, then publishes to PyPI.
5. Update `Formula/rundown.rb` in `EricGrill/homebrew-tap` with the new source URL and SHA-256.

PyPI publishing uses trusted publishing. Before the first release, add a pending publisher on pypi.org for project `gh-rundown`, repository `EricGrill/rundown`, workflow `release.yml`, environment `pypi`.
