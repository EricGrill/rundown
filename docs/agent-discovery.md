# Discover tools beyond your catalog

```bash
rd discover "background jobs language:Python" --json --limit 5
rd discover "search language:Rust stars:>100" --sort stars --json
rd discover "terminal language:Python" --sort updated --include-saved --json
rd add owner/repository --json
rd inspect owner/repository --json
rd research owner/repository --json
```

`discover` explicitly contacts GitHub through the authenticated `gh` CLI. It searches public repository metadata using GitHub's keyword/qualifier syntax. It does not call an AI provider, save candidates, clone repositories or change stars.

`best-fit` means GitHub's best-match order, not a verified assessment of your project constraints. `stars` sorts by popularity; `updated` sorts by activity. Each result separately reports GitHub rank, star count, last-pushed timestamp, and local membership. Check source evidence before adopting a tool.

A request examines at most the first 100 GitHub candidates and returns up to `--limit` (default 5, maximum 100). Saved entries are excluded unless `--include-saved` is set; the result can contain fewer than the requested limit even when later GitHub pages contain more matches. `candidate_limit`, `more_candidates_available`, and `incomplete_results` expose this boundary. Narrow the query instead of assuming zero matches means no suitable tool exists.

Discovery adds `is:public` and defaults to `archived:false` unless you provide an archive qualifier. It respects GitHub query syntax rather than translating conversational requests. All requests use explicit GET, a 30-second timeout, and no automatic retry; auth/rate-limit/API failures return a machine error. Retry later according to GitHub's error guidance.

`add` is a separate explicit write: fetch public metadata, then insert an unstarred local entry. It does not star anything on GitHub or run research. Existing catalog entries are returned unchanged, preserving notes, project fit, decisions and research. Imported entries initially have no category; a later star sync or classification workflow can populate one. A later sync of the same GitHub star updates that catalog entry rather than duplicating it. Renamed repositories require you to add the canonical name explicitly.

The command's query and selected repo name are sent to GitHub. Saved research and human notes are not included in discovery requests.

Official behavior references: [GitHub repository search](https://docs.github.com/en/rest/search/search), [repository query syntax](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories), and [gh api GET parameters](https://cli.github.com/manual/gh_api).
