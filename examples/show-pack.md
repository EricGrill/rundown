# Rundown Sample Show Pack

This is actual exporter output from the bundled offline demo, not live research.
The default selection includes repositories marked present or shortlist: Textual
and uv. Saved views are preserved: Textual uses Host Brief and uv uses Research
Card. Lazygit is not selected because its demo entry has no export decision.
Repository metrics and findings are illustrative fixtures, not current verified
facts. Only the generated timestamp is normalized below for reproducibility.

Regenerate from a development checkout with `python scripts/export_demo.py`.
Verify it with `python scripts/export_demo.py --check`. Neither command contacts
GitHub or an AI provider, or reads your personal catalog.

---

# Rundown Export

*Generated from offline demo fixtures; timestamp omitted.*

**2 repositories**

---

## Textualize/textual

Build sophisticated user interfaces with a simple Python API.

32,600 stars · Python · Developer Tools

GitHub: https://github.com/Textualize/textual

### Hook

Textual gives Python applications a real interface without asking users to leave the terminal.

### What This Is

Textual is a Python framework for building terminal applications with layouts, widgets, events, and styling.

### Talking Points

- Python components compose the screen.
- CSS controls the terminal layout.
- Headless tests can drive real key bindings.

### Why Now

Terminal-first developer tools are increasingly expected to provide discoverable, testable interfaces.

### Demo

Not rehearsed: open Rundown, filter the catalog, and switch from the host brief to the full research card.

### Limitations and Risks

Terminal rendering and keyboard behavior still need testing across platforms and terminal emulators.

### Recommendation

Try now. Build one small workflow and cover its keyboard path with a headless pilot test.

### Sources

- README.md
- docs/guide/app.md
- docs/guide/testing.md

### Host Notes

Open with the fact that Rundown itself uses Textual.

---

## astral-sh/uv

An extremely fast Python package and project manager, written in Rust.

71,300 stars · Rust · Developer Tools

GitHub: https://github.com/astral-sh/uv

### What This Is

uv is a fast Python project and package manager that covers environments, dependencies, lockfiles, scripts, tools, and Python installations.

### Explain It Like I'm Seven

It is a single, fast toolbox that replaces several separate tools previously carried for Python project setup.

### Why Someone Would Use It

Developers use it to create repeatable environments, install dependencies, run tools, and build Python packages.

### Why It Might Matter to You

Rundown already benefits from a compact local setup, so reproducible development and release commands fit directly.

### Why It May Have Caught Your Eye

Inference: its speed and consolidation of common Python workflows plausibly made it attractive.

### How It Works

A Rust implementation manages Python interpreters, resolved dependency graphs, environments, caches, and standards-compatible project metadata.

### Practical Uses for You

- Create the Rundown environment.
- Run pinned quality tools.
- Build the wheel and source distribution.

### Strengths

- Fast dependency operations
- Cross-platform project workflow
- Compatible with standard Python package metadata

### Limitations and Risks

Teams still need to choose and document a consistent workflow when migrating from pip, pipx, or Poetry.

### Install / Run Notes

Install uv, then run `uv sync` in a Python project with a `pyproject.toml` file.

### Maturity Signals

The repository documents broad Python workflow support and distributes versioned releases.

### Questions to Answer

- Which legacy environment commands must remain supported?
- Should the lockfile cover every supported Python version?

### Recommendation

Try now. Rebuild the project environment from scratch and verify the full test suite.

### Sources

- README.md
- docs/guides/projects.md

### Host Notes

Compare the setup command with the older multi-tool Python workflow.

---
