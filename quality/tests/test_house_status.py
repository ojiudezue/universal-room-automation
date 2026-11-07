"""house_status.py — read-only house answers (NM-INBOUND-HOUSE-QUERIES-1 D1).

Behavioural tests over a mocked hass + fake coordinators. Each test names the
production line it protects. Expected values are hand-derived from the
fixture inputs, never from re-running the code.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import os
import sys
import types
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

# NOTE: deliberately does NOT import test_notification_manager / the NM diag
# harness. That bootstrap replaces sys.modules package entries at import time;
# importing it from a file that collects early ("test_h...") moved that
# surgery ahead of every file between here and test_imsg_audit_fix_1 and broke
# test_nm_life_safety_slot_precedence + test_restart_safety_doctrine_1
# in-suite (order-dependent). Normal package import only.
from custom_components.universal_room_automation.const import DOMAIN

hs = importlib.import_module("custom_components.universal_room_automation.house_status")

HS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "house_status.py",
)


def _now():
    return hs.dt_util.utcnow()


class _St:
    def __init__(self, state, attrs=None, age_s=0.0):
        self.state = state
        self.attributes = attrs or {}
        self.last_updated = _now() - timedelta(seconds=age_s)


def _hass(states=None, coords=None, extra=None):
    hass = MagicMock()
    states = states or {}
    hass.states.get = lambda eid: states.get(eid)
    mgr = None
    if coords is not None:
        mgr = MagicMock()
        mgr.coordinators = coords
    data = {"coordinator_manager": mgr} if mgr is not None else {}
    data.update(extra or {})
    hass.data = {DOMAIN: data}
    return hass


def _vals(result):
    return {f.label: f.value for f in result.fields}


# --- doors ------------------------------------------------------------------

def test_doors_reads_security_lists():
    """Protects house_status.doors: ids = sc._lock_entities (SC config list)."""
    sc = types.SimpleNamespace(_lock_entities=["lock.front", "lock.back"], _garage_entities=[])
    states = {
        "lock.front": _St("locked", {"friendly_name": "Front"}),
        "lock.back": _St("unlocked", {"friendly_name": "Back"}),
        "lock.not_in_list": _St("unlocked", {"friendly_name": "Other"}),
    }
    r = hs.doors(_hass(states, {"security": sc}))
    assert _vals(r) == {"Front": "locked", "Back": "unlocked"}
    assert r.problems == 1  # unlocked is a problem; locked is not


def test_doors_missing_security_is_unknown():
    r = hs.doors(_hass({}, {}))
    assert [f.value for f in r.fields] == ["unknown"]


# --- garage -----------------------------------------------------------------

def test_garage_reads_lockouts_directly_not_sc_list():
    """Protects garage(): lockouts come from HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES,
    covers from sc._garage_entities; the SC lock list is not consulted."""
    lo1, lo2 = hs.HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES
    sc = types.SimpleNamespace(_lock_entities=[lo1], _garage_entities=["cover.g"])
    states = {
        "cover.g": _St("open", {"friendly_name": "Garage"}),
        lo1: _St("locked", {"friendly_name": "LO1"}),
        lo2: _St("unlocked", {"friendly_name": "LO2"}),
    }
    r = hs.garage(_hass(states, {"security": sc}))
    v = _vals(r)
    assert v["Garage"] == "open"
    assert v["remotes locked out: LO1"] == "on"
    assert v["remotes locked out: LO2"] == "off"
    assert r.problems == 1  # only the open cover


def test_garage_lockout_not_found():
    sc = types.SimpleNamespace(_lock_entities=[], _garage_entities=[])
    r = hs.garage(_hass({}, {"security": sc}))
    assert [f.value for f in r.fields if f.label == "lockout"] == ["not found", "not found"]


# --- who ----------------------------------------------------------------------

class _HouseState:
    value = "home_day"


def test_house_state_renders_enum_value():
    """Protects who(): house = mgr.house_state.value (manager.py:325)."""
    mgr_coords = {}
    hass = _hass({}, mgr_coords)
    hass.data[DOMAIN]["coordinator_manager"].house_state = _HouseState()
    r = hs.who(hass)
    assert _vals(r)["house"] == "home_day"


def test_house_state_unknown_when_manager_missing():
    """Protects who(): no manager -> 'unknown', never presence's fabricated 'away'."""
    hass = _hass({}, None)
    r = hs.who(hass)
    assert _vals(r)["house"] == "unknown"
    assert _vals(r)["people"] == "unknown"


def test_person_location_called_by_name():
    """Protects who(): get_person_location(person NAME) + person_state_for_trust."""
    pc = MagicMock()
    pc.data = {"Oji Udezue": {"location": "study_b"}}
    pc.get_person_location = MagicMock(return_value="study_b")
    pc._find_person_entity = MagicMock(return_value="person.oji_udezue")
    pc.effective_person_state = MagicMock(return_value="home")
    pres = types.SimpleNamespace(census_count=3)
    hass = _hass({"person.oji_udezue": _St("home")}, {"presence": pres}, extra={"person_coordinator": pc})
    hass.data[DOMAIN]["coordinator_manager"].house_state = _HouseState()
    r = hs.who(hass)
    pc.get_person_location.assert_called_once_with("Oji Udezue")
    assert _vals(r)["Oji Udezue"] == "home (study_b)"
    assert _vals(r)["people"] == "~3 (estimate)"


# --- hvac ---------------------------------------------------------------------

def _zone(**kw):
    base = dict(zone_name="Zone 1", current_temperature=74.0, target_temp_low=68.0,
                target_temp_high=76.0, preset_mode="home", hvac_action="cooling",
                ac_load_sensor="sensor.ac1")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_hvac_running_from_load_sensor_not_hvac_action():
    """Protects hvac(): running derives from the arrester's kW read, not hvac_action."""
    z_idle = _zone(hvac_action="cooling")  # hvac_action says cooling (lies, HVAC §9.9)
    z_run = _zone(zone_name="Zone 2", hvac_action="idle", ac_load_sensor="sensor.ac2")
    arrester = MagicMock()
    arrester._read_kwh_rate = lambda zone, now, warn=True: {"sensor.ac1": 0.05, "sensor.ac2": 2.0}[zone.ac_load_sensor]
    hv = MagicMock()
    hv.zone_manager.zones = {"zone_1": z_idle, "zone_2": z_run}
    hv._override_arrester = arrester
    r = hs.hvac(_hass({}, {"hvac": hv}))
    v = _vals(r)
    assert v["Zone 1"].endswith("idle")
    assert v["Zone 2"].endswith("running")
    assert "thermostat reports home" in v["Zone 1"]
    assert "set 68-76" in v["Zone 1"]


def test_hvac_threshold_boundary_literal():
    """0.3 kW is the default threshold: 0.31 runs, 0.30 does not (hardcoded literals)."""
    hv = MagicMock()
    hv.zone_manager.zones = {"a": _zone(zone_name="A", ac_load_sensor="s.a"), "b": _zone(zone_name="B", ac_load_sensor="s.b")}
    hv._override_arrester._read_kwh_rate = lambda zone, now, warn=True: {"s.a": 0.31, "s.b": 0.30}[zone.ac_load_sensor]
    v = _vals(hs.hvac(_hass({}, {"hvac": hv})))
    assert v["A"].endswith("running") and v["B"].endswith("idle")


def test_hvac_no_load_sensor_not_measured():
    hv = MagicMock()
    hv.zone_manager.zones = {"a": _zone(zone_name="A", ac_load_sensor="")}
    v = _vals(hs.hvac(_hass({}, {"hvac": hv})))
    assert v["A"].endswith("running: not measured")


# --- energy -------------------------------------------------------------------

class _BS:
    def __init__(self, soc=42.0, solar=15382.0, net=-448.0, raw_solar=99999.0, raw_net=-0.448):
        self.battery_soc = soc
        self.solar_production_w = solar
        self.net_power_w = net
        # raw siblings the module must NOT read
        self.solar_production = raw_solar
        self.net_power = raw_net

    def _get_entity(self, key):
        return {"net_power": "sensor.net"}.get(key)


def _energy_hass(bs, states=None):
    ec = types.SimpleNamespace(battery_strategy=bs)
    return _hass(states or {}, {"energy": ec})


def test_energy_solar_uses_staleness_gated_getter():
    """Protects energy(): solar = solar_production_w (gated), not raw solar_production."""
    v = _vals(hs.energy(_energy_hass(_BS(solar=15382.0))))
    assert v["solar"] == "15.4"
    v2 = _vals(hs.energy(_energy_hass(_BS(solar=None))))  # stale CT -> None
    assert v2["solar"] == "unknown"
    assert _vals(hs.energy(_energy_hass(_BS()))) ["battery"] == "42"


def test_energy_grid_uses_net_power_w_with_age():
    """Protects energy(): grid = net_power_w (W-normalized) + source age render."""
    bs = _BS(net=-448.0, raw_net=-0.448)
    r = hs.energy(_energy_hass(bs, {"sensor.net": _St("-0.448", age_s=600)}))
    grid = [f for f in r.fields if f.label == "grid"][0]
    assert grid.value == "exporting 0.4"
    assert grid.age_s is not None and grid.age_s >= 600
    assert "(10 min old)" in hs.render(r, 900)


def test_energy_missing_coordinator_unknown():
    r = hs.energy(_hass({}, {}))
    assert [f.value for f in r.fields] == ["unknown"]


# --- alerts -------------------------------------------------------------------

def test_alerts_unacked_age_bounded():
    """Protects alerts(): rows filtered by nm._recovery_row_is_stale (24 h bound)."""
    from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
        AlertState, NotificationManager,
    )
    now = hs.dt_util.utcnow()
    fresh = {"timestamp": (now - timedelta(hours=2)).isoformat(), "hazard_type": "smoke"}
    stale = {"timestamp": (now - timedelta(hours=30)).isoformat(), "hazard_type": "water"}
    db = MagicMock()
    db.get_active_criticals = AsyncMock(return_value=[fresh, stale])
    nm = types.SimpleNamespace(
        alert_state=AlertState.IDLE, anomaly_status="nominal",
        _recovery_row_is_stale=NotificationManager._recovery_row_is_stale,
    )
    det = MagicMock()
    det.get_sensor_state = MagicMock(return_value="warning")
    hass = _hass({}, {"hvac": types.SimpleNamespace(anomaly_detector=det)}, extra={"database": db})
    loop = asyncio.new_event_loop()
    try:
        r = loop.run_until_complete(hs.alerts(hass, nm))
    finally:
        loop.close()
    v = _vals(r)
    assert v["unacked criticals"] == "1"
    assert "  smoke" in v and "  water" not in v
    assert v["anomaly hvac"] == "warning"
    assert v["alert state"] == "idle"


# --- health -------------------------------------------------------------------

def test_health_resolves_by_unique_id(monkeypatch):
    """Protects health(): entity id resolved from f'{entry_id}_unavailable_entities'
    through the entity registry, never from a slug."""
    calls = []

    class _Reg:
        def async_get_entity_id(self, domain, platform, uid):
            calls.append((domain, platform, uid))
            return {"E1_unavailable_entities": "sensor.weird_slug_x"}.get(uid)

    fake_er = types.ModuleType("homeassistant.helpers.entity_registry")
    fake_er.async_get = lambda hass: _Reg()
    fake_ir = types.ModuleType("homeassistant.helpers.issue_registry")
    fake_ir.async_get = lambda hass: types.SimpleNamespace(issues={(DOMAIN, "x"): 1, ("other", "y"): 1})
    import homeassistant.helpers as helpers_pkg
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", fake_er)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", fake_ir)
    monkeypatch.setattr(helpers_pkg, "entity_registry", fake_er, raising=False)
    monkeypatch.setattr(helpers_pkg, "issue_registry", fake_ir, raising=False)
    e1 = types.SimpleNamespace(entry_id="E1", title="Kitchen", data={"entry_type": "room"})
    e2 = types.SimpleNamespace(entry_id="E2", title="Den", data={"entry_type": "room"})
    zm = types.SimpleNamespace(entry_id="Z", title="ZM", data={"entry_type": "zone_manager"})
    states = {
        "sensor.weird_slug_x": _St("2", {"actuator_count": 1}),
        "sensor.kitchen_unavailable_entities": _St("9", {"actuator_count": 9}),  # slug decoy
    }
    hass = _hass(states, {})
    hass.config_entries.async_entries = lambda domain: [e1, e2, zm]
    v = _vals(hs.health(hass))
    assert v["Kitchen"] == "2 unavailable (1 actuators)"
    assert v["rooms reporting"] == "1/2"
    assert v["repairs"] == "1"
    assert ("sensor", DOMAIN, "E1_unavailable_entities") in calls


# --- read-only lint + render --------------------------------------------------

def test_module_is_read_only_ast_lint():
    """Shallow syntax lint (I2's real guard is the D3 recorder test)."""
    src = open(HS_PATH, encoding="utf-8").read()
    tree = ast.parse(src)
    banned_attrs = {"async_call", "async_fire", "async_create_task", "execute", "services"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned_attrs, node.attr
            assert not node.attr.startswith(("log_", "save_")), node.attr
        if isinstance(node, ast.Name):
            assert node.id not in ("async_dispatcher_send",), node.id
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                assert not isinstance(t, ast.Attribute), ast.dump(t)


def test_render_cap_and_problem_first():
    fields = [hs.Field(f"ok{i}", "fine") for i in range(200)] + [hs.Field("bad", "unlocked", problem=True)]
    r = hs.StatusResult("doors", _now(), fields, problems=1)
    out = hs.render(r, 120)
    assert len(out) <= 120
    assert out.split("\n")[1] == "! bad: unlocked"
    assert out.endswith("…(more: doors)")
    short = hs.render(hs.StatusResult("who", _now(), [], 0), 900)
    assert "\n" in short
