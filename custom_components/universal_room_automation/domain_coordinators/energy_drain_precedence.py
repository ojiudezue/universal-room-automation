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
    CONF_DP_MARGIN_MIN,
    CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT,
    DP_CAPACITY_KWH_PER_SOC_PP,
    DP_KV_KEY,
    DP_L1_RATE_THRESHOLD_KW,
    DP_NIGHT_WINDOW_END_HOUR,
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

    # B2c-2 item 2 (MEDIUM): TRANSITIONED / MUST_START_FORCED are NEVER
    # restored as-such. The paused-EVSE id set is NOT persisted with the
    # carrier — a restored TRANSITIONED state would leave `_paused_by_dp`
    # empty on the coordinator side, so the reversion sweep would be a
    # no-op and the state would be pointlessly stuck. Rather than resurrect
    # half-actuated state (INV-DP1/INV-DP2 hazard), we always coerce these
    # states to fresh HOLD_ONLY on boot; the next decision tick re-arms
    # from live signals (charging + kill-switch), which is authoritative.
    #
    # The prior expired-deadline / age-guard branches were the correct
    # rejections when the restored-as-TRANSITIONED path was live; with
    # that path retired they are dead code. `_save_evse_state` may still
    # WRITE a TRANSITIONED blob (single-writer state machine on the write
    # side is authoritative); the READ side collapses it.
    if carrier.state in (DPState.TRANSITIONED, DPState.MUST_START_FORCED):
        _LOGGER.info(
            "drain-precedence restore: %s not restorable "
            "(paused set not persisted) → fresh HOLD_ONLY; next tick re-arms",
            carrier.state.value,
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


# ==========================================================================
# Session B2a — pure eval + tick driver (NO actuation)
# --------------------------------------------------------------------------
# This session lands the decision math + the state-machine driver that
# updates the carrier and requests a KV persist. Actuation (paused_by_dp,
# reserve floor composition, must-start-by fire, write-verify extension)
# is Session B2b per the split. Tests here exercise the PURE surfaces
# only — no HA imports, no coordinator, no dispatcher.
#
# Design contracts:
#   - Every input is passed in explicitly via TransitionInputs. No hidden
#     reads (Bug Class #7 — stale data source resistance).
#   - Every decision returns a TransitionDecision carrying reason + snapshot.
#     Reason strings are stable identifiers callers can match on.
#   - The clock is passed via `now_provider: Callable[[], datetime]`.
#     NEVER wall-clock-couple (v5.17.1 _FrozenClock lesson).
#   - `_dp_maybe_tick` is the sole state-machine entry point. It NEVER
#     mutates external state; it mutates the carrier + calls the optional
#     persister callback when the carrier state edge fires.
# ==========================================================================


# Stable decision reason codes (tests match on these).
DP_REASON_KILL_SWITCH_OFF = "kill_switch_off"
DP_REASON_BLIND_HOLD = "blind_hold"
DP_REASON_FORCE_CHARGE_ACTIVE = "force_charge_active"
DP_REASON_L1_ONLY = "l1_only"
DP_REASON_NO_CHARGING_EVSE = "no_charging_evse"
DP_REASON_MISSING_SOC = "missing_soc"
DP_REASON_MISSING_INPUTS = "missing_inputs"
DP_REASON_ALREADY_BELOW_TARGET = "already_below_target"
DP_REASON_DOES_NOT_FIT = "does_not_fit"
DP_REASON_FITS = "fits"


@dataclass(frozen=True)
class TransitionInputs:
    """All inputs the eval needs. Callers build this from live readers.

    Every field is required except optionals used only for observability
    or diagnostic reason routing. The eval performs NO hidden reads — this
    is the sole source of truth for the decision.
    """

    # Kill-switch + mode gates
    dp_enabled: bool
    is_blind_hold: bool
    force_charge_active: bool

    # Battery state
    soc: Optional[int]  # % (0-100); None → MISSING_SOC hold
    drain_target_soc: int  # % floor to drain toward (max()-composed by actuation)

    # Charger state
    any_evse_charging: bool
    charger_rate_kw: float  # highest available rate across charging EVSEs
    needed_kwh: float  # projected car energy need

    # House-load model
    house_load_kw: float  # per CONF_DP_HOUSE_LOAD_SOURCE resolution

    # Time
    now: datetime  # tz-aware
    must_start_by_dt: datetime  # tz-aware; from compute_must_start_by

    # Knobs
    margin_min: int  # safety margin in minutes
    eval_delay_min: int  # HOLD_PRE_EVAL wait before firing

    # Optional constants override (tests / probe replay); defaults from module
    capacity_kwh_per_soc_pp: float = DP_CAPACITY_KWH_PER_SOC_PP
    l1_rate_threshold_kw: float = DP_L1_RATE_THRESHOLD_KW

    def to_snapshot(self) -> dict[str, Any]:
        """JSON-safe input snapshot for carrier.last_eval_snapshot."""
        return {
            "dp_enabled": bool(self.dp_enabled),
            "is_blind_hold": bool(self.is_blind_hold),
            "force_charge_active": bool(self.force_charge_active),
            "soc": self.soc,
            "drain_target_soc": int(self.drain_target_soc),
            "any_evse_charging": bool(self.any_evse_charging),
            "charger_rate_kw": float(self.charger_rate_kw),
            "needed_kwh": float(self.needed_kwh),
            "house_load_kw": float(self.house_load_kw),
            "now": self.now.isoformat(),
            "must_start_by_dt": self.must_start_by_dt.isoformat(),
            "margin_min": int(self.margin_min),
            "eval_delay_min": int(self.eval_delay_min),
        }


@dataclass(frozen=True)
class TransitionDecision:
    """Pure eval output. Contains the transition verdict plus the numbers
    that justify it — those numbers ride the observability snapshot and
    the info-log line so every decision is auditable post-fact.
    """

    transition: bool
    reason: str
    drain_hours: Optional[float]
    charge_hours: Optional[float]
    margin_hours: float
    hours_until_must_start_by: Optional[float]
    computed_start_dt: Optional[datetime]
    computed_finish_dt: Optional[datetime]

    def to_snapshot(self) -> dict[str, Any]:
        """JSON-safe decision snapshot for carrier.last_eval_snapshot."""
        return {
            "transition": bool(self.transition),
            "reason": self.reason,
            "drain_hours": self.drain_hours,
            "charge_hours": self.charge_hours,
            "margin_hours": self.margin_hours,
            "hours_until_must_start_by": self.hours_until_must_start_by,
            "computed_start_dt": (
                self.computed_start_dt.isoformat()
                if self.computed_start_dt else None
            ),
            "computed_finish_dt": (
                self.computed_finish_dt.isoformat()
                if self.computed_finish_dt else None
            ),
        }


def _no_fit(reason: str, inputs: TransitionInputs) -> TransitionDecision:
    """Build a HOLD decision with the margin_hours attribution intact."""
    margin_h = float(inputs.margin_min) / 60.0
    return TransitionDecision(
        transition=False,
        reason=reason,
        drain_hours=None,
        charge_hours=None,
        margin_hours=margin_h,
        hours_until_must_start_by=None,
        computed_start_dt=None,
        computed_finish_dt=None,
    )


def evaluate_dp_transition(inputs: TransitionInputs) -> TransitionDecision:
    """Pure eval: does the hold-then-drain-then-charge plan fit tonight?

    Gate order (top-first — earlier gates cannot be masked by later math):
        1. INV-DP4 — blind-hold: no fresh SOC → hold stands unconditionally.
        2. Kill switch: dp_enabled False → hold.
        3. Force-charge yield: A-H1 force-charge wins unconditionally.
        4. No charging EVSE: nothing to plan against → hold.
        5. Missing SOC: cannot compute drain time → hold.
        6. L1-only: 16h L1 vs 9h night — never fits, per P4 (§345 of plan).
        7. Already at/below drain target: nothing to drain → hold.
        8. Arithmetic fits check.

    Returns a TransitionDecision with the numbers that justify it.
    """
    # (1) INV-DP4 blind-hold gate — TOP. Ratification #5: on the FIRST
    # sighted tick after blind-hold exit, an immediate one-shot re-eval
    # is legal (this function is called from _dp_maybe_tick which the
    # caller invokes on the fresh-sight tick). This function ONLY refuses
    # while is_blind_hold is TRUE.
    if inputs.is_blind_hold:
        return _no_fit(DP_REASON_BLIND_HOLD, inputs)

    # (2) Kill switch.
    if not inputs.dp_enabled:
        return _no_fit(DP_REASON_KILL_SWITCH_OFF, inputs)

    # (3) Force-charge yield (plan §127, interaction matrix row 1). A-H1
    # force-charge in energy_pool.py wins unconditionally; our eval must
    # yield rather than pause an EVSE force-charge wants running.
    if inputs.force_charge_active:
        return _no_fit(DP_REASON_FORCE_CHARGE_ACTIVE, inputs)

    # (4) No charging EVSE — nothing to plan against.
    if not inputs.any_evse_charging:
        return _no_fit(DP_REASON_NO_CHARGING_EVSE, inputs)

    # (5) Missing SOC — cannot compute drain_hours.
    if inputs.soc is None:
        return _no_fit(DP_REASON_MISSING_SOC, inputs)

    # (6) L1-only auto-hold (P4 verdict §345). Explicit branch, not an
    # emergent arithmetic outcome, per plan.
    if inputs.charger_rate_kw <= inputs.l1_rate_threshold_kw:
        return _no_fit(DP_REASON_L1_ONLY, inputs)

    # (7) Sanity: already at/below drain target. Nothing to drain toward.
    if int(inputs.soc) <= int(inputs.drain_target_soc):
        return _no_fit(DP_REASON_ALREADY_BELOW_TARGET, inputs)

    # (8) Arithmetic. Guard divide-by-zero-ish house_load / charger_rate.
    if inputs.house_load_kw <= 0.0 or inputs.charger_rate_kw <= 0.0 or inputs.needed_kwh <= 0.0:
        return _no_fit(DP_REASON_MISSING_INPUTS, inputs)

    drain_soc_pp = int(inputs.soc) - int(inputs.drain_target_soc)
    drain_energy_kwh = drain_soc_pp * float(inputs.capacity_kwh_per_soc_pp)
    drain_hours = drain_energy_kwh / float(inputs.house_load_kw)
    charge_hours = float(inputs.needed_kwh) / float(inputs.charger_rate_kw)
    margin_hours = float(inputs.margin_min) / 60.0

    hours_until_must_start_by = (
        (inputs.must_start_by_dt - inputs.now).total_seconds() / 3600.0
    )

    # The plan (§162-166) states: fits iff (drain + charge + margin) <=
    # night_hours_remaining AND charge_start <= must_start_by. When the
    # must_start_by deadline is the binding constraint, we require the
    # DRAIN portion + margin to fit before must_start_by (so the CHARGE
    # portion begins at or before must_start_by and finishes at
    # must_start_by + charge_hours). P4 replay confirms this framing on
    # all 7 nights (§334-346).
    # Plan §332-346: computed_start = now + drain_hours (margin is applied
    # to the FIT check, not to the computed start time — matches the P4
    # counterfactual table exactly). Finish = start + charge_hours.
    computed_start_dt = inputs.now + timedelta(hours=drain_hours)
    computed_finish_dt = computed_start_dt + timedelta(hours=charge_hours)

    # Primary fit test: drain + margin must complete by must_start_by, and
    # charge_hours must fit before end-of-night (default 06:00 next day).
    # We compute end_of_night from must_start_by's date at
    # DP_NIGHT_WINDOW_END_HOUR to avoid coupling to a distinct "night"
    # object — the must-start-by machinery already carries the correct
    # day-boundary semantics via compute_must_start_by().
    end_of_night = inputs.must_start_by_dt.replace(
        hour=DP_NIGHT_WINDOW_END_HOUR, minute=0, second=0, microsecond=0,
    )
    # If must_start_by hour is >= end_of_night hour on the same day, the
    # end_of_night wraps to the next day.
    if end_of_night <= inputs.must_start_by_dt:
        end_of_night = end_of_night + timedelta(days=1)

    # Fit test (plan §162-166):
    #   (drain + charge + margin) ≤ hours_until_end_of_night AND
    #   charge_start ≤ must_start_by
    # Margin is a safety cushion on the TOTAL night arithmetic, not an
    # offset on the charge-start clock.
    hours_until_end_of_night = (
        (end_of_night - inputs.now).total_seconds() / 3600.0
    )
    total_hours = drain_hours + charge_hours + margin_hours
    fits = (
        computed_start_dt <= inputs.must_start_by_dt
        and total_hours <= hours_until_end_of_night
    )

    if not fits:
        return TransitionDecision(
            transition=False,
            reason=DP_REASON_DOES_NOT_FIT,
            drain_hours=drain_hours,
            charge_hours=charge_hours,
            margin_hours=margin_hours,
            hours_until_must_start_by=hours_until_must_start_by,
            computed_start_dt=computed_start_dt,
            computed_finish_dt=computed_finish_dt,
        )

    return TransitionDecision(
        transition=True,
        reason=DP_REASON_FITS,
        drain_hours=drain_hours,
        charge_hours=charge_hours,
        margin_hours=margin_hours,
        hours_until_must_start_by=hours_until_must_start_by,
        computed_start_dt=computed_start_dt,
        computed_finish_dt=computed_finish_dt,
    )


# ==========================================================================
# State-machine tick driver
# ==========================================================================


def _snapshot_eval(
    inputs: TransitionInputs, decision: TransitionDecision,
) -> dict[str, Any]:
    """Combined input+decision blob for carrier.last_eval_snapshot."""
    return {
        "inputs": inputs.to_snapshot(),
        "decision": decision.to_snapshot(),
    }


def _dp_maybe_tick(
    carrier: DrainPrecedenceState,
    inputs: TransitionInputs,
    *,
    now_provider: Callable[[], datetime],
    persister: Optional[Callable[[DrainPrecedenceState], None]] = None,
) -> TransitionDecision:
    """State-machine tick driver — NO actuation.

    Called from the coordinator's decision cycle. Drives:
        HOLD_ONLY → HOLD_PRE_EVAL   when any_evse_charging & dp_enabled
        HOLD_PRE_EVAL → EVAL_TRANSITION   after eval_delay_min
        EVAL_TRANSITION → TRANSITIONED   iff eval says fits
        EVAL_TRANSITION → HOLD_ONLY      iff eval says no
        TRANSITIONED → HOLD_ONLY         when EVSE stops charging (Session
                                          B2b will add reversion + must-
                                          start-forced edges via a
                                          dedicated reversion path).
        HOLD_PRE_EVAL → HOLD_ONLY        when EVSE stops charging OR
                                          kill-switch flips off.

    Returns the eval decision if an eval was actually run this tick,
    otherwise returns a synthetic HOLD decision carrying the entry reason.
    The carrier is mutated in place; the optional `persister` is invoked
    on ANY state edge (self-loops do not persist to avoid write-flood).
    """
    now = now_provider()
    prev_state = carrier.state

    # Master gate — kill switch or no EVSE charging → drive back to HOLD_ONLY
    # from any pre-transition state. Do NOT collapse TRANSITIONED here;
    # B2b's actuation path is authoritative for exiting TRANSITIONED
    # (reversion sweep + must-start-by fire).
    if (not inputs.dp_enabled) or (not inputs.any_evse_charging):
        if carrier.state in (DPState.HOLD_ONLY, DPState.HOLD_PRE_EVAL):
            if carrier.state != DPState.HOLD_ONLY:
                try_transition(
                    carrier, DPState.HOLD_ONLY, now_provider=now_provider,
                )
                if persister is not None and carrier.state != prev_state:
                    persister(carrier)
            return _no_fit(
                DP_REASON_KILL_SWITCH_OFF if not inputs.dp_enabled
                else DP_REASON_NO_CHARGING_EVSE,
                inputs,
            )

    # From HOLD_ONLY → HOLD_PRE_EVAL when armed (charging + enabled).
    if carrier.state == DPState.HOLD_ONLY:
        if inputs.dp_enabled and inputs.any_evse_charging:
            try_transition(
                carrier, DPState.HOLD_PRE_EVAL, now_provider=now_provider,
            )
            if persister is not None:
                persister(carrier)
        return _no_fit(DP_REASON_NO_CHARGING_EVSE, inputs)

    # From HOLD_PRE_EVAL → EVAL_TRANSITION when eval_delay elapsed OR
    # blind-hold JUST exited (ratification #5: one-shot immediate re-eval).
    # We do NOT track a blind-hold edge here — the caller passes fresh
    # inputs each tick; the eval itself gates on is_blind_hold.
    if carrier.state == DPState.HOLD_PRE_EVAL:
        # Belt-and-suspenders: hold_started_at should be set by the
        # HOLD_ONLY → HOLD_PRE_EVAL edge; if it isn't (test poking the
        # carrier directly), treat now as the hold start.
        hold_started = carrier.hold_started_at or now
        elapsed_min = (now - hold_started).total_seconds() / 60.0
        if elapsed_min < float(inputs.eval_delay_min):
            # Still waiting — hold stands. Reason is diagnostic; caller
            # can also inspect carrier.state to distinguish.
            return _no_fit("waiting_eval_delay", inputs)
        # Move into the one-shot EVAL_TRANSITION state.
        try_transition(
            carrier, DPState.EVAL_TRANSITION, now_provider=now_provider,
        )
        if persister is not None:
            persister(carrier)

    # From EVAL_TRANSITION: fire eval; TRANSITIONED on fit, HOLD_ONLY on
    # no-fit. Snapshot goes into carrier.last_eval_snapshot regardless.
    if carrier.state == DPState.EVAL_TRANSITION:
        decision = evaluate_dp_transition(inputs)
        carrier.last_eval_at = now
        carrier.last_eval_snapshot = _snapshot_eval(inputs, decision)
        _LOGGER.info(
            "drain-precedence eval: transition=%s reason=%s "
            "drain_h=%s charge_h=%s margin_h=%.2f start=%s finish=%s",
            decision.transition,
            decision.reason,
            (f"{decision.drain_hours:.2f}"
             if decision.drain_hours is not None else "None"),
            (f"{decision.charge_hours:.2f}"
             if decision.charge_hours is not None else "None"),
            decision.margin_hours,
            (decision.computed_start_dt.isoformat()
             if decision.computed_start_dt else "None"),
            (decision.computed_finish_dt.isoformat()
             if decision.computed_finish_dt else "None"),
        )
        if decision.transition:
            # Stamp the must-start-by deadline for INV-DP2 restart guard.
            carrier.must_start_by_dt = inputs.must_start_by_dt
            try_transition(
                carrier, DPState.TRANSITIONED, now_provider=now_provider,
            )
        else:
            try_transition(
                carrier, DPState.HOLD_ONLY, now_provider=now_provider,
            )
        if persister is not None:
            persister(carrier)
        return decision

    # In TRANSITIONED: B2a records nothing but the tick — actuation +
    # reversion is B2b. Return a synthetic hold "already transitioned"
    # decision so callers can log; carrier state is authoritative.
    return _no_fit("already_transitioned", inputs)


