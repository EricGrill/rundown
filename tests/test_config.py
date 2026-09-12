"""Tests for configuration management."""

import tempfile
from pathlib import Path

import pytest

from rundown.config import Config, ScoreWeights


class TestScoreWeights:
    """Tests for ScoreWeights dataclass."""
    
    def test_default_values(self):
        """Test default weight values."""
        weights = ScoreWeights()
        
        assert weights.freshness == 30.0
        assert weights.description_quality == 20.0
        assert weights.readme_signal == 15.0
        assert weights.stars_normalized == 10.0
        assert weights.topics_count == 10.0
        assert weights.has_license == 5.0
        assert weights.low_issues_ratio == 5.0
        assert weights.manual_boost_multiplier == 5.0
        assert weights.archived_penalty == -50.0
        assert weights.freshness_half_life_days == 180
    
    def test_custom_values(self):
        """Test custom weight values."""
        weights = ScoreWeights(freshness=50.0, archived_penalty=-100.0)
        
        assert weights.freshness == 50.0
        assert weights.archived_penalty == -100.0


class TestConfig:
    """Tests for Config class."""
    
    def test_default_paths(self):
        """Test default paths are set."""
        config = Config()
        
        assert config.db_path.name == "rundown.db"
        assert config.config_path.name == "config.toml"
    
    def test_load_creates_default_config(self):
        """Test loading creates default config if not exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config = Config.load(config_path)
            
            assert config_path.exists()
            assert config.weights.freshness == 30.0
    
    def test_load_existing_config(self):
        """Test loading an existing config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            db_path = Path(tmpdir) / "custom" / "db.sqlite"
            
            config_path.write_text(f"""
[database]
path = "{db_path}"

[weights]
freshness = 40.0
archived_penalty = -75.0
""")
            
            config = Config.load(config_path)
            
            assert config.weights.freshness == 40.0
            assert config.weights.archived_penalty == -75.0
            assert str(config.db_path) == str(db_path)
    
    def test_save_config(self):
        """Test saving config to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config = Config(config_path=config_path)
            config.weights.freshness = 45.0
            config.save()
            
            content = config_path.read_text()
            assert "freshness = 45.0" in content
    
    def test_load_preserves_unset_defaults(self):
        """Test loading config with partial weights uses defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            
            config_path.write_text("""
[weights]
freshness = 40.0
""")
            
            config = Config.load(config_path)
            
            assert config.weights.freshness == 40.0
            assert config.weights.description_quality == 20.0
            assert config.weights.readme_signal == 15.0
    
    def test_db_path_parent_created(self):
        """Test database path parent directory is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            db_path = Path(tmpdir) / "nested" / "dir" / "rundown.db"
            
            config_path.write_text(f"""
[database]
path = "{db_path}"
""")
            
            Config.load(config_path)
            
            assert db_path.parent.exists()


class TestConfigRoundTrip:
    """Tests for config save/load round trip."""
    
    def test_roundtrip_preserves_all_weights(self):
        """Test saving and loading preserves all weight values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            
            original = Config(config_path=config_path)
            original.weights.freshness = 35.0
            original.weights.description_quality = 25.0
            original.weights.readme_signal = 18.0
            original.weights.archived_penalty = -60.0
            original.weights.freshness_half_life_days = 200
            original.save()
            
            loaded = Config.load(config_path)
            
            assert loaded.weights.freshness == 35.0
            assert loaded.weights.description_quality == 25.0
            assert loaded.weights.readme_signal == 18.0
            assert loaded.weights.archived_penalty == -60.0
            assert loaded.weights.freshness_half_life_days == 200
