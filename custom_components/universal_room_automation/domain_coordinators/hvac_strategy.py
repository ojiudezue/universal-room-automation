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
        if pre_preset in (None, "", "manual"):
            return True
        if preset_modes is not None and len(preset_modes) == 0:
            return True
        return False

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

    def is_human_manual_snapshot(
        self, pre_preset: Optional[str], *, preset_modes: tuple[str, ...] | None = None,
    ) -> bool:
        # Carrier always advertises presets; only the snapshot value decides.
        return pre_preset in (None, "", "manual")


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


def _test_reset_cache() -> None:
    _STRATEGY_BY_PLATFORM.clear()
