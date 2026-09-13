# Research harnesses

`research.provider` remains the harness selector, not a model provider or executable path.
The built-in registry contains `claude`, `gemini`, `codex`, and `opencode`. Existing settings
continue to work. Rundown does not install or authenticate these commands for you.

```toml
[research]
provider = "auto"
fallback = ["claude", "gemini", "codex"]
# Optional. Omit to preserve each CLI's configured model.
# model = "your-model-id"
timeout_seconds = 180
```

`auto` tries only the ordered `fallback` list. An explicit provider runs only that
harness, never another one. A one-item list permits auto without cross-harness
fallback. Empty lists, duplicates, unknown identifiers, and invalid model values
are configuration errors. The default remains Claude, Gemini, Codex; registering
additional harnesses never silently expands that default.

Fallback occurs for missing executables, launch errors, timeout, nonzero exit,
or invalid/incomplete output. Cancellation always propagates without fallback,
even before executable discovery. Every command runs through the shared bounded
process runner, which terminates its process group on timeout/cancellation on
POSIX. A timeout is per attempt, not for the complete fallback chain.

## Isolated OpenCode

```toml
[research]
provider = "opencode"
model = "openai/your-model-id"
```

Set the selected provider's API key in your shell or secret manager. Supported
provider prefixes and environment keys are:

| Prefix | Environment key |
| --- | --- |
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `google` | `GOOGLE_GENERATIVE_AI_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |

Unlike the existing CLI integrations, OpenCode requires an explicit model because
its personal configuration and auth store are deliberately not loaded. Plugin
OAuth authentication and custom provider endpoints are not supported by this
restricted built-in. Use a reviewed custom wrapper if you need a different trust
boundary, rather than weakening the built-in restrictions.

The adapter supplies context on stdin, sets global and agent permissions to deny
all, disables plugins/MCP/skills/project configuration, and gives OpenCode a
disposable HOME and XDG directories. Only the selected provider credential is
forwarded, not arbitrary inherited environment variables. Research still uses the
network to reach that provider. This is configuration/tool isolation, not an OS
sandbox against a compromised installed executable.

System-managed OpenCode configuration can override those restrictions. Rundown
therefore refuses to run when managed JSON/JSONC files or macOS managed preferences
are present, including broken symlinks, or cannot be checked. Doctor reports these
preflight failures without invoking OpenCode. Preflight details are also retained
in fallback history, without credential values.

Output is strict JSONL: only completed `text` parts form the report. Duplicate
part IDs are deduplicated; conflicting duplicates, malformed/unexpected events,
error events, and tool-use events fail the attempt. A requested model is not
treated as proof of the actual model.

The installed OpenCode 1.17.11 CLI was checked with real `debug config` and
`debug agent rundown` commands: plugins and MCP were empty and all reported tools
were disabled. Source behavior was reviewed against v1.18.30. Recheck your version
without inference using `python scripts/check_opencode_isolation.py`. No
authenticated model completion is implied by this offline check.

References: [CLI](https://opencode.ai/docs/cli/),
[permissions](https://opencode.ai/docs/permissions/),
[configuration](https://opencode.ai/docs/config/),
[run event implementation](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/cli/cmd/run.ts),
[managed configuration](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/config/managed.ts).

## Hermes and aider status

Hermes and aider are not registered built-ins. Their proposed restricted wrappers
did not pass the startup-isolation review. This is tracked in
[issue #23](https://github.com/EricGrill/rundown/issues/23), with
[verified findings and opt-in offline audit tests](safe-wrappers.md). Do not treat
an empty CLI tool list or ask mode as a verified deny-all execution boundary.

## Custom commands

```toml
[research]
provider = "local"

[research.custom.local]
executable = "/absolute/path/to/my-research-wrapper"
args = ["--noninteractive"]
prompt = "stdin"
output = "text"
```

Alternatively, use `prompt = "argument"` and `args = ["--prompt", "{prompt}"]`.
Exactly one entire argument must be `{prompt}`. Embedded substitution is rejected.
Stdin mode permits no placeholder. Argument arrays are passed literally, without a
shell, variable expansion, interpolation, or splitting. For executables outside
PATH, use an absolute path. Relative paths resolve against the isolated temporary
working directory, not the repository or configuration file.

`output = "text"` means stdout is the report itself: versioned Rundown card JSON
or the supported Markdown report, still subject to strict section validation.
`output = "json"` means stdout is a JSON envelope:

```json
{"text": "the complete report as a string", "model": "optional-reported-model-id"}
```

Only the envelope's `model` is treated as reported model provenance. If omitted,
it remains unknown. Stderr is not report content. Nonzero exits discard stdout.
Custom harnesses reject `research.model` overrides because arbitrary wrappers have
no standard model flag. Configure model selection in the wrapper's argument array;
this does not imply Rundown knows the actual model. Custom names cannot shadow
built-ins or `auto` and must match `[a-z][a-z0-9_-]*`.

Custom commands are trusted local configuration and execute with the user's
privileges. They are not sandboxed by Rundown and can read environment credentials
or use tools/network. Review wrappers before configuring them. The supplied
repository is untrusted context: built-in commands restrict tools, run outside the
clone in a temporary directory, and never load clone-local command configuration.
The temporary cwd is isolation from repository configuration, not an OS sandbox.

## Provenance and history

Stored provenance retains `provider` for compatibility and adds `harness`,
`requested_harness`, `requested_model`, `actual_model`, and ordered `attempts`.
Harness identifiers are stable registry names, never executable paths.
`requested_model` records intent, not evidence of the model used. Built-in text
outputs do not report model identity, so `actual_model` is null even when a model
was explicitly requested. Legacy records remain readable with unknown fields.

Attempt entries contain only `harness` and a safe `reason`: `missing_executable`,
`launch_error`, `timeout`, `nonzero_exit`, `invalid_output`, `preflight_failed`, or `success`.
Preflight failures may include a safe, adapter-authored `detail` explaining missing
configuration or restrictions. Raw provider diagnostics are never used as details.
No raw stderr, failed stdout, command arguments, environment, or exception text
is included in attempt diagnostics. Failed generations also persist attempts.
`rd research-history owner/repo` and the TUI History view show model provenance,
attempts from successful runs, and the two most recent failed runs. `--json`
returns those failed records followed by the last two successful records.
Model, selection order, and custom command changes invalidate research cache
fingerprints. Existing database columns hold the metadata; no migration is needed.

`rd doctor` uses the same registry and selection rules. It checks executable
availability without invoking AI/custom commands and displays the configured order
and requested model. Availability is not proof of authentication or model access.

## Adapter extension API

All types live in `rundown.harnesses`:

- `HarnessInvocation(argv, input=None, env={}, inherit_env=True)`.
  `None` input means DEVNULL. Environment additions merge with the current process
  unless `inherit_env=False`, which passes only the explicitly supplied environment.
- `HarnessOutput(text: str, actual_model: str | None = None)`.
- `HarnessAdapter(identifier, executable, build, decode=decode_text, supports_model=True)`.
  An optional `preflight(model)` returns a safe failure description or `None`.
  Doctor and execution both use it, without launching the harness.
- `build(prompt: str, model: str | None, workdir: Path) -> HarnessInvocation`.
  Builders may prepare temporary harness configuration inside `workdir`.
- `decode(stdout: str) -> HarnessOutput`. Raise `ValueError` for invalid output.
- `register_harness(adapter)` rejects duplicate/reserved/invalid identifiers.
- `get_harnesses(settings)` returns registered adapters plus configured custom ones.
- `selected_harnesses(settings)` validates settings and returns ordered adapters.

Register adapters before creating settings that reference them. Implementations
must preserve no-model defaults and reject unsupported overrides. Do not infer
actual models from requested flags. Builders must not modify the source clone.

`generate_repository_research(..., return_provider=True)` still returns
`(text, harness_identifier)`; default calls still return a string. The additive
`return_metadata=True` takes precedence and returns
`ResearchGeneration(text, harness, requested_model, actual_model, attempts)`.
`ResearchAgentError.attempts` supplies safe metadata when all selected attempts fail.
