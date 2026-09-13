# Rundown Sample Show Pack

*Generated from bundled demo fixtures — no AI provider calls required*

This sample demonstrates Rundown's export format using the three repositories included in the offline demo (`rd demo`). Each entry shows both the **Host Brief** format (for presentations) and selected **Research Card** sections.

---

## Textualize/textual

Build sophisticated user interfaces with a simple Python API.

32,600 stars · Python · Developer Tools

GitHub: https://github.com/Textualize/textual

### Hook

Textual gives Python applications a real interface without asking users to leave the terminal.

### What It Is

Textual is a Python framework for building terminal applications with layouts, widgets, events, and styling.

### Analogy

It is like a web UI toolkit whose screen is the terminal instead of a browser tab.

### Talking Points

- Python components compose the screen.
- CSS controls the terminal layout.
- Headless tests can drive real key bindings.

### Practical Uses

- Prototype a focused internal dashboard.
- Add a modal editor or command palette to a CLI.
- Test keyboard workflows without launching a browser.

### Strengths

- Familiar Python API
- Automated headless testing
- Rich terminal layouts and styling

### Risks

Terminal rendering and keyboard behavior still need testing across platforms and terminal emulators.

### Recommendation

Try now. Build one small workflow and cover its keyboard path with a headless pilot test.

### Host Notes

Open with the fact that Rundown itself uses Textual.

---

## astral-sh/uv

An extremely fast Python package and project manager, written in Rust.

71,300 stars · Rust · Developer Tools

GitHub: https://github.com/astral-sh/uv

### Hook

uv turns the slow, fragmented parts of Python setup into one quick project command.

### What It Is

uv is a fast Python project and package manager that covers environments, dependencies, lockfiles, scripts, tools, and Python installations.

### Analogy

It is a single, fast toolbox that replaces several separate tools previously carried for Python project setup.

### Talking Points

- One tool manages environments and packages.
- The project still uses standard `pyproject.toml`.
- Cached operations make repeated setup fast.

### Use Cases

Developers use it to create repeatable environments, install dependencies, run tools, and build Python packages.

### Strengths

- Fast dependency operations
- Cross-platform project workflow
- Compatible with standard Python package metadata

### Risks

Teams still need to choose and document a consistent workflow when migrating from pip, pipx, or Poetry.

### Recommendation

Try now. Rebuild the project environment from scratch and verify the full test suite.

### Host Notes

Compare the setup command with the older multi-tool Python workflow.

---

## jesseduffield/lazygit

A simple terminal UI for git commands.

62,000 stars · Go · Developer Tools

GitHub: https://github.com/jesseduffield/lazygit

### Hook

lazygit shows how much faster a command-line workflow feels when its state stays visible.

### What It Is

lazygit is an interactive terminal interface for common Git operations and repository state.

### Analogy

It is a control panel over Git: the same engine, with the important state and actions visible together.

### Talking Points

- The repository state stays on screen.
- Keyboard actions operate on the current context.
- Help is part of the interface.

### Practical Uses

- Study its shortcut discoverability.
- Compare compact terminal layouts.
- Observe how destructive actions request confirmation.

### Strengths

- Fast keyboard workflow
- Repository context remains visible
- Common Git operations are discoverable

### Risks

A UI can hide exact command details, so users need a clear way to inspect or understand consequential actions.

### Recommendation

Borrow ideas. Study its contextual help and panel navigation before adding more Rundown shortcuts.

### Host Notes

Use as the familiar comparison for keyboard-first navigation.

---

## About This Export

This show pack was generated from Rundown's bundled demo fixtures to demonstrate the export format without requiring:

- GitHub API access
- AI provider credentials
- Network connectivity

To generate your own show pack:

```bash
# Sync your GitHub stars
rd sync-stars

# Research repositories
rd research-missing --limit 10

# Mark repos for presentation
rd mark astral-sh/uv present
rd mark Textualize/textual present

# Export to Markdown
rd export --output my-show-pack.md
```

Run `rd demo` to explore these same repositories in the interactive TUI.
