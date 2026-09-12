from pathlib import Path

import pytest

from rundown.cards import HOST_SECTIONS, RESEARCH_SECTIONS
from rundown.config import CardSettings, CardTemplateSettings, load_config


def test_load_config_defaults_from_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config(Path("missing.toml"))

    assert config.database_path == tmp_path / "data" / "rundown.sqlite"
    config.ensure_directories()
    assert config.database_path.parent.exists()
    assert config.repo_root.exists()
    assert (config.wiki_root / "repos").exists()
    assert config.research.provider == "auto"
    assert "developer tools" in config.research.profile.lower()
    assert config.scoring.active_projects == []
    assert config.github.include_private is False
    assert config.cards.default_view == "host"
    assert config.cards.host.sections == HOST_SECTIONS
    assert config.cards.research.sections == RESEARCH_SECTIONS


def test_load_config_uses_config_root(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "rundown.toml"
    config_file.write_text(
        """
[paths]
repo_root = "custom-repos"
wiki_root = "custom-wiki"
database = "custom-data/app.sqlite"
logs = "custom-logs"
exports = "custom-exports"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.repo_root == tmp_path / "custom-repos"
    assert config.wiki_root == tmp_path / "custom-wiki"
    assert config.database_path == tmp_path / "custom-data" / "app.sqlite"


def test_load_config_can_include_private_starred_repositories(tmp_path):
    config_file = tmp_path / "rundown.toml"
    config_file.write_text(
        """
[github]
include_private = true
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.github.include_private is True


def test_load_config_reads_card_templates(tmp_path):
    config_file = tmp_path / "rundown.toml"
    config_file.write_text(
        """
[cards]
default_view = "research"
audience = "Engineering leaders"
tone = "Direct"
duration_seconds = 180

[cards.host]
sections = ["hook", "what_it_is", "sources"]
word_limit = 40

[cards.research]
sections = ["what_it_is", "risks", "questions", "sources"]
word_limit = 200
""",
        encoding="utf-8",
    )

    cards = load_config(config_file).cards

    assert cards.default_view == "research"
    assert cards.audience == "Engineering leaders"
    assert cards.duration_seconds == 180
    assert cards.host == CardTemplateSettings(("hook", "what_it_is", "sources"), 40)
    assert cards.research.word_limit == 200


@pytest.mark.parametrize(
    "settings, message",
    [
        ('default_view = "script"', "default_view"),
        ("duration_seconds = 14", "between 15 and 3600"),
        ('audience = "   "', "nonblank"),
        ('host = "compact"', "must be a table"),
        ('[cards.host]\nsections = ["hook", "hook"]', "unique"),
        ('[cards.host]\nsections = ["hook", "unknown"]', "unknown card sections"),
        ('[cards.host]\nword_limit = 9', "between 10 and 1000"),
    ],
)
def test_invalid_card_settings_fail_clearly(tmp_path, settings, message):
    config_file = tmp_path / "rundown.toml"
    config_file.write_text(f"[cards]\n{settings}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(config_file)


def test_card_dataclasses_validate_programmatic_settings():
    with pytest.raises(ValueError, match="duration_seconds"):
        CardSettings(duration_seconds=True)
    with pytest.raises(ValueError, match="default_view"):
        CardSettings(default_view=["host"])
    with pytest.raises(ValueError, match="word_limit"):
        CardTemplateSettings(("hook",), 1001)
