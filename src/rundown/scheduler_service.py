"""Per-catalog user LaunchAgent management; never invokes a shell."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from .agent_io import AgentError
from .config import AppConfig


def service_label(config: AppConfig) -> str:
    key = hashlib.sha256(str(config.database_path.resolve()).encode()).hexdigest()[:16]
    return f"com.rundown.research.{key}"


def _platform() -> None:
    if sys.platform != "darwin":
        raise AgentError("unsupported_platform", "Automatic installation supports macOS. Use `rd schedule run --config PATH --json` with your external scheduler.", 2)


def _plist_path(config: AppConfig) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{service_label(config)}.plist"


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True,
                              check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise AgentError("service_unavailable", "launchctl did not respond within 30 seconds.") from exc


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _registered(label: str) -> bool:
    if _launchctl("print", f"{_domain()}/{label}").returncode == 0:
        return True
    domain = _launchctl("print", _domain())
    if domain.returncode:
        raise AgentError("service_unavailable", f"Cannot access the user launchd domain: {domain.stderr.strip()}")
    return False


def _owned(path: Path, label: str) -> dict:
    if path.is_symlink():
        raise AgentError("service_conflict", f"Refusing to modify a symlink: {path}")
    try:
        with path.open("rb") as stream:
            value = plistlib.load(stream)
    except (ValueError, plistlib.InvalidFileException) as exc:
        raise AgentError("service_conflict", f"Unrecognized LaunchAgent: {path}") from exc
    args = value.get("ProgramArguments") if isinstance(value, dict) else None
    if not (isinstance(value, dict) and value.get("Label") == label
            and isinstance(args, list) and len(args) == 8
            and args[1:6] == ["-m", "rundown.cli", "schedule", "run", "--config"]
            and isinstance(args[6], str) and Path(args[6]).is_absolute()
            and args[7] == "--json"):
        raise AgentError("service_conflict", f"Refusing to modify an unrelated LaunchAgent: {path}")
    return value


def launch_agent(config: AppConfig, config_path: Path) -> dict:
    """Keep the virtualenv interpreter path: resolving its symlink loses the venv."""
    path_entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
                    if entry and Path(entry).is_absolute()]
    for entry in ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        if entry not in path_entries:
            path_entries.append(entry)
    label = service_label(config)
    return {
        "Label": label,
        "ProgramArguments": [os.path.abspath(sys.executable), "-m", "rundown.cli", "schedule", "run", "--config", str(config_path.resolve()), "--json"],
        "WorkingDirectory": str(config.root.resolve()),
        "EnvironmentVariables": {"PATH": os.pathsep.join(path_entries)},
        "StartInterval": config.scheduler.interval_minutes * 60,
        "RunAtLoad": True,
        "ExitTimeOut": 30,
        "StandardOutPath": str(config.logs_root / f"{label}.stdout.log"),
        "StandardErrorPath": str(config.logs_root / f"{label}.stderr.log"),
    }


def service_status(config: AppConfig) -> dict:
    if sys.platform != "darwin":
        return {"supported": False, "enabled": False, "message": "Use `rd schedule run --config PATH --json` with your external scheduler."}
    path = _plist_path(config)
    if path.exists() or path.is_symlink():
        _owned(path, service_label(config))
    return {"supported": True, "enabled": _registered(service_label(config)),
            "installed": path.exists(), "label": service_label(config), "plist": str(path)}


def enable_service(config: AppConfig, config_path: Path | None = None) -> dict:
    _platform()
    source = (config_path or Path("config/rundown.toml")).resolve()
    if not source.is_file():
        raise AgentError("invalid_config", f"Scheduler needs a saved configuration file: {source}. Pass --config PATH.", 2)
    expected = launch_agent(config, source)
    label = service_label(config)
    path = _plist_path(config)
    exists = path.exists() or path.is_symlink()
    if exists and _owned(path, label) != expected:
        raise AgentError("service_conflict", "Existing scheduler settings differ. Disable the scheduler before enabling the new settings.")
    registered = _registered(label)
    if registered:
        if not exists:
            raise AgentError("service_conflict", "A service with this label is loaded without its owned plist; refusing to replace it.")
        return {"enabled": True, "changed": False, "label": label, "plist": str(path)}
    config.logs_root.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        if not exists:
            with path.open("xb") as stream:
                created = True
                plistlib.dump(expected, stream)
        result = _launchctl("bootstrap", _domain(), str(path))
        if result.returncode:
            raise AgentError("service_failed", f"Could not enable scheduler: {result.stderr.strip()}")
    except (OSError, AgentError):
        if created:
            path.unlink(missing_ok=True)
        raise
    return {"enabled": True, "changed": True, "label": label, "plist": str(path)}


def disable_service(config: AppConfig) -> dict:
    _platform()
    path = _plist_path(config)
    label = service_label(config)
    exists = path.exists() or path.is_symlink()
    if exists:
        _owned(path, label)
    registered = _registered(label)
    if registered:
        if not exists:
            raise AgentError("service_conflict", "Cannot verify ownership of the loaded service without its plist.")
        result = _launchctl("bootout", f"{_domain()}/{label}")
        if result.returncode:
            raise AgentError("service_failed", f"Could not disable scheduler: {result.stderr.strip()}")
    if exists:
        path.unlink()
    return {"enabled": False, "changed": exists or registered, "label": label, "plist": str(path)}
