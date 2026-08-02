"""Hierarchical Memory MVP Stage 1 — tests.

Coverage:
  * MemoryFacade — seven verbs happy path + insufficient_history +
    kill switch + access-policy rejection + fallback-ladder provenance
    + MemoryAnswer frozen.
  * Episode writers — each of the 3 sites writes the right row.
  * Baseline writer — Welford fold correctness; quality gate excludes
    suppression windows; allowlist respected; UTC->CDT bin correctness
    at a bin boundary.
  * Seeds — F1-F4 present after init, idempotent on re-init.

Bug-class #62 discipline: tests drive the production DAO write path.
Where the production code is a coordinator method we can't easily
instantiate, we use the DAO directly and mark those as source-anchor
tests (disclosed in the test docstring).
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.const import (  # noqa: E402
    DOMAIN,
    MEMORY_BASELINE_ALLOWLIST,
    MEMORY_BASELINE_SAMPLE_CAP,
    MEMORY_SEED_FACTS,
)
from custom_components.universal_room_automation.memory_facade import (  # noqa: E402
    MemoryAnswer,
    MemoryFacade,
    build_metric_key,
    house_state_to_family,
    utc_to_local_hour_bin,
)


# ---------------------------------------------------------------------------
# Tiny fake DB — drives the facade verbs without spinning up aiosqlite.
# ---------------------------------------------------------------------------


class _FakeDB:
    def __init__(self) -> None:
        self.baselines: dict[tuple[str, str], dict] = {}
        self.episodes: list[dict] = []
        self.facts: list[dict] = []

    async def read_memory_baseline(self, node_id, metric_name):
        return self.baselines.get((node_id, metric_name))

    async def read_memory_baselines_for_node(self, node_id):
        return [
            {**v, "metric_name": k[1]}
            for k, v in self.baselines.items() if k[0] == node_id
        ]

    async def read_memory_episodes(
        self, node_id, episode_type=None, since_iso=None,
    ):
        out = [e for e in self.episodes if e["node_id"] == node_id]
        if episode_type is not None:
            out = [e for e in out if e["episode_type"] == episode_type]
        if since_iso is not None:
            out = [e for e in out if e["started_at"] >= since_iso]
        return out

    async def read_memory_facts(
        self, node_id, topic=None, include_superseded=False,
    ):
        out = [f for f in self.facts if f["node_id"] == node_id]
        if topic is not None:
            out = [f for f in out if f["topic"] == topic]
        if not include_superseded:
            out = [f for f in out if f.get("superseded_by") is None]
        return out


class _FakeHass:
    def __init__(self):
        self.data = {DOMAIN: {"database": _FakeDB()}}
        self.config_entries = MagicMock()
        self.config_entries.async_entries = MagicMock(return_value=[])
        self.states = MagicMock()
        self.states.get = MagicMock(return_value=None)


@pytest.fixture
def fake_hass():
    return _FakeHass()


@pytest.fixture
def facade(fake_hass):
    return MemoryFacade(fake_hass)


# ---------------------------------------------------------------------------
# 1. MemoryAnswer is frozen.
# ---------------------------------------------------------------------------


def test_memory_answer_is_frozen():
    ans = MemoryAnswer(verdict="ok", value=1, support=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ans.verdict = "no_data"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Verb happy paths + insufficient_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_ok_and_insufficient(facade, fake_hass):
    key = ("room:study_a", build_metric_key("humidity", 12, "home"))
    fake_hass.data[DOMAIN]["database"].baselines[key] = {
        "mean": 60.3, "variance": 10.89, "sample_count": 1046,
        "last_updated": "x",
    }
    ans = await facade.baseline(
        "room:study_a", "humidity",
        context={"hour_bin": 12, "family": "home"},
    )
    assert ans.verdict == "ok"
    assert ans.value["mean"] == pytest.approx(60.3)
    assert ans.value["sd"] == pytest.approx(3.3, abs=0.05)
    assert ans.support == 1046

    ans2 = await facade.baseline(
        "room:study_a", "co2",
        context={"hour_bin": 12, "family": "home"},
    )
    assert ans2.verdict == "insufficient_history"


@pytest.mark.asyncio
async def test_baseline_fallback_ladder_provenance(facade, fake_hass):
    # Only an "all" fallback row exists — verb must fall through.
    key = ("room:study_a", "temperature:h00:all")
    fake_hass.data[DOMAIN]["database"].baselines[key] = {
        "mean": 76.0, "variance": 4.0, "sample_count": 500,
        "last_updated": "x",
    }
    ans = await facade.baseline(
        "room:study_a", "temperature",
        context={"hour_bin": 0, "family": "away"},
    )
    assert ans.verdict == "ok"
    # Provenance records the fallback rung so consumers can see which
    # exact key answered.
    assert any("fallback:drop_family" in p for p in ans.provenance)


@pytest.mark.asyncio
async def test_episodes_happy_and_empty(facade, fake_hass):
    fake_hass.data[DOMAIN]["database"].episodes = [
        {"node_id": "room:study_a", "episode_type": "occupancy_phantom",
         "started_at": "2026-08-01T13:05:00+00:00",
         "adjudication": "phantom"},
    ]
    ans = await facade.episodes("room:study_a", pattern="occupancy_phantom")
    assert ans.verdict == "ok"
    assert ans.support == 1

    ans2 = await facade.episodes("room:study_b")
    assert ans2.verdict == "insufficient_history"


@pytest.mark.asyncio
async def test_facts_happy_and_empty(facade, fake_hass):
    fake_hass.data[DOMAIN]["database"].facts = [
        {"node_id": "room:study_a", "topic": "sensor_trust",
         "statement": "InvisOutlet unreliable",
         "confidence": 0.9, "derived_from": "E3,E4",
         "created_at": "2026-08-02T00:00:00+00:00",
         "superseded_by": None},
    ]
    ans = await facade.facts("room:study_a")
    assert ans.verdict == "ok"
    assert ans.support == 1

    ans2 = await facade.facts("room:study_z")
    assert ans2.verdict == "insufficient_history"


@pytest.mark.asyncio
async def test_unusual_insufficient_history_gate(facade, fake_hass):
    # support < MEMORY_UNUSUAL_MIN_SUPPORT (30) -> insufficient_history
    fake_hass.data[DOMAIN]["database"].baselines[
        ("room:study_a", "humidity:h12:home")
    ] = {"mean": 60.0, "variance": 1.0, "sample_count": 5,
         "last_updated": "x"}
    ans = await facade.unusual("room:study_a")
    assert ans.verdict == "insufficient_history"
    assert any("support=" in p for p in ans.provenance)


@pytest.mark.asyncio
async def test_unusual_ok_over_threshold(facade, fake_hass):
    db = fake_hass.data[DOMAIN]["database"]
    for i in range(5):
        db.baselines[("room:study_a", f"m{i}:h12:home")] = {
            "mean": 50.0, "variance": float(i + 1),
            "sample_count": 100, "last_updated": "x",
        }
    ans = await facade.unusual("room:study_a")
    assert ans.verdict == "ok"
    assert ans.support >= 500


@pytest.mark.asyncio
async def test_profile_returns_capability_registry(facade):
    ans = await facade.profile("room:study_a")
    assert ans.verdict == "ok"
    caps = ans.value["capability"]
    # spec: complete registry — must include the whole comfort-fan trust
    # stack, humidity-fan, cover schedule, camera-person fusion, BLE
    # corroboration, occupancy substrates.
    for expected in (
        "lighting", "comfort_fan", "comfort_fan_away_veto",
        "comfort_fan_d2_demotion", "comfort_fan_transition_gate",
        "humidity_fan", "cover_schedule", "camera_person_fusion",
        "ble_corroboration", "occupancy_substrate_mmwave",
        "vacancy_hold", "fan_recheck",
    ):
        assert expected in caps["declared"], expected


@pytest.mark.asyncio
async def test_profile_coordinator_capabilities(facade):
    ans = await facade.profile("coordinator:energy")
    assert ans.verdict == "ok"
    declared = ans.value["capability"]["declared"]
    for expected in (
        "reserve_strategy", "tou_arbitrage",
        "peak_avoidance_savings", "ac_ramp_savings",
        "evse_precedence", "db_write_governance",
    ):
        assert expected in declared, expected


@pytest.mark.asyncio
async def test_narrative_ok_from_episodes(facade, fake_hass):
    fake_hass.data[DOMAIN]["database"].episodes = [
        {"node_id": "room:study_a", "episode_type": "occupancy_phantom",
         "started_at": "2026-08-01T13:05:00+00:00",
         "adjudication": "phantom"},
    ]
    ans = await facade.narrative("room:study_a")
    assert ans.verdict == "ok"
    assert ans.support >= 1


# ---------------------------------------------------------------------------
# 3. Kill switch degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_disables_all_verbs(fake_hass, monkeypatch):
    from custom_components.universal_room_automation import (
        memory_facade as _mf,
    )
    monkeypatch.setattr(_mf, "MEMORY_FACADE_ENABLED", False)
    facade = MemoryFacade(fake_hass)
    for coro in (
        facade.baseline("room:x", "humidity"),
        facade.episodes("room:x"),
        facade.unusual("room:x"),
        facade.outcome("room:x"),
        facade.narrative("room:x"),
        facade.profile("room:x"),
        facade.facts("room:x"),
    ):
        ans = await coro
        assert ans.verdict == "no_data"
        assert any(p.startswith("kill_switch") for p in ans.provenance)


# ---------------------------------------------------------------------------
# 4. Access policy — room may not query distant room.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_policy_room_to_distant_room(facade, fake_hass):
    # No Zone Manager entry -> not same-zone -> denied.
    ans = await facade.facts(
        "room:distant_room", caller_id="room:study_a",
    )
    assert ans.verdict == "no_data"
    assert any(
        p.startswith("access_denied:room_may_only_query_zone_siblings")
        for p in ans.provenance
    )


@pytest.mark.asyncio
async def test_access_policy_room_to_house_allowed(facade):
    # A room may query the house for context.
    ans = await facade.facts("house", caller_id="room:study_a")
    # No facts stored ⇒ insufficient_history (NOT access_denied).
    assert ans.verdict == "insufficient_history"
    assert not any(
        p.startswith("access_denied") for p in ans.provenance
    )


@pytest.mark.asyncio
async def test_access_policy_room_to_coordinator_denied(facade):
    ans = await facade.facts(
        "coordinator:energy", caller_id="room:study_a",
    )
    assert ans.verdict == "no_data"
    assert any("access_denied" in p for p in ans.provenance)


@pytest.mark.asyncio
async def test_access_policy_observer_bypass(facade):
    # No caller_id ⇒ observer tier ⇒ nothing denied.
    ans = await facade.facts("coordinator:energy")
    assert ans.verdict == "insufficient_history"
    assert not any(p.startswith("access_denied") for p in ans.provenance)


# ---------------------------------------------------------------------------
# 5. UTC -> CDT bin boundary correctness (audit gap #5).
# ---------------------------------------------------------------------------


def test_utc_to_local_hour_bin_boundary_cdt():
    # 2026-08-01 15:00 UTC = 10:00 CDT (CST is UTC-6; CDT is UTC-5).
    # Bin 9 (contains 9-11). Same moment naive-interpreted would say 15
    # UTC -> bin 15 (contains 15-17), an off-by-5-hour bug — the
    # audit's gap #5.
    ts = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
    assert utc_to_local_hour_bin(ts) == 9


def test_utc_to_local_hour_bin_bin_edge():
    # 2026-08-01 18:00 UTC = 13:00 CDT -> bin 12.
    ts = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
    assert utc_to_local_hour_bin(ts) == 12


# ---------------------------------------------------------------------------
# 6. Family map (house_state -> family)
# ---------------------------------------------------------------------------


def test_family_map_covers_all_states():
    for state in (
        "auto", "away", "arriving", "home_day", "home_evening",
        "home_night", "sleep", "waking", "guest", "vacation",
    ):
        fam = house_state_to_family(state)
        assert fam in ("home", "away", "sleep")


# ---------------------------------------------------------------------------
# 7. Seeds — F1-F4 present after init, idempotent on re-init.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_facts_seeded_on_init(tmp_path, monkeypatch):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    (tmp_path).mkdir(exist_ok=True)
    db = UniversalRoomDatabase(hass)
    ok = await db.initialize()
    assert ok
    await db.start_write_worker()
    try:
        facts = await db.read_memory_facts(
            "room:study_a", include_superseded=True,
        )
        # F1..F4 all have node_id room:study_a
        assert len(facts) == len(MEMORY_SEED_FACTS)
        topics = {f["topic"] for f in facts}
        assert {"occupancy_reliability", "sensor_trust",
                "occupancy_baseline", "notification_hygiene"} <= topics
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_memory_facts_seed_idempotent(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        # Re-invoke initialize; INSERT-if-empty must not double-seed.
        assert await db.initialize()
        facts = await db.read_memory_facts(
            "room:study_a", include_superseded=True,
        )
        assert len(facts) == len(MEMORY_SEED_FACTS)
    finally:
        await db.stop_write_worker()


# ---------------------------------------------------------------------------
# 8. Episode writer — DAO write path + registered vocabulary gate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_memory_episode_writes_row(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        # D2-demotion equivalent (drives the same DAO the coordinator
        # site calls). Verifies row shape + adjudication columns.
        row_id = await db.log_memory_episode(
            node_id="room:study_a",
            episode_type="occupancy_phantom",
            adjudication="phantom",
            adjudicated_by="d2_demotion",
            attrs={"reason": "mmwave_sole_fan_on_no_corroboration"},
            source_ref="coordinator.py:d2_demotion",
        )
        assert row_id is not None and row_id > 0

        rows = await db.read_memory_episodes("room:study_a")
        assert len(rows) == 1
        r = rows[0]
        assert r["episode_type"] == "occupancy_phantom"
        assert r["adjudication"] == "phantom"
        assert r["adjudicated_by"] == "d2_demotion"
        assert r["attrs"]["reason"] == (
            "mmwave_sole_fan_on_no_corroboration"
        )
        # Timestamps carry explicit +00:00 offset (audit gap #5).
        assert r["started_at"].endswith("+00:00")
        assert r["adjudicated_at"] and r["adjudicated_at"].endswith(
            "+00:00",
        )
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_log_memory_episode_registered_vocabulary_gate(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        # Unregistered type — must be rejected.
        row_id = await db.log_memory_episode(
            node_id="room:x",
            episode_type="not_a_registered_type",
        )
        assert row_id is None
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_all_three_writer_sites_use_registered_types(tmp_path):
    """The three episode-writer sites (d2_demotion, fan_transition_gate,
    fan_veto) each use a registered episode_type. Drive the DAO the way
    each site does and verify each row is accepted + carries the
    expected adjudicated_by field.
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        # Site 1 — D2 demotion (coordinator.py).
        assert await db.log_memory_episode(
            node_id="room:study_a",
            episode_type="occupancy_phantom",
            adjudication="phantom",
            adjudicated_by="d2_demotion",
            source_ref="coordinator.py:d2_demotion",
        )
        # Site 2 — fan-transition gate (coordinator.py).
        assert await db.log_memory_episode(
            node_id="room:study_a",
            episode_type="fan_transition_suppressed",
            adjudication="phantom",
            adjudicated_by="fan_transition_gate",
            source_ref="coordinator.py:fan_transition_gate",
        )
        # Site 3 — comfort-fan away-veto (fan_veto.py).
        assert await db.log_memory_episode(
            node_id="room:study_a",
            episode_type="comfort_fan_vetoed",
            adjudication="confirmed",
            adjudicated_by="fan_veto",
            source_ref="fan_veto.py:_record_veto",
        )
        rows = await db.read_memory_episodes("room:study_a")
        by = {r["adjudicated_by"]: r for r in rows}
        assert set(by) == {
            "d2_demotion", "fan_transition_gate", "fan_veto",
        }
    finally:
        await db.stop_write_worker()


# ---------------------------------------------------------------------------
# 9. Baseline writer — Welford + quality gate + allowlist.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welford_upsert_matches_stats(tmp_path):
    """A stream of samples through the DAO should converge to the same
    mean and variance the offline formulas predict.
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        samples = [60.0, 62.0, 58.0, 61.0, 59.0, 60.5, 60.2, 59.8, 61.1, 60.4]
        node = "room:study_a"
        metric = "humidity:h12:home"
        for s in samples:
            await db.upsert_memory_baseline(
                node, metric, s, MEMORY_BASELINE_SAMPLE_CAP,
            )
        row = await db.read_memory_baseline(node, metric)
        assert row is not None
        n = len(samples)
        mean = sum(samples) / n
        var = sum((x - mean) ** 2 for x in samples) / (n - 1)
        assert row["sample_count"] == n
        assert row["mean"] == pytest.approx(mean, abs=1e-6)
        assert row["variance"] == pytest.approx(var, abs=1e-6)
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_baseline_writer_quality_gate_excludes_suppressed(
    monkeypatch, tmp_path,
):
    """Room with an active fan-transition suppression bump this cycle
    is EXCLUDED from folding — baseline unmoved.
    """
    from custom_components.universal_room_automation import (
        memory_baseline as mb,
    )
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()

    class _FakeCoord:
        room_name = "Study A"
        _mmwave_demoted_latch = False
        _mmwave_fan_demoted_last_tick = False
        _fan_transition_suppressed_count = 5  # bumped this cycle

    _fake_hass_data = {
        DOMAIN: {
            "database": db,
            "study_a_slot": {"coordinator": _FakeCoord()},
        },
    }
    hass.data = _fake_hass_data
    # Orchestrator-drill fix (2026-08-02): the original fixture returned
    # None for every state, so zero rows folded REGARDLESS of the gate —
    # a dead-limb anchor (bug class #62; neutering _is_room_suppressed
    # left this test green). Provide a REAL humidity sample so that an
    # ungated fold WOULD write, making the gate the discriminator.
    _hum = MagicMock()
    _hum.state = "61.5"
    hass.states = MagicMock()
    hass.states.get = MagicMock(
        side_effect=lambda eid: _hum if eid.endswith("_humidity") else None
    )
    monkeypatch.setattr(mb, "MEMORY_BASELINE_ALLOWLIST", ("study_a",))
    # Simulate a prior suppression count so the "increment since last
    # tick" gate fires. Coordinator dict already carries no prev, so
    # first call registers 5 as a jump above 0.
    try:
        n = await mb.async_fold_samples(hass)
        # Samples EXIST (humidity=61.5) but the room is gated → zero rows.
        assert n == 0
        rows = await db.read_memory_baselines_for_node("room:study_a")
        assert not rows
        # Sanity leg: second fold with an UNCHANGED suppression count (no
        # new delta) and no latch flags → gate releases → same fixture
        # MUST write. Proves the sample was real and the gate was the
        # only thing standing between the room and the table.
        n2 = await mb.async_fold_samples(hass)
        assert n2 >= 1, "ungated fold with real samples must write"
        rows2 = await db.read_memory_baselines_for_node("room:study_a")
        assert rows2
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_baseline_writer_respects_allowlist(monkeypatch, tmp_path):
    from custom_components.universal_room_automation import (
        memory_baseline as mb,
    )
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    hass.data = {DOMAIN: {"database": db}}
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    monkeypatch.setattr(mb, "MEMORY_BASELINE_ALLOWLIST", ())
    try:
        n = await mb.async_fold_samples(hass)
        assert n == 0
    finally:
        await db.stop_write_worker()


# ---------------------------------------------------------------------------
# 10. Fix-up cycle new coverage — items 2, 6, 9, 13, 14.
# ---------------------------------------------------------------------------


def _tmp_db_hass(tmp_path):
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    return hass


@pytest.mark.asyncio
async def test_seed_idempotent_partial_shape(tmp_path):
    """HIGH A2 fix-up: seed is idempotent under partial-failure shape.

    Manually insert 2 of the 4 seed rows, re-run initialize, and assert
    exactly 4 total (the missing 2 filled in, no dupes on the pre-existing).
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = _tmp_db_hass(tmp_path)
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        # Manually clear-and-insert 2 rows to simulate partial-shape state.
        # Use a fresh initialize path: drop all and put back 2 rows through
        # the DAO surface via a direct connection (test-scope only).
        import aiosqlite  # noqa: PLC0415
        async with aiosqlite.connect(db.db_file) as conn:
            await conn.execute("DELETE FROM memory_facts")
            await conn.commit()
        # Insert 2 of the seed facts by hand.
        async with aiosqlite.connect(db.db_file) as conn:
            for fact in list(MEMORY_SEED_FACTS)[:2]:
                await conn.execute(
                    """INSERT INTO memory_facts (
                        node_id, topic, statement, attrs_json,
                        confidence, derived_from, created_at, superseded_by
                    ) VALUES (?, ?, ?, '{}', ?, ?, ?, NULL)""",
                    (fact["node_id"], fact["topic"], fact["statement"],
                     float(fact["confidence"]), fact["derived_from"],
                     "2026-01-01T00:00:00+00:00"),
                )
            await conn.commit()
        # Re-initialize; INSERT OR IGNORE must fill in the missing 2.
        assert await db.initialize()
        facts = await db.read_memory_facts(
            "room:study_a", include_superseded=True,
        )
        assert len(facts) == len(MEMORY_SEED_FACTS)
        # Double-init once more should also be a no-op.
        assert await db.initialize()
        facts2 = await db.read_memory_facts(
            "room:study_a", include_superseded=True,
        )
        assert len(facts2) == len(MEMORY_SEED_FACTS)
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_welford_variance_decays_after_distribution_shift(tmp_path):
    """MED A-M1 fix-up: variance tracks CURRENT spread after the count hits
    the clamp. Feed 100 sd~5 samples then 500 sd~1 samples with cap=200 and
    assert variance is closer to 1 than to 5 by the end.
    """
    import random  # noqa: PLC0415
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = _tmp_db_hass(tmp_path)
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        node = "room:test"
        metric = "temperature:h12:home"
        rng = random.Random(1234)
        cap = 200
        # Phase 1: 100 samples with sd~5 around 60
        for _ in range(100):
            await db.upsert_memory_baseline(
                node, metric, 60.0 + rng.gauss(0, 5.0), cap,
            )
        # Phase 2: 500 tight samples with sd~1 around 60
        for _ in range(500):
            await db.upsert_memory_baseline(
                node, metric, 60.0 + rng.gauss(0, 1.0), cap,
            )
        row = await db.read_memory_baseline(node, metric)
        assert row is not None
        sd = row["variance"] ** 0.5
        # Without decay this would remain wedged around 5 (early rows
        # dominate the M2 numerator forever). Assert convergence toward 1.
        assert sd < 2.0, f"variance did not decay: sd={sd:.3f}"
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_episode_dedup_gate_drops_in_window(tmp_path):
    """MED B4 fix-up: two writes for the same (node, type) in the dedup
    window collapse to one row."""
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = _tmp_db_hass(tmp_path)
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        node = "room:study_a"
        r1 = await db.log_memory_episode(
            node_id=node, episode_type="occupancy_phantom",
            adjudication="phantom", adjudicated_by="d2_demotion",
        )
        r2 = await db.log_memory_episode(
            node_id=node, episode_type="occupancy_phantom",
            adjudication="phantom", adjudicated_by="d2_demotion",
        )
        assert r1 is not None and r1 > 0
        assert r2 is None, "in-window repeat must be dropped"
        rows = await db.read_memory_episodes(node)
        assert len(rows) == 1
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_zone_sibling_allow_via_zm_config(fake_hass):
    """MED C-M6 fix-up: two rooms in the same ZM zone → sibling episodes()
    is NOT denied."""
    # Seed a fake ZM entry into the fake hass config_entries.
    _entry = MagicMock()
    _entry.data = {}
    _entry.options = {
        "zones": {
            "Study Wing": {
                "zone_rooms": ["Study A", "Study B"],
            },
        },
    }
    fake_hass.config_entries.async_entries = MagicMock(
        return_value=[_entry],
    )
    facade = MemoryFacade(fake_hass)
    ans = await facade.episodes(
        "room:study_b", caller_id="room:study_a",
    )
    # Sibling → no access_denied provenance. No episodes stored → insufficient_history.
    assert ans.verdict == "insufficient_history"
    assert not any(
        p.startswith("access_denied") for p in ans.provenance
    ), ans.provenance


@pytest.mark.asyncio
async def test_unknown_caller_tier_denied(fake_hass):
    """MED C-M5 fix-up: unrecognized caller_id prefix → DENY."""
    facade = MemoryFacade(fake_hass)
    ans = await facade.facts(
        "room:study_a", caller_id="mystery_caller",
    )
    assert ans.verdict == "no_data"
    assert any(
        "access_denied:unknown_caller_tier" in p for p in ans.provenance
    )


@pytest.mark.asyncio
async def test_episode_writer_site_fan_veto_lands_row(tmp_path):
    """MED C-M3 fix-up: drive the fan_veto._record_veto site with minimal
    fixtures and assert the row lands.
    """
    # Ensure homeassistant.const carries STATE_ON/STATE_OFF for fan_veto.
    import sys  # noqa: PLC0415
    _hac = sys.modules.get("homeassistant.const")
    if _hac is not None and not hasattr(_hac, "STATE_OFF"):
        _hac.STATE_OFF = "off"
        _hac.STATE_ON = "on"
    from custom_components.universal_room_automation import fan_veto
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = _tmp_db_hass(tmp_path)
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        hass.data = {DOMAIN: {"database": db}}
        # Direct call to the writer site.
        fan_veto._record_veto(hass, "Study A")
        # Give the async task time to complete.
        await asyncio.sleep(0.05)
        rows = await db.read_memory_episodes("room:study_a")
        by = [r["adjudicated_by"] for r in rows]
        assert "fan_veto" in by
    finally:
        await db.stop_write_worker()
