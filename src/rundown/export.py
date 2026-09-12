"""Markdown export for Rundown."""

from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO
import sys

from .models import Repo, Status


def export_markdown(
    repos: list[Repo],
    output: Optional[Path] = None,
    title: str = "Rundown",
    include_scores: bool = True,
) -> str:
    """Export repos to presentation-ready Markdown.
    
    Args:
        repos: List of repos to export
        output: Optional file path to write to
        title: Document title
        include_scores: Whether to include score details
    
    Returns:
        The generated Markdown string
    """
    lines: list[str] = []
    
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    
    status_counts = {}
    for repo in repos:
        status_counts[repo.status] = status_counts.get(repo.status, 0) + 1
    
    if status_counts:
        status_parts = [f"{s.value}: {c}" for s, c in sorted(status_counts.items(), key=lambda x: x[0].value)]
        lines.append(f"**{len(repos)} repos** ({', '.join(status_parts)})")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    for repo in repos:
        lines.extend(_format_repo(repo, include_scores))
        lines.append("")
    
    content = "\n".join(lines)
    
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    
    return content


def export_to_stream(
    repos: list[Repo],
    stream: TextIO,
    title: str = "Rundown",
    include_scores: bool = True,
) -> None:
    """Export repos to a text stream."""
    content = export_markdown(repos, title=title, include_scores=include_scores)
    stream.write(content)


def _format_repo(repo: Repo, include_scores: bool = True) -> list[str]:
    """Format a single repo as Markdown."""
    lines: list[str] = []
    
    lines.append(f"## [{repo.full_name}]({repo.github_url})")
    lines.append("")
    
    if repo.hook:
        lines.append(f"**{repo.hook}**")
        lines.append("")
    elif repo.description:
        lines.append(f"*{repo.description}*")
        lines.append("")
    
    meta_parts = []
    if repo.language:
        meta_parts.append(repo.language)
    if repo.stars:
        meta_parts.append(f"⭐ {repo.stars:,}")
    if repo.license:
        meta_parts.append(f"📄 {repo.license}")
    if repo.archived:
        meta_parts.append("🗄️ Archived")
    
    if meta_parts:
        lines.append(" | ".join(meta_parts))
        lines.append("")
    
    if repo.who_for or repo.problem or repo.why_now:
        if repo.who_for:
            lines.append(f"**Who's it for:** {repo.who_for}")
        if repo.problem:
            lines.append(f"**Problem:** {repo.problem}")
        if repo.why_now:
            lines.append(f"**Why now:** {repo.why_now}")
        lines.append("")
    
    if repo.demo_path:
        lines.append(f"**Demo:** {repo.demo_path}")
        lines.append("")
    
    if repo.flags:
        lines.append(f"**Flags:** {', '.join(repo.flags)}")
        lines.append("")
    
    if repo.notes:
        lines.append(f"> {repo.notes}")
        lines.append("")
    
    if include_scores:
        score_line = f"📊 Score: **{repo.present_score:.0f}**/100"
        if repo.score_reason:
            score_line += f" — {repo.score_reason}"
        lines.append(score_line)
        lines.append("")
    
    if repo.topics:
        lines.append(f"`{' '.join(repo.topics)}`")
        lines.append("")
    
    lines.append("---")
    
    return lines


def format_summary_table(repos: list[Repo]) -> str:
    """Format repos as a summary table."""
    lines = []
    lines.append("| Repo | Score | Status | Language | Stars |")
    lines.append("|------|-------|--------|----------|-------|")
    
    for repo in repos:
        name = f"[{repo.name}]({repo.github_url})"
        score = f"{repo.present_score:.0f}"
        status = repo.status.value
        lang = repo.language or "-"
        stars = f"{repo.stars:,}" if repo.stars else "-"
        lines.append(f"| {name} | {score} | {status} | {lang} | {stars} |")
    
    return "\n".join(lines)
