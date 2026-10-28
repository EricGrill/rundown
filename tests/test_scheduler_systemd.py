from pathlib import Path
import subprocess

import pytest

from rundown.agent_io import AgentError
from rundown.config import AppConfig
from rundown import scheduler_service as service
from rundown import scheduler_systemd as systemd


@pytest.fixture
def linux(tmp_path, monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    root = tmp_path / "project with spaces"
    source = root / "config" / "rundown.toml"
    source.parent.mkdir(parents=True)
    source.write_text("")
    state = {"enabled": False, "fail": None, "calls": []}

    def systemctl(*args):
        state["calls"].append(args)
        code = 0
        if args[0] == state["fail"]:
            code = 1
        elif args[0] == "is-enabled":
            code = 0 if state["enabled"] else 1
        elif args[0] == "enable":
            state["enabled"] = True
        elif args[0] == "disable":
            state["enabled"] = False
        return subprocess.CompletedProcess(args, code, "", "mock failure" if code else "")

    monkeypatch.setattr(systemd, "_systemctl", systemctl)
    return AppConfig(root=root), source, state


def test_enable_writes_owned_units_and_starts_timer(linux):
    cfg, source, state = linux
    result = service.enable_service(cfg, source)
    timer = Path(result["unit"])
    unit = timer.with_suffix(".service")
    assert timer.parent == Path.home() / ".config" / "systemd" / "user"
    text = unit.read_text()
    assert f'"--config" "{source}" "--json"' in text
    assert f"WorkingDirectory={cfg.root.resolve()}\n" in text
    assert "OnUnitActiveSec=60min" in timer.read_text()
    assert ("enable", "--now", timer.name) in state["calls"]
    assert service.service_status(cfg)["enabled"] is True
    again = service.enable_service(cfg, source)
    assert again["changed"] is False


def test_disable_removes_units_and_is_idempotent(linux):
    cfg, source, state = linux
    timer = Path(service.enable_service(cfg, source)["unit"])
    assert service.disable_service(cfg)["changed"] is True
    assert not timer.exists() and not timer.with_suffix(".service").exists()
    assert service.disable_service(cfg)["changed"] is False


def test_enable_failure_rolls_back_new_units(linux):
    cfg, source, state = linux
    state["fail"] = "enable"
    with pytest.raises(AgentError, match="Could not enable"):
        service.enable_service(cfg, source)
    assert not list((Path.home() / ".config" / "systemd" / "user").glob("rundown-research-*"))


def test_unrelated_unit_is_never_overwritten_or_deleted(linux):
    cfg, source, _ = linux
    timer = systemd.unit_paths(service.service_label(cfg))[1]
    timer.parent.mkdir(parents=True)
    timer.write_text("[Timer]\nOnCalendar=daily\n")
    for operation in (lambda: service.enable_service(cfg, source), lambda: service.disable_service(cfg)):
        with pytest.raises(AgentError, match="unrelated"):
            operation()
    assert timer.read_text() == "[Timer]\nOnCalendar=daily\n"


def test_changed_settings_require_disable(linux, monkeypatch):
    cfg, source, _ = linux
    service.enable_service(cfg, source)
    monkeypatch.setenv("PATH", "/different/bin")
    with pytest.raises(AgentError, match="differ"):
        service.enable_service(cfg, source)


def test_quote_escapes_systemd_specifiers():
    assert systemd._quote('a b"%$\\') == '"a b\\"%%$$\\\\"'


def test_xdg_config_home_is_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert systemd.unit_paths("com.rundown.research.abc")[1] == tmp_path / "xdg" / "systemd" / "user" / "rundown-research-abc.timer"
