"""HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1 — zone vacancy sweep cleanup.

Drives real production code:
  (1) switch "46 · Vacancy Auto-Off" is a MASTER gate ANDed with each
      zone's own CONF_ZONE_VACANCY_SWEEP_ENABLED (it no longer overwrites
      the per-zone value) — real ``HVACZoneSweepSwitch`` class body.
  (2) ``vacancy_sweeps_today`` counts only sweeps that turned something
      off; a no-op still spends the vacancy (done flag).
  (3) one ``vacancy_sweep`` activity row per real sweep listing what was
      turned off; none for a no-op.
  (4) a zone with an active pre-arrival keeps its fans (lights still swept).
  Call-site anchors: the row-1 and D6 sites in ``_apply_house_state_presets``
  each route through ``_maybe_run_vacancy_sweep``.

Harnesses are imported from sibling files (their module-load stubbing is
self-restoring; the live-room harness's module-scoped shim fixture is
imported so it also applies here).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_hvac_vacancy_sweep_manual_on_guard import (  # noqa: F401
    DOMAIN,
    _make_hvac_coord,
    _run,
)
from test_restore_guard_52_sweep import _load_class
from test_hvac_live_room_hold_wire_in import (  # noqa: F401
    _scoped_shim_purge,
    _make_coord,
    _pin_aware_clock,
    _seed_zone_all_live_and_empty,
    _drive_apply_presets,
)


class _Counter:
    def __init__(self):
        self.value = 0

    def increment(self):
        self.value += 1


class _Zone:
    def __init__(self, rooms, zone_id="zone_9", *, enabled=True,
                 done=False, occupied=False):
        self.zone_id = zone_id
        self.zone_name = "ZoneA"
        self.rooms = rooms
        self.vacancy_sweep_enabled = enabled
        self.vacancy_sweep_done = done
        self.any_room_occupied = occupied


class _CaptureLogger:
    def __init__(self):
        self.rows: list[dict] = []

    async def log(self, **kw):
        self.rows.append(kw)


def _coord(rooms=("FreeRoom",), *, all_off=False):
    coord, log = _make_hvac_coord({r: False for r in rooms})
    coord._vacancy_sweeps_today = _Counter()
    coord._vacancy_sweep_master_enabled = True
    coord._pre_arrival_zones = set()
    coord._house_state = "home_day"
    tasks: list = []
    coord.hass.async_create_task = lambda c: tasks.append(c)
    alog = _CaptureLogger()
    coord.hass.data[DOMAIN]["activity_logger"] = alog
    if all_off:
        for r in rooms:
            for eid in (f"fan.{r.lower()}", f"light.{r.lower()}"):
                coord.hass.states.get(eid).state = "off"
    return coord, log, tasks, alog


def _offs(log):
    return sorted(d["entity_id"] for (_dom, svc, d) in log if svc == "turn_off")


def _drain(tasks):
    for t in list(tasks):
        _run(t)


# ---------------------------------------------------------------------------
# (1) master gate AND per-zone opt-out
# ---------------------------------------------------------------------------

def test_both_on_sweeps_and_counts():
    coord, log, tasks, _ = _coord()
    zone = _Zone(["FreeRoom"])
    _run(coord._maybe_run_vacancy_sweep(zone))
    assert _offs(log) == ["fan.freeroom", "light.freeroom"]
    assert zone.vacancy_sweep_done is True
    assert coord._vacancy_sweeps_today.value == 1


def test_master_off_disables_sweep_even_when_zone_enabled():
    coord, log, _, _ = _coord()
    coord._vacancy_sweep_master_enabled = False
    zone = _Zone(["FreeRoom"], enabled=True)
    _run(coord._maybe_run_vacancy_sweep(zone))
    assert _offs(log) == []
    assert zone.vacancy_sweep_done is False
    assert coord._vacancy_sweeps_today.value == 0


def test_zone_opt_out_honoured_when_master_on():
    coord, log, _, _ = _coord()
    zone = _Zone(["FreeRoom"], enabled=False)
    _run(coord._maybe_run_vacancy_sweep(zone))
    assert _offs(log) == []
    assert zone.vacancy_sweep_done is False


def test_lighting_occupied_zone_not_swept():
    coord, log, _, _ = _coord()
    zone = _Zone(["FreeRoom"], occupied=True)
    _run(coord._maybe_run_vacancy_sweep(zone))
    assert _offs(log) == []
    assert zone.vacancy_sweep_done is False


def test_already_swept_vacancy_not_swept_again():
    coord, log, _, _ = _coord()
    zone = _Zone(["FreeRoom"], done=True)
    _run(coord._maybe_run_vacancy_sweep(zone))
    assert _offs(log) == []
    assert coord._vacancy_sweeps_today.value == 0


class _FakeZM:
    def __init__(self, zones):
        self.zones = zones


def _switch_with(hvac):
    Switch = _load_class("HVACZoneSweepSwitch")
    sw = Switch(MagicMock(), MagicMock())
    sw._get_hvac = lambda: hvac
    sw.async_write_ha_state = lambda: None
    return sw


def test_global_switch_does_not_overwrite_per_zone_value():
    z_off = SimpleNamespace(vacancy_sweep_enabled=False)
    z_on = SimpleNamespace(vacancy_sweep_enabled=True)
    hvac = SimpleNamespace(
        zone_manager=_FakeZM({"zone_1": z_off, "zone_2": z_on}),
        vacancy_sweep_master_enabled=None,
    )
    sw = _switch_with(hvac)
    _run(sw.async_turn_on())
    assert hvac.vacancy_sweep_master_enabled is True
    assert z_off.vacancy_sweep_enabled is False  # per-zone opt-out kept
    assert z_on.vacancy_sweep_enabled is True
    _run(sw.async_turn_off())
    assert hvac.vacancy_sweep_master_enabled is False
    assert z_on.vacancy_sweep_enabled is True  # not overwritten either way
    assert z_off.vacancy_sweep_enabled is False


def test_hvac_ready_signal_repushes_master_value():
    hvac = SimpleNamespace(
        zone_manager=_FakeZM({}), vacancy_sweep_master_enabled=True,
    )
    sw = _switch_with(hvac)
    sw._is_on = False
    sw._handle_hvac_ready()  # e.g. a rebuilt coordinator starts at True
    assert hvac.vacancy_sweep_master_enabled is False


# ---------------------------------------------------------------------------
# (2) + (3) real sweeps only: counter + activity row
# ---------------------------------------------------------------------------

def test_noop_sweep_spends_vacancy_but_not_counted_no_row():
    coord, log, tasks, alog = _coord(all_off=True)
    zone = _Zone(["FreeRoom"])
    _run(coord._maybe_run_vacancy_sweep(zone))
    _drain(tasks)
    assert _offs(log) == []
    assert zone.vacancy_sweep_done is True  # once per vacancy
    assert coord._vacancy_sweeps_today.value == 0
    assert alog.rows == []


def test_real_sweep_returns_entities_and_writes_one_row():
    coord, log, tasks, alog = _coord()
    zone = _Zone(["FreeRoom"])
    turned_off = _run(coord._execute_vacancy_sweep(zone))
    _drain(tasks)
    assert sorted(turned_off) == ["fan.freeroom", "light.freeroom"]
    assert len(alog.rows) == 1
    row = alog.rows[0]
    assert row["coordinator"] == "hvac"
    assert row["action"] == "vacancy_sweep"
    assert row["zone"] == "zone_9"
    assert sorted(row["details"]["turned_off"]) == [
        "fan.freeroom", "light.freeroom",
    ]
    assert "light.freeroom" in row["description"]


def test_observation_mode_returns_empty_list():
    coord, log, _, _ = _coord()
    coord._observation_mode = True
    assert _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"]))) == []
    assert _offs(log) == []


# ---------------------------------------------------------------------------
# (4) pre-arrival fan exemption
# ---------------------------------------------------------------------------

def test_pre_arrival_zone_keeps_fans_but_sweeps_lights():
    coord, log, tasks, alog = _coord()
    zone = _Zone(["FreeRoom"], zone_id="zone_1")
    coord._pre_arrival_zones = {"zone_1"}
    _run(coord._maybe_run_vacancy_sweep(zone))
    _drain(tasks)
    assert _offs(log) == ["light.freeroom"]
    assert alog.rows[0]["details"]["pre_arrival_fans_kept"] is True


def test_other_zone_pre_arrival_does_not_exempt_fans():
    coord, log, _, _ = _coord()
    zone = _Zone(["FreeRoom"], zone_id="zone_1")
    coord._pre_arrival_zones = {"zone_2"}
    _run(coord._maybe_run_vacancy_sweep(zone))
    assert _offs(log) == ["fan.freeroom", "light.freeroom"]


# ---------------------------------------------------------------------------
# Call-site anchors in the enclosing method _apply_house_state_presets
# ---------------------------------------------------------------------------

def _recording_sweep(coord, result):
    calls: list = []

    async def _fake(zone):
        calls.append(zone.zone_id)
        return list(result)

    coord._execute_vacancy_sweep = _fake
    return calls


@pytest.mark.asyncio
async def test_row1_site_runs_sweep_and_counts(monkeypatch):
    coord, hass = _make_coord()
    pinned = _pin_aware_clock(monkeypatch)
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "home"
    _seed_zone_all_live_and_empty(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    zone.vacancy_sweep_enabled = True
    zone.vacancy_sweep_done = False
    zone.last_occupied_time = pinned - timedelta(minutes=coord._vacancy_grace + 5)
    calls = _recording_sweep(coord, ["light.x"])
    before = coord.vacancy_sweeps_today
    await _drive_apply_presets(coord)
    assert calls == ["zone_1"]
    assert zone.vacancy_sweep_done is True
    assert coord.vacancy_sweeps_today == before + 1


@pytest.mark.asyncio
async def test_d6_stale_site_runs_sweep(monkeypatch):
    coord, hass = _make_coord()
    pinned = _pin_aware_clock(monkeypatch)
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "home"
    _seed_zone_all_live_and_empty(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    # HVAC-fused occupied for longer than the max (stuck sensor), lighting
    # empty: row-1 cannot retreat (not fused-empty), D6 forces away + sweeps.
    assert zone.room_conditions
    zone.room_conditions[0].hvac_occupied = True
    for rc in zone.room_conditions:
        rc.occupied = False
    assert zone.any_room_hvac_occupied and not zone.any_room_occupied
    zone.continuous_occupied_since = pinned - timedelta(
        hours=coord._max_occupancy_hours + 1,
    )
    zone.vacancy_sweep_enabled = True
    zone.vacancy_sweep_done = False
    hass.data.get(DOMAIN, {}).pop("coordinator_manager", None)
    calls = _recording_sweep(coord, [])
    before = coord.vacancy_sweeps_today
    await _drive_apply_presets(coord)
    assert calls == ["zone_1"]
    assert zone.vacancy_sweep_done is True
    assert coord.vacancy_sweeps_today == before  # no-op not counted


@pytest.mark.asyncio
async def test_row1_site_skips_sweep_when_lighting_occupied(monkeypatch):
    """A-HIGH/B-CRIT-1 (2026-09-17): a standing hallway occupant makes the
    zone HVAC-empty (circulation exclusion) but lighting-occupied. The zone
    retreats (row-1) yet the hallway lights must stay on: no sweep."""
    coord, hass = _make_coord()
    pinned = _pin_aware_clock(monkeypatch)
    coord._house_state = "home_day"
    coord._energy_constraint_mode = "normal"
    coord.set_d5_enabled(False)
    for _z in coord.zone_manager.zones.values():
        _z.hvac_mode = "heat_cool"
        _z.preset_mode = "home"
    _seed_zone_all_live_and_empty(coord, "zone_1")
    zone = coord.zone_manager.zones["zone_1"]
    zone.room_conditions[0].occupied = True  # lighting-occupied hallway
    for rc in zone.room_conditions:
        rc.hvac_occupied = False
    assert zone.any_room_occupied and not zone.any_room_hvac_occupied
    zone.vacancy_sweep_enabled = True
    zone.vacancy_sweep_done = False
    zone.last_occupied_time = pinned - timedelta(minutes=coord._vacancy_grace + 5)
    calls = _recording_sweep(coord, ["light.hallway"])
    hass.services.calls.clear()
    await _drive_apply_presets(coord)
    away = [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_preset_mode"
        and c[2].get("preset_mode") == "away"
    ]
    assert away, "positive control: the HVAC-empty zone still retreats"
    assert calls == []
    assert zone.vacancy_sweep_done is False


# ---------------------------------------------------------------------------
# Manual devices (CONF_MANUAL_DEVICES + legacy CONF_MANUAL_SWITCHES)
# ---------------------------------------------------------------------------

def _with_manual(coord, room, key, ids, *, on=True):
    entry = coord.hass.data[DOMAIN][f"entry_{room}"].config_entry
    entry.data[key] = ids
    states_get = coord.hass.states.get
    extra = {}
    for eid in (ids if isinstance(ids, list) else [ids]):
        st = MagicMock()
        st.state = "on" if on else "off"
        extra[eid] = st
    coord.hass.states.get = lambda e: extra.get(e) or states_get(e)
    return coord.hass.data[DOMAIN][f"entry_{room}"]


def test_manual_device_swept_and_recorded():
    coord, log, tasks, alog = _coord()
    _with_manual(coord, "FreeRoom", "manual_devices", ["switch.relay_a"])
    _run(coord._maybe_run_vacancy_sweep(_Zone(["FreeRoom"])))
    _drain(tasks)
    assert "switch.relay_a" in _offs(log)
    assert "switch.relay_a" in alog.rows[0]["details"]["turned_off"]
    # off only, never on
    assert not [d for (_dm, svc, d) in log if svc == "turn_on"]


def test_legacy_manual_switches_key_read():
    coord, log, _, _ = _coord()
    _with_manual(coord, "FreeRoom", "manual_switches", "switch.legacy_b")
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert "switch.legacy_b" in _offs(log)


def test_manual_device_off_state_not_called():
    coord, log, _, _ = _coord()
    _with_manual(coord, "FreeRoom", "manual_devices", ["switch.relay_a"], on=False)
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert "switch.relay_a" not in _offs(log)


def test_paused_room_manual_device_not_swept():
    coord, log, _, _ = _coord()
    rc = _with_manual(coord, "FreeRoom", "manual_devices", ["switch.relay_a"])
    rc._is_automation_enabled = lambda: False
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert _offs(log) == []


def test_manual_device_registry_guard_applied():
    coord, log, _, _ = _coord()
    rc = _with_manual(
        coord, "FreeRoom", "manual_devices", ["switch.relay_a", "switch.fw_update"],
    )
    rc.automation = SimpleNamespace(
        _actuatable_ids=lambda ids: [i for i in ids if i != "switch.fw_update"],
    )
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    offs = _offs(log)
    assert "switch.relay_a" in offs and "switch.fw_update" not in offs


def test_manual_device_leave_on_exempt():
    coord, log, _, _ = _coord()
    rc = _with_manual(coord, "FreeRoom", "manual_devices", ["switch.relay_a"])
    rc.config_entry.data["lights_leave_on_when_empty"] = ["switch.relay_a"]
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert "switch.relay_a" not in _offs(log)


# ---------------------------------------------------------------------------
# Review fix-up: fans never via the manual-device loop (B-H1 / A-LOW2);
# full light list compare (A-LOW1); effective status attribute (A-LOW3)
# ---------------------------------------------------------------------------

_CEIL = "fan.master_ceiling_fan_2"


def _fan_in_both(coord, room="FreeRoom"):
    rc = _with_manual(coord, room, "manual_devices", [_CEIL])
    rc.config_entry.data["fans"] = [_CEIL]
    return rc


def test_fan_in_manual_and_fans_kept_under_pre_arrival():
    coord, log, _, _ = _coord()
    _fan_in_both(coord)
    coord._pre_arrival_zones = {"zone_1"}
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"], zone_id="zone_1")))
    assert _CEIL not in _offs(log)


def test_fan_in_manual_and_fans_kept_under_fan_mode_room():
    coord, log, _, _ = _coord()
    rc = _fan_in_both(coord)
    rc.config_entry.options["room_fan_mode"] = "room"
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert _CEIL not in _offs(log)


def test_switch_listed_as_fan_kept_under_pre_arrival():
    coord, log, _, _ = _coord()
    rc = _with_manual(coord, "FreeRoom", "manual_devices", ["switch.fan_relay"])
    rc.config_entry.data["fans"] = ["switch.fan_relay"]
    coord._pre_arrival_zones = {"zone_1"}
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"], zone_id="zone_1")))
    assert "switch.fan_relay" not in _offs(log)


def test_fan_only_in_manual_devices_not_swept_by_manual_loop():
    coord, log, _, _ = _coord()
    _with_manual(coord, "FreeRoom", "manual_devices", ["fan.loose_fan"])
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert "fan.loose_fan" not in _offs(log)


def test_held_light_also_in_manual_devices_not_swept():
    coord, log, _, _ = _coord()
    rc = _with_manual(coord, "FreeRoom", "manual_devices", ["light.freeroom"])
    rc.automation = SimpleNamespace(
        light_hold_allowed=lambda ids, _a: [i for i in ids if i != "light.freeroom"],
    )
    _run(coord._execute_vacancy_sweep(_Zone(["FreeRoom"])))
    assert "light.freeroom" not in _offs(log)


def test_zone_status_attr_is_master_and_zone():
    from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (  # noqa: E501
        ZoneManager, ZoneState,
    )
    zm = ZoneManager(MagicMock())
    zm._zones["zone_1"] = ZoneState(
        zone_id="zone_1", zone_name="Z", climate_entity="climate.z", rooms=[],
    )
    assert zm.get_zone_status_attrs("zone_1")["vacancy_sweep_enabled"] is True
    zm.vacancy_sweep_master_enabled = False
    assert zm.get_zone_status_attrs("zone_1")["vacancy_sweep_enabled"] is False
    zm.vacancy_sweep_master_enabled = True
    zm._zones["zone_1"].vacancy_sweep_enabled = False
    assert zm.get_zone_status_attrs("zone_1")["vacancy_sweep_enabled"] is False


def test_coordinator_setter_mirrors_master_to_zone_manager():
    coord, _, _, _ = _coord()
    coord._zone_manager = SimpleNamespace(vacancy_sweep_master_enabled=True)
    coord.vacancy_sweep_master_enabled = False
    assert coord._zone_manager.vacancy_sweep_master_enabled is False
