# Decision memory for agents and projects

Record why a tool was chosen or rejected so the next agent does not repeat the evaluation:

```bash
rd remember owner/repository --project "My app" \
  --decision "rejected" --reason "Requires a persistent Redis service" \
  --evidence "README setup section at commit abc123" --actor "coding-agent" --json

rd recall --project "My app" --json --limit 10
rd recall --repo owner/repository --json
```

Every call to `remember` appends a timestamped record with project, decision, reason, evidence and actor. It does not overwrite the previous decision, repository notes, host notes or the existing project-fit score. `recall` returns newest records first, ordered by timestamp and insertion ID, with optional project and repository filters.

Evidence is caller-provided and explicitly labeled unverified. The actor field is an attribution label, not authenticated identity. These records explain past reasoning; they are not proof of current repository behavior. A later decision can supersede an earlier one by explanation without deleting history.

Memory appears in inspection and local search. The project filter for search/digest continues to use explicit project-fit mappings; recording a decision does not silently create a project-fit recommendation. Use the existing mapping command when appropriate:

```bash
rd project-fit owner/repository "My app" --score 80 --reason "Passed a local proof of concept"
```

The memory table is created on the first explicit `remember`. Read operations do not migrate older catalogs. Star syncs and research refreshes preserve the append-only history. Recall defaults to 20 records, with limits 1–100. Project/actor labels are limited to 200 characters, decisions to 500, reasons to 4,000 and evidence to 10,000. Empty required fields are rejected.
