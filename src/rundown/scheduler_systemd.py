"""Per-catalog systemd user timer management for Linux; never invokes a shell."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

from .agent_io import AgentError
from .config import AppConfig

MARKER = "# Managed by rundown:"


def unit_name(label: str) -> str:
    return label.replace("com.rundown.research.", "rundown-research-")


def _unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return root / "systemd" / "user"


def unit_paths(label: str) -> tuple[Path, Path]:
    directory = _unit_dir()
    name = unit_name(label)
    return directory / f"{name}.service", directory / f"{name}.timer"


def _quote(value: str) -> str:
    """Quote one ExecStart word so spaces, quotes, % and $ survive systemd parsing."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{escaped}"'


def _env_value(value: str) -> str:
    """Environment= honours C-style quotes and % specifiers but never expands $."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def _path(value: Path) -> str:
    """Path settings take the rest of the line literally, apart from % specifiers."""
    return str(value).replace("%", "%%")


def render_units(config: AppConfig, config_path: Path, label: str, path_value: str) -> tuple[str, str]:
    command = [os.path.abspath(sys.executable), "-m", "rundown.cli", "schedule", "run",
               "--config", str(config_path.resolve()), "--json"]
    logs = config.logs_root
    service = "\n".join([
        f"{MARKER} {label}",
        "[Unit]",
        "Description=Rundown research for starred repositories",
        "",
        "[Service]",
        "Type=oneshot",
        f"ExecStart={' '.join(_quote(word) for word in command)}",
        f"WorkingDirectory={_path(config.root.resolve())}",
        f'Environment="PATH={_env_value(path_value)}"',
        f"StandardOutput=append:{_path(logs / f'{label}.stdout.log')}",
        f"StandardError=append:{_path(logs / f'{label}.stderr.log')}",
        "TimeoutStopSec=30",
        "",
    ])
    timer = "\n".join([
        f"{MARKER} {label}",
        "[Unit]",
        "Description=Run Rundown research on a schedule",
        "",
        "[Timer]",
        "OnActiveSec=10s",
        "OnStartupSec=2min",
        f"OnUnitActiveSec={config.scheduler.interval_minutes}min",
        f"Unit={unit_name(label)}.service",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ])
    return service, timer


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("systemctl")
    if executable is None:
        raise AgentError("unsupported_platform", "systemctl was not found. Use `rd schedule run --config PATH --json` with cron.", 2)
    try:
        return subprocess.run([executable, "--user", *args], capture_output=True, text=True,
                              check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise AgentError("service_unavailable", "systemctl did not respond within 30 seconds.") from exc


def _read_owned(path: Path, label: str) -> str | None:
    if path.is_symlink():
        raise AgentError("service_conflict", f"Refusing to modify a symlink: {path}")
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    if content.splitlines()[:1] != [f"{MARKER} {label}"]:
        raise AgentError("service_conflict", f"Refusing to modify an unrelated systemd unit: {path}")
    return content


def _enabled(label: str) -> bool:
    return _systemctl("is-enabled", f"{unit_name(label)}.timer").returncode == 0


def status(label: str) -> dict:
    service_path, timer_path = unit_paths(label)
    for path in (service_path, timer_path):
        _read_owned(path, label)
    return {"supported": True, "enabled": _enabled(label),
            "installed": service_path.exists() and timer_path.exists(),
            "label": label, "unit": str(timer_path)}


def enable(config: AppConfig, config_path: Path, label: str, path_value: str) -> dict:
    expected = dict(zip(unit_paths(label), render_units(config, config_path, label, path_value)))
    existing = {path: _read_owned(path, label) for path in expected}
    if any(content is not None and content != expected[path] for path, content in existing.items()):
        raise AgentError("service_conflict", "Existing scheduler settings differ. Disable the scheduler before enabling the new settings.")
    timer_path = unit_paths(label)[1]
    if all(content is not None for content in existing.values()) and _enabled(label):
        return {"enabled": True, "changed": False, "label": label, "unit": str(timer_path)}
    config.logs_root.mkdir(parents=True, exist_ok=True)
    timer_path.parent.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for path, content in expected.items():
            if existing[path] is None:
                with path.open("x", encoding="utf-8") as stream:
                    created.append(path)
                    stream.write(content)
        for args in (("daemon-reload",), ("enable", "--now", timer_path.name)):
            result = _systemctl(*args)
            if result.returncode:
                raise AgentError("service_failed", f"Could not enable scheduler: {result.stderr.strip()}")
    except (OSError, AgentError):
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {"enabled": True, "changed": True, "label": label, "unit": str(timer_path)}


def disable(label: str) -> dict:
    paths = unit_paths(label)
    existing = [path for path in paths if _read_owned(path, label) is not None]
    timer_path = paths[1]
    enabled = _enabled(label)
    if enabled:
        if timer_path not in existing:
            raise AgentError("service_conflict", "Cannot verify ownership of the enabled timer without its unit file.")
        result = _systemctl("disable", "--now", timer_path.name)
        if result.returncode:
            raise AgentError("service_failed", f"Could not disable scheduler: {result.stderr.strip()}")
    for path in existing:
        path.unlink()
    if existing:
        _systemctl("daemon-reload")
    return {"enabled": False, "changed": bool(existing) or enabled, "label": label, "unit": str(timer_path)}
