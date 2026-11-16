"""S1 (K2): P22 off-pulse tolerance for MOTION-class inputs.

Plan: docs/planning/PLANNING_stuck_sensor_truth.md rev 2, §3 S1.
INV-S1: with tolerance > 0, a motion-class input whose every off and every
dead stretch is shorter than the tolerance is P22-excluded at run start
(``last_changed`` of its rising edge) + ``STUCK_P22_HOURS``, whatever the
poll phase; an off or dead stretch >= tolerance restarts the run; a still
holder, an unknown family and tolerance 0 behave exactly as develop.

Every test drives the REAL ``_p22_stamp_tick`` (and its tolerance resolver,
the REAL ``derive_capability`` + ``fan_veto.resolve_sensor_family`` over a
scoped registry fake) bound onto a bare room object; the enclosing-method
anchor executes the production slice of ``_async_update_data`` that holds
the call. Oracles are hand-derived timestamps; boundaries are literals
(9 / 10 / 11 s, 3:59:59 / 4:00:00), never the imported constant.

Bug classes guarded: #53 (every reader of the run sees the same run), #62
(no source greps), #63 (still holder vs fan-immune witness are two
properties: the bed case), suppression-needs-discharge (an off >= the
tolerance, a dead stretch, a restart all end the run).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import test_occupancy_source_follows_capability as occ

CO = occ.CO
CONST = occ.CONST
SC = occ.SC

ZV = "binary_sensor.upguest_zv_presence_2"        # ZG-204ZV, motion list
PIR = "binary_sensor.hall_pir_motion"             # SNZB-03P, motion list
RADAR = "binary_sensor.media_matter_occupancy"    # MS600 Matter, presence list
BED = "binary_sensor.bed_left"                    # PIR-family device, bed override
CAMP = "binary_sensor.room_camera_person"         # PIR-family device, camera override
ESP = "binary_sensor.jaya_ld2410_presence"        # unknown family (ESPHome board)
MS_BIT = "binary_sensor.media_sensor_presence_motion"  # ms600-un, motion list

MODELS = {
    ZV: ("ZG-204ZV", "Millimeter wave motion detection"),
    PIR: ("SNZB-03P", "Motion sensor"),
    RADAR: ("16897", "Smart Presence Sensor"),
    BED: ("SNZB-03P", "Motion sensor"),
    CAMP: ("SNZB-03P", "Motion sensor"),
    ESP: (None, "esp32-c3-devkitm-1"),
    MS_BIT: (None, "ms600-un"),
}

UTC = timezone.utc
T0 = datetime(2026, 11, 15, 8, 51, 52, tzinfo=UTC)  # upguest ZV run start


class _St:
    def __init__(self, state, last_changed):
        self.state = state
        self.last_changed = last_changed
        self.attributes = {}


class _Room:
    pass


_BOUND = (
    "_p22_stamp_tick", "_p22_off_gap_tolerance_s", "_is_sensor_on",
    "_p22_stuck_sensor_set", "_get_config",
)


def _room(monkeypatch, *, motion=(ZV, PIR, BED, CAMP, ESP, MS_BIT),
          presence=(RADAR,), caps=None, tol=None):
    occ._install_registry(monkeypatch, MODELS)
    if tol is not None:
        monkeypatch.setattr(CONST, "STUCK_P22_OFF_GAP_TOLERANCE_S", tol)
    states: dict = {}
    hass = occ._hass(states)
    hass.data = {CONST.DOMAIN: {}}
    caps = {BED: {"kind": "bed"}, CAMP: {"kind": "camera_presence"}} if caps is None else caps
    entry = occ._entry("Upstairs Guest", motion=motion, presence=presence, caps=caps)
    r = _Room()
    r.hass = hass
    r.entry = entry
    for name in _BOUND:
        setattr(r, name, getattr(CO.UniversalRoomCoordinator, name).__get__(r))
    r._sensor_on_since = {}
    r._p22_off_since = {}
    r._p22_off_state = {}
    r._p22_last_on_tick = {}
    r._p22_on_lc = {}
    r._post_restart_seen_on = set()
    r._stuck_sensor_hours = 4.0
    r._d2_boot_settle_done = lambda: True
    r.states = states
    return r


def _tick(r, now, **readings):
    """One room tick: set each named input's state, run the REAL stamp."""
    for eid, (state, lc) in readings.items():
        r.states[eid] = _St(state, lc)
    r._p22_stamp_tick(now, (r._get_config(CONST.CONF_MOTION_SENSORS, []),
                            r._get_config(CONST.CONF_MMWAVE_SENSORS, []),
                            r._get_config(CONST.CONF_OCCUPANCY_SENSORS, [])))


def _s(sec):
    return timedelta(seconds=sec)


def _run_on(r, eid, start, until, step=30, phase=7):
    """Ticks every ``step`` s from start+phase to ``until``, input on since
    ``start`` (one rising edge)."""
    t = start + _s(phase)
    while t <= until:
        _tick(r, t, **{eid: ("on", start)})
        t += _s(step)
    return t - _s(step)


# --- class gate -------------------------------------------------------------

def test_p22_class_gate_values(monkeypatch):
    r = _room(monkeypatch)
    assert r._p22_off_gap_tolerance_s(ZV) == 10.0
    assert r._p22_off_gap_tolerance_s(PIR) == 10.0
    assert r._p22_off_gap_tolerance_s(RADAR) == 0.0      # presence list
    assert r._p22_off_gap_tolerance_s(MS_BIT) == 0.0     # radar family (S3b)
    assert r._p22_off_gap_tolerance_s(BED) == 0.0        # bed override
    assert r._p22_off_gap_tolerance_s(CAMP) == 0.0       # camera override
    assert r._p22_off_gap_tolerance_s(ESP) == 0.0        # unknown family


def test_p22_override_pir_on_radar_family_stays_zero(monkeypatch):
    """Override wins both ways for the still-holder test, but a radar device
    family is not a motion-class family: tolerance stays 0."""
    r = _room(monkeypatch, caps={MS_BIT: {"kind": "pir"}})
    assert r._p22_off_gap_tolerance_s(MS_BIT) == 0.0


def test_p22_knob_zero_disables_everywhere(monkeypatch):
    r = _room(monkeypatch, tol=0)
    assert r._p22_off_gap_tolerance_s(ZV) == 0.0


# --- run bookkeeping --------------------------------------------------------

def test_p22_new_run_stamped_at_last_changed(monkeypatch):
    """Motion class: the run starts at the rising edge's last_changed, not
    at the tick that first saw it (poll phase does not move the clock)."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(27), **{ZV: ("on", T0)})
    assert r._sensor_on_since[ZV] == T0


def test_p22_short_off_pulse_keeps_run(monkeypatch):
    """Upguest 13:51:48: a 1.8 s off seen by a tick does not re-arm."""
    r = _room(monkeypatch)
    last = _run_on(r, ZV, T0, T0 + timedelta(hours=5))
    off_at = last + _s(10)
    _tick(r, off_at + _s(1), **{ZV: ("off", off_at)})
    assert r._sensor_on_since[ZV] == T0
    _tick(r, off_at + _s(31), **{ZV: ("on", off_at + _s(1.8))})
    assert r._sensor_on_since[ZV] == T0
    assert ZV in r._p22_stuck_sensor_set(off_at + _s(31))


@pytest.mark.parametrize("gap,keeps", [(9, True), (10, False), (11, False)])
def test_p22_off_gap_boundary(monkeypatch, gap, keeps):
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    off_at = T0 + _s(100)
    _tick(r, off_at + _s(gap - 0.5), **{ZV: ("off", off_at)})  # still under
    back = off_at + _s(gap)
    _tick(r, back + _s(5), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == (T0 if keeps else back)


def test_p22_long_off_resets_run(monkeypatch):
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    off_at = T0 + _s(100)
    _tick(r, off_at + _s(30), **{ZV: ("off", off_at)})
    assert ZV not in r._sensor_on_since          # popped while off (30 >= 10)
    back = off_at + _s(45)
    _tick(r, back + _s(15), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == back


def test_p22_off_pops_at_tolerance_while_still_off(monkeypatch):
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    off_at = T0 + _s(100)
    _tick(r, off_at + _s(9), **{ZV: ("off", off_at)})
    assert r._sensor_on_since.get(ZV) == T0
    _tick(r, off_at + _s(10), **{ZV: ("off", off_at)})
    assert ZV not in r._sensor_on_since


def test_p22_two_polls_in_different_short_gaps_keeps_run(monkeypatch):
    """Two ticks inside two DIFFERENT short gaps (an unseen on between) must
    not add up: the off start is the CURRENT off's last_changed."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    t1 = T0 + _s(1000)
    _tick(r, t1, **{ZV: ("off", t1 - _s(3))})         # gap A, 3 s old
    _tick(r, t1 + _s(30), **{ZV: ("off", t1 + _s(27))})  # gap B, 3 s old
    assert r._sensor_on_since[ZV] == T0


def test_p22_subtick_off_bounded_by_last_on_tick(monkeypatch):
    """An off no tick saw: bounded by on.last_changed - last on-tick."""
    r = _room(monkeypatch)
    t1 = T0 + _s(600)
    _tick(r, t1, **{ZV: ("on", T0)})
    # off 12:00:01-12:00:04 then on again: bound = 4 s < 10 -> keep.
    _tick(r, t1 + _s(30), **{ZV: ("on", t1 + _s(4))})
    assert r._sensor_on_since[ZV] == T0
    # next: on edge 20 s after the last on-tick -> bound 20 >= 10 -> restart
    # at that edge's last_changed (not at the tick).
    t2 = t1 + _s(30)
    _tick(r, t2 + _s(30), **{ZV: ("on", t2 + _s(20))})
    assert r._sensor_on_since[ZV] == t2 + _s(20)


def test_p22_unavailable_short_is_a_pulse(monkeypatch):
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    dead = T0 + _s(500)
    _tick(r, dead + _s(4), **{ZV: ("unavailable", dead)})
    back = dead + _s(6)
    _tick(r, back + _s(20), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == T0


def test_p22_unavailable_long_restarts_run(monkeypatch):
    """A sensor dead for hours that returns on is never excluded at once."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    dead = T0 + _s(500)
    t = dead + _s(30)
    while t < dead + timedelta(hours=4, minutes=1):
        _tick(r, t, **{ZV: ("unavailable", dead)})
        t += _s(30)
    assert ZV not in r._sensor_on_since
    back = dead + timedelta(hours=4, minutes=2)
    _tick(r, back + _s(10), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == back
    assert ZV not in r._p22_stuck_sensor_set(back + _s(10))


def test_p22_missing_state_counts_from_first_missing_tick(monkeypatch):
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    del r.states[ZV]
    t = T0 + _s(100)
    r._p22_stamp_tick(t, ([ZV],))
    assert r._sensor_on_since.get(ZV) == T0
    r._p22_stamp_tick(t + _s(9), ([ZV],))
    assert r._sensor_on_since.get(ZV) == T0
    r._p22_stamp_tick(t + _s(10), ([ZV],))
    assert ZV not in r._sensor_on_since


@pytest.mark.parametrize("phase", [0, 7, 29])
def test_p22_excluded_at_run_start_plus_four_hours_any_phase(monkeypatch, phase):
    """INV-S1 with blips: exclusion lands at T0 + 4 h (literal), whatever the
    poll phase, and stays across sub-tolerance blips."""
    r = _room(monkeypatch)
    t = T0 + _s(phase)
    lc = T0
    excluded_at = None
    while t <= T0 + timedelta(hours=4, minutes=1):
        # a 2 s blip every 17 min, seen by the tick when it lands inside
        minute = int((t - T0).total_seconds())
        if minute % 1020 < 30 and minute > 30:
            _tick(r, t, **{ZV: ("off", t - _s(1))})
            lc = t + _s(1)
        else:
            _tick(r, t, **{ZV: ("on", lc)})
        if excluded_at is None and ZV in r._p22_stuck_sensor_set(t):
            excluded_at = t
        t += _s(30)
    assert r._sensor_on_since[ZV] == T0
    assert ZV not in r._p22_stuck_sensor_set(T0 + timedelta(hours=3, minutes=59, seconds=59))
    assert ZV in r._p22_stuck_sensor_set(T0 + timedelta(hours=4))
    assert excluded_at is not None
    assert T0 + timedelta(hours=4) <= excluded_at < T0 + timedelta(hours=4, seconds=30)


def test_p22_restart_with_open_gap(monkeypatch):
    """Restored run (Store), RAM gap state lost, input off at boot: the
    first tick pops it once the off has lasted the tolerance."""
    r = _room(monkeypatch)
    r._sensor_on_since[ZV] = T0                 # restored from Store
    boot = T0 + timedelta(hours=2)
    _tick(r, boot + _s(40), **{ZV: ("off", boot)})
    assert ZV not in r._sensor_on_since


def test_p22_restart_with_input_on_keeps_restored_run(monkeypatch):
    r = _room(monkeypatch)
    r._sensor_on_since[ZV] = T0
    boot = T0 + timedelta(hours=2)
    _tick(r, boot + _s(40), **{ZV: ("on", boot)})   # restore stamps lc=boot
    assert r._sensor_on_since[ZV] == T0
    assert ZV in r._post_restart_seen_on


# --- still holders / unknown / tolerance 0 = develop -----------------------

def _develop_reference(ticks):
    """Independent re-statement of the pre-S1 rule (develop c67b8a78):
    on -> setdefault(now); not on -> pop."""
    since = {}
    for now, eid, state in ticks:
        if state == "on":
            since.setdefault(eid, now)
        else:
            since.pop(eid, None)
    return since


def _upguest_sequence(eid):
    """The 11-15 upguest shape: on from 08:51:52, a tick at 13:51:48 sees a
    1.8 s off, ticks every 30 s."""
    blip = datetime(2026, 11, 15, 13, 51, 47, tzinfo=UTC)
    out = []
    t = T0 + _s(11)
    while t <= datetime(2026, 11, 15, 14, 30, tzinfo=UTC):
        if blip <= t < blip + _s(1.8):
            out.append((t, eid, "off", blip))
        else:
            lc = T0 if t < blip else blip + _s(1.8)
            out.append((t, eid, "on", lc))
        t += _s(30)
    # force the 13:51:48 tick inside the blip
    out.append((blip + _s(1), eid, "off", blip))
    out.sort(key=lambda x: x[0])
    return out


@pytest.mark.parametrize("eid", [RADAR, MS_BIT, BED, CAMP, ESP])
def test_p22_still_holder_and_unknown_are_develop(monkeypatch, eid):
    r = _room(monkeypatch)
    seq = _upguest_sequence(eid)
    for now, e, state, lc in seq:
        _tick(r, now, **{e: (state, lc)})
    assert r._sensor_on_since == _develop_reference(
        [(n, e, s) for n, e, s, _lc in seq]
    )


def test_p22_still_holder_no_tolerance(monkeypatch):
    """Radar, bed and camera_presence: a 2 s off pops the run (develop)."""
    for eid in (RADAR, BED, CAMP):
        r = _room(monkeypatch)
        _tick(r, T0 + _s(5), **{eid: ("on", T0)})
        _tick(r, T0 + _s(35), **{eid: ("off", T0 + _s(34))})
        assert eid not in r._sensor_on_since, eid


def test_p22_unknown_family_no_tolerance(monkeypatch):
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ESP: ("on", T0)})
    assert r._sensor_on_since[ESP] == T0 + _s(5)     # develop: tick time
    _tick(r, T0 + _s(35), **{ESP: ("off", T0 + _s(34))})
    assert ESP not in r._sensor_on_since


def test_p22_tolerance_zero_is_develop(monkeypatch):
    """Golden over the 11-15 upguest sequence with the knob at 0: the ZV
    behaves exactly as develop (re-armed after the 13:51 blip)."""
    r = _room(monkeypatch, tol=0)
    seq = _upguest_sequence(ZV)
    for now, e, state, lc in seq:
        _tick(r, now, **{e: (state, lc)})
    ref = _develop_reference([(n, e, s) for n, e, s, _lc in seq])
    assert r._sensor_on_since == ref
    assert ref[ZV] > datetime(2026, 11, 15, 13, 51, 47, tzinfo=UTC)


def test_p22_upguest_with_tolerance_never_rearms(monkeypatch):
    """Same sequence, knob 10 s: the run stays at 08:51:52 (the goal)."""
    r = _room(monkeypatch)
    for now, e, state, lc in _upguest_sequence(ZV):
        _tick(r, now, **{e: (state, lc)})
    assert r._sensor_on_since[ZV] == T0


def test_p22_two_rooms_listing_one_sensor_agree(monkeypatch):
    """Each room keeps its own run; both see the same edges -> same run."""
    a, b = _room(monkeypatch), _room(monkeypatch)
    b.states = a.states
    b.hass = a.hass
    for now, e, state, lc in _upguest_sequence(ZV):
        a.states[e] = _St(state, lc)
        a._p22_stamp_tick(now, ([ZV],))
        b._p22_stamp_tick(now, ([ZV],))
    assert a._sensor_on_since[ZV] == b._sensor_on_since[ZV] == T0


# --- enclosing-method anchor ------------------------------------------------

_STAMP_SLICE = occ._slice(
    "        # === Fix #9: Stuck sensor detection (before detection + trigger tracking) ===",
    "        # STUCK-SENSOR-1 D3 — persist (dirty-gated + 60s delayed-save).",
)


def test_update_tick_slice_runs_the_stamp(monkeypatch):
    """The production slice of ``_async_update_data`` that holds the call:
    neutering the call leaves the run unstamped."""
    r = _room(monkeypatch)
    r.states[ZV] = _St("on", T0)
    ns = dict(vars(CO))
    ns.update(self=r, now=T0 + _s(12), motion_sensors=[ZV],
              mmwave_sensors=[RADAR], occupancy_sensors=[])
    exec(_STAMP_SLICE, ns)
    assert r._sensor_on_since[ZV] == T0


def test_init_reads_hours_knob(monkeypatch):
    """The REAL ``__init__`` takes ``_stuck_sensor_hours`` from the rung-1
    knob STUCK_P22_HOURS (a distinct value proves it is not a literal) and
    seeds the RAM gap maps empty."""
    import homeassistant.helpers.frame as _frame
    from unittest.mock import MagicMock, patch

    monkeypatch.setattr(CONST, "STUCK_P22_HOURS", 2.5)
    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.data = {"room_name": "R", "room_type": "bedroom"}
    entry.options = {}
    entry.entry_id = "E1"
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        c = CO.UniversalRoomCoordinator(hass, entry)
    assert c._stuck_sensor_hours == 2.5
    assert c._p22_off_since == {} and c._p22_last_on_tick == {} and c._p22_on_lc == {}
    assert c._p22_off_state == {}


def test_shipped_knob_values():
    assert CONST.STUCK_P22_HOURS == 4.0
    assert CONST.STUCK_P22_OFF_GAP_TOLERANCE_S == 10.0


def test_is_still_holder_pure():
    """The NEW predicate (S5 will read it too): radar family, mmwave kind,
    bed / camera / BLE kinds hold a still person; ZV / PIR motion do not;
    an override decides both ways."""
    cap = SC.SensorCapability
    motion = cap(kind="motion", trust_class="witness", failure_mode="unknown",
                 source="conf_list")
    mmwave = cap(kind="mmwave", trust_class="weak_witness",
                 failure_mode="unknown", source="conf_list")
    bed_ovr = cap(kind="bed", trust_class="strong_evidence",
                  failure_mode="physical_independent", source="override")
    pir_ovr = cap(kind="pir", trust_class="witness", failure_mode="unknown",
                  source="override")
    assert SC.is_still_holder(motion, "generic_radar") is True   # MS600 bit
    assert SC.is_still_holder(motion, "zigbee_zv") is False
    assert SC.is_still_holder(motion, "pir") is False
    assert SC.is_still_holder(mmwave, "unknown") is True
    assert SC.is_still_holder(bed_ovr, "pir") is True
    assert SC.is_still_holder(pir_ovr, "generic_radar") is False  # override wins
    assert SC.is_p22_motion_class(motion, "zigbee_zv") is True
    assert SC.is_p22_motion_class(motion, "unknown") is False
    assert SC.is_p22_motion_class(None, "zigbee_zv") is False
    # review C d12: BLE kind (list kind and override) holds a still person.
    ble = cap(kind="ble_presence", trust_class="witness",
              failure_mode="correlated_wireless", source="conf_list")
    ble_ovr = cap(kind="ble_presence", trust_class="witness",
                  failure_mode="correlated_wireless", source="override")
    assert SC.is_still_holder(ble, "zigbee_zv") is True
    assert SC.is_still_holder(ble_ovr, "pir") is True


# --- fix pass: one not-on stretch (review A-1 / B-2, replay 14:20) ---------

CDT = timezone(timedelta(hours=-6))


def test_p22_replay_unavailable_then_unknown_is_one_stretch(monkeypatch):
    """Step-0 replay fixture (AUDIT_stuck_s1_step0_replay_2026_11_15, upguest
    ZV 11-15 CDT): on from 07:28:19, then unavailable 14:20:04 (6.1 s),
    unknown 14:20:10.1 (6.6 s), on 14:20:16.7. The dead stretch is 12.7 s
    >= 10 s, so the run restarts at the new edge (the build read 6.6 s)."""
    r = _room(monkeypatch)
    start = datetime(2026, 11, 15, 7, 28, 19, tzinfo=CDT)
    _tick(r, start + _s(20), **{ZV: ("on", start)})
    dead = datetime(2026, 11, 15, 14, 20, 4, tzinfo=CDT)
    _tick(r, dead + _s(1), **{ZV: ("unavailable", dead)})
    _tick(r, dead + _s(7), **{ZV: ("unknown", dead + _s(6.1))})
    assert r._sensor_on_since[ZV] == start            # 7 s < 10
    back = dead + _s(12.7)
    _tick(r, back + _s(1), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == back


def test_p22_off_then_unavailable_pops_at_total(monkeypatch):
    """off 8 s then unavailable 8 s: one 16 s stretch -> popped while dead,
    and the next on starts a new run."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    off_at = T0 + _s(100)
    _tick(r, off_at + _s(1), **{ZV: ("off", off_at)})
    _tick(r, off_at + _s(9), **{ZV: ("unavailable", off_at + _s(8))})
    assert r._sensor_on_since[ZV] == T0               # 9 s
    _tick(r, off_at + _s(15), **{ZV: ("unavailable", off_at + _s(8))})
    assert ZV not in r._sensor_on_since               # 15 s >= 10
    back = off_at + _s(16)
    _tick(r, back + _s(1), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == back


def test_p22_off_then_unavailable_then_on_restarts(monkeypatch):
    """off 8 s + unavailable 8 s, on seen before any tick crossed 10 s: the
    gap is measured from the off (16 s), not from the unavailable (8 s)."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    off_at = T0 + _s(100)
    _tick(r, off_at + _s(1), **{ZV: ("off", off_at)})
    _tick(r, off_at + _s(9), **{ZV: ("unavailable", off_at + _s(8))})
    back = off_at + _s(16)
    _tick(r, back + _s(0.5), **{ZV: ("on", back)})
    assert r._sensor_on_since[ZV] == back


def test_p22_flip_flop_off_unavailable_pops_at_total(monkeypatch):
    """off / unavailable alternating every 3 s, each seen: kept below 10 s
    total, popped once the total reaches 10 s."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    t = T0 + _s(100)
    for i, st in enumerate(["off", "unavailable", "off"]):
        _tick(r, t + _s(3 * i + 1), **{ZV: (st, t + _s(3 * i))})
        assert r._sensor_on_since.get(ZV) == T0, i    # 1 s, 4 s, 7 s
    _tick(r, t + _s(10), **{ZV: ("unavailable", t + _s(9))})   # 10 s
    assert ZV not in r._sensor_on_since


def test_p22_dead_seen_twice_with_new_lc_is_one_stretch(monkeypatch):
    """unavailable -> (unseen) -> unavailable with a new last_changed: an
    `on` is not guessed into a dead stretch; it stays one stretch."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    d = T0 + _s(100)
    _tick(r, d + _s(1), **{ZV: ("unavailable", d)})
    _tick(r, d + _s(11), **{ZV: ("unavailable", d + _s(8))})
    assert ZV not in r._sensor_on_since


def test_p22_off_unseen_dead_off_is_the_two_polls_residual(monkeypatch):
    """The conflict, pinned: off -> unavailable (no tick saw it) -> off reads
    exactly like two_polls (off -> unseen on -> off). Nothing observed the
    dead stretch, so the plan's two_polls rule (a re-read off with a new
    last_changed starts a new stretch) decides and the run is kept."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    o = T0 + _s(100)
    _tick(r, o + _s(1), **{ZV: ("off", o)})
    _tick(r, o + _s(13), **{ZV: ("off", o + _s(12))})
    assert r._sensor_on_since[ZV] == T0


# --- review C MEDIUM / LOW gaps --------------------------------------------

ZV2 = "binary_sensor.upguest_zv_second_presence_2"


def _entry_options_room(monkeypatch, *, data_lists, opt_lists, data_caps=None,
                        opt_caps=None):
    models = dict(MODELS)
    models[ZV2] = ("ZG-204ZV", "Millimeter wave motion detection")
    occ._install_registry(monkeypatch, models)
    r = _room(monkeypatch, motion=(), presence=(), caps={})
    occ._install_registry(monkeypatch, models)
    data = {CONST.CONF_ENTRY_TYPE: CONST.ENTRY_TYPE_ROOM, "room_name": "R",
            CONST.CONF_ROOM_NAME: "R", CONST.CONF_MOTION_SENSORS: list(data_lists)}
    if data_caps:
        data[CONST.CONF_SENSOR_CAPABILITIES] = dict(data_caps)
    opts = {CONST.CONF_MOTION_SENSORS: list(opt_lists)} if opt_lists else {}
    if opt_caps:
        opts[CONST.CONF_SENSOR_CAPABILITIES] = dict(opt_caps)
    r.entry = occ._Entry("entry_R", data, opts)
    return r


def test_p22_lists_only_in_entry_options(monkeypatch):
    """Review C c9: a room edited in the options flow keeps its lists in
    entry.options; S1 must see them."""
    r = _entry_options_room(monkeypatch, data_lists=(), opt_lists=(ZV,))
    assert r._p22_off_gap_tolerance_s(ZV) == 10.0


def test_p22_override_only_in_entry_options(monkeypatch):
    """Review C c9: a CONF_SENSOR_CAPABILITIES override stored only in
    entry.options (mmwave on a ZV device = still holder) wins."""
    r = _entry_options_room(monkeypatch, data_lists=(ZV, ZV2), opt_lists=(),
                            opt_caps={ZV2: {"kind": "mmwave"}})
    assert r._p22_off_gap_tolerance_s(ZV) == 10.0
    assert r._p22_off_gap_tolerance_s(ZV2) == 0.0


def test_p22_family_lookup_error_is_zero(monkeypatch):
    """Review C c10: any error resolving the family -> the pre-S1 rule."""
    r = _room(monkeypatch)

    def _boom(hass, eid):
        raise RuntimeError("registry gone")

    monkeypatch.setattr(occ.FV, "resolve_sensor_family", _boom)
    assert r._p22_off_gap_tolerance_s(ZV) == 0.0


@pytest.mark.parametrize("which,eid,stamp", [
    ("motion_sensors", ZV, "lc"),
    ("mmwave_sensors", RADAR, "now"),
    ("occupancy_sensors", ESP, "now"),
])
def test_update_tick_slice_stamps_each_list(monkeypatch, which, eid, stamp):
    """Review C e2/e3: the production slice passes every list to the stamp;
    an input only in that list gets its run."""
    r = _room(monkeypatch)
    r.states[eid] = _St("on", T0)
    now = T0 + _s(12)
    lists = {"motion_sensors": [], "mmwave_sensors": [], "occupancy_sensors": []}
    lists[which] = [eid]
    ns = dict(vars(CO))
    ns.update(self=r, now=now, **lists)
    exec(_STAMP_SLICE, ns)
    assert r._sensor_on_since[eid] == (T0 if stamp == "lc" else now)


@pytest.mark.parametrize("eid", [RADAR, ESP])
def test_p22_restored_run_tol0_needs_live_on(monkeypatch, eid):
    """Review C e7 (STUCK-SENSOR-1 D3 MED-1): a restored run of a still
    holder / unknown family gains no exclusion until a live on is seen."""
    r = _room(monkeypatch)
    r._sensor_on_since[eid] = T0                      # restored, > 4 h old
    late = T0 + timedelta(hours=6)
    assert eid not in r._p22_stuck_sensor_set(late)
    _tick(r, late, **{eid: ("on", T0)})
    assert eid in r._post_restart_seen_on
    assert eid in r._p22_stuck_sensor_set(late)


def test_p22_class_flip_to_zero_clears_gap_state(monkeypatch):
    """Review C e9/e10: a motion-class input flips to tolerance 0 mid-run
    (override / knob change): the tol-0 tick clears the S1 maps."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    _tick(r, T0 + _s(100), **{ZV: ("off", T0 + _s(99))})
    assert r._p22_off_since and r._p22_off_state and r._p22_last_on_tick
    monkeypatch.setattr(CONST, "STUCK_P22_OFF_GAP_TOLERANCE_S", 0)
    _tick(r, T0 + _s(130), **{ZV: ("on", T0 + _s(101))})
    assert r._p22_off_since == {} and r._p22_off_state == {}
    assert r._p22_last_on_tick == {} and r._p22_on_lc == {}


def test_p22_seen_short_off_then_unseen_short_off_keeps_run(monkeypatch):
    """Review C e13: the off start is consumed by the on that closes it; a
    later unseen short off is bounded by the last on-tick, not by the stale
    earlier off."""
    r = _room(monkeypatch)
    _tick(r, T0 + _s(5), **{ZV: ("on", T0)})
    o = T0 + _s(100)
    _tick(r, o + _s(1), **{ZV: ("off", o)})
    _tick(r, o + _s(3), **{ZV: ("on", o + _s(2))})
    _tick(r, o + _s(33), **{ZV: ("on", o + _s(2))})
    _tick(r, o + _s(63), **{ZV: ("on", o + _s(40))})   # 40 - 33 = 7 s
    assert r._sensor_on_since[ZV] == T0


@pytest.mark.parametrize("bound,keeps", [(9, True), (10, False), (11, False)])
def test_p22_unseen_off_boundary(monkeypatch, bound, keeps):
    """Review C e19: the unseen-off bound at 9 / 10 / 11 s (literals)."""
    r = _room(monkeypatch)
    t1 = T0 + _s(600)
    _tick(r, t1, **{ZV: ("on", T0)})
    edge = t1 + _s(bound)
    _tick(r, edge + _s(5), **{ZV: ("on", edge)})
    assert r._sensor_on_since[ZV] == (T0 if keeps else edge)
