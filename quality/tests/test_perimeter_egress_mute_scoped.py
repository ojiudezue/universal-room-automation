"""PERIMETER-GLOBAL-EGRESS-MUTE-1 — the scoped egress mute (D1, D3, D4).

Plan: docs/planning/PLANNING_perimeter_egress_mute_scoped.md (decision A:
alert now, name it afterwards; no hold anywhere).

Harness: the shared perimeter stubs (test_perimeter_fp_gates /
test_perimeter_alert_nm_routing). Every test drives the REAL entry points:
`async_setup` (wiring + listener registration), the captured
`ura_person_egress_event` listener, the captured egress state listener, and
`_async_handle_perimeter_trigger` (the method that CONTAINS the mute call).
Expected outcomes are written by hand from the plan's INV-MUTE-KNOWN (a)-(d)
and INV-MUTE-FAILOPEN; boundary values are literals, never the imported knob.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from test_perimeter_fp_gates import (  # noqa: E402
    DB_CAM,
    DB_PR,
    FS_CAM,
    FS_PR,
    GA_CAM,
    GA_PR,
    _Census,
    _St,
    _build,
    _const,
    _edge,
    _perimeter,
    _setup,
)
from custom_components.universal_room_automation import (  # noqa: E402
    exterior_track_linker as _etl,
)

G5_CAM = "camera.g5_bullet"
G5_PR = "binary_sensor.g5_bullet_person_detected"
GA_F2 = "binary_sensor.garage_a_person_occupancy_2"
GA_COUNT = "sensor.garage_a_person_count"
MG_CAM = "camera.madrone_g6_entry"
MG_PR = "binary_sensor.madrone_g6_entry_person_detected"

LEGS = {
    G5_CAM: [(G5_PR, "protect")],
    FS_CAM: [(FS_PR, "protect")],
    GA_CAM: [(GA_PR, "protect"), (GA_F2, "frigate2")],
    MG_CAM: [(MG_PR, "protect")],
    DB_CAM: [(DB_PR, "protect")],
}
COVERS = {
    "garage_a": ("doorbell_lite", "g5_bullet", "rear_ptz"),
    "madrone_g6_entry": ("front_side_ptz", "sonoffwindow", "utilities_ptz"),
}
T0 = datetime(2026, 11, 13, 14, 0, 0, tzinfo=_perimeter.dt_util.now().tzinfo)


class _Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t = self.t + timedelta(seconds=s)


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(_perimeter.dt_util, "now", c)
    monkeypatch.setattr(_perimeter.dt_util, "utcnow", c)
    monkeypatch.setattr(_perimeter.dt_util, "parse_datetime",
                        datetime.fromisoformat, raising=False)
    return c


def _rig(monkeypatch, covers=COVERS, census=True, linker=True):
    hass, nm = _build(
        perimeter=(G5_CAM, FS_CAM), egress=(GA_CAM, MG_CAM, DB_CAM), legs=LEGS,
    )
    cam_mgr = hass.data[_const.DOMAIN]["camera_manager"]
    real_resolve = cam_mgr.resolve_camera_entity

    def _resolve(cam_id):
        infos = real_resolve(cam_id)
        if cam_id == GA_CAM:
            infos[0].person_count_sensor = GA_COUNT
        return infos
    cam_mgr.resolve_camera_entity = _resolve
    if census:
        hass.data[_const.DOMAIN]["census"] = _Census()
    mgr, subs = _setup(hass, monkeypatch)
    if linker:
        lk = _etl.ExteriorTrackLinker(hass)
        lk.egress_mute_covers = dict(covers) if covers is not None else {}
        hass.data[_const.DOMAIN]["exterior_track_linker"] = lk
    mgr._subs = subs
    return hass, nm, mgr


def _xcb(hass):
    cbs = [c.args[1] for c in hass.bus.async_listen.call_args_list
           if c.args[0] == "ura_person_egress_event"]
    assert cbs, "egress identity listener not registered"
    return cbs[0]


def _cross(hass, clock, door=GA_PR, ago_s=10, pid="oji_udezue", conf=0.95,
           direction="exit", synthetic=False):
    _xcb(hass)(SimpleNamespace(data={
        "egress_camera": door,
        "timestamp": (clock() - timedelta(seconds=ago_s)).isoformat(),
        "person_id": pid,
        "identity_confidence": conf,
        "direction": direction,
        "identity_synthetic_corroborated": synthetic,
    }))


def _stamp(mgr, sensor=GA_PR):
    for ents, cb in mgr._subs:
        if sensor in ents and cb.__name__ == "_on_egress_state_change":
            cb(_edge(sensor))
            return
    raise AssertionError("no egress state listener")


def _alert(mgr, eid=G5_PR):
    """Drive the real handler; return how many alerts were dispatched."""
    nm = mgr.hass.data[_const.DOMAIN]["notification_manager"]
    before = nm.async_notify.await_count
    mgr._last_alert.clear()  # cooldown is not under test here
    asyncio.run(mgr._async_handle_perimeter_trigger(eid))
    return nm.async_notify.await_count - before


def _row(mgr, key="g5_bullet"):
    return mgr._last_gate_decisions.get(key, {}).get("egress_mute")


# =========================================================================
# D1 — door identity memory
# =========================================================================

def test_egress_listener_registers_without_dual_role(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    assert mgr._dual_role_cameras == set()
    assert mgr._unsub_egress_identity is not None
    _xcb(hass)  # registered


def test_egress_memory_keys_all_legs_to_one_door(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    for i, leg in enumerate((GA_PR, GA_F2, GA_COUNT, GA_CAM)):
        _cross(hass, clock, door=leg, ago_s=40 - i)
    assert list(mgr._recent_egress_identity) == ["garage_a"]
    assert len(mgr._recent_egress_identity["garage_a"]) == 4


def test_egress_memory_count_sensor_without_map_is_not_garage_a(monkeypatch, clock):
    """Discriminator for the map: the stem fallback alone would key the
    count sensor under its raw entity id, not the door."""
    hass, _nm, mgr = _rig(monkeypatch)
    mgr._egress_door_key_by_entity.pop(GA_COUNT)
    _cross(hass, clock, door=GA_COUNT)
    assert "garage_a" not in mgr._recent_egress_identity


def test_egress_memory_stores_unknown_crossing(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, pid=None, conf=None, direction="entry")
    (entry,) = mgr._recent_egress_identity["garage_a"]
    assert entry[1:] == ("", 0.0, False, "entry")


def test_d10_5_ignores_unknown_entries(monkeypatch, clock):
    """D10.5 golden: `_known_identity_for` returns the same value with and
    without unknown crossings interleaved."""
    hass, _nm, mgr = _rig(monkeypatch)
    edge = clock()
    mgr._recent_egress_identity["garage_a"] = [
        (edge - timedelta(seconds=3), "oji_udezue", 0.92, False, "exit"),
    ]
    golden = ("oji_udezue", 0.92, "egress_event")
    assert mgr._known_identity_for("garage_a", edge) == golden
    mgr._recent_egress_identity["garage_a"] = [
        (edge - timedelta(seconds=4), "", 0.0, False, "exit"),
        (edge - timedelta(seconds=3), "oji_udezue", 0.92, False, "exit"),
        (edge - timedelta(seconds=2), "", 0.0, False, "entry"),
    ]
    assert mgr._known_identity_for("garage_a", edge) == golden
    mgr._recent_egress_identity["garage_a"] = [
        (edge - timedelta(seconds=2), "", 0.0, False, "entry"),
    ]
    assert mgr._known_identity_for("garage_a", edge) is None


# =========================================================================
# D3 — the scoped mute (INV-MUTE-KNOWN)
# =========================================================================

def test_mute_known_resident_covered_camera(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=60)
    assert _alert(mgr) == 0
    r = _row(mgr)
    assert r["reason"] == "egress_mute_known_resident"
    assert r["suppressed"] is True and r["demoted"] is False
    assert r["inputs"]["door"] == "garage_a"
    assert r["inputs"]["person_id"] == "oji_udezue"
    assert r["inputs"]["seconds_since"] == 60.0
    assert mgr._last_suppression["g5_bullet"]["reason"] == "egress_mute"


@pytest.mark.parametrize("ago_s,alerts", [(119, 0), (120, 0), (121, 1)])
def test_mute_window_boundary(monkeypatch, clock, ago_s, alerts):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=ago_s)
    assert _alert(mgr) == alerts


def test_mute_not_covered_alerts(monkeypatch, clock):
    """madrone_g6_entry covers front_side_ptz, NOT g5_bullet."""
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, door=MG_PR)
    assert _alert(mgr, G5_PR) == 1
    assert _row(mgr) is None  # no covering door -> no row
    assert _alert(mgr, FS_PR) == 0  # ...but it does cover front_side_ptz


def test_mute_uncovered_door_mutes_nothing(monkeypatch, clock):
    """doorbell_lite is an egress camera with no egress_mute_covers entry."""
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, door=DB_PR)
    _stamp(mgr, DB_PR)
    assert _alert(mgr, G5_PR) == 1
    assert _alert(mgr, FS_PR) == 1


def test_mute_no_record_alerts_now(monkeypatch, clock):
    """Door on-edge at -1 s, crossing record not landed yet (+45 s): alert
    immediately, decline row `no_record`. Discriminates "the window got
    shorter": the old rule muted this edge."""
    hass, _nm, mgr = _rig(monkeypatch)
    _stamp(mgr, GA_PR)
    clock.advance(1)
    assert _alert(mgr) == 1
    r = _row(mgr)
    assert r["reason"] == "egress_mute_no_record" and r["suppressed"] is False


def test_mute_no_activity_no_row(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    assert _alert(mgr) == 1
    assert _row(mgr) is None


def test_mute_stamp_on_uncovering_door_writes_no_row(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _stamp(mgr, MG_PR)
    assert _alert(mgr, G5_PR) == 1
    assert _row(mgr) is None


def test_mute_vetoed_by_unknown_crossing(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=30)
    _cross(hass, clock, ago_s=20, pid=None, conf=None)
    assert _alert(mgr) == 1
    assert _row(mgr)["reason"] == "egress_mute_vetoed_unknown"


def test_mute_stranger_after_unknown_crossing_alerts(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=30, pid=None, conf=None)
    assert _alert(mgr) == 1
    assert _row(mgr)["reason"] == "egress_mute_vetoed_unknown"


def test_mute_unknown_crossing_outside_window_does_not_veto(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=200, pid=None, conf=None)
    _cross(hass, clock, ago_s=30)
    assert _alert(mgr) == 0


@pytest.mark.parametrize("conf,alerts", [(0.89, 1), (0.9, 0), (0.95, 0)])
def test_mute_below_floor_alerts(monkeypatch, clock, conf, alerts):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, conf=conf)
    assert _alert(mgr) == alerts
    if alerts:
        assert _row(mgr)["reason"] == "egress_mute_below_floor"


def test_mute_synthetic_alerts(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, synthetic=True)
    assert _alert(mgr) == 1
    assert _row(mgr)["reason"] == "egress_mute_synthetic"


@pytest.mark.parametrize("direction,alerts", [
    ("ambiguous", 1), ("", 1), ("entry", 0), ("exit", 0),
])
def test_mute_ambiguous_direction_alerts(monkeypatch, clock, direction, alerts):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, direction=direction)
    assert _alert(mgr) == alerts
    if alerts:
        assert _row(mgr)["reason"] == "egress_mute_ambiguous"


def test_mute_guest_never_mutes(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)

    class _G(_Census):
        def _get_known_face_guests(self):
            return ["auntie_ada"]
    hass.data[_const.DOMAIN]["census"] = _G()
    _cross(hass, clock, pid="auntie_ada", conf=0.99)
    assert _alert(mgr) == 1
    assert _row(mgr)["reason"] == "egress_mute_vetoed_unknown"


def _mute_at(hass, mgr, clock, alerts_expected):
    _cross(hass, clock, ago_s=10)
    assert _alert(mgr) == alerts_expected


def test_mute_episode_cap_no_chaining(monkeypatch, clock):
    """Fresh crossings every 100 s keep a resident 'known', but one episode
    is capped at 300 s: 0/100/200/300 mute, 301 alerts (cap)."""
    hass, _nm, mgr = _rig(monkeypatch)
    for step in (0, 100, 100, 100):
        clock.advance(step)
        _mute_at(hass, mgr, clock, 0)
    clock.advance(1)
    _mute_at(hass, mgr, clock, 1)
    r = _row(mgr)
    assert r["reason"] == "egress_mute_cap" and r["suppressed"] is False
    assert r["inputs"]["episode_age_s"] == 301.0


def test_mute_episode_resets_after_quiet(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    for step in (0, 100, 100, 100):
        clock.advance(step)
        _mute_at(hass, mgr, clock, 0)
    clock.advance(1)
    _mute_at(hass, mgr, clock, 1)          # capped
    clock.advance(120)                     # 121 s since the last mute
    _mute_at(hass, mgr, clock, 0)          # a new episode
    assert _row(mgr)["inputs"]["episode_age_s"] == 0.0


def test_mute_episode_quiet_exactly_reset_does_not_reset(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    for step in (0, 100, 100, 100):
        clock.advance(step)
        _mute_at(hass, mgr, clock, 0)
    clock.advance(1)
    _mute_at(hass, mgr, clock, 1)          # capped, last mute at +300
    clock.advance(119)                     # 120 s since the last mute
    _mute_at(hass, mgr, clock, 1)


def test_mute_dual_role_keeps_inv_egress_self(monkeypatch, clock):
    """A dual-role camera is untouched by the scoped mute: a door stamp from
    an egress-only camera still mutes it (INV-EGRESS-SELF, unchanged)."""
    hass, nm = _build(perimeter=(DB_CAM,), egress=(DB_CAM, GA_CAM), legs=LEGS)
    mgr, subs = _setup(hass, monkeypatch)
    mgr._subs = subs
    lk = _etl.ExteriorTrackLinker(hass)
    lk.egress_mute_covers = dict(COVERS)
    hass.data[_const.DOMAIN]["exterior_track_linker"] = lk
    _stamp(mgr, GA_PR)
    assert _alert(mgr, DB_PR) == 0
    assert mgr._last_suppression["doorbell_lite"]["reason"] == "egress_suppression"
    assert _row(mgr, "doorbell_lite") is None


# =========================================================================
# INV-MUTE-FAILOPEN
# =========================================================================

def test_mute_failopen_no_linker(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch, linker=False)
    _cross(hass, clock)
    assert _alert(mgr) == 1


def test_mute_failopen_absent_covers(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch, covers=None)
    _cross(hass, clock)
    assert _alert(mgr) == 1


def test_mute_failopen_no_census(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch, census=False)
    _cross(hass, clock)
    assert _alert(mgr) == 1


def test_mute_failopen_census_raises(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)

    class _Bad(_Census):
        def _get_tracked_person_slugs(self):
            raise RuntimeError("census down")
    hass.data[_const.DOMAIN]["census"] = _Bad()
    _cross(hass, clock)
    assert _alert(mgr) == 1


def test_mute_failopen_errors(monkeypatch, clock):
    """An internal error inside the decision = alert (never a silent drop)."""
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock)
    mgr._recent_egress_identity["garage_a"].append(("not-a-datetime",))
    assert _alert(mgr) == 1


def test_mute_failopen_covers_not_a_dict(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    hass.data[_const.DOMAIN]["exterior_track_linker"].egress_mute_covers = ["garage_a"]
    _cross(hass, clock)
    assert _alert(mgr) == 1


def test_mute_restart_memory_empty(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock)
    asyncio.run(mgr.async_teardown())
    asyncio.run(mgr.async_setup())
    mgr._setup_time = None
    assert mgr._recent_egress_identity == {} and mgr._mute_episodes == {}
    assert _alert(mgr) == 1


def test_mute_restart_clears_episodes(monkeypatch, clock):
    """An episode aged 290 s before a reload must not carry over: after the
    reload a fresh qualifying crossing opens a NEW episode (age 0)."""
    hass, _nm, mgr = _rig(monkeypatch)
    _mute_at(hass, mgr, clock, 0)
    clock.advance(100)
    _mute_at(hass, mgr, clock, 0)
    clock.advance(100)
    _mute_at(hass, mgr, clock, 0)
    clock.advance(90)
    _mute_at(hass, mgr, clock, 0)          # episode age 290
    asyncio.run(mgr.async_teardown())
    asyncio.run(mgr.async_setup())
    mgr._setup_time = None
    clock.advance(20)                       # 310 s after the old start
    _mute_at(hass, mgr, clock, 0)
    assert _row(mgr)["inputs"]["episode_age_s"] == 0.0


# =========================================================================
# Config extremes (five knobs)
# =========================================================================

def test_knob_window_zero_never_mutes(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_WINDOW_S", 0)
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=0)
    assert _alert(mgr) == 1


def test_knob_cap_below_window(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_MAX_EPISODE_S", 30)
    hass, _nm, mgr = _rig(monkeypatch)
    _mute_at(hass, mgr, clock, 0)
    clock.advance(30)
    _mute_at(hass, mgr, clock, 0)
    clock.advance(1)
    _mute_at(hass, mgr, clock, 1)
    assert _row(mgr)["reason"] == "egress_mute_cap"


def test_knob_cap_zero_never_mutes(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_MAX_EPISODE_S", 0)
    hass, _nm, mgr = _rig(monkeypatch)
    _mute_at(hass, mgr, clock, 1)
    assert _row(mgr)["reason"] == "egress_mute_cap"


def test_mute_min_conf_clamps_to_0_9(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_MIN_IDENTITY_CONF", 0.5)
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, conf=0.89)
    assert _alert(mgr) == 1
    assert _row(mgr)["reason"] == "egress_mute_below_floor"
    assert _row(mgr)["inputs"]["floor"] == 0.9


def test_knob_min_conf_above_one_kills(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_MIN_IDENTITY_CONF", 1.01)
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, conf=1.0)
    assert _alert(mgr) == 1


def test_knob_reset_zero_every_gap_ends_episode(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_EPISODE_RESET_S", 0)
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_MAX_EPISODE_S", 5)
    hass, _nm, mgr = _rig(monkeypatch)
    for _ in range(3):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(6)  # each gap > reset 0 -> fresh episode, cap never hit


# =========================================================================
# D4 trip-wires (driven through the real handler / listener)
# =========================================================================

def _tw_titles(nm):
    return [c.kwargs.get("title") for c in nm.async_notify.await_args_list]


def _with_tasks(hass):
    pending: list = []
    hass.async_create_task = lambda coro, *a, **k: pending.append(coro) or SimpleNamespace(
        add_done_callback=lambda cb: None, done=lambda: True)
    return pending


async def _drain(pending):
    while pending:
        await pending.pop(0)


def test_mute_ratio_tripwire_fires(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(10):  # 10 mutes, 10 rows, ratio 1.0 > 0.5
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == ["Perimeter egress mute is silencing most edges"]


def test_mute_ratio_tripwire_needs_min_rows(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(9):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []


def test_mute_ratio_tripwire_disabled_above_one(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_RATIO_ALARM", 1.01)
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(12):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []


def test_mute_ratio_zero_alarms_on_any_mute_mix(monkeypatch, clock):
    """Ratio 0: 1 mute in 10 rows alarms (any mute > 0)."""
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_RATIO_ALARM", 0.0)
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(9):  # 9 decline rows (unknown crossing vetoes)
        _cross(hass, clock, ago_s=5, pid=None, conf=None)
        _alert(mgr)
        clock.advance(200)
    _mute_at(hass, mgr, clock, 0)
    asyncio.run(_drain(pending))
    assert "Perimeter egress mute is silencing most edges" in _tw_titles(nm)


def test_mute_zero_fire_tripwire_fires(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    for _ in range(5):
        _cross(hass, clock)
        clock.advance(60)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == ["Perimeter egress mute never ran"]


def test_mute_zero_fire_quiet_when_rows_exist_or_boot(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(6):  # uptime < 24 h -> no alarm
        _cross(hass, clock)
        clock.advance(60)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    _alert(mgr)  # one mute row exists in the window
    for _ in range(6):
        _cross(hass, clock)
        clock.advance(60)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []


def test_mute_zero_fire_quiet_without_covers(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch, covers=None)
    pending = _with_tasks(hass)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    for _ in range(6):
        _cross(hass, clock)
        clock.advance(60)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []


def test_mute_counts_by_reason_on_diagnostic(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock)
    _alert(mgr)
    stats = mgr.gate_decision_stats()
    assert stats["egress_mute_counts_by_reason"] == {"egress_mute_known_resident": 1}
    assert stats["egress_mute_covers"]["garage_a"] == ["doorbell_lite", "g5_bullet", "rear_ptz"]


# =========================================================================
# Converted source-grep (was test_exterior_track_linker.py::
# test_perimeter_setup_installs_allowlist_anchor)
# =========================================================================

def test_perimeter_setup_installs_linker_allowlist(monkeypatch, clock):
    """async_setup installs the perimeter + egress camera keys on a linker
    that is already registered (inline install site)."""
    hass, _nm = _build(perimeter=(G5_CAM, FS_CAM), egress=(GA_CAM,), legs=LEGS)
    lk = _etl.ExteriorTrackLinker(hass)
    hass.data[_const.DOMAIN]["exterior_track_linker"] = lk
    _setup(hass, monkeypatch)
    assert lk._allowlist_installed is True
    assert lk._allowed_cameras == {"g5_bullet", "front_side_ptz", "garage_a"}


# =========================================================================
# Tier 2-DB: rows land in a REAL UniversalRoomDatabase (its own DDL)
# =========================================================================

def test_mute_row_suppressed_field_not_demoted(monkeypatch, clock, tmp_path):
    from test_perimeter_gate_log import _real_db, _rows

    hass, _nm, mgr = _rig(monkeypatch)
    hass.async_create_task = lambda coro, *a, **k: asyncio.ensure_future(coro)

    async def _go():
        db = await _real_db(tmp_path)
        hass.data[_const.DOMAIN]["database"] = db
        _cross(hass, clock, ago_s=60)                            # mute
        await mgr._async_handle_perimeter_trigger(G5_PR)
        clock.advance(200)
        _cross(hass, clock, ago_s=5, pid=None, conf=None)        # veto
        mgr._last_alert.clear()
        await mgr._async_handle_perimeter_trigger(G5_PR)
        mgr._record_gate("rear_ptz", {"gate": "vlm", "reason": "x",
                                      "at": clock().isoformat()})
        for _ in range(5):
            await asyncio.sleep(0)
        for t in list(mgr._gate_log_tasks):
            await t
        await db.stop_write_worker()
        return db

    db = asyncio.run(_go())
    rows = _rows(db)
    mute = [a for _n, a, _s in rows if a["gate"] == "egress_mute"]
    assert [(a["reason"], a["suppressed"], a["demoted"]) for a in mute] == [
        ("egress_mute_known_resident", True, False),
        ("egress_mute_vetoed_unknown", False, False),
    ]
    assert mute[0]["camera"] == "g5_bullet"
    assert mute[0]["inputs"]["door"] == "garage_a"
    assert mute[0]["inputs"]["direction"] == "exit"
    assert mute[0]["entity_id"] == G5_PR
    other = [a for _n, a, _s in rows if a["gate"] == "vlm"]
    assert len(other) == 1 and "suppressed" not in other[0]  # other gates unchanged
