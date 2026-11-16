"""S3b: MS600 family by registry ``model`` (never by entity name).

Plan: docs/planning/PLANNING_stuck_sensor_truth.md rev 2, §3 S3b.
INV-S3b: every MS600 device record resolves to the radar family by registry
``model``, and no other live (model_id, model) pair changes family.

Live fact (core.device_registry, read 2026-11-15): the meross_lan device
record that OWNS ``..._sensor_presence_motion`` has ``model`` = "ms600-un",
``model_id`` None; each room also has an "ms600 9.0.0" record with the same
meross_lan identifier. Before S3b "ms600-un" resolved ``unknown`` and only
the entity-name regex kept the bit out of the witness list.

Bug classes guarded: registry-not-names (CLAUDE.md), #63 (two device records
for one device: the fixture names the record that owns the entity), #62 (the
REAL coordinator producer / recheck manager / resolve_sensor_family run).
The golden oracle is develop's resolver output captured before the edit
(``fixtures/s3b_live_device_models.json``), plus the one intended change.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_occupancy_source_follows_capability as occ

SC = occ.SC
FV = occ.FV
FR = occ.FR
CONST = occ.CONST
RADAR = occ.RADAR

FIXTURE = Path(__file__).parent / "fixtures" / "s3b_live_device_models.json"

# The live media bit and its owner record (model "ms600-un").
BIT = occ.MS_MOT
MODELS_LIVE = dict(occ.MODELS)
MODELS_LIVE[BIT] = (None, "ms600-un")


def test_family_ms600_hyphen_model_is_radar():
    """The live owner model, and a suffix the exact table does not list
    (proves the hyphen / underscore split, not just the table row)."""
    assert SC.family_for_model(None, "ms600-un") == SC.SENSOR_FAMILY_GENERIC_RADAR
    assert SC.family_for_model(None, "MS600-EU") == SC.SENSOR_FAMILY_GENERIC_RADAR
    assert SC.family_for_model(None, "ms600_xx 1.2") == SC.SENSOR_FAMILY_GENERIC_RADAR
    assert SC.family_for_model(None, "ms600 9.0.0") == SC.SENSOR_FAMILY_GENERIC_RADAR


def test_family_split_does_not_capture_other_hyphen_models():
    """Hyphenated Zigbee models keep their exact-table family; an unknown
    hyphenated model stays unknown."""
    assert SC.family_for_model("ZG-204ZV", "x") == SC.SENSOR_FAMILY_ZIGBEE_ZV
    assert SC.family_for_model("SNZB-03P", "Motion sensor") == SC.SENSOR_FAMILY_PIR
    assert SC.family_for_model(None, "esp32-c3-devkitm-1") == SC.SENSOR_FAMILY_UNKNOWN
    assert SC.family_for_model(None, "") == SC.SENSOR_FAMILY_UNKNOWN
    assert SC.family_for_model(None, None) == SC.SENSOR_FAMILY_UNKNOWN


def test_family_golden_live_models():
    """Every live (model_id, model) pair: same family as develop, except the
    ms600-un records, which become generic_radar."""
    data = json.loads(FIXTURE.read_text())
    changed = []
    for row in data["pairs"]:
        mid, mod, before = row["model_id"], row["model"], row["family_develop"]
        expected = (
            SC.SENSOR_FAMILY_GENERIC_RADAR if mod == "ms600-un" else before
        )
        got = SC.family_for_model(mid, mod)
        assert got == expected, (mid, mod, before, got)
        if got != before:
            changed.append(mod)
    assert changed == ["ms600-un"], changed
    # Each MS600 motion bit is owned by an ms600-un record (three rooms).
    owners = data["ms600_entity_owner"]
    assert len(owners) == 3
    assert {o["model"] for o in owners.values()} == {"ms600-un"}


def test_bit_family_resolves_from_owner_record(monkeypatch):
    """The REAL resolve_sensor_family reads the entity's own device record."""
    occ._install_registry(monkeypatch, MODELS_LIVE)
    hass = occ._hass({})
    hass.data[CONST.DOMAIN] = {}
    assert FV.resolve_sensor_family(hass, BIT) == SC.SENSOR_FAMILY_GENERIC_RADAR


def _world_live(monkeypatch, on, **conf):
    hass, states, r = occ._world(monkeypatch, on=on, **conf)
    occ._install_registry(monkeypatch, MODELS_LIVE)
    hass.data[CONST.DOMAIN] = {}
    return hass, states, r


def test_media_bit_tick_is_radar_sole(monkeypatch):
    """Media: only the meross_lan bit is on (Matter occupancy off) -> the
    producer stamps a radar-sole tick (develop: unknown family -> False)."""
    _h, _s, r = _world_live(
        monkeypatch, on={BIT}, motion=[BIT], presence=[occ.MS_OCC],
    )
    assert occ._sole(r) is True
    assert occ._tick(r)[RADAR] is True


def test_bit_plus_zv_not_radar_sole(monkeypatch):
    """A fan-immune ZV on in the same tick keeps it mixed."""
    _h, _s, r = _world_live(
        monkeypatch, on={BIT, occ.ZV}, motion=[BIT, occ.ZV],
    )
    assert occ._sole(r) is False


def test_bit_is_not_a_fan_immune_witness_by_model(monkeypatch):
    """Rule 3: the bit is held out of the witness list by its MODEL (the
    entity id here has no mmwave / radar / presence word for the regex)."""
    occ._install_registry(monkeypatch, {"binary_sensor.gb_bit_motion": (None, "ms600-un")})
    hass = occ._hass({})
    hass.data[CONST.DOMAIN] = {}
    config = {CONST.CONF_MOTION_SENSORS: ["binary_sensor.gb_bit_motion"]}
    assert FV.is_fan_immune_motion_witness(
        hass, config, "binary_sensor.gb_bit_motion",
    ) is False


def _recheck_live(monkeypatch, *, on, fan_mode, **conf):
    mgr, rc, states = occ._recheck_world(monkeypatch, on=on, **conf)
    occ._install_registry(monkeypatch, MODELS_LIVE)
    rc.entry.options = {CONST.CONF_ROOM_FAN_MODE: fan_mode}
    return mgr, rc, states


def test_gb1_radar_route_eligible_after_s3b(monkeypatch):
    """GB1 shape (Fan Mode room_temperature, unpaused): only the bit is on ->
    radar-sole history -> the radar recheck route arms (develop vetoed it
    `not_radar_sole`). Q-B: intended."""
    mgr, rc, _s = _recheck_live(
        monkeypatch, on={BIT}, fan_mode=CONST.FAN_MODE_ROOM_TEMPERATURE,
        motion=[BIT, occ.ZV], presence=[occ.MS_OCC],
    )
    occ._fill(rc)
    assert rc.recent_radar_sole_ring()[-3:] == [True] * 3
    assert occ._eligible(mgr, rc) is True


def test_media_fan_mode_off_still_vetoed(monkeypatch):
    """Media / GB2 (Fan Mode Off): the radar route stays vetoed."""
    mgr, rc, _s = _recheck_live(
        monkeypatch, on={BIT}, fan_mode=CONST.FAN_MODE_OFF,
        motion=[BIT], presence=[occ.MS_OCC],
    )
    occ._fill(rc)
    assert occ._eligible(mgr, rc) is False
    assert mgr._veto_counts["Media"]["fan_control_off"] == 1


def test_bit_only_room_family_factor_is_generic_radar(monkeypatch):
    """The recheck window family factor reads the bit's family: 1.5."""
    mgr, rc, _s = _recheck_live(
        monkeypatch, on=set(), fan_mode=CONST.FAN_MODE_ROOM_TEMPERATURE,
        motion=[BIT],
    )
    merged = {**rc.entry.data, **rc.entry.options}
    assert mgr._family_factor(merged, {}, "Media") == 1.5
