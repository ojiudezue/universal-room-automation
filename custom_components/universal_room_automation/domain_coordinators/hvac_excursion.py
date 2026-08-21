"""Governed thermostat excursion primitive (HVAC-GOVERNED-EXCURSION-1 D2).

See ``docs/planning/PLANNING_hvac_governed_excursion.md`` for the full
specification.

**Design change 2026-08-21 (post-Tier-3 review):** the operator ruled to
STRIP the lease GATE from the S1 preset-apply site. That gate was
scoped to protect excursions once HVAC-MANUAL-PRESET-CONTRACT-1 removes
the accidental ``preset_mode == "manual"`` lockout that protects them
TODAY. The sibling cycle has not landed. Until it does, the gate's
current value is zero while three reviewers independently measured its
risk as real (a suppression with no reliable discharge — the same bug
class as the lockout it insures against). So this module KEEPS the
snapshot / restore / persistence / kill-switch / boot-audit machinery
that is the cycle's actual value, and DROPS the tick-side gate + the
"lease" framing that named it.

What this module now provides:

* Public API: ``ExcursionToken``, ``begin_excursion``, ``return_excursion``,
  ``async_startup_excursion_audit``.
* Snapshot-restore semantics (§13.5 CLOSED): UNFILTERED. ``pre_preset``
  is the raw observed value at ``begin_excursion`` (may be ``"manual"``,
  ``""``, or ``None``).
* Persistence via URADatabase DAOs (``save_excursion_row`` /
  ``clear_excursion_row`` / ``get_all_excursion_rows``); non-nudge
  outcomes go to ``hvac_excursion_events`` via ``log_excursion_event``;
  nudge outcomes stay in ``ac_ramp_events``.
* Restart-safety via ``async_startup_excursion_audit`` — rehydrates
  the in-memory row registry from persisted rows, drops any row whose
  age already exceeds ``EXCURSION_LEASE_MAX_S`` at boot, and fires a
  low-severity ``stale_excursion_row`` notice on such drops. NUDGE and
  BANKING rows are cleared without rehydration (collision-avoidance
  with ``ac_reset_state.in_flight_nudge_*`` and ``_first_eval_done``
  respectively).
* Kill switch (§4.7) — BEGIN-ONLY. Switch entity lives in
  ``switch.py``; this module exposes ``set_kill_switch_enabled`` +
  ``is_kill_switch_enabled`` for the coordinator's property setter.

What this module NO LONGER provides (removed with the design change):

* ``lease_active(zone_id)`` as a consumed API — gone. The last (and
  only) consumer was the S1 preset-apply merge-point gate in
  ``hvac.py``; that gate is removed. The module retains an INTERNAL
  ``_row_present_and_fresh`` helper for the ``begin_excursion``
  overlap-detection invariant (§4.6 REJECT-on-existing-row) and for
  the boot-audit's own stale-row triage — both are bookkeeping, not
  runtime governance.
* The gate-related ``stuck_excursion_lease`` HIGH-severity NM alert.
  The rename to ``stale_excursion_row`` at severity=low reflects what
  the observation actually diagnoses: an un-returned row on the
  ``hvac_excursion_state`` table — a caller defect worth surfacing but
  NOT a signal of live wire misbehaviour (with the gate gone, an
  un-returned row does not defer decision writes and does not affect
  the thermostat).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)


# --- Knob ladder (§6) --------------------------------------------------------

EXCURSION_LEASE_SLACK_S: int = 30
"""Grace beyond a bounded ``duration_s`` before a row is treated as stale
(§4.4). Historically named for the deleted lease; kept as the "row stale"
grace for the boot audit + housekeeping paths."""

EXCURSION_LEASE_MAX_S: int = 7200  # 2 hours
"""Absolute cap on row age regardless of ``duration_s``. Sized to comfortably
cover a legitimately long egress (front door held open through a party)
while still an order of magnitude below the 14-hour stuck-manual
observations that motivated the cycle."""

EXCURSION_RETURN_BLOCKING: bool = True
"""The `blocking=True` contract on return-path emits (§4.1). Named so a
mutation drill can flip at one point."""


class EXCURSION_KIND(str, Enum):
    """Five kinds per §4.1.

    ``HARD_RESET_PRESET_ASSERT`` is DELIBERATELY absent (§8 non-goal 6).
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
    intended_mode: str  # #53 audit 2026-08-21: NARROW consumer — this
    # field is written to hvac_excursion_events.mode_before by
    # return_excursion (analytics use) and it is NOT consumed by any
    # return logic to drive mode restoration. Each site owns its own
    # mode-restore path (egress reads _paused_by_egress[zid]["mode"];
    # nudge/compromise/banking/preheat don't touch mode at all). Do NOT
    # add a mode-restore consumer here without wiring it into every
    # affected caller in one motion.
    duration_s: Optional[int]
    caller_site: str
    excursion_target_low: Optional[float] = None
    excursion_target_high: Optional[float] = None
    _returned: bool = False
    _return_outcome: Any = None

    def stale_ts(self) -> float:
        """Time at which this row becomes stale for boot-audit purposes.

        Same computation as the pre-design-change lease expiry:
        ``min(started + duration + SLACK, started + MAX)``. Retained
        because the boot audit still needs to distinguish rows that
        outlived their window from ones that are legitimately in-flight
        across a fast restart.
        """
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
    """Outcome of a return_excursion call.

    Field semantics (item-1 ruling, 2026-08-21):

    * ``restore_ok = True``  — a restore was ATTEMPTED and the wire landed
      as intended.
    * ``restore_ok = False`` — a restore was ATTEMPTED and the wire is
      wrong (defer, exception, immediate/settled mismatch). A genuine
      divergence between intent and thermostat state.
    * ``restore_ok = None``  — no restore was attempted. Either policy
      decided not to (immunity engaged, comfort-delay grace, feature
      turned off) OR the measurement is in flight (settled callback
      pending). ``trigger_detail`` names the reason.

    Analytics that count wire failures MUST filter on
    ``restore_ok = False`` — treating None as failure conflates
    deliberate policy skips with real divergences.
    """

    trigger: str
    restore_ok_immediate: Optional[bool] = None
    restore_ok: Optional[bool] = None
    detail: Optional[str] = None


# --- In-memory row registry --------------------------------------------------
#
# Bookkeeping only (post design-change). Populated by ``begin_excursion``
# and by ``async_startup_excursion_audit``; consumed by
# ``begin_excursion`` for the overlap-reject invariant, by
# ``return_excursion`` to look up the cached outcome on a double-return,
# and by tests via ``_test_*`` helpers. NO runtime write path consults
# this map — the S1 gate that used to is removed.

_rows: dict[str, ExcursionToken] = {}
_kill_switch_enabled: bool = True
_db_ref: Any = None            # URADatabase instance; None => no persistence
_hass_ref: Any = None          # HomeAssistant instance
_nm_stale_rows: set[str] = set()  # dedupe stale-row NM notices (per excursion_id)


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
        "excursion.kill_switch=%s (begin-only; existing rows unaffected)",
        _kill_switch_enabled,
    )


def is_kill_switch_enabled() -> bool:
    return _kill_switch_enabled


def bind(hass: Any, db: Any) -> None:
    """Bind the primitive to the HA + DB refs. Called by HVACCoordinator."""
    global _hass_ref, _db_ref
    _hass_ref = hass
    _db_ref = db


def _fire_stale_row_nm(zone_id: str, tok: ExcursionToken, elapsed_s: float) -> None:
    """Emit ``stale_excursion_row`` (low severity) once per excursion_id.

    Design-change 2026-08-21: renamed from ``stuck_excursion_lease`` +
    severity dropped from HIGH → low. With the tick-side gate removed,
    an un-returned row does NOT defer decision writes and does NOT
    affect the wire. The row is still worth surfacing (it is a caller
    defect — a begin without a matching return) but the alert must not
    describe a return-path clobber that it cannot diagnose from the row
    alone.
    """
    if tok.excursion_id in _nm_stale_rows:
        return
    _nm_stale_rows.add(tok.excursion_id)
    diagnosis = (
        f"HVAC excursion row for zone {zone_id} (kind={tok.kind.value}, "
        f"started_ts={tok.started_iso}, duration_s={tok.duration_s}, "
        f"elapsed={int(elapsed_s)}s) outlived its window without a matching "
        f"return_excursion call. Row cleared. This is bookkeeping — with "
        f"the S1 gate removed the row does not affect wire behaviour — "
        f"but a missing return in caller_site={tok.caller_site!r} is a "
        f"caller defect."
    )
    remedy = (
        f"Check the caller at {tok.caller_site!r} for a return path that "
        f"can silently skip return_excursion."
    )
    if _hass_ref is None:
        _LOGGER.info(
            "excursion.nm.stale_row not dispatched (hass not bound): %s",
            diagnosis,
        )
        return
    try:
        from ._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
        _hass_ref.async_create_task(
            fire_stuck_signal(
                _hass_ref,
                "stale_excursion_row",
                (zone_id, tok.excursion_id),
                diagnosis,
                remedy,
            )
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("excursion.nm.stale_row dispatch failed: %s", exc)


def _schedule_db_clear(zone_id: str) -> None:
    """Best-effort background DELETE of the state row."""
    if _db_ref is None or _hass_ref is None:
        return
    try:
        _hass_ref.async_create_task(_db_ref.clear_excursion_row(zone_id))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("excursion: db clear schedule failed: %s", exc)


def _row_present_and_fresh(zone_id: str) -> bool:
    """Internal invariant — is there a non-stale row for ``zone_id``?

    Consumed by:
      * ``begin_excursion`` for §4.6 REJECT-on-existing-row (a second
        begin on the same zone is a caller defect worth logging + refusing).
      * The boot audit (indirectly, via ``_reap_stale``).

    NOT a runtime tick gate — the pre-design-change ``lease_active`` name
    was removed to make that clear at every call site.
    """
    tok = _rows.get(zone_id)
    if tok is None:
        return False
    if _now() >= tok.stale_ts():
        _reap_stale(zone_id, tok)
        return False
    return True


def _reap_stale(zone_id: str, tok: ExcursionToken) -> None:
    """Delete a stale row + emit the low-severity NM notice."""
    elapsed = _now() - tok.started_ts
    _LOGGER.warning(
        "excursion: row for zone %s (kind=%s, started_ts=%s, "
        "duration_s=%s, elapsed=%.0fs) outlived its window without return "
        "— clearing (bookkeeping only; no wire effect)",
        zone_id, tok.kind.value, tok.started_iso, tok.duration_s, elapsed,
    )
    _fire_stale_row_nm(zone_id, tok, elapsed)
    _rows.pop(zone_id, None)
    _schedule_db_clear(zone_id)


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
    no wire write. Already-persisted rows are unaffected.

    §4.6 REJECT-on-existing-row: if a fresh row exists for ``zone_id``,
    log a warning and return ``None``.
    """
    if not _kill_switch_enabled:
        _LOGGER.debug(
            "excursion.begin: kill switch OFF — refusing site=%s kind=%s zone=%s",
            site, kind.value, zone_id,
        )
        return None

    if _row_present_and_fresh(zone_id):
        existing = _rows[zone_id]
        _LOGGER.warning(
            "excursion.begin: zone %s already has an active row "
            "(kind=%s, site=%s) — refusing to overwrite (site=%s, kind=%s)",
            zone_id, existing.kind.value, existing.caller_site,
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
    _rows[zone_id] = token

    # R1 ordering — DB write BEFORE the downstream wire call.
    if _db_ref is not None:
        try:
            await _db_ref.save_excursion_row(token.to_row())
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "excursion.begin: DB save failed for %s (in-memory row "
                "still recorded this process): %s",
                zone_id, exc,
            )

    _LOGGER.info(
        "excursion.begin: zone=%s kind=%s site=%s pre_preset=%r "
        "duration_s=%s stale_ts=%.0f",
        zone_id, kind.value, site, pre_preset, duration_s, token.stale_ts(),
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
    trigger_detail: Optional[str] = None,
) -> ReturnOutcome:
    """Close an excursion; clear the row + adjudicate the outcome.

    Callers still emit the actual wire writes in the current migration
    (each site performs its own (a) set_temperature → (b) set_preset_mode →
    (c) set_hvac_mode via the existing chokepoint helpers). This method's
    job is:

    * drop the in-memory row (bookkeeping);
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
        detail=trigger_detail,
    )
    token._returned = True
    token._return_outcome = outcome
    _rows.pop(token.zone_id, None)

    if _db_ref is not None:
        try:
            await _db_ref.clear_excursion_row(token.zone_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "excursion.return: DB clear failed for %s: %s",
                token.zone_id, exc,
            )
        # Non-nudge outcome landing (§4.5). Nudge writes to
        # ac_ramp_events via the caller's existing D1 path.
        if token.kind != EXCURSION_KIND.NUDGE:
            try:
                await _db_ref.log_excursion_event(
                    excursion_id=token.excursion_id,
                    zone_id=token.zone_id,
                    kind=token.kind.value,
                    started_ts=token.started_iso,
                    ended_ts=_now_iso(),
                    trigger=trigger,
                    trigger_detail=trigger_detail,
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
    """Rehydrate rows from persistence + fire preset restores (§4.4 restart).

    Walks every ``hvac_excursion_state`` row; per row:

    * NUDGE / BANKING — cleared without rehydration. NUDGE collides with
      ``ac_reset_state.in_flight_nudge_*`` (the authoritative ramp-audit
      home); BANKING collides with ``_first_eval_done`` in hvac_predict.
      **NUDGE preset restore (F1 fix, 2026-08-21):** for a NUDGE row whose
      ``pre_preset`` snapshot was non-empty, emit
      ``set_preset_mode(pre_preset)`` before clearing the row. Without
      this, a restart mid-nudge left ``preset_mode=manual`` behind on
      the Bryant/Carrier thermostat, reproducing the exact zone-lockout
      this cycle exists to fix. ``async_startup_ramp_audit`` restores
      only the setpoint; the preset restore has to happen here.

    * Any row whose age already exceeds ``EXCURSION_LEASE_MAX_S`` at boot:
      cleared with a ``stale_excursion_row`` NM notice.

    * All remaining rows (PREHEAT, COMPROMISE, EGRESS_PAUSE, fresh
      others): re-materialise the ``ExcursionToken`` into ``_rows`` so
      the boot-time overlap-reject invariant sees them and so the
      shipped per-kind restore paths that call ``return_excursion``
      after boot can find their token.
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
    dropped_stale = 0
    nudge_preset_restored = 0
    dropped_nudge = 0
    dropped_banking = 0
    for row in rows:
        kind_str = row.get("kind") or ""
        zone_id = row.get("zone_id")
        try:
            kind = EXCURSION_KIND(kind_str)
        except ValueError:
            _LOGGER.warning(
                "excursion.startup_audit: unknown kind %r for zone %s — dropping",
                kind_str, zone_id,
            )
            try:
                await _db_ref.clear_excursion_row(zone_id)
            except Exception:  # noqa: BLE001
                pass
            continue

        # Parse started_ts back to epoch for the stale-ts math.
        started_ts_iso = row.get("started_ts") or ""
        started_epoch: Optional[float] = None
        try:
            from datetime import datetime
            started_epoch = datetime.fromisoformat(started_ts_iso).timestamp()
        except Exception:  # noqa: BLE001
            started_epoch = None
        if started_epoch is None:
            started_epoch = now  # conservative — treat as fresh from now

        age = now - started_epoch

        # F1 fix (2026-08-21): NUDGE rows carry the pre-nudge preset;
        # ramp_audit restores only the setpoint, so if we drop these
        # without firing the preset restore we reproduce the manual-
        # lockout defect. Do it here BEFORE clearing the row.
        if kind == EXCURSION_KIND.NUDGE:
            pre_preset = row.get("pre_preset") or ""
            entity_id = None
            # Prefer the zone's live climate entity if available.
            if coord is not None:
                zm = getattr(coord, "_zone_manager", None)
                if zm is not None:
                    zone_obj = getattr(zm, "zones", {}).get(zone_id)
                    if zone_obj is not None:
                        entity_id = getattr(zone_obj, "climate_entity", None)
            if pre_preset and entity_id and hass is not None:
                try:
                    from .hvac_setpoint import emit_set_preset_mode  # noqa: PLC0415
                    await emit_set_preset_mode(
                        hass,
                        entity_id,
                        pre_preset,
                        blocking=True,
                        gate=None,
                        site="startup_audit_nudge_preset_restore",
                        zone_id=zone_id,
                        reason="startup_audit_nudge_preset_restore",
                    )
                    nudge_preset_restored += 1
                    _LOGGER.info(
                        "excursion.startup_audit: NUDGE preset restored "
                        "for zone %s (entity=%s preset=%s)",
                        zone_id, entity_id, pre_preset,
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "excursion.startup_audit: NUDGE preset restore "
                        "FAILED for zone %s (entity=%s preset=%s): %s "
                        "— zone may remain locked in preset_mode=manual",
                        zone_id, entity_id, pre_preset, exc,
                    )
            try:
                await _db_ref.clear_excursion_row(zone_id)
            except Exception:  # noqa: BLE001
                pass
            dropped_nudge += 1
            continue

        if kind == EXCURSION_KIND.BANKING:
            try:
                await _db_ref.clear_excursion_row(zone_id)
            except Exception:  # noqa: BLE001
                pass
            dropped_banking += 1
            continue

        # Non-nudge / non-banking: check for stale before rehydrating.
        if age >= EXCURSION_LEASE_MAX_S:
            tok = ExcursionToken(
                zone_id=zone_id,
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
            _fire_stale_row_nm(zone_id, tok, age)
            try:
                await _db_ref.clear_excursion_row(zone_id)
            except Exception:  # noqa: BLE001
                pass
            dropped_stale += 1
            continue

        tok = ExcursionToken(
            zone_id=zone_id,
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
        _rows[zone_id] = tok
        rehydrated += 1

    _LOGGER.info(
        "excursion.startup_audit: rehydrated=%d stale_dropped=%d "
        "nudge_dropped=%d nudge_preset_restored=%d banking_dropped=%d",
        rehydrated, dropped_stale, dropped_nudge,
        nudge_preset_restored, dropped_banking,
    )


# --- Structural release-on-incomplete-write helper --------------------------
#
# Operator ruling 2026-08-21: ONE structural fix for lease-release leaks
# on early-exit paths, "so a future site cannot forget." Every
# ``begin_excursion`` caller MUST go through this context manager. The
# pattern:
#
#     token = await begin_excursion(...)
#     async with auto_release_on_incomplete(
#         token, trigger="s5_wire_failed",
#     ) as guard:
#         wrote = await emit_set_temperature(...)
#         if wrote:
#             guard.mark_committed()   # wire landed; future return_excursion
#                                      # elsewhere will close the row cleanly
#             self._nudge_excursion_tokens[zone_id] = token
#         # if not wrote: block exits without mark_committed(); CM auto-
#         # releases with restore_ok=False + trigger.
#
# Semantics (see ReturnOutcome docstring):
#   * mark_committed() called      -> CM is a no-op; caller owns the return.
#   * Block exits by exception     -> CM releases restore_ok=False +
#                                     trigger_detail="wire_exception:<type>".
#   * Block exits without commit   -> CM releases restore_ok=False +
#                                     trigger_detail (defaulted or supplied).
#   * token is None (kill switch)  -> CM is a no-op.
#
# The CM DELIBERATELY does not swallow the wrapped exception; the caller
# still sees it. But the excursion row is closed either way.


class _AutoReleaseOnIncomplete:
    """Return-excursion-on-scope-exit context manager. See module docs."""

    def __init__(
        self,
        token: Optional[ExcursionToken],
        *,
        trigger: str,
        trigger_detail: Optional[str] = None,
    ):
        self.token = token
        self._trigger = trigger
        self._trigger_detail = trigger_detail
        self._committed = False

    def mark_committed(self) -> None:
        """Wire write landed; caller owns the future return_excursion."""
        self._committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        tok = self.token
        if tok is None:
            return False
        if self._committed:
            return False
        if tok._returned:
            return False
        # Block exited without mark_committed() — release with
        # restore_ok=False so the outcome row records the divergence.
        try:
            await return_excursion(
                tok,
                trigger=self._trigger,
                restore_ok=False,
                trigger_detail=(
                    self._trigger_detail
                    or (
                        f"wire_exception:{exc_type.__name__}" if exc_type
                        else "no_commit_on_scope_exit"
                    )
                ),
            )
        except Exception as _e:  # noqa: BLE001
            _LOGGER.debug(
                "auto_release_on_incomplete: return_excursion failed for "
                "%s: %s", tok.zone_id, _e,
            )
        return False  # do not suppress the exception


def auto_release_on_incomplete(
    token: Optional[ExcursionToken],
    *,
    trigger: str = "auto_release_on_incomplete",
    trigger_detail: Optional[str] = None,
) -> _AutoReleaseOnIncomplete:
    """Public factory for the auto-release context manager. See class docs.

    Callers get a ``guard`` object; on the success path call
    ``guard.mark_committed()``. On any early exit (defer, exception,
    fall-through) the CM auto-releases the excursion with
    restore_ok=False.
    """
    return _AutoReleaseOnIncomplete(
        token, trigger=trigger, trigger_detail=trigger_detail,
    )


# --- Test helpers ------------------------------------------------------------
#
# Tests import these directly. Not part of the runtime public API.


def _test_seed_row(
    zone_id: str,
    *,
    kind: EXCURSION_KIND = EXCURSION_KIND.NUDGE,
    duration_s: Optional[int] = 120,
    started_ts: Optional[float] = None,
    pre_preset: Optional[str] = None,
    site: str = "test_seed",
) -> ExcursionToken:
    """Insert a synthetic row token (tests only)."""
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
    _rows[zone_id] = tok
    return tok


# Legacy alias — existing tests may still call _test_seed_lease.
_test_seed_lease = _test_seed_row


def _test_has_row(zone_id: str) -> bool:
    """Bookkeeping probe for tests (previously exposed as ``lease_active``)."""
    return _row_present_and_fresh(zone_id)


def _test_clear_leases() -> None:
    _rows.clear()
    _nm_stale_rows.clear()


_test_clear_rows = _test_clear_leases


def _test_set_kill_switch(enabled: bool) -> None:
    global _kill_switch_enabled
    _kill_switch_enabled = bool(enabled)


def _test_bind(hass=None, db=None) -> None:
    global _hass_ref, _db_ref
    _hass_ref = hass
    _db_ref = db
