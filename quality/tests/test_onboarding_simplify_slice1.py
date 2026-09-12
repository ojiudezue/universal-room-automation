"""ONBOARDING-SIMPLIFY-1 — Slice 1 tests (D1 / D2 / D5-thin / D9 anchor).

Slice 1 scope: additive filters in `_get_area_entities`, the NEW pure
ranker `_rank_area_candidates`, the D2 `ROOM_TYPE_FEATURE_DEFAULTS`
table + deletion of the create-side bathroom cascade, D5-thin weather
auto-detect, and the D9 anchor parity for
`CONF_HUMIDITY_FAN_SPIKE_ENABLED` on bathroom.

D3 essentials-chain restructure, D4 ribbon inversion, D6 empty-area
legibility, and full D9 enumeration land in Slice 2 with their own
tests.
"""
from __future__ import annotations

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
_FakeHass = _cbcf._FakeHass

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
# Registry fakes
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
    """Install fake ent/dev registries into the mocked HA modules."""
    ha_er = sys.modules["homeassistant.helpers.entity_registry"]
    ha_dr = sys.modules["homeassistant.helpers.device_registry"]
    ent_reg = _FakeEntReg(entries)
    dev_reg = _FakeDevReg(devices)
    ha_er.async_get = lambda hass: ent_reg
    ha_dr.async_get = lambda hass: dev_reg
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
    Live state device_class is only a tiebreak; passes even if live state has
    device_class=None (registry is the authority).
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
    # denylist entry appears last
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
    # The specific cascade line:
    assert "user_input[CONF_WET_ROOM] = True" not in src, (
        "D2 requires the bathroom -> wet_room cascade to be deleted; found "
        "surviving assignment in async_step_climate (config_flow.py)."
    )


# ---------------------------------------------------------------------------
# D9 anchor — CONF_HUMIDITY_FAN_SPIKE_ENABLED bathroom parity
# ---------------------------------------------------------------------------

def test_deferred_parity_humidity_fan_spike_enabled():
    """D9 anchor row: bathroom -> True (was schema-default via wet_default).
    Consumer fallback at automation.py:2550 is False, so if the create
    path stops emitting the field, the effective post-create value would
    silently flip. ROOM_TYPE_FEATURE_DEFAULTS[bathroom][...] = True
    preserves parity.
    """
    row = ROOM_TYPE_FEATURE_DEFAULTS[ROOM_TYPE_BATHROOM]
    assert row[CONF_HUMIDITY_FAN_SPIKE_ENABLED] is True


def test_seed_applies_at_create_time_and_is_soft():
    """The seed must be applied at room-create (async_step_notifications)
    ONLY when the operator did not already set the key. Operator explicit
    False must win."""
    import inspect
    src = inspect.getsource(_cf.UniversalRoomAutomationConfigFlow.async_step_notifications)
    assert "ROOM_TYPE_FEATURE_DEFAULTS" in src, (
        "async_step_notifications must apply ROOM_TYPE_FEATURE_DEFAULTS seed"
    )
    # Soft-seed guard present:
    assert "not in self._data" in src, (
        "seed must be SOFT — operator explicit choice must win"
    )


# ---------------------------------------------------------------------------
# D5-thin — weather auto-detect
# ---------------------------------------------------------------------------

def test_weather_autodetect_single_entity():
    entries = [
        _reg_entry("weather.home", "weather"),
    ]
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
    """AUTODETECT_NAME_DENYLIST must cover the common diagnostic families
    the ranker uses as its safety backstop when entity_category is
    missing (mis-labeled devices)."""
    for token in ("chip_temperature", "linkquality", "rssi", "battery"):
        assert token in AUTODETECT_NAME_DENYLIST
