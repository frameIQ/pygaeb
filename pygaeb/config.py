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

    # MCP server (see pygaeb.mcp). All are inert unless the server is running.
    mcp_roots: str | None = None
    mcp_allow_write: bool = False
    mcp_output_dir: str | None = None
    mcp_max_open_documents: int = 8
    mcp_max_cache_mb: int = 512
    mcp_max_page_size: int = 200
    mcp_max_response_chars: int = 20_000


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
    mcp_roots: str | None = None,
    mcp_allow_write: bool | None = None,
    mcp_output_dir: str | None = None,
    mcp_max_open_documents: int | None = None,
    mcp_max_cache_mb: int | None = None,
    mcp_max_page_size: int | None = None,
    mcp_max_response_chars: int | None = None,
) -> PyGAEBSettings:
    """Override settings for the current session. Only supplied values are changed."""
    global _settings
    current = get_settings()
    overrides: dict[str, str | int | bool] = {}
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
    if mcp_roots is not None:
        overrides["mcp_roots"] = mcp_roots
    if mcp_allow_write is not None:
        overrides["mcp_allow_write"] = mcp_allow_write
    if mcp_output_dir is not None:
        overrides["mcp_output_dir"] = mcp_output_dir
    if mcp_max_open_documents is not None:
        overrides["mcp_max_open_documents"] = mcp_max_open_documents
    if mcp_max_cache_mb is not None:
        overrides["mcp_max_cache_mb"] = mcp_max_cache_mb
    if mcp_max_page_size is not None:
        overrides["mcp_max_page_size"] = mcp_max_page_size
    if mcp_max_response_chars is not None:
        overrides["mcp_max_response_chars"] = mcp_max_response_chars
    merged = current.model_dump()
    merged.update(overrides)
    _settings = PyGAEBSettings(**merged)
    _apply_log_level(_settings.log_level)
    return _settings


def reset_settings() -> None:
    """Reset to default settings. Useful in tests."""
    global _settings
    _settings = None
