"""v4.5.13.1 — HVAC zone dedup across per-zone platforms.

Bug Class #36 prevention: per-zone entity registration must consult the
same thermostat-keyed dedup logic that ZoneManager.async_discover_zones
uses. v4.5.12 shipped a regression where sensor.py created parallel sets
of D7 sensors for home zones sharing a thermostat (Entertainment +
Master Suite both pointing at climate.thermostat_bryant_wifi_studyb_zone_1).

The Layer 3 fix is a shared helper `iter_canonical_hvac_zones` in
`hvac_zones.py` that all per-zone platform setup paths must call.

Tests below:
  - Behavior: helper returns correct dedup + merged names for synthetic
    install resembling the user's canonical setup
  - AST: every per-zone platform setup path uses `iter_canonical_hvac_zones`
    and does NOT loop over Zone Manager `zones` dict independently
  - Source-grep: no orphaned `seen: set[str]` patterns indicating a
    platform rolled its own (incomplete) dedup
"""

import ast
import sys
import types
from pathlib import Path

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def button_src() -> str:
    with open("custom_components/universal_room_automation/button.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def number_src() -> str:
    with open("custom_components/universal_room_automation/number.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_zones_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_zones.py"
    ) as f:
        return f.read()


# ===========================================================================
# Behavior tests for iter_canonical_hvac_zones
# ===========================================================================


def _load_helper():
    """Load `iter_canonical_hvac_zones` with HA + const dependencies stubbed."""
    if "ura_hvac_zones_under_test" in sys.modules:
        mod = sys.modules["ura_hvac_zones_under_test"]
        return mod.iter_canonical_hvac_zones, mod._zone_id_from_thermostat_pure

    # Stub homeassistant surface — additive so other tests' loaders can
    # cooperate. Each branch checks the specific submodule it sets up.
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
        sys.modules["homeassistant"].__path__ = []
    if "homeassistant.core" not in sys.modules:
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = type("HomeAssistant", (), {})
        ha_core.callback = lambda f: f
        sys.modules["homeassistant.core"] = ha_core
    if "homeassistant.util" not in sys.modules:
        ha_util = types.ModuleType("homeassistant.util")
        ha_util.__path__ = []
        sys.modules["homeassistant.util"] = ha_util
    if "homeassistant.util.dt" not in sys.modules:
        ha_util_dt = types.ModuleType("homeassistant.util.dt")
        from datetime import datetime, timezone
        ha_util_dt.utcnow = lambda: datetime.now(timezone.utc)
        sys.modules["homeassistant.util.dt"] = ha_util_dt
    if "homeassistant.helpers" not in sys.modules:
        ha_helpers = types.ModuleType("homeassistant.helpers")
        ha_helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = ha_helpers
    if "homeassistant.helpers.event" not in sys.modules:
        ha_helpers_event = types.ModuleType("homeassistant.helpers.event")
        ha_helpers_event.async_call_later = lambda *a, **kw: None
        sys.modules["homeassistant.helpers.event"] = ha_helpers_event

    # Stub the package's `const` and `hvac_const` siblings
    pkg = types.ModuleType("ura_zd_pkg"); pkg.__path__ = []
    const = types.ModuleType("ura_zd_pkg.const")
    const.DOMAIN = "universal_room_automation"
    const.CONF_ENTRY_TYPE = "entry_type"
    const.CONF_ROOM_NAME = "room_name"
    const.CONF_ZONE_ROOMS = "zone_rooms"
    const.CONF_ZONE_THERMOSTAT = "zone_thermostat"
    const.ENTRY_TYPE_ROOM = "room"
    const.ENTRY_TYPE_ZONE = "zone"
    const.ENTRY_TYPE_ZONE_MANAGER = "zone_manager"

    coord_pkg = types.ModuleType("ura_zd_pkg.domain_coordinators")
    coord_pkg.__path__ = []
    hvac_const = types.ModuleType("ura_zd_pkg.domain_coordinators.hvac_const")
    hvac_const.CONF_HVAC_AC_LOAD_SENSOR = "ac_load_sensor"
    hvac_const.CONF_HVAC_AC_RAMP_ZONE_ENABLED = "ac_ramp_zone_enabled"
    hvac_const.DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED = True
    hvac_const.DUTY_CYCLE_WINDOW_SECONDS = 3600
    hvac_const.DEFAULT_VACANCY_GRACE_MINUTES = 30
    hvac_const.CONF_ZONE_VACANCY_SWEEP_ENABLED = "vacancy_sweep_enabled"
    hvac_const.CONF_ZONE_PERSONS = "zone_persons"
    hvac_const.CONF_ZONE_CAMERAS = "zone_cameras"

    sys.modules["ura_zd_pkg"] = pkg
    sys.modules["ura_zd_pkg.const"] = const
    sys.modules["ura_zd_pkg.domain_coordinators"] = coord_pkg
    sys.modules["ura_zd_pkg.domain_coordinators.hvac_const"] = hvac_const

    import importlib.util
    root = Path(__file__).resolve().parents[2]
    src = root / "custom_components" / "universal_room_automation" / \
        "domain_coordinators" / "hvac_zones.py"
    spec = importlib.util.spec_from_file_location(
        "ura_zd_pkg.domain_coordinators.hvac_zones", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ura_zd_pkg.domain_coordinators.hvac_zones"] = mod
    mod.__package__ = "ura_zd_pkg.domain_coordinators"
    spec.loader.exec_module(mod)
    sys.modules["ura_hvac_zones_under_test"] = mod
    return mod.iter_canonical_hvac_zones, mod._zone_id_from_thermostat_pure


class _StubEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}


class _StubConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return self._entries


class _StubHass:
    def __init__(self, entries):
        self.config_entries = _StubConfigEntries(entries)


def _zm_entry(zones_dict):
    return _StubEntry(
        data={"entry_type": "zone_manager"},
        options={"zones": zones_dict},
    )


def test_helper_dedups_two_zones_sharing_one_thermostat():
    """Canonical user install case: Entertainment + Master Suite share
    climate.thermostat_bryant_wifi_studyb_zone_1. Helper must return ONE
    zone with merged name + thermostat.
    """
    iter_canonical, _ = _load_helper()
    hass = _StubHass([
        _zm_entry({
            "Entertainment": {
                "zone_thermostat": "climate.thermostat_bryant_wifi_studyb_zone_1",
                "ac_load_sensor": "sensor.span_panel_ac1_power",
            },
            "Master Suite": {
                "zone_thermostat": "climate.thermostat_bryant_wifi_studyb_zone_1",
                "ac_load_sensor": "sensor.span_panel_ac1_power",
            },
        }),
    ])
    zones = iter_canonical(hass)
    assert len(zones) == 1, (
        f"Expected 1 deduplicated zone, got {len(zones)}: "
        f"{[z['zone_name'] for z in zones]}"
    )
    z = zones[0]
    assert z["zone_name"] == "Entertainment + Master Suite"
    assert z["climate_entity"] == \
        "climate.thermostat_bryant_wifi_studyb_zone_1"
    assert z["zone_id"] == "zone_1"  # matches `zone_1` suffix in thermostat
    assert z["ac_load_sensor"] == "sensor.span_panel_ac1_power"


def test_helper_user_canonical_3_zone_install():
    """The user's actual install: 4 home zones, 3 physical HVAC zones.
    Verify the merged result and zone_id assignment matches ZoneManager
    runtime semantics.
    """
    iter_canonical, _ = _load_helper()
    hass = _StubHass([
        _zm_entry({
            "Back Hallway": {
                "zone_thermostat": "climate.back_hallway_zone_3",
                "ac_load_sensor": "sensor.span_panel_ac_3_power",
            },
            "Entertainment": {
                "zone_thermostat": "climate.thermostat_bryant_wifi_studyb_zone_1",
                "ac_load_sensor": "sensor.span_panel_ac1_power",
            },
            "Master Suite": {
                "zone_thermostat": "climate.thermostat_bryant_wifi_studyb_zone_1",
                "ac_load_sensor": "sensor.span_panel_ac1_power",
            },
            "Upstairs": {
                "zone_thermostat": "climate.up_hallway_zone_2",
                "ac_load_sensor": "sensor.span_panel_ac_2_power",
            },
        }),
    ])
    zones = iter_canonical(hass)
    assert len(zones) == 3, (
        f"Expected 3 canonical zones, got {len(zones)}: "
        f"{[(z['zone_id'], z['zone_name']) for z in zones]}"
    )
    by_id = {z["zone_id"]: z for z in zones}
    assert "zone_1" in by_id
    assert "zone_2" in by_id
    assert "zone_3" in by_id

    # Verify each zone_id maps to the expected thermostat (matches
    # ZoneManager._zone_id_from_thermostat behavior)
    assert by_id["zone_1"]["climate_entity"] == \
        "climate.thermostat_bryant_wifi_studyb_zone_1"
    assert by_id["zone_1"]["zone_name"] == "Entertainment + Master Suite"
    assert by_id["zone_2"]["climate_entity"] == "climate.up_hallway_zone_2"
    assert by_id["zone_2"]["zone_name"] == "Upstairs"
    assert by_id["zone_3"]["climate_entity"] == "climate.back_hallway_zone_3"
    assert by_id["zone_3"]["zone_name"] == "Back Hallway"


def test_helper_returns_empty_when_no_zone_manager_entry():
    iter_canonical, _ = _load_helper()
    hass = _StubHass([])
    assert iter_canonical(hass) == []


def test_helper_skips_zones_without_thermostat():
    iter_canonical, _ = _load_helper()
    hass = _StubHass([
        _zm_entry({
            "Configured": {
                "zone_thermostat": "climate.foo_zone_1",
            },
            "Unconfigured": {
                "zone_thermostat": None,
            },
        }),
    ])
    zones = iter_canonical(hass)
    assert len(zones) == 1
    assert zones[0]["zone_name"] == "Configured"


def test_helper_ac_load_sensor_first_non_empty_wins():
    """When two home zones share a thermostat, the merged zone keeps the
    first non-empty ac_load_sensor and OR's the ramp_zone_enabled flag.
    Matches ZoneManager merge semantics at hvac_zones.py:299-307.
    """
    iter_canonical, _ = _load_helper()
    hass = _StubHass([
        _zm_entry({
            "First": {
                "zone_thermostat": "climate.shared_zone_1",
                "ac_load_sensor": "",  # empty — falls through
                "ac_ramp_zone_enabled": False,
            },
            "Second": {
                "zone_thermostat": "climate.shared_zone_1",
                "ac_load_sensor": "sensor.real_kw",  # wins
                "ac_ramp_zone_enabled": True,
            },
        }),
    ])
    zones = iter_canonical(hass)
    assert len(zones) == 1
    assert zones[0]["ac_load_sensor"] == "sensor.real_kw"
    assert zones[0]["ramp_zone_enabled"] is True


def test_zone_id_from_thermostat_pure_matches_zone_suffix():
    _, pure = _load_helper()
    assert pure("climate.back_hallway_zone_3", 0, set()) == "zone_3"
    assert pure("climate.up_hallway_zone_2", 0, set()) == "zone_2"
    assert pure("climate.thermostat_zone_1", 0, set()) == "zone_1"


def test_zone_id_from_thermostat_pure_auto_numbers_when_no_suffix():
    _, pure = _load_helper()
    assigned = set()
    assert pure("climate.bedroom_thermostat", 0, assigned) == "zone_0"
    assigned.add("zone_0")
    assert pure("climate.kitchen_thermostat", 1, assigned) == "zone_1"


def test_zone_id_from_thermostat_pure_handles_collision():
    """When the suffix-matched id collides with an already-assigned one,
    falls through to auto-numbering."""
    _, pure = _load_helper()
    assigned = {"zone_1"}
    # Two thermostats with `zone_1` suffix — second one collides
    second = pure("climate.other_zone_1", 0, assigned)
    assert second == "zone_0"


# ===========================================================================
# AST tests — verify all per-zone platform setup uses the helper
# ===========================================================================


def _count_zones_dict_loops(src: str) -> int:
    """Count the Zone-Manager-config zones iteration pattern specifically.

    Looks for `<var>.get("zones", {})` where var is named like
    `merged`/`zm`/`entry_data`/`zone_manager_data` — the typical alias
    for the Zone Manager entry's data+options union. This avoids false
    positives on other "zones"-keyed dicts (e.g., arrester detail dump).
    """
    tree = ast.parse(src)
    zm_var_hints = {
        "merged", "zm", "zm_data", "entry_data",
        "zone_manager_data", "zm_entry", "zm_merged",
    }
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        if not (
            len(node.args) >= 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "zones"
        ):
            continue
        # Inspect the receiver — must look like a ZM-data var
        receiver = func.value
        if isinstance(receiver, ast.Name) and receiver.id in zm_var_hints:
            count += 1
    return count


def test_sensor_py_does_not_iterate_zones_dict_directly(sensor_src: str):
    """sensor.py's per-zone setup must route through iter_canonical_hvac_zones.

    The v4.5.12 bug was a direct loop over `merged.get("zones", {})`
    without dedup. v4.5.13.1 replaces it with the helper.
    """
    assert "iter_canonical_hvac_zones" in sensor_src, (
        "sensor.py must import and use iter_canonical_hvac_zones for "
        "per-zone setup (v4.5.13.1 fix)."
    )
    assert _count_zones_dict_loops(sensor_src) == 0, (
        "sensor.py still iterates `merged.get('zones', {})` directly — "
        "this bypasses dedup. Route through iter_canonical_hvac_zones."
    )


def test_button_py_uses_canonical_helper(button_src: str):
    assert "iter_canonical_hvac_zones" in button_src, (
        "button.py:_discover_ac_zones must delegate to "
        "iter_canonical_hvac_zones (v4.5.13.1 fix)."
    )
    assert _count_zones_dict_loops(button_src) == 0


def test_number_py_uses_canonical_helper(number_src: str):
    assert "iter_canonical_hvac_zones" in number_src, (
        "number.py:_discover_ac_zones must delegate to "
        "iter_canonical_hvac_zones (v4.5.13.1 fix)."
    )
    assert _count_zones_dict_loops(number_src) == 0


def test_helper_defined_in_hvac_zones(hvac_zones_src: str):
    """The canonical helper must live where ZoneManager lives so the
    dedup logic stays in lockstep with async_discover_zones.
    """
    assert "def iter_canonical_hvac_zones" in hvac_zones_src
    assert "def _zone_id_from_thermostat_pure" in hvac_zones_src
    # Helper docstring should reference the bug class for future
    # readers to find the prevention narrative
    assert "Bug Class #36" in hvac_zones_src, (
        "iter_canonical_hvac_zones docstring should cite Bug Class #36 "
        "to keep the prevention narrative discoverable."
    )


def test_no_kwarg_unpack_of_zone_spec_in_platforms(
    sensor_src: str, button_src: str, number_src: str,
):
    """v4.5.13.1.1 regression: `**zone_spec` unpacking into a factory or
    constructor breaks when the helper adds new keys. Helper returns 5
    keys (zone_id, zone_name, climate_entity, ac_load_sensor,
    ramp_zone_enabled); old callers expecting 3 will raise TypeError on
    extra keyword arguments.

    Routes: callers must either (a) pass the dict positionally, (b)
    select specific keys, or (c) accept **kwargs and ignore extras.
    Direct `**zone_spec` to a fixed-signature function is the bug shape.
    """
    for name, src in [
        ("sensor.py", sensor_src),
        ("button.py", button_src),
        ("number.py", number_src),
    ]:
        # AST: look for `func(**zone_spec)` pattern
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                # keyword=None marks **kwargs spread
                if kw.arg is None and isinstance(kw.value, ast.Name) and \
                        kw.value.id == "zone_spec":
                    pytest.fail(
                        f"{name} has `**zone_spec` unpack pattern. "
                        "Helper returns 5 keys; if the callee's signature "
                        "doesn't accept all of them, this raises TypeError "
                        "at runtime. v4.5.13.1.1 regression."
                    )


def test_no_orphan_seen_thermostat_dedup_in_platforms(
    sensor_src: str, button_src: str, number_src: str,
):
    """A platform rolling its own `seen: set[str]` dedup indicates the
    helper isn't being used. Catches future regressions.
    """
    for name, src in [
        ("sensor.py", sensor_src),
        ("button.py", button_src),
        ("number.py", number_src),
    ]:
        # Heuristic: look for `seen.add(thermostat)` which is the
        # in-place dedup pattern the helper supersedes
        assert "seen.add(thermostat)" not in src, (
            f"{name} still has an in-place `seen.add(thermostat)` "
            "dedup pattern. Use iter_canonical_hvac_zones instead "
            "(Bug Class #36 prevention)."
        )


# ===========================================================================
# Lockstep equivalence test (Review-1 LOW finding)
# ===========================================================================
# Guards against silent drift between iter_canonical_hvac_zones (used at
# platform setup) and ZoneManager.async_discover_zones (used at runtime).
# Both must produce identical (zone_id, climate_entity, merged_name) for
# the same fixture. If a future cycle modifies one without the other,
# this test fails.


def test_lockstep_helper_matches_zone_manager_for_canonical_install():
    """iter_canonical_hvac_zones output must match ZoneManager runtime
    semantics: same zone_ids, same merged names, same climate_entities.

    Constructs the user's canonical install (4 home zones, 2 sharing one
    thermostat) and runs both code paths. Asserts the
    (zone_id → (climate_entity, zone_name)) mapping agrees.
    """
    iter_canonical, _ = _load_helper()
    mod = sys.modules["ura_hvac_zones_under_test"]
    ZoneManager = mod.ZoneManager

    canonical_zones = {
        "Back Hallway": {
            "zone_thermostat": "climate.back_hallway_zone_3",
            "ac_load_sensor": "sensor.span_panel_ac_3_power",
        },
        "Entertainment": {
            "zone_thermostat": "climate.thermostat_bryant_wifi_studyb_zone_1",
            "ac_load_sensor": "sensor.span_panel_ac1_power",
        },
        "Master Suite": {
            "zone_thermostat": "climate.thermostat_bryant_wifi_studyb_zone_1",
            "ac_load_sensor": "sensor.span_panel_ac1_power",
        },
        "Upstairs": {
            "zone_thermostat": "climate.up_hallway_zone_2",
            "ac_load_sensor": "sensor.span_panel_ac_2_power",
        },
    }
    hass = _StubHass([_zm_entry(canonical_zones)])

    helper_out = iter_canonical(hass)
    helper_map = {
        z["zone_id"]: (z["climate_entity"], z["zone_name"]) for z in helper_out
    }

    zm = ZoneManager(hass)
    import asyncio
    asyncio.get_event_loop().run_until_complete(zm.async_discover_zones())
    zm_map = {
        zid: (zs.climate_entity, zs.zone_name)
        for zid, zs in zm.zones.items()
    }

    assert helper_map == zm_map, (
        f"Lockstep drift detected.\n"
        f"  helper: {helper_map}\n"
        f"  ZM   : {zm_map}\n"
        f"Both code paths must agree on (zone_id → climate_entity, "
        f"zone_name). If you modified one, modify the other "
        f"(Bug Class #36)."
    )


def test_lockstep_helper_matches_zone_manager_for_no_dedup_install():
    """4 unique thermostats — no dedup needed. Both paths should produce
    4 entries with matching zone_ids.
    """
    iter_canonical, _ = _load_helper()
    mod = sys.modules["ura_hvac_zones_under_test"]
    ZoneManager = mod.ZoneManager

    zones = {
        "A": {"zone_thermostat": "climate.foo_zone_1"},
        "B": {"zone_thermostat": "climate.bar_zone_2"},
        "C": {"zone_thermostat": "climate.baz_zone_3"},
        "D": {"zone_thermostat": "climate.qux_no_suffix"},
    }
    hass = _StubHass([_zm_entry(zones)])

    helper_map = {
        z["zone_id"]: (z["climate_entity"], z["zone_name"])
        for z in iter_canonical(hass)
    }

    zm = ZoneManager(hass)
    import asyncio
    asyncio.get_event_loop().run_until_complete(zm.async_discover_zones())
    zm_map = {
        zid: (zs.climate_entity, zs.zone_name)
        for zid, zs in zm.zones.items()
    }

    assert helper_map == zm_map, (
        f"Lockstep drift on 4-distinct-thermostats fixture.\n"
        f"  helper: {helper_map}\n"
        f"  ZM   : {zm_map}"
    )
