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


def _rig(monkeypatch, covers=COVERS, census=True, linker=True, census_obj=None):
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
        hass.data[_const.DOMAIN]["census"] = census_obj or _Census()
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


# =========================================================================
# Fix-up round (reviews A / B / C)
# =========================================================================

def _notified(nm):
    return nm.async_notify.await_count


# ---- A2: late re-alert (operator decision "(a) Re-alert late") ---------

def _realert_scenario(monkeypatch, clock, stranger=True):
    """Oji exits garage_a at t=0 (record lands t=45); a stranger's edge on
    g5_bullet at t=75 is muted; the stranger's own crossing (detected t=60,
    unknown) lands at t=105."""
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    clock.advance(45)
    _cross(hass, clock, ago_s=45)                       # Oji, ts = t0
    clock.advance(30)                                   # t = 75
    assert _alert(mgr) == 0                             # muted
    assert _row(mgr)["reason"] == "egress_mute_known_resident"
    clock.advance(30)                                   # t = 105
    before = _notified(nm)
    if stranger:
        _cross(hass, clock, ago_s=45, pid=None, conf=None, direction="entry")
    asyncio.run(_drain(pending))
    return hass, nm, mgr, pending, _notified(nm) - before


def test_mute_realert_stranger_crossing_lands_late(monkeypatch, clock):
    _h, _nm, mgr, _p, sent = _realert_scenario(monkeypatch, clock)
    assert sent == 1
    r = _row(mgr)
    assert r["reason"] == "egress_mute_realert" and r["suppressed"] is False
    assert r["entity_id"] == G5_PR
    assert r["inputs"]["veto_reason"] == "egress_mute_vetoed_unknown"
    assert r["inputs"]["late_by_s"] == 30.0
    assert mgr._last_alert["g5_bullet"] == clock()        # sent at t = 105


def test_mute_realert_no_stranger_sends_nothing(monkeypatch, clock):
    _h, _nm, mgr, _p, sent = _realert_scenario(monkeypatch, clock, stranger=False)
    assert sent == 0
    assert _row(mgr)["reason"] == "egress_mute_known_resident"


def test_mute_realert_never_for_qualifying_crossing(monkeypatch, clock):
    hass, nm, mgr, pending, _s = _realert_scenario(
        monkeypatch, clock, stranger=False)
    before = _notified(nm)
    _cross(hass, clock, ago_s=45, pid="jaya_udezue", conf=0.97)  # qualifies
    asyncio.run(_drain(pending))
    assert _notified(nm) - before == 0
    assert _row(mgr)["reason"] == "egress_mute_known_resident"


def test_mute_realert_once_per_muted_edge(monkeypatch, clock):
    hass, nm, mgr, pending, sent = _realert_scenario(monkeypatch, clock)
    assert sent == 1
    mgr._last_alert.clear()   # a second send would not be cooled down
    before = _notified(nm)
    _cross(hass, clock, ago_s=40, pid=None, conf=None, direction="exit")
    asyncio.run(_drain(pending))
    assert _notified(nm) - before == 0


@pytest.mark.parametrize("ago_s,sent", [
    (29, 0),    # detected AFTER the muted edge (t=76): it was never vetoable
    (30, 1),    # detected at the edge (lag 0)
    (150, 1),   # lag 120 (window, inclusive)
    (151, 0),   # lag 121: outside the window
])
def test_mute_realert_window_boundary(monkeypatch, clock, ago_s, sent):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    clock.advance(200)
    _cross(hass, clock, ago_s=10)                       # Oji, fresh
    assert _alert(mgr) == 0                             # muted at t=200
    mgr._recent_egress_identity.clear()                 # isolate the late record
    clock.advance(30)
    before = _notified(nm)
    _cross(hass, clock, ago_s=ago_s, pid=None, conf=None, direction="entry")
    asyncio.run(_drain(pending))
    assert _notified(nm) - before == sent


def test_mute_realert_only_from_a_covering_door(monkeypatch, clock):
    """madrone_g6_entry does not cover g5_bullet: its unknown crossing
    would not have vetoed the g5_bullet mute, so it re-sends nothing."""
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    _cross(hass, clock, ago_s=10)
    assert _alert(mgr) == 0
    clock.advance(20)
    before = _notified(nm)
    _cross(hass, clock, door=MG_PR, ago_s=25, pid=None, conf=None)
    asyncio.run(_drain(pending))
    assert _notified(nm) - before == 0


def test_mute_realert_cooldown_applies(monkeypatch, clock):
    """The late send runs the normal handler, so a camera that alerted
    inside the cooldown folds it (recorded as a cooldown suppression)."""
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    _cross(hass, clock, ago_s=10)
    assert _alert(mgr) == 0
    clock.advance(20)
    mgr._last_alert["g5_bullet"] = clock() - timedelta(seconds=10)
    before = _notified(nm)
    _cross(hass, clock, ago_s=25, pid=None, conf=None)
    asyncio.run(_drain(pending))
    assert _notified(nm) - before == 0
    assert _row(mgr)["reason"] == "egress_mute_realert"
    assert mgr._last_suppression["g5_bullet"]["reason"] == "cooldown"


def test_mute_realert_skips_mute_step(monkeypatch, clock):
    """The late send must not be muted again by the qualifying crossing
    still in memory (it is in the window, so a full re-decision would see
    the veto only if the late record is also in memory; the flag makes the
    send independent of that)."""
    hass, nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=10)                       # qualifying, in memory
    before = _notified(nm)
    asyncio.run(mgr._async_handle_perimeter_trigger(G5_PR, egress_realert=True))
    assert _notified(nm) - before == 1
    assert _row(mgr) is None                            # no mute decision ran


def test_mute_realert_not_after_teardown(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    _cross(hass, clock, ago_s=10)
    assert _alert(mgr) == 0
    mgr._gate_log_torn_down = True
    assert mgr._realert_muted_edges(
        "garage_a", (clock() - timedelta(seconds=5), "", 0.0, False, "entry")) == 0
    mgr._gate_log_torn_down = False
    mgr._active = False
    assert mgr._realert_muted_edges(
        "garage_a", (clock() - timedelta(seconds=5), "", 0.0, False, "entry")) == 0
    assert pending == []


# ---- A3: door-key map from the egress producer's own leg set -----------

MG_ZONE = "binary_sensor.madrone_g6_entry_package_person_occupancy_2"
GA_F1 = "binary_sensor.garage_a_person_occupancy"


class _ProducerCensus(_Census):
    def __init__(self, by_cam, extra_union=()):
        super().__init__()
        self.by_cam = by_cam
        self.extra_union = list(extra_union)

    def get_transit_egress_entities_by_camera(self):
        return self.by_cam

    def get_transit_egress_entities(self):
        return [ci for v in self.by_cam.values() for ci in v] + self.extra_union


def _ci(eid, count=None):
    return SimpleNamespace(entity_id=eid, person_binary_sensor=eid,
                           person_count_sensor=count)


_BY_CAM = {
    GA_CAM: [_ci(GA_PR), _ci(GA_F1, "sensor.garage_a_person_count_2")],
    MG_CAM: [_ci(MG_PR), _ci(MG_ZONE)],
    DB_CAM: [_ci(DB_PR)],
}


def test_door_key_map_resolves_every_producer_leg(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch, census_obj=_ProducerCensus(_BY_CAM))
    want = {GA_PR: "garage_a", GA_F1: "garage_a",
            "sensor.garage_a_person_count_2": "garage_a",
            MG_PR: "madrone_g6_entry", MG_ZONE: "madrone_g6_entry",
            DB_PR: "doorbell_lite"}
    for leg, door in want.items():
        assert mgr._door_key_for(leg) == door, leg
    stats = mgr.egress_mute_stats()
    assert stats["egress_mute_unmapped_producer_legs"] == []
    assert stats["egress_mute_door_key_fallbacks"] == {}
    # Discriminator: the name key alone splits the zone leg off its door.
    assert mgr._egress_key(MG_ZONE) != "madrone_g6_entry"


def test_door_key_map_zone_leg_crossing_mutes_covered_camera(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch, census_obj=_ProducerCensus(_BY_CAM))
    _cross(hass, clock, door=MG_ZONE)
    assert _alert(mgr, FS_PR) == 0
    assert _row(mgr, "front_side_ptz")["inputs"]["door"] == "madrone_g6_entry"


def test_door_key_map_unknown_zone_leg_vetoes(monkeypatch, clock):
    """The security direction: an unknown crossing on the zone leg must
    veto the resident's mute at the same door."""
    hass, _nm, mgr = _rig(monkeypatch, census_obj=_ProducerCensus(_BY_CAM))
    _cross(hass, clock, door=MG_PR, ago_s=30)
    _cross(hass, clock, door=MG_ZONE, ago_s=20, pid=None, conf=None)
    assert _alert(mgr, FS_PR) == 1


def test_door_key_map_lists_unmapped_producer_leg(monkeypatch, clock):
    stray = _ci("binary_sensor.mystery_door_person_occupancy")
    hass, _nm, mgr = _rig(monkeypatch, census_obj=_ProducerCensus(
        _BY_CAM, extra_union=[stray]))
    assert mgr.egress_mute_stats()["egress_mute_unmapped_producer_legs"] == [
        "binary_sensor.mystery_door_person_occupancy"]


def test_door_key_fallback_counted_and_logged_once(monkeypatch, clock, caplog):
    import logging
    hass, _nm, mgr = _rig(monkeypatch)
    stray = "binary_sensor.mystery_door_person_occupancy"
    with caplog.at_level(logging.INFO):
        _cross(hass, clock, door=stray)
        _cross(hass, clock, door=stray, ago_s=5)
    assert mgr.egress_mute_stats()["egress_mute_door_key_fallbacks"] == {stray: 2}
    hits = [r for r in caplog.records if "not in the door-key map" in r.getMessage()]
    assert len(hits) == 1
    assert mgr._door_key_for(GA_PR) == "garage_a"            # mapped: no count
    assert stray in mgr.egress_mute_stats()["egress_mute_door_key_fallbacks"]
    assert GA_PR not in mgr.egress_mute_stats()["egress_mute_door_key_fallbacks"]


def test_door_key_map_reset_on_resetup(monkeypatch, clock):
    """Review C F12: a re-setup rebuilds the map (no stale entries)."""
    hass, _nm, mgr = _rig(monkeypatch)
    mgr._egress_door_key_by_entity["binary_sensor.old_leg"] = "garage_a"
    asyncio.run(mgr.async_teardown())
    asyncio.run(mgr.async_setup())
    assert "binary_sensor.old_leg" not in mgr._egress_door_key_by_entity
    assert mgr._door_key_for(GA_F2) == "garage_a"


def test_door_key_map_first_camera_wins_shared_entity(monkeypatch, clock):
    """Review C F12 (setdefault): an entity listed under two cameras keeps
    the first configured camera's door."""
    shared = "binary_sensor.shared_leg_person_occupancy"
    by_cam = {GA_CAM: [_ci(GA_PR), _ci(shared)], MG_CAM: [_ci(MG_PR), _ci(shared)]}
    hass, _nm, mgr = _rig(monkeypatch, census_obj=_ProducerCensus(by_cam))
    assert mgr._door_key_for(shared) == "garage_a"


def test_door_key_map_unmapped_camera_uses_name_fallback(monkeypatch, clock):
    """Review C F12 (D2/D12): with no map entry the name key still applies
    (and is counted) rather than dropping the crossing."""
    hass, _nm, mgr = _rig(monkeypatch)
    mgr._egress_door_key_by_entity.pop(GA_F2)
    _cross(hass, clock, door=GA_F2)
    assert "garage_a" in mgr._recent_egress_identity
    assert mgr.egress_mute_stats()["egress_mute_door_key_fallbacks"] == {GA_F2: 1}


# ---- A4: D10.5 now sees count-sensor crossings under the door key -------

def test_d10_5_count_sensor_crossing_reaches_door_key(monkeypatch, clock):
    """README-stated change: a crossing whose egress_camera is the person
    count sensor used to key under the raw sensor id (unreachable by
    D10.5); it now keys under the door, so D10.5 can use it."""
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, door=GA_COUNT, ago_s=3, pid="oji_udezue", conf=0.92)
    assert "sensor.garage_a_person_count" not in mgr._recent_egress_identity
    assert mgr._known_identity_for("garage_a", clock()) == (
        "oji_udezue", 0.92, "egress_event")


# ---- A6 / F7: dual-role window ------------------------------------------

def _dual(monkeypatch):
    hass, nm = _build(perimeter=(DB_CAM,), egress=(DB_CAM, GA_CAM), legs=LEGS)
    mgr, subs = _setup(hass, monkeypatch)
    mgr._subs = subs
    return hass, nm, mgr


def test_dual_role_window_zero_never_mutes_even_at_age_zero(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_WINDOW_S", 0)
    _h, _nm, mgr = _dual(monkeypatch)
    _stamp(mgr, GA_PR)                       # age exactly 0.0
    assert _alert(mgr, DB_PR) == 1


@pytest.mark.parametrize("age,alerts", [(119, 0), (120, 0), (121, 1)])
def test_dual_role_window_boundary(monkeypatch, clock, age, alerts):
    _h, _nm, mgr = _dual(monkeypatch)
    _stamp(mgr, GA_PR)
    clock.advance(age)
    assert _alert(mgr, DB_PR) == alerts


def test_arrival_listener_stays_dual_role_only(monkeypatch, clock):
    """Review C F13: the egress identity listener widened; the arrival
    listener did not."""
    _h, _nm, mgr = _rig(monkeypatch)
    assert mgr._unsub_person_arrivals is None and mgr._fp_setup_ts is None
    _h2, _nm2, dual = _dual(monkeypatch)
    assert dual._fp_setup_ts is not None


# ---- A7 / B MEDIUM: zero-fire counts only covering-door crossings -------

def test_mute_zero_fire_ignores_uncovered_door_crossings(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    for _ in range(8):
        _cross(hass, clock, door=DB_PR)      # doorbell_lite covers nothing
        clock.advance(60)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []
    assert mgr._egress_crossing_times == []


# ---- B LOWs --------------------------------------------------------------

def test_setup_without_teardown_drops_previous_listener(monkeypatch, clock):
    from unittest.mock import MagicMock
    hass, _nm, mgr = _rig(monkeypatch)
    old = MagicMock()
    mgr._unsub_egress_identity = old
    asyncio.run(mgr.async_setup())
    assert old.call_count == 1
    assert mgr._unsub_egress_identity is not old


def test_tripwire_not_scheduled_after_teardown(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    mgr._gate_log_torn_down = True
    mgr._fire_mute_tripwire("perimeter.egress_mute_ratio", 1.0, "t", "m", 1.0, 1)
    assert pending == []
    mgr._gate_log_torn_down = False
    mgr._active = False                      # C F4: the not-active guard
    mgr._fire_mute_tripwire("perimeter.egress_mute_zero_fire", 2.0, "t", "m", 0.0, 1)
    assert pending == []


# ---- C F1: re-alarm cooldown ---------------------------------------------

def test_mute_ratio_tripwire_cooldown(monkeypatch, clock):
    """A ratio alarm that stays true pages once per 24 h, not per row."""
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(14):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == ["Perimeter egress mute is silencing most edges"]
    clock.advance(86400 - 14)                # 86399 s after the first page
    _mute_at(hass, mgr, clock, 0)
    asyncio.run(_drain(pending))
    assert len(_tw_titles(nm)) == 1
    clock.advance(400)                       # past the cooldown
    for _ in range(11):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    asyncio.run(_drain(pending))
    assert len(_tw_titles(nm)) == 2


# ---- C F2 / F15 / F17: ratio boundaries, defaults ------------------------

def _decline(hass, mgr, clock):
    _cross(hass, clock, ago_s=5, pid=None, conf=None)
    _alert(mgr)
    clock.advance(200)                       # out of window + episode reset


@pytest.mark.parametrize("mutes,declines,fires", [
    (1, 10, False),   # mostly declines: quiet (C F2)
    (5, 5, False),    # exactly 0.5: the alarm is strictly ABOVE 0.5
    (6, 4, True),     # 0.6 > 0.5 (pins the shipped 0.5 default)
])
def test_mute_ratio_tripwire_ratio_boundary(monkeypatch, clock, mutes, declines, fires):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    for _ in range(declines):
        _decline(hass, mgr, clock)
    for _ in range(mutes):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    asyncio.run(_drain(pending))
    titles = [t for t in _tw_titles(nm) if t.startswith("Perimeter egress mute")]
    assert (titles == ["Perimeter egress mute is silencing most edges"]) is fires


@pytest.mark.parametrize("age,fires", [(86399, True), (86401, False)])
def test_mute_ratio_window_cutoff(monkeypatch, clock, age, fires):
    """Rows older than 24 h (shipped default) leave the ratio window."""
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    now = clock().timestamp()
    mgr._egress_mute_rows = [(now - age, True)] * 5 + [(now, False)] * 4
    _mute_at(hass, mgr, clock, 0)            # the 10th row (a mute)
    asyncio.run(_drain(pending))
    # within: 6 mutes / 10 rows -> fires; beyond: 1 mute / 5 rows -> too few
    assert bool(_tw_titles(nm)) is fires


def test_mute_zero_fire_window_and_disable(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    now = clock().timestamp()
    mgr._egress_crossing_times = [now - 86401] * 10      # outside the window
    _cross(hass, clock)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []
    mgr._egress_crossing_times = [now - 86399] * 4       # inside: 4 + 1 = 5
    _cross(hass, clock)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == ["Perimeter egress mute never ran"]


def test_mute_zero_fire_need_zero_disables(monkeypatch, clock):
    monkeypatch.setattr(_perimeter, "EGRESS_MUTE_ZERO_FIRE_MIN_CROSSINGS", 0)
    hass, nm, mgr = _rig(monkeypatch)
    pending = _with_tasks(hass)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    for _ in range(6):
        _cross(hass, clock)
        clock.advance(60)
    asyncio.run(_drain(pending))
    assert _tw_titles(nm) == []


# ---- C F3: anomaly row, kind, severity ------------------------------------

class _FakeDb:
    def __init__(self):
        self.events = []

    async def save_anomaly_event(self, ev):
        self.events.append(ev)
        return 1


def test_mute_tripwire_saves_anomaly_with_kind_and_severity(monkeypatch, clock):
    from custom_components.universal_room_automation.domain_coordinators.anomaly_event import (  # noqa: E501
        AnomalySeverity, AnomalyType,
    )
    hass, nm, mgr = _rig(monkeypatch)
    db = _FakeDb()
    hass.data[_const.DOMAIN]["database"] = db
    pending = _with_tasks(hass)
    for _ in range(10):
        _mute_at(hass, mgr, clock, 0)
        clock.advance(1)
    mgr._egress_mute_tw_since = clock().timestamp() - 86401
    mgr._egress_mute_rows = []
    for _ in range(5):
        _cross(hass, clock)
        clock.advance(60)
    asyncio.run(_drain(pending))
    kinds = [(e.type, e.severity, e.anomaly_type, e.coordinator) for e in db.events]
    assert kinds == [
        ("perimeter.egress_mute_ratio", AnomalySeverity.WARNING,
         AnomalyType.POINT_IN_TIME, "security"),
        ("perimeter.egress_mute_zero_fire", AnomalySeverity.WARNING,
         AnomalyType.POINT_IN_TIME, "security"),
    ]
    assert db.events[0].observed_value == 1.0 and db.events[0].sample_size == 10
    sev = [c.kwargs["severity"] for c in nm.async_notify.await_args_list
           if c.kwargs.get("title", "").startswith("Perimeter egress mute")]
    assert sev == [_perimeter.Severity.MEDIUM, _perimeter.Severity.MEDIUM]


def test_mute_tripwire_anomaly_row_real_db(monkeypatch, clock, tmp_path):
    """Tier 2-DB: the trip-wire row lands in a REAL anomaly_log with
    non-sentinel values."""
    import sqlite3
    from test_perimeter_gate_log import _real_db

    hass, _nm, mgr = _rig(monkeypatch)

    async def _go():
        db = await _real_db(tmp_path)
        hass.data[_const.DOMAIN]["database"] = db
        hass.async_create_task = lambda coro, *a, **k: asyncio.ensure_future(coro)
        for _ in range(10):
            _cross(hass, clock, ago_s=10)
            mgr._last_alert.clear()
            await mgr._async_handle_perimeter_trigger(G5_PR)
            clock.advance(1)
        for _ in range(5):
            await asyncio.sleep(0)
        for t in list(mgr._gate_log_tasks):
            await t
        await db.stop_write_worker()
        return db

    db = asyncio.run(_go())
    conn = sqlite3.connect(db.db_file)
    try:
        rows = conn.execute(
            "SELECT coordinator_id, metric_name, severity, observed_value, "
            "sample_size, anomaly_type FROM anomaly_log").fetchall()
    finally:
        conn.close()
    assert rows == [("security", "perimeter.egress_mute_ratio", "1", 1.0, 10,
                     "point_in_time")]


# ---- C F4: trip-wire task tracked and drained at teardown -----------------

def test_mute_tripwire_task_tracked_and_drained(monkeypatch, clock):
    hass, nm, mgr = _rig(monkeypatch)
    state = {}

    async def _go():
        hass.async_create_task = lambda coro, *a, **k: asyncio.ensure_future(coro)
        mgr._fire_mute_tripwire("perimeter.egress_mute_ratio", 1.0,
                                "Perimeter egress mute is silencing most edges",
                                "m", 1.0, 10)
        state["tracked"] = len(mgr._gate_log_tasks)
        await mgr.async_teardown()           # gathers the tracked task
        state["after"] = len(mgr._gate_log_tasks)

    asyncio.run(_go())
    assert state == {"tracked": 1, "after": 0}
    assert _tw_titles(nm) == ["Perimeter egress mute is silencing most edges"]


# ---- C F6: diagnostics surface --------------------------------------------

def test_diag_egress_mute_keys_unrecorded():
    import importlib
    sensor_mod = importlib.import_module(
        "custom_components.universal_room_automation.sensor")
    un = sensor_mod.ExteriorOpenTracksDiagnosticSensor._unrecorded_attributes
    for k in ("egress_mute_counts_by_reason", "egress_mute_covers",
              "egress_mute_episodes", "egress_mute_door_key_fallbacks",
              "egress_mute_unmapped_producer_legs"):
        assert k in un, k


def test_diag_sensor_shows_egress_mute_stats(monkeypatch, clock):
    import importlib
    from unittest.mock import MagicMock
    sensor_mod = importlib.import_module(
        "custom_components.universal_room_automation.sensor")
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock)
    _alert(mgr)
    s_ = sensor_mod.ExteriorOpenTracksDiagnosticSensor.__new__(
        sensor_mod.ExteriorOpenTracksDiagnosticSensor)
    lk = MagicMock()
    lk.open_tracks_snapshot.return_value = {}
    lk.census_counts.return_value = {}
    s_.hass = SimpleNamespace(data={_const.DOMAIN: {
        "exterior_track_linker": lk, "perimeter_alert_manager": mgr}})
    attrs = s_.extra_state_attributes
    assert attrs["egress_mute_counts_by_reason"] == {"egress_mute_known_resident": 1}
    assert attrs["egress_mute_episodes"] == {
        "g5_bullet": {"start": clock().isoformat(), "last": clock().isoformat()}}
    assert attrs["egress_mute_door_key_fallbacks"] == {}


def test_diag_stats_survive_egress_mute_stats_error(monkeypatch, clock):
    hass, _nm, mgr = _rig(monkeypatch)

    def _boom():
        raise RuntimeError("x")
    monkeypatch.setattr(mgr, "egress_mute_stats", _boom)
    out = mgr.gate_decision_stats()
    assert "gate_decisions_by_camera" in out
    assert "egress_mute_counts_by_reason" not in out


# ---- C LOWs F8-F11 ---------------------------------------------------------

def test_mute_future_dated_crossing_does_not_qualify(monkeypatch, clock):
    """Review C F8: clock skew must never make a crossing qualify."""
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=-5)
    assert _alert(mgr) == 1


@pytest.mark.parametrize("stamp_age,row", [(-5, False), (120, True), (121, False)])
def test_mute_stamp_window_bounds_gate_the_row(monkeypatch, clock, stamp_age, row):
    """Review C F9: the decline row needs a covering-door stamp inside the
    window (0 <= age <= 120)."""
    hass, _nm, mgr = _rig(monkeypatch)
    mgr._last_egress_time_by_door["garage_a"] = clock() - timedelta(seconds=stamp_age)
    assert _alert(mgr) == 1
    assert (_row(mgr) is not None) is row


def test_mute_identity_case_insensitive(monkeypatch, clock):
    """Review C F10: census slug and person_id compare lowercased."""
    class _Up(_Census):
        def _get_tracked_person_slugs(self):
            return ["Oji_Udezue"]
    hass, _nm, mgr = _rig(monkeypatch, census_obj=_Up())
    _cross(hass, clock, pid="OJI_UDEZUE")
    assert _alert(mgr) == 0


def test_mute_row_reference_is_latest_crossing(monkeypatch, clock):
    """Review C F11: the row names the most recent qualifying crossing."""
    hass, _nm, mgr = _rig(monkeypatch)
    _cross(hass, clock, ago_s=90, pid="jaya_udezue")
    _cross(hass, clock, ago_s=20, pid="oji_udezue")
    _cross(hass, clock, ago_s=60, pid="jaya_udezue")
    assert _alert(mgr) == 0
    r = _row(mgr)
    assert r["inputs"]["person_id"] == "oji_udezue"
    assert r["inputs"]["seconds_since"] == 20.0


# ---- A5 producer side: perimeter-only keys staged for the validator ------

def test_perimeter_only_camera_keys_exclude_egress_and_dual_role(monkeypatch, clock):
    _h, _nm, mgr = _rig(monkeypatch)
    assert mgr.perimeter_only_camera_keys == {"g5_bullet", "front_side_ptz"}
    _h2, _nm2, dual = _dual(monkeypatch)   # doorbell_lite is dual-role here
    assert dual.perimeter_only_camera_keys == set()


# ---- A3 producer API: per-camera form of get_transit_egress_entities -----

def test_census_egress_entities_by_camera_uses_producer_resolution():
    from custom_components.universal_room_automation.camera_census import (
        PersonCensus,
    )
    calls = []

    class _CM:
        def resolve_cross_platform_sensors(self, cams):
            calls.append(list(cams))
            if cams == ["camera.bad"]:
                raise RuntimeError("registry")
            return [_ci(f"binary_sensor.{cams[0][7:]}_person_detected")]

    c = PersonCensus.__new__(PersonCensus)
    c._camera_manager = _CM()
    c._get_raw_camera_list = lambda key: ["camera.garage_a_2", "camera.bad"]
    out = c.get_transit_egress_entities_by_camera()
    assert calls == [["camera.garage_a_2"], ["camera.bad"]]
    assert [ci.entity_id for ci in out["camera.garage_a_2"]] == [
        "binary_sensor.garage_a_2_person_detected"]
    assert out["camera.bad"] == []
