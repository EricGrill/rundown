"""Shared CLI helpers for loading configuration and opening the catalog database."""
from __future__ import annotations

from pathlib import Path

from . import db
from .config import AppConfig, load_config


def _config(config: Path | None) -> AppConfig:
    loaded = load_config(config)
    loaded.ensure_directories()
    return loaded


def _conn(config: AppConfig):
    return db.session(config.database_path)
