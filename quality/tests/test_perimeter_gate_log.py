"""PERIMETER-GATE-EVIDENCE D2: one memory_episodes row per gate decision.

Plan: PLANNING_perimeter_gate_evidence_and_input_health.md D2 (INV-ROW).
Rows land in a REAL ``UniversalRoomDatabase`` (its own DDL, its own write
queue — never hand-copied schema); alerts enter through the REAL handler
(`_async_handle_perimeter_trigger`) of the shared perimeter harness. The
expected row counts are derived by hand from the plan's gate table.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from unittest.mock import MagicMock

import pytest

from custom_components.universal_room_automation import const as ura_const
from test_perimeter_fp_gates import (  # noqa: E402
    DB_KEY,
    DB_PR,
    RP_KEY,
    RP_PR,
    Severity,
    _St,
    _d5,
    _d105,
    _drive,
    _perimeter,
    _sev,
)

EPISODE = "perimeter_gate_decision"


async def _real_db(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    db_hass = MagicMock()
    db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    db_hass.async_create_task = _sched
    db_hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(db_hass)
    assert await db.initialize()
    await db.start_write_worker()
    return db


def _rows(db):
    conn = sqlite3.connect(db.db_file)
    try:
        return [
            (node, json.loads(attrs), src)
            for node, attrs, src in conn.execute(
                "SELECT node_id, attrs_json, source_ref FROM memory_episodes "
                "WHERE episode_type = ? ORDER BY id", (EPISODE,),
            )
        ]
    finally:
        conn.close()


def _wire(hass, mgr, db):
    hass.data[ura_const.DOMAIN]["database"] = db
    hass.async_create_task = lambda coro, *a, **k: asyncio.ensure_future(coro)


async def _flush(mgr):
    for _ in range(5):
        await asyncio.sleep(0)
    for t in list(mgr._gate_log_tasks):
        await t


def _spy(mgr):
    calls: list = []
    real = mgr._record_gate

    def _rec(k, d):
        calls.append((k, d.get("gate")))
        return real(k, d)
    mgr._record_gate = _rec
    return calls


def _sun(hass, elev):
    hass._states["sun.sun"] = _St("above_horizon" if elev >= 0 else "below_horizon",
                                  {"elevation": elev})


# --------------------------------------------------------------------------

def test_d5_and_d6_same_alert_two_rows(monkeypatch, tmp_path):
    """One alert: D5 (shadow) then D6 (shadow) -> two rows with distinct
    source_ref. Fails if window_dedup is left at its default (same node_id
    inside 60 s drops the second row)."""
    db, mgr, nm = _run_d5_d6(monkeypatch, tmp_path)
    rows = _rows(db)
    gates = [a["gate"] for _n, a, _s in rows]
    assert gates.count("single_source") == 1 and gates.count("vlm") == 1
    assert len({s for _n, _a, s in rows}) == len(rows)
    assert all(n == f"perimeter_gate:{RP_KEY}" for n, _a, _s in rows)
    assert _sev(nm) == Severity.CRITICAL


def _run_d5_d6(monkeypatch, tmp_path):
    """Build the D6 rig with D5 shadow on, then drive the alert and the DB
    in ONE loop."""
    from test_perimeter_fp_gates import _build, _const, _setup
    import custom_components.universal_room_automation.perimeter_enrichment as pe
    from test_perimeter_fp_gates import RP_CAM
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_VLM_GATE: "shadow",
        _const.CONF_PERIMETER_SINGLE_SOURCE_DEMOTE: False,
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [RP_PR],
    })
    mgr, _subs = _setup(hass, monkeypatch)
    mgr._agreement.load_dict({"outcomes": {RP_KEY: [True] * 20}})

    async def _svc(domain, service, data, **kw):
        return {"response_text": "PERSON: YES\nLOCATION: STREET\nA man."}
    hass.services.async_call = _svc
    path = "/media/ura/snapshots/rear_ptz_x.jpg"

    async def _cap(_eid):
        mgr._last_snapshot_capture[RP_KEY] = {"path": path, "engine": "frigate_event"}
        return path
    mgr._await_edge_capture = _cap

    async def _go():
        db = await _real_db(tmp_path)
        # after the DB made its directory (os.path.exists is global)
        monkeypatch.setattr(pe.os.path, "exists", lambda p: True)
        _wire(hass, mgr, db)
        await mgr._async_handle_perimeter_trigger(RP_PR)
        await _flush(mgr)
        await db.stop_write_worker()
        return db
    db = asyncio.run(_go())
    return db, mgr, nm


def test_one_row_per_record_gate_call(monkeypatch, tmp_path):
    """Every gate function, through its demote branch (and the D1 night /
    D10.5 gate_off non-demote paths), writes exactly one row per
    _record_gate call."""
    total_calls = 0
    total_rows = 0

    async def _drive_with_db(hass, mgr, coro_fn):
        db = await _real_db(tmp_path)
        _wire(hass, mgr, db)
        calls = _spy(mgr)
        await coro_fn()
        await _flush(mgr)
        await db.stop_write_worker()
        return db, calls

    # D5 demote (day, enforce)
    hass, nm, mgr = _d5(monkeypatch)
    db, calls = asyncio.run(_drive_with_db(hass, mgr, lambda: _drive(mgr, RP_PR)))
    assert _sev(nm) == Severity.LOW
    assert [g for _k, g in calls] == ["single_source"]
    rows = _rows(db)
    assert [(a["gate"], a["reason"], a["demoted"]) for _n, a, _s in rows] == [
        ("single_source", "single_source", True)]
    total_calls += len(calls)
    total_rows += len(rows)
    os.remove(db.db_file)

    # D5 night (no demote) -> still one row
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, -30.0)
    db, calls = asyncio.run(_drive_with_db(hass, mgr, lambda: _drive(mgr, RP_PR)))
    rows = _rows(db)
    assert [(a["gate"], a["reason"], a["is_day"]) for _n, a, _s in rows] == [
        ("single_source", "night", False)]
    os.remove(db.db_file)

    # D10.5 uncorroborated demote (day) -> one row
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    db, calls = asyncio.run(_drive_with_db(
        hass, mgr, lambda: _drive(mgr, DB_PR, fire_delays=(20,))))
    assert _sev(nm) == Severity.LOW
    rows = _rows(db)
    eg = [a for _n, a, _s in rows if a["gate"] == "egress_identity"]
    assert len(eg) == 1 and eg[0]["reason"] == "egress_uncorroborated"
    assert len(rows) == len(calls)
    os.remove(db.db_file)

    # D10.5 gate_off early return -> one row
    hass, nm, mgr = _d105(monkeypatch)
    hass.config_entries.async_entries.return_value[0].options[
        ura_const.CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE] = False
    db, calls = asyncio.run(_drive_with_db(
        hass, mgr, lambda: mgr._async_handle_perimeter_trigger(DB_PR)))
    rows = _rows(db)
    eg = [a for _n, a, _s in rows if a["gate"] == "egress_identity"]
    assert len(eg) == 1 and eg[0]["reason"] == "gate_off"
    assert len(rows) == len(calls)
    os.remove(db.db_file)

    # D3 zone agreement + D6: driven directly (their own demote branches)
    hass, nm, mgr = _d5(monkeypatch)

    async def _d3_d6():
        mgr._zoned_cameras = {"camera.rear_ptz_high_resolution_channel": ["z"]}
        mgr._zone_map = {"z": {"frigate_name": "rear_ptz", "zone_slug": "yard"}}
        mgr._sensor_to_camera[RP_PR] = "camera.rear_ptz_high_resolution_channel"
        from datetime import timedelta  # noqa: PLC0415
        now = _perimeter.dt_util.now()
        mgr._frigate_event_cache["rear_ptz"] = {
            "entered_zones": ["street"], "received_at": now - timedelta(seconds=1)}
        hass.config_entries.async_entries.return_value[0].options[
            ura_const.CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE] = True
        s1 = mgr._apply_zone_agreement_gate(RP_KEY, RP_PR, now, Severity.CRITICAL, False)
        assert s1 == Severity.LOW
        mgr._last_snapshot_capture[RP_KEY] = {"path": "/s/a.jpg", "engine": "frigate_event"}
        s2 = mgr._apply_vlm_gate(RP_KEY, RP_PR, Severity.CRITICAL, "NO",
                                 "/s/a.jpg", False, "enforce")
        assert s2 == Severity.LOW
    db, calls = asyncio.run(_drive_with_db(hass, mgr, _d3_d6))
    rows = _rows(db)
    assert sorted((a["gate"], a["demoted"]) for _n, a, _s in rows) == [
        ("vlm", True), ("zone_agreement", True)]
    assert len(rows) == len(calls) == 2


def test_followup_record_writes_one_row(monkeypatch, tmp_path):
    hass, _nm, mgr = _d5(monkeypatch)

    async def _go():
        db = await _real_db(tmp_path)
        _wire(hass, mgr, db)
        edge = _perimeter.dt_util.now()
        state = {"edge": edge, "entity_id": RP_PR, "severity": Severity.HIGH,
                 "elapsed": 5.0, "unsub": None}
        mgr._pending_followups[RP_KEY] = state
        mgr._known_identity_for = lambda k, e: ("oji_udezue", 0.95, "face_leg")
        mgr.hass.async_create_task = lambda coro, *a, **k: asyncio.ensure_future(coro)
        mgr._async_send_identity_followup = lambda st, slug: asyncio.sleep(0)
        mgr._followup_check(RP_KEY, state)
        await _flush(mgr)
        await db.stop_write_worker()
        return db
    db = asyncio.run(_go())
    rows = _rows(db)
    assert [(a["gate"], a["identity"]) for _n, a, _s in rows] == [
        ("identity_followup", "oji_udezue")]
    assert rows[0][1]["is_day"] is True and rows[0][1]["sun_elevation"] == 35.0


def test_writer_failure_never_blocks_alert(monkeypatch):
    class _Boom:
        async def log_memory_episode(self, **kw):
            raise RuntimeError("disk full")

    hass, nm, mgr = _d5(monkeypatch)

    async def _go():
        _wire(hass, mgr, _Boom())
        await _drive(mgr, RP_PR)
        await _flush(mgr)
    asyncio.run(_go())
    assert nm.async_notify.await_count == 1 and _sev(nm) == Severity.LOW
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "single_source"

    # create_task itself raising -> still no escape, same severity
    hass, nm, mgr = _d5(monkeypatch)
    hass.data[ura_const.DOMAIN]["database"] = _Boom()

    def _raise(coro, *a, **k):
        coro.close()
        raise RuntimeError("loop closed")
    hass.async_create_task = _raise
    asyncio.run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.LOW

    # no database at all
    hass, nm, mgr = _d5(monkeypatch)
    hass.data[ura_const.DOMAIN].pop("database", None)
    asyncio.run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.LOW and mgr._gate_log_tasks == set()


def test_no_row_after_teardown(monkeypatch, tmp_path):
    hass, _nm, mgr = _d5(monkeypatch)

    async def _go():
        db = await _real_db(tmp_path)
        _wire(hass, mgr, db)
        await mgr.async_teardown()
        mgr._record_gate(RP_KEY, {"gate": "identity_followup",
                                  "at": "2026-11-13T20:00:00"})
        assert mgr._gate_log_tasks == set()
        await _flush(mgr)
        await db.stop_write_worker()
        return db
    db = asyncio.run(_go())
    assert _rows(db) == []
    # the in-memory dict is still written (display surface unchanged)
    assert "identity_followup" in mgr._last_gate_decisions[RP_KEY]


def test_teardown_gathers_inflight_write(monkeypatch, tmp_path):
    hass, _nm, mgr = _d5(monkeypatch)

    async def _go():
        db = await _real_db(tmp_path)
        _wire(hass, mgr, db)
        real = db.log_memory_episode
        gate = asyncio.Event()

        async def _slow(**kw):
            await gate.wait()
            return await real(**kw)
        db.log_memory_episode = _slow
        mgr._record_gate(RP_KEY, {"gate": "single_source", "at": "2026-11-13T12:00:00",
                                  "reason": "shadow"})
        assert len(mgr._gate_log_tasks) == 1
        asyncio.get_running_loop().call_later(0.05, gate.set)
        await mgr.async_teardown()
        assert mgr._gate_log_tasks == set()
        await db.stop_write_worker()
        return db
    db = asyncio.run(_go())
    assert [a["reason"] for _n, a, _s in _rows(db)] == ["shadow"]


def test_persist_off_no_calls(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_GATE_LOG_PERSIST", False)
    calls: list = []

    class _Db:
        async def log_memory_episode(self, **kw):
            calls.append(kw)

    hass, nm, mgr = _d5(monkeypatch)

    async def _go():
        _wire(hass, mgr, _Db())
        await _drive(mgr, RP_PR)
        await _flush(mgr)
    asyncio.run(_go())
    assert calls == [] and mgr._gate_log_tasks == set()
    assert _sev(nm) == Severity.LOW
    assert mgr._last_gate_decisions[RP_KEY]["single_source"]["reason"] == "single_source"


@pytest.mark.parametrize("elev", [35.0, -12.0, None])
def test_row_carries_sun_state_for_every_gate(monkeypatch, elev):
    """Gates that do not read the sun themselves (D3, D6, follow-up, D10.5
    early returns) still carry sun state on the row."""
    calls: list = []

    class _Db:
        async def log_memory_episode(self, **kw):
            calls.append(kw)

    hass, _nm, mgr = _d5(monkeypatch)
    if elev is None:
        hass._states.pop("sun.sun", None)
    else:
        _sun(hass, elev)

    async def _go():
        _wire(hass, mgr, _Db())
        for g in ("zone_agreement", "vlm", "identity_followup", "egress_identity"):
            mgr._record_gate(RP_KEY, {"gate": g, "at": f"2026-11-13T12:00:00|{g}"})
        await _flush(mgr)
    asyncio.run(_go())
    assert len(calls) == 4
    for kw in calls:
        assert kw["attrs"]["sun_elevation"] == elev
        assert kw["attrs"]["is_day"] is (elev is not None and elev >= 0)
        assert kw["window_dedup"] is False
        assert kw["episode_type"] == EPISODE
        assert kw["node_id"] == f"perimeter_gate:{RP_KEY}"
        assert kw["source_ref"] == f"{RP_KEY}|{kw['attrs']['gate']}|{kw['started_at']}"


def test_row_payload_shape_d5(monkeypatch):
    calls: list = []

    class _Db:
        async def log_memory_episode(self, **kw):
            calls.append(kw)

    hass, _nm, mgr = _d5(monkeypatch)

    async def _go():
        _wire(hass, mgr, _Db())
        await _drive(mgr, RP_PR)
        await _flush(mgr)
    asyncio.run(_go())
    (kw,) = calls
    a = kw["attrs"]
    assert (a["camera"], a["gate"], a["reason"], a["would_demote"], a["demoted"],
            a["enforce"], a["severity_before"], a["severity_after"], a["entity_id"],
            a["nvr_family"], a["sun_elevation"], a["is_day"]) == (
        RP_KEY, "single_source", "single_source", True, True, True, "CRITICAL",
        "LOW", RP_PR, "protect", 35.0, True)
    assert a["inputs"]["agreement_rate"] == 1.0
    assert kw["started_at"] == kw["ended_at"]


def test_registered_in_writer_health_set():
    assert EPISODE == ura_const.PERIMETER_GATE_EPISODE_TYPE
    assert EPISODE in ura_const.MEMORY_EPISODE_TYPES
    assert EPISODE in ura_const.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert EPISODE not in ura_const.MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES
    assert (
        ura_const.PERIMETER_GATE_LOG_PERSIST
        or EPISODE in ura_const.MEMORY_WRITER_HEALTH_EXEMPT_TYPES
    )


def test_scorer_pure_functions():
    import importlib.util  # noqa: PLC0415
    import pathlib  # noqa: PLC0415
    p = pathlib.Path(__file__).resolve().parents[2] / "scripts/probes/perimeter_gate_scorer_weekly.py"
    spec = importlib.util.spec_from_file_location("pg_scorer", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [
        {"camera": "g5", "gate": "single_source", "reason": "night", "is_day": False,
         "would_demote": False, "demoted": False},
        {"camera": "g5", "gate": "single_source", "reason": "single_source", "is_day": True,
         "would_demote": True, "demoted": True},
        {"camera": "g5", "gate": "single_source", "reason": "single_source", "is_day": True,
         "would_demote": True, "demoted": True},
        {"camera": "g5", "gate": "vlm", "verdict": "YES", "location": "STREET",
         "reason": "verdict_not_no"},
    ]
    agg = m.aggregate(rows)
    assert agg[("g5", "single_source", "single_source", "day")] == [2, 2, 2]
    assert agg[("g5", "single_source", "night", "night")] == [1, 0, 0]
    assert agg[("g5", "vlm", "verdict_not_no", "unknown")] == [1, 0, 0]
    assert m.person_location_crosstab(rows) == {("YES", "STREET"): 1}
    files = [("g5_100.jpg", 1000.0), ("g5_200.jpg", 1009.0), ("rear_1.jpg", 1000.5)]
    assert m.nearest_snapshot("g5", 1001.0, files) == "g5_100.jpg"
    assert m.nearest_snapshot("g5", 1020.0, files) is None
    assert m.nearest_snapshot("g5", None, files) is None


def test_no_row_before_setup(monkeypatch):
    """A manager that never finished async_setup (`_active` False) writes no
    row even with a database present."""
    from test_perimeter_fp_gates import RP_CAM, _build  # noqa: PLC0415
    calls: list = []

    class _Db:
        async def log_memory_episode(self, **kw):
            calls.append(kw)

    hass, _nm = _build(perimeter=(RP_CAM,))
    mgr = _perimeter.PerimeterAlertManager(hass)

    async def _go():
        _wire(hass, mgr, _Db())
        mgr._record_gate(RP_KEY, {"gate": "single_source", "at": "x"})
        await _flush(mgr)
    asyncio.run(_go())
    assert calls == [] and mgr._gate_log_tasks == set()


def test_teardown_latch_alone_blocks_rows(monkeypatch):
    """The latch is set FIRST in async_teardown, before `_active` drops; on
    its own (manager still active) it blocks the write."""
    calls: list = []

    class _Db:
        async def log_memory_episode(self, **kw):
            calls.append(kw)

    hass, _nm, mgr = _d5(monkeypatch)

    async def _go():
        _wire(hass, mgr, _Db())
        assert mgr._active is True
        mgr._gate_log_torn_down = True
        mgr._record_gate(RP_KEY, {"gate": "single_source", "at": "x"})
        await _flush(mgr)
    asyncio.run(_go())
    assert calls == []
