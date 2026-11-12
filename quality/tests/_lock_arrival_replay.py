"""Replay driver for the lock suspicious-arrival hold (plan D6 / D5 golden).

Drives the REAL ``LockRegimeController`` (garage lockout ON + away lock ON)
through the committed probe fixture
``fixtures/lock_arrival_edges_2026_11.json`` (118 person ``-> home`` edges,
52 proximity crossings, 2026-11-05..11-12). Each edge is rebuilt the way HA's
``person`` writes it: the person state carries ``source`` = the fixture's
source tracker, whose own ``last_changed`` is ``edge_ts - src_age`` (no
tracker state when the probe had no history). A blip reverts to
``not_home`` after its measured ``dur``; a real edge leaves at ``edge_ts +
dur``. Every edge is followed by a ``SIGNAL_PERSON_ARRIVING(geofence)`` (the
P2 path; presence fires it on every ``-> home``). Each crossing sets the
distance sensor (ft) to ``to_ft`` and back to the far value 10 ms later.

Before every input the lockouts and the away lock are re-locked (and the
away lock re-owned), so each input's own release is observable. Per input the
driver records, SYNCHRONOUSLY after the callback (no time advance), the
garage ``release_gen`` delta and the away-lock release-epoch delta: a
non-zero delta there is a release issued in the same callback (0 s added
delay). The confirm of any hold is then observed as a delta on the NEXT
input's pre-sample (``late``).

Self-contained (its own event emitter), so the same file runs against a
develop tree to produce the H=0 golden.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "lock_arrival_edges_2026_11.json"

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
BED = "lock.master_bedroom_lock"
FAR_FT = 9999.0


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def is_blip(edge: dict) -> bool:
    return edge["dur"] < 10


class _Ev:
    def __init__(self, data):
        self.data = data


def emit(w, eid: str, state: str, attrs: dict, last_changed: datetime) -> None:
    """Write a state and fire the state_changed event to the regime's
    trackers (same dispatch as the harness, explicit attrs/last_changed)."""
    from _lockout_harness import FakeState  # noqa: PLC0415

    old = w.hass.states.get(eid)
    new = FakeState(eid, state, attrs, last_changed=last_changed)
    w.hass.states._s[eid] = new
    ev = _Ev({"entity_id": eid, "old_state": old, "new_state": new})
    for rec in list(w.listeners):
        if rec["active"] and eid in rec["ids"]:
            rec["cb"](ev)


def _tz_dt(ts: float, tz) -> datetime:
    return datetime.fromtimestamp(ts, tz=tz)


def build_timeline(fx: dict, *, drop_blips: bool) -> list[tuple]:
    """(ts, order, kind, payload) sorted."""
    tl: list[tuple] = []
    blip_ts = {e["edge_ts"] for e in fx["edges"] if is_blip(e)}
    for i, e in enumerate(fx["edges"]):
        if drop_blips and is_blip(e):
            continue
        tl.append((e["edge_ts"], 0, "edge", i))
        if e["dur"] < 1e8:
            tl.append((e["edge_ts"] + e["dur"], 0, "leave", i))
    for j, c in enumerate(fx["crossings"]):
        if drop_blips and c["edge_ts"] in blip_ts:
            continue
        tl.append((c["ts"], 1, "cross", j))
        tl.append((c["ts"] + 0.01, 1, "uncross", j))
    tl.sort(key=lambda t: (t[0], t[1]))
    return tl


async def run_replay(hold_s: float | None, *, drop_blips: bool = False) -> dict:
    """Replay the fixture; return {"trace": [...], "final": {...}}.

    ``hold_s`` None = do not set the knob (develop has none)."""
    from _lockout_harness import TZ, World, load, settle  # noqa: PLC0415

    const = load("const")
    R = load("domain_coordinators.security_lock_regime")
    fx = load_fixture()
    persons = sorted({"person." + e["person"] for e in fx["edges"]})
    dist_sensor = fx["crossings"][0]["sensor"]
    opts = {
        "security_garage_lockout_enabled": True,
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_lock_entities": [BED],
        "security_lock_sweep_exclude": [BED],
        "security_away_lock_enabled": True,
        "security_away_lock_entities": [BED],
        "security_away_lock_persons": persons,
        "security_lockout_distance_sensors": [dist_sensor],
        "security_coordinator_enabled": True,
        "sleep_start_hour": 22,
        "sleep_end_hour": 6,
    }
    if hold_s is not None:
        opts["garage_lockout_arrival_hold_s"] = hold_s
    tl = build_timeline(fx, drop_blips=drop_blips)
    start = _tz_dt(tl[0][0] - 700.0, TZ)
    w = World(start, opts, entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    w.hass.data[const.DOMAIN] = {"coordinator_manager": SimpleNamespace(house_state="away")}
    for ent in (LOCK_A, LOCK_B, BED):
        w.seed(ent, "locked")
    w.seed(dist_sensor, str(FAR_FT), {"unit_of_measurement": "ft"})
    for pid in persons:
        src = f"device_tracker.{pid.split('.', 1)[1]}_replay_phone"
        w.seed(src, "not_home", {"source_type": "gps"}, last_changed=start)
        w.seed(pid, "not_home", {"source": src}, last_changed=start)
    sc = SimpleNamespace(enabled=True, _shutting_down=False, observation_mode=False,
                         _garage_entities=[], decision_logger=None)
    regime = R.LockRegimeController(
        w.hass, sc, now=w.clock, call_later=w.call_later, track_state=w.track_state,
        track_added_domain=w.track_added, track_removed_domain=w.track_removed,
    )
    await regime.async_setup()
    await w.advance(601)
    emit(w, dist_sensor, str(FAR_FT), {"unit_of_measurement": "ft"}, w.now)

    trace: list[dict] = []
    for ts, _o, kind, idx in tl:
        target = _tz_dt(ts, TZ)
        g_pre, e_pre = regime.release_gen, regime._away_release_epoch
        if target > w.now:
            await w.advance((target - w.now).total_seconds())
        if trace:
            # Releases fired by timers between the previous input and this one
            # (a hold's confirm lands here).
            trace[-1]["late_gen"] = regime.release_gen - g_pre
            trace[-1]["late_away"] = regime._away_release_epoch - e_pre
        # Re-lock everything (no events) so this input's release shows.
        for ent in (LOCK_A, LOCK_B, BED):
            w.seed(ent, "locked")
        regime.away_lock_owned = {BED}
        regime._release_inflight.clear()
        gen0, ep0 = regime.release_gen, regime._away_release_epoch
        if kind in ("edge", "leave"):
            e = fx["edges"][idx]
            pid = "person." + e["person"]
            if kind == "edge":
                src = e["source"] or f"device_tracker.{e['person']}_replay_phone"
                if e["src_age"] is None:
                    w.hass.states._s.pop(src, None)
                else:
                    w.seed(src, "home", {"source_type": e["source_type"]},
                           last_changed=target - timedelta(seconds=e["src_age"]))
                emit(w, pid, "home", {"source": src}, target)
                rec = {"kind": kind, "i": idx, "gen": regime.release_gen - gen0,
                       "away": regime._away_release_epoch - ep0}
                gen1, ep1 = regime.release_gen, regime._away_release_epoch
                regime.on_person_arriving({"person_entity": pid, "source": "geofence"})
                rec["sig_gen"] = regime.release_gen - gen1
                rec["sig_away"] = regime._away_release_epoch - ep1
            else:
                phone = f"device_tracker.{e['person']}_replay_phone"
                w.seed(phone, "not_home", {"source_type": "gps"}, last_changed=target)
                emit(w, pid, "not_home", {"source": phone}, target)
                rec = {"kind": kind, "i": idx, "gen": regime.release_gen - gen0,
                       "away": regime._away_release_epoch - ep0}
        else:
            c = fx["crossings"][idx]
            val = c["to_ft"] if kind == "cross" else FAR_FT
            emit(w, dist_sensor, str(val), {"unit_of_measurement": "ft"}, target)
            rec = {"kind": kind, "i": idx, "gen": regime.release_gen - gen0,
                   "away": regime._away_release_epoch - ep0}
        await settle()
        trace.append(rec)
    # Let every pending hold resolve.
    gen0, ep0 = regime.release_gen, regime._away_release_epoch
    await w.advance(60)
    final = {
        "tail_gen": regime.release_gen - gen0,
        "tail_away": regime._away_release_epoch - ep0,
        "last_real": {k: [v[0], round(v[1], 3), v[2]] for k, v in sorted(regime._last_real.items())},
        "arrival_edges": {k: round(v, 3) for k, v in sorted(regime._arrival_edges.items())},
        "away_not_home_since": {
            k: round(v, 3) for k, v in sorted(regime._away_not_home_since.items())},
        "held_edges": sorted(getattr(regime, "_held_edges", {}) or {}),
        "unlock_calls": len(w.locks_called("unlock")),
    }
    await regime.async_teardown()
    return {"trace": trace, "final": final}
