import json
import subprocess
import sys
import threading
from dataclasses import replace
from unittest.mock import patch

import pytest

from rundown import db, harnesses, history, research
from rundown.config import AppConfig, ResearchSettings, load_config
from rundown.harnesses import CustomHarnessSettings, HarnessAdapter, HarnessInvocation, HarnessOutput
from rundown.processes import OperationCancelled

REPORT = "\n\n".join(f"{heading}\nResearch content." for heading in research.REQUIRED_SECTIONS)


@pytest.mark.parametrize("kwargs", [
    {"provider": "unknown"}, {"fallback": ()}, {"fallback": "claude"},
    {"fallback": ("claude", "claude")}, {"fallback": ("auto",)},
    {"fallback": ("unknown",)}, {"model": ""}, {"model": False},
])
def test_invalid_research_settings(kwargs):
    with pytest.raises(ValueError):
        ResearchSettings(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"executable": ""}, {"executable": "x", "args": "--hello"},
    {"executable": "x", "args": (42,)},
    {"executable": "x", "prompt": "argument"},
    {"executable": "x", "args": ("{prompt}",)},
    {"executable": "x", "prompt": "argument", "args": ("a{prompt}",)},
    {"executable": "x", "prompt": "argument", "args": ("{prompt}", "{prompt}")},
    {"executable": "x", "output": "yaml"},
])
def test_invalid_custom_settings(kwargs):
    with pytest.raises(ValueError):
        CustomHarnessSettings(**kwargs)


def test_toml_custom_and_explicit_order(tmp_path):
    path = tmp_path / "rundown.toml"
    path.write_text('''[research]
provider = "auto"
fallback = ["local", "codex"]
[research.custom.local]
executable = "/opt/local runner"
args = ["--prompt", "{prompt}"]
prompt = "argument"
output = "json"
''')
    settings = load_config(path).research
    adapters = harnesses.selected_harnesses(settings)
    assert [adapter.identifier for adapter in adapters] == ["local", "codex"]
    invocation = adapters[0].build("literal $(x);\nhello", None, tmp_path)
    assert invocation.argv == ["/opt/local runner", "--prompt", "literal $(x);\nhello"]
    assert invocation.input is None
    with pytest.raises(ValueError, match="model overrides"):
        replace(settings, model="requested")
    with pytest.raises(ValueError, match="duplicate"):
        ResearchSettings(custom={"codex": CustomHarnessSettings("x")})


@pytest.mark.parametrize("name", ["claude", "gemini", "codex"])
def test_builtin_model_override_and_defaults(name, tmp_path):
    adapter = harnesses.get_harnesses(ResearchSettings())[name]
    assert "--model" not in adapter.build("prompt", None, tmp_path).argv
    argv = adapter.build("prompt", "provider/model", tmp_path).argv
    assert argv[argv.index("--model") + 1] == "provider/model"
    assert adapter.decode(REPORT).actual_model is None


def test_order_and_safe_attempt_metadata(tmp_path):
    config = AppConfig(root=tmp_path, research=ResearchSettings(fallback=("codex", "claude"), model="requested"))
    with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(
        research, "run_command", side_effect=[
            subprocess.CompletedProcess([], 1, "secret stdout", "token=SECRET"),
            subprocess.CompletedProcess([], 0, REPORT, ""),
        ]
    ) as run:
        result = research.generate_repository_research(config, "prompt", tmp_path, return_metadata=True)
    assert isinstance(result, research.ResearchGeneration)
    assert result.harness == "claude"
    assert result.requested_model == "requested"
    assert result.actual_model is None
    assert result.attempts == ({"harness": "codex", "reason": "nonzero_exit"}, {"harness": "claude", "reason": "success"})
    assert [call.args[0][0] for call in run.call_args_list] == ["codex", "claude"]
    assert "SECRET" not in repr(result)


@pytest.mark.parametrize("failure,reason", [
    (OSError("secret path"), "launch_error"),
    (subprocess.TimeoutExpired("secret", 1), "timeout"),
    (subprocess.CompletedProcess([], 0, "secret invalid output", ""), "invalid_output"),
    (subprocess.CompletedProcess([], 1, "", "secret"), "nonzero_exit"),
])
def test_explicit_harness_never_falls_back(tmp_path, failure, reason):
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider="codex"))
    with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(research, "run_command", side_effect=[failure]) as run:
        with pytest.raises(research.ResearchAgentError) as exc:
            research.generate_repository_research(config, "prompt", tmp_path)
    run.assert_called_once()
    assert exc.value.attempts == ({"harness": "codex", "reason": reason},)
    assert "secret" not in str(exc.value)


def test_cancellation_before_discovery_and_during_execution(tmp_path):
    event = threading.Event()
    event.set()
    with patch.object(research.shutil, "which") as which, pytest.raises(OperationCancelled):
        research.generate_repository_research(AppConfig(root=tmp_path), "prompt", tmp_path, cancel_event=event)
    which.assert_not_called()
    with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(research, "run_command", side_effect=OperationCancelled()) as run, pytest.raises(OperationCancelled):
        research.generate_repository_research(AppConfig(root=tmp_path), "prompt", tmp_path)
    run.assert_called_once()


def test_extension_builder_env_decoder_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses, "_REGISTRY", dict(harnesses._REGISTRY))
    paths = []
    def build(prompt, model, cwd):
        paths.append(cwd)
        (cwd / "config.json").write_text("{}")
        return HarnessInvocation(["extension", "run"], input=prompt, env={"HARNESS_TEST": "yes"})
    harnesses.register_harness(HarnessAdapter("extension", "extension", build, lambda text: HarnessOutput(text, "reported")))
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider="extension", model="requested"))
    def run(argv, **kwargs):
        assert kwargs["input"] == "prompt"
        assert "stdin" not in kwargs
        assert kwargs["env"]["HARNESS_TEST"] == "yes"
        assert (paths[0] / "config.json").is_file()
        return subprocess.CompletedProcess(argv, 0, REPORT, "")
    with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(research, "run_command", side_effect=run):
        result = research.generate_repository_research(config, "prompt", tmp_path, return_metadata=True)
    assert result.actual_model == "reported"
    assert not paths[0].exists()
    with pytest.raises(ValueError, match="Duplicate"):
        harnesses.register_harness(HarnessAdapter("extension", "x", build))


@pytest.mark.parametrize("payload", ["[]", '{}', '{"text": 42}', '{"text":"ok","model":false}'])
def test_custom_json_rejects_invalid_envelope(payload):
    with pytest.raises(ValueError):
        harnesses.decode_json(payload)


def test_custom_json_model_is_reported_not_inferred():
    assert harnesses.decode_json(json.dumps({"text": REPORT, "model": "reported"})) == HarnessOutput(REPORT, "reported")
    assert harnesses.decode_json(json.dumps({"text": REPORT})).actual_model is None


def test_custom_json_rejects_excessive_nesting():
    # CPython 3.14 can parse this depth; it must still reject a non-envelope.
    with pytest.raises(ValueError):
        harnesses.decode_json("[" * 10000 + "0" + "]" * 10000)


def test_custom_json_normalizes_parser_recursion_failure():
    with patch.object(harnesses.json, "loads", side_effect=RecursionError), pytest.raises(ValueError, match="nesting"):
        harnesses.decode_json("[]")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_real_invalid_encoding_records_safe_failure_and_falls_back(tmp_path, stream, exit_code):
    code = f"import sys; sys.{stream}.buffer.write(b'private-token=\\xff'); sys.exit({exit_code})"
    settings = ResearchSettings(fallback=("broken", "good"), custom={
        "broken": CustomHarnessSettings(sys.executable, ("-c", code)),
        "good": CustomHarnessSettings(sys.executable, ("-c", "import sys; print(sys.stdin.read())")),
    })
    result = research.generate_repository_research(AppConfig(root=tmp_path, research=settings), REPORT, tmp_path, return_metadata=True)
    assert result.harness == "good"
    assert result.attempts == ({"harness": "broken", "reason": "invalid_output"}, {"harness": "good", "reason": "success"})
    assert "private-token" not in repr(result)


def test_nested_custom_envelope_continues_fallback(tmp_path):
    code = "print('[' * 10000 + '0' + ']' * 10000)"
    settings = ResearchSettings(fallback=("nested", "good"), custom={
        "nested": CustomHarnessSettings(sys.executable, ("-c", code), output="json"),
        "good": CustomHarnessSettings(sys.executable, ("-c", "import sys; print(sys.stdin.read())")),
    })
    result = research.generate_repository_research(AppConfig(root=tmp_path, research=settings), REPORT, tmp_path, return_metadata=True)
    assert result.harness == "good"
    assert result.attempts[0] == {"harness": "nested", "reason": "invalid_output"}


def test_provenance_persisted_for_success_and_failure(tmp_path):
    config = AppConfig(root=tmp_path)
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "README.md").write_text("A useful library")
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        conn.execute("INSERT INTO repos (full_name, owner, repo, url, local_path) VALUES (?, ?, ?, ?, ?)", ("owner/repo", "owner", "repo", "https://github.com/owner/repo", str(clone)))
        row = db.get_repo(conn, "owner/repo")
        with patch.object(research.shutil, "which", return_value="/bin/tool"), patch.object(research, "run_command", return_value=subprocess.CompletedProcess([], 0, REPORT, "")):
            assert research.run_repository_research(config, conn, "owner/repo", force=True)[0] == "success"
        saved = db.latest_successful_research(conn, row["id"])
        metadata = json.loads(saved["provenance_json"])
        assert metadata["harness"] == "claude"
        assert metadata["actual_model"] is None
        assert metadata["attempts"] == [{"harness": "claude", "reason": "success"}]
        with patch.object(research.shutil, "which", return_value=None):
            assert research.run_repository_research(config, conn, "owner/repo", force=True)[0] == "failed"
        reports = history.research_history(conn, row["id"], include_failed=True)
        output = history.format_research_history(reports)
        assert "Failed research:" in output
        assert "codex: missing_executable" in output
        assert "Harness: claude" in output
        assert "Actual model: unknown" in output
        assert len(history.research_history(conn, row["id"])) == 1


def test_model_change_invalidates_cache_fingerprint(tmp_path):
    config = AppConfig(root=tmp_path)
    updated = replace(config, research=replace(config.research, model="requested"))
    assert research.repository_fingerprint(config, tmp_path, "context", revision=None) != research.repository_fingerprint(updated, tmp_path, "context", revision=None)


def test_real_custom_stdin_and_json_metadata(tmp_path):
    code = "import sys,json; prompt=sys.stdin.read(); print(json.dumps({'text':prompt,'model':'reported'}))"
    settings = ResearchSettings(provider="local", custom={
        "local": CustomHarnessSettings(sys.executable, ("-c", code), output="json"),
    })
    result = research.generate_repository_research(AppConfig(root=tmp_path, research=settings), REPORT, tmp_path, return_metadata=True)
    assert result.text == REPORT
    assert result.harness == "local"
    assert result.actual_model == "reported"


@pytest.mark.parametrize("text", ['research = "bad"', '[research]\nunknown = true', '[research.custom.local]\nargs = []'])
def test_invalid_toml_shape(tmp_path, text):
    path = tmp_path / "rundown.toml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_config(path)
