# Research harness verification

Rundown has two distinct verification layers. Passing the offline suite does not
prove that a particular installed harness version can authenticate or reach its
model provider.

## Offline contract checks

From an installed development checkout:

```sh
python -m pytest -q
python -m ruff check src tests scripts
python -m pyright --pythonpath "$(command -v python)"
python -m build
python scripts/verify_release.py dist
```

The research tests validate command construction, configuration, structured
research parsing, fallback, and provenance. Process transport tests launch local
Python subprocesses, not model providers. They exercise literal argument passing,
large Unicode prompts through stdin, and cancellation or timeout while the child
is not consuming stdin. Existing process-group tests check descendant cleanup on
POSIX systems.

When adding a harness, check all these failure paths, not just a successful
response:

- Executable missing or not executable.
- Nonzero exit, including authentication failure. Do not persist raw stderr that
  could contain credentials or provider request details.
- Empty output, malformed output, and valid JSON with incomplete research fields.
- Deadline expiration, including processes that spawn children.
- Cancellation before launch and during generation. Cancellation must not start
  the next fallback candidate.
- A successful fallback records which harness was actually used and why earlier
  candidates failed.
- Prompt content containing quotes, newlines, shell metacharacters, and Unicode.
- Model defaults remain untouched unless an override was explicitly requested.

## Optional authenticated smoke test

Run this separately for each installed harness you intend to use. It can incur
model charges and transmit the supplied public repository context to that
harness's configured model service.

1. Inspect the installed harness version and compare its flags with the adapter's
   documented upstream references. Do not silently replace rejected safety flags.
2. Authenticate using the harness's own documented setup, outside Rundown. Never
   put credentials in a test fixture or commit them in TOML.
3. Use an isolated Rundown configuration with temporary database, repository,
   research, and export paths. Select one harness explicitly, not automatic
   fallback. Use a small public repository you have permission to inspect.
4. Run the repository research command with that configuration. Verify the saved
   record contains every required field and identifies the selected harness.
5. Inspect research history. An unreported actual model must remain unknown; a
   requested model is not proof of the serving model's identity.
6. Repeat with a forced refresh and cancel during generation. Confirm no report
   replaced the previous successful record and no child process remains alive.
7. Delete only the temporary test catalog when finished. Do not change the user's
   personal harness profiles or credential stores to make a test pass.

Record the harness version, operating system, selected model (if known), command
exit status, and validation result. Never describe an offline fixture run as an
authenticated end-to-end test.
