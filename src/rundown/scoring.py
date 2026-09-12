from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from . import db
from .config import AppConfig


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def score_repo(config: AppConfig, row: sqlite3.Row, execution_success: bool = False) -> tuple[int, str, int]:
    score = 0
    reasons: list[str] = []

    language = row["language"]
    if language and language in config.scoring.preferred_languages:
        score += 15
        reasons.append(f"Preferred language/runtime match: {language} (+15)")

    pushed_at = _parse_date(row["last_pushed"])
    if pushed_at:
        age_days = (datetime.now(timezone.utc) - pushed_at).days
        if age_days <= 180:
            score += 15
            reasons.append("Recently pushed within 180 days (+15)")
        elif age_days <= 730:
            score += 8
            reasons.append("Some upstream activity within two years (+8)")

    stars = int(row["stars"] or 0)
    if stars >= 5000:
        score += 10
        reasons.append("Strong maturity signal from stars (+10)")
    elif stars >= 500:
        score += 6
        reasons.append("Moderate maturity signal from stars (+6)")

    if row["last_research_sync"]:
        score += 10
        reasons.append("Research pass complete (+10)")

    if execution_success:
        score += 15
        reasons.append("Execution succeeded (+15)")

    tags_text = " ".join(str(row[key] or "") for key in ["tags", "notes", "description"])
    project_hits = [project for project in config.scoring.active_projects if project.lower() in tags_text.lower()]
    if project_hits:
        score += 30
        reasons.append(f"Project match: {', '.join(project_hits)} (+30)")

    decision = row["decision"]
    if decision in {"useful", "watch", "fork", "integrate"} or row["status"] in {"useful", "watch", "fork", "integrate"}:
        score += 5
        reasons.append("Positive manual decision/status (+5)")

    score = min(100, max(0, score))
    decay = calculate_decay(row, score)
    if not reasons:
        reasons.append("No strong fit signals detected yet.")
    return score, "\n".join(f"- {reason}" for reason in reasons), decay


def calculate_decay(row: sqlite3.Row, relevance_score: int) -> int:
    decay = 0
    if not row["last_opened"]:
        decay += 20
    if not row["last_research_sync"]:
        decay += 25
    if relevance_score < 30:
        decay += 20
    if not row["decision"]:
        decay += 20
    pushed_at = _parse_date(row["last_pushed"])
    if pushed_at and (datetime.now(timezone.utc) - pushed_at).days > 1095:
        decay += 15
    if row["status"] in {"useful", "watch", "fork", "integrate"}:
        decay -= 25
    return min(100, max(0, decay))


def recalculate_scores(config: AppConfig, conn) -> int:
    rows = db.list_repos(conn, include_archived=True)
    for row in rows:
        score, reason, decay = score_repo(config, row, db.has_successful_execution(conn, row["id"]))
        db.update_repo(conn, row["full_name"], relevance_score=score, score_reason=reason, decay_score=decay)
        for project in config.scoring.active_projects:
            haystack = " ".join(str(row[key] or "") for key in ["tags", "notes", "description", "score_reason"]).lower()
            if project.lower() in haystack:
                db.upsert_project_mapping(conn, row["id"], project, min(100, score + 10), "Matched configured project keyword.")
    return len(rows)
