"""HVAC W1/W2 finish — PART C (W2-2, ruling Q5): the stuck-occupancy
failsafe's occupancy clock is not reset while a room is reloading.

Falsifiable invariant (plan §C.1):

INV-C  On any pass where zone Z contains a TRANSIENT (reloading) room and
       fused HVAC occupancy is False, `Z.continuous_occupied_since` after the
       pass equals its value before the pass. The v5.103.20
       `last_occupied_time` back-fill runs exactly as it does today (M4).

Drives the REAL `ZoneManager.update_room_conditions` against real HA
`ConfigEntryState` members (never hand-copied), same pattern as
test_hvac_live_room_establishment.py.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from homeassistant.config_entries import ConfigEntryState  # noqa: E402

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_zones as _hvac_zones,
)

ZoneManager = _hvac_zones.ZoneManager
ZoneState = _hvac_zones.ZoneState

NOW = datetime(2026, 9, 28, 20, 0, 0, tzinfo=timezone.utc)
CLOCK = datetime(2026, 9, 28, 14, 0, 0, tzinfo=timezone.utc)   # restored clock


class _Entry:
    def __init__(self, room_name, state=ConfigEntryState.LOADED):
        self.entry_id = f"e_{room_name}"
        self.state = state
        self.disabled_by = None
        self.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: room_name}
        self.options: dict = {}


class _RoomCoord:
    """Room coordinator surface the producer reads (lighting `occupied` +
    the v5.103.20 HVAC-evidence accessors)."""

    def __init__(self, occupied=False, ev=None, active=False):
        self.data = {"occupied": occupied, "temperature": None, "humidity": None}
        self._ev = ev
        self._active = active
        self.last_update_success = True

    def get_last_hvac_evidence_time(self):
        return self._ev

    def is_hvac_evidence_active(self):
        return self._active


def _zm(entries, coords):
    hass = MagicMock()

    class _CEs:
        def async_entries(self, dom):
            return list(entries)

    hass.config_entries = _CEs()
    hass.data = {DOMAIN: dict(coords)}
    hass.states = MagicMock()
    hass.states.get = lambda ent_id: None
    zm = ZoneManager(hass)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = [e.data[CONF_ROOM_NAME] for e in entries]
    zm._zones["z1"] = zone
    return zm, zone


def _at(t):
    return (patch.object(_hvac_zones.dt_util, "now", return_value=t),
            patch.object(_hvac_zones.dt_util, "utcnow", return_value=t))


def _pass(zm, t, house_state="home_day"):
    p1, p2 = _at(t)
    with p1, p2:
        zm.update_room_conditions(house_state=house_state)


def _two_rooms(reload_state=ConfigEntryState.SETUP_IN_PROGRESS, *, ev=None):
    ok = _Entry("r_ok")
    rel = _Entry("r_reload", state=reload_state)
    coords = {ok.entry_id: _RoomCoord(occupied=False, ev=ev, active=False)}
    return _zm([ok, rel], coords)


def test_continuous_clock_not_reset_while_room_reloading():
    zm, zone = _two_rooms()
    zone.continuous_occupied_since = CLOCK
    _pass(zm, NOW)
    assert zone.any_room_hvac_occupied is False
    assert zm.is_zone_transient_blocked("z1") is True
    assert zone.continuous_occupied_since == CLOCK


def test_continuous_clock_resets_when_no_room_is_reloading():
    """Twin (today's behaviour kept): every room live and the zone empty ->
    the clock resets."""
    ok = _Entry("r_ok")
    zm, zone = _zm([ok], {ok.entry_id: _RoomCoord(occupied=False)})
    zone.continuous_occupied_since = CLOCK
    _pass(zm, NOW)
    assert zone.continuous_occupied_since is None


def test_backfill_still_runs_while_room_reloading():
    """M4: the v5.103.20 `last_occupied_time` back-fill in the same `else`
    still runs while a room reloads. r_ok's evidence ended at NOW-10 min;
    its release is ev + its hold, so the back-fill moves last_occupied_time
    forward from None to a value <= NOW."""
    ev = NOW - timedelta(minutes=10)
    zm, zone = _two_rooms(ev=ev)
    zone.continuous_occupied_since = CLOCK
    zone.last_occupied_time = None
    _pass(zm, NOW)
    assert zone.continuous_occupied_since == CLOCK
    assert zone.last_occupied_time is not None
    assert ev < zone.last_occupied_time <= NOW


def test_continuous_clock_resets_after_room_excluded():
    """Discharge: past the 300 s transient grace the room is EXCLUDED, the
    zone is no longer transient-blocked, and the clock resets."""
    zm, zone = _two_rooms(reload_state=ConfigEntryState.NOT_LOADED)
    zone.continuous_occupied_since = CLOCK
    _pass(zm, NOW)
    assert zone.continuous_occupied_since == CLOCK
    _pass(zm, NOW + timedelta(seconds=299))
    assert zone.continuous_occupied_since == CLOCK
    _pass(zm, NOW + timedelta(seconds=301))
    assert zm._room_hvac_class["r_reload"][0] == "excluded"
    assert zone.continuous_occupied_since is None


def test_continuous_clock_resets_after_room_loaded_and_empty():
    zm, zone = _two_rooms(reload_state=ConfigEntryState.SETUP_IN_PROGRESS)
    zone.continuous_occupied_since = CLOCK
    _pass(zm, NOW)
    assert zone.continuous_occupied_since == CLOCK
    zm.hass.config_entries.async_entries("x")[1].state = ConfigEntryState.LOADED
    # The reloaded room's coordinator is back (empty).
    zm.hass.data[DOMAIN]["e_r_reload"] = _RoomCoord(occupied=False)
    _pass(zm, NOW + timedelta(seconds=60))
    assert zm.is_zone_transient_blocked("z1") is False
    assert zone.continuous_occupied_since is None


def test_boot_pass_keeps_restored_continuous_clock():
    """First pass of a fresh ZoneManager (classification not ready before it)
    with a room still loading: the clock restored from the zone-state store
    survives. Classification runs inside the same pass, before the rollup,
    so the guard already applies on the boot pass."""
    zm, zone = _two_rooms(reload_state=ConfigEntryState.SETUP_IN_PROGRESS)
    assert zm._hvac_classification_ready is False
    zone.continuous_occupied_since = CLOCK
    _pass(zm, NOW)
    assert zone.continuous_occupied_since == CLOCK


def test_occupied_pass_unchanged_by_guard():
    """Byte-identical on the occupied path: an occupied zone keeps / sets
    its clock exactly as before."""
    ok = _Entry("r_ok")
    rel = _Entry("r_reload", state=ConfigEntryState.SETUP_IN_PROGRESS)
    zm, zone = _zm([ok, rel], {ok.entry_id: _RoomCoord(occupied=True, ev=NOW, active=True)})
    zone.continuous_occupied_since = None
    _pass(zm, NOW)
    assert zone.any_room_hvac_occupied is True
    assert zone.continuous_occupied_since is not None
