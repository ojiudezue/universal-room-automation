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

Mutation drills (per §6 + fix-up 2026-08-14 additions; each drill
maps to a named test that MUST go red on detach and green on restore):
  #1 detach INSERT OR IGNORE            -> test_idempotent_rerun
  #2 detach "AND superseded_by IS NULL" -> test_double_supersede_noop
  #3 swap engine reads for raw conn     -> test_reads_use_read_pool
  #4 aiosqlite reference anywhere in the compactor module (C2 fix:
     covers direct imports, attribute access, AND string-constant
     evasions such as importlib.import_module("aiosqlite"))
                                        -> test_no_raw_aiosqlite_in_compactor
  #5 neuter read_distinct_nodes_for_episodes -> return []
     (HIGH-A1 fix — sanctioned third read DAO on _db_read)
     -> test_drill5_room_scoped_rule_distills_via_new_dao
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
import pytest_asyncio

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
    assert "actuation_conflict_summary" in _c.MEMORY_FACT_TOPICS


def test_no_raw_aiosqlite_in_compactor():
    """HIGH-2 drill #4: raw aiosqlite anywhere in memory_compactor.py
    is a CRIT-blocking finding. AST scan covers:
      * ``import aiosqlite`` / ``from aiosqlite import ...``
      * ``aiosqlite.connect`` attribute access
      * ANY ``ast.Constant`` whose value is the string ``"aiosqlite"``
        — closes the importlib evasion caught by Review C2 (2026-08-14):
        ``importlib.import_module("aiosqlite")`` / ``__import__("aiosqlite")``
        would otherwise green-light a fresh raw-connection path.
    The module has zero legitimate reason to name that string.
    """
    from custom_components.universal_room_automation import memory_compactor as mc
    src = Path(mc.__file__).read_text()
    tree = ast.parse(src)
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
        # C2 fix: string-constant evasion guard.
        if isinstance(node, ast.Constant) and node.value == "aiosqlite":
            raise AssertionError(
                "memory_compactor.py must not reference the string "
                "'aiosqlite' anywhere (importlib.import_module / "
                "__import__ evasion path). See Review C2."
            )


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
    # SUITE-WEDGE fix (2026-08-23): register for guaranteed teardown. Each
    # UniversalRoomDatabase starts an aiosqlite worker whose connection lives
    # in an `async with` inside a NON-DAEMON thread. If it is never closed the
    # thread never exits, and CPython's interpreter shutdown blocks forever in
    # threading._shutdown joining it — the process hangs AFTER the tests pass.
    # Measured: tests complete in 1.17s, process still alive at 30s (rc=124),
    # four leaked aiosqlite worker threads in the fault-handler dump.
    _OPEN_DBS.append(db)
    return db, hass


# SUITE-WEDGE fix (2026-08-23): every db handed out by _make_db lands here so
# the autouse fixture below can close it even when a test raises.
_OPEN_DBS: list = []


async def _teardown(db):
    """Close the DB properly.

    WAS BROKEN AND NEVER CALLED. The old body did a bare
    `db._write_task.cancel()` with NO await, and nothing in the module ever
    invoked it. Cancelling without awaiting means the worker's
    CancelledError handler never runs, so the `async with
    aiosqlite.connect(...)` block never exits and its connection — plus the
    non-daemon thread servicing it — leaks for the life of the process.
    `stop_write_worker()` is the supported close: it cancels AND awaits, which
    is what actually unwinds the context manager (database.py:161).
    """
    try:
        await db.stop_write_worker()
    except Exception:  # noqa: BLE001 — teardown must never mask a test failure
        pass


@pytest_asyncio.fixture(autouse=True)
async def _close_dbs_after_each_test():
    """Guarantee DB teardown regardless of how the test exits.

    MUST be async and MUST share the test's event loop. A sync fixture that
    spins up its own loop CANNOT unwind these connections: the aiosqlite
    connection and its `async with` live on the loop that created them, so
    cancelling from a foreign loop leaves the context manager open and the
    non-daemon worker thread alive. Verified empirically — the sync version
    of this fixture left the process wedged at rc=124.

    Autouse rather than per-test cleanup because there are ~15 `_make_db`
    call sites and a missed one silently reintroduces the hang. The failure
    mode is invisible (tests still PASS) and only surfaces as a wedged
    process that kills the NEXT suite run.
    """
    yield
    while _OPEN_DBS:
        await _teardown(_OPEN_DBS.pop())


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
async def test_idempotent_rerun(tmp_path, caplog):
    """Drill #1: re-running the engine on the same DB writes zero new
    facts AND logs ZERO warnings (INSERT OR IGNORE turns the second
    write into a clean UNIQUE-index no-op). Detaching INSERT OR IGNORE
    -> the second run raises IntegrityError inside the DAO, which the
    DAO's broad-except swallows and logs as "distill_memory_fact failed"
    — that log line is what fails this test.
    """
    import logging as _lg
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    s1 = await MemoryCompactor(db).run(triggered_by="t1", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    caplog.clear()
    caplog.set_level(_lg.WARNING,
                     logger="custom_components.universal_room_automation.database")
    s2 = await MemoryCompactor(db).run(triggered_by="t2", now=datetime(2026,8,12,12,tzinfo=timezone.utc))
    assert s1["facts_created"] == 3
    # Second run: identical attrs, identity match -> no supersede,
    # INSERT OR IGNORE hits UNIQUE -> zero created.
    assert s2["facts_created"] == 0
    assert s2["facts_superseded"] == 0
    # Drill anchor: no exception log from the DAO. Without
    # INSERT OR IGNORE the second run's INSERT would raise
    # IntegrityError which the DAO swallows and logs as WARNING.
    dao_warnings = [
        r for r in caplog.records
        if "distill_memory_fact failed" in r.getMessage()
    ]
    assert not dao_warnings, (
        "Expected zero DAO warnings on idempotent re-run — got: "
        f"{[r.getMessage() for r in dao_warnings]}"
    )


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
    EFFECTIVE write with aborted_reason='cap'. Fix-up B-LOW-2
    (2026-08-14): ``writes_total`` counts only effective writes
    (inserted/superseded/redacted); INSERT-OR-IGNORE no-ops go into
    ``distill_calls`` only, so cap-abort resumability isn't burned by
    re-run idempotency.
    """
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    from custom_components.universal_room_automation import memory_compactor as mc
    monkeypatch.setattr(mc, "MEMORY_COMPACTOR_MAX_WRITES_PER_RUN", 1)
    stats = await mc.MemoryCompactor(db).run(
        triggered_by="t",
        now=datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
    )
    assert stats["aborted_reason"] == "cap"
    assert stats["writes_total"] == 1
    # Distill calls == effective writes on a fresh DB (first pass).
    assert stats["distill_calls"] == 1


@pytest.mark.asyncio
async def test_cap_not_burned_by_insert_ignore_noops(tmp_path, monkeypatch):
    """B-LOW-2 (2026-08-14): a rerun after cap-abort must NOT consume
    write-cap slots on INSERT-OR-IGNORE no-ops. First run to
    completion, second run at cap=2 must not abort — the three
    existing exterior_track facts are IGNOREd, ``writes_total`` stays
    at 0, ``distill_calls`` counts the three DAO calls.
    """
    db, _ = await _make_db(tmp_path)
    await _seed_exterior_track_from_fixture(db)
    from custom_components.universal_room_automation import memory_compactor as mc
    anchor = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    # First run — no cap, all 3 facts written.
    s1 = await mc.MemoryCompactor(db).run(triggered_by="t1", now=anchor)
    assert s1["facts_created"] == 3
    assert s1["writes_total"] == 3
    # Second run at cap=2 — every group is a UNIQUE-index no-op, so
    # writes_total stays 0 (well under cap=2) and the engine completes
    # cleanly rather than aborting mid-loop.
    monkeypatch.setattr(mc, "MEMORY_COMPACTOR_MAX_WRITES_PER_RUN", 2)
    s2 = await mc.MemoryCompactor(db).run(triggered_by="t2", now=anchor)
    assert s2["aborted_reason"] is None, s2
    assert s2["writes_total"] == 0
    assert s2["facts_created"] == 0
    # Three distill calls happened even though zero effective writes —
    # observability delta so a real starvation scenario is visible.
    assert s2["distill_calls"] == 3


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
    """MEMORY_COMPACTOR_ENABLED=False -> nightly and manual both no-op.

    run_memory_compactor imports the const via ``from .const import
    MEMORY_COMPACTOR_ENABLED`` at call time; patch BOTH the const
    module attribute AND the sys.modules identity to defend against
    dual-module aliasing under full-suite import order.
    """
    import sys as _sys
    db, _ = await _make_db(tmp_path)
    # Resolve the exact module reference that run_memory_compactor sees.
    _cm = _sys.modules[
        "custom_components.universal_room_automation.const"
    ]
    monkeypatch.setattr(_cm, "MEMORY_COMPACTOR_ENABLED", False)
    s1 = await db.run_memory_compactor(triggered_by="nightly")
    s2 = await db.run_memory_compactor(triggered_by="manual")
    assert s1 is None and s2 is None


def _extract_cleanup_ops_names(src: str, list_name: str) -> list[str]:
    """AST-parse __init__.py and return the ordered list of op-names
    from the assignment `<list_name> = [ ("name", "method", {}), ... ]`.
    Returns the first-tuple-element strings so tests can assert
    presence + relative order without brittle substring scanning.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Name) or tgt.id != list_name:
                continue
            if not isinstance(node.value, ast.List):
                continue
            out: list[str] = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple) and elt.elts:
                    first = elt.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(
                        first.value, str,
                    ):
                        out.append(first.value)
            return out
    return []


@pytest.mark.asyncio
async def test_nightly_ops_includes_memory_compactor():
    """Wiring anchor (C1/B-HIGH-1 fix, 2026-08-14): AST-parse both the
    primary ``_cleanup_ops`` and the deferred-startup
    ``_cleanup_ops_d`` list literals in ``__init__.py``. Assert that
    ``memory_compactor`` appears in BOTH (after ``incremental_vacuum``
    in both). Prior source-scan anchor was hollow — the single primary
    substring passed while the deferred branch was missing the
    compactor entirely.
    """
    src_path = Path(__file__).parent.parent.parent / (
        "custom_components/universal_room_automation/__init__.py"
    )
    src = src_path.read_text()
    primary = _extract_cleanup_ops_names(src, "_cleanup_ops")
    deferred = _extract_cleanup_ops_names(src, "_cleanup_ops_d")
    assert primary, "could not AST-extract _cleanup_ops list"
    assert deferred, "could not AST-extract _cleanup_ops_d list"
    # Presence in BOTH.
    for lst_name, lst in (("_cleanup_ops", primary),
                           ("_cleanup_ops_d", deferred)):
        assert "memory_compactor" in lst, (
            f"{lst_name} missing 'memory_compactor' entry — "
            f"deferred-startup boots would never run the compactor"
        )
        assert "incremental_vacuum" in lst
        # Compactor AFTER incremental_vacuum in both (rides at end).
        assert lst.index("memory_compactor") > lst.index("incremental_vacuum"), (
            f"'memory_compactor' must appear AFTER 'incremental_vacuum' "
            f"in {lst_name}"
        )


def test_cleanup_ops_deferred_mirrors_primary():
    """Permanent parity guard (B-HIGH-1 recommendation, Bug Class #27):
    the deferred-startup ``_cleanup_ops_d`` MUST contain every op-name
    that the primary ``_cleanup_ops`` contains. Prevents the class of
    drift that has now claimed four fix-ups in this file (see
    egress_state, optimizer prunes, shadow_samples, decision_log,
    incremental_vacuum, and now memory_compactor).
    """
    src_path = Path(__file__).parent.parent.parent / (
        "custom_components/universal_room_automation/__init__.py"
    )
    src = src_path.read_text()
    primary = set(_extract_cleanup_ops_names(src, "_cleanup_ops"))
    deferred = set(_extract_cleanup_ops_names(src, "_cleanup_ops_d"))
    missing = primary - deferred
    assert not missing, (
        "Deferred-startup nightly branch is missing ops present in the "
        f"primary branch: {sorted(missing)}. Every op added to "
        "_cleanup_ops must be mirrored into _cleanup_ops_d (Bug Class "
        "#27, see repeated fix-up history in __init__.py)."
    )


# ---------------------------------------------------------------------------
# D5 sensor attrs — behavioral round-trip (C3 fix) + source-scan.
# ---------------------------------------------------------------------------


def test_sensor_exposes_compactor_attrs():
    """D5 anchor (C3 fix, 2026-08-14): the source-scan alone is hollow
    — renaming a getter argument (``stats.get("finshed_at")``) leaves
    the string literals intact but breaks the read. Behavioral arm
    below drives ``_compactor_attrs`` with a fake DB carrying a real
    stats dict and asserts every key's value round-trips. A typo in
    any read-site key will fail one of the value assertions.
    """
    # Source-scan half — cheap upstream guard.
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
        "compactor_distill_calls_last_run",
        "compactor_skipped_missing_identity_last_run",
        "compactor_aborted_reason",
        "compactor_triggered_by",
    ):
        assert f'"{k}"' in src, f"sensor.py missing compactor attr {k}"
    assert "self._compactor_attrs()" in src

    # Behavioral half — exec _compactor_attrs directly against source.
    # We can't import sensor.py (HA units stubs); pull the source of
    # _compactor_attrs, wrap it as a module-level function, and
    # evaluate against a fake self+DB.
    import ast as _ast
    tree = _ast.parse(src)
    fn_src: str | None = None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name == "_compactor_attrs":
            fn_src = _ast.unparse(node)
            break
    assert fn_src is not None, "could not locate _compactor_attrs in sensor.py"

    # Keep `self` parameter name; pass fake self positionally. Rename
    # only the function name so we can pull it out of the namespace.
    src_fn = fn_src.replace(
        "def _compactor_attrs(self)", "def _fn(self)",
    )
    # Provide DOMAIN token the function reads via self.hass.data.
    ns: dict = {"DOMAIN": "universal_room_automation", "getattr": getattr}
    exec(src_fn, ns)  # noqa: S102

    class _DB:
        _last_compactor_stats = {
            "finished_at": "2026-08-14T02:30:15+00:00",
            "facts_created": 3,
            "facts_superseded": 1,
            "writes_total": 4,
            "distill_calls": 5,
            "skipped_missing_identity": 2,
            "aborted_reason": None,
            "triggered_by": "manual",
        }

    class _Hass:
        data = {"universal_room_automation": {"database": _DB()}}

    class _Self:
        hass = _Hass()

    attrs = ns["_fn"](_Self())
    assert attrs["compactor_last_run"] == "2026-08-14T02:30:15+00:00"
    assert attrs["compactor_facts_created_last_run"] == 3
    assert attrs["compactor_facts_superseded_last_run"] == 1
    assert attrs["compactor_writes_last_run"] == 4
    assert attrs["compactor_distill_calls_last_run"] == 5
    assert attrs["compactor_skipped_missing_identity_last_run"] == 2
    assert attrs["compactor_aborted_reason"] is None
    assert attrs["compactor_triggered_by"] == "manual"

    # None-render pre-first-run path.
    class _DBNone:
        _last_compactor_stats = None

    class _HassNone:
        data = {"universal_room_automation": {"database": _DBNone()}}

    class _SelfNone:
        hass = _HassNone()

    none_attrs = ns["_fn"](_SelfNone())
    assert all(v is None for v in none_attrs.values())


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
    house_state) shape -> single fact under actuation_conflict_summary.
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
        "room:study_a", topic="actuation_conflict_summary",
    )
    assert len(facts) == 1, facts
    a = facts[0]["attrs"]
    assert a["count"] == 20
    assert a["action"] == "turn_off"
    assert a["trigger"] == "zone_vacancy_sweep"
    assert a["house_state"] == "home_day"
    # MED-A3 rename: window_span_s must be present and >=0 (95 min in
    # this fixture => 5700s).
    assert "window_span_s" in a
    assert a["window_span_s"] >= 0
    assert "summary" in facts[0]["statement"]
    assert "window_span_s=" in facts[0]["statement"]


# ---------------------------------------------------------------------------
# Drill #5 — data-driven node discovery via new read DAO (HIGH-A1 fix).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drill5_room_scoped_rule_distills_via_new_dao(tmp_path):
    """Fix-up HIGH-A1 anchor: room-scoped rules must produce facts.

    Seed occupancy_phantom rows on multiple rooms; run the compactor;
    the new ``read_distinct_nodes_for_episodes`` DAO must enumerate
    them and each qualifying room must get one phantom_recurrence
    fact. Neuter the DAO (return []) -> this test MUST go red
    (drill #5). Before this cycle the room-scoped rules silently
    distilled nothing because node discovery leaned on a nonexistent
    hass.data key.
    """
    db, hass = await _make_db(tmp_path)
    base = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    for room in ("jaya", "study_a"):
        for i in range(3):
            db.__dict__["_memory_episode_dedup"] = {}
            started = (base + timedelta(hours=i)).isoformat()
            ended = (base + timedelta(hours=i, minutes=5)).isoformat()
            await db.log_memory_episode(
                node_id=f"room:{room}",
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
    stats = await MemoryCompactor(db).run(
        triggered_by="t",
        now=datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert stats["aborted_reason"] is None, stats
    # Both rooms distilled — HIGH-A1 previously produced 0 here.
    f_jaya = await db.read_memory_facts(
        "room:jaya", topic="phantom_recurrence",
    )
    f_study = await db.read_memory_facts(
        "room:study_a", topic="phantom_recurrence",
    )
    assert len(f_jaya) == 1
    assert len(f_study) == 1
    # And the DAO itself returns both nodes for the type/window.
    nodes = await db.read_distinct_nodes_for_episodes(
        "occupancy_phantom",
        (datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
         - timedelta(days=30)).isoformat(),
    )
    assert sorted(nodes) == ["room:jaya", "room:study_a"]


# ---------------------------------------------------------------------------
# MED-A2 — identity_keys missing surfaces a counter + WARNING.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_keys_missing_warns_and_counts(tmp_path, caplog):
    """When an actuation_conflict row lacks one of the identity keys
    (e.g. no 'trigger'), the engine must count the skip in
    stats['skipped_missing_identity'] and log a WARNING once per rule.
    Guards against silent under-distillation on upstream shape drift.
    """
    import logging as _lg
    db, hass = await _make_db(tmp_path)
    base = datetime(2026, 8, 12, 8, 0, 0, tzinfo=timezone.utc)
    # 20 well-formed + 5 missing-trigger rows for the same room.
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
    for i in range(5):
        db.__dict__["_memory_episode_dedup"] = {}
        started = (base + timedelta(hours=3, minutes=i)).isoformat()
        await db.log_memory_episode(
            node_id="room:study_a",
            episode_type="actuation_conflict",
            attrs={
                "action": "turn_off",
                # NOTE: 'trigger' intentionally omitted.
                "house_state": "home_day",
            },
            started_at=started,
            ended_at=started,
            adjudication="observed",
        )
    caplog.set_level(
        _lg.WARNING,
        logger="custom_components.universal_room_automation.memory_compactor",
    )
    from custom_components.universal_room_automation.memory_compactor import (
        MemoryCompactor,
    )
    stats = await MemoryCompactor(db).run(
        triggered_by="t",
        now=datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert stats["skipped_missing_identity"] == 5, stats
    warn_msgs = [
        r.getMessage() for r in caplog.records
        if "missing identity_keys" in r.getMessage()
    ]
    assert warn_msgs, (
        "MED-A2 fix expected a WARNING when identity keys are missing"
    )


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
