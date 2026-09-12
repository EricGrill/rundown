from pathlib import Path

from rundown.config import load_config


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
