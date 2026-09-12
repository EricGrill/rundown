import json
from types import SimpleNamespace

from rundown import github
from rundown.github import _parse_star_output


def test_parse_star_output_includes_description_and_starred_date():
    payload = {
        "starred_at": "2026-07-20T14:30:00Z",
        "full_name": "owner/project",
        "html_url": "https://github.com/owner/project",
        "description": "A useful project.",
        "language": "Python",
        "stargazers_count": 42,
        "forks_count": 3,
        "open_issues_count": 1,
        "pushed_at": "2026-07-19T00:00:00Z",
        "archived": False,
    }

    repos = list(_parse_star_output([json.dumps(payload)]))

    assert len(repos) == 1
    assert repos[0].description == "A useful project."
    assert repos[0].starred_at == "2026-07-20T14:30:00Z"


def test_parse_star_output_excludes_private_repositories_by_default():
    payload = {
        "starred_at": "2026-07-20T14:30:00Z",
        "full_name": "owner/private-project",
        "html_url": "https://github.com/owner/private-project",
        "private": True,
    }

    assert list(_parse_star_output([json.dumps(payload)])) == []


def test_parse_star_output_can_include_private_repositories():
    payload = {
        "starred_at": "2026-07-20T14:30:00Z",
        "full_name": "owner/private-project",
        "html_url": "https://github.com/owner/private-project",
        "private": True,
    }

    repos = list(
        _parse_star_output([json.dumps(payload)], include_private=True)
    )

    assert [repo.full_name for repo in repos] == ["owner/private-project"]


def test_fetch_starred_requests_privacy_and_filters_private_repositories(
    monkeypatch,
):
    public = {
        "full_name": "owner/public-project",
        "html_url": "https://github.com/owner/public-project",
        "private": False,
    }
    private = {
        "full_name": "owner/private-project",
        "html_url": "https://github.com/owner/private-project",
        "private": True,
    }
    commands = []

    monkeypatch.setattr(github, "ensure_gh_authenticated", lambda: None)

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=f"{json.dumps(public)}\n{json.dumps(private)}\n",
            stderr="",
        )

    monkeypatch.setattr(github.subprocess, "run", run)

    repos = github.fetch_starred()

    assert [repo.full_name for repo in repos] == ["owner/public-project"]
    jq = commands[0][commands[0].index("--jq") + 1]
    assert "private: .repo.private" in jq
