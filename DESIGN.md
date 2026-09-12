# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-09-12
- Primary product surfaces: Rundown CLI and Textual TUI.
- Evidence reviewed: README.md, src/rundown/tui.py, src/rundown/research.py, src/rundown/config.py, docs/images/, approved research/show-card proposal.

## Brand
- Personality: practical, calm, concise.
- Trust signals: research date, source references, explicit unknowns, clear distinction between generated advice and host notes.
- Avoid: walls of prose, unsupported readiness claims, decorative dashboards.

## Product goals
- Goals: browse saved tools, understand their value, prepare a short host segment from reusable research.
- Non-goals: video production, an episode scheduler, automatically running demos, or publishing research.
- Success signals: switch card views without AI/network work; scan key findings; expand detail; save notes without losing them during refresh.

## Personas and jobs
- Primary personas: developers exploring repositories and hosts presenting useful software.
- User jobs: understand, evaluate, explain, and prepare next actions.
- Key contexts of use: keyboard-driven browsing, offline saved research, preparation before recording.

## Information architecture
- Primary navigation: repository catalog on left; reader on right.
- Core screens: catalog/reader, action menu, host-notes editor.
- Content hierarchy: repository identity, card view, short labeled sections, notes, expandable complete research.

## Design principles
- Reuse evidence across views; presentation does not trigger research.
- Preserve information: previews can shorten text but complete results remain accessible.
- Preserve human intent: notes and selected views persist separately from generated reports.
- Tradeoffs: compact summaries favor scanning; disclosure retains technical depth.

## Visual language
- Color: existing Textual theme tokens; primary blue for active selection, amber shortcut accents, muted secondary metadata.
- Typography: terminal monospace; strong section labels and readable body text.
- Spacing/layout rhythm: one blank row between groups, padded reader panels, no dense multi-column field grids.
- Shape/radius/elevation: native terminal borders; no new visual framework.
- Motion: avoid animation in card switches; preserve scroll/focus where meaningful.
- Imagery/iconography: actual TUI screenshots in docs; text labels for status.

## Components
- Existing components: DataTable, Markdown, Select, Static, VerticalScroll, command palette.
- New/changed: card-view selector; section disclosures; host-notes modal with Save and Cancel.
- Variants/states: Host brief, Research card, empty, partial/legacy, research error, saved notes.
- Ownership: tui.py and native Textual components; shared card data lives in cards.py.

## Accessibility
- Target: keyboard-operable terminal UI with readable theme contrast.
- Keyboard/focus: explicit view-switch and notes actions; standard disclosure controls; Escape cancels the editor without saving.
- Contrast/readability: never encode readiness or failure with color alone.
- Screen-reader semantics: use native labeled controls where Textual supports them; do not claim untested screen-reader compatibility.
- Reduced motion: no decorative transitions.

## Responsive behavior
- Supported: wide terminal at 140 columns; compact layout below 100 columns.
- Layout adaptations: retain current vertical compact mode and full reader on Enter.
- Touch/hover: no required hover interactions; keyboard is primary.

## Interaction states
- Loading: existing queued/running research remains visible; cached content usable.
- Empty: explain how to research; show missing show fields explicitly without inventing them.
- Error: retain previous research; report validation/provider/save errors with retry guidance.
- Success: save confirmation and a stable selected repository.
- Disabled: no notes edit when no repository is selected.
- Offline/slow network: view changes and note edits work locally; no hidden provider calls.

## Content voice
- Tone: plain and specific; short headings and bullets.
- Terminology: Host brief, Research card, Host notes, Full research, Unknown, Not rehearsed.
- Microcopy: generated demo ideas are not verified demos; a duration is a target, not a measurement.

## Implementation constraints
- Framework: existing Python/Textual/Rich; no new application dependencies.
- Tokens: reuse Textual theme colors and existing layout breakpoints.
- Performance: parse/render cached data locally; no provider calls on view changes.
- Compatibility: keep old Markdown and wiki exports, use additive storage only, retain all unrecognized content.
- Tests/screenshots: test config, parser, cache, note persistence, view switching, disclosure and compact layout; inspect both final card views.

## Open questions
- None blocking this first version. Episode scheduling, dedicated demo records, and audience-facing exports are deferred.
