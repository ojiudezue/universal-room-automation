"""FACE-ARRIVAL-REBUILD-1 INV-NOOP, Phase 1 form (plan rev 11 §2, D8a).

Phase 1 has NO direction-aware code. This file pins that the egress producer's
outputs equal develop's for a fixture covering entry x {home, not_home, named
zone, unknown} and exit x {home, not_home, named zone}, plus a vetoed 0.75 and
a vetoed synthetic 0.9 crossing, and that turning the outcome log ON adds
nothing but the memory_episodes rows.

The oracle (EXPECTED) is hand-written from develop's rules (veto only on raw
`not_home`; 0.6 single leg; 0.75 two engines one camera; 0.9 two cameras;
notification names only at >= 0.75; entry registers, exit evicts), not
re-computed by the code under test.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from test_egress_outcome_log import (  # noqa: F401 — fixture reuse
    NOW,
    _cross,
    _leg,
    _rows,
    _state,
    rig,
)

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import transit_validator as tv

FRONT = "binary_sensor.front_door_person_occupancy"

# (name, direction, person raw state, leg recipe, expected develop outputs)
# leg recipe: "single" | "two_engines" | "two_cams_synthetic"
FIXTURE = [
    ("entry_home", "entry", "home", "single"),
    ("entry_not_home", "entry", "not_home", "single"),
    ("entry_zone", "entry", "work", "single"),
    ("entry_unknown", "entry", "unknown", "single"),
    ("exit_home", "exit", "home", "single"),
    ("exit_not_home", "exit", "not_home", "single"),
    ("exit_zone", "exit", "work", "single"),
    ("entry_vetoed_075", "entry", "not_home", "two_engines"),
    ("entry_vetoed_syn_09", "entry", "not_home", "two_cams_synthetic"),
]

# Hand-derived develop outputs per crossing:
# (person_id, identity_confidence, agreement_class, synthetic_flag,
#  outcome label, notification title, census call)
EXPECTED = {
    "entry_home": ("oji_udezue", 0.6, "single_source", False, "attached", "Someone arrived", ("register", "oji_udezue", "face")),
    "entry_not_home": (None, None, "single_source", False, "vetoed", "Someone arrived", None),
    "entry_zone": ("oji_udezue", 0.6, "single_source", False, "attached", "Someone arrived", ("register", "oji_udezue", "face")),
    "entry_unknown": ("oji_udezue", 0.6, "single_source", False, "attached", "Someone arrived", ("register", "oji_udezue", "face")),
    "exit_home": ("oji_udezue", 0.6, "single_source", False, "attached", "Someone left", ("evict", "oji_udezue")),
    "exit_not_home": (None, None, "single_source", False, "vetoed", "Someone left", None),
    "exit_zone": ("oji_udezue", 0.6, "single_source", False, "attached", "Someone left", ("evict", "oji_udezue")),
    "entry_vetoed_075": (None, None, "single_source", False, "vetoed", "Someone arrived", None),
    "entry_vetoed_syn_09": (None, None, "single_source", False, "vetoed", "Someone arrived", None),
}


class _NM:
    def __init__(self):
        self.titles: list[str] = []

    async def async_notify(self, **kw):
        self.titles.append(kw["title"])


class _DB:
    """Observes the producer's DB calls (the DAO itself is not under test
    here; test_egress_outcome_log uses the real DB)."""

    def __init__(self, real):
        self.real = real
        self.entry_rows: list[dict] = []

    async def log_entry_exit_event(self, **kw):
        self.entry_rows.append(dict(kw))

    async def log_memory_episode(self, **kw):
        return await self.real.log_memory_episode(**kw)


async def _replay(rig):
    nm = _NM()
    db = _DB(rig.db)
    rig.hass.data[ura_const.DOMAIN]["notification_manager"] = nm
    rig.hass.data[ura_const.DOMAIN]["database"] = db
    calls: list = []
    census = rig.census
    census.register_egress_face = lambda name, ts=None, provenance="face": calls.append(
        ("register", name, provenance))
    census.evict_egress_face = lambda name: calls.append(("evict", name))
    out = {}
    for i, (name, direction, pstate, recipe) in enumerate(FIXTURE):
        t = NOW + timedelta(minutes=10 * i)
        rig.states["person.oji_udezue"] = _state(pstate)
        if direction == "entry":
            lc = t + timedelta(seconds=3)
        else:
            lc = t - timedelta(seconds=20)
        rig.legs.clear()
        if recipe == "single":
            rig.legs["front_door"] = [_leg("front_door", "oji_udezue", lc)]
        elif recipe == "two_engines":
            rig.legs["front_door"] = [
                _leg("front_door", "oji_udezue", lc, device="a"),
                _leg("front_door", "oji_udezue", lc, device="b"),
            ]
        else:
            rig.legs["front_door"] = [_leg("front_door", "oji_udezue", lc)]
            rig.legs["foyer"] = [_leg("foyer", "oji_udezue", lc, synthetic=True)]
        boost_before = len(census._egress_identity_boost_events)
        n_calls, n_titles, n_rows = len(calls), len(nm.titles), len(db.entry_rows)
        if direction == "exit":
            # interior fires BEFORE the egress camera -> exit
            rig.clock.t = t - timedelta(seconds=5)
            rig.tracker._on_interior_state_change(
                type("E", (), {"data": {"new_state": type("S", (), {
                    "entity_id": "binary_sensor.foyer_person_occupancy", "state": "on"})()}})()
            )
            await _cross(rig, FRONT, at=t, interior_after_s=None)
        else:
            await _cross(rig, FRONT, at=t)
        await __import__("asyncio").sleep(0)
        payload = dict(rig.fired[-1][1])
        prov = payload.pop("identity_provenance")
        out[name] = {
            "bus": payload,
            "provenance": prov,
            "outcome": census._egress_identity_outcomes[-1][1],
            "title": nm.titles[n_titles] if len(nm.titles) > n_titles else None,
            "census": calls[n_calls:],
            "db": db.entry_rows[n_rows:],
            "boost_delta": len(census._egress_identity_boost_events) - boost_before,
        }
    return out


def _assert_develop(out):
    for name, (pid, conf, agree, syn, outcome, title, call) in EXPECTED.items():
        o = out[name]
        bus = o["bus"]
        direction = "entry" if name.startswith("entry") else "exit"
        assert bus["direction"] == direction, name
        assert bus["person_id"] == pid, name
        assert bus["identity_confidence"] == conf, name
        assert bus["agreement_class"] == agree, name
        assert bus["identity_synthetic_corroborated"] is syn, name
        assert set(bus) == {
            "direction", "egress_camera", "timestamp", "person_id", "confidence",
            "identity_confidence", "agreement_class",
            "identity_synthetic_corroborated",
        }, name
        assert o["outcome"] == outcome, name
        assert o["title"] == title, name
        assert o["census"] == ([call] if call else []), name
        assert len(o["db"]) == 1 and o["db"][0]["person_id"] == pid, name
        assert o["db"][0]["direction"] == direction, name
        assert o["boost_delta"] == 0, name
        assert o["provenance"] == ("face" if pid else None), name


@pytest.mark.asyncio
async def test_switch_off_golden_replay(rig, monkeypatch):
    """Log OFF: every output equals develop's (hand oracle), no memory row.
    Log ON: the same outputs plus exactly one memory row per crossing."""
    monkeypatch.setattr(tv, "EGRESS_OUTCOME_LOG_PERSIST", False)
    off = await _replay(rig)
    _assert_develop(off)
    assert _rows(rig.db) == []

    monkeypatch.setattr(tv, "EGRESS_OUTCOME_LOG_PERSIST", True)
    rig.fired.clear()
    rig.tracker._last_resolved.clear()
    on = await _replay(rig)
    _assert_develop(on)
    for name in off:
        a, b = dict(off[name]), dict(on[name])
        a["bus"] = {k: v for k, v in a["bus"].items() if k != "timestamp"}
        b["bus"] = {k: v for k, v in b["bus"].items() if k != "timestamp"}
        assert a == b, name
    rows = _rows(rig.db)
    assert [r[1]["outcome"] for r in rows] == [EXPECTED[n][4] for n, *_ in FIXTURE]
