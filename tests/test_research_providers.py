import subprocess
from unittest.mock import patch

import pytest

from rundown import research
from rundown.config import AppConfig, ResearchSettings, load_config


REPORT = "\n\n".join(f"{heading}\nResearch content." for heading in research.REQUIRED_SECTIONS)


def test_codex_provider_loads_and_returns_final_report(tmp_path):
    config_file = tmp_path / "research.toml"
    config_file.write_text('[research]\nprovider = "codex"\n', encoding="utf-8")
    config = load_config(config_file)
    with (
        patch.object(research.shutil, "which", return_value="/bin/codex"),
        patch.object(research.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, REPORT, "Codex diagnostic output",
        )) as run,
    ):
        assert research.generate_repository_research(config, "research prompt", tmp_path) == REPORT

    command = run.call_args.args[0]
    assert command[:2] == ["codex", "exec"]
    assert command[-1] == "research prompt"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert 'approval_policy="never"' in command
    assert "shell_tool" in command
    assert 'web_search="disabled"' in command
    assert "--ephemeral" in command
    assert "--model" not in command and "-m" not in command
    assert "--ignore-user-config" not in command
    assert run.call_args.kwargs["cwd"] != str(tmp_path)
    assert run.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert run.call_args.kwargs["timeout"] == config.research.timeout_seconds


def test_auto_falls_back_to_codex_after_other_agents_fail(tmp_path):
    config = AppConfig(root=tmp_path)
    with (
        patch.object(research.shutil, "which", side_effect=lambda name: f"/bin/{name}"),
        patch.object(research.subprocess, "run", side_effect=[
            subprocess.CompletedProcess([], 1, "", "Claude unavailable"),
            subprocess.CompletedProcess([], 0, "Incomplete Gemini report", ""),
            subprocess.CompletedProcess([], 0, REPORT, ""),
        ]) as run,
    ):
        assert research.generate_repository_research(config, "prompt", tmp_path) == REPORT
    assert [call.args[0][0] for call in run.call_args_list] == ["claude", "gemini", "codex"]


def test_auto_uses_codex_when_other_clis_are_not_installed(tmp_path):
    with (
        patch.object(research.shutil, "which", side_effect=lambda name: "/bin/codex" if name == "codex" else None),
        patch.object(research.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, REPORT, "")) as run,
    ):
        assert research.generate_repository_research(AppConfig(root=tmp_path), "prompt", tmp_path) == REPORT
    run.assert_called_once()
    assert run.call_args.args[0][0] == "codex"


@pytest.mark.parametrize("failure, message", [
    (subprocess.CompletedProcess([], 1, "", "login required"), "codex failed: login required"),
    (subprocess.CompletedProcess([], 0, "incomplete", ""), "codex returned incomplete research"),
    (subprocess.TimeoutExpired("codex", 180), "codex exceeded the 180s timeout"),
])
def test_codex_failures_are_reported(tmp_path, failure, message):
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider="codex"))
    with (
        patch.object(research.shutil, "which", return_value="/bin/codex"),
        patch.object(research.subprocess, "run", side_effect=[failure]),
        pytest.raises(research.ResearchAgentError, match=message),
    ):
        research.generate_repository_research(config, "prompt", tmp_path)


def test_explicit_codex_reports_missing_installation(tmp_path):
    config = AppConfig(root=tmp_path, research=ResearchSettings(provider="codex"))
    with (
        patch.object(research.shutil, "which", return_value=None),
        patch.object(research.subprocess, "run") as run,
        pytest.raises(research.ResearchAgentError, match="codex is not installed"),
    ):
        research.generate_repository_research(config, "prompt", tmp_path)
    run.assert_not_called()
