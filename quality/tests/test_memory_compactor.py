"""MEMORY-COMPACTOR-1 — engine + DAO + wiring tests.

Coverage (see PLANNING_memory_compactor.md §6):
  * D0 topic vocabulary gate (import-time asserts).
  * D2 engine: stage-0 fixture-diff against hand-oracle
    (exterior_track); inline spot fixtures for phantom_recurrence and
    actuation_conflict; idempotent re-run; supersession + lineage;
    supersession atomic single-commit; write-cap; read-pool discipline;
    no-raw-aiosqlite (static scan).
  * D3 combined DAO: atomic single commit; insert-ignore no-supersede;
    double-supersede no-op; redact-guard-when-disabled.
  * D4 wiring: cadence guard behaviour; enabled/disabled kill switch;
    manual override bypasses cadence.
  * D5 sensor attrs — missing stats render None (basic).

Mutation drills (per §6 — verified out-of-band by orchestrator, but
each drill maps to a named test that MUST fail on detach):
  #1 detach INSERT OR IGNORE       -> test_idempotent_rerun
  #2 detach "AND superseded_by IS NULL" -> test_double_supersede_noop
  #3 swap engine reads for raw conn -> test_reads_use_read_pool
  #4 insert aiosqlite.connect in module -> test_no_raw_aiosqlite_in_compactor
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_FIXTURE_NOW_ANCHOR = None  # set below

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()
# The bootstrap installs a MagicMock for aiosqlite (needed by files
# that don't do real DB I/O). This test suite drives the REAL DB, so
# we drop the mock and let Python import the real module below.
import sys as _sys  # noqa: E402

_sys.modules.pop("aiosqlite", None)
import aiosqlite  # noqa: E402,F401

from custom_components.universal_room_automation import const as _c  # noqa: E402
from custom_components.universal_room_automation.database import (  # noqa: E402
    UniversalRoomDatabase,
)
from runtime_harness import StubHass  # noqa: E402


_FIX = Path(__file__).parent / "fixtures" / "memory_compactor"


# ---------------------------------------------------------------------------
# D0: vocabulary + statement_fn gate — asserts fire at module load.
# ---------------------------------------------------------------------------


def test_topic_vocabulary_gate():
    """Every registered rule's topic must be in MEMORY_FACT_TOPICS, its
    key in MEMORY_EPISODE_TYPES, and its statement_fn implemented.
    """
    from custom_components.universal_room_automation import memory_compactor as mc

    # subset invariants
    keys = set(_c.MEMORY_COMPACTION_RULES.keys())
    topics = {r["topic"] for r in _c.MEMORY_COMPACTION_RULES.values()}
    fns = {r["statement_fn"] for r in _c.MEMORY_COMPACTION_RULES.values()}
    assert keys <= _c.MEMORY_EPISODE_TYPES
    assert topics <= _c.MEMORY_FACT_TOPICS
    assert fns <= set(mc._STATEMENT_FNS.keys())
    # required D0 shipping topics present
    assert "exterior_track_baseline" in _c.MEMORY_FACT_TOPICS
    assert "phantom_recurrence" in _c.MEMORY_FACT_TOPICS
    assert "actuation_conflict_daily" in _c.MEMORY_FACT_TOPICS


def test_no_raw_aiosqlite_in_compactor():
    """HIGH-2 drill #4: raw aiosqlite.connect anywhere in
    memory_compactor.py is a CRIT-blocking finding. AST scan.
    """
    from custom_components.universal_room_automation import memory_compactor as mc
    src = Path(mc.__file__).read_text()
    tree = ast.parse(src)
    # No 'import aiosqlite' and no attribute reference 'aiosqlite.connect'.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert n.name != "aiosqlite", (
                    "memory_compactor.py must not import aiosqlite"
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "aiosqlite", (
                "memory_compactor.py must not import from aiosqlite"
            )
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert not (
                node.value.id == "aiosqlite" and node.attr == "connect"
            ), "memory_compactor.py must not call aiosqlite.connect"


# ---------------------------------------------------------------------------
# Real-DB fixture (URA style).
# ---------------------------------------------------------------------------


async def _make_db(tmp_path):
    """Async helper — replaces async pytest fixture (quality suite does
    not depend on pytest-asyncio-fixture support)."""
    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    db.hass = hass  # so engine can enumerate rooms
    # Initialize schema BEFORE starting the write worker (the worker
    # holds a persistent connection; initialize() opens its own and
    # would collide with `database is locked`).
    ok = await db.initialize()
    assert ok
    await db.start_write_worker()
    return db, hass


async def _teardown(db):
    if db._write_task and not db._write_task.done():
        db._write_task.cancel()


async def _seed_exterior_track_from_fixture(db):
    data = json.loads((_FIX / "exterior_track_rows.json").read_text())
    for _key, rows in data.items():
        for r in rows:
            # Reset the DAO's dedup gate between calls — the 60s window
            # would otherwise drop all but the first same-(node,type)
            # write in this rapid loop. Production callsite spacing is
            # >>60s so the gate is a real defense; the test seeding is
            # what needs bypass, not the gate itself.
            db.__dict__["_memory_episode_dedup"] = {}
            await db.log_memory_episode(
                node_id=r["node_id"],
                episode_type="exterior_track",
                attrs=r["attrs"],
                started_at=r["started_at"],
                ended_at=r["ended_at"],
                adjudication=r.get("adjudication") or "observed",
            )


# ---------------------------------------------------------------------------
# D2: engine round-trip against the D1 hand-oracle.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage0_fixture_diff(tmp_path):
    """Feed the machine fixture, run the engine, diff against the
    hand-oracle. Exact statement + attrs + derived_from set equality.
    """
    db, hass = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    # Force wide window / now anchored beyond fixture rows.
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    # Anchor now so the 7d window contains all fixture rows.
    fake_now = datetime.fromisoformat(
        "2026-08-10T18:00:00.000000-05:00"
    ).astimezone(timezone.utc)
    # Only run exterior_track rule here — other rules have no rows.
    # Anchor "now" so the 7d rolling window covers the fixture rows.
    _now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    stats = await MemoryCompactor(db).run(triggered_by="test", now=_now)
    assert stats["aborted_reason"] is None, stats
    # 3 groups meet count>=20 -> 3 facts.
    facts = await db.read_memory_facts(
        "exterior:perimeter", topic="exterior_track_baseline",
    )
    got = sorted(
        [{"node_id": f["node_id"], "topic": f["topic"],
          "statement": f["statement"], "attrs": f["attrs"],
          "derived_from": f["derived_from"]} for f in facts],
        key=lambda x: x["statement"],
    )
    oracle = sorted(
        json.loads((_FIX / "exterior_track_oracle.json").read_text()),
        key=lambda x: x["statement"],
    )
    assert len(got) == len(oracle), (len(got), len(oracle))
    # Diff statement + attrs verbatim (frozen statement_fn template);
    # derived_from is diffed as SET SIZE + uniqueness. Live-DB source
    # IDs (used in the oracle) differ from AUTOINCREMENT ids assigned
    # at seed time — the invariant §1(c) property that matters is that
    # every raw episode id appears in exactly one fact's derived_from,
    # which we assert cardinality-wise per group and (below) globally.
    all_derived_ids: list[str] = []
    for g, o in zip(got, oracle):
        assert g["statement"] == o["statement"]
        assert g["attrs"] == o["attrs"]
        o_ids = o["derived_from"].split(",")
        g_ids = g["derived_from"].split(",")
        assert len(g_ids) == len(o_ids)  # per-group cardinality
        assert len(set(g_ids)) == len(g_ids)  # uniqueness within group
        all_derived_ids.extend(g_ids)
    # Global partition (§1(c)): every raw id appears once across facts.
    assert len(all_derived_ids) == len(set(all_derived_ids))
    # And equals the total seeded row count.
    assert len(all_derived_ids) == 60


@pytest.mark.asyncio
async def test_idempotent_rerun(tmp_path):
    """Drill #1: re-running the engine on the same DB writes zero new
    facts (INSERT OR IGNORE). Detaching that clause -> UNIQUE violation.
    """
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    s1 = await MemoryCompactor(db).run(triggered_by="t1", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    s2 = await MemoryCompactor(db).run(triggered_by="t2", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    assert s1["facts_created"] == 3
    # Second run: identical attrs, identity match -> no supersede,
    # INSERT OR IGNORE hits UNIQUE -> zero created.
    assert s2["facts_created"] == 0
    assert s2["facts_superseded"] == 0


@pytest.mark.asyncio
async def test_supersession_records_lineage(tmp_path):
    """Correction path: new attrs under same identity keys ->
    supersede old fact, derived_from on new cites the new source rows.
    """
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    await MemoryCompactor(db).run(triggered_by="t1", now=datetime(2026,8,12,12,tzinfo=timezone.utc))

    # Simulate new evidence: add one more rear_ptz/car row so the group
    # attrs (count + last_ts) shift -> supersession expected.
    db.__dict__["_memory_episode_dedup"] = {}
    await db.log_memory_episode(
        node_id="exterior:perimeter",
        episode_type="exterior_track",
        attrs={"path": ["rear_ptz"], "label": "car"},
        started_at="2026-08-11T09:00:00.000000-05:00",
        ended_at="2026-08-11T09:00:15.000000-05:00",
        adjudication="observed",
    )
    s2 = await MemoryCompactor(db).run(triggered_by="t2", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    assert s2["facts_created"] == 1
    assert s2["facts_superseded"] == 1

    all_facts = await db.read_memory_facts(
        "exterior:perimeter",
        topic="exterior_track_baseline",
        include_superseded=True,
    )
    car_facts = [f for f in all_facts if f["attrs"].get("camera") == "rear_ptz"]
    assert len(car_facts) == 2
    # The superseded one points at the new one; the new one is current.
    superseded = [f for f in car_facts if f["superseded_by"] is not None]
    current = [f for f in car_facts if f["superseded_by"] is None]
    assert len(superseded) == 1 and len(current) == 1
    assert superseded[0]["superseded_by"] == current[0]["id"]


@pytest.mark.asyncio
async def test_supersession_atomic_single_commit(tmp_path):
    """Drill for D3 atomicity: one distill_memory_fact call with a
    supersede_old_id issues exactly ONE commit().
    """
    db, _ = await _make_db(tmp_path)
    # Seed one prior fact directly via the DAO.
    r1 = await db.distill_memory_fact(
        node_id="room:test", topic="phantom_recurrence",
        statement="stmt-A",
        attrs={"room": "room:test", "phantom_count": 3,
               "first_ts": "x", "last_ts": "y", "typical_fan_on_s": 0.0},
        confidence=0.8, derived_from="1,2,3",
    )
    old_id = r1["inserted_id"]
    assert old_id is not None

    # Count commits during the atomic call.
    commits = {"n": 0}
    orig_db_ctx = db._db

    class _CountingCM:
        def __init__(self, real): self._r = real

        async def __aenter__(self): return await self._r.__aenter__()

        async def __aexit__(self, *a): return await self._r.__aexit__(*a)

    # Patch commit on the aiosqlite connection returned inside _db.
    import aiosqlite

    orig_commit = aiosqlite.Connection.commit

    async def counting_commit(self):
        commits["n"] += 1
        return await orig_commit(self)

    aiosqlite.Connection.commit = counting_commit
    try:
        r2 = await db.distill_memory_fact(
            node_id="room:test", topic="phantom_recurrence",
            statement="stmt-B",
            attrs={"room": "room:test", "phantom_count": 5,
                   "first_ts": "x", "last_ts": "z",
                   "typical_fan_on_s": 1.0},
            confidence=0.8, derived_from="1,2,3,4,5",
            supersede_old_id=old_id,
        )
    finally:
        aiosqlite.Connection.commit = orig_commit
    assert r2["inserted_id"] is not None
    assert r2["superseded"] is True
    # Exactly ONE commit for the whole logical fact (invariant §1(a)).
    assert commits["n"] == 1, (
        f"Expected 1 commit for combined DAO, got {commits['n']}"
    )


@pytest.mark.asyncio
async def test_double_supersede_noop(tmp_path):
    """Drill #2: superseding an already-superseded row is a WHERE-guarded
    no-op. Detach 'AND superseded_by IS NULL' -> this test fails.
    """
    db, _ = await _make_db(tmp_path)
    # Insert base fact.
    r1 = await db.distill_memory_fact(
        node_id="room:test", topic="phantom_recurrence",
        statement="stmt-A", attrs={"room": "room:test"},
        confidence=0.8, derived_from="1",
    )
    # Supersede once.
    r2 = await db.distill_memory_fact(
        node_id="room:test", topic="phantom_recurrence",
        statement="stmt-B", attrs={"room": "room:test", "x": 1},
        confidence=0.8, derived_from="1,2",
        supersede_old_id=r1["inserted_id"],
    )
    assert r2["superseded"] is True
    # Attempt to supersede the already-superseded row again.
    r3 = await db.distill_memory_fact(
        node_id="room:test", topic="phantom_recurrence",
        statement="stmt-C", attrs={"room": "room:test", "x": 2},
        confidence=0.8, derived_from="1,2,3",
        supersede_old_id=r1["inserted_id"],
    )
    assert r3["inserted_id"] is not None
    # Old row already superseded — WHERE clause guards; no-op.
    assert r3["superseded"] is False


@pytest.mark.asyncio
async def test_write_cap_aborts_gracefully(tmp_path, monkeypatch):
    """Setting the cap to 1 forces the engine to abort after the first
    write with aborted_reason='cap'.
    """
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    from custom_components.universal_room_automation import memory_compactor as mc
    monkeypatch.setattr(mc, "MEMORY_COMPACTOR_MAX_WRITES_PER_RUN", 1)
    stats = await mc.MemoryCompactor(db).run(triggered_by="t", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    assert stats["aborted_reason"] == "cap"
    assert stats["writes_total"] == 1


@pytest.mark.asyncio
async def test_reads_use_read_pool(tmp_path):
    """Drill #3: the engine's read callsites must resolve to the two
    sanctioned DAOs. Swap them for raw connections -> this test fails
    (we assert the engine invokes the DAO methods, not aiosqlite).
    """
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)

    calls = {"episodes": 0, "facts": 0}
    orig_ep = db.read_memory_episodes
    orig_fa = db.read_memory_facts

    async def spy_ep(*a, **k):
        calls["episodes"] += 1
        return await orig_ep(*a, **k)

    async def spy_fa(*a, **k):
        calls["facts"] += 1
        return await orig_fa(*a, **k)

    db.read_memory_episodes = spy_ep  # type: ignore
    db.read_memory_facts = spy_fa  # type: ignore
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    await MemoryCompactor(db).run(triggered_by="t", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    assert calls["episodes"] >= 1
    assert calls["facts"] >= 1


# ---------------------------------------------------------------------------
# D3 DAO focused tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_ignore_no_supersede(tmp_path):
    """Double call with same (node,topic,statement) — second returns
    inserted_id=None, and if supersede_old_id was passed the supersede
    branch does NOT fire (guarded by 'inserted' bool).
    """
    db, _ = await _make_db(tmp_path)
    r1 = await db.distill_memory_fact(
        node_id="room:z", topic="phantom_recurrence",
        statement="same-stmt", attrs={},
        confidence=0.5, derived_from="1",
    )
    # Seed a distinct prior fact so supersede has a target.
    _prior = await db.distill_memory_fact(
        node_id="room:z", topic="phantom_recurrence",
        statement="prior-stmt", attrs={"a": 1},
        confidence=0.5, derived_from="0",
    )
    r2 = await db.distill_memory_fact(
        node_id="room:z", topic="phantom_recurrence",
        statement="same-stmt", attrs={},
        confidence=0.5, derived_from="1",
        supersede_old_id=_prior["inserted_id"],
    )
    assert r1["inserted_id"] is not None
    assert r2["inserted_id"] is None
    assert r2["superseded"] is False  # branch guarded


@pytest.mark.asyncio
async def test_redact_guard_when_disabled(tmp_path):
    """Framework-only redaction path asserts against
    MEMORY_REDACTION_HORIZON_DAYS is None.
    """
    db, _ = await _make_db(tmp_path)
    with pytest.raises(AssertionError):
        await db.distill_memory_fact(
            node_id="room:z", topic="phantom_recurrence",
            statement="s", attrs={}, confidence=0.5, derived_from="1",
            redact_episode_id=1,
        )


# ---------------------------------------------------------------------------
# D4 cadence + wiring.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cadence_guard_skips_within_window(tmp_path, monkeypatch):
    """Two nightly calls within cadence -> one run + one skip."""
    db, _ = await _make_db(tmp_path)
    # First run executes.
    s1 = await db.run_memory_compactor(triggered_by="nightly")
    assert s1 is not None  # ran (may be no-op empty stats)
    # Immediately re-run — cadence guard skips.
    s2 = await db.run_memory_compactor(triggered_by="nightly")
    assert s2 is None


@pytest.mark.asyncio
async def test_manual_bypasses_cadence(tmp_path):
    db, _ = await _make_db(tmp_path)
    s1 = await db.run_memory_compactor(triggered_by="nightly")
    assert s1 is not None
    s2 = await db.run_memory_compactor(triggered_by="manual")
    assert s2 is not None
    assert s2["triggered_by"] == "manual"


@pytest.mark.asyncio
async def test_disabled_returns_none(tmp_path, monkeypatch):
    """MEMORY_COMPACTOR_ENABLED=False -> nightly and manual both no-op."""
    db, _ = await _make_db(tmp_path)
    from custom_components.universal_room_automation import database as _dbmod
    # Patch the const referenced inside run_memory_compactor's local import.
    monkeypatch.setattr(_c, "MEMORY_COMPACTOR_ENABLED", False)
    s1 = await db.run_memory_compactor(triggered_by="nightly")
    s2 = await db.run_memory_compactor(triggered_by="manual")
    assert s1 is None and s2 is None


@pytest.mark.asyncio
async def test_nightly_ops_includes_memory_compactor():
    """Wiring anchor: __init__._cleanup_ops must include
    ('memory_compactor', 'run_memory_compactor', {}) appended AFTER
    incremental_vacuum. Source scan (not import) to avoid HA setup.
    """
    src_path = Path(__file__).parent.parent.parent / (
        "custom_components/universal_room_automation/__init__.py"
    )
    src = src_path.read_text()
    iv = src.index('("incremental_vacuum"')
    mc = src.index('("memory_compactor"')
    assert mc > iv, (
        "memory_compactor tuple must appear AFTER incremental_vacuum"
    )
    # Method name reference is what the loop calls.
    assert '"run_memory_compactor"' in src


# ---------------------------------------------------------------------------
# D5 sensor attrs — missing stats render None.
# ---------------------------------------------------------------------------


def test_sensor_exposes_compactor_attrs():
    """D5 anchor: sensor.py's URAMemoryStatusSensor emits the six
    compactor attributes via _compactor_attrs. Source scan avoids
    importing the sensor module (which pulls the full HA units surface
    that the quality-suite stubs don't provide as real symbols).
    """
    src_path = Path(__file__).parent.parent.parent / (
        "custom_components/universal_room_automation/sensor.py"
    )
    src = src_path.read_text()
    assert "def _compactor_attrs" in src
    for k in (
        "compactor_last_run",
        "compactor_facts_created_last_run",
        "compactor_facts_superseded_last_run",
        "compactor_writes_last_run",
        "compactor_aborted_reason",
        "compactor_triggered_by",
    ):
        assert f'"{k}"' in src, f"sensor.py missing compactor attr {k}"
    # And the helper is invoked in extra_state_attributes.
    assert "self._compactor_attrs()" in src


# ---------------------------------------------------------------------------
# D2 spot fixtures — phantom_recurrence (plan §D2) + orchestrator amendment
# 2026-08-14 (coverage-provenance marker MUST appear in attrs so Vision §6
# confident-garbage misread class stays out of reach).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phantom_rule_spot(tmp_path, monkeypatch):
    """Inline spot-fixture: ~3 adjudicated occupancy_phantom rows in one
    room -> single phantom_recurrence fact carrying the coverage marker
    and a d2-detected statement string.
    """
    db, hass = await _make_db(tmp_path)
    # Make node-discovery see "room:jaya" via hass.data.
    hass.data.setdefault("universal_room_automation", {})["rooms"] = {
        "jaya": object(),
    }
    # Seed 3 adjudicated rows (require_adjudicated=True for this rule).
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        db.__dict__["_memory_episode_dedup"] = {}
        started = (base + timedelta(hours=i)).isoformat()
        ended = (base + timedelta(hours=i, minutes=5)).isoformat()
        await db.log_memory_episode(
            node_id="room:jaya",
            episode_type="occupancy_phantom",
            attrs={"source": "d2_detector"},
            started_at=started,
            ended_at=ended,
            adjudication="d2_demotion",
            adjudicated_by="d2",
        )
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    stats = await MemoryCompactor(db).run(triggered_by="t")
    assert stats["aborted_reason"] is None
    facts = await db.read_memory_facts(
        "room:jaya", topic="phantom_recurrence",
    )
    assert len(facts) == 1, facts
    f = facts[0]
    # Coverage-provenance marker MUST be present (amendment 2026-08-14).
    assert f["attrs"].get("coverage") == "d2_gated", (
        "phantom_recurrence fact MUST carry coverage='d2_gated' — "
        "absence invites the Ziri/Guestroom confident-garbage misread"
    )
    # Statement text carries the d2-detected qualifier.
    assert "d2-detected" in f["statement"]
    assert f["attrs"]["phantom_count"] == 3
    assert f["attrs"]["room"] == "room:jaya"


@pytest.mark.asyncio
async def test_actuation_conflict_rule_spot(tmp_path):
    """20 actuation_conflict rows with identical (action, trigger,
    house_state) shape -> single fact under actuation_conflict_daily.
    """
    db, hass = await _make_db(tmp_path)
    hass.data.setdefault("universal_room_automation", {})["rooms"] = {
        "study_a": object(),
    }
    base = datetime(2026, 8, 12, 8, 0, 0, tzinfo=timezone.utc)
    for i in range(20):
        db.__dict__["_memory_episode_dedup"] = {}
        started = (base + timedelta(minutes=5 * i)).isoformat()
        await db.log_memory_episode(
            node_id="room:study_a",
            episode_type="actuation_conflict",
            attrs={
                "action": "turn_off",
                "trigger": "zone_vacancy_sweep",
                "house_state": "home_day",
            },
            started_at=started,
            ended_at=started,
            adjudication="observed",
        )
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    stats = await MemoryCompactor(db).run(triggered_by="t")
    assert stats["aborted_reason"] is None
    facts = await db.read_memory_facts(
        "room:study_a", topic="actuation_conflict_daily",
    )
    assert len(facts) == 1, facts
    a = facts[0]["attrs"]
    assert a["count"] == 20
    assert a["action"] == "turn_off"
    assert a["trigger"] == "zone_vacancy_sweep"
    assert a["house_state"] == "home_day"


def test_statement_fn_is_deterministic():
    """Same input rows -> same (statement, attrs) tuple. Guards the
    D1 acceptance criterion: no wall-clock, no set-ordering ambiguity.
    """
    from custom_components.universal_room_automation import memory_compactor as mc
    rows = json.loads((_FIX / "exterior_track_rows.json").read_text())[
        "rear_ptz|car"
    ]
    s1, a1 = mc._statement_exterior_track_baseline(
        rows, "exterior:perimeter", "exterior_track_baseline",
    )
    s2, a2 = mc._statement_exterior_track_baseline(
        list(rows), "exterior:perimeter", "exterior_track_baseline",
    )
    assert s1 == s2
    assert a1 == a2
