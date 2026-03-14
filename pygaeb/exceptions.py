"""Custom exception hierarchy for pyGAEB."""

from __future__ import annotations


class PyGAEBError(Exception):
    """Base exception for all pyGAEB errors."""


class GAEBParseError(PyGAEBError):
    """Raised when a file cannot be parsed at all (even after recovery)."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class GAEBValidationError(PyGAEBError):
    """Raised in strict mode on the first ERROR-level validation result."""


class ClassificationBackendError(PyGAEBError):
    """Raised when all LLM backends (including fallbacks) fail."""
