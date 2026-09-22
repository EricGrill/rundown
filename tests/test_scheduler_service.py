import plistlib
from pathlib import Path
import subprocess

import pytest

from rundown.agent_io import AgentError
from rundown.config import AppConfig
from rundown import scheduler_service as service


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    root = tmp_path / "project with spaces"
    source = root / "config" / "rundown.toml"
    source.parent.mkdir(parents=True)
    source.write_text("")
    config = AppConfig(root=root)
    state = {"loaded": False, "fail": None, "calls": []}

    def launchctl(*args):
        state["calls"].append(args)
        code = 0
        if args[0] == state["fail"]:
            code = 1
        elif args[0] == "print":
            code = 0 if args[1] == service._domain() or state["loaded"] else 1
        elif args[0] == "bootstrap":
            state["loaded"] = True
        elif args[0] == "bootout":
            state["loaded"] = False
        return subprocess.CompletedProcess(args, code, "", "mock failure" if code else "")

    monkeypatch.setattr(service, "_launchctl", launchctl)
    return config, source, state


def test_plist_preserves_venv_paths_and_safe_environment(environment, monkeypatch, tmp_path):
    cfg, source, _ = environment
    interpreter = tmp_path / "venv with spaces" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to("/usr/bin/python3")
    monkeypatch.setattr(service.sys, "executable", str(interpreter))
    monkeypatch.setenv("PATH", "/opt/provider bin:relative::/usr/bin")
    result = service.enable_service(cfg, source)
    with Path(result["plist"]).open("rb") as stream:
        plist = plistlib.load(stream)
    assert plist["ProgramArguments"] == [str(interpreter), "-m", "rundown.cli", "schedule", "run", "--config", str(source), "--json"]
    assert plist["StartInterval"] == 3600
    assert plist["RunAtLoad"] is True
    assert "KeepAlive" not in plist
    assert plist["ExitTimeOut"] == 30
    assert plist["WorkingDirectory"] == str(cfg.root)
    assert "/opt/provider bin" in plist["EnvironmentVariables"]["PATH"]
    assert "relative" not in plist["EnvironmentVariables"]["PATH"]
    assert all(Path(p).is_absolute() for p in plist["EnvironmentVariables"]["PATH"].split(":"))


def test_enable_disable_are_idempotent_and_preserve_data(environment):
    cfg, source, state = environment
    cfg.database_path.parent.mkdir(parents=True)
    cfg.database_path.write_text("preserve catalog")
    assert service.enable_service(cfg, source)["changed"] is True
    assert service.enable_service(cfg, source)["changed"] is False
    assert service.service_status(cfg)["enabled"] is True
    assert service.disable_service(cfg)["changed"] is True
    assert service.disable_service(cfg)["changed"] is False
    assert cfg.database_path.read_text() == "preserve catalog"
    assert len([call for call in state["calls"] if call[0] == "bootstrap"]) == 1
    assert [call for call in state["calls"] if call[0] == "bootout"] == [("bootout", f"{service._domain()}/{service.service_label(cfg)}")]


def test_bootstrap_failure_rolls_back_new_plist(environment):
    cfg, source, state = environment
    state["fail"] = "bootstrap"
    with pytest.raises(AgentError, match="Could not enable"):
        service.enable_service(cfg, source)
    assert not service._plist_path(cfg).exists()


def test_bootout_failure_preserves_plist(environment):
    cfg, source, state = environment
    service.enable_service(cfg, source)
    state["fail"] = "bootout"
    with pytest.raises(AgentError, match="Could not disable"):
        service.disable_service(cfg)
    assert service._plist_path(cfg).exists()


def test_unrelated_plist_is_never_overwritten_or_deleted(environment):
    cfg, source, state = environment
    path = service._plist_path(cfg)
    path.parent.mkdir(parents=True)
    content = plistlib.dumps({"Label": service.service_label(cfg), "ProgramArguments": ["other"]})
    path.write_bytes(content)
    for operation in (lambda: service.enable_service(cfg, source), lambda: service.disable_service(cfg)):
        with pytest.raises(AgentError, match="unrelated"):
            operation()
    assert path.read_bytes() == content
    assert state["calls"] == []


def test_changed_settings_require_explicit_disable(environment, monkeypatch):
    cfg, source, _ = environment
    monkeypatch.setenv("PATH", "/usr/bin")
    service.enable_service(cfg, source)
    monkeypatch.setenv("PATH", "/custom/bin:/usr/bin")
    with pytest.raises(AgentError, match="settings differ"):
        service.enable_service(cfg, source)


def test_missing_saved_configuration_is_rejected(environment):
    cfg, source, state = environment
    source.unlink()
    with pytest.raises(AgentError, match="saved configuration"):
        service.enable_service(cfg, source)
    assert state["calls"] == []


def test_platform_guard(environment, monkeypatch):
    cfg, source, state = environment
    monkeypatch.setattr(service.sys, "platform", "win32")
    for operation in (lambda: service.enable_service(cfg, source), lambda: service.disable_service(cfg)):
        with pytest.raises(AgentError, match="external scheduler"):
            operation()
    assert service.service_status(cfg)["supported"] is False
    assert state["calls"] == []


def test_unavailable_launchd_domain_reported(environment):
    cfg, _, state = environment
    state["fail"] = "print"
    with pytest.raises(AgentError, match="Cannot access"):
        service.service_status(cfg)


def test_labels_follow_catalog_identity(tmp_path):
    from rundown.config import PathSettings
    cfg = AppConfig(root=tmp_path)
    same = AppConfig(root=tmp_path / "other", paths=PathSettings(database=cfg.database_path))
    other = AppConfig(root=tmp_path / "other")
    assert service.service_label(cfg) == service.service_label(same)
    assert service.service_label(cfg) != service.service_label(other)


def test_retry_bootstrap_preserves_existing_owned_plist(environment):
    cfg, source, state = environment
    service.enable_service(cfg, source)
    path = service._plist_path(cfg)
    content = path.read_bytes()
    state["loaded"] = False
    state["fail"] = "bootstrap"
    with pytest.raises(AgentError, match="Could not enable"):
        service.enable_service(cfg, source)
    assert path.read_bytes() == content


def test_launchctl_os_error_rolls_back_new_plist(environment, monkeypatch):
    cfg, source, _ = environment
    previous = service._launchctl

    def fail_bootstrap(*args):
        if args[0] == "bootstrap":
            raise OSError("launchctl unavailable")
        return previous(*args)

    monkeypatch.setattr(service, "_launchctl", fail_bootstrap)
    with pytest.raises(OSError, match="launchctl unavailable"):
        service.enable_service(cfg, source)
    assert not service._plist_path(cfg).exists()


def test_unowned_loaded_service_is_not_stopped(environment):
    cfg, _, state = environment
    state["loaded"] = True
    with pytest.raises(AgentError, match="ownership"):
        service.disable_service(cfg)
    assert all(call[0] != "bootout" for call in state["calls"])


def test_symlink_plist_is_not_modified(environment, tmp_path):
    cfg, source, _ = environment
    destination = tmp_path / "other.plist"
    destination.write_bytes(plistlib.dumps(service.launch_agent(cfg, source)))
    path = service._plist_path(cfg)
    path.parent.mkdir(parents=True)
    path.symlink_to(destination)
    with pytest.raises(AgentError, match="symlink"):
        service.disable_service(cfg)
    assert path.is_symlink()
    assert destination.exists()


def test_launchctl_timeout_reports_service_error(monkeypatch):
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(command, 30)
    monkeypatch.setattr(service.subprocess, "run", timeout)
    with pytest.raises(AgentError, match="did not respond"):
        service._launchctl("print", "gui/123/example")
