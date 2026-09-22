"""One bounded, restartable research pass for a system scheduler."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from threading import Event
from typing import Any, Iterator

from . import categories, db, github, research_workflow
from .agent_io import AgentError, read_catalog
from .config import AppConfig
from .processes import OperationCancelled, check_cancelled


def _state_path(config: AppConfig) -> Path:
    database = config.database_path.resolve()
    return database.with_suffix(database.suffix + ".scheduler.json")


def _read_state(config: AppConfig) -> dict[str, Any]:
    path = _state_path(config)
    if not path.exists():
        return {"version": 1, "retries": {}, "last_run": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("unsupported state format")
        retries = state.get("retries")
        if not isinstance(retries, dict) or any(
            not isinstance(name, str) or isinstance(value, bool)
            or not isinstance(value, (int, float)) or not math.isfinite(value)
            for name, value in retries.items()
        ):
            raise ValueError("invalid retry timestamps")
        if state.get("last_run") is not None and not isinstance(state["last_run"], dict):
            raise ValueError("invalid last run")
        return state
    except (ValueError, TypeError) as exc:
        raise AgentError("invalid_scheduler_state", f"Cannot read {path}: {exc}") from exc


def _save_state(config: AppConfig, state: dict[str, Any]) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _scheduler_lock(config: AppConfig) -> Iterator[bool]:
    if os.name != "posix":
        raise AgentError("unsupported_platform", "Scheduled research requires macOS or Linux.", 2)
    import fcntl

    path = _state_path(config).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _pending_names(config: AppConfig) -> list[str]:
    with read_catalog(config) as conn:
        return [row["full_name"] for row in conn.execute(
            "SELECT r.full_name FROM repos r "
            "WHERE r.starred = 1 AND COALESCE(r.archived, 0) = 0 "
            "AND COALESCE(r.status, '') != 'archived' "
            "AND NOT EXISTS (SELECT 1 FROM research_logs l WHERE l.repo_id = r.id "
            "AND l.pass_type = 'Repository Understanding' AND l.status = 'success') "
            "ORDER BY r.starred_at DESC, r.full_name COLLATE NOCASE, r.id"
        )]


def _selection(config: AppConfig, state: dict[str, Any]) -> tuple[list[str], list[str]]:
    pending = _pending_names(config)
    now = datetime.now(timezone.utc).timestamp()
    eligible = [name for name in pending if state["retries"].get(name, 0) <= now]
    # New work goes first; due retries rotate by their previous attempt time.
    eligible.sort(key=lambda name: state["retries"].get(name, 0))
    return pending, eligible


def scheduler_status(config: AppConfig) -> dict[str, Any]:
    """Read saved progress and local candidates without network or filesystem writes."""
    state = _read_state(config)
    pending, eligible = _selection(config, state)
    running = False
    lock_path = _state_path(config).with_suffix(".lock")
    if os.name == "posix" and lock_path.exists():
        import fcntl

        with lock_path.open("r") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                running = True
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    last_run = state["last_run"]
    if last_run and last_run.get("status") == "running" and not running:
        last_run = {**last_run, "status": "interrupted"}
    return {"settings": asdict(config.scheduler), "pending": len(pending),
            "eligible": len(eligible), "deferred": len(pending) - len(eligible),
            "next_batch": eligible[:config.scheduler.batch_size],
            "last_run": last_run, "running": running, "state_path": str(_state_path(config))}


def run_scheduled_research(config: AppConfig, *, dry_run: bool = False,
                           cancel_event: Event | None = None) -> dict[str, Any]:
    """Sync stars, then research a bounded batch; failures cool down across runs."""
    report: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success", "started_at": db.now_utc(),
        "selected": [], "results": [], "succeeded": 0, "failed": 0,
        "remaining": 0, "cancelled": False, "synced": None,
        "batch_size": config.scheduler.batch_size,
    }
    if dry_run:
        preview = scheduler_status(config)
        report.update(selected=[{"full_name": name, "reason": "missing"}
                                for name in preview["next_batch"]],
                      remaining=preview["pending"], deferred=preview["deferred"],
                      sync_stars=config.scheduler.sync_stars)
        return report
    event = cancel_event if cancel_event is not None else Event()
    with _scheduler_lock(config) as acquired:
        if not acquired:
            report["status"] = "busy"
            return report
        state = _read_state(config)
        state["last_run"] = report
        try:
            check_cancelled(event)
            if config.scheduler.sync_stars:
                try:
                    stars = github.fetch_starred(include_private=config.github.include_private,
                                                 cancel_event=event)
                    check_cancelled(event)
                    with db.session(config.database_path) as conn:
                        db.init_db(conn)
                        for repo in stars:
                            db.upsert_repo(conn, repo)
                        db.mark_unstarred_missing(conn, {repo.full_name for repo in stars})
                        categories.classify_repos(conn)
                    report["synced"] = len(stars)
                except (KeyboardInterrupt, OperationCancelled):
                    raise
                except Exception as exc:
                    report.update(status="sync_failed", error=str(exc)[:1200])
                    return report
            pending, eligible = _selection(config, state)
            pending_set = set(pending)
            state["retries"] = {name: value for name, value in state["retries"].items()
                                if name in pending_set}
            selected = eligible[:config.scheduler.batch_size]
            report.update(selected=[{"full_name": name, "reason": "missing"} for name in selected],
                          remaining=len(pending), deferred=len(pending) - len(eligible))
            _save_state(config, state)
            if selected:
                config.ensure_directories()
            for name in selected:
                check_cancelled(event)
                # Persist before launching a provider so a killed run cannot hot-loop on it.
                state["retries"][name] = (datetime.now(timezone.utc).timestamp()
                                          + config.scheduler.retry_hours * 3600)
                report["current_repo"] = name
                report["status"] = "running"
                _save_state(config, state)
                try:
                    with db.session(config.database_path) as conn:
                        db.init_db(conn)
                        row = db.get_repo(conn, name)
                        # Recheck: another completed operation or user decision may supersede selection.
                        if (row is None or not row["starred"] or row["archived"]
                                or row["status"] == "archived"
                                or db.latest_successful_research(conn, row["id"]) is not None):
                            status, summary = "skipped", "No longer needs automatic research."
                        else:
                            def checkpoint_clone(stage: str, message: str) -> None:
                                if stage == "researching":
                                    # Do not hold SQLite's write lock during a provider call.
                                    conn.commit()

                            status, summary = research_workflow.research_repository(
                                config, conn, name, cancel_event=event, on_stage=checkpoint_clone,
                                clone_timeout=config.execution.timeout_seconds,
                            )
                    if status == "cancelled":
                        raise OperationCancelled(summary)
                except (KeyboardInterrupt, OperationCancelled):
                    state["retries"].pop(name, None)
                    report["results"].append({"full_name": name, "status": "cancelled"})
                    raise
                except Exception as exc:
                    status, summary = "failed", str(exc)
                if status in {"success", "cached", "skipped"}:
                    state["retries"].pop(name, None)
                    report["remaining"] -= 1
                    if status != "skipped":
                        report["succeeded"] += 1
                else:
                    report["failed"] += 1
                report["results"].append({"full_name": name, "status": status,
                                          "summary": summary[:1200]})
                report.pop("current_repo", None)
                _save_state(config, state)
            report["status"] = "partial_failure" if report["failed"] else "success"
        except (KeyboardInterrupt, OperationCancelled):
            event.set()
            report.update(status="cancelled", cancelled=True)
        except Exception as exc:
            report.update(status="partial_failure", error=str(exc)[:1200])
        finally:
            report.pop("current_repo", None)
            report["finished_at"] = db.now_utc()
            _save_state(config, state)
    return report
