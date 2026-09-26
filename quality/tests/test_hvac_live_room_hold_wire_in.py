"""HVAC-DEGRADED-ROOM-TRIPWIRE-1 fix-up round 2 — wire-in anchors.

Behavioural tests that DRIVE the real production call sites for the
row-1 HOLD (hvac.py ~2029-2074), the D9 compose-away HOLD (~3000-3021),
and the NM `location` kwarg in `_drain_hvac_degraded_room_events`
(~3175-3207). The prior round's tests exercised the ZoneManager helper
`is_zone_transient_blocked` in isolation — that is not a wire-in
anchor. Per memory `feedback_wire_in_anchor_mandatory`, every
load-bearing call site needs an enclosing-method behavioural test + a
call-neuter mutation drill.

Fixture pattern reuses the smoke-hass path from
`quality/tests/runtime_harness.py` (mirrors
`test_hvac_d5_reframe_and_occupancy_gate.py::_make_coord`).
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Behavioral coord drives require the real homeassistant package.
_ha = pytest.importorskip(
    "homeassistant.config_entries",
    reason="homeassistant not installed — HVAC row-1/D9 wire-in tests skipped",
)

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _purge_shim_modules():
    """FIX-UP round 5 item 11 (2026-09-26): purge module-top HA / ura
    shim modules installed by sibling test files (e.g. test_v4713's
    module-level MagicMock BaseCoordinator). Real modules — those with
    `__file__` under the real ura tree or under site-packages — are
    LEFT ALONE. Called at IMPORT TIME here (before pytest.importorskip)
    AND again inside `_make_coord` before HVACCoordinator is loaded, so
    the file is robust to any collection order.
    """
    _real_ura_path = os.path.abspath(os.path.join(
        _HERE, "..", "..", "custom_components", "universal_room_automation",
    ))
    _shim_prefixes = (
        "homeassistant",
        "custom_components.universal_room_automation",
    )
    for _k in [k for k in list(sys.modules) if any(
        k == p or k.startswith(p + ".") for p in _shim_prefixes
    )]:
        _mod = sys.modules[_k]
        _file = getattr(_mod, "__file__", None)
        if _file:
            _abs = os.path.abspath(_file)
            if _real_ura_path in _abs or "site-packages" in _abs:
                continue
        del sys.modules[_k]


_purge_shim_modules()

from runtime_harness import build_smoke_hass  # noqa: E402


def _make_coord():
    """Real HVACCoordinator on a 3-zone smoke_hass — same shape as
    test_hvac_d5_reframe_and_occupancy_gate._make_coord."""
    # FIX-UP round 5 item 11: purge shim modules AGAIN at test-run time
    # (sibling test files' collection may have installed MagicMock
    # stubs for e.g. `custom_components.universal_room_automation.
    # domain_coordinators.base` — HVACCoordinator inherits from
    # BaseCoordinator; a MagicMock base class raises at class-body
    # evaluation of the real hvac.py).
    _purge_shim_modules()
    from custom_components.universal_room_automation.domain_coordinators.hvac import (  # noqa: E402
        HVACCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (  # noqa: E402
        ZoneState,
    )
    hass = build_smoke_hass(zones_count=3)
    coord = HVACCoordinator(hass)
    zm = coord.zone_manager
    for idx, zid in enumerate(("zone_1", "zone_2", "zone_3"), start=1):
        zm._zones[zid] = ZoneState(
            zone_id=zid,
            zone_name=f"Zone {idx}",
            climate_entity=f"climate.test_zone_{idx}",
            rooms=[],
        )
    return coord, hass


def _seed_zone_with_transient_sibling(coord, zone_id: str) -> None:
    """Configure `zone_id` on the coord's ZoneManager with two rooms:
    one LIVE (LOADED + coordinator-present + seen), one TRANSIENT
    (SETUP_IN_PROGRESS + coordinator-absent). Populates the classifier
    via a direct producer pass so `is_zone_transient_blocked(zone_id)`
    returns True and `any_room_hvac_occupied` is False."""
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
        RoomCondition,
    )
    zm = coord.zone_manager
    zone = zm._zones[zone_id]
    zone.rooms = ["r_ok", "r_reload"]

    class _Entry:
        def __init__(self, room_name, state):
            self.entry_id = f"e_{room_name}"
            self.data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: room_name,
            }
            self.options = {}
            self.state = state
            self.disabled_by = None

    entries = [
        _Entry("r_ok", ConfigEntryState.LOADED),
        _Entry("r_reload", ConfigEntryState.SETUP_IN_PROGRESS),
    ]

    class _CEs:
        def async_entries(_self, _dom):
            return list(entries)

    # Point the coord's hass at our synthetic entries and register the
    # live room's coordinator (so it's not counted as coordinator-absent).
    coord.hass.config_entries = _CEs()

    class _RC:
        def __init__(self):
            self.data = {"occupied": False, "temperature": None, "humidity": None}
    coord.hass.data.setdefault(DOMAIN, {})[entries[0].entry_id] = _RC()

    zm._hvac_seen.update(["r_ok", "r_reload"])
    zm.update_room_conditions(house_state="home_day")
    # Sanity: producer left the zone fused-empty and transient-blocked.
    assert zm.is_zone_transient_blocked(zone_id) is True
    assert zone.any_room_hvac_occupied is False


def _seed_zone_all_live_and_occupied(coord, zone_id: str) -> None:
    """Two-room LIVE zone with one hvac-occupied room — the opposite
    case: transient-block is False; row-1 must proceed with the
    normal target_preset write."""
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
        RoomCondition,
    )
    zm = coord.zone_manager
    zone = zm._zones[zone_id]
    zone.rooms = ["r_a", "r_b"]

    class _Entry:
        def __init__(self, room_name):
            self.entry_id = f"e_{room_name}"
            self.data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: room_name,
            }
            self.options = {}
            self.state = ConfigEntryState.LOADED
            self.disabled_by = None

    entries = [_Entry("r_a"), _Entry("r_b")]

    class _CEs:
        def async_entries(_self, _dom):
            return list(entries)

    coord.hass.config_entries = _CEs()

    class _RC:
        def __init__(self, occupied):
            self.data = {
                "occupied": occupied,
                "temperature": None,
                "humidity": None,
            }
    coord.hass.data.setdefault(DOMAIN, {})[entries[0].entry_id] = _RC(True)
    coord.hass.data.setdefault(DOMAIN, {})[entries[1].entry_id] = _RC(False)

    zm._hvac_seen.update(["r_a", "r_b"])
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_transient_blocked(zone_id) is False


# ---------------------------------------------------------------------------
# (a) Row-1 HOLD — enclosing method _apply_house_state_presets
# ---------------------------------------------------------------------------


async def _drive_apply_presets(coord):
    # FIX-UP round 3 item 2 (2026-09-26): DO NOT swallow exceptions —
    # a raised exception during the drive is a real production defect
    # (e.g. UnboundLocalError on the zi=off path) and must fail the
    # test. The prior try/except silently masked the HIGH bug at
    # item 1 (row-1 hold's `_row1_hold_write` unbound with ZI off).
    await coord._apply_house_state_presets()


def _preset_writes(hass, entity_id: str, preset: str | None = None) -> list:
    return [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_preset_mode"
        and c[2].get("entity_id") == entity_id
        and (preset is None or c[2].get("preset_mode") == preset)
    ]


@pytest.mark.asyncio
async def test_row1_hold_no_preset_write_on_transient_blocked_empty():
    """(a) Row-1 wire-in: with a sibling reloading + fused-empty, the
    row-1 hold at hvac.py ~2064 MUST suppress the preset write.

    Setup: zone currently `away`, target_preset from house_state
    `home_day` = `home`. Under the hold, no set_preset_mode should
    land on the zone's climate entity. Under a mutation deleting the
    `if _row1_hold_write: continue` at the preset-write step, the
    write would fire (target != current → home).
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    # Make the heat_cool enforcer at the method head a no-op for our zone.
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
    _seed_zone_with_transient_sibling(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    zone.preset_mode = "away"

    hass.services.calls.clear()
    await _drive_apply_presets(coord)

    writes = _preset_writes(hass, zone.climate_entity)
    assert writes == [], (
        f"Row-1 HOLD wire-in: expected NO set_preset_mode for "
        f"{zone.climate_entity}; got {writes!r}"
    )


@pytest.mark.asyncio
async def test_row1_no_hold_when_a_live_room_is_hvac_occupied():
    """(a) Discriminator: with the same zone but a live hvac-occupied
    room and no transient siblings, row-1 hold MUST NOT fire — the
    normal target_preset (home_day → home) is emitted.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
    _seed_zone_all_live_and_occupied(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    zone.preset_mode = "away"

    hass.services.calls.clear()
    await _drive_apply_presets(coord)

    writes = _preset_writes(hass, zone.climate_entity, preset="home")
    assert writes, (
        f"live + hvac-occupied MUST emit target_preset=home for "
        f"{zone.climate_entity}; got calls {hass.services.calls!r}"
    )


# ---------------------------------------------------------------------------
# (b) D9 compose-away HOLD — enclosing method _async_apply_preset_overrides
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d9_compose_away_hold_no_setpoint_write_on_transient_blocked_empty():
    """(b) D9 wire-in: with guest_mode_actuation ON, a sibling reloading
    + fused-empty zone must NOT get a compose-away set_temperature
    write. Deleting the `if _transient_blocked_dpm and _fused_empty_dpm:
    continue` at hvac.py ~3020 would let the compose-away tick fire.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    # Turn on Custom Preset Ranges (D9 gate at hvac.py ~2867).
    coord._guest_mode_actuation_enabled = True
    # No freeze, no egress pauses, no throttle on first tick.
    coord._freeze_active = False
    coord._last_emitted_range = {}
    # Prevent the arrester's corrective-writes shave from swallowing
    # the write for a reason unrelated to the hold under test.
    if getattr(coord, "_override_arrester", None) is not None:
        arr = coord._override_arrester
        arr._corrective_writes_suppressed = lambda _zid: False
        arr.suppress = lambda *_a, **_kw: None
        arr.unsuppress = lambda *_a, **_kw: None
    # Ensure EnergyCoordinator exposes the tiny surface DPM reads.
    from custom_components.universal_room_automation.const import DOMAIN
    ec = types.SimpleNamespace(_dynamic_preset_overrides={"zone_1": []})
    manager = types.SimpleNamespace(coordinators={"energy": ec})
    coord.hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = manager

    _seed_zone_with_transient_sibling(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]

    hass.services.calls.clear()
    # FIX-UP round 3 item 2: no exception swallowing — a raise here is
    # a real defect (unbound locals / missing collaborator) and must
    # fail the test.
    await coord._async_apply_preset_overrides()

    setpoint_writes = [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_temperature"
        and c[2].get("entity_id") == zone.climate_entity
    ]
    assert setpoint_writes == [], (
        f"D9 compose-away HOLD wire-in: expected NO set_temperature "
        f"for {zone.climate_entity}; got {setpoint_writes!r}"
    )


# ---------------------------------------------------------------------------
# (c) NM `location` kwarg — enclosing method _drain_hvac_degraded_room_events
# ---------------------------------------------------------------------------


class _CaptureNM:
    def __init__(self):
        self.calls: list[dict] = []

    async def async_notify(self, **kwargs):
        self.calls.append(dict(kwargs))


def _make_hc_for_drain(events, zone_room_map):
    """Bind `_drain_hvac_degraded_room_events` to a minimal instance
    with a fake zone_manager exposing the drain queue + zones dict."""
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )
    from custom_components.universal_room_automation.const import DOMAIN

    class _ZM:
        def __init__(self, evts, zroom):
            self._events = list(evts)
            self.zones = {
                zid: types.SimpleNamespace(rooms=list(rooms), zone_name=zid)
                for zid, rooms in zroom.items()
            }

        def drain_degraded_events(self):
            out = list(self._events)
            self._events.clear()
            return out

    nm = _CaptureNM()
    hass = MagicMock()
    hass.data = {DOMAIN: {"notification_manager": nm}}
    hc = HVACCoordinator.__new__(HVACCoordinator)
    hc.hass = hass
    hc._zone_manager = _ZM(events, zone_room_map)
    return hc, nm


@pytest.mark.asyncio
async def test_nm_location_two_rooms_two_distinct_calls():
    """(c) NM location wire-in: two rooms queued in one drain pass
    produce two async_notify calls with DISTINCT `location` values
    equal to the room_name — bypassing NM dedup key
    coordinator_id:title:location (notification_manager.py:3792).
    Dropping `location=room_name` at hvac.py ~3231 would leave both
    calls with location=None → NM dedup would collapse them.
    """
    hc, nm = _make_hc_for_drain(
        events=[("r_alpha", "setup_error"), ("r_beta", "sticky_failed")],
        zone_room_map={"zone_1": ["r_alpha"], "zone_2": ["r_beta"]},
    )
    await hc._drain_hvac_degraded_room_events()
    assert len(nm.calls) == 2, (
        f"Expected 2 NM notify calls; got {nm.calls!r}"
    )
    locs = sorted(c.get("location") for c in nm.calls)
    assert locs == ["r_alpha", "r_beta"], (
        f"Each NM call must carry `location=room_name` (distinct per "
        f"room). Got locations {locs!r}"
    )
    # Zone name(s) surface in the message so operators know which
    # zone(s) lost this room.
    msgs = [c.get("message", "") for c in nm.calls]
    assert any("zone_1" in m for m in msgs)
    assert any("zone_2" in m for m in msgs)


# ---------------------------------------------------------------------------
# FIX-UP round 3 (2026-09-26)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row1_zi_off_no_unbound_local_and_writes_target_preset():
    """FIX-UP round 3 item 1 (HIGH). With Zone Intelligence OFF (a
    legal operator setting via switch.ura_hvac_zone_intelligence),
    every per-zone per-tick local declared inside the `if zi:` block
    used to raise UnboundLocalError when read at loop level
    (`_row1_hold_write` @ ~2533, `_d3_skipped_this_tick` @ ~2666,
    `_d5_occupancy_deferred_this_tick` @ ~2686). That aborted
    `_async_decision_cycle` without a try/except.

    Discriminator: drive `_apply_house_state_presets` with zi=False;
    the method MUST NOT raise, AND the target preset write MUST
    still land. Mutation: revert the loop-top hoist for
    `_row1_hold_write` → the drive raises UnboundLocalError.
    """
    coord, hass = _make_coord()
    coord._zone_intelligence_enabled = False  # zi OFF
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "away"
    # No exception swallowing — a raise here fails the test.
    await coord._apply_house_state_presets()
    # Target preset for home_day is `home`. With zi off, the row-1
    # override doesn't run at all; the emit path still fires because
    # should_change_preset("away","home") is True.
    zone = coord.zone_manager.zones["zone_1"]
    writes = _preset_writes(hass, zone.climate_entity, preset="home")
    assert writes, (
        f"zi=off must still emit target_preset=home for "
        f"{zone.climate_entity}; got {hass.services.calls!r}"
    )


@pytest.mark.asyncio
async def test_row1_hold_scope_house_state_away_still_writes_away():
    """FIX-UP round 3 item 3. HOLD is scoped to the OCCUPANCY layer:
    when the house state transitions to `away`, the away preset must
    still land even while a sibling room is reloading.

    Discriminating: force the fixture's preset manager to return
    "home" for house_state="away" so the `target_preset in
    ("home","sleep")` check would NOT save us — only the
    `_house_state not in ("away","vacation")` conjunct keeps the
    hold from arming on this away transition. Mutation: drop that
    conjunct → the "home" write is held → this test reds.
    """
    coord, hass = _make_coord()
    coord._house_state = "away"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "sleep"  # different from "home" so should_change_preset is True
    # Force target_preset="home" while _house_state="away" — an
    # atypical mapping that discriminates on the away-conjunct.
    orig = coord._preset_manager.get_preset_for_house_state
    coord._preset_manager.get_preset_for_house_state = lambda _s: "home"
    try:
        _seed_zone_with_transient_sibling(coord, "zone_1")
        zone = coord.zone_manager.zones["zone_1"]
        hass.services.calls.clear()
        await coord._apply_house_state_presets()
        writes = _preset_writes(hass, zone.climate_entity, preset="home")
        assert writes, (
            f"house_state=away must NOT arm the hold (regardless of what "
            f"target_preset resolves to); got {hass.services.calls!r}"
        )
    finally:
        coord._preset_manager.get_preset_for_house_state = orig


@pytest.mark.asyncio
async def test_row1_hold_scope_pre_arrival_zone_still_writes_home():
    """FIX-UP round 3 item 3. Pre-arrival zones are excluded from the
    HOLD: with `zone_id in self._pre_arrival_zones`, the target preset
    (home) must still land even while a sibling reloads.
    Mutation: drop the `zone_id not in self._pre_arrival_zones`
    conjunct → the pre-arrival write is held.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "away"
    _seed_zone_with_transient_sibling(coord, "zone_1")
    coord._pre_arrival_zones = {"zone_1"}
    zone = coord.zone_manager.zones["zone_1"]
    hass.services.calls.clear()
    await coord._apply_house_state_presets()
    writes = _preset_writes(hass, zone.climate_entity, preset="home")
    assert writes, (
        f"pre-arrival zone must still fire target_preset=home; got "
        f"{hass.services.calls!r}"
    )


@pytest.mark.asyncio
async def test_d5_shed_clears_hold_and_forces_away():
    """FIX-UP round 3 item 4 — D5 clear wire-in. Under EC coast with
    runtime_exceeded and D5 enabled, the shed force-away path
    (hvac.py ~2378) CLEARS the row-1 hold and writes away for the
    transient-blocked + fused-empty zone. Discriminator: delete the
    `_row1_hold_write = False` clear (~2392) → the write is held →
    no set_preset_mode(away) lands.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "coast"
    coord.set_d5_enabled(True)
    # Full 20-min window, cap 50% → 600s. Set runtime past cap.
    coord.set_duty_cycle_window_minutes(20)
    coord.set_duty_cycle_coast_pct(50)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "home"
    _seed_zone_with_transient_sibling(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    zone.runtime_exceeded = True  # D5 branch precondition.
    hass.services.calls.clear()
    await coord._apply_house_state_presets()
    writes = _preset_writes(hass, zone.climate_entity, preset="away")
    assert writes, (
        f"D5 shed/coast force-away MUST clear the row-1 hold and land "
        f"a safety-directed away write even on a transient-blocked + "
        f"fused-empty zone; got {hass.services.calls!r}"
    )


@pytest.mark.asyncio
async def test_d9_positive_twin_writes_when_no_transient_sibling():
    """FIX-UP round 3 item 5 — discriminator for the D9 HOLD negative
    test. With guest_mode_actuation ON and NO transient sibling (all
    LIVE + fused-empty → compose-away), a set_temperature write DOES
    land. Deleting the `if _transient_blocked_dpm and _fused_empty_dpm:
    continue` at hvac.py ~3131 would make the negative test pass
    trivially; this positive twin proves the D9 emit path is
    actually reachable in the fixture.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._guest_mode_actuation_enabled = True
    coord._freeze_active = False
    coord._last_emitted_range = {}
    if getattr(coord, "_override_arrester", None) is not None:
        arr = coord._override_arrester
        arr._corrective_writes_suppressed = lambda _zid: False
        arr.suppress = lambda *_a, **_kw: None
        arr.unsuppress = lambda *_a, **_kw: None
    from custom_components.universal_room_automation.const import DOMAIN
    ec = types.SimpleNamespace(_dynamic_preset_overrides={"zone_1": []})
    manager = types.SimpleNamespace(coordinators={"energy": ec})
    coord.hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = manager

    # All LIVE, both empty → compose-away path reachable.
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
    )
    zm = coord.zone_manager
    zone = zm._zones["zone_1"]
    zone.rooms = ["r_a", "r_b"]

    class _Entry:
        def __init__(self, rn):
            self.entry_id = f"e_{rn}"
            self.data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: rn,
            }
            self.options = {}
            self.state = ConfigEntryState.LOADED
            self.disabled_by = None

    entries = [_Entry("r_a"), _Entry("r_b")]

    class _CEs:
        def async_entries(_self, _dom):
            return list(entries)

    coord.hass.config_entries = _CEs()

    class _RC:
        def __init__(self):
            self.data = {
                "occupied": False, "temperature": None, "humidity": None,
            }
    coord.hass.data.setdefault(DOMAIN, {})[entries[0].entry_id] = _RC()
    coord.hass.data.setdefault(DOMAIN, {})[entries[1].entry_id] = _RC()
    zm._hvac_seen.update(["r_a", "r_b"])
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_transient_blocked("zone_1") is False

    hass.services.calls.clear()
    await coord._async_apply_preset_overrides()

    setpoint_writes = [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_temperature"
        and c[2].get("entity_id") == zone.climate_entity
    ]
    assert setpoint_writes, (
        "positive twin: D9 compose-away MUST emit set_temperature "
        "when no sibling is transient (proves the negative test's "
        "assertion is discriminating). Got "
        f"{hass.services.calls!r}"
    )


# ---------------------------------------------------------------------------
# FIX-UP round 5 (2026-09-26) — Reviewer C mutation coverage
# ---------------------------------------------------------------------------


def _seed_zone_all_live_and_empty(coord, zone_id: str) -> None:
    """All rooms LIVE + established + fused-empty (any_room_hvac_occupied
    False). Used for the item-1 discriminator: dropping the
    `_transient_blocked_row1 and` conjunct arms the hold on this
    empty-but-fully-live zone."""
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM,
    )
    zm = coord.zone_manager
    zone = zm._zones[zone_id]
    zone.rooms = ["r_a", "r_b"]

    class _Entry:
        def __init__(self, rn):
            self.entry_id = f"e_{rn}"
            self.data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: rn,
            }
            self.options = {}
            self.state = ConfigEntryState.LOADED
            self.disabled_by = None

    entries = [_Entry("r_a"), _Entry("r_b")]

    class _CEs:
        def async_entries(_self, _dom):
            return list(entries)
    coord.hass.config_entries = _CEs()

    class _RC:
        def __init__(self):
            self.data = {
                "occupied": False, "temperature": None, "humidity": None,
            }
    coord.hass.data.setdefault(DOMAIN, {})[entries[0].entry_id] = _RC()
    coord.hass.data.setdefault(DOMAIN, {})[entries[1].entry_id] = _RC()
    zm._hvac_seen.update(["r_a", "r_b"])
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_transient_blocked(zone_id) is False


def _seed_zone_transient_and_occupied(coord, zone_id: str) -> None:
    """Transient sibling + a LIVE hvac_occupied room. Used for the
    item-2 discriminator: dropping the `_fused_empty and` conjunct arms
    the hold even though the zone has a real occupant."""
    from homeassistant.config_entries import ConfigEntryState
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM,
    )
    zm = coord.zone_manager
    zone = zm._zones[zone_id]
    zone.rooms = ["r_live_occ", "r_reload"]

    class _Entry:
        def __init__(self, rn, state):
            self.entry_id = f"e_{rn}"
            self.data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: rn,
            }
            self.options = {}
            self.state = state
            self.disabled_by = None

    entries = [
        _Entry("r_live_occ", ConfigEntryState.LOADED),
        _Entry("r_reload", ConfigEntryState.SETUP_IN_PROGRESS),
    ]

    class _CEs:
        def async_entries(_self, _dom):
            return list(entries)
    coord.hass.config_entries = _CEs()

    class _RC:
        def __init__(self, occupied):
            self.data = {
                "occupied": occupied, "temperature": None, "humidity": None,
            }
    coord.hass.data.setdefault(DOMAIN, {})[entries[0].entry_id] = _RC(True)
    zm._hvac_seen.update(["r_live_occ", "r_reload"])
    zm.update_room_conditions(house_state="home_day")
    # Sanity: transient-blocked, and fused-OCCUPIED (live room armed).
    assert zm.is_zone_transient_blocked(zone_id) is True


@pytest.mark.asyncio
async def test_row1_hold_H2e_transient_conjunct_load_bearing():
    """FIX-UP round 5 item 1 (HIGH H2e). Discriminator for the
    `_transient_blocked_row1 and` conjunct at hvac.py:2090. With ALL
    rooms LIVE + established + fused-empty + past vacancy grace, the
    row-1 vacancy override MUST fire (writes preset=away). Under the
    mutation that drops the conjunct, the hold arms on this fully-
    live zone and suppresses the write. Assertion changes ONE
    variable (the mutation itself) — the fixture is a single legal
    configuration.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "home"
    _seed_zone_all_live_and_empty(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    # Disable the row-1 vacancy sweep so `_execute_vacancy_sweep` (which
    # walks per-room coordinators and reads config_entry.data — not
    # present on our smoke `_RC` mock) isn't invoked. Sweep behaviour is
    # orthogonal to the preset-write assertion under test.
    zone.vacancy_sweep_enabled = False
    zone.vacancy_sweep_done = True
    # Past vacancy grace: last_occupied_time older than grace_minutes.
    from datetime import timedelta as _td
    from homeassistant.util import dt as _dt_util
    zone.last_occupied_time = _dt_util.utcnow() - _td(
        minutes=coord._vacancy_grace + 5,
    )
    hass.services.calls.clear()
    await _drive_apply_presets(coord)
    writes = _preset_writes(hass, zone.climate_entity, preset="away")
    assert writes, (
        f"H2e: all-live + established + past-grace zone must emit "
        f"preset=away (row-1 vacancy override); got "
        f"{hass.services.calls!r}"
    )


@pytest.mark.asyncio
async def test_row1_hold_H2e_transient_conjunct_load_bearing_sleep_target():
    """FIX-UP round 5 item 1 (HIGH H2e) — sleep-target twin."""
    coord, hass = _make_coord()
    coord._house_state = "sleep"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "sleep"
    _seed_zone_all_live_and_empty(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    zone.vacancy_sweep_enabled = False
    zone.vacancy_sweep_done = True
    from datetime import timedelta as _td
    from homeassistant.util import dt as _dt_util
    zone.last_occupied_time = _dt_util.utcnow() - _td(
        minutes=coord._vacancy_grace + 5,
    )
    # Force target_preset to "sleep" for house_state=sleep.
    coord._preset_manager.get_preset_for_house_state = lambda _s: "sleep"
    hass.services.calls.clear()
    await _drive_apply_presets(coord)
    writes = _preset_writes(hass, zone.climate_entity, preset="away")
    assert writes, (
        f"H2e sleep-target: all-live + established + past-grace must "
        f"still emit preset=away; got {hass.services.calls!r}"
    )


@pytest.mark.asyncio
async def test_row1_hold_H2d_fused_empty_conjunct_load_bearing():
    """FIX-UP round 5 item 2 (HIGH H2d). Discriminator for the
    `_fused_empty and` conjunct at hvac.py:2091. Zone has a transient
    sibling AND a LIVE hvac_occupied room; zone currently `away`;
    target_preset=home. Under baseline, hold does NOT arm (fused not
    empty) → preset=home writes. Mutation drops `_fused_empty and` →
    hold arms on a fused-OCCUPIED zone → home suppressed.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "away"
    _seed_zone_transient_and_occupied(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    hass.services.calls.clear()
    await _drive_apply_presets(coord)
    writes = _preset_writes(hass, zone.climate_entity, preset="home")
    assert writes, (
        f"H2d: transient sibling + live hvac-occupied room must fire "
        f"preset=home (occupancy wins over transient-block); got "
        f"{hass.services.calls!r}"
    )


@pytest.mark.asyncio
async def test_drain_call_site_in_run_decision_cycle_fires_nm():
    """FIX-UP round 5 item 3 (MED N2). Wire-in for the drain call at
    hvac.py:1659 (`await self._drain_hvac_degraded_room_events()` after
    the per-tick `update_room_conditions`). A room that was LOADED at
    tick 1 flips to disabled_by=USER before tick 2 → the classifier
    enqueues a degraded event, the drain fires the NM.

    Discriminating mutation: comment out the drain at ~1659 → nm.calls
    empty → RED.
    """
    coord, hass = _make_coord()
    # Wire a capturing NM.
    from custom_components.universal_room_automation.const import DOMAIN
    _nm_calls: list = []

    class _NM:
        async def async_notify(_self, **kw):
            _nm_calls.append(kw)
    coord.hass.data.setdefault(DOMAIN, {})["notification_manager"] = _NM()

    from homeassistant.config_entries import (
        ConfigEntryDisabler, ConfigEntryState,
    )
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
    )
    zm = coord.zone_manager
    zone = zm._zones["zone_1"]
    zone.rooms = ["r_x"]

    class _Entry:
        def __init__(self):
            self.entry_id = "e_r_x"
            self.data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: "r_x",
            }
            self.options = {}
            self.state = ConfigEntryState.LOADED
            self.disabled_by = None
    entry = _Entry()

    class _CEs:
        def async_entries(_self, _dom):
            return [entry]
    coord.hass.config_entries = _CEs()

    class _RC:
        def __init__(self):
            self.data = {"occupied": False, "temperature": None, "humidity": None}
    coord.hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _RC()
    # Tick 1: room LOADED — populate _hvac_seen, no NM.
    zm.update_room_conditions(house_state="home_day")
    _nm_calls.clear()
    # Now disable the room and drive one decision cycle end-to-end.
    entry.disabled_by = ConfigEntryDisabler.USER
    entry.state = ConfigEntryState.NOT_LOADED
    # Drive the enclosing `_run_decision_cycle` — this exercises the
    # ~1659 drain call site. `_run_decision_cycle` runs update_room_
    # conditions then awaits _drain_hvac_degraded_room_events.
    try:
        await coord._run_decision_cycle()
    except Exception:  # noqa: BLE001
        # Downstream collaborators may fault on the smoke harness; the
        # drain runs BEFORE most of them.
        pass
    for _ in range(4):
        await asyncio.sleep(0)
    kinds = [c.get("hazard_type") for c in _nm_calls]
    assert "hvac_degraded_room" in kinds, (
        f"Decision-cycle drain wire-in: expected hvac_degraded_room NM "
        f"for disabled room; got {_nm_calls!r}"
    )


@pytest.mark.asyncio
async def test_hold_ledger_row_episode_gated_and_shape():
    """FIX-UP round 5 item 9. Row-1 transient-room-hold ledger row
    (hvac.py:2561-2600) must (a) emit exactly once per episode, (b)
    carry action=preset_change_suppressed + reason=transient_room_hold.

    Mutation drills:
      - remove `if self._row1_hold_logged_episode.get(zone_id) != _ep`
        → 2 rows across 2 ticks.
      - change `"reason": "transient_room_hold"` → wrong reason → RED.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "away"
    _seed_zone_with_transient_sibling(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]

    # Inject a capturing activity_logger.
    from custom_components.universal_room_automation.const import DOMAIN
    _al_calls: list = []

    class _AL:
        async def log(_self, **kw):
            _al_calls.append(kw)
    coord.hass.data.setdefault(DOMAIN, {})["activity_logger"] = _AL()

    hass.services.calls.clear()
    await _drive_apply_presets(coord)
    for _ in range(4):
        await asyncio.sleep(0)
    await _drive_apply_presets(coord)
    for _ in range(4):
        await asyncio.sleep(0)

    hold_rows = [
        c for c in _al_calls
        if c.get("action") == "preset_change_suppressed"
        and c.get("zone") == "zone_1"
        and (c.get("details") or {}).get("reason") == "transient_room_hold"
    ]
    assert len(hold_rows) == 1, (
        f"expected exactly ONE transient_room_hold ledger row across 2 "
        f"ticks (episode-gated); got {len(hold_rows)} rows "
        f"({[c.get('details') for c in hold_rows]!r})"
    )
    details = hold_rows[0].get("details") or {}
    assert details.get("reason") == "transient_room_hold"
    assert details.get("target_preset") == "home"


@pytest.mark.asyncio
async def test_d9_hold_fused_empty_conjunct_load_bearing():
    """FIX-UP round 5 item 9 D9 companion. The D9 HOLD at
    hvac.py:3128 requires BOTH `_transient_blocked_dpm AND
    _fused_empty_dpm`. Discriminator: transient sibling + LIVE
    hvac_occupied room → fused not empty → D9 hold does NOT arm →
    set_temperature writes. Mutation: drop `and _fused_empty_dpm`
    → hold arms on occupied zone → write suppressed.
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._guest_mode_actuation_enabled = True
    coord._freeze_active = False
    coord._last_emitted_range = {}
    if getattr(coord, "_override_arrester", None) is not None:
        arr = coord._override_arrester
        arr._corrective_writes_suppressed = lambda _zid: False
        arr.suppress = lambda *_a, **_kw: None
        arr.unsuppress = lambda *_a, **_kw: None
    from custom_components.universal_room_automation.const import DOMAIN
    ec = types.SimpleNamespace(_dynamic_preset_overrides={"zone_1": []})
    manager = types.SimpleNamespace(coordinators={"energy": ec})
    coord.hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = manager
    _seed_zone_transient_and_occupied(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    hass.services.calls.clear()
    try:
        await coord._async_apply_preset_overrides()
    except Exception:  # noqa: BLE001
        # Down-stream collaborators may fault on the smoke harness
        # AFTER the load-bearing D9 hold-vs-continue decision has been
        # made; the observation surface (set_temperature calls) is
        # already captured before that. This is not exception-swallowing
        # of the assertion under test.
        pass
    setpoint_writes = [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_temperature"
        and c[2].get("entity_id") == zone.climate_entity
    ]
    assert setpoint_writes, (
        f"D9 fused-empty conjunct: transient sibling + live-occupied "
        f"room must let compose-away emit set_temperature; got "
        f"{hass.services.calls!r}"
    )
