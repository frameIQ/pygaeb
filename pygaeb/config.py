"""Configuration management via pydantic-settings."""

from __future__ import annotations

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


class PyGAEBSettings(BaseSettings):
    """Library-wide configuration — supports env vars, .env files, and constructor kwargs."""

    model_config = SettingsConfigDict(env_prefix="PYGAEB_")

    default_model: str = "anthropic/claude-sonnet-4-6"
    classifier_concurrency: int = 5
    xsd_dir: str | None = None
    log_level: str = "WARNING"
    large_file_threshold_mb: int = 50
    large_file_item_threshold: int = 10000
    max_file_size_mb: int = 100


_settings: PyGAEBSettings | None = None


def _apply_log_level(level: str) -> None:
    """Set the ``pygaeb`` logger to *level*."""
    logging.getLogger("pygaeb").setLevel(
        getattr(logging, level.upper(), logging.WARNING),
    )


def get_settings() -> PyGAEBSettings:
    """Get or create the shared settings instance."""
    global _settings
    if _settings is None:
        _settings = PyGAEBSettings()
        _apply_log_level(_settings.log_level)
    return _settings


def configure(
    default_model: str | None = None,
    classifier_concurrency: int | None = None,
    xsd_dir: str | None = None,
    log_level: str | None = None,
    large_file_threshold_mb: int | None = None,
    large_file_item_threshold: int | None = None,
    max_file_size_mb: int | None = None,
) -> PyGAEBSettings:
    """Override settings for the current session. Only supplied values are changed."""
    global _settings
    current = get_settings()
    overrides: dict[str, str | int] = {}
    if default_model is not None:
        overrides["default_model"] = default_model
    if classifier_concurrency is not None:
        overrides["classifier_concurrency"] = classifier_concurrency
    if xsd_dir is not None:
        overrides["xsd_dir"] = xsd_dir
    if log_level is not None:
        overrides["log_level"] = log_level
    if large_file_threshold_mb is not None:
        overrides["large_file_threshold_mb"] = large_file_threshold_mb
    if large_file_item_threshold is not None:
        overrides["large_file_item_threshold"] = large_file_item_threshold
    if max_file_size_mb is not None:
        overrides["max_file_size_mb"] = max_file_size_mb
    merged = current.model_dump()
    merged.update(overrides)
    _settings = PyGAEBSettings(**merged)
    _apply_log_level(_settings.log_level)
    return _settings


def reset_settings() -> None:
    """Reset to default settings. Useful in tests."""
    global _settings
    _settings = None
