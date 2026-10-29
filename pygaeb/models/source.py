"""Where a parsed element sits in its source file."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SourceSpan(BaseModel):
    """An element's place in the file, counted the way editors count.

    Lines break at CR, LF and CRLF; columns count characters; both start at 1.
    The start is the ``<`` of the element's start tag; the end is just past the
    ``>`` that closes the element, so the span covers the whole element.
    """

    model_config = ConfigDict(frozen=True)

    start_line: int
    start_column: int
    end_line: int
    end_column: int
