"""Opt-in, offline reproductions of blockers, not adapter acceptance tests.

See docs/safe-wrappers.md for disposable dependency/source setup. No upstream
module is imported into pytest, and the child never receives the user's env.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

HERMES_HASHES = {
    "hermes_cli/oneshot.py": "66219f62f3d4638d2ef16b374661134b0be681aeefd90d4b18084018b632395d",
    "agent/agent_init.py": "3785675c236518a71c2d646dce823bdd4285c0a0acad3642704e700087a8e16a",
    "model_tools.py": "c99620c824ab59f341ac7d0e22cde016b0c469d0643e7a5a5a82e0d63176e4b5",
}


def hermes_function(filename: str, name: str, namespace: dict[str, Any] | None = None) -> Any:
    root = os.environ.get("RUNDOWN_HERMES_AUDIT_SOURCE")
    if not root:
        pytest.skip("Set RUNDOWN_HERMES_AUDIT_SOURCE to the pinned public source")
    data = (Path(root) / filename).read_bytes()
    assert hashlib.sha256(data).hexdigest() == HERMES_HASHES[filename]
    tree = ast.parse(data)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    # Execute only the selected public-source function, never module startup.
    module = ast.Module(body=[node], type_ignores=[])
    scope = {} if namespace is None else dict(namespace)
    exec(compile(module, filename, "exec", flags=__import__("__future__").annotations.compiler_flag), scope)
    return scope[name]


@pytest.mark.parametrize("value", ["", [], ["", " , "]])
def test_hermes_oneshot_empty_toolsets_mean_default(value):
    normalize = hermes_function("hermes_cli/oneshot.py", "_normalize_toolsets")
    assert normalize(value) is None


@pytest.mark.parametrize("worker", [False, True])
def test_hermes_empty_list_depends_on_worker_environment(worker):
    selected = []

    def apply(tools, enabled, quiet, disable):
        selected.extend(enabled)

    select = hermes_function("model_tools.py", "_select_tool_names", {
        "os": SimpleNamespace(environ={"HERMES_KANBAN_TASK": "offline-fixture"} if worker else {}),
        "_is_delegated_child_context": lambda: False,
        "_is_dispatcher_owned_worker": lambda: True,
        "_apply_toolset_selection": apply,
    })
    select([], None, True)
    # Literal [] is empty in a clean environment, but not an unconditional deny-all.
    assert selected == (["kanban"] if worker else [])


def test_hermes_python_api_discovers_plugins_before_empty_selection():
    events = []

    def discover():
        events.append("plugin-discovery")

    def definitions(**kwargs):
        assert kwargs["enabled_toolsets"] == []
        events.append("empty-tool-selection")
        return []

    modules = {
        "hermes_cli.plugins": SimpleNamespace(discover_plugins=discover),
        "tools.registry": SimpleNamespace(registry=SimpleNamespace(_generation=0)),
        "model_tools": SimpleNamespace(get_tool_definitions=definitions),
        "agent.prompt_builder": SimpleNamespace(KANBAN_GUIDANCE=""),
    }

    def isolated_import(name, *args, **kwargs):
        return modules[name]

    load = hermes_function("agent/agent_init.py", "_load_tools", {
        "__builtins__": {"__import__": isolated_import, "set": set, "Exception": Exception},
    })
    agent = SimpleNamespace(quiet_mode=True)
    load(agent, [], None)
    assert agent.tools == []
    assert events == ["plugin-discovery", "empty-tool-selection"]


# This executes real aider code with blocked process/network side effects.
# The send_message replacement below tests routing only, not model inference.
AIDER_PROBE = r'''
import importlib.metadata
import json
import os
import sys
from unittest.mock import Mock

assert importlib.metadata.version("aider-chat") == "0.86.0"
assert importlib.metadata.version("litellm") == "1.75.0"
events = []
def audit(event, args):
    if event in {"subprocess.Popen", "os.system", "socket.connect", "socket.getaddrinfo"}:
        events.append([event, str(args[0])])
        raise PermissionError("blocked offline audit: " + event)
sys.addaudithook(audit)
from aider.coders import Coder
from aider.io import InputOutput
from aider.models import Model
io = InputOutput(yes=False, pretty=False, input_history_file=None, chat_history_file=None)
coder = Coder.create(main_model=Model("gpt-4o"), edit_format="ask", io=io,
    use_git=False, auto_lint=False, auto_test=False, suggest_shell_commands=False,
    detect_urls=False, fnames=[])
startup_events = list(events)
events.clear()
seen = []
def record_message(message):
    seen.append(message)
    coder.partial_response_content = "offline routing fixture, not inference"
    return iter(())
coder.send_message = record_message
prompt = "/run printf SHOULD_NOT_RUN"
result = coder.run(prompt, preproc=False)
literal = seen == [prompt]
commands = Mock()
commands.is_command.return_value = True
coder.commands = commands
coder.preproc_user_input(prompt)
command_dispatched = commands.run.call_args.args == (prompt,)
url_declined = io.offer_url("https://example.invalid/offline-audit") is False
approval_declined = io.confirm_ask("Create a file?") is False
print("RUNDOWN_AUDIT=" + json.dumps({
    "startup_events": startup_events, "routing_events": events,
    "literal": literal, "command_dispatched": command_dispatched,
    "url_declined": url_declined, "approval_declined": approval_declined,
    "edit_format": coder.edit_format, "edits": coder.get_edits(),
    "files": sorted(os.listdir(".")), "result": result,
}))
'''


@pytest.fixture(scope="module")
def aider_audit(tmp_path_factory):
    executable = os.environ.get("RUNDOWN_AIDER_AUDIT_PYTHON")
    if not executable:
        pytest.skip("Set RUNDOWN_AIDER_AUDIT_PYTHON to a disposable aider 0.86.0 venv")
    assert Path(executable).is_absolute()
    home = tmp_path_factory.mktemp("aider-audit")
    result = subprocess.run(
        [executable, "-I", "-B", "-c", AIDER_PROBE],
        input="", capture_output=True, text=True, cwd=home, timeout=90,
        env={
            "HOME": str(home), "PATH": "/usr/bin:/bin",
            "GIT_PYTHON_REFRESH": "quiet", "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "OPENAI_API_KEY": "offline-placeholder-not-a-credential",
        },
    )
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("RUNDOWN_AUDIT="))
    return json.loads(line.removeprefix("RUNDOWN_AUDIT="))


def test_aider_candidate_still_attempts_startup_process_and_metadata_network(aider_audit):
    assert ["subprocess.Popen", "git"] in aider_audit["startup_events"]
    assert ["socket.getaddrinfo", "raw.githubusercontent.com"] in aider_audit["startup_events"]


def test_aider_python_flags_solve_routing_and_approval_not_startup(aider_audit):
    assert aider_audit["literal"]
    assert aider_audit["command_dispatched"]
    assert aider_audit["url_declined"]
    assert aider_audit["approval_declined"]
    assert aider_audit["edit_format"] == "ask"
    assert aider_audit["edits"] == []
    assert aider_audit["routing_events"] == []
