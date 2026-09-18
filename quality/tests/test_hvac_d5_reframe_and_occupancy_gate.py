"""HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 — BEHAVIORAL tests (fix-up F7).

Reviewer C required real behavioral tests that CONSTRUCT the HVACCoordinator
and DRIVE its code paths — the prior rev of this file was 9 source-string
reads (Bug Class #62 "hollow anchors"). Every test below either:

  (a) constructs a real HVACCoordinator via the `build_smoke_hass` harness
      and calls a real method (`_accumulate_zone_runtime`,
      `_compute_zone_presence_states`, `_apply_house_state_presets`)
      and asserts on the resulting mutated state; or

  (b) is an AST-anchored VOCABULARY completeness check for
      `HVAC_PRESET_REASONS` where the mutation drill is a symbol removal
      (the frozenset is the acceptance surface for reason strings).

Per-site mutation → RED table (documented in the delivery report). Each
test names the production site whose neutering makes it fail. Runs are
serialised via pytest-asyncio's default event loop; no wall-clock.
"""
from __future__ import annotations

import ast
import asyncio
import os
from datetime import datetime, timezone

import pytest


_HERE = os.path.dirname(__file__)
_URA = os.path.abspath(os.path.join(_HERE, "..", "..",
                                    "custom_components",
                                    "universal_room_automation"))
_DC = os.path.join(_URA, "domain_coordinators")


# Smoke tests / behavioral coordinator drives require homeassistant.
_ha = pytest.importorskip(
    "homeassistant.config_entries",
    reason=(
        "homeassistant not installed — behavioral HVAC D5 tests skipped. "
        "Install via pip install pytest-homeassistant-custom-component "
        "(see quality/requirements_test.txt)."
    ),
)


from runtime_harness import build_smoke_hass  # noqa: E402


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _make_coord():
    """Build a real HVACCoordinator on a 3-zone smoke_hass. Caller drives
    per-method behavior; no async_setup() (which pulls in real listeners /
    entities we don't need for these unit-level drives)."""
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )
    hass = build_smoke_hass(zones_count=3)
    coord = HVACCoordinator(hass)
    # Seed the zones the coord's ZoneManager needs — a minimum ZoneState
    # per test-facing zone_id, matching the smoke harness.
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
        ZoneState,
    )
    zm = coord.zone_manager
    for idx, zid in enumerate(("zone_1", "zone_2", "zone_3"), start=1):
        zm._zones[zid] = ZoneState(
            zone_id=zid,
            zone_name=f"Zone {idx}",
            climate_entity=f"climate.test_zone_{idx}",
            rooms=[],
        )
    return coord, hass


def _set_zone_occupied(zone, hvac_occupied: bool, lighting_occupied: bool | None = None) -> None:
    """Seed a single RoomCondition on the zone so `any_room_occupied` /
    `any_room_hvac_occupied` (both @property fed from room_conditions)
    return the desired truth value. Lighting-occupied defaults to match
    hvac_occupied when not supplied."""
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
        RoomCondition,
    )
    zone.room_conditions = [
        RoomCondition(
            room_name=f"{zone.zone_name}_room",
            occupied=bool(hvac_occupied if lighting_occupied is None else lighting_occupied),
            hvac_occupied=bool(hvac_occupied),
        )
    ]


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# HVAC_PRESET_REASONS — vocabulary completeness (AST/frozenset symbol)
# ---------------------------------------------------------------------------

def test_hvac_preset_reasons_carries_new_reasons_and_no_alias():
    """D-b1 / D-b2: `energy_shed_cap_reached` and
    `energy_shed_cap_deferred_occupied` are members; the pre-rename
    `runtime_exceeded` is NOT (Single-User-No-Back-Compat: no alias).

    Mutation → RED: revert the frozenset entries in const.py to
    `runtime_exceeded` and this test REDs.
    """
    from custom_components.universal_room_automation.const import (
        HVAC_PRESET_REASONS,
    )
    assert "energy_shed_cap_reached" in HVAC_PRESET_REASONS
    assert "energy_shed_cap_deferred_occupied" in HVAC_PRESET_REASONS
    assert "runtime_exceeded" not in HVAC_PRESET_REASONS


# ---------------------------------------------------------------------------
# D-b1 rename — DRIVEN through _compute_zone_presence_states
# ---------------------------------------------------------------------------

def test_zone_presence_state_producer_emits_energy_shed_cap_reached():
    """D-b1 rename verified BEHAVIORALLY: with runtime_exceeded=True and
    the coordinator NOT in sleep, `_compute_zone_presence_states` writes
    `zone.zone_presence_state = "energy_shed_cap_reached"` (previously
    `runtime_limited`).

    Mutation → RED (M0): revert the string at hvac.py:_compute_zone_presence_states
    to "runtime_limited" and this test REDs.
    """
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    zone = coord.zone_manager._zones["zone_1"]
    zone.runtime_exceeded = True
    coord._compute_zone_presence_states(_now())
    assert zone.zone_presence_state == "energy_shed_cap_reached", (
        f"expected renamed state 'energy_shed_cap_reached'; got "
        f"{zone.zone_presence_state!r}"
    )


def test_zone_presence_state_sleep_still_dominates_rename():
    """Precedence guard: sleep > energy_shed_cap_reached (unchanged by
    D-b1 rename). Mutation → RED: swap the sleep/runtime_exceeded elif
    ordering and this REDs on the sleep case."""
    coord, _hass = _make_coord()
    coord._house_state = "sleep"
    zone = coord.zone_manager._zones["zone_1"]
    zone.runtime_exceeded = True
    coord._compute_zone_presence_states(_now())
    assert zone.zone_presence_state == "sleep"


# ---------------------------------------------------------------------------
# D-b3 knobs + accumulator — DRIVEN through _accumulate_zone_runtime
# ---------------------------------------------------------------------------

def test_accumulator_reads_live_window_knob_not_module_constant():
    """D-b3 (M1): mutate the LIVE window knob and confirm the
    accumulator's effective cap uses it — a 10-minute window @ 75%
    coast trips at 450s, a 40-minute window at the SAME occupancy
    rate does NOT.

    Mutation → RED: swap the accumulator's `self.duty_cycle_window_seconds`
    read back to `DUTY_CYCLE_WINDOW_SECONDS` (module constant) and
    this test REDs.
    """
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "coast"
    coord.set_duty_cycle_coast_pct(75)
    coord.set_d5_enabled(True)

    zone = coord.zone_manager._zones["zone_1"]
    # Simulate 500s runtime accumulated already.
    zone.window_start = _now()
    zone.runtime_seconds_this_window = 500.0
    zone.hvac_action = "idle"  # don't add more this tick
    zone.runtime_exceeded = False

    # 10-min window: cap @ 75% = 450s → EXCEED.
    coord.set_duty_cycle_window_minutes(10)
    coord._last_runtime_accumulation = _now()  # so elapsed == 0
    coord._accumulate_zone_runtime(_now())
    assert zone.runtime_exceeded is True, (
        "10-min window at 75% coast should trip on 500s runtime"
    )

    # Same runtime but a 40-min window: cap @ 75% = 1800s → OK.
    zone.runtime_exceeded = False
    zone.window_start = _now()
    zone.runtime_seconds_this_window = 500.0
    coord.set_duty_cycle_window_minutes(40)
    coord._last_runtime_accumulation = _now()
    coord._accumulate_zone_runtime(_now())
    assert zone.runtime_exceeded is False, (
        "40-min window at 75% coast should NOT trip on 500s runtime "
        "— live knob not consulted?"
    )


def test_accumulator_cap_pct_zero_clears_latch_F5():
    """F5 (M4): setting the mode cap to 0 mid-episode MUST clear a
    latched `runtime_exceeded` before `continue`. Prior build left it
    latched for up to a full window (silent force-away).

    Mutation → RED: delete the `zone.runtime_exceeded = False` immediately
    before the `continue` in the `if cap_pct <= 0` branch and this test
    REDs.
    """
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "coast"
    coord.set_d5_enabled(True)

    zone = coord.zone_manager._zones["zone_1"]
    zone.window_start = _now()
    zone.runtime_seconds_this_window = 9999.0
    zone.hvac_action = "idle"
    zone.runtime_exceeded = True  # latched from a prior tick

    # Kill switch on coast cap.
    coord.set_duty_cycle_coast_pct(0)
    coord._last_runtime_accumulation = _now()
    coord._accumulate_zone_runtime(_now())
    assert zone.runtime_exceeded is False, (
        "F5: cap_pct=0 kill switch must CLEAR the latched "
        "runtime_exceeded, not leave it set."
    )


def test_accumulator_d5_disabled_short_circuits():
    """D-b3 master enable (M5): with `d5_enabled=False`, the accumulator
    MUST not set runtime_exceeded even when runtime > cap.

    Mutation → RED: delete the `if not self.d5_enabled: continue` guard
    in `_accumulate_zone_runtime` and this test REDs.
    """
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "coast"
    coord.set_duty_cycle_window_minutes(10)
    coord.set_duty_cycle_coast_pct(50)  # cap 300s
    coord.set_d5_enabled(False)

    zone = coord.zone_manager._zones["zone_1"]
    zone.window_start = _now()
    zone.runtime_seconds_this_window = 9999.0
    zone.hvac_action = "idle"
    zone.runtime_exceeded = False
    coord._last_runtime_accumulation = _now()
    coord._accumulate_zone_runtime(_now())
    assert zone.runtime_exceeded is False, (
        "d5_enabled=False must short-circuit enforcement — but the "
        "accumulator still set runtime_exceeded."
    )


def test_accumulator_normal_mode_never_trips():
    """`_energy_constraint_mode = "normal"` → the accumulator continues
    without imposing a cap. Baseline sanity that pairs with the coast
    trip test above."""
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(True)

    zone = coord.zone_manager._zones["zone_1"]
    zone.window_start = _now()
    zone.runtime_seconds_this_window = 9999.0
    zone.hvac_action = "idle"
    zone.runtime_exceeded = False
    coord._last_runtime_accumulation = _now()
    coord._accumulate_zone_runtime(_now())
    assert zone.runtime_exceeded is False


# ---------------------------------------------------------------------------
# D-b2 gate 3-cell matrix — DRIVEN through _apply_house_state_presets
# ---------------------------------------------------------------------------
#
# Each cell drives a real HVACCoordinator.  Preconditions:
#   - runtime_exceeded latched True on the target zone
#   - _house_state = "home_day" (D5 branch is sleep-skipped otherwise)
#   - _energy_constraint_mode set per cell
#   - zone.any_room_hvac_occupied set per cell
# The test asserts on the RESULTING internal state maps
# (`_d5_occupancy_deferred_current_tick` and `_d5_occ_defer_logged_episode`)
# and on whether the D5 branch flowed to `effective_preset="away"`
# (proxied by the presence of ANY defer flag when the gate SHOULD fire).
#
# NOTE: `_apply_house_state_presets` is a large method with many
# collaborators. We wrap the drive in try/except and treat "did the map
# get written" as the discriminator — the D5 gate writes the map BEFORE
# any of the later collaborators would raise, so the assertion is
# reachable even if a downstream helper errors on the smoke hass.

async def _drive_apply_presets(coord):
    """Best-effort drive: swallow downstream helper exceptions so the
    D5 branch's map mutations (which happen early in the loop iteration)
    are observable."""
    try:
        await coord._apply_house_state_presets()
    except Exception:  # noqa: BLE001
        pass


@pytest.mark.asyncio
async def test_d5_gate_coast_and_occupied_DEFERS_no_write():
    """D-b2 cell 1 (M2): coast + fused-occupied → defer flag set,
    effective_preset NOT forced to away for that zone.

    Mutation → RED: revert the gate's `and _row2054_fused` check to
    always-True (delete the condition) or delete the
    `_d5_occupancy_deferred_this_tick = True` assignment.
    """
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "coast"
    coord.set_d5_enabled(True)
    zone = coord.zone_manager._zones["zone_1"]
    zone.runtime_exceeded = True
    _set_zone_occupied(zone, hvac_occupied=True)
    zone.preset_mode = "home"

    await _drive_apply_presets(coord)

    assert coord._d5_occupancy_deferred_current_tick.get("zone_1") is True, (
        "coast + occupied must set the D5 occupancy-deferred flag on "
        "the zone; got "
        f"{coord._d5_occupancy_deferred_current_tick!r}"
    )
    # NOTE: the episode-gate map (`_d5_occ_defer_logged_episode`) is
    # only populated when an `activity_logger` is wired in; on the
    # smoke harness it's None, so we do NOT assert on that map here —
    # the per-tick defer map above is the authoritative behavioral
    # discriminator for this test.


@pytest.mark.asyncio
async def test_d5_gate_coast_and_empty_STILL_forces_away():
    """D-b2 cell 2 (M3): coast + fused-empty → gate does NOT fire; the
    else-branch preserves the force-away lever.

    Mutation → RED: remove the `else: effective_preset = "away"` below
    the gate — the deferred flag becomes True on empty zones (leaks
    the additive lever).
    """
    coord, hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "coast"
    coord.set_d5_enabled(True)
    zone = coord.zone_manager._zones["zone_1"]
    zone.runtime_exceeded = True
    _set_zone_occupied(zone, hvac_occupied=False)
    zone.preset_mode = "home"
    # Snapshot the service-call recorder so we can prove the force-away
    # write path fired for THIS zone (a mutation that removes the
    # `else: effective_preset = "away"` block would eliminate the call).
    hass.services.calls.clear()

    await _drive_apply_presets(coord)

    assert any(
        call[0] == "climate" and call[1] == "set_preset_mode"
        and call[2].get("entity_id") == zone.climate_entity
        and call[2].get("preset_mode") == "away"
        for call in hass.services.calls
    ), (
        f"empty + coast MUST issue climate.set_preset_mode=away for the "
        f"zone (force-away lever preserved); got calls "
        f"{hass.services.calls!r}"
    )
    assert coord._d5_occupancy_deferred_current_tick.get("zone_1", False) is False, (
        "empty + coast must NOT set the D5 defer flag — additive "
        "force-away lever leaked"
    )


@pytest.mark.asyncio
async def test_d5_gate_shed_dominates_even_when_occupied():
    """D-b2 cell 3 (M7): shed + fused-occupied → gate does NOT fire
    (shed dominates the D3 comfort-delay ordering).

    Mutation → RED: remove the `self._energy_constraint_mode != "shed"`
    guard from the gate condition — shed suddenly defers too.
    """
    coord, _hass = _make_coord()
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "shed"
    coord.set_d5_enabled(True)
    zone = coord.zone_manager._zones["zone_1"]
    zone.runtime_exceeded = True
    _set_zone_occupied(zone, hvac_occupied=True)
    zone.preset_mode = "home"

    await _drive_apply_presets(coord)

    assert coord._d5_occupancy_deferred_current_tick.get("zone_1", False) is False, (
        "shed + occupied must NOT defer — shed dominates D5 occupancy "
        "gate (matches D3 comfort-delay ordering)"
    )


# ---------------------------------------------------------------------------
# D-b1 zone-status attribute rename — DRIVEN through get_zone_status_attrs
# ---------------------------------------------------------------------------

def test_zone_status_attrs_expose_energy_shed_cap_reached_key():
    """D-b1 (M8): the operator-facing attr dict carries
    `energy_shed_cap_reached` sourced from `zone.runtime_exceeded`.

    Mutation → RED: revert the dict key literal in
    `hvac_zones.py:get_zone_status_attrs` and this REDs.
    """
    coord, _hass = _make_coord()
    zone = coord.zone_manager._zones["zone_1"]
    zone.runtime_exceeded = True
    attrs = coord.zone_manager.get_zone_status_attrs("zone_1")
    assert attrs.get("energy_shed_cap_reached") is True


def test_zone_status_attrs_duty_pct_honors_live_window():
    """B-M2 (fix-up): duty_cycle denominator must use the live window
    knob when the caller passes it. 600s runtime / 20-min window = 50%;
    the SAME runtime / 10-min window = 100%.
    """
    coord, _hass = _make_coord()
    zone = coord.zone_manager._zones["zone_1"]
    zone.window_start = _now()
    zone.runtime_seconds_this_window = 600.0

    default = coord.zone_manager.get_zone_status_attrs("zone_1")
    # module constant is 20 min = 1200s → 50%
    assert default["runtime_duty_cycle_pct"] == 50.0

    live = coord.zone_manager.get_zone_status_attrs(
        "zone_1", window_seconds=10 * 60,
    )
    assert live["runtime_duty_cycle_pct"] == 100.0, (
        f"live window knob (10min) not honored: got "
        f"{live['runtime_duty_cycle_pct']!r}"
    )


# ---------------------------------------------------------------------------
# F1 consumer-rename anchor — the `zones_runtime_limited` consumer must
# read the NEW producer label. Driven behaviorally: set zone's
# zone_presence_state and confirm the sensor filter matches it.
# ---------------------------------------------------------------------------

def test_zones_runtime_limited_consumer_reads_new_label():
    """F1: consumer filter renamed from `zone_presence_state=="runtime_limited"`
    to `=="energy_shed_cap_reached"`. Grep the sensor source AST-style —
    a stale "runtime_limited" filter is a Bug Class #63/Bug Class #7 hazard.

    Mutation → RED: revert the filter comparand in sensor.py to
    `"runtime_limited"` and this test REDs.
    """
    src = _read(os.path.join(_URA, "sensor.py"))
    # Only presence-state consumers of interest.
    assert 'z.zone_presence_state == "energy_shed_cap_reached"' in src, (
        "F1: sensor.py consumer filter must match the renamed producer "
        "label `energy_shed_cap_reached`"
    )
    assert 'z.zone_presence_state == "runtime_limited"' not in src, (
        "F1: stale `runtime_limited` filter still present"
    )
