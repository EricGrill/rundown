# Contributing to Rundown

Contributions are welcome. This document explains how to set up a development environment, run checks, and submit changes.

## Development setup

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/EricGrill/rundown.git
cd rundown
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Or use `uv` for faster installs:

```bash
git clone https://github.com/EricGrill/rundown.git
cd rundown
uv venv
uv pip install -e ".[dev]"
source .venv/bin/activate
```

Verify your setup:

```bash
rd doctor
rd demo
```

## Running checks

Run the full test and lint suite before submitting:

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m pyright --pythonpath .venv/bin/python
python scripts/capture_tui.py
```

`capture_tui.py` compares twelve TUI snapshots against committed baselines. If you intentionally change the UI, review the diff and update baselines:

```bash
python scripts/capture_tui.py --update-baselines --png
```

Build and verify the package locally:

```bash
python -m build
python scripts/verify_release.py dist
```

## Pull request expectations

- **Tests**: Add or update tests for new behavior. All checks must pass.
- **Docs**: Update README, docstrings, or docs/ if user-facing behavior changes.
- **Commits**: Write clear commit messages. One logical change per commit is preferred.
- **No secrets**: Never commit API keys, tokens, or personal catalog data.
- **PR description**: Explain what changed and why. Link related issues if applicable.

PRs are reviewed for correctness, clarity, and consistency with the existing codebase.

## Finding work

Look for issues labeled:

- **good first issue**: Smaller tasks suitable for new contributors
- **help wanted**: Well-defined work that could use assistance
- **bug**: Confirmed problems to fix
- **enhancement**: Approved feature requests

Maintainers may add `epic` or area labels to organize larger efforts. Check the [implementation roadmap](docs/implementation-roadmap.md) for current delivery priorities.

If you want to work on something not yet filed, open an issue first to discuss scope.

## Project structure

Key modules and their responsibilities:

| Path | Purpose |
| --- | --- |
| `src/rundown/cli.py` | Typer CLI entry points |
| `src/rundown/tui.py` | Textual TUI application |
| `src/rundown/research.py` | AI provider orchestration |
| `src/rundown/cards.py` | Research card parsing and validation |
| `src/rundown/db.py` | SQLite catalog operations |
| `src/rundown/demo.py` | Offline demo fixtures |
| `src/rundown/doctor.py` | Setup diagnostics |
| `scripts/capture_tui.py` | Deterministic TUI snapshot capture |
| `tests/` | pytest test suite |

See [DESIGN.md](DESIGN.md) for product goals, personas, and design principles.

## Code style

- Python 3.11+ with type hints
- Ruff for linting (configured in pyproject.toml)
- Pyright for type checking
- Prefer clear, direct code over clever abstractions
- Match the existing tone: practical, calm, concise

## Questions

Open a GitHub issue or discussion. The maintainers respond to issues directly—no DM required.
