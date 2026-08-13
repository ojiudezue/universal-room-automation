"""DP-REASON-NULL-1: _log_dp_eval_decision must log the real eval reason.

The DrainPrecedenceState carrier has NO `reason` attribute. The pre-fix
code did `getattr(carrier, "reason", None)`, which silently produced
`null` in every decision_log row. The reason of record lives on
`carrier.last_eval_snapshot["decision"]["reason"]` (see
energy_drain_precedence._snapshot_eval).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

# Piggyback on the sibling test's HA bootstrap (setdefault-based).
from test_arbitrage_completed_chunk_hold_precedence import (  # noqa: F401
    _mock_module,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (
    EnergyCoordinator,
)


class _CapturingDB:
    def __init__(self):
        self.rows = []

    async def log_coordinator_decision(self, **kwargs):
        self.rows.append(kwargs)
        return 1


def _make_ec_with_carrier(carrier) -> tuple[EnergyCoordinator, _CapturingDB]:
    ec = EnergyCoordinator.__new__(EnergyCoordinator)
    db = _CapturingDB()
    hass = MagicMock()
    hass.data = {"universal_room_automation": {"database": db}}
    ec.hass = hass
    ec._dp_carrier = carrier
    ec._battery = SimpleNamespace(soc_envelope=lambda: (None, None))
    ec.reserve_write_verifiable = lambda: True
    return ec, db


def _inputs(**over):
    base = dict(
        charger_rate_kw=0.0,
        soc=50,
        is_blind_hold=False,
        drain_target_soc=30,
        force_charge_active=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _now():
    import datetime as _dt
    return _dt.datetime(2026, 8, 12, 22, 0, 0, tzinfo=_dt.timezone.utc)


def test_dp_reason_null_1_post_eval_row_has_non_null_reason():
    """After an eval populates the snapshot, the row's reason is the real
    decision.reason string — NOT null.
    """
    carrier = SimpleNamespace(
        state="L1_ONLY",
        last_eval_snapshot={
            "inputs": {},
            "decision": {"reason": "already_below_target", "transition": False},
        },
    )
    ec, db = _make_ec_with_carrier(carrier)
    asyncio.run(ec._log_dp_eval_decision(
        prev_state="L1_ONLY", now=_now(), inputs=_inputs(), period="off_peak",
        ev_load_w=0.0,
    ))
    assert len(db.rows) == 1
    ctx = json.loads(db.rows[0]["context_json"])
    assert ctx["reason"] == "already_below_target", (
        f"expected real eval reason, got {ctx['reason']!r}"
    )


def test_dp_reason_null_1_pre_eval_row_writes_safely_as_none():
    """Before any eval runs the snapshot is empty; the row must still
    persist, carrying reason=None (no crash, no getattr on missing attr).
    """
    carrier = SimpleNamespace(state="IDLE", last_eval_snapshot={})
    ec, db = _make_ec_with_carrier(carrier)
    asyncio.run(ec._log_dp_eval_decision(
        prev_state="IDLE", now=_now(), inputs=_inputs(), period="off_peak",
        ev_load_w=0.0,
    ))
    assert len(db.rows) == 1
    ctx = json.loads(db.rows[0]["context_json"])
    assert ctx["reason"] is None
