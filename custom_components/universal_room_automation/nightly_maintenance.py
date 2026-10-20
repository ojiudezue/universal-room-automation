"""Nightly DB maintenance: the single op list + rotating runner.

DB-SIZE-GROWTH-1 (plan review PR-2): the op list used to be duplicated as two
literals in ``__init__.py`` (``_cleanup_ops`` primary + ``_cleanup_ops_d``
deferred-startup mirror). Six fix-ups were needed when an op landed in one but
not the other (Bug Class #27). Both nightly closures now call
``run_nightly_cleanup`` which builds its list from ``nightly_cleanup_ops`` —
one list, no mirror to drift.

Light module on purpose (imports only ``const``) so tests can drive the real
list and runner without importing ``__init__.py``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import RETENTION_ROOM_HISTORY_DAYS

_LOGGER = logging.getLogger(__name__)

# Seconds: the nightly loop stops starting new ops after this much wall time
# (between ops only; it never preempts a running op). Unchanged from v4.2.8.
NIGHTLY_MAINTENANCE_BUDGET_S = 300
# Seconds slept between ops (unchanged from v4.2.8).
NIGHTLY_MAINTENANCE_OP_GAP_S = 1.0
# hass.data[DOMAIN] key for the rotating start index (shared by both paths).
NIGHTLY_START_IDX_KEY = "_nightly_start_idx"


def nightly_cleanup_ops() -> list[tuple[str, str, dict[str, Any]]]:
    """Return the ordered (name, db_method_name, kwargs) nightly ops."""
    return [
        ("predictions", "prune_prediction_results", {"days": 30}),
        ("census", "cleanup_census", {"retention_days": 90}),
        ("energy_history", "cleanup_energy_history", {"retention_days": 180}),
        ("external_conditions", "cleanup_external_conditions", {"retention_days": 90}),
        ("notifications", "prune_notification_log", {"retention_days": 30}),
        ("inbound", "prune_inbound_log", {"retention_days": 30}),
        ("person_data", "cleanup_person_data", {"retention_days": 90}),
        ("room_energy_baselines", "cleanup_room_energy_baselines", {"retention_days": 90}),
        ("anomaly_log", "cleanup_anomaly_log", {"retention_days_point_in_time": 90, "retention_days_regime_shift": 365}),
        # v4.7.8 fix-up B-H1 / C-H2 (Bug Class #27): egress_state sweep for
        # deleted rooms / orphaned transitions.
        ("egress_state", "prune_stale_egress_state", {"cutoff_days": 7}),
        # v4.7.36 fix-up B3: optimizer Phase 1 + Phase 3 prunes.
        ("optimization_findings", "prune_optimization_findings", {}),
        ("optimization_daily_digest", "prune_optimization_daily_digest", {}),
        # v5.11.0 F-MED: shadow-samples prune.
        ("optimizer_shadow_samples", "prune_optimizer_shadow_samples", {}),
        # Fix-up A-HIGH-1 (Batch 4): decision_log retention, one op per type.
        ("decision_log_dp_eval", "cleanup_decision_log", {"decision_type": "dp_eval", "retention_days": 90}),
        ("decision_log_blind_window_defer", "cleanup_decision_log", {"decision_type": "blind_window_defer", "retention_days": 90}),
        ("decision_log_blind_window_liveness_release", "cleanup_decision_log", {"decision_type": "blind_window_liveness_release", "retention_days": 90}),
        # DB-SIZE-GROWTH-1: age-based retention for the four per-room history
        # tables (env / energy / occupancy / room_transitions).
        ("room_history", "cleanup_room_history", {"retention_days": RETENTION_ROOM_HISTORY_DAYS}),
        # Bounded incremental_vacuum after the prunes (start index rotates,
        # so on some nights it runs first; freed pages reclaim next night).
        ("incremental_vacuum", "incremental_vacuum", {}),
        # MEMORY-COMPACTOR-1 D4: rides after incremental_vacuum; cadence-guarded.
        ("memory_compactor", "run_memory_compactor", {}),
        # MEMORY-WRITERS-SILENT-DROP-1 D3: weekly writer-health trip-wire.
        ("memory_writer_health", "run_memory_writer_health_check", {}),
    ]


async def run_nightly_cleanup(
    domain_data: dict,
    db: Any,
    *,
    now_fn: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[Any]] | None = None,
) -> None:
    """Run every nightly op once, rotating the start index, under the budget.

    ``domain_data`` is ``hass.data[DOMAIN]`` (holds the rotating index).
    A failing op is logged and skipped; the loop continues.
    """
    _now = now_fn or dt_util.utcnow
    _sleep = sleep or asyncio.sleep
    ops = nightly_cleanup_ops()
    start = _now()
    idx = domain_data.get(NIGHTLY_START_IDX_KEY, 0)
    n = len(ops)
    for i in range(n):
        name, method_name, kwargs = ops[(idx + i) % n]
        if (_now() - start).total_seconds() > NIGHTLY_MAINTENANCE_BUDGET_S:
            _LOGGER.warning(
                "Nightly maintenance hit 5-min budget — continuing tomorrow from %s",
                name,
            )
            break
        try:
            method = getattr(db, method_name, None)
            if method:
                await method(**kwargs)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Nightly %s cleanup failed: %s", name, exc)
        await _sleep(NIGHTLY_MAINTENANCE_OP_GAP_S)
    domain_data[NIGHTLY_START_IDX_KEY] = (idx + 1) % n
