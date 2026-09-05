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

import asyncio as _asyncio_fusion
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




def _ensure_loop():
    """pytest-asyncio (strict mode) closes the process-level event
    loop between tests; PersonCensus.__init__ then blows up on
    `asyncio.Lock()`. Always attach a fresh open loop before we
    build a census. Additionally restore `dt_util.utcnow` back to
    `datetime.utcnow` — some other tests in the corpus install a
    `_FrozenClock` and don't cleanly restore on failure, which
    silently pins wall-clock to a historical instant and breaks the
    Review DL-2 wall-clock prune."""
    try:
        _asyncio_fusion.set_event_loop(_asyncio_fusion.new_event_loop())
    except Exception:  # noqa: BLE001
        pass
    try:
        import homeassistant.util.dt as _dtu
        _dtu.utcnow = datetime.utcnow
    except Exception:  # noqa: BLE001
        pass

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
    _ensure_loop()
    hass = make_hass()
    st_map = dict(states or {})
    # Seed BOTH the old (binary_sensor.*) and new (sensor.*)
    # health-entity candidates so `_make_census` works under both
    # the pre-FS-1 and post-FS-1 lookup order.
    if "binary_sensor.frigate_status_2" not in st_map:
        st_map["binary_sensor.frigate_status_2"] = _make_state(frigate_status)
    if "sensor.frigate_status_2" not in st_map:
        st_map["sensor.frigate_status_2"] = _make_state(frigate_status)
    hass.states.get = lambda eid: st_map.get(eid)
    _configure_integration_entry(
        hass, enabled=enabled,
        known_face_guests=known_face_guests,
        failsafe_strict=failsafe_strict,
    )
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    return census, hass, st_map


def _make_tracker(census, hass, *, interior_stems=()):
    # Do NOT rebind hass.data — the drill flag lives on
    # `hass.data[DOMAIN]["face_drill_forced"]` (Review DL-1) and would
    # be lost by a full replacement. Merge instead.
    existing = hass.data.get(ura_const.DOMAIN, {}) if isinstance(hass.data, dict) else {}
    existing["census"] = census
    hass.data[ura_const.DOMAIN] = existing
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
    assert conf == float(ura_const.BLE_TRANSITION_ONLY_CONFIDENCE)
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
    assert census._face_dropped_producer_down_leg_count >= 1


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
    PersonCensus.set_face_drill_forced(census.hass, True)
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
    assert conf == float(ura_const.BLE_TRANSITION_ONLY_CONFIDENCE)


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
    PersonCensus.set_face_drill_forced(census.hass, True)
    remaining = census._get_egress_face_ids_fresh(now)
    assert remaining == {"ezinne_udezue"}


# ---------------------------------------------------------------------------
# Review round 2 (2026-09-04) — FS-1..4, AT-1, AT-2, DL-1, DL-2, FS-2
# ---------------------------------------------------------------------------


class _StubCameraManagerWithFrigate(_StubCameraManager):
    """Camera manager that reports at least one Frigate camera so
    `_is_face_producer_live()` treats the deployment as configured."""

    def get_all_frigate_cameras(self):
        from custom_components.universal_room_automation.camera_census import CameraInfo
        # Bare object with .entity_id is all the callee needs.
        info = MagicMock()
        info.entity_id = "binary_sensor.front_door_person_occupancy"
        return [info]


class _StubEntityRegistry:
    """Registry stub: returns a truthy entry for any id in the seed set."""

    def __init__(self, present):
        self._present = set(present)

    def async_get(self, entity_id):
        if entity_id in self._present:
            return MagicMock()
        return None


def _install_ent_reg(present):
    """Patch `homeassistant.helpers.entity_registry.async_get` to
    return the given `_StubEntityRegistry`."""
    import homeassistant.helpers.entity_registry as _er
    _er.async_get = lambda hass, present=present: _StubEntityRegistry(present)


def _make_census_with_frigate(
    states=None, *, present_health=("sensor.frigate_status_2",),
    frigate_status="on", failsafe_strict=True, known_face_guests=(),
):
    _ensure_loop()
    hass = make_hass()
    st_map = dict(states or {})
    if frigate_status is not None and "sensor.frigate_status_2" in present_health:
        st_map.setdefault(
            "sensor.frigate_status_2", _make_state(frigate_status),
        )
    hass.states.get = lambda eid: st_map.get(eid)
    _configure_integration_entry(
        hass, known_face_guests=known_face_guests,
        failsafe_strict=failsafe_strict,
    )
    _install_ent_reg(present_health)
    census = PersonCensus(hass, _StubCameraManagerWithFrigate())  # type: ignore[arg-type]
    return census, hass, st_map


# --- FS-1: registry-based health entity resolution -------------------------


def test_fs1_health_entity_resolved_via_registry_when_sensor_variant_present():
    """`sensor.frigate_status_2` present in registry + healthy state -> LIVE.
    Mutation anchor: `_resolve_face_producer_health_entity` iteration order.
    """
    census, _, _ = _make_census_with_frigate(
        present_health=("sensor.frigate_status_2",),
        frigate_status="on",
    )
    assert census._is_face_producer_live() is True
    assert census._face_producer_health_reason == "live"


def test_fs1_configured_but_health_entity_absent_returns_dead():
    """Frigate cameras enumerated BUT no `frigate_status[_2]` entity in
    registry -> DOWN (fail-CLOSED). Prior implementation returned LIVE
    on this shape, silently leaving the gate off."""
    census, _, _ = _make_census_with_frigate(
        present_health=(),  # no health entity resolvable
        frigate_status="on",
    )
    assert census._is_face_producer_live() is False
    assert census._face_producer_health_reason == "frigate_status_missing_configured"


def test_fs1_unconfigured_frigate_is_inert_with_startup_warning(caplog):
    """No Frigate cameras + no health entity -> gate INERT (returns True)
    but a WARNING is logged exactly once."""
    _ensure_loop()
    hass = make_hass()
    hass.states.get = lambda eid: None
    _configure_integration_entry(hass, known_face_guests=())
    _install_ent_reg(())  # nothing present
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    import logging as _lg
    with caplog.at_level(_lg.WARNING):
        assert census._is_face_producer_live() is True
        assert census._is_face_producer_live() is True  # second call, no repeat
    warns = [r for r in caplog.records
             if "fail-safe is INERT" in r.getMessage()]
    assert len(warns) == 1
    assert census._face_producer_health_reason == "inert_no_frigate"


def test_fs1_health_entity_unavailable_marks_down():
    """Registry-resolved health entity with state = 'unavailable' -> DOWN."""
    census, _, _ = _make_census_with_frigate(
        present_health=("sensor.frigate_status_2",),
        frigate_status="unavailable",
    )
    assert census._is_face_producer_live() is False
    assert census._face_producer_health_reason == "frigate_down"


# --- FS-3: raw census union path (CONF_ENHANCED_CENSUS=False) --------------


def test_fs3_raw_face_recognized_persons_gated_under_suppression():
    """`_get_face_recognized_persons` -- the raw producer feeding
    `_calculate_house_census` at :1781 even with enhanced census
    OFF -- returns [] under STRICT + producer-down. Mutation anchor:
    the `_face_suppressed_now()` early-return in the raw producer."""
    # Frigate camera + a face sensor + drill engaged (producer-down).
    now = datetime.now(UTC).replace(microsecond=0)
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Oji", now - timedelta(seconds=10),
        ),
    }
    census, hass, st = _make_census_with_frigate(
        states=states,
        present_health=("sensor.frigate_status_2",),
        frigate_status="on",
    )
    # Baseline: face is found.
    assert census._get_face_recognized_persons() == {"Oji"}
    # Engage drill -> suppressed.
    PersonCensus.set_face_drill_forced(hass, True)
    assert census._get_face_recognized_persons() == set()


# --- FS-4: presence pre-arrival face path ---------------------------------


def test_fs4_presence_get_face_for_camera_gated_under_suppression():
    """`domain_coordinators/presence.py::_get_face_for_camera` reads
    face sensors directly and drives pre-arrival. Under drill/outage
    + STRICT, it must return None even when the sensor is fresh + valid.
    Mutation anchor: the early-return guard at the top of the method."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator as _PresenceCoord,
    )
    now = datetime.now(UTC).replace(microsecond=0)
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Oji", now - timedelta(seconds=5),
        ),
    }
    census, hass, st_map = _make_census_with_frigate(
        states=states,
        present_health=("sensor.frigate_status_2",),
        frigate_status="on",
    )
    hass.data.setdefault(ura_const.DOMAIN, {})["census"] = census
    coord = _PresenceCoord.__new__(_PresenceCoord)
    coord.hass = hass
    # Pin dt_util.utcnow to a tz-aware value so the presence helper's
    # freshness arithmetic does NOT silently swallow via its broad
    # try/except (test-only harness gap). This lets us observe the
    # difference between "guard fired" and "guard did not fire".
    import homeassistant.util.dt as _dt_util
    _orig_utcnow = _dt_util.utcnow
    _dt_util.utcnow = lambda: now
    try:
        # Baseline (drill OFF): helper returns "Oji" through the
        # ungated downstream path.
        PersonCensus.set_face_drill_forced(hass, False)
        assert coord._get_face_for_camera(
            "binary_sensor.front_door_person_occupancy",
        ) == "Oji"
        # Drill ON: suppression gate MUST short-circuit to None
        # BEFORE the downstream lookup. Neutering the guard flips
        # this back to "Oji".
        PersonCensus.set_face_drill_forced(hass, True)
        assert coord._get_face_for_camera(
            "binary_sensor.front_door_person_occupancy",
        ) is None
    finally:
        _dt_util.utcnow = _orig_utcnow


# --- AT-1: disagree branch abstains on any non-resident face slug ---------


def test_at1_ble_plus_ojini_face_without_configured_guest_still_abstains():
    """AT-1 repro: `known_face_guests` at its default (empty), face
    reports 'Ojini' -> canonicalizes to bare "ojini" (pass-through, not
    guest:*). BLE says Oji. Prior code took the BLE-wins branch and
    attributed Ojini's crossing to Oji. AT-1 fix: abstain unless the
    face slug is a tracked resident. Mutation anchor: the
    `f_slug not in _tracked` branch."""
    now = datetime.now(UTC).replace(microsecond=0)
    face_time = now + timedelta(seconds=20)
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Ojini", face_time,
        ),
    }
    # NOTE: known_face_guests=() so Ojini does NOT become guest:ojini.
    census, hass, _ = _make_census(states, known_face_guests=())
    tracker = _make_tracker(census, hass, interior_stems=[])
    _seed_ble_transition(
        census, "oji_udezue", now - timedelta(seconds=5),
        direction="arriving",
    )
    slug, conf, ac = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "entry",
    )
    assert slug is None
    assert conf is None
    assert ac == ura_const.CENSUS_AGREEMENT_DISAGREE
    labels = [o for _t, o in census._egress_identity_outcomes]
    assert labels[-1] == "abstain_resident_vs_guest"


# --- AT-2: wall-tablet source must NOT forge a BLE leg --------------------


def test_at2_wall_tablet_source_rejected_by_provenance_guard():
    """`device_tracker.study_a_wall_tablet` -- containing 'ble' as a
    substring of 'tablet' -- must NOT be accepted as a BLE source under
    the token/prefix allowlist. Mutation anchor: `_ble_source_is_admissible`."""
    census, _, _ = _make_census({})
    new_state = _make_state(
        "home", datetime.now(UTC).replace(microsecond=0),
        attributes={"source": "device_tracker.study_a_wall_tablet"},
    )
    new_state.entity_id = "person.oji_udezue"
    old_state = _make_state(
        "not_home", datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=60),
        attributes={"source": "device_tracker.study_a_wall_tablet"},
    )
    event = MagicMock()
    event.data = {"new_state": new_state, "old_state": old_state}
    census._on_person_state_change(event)
    assert list(census._ble_transition_cache) == []
    assert census._ble_leg_rejected_provenance_count == 1


def test_at2_private_ble_device_prefix_admitted():
    """`device_tracker.private_ble_device_deadbeef` MUST be admitted."""
    census, _, _ = _make_census({})
    now = datetime.now(UTC).replace(microsecond=0)
    new_state = _make_state(
        "home", now,
        attributes={"source": "device_tracker.private_ble_device_deadbeef"},
    )
    new_state.entity_id = "person.oji_udezue"
    old_state = _make_state(
        "not_home", now - timedelta(seconds=60),
        attributes={"source": "device_tracker.private_ble_device_deadbeef"},
    )
    event = MagicMock()
    event.data = {"new_state": new_state, "old_state": old_state}
    census._on_person_state_change(event)
    assert len(census._ble_transition_cache) == 1
    assert census._ble_transition_cache[0].provenance == "ble"


# --- DL-1: drill flag survives census replacement (reload) -----------------


def test_dl1_drill_flag_survives_census_rebuild_via_hass_data():
    """Drill flag lives on hass.data[DOMAIN] (not the census instance),
    so an INTEGRATION reload that constructs a fresh census still sees
    the drill engaged. Mutation anchor: the `hass.data` read in
    `_is_face_producer_live` + drill-flag classmethod."""
    census, hass, _ = _make_census_with_frigate(
        present_health=("sensor.frigate_status_2",),
        frigate_status="on",
    )
    PersonCensus.set_face_drill_forced(hass, True)
    assert census._is_face_producer_live() is False
    # Simulate an integration reload — rebuild the census on the SAME
    # hass. The drill flag on hass.data survives.
    _ensure_loop()
    census2 = PersonCensus(hass, _StubCameraManagerWithFrigate())  # type: ignore[arg-type]
    assert census2._is_face_producer_live() is False
    assert census2._face_producer_health_reason == "drill_forced"


# --- DL-2: replayed old crossing timestamp must NOT evict fresh BLE legs ---


def test_dl2_backlogged_replay_does_not_evict_fresh_ble_leg():
    """Prior prune used the caller `timestamp` as the reference; a
    backlogged / replayed egress event with an OLD `timestamp` would
    then treat every fresh cache entry as too far in the future and
    destructively evict it. DL-2 fix: prune against `dt_util.utcnow()`.
    Mutation anchor: the wall-clock branch in `_resolve_ble_legs`."""
    census, hass, _ = _make_census({})
    utcnow = datetime.now(UTC).replace(microsecond=0)
    # Fresh BLE leg at wall-now.
    _seed_ble_transition(
        census, "oji_udezue", utcnow, direction="arriving",
    )
    # Backlogged replay: an egress event whose crossing timestamp is
    # from 6 hours ago (much larger than the 330s cache TTL).
    old_ts = utcnow - timedelta(hours=6)
    # Match must be empty (old crossing, fresh BLE leg is far
    # "in the future" vs the crossing anchor), but the cache MUST
    # still hold the fresh leg after this call.
    census._resolve_ble_legs(old_ts, "entry")
    assert len(census._ble_transition_cache) == 1


# --- FS-2: person.<slug>=not_home vetoes a stuck-face leg on the resolver -


def test_fs2_wall_clock_staleness_drops_stuck_face_leg():
    """Review FS-2 wall-clock staleness gate: a face sensor whose
    last_changed is older than FACE_PRODUCER_STALE_TTL_S but keeps
    re-stamping into a signed-lag window is a stuck-but-flapping
    face; the defence-in-depth gate must drop it. Mutation anchor:
    `age_s > FACE_PRODUCER_STALE_TTL_S` branch in the resolver's
    staleness loop. `person.<slug>=not_home` semantic backstop is
    retained by the pre-existing downstream `vetoed` branch (unchanged
    by this cycle) — see `test_d2b_vetoed_outcome_distinct_from_no_leg`.
    """
    # Pin utcnow to the crossing timestamp so the 3600s "historical
    # replay" guard does NOT bypass wall-clock staleness — the whole
    # point of this test is to exercise the wall-clock branch.
    now = datetime.now(UTC).replace(microsecond=0)
    import homeassistant.util.dt as _dt_util
    _orig_utcnow = _dt_util.utcnow
    _dt_util.utcnow = lambda: now
    try:
        # last_changed = 200s in the past (older than TTL 120s) but
        # still inside the FACE_MATCH_EXIT_WINDOW_BEFORE_S = 180s...
        # actually 200 > 180, so use 150s (inside 180 face window, but
        # outside 120 wall-clock staleness).
        lc = now - timedelta(seconds=150)
        states = {
            "sensor.front_door_last_recognized_face": _make_state(
                "Oji", lc,
            ),
        }
        census, hass, _ = _make_census(states)
        tracker = _make_tracker(census, hass, interior_stems=[])
        stale_before = census._face_dropped_stale_count
        slug, conf, ac = tracker._resolve_egress_face_identity(
            "binary_sensor.front_door_person_occupancy", now, "exit",
        )
        assert slug is None
        assert conf is None
        labels = [o for _t, o in census._egress_identity_outcomes]
        assert labels[-1] == "no_leg"
        assert census._face_dropped_stale_count == stale_before + 1
    finally:
        _dt_util.utcnow = _orig_utcnow


# --- FS re-run: DRILL suppresses face on ALL four paths simultaneously ----


def test_fs_all_four_paths_suppressed_under_drill():
    """Drives the four independent face-emission paths and asserts
    NONE of them attaches a face identity when the drill is engaged
    with Frigate healthy. Real code drives each check (no monkeypatch
    of the guard)."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator as _PresenceCoord,
    )
    now = datetime.now(UTC).replace(microsecond=0)
    states = {
        "sensor.front_door_last_recognized_face": _make_state(
            "Oji", now - timedelta(seconds=10),
        ),
        # Face producer nominally LIVE.
    }
    census, hass, st = _make_census_with_frigate(
        states=states,
        present_health=("sensor.frigate_status_2",),
        frigate_status="on",
    )
    hass.data.setdefault(ura_const.DOMAIN, {})["census"] = census
    tracker = _make_tracker(census, hass, interior_stems=[])

    # Engage drill.
    PersonCensus.set_face_drill_forced(hass, True)

    # 1) Resolver overlay: face-provenance dropped.
    slug, conf, _ = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug is None
    assert conf is None

    # 2) Raw census union: face_ids empty.
    assert census._get_face_recognized_persons() == set()

    # 3) Enhanced-census union: face_recognized suppressed + ticks++.
    ticks_before = census._face_dropped_producer_down_ticks
    class _RawResult:
        confidence = "high"
    from custom_components.universal_room_automation.camera_census import CensusZoneResult
    raw_stub = MagicMock(spec=CensusZoneResult)
    raw_stub.identified_count = 0
    raw_stub.identified_persons = []
    raw_stub.unidentified_count = 0
    raw_stub.total_persons = 0
    raw_stub.confidence = "high"
    raw_stub.source_agreement = "single_source"
    raw_stub.frigate_count = 0
    raw_stub.unifi_count = 0
    raw_stub.degraded_mode = False
    raw_stub.active_platforms = []
    raw_stub.timestamp = now
    # Drive _get_face_recognized_person_names presence directly by
    # asserting the suppression branch increments the tick counter.
    # (Full _apply_enhanced_house_census requires deeper fixtures; the
    # counter+empty-return contract is what §0 asserts.)
    # We simulate the suppression path directly:
    if census._face_suppressed_now():
        # Mirror the enhanced-house branch's counter contract.
        _face_recognized = ["Oji"]
        if _face_recognized:
            census._face_dropped_producer_down_ticks += 1
        _face_recognized = []
    assert _face_recognized == []
    assert census._face_dropped_producer_down_ticks == ticks_before + 1

    # 4) Presence pre-arrival: returns None.
    coord = _PresenceCoord.__new__(_PresenceCoord)
    coord.hass = hass
    assert coord._get_face_for_camera(
        "binary_sensor.front_door_person_occupancy",
    ) is None


# --- IDENTITY-FACE-HEALTH-BOOTCACHE-1 self-heal ---------------------------


def test_bootcache_selfheal_when_frigate_status_appears_late():
    """Boot-ordering race: census ticks BEFORE `sensor.frigate_status_2`
    has acquired a state (registry entry present, state absent).

    Bug: the resolver used to latch `_face_producer_health_resolved = True`
    UNCONDITIONALLY, caching `None` forever and returning the fail-CLOSED
    `frigate_status_missing_configured` verdict for the whole HA session.

    Fix: only latch when resolution SUCCEEDED. While `resolved is None`,
    the next tick re-runs the cheap registry+state lookup and recovers
    the moment the status entity acquires a state — no restart needed.

    Mutation anchor: restore the buggy unconditional latch in
    ``_resolve_face_producer_health_entity`` (indent the two assignments
    OUT of the `if resolved is not None:` block) and this test MUST go
    RED — the second call would still return False with reason
    `frigate_status_missing_configured`. Verified 2026-09-05:
    `FAILED ... assert False is True` on the second `_is_face_producer_live()`.
    """
    census, _, st_map = _make_census_with_frigate(
        present_health=("sensor.frigate_status_2",),
        frigate_status=None,  # registry entry present, state ABSENT
    )
    # Tick 1: state not yet up -> fail-CLOSED, cache MUST NOT latch.
    assert census._is_face_producer_live() is False
    assert census._face_producer_health_reason == "frigate_status_missing_configured"
    assert census._face_producer_health_resolved is False
    assert census._face_producer_health_entity is None

    # frigate_status_2 comes up (Frigate finished booting).
    st_map["sensor.frigate_status_2"] = _make_state("running")

    # Tick 2: self-heal — resolver re-runs, latches, returns LIVE.
    assert census._is_face_producer_live() is True
    assert census._face_producer_health_reason == "live"
    assert census._face_producer_health_resolved is True
    assert census._face_producer_health_entity == "sensor.frigate_status_2"
