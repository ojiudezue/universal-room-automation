"""INV-P2-AWAY-LATENCY + trust-view golden (census deconfliction CD1).

Plan: docs/planning/PLANNING_census_deconfliction.md §4. Harness and golden
provenance: ``_census_vision_harness.py``.

Non-hollow configuration (#63): besides the dark default, every comparison
also runs with ``CROSSING_VISION_AWARENESS_VISION_LEADS = True``, the class
set {display, notification}, the downgrade switch ON and a ledger whose
``guest_vis`` differs from the camera estimate (50), or is missing (None).
"""
from __future__ import annotations

import os

import pytest

import _census_vision_harness as H
from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse

SWITCH = "switch.ura_crossing_vision_census_authority"
VARIANTS = ["dark_default", "absent", "vision50_lead", "visionNone_lead",
            "vision50_unhealthy_lead", "interior_records_on"]


def _install_interior(mods, hass, monkeypatch, w):
    """VISION-INTERIOR-SIGHTINGS-1 INV-IV-AWAY variant ``interior_records_on``:
    the interior room records run (real producer, real twin groups over the
    rig registry, its on-edge listener bound) on every tick, between census
    updates, as the timer would. Ship 1 has no sampler and no census term,
    so this is the whole interior runtime."""
    c = mods.const
    hass.data[H.DOMAIN][c.CROSSING_VISION_HASS_KEY] = H.FakeVision(0)
    producer = w.presence._person_sightings
    producer._interior_registries = lambda: (w.rig.er, w.rig.dr)
    # The producer's clock (time.time bound at construction) is not the
    # frozen test clock; give it the frozen one so the path windows line up.
    from homeassistant.util import dt as _dt
    producer._now = lambda: _dt.utcnow().timestamp()
    # Review B LOW-4: drive D5 too. One entry on a mapped door whose only
    # inward edge reaches the family room (the scripted Frigate turns on again
    # at tick 17 = +510 s), so `_path_tick` and the DB-row path run inside the
    # per-tick trigger window.
    from datetime import timedelta
    from test_interior_vision_records import FAM_KEY, _DB, _Tracker, _crossing, _edge
    door_key = mods.resolver.canonical_camera_key(
        w.rig.resolver.resolve_operator_declaration([H.R.GARAGE_A_FRIGATE])[0])
    tracker = _Tracker({"garage_a": [_edge(mods, door_key, FAM_KEY, 63)]})
    tracker.crossings.append(_crossing(mods, H.START + timedelta(seconds=450), "golden:1"))
    hass.data[H.DOMAIN]["egress_tracker"] = tracker
    class _GoldenDB(_DB):
        """Records `interior_path` rows; any other DB call the census makes
        once a database exists is an awaited no-op (writes only)."""

        def __getattr__(self, name):
            async def _noop(*a, **k):
                return None
            return _noop

    w.interior_db = _GoldenDB()
    hass.data[H.DOMAIN]["database"] = w.interior_db
    w.interior_bodies = []

    def _tick():
        recs = producer.interior_tick()
        w.interior_bodies.append(max((r.bodies or 0) for r in recs) if recs else None)

    w.after_census_tick = _tick
    w.interior_producer = producer


def _install_variant(mods, hass, monkeypatch, variant):
    c = mods.const
    if variant == "dark_default":
        hass.data[H.DOMAIN][c.CROSSING_VISION_HASS_KEY] = H.FakeVision(0)
        return
    if variant == "absent":
        hass.data[H.DOMAIN].pop(c.CROSSING_VISION_HASS_KEY, None)
        return
    monkeypatch.setattr(c, "CROSSING_VISION_AWARENESS_VISION_LEADS", True,
                        raising=False)
    monkeypatch.setattr(c, "CROSSING_VISION_CONSUMER_CLASSES",
                        frozenset({"display", "notification"}))
    hass.states.async_set(SWITCH, "on")
    fake = {
        "vision50_lead": H.FakeVision(50),
        "visionNone_lead": H.FakeVision(None, healthy=False, state="unknown"),
        "vision50_unhealthy_lead": H.FakeVision(50, healthy=False),
    }[variant]
    hass.data[H.DOMAIN][c.CROSSING_VISION_HASS_KEY] = fake


async def _run(mods, hass, monkeypatch, freezer, variant):  # noqa: F811
    freezer.move_to(H.START)
    w = await H.build(mods, hass, monkeypatch)
    try:
        if variant == "interior_records_on":
            _install_interior(mods, hass, monkeypatch, w)
        else:
            _install_variant(mods, hass, monkeypatch, variant)
        records = await H.replay(w, freezer.tick)
        if variant == "interior_records_on":
            # Non-hollow (#63): the records really ran, and saw bodies.
            p = w.interior_producer
            assert p.interior_counters["record_builds"] >= len(records)  # + timer
            assert p.interior_counters.get("tick_errors", 0) == 0
            assert len(p._interior_groups) == 2
            # Script: the family room Frigate count reads 3 on ticks 3-4.
            assert max(b for b in w.interior_bodies if b is not None) == 3
            (path,) = p.get_last_path_records()
            assert path.source_ref == "golden:1" and [h[0] for h in path.hops] == [
                "62f7b21e657126f3482121f0f49d08fc"]
            assert [r["episode_type"] for r in w.interior_db.rows] == ["interior_path"]
        return records
    finally:
        await H.R.teardown(w.rig)


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("URA_REGEN_CENSUS_GOLDEN") != "1",
                    reason="golden generator (scripts/probes/gen_census_trust_golden.py)")
async def test_regenerate_golden(mods, hass, monkeypatch, freezer):  # noqa: F811
    records = await _run(mods, hass, monkeypatch, freezer, "absent")
    H.write_golden(records, os.environ.get("URA_GOLDEN_BASE", "unknown"))


def _strip(records, keys):
    return [{k: r[k] for k in keys} for r in records]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_away_tick_identical_with_vision_payload(
    mods, hass, monkeypatch, freezer, variant,  # noqa: F811
):
    """The AWAY inputs presence takes from the census, the inference
    triggers the update schedules and the engine verdict per tick equal the
    develop golden, for every vision variant (and therefore each other)."""
    got = await _run(mods, hass, monkeypatch, freezer, variant)
    keys = ("tick", "presence", "inference_triggers", "away_verdict", "veto_path")
    assert _strip(got, keys) == _strip(H.load_golden(), keys)
    # Self-check of the scenario: AWAY fires, and on the scripted tick.
    verdicts = [r["away_verdict"] for r in got]
    assert verdicts.index("away") == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_census_existing_fields_golden_all_classes(
    mods, hass, monkeypatch, freezer, variant,  # noqa: F811
):
    """Every pre-existing house field, the property zone, the full
    dispatched payload (every key) and the four existing census sensors equal
    the develop golden."""
    got = await _run(mods, hass, monkeypatch, freezer, variant)
    keys = ("tick", "house", "property", "payload", "sensors")
    assert _strip(got, keys) == _strip(H.load_golden(), keys)
    # Scenario self-check: guests appear and are held, the fleet goes dark.
    assert max(r["house"]["unidentified_count"] for r in got) >= 1
    assert any(r["payload"]["camera_input_dark"] for r in got)
    # Non-hollow (#63): the vision value really reached the census result
    # (awareness) on the lead variants while every trust field held.
    aware = [r["aware"] for r in got]
    if variant == "vision50_lead":
        assert aware == [50] * len(got)
    elif variant == "absent":
        assert all(a == r["house"]["unidentified_count"] for a, r in zip(aware, got))
    else:  # dark default, missing or unhealthy ledger: camera value
        assert aware == [r["house"]["unidentified_count"] for r in got]
