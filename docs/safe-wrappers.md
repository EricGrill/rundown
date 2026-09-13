# Hermes and aider text-only wrapper investigation

## Decision

**Neither adapter is registered by this change.** These are verified blockers
and a reproducible offline audit, not completed harness support. No production
wrapper, permissive CLI fallback, or invented `none` toolset is shipped.

An isolated working directory is not a sandbox. A text-only research harness
must not interpret repository text as commands, run startup hooks, open a
browser, read unrelated user files, or silently load additional capabilities.
Merely obtaining a final text response is not sufficient verification.

The findings below do not prove that safe integration is impossible. They show
why the proposed thin wrappers do not yet justify registering either harness.
A more restricted implementation needs separate review and end-to-end tests.

## aider 0.86.0

The [Python scripting documentation](https://aider.chat/docs/scripting.html)
explicitly says the Python API is not officially supported and can change
without backward compatibility. Version pinning is necessary, not sufficient.

The proposed candidate was constructed using the real `aider-chat==0.86.0`
distribution, with its `litellm==1.75.0` dependency, in a disposable Python 3.12
environment:

```python
io = InputOutput(yes=False, pretty=False,
                 input_history_file=None, chat_history_file=None)
coder = Coder.create(
    main_model=Model("gpt-4o"), edit_format="ask", io=io,
    use_git=False, auto_lint=False, auto_test=False,
    suggest_shell_commands=False, detect_urls=False, fnames=[],
)
coder.run(prompt, preproc=False)
```

### What the controls do solve

- `preproc=False` keeps a prompt beginning with `/run` as literal model input.
  Without it, the actual preprocessing method dispatches that prompt to the
  commands object, even on an ask coder.
- `InputOutput(yes=False)` declines both ordinary confirmations and `offer_url`.
  This also covers URL offers reached through model-error handling. The browser
  concern in the stock CLI is **not** an unsolved issue for this candidate.
- Ask mode returns no edits from `get_edits()`. Disabling suggested commands,
  Git use, linting, testing, file arguments, and history is useful defense.

### Remaining verified startup blocker

Before any model inference, constructing this candidate attempted:

1. `subprocess.Popen` for `git`, during imports. `use_git=False` does not prevent
   this earlier process launch attempt.
2. DNS lookup of `raw.githubusercontent.com`, for the model metadata URL
   `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`.
   This occurred despite `LITELLM_LOCAL_MODEL_COST_MAP=True`; that setting does
   not eliminate every metadata-fetch path in the installed stack.

A Python audit hook denied both operations. The constructor still completed,
so simply checking construction success would have missed the attempts. The
initial probe recorded one Git launch attempt and two metadata DNS attempts.
The committed test checks presence, not a fragile exact retry count.

These observations do **not** show that Git hooks were executed or information
was exfiltrated: the attempts were blocked, and the probe ran in an empty home
and working directory. They show that the candidate is not a self-contained
inference-only execution path. There is not yet a reviewed restriction covering
imports, metadata loading, model/provider credential discovery, retries,
errors, and response handling. Globally monkeypatching subprocess or networking
inside the real wrapper would not constitute an OS security boundary and could
silently change inference behavior.

Relevant source:

- [AskCoder](https://github.com/Aider-AI/aider/blob/v0.86.0/aider/coders/ask_coder.py)
- [Coder constructor, run, preprocessing, and response handling](https://github.com/Aider-AI/aider/blob/v0.86.0/aider/coders/base_coder.py)
- [InputOutput confirmations and offer_url](https://github.com/Aider-AI/aider/blob/v0.86.0/aider/io.py)
- [Model metadata loading](https://github.com/Aider-AI/aider/blob/v0.86.0/aider/models.py)

## Hermes

The source audit is pinned to commit
`de2d6a1b93508463c31434c1ae067e204af81238`. It is **not** a runtime certification
of every Hermes release or the currently installed personal Hermes environment.
The audited files were compared byte-for-byte with that public commit. Tests
verify SHA-256 before extracting any function.

- The oneshot CLI's `_normalize_toolsets` converts `""`, `[]`, and lists
  containing only blanks to `None`, which means default selection, not deny-all.
  Unknown names are not a valid substitute for a supported empty selection.
- The lower-level Python API does distinguish an empty list from `None`, but
  `_select_tool_names` conditionally appends `kanban` for an owned dispatcher
  worker when `HERMES_KANBAN_TASK` is present. An inherited environment therefore
  matters even for an explicitly empty list. Tests use a synthetic environment,
  not the real worker context.
- `_load_tools` calls plugin discovery **before** fetching tool definitions,
  even when `enabled_toolsets=[]`. `model_tools.py` also invokes built-in tool
  discovery and plugin discovery at module import. Setting `agent.tools=[]`
  after construction cannot prevent earlier startup behavior.
- The constructor additionally initializes provider clients, fallback state,
  configuration, session state, memory/context machinery, and other runtime
  components. An empty schema list alone is not proof of a fully inert lifecycle.

Hermes has configuration-isolation controls. They should not be misrepresented
as a no-tools execution policy. The authoritative
[CLI documentation](https://hermes-agent.nousresearch.com/docs/reference/cli-commands/)
states that `--ignore-user-config` still loads `.env` credentials, and describes
`--ignore-rules` as skipping rules, memory, and preloaded skills. Combining such
controls with a clean environment and an explicit Python empty list is a
possible starting point, not an audited wrapper delivered here.

Relevant pinned source:

- [Oneshot selection](https://github.com/NousResearch/hermes-agent/blob/de2d6a1b93508463c31434c1ae067e204af81238/hermes_cli/oneshot.py#L35-L41)
- [Tool selection and import discovery](https://github.com/NousResearch/hermes-agent/blob/de2d6a1b93508463c31434c1ae067e204af81238/model_tools.py#L313-L334)
- [Agent tool initialization](https://github.com/NousResearch/hermes-agent/blob/de2d6a1b93508463c31434c1ae067e204af81238/agent/agent_init.py#L1046-L1065)
- [Agent initialization pipeline](https://github.com/NousResearch/hermes-agent/blob/de2d6a1b93508463c31434c1ae067e204af81238/agent/agent_init.py#L2175)

## Reproduce without paid inference or personal configuration

The tests are opt-in because installing aider's dependencies and obtaining
Hermes source should not happen automatically during rundown's normal tests.
Without the two audit variables, the corresponding tests explicitly skip.

From the rundown checkout, with `uv`, `curl`, and the project's pytest available:

```sh
AUDIT_ROOT=$(mktemp -d)
uv venv --python 3.12 "$AUDIT_ROOT/aider-venv"
uv pip install --python "$AUDIT_ROOT/aider-venv/bin/python" 'aider-chat==0.86.0'
mkdir -p "$AUDIT_ROOT/hermes/agent" "$AUDIT_ROOT/hermes/hermes_cli"
REV=de2d6a1b93508463c31434c1ae067e204af81238
for FILE in agent/agent_init.py model_tools.py hermes_cli/oneshot.py; do
  curl --fail --silent --show-error \
    "https://raw.githubusercontent.com/NousResearch/hermes-agent/$REV/$FILE" \
    --output "$AUDIT_ROOT/hermes/$FILE"
done
RUNDOWN_AIDER_AUDIT_PYTHON="$AUDIT_ROOT/aider-venv/bin/python" \
RUNDOWN_HERMES_AUDIT_SOURCE="$AUDIT_ROOT/hermes" \
  python -m pytest tests/test_safe_wrappers.py -q
```

The dependency installation and public-source download use the network. The
actual aider probe blocks process launch, shell execution, DNS, and socket
connect attempts **before importing aider**. The child starts with an explicit
minimal environment, a temporary HOME/cwd, `-I`, `-B`, and a fake API key. It does
not invoke the aider CLI entrypoint or load the user's config or secrets. Hermes tests
execute selected, hash-verified functions with instrumented dependencies; they
do not import or initialize a real Hermes agent.

The routing test replaces `send_message` with a recording fixture. This proves
literal prompt routing and confirmation behavior, **not** live model inference,
response-processing safety, provider authentication, or a usable adapter.

## Requirements before enabling either adapter

1. A pinned and reproducible runtime, not whatever packages the user's agent
   interpreter happens to contain.
2. Isolation established before third-party imports, with no inherited plugin,
   tool, worker, dotenv, Python startup, or provider configuration switches.
3. An audited way to avoid unrelated startup processes and metadata traffic,
   plus tests for errors, retries, output handling, and unsolicited tool calls.
4. A deny-all capability policy that survives initialization and refresh, or
   an independently enforced sandbox that makes those capabilities unavailable.
5. A clear credential/model contract. Isolating personal configuration also
   removes configured model defaults and OAuth state; do not silently choose a
   paid model or copy all personal configuration to restore them. An initial
   restricted adapter may need an explicit model and approved credential inputs.
6. Actual subprocess end-to-end fixtures, followed by separately authorized live
   inference. Offline routing or constructor tests cannot be reported as live
   harness support.
