"""Shared INV-NOOP scenarios for the anomaly coverage cycle
(PLANNING_anomaly_detector_blind_metrics.md §6 INV-NOOP, D1 test
`test_house_only_detector_summary_byte_identical`).

The golden fixture `quality/fixtures/anomaly_noop_golden.json` was generated
from `develop` @4233304dc (BEFORE the build) by running this module as a
script:

    PYTHONPATH=quality .venv-ha/bin/python quality/tests/_anomaly_noop_scenario.py

Each scenario is a house-only detector whose metrics are all mature (`ok`)
with an empty unwired set — the INV-NOOP domain. The golden records:
  - `get_status_summary()` (pre-existing keys only, by construction),
  - the sensor state as the OLD 5-site projection computed it
    (learning → learning value; else worst severity),
  - `get_learning_status()` / `get_worst_severity()`,
  - the rows `save_baselines()` writes (real aiosqlite, production DDL).

Deterministic: every baseline's `last_updated` is pinned after the scenario's
observations, and nothing in the recorded payload depends on wall time.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DOMAIN = "universal_room_automation"
GOLDEN_PATH = _REPO_ROOT / "quality" / "fixtures" / "anomaly_noop_golden.json"
PINNED_TS = "2026-09-28T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Import isolation (suite-order hygiene).
#
# These tests drive the REAL production modules. But several sibling files
# (e.g. test_house_state_rung2a.py) stub HA and then import coordinator
# modules FRESH, relying on nothing having imported them first. So the
# anomaly-coverage test files import what they need at collection, keep the
# module objects, and REMOVE every `custom_components.*` entry they added from
# sys.modules (plus the parent-package attribute). `reinstall(monkeypatch)`
# puts exactly those objects back for the duration of one test, so runtime
# relative imports inside production code (`from .coordinator_diagnostics
# import AnomalyDetector`) resolve to the same objects the test patched.
# ---------------------------------------------------------------------------
ISOLATED: dict = {}


def _is_cc(name: str) -> bool:
    return name == "custom_components" or name.startswith("custom_components.")


def _is_stub_aiosqlite(name: str) -> bool:
    if name != "aiosqlite" and not name.startswith("aiosqlite."):
        return False
    return not getattr(sys.modules.get(name), "__file__", None)


def import_isolated(*module_names):
    """Import REAL production modules regardless of what sibling files left in
    sys.modules, then leave sys.modules exactly as found."""
    import importlib  # noqa: PLC0415
    # Shelve whatever custom_components.* (often stubs) and stubbed aiosqlite
    # entries sibling files installed, so the import below binds real code.
    shelved = {k: m for k, m in list(sys.modules.items())
               if _is_cc(k) or _is_stub_aiosqlite(k)}
    for k in shelved:
        sys.modules.pop(k, None)
    # Re-seat modules isolated by an earlier call so every anomaly-coverage
    # test file shares ONE copy of each production module.
    sys.modules.update(ISOLATED)
    try:
        mods = [importlib.import_module(n) for n in module_names]
    finally:
        for k in [k for k in sys.modules if _is_cc(k)]:
            ISOLATED[k] = sys.modules.pop(k)
        sys.modules.update(shelved)
    return mods


def reinstall(monkeypatch) -> None:
    for name, mod in ISOLATED.items():
        monkeypatch.setitem(sys.modules, name, mod)


(_DIAG,) = import_isolated(
    "custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics",
)


def _diag():
    return _DIAG


def _load_real_aiosqlite():
    """The REAL aiosqlite, even if a sibling test left a stub in sys.modules
    (the stub is restored afterwards so that test's expectations hold)."""
    mod = sys.modules.get("aiosqlite")
    if mod is not None and getattr(mod, "__file__", None):
        return mod
    saved = {k: v for k, v in sys.modules.items()
             if k == "aiosqlite" or k.startswith("aiosqlite.")}
    for k in saved:
        sys.modules.pop(k, None)
    try:
        import aiosqlite as real  # noqa: PLC0415
    finally:
        for k in [k for k in sys.modules if k == "aiosqlite" or k.startswith("aiosqlite.")]:
            sys.modules.pop(k, None)
        sys.modules.update(saved)
    return real


_AIOSQLITE = _load_real_aiosqlite()


def extract_metric_baselines_ddl() -> str:
    """Production DDL for metric_baselines (never hand-copied)."""
    src = (
        _REPO_ROOT / "custom_components" / "universal_room_automation" / "database.py"
    ).read_text()
    m = re.search(
        r'"""(CREATE TABLE IF NOT EXISTS metric_baselines\b.*?)"""', src, re.DOTALL,
    )
    assert m, "metric_baselines DDL not found in database.py"
    return m.group(1)


class AiosqliteDB:
    """Minimal `database` stand-in exposing `_db()` over a REAL aiosqlite
    connection (production DDL). `on_execute` lets a test inject work that
    runs INSIDE the save loop's await (the M3 race drill)."""

    def __init__(self, path: str, on_execute=None) -> None:
        self.path = path
        self.on_execute = on_execute
        self.execute_calls = 0

    async def setup(self) -> None:
        async with _AIOSQLITE.connect(self.path) as db:
            await db.execute(extract_metric_baselines_ddl())
            await db.commit()

    @contextlib.asynccontextmanager
    async def _db(self):
        outer = self

        async with _AIOSQLITE.connect(self.path) as real:

            class _Conn:
                # load_baselines sets `db.row_factory = aiosqlite.Row`; proxy it
                # to the real connection so rows come back as Row objects.
                @property
                def row_factory(self):
                    return real.row_factory

                @row_factory.setter
                def row_factory(self, value):
                    real.row_factory = value

                async def execute(self, sql, params=()):
                    outer.execute_calls += 1
                    if outer.on_execute is not None:
                        outer.on_execute(outer.execute_calls)
                    # Yield to the loop like a real awaited write would.
                    await asyncio.sleep(0)
                    return await real.execute(sql, params)

                async def commit(self):
                    await real.commit()

            yield _Conn()

    async def rows(self) -> list:
        async with _AIOSQLITE.connect(self.path) as db:
            cur = await db.execute(
                "SELECT coordinator_id, metric_name, scope, mean, variance, "
                "sample_count, last_updated FROM metric_baselines "
                "ORDER BY coordinator_id, metric_name, scope"
            )
            return [list(r) for r in await cur.fetchall()]


def make_hass(database=None):
    # Key by the detector module's own DOMAIN binding (robust to const stubs).
    domain = getattr(_DIAG, "DOMAIN", DOMAIN)
    return types.SimpleNamespace(data={domain: {"database": database}})


def _seed(det, metric, scope, mean, variance, n):
    diag = _diag()
    det._baselines[(metric, scope)] = diag.MetricBaseline(
        metric_name=metric, coordinator_id=det.coordinator_id, scope=scope,
        mean=mean, variance=variance, sample_count=n, last_updated=PINNED_TS,
    )


def build_scenario(name: str, hass=None):
    """Return a detector for the named INV-NOOP scenario."""
    diag = _diag()
    hass = hass if hass is not None else make_hass()
    if name == "all_ok_quiet":
        det = diag.AnomalyDetector(
            hass, "noop_quiet", ["m_alpha", "m_beta", "m_gamma"],
            minimum_samples=24,
        )
        _seed(det, "m_alpha", "house", 5.0, 2.0, 100)
        _seed(det, "m_beta", "house", 1.0, 0.5, 50)
        _seed(det, "m_gamma", "house", 3.0, 1.5, 30)
        det.record_observation("m_alpha", "house", 5.1)
    elif name == "all_ok_with_anomalies":
        det = diag.AnomalyDetector(
            hass, "noop_anom", ["m_alpha", "m_beta", "m_gamma"],
            minimum_samples=24,
            suppressed_metric_names=frozenset({"m_beta"}),
            minimum_samples_by_metric={"m_gamma": 10},
        )
        _seed(det, "m_alpha", "house", 5.0, 2.0, 100)
        _seed(det, "m_beta", "house", 1.0, 0.5, 50)
        _seed(det, "m_gamma", "house", 3.0, 1.5, 12)
        # advisory on m_alpha: z = 2.5
        det.record_observation("m_alpha", "house", 5.0 + 2.5 * math.sqrt(2.0))
        # critical on suppressed m_beta: z = 5
        det.record_observation("m_beta", "house", 1.0 + 5.0 * math.sqrt(0.5))
        # quiet obs on m_gamma
        det.record_observation("m_gamma", "house", 3.1)
    else:  # pragma: no cover
        raise KeyError(name)
    for b in det._baselines.values():
        b.last_updated = PINNED_TS
    return det


SCENARIOS = ("all_ok_quiet", "all_ok_with_anomalies")


def old_projection_state(det) -> str:
    """The pre-cycle 5-site projection, verbatim semantics (golden only)."""
    learning = det.get_learning_status()
    if hasattr(learning, "value") and learning.value in (
        "insufficient_data", "learning",
    ):
        return learning.value
    return det.get_worst_severity().value


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


async def capture(name: str, tmpdir: str, *, state_fn=old_projection_state) -> dict:
    db = AiosqliteDB(os.path.join(tmpdir, f"{name}.db"))
    await db.setup()
    det = build_scenario(name, make_hass(db))
    out = {
        "summary": _jsonable(det.get_status_summary()),
        "state": state_fn(det),
        "learning_status": str(det.get_learning_status().value),
        "worst_severity": det.get_worst_severity().value,
        "baseline_keys": sorted(list(k) for k in det._baselines),
    }
    await det.save_baselines()
    out["saved_rows"] = await db.rows()
    return out


async def _generate(tmpdir: str) -> dict:
    return {name: await capture(name, tmpdir) for name in SCENARIOS}


if __name__ == "__main__":  # pragma: no cover - golden generator
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        golden = asyncio.run(_generate(td))
    GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN_PATH}")
