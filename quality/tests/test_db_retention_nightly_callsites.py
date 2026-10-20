"""DB-SIZE-GROWTH-1 Review C: the two nightly call sites in __init__.py.

Both nightly closures (primary ``_nightly_db_maintenance`` and the
deferred-startup ``_nightly_maintenance_deferred``) are nested inside the
~1000-line ``async_setup_entry``. Each must (a) await the shared
``run_nightly_cleanup`` with the live database and domain dict and (b) be
registered with ``async_track_time_change`` at 02:30:00.

Style (repo precedent: test_reload_watchdog_hazard.py): the REAL closure
source is sliced out of ``__init__.py`` by AST, exec'd against a spy
``run_nightly_cleanup``, and CALLED. Removing/neutering the call in either
closure makes the spy-not-awaited assertion fail; dropping either
registration fails the registration test. Not a source grep of the call.
"""
from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PKG = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
SRC = (PKG / "__init__.py").read_text()
TREE = ast.parse(SRC)

# closure name -> registration callable alias used in __init__.py
SITES = {
    "_nightly_db_maintenance": "async_track_time_change",
    "_nightly_maintenance_deferred": "_attc_d",
}


def _closure_def(name: str) -> ast.AsyncFunctionDef:
    found = [n for n in ast.walk(TREE)
             if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(found) == 1, f"{name}: expected exactly one definition, got {len(found)}"
    return found[0]


def _load(name: str, spy):
    mod = ast.Module(body=[_closure_def(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {
        "DOMAIN": "universal_room_automation",
        "run_nightly_cleanup": spy,
        "_LOGGER": logging.getLogger("test"),
        "asyncio": asyncio,
    }
    exec(compile(mod, str(PKG / "__init__.py"), "exec"), ns)
    return ns


@pytest.mark.parametrize("name", list(SITES))
@pytest.mark.asyncio
async def test_nightly_closure_runs_shared_cleanup_with_db(name):
    awaited = []

    async def spy(domain_data, db, **kw):
        awaited.append((domain_data, db))

    ns = _load(name, spy)
    fn = ns[name]
    db = object()
    domain = {"database": db}
    ns["hass"] = MagicMock()
    ns["hass"].data = {ns["DOMAIN"]: domain}
    ns["entry"] = MagicMock()
    await fn(None)
    assert len(awaited) == 1, f"{name} did not await run_nightly_cleanup exactly once"
    assert awaited[0][0] is domain
    assert awaited[0][1] is db


@pytest.mark.parametrize("name", list(SITES))
@pytest.mark.asyncio
async def test_nightly_closure_noop_without_database(name):
    awaited = []

    async def spy(domain_data, db, **kw):
        awaited.append(1)

    ns = _load(name, spy)
    ns["hass"] = MagicMock()
    ns["hass"].data = {ns["DOMAIN"]: {}}
    ns["entry"] = MagicMock()
    await ns[name](None)
    assert awaited == []


@pytest.mark.parametrize("name,alias", list(SITES.items()))
def test_nightly_closure_registered_at_0230(name, alias):
    """The closure is handed to async_track_time_change at 02:30:00."""
    hits = []
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == alias and len(node.args) >= 2
                and isinstance(node.args[1], ast.Name) and node.args[1].id == name):
            kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
            hits.append(kw)
    assert hits == [{"hour": 2, "minute": 30, "second": 0}], (name, hits)


# ---------------------------------------------------------------------------
# Review-C additions: yield + short-batch exit + inter-op gap (mutants that
# survived the first drill pass).
# ---------------------------------------------------------------------------
import os  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from custom_components.universal_room_automation import database as _db_mod  # noqa: E402
from custom_components.universal_room_automation import nightly_maintenance as _nm  # noqa: E402
from test_db_retention_room_history import _make_db, _run, _insert  # noqa: E402


def _fixed_clock(monkeypatch):
    monkeypatch.setattr(_db_mod, "dt_util", SimpleNamespace(
        utcnow=lambda: datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
        now=lambda: datetime(2026, 12, 1, 6, 0, tzinfo=timezone(timedelta(hours=-6)))))


@pytest.mark.asyncio
async def test_prune_yields_between_full_batches_and_stops_on_short_batch(tmp_path, monkeypatch):
    """Full batch -> 0.1 s yield and another pass; short batch -> stop (no
    pointless extra DELETE, no false 'hit the cap' warning)."""
    _fixed_clock(monkeypatch)
    sleeps: list[float] = []

    async def rec_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(_db_mod.asyncio, "sleep", rec_sleep)
    db = _make_db(str(tmp_path))
    entered = {"n": 0}

    async def body():
        # 5 old env rows, batch_size 2 -> batches of 2,2,1: two yields, 3 DELETEs.
        await _insert(db, "environmental_data",
                      [f"2025-01-{d:02d}T00:00:00" for d in range(1, 6)])
        real = db._db

        def counting():
            entered["n"] += 1
            return real()

        db._db = counting
        return await db.cleanup_room_history(retention_days=365, batch_size=2, max_batches=50)

    n = await _run(db, body)
    assert n == 5
    assert sleeps.count(0.1) == 2, sleeps
    # env: 3 DELETE batches; the other 3 tables: 1 (empty, short) DELETE each.
    assert entered["n"] == 3 + 3, entered["n"]


@pytest.mark.asyncio
async def test_run_nightly_cleanup_sleeps_op_gap_between_ops():
    sleeps: list[float] = []

    async def rec(s):
        sleeps.append(s)

    class _DB:
        def __getattr__(self, name):
            async def _m(**kw):
                return None
            return _m

    await _nm.run_nightly_cleanup({}, _DB(), sleep=rec)
    assert sleeps == [_nm.NIGHTLY_MAINTENANCE_OP_GAP_S] * len(_nm.nightly_cleanup_ops())
    assert _nm.NIGHTLY_MAINTENANCE_OP_GAP_S == 1.0
