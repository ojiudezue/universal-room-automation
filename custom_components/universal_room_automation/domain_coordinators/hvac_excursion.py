"""Governed thermostat excursion primitive (HVAC-GOVERNED-EXCURSION-1 D2).

See ``docs/planning/PLANNING_hvac_governed_excursion.md`` REV-5 for the
full specification. This module ships:

* Public API (§4.1): ``ExcursionToken``, ``begin_excursion``,
  ``return_excursion``, ``lease_active``, ``async_startup_excursion_audit``.
* In-memory lease registry with **explicit, bounded expiry** per §4.4:
  ``expiry_ts = min(started_ts + duration_s + EXCURSION_LEASE_SLACK_S,
                    started_ts + EXCURSION_LEASE_MAX_S)``.
* Persistence via new DAOs on ``URADatabase``:
  ``save_excursion_row`` / ``clear_excursion_row`` /
  ``get_all_excursion_rows``, and ``log_excursion_event`` for non-nudge
  outcomes (§4.5). Nudge outcomes remain in ``ac_ramp_events`` via the
  new ``excursion_id`` column (§4.5 "Authority rule per kind").
* Boot audit (§4.4 restart interaction) that rehydrates live leases and
  emits a ``stuck_excursion_lease`` NM signal on any row whose age
  already exceeds ``EXCURSION_LEASE_MAX_S`` at boot.
* Kill switch (§4.7) — BEGIN-ONLY semantics. The switch entity lives in
  ``switch.py``; this module exposes ``set_kill_switch_enabled`` +
  ``is_kill_switch_enabled`` so the coordinator property can push state.
* Stuck-lease housekeeping (§4.4 + AC15): ``lease_active`` self-clears
  expired rows and fires the ``stuck_excursion_lease`` NM signal.

Snapshot semantics (§4.3): UNFILTERED. ``pre_preset`` is the raw
observed value at ``begin_excursion`` — may be ``"manual"``, may be
empty, may be ``None`` — with no interpretation. The self-disarm latch
this cycle exists to fix dissolves at source under UNFILTERED snapshot.

The lease surface is the load-bearing correctness property (§1.2): it
replaces the accidental ``preset_mode == "manual"`` lockout at
``hvac_preset.py:202-217`` with an explicit, visible, bounded lease
that the S1 preset-apply site consults at the emit merge point in
``_apply_house_state_presets``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)


# --- Knob ladder (§6) --------------------------------------------------------
#
# Both constants are at ladder rung 1 (module constant) per §6: making them
# operator-tunable would let an operator recreate the accidental-permanent-
# lock failure mode the lease exists to prevent.

EXCURSION_LEASE_SLACK_S: int = 30
"""Grace beyond a bounded ``duration_s`` before a tick treats the lease as
expired (§4.4). Covers the settle window + small margin for cloud-poll
latency."""

EXCURSION_LEASE_MAX_S: int = 7200  # 2 hours
"""Absolute cap on lease age regardless of ``duration_s`` (§4.4). Sized to
comfortably cover a legitimately long egress (front door held open through
a party) while still an order of magnitude below the 14-hour stuck-manual
observations that motivated the cycle."""

EXCURSION_RETURN_BLOCKING: bool = True
"""The `blocking=True` contract on return-path emits (§4.1). Named so
Reviewer C's mutation drill can flip at one point."""


class EXCURSION_KIND(str, Enum):
    """Five kinds per §4.1.

    ``HARD_RESET_PRESET_ASSERT`` is DELIBERATELY absent (§8 non-goal 6) —
    that path uses a small self-contained snapshot pair in the hard-reset
    lifecycle, NOT this primitive.
    """

    NUDGE = "nudge"
    COMPROMISE = "compromise"
    BANKING = "banking"
    PREHEAT = "preheat"
    EGRESS_PAUSE = "egress_pause"


@dataclass
class ExcursionToken:
    """Handle returned by ``begin_excursion`` (§4.1)."""

    zone_id: str
    excursion_id: str
    kind: EXCURSION_KIND
    started_ts: float  # epoch seconds (single-process authoritative)
    started_iso: str   # ISO for DB row
    pre_preset: Optional[str]  # SNAPSHOT — may be "manual"; None = no attr
    pre_target_low: Optional[float]
    pre_target_high: Optional[float]
    intended_mode: str
    duration_s: Optional[int]
    caller_site: str
    excursion_target_low: Optional[float] = None
    excursion_target_high: Optional[float] = None
    _returned: bool = False
    _return_outcome: Any = None

    def expiry_ts(self) -> float:
        """Explicit, bounded expiry per §4.4."""
        cap = self.started_ts + EXCURSION_LEASE_MAX_S
        if self.duration_s is None:
            return cap
        return min(self.started_ts + self.duration_s + EXCURSION_LEASE_SLACK_S, cap)

    def to_row(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "excursion_id": self.excursion_id,
            "kind": self.kind.value,
            "started_ts": self.started_iso,
            "duration_s": self.duration_s,
            "pre_preset": self.pre_preset,
            "pre_target_low": self.pre_target_low,
            "pre_target_high": self.pre_target_high,
            "excursion_target_low": self.excursion_target_low,
            "excursion_target_high": self.excursion_target_high,
            "intended_mode": self.intended_mode,
            "caller_site": self.caller_site,
        }


@dataclass
class ReturnOutcome:
    trigger: str
    restore_ok_immediate: Optional[bool] = None
    restore_ok: Optional[bool] = None
    detail: Optional[str] = None


# --- In-memory lease registry ------------------------------------------------
#
# The runtime source of truth for ``lease_active``. Populated by
# ``begin_excursion`` and by ``async_startup_excursion_audit`` (rehydration
# from ``hvac_excursion_state``). Cleared by ``return_excursion`` and by
# stuck-lease housekeeping in ``lease_active``.
#
# Module-global (not per-coordinator) because ``lease_active`` is called
# from ``_apply_house_state_presets`` where reaching a coordinator ref
# would require plumbing through many arms. One-URA-per-process makes a
# module singleton correct here (single_user_no_backcompat memory).

_leases: dict[str, ExcursionToken] = {}
_kill_switch_enabled: bool = True
_db_ref: Any = None            # URADatabase instance; None => no persistence
_hass_ref: Any = None          # HomeAssistant instance; for NM dispatch
_nm_stuck_leases: set[str] = set()  # dedupe stuck-lease NM emits (per zone)


def _now() -> float:
    return time.time()


def _now_iso() -> str:
    try:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return f"epoch:{_now()}"


def set_kill_switch_enabled(enabled: bool) -> None:
    """Push the kill switch state (called by the coordinator setter)."""
    global _kill_switch_enabled
    _kill_switch_enabled = bool(enabled)
    _LOGGER.info(
        "excursion.kill_switch=%s (begin-only; existing leases unaffected)",
        _kill_switch_enabled,
    )


def is_kill_switch_enabled() -> bool:
    return _kill_switch_enabled


def bind(hass: Any, db: Any) -> None:
    """Bind the primitive to the HA + DB refs. Called by HVACCoordinator."""
    global _hass_ref, _db_ref
    _hass_ref = hass
    _db_ref = db


def _fire_stuck_lease_nm(zone_id: str, tok: ExcursionToken, elapsed_s: float) -> None:
    """Emit ``stuck_excursion_lease`` via the existing stuck-signal dispatcher.

    §4.4 + AC15. Dedupe on ``excursion_id`` so a lease that fails to
    return only alerts once per lifetime. Uses
    ``domain_coordinators._stuck_signal_nm.fire_stuck_signal`` — the same
    pattern already imported at ``hvac.py:~1624``.
    """
    if tok.excursion_id in _nm_stuck_leases:
        return
    _nm_stuck_leases.add(tok.excursion_id)
    diagnosis = (
        f"HVAC excursion lease for zone {zone_id} (kind={tok.kind.value}, "
        f"started_ts={tok.started_iso}, duration_s={tok.duration_s}, "
        f"elapsed={int(elapsed_s)}s) expired without a return call — "
        "the thermostat wire is in an unknown state and the lease has "
        "been cleared. This indicates a return-path defect in the "
        "excursion caller."
    )
    remedy = (
        "Check the site named in caller_site on hvac_excursion_state "
        "for a missing return_excursion invocation."
    )
    if _hass_ref is None:
        _LOGGER.warning(
            "excursion.nm.stuck_lease not dispatched (hass not bound): %s",
            diagnosis,
        )
        return
    try:
        from ._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
        _hass_ref.async_create_task(
            fire_stuck_signal(
                _hass_ref,
                "stuck_excursion_lease",
                (zone_id, tok.excursion_id),
                diagnosis,
                remedy,
            )
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("excursion.nm.stuck_lease dispatch failed: %s", exc)


def _schedule_db_clear(zone_id: str) -> None:
    """Best-effort background DELETE of the state row."""
    if _db_ref is None or _hass_ref is None:
        return
    try:
        _hass_ref.async_create_task(_db_ref.clear_excursion_row(zone_id))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("excursion: db clear schedule failed: %s", exc)


def lease_active(zone_id: str) -> bool:
    """Return True iff an UNEXPIRED lease exists for ``zone_id`` (§4.4).

    Also self-clears an expired row it observes (housekeeping happens on
    the same read path — see §4.4 "Stuck-lease visibility") AND fires
    the ``stuck_excursion_lease`` NM alert on first observation of the
    expiry (§4.4 + AC15 discharge).
    """
    tok = _leases.get(zone_id)
    if tok is None:
        return False
    now = _now()
    if now >= tok.expiry_ts():
        elapsed = now - tok.started_ts
        _LOGGER.warning(
            "excursion: lease for zone %s (kind=%s, started_ts=%s, "
            "duration_s=%s, elapsed=%.0fs) expired without return — "
            "clearing (trigger_detail=lease_expired_no_return)",
            zone_id, tok.kind.value, tok.started_iso, tok.duration_s, elapsed,
        )
        _fire_stuck_lease_nm(zone_id, tok, elapsed)
        _leases.pop(zone_id, None)
        _schedule_db_clear(zone_id)
        return False
    return True


async def begin_excursion(
    hass,
    *,
    zone_id: str,
    entity_id: str,
    kind: EXCURSION_KIND,
    excursion_low: Optional[float] = None,
    excursion_high: Optional[float] = None,
    duration_s: Optional[int],
    freeze_active: bool = False,
    gate: Optional[Callable[[], bool]] = None,
    site: str,
    reason: str = "",
    arrester: Any = None,
    intended_mode: str = "heat_cool",
) -> Optional[ExcursionToken]:
    """Open an excursion; return a token or None (§4.1).

    §4.7 kill-switch: OFF => return ``None`` immediately, no state row,
    no lease, no suppress, no wire write. Already-persisted rows are
    unaffected (BEGIN-ONLY semantics).

    §4.6 REJECT-on-existing-row: if a lease exists for ``zone_id``, log
    a warning and return ``None`` — a second beginning on the same zone
    is a caller defect, not something to paper over by overwriting.
    """
    if not _kill_switch_enabled:
        _LOGGER.debug(
            "excursion.begin: kill switch OFF — refusing site=%s kind=%s zone=%s",
            site, kind.value, zone_id,
        )
        return None

    if zone_id in _leases and lease_active(zone_id):
        _LOGGER.warning(
            "excursion.begin: zone %s already has an active lease "
            "(kind=%s, site=%s) — refusing to overwrite (site=%s, kind=%s)",
            zone_id, _leases[zone_id].kind.value, _leases[zone_id].caller_site,
            site, kind.value,
        )
        return None

    # UNFILTERED snapshot per §4.3.
    pre_preset: Optional[str] = None
    pre_low: Optional[float] = None
    pre_high: Optional[float] = None
    try:
        st = hass.states.get(entity_id) if hass is not None else None
        if st is not None:
            pre_preset = st.attributes.get("preset_mode")
            _low = st.attributes.get("target_temp_low")
            _high = st.attributes.get("target_temp_high")
            if _low is not None:
                try:
                    pre_low = float(_low)
                except (TypeError, ValueError):
                    pre_low = None
            if _high is not None:
                try:
                    pre_high = float(_high)
                except (TypeError, ValueError):
                    pre_high = None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug(
            "excursion.begin: snapshot read failed for %s: %s",
            entity_id, exc,
        )

    now = _now()
    token = ExcursionToken(
        zone_id=zone_id,
        excursion_id=f"{kind.value}:{zone_id}:{int(now * 1000)}",
        kind=kind,
        started_ts=now,
        started_iso=_now_iso(),
        pre_preset=pre_preset,
        pre_target_low=pre_low,
        pre_target_high=pre_high,
        intended_mode=intended_mode,
        duration_s=duration_s,
        caller_site=site,
        excursion_target_low=excursion_low,
        excursion_target_high=excursion_high,
    )
    _leases[zone_id] = token

    # R1 ordering — DB write BEFORE any downstream wire call. Callers
    # perform the actual wire write themselves in the current migration
    # cut; the DB row here means a crash between now and the wire call
    # leaves the boot audit with an unadjudicated row to close.
    if _db_ref is not None:
        try:
            await _db_ref.save_excursion_row(token.to_row())
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "excursion.begin: DB save failed for %s (in-memory lease "
                "will still gate ticks this process): %s",
                zone_id, exc,
            )

    _LOGGER.info(
        "excursion.begin: zone=%s kind=%s site=%s pre_preset=%r "
        "duration_s=%s expiry=%.0f",
        zone_id, kind.value, site, pre_preset, duration_s, token.expiry_ts(),
    )
    return token


async def return_excursion(
    token: ExcursionToken,
    *,
    trigger: str,
    override_target_high: Optional[float] = None,
    restore_ok_immediate: Optional[bool] = None,
    restore_ok: Optional[bool] = None,
    preset_after: Optional[str] = None,
    target_low_after: Optional[float] = None,
    target_high_after: Optional[float] = None,
    mode_after: Optional[str] = None,
) -> ReturnOutcome:
    """Close an excursion; release the lease + adjudicate the outcome row.

    Callers still emit the actual wire writes in the current migration
    cut (each site performs (a) set_temperature → (b) set_preset_mode →
    (c) set_hvac_mode via the existing chokepoint helpers per §1). This
    method's job is:

    * release the in-memory lease so ticks stop deferring;
    * delete the persisted state row (§4.5);
    * write an outcome event row — nudge kinds via ``log_ac_ramp_event``
      (already the D1 site), others via ``log_excursion_event``.

    §4.6 double-return: second call is a no-op, returns cached outcome.
    """
    if token._returned:
        return token._return_outcome  # type: ignore[return-value]

    outcome = ReturnOutcome(
        trigger=trigger,
        restore_ok_immediate=restore_ok_immediate,
        restore_ok=restore_ok,
    )
    token._returned = True
    token._return_outcome = outcome
    _leases.pop(token.zone_id, None)

    if _db_ref is not None:
        try:
            await _db_ref.clear_excursion_row(token.zone_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "excursion.return: DB clear failed for %s: %s",
                token.zone_id, exc,
            )
        # Non-nudge outcome landing (§4.5). Nudge writes to
        # ac_ramp_events via the caller's existing D1 path; the
        # excursion_id is populated there so JOINs work either way.
        if token.kind != EXCURSION_KIND.NUDGE:
            try:
                await _db_ref.log_excursion_event(
                    excursion_id=token.excursion_id,
                    zone_id=token.zone_id,
                    kind=token.kind.value,
                    started_ts=token.started_iso,
                    ended_ts=_now_iso(),
                    trigger=trigger,
                    site=token.caller_site,
                    duration_actual_s=int(_now() - token.started_ts),
                    pre_preset=token.pre_preset,
                    pre_target_low=token.pre_target_low,
                    pre_target_high=token.pre_target_high,
                    preset_after=preset_after,
                    target_low_after=target_low_after,
                    target_high_after=target_high_after,
                    mode_before=token.intended_mode,
                    mode_after=mode_after,
                    restore_ok=restore_ok,
                    restore_ok_immediate=restore_ok_immediate,
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug(
                    "excursion.return: event log failed for %s: %s",
                    token.zone_id, exc,
                )

    _LOGGER.info(
        "excursion.return: zone=%s kind=%s trigger=%s",
        token.zone_id, token.kind.value, trigger,
    )
    return outcome


async def async_startup_excursion_audit(hass, coord) -> None:
    """Rehydrate live leases from persisted rows (§4.4 + §4.5 restart).

    Walks every ``hvac_excursion_state`` row; for each:

    * If the row's age already exceeds ``EXCURSION_LEASE_MAX_S``, treat
      it as stuck, fire the NM alert, and DELETE the row. The physical
      thermostat is NOT touched — a return that never fired left the
      wire in an unknown state and the audit is not entitled to guess
      (§4.4 stuck-lease clause).
    * Otherwise, re-materialise the ``ExcursionToken`` into ``_leases``
      so ticks continue to defer for the remaining lease window. The
      shipped per-kind restore paths (nudge audit at ``hvac_override.py:
      4057``, egress resume at ``hvac_egress.py``, etc.) still own the
      wire-restore for their kind; this audit just re-arms the lease.

    Filtered to NUDGE / COMPROMISE / PREHEAT / EGRESS_PAUSE (§4.5
    collision-avoidance: BANKING is owned by ``_first_eval_done``).
    """
    if _db_ref is None:
        _LOGGER.debug("excursion.startup_audit: DB not bound; skipping")
        return
    try:
        rows = await _db_ref.get_all_excursion_rows()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("excursion.startup_audit: scan failed: %s", exc)
        return

    now = _now()
    rehydrated = 0
    dropped_stuck = 0
    dropped_banking = 0
    for row in rows:
        kind_str = row.get("kind") or ""
        try:
            kind = EXCURSION_KIND(kind_str)
        except ValueError:
            _LOGGER.warning(
                "excursion.startup_audit: unknown kind %r for zone %s — dropping",
                kind_str, row.get("zone_id"),
            )
            try:
                await _db_ref.clear_excursion_row(row["zone_id"])
            except Exception:  # noqa: BLE001
                pass
            continue

        if kind == EXCURSION_KIND.BANKING:
            # §4.5 collision-avoidance — banking is owned by
            # `_first_eval_done` in hvac_predict.py; clear the row so
            # the audit doesn't fight it.
            try:
                await _db_ref.clear_excursion_row(row["zone_id"])
            except Exception:  # noqa: BLE001
                pass
            dropped_banking += 1
            continue

        # Parse started_ts (ISO) back to epoch for the lease math.
        started_ts_iso = row.get("started_ts") or ""
        started_epoch: Optional[float] = None
        try:
            from datetime import datetime
            started_epoch = datetime.fromisoformat(started_ts_iso).timestamp()
        except Exception:  # noqa: BLE001
            started_epoch = None
        if started_epoch is None:
            started_epoch = now  # conservative — a fresh lease from now

        # Boot-safety guard on a maximally-stale lease (§4.4).
        age = now - started_epoch
        if age >= EXCURSION_LEASE_MAX_S:
            tok = ExcursionToken(
                zone_id=row["zone_id"],
                excursion_id=row["excursion_id"],
                kind=kind,
                started_ts=started_epoch,
                started_iso=started_ts_iso,
                pre_preset=row.get("pre_preset"),
                pre_target_low=row.get("pre_target_low"),
                pre_target_high=row.get("pre_target_high"),
                intended_mode=row.get("intended_mode") or "heat_cool",
                duration_s=row.get("duration_s"),
                caller_site=row.get("caller_site") or "restart_audit",
            )
            _fire_stuck_lease_nm(row["zone_id"], tok, age)
            try:
                await _db_ref.clear_excursion_row(row["zone_id"])
            except Exception:  # noqa: BLE001
                pass
            dropped_stuck += 1
            continue

        # Rehydrate.
        tok = ExcursionToken(
            zone_id=row["zone_id"],
            excursion_id=row["excursion_id"],
            kind=kind,
            started_ts=started_epoch,
            started_iso=started_ts_iso,
            pre_preset=row.get("pre_preset"),
            pre_target_low=row.get("pre_target_low"),
            pre_target_high=row.get("pre_target_high"),
            intended_mode=row.get("intended_mode") or "heat_cool",
            duration_s=row.get("duration_s"),
            caller_site=row.get("caller_site") or "restart_audit",
            excursion_target_low=row.get("excursion_target_low"),
            excursion_target_high=row.get("excursion_target_high"),
        )
        _leases[row["zone_id"]] = tok
        rehydrated += 1

    _LOGGER.info(
        "excursion.startup_audit: rehydrated=%d stuck_dropped=%d "
        "banking_dropped=%d",
        rehydrated, dropped_stuck, dropped_banking,
    )


# --- Test helpers ------------------------------------------------------------
#
# Tests import these directly to seed/inspect the lease registry without
# reaching through hass state. Not part of the public runtime API.


def _test_seed_lease(
    zone_id: str,
    *,
    kind: EXCURSION_KIND = EXCURSION_KIND.NUDGE,
    duration_s: Optional[int] = 120,
    started_ts: Optional[float] = None,
    pre_preset: Optional[str] = None,
    site: str = "test_seed",
) -> ExcursionToken:
    """Insert a synthetic lease token (tests only)."""
    now = started_ts if started_ts is not None else _now()
    tok = ExcursionToken(
        zone_id=zone_id,
        excursion_id=f"test:{zone_id}:{int(_now() * 1000)}",
        kind=kind,
        started_ts=now,
        started_iso=_now_iso(),
        pre_preset=pre_preset,
        pre_target_low=None,
        pre_target_high=None,
        intended_mode="heat_cool",
        duration_s=duration_s,
        caller_site=site,
    )
    _leases[zone_id] = tok
    return tok


def _test_clear_leases() -> None:
    _leases.clear()
    _nm_stuck_leases.clear()


def _test_set_kill_switch(enabled: bool) -> None:
    global _kill_switch_enabled
    _kill_switch_enabled = bool(enabled)


def _test_bind(hass=None, db=None) -> None:
    global _hass_ref, _db_ref
    _hass_ref = hass
    _db_ref = db
