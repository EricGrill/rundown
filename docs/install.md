# Install and upgrade Rundown

Rundown requires Python 3.11 or newer, Git, and GitHub CLI for star synchronization. Live research needs a configured supported harness: Claude, Gemini, Codex, isolated OpenCode, or a trusted custom command. See [harness configuration and restrictions](research-harnesses.md). The offline demo and previously saved research do not need those services.

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

When an intentional TUI change has been visually reviewed, refresh the committed SVG baselines and README screenshots with `python scripts/capture_tui.py --update-baselines --png`. The default command compares the committed wide, compact, and modal views against those baselines and never changes them.

## Publish a GitHub release

1. Confirm the version matches in `pyproject.toml` and `src/rundown/__init__.py`.
2. Run the full verification commands above and install the built wheel in a clean environment.
3. Commit the release, then create and push an annotated tag such as `v0.2.0`.
4. The release workflow verifies the tag, rebuilds the artifacts, and creates the GitHub release with the wheel and source distribution.

## Distribution roadmap

The supported installation route is GitHub source or a built release wheel.
The build currently declares the distribution name `rundown`; `gh-rundown` is
only a proposal, not an implemented package rename or published install route.
PyPI naming and publishing are tracked in [issue #32](https://github.com/EricGrill/rundown/issues/32).
A future trusted-publishing workflow must match the final distribution name and
PyPI publisher configuration, including its environment and OIDC permissions.

Homebrew distribution is tracked in [issue #33](https://github.com/EricGrill/rundown/issues/33).
There is no supported tap/formula in this checkout. A release formula needs real
source/resource URLs and verified hashes before its installation instructions
can be published. Use `rd --help` for a dependency-free CLI smoke test; doctor
also checks optional research prerequisites and may report them as unavailable.
