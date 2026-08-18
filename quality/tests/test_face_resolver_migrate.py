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


def test_real_person_census_exposes_resolve_face_entity_id():
    """M1 anti-hollow anchor: import the REAL PersonCensus and assert the
    resolver attribute the presence helper calls actually exists and is
    callable. If someone renames or removes
    `camera_census.PersonCensus._resolve_face_entity_id`, this test MUST
    fail — otherwise the suffix-only test above (which uses a hand-rolled
    census stub) would silently pass while production reverted to the
    bare-string fallback path.
    """
    # Reuse the harness path installed by test_presence_coordinator.
    import importlib.util as _iu
    import os as _os
    import sys as _sys
    import types as _types

    _here = _os.path.dirname(__file__)
    _ura_path = _os.path.abspath(_os.path.join(
        _here, "..", "..", "custom_components", "universal_room_automation",
    ))
    _full = "custom_components.universal_room_automation.camera_census"
    cached = _sys.modules.get(_full)
    if cached is None or not getattr(cached, "__file__", None):
        # Ensure entity_registry stub exists (camera_census imports it at top).
        _er_name = "homeassistant.helpers.entity_registry"
        if _er_name not in _sys.modules:
            _er = _types.ModuleType(_er_name)
            _er.async_get = MagicMock()
            _sys.modules[_er_name] = _er
        spec = _iu.spec_from_file_location(
            _full, _os.path.join(_ura_path, "camera_census.py"),
        )
        mod = _iu.module_from_spec(spec)
        _sys.modules[_full] = mod
        spec.loader.exec_module(mod)
        cached = mod

    PersonCensus = getattr(cached, "PersonCensus", None)
    assert PersonCensus is not None, "PersonCensus class missing from camera_census"
    assert hasattr(PersonCensus, "_resolve_face_entity_id"), (
        "PersonCensus._resolve_face_entity_id missing — presence."
        "_get_face_for_camera would silently fall back to the bare-string "
        "path and lose `_2`-suffix tolerance"
    )
    assert callable(getattr(PersonCensus, "_resolve_face_entity_id")), (
        "PersonCensus._resolve_face_entity_id is not callable"
    )


def test_face_resolver_no_sensor_returns_none():
    """Absent face sensor -> None (accelerator, not requirement)."""
    hass = make_hass()
    _install_states(hass, {})
    hass.data = {DOMAIN: {"census": _make_census(hass)}}

    coord = _stub_coord(hass)
    result = coord._get_face_for_camera("binary_sensor.nowhere_person_occupancy")
    assert result is None
