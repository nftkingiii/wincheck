"""Thin wrapper around neatlogs so the agent still runs when tracing is off.

Every phase and tool goes through `span`. With NEATLOGS_API_KEY set, spans are
exported to neatlogs; without it, neatlogs runs with export disabled so the
code path is the same in local dry runs.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

try:
    import neatlogs
except ImportError:  # pragma: no cover - neatlogs is a hard dependency, but stay usable
    neatlogs = None

ENDPOINT = "https://ingest.neatlogs.com"
_started = False


def init(workflow_name: str, tags: list[str] | None = None) -> bool:
    """Start tracing. Returns True when spans will actually be exported."""
    global _started
    if neatlogs is None or _started:
        return False
    api_key = os.environ.get("NEATLOGS_API_KEY")
    try:
        neatlogs.init(
            api_key=api_key,
            endpoint=ENDPOINT,
            workflow_name=workflow_name,
            tags=tags,
            instrumentations=["anthropic"],
            disable_export=not api_key,
        )
    except Exception as exc:  # tracing must never take the agent down
        print(f"[wincheck] neatlogs init failed: {exc}", file=sys.stderr)
        return False
    _started = True
    return bool(api_key)


def span(kind: str, name: str | None = None, **kwargs: Any) -> Callable[[F], F]:
    if neatlogs is None:
        return lambda fn: fn
    return neatlogs.span(kind=kind, name=name, **kwargs)


def shutdown() -> None:
    global _started
    if neatlogs is None or not _started:
        return
    try:
        neatlogs.flush()
        neatlogs.shutdown()
    except Exception as exc:
        print(f"[wincheck] neatlogs shutdown failed: {exc}", file=sys.stderr)
    _started = False
