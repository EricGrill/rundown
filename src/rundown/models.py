"""Data models for Rundown."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Status(str, Enum):
    """Repository triage status."""
    INBOX = "inbox"
    SHORTLIST = "shortlist"
    PRESENT = "present"
    HOLD = "hold"
    SKIP = "skip"


@dataclass
class RepoMetadata:
    """GitHub repository metadata fetched via gh CLI."""
    owner: str
    name: str
    full_name: str
    description: Optional[str] = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    pushed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    language: Optional[str] = None
    license: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    archived: bool = False
    homepage: Optional[str] = None
    default_branch: str = "main"
    has_readme: bool = False
    readme_length: int = 0


@dataclass
class Card:
    """Presentation card fields for a repo."""
    hook: str = ""
    who_for: str = ""
    problem: str = ""
    why_now: str = ""
    demo_path: str = ""
    flags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Repo:
    """A repository in the Rundown database."""
    id: Optional[int] = None
    full_name: str = ""
    owner: str = ""
    name: str = ""
    url: str = ""
    
    description: Optional[str] = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    pushed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    language: Optional[str] = None
    license: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    archived: bool = False
    homepage: Optional[str] = None
    default_branch: str = "main"
    has_readme: bool = False
    readme_length: int = 0
    
    status: Status = Status.INBOX
    present_score: float = 0.0
    score_reason: str = ""
    manual_boost: int = 0
    
    hook: str = ""
    who_for: str = ""
    problem: str = ""
    why_now: str = ""
    demo_path: str = ""
    flags: list[str] = field(default_factory=list)
    notes: str = ""
    
    added_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    starred_at: Optional[datetime] = None
    
    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.full_name}"
    
    @classmethod
    def from_metadata(cls, meta: RepoMetadata, starred_at: Optional[datetime] = None) -> "Repo":
        """Create a Repo from GitHub metadata."""
        now = datetime.now()
        return cls(
            full_name=meta.full_name,
            owner=meta.owner,
            name=meta.name,
            url=f"https://github.com/{meta.full_name}",
            description=meta.description,
            stars=meta.stars,
            forks=meta.forks,
            open_issues=meta.open_issues,
            pushed_at=meta.pushed_at,
            created_at=meta.created_at,
            language=meta.language,
            license=meta.license,
            topics=meta.topics,
            archived=meta.archived,
            homepage=meta.homepage,
            default_branch=meta.default_branch,
            has_readme=meta.has_readme,
            readme_length=meta.readme_length,
            added_at=now,
            updated_at=now,
            starred_at=starred_at,
        )
