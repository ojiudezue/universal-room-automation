"""D3 — Dispatch snapshot consistency (Zone-prune hotfix).

Anchors: ``config_flow.py`` OptionsFlow ``_delete_zone`` (~:7546) and
``_delete_zone_locked`` (~:7659).

Mutation-anchored: if production reverts to
``self._resolve_zone_id_for_delete(zone_name)`` at the dispatch site,
``test_dispatch_site_uses_confirm_time_snapshot`` MUST fail.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_CONFIG_FLOW_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components" / "universal_room_automation" / "config_flow.py"
)


def _extract_delete_zone_body(src: str) -> str:
    """Return the source of ``async def _delete_zone(`` up to (but not
    including) ``async def _delete_zone_locked(``."""
    start = src.index("async def _delete_zone(")
    end = src.index("async def _delete_zone_locked(", start)
    return src[start:end]


def test_delete_zone_locked_returns_zone_id_snapshot():
    src = _CONFIG_FLOW_PY.read_text()
    # Locked helper signature: return annotation now includes `str | None`.
    m = re.search(
        r"async def _delete_zone_locked\([^)]*\)\s*->\s*str\s*\|\s*None:",
        src,
    )
    assert m is not None, (
        "_delete_zone_locked must be typed to return str | None (D3)"
    )
    # And it must have a `return zone_id` line at the bottom.
    body_start = src.index("async def _delete_zone_locked(")
    body = src[body_start:]
    assert "return zone_id" in body, (
        "_delete_zone_locked must return zone_id (D3 confirm-time snapshot)"
    )


def test_dispatch_site_uses_confirm_time_snapshot():
    """The dispatch site must NOT re-resolve zone_id via
    ``_resolve_zone_id_for_delete`` inside the dispatch try-block; it must
    use the value returned by ``_delete_zone_locked``."""
    src = _CONFIG_FLOW_PY.read_text()
    delete_zone_body = _extract_delete_zone_body(src)

    # The confirm-time snapshot variable must be captured from the locked call.
    assert "confirm_time_zone_id = await self._delete_zone_locked(" in delete_zone_body, (
        "_delete_zone must capture confirm-time zone_id from _delete_zone_locked"
    )

    # Isolate the dispatch try-block. It starts at the "Step 9" comment.
    dispatch_marker = "Step 9: dispatch AFTER the lock is released"
    assert dispatch_marker in delete_zone_body
    dispatch_region = delete_zone_body[delete_zone_body.index(dispatch_marker):]

    # The dispatched payload MUST reference the snapshot, not a re-resolve.
    assert '"deleted_zone_id": confirm_time_zone_id' in dispatch_region, (
        "Dispatch payload MUST carry the confirm-time snapshot (D3)"
    )
    # And the pre-hotfix re-resolve line MUST be gone from the dispatch region.
    assert "zone_id_final, _ = self._resolve_zone_id_for_delete(zone_name)" not in dispatch_region, (
        "Dispatch site must not re-resolve zone_id post-mutation (D3)"
    )
