from __future__ import annotations

import json
import shutil
import subprocess
from typing import Iterable

from .db import RepoInput


class GithubCliError(RuntimeError):
    pass


def ensure_gh_authenticated() -> None:
    if shutil.which("gh") is None:
        raise GithubCliError("GitHub CLI `gh` is not installed or not on PATH.")
    result = subprocess.run(["gh", "auth", "status"], text=True, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "gh auth status failed"
        raise GithubCliError(f"GitHub CLI is not authenticated: {message}")


def fetch_starred(include_private: bool = False) -> list[RepoInput]:
    ensure_gh_authenticated()
    command = [
        "gh",
        "api",
        "--paginate",
        "/user/starred",
        "--header",
        "Accept: application/vnd.github.star+json",
        "--jq",
        (
            ".[] | {starred_at, full_name: .repo.full_name, html_url: .repo.html_url, "
            "description: .repo.description, language: .repo.language, "
            "stargazers_count: .repo.stargazers_count, forks_count: .repo.forks_count, "
            "open_issues_count: .repo.open_issues_count, pushed_at: .repo.pushed_at, "
            "archived: .repo.archived, private: .repo.private}"
        ),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise GithubCliError(f"Unable to fetch starred repositories: {message}")
    return list(
        _parse_star_output(result.stdout.splitlines(), include_private=include_private)
    )


def _parse_star_output(
    lines: Iterable[str], *, include_private: bool = False
) -> Iterable[RepoInput]:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("private") and not include_private:
            continue
        full_name = str(payload["full_name"])
        owner, repo = full_name.split("/", 1)
        yield RepoInput(
            full_name=full_name,
            owner=owner,
            repo=repo,
            url=str(payload["html_url"]),
            description=payload.get("description"),
            language=payload.get("language"),
            stars=payload.get("stargazers_count"),
            forks=payload.get("forks_count"),
            open_issues=payload.get("open_issues_count"),
            last_pushed=payload.get("pushed_at"),
            starred_at=payload.get("starred_at"),
            archived=bool(payload.get("archived")),
        )
