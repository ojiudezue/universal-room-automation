"""OverrideEngine — shared preset-range override schema for Guest Mode + Dynamic Preset.

Schema owner: this module. Consumers (Guest Mode Phase 1, Dynamic Preset Cycle B)
register override records; the engine resolves them per highest-priority-wins rule.

v4.7.1: Initial implementation (prerequisite for Cycle B Dynamic Preset).
Per PLANNING_v4.7.x_guest_mode_actuation_phase1.md §4 — schema design.

Bug class prevention:
- #11 (UTC vs local): no datetime ops here; callers supply context
- #14 (config staleness): engine is stateless; callers supply overrides list
- #19 (untracked tasks): no async; pure synchronous engine
- #20 (concurrent reload): no shared mutable state between resolution calls
- #22 (enum mismatch): source + preset as typed str; validated at insert site
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Valid source identifiers (extensible — new sources add to this set)
OVERRIDE_SOURCE_GUEST_MODE: str = "guest_mode"
OVERRIDE_SOURCE_DYNAMIC_PRESET: str = "dynamic_preset"

# Valid preset identifiers (subset of HVAC preset names)
OVERRIDE_PRESET_HOME: str = "home"
OVERRIDE_PRESET_SLEEP: str = "sleep"
OVERRIDE_PRESET_AWAY: str = "away"
OVERRIDE_PRESET_VACATION: str = "vacation"

# Schema invariants
_MIN_DEADBAND: float = 2.0
_COOL_LOW_FLOOR: float = 60.0
_COOL_HIGH_CEIL: float = 90.0


@dataclass
class PresetOverride:
    """Single override record — describes one source's opinion on a zone+preset range.

    Fields per PLANNING_v4.7.x_guest_mode_actuation_phase1.md §4.2:
        source: producer identifier — guest_mode | dynamic_preset | vacation | manual
        preset: home | sleep | away | vacation
        cool_low: lower cooling target bound (°F), or None = no opinion
        cool_high: upper cooling target bound (°F), or None = no opinion
        heat_low: reserved; not exposed in current UI
        heat_high: reserved; not exposed in current UI
        priority: higher wins; guest_mode=50, dynamic_preset=30, vacation=70, manual=100
        active_when: optional context-predicate identifier for filtering (Phase 1 uses
                     "house_state == 'guest'"; dynamic_preset uses own predicate)
    """

    source: str
    preset: str
    priority: int
    cool_low: float | None = None
    cool_high: float | None = None
    heat_low: float | None = None
    heat_high: float | None = None
    active_when: str | None = None
    # Dynamic-preset extras (not persisted; computed fresh per tick)
    zone_id: str | None = None
    bucket: str | None = None


@dataclass
class ResolvedRange:
    """Result of OverrideEngine.resolve_range().

    cool_low / cool_high: composed values (may equal baseline if no overrides).
    sources: per-field attribution — e.g. {"cool_high": "guest_mode"}.
    """

    cool_low: float
    cool_high: float
    sources: dict[str, str] = field(default_factory=dict)

    def differs_from_baseline(self, baseline_low: float, baseline_high: float) -> bool:
        """Return True if the resolved range differs from the given baseline."""
        return self.cool_low != baseline_low or self.cool_high != baseline_high


class OverrideEngine:
    """Shared preset-range override composition engine.

    Stateless per-resolution — callers supply the full active-overrides list.
    Singleton not required; OverrideEngine can be instantiated per coordinator
    or per resolution call.

    Public API:
        get_active_overrides(zone_id, preset, house_state, master_enabled) -> list[PresetOverride]
        resolve_range(baseline_low, baseline_high, overrides) -> ResolvedRange
        describe_active(zone_id, preset, house_state, master_enabled, all_overrides) -> list[dict]
    """

    def get_active_overrides(
        self,
        zone_id: str,
        preset: str,
        house_state: str,
        master_enabled: bool,
        all_overrides: list[PresetOverride],
    ) -> list[PresetOverride]:
        """Filter override records to those active for (zone_id, preset, house_state).

        Filters on:
        - master_enabled: if False, returns []
        - zone_id match (override.zone_id must match, or be None for house-global)
        - preset match
        - active_when predicate — currently evaluated inline:
            "house_state == 'guest'" → house_state == "guest"
            None (or unknown predicate) → always active
        """
        if not master_enabled:
            return []

        result: list[PresetOverride] = []
        for override in all_overrides:
            # Zone filter: None means house-global; exact-match otherwise
            if override.zone_id is not None and override.zone_id != zone_id:
                continue
            # Preset filter
            if override.preset != preset:
                continue
            # active_when predicate
            if not self._eval_predicate(override.active_when, house_state):
                continue
            result.append(override)

        return result

    @staticmethod
    def _eval_predicate(predicate: str | None, house_state: str) -> bool:
        """Evaluate an active_when predicate string.

        Supported predicates:
            None → always active
            "house_state == 'guest'" → house_state == "guest"
            "dynamic_preset" → always active (dynamic_preset manages its own gating)
        """
        if predicate is None:
            return True
        if predicate == "house_state == 'guest'":
            return house_state == "guest"
        if predicate == "dynamic_preset":
            # Dynamic preset always passes through here; actual bucket-gating
            # is done by DynamicPresetOverrideSource before inserting the record.
            return True
        # Unknown predicate — treat as inactive (safe default)
        _LOGGER.warning("OverrideEngine: unknown predicate %r — treating as inactive", predicate)
        return False

    def resolve_range(
        self,
        baseline_low: float,
        baseline_high: float,
        overrides: list[PresetOverride],
    ) -> ResolvedRange:
        """Resolve the final range from baseline + overrides using highest-priority-wins.

        Per §4.2 schema:
        - Each field (cool_low, cool_high) is resolved independently.
        - Highest priority override with a non-None opinion on that field wins.
        - A None field means "no opinion" — the field falls through to baseline.
        - If no override has an opinion on a field, the baseline value is used.
        """
        # Sort by priority descending (highest priority first)
        sorted_overrides = sorted(overrides, key=lambda o: o.priority, reverse=True)

        resolved_low = baseline_low
        resolved_high = baseline_high
        sources: dict[str, str] = {}

        for override in sorted_overrides:
            if override.cool_low is not None and "cool_low" not in sources:
                resolved_low = override.cool_low
                sources["cool_low"] = override.source
            if override.cool_high is not None and "cool_high" not in sources:
                resolved_high = override.cool_high
                sources["cool_high"] = override.source

        # Post-resolution deadband invariant: enforce cool_low ≤ cool_high − MIN_DEADBAND
        # If composition violates this (shouldn't happen if form validation worked),
        # clamp cool_low to maintain the invariant.
        if resolved_low > resolved_high - _MIN_DEADBAND:
            _LOGGER.warning(
                "OverrideEngine: composed range %s–%s violates MIN_DEADBAND=%s; "
                "clamping cool_low to %s",
                resolved_low, resolved_high, _MIN_DEADBAND,
                resolved_high - _MIN_DEADBAND,
            )
            resolved_low = resolved_high - _MIN_DEADBAND

        return ResolvedRange(
            cool_low=resolved_low,
            cool_high=resolved_high,
            sources=sources,
        )

    def describe_active(
        self,
        zone_id: str,
        preset: str,
        house_state: str,
        master_enabled: bool,
        all_overrides: list[PresetOverride],
        baseline_low: float,
        baseline_high: float,
    ) -> dict[str, Any]:
        """Return a diagnostic dict describing the active overrides and resolved range.

        Used by the sensor.ura_active_preset_overrides diagnostic surface.
        """
        active = self.get_active_overrides(
            zone_id, preset, house_state, master_enabled, all_overrides
        )
        resolved = self.resolve_range(baseline_low, baseline_high, active)
        return {
            "active_overrides": [
                {
                    "source": o.source,
                    "preset": o.preset,
                    "cool_low": o.cool_low,
                    "cool_high": o.cool_high,
                    "priority": o.priority,
                    "bucket": o.bucket,
                }
                for o in active
            ],
            "resolved": {
                "cool_low": resolved.cool_low,
                "cool_high": resolved.cool_high,
                "sources": resolved.sources,
            },
        }

    # HIGH A3: build_guest_mode_overrides deleted — was dead code (zero callers
    # in production code). Guest Mode Phase 1 D2 wires the OverrideEngine
    # directly through HVAC coordinator. When Guest Mode UI ships (v4.7.2),
    # the caller and this helper can be added together in the same commit so
    # they are always integration-tested.
    #
    # Cycle B test TestBuildGuestModeOverrides was also removed (it tested dead
    # code). If you are re-adding this method, also re-add those tests and wire
    # a real caller in the same commit.
