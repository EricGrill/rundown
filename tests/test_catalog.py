from datetime import datetime, timezone

import pytest

from rundown.catalog import CatalogView, filter_sort_repos


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def repos():
    return [
        {
            "id": 1,
            "full_name": "acme/fresh",
            "description": "Terminal developer tool",
            "language": "Python",
            "category": "Developer Tools",
            "tags": "terminal",
            "decision": "present",
            "last_pushed": "2026-09-01T00:00:00+00:00",
            "starred_at": "2026-09-10T00:00:00+00:00",
            "stars": 50,
            "relevance_score": 80,
        },
        {
            "id": 2,
            "full_name": "acme/stale",
            "description": "Old research",
            "language": "Rust",
            "category": "Infrastructure",
            "decision": "shortlist",
            "last_pushed": "2026-09-11T00:00:00+00:00",
            "starred_at": "2026-08-01T00:00:00+00:00",
            "stars": 500,
            "relevance_score": 30,
        },
        {
            "id": 3,
            "full_name": "acme/unresearched",
            "description": "No report yet",
            "language": "Go",
            "category": "Developer Tools",
            "decision": None,
            "starred_at": None,
            "stars": None,
            "relevance_score": 90,
        },
    ]


def research():
    return {
        1: {"timestamp": "2026-09-10T00:00:00+00:00"},
        2: {"timestamp": "2026-08-20T00:00:00+00:00"},
    }


@pytest.mark.parametrize(
    "research_filter, expected",
    [
        ("researched", ["acme/fresh", "acme/stale"]),
        ("unresearched", ["acme/unresearched"]),
        ("stale", ["acme/stale"]),
        ("shortlisted", ["acme/stale"]),
        ("presentation_ready", ["acme/fresh"]),
    ],
)
def test_catalog_filters(research_filter, expected):
    result = filter_sort_repos(
        repos(), research(), CatalogView(research_filter=research_filter), now=NOW
    )
    assert [row["full_name"] for row in result] == expected


def test_stale_excludes_unresearched_and_detects_age_or_new_push():
    reports = research()
    reports[1] = {"timestamp": "2026-09-01T00:00:00+00:00"}
    result = filter_sort_repos(
        repos(), reports, CatalogView(research_filter="stale", stale_days=5), now=NOW
    )
    assert [row["id"] for row in result] == [1, 2]
    assert 3 not in [row["id"] for row in result]


def test_query_category_and_each_sort_are_deterministic():
    assert [row["id"] for row in filter_sort_repos(
        repos(), research(), CatalogView(query="terminal", category="Developer Tools"), now=NOW
    )] == [1]
    assert [row["id"] for row in filter_sort_repos(
        repos(), research(), CatalogView(sort="stars"), now=NOW
    )] == [2, 1, 3]
    assert [row["id"] for row in filter_sort_repos(
        repos(), research(), CatalogView(sort="relevance"), now=NOW
    )] == [3, 1, 2]
    assert [row["id"] for row in filter_sort_repos(
        repos(), research(), CatalogView(sort="research_date"), now=NOW
    )] == [1, 2, 3]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"research_filter": "broken"},
        {"sort": "popular"},
        {"stale_days": 0},
        {"stale_days": True},
        {"name": "  "},
    ],
)
def test_catalog_view_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        CatalogView(**kwargs)
