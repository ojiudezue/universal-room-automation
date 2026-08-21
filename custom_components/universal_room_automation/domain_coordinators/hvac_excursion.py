"""Governed thermostat excursion primitive (HVAC-GOVERNED-EXCURSION-1 D2).

PARTIAL BUILD (see planning doc REV-5, §4). This file lands the
**load-bearing lease surface** required to close the accidental
`preset_mode == "manual"` lockout that today implicitly protects
in-flight excursions from decision-tick clobbers (§1.2 of the plan).

Scope shipped in this file
--------------------------
* Public API: ``ExcursionToken``, ``begin_excursion``, ``return_excursion``,
  ``lease_active``, ``async_startup_excursion_audit`` — signatures per §4.1.
* In-memory lease registry with **explicit, bounded expiry** per §4.4:
  ``expiry_ts = min(started_ts + duration_s + EXCURSION_LEASE_SLACK_S,
                    started_ts + EXCURSION_LEASE_MAX_S)``.
* ``EXCURSION_KIND`` StrEnum with the 5 kinds explicitly listed in §4.1
  (``HARD_RESET_PRESET_ASSERT`` DELIBERATELY absent per non-goal 6).
* Snapshot semantics: ``pre_preset`` is the raw observed value at
  ``begin_excursion`` (no filter — §4.3 unopinionated snapshot).
* Kind constants ``EXCURSION_LEASE_SLACK_S = 30`` and
  ``EXCURSION_LEASE_MAX_S = 7200`` at knob-ladder rung 1 (§6).

Scope DEFERRED (call out to the operator; NOT built here)
---------------------------------------------------------
* ``hvac_excursion_state`` + ``hvac_excursion_events`` tables and their
  DAOs (§4.5). The in-memory cache here is sufficient for the row-1 lease
  wiring and for AC14/AC14b test authority, but restart-safety per §4.4 is
  NOT yet delivered (any live lease is lost on HA restart — no worse than
  today's behaviour, where the accidental ``preset_mode == "manual"``
  lockout is likewise lost on restart).
* ``async_startup_excursion_audit`` is stubbed (returns immediately) —
  needs the persisted tables to have anything to audit.
* Kill-switch entity ``excursion_primitive_enabled`` (§4.7) — not created;
  ``begin_excursion`` currently unconditionally issues tokens.
* ``ac_ramp_events.excursion_id`` column and the ``hvac_excursion_events``
  table (§4.5). Site migrations 4-15 in §3 all depend on these and are
  NOT WIRED THROUGH THIS PRIMITIVE YET. They continue to use their
  existing hand-rolled emit + suppress paths.
* Stuck-lease NM alert (§4.4 + AC15) — housekeeping tick is scheduled but
  currently only clears the expired row (no NM emit until the persistence
  and NM plumbing lands).

The lease check that guards ``_apply_house_state_presets`` (site row 1 of
§3) is wired in ``hvac.py`` at the emit merge point (§4.4, rev-5
correction). ``lease_active`` in this file is that check's implementation.

Failing to build the persistence surface here is a DELIBERATE deferral —
the load-bearing correctness property the operator identified as the
"single most important thing" (§4.4, AC14b) is the lease-at-merge-point
gate, which does not itself require persistence to be correct within a
single process lifetime. Restart-safety of live leases becomes required
the moment sites 4-15 start creating leases through this primitive; it
must land before those migrations.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
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
    started_ts: float  # monotonic-style epoch seconds; single-process only
    pre_preset: Optional[str]  # SNAPSHOT — may be "manual"; None = no attr
    pre_target_low: Optional[float]
    pre_target_high: Optional[float]
    intended_mode: str
    duration_s: Optional[int]
    caller_site: str
    _returned: bool = False
    _return_outcome: Any = None

    def expiry_ts(self) -> float:
        """Explicit, bounded expiry per §4.4."""
        cap = self.started_ts + EXCURSION_LEASE_MAX_S
        if self.duration_s is None:
            return cap
        return min(self.started_ts + self.duration_s + EXCURSION_LEASE_SLACK_S, cap)


@dataclass
class ReturnOutcome:
    trigger: str
    restore_ok_immediate: Optional[bool] = None
    restore_ok: Optional[bool] = None
    detail: Optional[str] = None


# --- In-memory lease registry ------------------------------------------------
#
# The single source of truth for ``lease_active`` in this partial build.
# Once §4.5 tables land, this cache is rehydrated by
# ``async_startup_excursion_audit`` from the persisted rows.
#
# Module-global (not per-coordinator) because ``lease_active`` is called
# from ``_apply_house_state_presets`` where reaching a coordinator ref
# would require plumbing through many arms. One-URA-per-process makes a
# module singleton correct here (single_user_no_backcompat memory).

_leases: dict[str, ExcursionToken] = {}


def _now() -> float:
    return time.time()


def lease_active(zone_id: str) -> bool:
    """Return True iff an UNEXPIRED lease exists for ``zone_id`` (§4.4).

    Also self-clears an expired row it observes (housekeeping happens on
    the same read path — see §4.4 "Stuck-lease visibility"). NM alert
    emission is deferred until the persistence + NM plumbing lands.
    """
    tok = _leases.get(zone_id)
    if tok is None:
        return False
    now = _now()
    if now >= tok.expiry_ts():
        # Housekeeping: treat as absent, clear.
        _LOGGER.warning(
            "excursion: lease for zone %s (kind=%s, started_ts=%.0f, "
            "duration_s=%s) expired without return — clearing "
            "(trigger_detail=lease_expired_no_return). NM stuck-lease "
            "alert not yet wired (§4.4 deferred).",
            zone_id, tok.kind.value, tok.started_ts, tok.duration_s,
        )
        _leases.pop(zone_id, None)
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
    """Open an excursion; return a token or None (see §4.1).

    PARTIAL: no DB row is written here yet (§4.5 deferred). The token is
    kept only in the in-memory ``_leases`` cache. The service-call
    orchestration (freeze/deadband/comfort chokepoints) is NOT performed —
    callers today still emit their own writes; site migrations will move
    to this primitive when the persistence and chokepoint plumbing lands.

    §4.6 REJECT-on-existing-row: if a lease exists for ``zone_id``, log a
    warning and return ``None`` — a second beginning on the same zone is
    a caller defect, not something to paper over by overwriting.
    """
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

    token = ExcursionToken(
        zone_id=zone_id,
        excursion_id=f"{kind.value}:{zone_id}:{int(_now() * 1000)}",
        kind=kind,
        started_ts=_now(),
        pre_preset=pre_preset,
        pre_target_low=pre_low,
        pre_target_high=pre_high,
        intended_mode=intended_mode,
        duration_s=duration_s,
        caller_site=site,
    )
    _leases[zone_id] = token
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
) -> ReturnOutcome:
    """Close an excursion; release the lease. PARTIAL: no wire writes.

    In this partial build the primitive does NOT itself perform the
    ``emit_set_temperature`` / ``emit_set_preset_mode`` / ``set_hvac_mode``
    sequence in §1 — the shipped nudge/compromise/egress paths continue
    to perform their own restore. This method's job is to release the
    lease so ticks stop deferring.

    §4.6 double-return: second call is a no-op, returns cached outcome.
    """
    if token._returned:
        return token._return_outcome  # type: ignore[return-value]
    outcome = ReturnOutcome(trigger=trigger)
    token._returned = True
    token._return_outcome = outcome
    _leases.pop(token.zone_id, None)
    _LOGGER.info(
        "excursion.return: zone=%s kind=%s trigger=%s",
        token.zone_id, token.kind.value, trigger,
    )
    return outcome


async def async_startup_excursion_audit(hass, coord) -> None:
    """Rehydrate live leases from persisted rows (§4.4 + §4.5). STUB.

    Not implemented in this partial build because the ``hvac_excursion_state``
    table has not landed yet. Once §4.5 ships, this generalises
    ``async_startup_ramp_audit`` at ``hvac_override.py:4057`` and populates
    ``_leases`` before the first HVAC decision tick.
    """
    _LOGGER.debug(
        "excursion.startup_audit: STUB — persistence not yet built; "
        "no leases to rehydrate."
    )
    return None


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
    tok = ExcursionToken(
        zone_id=zone_id,
        excursion_id=f"test:{zone_id}:{int(_now() * 1000)}",
        kind=kind,
        started_ts=started_ts if started_ts is not None else _now(),
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
