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
  W1-C P2 (``PLANNING_hvac_w1c_p2_ecobee.md`` REV 3 §4.8): the
  capabilities record only how a brand is commanded, read and classified —
  NEVER whether a URA feature runs (operator ruling 2026-10-03: the brand
  layer is a thin command adapter). P1's ``feature_available`` predicate is
  deleted; a thermostat that cannot do a verb says so in the verb's own
  ``WriteResult``.
* W1-C P2: ``EcobeeHomeKitStrategy`` (``homekit_controller`` + ecobee) —
  holds a preset by writing URA's effective heat_cool RANGE for it,
  reports the thermostat in Carrier's vocabulary through ``preset_of``.
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
    """How this brand is commanded, read and classified — never whether a
    URA feature runs (W1-C P2 §4.8, INV-F). RUNG 1 (module constant on each
    concrete strategy): physics / protocol facts change only by reviewed
    code. Consumed only inside this module (the AST lint forbids a
    ``.capabilities`` read anywhere else)."""

    platform: str
    manufacturer: Optional[str]
    hold_via: str  # "preset" | "setpoint_range" | "unsupported"
    setpoint_shape: str  # "dual_leg"
    echo_ttl_s: Optional[int]
    preset_echo_ttl_s: Optional[int]
    write_rate_min_interval_s: int
    retry_interval_s: int
    person_change_shape: str  # "heat_cool_both_legs"
    person_change_match_window_s: Optional[int]


# Carrier timings MIRROR the live module constants
# (pinned equal by test_carrier_capabilities_mirror_constants):
#   echo_ttl_s 15        = hvac_override.SUPPRESS_TTL_SECONDS
#   preset_echo_ttl_s 120 = hvac_override.SUPPRESS_TTL_SECONDS_PRESET
#   write_rate 60         = hvac_const.HVAC_FAST_PATH_MIN_INTERVAL_S
#   retry_interval 0      = hvac_setpoint resume-then-pin retries at once
CARRIER_CAPABILITIES = ProfileCapabilities(
    platform=CARRIER_PLATFORM,
    manufacturer="Carrier",
    hold_via="preset",
    setpoint_shape="dual_leg",
    echo_ttl_s=15,
    preset_echo_ttl_s=120,
    write_rate_min_interval_s=60,
    retry_interval_s=0,
    person_change_shape="heat_cool_both_legs",
    person_change_match_window_s=None,
)

# Generic: no way to hold a named preset (``hold_preset`` reports
# ``FAILED("no_presets_supported")`` on an entity with no presets). Every
# other verb routes through the same funnels as Carrier. W1-C P2 F2: the
# person-change shape is the same dual-leg heat_cool shape as every other
# profile (P1 declared single_setpoint / 600 s, inconsistent with dual_leg).
GENERIC_CAPABILITIES = ProfileCapabilities(
    platform=GENERIC_PLATFORM,
    manufacturer=None,
    hold_via="unsupported",
    setpoint_shape="dual_leg",
    echo_ttl_s=15,
    preset_echo_ttl_s=120,
    write_rate_min_interval_s=60,
    retry_interval_s=0,
    person_change_shape="heat_cool_both_legs",
    person_change_match_window_s=None,
)

# HVAC W1-C P2 — ecobee over HomeKit (``homekit_controller``).
HOMEKIT_PLATFORM = "homekit_controller"
ECOBEE_PROFILE = "ecobee_homekit"
# Device-registry manufacturer must CONTAIN this (case-insensitive). D0b
# discovery 2026-10-05: all three Wigton units read "ecobee Inc.".
ECOBEE_MANUFACTURER_MATCH = "ecobee"
# RUNG 1. D0b supervised probe 2026-10-05 (G2, all three units): a range
# write lands as legs equal to the written whole degrees; `.5` writes are
# rounded by the device (away from the mean), T = 0.50 °F. The adapter
# rounds to whole degrees before sending, so readback is exact; 0.5 °F is
# the inclusive matching tolerance for the projection, the within-manual
# classifier and the pair ring (``echo_tolerance_f``).
ECOBEE_RANGE_TOLERANCE_F: float = 0.5
# The comfort names HomeKit's ecobee "Current Mode" select can report
# (HA `homekit_controller/select.py` `EcobeeModeSelect._attr_options`,
# translation_key "ecobee_mode"). Anything else (incl. "unknown", which the
# select reads while a hold is active) is "no comfort setting readable" —
# never Away.
ECOBEE_COMFORT_OPTIONS: frozenset = frozenset({"home", "sleep", "away"})
ECOBEE_MODE_SELECT_TRANSLATION_KEY = "ecobee_mode"
# Presets the adapter can carry a range for (Seasonal Baseline Presets).
ECOBEE_RANGE_PRESETS: tuple = ("home", "sleep", "away", "vacation")

# D0b G3 (p95 echo 0.035–0.044 s on all three units) is far inside Carrier's
# 15 / 120 s windows, so the C1 per-profile TTL is not needed: same values.
ECOBEE_HOMEKIT_CAPABILITIES = ProfileCapabilities(
    platform=HOMEKIT_PLATFORM,
    manufacturer="ecobee",
    hold_via="setpoint_range",
    setpoint_shape="dual_leg",
    echo_ttl_s=15,
    preset_echo_ttl_s=120,
    write_rate_min_interval_s=60,
    retry_interval_s=0,
    person_change_shape="heat_cool_both_legs",
    person_change_match_window_s=None,
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
    profile_name: str = "generic"
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

    # ---- W1-C P2: the state read (§4.3) --------------------------------
    def preset_of(
        self, state: Any, default: Any = None, *, hass: Any = None,
        entity_id: Optional[str] = None,
    ) -> Any:
        """The thermostat's preset in Carrier's vocabulary. Carrier /
        Generic: the raw ``preset_mode`` attribute, VERBATIM, with the call
        site's own default (byte-identical to the pre-P2 reads; each site
        keeps its own ``or ""`` coercion outside this call)."""
        return (getattr(state, "attributes", None) or {}).get("preset_mode", default)

    def echo_tolerance_f(self) -> float:
        """§4.4: the tolerance the within-manual classifier (T1) and the
        pair ring (T2) use to recognise URA's own echo. Carrier / Generic:
        ``LAST_SENT_TOLERANCE_F`` (byte-identical)."""
        return LAST_SENT_TOLERANCE_F

    def hold_needs_reassert(self, hass: Any, entity_id: str, preset: str) -> bool:
        """S1 asks this when the zone already reads its target preset.
        True = the device does not carry URA's range for that preset any
        more, so S1 must hold it again. Carrier / Generic: the device preset
        IS the range — never (byte-identical: S1 skips as before)."""
        return False

    def reference_setpoints(
        self, hass: Any, entity_id: Optional[str], preset: str, baseline: Any,
    ) -> Any:
        """W1-C P2 fix (D MED-1): the ``(cool, heat)`` pair URA actually
        holds for ``preset`` on this thermostat — what the arrester and the
        startup audit measure a person's change against. Carrier / Generic:
        ``baseline`` returned unchanged (the device preset IS the range;
        byte-identical)."""
        return baseline

    # ---- W1-C P2: adapter state persistence (§4.2a) --------------------
    def export_state(self) -> dict[str, Any]:
        """Per-entity adapter state for the ``__w1c_adapter`` side-key.
        Carrier / Generic hold none."""
        return {}

    def rehydrate_state(self, blob: Any) -> bool:
        """Accept a persisted per-entity slice. False = this profile keeps
        no adapter state (the caller keeps the slice pending, verbatim)."""
        return False

    def flush_entity(self, entity_id: str) -> None:
        """Profile switch (§4.1): forget everything held for the entity."""
        self._clear_sent(entity_id)

    # ---- W1-C P2: integration freshness (§4.10) -------------------------
    def freshness_row(
        self, hass: Any, zone: Any, *, max_age_s: float,
        require_corroboration: bool, span_kw_fn: Callable[[Any], Any],
        now_utc: Any, state_age_fn: Any = None,
    ) -> tuple[dict[str, Any], bool]:
        """(row, qualifies). Non-Carrier profiles have no integration-
        staleness remedy: the row says ``not_applicable`` and never counts
        toward staleness, the reload or the stale NM."""
        climate = getattr(zone, "climate_entity", "") or ""
        try:
            st = hass.states.get(climate)
        except Exception:  # noqa: BLE001
            st = None
        row: dict[str, Any] = {
            "climate_entity": climate,
            "state": (st.state if st is not None else "missing"),
            "age_s": None,
            "stale": False,
            "corroborated": False,
            "span_kw": None,
            "ac_load_sensor": getattr(zone, "ac_load_sensor", "") or "",
            "span_unreadable": False,
            "freshness": "not_applicable",
        }
        return row, False

    async def remediate_stale(
        self, hass: Any, qualifier_zones: list[str], *, reload_fn: Callable[..., Any],
    ) -> None:
        """No integration repair for non-Carrier profiles (no NM)."""
        return None

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
        self, low: float, high: float, entity_id: Optional[str] = None,
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
        full_tick: bool = True,
    ) -> WriteResult:
        # ``full_tick`` (W1-C P2 fix A-L1): False on a zone-scoped fast run.
        # Only a range-holding adapter reads it (its heat_cool stuck count
        # advances on full ticks only); Carrier / Generic ignore it.
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
    profile_name: str = "carrier"
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
        self, low: float, high: float, entity_id: Optional[str] = None,
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

    # ---- W1-C P2 §4.10: ha_carrier staleness test + reload --------------
    def freshness_row(
        self, hass: Any, zone: Any, *, max_age_s: float,
        require_corroboration: bool, span_kw_fn: Callable[[Any], Any],
        now_utc: Any, state_age_fn: Any = None,
    ) -> tuple[dict[str, Any], bool]:
        """The per-zone body of ``HVACCoordinator._check_carrier_freshness``
        moved VERBATIM (same row keys, staleness, corroboration and
        qualifier logic). Returns ``(row, qualifies)``."""
        from .hvac_const import CARRIER_BLIND_CORROBORATION_KW_THRESHOLD  # noqa: PLC0415

        climate = getattr(zone, "climate_entity", "") or ""
        zone_id = getattr(zone, "zone_id", None)
        row: dict[str, Any] = {
            "climate_entity": climate,
            "state": None,
            "age_s": None,
            "stale": False,
            "corroborated": False,
            "span_kw": None,
            "ac_load_sensor": getattr(zone, "ac_load_sensor", "") or "",
            "span_unreadable": False,  # A5 fix-up diagnostic
        }
        try:
            st = hass.states.get(climate)
        except Exception:  # noqa: BLE001
            st = None
        # A4 fix-up (2026-09-09): surface unavailable zones in the
        # diagnostic snapshot rather than dropping them silently.
        if st is None:
            row["state"] = "missing"
            return row, False
        row["state"] = st.state
        if st.state in ("unavailable", "unknown"):
            return row, False
        age = None
        if state_age_fn is not None:
            try:
                age = state_age_fn(st, stamp="last_reported")
            except Exception:  # noqa: BLE001
                age = None
        if age is None:
            try:
                last_reported = getattr(st, "last_reported", None)
                if last_reported is None or getattr(
                    last_reported, "tzinfo", None,
                ) is None:
                    return row, False
                age = (now_utc - last_reported).total_seconds()
            except Exception:  # noqa: BLE001
                return row, False
        row["age_s"] = age
        if age <= max_age_s:
            return row, False
        row["stale"] = True

        # Corroboration path
        span_kw = span_kw_fn(zone)
        row["span_kw"] = span_kw
        # A5 fix-up (2026-09-09): distinguishable diagnostic when a
        # configured SPAN sensor is unreadable (unknown unit / dead /
        # non-numeric). Previously degraded silently to age-only.
        if row["ac_load_sensor"] and span_kw is None:
            row["span_unreadable"] = True
        hvac_action = (st.attributes.get("hvac_action") or "").lower()
        blind_evidence = (
            hvac_action == "idle"
            and span_kw is not None
            and span_kw > CARRIER_BLIND_CORROBORATION_KW_THRESHOLD
        )
        row["corroborated"] = blind_evidence

        qualifies = False
        if require_corroboration:
            # Skip corroboration ONLY when zone has no SPAN sensor
            # (graceful degrade — age-only for that zone).
            if row["ac_load_sensor"] == "":
                _LOGGER.debug(
                    "Carrier stale zone %s has no SPAN load sensor; "
                    "falling back to age-only qualifier",
                    zone_id,
                )
                qualifies = True
            elif blind_evidence:
                qualifies = True
            # else: quiet-idle — do NOT reload
        else:
            qualifies = True
        return row, qualifies

    async def remediate_stale(
        self, hass: Any, qualifier_zones: list[str], *, reload_fn: Callable[..., Any],
    ) -> None:
        """Carrier: today's bounded ``ha_carrier`` reload (the coordinator's
        ``_reload_ha_carrier_entry`` — its lock, counters, cooldown, NMs and
        the never-reload-the-parent invariant stay coordinator state)."""
        await reload_fn(qualifier_zones)


# ---------------------------------------------------------------------------
# HVAC W1-C P2 — adapter context. The ecobee adapter needs URA-side facts
# that live on the HVAC coordinator (the Seasonal Baseline resolver, the
# season, the freeze floor, the per-thermostat min delta, a save request).
# The coordinator registers them once at setup (``set_adapter_context``);
# an unset context degrades safely (no baseline → FAILED no_range).
# ---------------------------------------------------------------------------
@dataclass
class AdapterContext:
    hass: Any = None
    # preset -> (cool, heat) | None  (HVACPresetManager.get_seasonal_setpoints)
    baseline: Optional[Callable[[str], Any]] = None
    season: Optional[Callable[[], Optional[str]]] = None
    freeze_active: Optional[Callable[[], bool]] = None
    # entity_id -> configured heat/cool min delta (°F) | None
    min_delta_f: Optional[Callable[[str], Optional[float]]] = None
    # reason -> None (non-blocking zone-state save request)
    on_change: Optional[Callable[[str], None]] = None


_CTX = AdapterContext()


def set_adapter_context(**kwargs: Any) -> None:
    """HVAC coordinator setup hook (W1-C P2 §4.2a)."""
    for k, v in kwargs.items():
        if not hasattr(_CTX, k):
            raise TypeError(f"unknown adapter context field {k!r}")
        setattr(_CTX, k, v)


def _ctx_freeze() -> bool:
    try:
        return bool(_CTX.freeze_active()) if _CTX.freeze_active else False
    except Exception:  # noqa: BLE001
        return False


def _ctx_season() -> Optional[str]:
    try:
        return _CTX.season() if _CTX.season else None
    except Exception:  # noqa: BLE001
        return None


def _ctx_min_delta(entity_id: Optional[str]) -> float:
    from .hvac_const import DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F  # noqa: PLC0415
    val = None
    try:
        if _CTX.min_delta_f is not None and entity_id:
            val = _CTX.min_delta_f(entity_id)
    except Exception:  # noqa: BLE001
        val = None
    try:
        return float(val) if val is not None else float(DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F)
    except (TypeError, ValueError):
        return float(DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F)


def _ctx_changed(reason: str) -> None:
    try:
        if _CTX.on_change is not None:
            _CTX.on_change(reason)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("adapter save request failed", exc_info=True)


def _state_of(hass: Any, entity_id: str) -> Any:
    try:
        return hass.states.get(entity_id) if hass is not None else None
    except Exception:  # noqa: BLE001
        return None


def _within(a: Optional[float], b: Optional[float], tol: float) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


class EcobeeHomeKitStrategy(GenericStrategy):
    """ecobee over HomeKit (``homekit_controller``) — W1-C P2 REV 3.

    The thermostat has no presets over HomeKit. URA holds preset P by
    writing P's EFFECTIVE heat_cool range (§4.2a): the range S10 / Custom
    Preset Ranges stored for P this season, else the house's Seasonal
    Baseline for P — after the freeze/deadband guards, whole-degree
    rounding (half up) and the thermostat's configured min delta (heat
    kept, cool raised). ``preset_of`` reports the thermostat in Carrier's
    vocabulary: the range URA last held reads as that preset, anything
    else in heat_cool reads ``manual``. Every HC feature runs unchanged.

    Brand quirks absorbed here (never a feature gate):
    * no ``preset_mode``; comfort lives on a sibling "Current Mode" select —
      READ only, and only off heat_cool while URA holds nothing for the
      entity (the unit is on its own schedule); "unknown" there is
      unreadable, never Away. URA never selects an option (it would hold
      the device's own comfort setpoints, not URA's ranges);
    * a range write outside heat_cool would send ``temperature=None`` over
      HomeKit (HA `homekit_controller/climate.py` `async_set_temperature`):
      every range verb DEFERs (zero calls) unless the LIVE mode is
      heat_cool and both legs are numeric (§4.2 mechanism (i));
    * the device rounds `.5` writes: the adapter sends whole degrees;
    * the device enforces a min heat/cool gap: the adapter widens first.
    """

    platform: str = HOMEKIT_PLATFORM
    profile_name: str = ECOBEE_PROFILE
    capabilities: ProfileCapabilities = ECOBEE_HOMEKIT_CAPABILITIES
    app_name: Optional[str] = "ecobee"

    def __init__(self) -> None:
        super().__init__()
        # entity -> (preset, low, high)  — the range URA last held (post-guard)
        self._held: dict[str, tuple[str, float, float]] = {}
        # (entity, preset, season) -> (low, high)  — S10/CPR stored ranges
        self._ranges: dict[tuple[str, str, str], tuple[float, float]] = {}
        # entity -> consecutive S1 ticks deferred in cool/heat (§4.11)
        self._mode_stuck: dict[str, int] = {}
        self._repairs: set[tuple[str, str]] = set()  # (entity, Repair key)
        self._season_seen: Optional[str] = None

    # ---- range arithmetic ---------------------------------------------
    @staticmethod
    def wire_range(
        low: Any, high: Any, *, entity_id: Optional[str] = None,
        freeze_active: Optional[bool] = None,
    ) -> Optional[tuple[int, int]]:
        """What actually goes on the wire for a requested range: the
        freeze/deadband guards, whole degrees (half up), then the configured
        min delta (heat kept, cool raised). None when a leg is missing."""
        lo = _as_float(low)
        hi = _as_float(high)
        if lo is None or hi is None:
            return None
        from .hvac_setpoint import apply_setpoint_guards  # noqa: PLC0415
        fz = _ctx_freeze() if freeze_active is None else bool(freeze_active)
        g_lo, g_hi = apply_setpoint_guards(lo, hi, freeze_active=fz)
        w_lo, w_hi = _whole_degree(g_lo), _whole_degree(g_hi)
        gap = _ctx_min_delta(entity_id)
        if w_hi - w_lo < gap:
            import math  # noqa: PLC0415
            w_hi = w_lo + int(math.ceil(gap))
        return (w_lo, w_hi)

    def _prune_seasons(self) -> None:
        season = _ctx_season()
        if season is None or season == self._season_seen:
            return
        self._season_seen = season
        stale = [k for k in self._ranges if k[2] != season]
        for k in stale:
            self._ranges.pop(k, None)
        if stale:
            _ctx_changed("w1c_adapter_season_rollover")

    def _baseline_wire(self, entity_id: str, preset: str) -> Optional[tuple[int, int]]:
        try:
            pair = _CTX.baseline(preset) if _CTX.baseline is not None else None
        except Exception:  # noqa: BLE001
            pair = None
        if not pair:
            return None
        cool, heat = pair  # Bug Class #49: (cool_setpoint, heat_setpoint)
        return self.wire_range(heat, cool, entity_id=entity_id)

    def effective_range(self, entity_id: str, preset: str) -> Optional[tuple[int, int]]:
        """§4.2a: the stored S10/CPR range for (entity, preset, this season),
        else the Seasonal Baseline — always post-guard, whole degrees, min
        delta applied. None when the preset has no baseline."""
        self._prune_seasons()
        season = _ctx_season()
        stored = self._ranges.get((entity_id, preset, season)) if season else None
        if stored is not None:
            return self.wire_range(stored[0], stored[1], entity_id=entity_id)
        return self._baseline_wire(entity_id, preset)

    @staticmethod
    def _legs(state: Any) -> tuple[Optional[float], Optional[float]]:
        attrs = getattr(state, "attributes", None) or {}
        return _as_float(attrs.get("target_temp_low")), _as_float(attrs.get("target_temp_high"))

    @staticmethod
    def _legs_match(state: Any, rng: Optional[tuple[float, float]]) -> bool:
        if rng is None:
            return False
        lo, hi = EcobeeHomeKitStrategy._legs(state)
        return _within(lo, rng[0], ECOBEE_RANGE_TOLERANCE_F) and _within(
            hi, rng[1], ECOBEE_RANGE_TOLERANCE_F,
        )

    # ---- the Current Mode select (read-only) ----------------------------
    @staticmethod
    def _comfort_select_value(hass: Any, entity_id: Optional[str]) -> Optional[str]:
        """The sibling ``select`` (translation_key ``ecobee_mode``) value if
        it names a comfort setting; None for unknown / unavailable / absent."""
        if hass is None or not entity_id:
            return None
        try:
            from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
            reg = er.async_get(hass)
            entry = reg.async_get(entity_id) if reg is not None else None
            dev = getattr(entry, "device_id", None)
            if not dev:
                return None
            for e in er.async_entries_for_device(reg, dev):
                if getattr(e, "domain", None) != "select":
                    continue
                if getattr(e, "translation_key", None) != ECOBEE_MODE_SELECT_TRANSLATION_KEY:
                    continue
                st = hass.states.get(e.entity_id)
                val = getattr(st, "state", None) if st is not None else None
                return val if val in ECOBEE_COMFORT_OPTIONS else None
        except Exception:  # noqa: BLE001
            return None
        return None

    # ---- the projection (§4.3) ------------------------------------------
    def preset_of(
        self, state: Any, default: Any = None, *, hass: Any = None,
        entity_id: Optional[str] = None,
    ) -> Any:
        if state is None:
            return default
        mode = getattr(state, "state", None)
        if mode in (None, "unavailable", "unknown"):
            return default
        entity_id = entity_id or getattr(state, "entity_id", None)
        held = self._held.get(entity_id) if entity_id else None
        lo, hi = self._legs(state)
        if mode == "heat_cool" and lo is not None and hi is not None:
            if held is not None:
                if self._legs_match(state, (held[1], held[2])):
                    return held[0]
                return MANUAL_HOLD_PRESET
            # Restart / never-held fallback: exactly ONE current-season
            # effective range matches (two near candidates -> no match).
            hits = [
                p for p in ECOBEE_RANGE_PRESETS
                if self._legs_match(state, self.effective_range(entity_id, p))
            ]
            if len(hits) == 1:
                return hits[0]
            # The Current Mode select is NOT consulted here: HomeKit can
            # report a stale comfort name (parent plan REV 3.2; HA core
            # #84399 / #85715), which would hide a person's range from the
            # arrester. An unexplained heat_cool range reads `manual`.
            return MANUAL_HOLD_PRESET
        # Mode drift (cool / heat / off): keep the held name (B1 owns the
        # drift, as on Carrier); nothing held -> the comfort select or "".
        if held is not None:
            return held[0]
        sel = self._comfort_select_value(hass or _CTX.hass, entity_id)
        return sel if sel is not None else ""

    def observe(self, hass: Any, entity_id: str) -> Optional[HoldObservation]:
        obs = super().observe(hass, entity_id)
        if obs is not None:
            obs.preset_mode = self.preset_of(
                _state_of(hass, entity_id), None, hass=hass, entity_id=entity_id,
            )
        return obs

    def is_human_manual_snapshot(
        self, pre_preset: Optional[str], *, preset_modes: tuple[str, ...] | None = None,
    ) -> bool:
        # PR2-6: Carrier's rule. HomeKit advertises no presets, so the
        # inherited Generic "no presets -> human" branch would turn every
        # ecobee borrow return into a raw setpoint restore.
        return pre_preset in (None, "", MANUAL_HOLD_PRESET)

    def echo_tolerance_f(self) -> float:
        return ECOBEE_RANGE_TOLERANCE_F

    def classify_person_change(
        self, old_state: Any, new_state: Any, *, recent: Any = (), tol: float = ECOBEE_RANGE_TOLERANCE_F,
    ) -> PersonChange:
        """The Carrier classifier fed PROJECTED presets (no live caller —
        the arrester calls the classifier directly with ``preset_of``)."""
        try:
            from .hvac_override import (  # noqa: PLC0415
                MANUAL_CHANGE_HUMAN,
                MANUAL_CHANGE_URA_ECHO,
                classify_manual_setpoint_change,
                manual_changed_legs,
            )
            cls = classify_manual_setpoint_change(
                old_state, new_state, recent, tol, preset_of=self.preset_of,
            )
            if cls == MANUAL_CHANGE_HUMAN:
                verdict: Optional[PersonChangeVerdict] = PersonChangeVerdict.HUMAN
            elif cls == MANUAL_CHANGE_URA_ECHO:
                verdict = PersonChangeVerdict.URA_ECHO
            else:
                return PersonChange(None)
            return PersonChange(verdict, tuple(manual_changed_legs(old_state, new_state)))
        except Exception:  # noqa: BLE001
            return PersonChange(None)

    def hold_needs_reassert(self, hass: Any, entity_id: str, preset: str) -> bool:
        """The zone reads ``preset`` but the device does not carry URA's
        effective range for it (season rollover, baseline edit, a stored
        composition, or the mode drifted off heat_cool): S1 holds again.
        Never raises (False on any doubt = today's skip)."""
        try:
            st = _state_of(hass, entity_id)
            if st is None or getattr(st, "state", None) in (None, "unavailable", "unknown"):
                return False
            if getattr(st, "state", None) != "heat_cool":
                return True
            eff = self.effective_range(entity_id, preset)
            if eff is None:
                return False
            if self._legs_match(st, eff):
                # B-L2: S1 skips here (mode reached, legs match) — that
                # ends any heat_cool stuck episode and its Repair, exactly
                # like the no-op clause in `hold_preset`.
                self._mode_stuck.pop(entity_id, None)
                self._clear_repair(hass, entity_id)
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

    def reference_setpoints(
        self, hass: Any, entity_id: Optional[str], preset: str, baseline: Any,
    ) -> Any:
        """D MED-1: the range URA holds for ``preset`` is the EFFECTIVE
        range (stored S10 range, else the baseline, after the guards,
        rounding and min gap) — returned as ``(cool, heat)``. Falls back to
        ``baseline`` when there is none. Never raises."""
        try:
            eff = self.effective_range(entity_id, preset) if entity_id else None
        except Exception:  # noqa: BLE001
            eff = None
        if eff is None:
            return baseline
        return (float(eff[1]), float(eff[0]))

    # ---- preconditions (§4.2, §4.11) ------------------------------------
    @staticmethod
    def _issue_id(entity_id: str, key: str) -> str:
        # B-L3: one issue per (Repair key, thermostat) — the two Repairs
        # never overwrite each other's translation.
        return f"{key}_{entity_id}"

    def _raise_repair(self, hass: Any, entity_id: str, key: str) -> None:
        if (entity_id, key) in self._repairs:
            return
        try:
            from homeassistant.helpers import issue_registry as ir  # noqa: PLC0415
            from ..const import DOMAIN  # noqa: PLC0415
            ir.async_create_issue(
                hass, DOMAIN, self._issue_id(entity_id, key),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders={"thermostat": entity_id},
            )
            self._repairs.add((entity_id, key))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("heat_cool repair create failed", exc_info=True)

    def _clear_repair(self, hass: Any, entity_id: str, key: Optional[str] = None) -> None:
        """Delete the entity's Repair ``key`` (None = every key raised)."""
        keys = [k for (e, k) in self._repairs if e == entity_id and (key is None or k == key)]
        for k in keys:
            try:
                from homeassistant.helpers import issue_registry as ir  # noqa: PLC0415
                from ..const import DOMAIN  # noqa: PLC0415
                ir.async_delete_issue(hass, DOMAIN, self._issue_id(entity_id, k))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("heat_cool repair delete failed", exc_info=True)
            self._repairs.discard((entity_id, k))

    def _range_precondition(
        self, hass: Any, entity_id: str, st: Any, *, s1_tick: bool = False,
    ) -> Optional[WriteResult]:
        """None = the device can take a range NOW. Otherwise the result to
        return with ZERO calls (FAILED for a missing heat_cool capability,
        DEFERRED for a live mode / readability problem)."""
        if st is None or getattr(st, "state", None) in (None, "unavailable", "unknown"):
            return WriteResult(WriteStatus.DEFERRED, "climate_unreadable")
        attrs = getattr(st, "attributes", None) or {}
        modes = attrs.get("hvac_modes") or ()
        try:
            has_hc = "heat_cool" in modes
        except TypeError:
            has_hc = False
        if not has_hc:
            # Auto heat/cool disabled on the thermostat (§4.11).
            self._raise_repair(hass, entity_id, "thermostat_no_heat_cool")
            return WriteResult(WriteStatus.FAILED, "no_heat_cool_mode")
        # B-L3: heat_cool is offered again — that Repair alone is resolved.
        self._clear_repair(hass, entity_id, "thermostat_no_heat_cool")
        mode = getattr(st, "state", None)
        if mode == "heat_cool":
            if s1_tick:
                self._mode_stuck.pop(entity_id, None)
            self._clear_repair(hass, entity_id)
            return None
        if mode == "off":
            # Deliberate (egress pause, AC reset, a person) — no escalation.
            if s1_tick:
                self._mode_stuck.pop(entity_id, None)
            return WriteResult(WriteStatus.DEFERRED, "mode_not_heat_cool")
        if s1_tick:
            from .hvac_const import ECOBEE_HEAT_COOL_STUCK_TICKS  # noqa: PLC0415
            n = self._mode_stuck.get(entity_id, 0) + 1
            self._mode_stuck[entity_id] = n
            if n >= ECOBEE_HEAT_COOL_STUCK_TICKS:
                self._raise_repair(hass, entity_id, "thermostat_heat_cool_not_reached")
                return WriteResult(WriteStatus.FAILED, "heat_cool_not_reached")
        return WriteResult(WriteStatus.DEFERRED, "mode_not_heat_cool")

    # ---- the range write (binding ordering, §4.2 PR2-1) -----------------
    async def _hold_range(
        self, hass: Any, entity_id: str, preset: str, rng: tuple[int, int], *,
        gate: Callable[[], bool] | None, blocking: bool, site: str,
        zone_id: str, reason: str, excursion_id: str | None,
    ) -> bool:
        """Steps 4-6 + 8: stamp ``held`` with the post-guard range, emit,
        restore the previous ``held`` on a deferral or an exception (the
        exception propagates), persist when it changed. Returns the funnel
        bool."""
        from .hvac_setpoint import emit_set_temperature  # noqa: PLC0415
        prev = self._held.get(entity_id)
        new = (preset, float(rng[0]), float(rng[1]))
        self._held[entity_id] = new  # step 4: clamp before stamp, BEFORE the wire
        try:
            wrote = await emit_set_temperature(
                hass, entity_id,
                target_temp_low=float(rng[0]),
                target_temp_high=float(rng[1]),
                freeze_active=_ctx_freeze(),
                blocking=blocking,
                gate=gate,
                site=site,
                zone_id=zone_id,
                reason=reason,
                excursion_id=excursion_id,
            )
        except BaseException:
            self._restore_held(entity_id, prev, new)
            raise
        if not wrote:
            self._restore_held(entity_id, prev, new)
            return False
        if prev != new:
            _ctx_changed("w1c_adapter_held")
        return True

    def _restore_held(
        self, entity_id: str, prev: Optional[tuple[str, float, float]],
        stamp: tuple[str, float, float],
    ) -> None:
        # B-L4: undo only OUR stamp. Another write that stamped `held`
        # during this call's await owns it now — leave it.
        if self._held.get(entity_id) is not stamp:
            return
        if prev is None:
            self._held.pop(entity_id, None)
        else:
            self._held[entity_id] = prev

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
        full_tick: bool = True,
    ) -> WriteResult:
        st = _state_of(hass, entity_id)
        rng = self.effective_range(entity_id, preset)
        if rng is None:
            return WriteResult(WriteStatus.FAILED, "no_range_for_preset")
        # D2.5 no-op, three clauses (PR2-2 + REV 3).
        sent = self.last_sent(entity_id, "set_preset_mode")
        if (
            sent == preset
            and st is not None
            and getattr(st, "state", None) == "heat_cool"
            and self.preset_of(st, None, hass=hass, entity_id=entity_id) == preset
            and self._legs_match(st, rng)
        ):
            self._mode_stuck.pop(entity_id, None)
            self._clear_repair(hass, entity_id)
            return WriteResult(WriteStatus.SKIPPED_ALREADY_CORRECT, "no_op_last_sent_matches")
        # A-L1: the stuck count advances on FULL S1 ticks only (a zone-scoped
        # fast run is not a tick and must not shorten the escalation).
        blocked = self._range_precondition(hass, entity_id, st, s1_tick=full_tick)
        if blocked is not None:
            return blocked
        try:
            wrote = await self._hold_range(
                hass, entity_id, preset, rng, gate=gate, blocking=blocking,
                site=site, zone_id=zone_id, reason=reason, excursion_id=excursion_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._clear_sent(entity_id)
            return WriteResult(WriteStatus.FAILED, "emit_raised", type(exc).__name__)
        if not wrote:
            return WriteResult(WriteStatus.DEFERRED, "gate_deferred")
        self._record_sent(entity_id, "set_preset_mode", preset)
        return WriteResult(WriteStatus.APPLIED, "emitted")

    async def pin_preset(
        self,
        hass: Any,
        entity_id: str,
        preset: str,
        *,
        emit: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        """Every non-S1 preset write: the same range translation as
        ``hold_preset`` without the no-op and without ``last_sent``. The
        caller's ``emit`` (the preset funnel) is ignored — the range goes
        through ``emit_set_temperature``. A wire exception propagates."""
        st = _state_of(hass, entity_id)
        rng = self.effective_range(entity_id, preset)
        if rng is None:
            return WriteResult(WriteStatus.FAILED, "no_range_for_preset")
        blocked = self._range_precondition(hass, entity_id, st)
        if blocked is not None:
            return blocked
        wrote = await self._hold_range(
            hass, entity_id, preset, rng,
            gate=kwargs.get("gate"), blocking=bool(kwargs.get("blocking", False)),
            site=kwargs["site"], zone_id=kwargs["zone_id"], reason=kwargs["reason"],
            excursion_id=kwargs.get("excursion_id"),
        )
        return self._map_funnel_result(wrote)

    async def set_setpoints(
        self,
        hass: Any,
        entity_id: str,
        *,
        emit: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        """Raw range write (borrows, nudges, compromise). Delegates to the
        caller's funnel behind the live-mode AND both-legs preconditions
        (PR2-3), with the legs rounded and widened to the min delta. Never
        touches ``held`` — the range reads ``manual``, exactly what a raw
        setpoint write reads on Carrier."""
        st = _state_of(hass, entity_id)
        blocked = self._range_precondition(hass, entity_id, st)
        if blocked is not None:
            return blocked
        rng = self.wire_range(
            kwargs.get("target_temp_low"), kwargs.get("target_temp_high"),
            entity_id=entity_id,
            freeze_active=bool(kwargs.get("freeze_active", False)),
        )
        if rng is None:
            return WriteResult(WriteStatus.DEFERRED, "setpoint_leg_missing")
        if emit is None:
            from .hvac_setpoint import emit_set_temperature as _funnel  # noqa: PLC0415
            emit = _funnel
        call_kw = dict(kwargs)
        call_kw["target_temp_low"] = float(rng[0])
        call_kw["target_temp_high"] = float(rng[1])
        return self._map_funnel_result(await emit(hass, entity_id, **call_kw))

    async def release_hold(
        self, hass: Any, entity_id: str, *, site: str, zone_id: str, reason: str,
    ) -> WriteResult:
        """REV 3: no caller; the ecobee's Clear Hold is a button that hands
        the unit to its own schedule (D0b quirk 12) — never pressed by URA."""
        return WriteResult(WriteStatus.FAILED, "no_device_hold_release")

    # ---- Custom Preset Ranges (Batch C interface, §4.9) -----------------
    def preset_range_original(
        self, hass: Any, entity_id: str, preset: str,
    ) -> Optional[tuple[int, int]]:
        """§4.9: the ecobee "original" of every preset is its Seasonal
        Baseline (as the adapter would write it). Never raises."""
        try:
            return self._baseline_wire(entity_id, preset)
        except Exception:  # noqa: BLE001
            return None

    def preset_range_would_write(
        self, low: float, high: float, entity_id: Optional[str] = None,
    ) -> Optional[tuple[int, int]]:
        try:
            return self.wire_range(low, high, entity_id=entity_id)
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
        """(1) store the range URA-side — always, before any precondition
        (a range equal to the baseline DELETES the entry); (2) the zone
        does not hold ``preset`` -> SKIPPED ``stored_for_next_hold``; (3) the
        live legs already carry it -> SKIPPED ``range_already_live``; (4)
        otherwise write it now through the range ordering. ``emit`` (the
        Carrier activity funnel) is ignored."""
        self._prune_seasons()
        season = _ctx_season()
        want = self.wire_range(low, high, entity_id=entity_id, freeze_active=freeze_active)
        if season is not None and want is not None:
            key = (entity_id, preset, season)
            before = self._ranges.get(key)
            if want == self._baseline_wire(entity_id, preset):
                self._ranges.pop(key, None)
            else:
                self._ranges[key] = (float(low), float(high))
            if self._ranges.get(key) != before:
                _ctx_changed("w1c_adapter_ranges")
        held = self._held.get(entity_id)
        if held is None or held[0] != preset:
            return WriteResult(WriteStatus.SKIPPED_ALREADY_CORRECT, "stored_for_next_hold")
        st = _state_of(hass, entity_id)
        rng = self.effective_range(entity_id, preset)
        if rng is None:
            return WriteResult(WriteStatus.FAILED, "no_range_for_preset")
        if (
            st is not None and getattr(st, "state", None) == "heat_cool"
            and self._legs_match(st, rng)
        ):
            return WriteResult(WriteStatus.SKIPPED_ALREADY_CORRECT, "range_already_live")
        blocked = self._range_precondition(hass, entity_id, st)
        if blocked is not None:
            return blocked
        try:
            wrote = await self._hold_range(
                hass, entity_id, preset, rng, gate=gate, blocking=True,
                site=site, zone_id=zone_id, reason=reason, excursion_id=None,
            )
        except Exception as exc:  # noqa: BLE001
            return WriteResult(WriteStatus.FAILED, "emit_raised", type(exc).__name__)
        if not wrote:
            return WriteResult(WriteStatus.DEFERRED, "gate_deferred")
        return WriteResult(WriteStatus.APPLIED, "emitted")

    # ---- persistence (§4.2a) --------------------------------------------
    def export_state(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for ent, (p, lo, hi) in self._held.items():
            out.setdefault(ent, {"held": None, "ranges": []})["held"] = [p, lo, hi]
        for (ent, p, season), (lo, hi) in sorted(self._ranges.items()):
            out.setdefault(ent, {"held": None, "ranges": []})["ranges"].append(
                [p, season, lo, hi],
            )
        return out

    def rehydrate_state(self, blob: Any) -> bool:
        if not isinstance(blob, dict):
            return True
        season = _ctx_season()
        for ent, sl in blob.items():
            if not isinstance(sl, dict):
                continue
            try:
                h = sl.get("held")
                if isinstance(h, (list, tuple)) and len(h) == 3:
                    self._held[str(ent)] = (str(h[0]), float(h[1]), float(h[2]))
            except (TypeError, ValueError):
                _LOGGER.warning("W1-C adapter: malformed held for %s dropped", ent)
            # A-M2: a corrupt "ranges" (not a list) is dropped with one
            # warning — never a TypeError on every later `strategy_for`.
            ranges = sl.get("ranges") or ()
            if not isinstance(ranges, (list, tuple)):
                _LOGGER.warning("W1-C adapter: malformed ranges for %s dropped", ent)
                ranges = ()
            for r in ranges:
                try:
                    p, s, lo, hi = r
                    if season is not None and s != season:
                        continue  # RR3-4: a year-old composition never lands
                    self._ranges[(str(ent), str(p), str(s))] = (float(lo), float(hi))
                except (TypeError, ValueError):
                    _LOGGER.warning("W1-C adapter: malformed range for %s dropped", ent)
        return True

    def flush_entity(self, entity_id: str) -> None:
        super().flush_entity(entity_id)
        self._held.pop(entity_id, None)
        for k in [k for k in self._ranges if k[0] == entity_id]:
            self._ranges.pop(k, None)
        self._mode_stuck.pop(entity_id, None)


_STRATEGY_BY_PLATFORM: dict[str, GenericStrategy] = {}
_KNOWN: dict[str, type[GenericStrategy]] = {CARRIER_PLATFORM: CarrierStrategy}
# W1-C P2 §4.1: HomeKit thermostats are NOT cached by platform (an ecobee and
# a non-ecobee HomeKit thermostat share it) — by profile key instead.
_STRATEGY_BY_PROFILE: dict[str, GenericStrategy] = {}
# entity -> the instance it last resolved to (F1: a registry miss on an
# entity resolved earlier returns that instance; a never-resolved entity
# gets ONE cached Generic).
_RESOLVED_BY_ENTITY: dict[str, GenericStrategy] = {}
_MISS_ENTITIES: set[str] = set()
# §4.2a / RR3-2: persisted adapter slices whose entity does not (yet)
# resolve to a profile that keeps state — kept verbatim, re-exported by the
# snapshot, handed over on the first later resolution that accepts it.
_PENDING_ADAPTER_STATE: dict[str, Any] = {}
# §4.1 F3: entity ids whose RESOLVED profile changed brand mid-run; the HVAC
# coordinator drains it (suppression flush + live borrows closed).
_PROFILE_SWITCHES: list[tuple[str, str, str]] = []


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


def _device_manufacturer(hass: Any, entity_id: str) -> Optional[str]:
    """The DEVICE registry's ``manufacturer`` for the entity's device."""
    try:
        from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
        entry = er.async_get(hass).async_get(entity_id)
        dev_id = getattr(entry, "device_id", None) if entry is not None else None
        if not dev_id:
            return None
        dev = dr.async_get(hass).async_get(dev_id)
        manu = getattr(dev, "manufacturer", None) if dev is not None else None
        return str(manu) if manu else None
    except Exception:  # noqa: BLE001
        return None


def _profile_key(hass: Any, entity_id: str, plat: str) -> str:
    if plat == HOMEKIT_PLATFORM:
        raw = _device_manufacturer(hass, entity_id)
        if raw is None and isinstance(
            _RESOLVED_BY_ENTITY.get(entity_id), EcobeeHomeKitStrategy,
        ):
            # D LOW-1: an unreadable manufacturer (device registry miss /
            # not loaded yet) never downgrades an entity already resolved to
            # ecobee — only a real, different manufacturer does.
            return ECOBEE_PROFILE
        manu = (raw or "").lower()
        if ECOBEE_MANUFACTURER_MATCH in manu:
            return ECOBEE_PROFILE
        return f"{HOMEKIT_PLATFORM}:other"
    return plat


def _note_resolution(entity_id: str, inst: GenericStrategy, *, miss: bool) -> None:
    prev = _RESOLVED_BY_ENTITY.get(entity_id)
    _RESOLVED_BY_ENTITY[entity_id] = inst
    if miss:
        _MISS_ENTITIES.add(entity_id)
    if prev is not None and prev is not inst:
        prev_was_miss = entity_id in _MISS_ENTITIES and not miss
        if prev_was_miss:
            # Miss -> hit: the placeholder Generic's live state is dropped;
            # a pending persisted slice is NOT (RR3-2).
            prev.flush_entity(entity_id)
        elif type(prev) is not type(inst) or prev.platform != inst.platform:
            # A resolved brand changed: flush both sides + tell the HC.
            prev.flush_entity(entity_id)
            inst.flush_entity(entity_id)
            _PROFILE_SWITCHES.append((entity_id, prev.platform, inst.platform))
            _ctx_changed("w1c_profile_switch")
    if not miss:
        _MISS_ENTITIES.discard(entity_id)
    if entity_id in _PENDING_ADAPTER_STATE:
        try:
            accepted = inst.rehydrate_state({entity_id: _PENDING_ADAPTER_STATE[entity_id]})
        except Exception:  # noqa: BLE001
            # A-M2: a slice the profile cannot read is dropped, not retried
            # on every resolution.
            _LOGGER.warning(
                "W1-C adapter: persisted state for %s unreadable; dropped",
                entity_id, exc_info=True,
            )
            accepted = True
        if accepted:
            _PENDING_ADAPTER_STATE.pop(entity_id, None)


def strategy_for(hass: Any, entity_id: str) -> GenericStrategy:
    """Dispatch by registry platform (+ device manufacturer for HomeKit).

    * Carrier / other platforms: cached per platform (unchanged).
    * ``homekit_controller``: cached per profile key (ecobee vs other).
    * Registry miss: the instance this entity resolved to earlier, else ONE
      cached Generic for the entity (P1 F1: the Generic no-op now fires).
    """
    plat = _entity_platform(hass, entity_id)
    if plat is None:
        prev = _RESOLVED_BY_ENTITY.get(entity_id) if entity_id else None
        if prev is not None:
            return prev
        inst = GenericStrategy()
        if entity_id:
            _note_resolution(entity_id, inst, miss=True)
        return inst
    if plat == HOMEKIT_PLATFORM:
        key = _profile_key(hass, entity_id, plat)
        inst = _STRATEGY_BY_PROFILE.get(key)
        if inst is None:
            inst = EcobeeHomeKitStrategy() if key == ECOBEE_PROFILE else GenericStrategy()
            inst.platform = plat
            _STRATEGY_BY_PROFILE[key] = inst
    else:
        inst = _STRATEGY_BY_PLATFORM.get(plat)
        if inst is None:
            cls = _KNOWN.get(plat, GenericStrategy)
            inst = cls()
            inst.platform = plat
            _STRATEGY_BY_PLATFORM[plat] = inst
    if _RESOLVED_BY_ENTITY.get(entity_id) is not inst or entity_id in _PENDING_ADAPTER_STATE:
        _note_resolution(entity_id, inst, miss=False)
    return inst


def strategy_for_platform(platform: Optional[str]) -> GenericStrategy:
    """Dispatch by a platform name already in hand. Zero production
    callers. It cannot see a device manufacturer, so it REFUSES
    ``homekit_controller`` (returns Generic): any site that needs the
    ecobee adapter resolves it by ENTITY (W1-C P2 §4.1)."""
    if not platform or platform == HOMEKIT_PLATFORM:
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


def preset_of_for(hass: Any, entity_id: Optional[str], state: Any, default: Any = None) -> Any:
    """W1-C P2 §5 — the ONE routed thermostat ``preset_mode`` read. The
    entity's profile projects the state (Carrier / Generic: the raw
    attribute verbatim). Never raises (falls back to the raw read)."""
    ent = entity_id or getattr(state, "entity_id", None)
    try:
        strat = strategy_for(hass, ent) if ent else GenericStrategy()
        return strat.preset_of(state, default, hass=hass, entity_id=ent)
    except Exception:  # noqa: BLE001
        return (getattr(state, "attributes", None) or {}).get("preset_mode", default)


def export_adapter_state() -> dict[str, Any]:
    """§4.2a: the ``__w1c_adapter`` blob — every resolved instance's state
    plus the pending slices, verbatim. Empty on a Carrier-only install."""
    out: dict[str, Any] = dict(_PENDING_ADAPTER_STATE)
    seen: set[int] = set()
    for inst in list(_RESOLVED_BY_ENTITY.values()) + list(_STRATEGY_BY_PROFILE.values()):
        if id(inst) in seen:
            continue
        seen.add(id(inst))
        try:
            out.update(inst.export_state())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("adapter export failed", exc_info=True)
    return out


def rehydrate_adapter_state(hass: Any, blob: Any) -> None:
    """Boot restore, per ENTITY (RR3-2): each entity's slice goes to the
    instance it resolves to now; a profile that keeps no state leaves the
    slice pending (re-exported unchanged, handed over later)."""
    if not isinstance(blob, dict):
        return
    for ent, sl in blob.items():
        try:
            _PENDING_ADAPTER_STATE[str(ent)] = sl
            strategy_for(hass, str(ent))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("adapter rehydrate failed for %s", ent, exc_info=True)


def prune_adapter_state(valid_entities: set[str]) -> bool:
    """§4.2a prune at the latch seam: drop every entity no longer mapped to
    a zone. Returns True when anything was dropped. Empty set = zone map
    unknown — prune nothing."""
    if not valid_entities:
        return False
    dropped = False
    for ent in [e for e in _PENDING_ADAPTER_STATE if e not in valid_entities]:
        _PENDING_ADAPTER_STATE.pop(ent, None)
        dropped = True
    for inst in set(_STRATEGY_BY_PROFILE.values()) | set(_RESOLVED_BY_ENTITY.values()):
        for ent in list(inst.export_state()):
            if ent not in valid_entities:
                inst.flush_entity(ent)
                dropped = True
    return dropped


def profile_info(hass: Any, entity_id: Optional[str]) -> tuple[str, str]:
    """D1 display: (profile name, source). Source ``detected`` = resolved
    from the entity / device registry; ``default`` = registry miss
    (Generic placeholder) or no entity."""
    if not entity_id:
        return "generic", "default"
    inst = strategy_for(hass, entity_id)
    src = "default" if entity_id in _MISS_ENTITIES else "detected"
    return inst.profile_name, src


def drain_profile_switches() -> list[tuple[str, str, str]]:
    out = list(_PROFILE_SWITCHES)
    _PROFILE_SWITCHES.clear()
    return out


def _test_reset_cache() -> None:
    _STRATEGY_BY_PLATFORM.clear()
    _STRATEGY_BY_PROFILE.clear()
    _RESOLVED_BY_ENTITY.clear()
    _MISS_ENTITIES.clear()
    _PENDING_ADAPTER_STATE.clear()
    _PROFILE_SWITCHES.clear()
