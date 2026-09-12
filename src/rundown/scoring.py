"""Scoring system for Rundown repos."""

import math
from datetime import datetime, timezone
from typing import Optional

from .config import ScoreWeights
from .models import Repo


def calculate_score(repo: Repo, weights: ScoreWeights) -> tuple[float, str]:
    """Calculate present_score for a repo with explanation.
    
    Returns (score, reason) tuple where score is 0-100.
    """
    components: list[tuple[str, float, str]] = []
    
    freshness_score = _calc_freshness(repo.pushed_at, weights.freshness_half_life_days)
    freshness_contrib = freshness_score * weights.freshness / 100
    if freshness_score > 0:
        days_ago = _days_since(repo.pushed_at) if repo.pushed_at else None
        if days_ago is not None:
            components.append((
                "freshness",
                freshness_contrib,
                f"pushed {int(days_ago)}d ago"
            ))
    
    desc_score = _calc_description_quality(repo.description)
    desc_contrib = desc_score * weights.description_quality / 100
    if desc_score > 0:
        components.append((
            "description",
            desc_contrib,
            f"{len(repo.description or '')} chars"
        ))
    
    readme_score = _calc_readme_signal(repo.has_readme, repo.readme_length)
    readme_contrib = readme_score * weights.readme_signal / 100
    if readme_score > 0:
        size_kb = repo.readme_length / 1024
        components.append((
            "readme",
            readme_contrib,
            f"{size_kb:.1f}KB" if repo.readme_length > 0 else "present"
        ))
    
    stars_score = _calc_stars_normalized(repo.stars)
    stars_contrib = stars_score * weights.stars_normalized / 100
    if stars_score > 0:
        components.append((
            "stars",
            stars_contrib,
            f"{repo.stars:,}★"
        ))
    
    topics_score = _calc_topics_score(repo.topics)
    topics_contrib = topics_score * weights.topics_count / 100
    if topics_score > 0:
        components.append((
            "topics",
            topics_contrib,
            f"{len(repo.topics)} tags"
        ))
    
    if repo.license:
        license_contrib = weights.has_license
        components.append((
            "license",
            license_contrib,
            repo.license[:20]
        ))
    else:
        license_contrib = 0
    
    issues_score = _calc_issues_ratio(repo.open_issues, repo.stars)
    issues_contrib = issues_score * weights.low_issues_ratio / 100
    if issues_score > 50:
        components.append((
            "issues",
            issues_contrib,
            f"{repo.open_issues} open"
        ))
    
    boost_contrib = 0.0
    if repo.manual_boost != 0:
        boost_contrib = repo.manual_boost * weights.manual_boost_multiplier
        sign = "+" if repo.manual_boost > 0 else ""
        components.append((
            "boost",
            boost_contrib,
            f"{sign}{repo.manual_boost}"
        ))
    
    archived_contrib = 0.0
    if repo.archived:
        archived_contrib = weights.archived_penalty
        components.append((
            "archived",
            archived_contrib,
            "⚠️ archived"
        ))
    
    raw_score = (
        freshness_contrib +
        desc_contrib +
        readme_contrib +
        stars_contrib +
        topics_contrib +
        license_contrib +
        issues_contrib +
        boost_contrib +
        archived_contrib
    )
    
    final_score = max(0, min(100, raw_score))
    
    reason_parts = []
    sorted_components = sorted(components, key=lambda x: abs(x[1]), reverse=True)
    for name, contrib, detail in sorted_components[:5]:
        if contrib != 0:
            sign = "+" if contrib > 0 else ""
            reason_parts.append(f"{name}({sign}{contrib:.0f}): {detail}")
    
    reason = " | ".join(reason_parts) if reason_parts else "no scoring factors"
    
    return final_score, reason


def _days_since(dt: Optional[datetime]) -> Optional[float]:
    """Calculate days since a datetime."""
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return delta.total_seconds() / 86400


def _calc_freshness(pushed_at: Optional[datetime], half_life_days: int) -> float:
    """Calculate freshness score (0-100) with exponential decay."""
    days = _days_since(pushed_at)
    if days is None:
        return 0
    decay = math.exp(-0.693 * days / half_life_days)
    return decay * 100


def _calc_description_quality(description: Optional[str]) -> float:
    """Calculate description quality score (0-100)."""
    if not description:
        return 0
    length = len(description.strip())
    if length < 10:
        return 20
    elif length < 50:
        return 50
    elif length < 100:
        return 80
    else:
        return 100


def _calc_readme_signal(has_readme: bool, readme_length: int) -> float:
    """Calculate README signal score (0-100)."""
    if not has_readme:
        return 0
    if readme_length == 0:
        return 30
    elif readme_length < 500:
        return 50
    elif readme_length < 2000:
        return 80
    else:
        return 100


def _calc_stars_normalized(stars: int) -> float:
    """Calculate normalized stars score (0-100) using log scale."""
    if stars <= 0:
        return 0
    log_stars = math.log10(stars + 1)
    return min(100, log_stars * 25)


def _calc_topics_score(topics: list[str]) -> float:
    """Calculate topics score (0-100)."""
    count = len(topics)
    if count == 0:
        return 0
    elif count < 3:
        return 50
    elif count < 6:
        return 80
    else:
        return 100


def _calc_issues_ratio(open_issues: int, stars: int) -> float:
    """Calculate issues ratio score (0-100). Lower ratio = better score."""
    if stars == 0:
        return 50
    ratio = open_issues / (stars + 1)
    if ratio > 0.5:
        return 0
    elif ratio > 0.2:
        return 50
    elif ratio > 0.05:
        return 80
    else:
        return 100
