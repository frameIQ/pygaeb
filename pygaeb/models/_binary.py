"""Binary attachment data: bytes in Python, standard base64 text in JSON."""

from __future__ import annotations

import base64
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


def _from_base64(value: Any) -> Any:
    # JSON holds the bytes as base64 text, whether read by model_validate_json or json.load.
    if isinstance(value, str):
        return base64.b64decode("".join(value.split()), validate=True)
    return value


def _to_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


#: Standard base64 (``+`` and ``/``), not pydantic's URL-safe variant: data URLs and
#: most decoders expect the standard alphabet. Without this, JSON tried UTF-8 and failed.
BinaryData = Annotated[
    bytes,
    BeforeValidator(_from_base64),
    PlainSerializer(_to_base64, return_type=str, when_used="json"),
]
