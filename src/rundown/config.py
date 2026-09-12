from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any


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


@dataclass(frozen=True)
class TuiSettings:
    default_filter: str = "not_archived"
    default_sort: str = "starred_at"


@dataclass(frozen=True)
class AppConfig:
    root: Path
    paths: PathSettings = field(default_factory=PathSettings)
    github: GithubSettings = field(default_factory=GithubSettings)
    scoring: ScoringSettings = field(default_factory=ScoringSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    research: ResearchSettings = field(default_factory=ResearchSettings)
    tui: TuiSettings = field(default_factory=TuiSettings)

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


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or Path("config/rundown.toml")
    root = path.parent.parent.resolve() if path.exists() else Path.cwd().resolve()
    data: dict[str, object] = {}
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))

    github = _table(data, "github")
    scoring = _table(data, "scoring")
    execution = _table(data, "execution")
    research = _table(data, "research")
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
            provider=str(research.get("provider", "auto")),
            profile=str(research.get("profile", ResearchSettings().profile)),
            timeout_seconds=int(research.get("timeout_seconds", 180)),
            max_context_chars=int(research.get("max_context_chars", 60000)),
        ),
        tui=TuiSettings(
            default_filter=str(tui.get("default_filter", "not_archived")),
            default_sort=str(tui.get("default_sort", "starred_at")),
        ),
    )
