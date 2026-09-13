import json

from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from rundown import doctor, harnesses, opencode_harness, research
from rundown.config import AppConfig, ResearchSettings
from rundown.processes import OperationCancelled

REPORT = "\n\n".join(f"{heading}\nResearch content." for heading in research.REQUIRED_SECTIONS)


def event(text=REPORT, identifier="part-1"):
    return {"type": "text", "part": {"id": identifier, "text": text}}


@pytest.fixture
def isolated_opencode(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-credential")
    monkeypatch.setattr(opencode_harness, "managed_config_paths", lambda: ())


def test_registry_does_not_expand_default_fallback():
    settings = ResearchSettings()
    assert "opencode" in harnesses.get_harnesses(settings)
    assert [item.identifier for item in harnesses.selected_harnesses(settings)] == ["claude", "gemini", "codex"]


def test_opencode_environment_and_deny_all_config(tmp_path, monkeypatch, isolated_opencode):
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission":"allow"}')
    monkeypatch.setenv("NODE_OPTIONS", "--require /evil/plugin.js")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-secret")
    monkeypatch.setattr(opencode_harness.shutil, "which", lambda name: "/bin/opencode")
    invocation = opencode_harness.build_opencode("literal $(touch x)", "openai/test", tmp_path)
    assert invocation.inherit_env is False
    assert invocation.input == "literal $(touch x)"
    assert invocation.argv[0] == "/bin/opencode"
    assert "--pure" in invocation.argv
    assert invocation.argv[invocation.argv.index("--model") + 1] == "openai/test"
    for key in ("OPENCODE_CONFIG_CONTENT", "NODE_OPTIONS", "ANTHROPIC_API_KEY"):
        assert key not in invocation.env
    assert invocation.env["OPENAI_API_KEY"] == "offline-test-not-a-credential"
    assert invocation.env["HOME"] == str(tmp_path / "home")
    config = json.loads(Path(invocation.env["OPENCODE_CONFIG"]).read_text())
    assert config["permission"] == config["agent"]["rundown"]["permission"] == {"*": "deny"}
    assert config["enabled_providers"] == ["openai"]
    assert config["plugin"] == [] and config["mcp"] == {}
    assert config["share"] == "disabled"


def test_managed_config_blocks_even_broken_symlink(tmp_path, monkeypatch, isolated_opencode):
    managed = tmp_path / "managed.json"
    managed.symlink_to(tmp_path / "missing")
    monkeypatch.setattr(opencode_harness, "managed_config_paths", lambda: (managed,))
    assert "system-managed" in opencode_harness.opencode_preflight("openai/test")


@pytest.mark.parametrize("model", [None, "model-only", "unknown/model", "openai/", "openai/a\x00b"])
def test_unsafe_or_missing_model_fails_closed(model, isolated_opencode):
    assert opencode_harness.opencode_preflight(model)


def test_missing_credential_is_actionable_without_exposing_values(monkeypatch, isolated_opencode):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "requires OPENAI_API_KEY" in opencode_harness.opencode_preflight("openai/test")


def test_decoder_deduplicates_complete_parts_and_ignores_reasoning():
    events = [event("one"), {"type": "reasoning", "part": {"text": "private reasoning"}},
              event("one"), event("two", "part-2"), {"type": "step_finish"}]
    decoded = opencode_harness.decode_opencode("\n".join(map(json.dumps, events)))
    assert decoded.text == "one\ntwo"
    assert decoded.actual_model is None


@pytest.mark.parametrize("bad", [
    "not json", "[]", "{}", '{"type":"text","part":{"text":"no id"}}',
    '{"type":"unknown"}', '{"type":"error"}', '{"type":"tool_use"}',
    '{"type":"text","part":{"id":"x","text":42}}',
])
def test_decoder_rejects_errors_even_after_valid_text(bad):
    with pytest.raises(ValueError):
        opencode_harness.decode_opencode(json.dumps(event()) + "\n" + bad)


def test_decoder_rejects_conflicting_parts():
    with pytest.raises(ValueError, match="Conflicting"):
        opencode_harness.decode_opencode(json.dumps(event("first")) + "\n" + json.dumps(event("second")))


def test_preflight_is_visible_in_doctor_and_fallback_history(tmp_path, isolated_opencode):
    config = AppConfig(root=tmp_path, research=ResearchSettings(fallback=("opencode", "codex")))
    with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(
        research, "run_command", return_value=subprocess.CompletedProcess([], 0, REPORT, "")
    ) as run:
        result = research.generate_repository_research(config, "prompt", tmp_path, return_metadata=True)
        check = doctor._provider_check(config)
    run.assert_called_once()
    assert result.harness == "codex"
    assert result.attempts[0]["reason"] == "preflight_failed"
    assert "requires research.model" in result.attempts[0]["detail"]
    assert "requires research.model" in check.message


def test_real_opencode_fixture_uses_stdin_and_clean_environment(tmp_path, monkeypatch, isolated_opencode):
    executable = tmp_path / "opencode"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,sys\n"
        "assert 'UNRELATED_SECRET' not in os.environ\n"
        "assert os.environ['OPENCODE_PURE'] == 'true'\n"
        "assert pathlib.Path.cwd() == pathlib.Path(os.environ['HOME']).parent.resolve()\n"
        "text = sys.stdin.read()\n"
        "print(json.dumps({'type':'text','part':{'id':'fixture','text':text}}))\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-leak")
    monkeypatch.setattr(research.shutil, "which", lambda name: str(executable))
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider="opencode", model="openai/test"))
    result = research.generate_repository_research(config, REPORT, tmp_path, return_metadata=True)
    assert result.text == REPORT
    assert result.harness == "opencode"
    assert result.requested_model == "openai/test"
    assert result.actual_model is None


@pytest.mark.parametrize("name", ["claude", "gemini", "codex", "opencode"])
@pytest.mark.parametrize("failure,reason", [
    (subprocess.CompletedProcess([], 1, "", "authentication failed token=DO_NOT_LOG"), "nonzero_exit"),
    (subprocess.CompletedProcess([], 0, "malformed", ""), "invalid_output"),
    (subprocess.TimeoutExpired("secret argv", 1), "timeout"),
    (OSError("secret path"), "launch_error"),
])
def test_shared_failure_contract(name, failure, reason, tmp_path, isolated_opencode):
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider=name, model="openai/test"))
    with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(
        research, "run_command", side_effect=[failure]
    ) as run, pytest.raises(research.ResearchAgentError) as raised:
        research.generate_repository_research(config, REPORT, tmp_path)
    run.assert_called_once()
    assert raised.value.attempts == ({"harness": name, "reason": reason},)
    assert "secret" not in str(raised.value) and "DO_NOT_LOG" not in str(raised.value)


@pytest.mark.parametrize("name", ["claude", "gemini", "codex", "opencode"])
def test_shared_missing_and_cancellation_contract(name, tmp_path, isolated_opencode):
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider=name, model="openai/test"))
    with patch.object(research.shutil, "which", return_value=None), pytest.raises(research.ResearchAgentError) as raised:
        research.generate_repository_research(config, REPORT, tmp_path)
    assert raised.value.attempts == ({"harness": name, "reason": "missing_executable"},)
    cancelled = threading.Event()
    cancelled.set()
    with patch.object(research, "run_command") as run, pytest.raises(OperationCancelled):
        research.generate_repository_research(config, REPORT, tmp_path, cancel_event=cancelled)
    run.assert_not_called()
