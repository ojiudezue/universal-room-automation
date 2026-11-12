"""Suspicious-arrival hold — replay acceptance oracle (plan rev 2 D0 / D5 / D6).

The fixture ``fixtures/lock_arrival_edges_2026_11.json`` is the committed
output of ``scripts/probes/lock_arrival_edge_probe.py`` over the live
recorder, 2026-11-05 04:12 .. 11-12 14:30 CST (118 person edges, 52
proximity crossings). The expected counts below are literals from the plan's
measurement (§2.1 / §2.3), not derived from the fixture.

``fixtures/lock_arrival_hold_develop_golden.json`` is the SAME replay
(``_lock_arrival_replay.run_replay``) run against the develop tree at
b7e4289e (no hold knob): the H = 0 run on this branch must equal it.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import _lock_arrival_replay as RP

GOLDEN = pathlib.Path(__file__).resolve().parent / "fixtures" / "lock_arrival_hold_develop_golden.json"


def _blip_ts(fx):
    return {e["edge_ts"] for e in fx["edges"] if RP.is_blip(e)}


def test_fixture_shape():
    fx = RP.load_fixture()
    edges, crossings = fx["edges"], fx["crossings"]
    assert len(edges) == 118
    assert sum(1 for e in edges if RP.is_blip(e)) == 78
    assert sum(1 for e in edges if not RP.is_blip(e)) == 40
    blips = _blip_ts(fx)
    assert len(crossings) == 52
    assert sum(1 for c in crossings if c["edge_ts"] in blips) == 49
    assert sum(1 for c in crossings if c["edge_ts"] not in blips) == 3
    # No coordinates: ages / distances only.
    for e in edges:
        assert set(e) == {"person", "edge_ts", "prev", "dur", "source", "source_type",
                          "src_age", "unav_ago"}
    # The measured gap the classifier sits in (plan §2.2).
    real_ages = [e["src_age"] for e in edges if not RP.is_blip(e)]
    blip_ages = [e["src_age"] for e in edges if RP.is_blip(e) and e["src_age"] is not None]
    assert max(real_ages) < 0.001
    assert min(blip_ages) > 4000


@pytest.mark.asyncio
async def test_replay_real_instant_blips_never_unlock():
    fx = RP.load_fixture()
    run = await RP.run_replay(5)
    trace = run["trace"]
    blips = _blip_ts(fx)
    real_edges = [t for t in trace if t["kind"] == "edge" and not RP.is_blip(fx["edges"][t["i"]])]
    blip_edges = [t for t in trace if t["kind"] == "edge" and RP.is_blip(fx["edges"][t["i"]])]
    reverts = [t for t in trace if t["kind"] == "leave" and RP.is_blip(fx["edges"][t["i"]])]
    real_x = [t for t in trace if t["kind"] == "cross"
              and fx["crossings"][t["i"]]["edge_ts"] not in blips]
    blip_x = [t for t in trace if t["kind"] == "cross"
              and fx["crossings"][t["i"]]["edge_ts"] in blips]
    assert (len(real_edges), len(blip_edges), len(real_x), len(blip_x)) == (40, 78, 3, 49)
    # 40/40 real edges release garage AND away lock in the edge's own callback.
    assert [(t["gen"] >= 1, t["away"] >= 1) for t in real_edges] == [(True, True)] * 40
    # 3/3 real crossings release at the crossing.
    assert [t["gen"] for t in real_x] == [1, 1, 1]
    # 78/78 blips: no release at the edge, the P2 signal, the revert, or later.
    for t in blip_edges + reverts + blip_x:
        assert (t["gen"], t["away"], t.get("sig_gen", 0), t.get("sig_away", 0),
                t.get("late_gen", 0), t.get("late_away", 0)) == (0, 0, 0, 0, 0, 0), t
    assert run["final"]["tail_gen"] == 0
    assert run["final"]["held_edges"] == []
    # Final state equals the run with the blips removed (INV-H3).
    clean = await RP.run_replay(5, drop_blips=True)
    for key in ("last_real", "arrival_edges", "away_not_home_since", "unlock_calls"):
        assert run["final"][key] == clean["final"][key], key


@pytest.mark.asyncio
async def test_hold_zero_is_develop_golden():
    golden = json.loads(GOLDEN.read_text())
    run = await RP.run_replay(0)
    assert run["trace"] == golden["trace"]
    assert run["final"] == golden["final"]
    # Sanity: the golden is the unguarded house (every blip released).
    fx = RP.load_fixture()
    blip_edges = [t for t in golden["trace"]
                  if t["kind"] == "edge" and RP.is_blip(fx["edges"][t["i"]])]
    assert all(t["gen"] >= 1 for t in blip_edges)
