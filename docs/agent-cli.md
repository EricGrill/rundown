# Agent CLI

Rundown can supply a coding agent with your saved tools before it chooses a dependency. Local lookup does not start the TUI or an AI provider.

## Search your library

```bash
rd search "background jobs python" --json --limit 5
rd search "termnal" --json
rd search "queue" --project "My app" --json
rd repos --json --project "My app" --limit 20
```

Search matches words in any order, prefixes, and spelling mistakes across repository metadata, human notes/presentation fields and the latest successful research. It returns deterministic scores, matched fields, source labels and excerpts. Exact names receive stronger weight. All query words must match; use a few descriptive keywords instead of a full conversational request. This is lexical retrieval, not semantic reasoning: matching “without Redis” is not proof that a tool works without Redis. An agent should inspect and verify the returned evidence.

Search excludes archived repositories by default; use `--include-archived` to include them. `--project` uses existing project-fit mappings. Results include locally imported/unstarred catalog entries as well as stars.

## Machine output

New commands with `--json` emit exactly one UTF-8 JSON object on stdout:

```json
{"schema_version":1,"ok":true,"data":{"results":[]},"error":null}
```

Failures use `ok:false` and `error:{code,message}`. Exit codes: `0` success (including zero matches), `1` operational failure, `2` invalid input/configuration, `130` cancellation. Option-parser syntax errors (unknown flags, missing required arguments, noninteger integer flags) use Typer's stderr diagnostics with exit 2 rather than a JSON envelope. Always check the process exit status. Existing `doctor --json` and `research-history --json` retain their original formats.

`--config /absolute/path/to/config/rundown.toml` belongs after the subcommand. Use an absolute path when invoking from an editor, agent or scheduler in another working directory. An explicitly supplied missing configuration is an error.

Local read commands open existing SQLite catalogs read-only without migrations or application directory creation. SQLite may create or use `-wal`/`-shm` coordination files beside an existing WAL database; readers preserve committed WAL data rather than ignoring it. Missing databases are treated as empty catalogs. Unsupported core schemas report `incompatible_catalog`; missing optional legacy fields are treated as unavailable.

Search defaults to 5 results, catalog JSON to 100; both accept limits from 1 to 100. Catalog listing reports `total_count` and `truncated`. Human `rd repos` output remains the existing table; its `--limit` applies only to JSON output. Search reports retrieval bounds and truncation separately: a bounded corpus match is not a guarantee that no other relevant repository exists.
