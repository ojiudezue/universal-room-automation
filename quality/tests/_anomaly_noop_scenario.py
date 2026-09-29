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


def _diag():
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415
        coordinator_diagnostics as diag,
    )
    return diag


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
        import aiosqlite  # noqa: PLC0415
        async with aiosqlite.connect(self.path) as db:
            await db.execute(extract_metric_baselines_ddl())
            await db.commit()

    @contextlib.asynccontextmanager
    async def _db(self):
        import aiosqlite  # noqa: PLC0415
        outer = self

        async with aiosqlite.connect(self.path) as real:

            class _Conn:
                row_factory = None

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
        import aiosqlite  # noqa: PLC0415
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT coordinator_id, metric_name, scope, mean, variance, "
                "sample_count, last_updated FROM metric_baselines "
                "ORDER BY coordinator_id, metric_name, scope"
            )
            return [list(r) for r in await cur.fetchall()]


def make_hass(database=None):
    return types.SimpleNamespace(data={DOMAIN: {"database": database}})


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
