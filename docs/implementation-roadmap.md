# Reliability and workflow delivery

Tracking: https://github.com/EricGrill/rundown/issues/15

## Scope

Implement repository ideas 1–5 and TUI ideas 3–5. Preserve saved Markdown, structured reports, notes, CLI exports, presentation markers, and offline browsing. Episode queues and presenter mode are not part of this release.

## Delivery lanes

| Issues | Work | Main modules |
| --- | --- | --- |
| #7, #9, #10 | CI, isolated demo, reproducible screenshots, doctor, release | .github, demo.py, doctor.py, scripts, pyproject.toml |
| #8, #11 | Effective-card export, human overrides, source provenance/history | db.py, research.py, export.py, history.py |
| #12, #13 | Presets/editor, local preferences, catalog filters/saved views | preferences.py, template_ui.py, catalog.py, catalog_ui.py |
| #14 | Visible job states, retry/cancel, integration | tui.py, jobs.py, jobs_ui.py, processes.py, repo_ops.py |

## Decisions and boundaries

- Reuse Textual and SQLite, with additive schema updates and no new runtime packages.
- Template precedence: repository override, saved global settings, configured TOML defaults. Editing presentation does not call an AI provider.
- Generated content is reusable evidence; manually authored export fields override matching generated sections. Host notes remain independent and are included explicitly.
- Research provenance records the actual provider and supplied repository context; generated citations are not independently verified sources.
- A cancelled job must terminate its subprocess, preserve prior successful research, and never trigger provider fallback. Pending jobs may continue unless the app exits.
- Stale catalog filters use available timestamps and a visible age threshold; filtering never clones or requests research.
- Demo storage is temporary and isolated. Demo controls cannot invoke live research.

## Verification and publication

Run targeted unit and Textual interaction tests per lane, the full suite, typechecking and configured lint. Build wheel and sdist; install in a clean environment and smoke-test help, demo fixtures and doctor. Capture and inspect compact and wide TUI states. Validate cancellation with real harmless child processes. Push all code to main; inspect GitHub Actions. Publish versioned release artifacts only after checks pass. Record issue completion evidence and close tracking only when all eight criteria are met.

## Main risks

Settings resolution can drift between UI/research/export: use one effective-settings helper. Cancellation can race completion: check at every stage and before persistence, and keep previous results. Schema changes can affect old catalogs: cover migrations from legacy tables. UI focus can be stolen by closing/recomposing controls: test Enter, Escape, cancel and modal completion explicitly.

## Simplified daily workflow

Tracking: issues #17–#21

| Issue | Result | Main modules |
| --- | --- | --- |
| #17 | Browse → Read → Prepare → Export action row and local TUI export | tui.py, export_ui.py, export.py |
| #18 | Three basic template presets and duration, with advanced settings under Customize | template_ui.py |
| #19 | One atomic editor for presentation overrides, host notes, and repository notes | presentation.py, card_edit_ui.py |
| #20 | One cache/clone/provider workflow shared by TUI, single, and batch research | research_workflow.py, cli.py, tui.py |
| #21 | Bare `rd` app launch and first-run Try demo / Connect GitHub choice | startup.py, cli.py |

The primary path stays on the main screen. Enter reads, `e` prepares the complete human-authored layer, `n` opens that editor at Host notes, and `x` exports. Generated sections remain read-only. Resetting an override reveals the generated section again without mutating the research log. Explicit CLI commands remain available for scripting, and noninteractive no-argument use does not launch the TUI.
