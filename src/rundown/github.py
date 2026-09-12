"""GitHub CLI integration for Rundown."""

import json
import re
import subprocess
from datetime import datetime
from typing import Optional

from .models import RepoMetadata


class GitHubError(Exception):
    """Error communicating with GitHub via gh CLI."""
    pass


def _run_gh(*args: str, check: bool = True) -> str:
    """Run a gh CLI command and return stdout."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise GitHubError(f"gh command failed: {e.stderr}") from e
    except FileNotFoundError:
        raise GitHubError("gh CLI not found. Install from https://cli.github.com/")


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime from GitHub API."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_gh_auth() -> bool:
    """Check if gh CLI is authenticated."""
    try:
        _run_gh("auth", "status")
        return True
    except GitHubError:
        return False


def parse_repo_identifier(identifier: str) -> tuple[str, str]:
    """Parse owner/repo from various formats.
    
    Accepts:
    - owner/repo
    - https://github.com/owner/repo
    - github.com/owner/repo
    - git@github.com:owner/repo.git
    """
    identifier = identifier.strip()
    
    if identifier.startswith("git@github.com:"):
        identifier = identifier[15:]
        if identifier.endswith(".git"):
            identifier = identifier[:-4]
    elif "github.com" in identifier:
        match = re.search(r"github\.com[/:]([^/]+)/([^/\s]+)", identifier)
        if match:
            owner, name = match.groups()
            if name.endswith(".git"):
                name = name[:-4]
            return owner, name
    
    if "/" in identifier:
        parts = identifier.split("/")
        if len(parts) >= 2:
            owner = parts[-2]
            name = parts[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return owner, name
    
    raise ValueError(f"Cannot parse repository identifier: {identifier}")


def fetch_repo_metadata(owner: str, name: str) -> RepoMetadata:
    """Fetch repository metadata via gh CLI."""
    full_name = f"{owner}/{name}"
    
    output = _run_gh(
        "repo", "view", full_name, "--json",
        "name,owner,description,stargazerCount,forkCount,pushedAt,createdAt,"
        "primaryLanguage,licenseInfo,repositoryTopics,isArchived,homepageUrl,"
        "defaultBranchRef,issues"
    )
    
    data = json.loads(output)
    
    topics = []
    if data.get("repositoryTopics"):
        for topic in data["repositoryTopics"]:
            if isinstance(topic, dict) and "name" in topic:
                topics.append(topic["name"])
            elif isinstance(topic, str):
                topics.append(topic)
    
    license_name = None
    if data.get("licenseInfo"):
        license_name = data["licenseInfo"].get("name") or data["licenseInfo"].get("spdxId")
    
    language = None
    if data.get("primaryLanguage"):
        language = data["primaryLanguage"].get("name")
    
    default_branch = "main"
    if data.get("defaultBranchRef"):
        default_branch = data["defaultBranchRef"].get("name", "main")
    
    open_issues = 0
    if data.get("issues"):
        open_issues = data["issues"].get("totalCount", 0)
    
    has_readme, readme_length = _check_readme(owner, name, default_branch)
    
    return RepoMetadata(
        owner=owner,
        name=name,
        full_name=full_name,
        description=data.get("description"),
        stars=data.get("stargazerCount", 0),
        forks=data.get("forkCount", 0),
        open_issues=open_issues,
        pushed_at=_parse_datetime(data.get("pushedAt")),
        created_at=_parse_datetime(data.get("createdAt")),
        language=language,
        license=license_name,
        topics=topics,
        archived=data.get("isArchived", False),
        homepage=data.get("homepageUrl"),
        default_branch=default_branch,
        has_readme=has_readme,
        readme_length=readme_length,
    )


def _check_readme(owner: str, name: str, default_branch: str) -> tuple[bool, int]:
    """Check if repo has a README and get its approximate length."""
    try:
        output = _run_gh(
            "api", f"repos/{owner}/{name}/readme",
            "--jq", ".size"
        )
        size = int(output.strip())
        return True, size
    except (GitHubError, ValueError):
        return False, 0


def fetch_starred_repos(limit: int = 500) -> list[tuple[RepoMetadata, datetime | None]]:
    """Fetch user's starred repositories.
    
    Returns list of (RepoMetadata, starred_at) tuples.
    """
    output = _run_gh(
        "api", "user/starred",
        "--paginate",
        "-H", "Accept: application/vnd.github.star+json",
        "--jq", ".[].repo | {nameWithOwner,description,stargazerCount,forkCount,"
                "pushedAt,createdAt,primaryLanguage,licenseInfo,repositoryTopics,"
                "isArchived,homepageUrl,defaultBranch,openIssuesCount}",
    )
    
    repos = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        
        full_name = data.get("nameWithOwner", "")
        if "/" not in full_name:
            continue
        
        owner, name = full_name.split("/", 1)
        
        topics = []
        if data.get("repositoryTopics"):
            topic_data = data["repositoryTopics"]
            if isinstance(topic_data, dict) and "nodes" in topic_data:
                for node in topic_data["nodes"]:
                    if isinstance(node, dict) and "topic" in node:
                        topics.append(node["topic"].get("name", ""))
            elif isinstance(topic_data, list):
                for t in topic_data:
                    if isinstance(t, str):
                        topics.append(t)
                    elif isinstance(t, dict):
                        topics.append(t.get("name", ""))
        
        license_name = None
        if data.get("licenseInfo"):
            license_name = data["licenseInfo"].get("name") or data["licenseInfo"].get("spdxId")
        
        language = None
        if data.get("primaryLanguage"):
            language = data["primaryLanguage"].get("name")
        
        default_branch = data.get("defaultBranch") or "main"
        
        meta = RepoMetadata(
            owner=owner,
            name=name,
            full_name=full_name,
            description=data.get("description"),
            stars=data.get("stargazerCount", 0),
            forks=data.get("forkCount", 0),
            open_issues=data.get("openIssuesCount", 0),
            pushed_at=_parse_datetime(data.get("pushedAt")),
            created_at=_parse_datetime(data.get("createdAt")),
            language=language,
            license=license_name,
            topics=topics,
            archived=data.get("isArchived", False),
            homepage=data.get("homepageUrl"),
            default_branch=default_branch,
            has_readme=True,
            readme_length=0,
        )
        
        repos.append((meta, None))
        
        if len(repos) >= limit:
            break
    
    return repos
