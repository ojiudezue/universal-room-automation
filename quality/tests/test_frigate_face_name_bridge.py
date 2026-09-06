"""FRIGATE-SUBLABEL-FACE-BRIDGE-1 (2026-09-06) tests.

Drives the PRODUCTION `PersonCensus` code paths added by the cycle:
  - `_on_frigate_face_msg` — MQTT payload -> latch write.
  - `_resolve_face_legs` — additive synthetic FaceLeg emission.
  - `async_register_frigate_face_listener` — inert on MQTT-absent.

Each test's failing assertion pins a specific line/behavior in
`camera_census.py` so a per-site neuter of that line makes exactly
this test fail (mutation anchor).
"""

from __future__ import annotations

import asyncio
import json
import sys as _sys
import types as _types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs
from _provenance_harness import make_hass


# Stubs identical to test_egress_face_identity_d1.py — see that file
# for the pollution-isolation rationale (C-MED-1).
if "homeassistant.helpers.area_registry" not in _sys.modules:
    _mod = _types.ModuleType("homeassistant.helpers.area_registry")
    _mod.async_get = MagicMock()
    _sys.modules["homeassistant.helpers.area_registry"] = _mod
if "homeassistant.helpers.event" not in _sys.modules:
    _ev = _types.ModuleType("homeassistant.helpers.event")
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _sys.modules["homeassistant.helpers.event"] = _ev


from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    FaceLeg,
    PersonCensus,
)


UTC = timezone.utc


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------
class _StubResolver:
    """Minimal CameraResolver surface exercised by the bridge."""
    def __init__(self, frig_index=None, stems=None, dev_id_map=None):
        self._frigate_stem_to_device_ids = dict(frig_index or {})
        self._stems = dict(stems or {})
        self._dev_id_map = dict(dev_id_map or {})

    def _compute_device_stems(self, device_ids):
        return {d: self._stems.get(d) for d in device_ids if d in self._stems}

    def resolve_entity_to_device_id(self, entity_id):
        return self._dev_id_map.get(entity_id)


class _StubCameraManager:
    def __init__(self, resolver=None):
        self._resolver = resolver

    def _get_resolver(self):
        return self._resolver

    # unused surfaces for these tests
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, camera_entity_ids):
        return []


def _configure_integration_entry(hass):
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_ENHANCED_CENSUS: True,
        "tracked_persons": ["person.oji_udezue"],
    }
    hass.config_entries.async_entries.return_value = [entry]


def _make_census(resolver=None, states=None) -> PersonCensus:
    hass = make_hass()
    st_map = dict(states or {})
    hass.states.get = lambda entity_id: st_map.get(entity_id)
    _configure_integration_entry(hass)
    mgr = _StubCameraManager(resolver)
    return PersonCensus(hass, mgr)  # type: ignore[arg-type]


def _msg(payload):
    m = MagicMock()
    m.payload = json.dumps(payload) if isinstance(payload, dict) else payload
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_face_msg_known_camera_latches_and_emits_synthetic_leg():
    """A `type=="face"` message for a known Frigate camera → latch
    entry + synthetic FaceLeg with canonical_slug + last_changed=ts."""
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        stems={"dev_fd": "front_door"},
    )
    census = _make_census(resolver=resolver)
    census._on_frigate_face_msg(_msg({
        "type": "face", "camera": "front_door", "name": "Oji Udezue",
    }))
    # Latch write (mutation anchor: the `self._frigate_face_latch[stem] = ...`
    # line in _on_frigate_face_msg).
    assert "front_door" in census._frigate_face_latch
    lname, lts = census._frigate_face_latch["front_door"]
    assert lname == "Oji Udezue"
    assert lts is not None

    legs = census._resolve_face_legs("front_door")
    # Synthetic leg emission (mutation anchor: the `results.append(synthetic)`
    # inside _resolve_face_legs's latch block).
    assert len(legs) == 1
    leg = legs[0]
    assert isinstance(leg, FaceLeg)
    assert leg.canonical_slug is not None and leg.canonical_slug != ""
    # last_changed=ts is REQUIRED (classifier keys on it).
    assert leg.last_changed == lts
    # engine defaults to frigate/frigate2 (F1 retired, both permitted).
    assert leg.engine in ("frigate", "frigate2")
    # confidence=None passes the FACE_MATCH_MIN_CONFIDENCE floor.
    assert leg.confidence is None
    assert leg.base_stem == "front_door"


def test_face_msg_non_face_type_is_ignored():
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        stems={"dev_fd": "front_door"},
    )
    census = _make_census(resolver=resolver)
    census._on_frigate_face_msg(_msg({
        "type": "person", "camera": "front_door", "name": "Oji",
    }))
    # Mutation anchor: the `if data.get("type") != "face": return` guard.
    assert census._frigate_face_latch == {}
    assert census._resolve_face_legs("front_door") == []


def test_face_msg_unknown_camera_dropped_with_counter():
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]},
                             stems={"dev_fd": "front_door"})
    census = _make_census(resolver=resolver)
    before = census._frigate_face_msg_dropped_count
    census._on_frigate_face_msg(_msg({
        "type": "face", "camera": "unknown_cam", "name": "Oji",
    }))
    # Mutation anchor: the collision guard `if not device_ids: drop`.
    assert census._frigate_face_latch == {}
    assert census._frigate_face_msg_dropped_count == before + 1


def test_ttl_prune_older_than_ttl_not_emitted():
    from custom_components.universal_room_automation.const import (
        FACE_NAME_LATCH_TTL_S,
    )
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        stems={"dev_fd": "front_door"},
    )
    census = _make_census(resolver=resolver)
    # Plant a stale latch entry directly (bypass cb to control ts).
    # Use dt_util so tz-awareness matches the census's own clock in
    # the test harness (naive) — real HA is tz-aware end-to-end.
    from homeassistant.util import dt as _dt_util
    stale_ts = _dt_util.utcnow() - timedelta(
        seconds=FACE_NAME_LATCH_TTL_S + 60,
    )
    census._frigate_face_latch["front_door"] = ("Oji Udezue", stale_ts)
    # Mutation anchor: the `age <= FACE_NAME_LATCH_TTL_S` gate in the
    # _resolve_face_legs latch block. A neuter removing the gate would
    # return the stale name and fail this assertion.
    legs = census._resolve_face_legs("front_door")
    assert legs == []


def test_dedup_no_boost_when_latch_matches_entity_leg():
    """If a live entity leg already carries the same canonical name +
    engine + base_stem, the latch must DEDUP (not append a duplicate)
    to avoid a spurious agreement boost in the corroboration
    classifier."""
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        stems={"dev_fd": "front_door"},
    )
    # Live Frigate F2 entity carrying the same name. Use the same
    # dt_util clock the census code uses so the tz-awareness matches
    # (avoids a naive-vs-aware comparison inside the dedup block).
    from homeassistant.util import dt as _dt_util
    entity_ts = _dt_util.utcnow() - timedelta(seconds=5)
    entity_state = MagicMock()
    entity_state.state = "Oji Udezue"
    entity_state.last_changed = entity_ts
    entity_state.attributes = {}
    census = _make_census(
        resolver=resolver,
        states={"sensor.front_door_last_recognized_face_2": entity_state},
    )
    # Latch a fresher entry via the cb.
    census._on_frigate_face_msg(_msg({
        "type": "face", "camera": "front_door", "name": "Oji Udezue",
    }))
    legs = census._resolve_face_legs("front_door")
    # Mutation anchor: the dedup check (`_dup_idx` scan) inside
    # _resolve_face_legs. Neutering the dedup would produce 2 legs.
    assert len(legs) == 1
    # Fresher last_changed wins.
    latched_ts = census._frigate_face_latch["front_door"][1]
    assert legs[0].last_changed == latched_ts


def test_failsafe_is_caller_side_not_census_side():
    """Plan §5 fence: `_resolve_face_legs` must add NO new suppression
    gate. Suppression is applied by the CALLER
    (`transit_validator._resolve_egress_face_identity`, which drops
    ALL legs under drill/outage). This test asserts that the synthetic
    leg emit path is NOT gated on `_face_suppressed_now` at the
    producer — i.e. it emits regardless — so the caller-side fail-safe
    remains the single point of truth. Mutation anchor: any future
    addition of a `_face_suppressed_now` gate inside the latch block
    would flip the emit to [] and fail this test."""
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        stems={"dev_fd": "front_door"},
    )
    census = _make_census(resolver=resolver)
    # Force any hypothetical suppression hook to True — behavior must
    # be unchanged (caller owns the drop, not the producer).
    try:
        census._face_suppressed_now = lambda *a, **kw: True  # type: ignore[assignment]
    except Exception:
        pass
    census._on_frigate_face_msg(_msg({
        "type": "face", "camera": "front_door", "name": "Oji Udezue",
    }))
    legs = census._resolve_face_legs("front_door")
    assert len(legs) == 1  # producer emits; caller is responsible for drop


def test_mqtt_unloaded_register_is_inert():
    """If `homeassistant.components.mqtt` is absent or `async_subscribe`
    raises, register leaves the bridge inert (unsub None) and does NOT
    raise. The entity point-read path is unaffected."""
    census = _make_census(resolver=None)

    # Force the import path to raise by installing a stub mqtt module
    # whose `async_subscribe` raises. This exercises the register
    # try/except (mutation anchor: the outer `except Exception: return`
    # around the subscribe call).
    saved = _sys.modules.get("homeassistant.components.mqtt")
    fake = _types.ModuleType("homeassistant.components.mqtt")

    async def _boom(*a, **kw):
        raise RuntimeError("mqtt unloaded")

    fake.async_subscribe = _boom
    _sys.modules["homeassistant.components.mqtt"] = fake
    try:
        asyncio.get_event_loop().run_until_complete(
            census.async_register_frigate_face_listener()
        ) if False else asyncio.new_event_loop().run_until_complete(
            census.async_register_frigate_face_listener()
        )
    finally:
        if saved is None:
            _sys.modules.pop("homeassistant.components.mqtt", None)
        else:
            _sys.modules["homeassistant.components.mqtt"] = saved
    # Bridge inert.
    assert census._frigate_face_unsub is None
    # Point-read path unaffected: no latch, empty legs.
    assert census._resolve_face_legs("front_door") == []
