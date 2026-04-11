"""Simple event/webhook system for pyGAEB lifecycle events.

Subscribe to events emitted at key points in the parse/write/classify
pipeline. Useful for logging, audit trails, webhook integrations, and
metrics collection.

Usage::

    from pygaeb import on_event, EventType

    def log_parse(payload):
        print(f"Parsed {payload['file']}: {payload['item_count']} items")

    on_event(EventType.PARSE_COMPLETED, log_parse)

    # Now every successful parse will trigger the callback.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger("pygaeb.events")

EventCallback = Callable[[dict[str, Any]], None]


class EventType(str, Enum):
    """Events emitted during pyGAEB operations."""

    PARSE_STARTED = "parse_started"
    PARSE_COMPLETED = "parse_completed"
    PARSE_FAILED = "parse_failed"
    WRITE_STARTED = "write_started"
    WRITE_COMPLETED = "write_completed"
    VALIDATION_FAILED = "validation_failed"
    CLASSIFICATION_COMPLETED = "classification_completed"


_subscribers: dict[EventType, list[EventCallback]] = {}


def on_event(event_type: EventType, callback: EventCallback) -> None:
    """Register a callback for an event type.

    Multiple callbacks per event type are supported and called in order.
    Callbacks should be fast and non-blocking — long-running work should
    be queued (e.g., to Celery, RQ, or a background thread).

    Args:
        event_type: The event to subscribe to.
        callback: ``callback(payload: dict)`` invoked when the event fires.
    """
    if event_type not in _subscribers:
        _subscribers[event_type] = []
    _subscribers[event_type].append(callback)


def off_event(event_type: EventType, callback: EventCallback) -> bool:
    """Unregister a previously-registered callback.

    Returns:
        ``True`` if removed, ``False`` if not found.
    """
    if event_type not in _subscribers:
        return False
    try:
        _subscribers[event_type].remove(callback)
        return True
    except ValueError:
        return False


def clear_subscribers(event_type: EventType | None = None) -> None:
    """Remove all subscribers for an event type, or all events if ``None``."""
    if event_type is None:
        _subscribers.clear()
    elif event_type in _subscribers:
        _subscribers[event_type].clear()


def emit(event_type: EventType, **payload: Any) -> None:
    """Fire an event with a payload dict.

    Errors in subscribers are logged but do not propagate (events
    must never break the calling pipeline).
    """
    if event_type not in _subscribers:
        return
    for callback in _subscribers[event_type]:
        try:
            callback(payload)
        except Exception as e:
            logger.warning(
                "Event subscriber failed for %s: %s", event_type.value, e,
            )


__all__ = ["EventType", "clear_subscribers", "emit", "off_event", "on_event"]
