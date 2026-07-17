"""EVSE Drain-Precedence — hold-then-eval state machine (Session A skeleton).

Tier 3 cycle. This module is the Session-A skeleton: state definitions,
pure transition guards, KV persist/restore with expiry validation, and an
observability attr block. Session B will:
    - wire the eval math (drain_hours / charge_hours / fits check),
    - route actuation through the existing `_paused_by_dp` provenance
      + `_apply_evse_battery_hold` reserve floor composition,
    - promote knobs to entity surfaces per plan §68-84,
    - add the reverse sweep + must-start-by force-release path.

Falsifiable invariants (planning §25-36):
    INV-DP1  drain-precedence master (bounded transitioned window)
    INV-DP2  car-charge liveness (must-start-by ⇒ CHARGING or DONE)
    INV-DP3  floor supremacy (max() composition, never demote)
    INV-DP4  blind-hold gate (no fresh SOC → no eval → hold stands)
    INV-DP5  single-writer stamp (every reserve write stamps
             `_desired_stamped_at` fresh)

Session A owns the state carrier + KV persistence + restore expiry guard.
INV-DP1..5 are enforced by Session B call sites.

Clock injection: `now_provider` is a Callable[[], datetime] injected by
callers. Tests pass a frozen provider (v5.17.1 _FrozenClock lesson —
NEVER wall-clock-couple state-machine tests). Production callers pass
`homeassistant.util.dt.now`.

Numbers Get Knobs: every behavioral number lives in `energy_const.py`
under the `EVSE Drain-Precedence` block (rung-1 module constants this
session; entity promotion deferred to Session B).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dt_time, timedelta
from enum import Enum
from typing import Any, Callable, Optional
import json
import logging

from .energy_const import (
    CONF_DP_ENABLE,
    CONF_DP_EVAL_DELAY_MIN,
    CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT,
    DP_KV_KEY,
    DP_TRANSITION_MAX_DURATION_H,
)

_LOGGER = logging.getLogger(__name__)

# KV blob format version — bump on any breaking schema change.
_KV_SCHEMA_VERSION: int = 1


class DPState(str, Enum):
    """Drain-precedence state machine states.

    HOLD_ONLY          Default; master switch off OR eval said no.
    HOLD_PRE_EVAL      Hold active, waiting `CONF_DP_EVAL_DELAY_MIN`
                       before firing a fresh eval.
    EVAL_TRANSITION    One-shot eval fires this tick.
    TRANSITIONED       EVSE(s) paused, reserve released to
                       max(inclement_floor, drain_target), ledger stamped.
    MUST_START_FORCED  Must-start-by deadline reached; EVSE released
                       regardless of drain progress (INV-DP2 guarantee).
    """

    HOLD_ONLY = "hold_only"
    HOLD_PRE_EVAL = "hold_pre_eval"
    EVAL_TRANSITION = "eval_transition"
    TRANSITIONED = "transitioned"
    MUST_START_FORCED = "must_start_forced"


# Legal transition table. Any transition NOT listed here is illegal.
# Independently anchored (hand-written from plan §141-158) — tests will
# hand-write the SAME table separately and diff, so a machine bug that
# happens to match the machine's own view cannot silently pass.
_LEGAL_TRANSITIONS: frozenset[tuple[DPState, DPState]] = frozenset({
    # From HOLD_ONLY
    (DPState.HOLD_ONLY, DPState.HOLD_ONLY),        # self-loop (kill switch off)
    (DPState.HOLD_ONLY, DPState.HOLD_PRE_EVAL),    # hold armed
    # From HOLD_PRE_EVAL
    (DPState.HOLD_PRE_EVAL, DPState.HOLD_PRE_EVAL),
    (DPState.HOLD_PRE_EVAL, DPState.EVAL_TRANSITION),
    (DPState.HOLD_PRE_EVAL, DPState.HOLD_ONLY),    # hold cleared / kill flipped
    # From EVAL_TRANSITION (one-shot; must exit same tick or next)
    (DPState.EVAL_TRANSITION, DPState.TRANSITIONED),
    (DPState.EVAL_TRANSITION, DPState.HOLD_ONLY),  # eval said no → hold-only
    # From TRANSITIONED
    (DPState.TRANSITIONED, DPState.TRANSITIONED),  # self-loop while transitioned
    (DPState.TRANSITIONED, DPState.HOLD_ONLY),     # clean reversion (charge done)
    (DPState.TRANSITIONED, DPState.MUST_START_FORCED),  # deadline reached
    # From MUST_START_FORCED
    (DPState.MUST_START_FORCED, DPState.HOLD_ONLY),  # force released
})


@dataclass
class DrainPrecedenceState:
    """Serializable carrier for the drain-precedence state machine.

    All datetimes are timezone-aware ISO strings on the wire (KV) and
    aware `datetime` objects in memory. Bug Class #21 (naive/aware) — the
    from_dict/to_dict boundary re-parses via `dt_util.parse_datetime`-
    equivalent semantics (`datetime.fromisoformat`) since we don't want
    to import HA at module scope in the pure state machine.

    `must_start_by_dt`: absolute wall-clock deadline for the *current*
    transition. Recomputed on every fresh transition arm; on restore it
    is validated against `now_provider()` — a stale/expired deadline
    causes the restore to REJECT the transition (INV-DP2 guard) rather
    than silently resurrect an out-of-window pause.
    """

    state: DPState = DPState.HOLD_ONLY
    since: Optional[datetime] = None
    hold_started_at: Optional[datetime] = None
    transitioned_at: Optional[datetime] = None
    must_start_by_dt: Optional[datetime] = None
    last_eval_at: Optional[datetime] = None
    last_eval_snapshot: dict[str, Any] = field(default_factory=dict)

    # ---- serialization -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Serialize for KV persistence (JSON-safe)."""
        def _iso(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt is not None else None

        return {
            "schema_version": _KV_SCHEMA_VERSION,
            "state": self.state.value,
            "since": _iso(self.since),
            "hold_started_at": _iso(self.hold_started_at),
            "transitioned_at": _iso(self.transitioned_at),
            "must_start_by_dt": _iso(self.must_start_by_dt),
            "last_eval_at": _iso(self.last_eval_at),
            "last_eval_snapshot": dict(self.last_eval_snapshot or {}),
        }

    @classmethod
    def from_dict(cls, blob: dict[str, Any]) -> "DrainPrecedenceState":
        """Deserialize from KV. Rejects unknown schema versions."""
        version = blob.get("schema_version")
        if version != _KV_SCHEMA_VERSION:
            raise ValueError(
                f"drain-precedence KV schema mismatch: got {version!r}, "
                f"expected {_KV_SCHEMA_VERSION}"
            )

        def _dt(v: Any) -> Optional[datetime]:
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except (TypeError, ValueError):
                return None

        raw_state = blob.get("state", DPState.HOLD_ONLY.value)
        try:
            st = DPState(raw_state)
        except ValueError:
            _LOGGER.warning(
                "drain-precedence KV: unknown state %r → coerced to HOLD_ONLY",
                raw_state,
            )
            st = DPState.HOLD_ONLY

        return cls(
            state=st,
            since=_dt(blob.get("since")),
            hold_started_at=_dt(blob.get("hold_started_at")),
            transitioned_at=_dt(blob.get("transitioned_at")),
            must_start_by_dt=_dt(blob.get("must_start_by_dt")),
            last_eval_at=_dt(blob.get("last_eval_at")),
            last_eval_snapshot=dict(blob.get("last_eval_snapshot") or {}),
        )

    # ---- observability -------------------------------------------------
    def to_attrs(self) -> dict[str, Any]:
        """Attr block for `sensor.ura_energy_drain_precedence_state`.

        Session A: attrs only (no new sensor entity — Session B adds the
        entity surface). The parent Energy Coordinator's diagnostics sensor
        picks these up via a `drain_precedence` sub-dict.
        """
        def _iso(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt is not None else None

        return {
            "state": self.state.value,
            "since": _iso(self.since),
            "hold_started_at": _iso(self.hold_started_at),
            "transitioned_at": _iso(self.transitioned_at),
            "must_start_by_dt": _iso(self.must_start_by_dt),
            "last_eval_at": _iso(self.last_eval_at),
            "last_eval_snapshot": dict(self.last_eval_snapshot or {}),
        }


# ==========================================================================
# Pure transition guards
# ==========================================================================


def is_legal_transition(src: DPState, dst: DPState) -> bool:
    """True iff (src → dst) is a listed legal transition."""
    return (src, dst) in _LEGAL_TRANSITIONS


def try_transition(
    carrier: DrainPrecedenceState,
    dst: DPState,
    *,
    now_provider: Callable[[], datetime],
) -> bool:
    """Apply (carrier.state → dst) if legal; return True on transition.

    Pure guard: does NOT actuate; Session B call sites drive the
    side-effects (pause, reserve write, KV save). This function only
    updates the carrier's state + timestamp bookkeeping.

    Illegal transitions are rejected (return False, no state change) and
    logged at WARNING — an illegal transition attempt is a state-machine
    bug in the caller, never a user-facing condition.
    """
    src = carrier.state
    if not is_legal_transition(src, dst):
        _LOGGER.warning(
            "drain-precedence: illegal transition rejected: %s → %s",
            src.value, dst.value,
        )
        return False

    if src == dst:
        # Self-loop: no bookkeeping churn.
        return True

    now = now_provider()
    _LOGGER.info(
        "drain-precedence: %s → %s at %s", src.value, dst.value, now.isoformat(),
    )
    carrier.state = dst
    carrier.since = now
    if dst == DPState.HOLD_PRE_EVAL:
        carrier.hold_started_at = now
    elif dst == DPState.TRANSITIONED:
        carrier.transitioned_at = now
    elif dst == DPState.HOLD_ONLY:
        # Clean reversion — drop the transition-only fields; keep last_eval
        # snapshot for observability.
        carrier.hold_started_at = None
        carrier.transitioned_at = None
        carrier.must_start_by_dt = None
    return True


def compute_must_start_by(
    now: datetime,
    *,
    minutes_past_midnight: int = CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT,
) -> datetime:
    """Compute the next-occurring must-start-by wall-clock deadline.

    If `now` is BEFORE today's HH:MM (say now=00:30, target=03:00), the
    deadline is today. If `now` is AT-OR-AFTER (say now=05:00), the
    deadline is tomorrow. Uses `now`'s tzinfo — caller controls tz-awareness.
    """
    hour, minute = divmod(minutes_past_midnight, 60)
    today_target = now.replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )
    if now < today_target:
        return today_target
    return today_target + timedelta(days=1)


# ==========================================================================
# Restore validation
# ==========================================================================


def restore_from_blob(
    raw: str | None,
    *,
    now_provider: Callable[[], datetime],
) -> DrainPrecedenceState:
    """Restore state from a KV blob with expiry / clock-drift validation.

    Contract (INV-DP2, INV-DP4 restart interaction):
        - Unknown / empty / malformed blob → fresh HOLD_ONLY.
        - Blob restores TRANSITIONED / MUST_START_FORCED but
          `must_start_by_dt` is None OR already-passed relative to
          `now_provider()` → REJECT the transition, return HOLD_ONLY
          (the resurrected pause would be an out-of-window drain, and
          Session B's tick will re-arm the hold from raw signals).
        - Blob restores TRANSITIONED with `transitioned_at` older than
          `DP_TRANSITION_MAX_DURATION_H` → REJECT (belt-and-suspenders
          bound; INV-DP1).
        - Blob restores HOLD_PRE_EVAL — always accepted (idle waiting
          state); Session B will re-arm eval on the next tick.
    """
    if not raw:
        return DrainPrecedenceState()

    try:
        blob = json.loads(raw)
    except (TypeError, ValueError):
        _LOGGER.warning("drain-precedence KV blob unparseable → fresh HOLD_ONLY")
        return DrainPrecedenceState()

    try:
        carrier = DrainPrecedenceState.from_dict(blob)
    except ValueError as exc:
        _LOGGER.warning("drain-precedence KV rejected: %s → fresh HOLD_ONLY", exc)
        return DrainPrecedenceState()

    if carrier.state in (DPState.TRANSITIONED, DPState.MUST_START_FORCED):
        now = now_provider()
        # INV-DP2 guard: expired must-start-by deadline.
        if carrier.must_start_by_dt is None:
            _LOGGER.info(
                "drain-precedence restore: %s without must_start_by_dt → "
                "rejecting transition, fresh HOLD_ONLY",
                carrier.state.value,
            )
            return DrainPrecedenceState()
        if carrier.must_start_by_dt <= now:
            _LOGGER.info(
                "drain-precedence restore: must_start_by_dt %s already passed "
                "at restore-now %s → rejecting transition, fresh HOLD_ONLY",
                carrier.must_start_by_dt.isoformat(), now.isoformat(),
            )
            return DrainPrecedenceState()
        # INV-DP1 belt-and-suspenders bound: transitioned longer than max.
        if carrier.transitioned_at is not None:
            age_h = (now - carrier.transitioned_at).total_seconds() / 3600.0
            if age_h > DP_TRANSITION_MAX_DURATION_H:
                _LOGGER.info(
                    "drain-precedence restore: transitioned age %.2fh exceeds "
                    "DP_TRANSITION_MAX_DURATION_H=%.2f → rejecting, fresh HOLD_ONLY",
                    age_h, DP_TRANSITION_MAX_DURATION_H,
                )
                return DrainPrecedenceState()

    return carrier


def serialize_for_kv(carrier: DrainPrecedenceState) -> str:
    """Serialize carrier to a JSON string suitable for `save_energy_state`."""
    return json.dumps(carrier.to_dict(), separators=(",", ":"))


# ==========================================================================
# Master-switch gate
# ==========================================================================


def is_dp_enabled(coordinator: Any = None) -> bool:
    """Master kill-switch reader.

    Session B1: if a coordinator is passed, read its `dp_enabled` attr
    (backed by `entry.options[CONF_ENERGY_DP_ENABLE]` via the Switch
    entity). Falls back to the module constant when no coordinator is
    supplied (state-machine unit tests, first-boot before entities exist).
    """
    if coordinator is not None:
        val = getattr(coordinator, "dp_enabled", None)
        if val is not None:
            return bool(val)
    return bool(CONF_DP_ENABLE)
