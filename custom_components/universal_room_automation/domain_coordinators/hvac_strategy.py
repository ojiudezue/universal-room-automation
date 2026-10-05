"""HVAC W1-B D1/D5 — per-BRAND thermostat strategy (thin, behaviour-neutral).

Plan: ``docs/planning/PLANNING_hvac_w1b_thermostat_definition.md`` REV 7,
§5 D1 / D5 / D2a / D2.5. Definition: ``docs/Coordinator/
THERMOSTAT_DEFINITION_CARRIER_BRYANT.md`` rev 2.

What lives here (and ONLY here — operator constraint 2026-09-27: nothing is
added to the ``emit_*`` funnels in ``hvac_setpoint.py``):

* ``WriteResult`` — quad-state ``APPLIED / SKIPPED_ALREADY_CORRECT /
  DEFERRED / FAILED``. Truthiness is BANNED (``bool(result)`` raises) so no
  caller can silently collapse four states into two.
* ``last_sent`` — the strategy layer's per-entity, per-verb record of the
  last value URA sent (D2a). No-op suppression (D2.5) lives on top of it:
  ``hold_preset`` returns ``SKIPPED_ALREADY_CORRECT`` and makes ZERO service
  calls when the intended preset equals the last sent value AND the live
  observation already shows it. Any write to the entity (any verb) clears
  every other verb's record; observed divergence clears the record.
  RAM-only — a restart forgets it, so the first post-boot write always
  emits (the safe direction).
* ``is_human_manual_snapshot`` — the D2.4 HUMAN_MANUAL classifier the five
  presets-only return sites consult: a snapshot preset of ``manual`` /
  ``None`` / ``""`` has no named profile to pin, so the return falls back
  to a raw setpoint restore (``reason`` prefixed ``human_manual_``).
* ``strategy_for(hass, entity_id)`` — dispatch by the entity registry's
  ``platform``; cached per platform; a registry miss returns the generic
  default for THIS call and is NOT cached.

Resume-then-pin stays exactly where it lives (``hvac_setpoint.
emit_set_preset_mode`` / ``_needs_resume_first``): ``hold_preset`` calls
the funnel, so the Carrier quirk keeps working for Carrier entities and the
funnel's capability check keeps it away from thermostats that do not
advertise ``resume``. ``_snapshot_climate_state`` (W1-A) is exempt from
strategy dispatch by design — it reads raw attributes behind the funnel.

HVAC W1-C P1 (``docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md``
REV 3 + 3.1 errata) adds the frozen PROFILE CONTRACT on top:

* ``ProfileCapabilities`` + ``PersonChangeVerdict`` (public types, §3a).
* Every thermostat write site (A1–A14) calls a strategy method:
  ``hold_preset`` (S1 only — D2.5 no-op + ``last_sent``), ``pin_preset``
  (every other preset write), ``set_setpoints``, ``set_hvac_mode``. The
  last three are PURE funnel delegates in P1: they call the governed funnel
  with exactly the caller's kwargs, map the funnel's ``True`` / ``False`` to
  ``APPLIED`` / ``DEFERRED`` and let a wire exception PROPAGATE unchanged,
  so each site's existing exception branch runs byte-identically. They
  record nothing in ``last_sent`` (R2-3: no new verb is recorded in P1).
  The funnel is passed in by the caller (``emit=``) so the site keeps
  resolving its module-level funnel name at call time — the existing
  test seams that patch ``hvac_override.emit_set_temperature`` etc. keep
  intercepting, and the call graph is unchanged.
* ``release_hold`` exists with NO caller and records nothing in P1 (N3).
* ``is_manual_hold`` — the ONE ``"manual"`` predicate the §B readers call
  (Carrier and, in P1, Generic: identical ``preset == "manual"``).
* ``classify_person_change`` — Carrier: verbatim delegate to
  ``hvac_override.classify_manual_setpoint_change``; every other profile:
  a stub returning ``INCONCLUSIVE``, never raising (N2). No P1 caller.
* Suppression stays with the ~22 callers (N1); nothing here registers it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)

CARRIER_PLATFORM = "ha_carrier"
GENERIC_PLATFORM = "generic"

# Setpoint tolerance for the observation half of the no-op predicate. RUNG 1
# (module constant): the device displays whole degrees; half a unit is the
# smallest difference that is a real difference.
LAST_SENT_TOLERANCE_F: float = 0.5

# The anonymous-hold marker Carrier/Bryant reports in `preset_mode` /
# `hold_activity` after any raw setpoint write (definition doc §6). The ONE
# home of the literal for the shared HVAC modules (W1-C P1 deliverable 4:
# AST lint forbids a raw "manual" literal in hvac*.py outside this module
# and a reasoned allowlist).
MANUAL_HOLD_PRESET: str = "manual"

# HVAC Batch C (CPR) — Carrier's "edit the current activity's comfort range
# in place, no hold" entity service (upstream ha_carrier #427, v2.28.4,
# `climate.py` `async_set_activity_setpoint`). This module is the ONLY place
# that names it (plan REV 3.1 F3); the funnel receives it as a kwarg.
CARRIER_ACTIVITY_SETPOINT_SERVICE: str = "set_activity_setpoint"


def _whole_degree(v: float) -> int:
    """Carrier displays whole °F (PRECISION_WHOLE); round half up."""
    import math  # noqa: PLC0415
    return int(math.floor(float(v) + 0.5))


class PersonChangeVerdict(str, Enum):
    """W1-C §3a / §3d — verdict of a person-change classification.

    HUMAN            revert / interrupt latch eligible
    DEVICE_SCHEDULE  thermostat-side schedule — never revert / never latch
    URA_ECHO         our own recent write matched
    INCONCLUSIVE     cannot tell (e.g. a non-Carrier profile in P1) — never
                     revert / never end a borrow / never latch
    """

    HUMAN = "human"
    DEVICE_SCHEDULE = "device_schedule"
    URA_ECHO = "ura_echo"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class PersonChange:
    """Result of ``classify_person_change``.

    ``verdict is None`` = not a person-change candidate at all (the Carrier
    classifier's ``none``: not both-heat_cool / not both-manual / a leg not
    numeric / no leg changed). ``delta_f`` is None in P1 (the Carrier
    delegate computes no delta; the arrester measures it against a
    reference preset elsewhere).
    """

    verdict: Optional[PersonChangeVerdict]
    changed_legs: tuple[str, ...] = ()
    delta_f: Optional[float] = None


@dataclass(frozen=True)
class ProfileCapabilities:
    """W1-C §3a — what a thermostat profile can do. RUNG 1 (module constant
    on each concrete strategy): physics / protocol facts change only by
    reviewed code. NO P1 CONSUMER reads these fields — P2 pipes
    ``feature_available`` to the degraded-feature surface and resolves echo
    TTLs from here at suppress time (F7). ``echo_ttl_s is None`` = timings
    TBD → the profile is UNDISPATCHABLE (F4)."""

    platform: str
    manufacturer: Optional[str]
    has_named_presets: bool
    named_preset_vocabulary: frozenset
    has_heat_cool_mode: bool
    setpoint_shape: str  # "dual_leg" | "single_setpoint"
    supports_resume: bool
    supports_activity_setpoint: bool
    has_next_activity_time: bool
    has_write_confirmation_feed: bool
    has_mode_select: bool
    mode_select_options: frozenset
    hold_via: str  # "preset" | "mode_select" | "setpoint_only" | "unsupported"
    hold_release_mechanism: str
    equipment_telemetry: frozenset
    echo_ttl_s: Optional[int]
    preset_echo_ttl_s: Optional[int]
    write_rate_min_interval_s: int
    retry_interval_s: int
    person_change_match_window_s: Optional[int]
    person_change_shape: str  # "heat_cool_both_legs" | "single_setpoint" | "select_or_setpoint"


# Carrier timings MIRROR the live module constants they will replace in P2
# (unread in P1; pinned equal by test_w1c_p1_carrier_capabilities_mirror_constants):
#   echo_ttl_s 15        = hvac_override.SUPPRESS_TTL_SECONDS
#   preset_echo_ttl_s 120 = hvac_override.SUPPRESS_TTL_SECONDS_PRESET
#   write_rate 60         = hvac_const.HVAC_FAST_PATH_MIN_INTERVAL_S
#   retry_interval 0      = hvac_setpoint resume-then-pin retries at once
CARRIER_CAPABILITIES = ProfileCapabilities(
    platform=CARRIER_PLATFORM,
    manufacturer="Carrier",
    has_named_presets=True,
    named_preset_vocabulary=frozenset({"home", "away", "sleep", "wake", "vacation"}),
    has_heat_cool_mode=True,
    setpoint_shape="dual_leg",
    supports_resume=True,
    supports_activity_setpoint=True,
    has_next_activity_time=True,
    # HVAC-WRITE-CONFIRMATION-ORACLE-1 (parked): neither feed confirms a
    # write reliably (state-of-play §10 C22/C23).
    has_write_confirmation_feed=False,
    has_mode_select=False,
    mode_select_options=frozenset(),
    hold_via="preset",
    hold_release_mechanism="resume_service",
    # P4 owns the equipment-telemetry inventory (§E); empty until then.
    equipment_telemetry=frozenset(),
    echo_ttl_s=15,
    preset_echo_ttl_s=120,
    write_rate_min_interval_s=60,
    retry_interval_s=0,
    person_change_match_window_s=None,
    person_change_shape="heat_cool_both_legs",
)

# Generic (§3d, this cycle): holds UNSUPPORTED — no invented setpoints, no
# borrows, no nudges. In P1 these declarations have NO consumer: a Generic
# zone still routes every write through the same funnels as Carrier (N2);
# the degraded surface bites from P2.
GENERIC_CAPABILITIES = ProfileCapabilities(
    platform=GENERIC_PLATFORM,
    manufacturer=None,
    has_named_presets=False,
    named_preset_vocabulary=frozenset(),
    has_heat_cool_mode=False,
    setpoint_shape="dual_leg",
    supports_resume=False,
    supports_activity_setpoint=False,
    has_next_activity_time=False,
    has_write_confirmation_feed=False,
    has_mode_select=False,
    mode_select_options=frozenset(),
    hold_via="unsupported",
    hold_release_mechanism="unsupported",
    equipment_telemetry=frozenset(),
    echo_ttl_s=15,
    preset_echo_ttl_s=120,
    write_rate_min_interval_s=60,
    retry_interval_s=0,
    person_change_match_window_s=600,
    person_change_shape="single_setpoint",
)


class WriteStatus(str, Enum):
    APPLIED = "applied"
    SKIPPED_ALREADY_CORRECT = "skipped_already_correct"
    DEFERRED = "deferred"
    FAILED = "failed"


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a strategy write. Inspect ``.status``; never truth-test."""

    status: WriteStatus
    reason: str = ""
    exc: Optional[str] = None

    def __bool__(self) -> bool:  # pragma: no cover - guarded by test
        raise TypeError(
            "WriteResult truthiness is banned — inspect .status "
            "(APPLIED / SKIPPED_ALREADY_CORRECT / DEFERRED / FAILED)"
        )


@dataclass
class HoldObservation:
    """What the live climate entity shows right now (standard attributes)."""

    preset_mode: Optional[str]
    hold_activity: Optional[str]
    target_high: Optional[float]
    target_low: Optional[float]
    hvac_mode: Optional[str]
    preset_modes: tuple[str, ...] = ()
    read_at: float = field(default_factory=time.time)
    observed_at_source: str = "live_state"


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class GenericStrategy:
    """Default for any thermostat that is NOT Carrier/Bryant.

    * ``hold_preset`` = direct pin through the funnel (the funnel's
      capability check never sends ``resume`` to an entity that does not
      advertise it — Carrier vocabulary does not leak).
    * A thermostat with NO ``preset_modes`` cannot hold a preset →
      ``FAILED('no_presets_supported')`` with zero service calls; the
      caller falls back to setpoints.
    * HUMAN_MANUAL snapshot := the snapshot preset is empty/None OR the
      entity advertises no presets at all (nothing nameable to pin).
    """

    platform: str = GENERIC_PLATFORM
    capabilities: ProfileCapabilities = GENERIC_CAPABILITIES
    # HVAC Batch C (REV 5 F9): the brand's own app name for user-facing NM
    # text ("check that preset in the <app>"). None = no brand app; callers
    # fall back to the neutral "the thermostat app".
    app_name: Optional[str] = None

    def __init__(self) -> None:
        # entity_id -> {verb: (values_tuple, ts)}
        self._last_sent: dict[str, dict[str, tuple[Any, float]]] = {}

    # ---- observation -------------------------------------------------
    def observe(self, hass: Any, entity_id: str) -> Optional[HoldObservation]:
        try:
            st = hass.states.get(entity_id) if hass is not None else None
        except Exception:  # noqa: BLE001
            st = None
        if st is None:
            return None
        attrs = getattr(st, "attributes", None) or {}
        modes = attrs.get("preset_modes") or ()
        try:
            modes_t = tuple(str(m) for m in modes)
        except TypeError:
            modes_t = ()
        return HoldObservation(
            preset_mode=attrs.get("preset_mode"),
            hold_activity=attrs.get("hold_activity"),
            target_high=_as_float(attrs.get("target_temp_high")),
            target_low=_as_float(attrs.get("target_temp_low")),
            hvac_mode=getattr(st, "state", None),
            preset_modes=modes_t,
        )

    # ---- last_sent (D2a) ---------------------------------------------
    def last_sent(self, entity_id: str, verb: str) -> Optional[Any]:
        rec = self._last_sent.get(entity_id, {}).get(verb)
        return rec[0] if rec else None

    def _record_sent(self, entity_id: str, verb: str, values: Any) -> None:
        # Any actual write clears EVERY verb's record for the entity, then
        # records this one.
        self._last_sent[entity_id] = {verb: (values, time.time())}

    def _clear_sent(self, entity_id: str) -> None:
        self._last_sent.pop(entity_id, None)

    # ---- HUMAN_MANUAL classifier (D2.4) --------------------------------
    def is_human_manual_snapshot(
        self, pre_preset: Optional[str], *, preset_modes: tuple[str, ...] | None = None,
    ) -> bool:
        # FAIL-SAFE direction: a snapshot that names nothing pinnable
        # (empty / None) OR the anonymous-hold marker `manual` restores
        # SETPOINTS. A registry miss must never turn `manual` into a
        # "named" profile — that would drop the setpoint restore and
        # strand the zone at the borrowed value. The generic default adds
        # "entity advertises no presets at all".
        if pre_preset in (None, "", MANUAL_HOLD_PRESET):
            return True
        if preset_modes is not None and len(preset_modes) == 0:
            return True
        return False

    # ---- W1-C P1: the "manual" predicate (§B readers) ----------------
    def is_manual_hold(self, obs_or_preset: Any) -> bool:
        """True when the observation (or a bare ``preset_mode`` value) is
        the anonymous manual hold. P1: Carrier AND Generic are the identical
        ``preset == "manual"`` (byte-identity, N2); P2 may specialise."""
        if isinstance(obs_or_preset, HoldObservation):
            pm = obs_or_preset.preset_mode
        else:
            pm = obs_or_preset
        return pm == MANUAL_HOLD_PRESET

    # ---- W1-C P1: degraded-feature surface (no P1 consumer) ----------
    def feature_available(self, feature: str) -> bool:
        return self.feature_unavailable_reason(feature) is None

    def feature_unavailable_reason(self, feature: str) -> Optional[str]:
        caps = self.capabilities
        if feature == "hold":
            return None if caps.hold_via != "unsupported" else "profile_has_no_hold"
        if feature == "cpr":
            return None if caps.supports_activity_setpoint else "profile_has_no_activity_setpoint"
        if feature == "nudge" or feature.startswith("borrow."):
            # Borrows and nudges return through a NAMED preset pin.
            return None if caps.hold_via == "preset" else "profile_has_no_named_presets"
        return "unknown_feature"

    # ---- W1-C P1: pure funnel delegates (A2–A14) ---------------------
    @staticmethod
    def _map_funnel_result(wrote: Any) -> WriteResult:
        # The funnels return True (issued) / False (comfort-delay gate
        # deferred) and RAISE on a wire failure — the exception is NOT
        # caught here (each site keeps its own exception branch).
        if wrote:
            return WriteResult(WriteStatus.APPLIED, "emitted")
        return WriteResult(WriteStatus.DEFERRED, "gate_deferred")

    async def pin_preset(
        self,
        hass: Any,
        entity_id: str,
        preset: str,
        *,
        emit: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        """Every preset write that is NOT the S1 hold (returns, reverts,
        restores, egress resume, boot audit). Pure delegate: NO D2.5 no-op,
        NO ``last_sent`` record — the call is exactly
        ``emit(hass, entity_id, preset, **kwargs)``."""
        if emit is None:
            from .hvac_setpoint import emit_set_preset_mode as _funnel  # noqa: PLC0415
            emit = _funnel
        return self._map_funnel_result(await emit(hass, entity_id, preset, **kwargs))

    async def set_setpoints(
        self,
        hass: Any,
        entity_id: str,
        *,
        emit: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        """Dual-leg setpoint write. Pure delegate:
        ``emit(hass, entity_id, **kwargs)`` (``target_temp_low`` /
        ``target_temp_high`` / ``freeze_active`` / ``gate`` / ``blocking`` /
        ``site`` / ``zone_id`` / ``reason`` / ``excursion_id``)."""
        if emit is None:
            from .hvac_setpoint import emit_set_temperature as _funnel  # noqa: PLC0415
            emit = _funnel
        return self._map_funnel_result(await emit(hass, entity_id, **kwargs))

    async def set_hvac_mode(
        self,
        hass: Any,
        entity_id: str,
        mode: str,
        *,
        emit: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        """HVAC-mode write. Pure delegate:
        ``emit(hass, entity_id, mode, **kwargs)``."""
        if emit is None:
            from .hvac_setpoint import emit_set_hvac_mode as _funnel  # noqa: PLC0415
            emit = _funnel
        return self._map_funnel_result(await emit(hass, entity_id, mode, **kwargs))

    async def release_hold(
        self,
        hass: Any,
        entity_id: str,
        *,
        site: str,
        zone_id: str,
        reason: str,
    ) -> WriteResult:
        """Release URA's hold. P1: NO caller and records nothing (N3) —
        Carrier ``resume`` still lives inside ``emit_set_preset_mode``.
        From P2 it records under its own ``release_hold`` verb key."""
        from .hvac_setpoint import (  # noqa: PLC0415
            PRESET_RESUME,
            emit_set_preset_mode,
        )
        return self._map_funnel_result(await emit_set_preset_mode(
            hass, entity_id, PRESET_RESUME,
            blocking=True, site=site, zone_id=zone_id, reason=reason,
        ))

    # ---- W1-C P1: person-change classifier (no P1 caller) ------------
    def classify_person_change(
        self, old_state: Any, new_state: Any, *, recent: Any = (), tol: float = LAST_SENT_TOLERANCE_F,
    ) -> PersonChange:
        """Non-Carrier stub (N2): INCONCLUSIVE, never raises."""
        return PersonChange(PersonChangeVerdict.INCONCLUSIVE)

    # ---- HVAC Batch C (CPR): named-preset range verbs -----------------
    async def set_preset_range(
        self,
        hass: Any,
        entity_id: str,
        preset: str,
        low: float,
        high: float,
        *,
        gate: Callable[[], bool] | None = None,
        zone_id: str,
        site: str,
        reason: str,
        freeze_active: bool = False,
        emit: Callable[..., Any] | None = None,
    ) -> WriteResult:
        """Put ``(low, high)`` into the thermostat's own ``preset`` profile.

        Generic (REV 5 F1): a thermostat with no device-side preset profile
        has nothing to edit — ONE result, ``FAILED("preset_range_unsupported")``,
        ZERO service calls, nothing recorded. S10 treats it as a quiet skip.
        Brand adapters override this (Carrier below; ecobee in W1-C P2).
        """
        return WriteResult(WriteStatus.FAILED, "preset_range_unsupported")

    def preset_range_original(
        self, hass: Any, entity_id: str, preset: str,
    ) -> Optional[tuple[int, int]]:
        """REV 5 F2: the device's own range for ``preset`` right now, in the
        brand's display rounding, or None when there is no device-side
        preset profile (Generic) or it cannot be read. Never raises."""
        return None

    def preset_range_would_write(
        self, low: float, high: float,
    ) -> Optional[tuple[int, int]]:
        """CPR fix-up (D-HIGH-1): the exact ``(low, high)`` this adapter's
        ``set_preset_range`` would put on the wire for the requested range,
        in the brand's rounding — S10 compares the device original against
        THIS (not the unrounded request) before deciding whether an original
        must be persisted. Generic writes nothing -> None. Never raises."""
        return None

    # ---- preset hold (S1) ---------------------------------------------
    async def hold_preset(
        self,
        hass: Any,
        entity_id: str,
        preset: str,
        *,
        gate: Callable[[], bool] | None = None,
        blocking: bool = False,
        zone_id: str,
        reason: str,
        site: str,
        excursion_id: str | None = None,
    ) -> WriteResult:
        obs = self.observe(hass, entity_id)
        if obs is not None and not obs.preset_modes:
            return WriteResult(WriteStatus.FAILED, "no_presets_supported")
        # D2.5 no-op: BOTH halves must hold — last sent equals intent AND
        # the observation already shows it.
        sent = self.last_sent(entity_id, "set_preset_mode")
        if sent is not None and obs is not None:
            if sent == preset and obs.preset_mode == preset:
                return WriteResult(
                    WriteStatus.SKIPPED_ALREADY_CORRECT, "no_op_last_sent_matches",
                )
            if obs.preset_mode != sent:
                # Observed divergence from what we last sent — forget it.
                self._clear_sent(entity_id)
        from .hvac_setpoint import emit_set_preset_mode  # noqa: PLC0415
        try:
            wrote = await emit_set_preset_mode(
                hass,
                entity_id,
                preset,
                blocking=blocking,
                gate=gate,
                site=site,
                zone_id=zone_id,
                reason=reason,
                excursion_id=excursion_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._clear_sent(entity_id)
            return WriteResult(WriteStatus.FAILED, "emit_raised", type(exc).__name__)
        if not wrote:
            return WriteResult(WriteStatus.DEFERRED, "gate_deferred")
        self._record_sent(entity_id, "set_preset_mode", preset)
        return WriteResult(WriteStatus.APPLIED, "emitted")


class CarrierStrategy(GenericStrategy):
    """Carrier/Bryant via ``ha_carrier``.

    HUMAN_MANUAL snapshot := ``pre_preset in {manual, None, ""}`` (§5 D2.4
    definition, decision 30). ``manual`` is the anonymous hold a raw
    setpoint write leaves behind (definition doc §6); pinning it restores
    nothing, so a return with that snapshot restores setpoints instead.
    """

    platform: str = CARRIER_PLATFORM
    capabilities: ProfileCapabilities = CARRIER_CAPABILITIES
    app_name: Optional[str] = "Bryant"

    # ---- HVAC Batch C (CPR) — plan §3.3 P1–P6 -------------------------
    def _confirmed_on(self, obs: Optional[HoldObservation], preset: str) -> Optional[str]:
        """P1 + P2 as one predicate: None when the zone is confirmed on
        ``preset`` in heat_cool, else the DEFERRED reason."""
        if obs is None or obs.preset_mode != preset or obs.hold_activity != preset:
            # P1: both feeds must name the preset (no write into an
            # unstable hold during ha_carrier's 5-min post-write guard).
            return "activity_not_confirmed"
        if obs.hvac_mode != "heat_cool":
            # P2: the service takes low/high as given only in AUTO.
            return "not_heat_cool"
        return None

    def preset_range_original(
        self, hass: Any, entity_id: str, preset: str,
    ) -> Optional[tuple[int, int]]:
        """Carrier: the HA view of ``preset``'s profile (whole °F), readable
        only while the zone is confirmed on it (P1/P2) — the service edits
        the status-named activity, so no other profile is visible."""
        try:
            obs = self.observe(hass, entity_id)
            if self._confirmed_on(obs, preset) is not None:
                return None
            if obs.target_low is None or obs.target_high is None:
                return None
            return (_whole_degree(obs.target_low), _whole_degree(obs.target_high))
        except Exception:  # noqa: BLE001
            return None

    def preset_range_would_write(
        self, low: float, high: float,
    ) -> Optional[tuple[int, int]]:
        """Carrier P3: whole °F, round half up — the same rounding
        ``set_preset_range`` applies before its P4 compare and the wire."""
        try:
            return (_whole_degree(low), _whole_degree(high))
        except Exception:  # noqa: BLE001
            return None

    async def set_preset_range(
        self,
        hass: Any,
        entity_id: str,
        preset: str,
        low: float,
        high: float,
        *,
        gate: Callable[[], bool] | None = None,
        zone_id: str,
        site: str,
        reason: str,
        freeze_active: bool = False,
        emit: Callable[..., Any] | None = None,
    ) -> WriteResult:
        """Edit ``preset``'s comfort range in place via
        ``ha_carrier.set_activity_setpoint`` (no hold, never ``manual``).

        Observes and decides; records NOTHING in ``last_sent`` (it would wipe
        S1's D2.5 record). No ``await`` sits between the observation and the
        wire call: ``observe`` and the funnel's pre-call work are synchronous.
        """
        obs = self.observe(hass, entity_id)
        not_confirmed = self._confirmed_on(obs, preset)
        if not_confirmed is not None:
            return WriteResult(WriteStatus.DEFERRED, not_confirmed)
        if obs.target_low is None or obs.target_high is None:
            # No readable range = no original to restore later; never edit
            # a profile whose original S10 cannot capture (CPR §3.4).
            return WriteResult(WriteStatus.DEFERRED, "range_unreadable")
        # P3: whole °F.
        w_low, w_high = _whole_degree(low), _whole_degree(high)
        # P4: the HA view already shows it (HA's copy, not cloud truth).
        if (
            abs(obs.target_low - w_low) <= LAST_SENT_TOLERANCE_F
            and abs(obs.target_high - w_high) <= LAST_SENT_TOLERANCE_F
        ):
            return WriteResult(WriteStatus.SKIPPED_ALREADY_CORRECT, "ha_view_matches")
        if emit is None:
            from .hvac_setpoint import emit_set_activity_setpoint as _funnel  # noqa: PLC0415
            emit = _funnel
        # P5: the brand service is named HERE and passed to the funnel.
        try:
            wrote = await emit(
                hass,
                entity_id,
                service_domain=CARRIER_PLATFORM,
                service_name=CARRIER_ACTIVITY_SETPOINT_SERVICE,
                target_temp_low=float(w_low),
                target_temp_high=float(w_high),
                freeze_active=freeze_active,
                blocking=True,
                gate=gate,
                site=site,
                zone_id=zone_id,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            return WriteResult(WriteStatus.FAILED, "emit_raised", type(exc).__name__)
        if not wrote:
            return WriteResult(WriteStatus.DEFERRED, "gate_deferred")
        # P6: after-call check — did the status activity move under us?
        after = self.observe(hass, entity_id)
        if (
            after is None
            or after.preset_mode != preset
            or after.hold_activity != obs.hold_activity
        ):
            return WriteResult(WriteStatus.APPLIED, "possible_wrong_profile")
        return WriteResult(WriteStatus.APPLIED, "emitted")

    def classify_person_change(
        self, old_state: Any, new_state: Any, *, recent: Any = (), tol: float = LAST_SENT_TOLERANCE_F,
    ) -> PersonChange:
        """Verbatim delegate to ``hvac_override.classify_manual_setpoint_change``
        (the within-manual heat_cool four-leg classifier). Never raises."""
        try:
            from .hvac_override import (  # noqa: PLC0415
                MANUAL_CHANGE_HUMAN,
                MANUAL_CHANGE_URA_ECHO,
                classify_manual_setpoint_change,
                manual_changed_legs,
            )
            cls = classify_manual_setpoint_change(old_state, new_state, recent, tol)
            if cls == MANUAL_CHANGE_HUMAN:
                verdict: Optional[PersonChangeVerdict] = PersonChangeVerdict.HUMAN
            elif cls == MANUAL_CHANGE_URA_ECHO:
                verdict = PersonChangeVerdict.URA_ECHO
            else:
                return PersonChange(None)
            return PersonChange(verdict, tuple(manual_changed_legs(old_state, new_state)))
        except Exception:  # noqa: BLE001
            return PersonChange(None)

    def is_human_manual_snapshot(
        self, pre_preset: Optional[str], *, preset_modes: tuple[str, ...] | None = None,
    ) -> bool:
        # Carrier always advertises presets; only the snapshot value decides.
        return pre_preset in (None, "", MANUAL_HOLD_PRESET)


_STRATEGY_BY_PLATFORM: dict[str, GenericStrategy] = {}
_KNOWN: dict[str, type[GenericStrategy]] = {CARRIER_PLATFORM: CarrierStrategy}


def _entity_platform(hass: Any, entity_id: str) -> Optional[str]:
    """Read ``RegistryEntry.platform`` for the entity; None on any miss."""
    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
        reg = er.async_get(hass)
        entry = reg.async_get(entity_id) if reg is not None else None
        plat = getattr(entry, "platform", None) if entry is not None else None
        return str(plat) if plat else None
    except Exception:  # noqa: BLE001
        return None


def strategy_for(hass: Any, entity_id: str) -> GenericStrategy:
    """Dispatch by registry platform; cache per BRAND; miss → generic, uncached."""
    plat = _entity_platform(hass, entity_id)
    if plat is None:
        return GenericStrategy()
    cached = _STRATEGY_BY_PLATFORM.get(plat)
    if cached is not None:
        return cached
    cls = _KNOWN.get(plat, GenericStrategy)
    inst = cls()
    inst.platform = plat
    _STRATEGY_BY_PLATFORM[plat] = inst
    return inst


def strategy_for_platform(platform: Optional[str]) -> GenericStrategy:
    """Dispatch by a platform name already in hand (return sites that know
    their thermostat's brand from the token/zone). None → generic."""
    if not platform:
        return GenericStrategy()
    cached = _STRATEGY_BY_PLATFORM.get(platform)
    if cached is not None:
        return cached
    cls = _KNOWN.get(platform, GenericStrategy)
    inst = cls()
    inst.platform = platform
    _STRATEGY_BY_PLATFORM[platform] = inst
    return inst


def is_manual_hold_for(hass: Any, entity_id: Optional[str], preset: Any) -> bool:
    """§B reader entry point: the zone's profile decides whether ``preset``
    is the anonymous manual hold. Never raises (``strategy_for`` never
    raises; a missing entity id resolves the generic default)."""
    strat = strategy_for(hass, entity_id) if entity_id else GenericStrategy()
    return strat.is_manual_hold(preset)


def _test_reset_cache() -> None:
    _STRATEGY_BY_PLATFORM.clear()
