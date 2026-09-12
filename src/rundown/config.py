"""Configuration management for Rundown."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w


@dataclass
class ScoreWeights:
    """Weights for calculating present_score."""
    freshness: float = 30.0
    description_quality: float = 20.0
    readme_signal: float = 15.0
    stars_normalized: float = 10.0
    topics_count: float = 10.0
    has_license: float = 5.0
    low_issues_ratio: float = 5.0
    manual_boost_multiplier: float = 5.0
    archived_penalty: float = -50.0
    
    freshness_half_life_days: int = 180


@dataclass 
class Config:
    """Rundown configuration."""
    db_path: Path = field(default_factory=lambda: Config.default_db_path())
    config_path: Path = field(default_factory=lambda: Config.default_config_path())
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    
    @staticmethod
    def default_data_dir() -> Path:
        """Get the default data directory."""
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / "rundown"
    
    @staticmethod
    def default_config_dir() -> Path:
        """Get the default config directory."""
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "rundown"
    
    @staticmethod
    def default_db_path() -> Path:
        return Config.default_data_dir() / "rundown.db"
    
    @staticmethod
    def default_config_path() -> Path:
        return Config.default_config_dir() / "config.toml"
    
    @classmethod
    def load(cls, config_path: Path | None = None) -> "Config":
        """Load config from TOML file, creating defaults if needed."""
        path = config_path or cls.default_config_path()
        config = cls(config_path=path)
        
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            config = cls._from_dict(data, path)
        else:
            config.save()
        
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        return config
    
    @classmethod
    def _from_dict(cls, data: dict[str, Any], config_path: Path) -> "Config":
        """Create Config from parsed TOML dict."""
        weights_data = data.get("weights", {})
        weights = ScoreWeights(
            freshness=weights_data.get("freshness", 30.0),
            description_quality=weights_data.get("description_quality", 20.0),
            readme_signal=weights_data.get("readme_signal", 15.0),
            stars_normalized=weights_data.get("stars_normalized", 10.0),
            topics_count=weights_data.get("topics_count", 10.0),
            has_license=weights_data.get("has_license", 5.0),
            low_issues_ratio=weights_data.get("low_issues_ratio", 5.0),
            manual_boost_multiplier=weights_data.get("manual_boost_multiplier", 5.0),
            archived_penalty=weights_data.get("archived_penalty", -50.0),
            freshness_half_life_days=weights_data.get("freshness_half_life_days", 180),
        )
        
        db_path_str = data.get("database", {}).get("path")
        db_path = Path(db_path_str) if db_path_str else cls.default_db_path()
        
        return cls(db_path=db_path, config_path=config_path, weights=weights)
    
    def save(self) -> None:
        """Save config to TOML file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "database": {
                "path": str(self.db_path),
            },
            "weights": {
                "freshness": self.weights.freshness,
                "description_quality": self.weights.description_quality,
                "readme_signal": self.weights.readme_signal,
                "stars_normalized": self.weights.stars_normalized,
                "topics_count": self.weights.topics_count,
                "has_license": self.weights.has_license,
                "low_issues_ratio": self.weights.low_issues_ratio,
                "manual_boost_multiplier": self.weights.manual_boost_multiplier,
                "archived_penalty": self.weights.archived_penalty,
                "freshness_half_life_days": self.weights.freshness_half_life_days,
            },
        }
        
        with open(self.config_path, "wb") as f:
            tomli_w.dump(data, f)
