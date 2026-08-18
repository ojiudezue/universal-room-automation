"""CENSUS-FACE-RESOLVER-MIGRATE-1 behavioral test.

Drives PRODUCTION `PresenceCoordinator._get_face_for_camera` and asserts
it now resolves `_2`-suffix-only Frigate face sensors via the census
resolver (`camera_census._resolve_face_entity_id`).

Cases:
  * A camera whose face sensor exists ONLY as
    ``sensor.<base>_last_recognized_face_2`` (Frigate-1-retired /
    disambiguation-suffix case, memory "frigate 1 retired 2 suffix")
    resolves to a name. This is the fix — previously returned None.
  * A camera with the bare canonical sensor still resolves (no regression).
  * A camera with no face sensor returns None.

Mutation anchor: in ``domain_coordinators/presence.py``
``_get_face_for_camera``, replace the census-resolver call with the bare
string build ``face_sensor_id = f"sensor.{base_name}_last_recognized_face"``
(the pre-fix code). The ``_2``-only test MUST fail. Restore.
"""

from __future__ import annotations

from datetime import datetime
from types import MethodType
from unittest.mock import MagicMock

import pytest

# Reuse the heavy sys.modules scaffolding installed by test_presence_coordinator
# (the presence module is deeply coupled to HA imports; duplicating the
# harness here would be unproductive).
from test_presence_coordinator import PresenceCoordinator, make_hass  # noqa: E402

from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402


class _State:
    def __init__(self, state: str, last_changed: datetime | None = None):
        self.state = state
        # Match dt_util.utcnow() shape used in production (harness stubs
        # it to naive datetime.utcnow — mixing tz-aware would raise).
        self.last_changed = last_changed or datetime.utcnow()


def _install_states(hass, mapping: dict[str, _State | None]) -> None:
    hass.states = MagicMock()
    hass.states.get = lambda eid: mapping.get(eid)


def _make_census(hass):
    """Minimal census stand-in exposing only `_resolve_face_entity_id` —
    the exact contract `_get_face_for_camera` now consumes. Reads live
    `hass.states` so the test controls which entity_ids exist.
    """
    class _Census:
        def __init__(self, h):
            self.hass = h
            self._face_lookup_missing_count = 0

        def _resolve_face_entity_id(self, base_name):
            canonical = f"sensor.{base_name}_last_recognized_face"
            suffixed = f"sensor.{base_name}_last_recognized_face_2"
            for cand in (canonical, suffixed):
                st = self.hass.states.get(cand)
                if st is None:
                    continue
                v = (st.state or "").strip().lower()
                if v in ("unavailable", "unknown", "", "none"):
                    continue
                return cand
            self._face_lookup_missing_count += 1
            return None

    return _Census(hass)


def _stub_coord(hass):
    stub = MagicMock()
    stub.hass = hass
    # Bind the real production method to the stub — we're testing the
    # helper, not the coordinator's construction.
    stub._get_face_for_camera = MethodType(
        PresenceCoordinator._get_face_for_camera, stub,
    )
    return stub


def test_face_resolver_finds_suffix_only_camera():
    """FIX: a `_2`-only Frigate face sensor is now resolved."""
    hass = make_hass()
    # Only the _2 variant exists — the pre-fix bare-string build missed it.
    _install_states(hass, {
        "sensor.frontdoor_last_recognized_face_2": _State("Oji"),
    })
    hass.data = {DOMAIN: {"census": _make_census(hass)}}

    coord = _stub_coord(hass)
    result = coord._get_face_for_camera("binary_sensor.frontdoor_person_occupancy")
    assert result == "Oji", (
        "regression: _2-only face sensor not resolved — the census "
        "resolver call is not wired"
    )


def test_face_resolver_finds_bare_canonical_camera():
    """No regression: cameras with the bare canonical sensor still resolve."""
    hass = make_hass()
    _install_states(hass, {
        "sensor.backdoor_last_recognized_face": _State("Ezinne"),
    })
    hass.data = {DOMAIN: {"census": _make_census(hass)}}

    coord = _stub_coord(hass)
    result = coord._get_face_for_camera("binary_sensor.backdoor_person_occupancy")
    assert result == "Ezinne"


def test_face_resolver_no_sensor_returns_none():
    """Absent face sensor -> None (accelerator, not requirement)."""
    hass = make_hass()
    _install_states(hass, {})
    hass.data = {DOMAIN: {"census": _make_census(hass)}}

    coord = _stub_coord(hass)
    result = coord._get_face_for_camera("binary_sensor.nowhere_person_occupancy")
    assert result is None
