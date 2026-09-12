"""Local catalog filtering and sorting primitives."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


RESEARCH_FILTERS = (
    "all",
    "researched",
    "unresearched",
    "stale",
    "shortlisted",
    "presentation_ready",
)
SORTS = ("starred_at", "relevance", "stars", "research_date")


@dataclass(frozen=True)
class CatalogView:
    query: str = ""
    category: str | None = None
    research_filter: str = "all"
    sort: str = "starred_at"
    stale_days: int = 30
    name: str | None = None

    def __post_init__(self) -> None:
        if self.research_filter not in RESEARCH_FILTERS:
            raise ValueError(f"unknown research filter: {self.research_filter}")
        if self.sort not in SORTS:
            raise ValueError(f"unknown catalog sort: {self.sort}")
        if isinstance(self.stale_days, bool) or not isinstance(self.stale_days, int):
            raise ValueError("stale_days must be an integer")
        if not 1 <= self.stale_days <= 3650:
            raise ValueError("stale_days must be between 1 and 3650")
        if self.name is not None and not self.name.strip():
            raise ValueError("named view name must not be blank")


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    source = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(source)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_research_stale(
    repo: Mapping[str, Any],
    research: Mapping[str, Any] | None,
    *,
    stale_days: int,
    now: datetime,
) -> bool:
    """Return whether saved research predates the repo or the age threshold.

    Unresearched repositories are deliberately not stale; they have their own filter.
    """
    if research is None:
        return False
    researched_at = _timestamp(_get(research, "timestamp"))
    if researched_at is None:
        return True
    pushed_at = _timestamp(_get(repo, "last_pushed"))
    return bool(
        (pushed_at is not None and pushed_at > researched_at)
        or now - researched_at > timedelta(days=stale_days)
    )


def filter_sort_repos(
    rows: Sequence[Mapping[str, Any]],
    research_by_repo: Mapping[int, Mapping[str, Any]],
    view: CatalogView,
    *,
    now: datetime | None = None,
) -> list[Mapping[str, Any]]:
    """Apply a saved/local catalog view without network or provider work."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    query = view.query.strip().casefold()

    def included(repo: Mapping[str, Any]) -> bool:
        repo_id = int(_get(repo, "id", 0))
        research = research_by_repo.get(repo_id)
        if query:
            searchable = " ".join(
                str(_get(repo, field, ""))
                for field in ("full_name", "description", "language", "category", "tags")
            ).casefold()
            if query not in searchable:
                return False
        if view.category and _get(repo, "category") != view.category:
            return False
        match view.research_filter:
            case "researched":
                return research is not None
            case "unresearched":
                return research is None
            case "stale":
                return is_research_stale(
                    repo, research, stale_days=view.stale_days, now=current
                )
            case "shortlisted":
                return _get(repo, "decision") == "shortlist"
            case "presentation_ready":
                return _get(repo, "decision") == "present"
        return True

    filtered = [repo for repo in rows if included(repo)]

    def date_key(value: Any) -> float:
        parsed = _timestamp(value)
        return parsed.timestamp() if parsed else float("-inf")

    def primary(repo: Mapping[str, Any]) -> float:
        if view.sort == "starred_at":
            return date_key(_get(repo, "starred_at"))
        if view.sort == "relevance":
            return float(_get(repo, "relevance_score", 0))
        if view.sort == "stars":
            return float(_get(repo, "stars", 0))
        research = research_by_repo.get(int(_get(repo, "id", 0)))
        return date_key(_get(research, "timestamp")) if research else float("-inf")

    return sorted(
        filtered,
        key=lambda repo: (-primary(repo), str(_get(repo, "full_name", "")).casefold()),
    )
