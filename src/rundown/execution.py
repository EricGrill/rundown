from __future__ import annotations

from pathlib import Path
import subprocess
import time

from . import db
from .config import AppConfig
from .wiki import append_section, ensure_wiki_page


def detect_runtime(local_path: Path) -> tuple[str, list[str]]:
    checks = [
        ("docker-compose", ["docker", "compose", "up"], ["docker-compose.yml", "compose.yml"]),
        ("dockerfile", ["docker", "build", "."], ["Dockerfile"]),
        ("node", ["npm", "start"], ["package.json"]),
        ("python-project", ["python", "-m", "pip", "install", "-e", "."], ["pyproject.toml"]),
        ("python-requirements", ["python", "-m", "pip", "install", "-r", "requirements.txt"], ["requirements.txt"]),
        ("make", ["make"], ["Makefile"]),
    ]
    for runtime, command, names in checks:
        if any((local_path / name).exists() for name in names):
            return runtime, command
    return "unknown", []


CONTAINER_RUNTIMES = {"docker-compose", "dockerfile"}


def run_repo(
    config: AppConfig,
    conn,
    full_name: str,
    execute: bool = False,
    allow_non_docker: bool = False,
) -> tuple[str, str]:
    row = db.get_repo(conn, full_name)
    if row is None:
        raise ValueError(f"Unknown repository: {full_name}")
    local_path = Path(row["local_path"]) if row["local_path"] else None
    if local_path is None or not local_path.is_dir():
        raise ValueError(f"Repository is not cloned locally: {full_name}")
    runtime, command = detect_runtime(local_path)
    wiki_path = ensure_wiki_page(config.wiki_root, row)
    log_path = config.logs_root / "execution" / f"{row['owner']}__{row['repo']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not execute:
        notes = f"Detected runtime: {runtime}\nCommand: {' '.join(command) if command else 'none'}\nExecution skipped."
        log_path.write_text(notes, encoding="utf-8")
        status = "detected" if command else "unknown"
    elif not command:
        notes = "No runnable command detected. Execution skipped."
        log_path.write_text(notes, encoding="utf-8")
        status = "unknown"
    elif runtime not in CONTAINER_RUNTIMES and not allow_non_docker:
        notes = (
            f"Detected non-Docker runtime `{runtime}`. Refusing automatic execution by safety policy. "
            "Re-run with explicit non-Docker permission after reviewing the command."
        )
        log_path.write_text(notes, encoding="utf-8")
        status = "blocked"
    else:
        start = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=local_path,
            text=True,
            capture_output=True,
            timeout=config.execution.timeout_seconds,
        )
        elapsed = time.perf_counter() - start
        notes = (result.stdout + "\n" + result.stderr).strip()
        log_path.write_text(notes, encoding="utf-8")
        status = "success" if result.returncode == 0 else "failed"
        db.insert_execution_log(
            conn,
            row["id"],
            status,
            runtime,
            " ".join(command),
            str(log_path),
            notes[:500],
            startup_time=elapsed,
        )
        db.update_repo(conn, full_name, last_execution_sync=db.now_utc(), status="broken" if status == "failed" else row["status"])
        append_section(wiki_path, "Execution Results", f"Status: {status}\nRuntime: {runtime}\nLog: {log_path}")
        return status, notes

    db.insert_execution_log(conn, row["id"], status, runtime, " ".join(command), str(log_path), notes)
    if status in {"success", "failed"}:
        db.update_repo(conn, full_name, last_execution_sync=db.now_utc())
    append_section(wiki_path, "Execution Results", f"Status: {status}\nRuntime: {runtime}\nLog: {log_path}")
    return status, notes
