"""ONBOARDING-SIMPLIFY-1 — Slice 1 tests (D1 / D2 / D5-thin / D9 anchor).

19 tests total. Slice 1 scope: additive filters in `_get_area_entities`,
the NEW pure ranker `_rank_area_candidates`, the D2
`ROOM_TYPE_FEATURE_DEFAULTS` table + deletion of the create-side
bathroom cascade, D5-thin weather auto-detect, and the D9 anchor
BEHAVIORAL parity for `CONF_HUMIDITY_FAN_SPIKE_ENABLED` on bathroom.

D3 essentials-chain restructure, D4 ribbon inversion, D6 empty-area
legibility, and full D9 enumeration land in Slice 2 with their own
tests.

**Env portability (F1).** The borrowed harness in
`test_cycle_b_config_flow._load_config_flow()` mocks the HA module
tree, loads config_flow, then REMOVES the mocked modules from
sys.modules in its finally block. Our tests must therefore reinstall
their own registry stubs directly into sys.modules — they cannot
rely on sys.modules keys the harness cleared. Tests pass GREEN in
both the standard stub env (PYTHONPATH=quality) and .venv-ha, and
green whether run standalone or after test_cycle_b_config_flow.py.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Reuse the mocked-HA harness already used by test_cycle_b_config_flow.
_cbcf = importlib.import_module("test_cycle_b_config_flow")
_cf = _cbcf._cf
_make_config_flow = _cbcf._make_config_flow

CONF_WET_ROOM = _cf.CONF_WET_ROOM
CONF_HUMIDITY_FAN_SPIKE_ENABLED = _cf.CONF_HUMIDITY_FAN_SPIKE_ENABLED
CONF_ROOM_TYPE = _cf.CONF_ROOM_TYPE
CONF_ROOM_NAME = _cf.CONF_ROOM_NAME
CONF_ENTRY_TYPE = _cf.CONF_ENTRY_TYPE
CONF_INTEGRATION_ENTRY_ID = _cf.CONF_INTEGRATION_ENTRY_ID
ROOM_TYPE_BATHROOM = _cf.ROOM_TYPE_BATHROOM
ROOM_TYPE_FEATURE_DEFAULTS = _cf.ROOM_TYPE_FEATURE_DEFAULTS
AUTODETECT_NAME_DENYLIST = _cf.AUTODETECT_NAME_DENYLIST


# ---------------------------------------------------------------------------
# Registry fakes (F1: locally installed — do not read sys.modules)
# ---------------------------------------------------------------------------

def _reg_entry(
    entity_id,
    domain,
    *,
    device_id=None,
    area_id=None,
    disabled_by=None,
    hidden_by=None,
    entity_category=None,
    platform="mqtt",
    original_device_class=None,
    device_class=None,
):
    return SimpleNamespace(
        entity_id=entity_id,
        domain=domain,
        device_id=device_id,
        area_id=area_id,
        disabled_by=disabled_by,
        hidden_by=hidden_by,
        entity_category=entity_category,
        platform=platform,
        original_device_class=original_device_class,
        device_class=device_class,
    )


class _FakeEntReg:
    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}

    def async_get(self, eid):
        return self.entities.get(eid)


class _FakeDevReg:
    def __init__(self, devices=None):
        self._d = devices or {}

    def async_get(self, dev_id):
        return self._d.get(dev_id)


def _install_registries(entries, devices=None):
    """Install fake ent/dev registries.

    F1: We construct the `homeassistant.helpers.entity_registry` and
    `homeassistant.helpers.device_registry` module objects locally and
    inject them into sys.modules. The borrowed
    `_load_config_flow()` finally-block removed the harness's mock
    modules from sys.modules after config_flow loaded, so we cannot
    look them up — we must (re)create them. This makes the tests
    portable across the standard stub env and .venv-ha.
    """
    ent_reg = _FakeEntReg(entries)
    dev_reg = _FakeDevReg(devices)

    # Ensure the parent packages exist (harmless if already present).
    for parent in ("homeassistant", "homeassistant.helpers"):
        if parent not in sys.modules:
            sys.modules[parent] = types.ModuleType(parent)

    er_mod = sys.modules.get("homeassistant.helpers.entity_registry")
    if er_mod is None:
        er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
        sys.modules["homeassistant.helpers.entity_registry"] = er_mod
    er_mod.async_get = lambda hass: ent_reg
    sys.modules["homeassistant.helpers"].entity_registry = er_mod

    dr_mod = sys.modules.get("homeassistant.helpers.device_registry")
    if dr_mod is None:
        dr_mod = types.ModuleType("homeassistant.helpers.device_registry")
        sys.modules["homeassistant.helpers.device_registry"] = dr_mod
    dr_mod.async_get = lambda hass: dev_reg
    sys.modules["homeassistant.helpers"].device_registry = dr_mod

    return ent_reg, dev_reg


# ---------------------------------------------------------------------------
# D1 — _get_area_entities additive filters
# ---------------------------------------------------------------------------

def test_get_area_entities_no_shrink_beyond_new_filters():
    """4-light device -> _get_area_entities returns all 4 (no dedup)."""
    entries = [
        _reg_entry(f"light.strip_{i}", "light", device_id="dev1", area_id="area1")
        for i in range(4)
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    got = flow._get_area_entities("area1", "light", None)
    assert got == sorted(e.entity_id for e in entries)
    assert len(got) == 4, "D1 must NOT dedup — 14 callers rely on full list"


def test_area_detect_excludes_diagnostic():
    """DIAGNOSTIC entity_category filtered out by additive filter."""
    entries = [
        _reg_entry("sensor.chip_temperature", "sensor", area_id="area1",
                   entity_category="diagnostic",
                   original_device_class="temperature"),
        _reg_entry("sensor.room_temp", "sensor", area_id="area1",
                   original_device_class="temperature"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    got = flow._get_area_entities("area1", "sensor", "temperature")
    assert "sensor.chip_temperature" not in got
    assert "sensor.room_temp" in got


def test_area_detect_excludes_hidden_and_helper_platform():
    entries = [
        _reg_entry("sensor.hidden_one", "sensor", area_id="area1",
                   original_device_class="temperature",
                   hidden_by="user"),
        _reg_entry("sensor.template_one", "sensor", area_id="area1",
                   original_device_class="temperature",
                   platform="template"),
        _reg_entry("sensor.real_one", "sensor", area_id="area1",
                   original_device_class="temperature"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    got = flow._get_area_entities("area1", "sensor", "temperature")
    assert got == ["sensor.real_one"]


# ---------------------------------------------------------------------------
# D1 — _rank_area_candidates
# ---------------------------------------------------------------------------

def test_ranker_dedup_2_suffix_registry_class():
    """`sensor.foo_temp` + `sensor.foo_temp_2` on same device -> single winner.

    Dedup key = (device_id, registry.original_device_class or device_class).
    Live state device_class is only a tiebreak; passes even if live state
    has device_class=None (registry is the authority).
    """
    entries = [
        _reg_entry("sensor.foo_temp", "sensor", device_id="d1", area_id="a1",
                   original_device_class="temperature", device_class=None),
        _reg_entry("sensor.foo_temp_2", "sensor", device_id="d1", area_id="a1",
                   original_device_class="temperature", device_class=None),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    ranked = flow._rank_area_candidates(
        ["sensor.foo_temp", "sensor.foo_temp_2"], actuator_device_ids=set()
    )
    assert len(ranked) == 1, f"expected 1 winner after dedup, got {ranked}"
    assert ranked[0] == "sensor.foo_temp"  # entity_id sort tiebreak


def test_ranker_classless_same_device_does_not_collapse():
    """F3: `light.*` (class None) on same device_id -> ALL kept.

    Regression fixture: 4-light bar on one dev1 with resolved class None.
    Prior dedup key `(device_id, None)` would have collapsed all 4 to 1.
    The classless-guard folds entity_id into the key.
    """
    entries = [
        _reg_entry(f"light.strip_{i}", "light", device_id="dev1", area_id="a1",
                   original_device_class=None, device_class=None)
        for i in range(4)
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    ranked = flow._rank_area_candidates(
        [e.entity_id for e in entries], actuator_device_ids=set()
    )
    assert len(ranked) == 4, (
        f"F3: classless entities on one device MUST NOT collapse; got {ranked}"
    )


def test_ranker_denylist_backstop():
    """A denylisted-name entity ranks LAST even if registry looks clean."""
    entries = [
        _reg_entry("sensor.zigbee_linkquality", "sensor", device_id="d1",
                   area_id="a1", original_device_class=None),
        _reg_entry("sensor.room_temp", "sensor", device_id="d2", area_id="a1",
                   original_device_class="temperature"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    ranked = flow._rank_area_candidates(
        ["sensor.zigbee_linkquality", "sensor.room_temp"], set()
    )
    assert ranked[-1] == "sensor.zigbee_linkquality"
    assert ranked[0] == "sensor.room_temp"


def test_ranker_actuator_shared_deprioritized():
    """Temp sharing device_id with a room switch ranks BELOW dedicated temp."""
    entries = [
        _reg_entry("sensor.dedicated_temp", "sensor", device_id="dtemp",
                   area_id="a1", original_device_class="temperature"),
        _reg_entry("sensor.shelly_relay_temp", "sensor", device_id="dsw",
                   area_id="a1", original_device_class="temperature"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    ranked = flow._rank_area_candidates(
        ["sensor.shelly_relay_temp", "sensor.dedicated_temp"],
        actuator_device_ids={"dsw"},
    )
    assert ranked[0] == "sensor.dedicated_temp"
    assert ranked[-1] == "sensor.shelly_relay_temp"


def test_ranker_entity_area_beats_device_area():
    """Entity with own area_id ranks ABOVE one only inheriting device area."""
    entries = [
        _reg_entry("sensor.own_area", "sensor", device_id="d1", area_id="a1",
                   original_device_class="temperature"),
        _reg_entry("sensor.inherited", "sensor", device_id="d2", area_id=None,
                   original_device_class="temperature"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    ranked = flow._rank_area_candidates(
        ["sensor.inherited", "sensor.own_area"], set()
    )
    assert ranked[0] == "sensor.own_area"


def test_ranker_is_pure_no_registry_mutation():
    """Calling ranker must not mutate registry or entity attributes."""
    entries = [
        _reg_entry("sensor.a", "sensor", device_id="d1", area_id="a1",
                   original_device_class="temperature"),
    ]
    ent_reg, _ = _install_registries(entries)
    before = dict(vars(entries[0]))
    flow = _make_config_flow()
    flow._rank_area_candidates(["sensor.a"], set())
    after = dict(vars(ent_reg.entities["sensor.a"]))
    assert before == after


# ---------------------------------------------------------------------------
# D2 — ROOM_TYPE_FEATURE_DEFAULTS + cascade deletion
# ---------------------------------------------------------------------------

def test_room_type_feature_defaults_has_bathroom_wet_room():
    """Table exists and seeds bathroom -> wet_room=True + spike=True."""
    assert ROOM_TYPE_BATHROOM in ROOM_TYPE_FEATURE_DEFAULTS
    row = ROOM_TYPE_FEATURE_DEFAULTS[ROOM_TYPE_BATHROOM]
    assert row.get(CONF_WET_ROOM) is True
    assert row.get(CONF_HUMIDITY_FAN_SPIKE_ENABLED) is True


def test_no_two_producers_wet_room_cascade_removed():
    """Grep test: the create-side climate-step bathroom->wet_room cascade
    must be DELETED; wet_room now flows exclusively via
    ROOM_TYPE_FEATURE_DEFAULTS. Any surviving `user_input[CONF_WET_ROOM] = True`
    inside the create-side async_step_climate block is a regression."""
    import inspect
    src = inspect.getsource(_cf.UniversalRoomAutomationConfigFlow.async_step_climate)
    assert "user_input[CONF_WET_ROOM] = True" not in src, (
        "D2 requires the bathroom -> wet_room cascade to be deleted; found "
        "surviving assignment in async_step_climate (config_flow.py)."
    )


# ---------------------------------------------------------------------------
# D9 anchor — BEHAVIORAL parity via async_step_notifications (F2)
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.new_event_loop().run_until_complete(coro)


def _drive_notifications(user_input):
    """T6 (Tier-3 fix-up): D9 anchor repointed to `async_step_room_summary`
    (the reachable create-path finale in the D3-reshaped chain).
    `async_step_notifications` is unreached from create-path after Slice 2
    and its duplicate seed loop was removed (single-producer discipline).

    Drives the room-summary step with pre-populated `_data` (mimicking
    what the reshaped chain accumulates) and returns the created-entry
    `data` dict."""
    flow = _make_config_flow()
    flow._data.update(user_input)
    result = _run(flow.async_step_room_summary(user_input={}))
    assert result.get("type") == "create_entry", (
        f"expected create_entry, got {result}"
    )
    return result["data"], flow


def test_bathroom_create_seeds_feature_defaults_behavioral():
    """F2 BEHAVIORAL: drive async_step_notifications for a bathroom with
    user_input that does NOT include CONF_WET_ROOM or
    CONF_HUMIDITY_FAN_SPIKE_ENABLED; assert the seed lands in the
    created-entry data. This is the discriminator: neutering the seed
    loop makes this test go RED. Slice 2 D3 removes those fields from
    the essentials path — this anchor guards that removal."""
    data, _ = _drive_notifications({
        CONF_ROOM_NAME: "Master Bath",
        CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
    })
    assert data[CONF_WET_ROOM] is True, (
        "D2/D9 seed did not land: bathroom room lacks CONF_WET_ROOM=True"
    )
    assert data[CONF_HUMIDITY_FAN_SPIKE_ENABLED] is True, (
        "D9 anchor did not land: bathroom lacks CONF_HUMIDITY_FAN_SPIKE_ENABLED=True"
    )


def test_bathroom_create_seed_is_soft_operator_false_wins():
    """F2 explicit-False-wins leg: operator sets CONF_WET_ROOM=False and
    CONF_HUMIDITY_FAN_SPIKE_ENABLED=False; seed must NOT override them.
    (SOFT default semantics: operator explicit choice wins on re-edit.)
    """
    data, _ = _drive_notifications({
        CONF_ROOM_NAME: "Powder Room",
        CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM,
        CONF_WET_ROOM: False,
        CONF_HUMIDITY_FAN_SPIKE_ENABLED: False,
    })
    assert data[CONF_WET_ROOM] is False, "seed overrode explicit-False (WET_ROOM)"
    assert data[CONF_HUMIDITY_FAN_SPIKE_ENABLED] is False, (
        "seed overrode explicit-False (HUMIDITY_FAN_SPIKE_ENABLED)"
    )


def test_deferred_parity_humidity_fan_spike_enabled_table():
    """D9 anchor row (table-level): bathroom -> True (was schema-default
    via wet_default). Consumer fallback at automation.py:2550 is False,
    so if the create path stops emitting the field the effective post-
    create value would silently flip. Table row asserts parity intent."""
    row = ROOM_TYPE_FEATURE_DEFAULTS[ROOM_TYPE_BATHROOM]
    assert row[CONF_HUMIDITY_FAN_SPIKE_ENABLED] is True


# ---------------------------------------------------------------------------
# D5-thin — weather auto-detect
# ---------------------------------------------------------------------------

def test_weather_autodetect_single_entity():
    entries = [_reg_entry("weather.home", "weather")]
    _install_registries(entries)
    flow = _make_config_flow()
    assert flow._detect_weather_entity() == "weather.home"


def test_weather_autodetect_none_when_absent():
    _install_registries([])
    flow = _make_config_flow()
    assert flow._detect_weather_entity() is None


def test_weather_autodetect_alphabetical_first_when_multiple():
    entries = [
        _reg_entry("weather.z_backup", "weather"),
        _reg_entry("weather.a_primary", "weather"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    assert flow._detect_weather_entity() == "weather.a_primary"


def test_weather_autodetect_skips_disabled():
    entries = [
        _reg_entry("weather.disabled", "weather", disabled_by="user"),
        _reg_entry("weather.live", "weather"),
    ]
    _install_registries(entries)
    flow = _make_config_flow()
    assert flow._detect_weather_entity() == "weather.live"


# ---------------------------------------------------------------------------
# D1 denylist constant sanity
# ---------------------------------------------------------------------------

def test_autodetect_denylist_covers_common_diagnostic_names():
    for token in ("chip_temperature", "linkquality", "rssi", "battery"):
        assert token in AUTODETECT_NAME_DENYLIST
