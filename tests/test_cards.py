import json

import pytest

from rundown.cards import (
    REQUIRED_SECTION_IDS,
    SECTION_TITLES,
    CardRecord,
    parse_research,
    record_from_saved,
    section_preview,
)


def complete_sections(**overrides):
    values = {section_id: None for section_id in SECTION_TITLES}
    values.update({section_id: f"Content for {section_id}." for section_id in REQUIRED_SECTION_IDS})
    values.update(overrides)
    return values


def test_strict_json_requires_version_known_keys_and_core_sections():
    text = json.dumps({"schema_version": 1, "sections": complete_sections()})

    record = parse_research(text, strict=True)

    assert record.schema_version == 1
    assert record.sections["what_it_is"] == "Content for what_it_is."
    assert record.sections["sources"] == ""
    assert json.loads(record.to_json())["sections"]["sources"] is None


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"schema_version": 2, "sections": complete_sections()}, "schema_version"),
        ({"schema_version": 1, "sections": {**complete_sections(), "surprise": "no"}}, "unknown"),
        ({"schema_version": 1, "sections": complete_sections(what_it_is="")}, "nonempty"),
        ({"schema_version": 1, "sections": complete_sections(analogy=7)}, "string or null"),
    ],
)
def test_strict_json_rejects_invalid_records(payload, message):
    with pytest.raises(ValueError, match=message):
        parse_research(json.dumps(payload), strict=True)


def test_strict_json_requires_every_named_section_even_when_optional_is_null():
    sections = complete_sections()
    sections.pop("sources")

    with pytest.raises(ValueError, match="missing sections"):
        parse_research(json.dumps({"schema_version": 1, "sections": sections}), strict=True)


def test_markdown_extracts_exact_h2_sections_outside_fences_and_preserves_source():
    markdown = """Intro stays available in the full research view.

## What This Is
A useful tool.

```markdown
## Explain It Like I'm Seven
This is example text, not a real section.
```

## Explain It Like I'm Seven
A labeled box.

## Why Someone Would Use It
It saves time.

## Why It Might Matter to You
It fits the work.

## Why It May Have Caught Your Eye
Inference: it is practical.

## Unrecognized Heading
This must not become part of Interest.
"""
    record = parse_research(markdown, strict=True)

    assert record.legacy_text == markdown
    assert record.sections["analogy"] == "A labeled box."
    assert record.sections["interest"] == "Inference: it is practical."
    assert "Unrecognized" not in record.sections["interest"]
    assert record.to_markdown() == markdown


@pytest.mark.parametrize("marker", ["```", "~~~"])
def test_strict_markdown_does_not_accept_required_headings_inside_fences(marker):
    fake_sections = "\n\n".join(
        f"## {SECTION_TITLES[section_id]}\nFake content."
        for section_id in REQUIRED_SECTION_IDS
    )
    markdown = f"{marker}text\n{marker}python\n{fake_sections}\n{marker}\n"

    with pytest.raises(ValueError, match="requires nonempty sections"):
        parse_research(markdown, strict=True)


def test_non_strict_malformed_json_falls_back_to_raw_text():
    malformed = '{"schema_version": 1, "sections": [}'

    record = parse_research(malformed)

    assert record.sections == {}
    assert record.legacy_text == malformed
    assert record.to_markdown() == malformed


def test_record_from_saved_prefers_valid_json_then_falls_back_to_summary():
    card_json = CardRecord(sections={"what_it_is": "Structured"}).to_json()
    preferred = record_from_saved("## What This Is\n\nLegacy", card_json)
    fallback = record_from_saved("## What This Is\n\nLegacy", "not valid JSON")

    assert preferred.sections["what_it_is"] == "Structured"
    assert preferred.legacy_text == ""
    assert fallback.sections["what_it_is"] == "Legacy"
    assert fallback.legacy_text.startswith("## What This Is")


def test_section_preview_preserves_short_text_and_marks_truncation():
    assert section_preview("  one two\nthree  ", 3) == "one two\nthree"
    assert section_preview("one two three four", 3) == "one two three…"
    assert section_preview("one", 0) == ""


def test_section_preview_preserves_multiline_markdown_structure():
    text = "- First useful point\n- Second useful point\n- Third useful point"

    preview = section_preview(text, 8)

    assert preview == "- First useful point\n- Second useful point…"


def test_section_preview_balances_a_fenced_code_block_when_truncated():
    text = "Example:\n```python\nprint('one two three')\nprint('four five')\n```\nAfterward"

    preview = section_preview(text, 5)

    assert preview == "Example:\n```python\nprint('one two three')\n```\n…"
    assert preview.count("```") == 2


@pytest.mark.parametrize("marker", ["```", "~~~"])
def test_section_preview_does_not_treat_info_string_as_a_closing_fence(marker):
    text = f"{marker}text\n{marker}python\none two three four five"

    preview = section_preview(text, 4)

    assert preview.endswith(f"\n{marker}\n…")
