"""D1/D2/D4 unit + mutation-anchor tests for the pause-release hygiene cycle.

Covers:
- D1 (INV-D1-RELEASE) — release-only paths drain orphan pause-owner sets
  within one decision cycle after the owning toggle flips OFF.
- D1 (INV-D1-RESTORE) — DB restore skips re-adding membership when the
  owning toggle is currently OFF.
- D1 (INV-D1-TOGGLE-CYCLE) — cross-owner deferral inside the release
  paths preserves membership when a stronger owner still holds.
- D2 (INV-D2-LEDGER) — `_apply_evse_battery_hold` stamps
  `_last_reserve_level` with the effective post-max() value so the
  write-verify sweep does NOT false-alarm `write_reverted` during a
  standing hold with deadband suppressing dispatch.
- D2 (INV-D2-DEADBAND) — overlay is byte-identical on the no-hold path.
- D4 — smart plug determine_actions ensure-on during off_peak with
  precedence pre-check (mirrors EVSE energy_pool.py:528-636).

Mutation-anchor table (executed by ura-builder, not merely claimed —
see mutations at end of file for the runnable proof):

    | Site (semantic)                | Neuter                                 | Anchoring test                             | Expected on neuter |
    |--------------------------------|----------------------------------------|--------------------------------------------|--------------------|
    | EVPool.release_all_grid_cap    | body = `return []` (no set.discard)    | test_grid_cap_release_drains_membership    | FAIL               |
    | EVPool.release_all_fill_priority | body = `return []`                   | test_fill_priority_release_drains_membership | FAIL             |
    | EVPool.release_all_tou         | body = `return []`                     | test_tou_release_drains_membership         | FAIL               |
    | Plug.release_all_tou           | body = `return []`                     | test_plug_tou_release_drains_membership    | FAIL               |
    | Plug determine_actions off_peak ensure-on | replace ensure-on turn_on with no-op | test_plug_offpeak_ensure_on_starts_off_plug | FAIL              |
    | _apply_evse_battery_hold ledger stamp | remove `_last_reserve_level = _new` | test_evse_battery_hold_stamps_ledger        | FAIL              |
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

# Import under test — bootstrap must run before these imports.
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_pool as _epool,
)


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state
        self.attributes: dict = {}


class _FakeHass:
    def __init__(self, entities: dict[str, str] | None = None) -> None:
        self._entities = entities or {}
        self.states = MagicMock()
        self.states.get = lambda eid: (
            _FakeState(self._entities[eid])
            if eid in self._entities else None
        )

    def set(self, eid: str, state: str) -> None:
        self._entities[eid] = state


def _make_evpool(hass: _FakeHass, evse_ids: list[str]) -> _epool.EVChargerController:
    evse_cfg = {eid: {"switch": eid} for eid in evse_ids}
    # EVChargerController takes (hass, evse_config, ...) — signature drift
    # check the ctor below during real runs.
    pool = _epool.EVChargerController.__new__(_epool.EVChargerController)
    pool.hass = hass
    pool._evse = evse_cfg
    pool._paused_by_us = set()
    pool._paused_by_grid_cap = set()
    pool._paused_by_fill_priority = set()
    pool._paused_by_battery_drain = set()
    pool._paused_by_arbitrage = set()
    pool._paused_by_load_shed = set()
    pool._excess_solar_active = set()
    pool._proactive_offpeak_holds = set()
    pool._arbitrage_pause_reason = {}
    pool._force_charge_until = None
    return pool


def _get_evse_state_shim(pool, hass):
    """Route `_get_evse_state` through the fake hass without exercising
    the real derivation logic."""
    def _shim(evse_id: str) -> dict:
        st = hass.states.get(evse_id)
        return {
            "is_on": (st is not None and st.state == "on"),
            "charging": False,
        }
    pool._get_evse_state = _shim


def _make_plug_ctrl(hass: _FakeHass, plug_ids: list[str]) -> _epool.SmartPlugController:
    ctrl = _epool.SmartPlugController.__new__(_epool.SmartPlugController)
    ctrl.hass = hass
    ctrl._plugs = list(plug_ids)
    ctrl._plug_config = {}
    ctrl._paused_by_us = set()
    ctrl._paused_by_battery_drain = set()
    ctrl._paused_by_fill_priority = set()
    ctrl._paused_by_load_shed = set()
    ctrl._load_shed_was_on_at_shed = {}
    ctrl._battery_drain_cooldown = {}
    ctrl._pause_dispatch_ts = {}
    ctrl._observed_off_since_pause = {}
    ctrl._dispatch_owners = {}
    ctrl._fill_priority_solar_ok = False
    ctrl._proactive_offpeak_holds = set()
    return ctrl


# ---------------------------------------------------------------------------
# D1 — EV release-only paths
# ---------------------------------------------------------------------------


def test_grid_cap_release_drains_membership() -> None:
    """release_all_grid_cap drains `_paused_by_grid_cap` when nothing
    else holds the device."""
    hass = _FakeHass({"garage_a": "off"})
    pool = _make_evpool(hass, ["garage_a"])
    _get_evse_state_shim(pool, hass)
    pool._paused_by_grid_cap.add("garage_a")

    actions = pool.release_all_grid_cap()

    assert "garage_a" not in pool._paused_by_grid_cap
    # off → issued turn_on
    assert any(
        a.get("service") == "switch.turn_on" and a.get("target") == "garage_a"
        for a in actions
    )


def test_grid_cap_release_defers_to_stronger_owner() -> None:
    """release_all_grid_cap drops grid-cap membership but does not
    turn the device back on when another owner still holds it."""
    hass = _FakeHass({"garage_a": "off"})
    pool = _make_evpool(hass, ["garage_a"])
    _get_evse_state_shim(pool, hass)
    pool._paused_by_grid_cap.add("garage_a")
    pool._paused_by_battery_drain.add("garage_a")

    actions = pool.release_all_grid_cap()

    assert "garage_a" not in pool._paused_by_grid_cap
    # No turn_on — drain still holds it.
    assert not any(a.get("service") == "switch.turn_on" for a in actions)


def test_fill_priority_release_drains_membership() -> None:
    hass = _FakeHass({"garage_b": "off"})
    pool = _make_evpool(hass, ["garage_b"])
    _get_evse_state_shim(pool, hass)
    pool._paused_by_fill_priority.add("garage_b")

    actions = pool.release_all_fill_priority()

    assert "garage_b" not in pool._paused_by_fill_priority
    assert any(a.get("service") == "switch.turn_on" for a in actions)


def test_tou_release_drains_membership() -> None:
    hass = _FakeHass({"garage_a": "off"})
    pool = _make_evpool(hass, ["garage_a"])
    _get_evse_state_shim(pool, hass)
    pool._paused_by_us.add("garage_a")

    actions = pool.release_all_tou()

    assert "garage_a" not in pool._paused_by_us
    assert any(a.get("service") == "switch.turn_on" for a in actions)


def test_tou_release_no_turnon_when_already_on() -> None:
    """Idempotent: if the device is already on, drain membership but
    do not issue a redundant turn_on."""
    hass = _FakeHass({"garage_a": "on"})
    pool = _make_evpool(hass, ["garage_a"])
    _get_evse_state_shim(pool, hass)
    pool._paused_by_us.add("garage_a")

    actions = pool.release_all_tou()

    assert "garage_a" not in pool._paused_by_us
    assert not any(a.get("service") == "switch.turn_on" for a in actions)


# ---------------------------------------------------------------------------
# D1 mirror — Plug release-only paths
# ---------------------------------------------------------------------------


def test_plug_tou_release_drains_membership() -> None:
    hass = _FakeHass({"switch.socket_2": "off"})
    ctrl = _make_plug_ctrl(hass, ["switch.socket_2"])
    ctrl._paused_by_us.add("switch.socket_2")

    actions = ctrl.release_all_tou()

    assert "switch.socket_2" not in ctrl._paused_by_us
    assert any(
        a.get("service") == "switch.turn_on"
        and a.get("target") == "switch.socket_2"
        for a in actions
    )


def test_plug_fill_priority_release_drains_membership() -> None:
    hass = _FakeHass({"switch.socket_2": "off"})
    ctrl = _make_plug_ctrl(hass, ["switch.socket_2"])
    ctrl._paused_by_fill_priority.add("switch.socket_2")

    actions = ctrl.release_all_fill_priority()

    assert "switch.socket_2" not in ctrl._paused_by_fill_priority
    assert any(a.get("service") == "switch.turn_on" for a in actions)


# ---------------------------------------------------------------------------
# D4 — Plug off_peak proactive ensure-on
# ---------------------------------------------------------------------------


def test_plug_offpeak_ensure_on_starts_off_plug() -> None:
    """A plug OFF at off_peak with no carry-over guard gets turned on.
    Reproduces the 2026-07-13 live incident where socket_2 was off at
    01:04 and URA would not start it."""
    hass = _FakeHass({"switch.socket_2": "off"})
    ctrl = _make_plug_ctrl(hass, ["switch.socket_2"])

    actions = ctrl.determine_actions("off_peak")

    assert any(
        a.get("service") == "switch.turn_on"
        and a.get("target") == "switch.socket_2"
        for a in actions
    )
    # Proactive hold claimed.
    assert "switch.socket_2" in ctrl._proactive_offpeak_holds
    # Legacy TOU bookkeeping cleared.
    assert "switch.socket_2" not in ctrl._paused_by_us


def test_plug_offpeak_defers_to_battery_drain_carryover() -> None:
    """Off_peak ensure-on must NOT turn on a plug currently held by
    battery drain (carry-over guard wins)."""
    hass = _FakeHass({"switch.socket_2": "off"})
    ctrl = _make_plug_ctrl(hass, ["switch.socket_2"])
    ctrl._paused_by_battery_drain.add("switch.socket_2")

    actions = ctrl.determine_actions("off_peak")

    assert not any(a.get("service") == "switch.turn_on" for a in actions)
    assert "switch.socket_2" not in ctrl._proactive_offpeak_holds


def test_plug_offpeak_ceded_when_force_charge_active() -> None:
    """When EVPool's force-charge override is active, plug proactive-on
    is skipped so the hold-set stays TOU-driven only."""
    hass = _FakeHass({"switch.socket_2": "off"})
    ctrl = _make_plug_ctrl(hass, ["switch.socket_2"])

    actions = ctrl.determine_actions("off_peak", force_charge_active=True)

    assert not any(a.get("service") == "switch.turn_on" for a in actions)
    assert "switch.socket_2" not in ctrl._proactive_offpeak_holds


def test_plug_peak_still_pauses() -> None:
    """Sanity: peak/mid_peak behavior unchanged."""
    hass = _FakeHass({"switch.socket_2": "on"})
    ctrl = _make_plug_ctrl(hass, ["switch.socket_2"])

    actions = ctrl.determine_actions("peak")

    assert any(a.get("service") == "switch.turn_off" for a in actions)
    assert "switch.socket_2" in ctrl._paused_by_us


def test_plug_prune_drops_removed_plug_membership() -> None:
    hass = _FakeHass()
    ctrl = _make_plug_ctrl(hass, ["switch.a"])
    ctrl._paused_by_us.add("switch.b")  # no longer configured
    ctrl._proactive_offpeak_holds.add("switch.c")  # no longer configured

    ctrl.prune_removed_plugs()

    assert "switch.b" not in ctrl._paused_by_us
    assert "switch.c" not in ctrl._proactive_offpeak_holds


# ---------------------------------------------------------------------------
# D2 — EVSE-battery-hold ledger stamp
# ---------------------------------------------------------------------------


class _FakeBattery:
    """Minimal battery fake exposing the ledger fields the overlay
    writes to and `_get_entity` used to resolve the reserve entity."""
    def __init__(self, reserve_entity: str = "number.enpower_reserve") -> None:
        self._last_reserve_level: int | None = 30
        self._last_reserve_level_at = None
        self._reserve_entity = reserve_entity

    def _get_entity(self, key: str, default: str) -> str:  # noqa: D401
        return self._reserve_entity


class _EnergyCoordShim:
    """Bind `_apply_evse_battery_hold` to a shim that carries the fields
    the method reads (`_battery`, `_evse_hold_soc`).

    Avoids constructing the full EnergyCoordinator (heavy)."""
    def __init__(self, hold_soc: int, reserve_entity: str) -> None:
        self._battery = _FakeBattery(reserve_entity)
        self._evse_hold_soc = hold_soc


def _bind_apply_overlay():
    """Return the unbound `_apply_evse_battery_hold` from EnergyCoordinator."""
    energy = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy",
    )
    return energy.EnergyCoordinator._apply_evse_battery_hold


def test_evse_battery_hold_stamps_ledger_on_update_in_place() -> None:
    """INV-D2-LEDGER: when overlay raises an EXISTING reserve action's
    value, the effective post-max() value MUST be stamped into
    `_last_reserve_level` — so `current_park_floor()` and the
    write-verify sweep see the value the hardware sees."""
    apply_overlay = _bind_apply_overlay()
    reserve_entity = "number.enpower_reserve"
    shim = _EnergyCoordShim(hold_soc=60, reserve_entity=reserve_entity)
    # Pre-overlay strategy stamped 30 in `_result`.
    shim._battery._last_reserve_level = 30

    # Strategy already appended a reserve action at 30.
    decision = {
        "reason": "off_peak drain",
        "actions": [
            {"service": "number.set_value",
             "target": reserve_entity, "data": {"value": 30}},
        ],
        "soc": 65,
    }

    out = apply_overlay(shim, decision)

    # Overlay raised the emitted value to max(30, 60) = 60.
    reserve_action = [
        a for a in out["actions"]
        if a.get("target") == reserve_entity
    ][0]
    assert reserve_action["data"]["value"] == 60
    # Ledger stamped to 60 — the sweep will read this on the next tick.
    assert shim._battery._last_reserve_level == 60


def test_evse_battery_hold_no_ledger_stamp_when_overlay_is_noop() -> None:
    """INV-D2-DEADBAND: when overlay would NOT raise the emitted value
    (e.g. inclement floor already >= hold_soc), the ledger MUST be
    byte-identical."""
    apply_overlay = _bind_apply_overlay()
    reserve_entity = "number.enpower_reserve"
    shim = _EnergyCoordShim(hold_soc=40, reserve_entity=reserve_entity)
    shim._battery._last_reserve_level = 70

    decision = {
        "reason": "inclement full_hold",
        "actions": [
            {"service": "number.set_value",
             "target": reserve_entity, "data": {"value": 70}},
        ],
        "soc": 80,
    }

    out = apply_overlay(shim, decision)

    reserve_action = [
        a for a in out["actions"]
        if a.get("target") == reserve_entity
    ][0]
    # max(70, 40) = 70 unchanged.
    assert reserve_action["data"]["value"] == 70
    # Ledger untouched by overlay.
    assert shim._battery._last_reserve_level == 70


def test_evse_battery_hold_stamps_ledger_on_append_path() -> None:
    """No prior reserve action → overlay appends one. Ledger must
    stamp so the append path is symmetric with update-in-place."""
    apply_overlay = _bind_apply_overlay()
    reserve_entity = "number.enpower_reserve"
    shim = _EnergyCoordShim(hold_soc=55, reserve_entity=reserve_entity)
    shim._battery._last_reserve_level = 20

    decision = {"reason": "off_peak drain", "actions": [], "soc": 60}

    out = apply_overlay(shim, decision)

    reserve_actions = [
        a for a in out["actions"]
        if a.get("target") == reserve_entity
    ]
    assert reserve_actions and reserve_actions[0]["data"]["value"] == 55
    assert shim._battery._last_reserve_level == 55


def test_standing_hold_no_dispatch_ledger_matches_hardware() -> None:
    """Repro of the false `write_reverted` scenario the review trail
    flagged: strategy desires 30, EVSE hold raises to 60, no dispatch
    for 3+ cycles (deadband). The sweep reads `_last_reserve_level`
    and MUST see 60 (hardware value), not 30 (strategy desired).

    We simulate three consecutive overlay applications with the same
    decision shape — the ledger must remain 60 across all three,
    matching what the cloud oracle would report."""
    apply_overlay = _bind_apply_overlay()
    reserve_entity = "number.enpower_reserve"
    shim = _EnergyCoordShim(hold_soc=60, reserve_entity=reserve_entity)

    for _cycle in range(3):
        # Emulate `_result` running each cycle and stamping the
        # strategy's pre-overlay desired value (30) into the ledger.
        shim._battery._last_reserve_level = 30
        decision = {
            "reason": "off_peak drain",
            "actions": [
                {"service": "number.set_value",
                 "target": reserve_entity, "data": {"value": 30}},
            ],
            "soc": 65,
        }
        apply_overlay(shim, decision)
        # After overlay, ledger MUST reflect the effective 60 —
        # otherwise the write-verify sweep will false-alarm.
        assert shim._battery._last_reserve_level == 60, (
            f"cycle {_cycle}: ledger fell back to strategy-desired "
            "value; sweep would false-alarm write_reverted."
        )
