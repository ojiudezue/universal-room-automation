"""D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1 — card tests.

Problem (card):
  coordinator.py stamped ``_last_pir_motion_time`` and cleared the D2
  flap-latch with reason ``pir_motion`` on ANY ``motion_detected`` tick —
  including the ``meross_lan`` MS600 motion bit, which is radar-derived
  and can be faked by a fan. So in GB1/GB2/Media a fan-faked motion bit
  kept ``pir_stale`` False and held D2 off, and the latch oscillated.

Fix (card):
  Both sites must consult
  ``fan_veto.is_fan_immune_motion_witness`` on the on-set of
  CONF_MOTION_SENSORS; stamp / clear ONLY when a real fan-immune witness
  is on. Fail-closed on exceptions (do NOT stamp / do NOT clear).

Tests drive the real production code:
  * ``_fan_immune_motion_witness_on`` is bound off the real coordinator
    class onto a stub (same technique as
    ``test_occupancy_source_follows_capability``).
  * ``_evaluate_mmwave_demoted_latch`` is called with the real
    production body (bound).
  * The PIR-stamp branch is extracted as a text SLICE from
    coordinator.py and ``exec``'d — real production source, not a
    hand-copy (mutation anchor: edit the real site, test flips).

Mutation drill results — recorded here, re-run by orchestrator:
  * Revert the ``if motion_witness_detected:`` guard at the stamp site
    (make the stamp unconditional under ``motion_detected``):
    ``test_stamp_slice_no_refresh_on_radar_motion_bit`` goes RED.
  * Revert the ``pir_fire = motion_witness_detected`` guard in
    ``_evaluate_mmwave_demoted_latch`` (use raw ``motion_detected``):
    ``test_latch_not_cleared_by_radar_motion_bit`` goes RED.
"""

from __future__ import annotations

import collections
import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_URA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)
_PKG = "ura_d2_pir_witness_pkg"


def _load():
    if f"{_PKG}.coordinator" not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_URA_ROOT)]
        sys.modules[_PKG] = pkg
        dc = types.ModuleType(f"{_PKG}.domain_coordinators")
        dc.__path__ = [str(_URA_ROOT / "domain_coordinators")]
        sys.modules[f"{_PKG}.domain_coordinators"] = dc
    names = (
        "const", "fan_veto", "domain_coordinators.sensor_capability",
        "coordinator",
    )
    return [importlib.import_module(f"{_PKG}.{n}") for n in names]


CONST, FV, SC, CO = _load()
DOMAIN = CONST.DOMAIN


# Entities + models mirror AUDIT_motion_sensors_live_models.md (reused
# from test_occupancy_source_follows_capability.py).
MS_MOT = "binary_sensor.media_sensor_presence_motion"   # meross_lan radar motion bit
PIR = "binary_sensor.pir_hall_motion"                   # fan-immune PIR
MS_OCC = "binary_sensor.mmwave_motion_lux_matter_wifi_media_occupancy"

MODELS = {
    MS_MOT: (None, "ms600 9.0.0"),               # family = generic_radar via model text
    PIR: ("SNZB-03P", "Motion sensor"),           # fan-immune PIR
    MS_OCC: ("16897", "Smart Presence Sensor"),   # Meross MS600 Matter radar
}


class _State:
    def __init__(self, s):
        self.state = s
        self.attributes = {}
        self.last_changed = None


class _Entry:
    def __init__(self, data):
        self.entry_id = "entry"
        self.data = dict(data)
        self.options = {}


def _install_registry(monkeypatch, models=None):
    models = dict(MODELS if models is None else models)
    ent_reg = types.SimpleNamespace(
        async_get=lambda eid: (
            types.SimpleNamespace(device_id=f"dev::{eid}")
            if eid in models else None
        ),
    )
    dev_reg = types.SimpleNamespace(
        async_get=lambda did: (
            types.SimpleNamespace(
                model_id=models[did[5:]][0], model=models[did[5:]][1],
            )
            if did.startswith("dev::") and did[5:] in models else None
        ),
    )
    er = types.ModuleType("homeassistant.helpers.entity_registry")
    er.async_get = lambda hass: ent_reg
    dr = types.ModuleType("homeassistant.helpers.device_registry")
    dr.async_get = lambda hass: dev_reg
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", er)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.device_registry", dr)
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is not None:
        monkeypatch.setattr(helpers, "entity_registry", er, raising=False)
        monkeypatch.setattr(helpers, "device_registry", dr, raising=False)


_BOUND = (
    "_get_config", "_is_sensor_on", "_fusion_filter_active",
    "_fan_immune_motion_witness_on", "_evaluate_mmwave_demoted_latch",
)


class _Coord:
    pass


def _coord(hass, motion):
    entry = _Entry({
        CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM,
        CONST.CONF_ROOM_NAME: "Media",
        "room_name": "Media",
        CONST.CONF_MMWAVE_SENSORS: [],
        CONST.CONF_MOTION_SENSORS: list(motion),
        CONST.CONF_OCCUPANCY_SENSORS: [],
    })
    r = _Coord()
    r.hass = hass
    r.entry = entry
    for name in _BOUND:
        setattr(r, name, getattr(CO.UniversalRoomCoordinator, name).__get__(r))
    r._exclusion_set = types.SimpleNamespace(is_excluded=lambda s: False)
    r._mmwave_demoted_latch = False
    r.data = {}
    return r


def _hass(on=()):
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    states = {e: _State("on" if e in on else "off") for e in MODELS}
    hass.states.get = lambda eid: states.get(eid)
    return hass


# ---------------------------------------------------------------------------
# Helper _fan_immune_motion_witness_on
# ---------------------------------------------------------------------------

def test_helper_false_when_only_radar_motion_bit_on(monkeypatch):
    """MS_MOT (meross_lan radar-derived motion bit) on, under
    CONF_MOTION_SENSORS -> helper returns False (device-model classifier
    recognises family = generic_radar and refuses it as a witness)."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={MS_MOT}), motion=[MS_MOT])
    assert r._fan_immune_motion_witness_on([MS_MOT]) is False


def test_helper_true_when_real_pir_on(monkeypatch):
    """Real PIR (SNZB-03P) on under CONF_MOTION_SENSORS -> helper
    returns True (fan-immune by capability + model)."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={PIR}), motion=[PIR])
    assert r._fan_immune_motion_witness_on([PIR]) is True


def test_helper_false_when_mixed_radar_on_pir_off(monkeypatch):
    """Mixed room: MS_MOT on + PIR off (both in CONF_MOTION_SENSORS)
    -> helper False (no on witness that is fan-immune)."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={MS_MOT}), motion=[MS_MOT, PIR])
    assert r._fan_immune_motion_witness_on([MS_MOT, PIR]) is False


def test_helper_true_when_mixed_radar_and_pir_both_on(monkeypatch):
    """MS_MOT on + PIR on -> helper True (short-circuits on first
    fan-immune on witness, radar presence does not disqualify)."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={MS_MOT, PIR}), motion=[MS_MOT, PIR])
    assert r._fan_immune_motion_witness_on([MS_MOT, PIR]) is True


# ---------------------------------------------------------------------------
# _evaluate_mmwave_demoted_latch — reason='pir_motion' now gated on
# motion_witness_detected, not raw motion_detected.
# ---------------------------------------------------------------------------

def test_latch_not_cleared_by_radar_motion_bit(monkeypatch):
    """motion_detected=True (radar-derived bit) BUT motion_witness
    =False -> pir_motion reason must NOT fire; latch stays set
    (presence_detected=True + no other recovery)."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={MS_MOT}), motion=[MS_MOT])
    r._mmwave_demoted_latch = True
    r._evaluate_mmwave_demoted_latch(
        "Media", motion_detected=True, presence_detected=True,
        radar_sole=True, motion_witness_detected=False,
    )
    assert r._mmwave_demoted_latch is True, (
        "radar motion bit must not clear the D2 latch — "
        "pir_motion reason requires a fan-immune witness"
    )


def test_latch_cleared_by_real_pir_witness(monkeypatch):
    """motion_witness=True -> pir_motion reason clears the latch."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={PIR}), motion=[PIR])
    r._mmwave_demoted_latch = True
    r._evaluate_mmwave_demoted_latch(
        "Media", motion_detected=True, presence_detected=True,
        radar_sole=False, motion_witness_detected=True,
    )
    assert r._mmwave_demoted_latch is False, (
        "fan-immune witness on must clear the D2 latch via pir_motion"
    )


def test_latch_legacy_shape_no_bool_falls_back_to_motion_detected(
    monkeypatch,
):
    """Direct callers that pre-date the fix (don't pass the kwarg)
    retain legacy semantics so this change is backward compatible —
    pir_motion fires on raw motion_detected=True."""
    _install_registry(monkeypatch)
    r = _coord(_hass(on={MS_MOT}), motion=[MS_MOT])
    r._mmwave_demoted_latch = True
    r._evaluate_mmwave_demoted_latch(
        "Media", motion_detected=True, presence_detected=True,
        radar_sole=True,  # motion_witness_detected omitted
    )
    assert r._mmwave_demoted_latch is False  # legacy shape


# ---------------------------------------------------------------------------
# Stamp site — real source slice compiled from coordinator.py.
# ---------------------------------------------------------------------------

def _stamp_slice():
    """Extract the exact PIR-stamp branch (inside _async_update_data)
    from coordinator.py and compile it. Dedent to module scope."""
    src = (_URA_ROOT / "coordinator.py").read_text(encoding="utf-8")
    start = '            if motion_detected:\n                data[STATE_OCCUPANCY_SOURCE] = "motion"'
    end = '            elif presence_detected:'
    assert src.count(start) == 1, "stamp-site start marker moved"
    i = src.index(start)
    j = src.index(end, i)
    block = src[i:j]
    lines = []
    for ln in block.splitlines():
        if ln.startswith("            "):
            lines.append(ln[12:])
        elif ln.strip() == "":
            lines.append("")
        else:
            lines.append(ln.strip())
    return compile("\n".join(lines), str(_URA_ROOT / "coordinator.py"), "exec")


_STAMP_CODE = _stamp_slice()


def _run_stamp(*, motion_witness_detected: bool):
    """Exec the real stamp branch with a fake self and capture
    whether ``_last_pir_motion_time`` got refreshed."""
    SENTINEL = datetime(2000, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    class _S:
        pass

    self_ = _S()
    self_._last_pir_motion_time = SENTINEL
    data: dict = {}
    ns = dict(vars(CO))
    ns.update(
        self=self_, data=data, now=now,
        motion_detected=True,
        motion_witness_detected=motion_witness_detected,
    )
    exec(_STAMP_CODE, ns)
    return self_._last_pir_motion_time, data, now, SENTINEL


def test_stamp_slice_no_refresh_on_radar_motion_bit():
    """motion_detected=True + motion_witness_detected=False ->
    _last_pir_motion_time MUST NOT be refreshed; occupancy source
    label stays 'motion' (card constraint — unchanged)."""
    stamp, data, now, sentinel = _run_stamp(motion_witness_detected=False)
    assert stamp == sentinel, (
        "radar motion bit refreshed _last_pir_motion_time — the "
        "pir_stale leg (e) of Invariant M is now permanently False"
    )
    assert data[CONST.STATE_OCCUPANCY_SOURCE] == "motion"


def test_stamp_slice_refresh_on_real_pir_witness():
    """motion_witness_detected=True -> stamp refreshed to `now`."""
    stamp, data, now, sentinel = _run_stamp(motion_witness_detected=True)
    assert stamp == now
    assert data[CONST.STATE_OCCUPANCY_SOURCE] == "motion"
