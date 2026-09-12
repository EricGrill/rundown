from __future__ import annotations

from pathlib import Path
import subprocess

from . import db
from .config import AppConfig


def clone_repo(config: AppConfig, conn, full_name: str) -> tuple[str, str]:
    row = db.get_repo(conn, full_name)
    if row is None:
        raise ValueError(f"Unknown repository: {full_name}")

    configured_path = Path(row["local_path"]) if row["local_path"] else None
    if configured_path is not None and configured_path.exists():
        return "already_cloned", f"{full_name} is already cloned at {configured_path}."

    target = config.repo_root / row["owner"] / row["repo"]
    if (target / ".git").exists():
        db.update_repo(
            conn,
            full_name,
            local_path=str(target),
            status="cloned",
            last_clone_sync=db.now_utc(),
        )
        return "already_cloned", f"Found existing clone for {full_name} at {target}."

    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["gh", "repo", "clone", full_name, str(target)],
        text=True,
        capture_output=True,
    )
    message = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        log_path = log_failure(
            config.logs_root / "execution",
            full_name,
            "clone",
            message or "Clone failed without output.",
        )
        return "failed", f"Clone failed for {full_name}: {message}\nLog: {log_path}"

    db.update_repo(
        conn,
        full_name,
        local_path=str(target),
        status="cloned",
        last_clone_sync=db.now_utc(),
    )
    return "cloned", message or f"Cloned {full_name} to {target}."


def clone_missing(config: AppConfig, conn) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT * FROM repos WHERE (local_path IS NULL OR local_path = '') AND archived = 0 ORDER BY full_name"
    ).fetchall()
    cloned = 0
    failed = 0
    for row in rows:
        status, _ = clone_repo(config, conn, row["full_name"])
        if status in {"cloned", "already_cloned"}:
            cloned += 1
        else:
            failed += 1
    return cloned, failed


def update_repos(config: AppConfig, conn) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT * FROM repos WHERE local_path IS NOT NULL AND local_path != '' ORDER BY full_name"
    ).fetchall()
    updated = 0
    failed = 0
    for row in rows:
        local_path = Path(row["local_path"])
        if not local_path.exists():
            failed += 1
            log_failure(config.logs_root / "execution", row["full_name"], "update", "Local path is missing")
            continue
        result = subprocess.run(
            ["git", "-C", str(local_path), "pull", "--ff-only"],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            db.update_repo(conn, row["full_name"], status="updated", last_clone_sync=db.now_utc())
            updated += 1
        else:
            failed += 1
            log_failure(config.logs_root / "execution", row["full_name"], "update", result.stderr or result.stdout)
    return updated, failed


def log_failure(log_root: Path, full_name: str, operation: str, message: str) -> Path:
    log_root.mkdir(parents=True, exist_ok=True)
    safe_name = full_name.replace("/", "__")
    path = log_root / f"{safe_name}-{operation}.log"
    path.write_text(message, encoding="utf-8")
    return path
