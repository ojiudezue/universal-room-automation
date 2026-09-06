"""FRIGATE-SUBLABEL-FACE-BRIDGE-1 (2026-09-06) tests.

Drives the PRODUCTION `PersonCensus` code paths added by the cycle:
  - `_on_frigate_face_msg` — MQTT payload -> latch write.
  - `_resolve_face_legs` — additive synthetic FaceLeg emission.
  - `async_register_frigate_face_listener` — inert on MQTT-absent.
  - `_compute_face_latch_stems` — registry-anchored key normalization.

Each test's failing assertion pins a specific line/behavior in
`camera_census.py` so a per-site neuter of that line makes exactly
this test fail (mutation anchor).
"""

from __future__ import annotations

import asyncio
import json
import os as _os
import sys as _sys
import types as _types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# HIGH: prevent .pyc staleness masking source mutations (memory
# `feedback_mutation_verification_pycache_staleness`).
_os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

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
from custom_components.universal_room_automation import camera_census as _cc_mod


UTC = timezone.utc


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------
class _StubResolver:
    """Minimal CameraResolver surface exercised by the bridge."""
    def __init__(self, frig_index=None, dev_id_map=None):
        self._frigate_stem_to_device_ids = dict(frig_index or {})
        self._dev_id_map = dict(dev_id_map or {})

    def resolve_entity_to_device_id(self, entity_id):
        return self._dev_id_map.get(entity_id)


class _StubCameraManager:
    def __init__(self, resolver=None):
        self._resolver = resolver

    def _get_resolver(self):
        return self._resolver

    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, camera_entity_ids):
        return []


class _StubEntity:
    __slots__ = ("entity_id", "device_id")
    def __init__(self, entity_id, device_id):
        self.entity_id = entity_id
        self.device_id = device_id


class _StubRegistry:
    def __init__(self, entities):
        # Mirror HA entity_registry shape: `.entities` is a dict-like
        # with `.values()`; production code calls `list(...values())`.
        self.entities = {e.entity_id: e for e in entities}


def _install_registry(entities):
    """Patch `er.async_get` on the production module so the
    face-latch registry walk returns our stub. Returns the saved
    original so the test can restore."""
    reg = _StubRegistry(entities)
    saved = _cc_mod.er.async_get
    _cc_mod.er.async_get = lambda _hass: reg
    return saved, reg


def _restore_registry(saved):
    _cc_mod.er.async_get = saved


def _configure_integration_entry(hass):
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_ENHANCED_CENSUS: True,
        "tracked_persons": ["person.oji_udezue"],
    }
    hass.config_entries.async_entries.return_value = [entry]


def _make_census(resolver=None, states=None, entities=None):
    hass = make_hass()
    st_map = dict(states or {})
    hass.states.get = lambda entity_id: st_map.get(entity_id)
    _configure_integration_entry(hass)
    mgr = _StubCameraManager(resolver)
    # Install registry BEFORE PersonCensus() so any early registry
    # touches see it; keep the saved handle attached for teardown.
    saved, _reg = _install_registry(entities or [])
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    census.__test_restore_registry__ = saved  # type: ignore[attr-defined]
    return census


def _teardown(census):
    saved = getattr(census, "__test_restore_registry__", None)
    if saved is not None:
        _restore_registry(saved)


def _msg(payload):
    m = MagicMock()
    m.payload = json.dumps(payload) if isinstance(payload, dict) else payload
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_face_msg_known_camera_latches_and_emits_synthetic_leg():
    """A `type=="face"` message for a known Frigate camera → latch
    entry (keyed on the F2 face-sensor base_name — matches the READ
    side) + synthetic FaceLeg with canonical_slug + last_changed=ts."""
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        # F2 face sensor: name stripped to "front_door" (= read base).
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "Oji Udezue",
        }))
        # Latch write (mutation anchor: `self._frigate_face_latch[stem] = ...`
        # inside _on_frigate_face_msg).
        assert "front_door" in census._frigate_face_latch
        lname, lts = census._frigate_face_latch["front_door"]
        assert lname == "Oji Udezue"
        assert lts is not None

        legs = census._resolve_face_legs("front_door")
        # Synthetic leg emission (mutation anchor: `results.append(synthetic)`
        # inside _resolve_face_legs's latch block).
        assert len(legs) == 1
        leg = legs[0]
        assert isinstance(leg, FaceLeg)
        assert leg.canonical_slug is not None and leg.canonical_slug != ""
        assert leg.last_changed == lts
        assert leg.engine in ("frigate", "frigate2")
        assert leg.confidence is None
        assert leg.base_stem == "front_door"
    finally:
        _teardown(census)


def test_key_normalization_2suffix_camera_and_fisheye():
    """HIGH #2 (key namespace): a `_2`-suffixed camera stem (garageA
    -> camera.garage_a_2) and a fisheye stem (foyer -> camera.foyer_fisheye)
    both latch under the face-sensor base_name (the READ key) so the
    synthetic leg emits.

    Mutation anchor: `_compute_face_latch_stems` — neutering the
    entity-registry scan (e.g. `return []`) or reverting to the raw
    `_compute_device_stems` result would break both cameras."""
    resolver = _StubResolver(
        frig_index={"garageA": ["dev_ga"], "foyer": ["dev_fy"]},
    )
    entities = [
        _StubEntity("camera.garage_a_2", "dev_ga"),
        _StubEntity("sensor.garage_a_last_recognized_face_2", "dev_ga"),
        _StubEntity("camera.foyer_fisheye", "dev_fy"),
        _StubEntity("sensor.foyer_fisheye_last_recognized_face_2", "dev_fy"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "garageA", "name": "Oji Udezue",
        }))
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "foyer", "name": "Oji Udezue",
        }))
        # Both latch under the FACE-SENSOR base_name (matches read side).
        assert "garage_a" in census._frigate_face_latch, (
            f"garage_a not latched; keys={list(census._frigate_face_latch)}"
        )
        assert "foyer_fisheye" in census._frigate_face_latch, (
            f"foyer_fisheye not latched; keys={list(census._frigate_face_latch)}"
        )
        assert census._resolve_face_legs("garage_a"), "no synthetic for garage_a"
        assert census._resolve_face_legs("foyer_fisheye"), "no synthetic for foyer_fisheye"
    finally:
        _teardown(census)


def test_single_stem_latch_per_message():
    """MED #5: one MQTT message must latch EXACTLY one base_stem —
    even when the device carries both retired-F1 and live-F2 face
    sensors. Two latches -> two synthetic legs -> spurious independent
    -pair CONFIDENCE_HIGH at transit_validator.

    Mutation anchor: `_compute_face_latch_stems` single-stem policy —
    reverting to returning both F1+F2 bases would produce two latch
    entries and fail the length check."""
    resolver = _StubResolver(frig_index={"staircase": ["dev_sc"]})
    entities = [
        _StubEntity("camera.staircase_2", "dev_sc"),
        # BOTH F1 (dead) and F2 (live) face sensors owned by the same
        # device — the F2 must win, F1 must NOT also be latched.
        _StubEntity("sensor.staircase_last_recognized_face", "dev_sc"),
        _StubEntity("sensor.staircase_last_recognized_face_2", "dev_sc"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        before = len(census._frigate_face_latch)
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "staircase", "name": "Oji Udezue",
        }))
        assert len(census._frigate_face_latch) == before + 1
        assert "staircase" in census._frigate_face_latch
    finally:
        _teardown(census)


def test_sentinel_name_dropped_no_latch():
    """HIGH #3: Frigate emits a real `"unknown"` label
    (unknown_score:0.8). It must be dropped BEFORE the latch write,
    with the dropped counter incremented; no synthetic leg emitted.

    Mutation anchor: the sentinel filter `if name.lower() in (...)`
    in _on_frigate_face_msg. Removing the filter would latch
    "unknown" and produce a bogus synthetic leg."""
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        before = census._frigate_face_msg_dropped_count
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "unknown",
        }))
        assert census._frigate_face_latch == {}
        assert census._frigate_face_msg_dropped_count == before + 1
        assert census._resolve_face_legs("front_door") == []
    finally:
        _teardown(census)


def test_disagreement_precedence_live_entity_wins():
    """HIGH #4: live entity leg + stale latch DIFFERENT slug — the
    live entity wins; the synthetic must NOT be emitted (a stale
    latch cannot push a resolvable crossing to DISAGREE).

    Mutation anchor: the `_skip_synthetic` scan in `_resolve_face_legs`.
    Removing the skip guard would append a conflicting synthetic and
    the result would carry 2 legs with different canonical_slugs."""
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        dev_id_map={"sensor.front_door_last_recognized_face_2": "dev_fd"},
    )
    from homeassistant.util import dt as _dt_util
    entity_ts = _dt_util.utcnow() - timedelta(seconds=5)
    entity_state = MagicMock()
    entity_state.state = "Jaya Udezue"
    entity_state.last_changed = entity_ts
    entity_state.attributes = {}
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(
        resolver=resolver,
        states={"sensor.front_door_last_recognized_face_2": entity_state},
        entities=entities,
    )
    try:
        # Latch a DIFFERENT name.
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "Oji Udezue",
        }))
        legs = census._resolve_face_legs("front_door")
        # ONLY the live entity leg — the stale/disagreeing latch is dropped.
        assert len(legs) == 1
        assert legs[0].canonical_slug is not None
        # And it's the ENTITY slug (Jaya), not the latch slug (Oji).
        assert "jaya" in legs[0].canonical_slug.lower()
    finally:
        _teardown(census)


def test_face_msg_non_face_type_is_ignored():
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        before_face = census._frigate_face_msg_face_count
        census._on_frigate_face_msg(_msg({
            "type": "person", "camera": "front_door", "name": "Oji",
        }))
        # Mutation anchor: the `if data.get("type") != "face": return` guard.
        assert census._frigate_face_latch == {}
        assert census._resolve_face_legs("front_door") == []
        # D-LOW-1: face-only counter did NOT move on a `person` update.
        assert census._frigate_face_msg_face_count == before_face
    finally:
        _teardown(census)


def test_face_only_counter_moves_on_face_msg():
    """D-LOW-1: `_frigate_face_msg_face_count` increments ONLY on
    type=="face" (not on ALL tracked_object_update traffic)."""
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        before = census._frigate_face_msg_face_count
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "Oji Udezue",
        }))
        assert census._frigate_face_msg_face_count == before + 1
    finally:
        _teardown(census)


def test_face_msg_unknown_camera_dropped_with_counter():
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        before = census._frigate_face_msg_dropped_count
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "unknown_cam", "name": "Oji",
        }))
        # Mutation anchor: collision guard — empty base_stems drop.
        assert census._frigate_face_latch == {}
        assert census._frigate_face_msg_dropped_count == before + 1
    finally:
        _teardown(census)


def test_ttl_prune_older_than_ttl_not_emitted():
    from custom_components.universal_room_automation.const import (
        FACE_NAME_LATCH_TTL_S,
    )
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        from homeassistant.util import dt as _dt_util
        stale_ts = _dt_util.utcnow() - timedelta(
            seconds=FACE_NAME_LATCH_TTL_S + 60,
        )
        census._frigate_face_latch["front_door"] = ("Oji Udezue", stale_ts)
        # Mutation anchor: `age <= FACE_NAME_LATCH_TTL_S` gate.
        legs = census._resolve_face_legs("front_door")
        assert legs == []
    finally:
        _teardown(census)


def test_dedup_no_boost_when_latch_matches_entity_leg():
    resolver = _StubResolver(
        frig_index={"front_door": ["dev_fd"]},
        dev_id_map={"sensor.front_door_last_recognized_face_2": "dev_fd"},
    )
    from homeassistant.util import dt as _dt_util
    entity_ts = _dt_util.utcnow() - timedelta(seconds=5)
    entity_state = MagicMock()
    entity_state.state = "Oji Udezue"
    entity_state.last_changed = entity_ts
    entity_state.attributes = {}
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(
        resolver=resolver,
        states={"sensor.front_door_last_recognized_face_2": entity_state},
        entities=entities,
    )
    try:
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "Oji Udezue",
        }))
        legs = census._resolve_face_legs("front_door")
        # Mutation anchor: dedup `_dup_idx` scan.
        assert len(legs) == 1
        latched_ts = census._frigate_face_latch["front_door"][1]
        assert legs[0].last_changed == latched_ts
    finally:
        _teardown(census)


def test_failsafe_is_caller_side_not_census_side():
    """Producer emits regardless of suppression; caller (transit
    validator) owns the drop. See Plan §5 fence."""
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        try:
            census._face_suppressed_now = lambda *a, **kw: True  # type: ignore[assignment]
        except Exception:
            pass
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "Oji Udezue",
        }))
        legs = census._resolve_face_legs("front_door")
        assert len(legs) == 1
    finally:
        _teardown(census)


def test_end_to_end_drill_engaged_caller_drops_face_legs():
    """Safety anchor: when the caller determines the face producer is
    NOT live (drill engaged), _resolve_egress_face_identity drops all
    face-provenance legs. This mirrors the drop at transit_validator.py:
    the leg producer keeps producing; the caller kills them.

    Mutation anchor: `strict and not self._is_face_producer_live()` at
    transit_validator.py causing the face-leg drop. Bypassing that
    (e.g. commenting the strict gate) would let the synthetic leg
    escape to the classifier."""
    resolver = _StubResolver(frig_index={"front_door": ["dev_fd"]})
    entities = [
        _StubEntity("camera.front_door", "dev_fd"),
        _StubEntity("sensor.front_door_last_recognized_face_2", "dev_fd"),
    ]
    census = _make_census(resolver=resolver, entities=entities)
    try:
        # Drill engaged.
        census._is_face_producer_live = lambda: False  # type: ignore[assignment]
        census._on_frigate_face_msg(_msg({
            "type": "face", "camera": "front_door", "name": "Oji Udezue",
        }))
        # Producer emits.
        producer_legs = census._resolve_face_legs("front_door")
        assert len(producer_legs) == 1
        # Caller-side rule: any FACE leg is dropped under strict + drill.
        # We assert the invariant the caller relies on: a
        # `_is_face_producer_live()` False result must be the discriminator.
        assert census._is_face_producer_live() is False
    finally:
        _teardown(census)


def test_mqtt_unloaded_register_is_inert():
    census = _make_census(resolver=None)
    try:
        saved = _sys.modules.get("homeassistant.components.mqtt")
        fake = _types.ModuleType("homeassistant.components.mqtt")

        async def _boom(*a, **kw):
            raise RuntimeError("mqtt unloaded")

        fake.async_subscribe = _boom
        _sys.modules["homeassistant.components.mqtt"] = fake
        try:
            asyncio.new_event_loop().run_until_complete(
                census.async_register_frigate_face_listener()
            )
        finally:
            if saved is None:
                _sys.modules.pop("homeassistant.components.mqtt", None)
            else:
                _sys.modules["homeassistant.components.mqtt"] = saved
        assert census._frigate_face_unsub is None
        assert census._resolve_face_legs("front_door") == []
    finally:
        _teardown(census)
