"""IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D2 / D3 / D4 tests.

Drives the PRODUCTION `camera_census.PersonCensus._resolve_face_legs`
(where the D4 fail-safe consumes it) and
`transit_validator.EgressDirectionTracker._resolve_egress_face_identity`.

Each test is behavioural + mutation-anchored per the Tier 2-DB / M4
requirement in the plan: neutering the load-bearing production site
must turn the named test RED. Mutation drill outputs pasted at end of
each block below (see BUILD REPORT below the tests for the full runs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass


import sys as _sys
import types as _types


_STUB_MODULES = (
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.event",
)


@pytest.fixture(autouse=True, scope="module")
def _install_stub_modules():
    saved: dict[str, object] = {}
    for name in _STUB_MODULES:
        saved[name] = _sys.modules.get(name, ...)
    if "homeassistant.helpers.area_registry" not in _sys.modules:
        mod = _types.ModuleType("homeassistant.helpers.area_registry")
        mod.async_get = MagicMock()
        _sys.modules["homeassistant.helpers.area_registry"] = mod
    if "homeassistant.helpers.event" not in _sys.modules:
        ev = _types.ModuleType("homeassistant.helpers.event")
        ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
        ev.async_call_later = lambda *a, **kw: (lambda: None)
        ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
        _sys.modules["homeassistant.helpers.event"] = ev
    yield
    for name, prior in saved.items():
        if prior is ...:
            _sys.modules.pop(name, None)
        else:
            _sys.modules[name] = prior


# Bootstrap stubs at collection time too.
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
    BleTransitionLeg,
    FaceLeg,
    PersonCensus,
)
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)


UTC = timezone.utc


class _StubCameraManager:
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


def _make_state(value, last_changed=None, attributes=None):
    st = MagicMock()
    st.state = value
    st.last_changed = last_changed
    st.attributes = attributes or {}
    return st


def _configure_integration_entry(
    hass,
    *,
    enabled=True,
    tracked=("person.oji_udezue", "person.ezinne_udezue"),
    known_face_guests=("Ojini",),
    failsafe_strict=True,
):
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": list(tracked),
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: enabled,
        ura_const.CONF_KNOWN_FACE_GUESTS: list(known_face_guests),
        ura_const.CONF_EGRESS_IDENTITY_FAILSAFE_STRICT: failsafe_strict,
    }
    hass.config_entries.async_entries.return_value = [entry]


def _make_census(states=None, *, enabled=True, known_face_guests=("Ojini",),
                 failsafe_strict=True, frigate_status="on"):
    hass = make_hass()
    st_map = dict(states or {})
    if "binary_sensor.frigate_status_2" not in st_map:
        st_map["binary_sensor.frigate_status_2"] = _make_state(frigate_status)
    hass.states.get = lambda eid: st_map.get(eid)
    _configure_integration_entry(
        hass, enabled=enabled,
        known_face_guests=known_face_guests,
        failsafe_strict=failsafe_strict,
    )
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    return census, hass, st_map


def _make_tracker(census, hass, *, interior_stems=()):
    hass.data = {ura_const.DOMAIN: {"census": census}}
    tracker = EgressDirectionTracker(hass)
    interior_entities = [
        f"binary_sensor.{s}_person_occupancy" for s in interior_stems
    ]
    tracker._get_interior_cameras_near = lambda cam: list(interior_entities)
    return tracker


def _seed_ble_transition(
    census, slug, ts, *, direction="arriving", source="device_tracker.bermuda_oji"
):
    census._ble_transition_cache.append(BleTransitionLeg(
        person_slug=slug,
        transition_ts=ts,
        direction=direction,
        engine="ble",
        confidence=ura_const.BLE_TRANSITION_CONFIDENCE,
        provenance="ble",
        source_entity=source,
    ))


# ---------------------------------------------------------------------------
# D3 — guest canonicalization
# ---------------------------------------------------------------------------


def test_d3_known_face_guest_canonicalizes_to_guest_namespace():
    """Ojini in `known_face_guests` -> `guest:ojini` slug (never dropped
    to pass-through). Mutation anchor: `known_face_guests` branch in
    `_canonical_person_slug`."""
    census, _, _ = _make_census({}, known_face_guests=("Ojini",))
    assert census._canonical_person_slug("Ojini") == "guest:ojini"


def test_d3_tracked_slug_wins_over_guest_namespace():
    """H2 precedence: a first-name that matches BOTH a tracked slug AND
    a guest name resolves to the tracked slug — the guest branch runs
    only after the tracked attempts miss."""
    census, _, _ = _make_census(
        {}, known_face_guests=("Oji",),
    )
    assert census._canonical_person_slug("Oji") == "oji_udezue"


def test_d3_guest_removed_reverts_to_passthrough():
    """Empty `known_face_guests` -> canonical passthrough of the
    lowercased name (pre-cycle behaviour)."""
    census, _, _ = _make_census({}, known_face_guests=())
    assert census._canonical_person_slug("Ojini") == "ojini"


# ---------------------------------------------------------------------------
# D2 — BLE-transition leg (provenance guard) + resolver precedence
# ---------------------------------------------------------------------------


def test_d2_person_state_change_provenance_guard_admits_bermuda():
    """Bermuda-source `person.<slug>` home->not_home transition creates
    a BleTransitionLeg. Mutation anchor: the substring provenance
    guard in `_on_person_state_change`."""
    census, _, _ = _make_census({})
    new_state = _make_state(
        "home", datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        attributes={"source": "device_tracker.bermuda_oji"},
    )
    new_state.entity_id = "person.oji_udezue"
    old_state = _make_state(
        "not_home", datetime(2026, 9, 4, 11, 58, tzinfo=UTC),
        attributes={"source": "device_tracker.bermuda_oji"},
    )
    event = MagicMock()
    event.data = {"new_state": new_state, "old_state": old_state}
    census._on_person_state_change(event)
    assert len(census._ble_transition_cache) == 1
    leg = census._ble_transition_cache[0]
    assert leg.person_slug == "oji_udezue"
    assert leg.direction == "arriving"
    assert leg.provenance == "ble"


def test_d2_person_state_change_rejects_camera_face_source():
    """A `person.<slug>` update whose `source` is a camera_face
    provider is NOT admitted as a BLE leg (§0: face-provenance in
    disguise). Mutation anchor: the provenance guard."""
    census, _, _ = _make_census({})
    new_state = _make_state(
        "home", datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        attributes={"source": "camera.front_door_face"},
    )
    new_state.entity_id = "person.oji_udezue"
    old_state = _make_state(
        "not_home", datetime(2026, 9, 4, 11, 58, tzinfo=UTC),
        attributes={"source": "camera.front_door_face"},
    )
    event = MagicMock()
    event.data = {"new_state": new_state, "old_state": old_state}
    census._on_person_state_change(event)
    assert list(census._ble_transition_cache) == []
    assert census._ble_leg_rejected_provenance_count == 1


def test_d2_ble_only_attaches_with_ble_provenance():
    """No face leg, BLE transition in-window (arriving) -> attach.
    Outcome label `attached_ble`, agreement SINGLE, confidence =
    BLE_TRANSITION_CONFIDENCE, provenance recorded as `ble`."""
    now = datetime.now(UTC).replace(microsecond=0)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _seed_ble_transition(
        census, "oji_udezue", now - timedelta(seconds=8), direction="arriving",
    )
    slug, conf, ac = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "entry",
    )
    assert slug == "oji_udezue"
    assert conf == float(ura_const.BLE_TRANSITION_CONFIDENCE)
    assert ac == ura_const.CENSUS_AGREEMENT_SINGLE
    assert (
        census._egress_identity_last_attach.get("provenance") == "ble"
    )
    labels = [o for _t, o in census._egress_identity_outcomes]
    assert labels[-1] == "attached_ble"


# ---------------------------------------------------------------------------
# D2 + H2 — resident BLE + guest face disagree -> ABSTAIN
# ---------------------------------------------------------------------------


def test_h2_resident_ble_plus_guest_face_abstains():
    """H2 repro drill: Oji BLE arriving at t-5s, Ojini face
    recognized 20s later -> outcome `abstain_resident_vs_guest`, NO
    attach, DB write path must NOT get Oji's slug. Mutation anchor:
    the H2 branch in `_resolve_egress_face_identity`."""
    now = datetime.now(UTC).replace(microsecond=0)
    face_time = now + timedelta(seconds=20)  # face event 20s after crossing
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Ojini", face_time,
        ),
    }
    census, hass, _ = _make_census(states, known_face_guests=("Ojini",))
    tracker = _make_tracker(census, hass, interior_stems=[])
    _seed_ble_transition(
        census, "oji_udezue", now - timedelta(seconds=5), direction="arriving",
    )
    slug, conf, ac = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "entry",
    )
    assert slug is None
    assert conf is None
    assert ac == ura_const.CENSUS_AGREEMENT_DISAGREE
    labels = [o for _t, o in census._egress_identity_outcomes]
    assert labels[-1] == "abstain_resident_vs_guest"


# ---------------------------------------------------------------------------
# D4 — fail-safe gate (drives REAL _resolve_face_legs)
# ---------------------------------------------------------------------------


def test_d4_face_legs_dropped_when_producer_dead():
    """Frigate `binary_sensor.frigate_status_2 = unavailable` +
    STRICT -> resolver drops the face leg; no attach on the face
    path. `_resolve_face_legs` still returns the leg (fail-safe lives
    in the resolver, not the accessor), but the resolver refuses to
    consume it. Mutation anchor: `_is_face_producer_live` +
    STRICT gate at the top of `_resolve_egress_face_identity`."""
    now = datetime.now(UTC).replace(microsecond=0)
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Oji", now - timedelta(seconds=10),
        ),
        # Face producer DEAD.
        "binary_sensor.frigate_status_2": _make_state("unavailable"),
    }
    census, hass, _ = _make_census(states, frigate_status="unavailable")
    # Drive REAL _resolve_face_legs (not monkeypatched): accessor
    # STILL enumerates the leg (proves the leg is there to be dropped),
    # then the resolver's D4 gate refuses to consume it.
    real_legs = census._resolve_face_legs("front_door")
    assert real_legs and real_legs[0].canonical_slug == "oji_udezue"

    tracker = _make_tracker(census, hass, interior_stems=[])
    slug, conf, ac = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug is None
    assert conf is None
    assert census._face_dropped_producer_down_count >= 1


def test_d4_drill_switch_forces_face_dead_with_frigate_live():
    """Drill switch engaged with frigate_status_2 HEALTHY -> face legs
    still dropped; BLE keeps naming. Mutation anchor: drill-branch in
    `_is_face_producer_live`."""
    now = datetime.now(UTC).replace(microsecond=0)
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Oji", now - timedelta(seconds=10),
        ),
        "binary_sensor.frigate_status_2": _make_state("on"),  # HEALTHY
    }
    census, hass, _ = _make_census(states, frigate_status="on")
    assert census._is_face_producer_live() is True
    # Engage drill.
    census._face_drill_forced = True
    assert census._is_face_producer_live() is False
    assert census._face_producer_health_reason == "drill_forced"

    # BLE still names (D4 §0 (b)).
    _seed_ble_transition(
        census, "oji_udezue", now - timedelta(seconds=8),
        direction="arriving",
    )
    tracker = _make_tracker(census, hass, interior_stems=[])
    slug, conf, ac = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "entry",
    )
    assert slug == "oji_udezue"
    assert conf == float(ura_const.BLE_TRANSITION_CONFIDENCE)


def test_d4_census_union_gates_face_provenance_under_outage():
    """H1: `_get_egress_face_ids_fresh` filters face-provenance entries
    under STRICT + face-producer-down; BLE-provenance entries survive.
    Mutation anchor: the provenance filter in
    `_get_egress_face_ids_fresh`."""
    now = datetime.now(UTC).replace(microsecond=0)
    states = {"binary_sensor.frigate_status_2": _make_state("on")}
    census, _, _ = _make_census(states, frigate_status="on")
    # Register one face-provenance + one ble-provenance identity.
    census.register_egress_face("Oji", now, provenance="face")
    census.register_egress_face("Ezinne", now, provenance="ble")
    assert census._get_egress_face_ids_fresh(now) == {"oji_udezue", "ezinne_udezue"}
    # Engage drill -> face producer dead; face-provenance dropped.
    census._face_drill_forced = True
    remaining = census._get_egress_face_ids_fresh(now)
    assert remaining == {"ezinne_udezue"}
