from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

SECTION_TITLES: dict[str, str] = {
    "what_it_is": "What This Is",
    "analogy": "Explain It Like I'm Seven",
    "use_cases": "Why Someone Would Use It",
    "personal_fit": "Why It Might Matter to You",
    "interest": "Why It May Have Caught Your Eye",
    "how_it_works": "How It Works",
    "practical_uses": "Practical Uses for You",
    "strengths": "Strengths",
    "risks": "Limitations and Risks",
    "setup": "Install / Run Notes",
    "maturity": "Maturity Signals",
    "questions": "Questions to Answer",
    "recommendation": "Recommendation",
    "hook": "Hook",
    "why_now": "Why Now",
    "talking_points": "Talking Points",
    "demo": "Demo",
    "sources": "Sources",
}

REQUIRED_SECTION_IDS = tuple(SECTION_TITLES)[:5]
HOST_SECTIONS = (
    "hook",
    "what_it_is",
    "talking_points",
    "why_now",
    "demo",
    "risks",
    "recommendation",
    "sources",
)
RESEARCH_SECTIONS = (*tuple(SECTION_TITLES)[:13], "sources")

_MAX_RECORD_CHARS = 1_000_000
_MAX_SECTION_CHARS = 200_000
_HEADING_RE = re.compile(r"^ {0,3}##[ \t]+(.+?)(?:[ \t]+#+[ \t]*)?$")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class CardRecord:
    schema_version: int = SCHEMA_VERSION
    sections: dict[str, str] = field(default_factory=dict)
    legacy_text: str = ""

    def to_json(self) -> str:
        sections = {
            section_id: self.sections.get(section_id) or None
            for section_id in SECTION_TITLES
        }
        return json.dumps(
            {"schema_version": self.schema_version, "sections": sections},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def to_markdown(self) -> str:
        if self.legacy_text:
            return self.legacy_text
        blocks = [
            f"## {title}\n\n{self.sections[section_id].strip()}"
            for section_id, title in SECTION_TITLES.items()
            if self.sections.get(section_id, "").strip()
        ]
        return "\n\n".join(blocks)


class _DuplicateKey(ValueError):
    pass


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate key: {key}")
        result[key] = value
    return result


def _json_source(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() == "```json" and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return None


def _fence_opener(line: str) -> tuple[str, int] | None:
    match = _FENCE_OPEN_RE.match(line)
    if not match:
        return None
    marker, info = match.groups()
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker)


def _is_fence_closer(line: str, fence: tuple[str, int]) -> bool:
    if len(line) - len(line.lstrip(" ")) > 3:
        return False
    candidate = line.lstrip(" ").rstrip(" \t")
    marker, minimum_length = fence
    return len(candidate) >= minimum_length and set(candidate) == {marker}


def _parse_json_record(source: str, *, strict: bool) -> CardRecord:
    if len(source) > _MAX_RECORD_CHARS:
        raise ValueError("research card JSON is too large")
    try:
        value = json.loads(source, object_pairs_hook=_object_from_pairs)
    except (_DuplicateKey, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid research card JSON: {exc}") from exc
    if not isinstance(value, dict):
        # JSON shape failures use one public validation exception type.
        raise ValueError("research card JSON must be an object")  # noqa: TRY004
    unknown_root = set(value) - {"schema_version", "sections"}
    if unknown_root:
        raise ValueError(f"unknown research card fields: {', '.join(sorted(unknown_root))}")
    if set(value) != {"schema_version", "sections"}:
        raise ValueError("research card JSON requires schema_version and sections")
    version = value["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise ValueError(f"unsupported research card schema_version: {version!r}")
    raw_sections = value["sections"]
    if not isinstance(raw_sections, dict):
        # JSON shape failures use one public validation exception type.
        raise ValueError("research card sections must be an object")  # noqa: TRY004
    unknown_sections = set(raw_sections) - set(SECTION_TITLES)
    if unknown_sections:
        raise ValueError(f"unknown research card sections: {', '.join(sorted(unknown_sections))}")
    if strict:
        missing = set(SECTION_TITLES) - set(raw_sections)
        if missing:
            raise ValueError(f"research card is missing sections: {', '.join(sorted(missing))}")

    sections: dict[str, str] = {}
    for section_id, content in raw_sections.items():
        if content is not None and not isinstance(content, str):
            raise ValueError(f"research card section {section_id!r} must be a string or null")
        normalized = content or ""
        if len(normalized) > _MAX_SECTION_CHARS:
            raise ValueError(f"research card section {section_id!r} is too large")
        sections[section_id] = normalized
    if strict:
        _require_core_sections(sections)
    return CardRecord(schema_version=version, sections=sections)


def _parse_markdown(text: str) -> CardRecord:
    title_to_id = {title: section_id for section_id, title in SECTION_TITLES.items()}
    collected: dict[str, list[str]] = {}
    active: str | None = None
    fence: tuple[str, int] | None = None

    for line in text.splitlines():
        if fence is not None:
            if active is not None:
                collected[active].append(line)
            if _is_fence_closer(line, fence):
                fence = None
            continue

        opener = _fence_opener(line)
        if opener is not None:
            fence = opener
            if active is not None:
                collected[active].append(line)
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            active = title_to_id.get(heading_match.group(1))
            if active is not None:
                collected.setdefault(active, [])
            continue

        if active is not None:
            collected[active].append(line)

    sections = {
        section_id: "\n".join(lines).strip()
        for section_id, lines in collected.items()
    }
    return CardRecord(sections=sections, legacy_text=text)


def _require_core_sections(sections: dict[str, str]) -> None:
    missing = [
        section_id
        for section_id in REQUIRED_SECTION_IDS
        if not sections.get(section_id, "").strip()
    ]
    if missing:
        raise ValueError(f"research card requires nonempty sections: {', '.join(missing)}")


def parse_research(text: str, *, strict: bool = False) -> CardRecord:
    if not isinstance(text, str):
        raise TypeError("research text must be a string")
    json_source = _json_source(text)
    if json_source is not None:
        try:
            return _parse_json_record(json_source, strict=strict)
        except ValueError:
            if strict:
                raise
            return CardRecord(legacy_text=text)

    if strict and len(text) > _MAX_RECORD_CHARS:
        raise ValueError("research Markdown is too large")
    record = _parse_markdown(text)
    if strict:
        oversized = [
            section_id
            for section_id, content in record.sections.items()
            if len(content) > _MAX_SECTION_CHARS
        ]
        if oversized:
            raise ValueError(f"research Markdown section is too large: {oversized[0]}")
        _require_core_sections(record.sections)
    return record


def record_from_saved(summary: str, card_json: str | None = None) -> CardRecord:
    if card_json:
        try:
            source = _json_source(card_json)
            if source is not None:
                return _parse_json_record(source, strict=False)
        except (TypeError, ValueError):
            pass
    try:
        return parse_research(summary)
    except (TypeError, ValueError):
        return CardRecord(legacy_text=summary if isinstance(summary, str) else str(summary))


def section_preview(text: str, word_limit: int) -> str:
    if word_limit <= 0:
        return ""
    words = list(re.finditer(r"\S+", text))
    if len(words) <= word_limit:
        return text.strip()
    preview = text[: words[word_limit - 1].end()].strip()

    fence: tuple[str, int] | None = None
    for line in preview.splitlines():
        if fence is None:
            opener = _fence_opener(line)
            if opener is not None:
                fence = opener
        elif _is_fence_closer(line, fence):
            fence = None
    if fence is not None:
        preview = f"{preview}\n{fence[0] * fence[1]}\n…"
    else:
        preview += "…"
    return preview
