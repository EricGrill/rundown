from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .harnesses import CustomHarnessSettings, selected_harnesses

from .cards import HOST_SECTIONS, RESEARCH_SECTIONS, SECTION_TITLES


@dataclass(frozen=True)
class PathSettings:
    repo_root: Path = Path("./repos")
    wiki_root: Path = Path("./wiki")
    database: Path = Path("./data/rundown.sqlite")
    logs: Path = Path("./logs")
    exports: Path = Path("./exports")


@dataclass(frozen=True)
class GithubSettings:
    use_gh_cli: bool = True
    include_private: bool = False


@dataclass(frozen=True)
class ScoringSettings:
    preferred_languages: list[str] = field(
        default_factory=lambda: ["Python", "JavaScript", "TypeScript", "Go", "Rust"]
    )
    active_projects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionSettings:
    prefer_docker: bool = True
    require_confirmation_for_unknown_commands: bool = True
    timeout_seconds: int = 120


@dataclass(frozen=True)
class ResearchSettings:
    provider: str = "auto"
    profile: str = (
        "I am interested in useful software, developer tools, and automation."
    )
    timeout_seconds: int = 180
    max_context_chars: int = 60000
    model: str | None = None
    fallback: tuple[str, ...] = ("claude", "gemini", "codex")
    custom: dict[str, CustomHarnessSettings] = field(default_factory=dict)

    def __post_init__(self) -> None:
        selected_harnesses(self)
        object.__setattr__(self, "fallback", tuple(self.fallback))


@dataclass(frozen=True)
class TuiSettings:
    default_filter: str = "not_archived"
    default_sort: str = "starred_at"


@dataclass(frozen=True)
class CardTemplateSettings:
    sections: tuple[str, ...]
    word_limit: int

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("card template sections must not be empty")
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("card template sections must be unique")
        unknown = set(self.sections) - set(SECTION_TITLES)
        if unknown:
            raise ValueError(f"unknown card sections: {', '.join(sorted(unknown))}")
        if isinstance(self.word_limit, bool) or not isinstance(self.word_limit, int):
            # Config validation consistently reports invalid settings as values.
            raise ValueError("card template word_limit must be an integer")  # noqa: TRY004
        if not 10 <= self.word_limit <= 1000:
            raise ValueError("card template word_limit must be between 10 and 1000")


def _default_host_card() -> CardTemplateSettings:
    return CardTemplateSettings(sections=HOST_SECTIONS, word_limit=60)


def _default_research_card() -> CardTemplateSettings:
    return CardTemplateSettings(sections=RESEARCH_SECTIONS, word_limit=120)


@dataclass(frozen=True)
class CardSettings:
    default_view: str = "host"
    audience: str = "Developers exploring useful repositories"
    tone: str = "Plain, concise, conversational"
    duration_seconds: int = 90
    host: CardTemplateSettings = field(default_factory=_default_host_card)
    research: CardTemplateSettings = field(default_factory=_default_research_card)

    def __post_init__(self) -> None:
        if not isinstance(self.default_view, str) or self.default_view not in {
            "host",
            "research",
        }:
            raise ValueError("cards.default_view must be 'host' or 'research'")
        for name, value in (("audience", self.audience), ("tone", self.tone)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"cards.{name} must be a nonblank string")
        if isinstance(self.duration_seconds, bool) or not isinstance(
            self.duration_seconds, int
        ):
            # Config validation consistently reports invalid settings as values.
            raise ValueError("cards.duration_seconds must be an integer")  # noqa: TRY004
        if not 15 <= self.duration_seconds <= 3600:
            raise ValueError("cards.duration_seconds must be between 15 and 3600")
        if not isinstance(self.host, CardTemplateSettings) or not isinstance(
            self.research, CardTemplateSettings
        ):
            # Config validation consistently reports invalid settings as values.
            raise ValueError(  # noqa: TRY004
                "cards.host and cards.research must be card templates"
            )


@dataclass(frozen=True)
class AppConfig:
    root: Path
    paths: PathSettings = field(default_factory=PathSettings)
    github: GithubSettings = field(default_factory=GithubSettings)
    scoring: ScoringSettings = field(default_factory=ScoringSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    research: ResearchSettings = field(default_factory=ResearchSettings)
    tui: TuiSettings = field(default_factory=TuiSettings)
    cards: CardSettings = field(default_factory=CardSettings)

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else (self.root / path).resolve()

    @property
    def database_path(self) -> Path:
        return self.resolve(self.paths.database)

    @property
    def repo_root(self) -> Path:
        return self.resolve(self.paths.repo_root)

    @property
    def wiki_root(self) -> Path:
        return self.resolve(self.paths.wiki_root)

    @property
    def logs_root(self) -> Path:
        return self.resolve(self.paths.logs)

    @property
    def exports_root(self) -> Path:
        return self.resolve(self.paths.exports)

    def ensure_directories(self) -> None:
        for path in [
            self.database_path.parent,
            self.repo_root,
            self.wiki_root / "repos",
            self.logs_root / "research",
            self.logs_root / "execution",
            self.exports_root,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def _path_settings(data: dict[str, object]) -> PathSettings:
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}
    return PathSettings(
        repo_root=Path(str(paths.get("repo_root", "./repos"))),
        wiki_root=Path(str(paths.get("wiki_root", "./wiki"))),
        database=Path(str(paths.get("database", "./data/rundown.sqlite"))),
        logs=Path(str(paths.get("logs", "./logs"))),
        exports=Path(str(paths.get("exports", "./exports"))),
    )


def _table(data: dict[str, object], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def _card_template(
    data: object,
    *,
    name: str,
    default: CardTemplateSettings,
) -> CardTemplateSettings:
    if data is None:
        return default
    if not isinstance(data, dict):
        # TOML shape failures use the same error type as invalid field values.
        raise ValueError(f"cards.{name} must be a table")  # noqa: TRY004
    unknown = set(data) - {"sections", "word_limit"}
    if unknown:
        raise ValueError(f"unknown cards.{name} settings: {', '.join(sorted(unknown))}")
    if "sections" in data:
        raw_sections = data["sections"]
        if not isinstance(raw_sections, list) or any(
            not isinstance(item, str) for item in raw_sections
        ):
            raise ValueError(f"cards.{name}.sections must be an array of strings")
        sections = tuple(raw_sections)
    else:
        sections = default.sections
    return CardTemplateSettings(
        sections=sections,
        word_limit=data.get("word_limit", default.word_limit),
    )


def _card_settings(data: dict[str, object]) -> CardSettings:
    raw = data.get("cards")
    if raw is None:
        return CardSettings()
    if not isinstance(raw, dict):
        # TOML shape failures use the same error type as invalid field values.
        raise ValueError("cards must be a table")  # noqa: TRY004
    known = {"default_view", "audience", "tone", "duration_seconds", "host", "research"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown cards settings: {', '.join(sorted(unknown))}")
    defaults = CardSettings()
    return CardSettings(
        default_view=raw.get("default_view", defaults.default_view),
        audience=raw.get("audience", defaults.audience),
        tone=raw.get("tone", defaults.tone),
        duration_seconds=raw.get("duration_seconds", defaults.duration_seconds),
        host=_card_template(raw.get("host"), name="host", default=defaults.host),
        research=_card_template(raw.get("research"), name="research", default=defaults.research),
    )


def _custom_harnesses(raw: object) -> dict[str, CustomHarnessSettings]:
    if not isinstance(raw, dict):
        raise ValueError("research.custom must be a table")
    result = {}
    for name, value in raw.items():
        if not isinstance(value, dict) or set(value) - {"executable", "args", "prompt", "output"}:
            raise ValueError("Invalid research.custom settings")
        if "executable" not in value:
            raise ValueError("custom executable is required")
        result[name] = CustomHarnessSettings(**value)
    return result


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or Path("config/rundown.toml")
    root = path.parent.parent.resolve() if path.exists() else Path.cwd().resolve()
    data: dict[str, object] = {}
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))

    github = _table(data, "github")
    scoring = _table(data, "scoring")
    execution = _table(data, "execution")
    research = data.get("research", {})
    if not isinstance(research, dict):
        raise ValueError("research must be a table")
    if set(research) - {"provider", "model", "fallback", "custom", "profile", "timeout_seconds", "max_context_chars"}:
        raise ValueError("Unknown research settings")
    tui = _table(data, "tui")

    return AppConfig(
        root=root,
        paths=_path_settings(data),
        github=GithubSettings(
            use_gh_cli=bool(github.get("use_gh_cli", True)),
            include_private=bool(github.get("include_private", False)),
        ),
        scoring=ScoringSettings(
            preferred_languages=[str(v) for v in scoring.get("preferred_languages", ScoringSettings().preferred_languages)],
            active_projects=[str(v) for v in scoring.get("active_projects", ScoringSettings().active_projects)],
        ),
        execution=ExecutionSettings(
            prefer_docker=bool(execution.get("prefer_docker", True)),
            require_confirmation_for_unknown_commands=bool(
                execution.get("require_confirmation_for_unknown_commands", True)
            ),
            timeout_seconds=int(execution.get("timeout_seconds", 120)),
        ),
        research=ResearchSettings(
            provider=research.get("provider", "auto"),
            model=research.get("model"),
            fallback=research.get("fallback", ("claude", "gemini", "codex")),
            custom=_custom_harnesses(research.get("custom", {})),
            profile=str(research.get("profile", ResearchSettings().profile)),
            timeout_seconds=int(research.get("timeout_seconds", 180)),
            max_context_chars=int(research.get("max_context_chars", 60000)),
        ),
        tui=TuiSettings(
            default_filter=str(tui.get("default_filter", "not_archived")),
            default_sort=str(tui.get("default_sort", "starred_at")),
        ),
        cards=_card_settings(data),
    )
