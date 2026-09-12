import json

from rundown import history
from rundown.cards import CardRecord


def _row(summary, sections=None, provenance=None, timestamp="2026-09-12T12:00:00+00:00"):
    return {
        "summary": summary,
        "card_json": CardRecord(sections=sections or {}).to_json() if sections is not None else None,
        "provenance_json": json.dumps(provenance) if provenance is not None else None,
        "timestamp": timestamp,
    }


def test_history_formats_provenance_and_section_changes():
    older = _row("old", {"what_it_is": "Old", "risks": "A risk"})
    newer = _row(
        "new",
        {"what_it_is": "New", "hook": "A hook"},
        {
            "provider": "codex",
            "generated_at": "2026-09-12T12:00:00+00:00",
            "git_commit": "1234567890abcdef",
            "working_tree_dirty": True,
            "prompt_version": "3",
            "schema_version": 1,
            "context_files": [
                {
                    "path": "README.md",
                    "sha256": "abcdef1234567890",
                    "captured_chars": 2048,
                    "truncated": False,
                },
                {
                    "path": "pyproject.toml",
                    "sha256": "123456abcdef7890",
                    "captured_chars": 12000,
                    "truncated": True,
                },
            ],
        },
    )

    output = history.format_research_history([newer, older])

    assert "Provider: codex" in output
    assert "Repository commit: 1234567890ab" in output
    assert "Working tree: dirty; captured file hashes may differ from the commit" in output
    assert "Prompt version: 3" in output
    assert "Card schema version: 1" in output
    assert "README.md (sha256 abcdef123456…, 2048 chars, complete)" in output
    assert "pyproject.toml (sha256 123456abcdef…, 12000 chars, truncated)" in output
    assert "Added sections: Hook" in output
    assert "Updated sections: What This Is" in output
    assert "Removed sections: Limitations and Risks" in output
    assert "--- previous/What This Is" in output
    assert "+New" in output
    assert "-Old" in output
    assert "not independently verified" in output


def test_history_labels_legacy_unknowns_explicitly():
    output = history.format_research_history(
        [_row("free-form newest"), _row("free-form older")]
    )

    assert "Provenance: unknown (legacy research)." in output
    assert "Changes: unknown for legacy unstructured research." in output
