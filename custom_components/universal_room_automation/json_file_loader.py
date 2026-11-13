"""Shared loader for operator-maintained JSON files under /config
(FACE-ARRIVAL-REBUILD-1 D7, plan rev 11 §9 D7; extracted from
``ExteriorTrackLinker.async_load_seam_file``).

The helper ONLY reads (in the executor), hashes the raw bytes, parses JSON and
calls the caller's validator. It never installs and never falls back: each
caller decides from the returned ``LoadOutcome`` (the seam loader keeps its
previous graph on a reject and publishes the rejected file's sha; the interior
path map installs its own fallback at setup and keeps the previous map on a
later reject). Never raises.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

STATUS_LOADED = "loaded"
STATUS_ABSENT = "absent"
STATUS_REJECTED = "rejected"
STATUS_READ_ERROR = "read_error"


@dataclass(frozen=True)
class LoadOutcome:
    status: str             # "loaded" | "absent" | "rejected" | "read_error"
    raw_sha256: str | None  # sha of the bytes read; None if absent/unreadable
    error: str | None       # validation or read error text (first error)
    value: Any | None       # parse_validate's result when status == "loaded"
    warnings: tuple = ()


class JsonValidationError(ValueError):
    """Raised by a ``parse_validate`` callback to reject the whole file."""


def _read(path: str) -> tuple[bytes | None, str | None]:
    """Blocking read, ALWAYS via the executor. (bytes, error)."""
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "rb") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, f"unreadable: {exc}"


async def load_validated_json(
    hass: Any, path: str, *, parse_validate: Callable[[Any], Any],
) -> LoadOutcome:
    """Read ``path`` and validate it with ``parse_validate(parsed_json)``.

    ``parse_validate`` returns the validated value, or a
    ``(value, warnings)`` tuple, or raises ``JsonValidationError`` (or any
    ValueError) to reject the whole file."""
    try:
        raw, read_err = await hass.async_add_executor_job(_read, path)
    except Exception as exc:  # noqa: BLE001
        raw, read_err = None, f"load failed: {exc}"
    if raw is None and read_err is None:
        return LoadOutcome(STATUS_ABSENT, None, None, None)
    if read_err is not None:
        return LoadOutcome(STATUS_READ_ERROR, None, read_err, None)
    sha = hashlib.sha256(raw).hexdigest()
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return LoadOutcome(STATUS_REJECTED, sha, f"invalid JSON: {exc}", None)
    try:
        result = parse_validate(spec)
    except ValueError as exc:
        return LoadOutcome(STATUS_REJECTED, sha, str(exc), None)
    except Exception as exc:  # noqa: BLE001
        return LoadOutcome(STATUS_REJECTED, sha, f"validator error: {exc}", None)
    warnings: tuple = ()
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], (list, tuple)):
        result, warnings = result[0], tuple(result[1])
    return LoadOutcome(STATUS_LOADED, sha, None, result, warnings)
