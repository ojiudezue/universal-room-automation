"""DynamicPresetOverrideSource — weather-forecast-driven per-zone HVAC preset ranges.

v4.7.1 Cycle B: Implements the B.B.1-B.B.5 spec from
PLANNING_v4.7.x_dynamic_preset_management.md.

Key design choices:
- Evaluation is synchronous; called from EC decision cycle (5-min cadence).
- Re-entrancy guard (asyncio.Lock) serializes concurrent evaluate calls.
- Bucket + transition timestamps persist via RestoreEntity (Bug #10).
- All datetime comparisons use dt_util.utcnow() only (Bug #11).
- Config read fresh on each evaluate call (Bug #14).
- No async_create_task calls (Bug #19, #42).
- Observation-mode gate is on the EC caller side, not here (Bug #23).

Bug class prevention:
- #5  (startup race): returns no overrides until WPM has a cached forecast
- #10 (cross-restart): bucket + last_transition_at persisted in RestoreEntity
- #11 (UTC vs local): all datetime ops via dt_util.utcnow()
- #14 (config staleness): _refresh_config() at top of evaluate_and_emit
- #19 (untracked tasks): no async_create_task anywhere in this module
- #22 (enum mismatch): BucketClass as StrEnum
- #23 (observation mode): gated by caller (EC decision cycle)
- #38 (listener cleanup): no state-change listeners owned here
- #42 (lambda + async_create_task): no scheduler callbacks
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        def __str__(self) -> str:  # pragma: no cover
            return self.value

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_const import (
    BUCKET_COOL,
    BUCKET_EXTREME,
    BUCKET_HOT,
    BUCKET_MILD,
    CONF_DYNAMIC_PRESET_DELTA_COOL_MAX,
    CONF_DYNAMIC_PRESET_DELTA_HOT_MAX,
    CONF_DYNAMIC_PRESET_DELTA_MILD_MAX,
    CONF_DYNAMIC_PRESET_DWELL_MINUTES,
    CONF_DYNAMIC_PRESET_HYSTERESIS_F,
    CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_LOW,
    CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_LOW,
    CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS,
    CONF_ZONE_DYNAMIC_PRESET_ENABLED,
    CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_LOW,
    CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_LOW,
    CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_LOW,
    CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_LOW,
    CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_LOW,
    CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_HIGH,
    CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_LOW,
    CONF_ZONE_DYNAMIC_PRESET_OFFSET,
    CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST,
    CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED,
    DEFAULT_DYNAMIC_PRESET_DELTA_COOL_MAX,
    DEFAULT_DYNAMIC_PRESET_DELTA_HOT_MAX,
    DEFAULT_DYNAMIC_PRESET_DELTA_MILD_MAX,
    DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES,
    DEFAULT_DYNAMIC_PRESET_HYSTERESIS_F,
    # v4.7.17.2: new operator-facing knobs + internal deadzone
    CONF_DPM_COOL_DAY_RELAX_F,
    CONF_DPM_HOT_DAY_TIGHTEN_F,
    DEFAULT_DPM_COOL_DAY_RELAX_F,
    DEFAULT_DPM_HOT_DAY_TIGHTEN_F,
    DPM_RELATIVE_DELTA_DEADZONE_F,
    DYNAMIC_PRESET_PRIORITY,
)
from .preset_overrides import (
    OVERRIDE_SOURCE_DYNAMIC_PRESET,
    PresetOverride,
)

_LOGGER = logging.getLogger(__name__)

# Sleep floor: sleep_high = max(SLEEP_FLOOR, home_high - 1) + offset
SLEEP_FLOOR_F: float = 74.0


def _compute_cool_high_adjustment(
    relative_delta: float,
    relax_f: float,
    tighten_f: float,
) -> float:
    """v4.7.17.2: Compute the °F adjustment to apply to cool_high values.

    Per planning doc §3:
      relative_delta <= -DEADZONE -> cool day -> +relax_f
      -DEADZONE < relative_delta < +DEADZONE -> typical -> 0.0
      relative_delta >= +DEADZONE -> hot day -> -tighten_f

    relative_delta = (today_apparent_high - 14d_rolling_median_apparent_high).
    Positive = hotter than usual locally; negative = cooler than usual locally.

    Returns signed °F to add to cool_high. Operator's two knobs are
    asymmetric — a non-zero relax_f with relax_f=0 means cool days relax
    but hot days don't tighten, and vice versa.
    """
    if relative_delta <= -DPM_RELATIVE_DELTA_DEADZONE_F:
        return float(relax_f)
    if relative_delta >= DPM_RELATIVE_DELTA_DEADZONE_F:
        return -float(tighten_f)
    return 0.0


class BucketClass(StrEnum):
    """Bucket identifiers for thermal load classification (Bug #22)."""

    COOL = BUCKET_COOL
    MILD = BUCKET_MILD
    HOT = BUCKET_HOT
    EXTREME = BUCKET_EXTREME


# Bucket CONF key lookup table: bucket → (home_low_conf, home_high_conf, sleep_low_conf, sleep_high_conf)
_BUCKET_CONF_KEYS: dict[str, tuple[str, str, str, str]] = {
    BUCKET_COOL: (
        CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_LOW,
        CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_HIGH,
        CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_LOW,
        CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_HIGH,
    ),
    BUCKET_MILD: (
        CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_LOW,
        CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_HIGH,
        CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_LOW,
        CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_HIGH,
    ),
    BUCKET_HOT: (
        CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_LOW,
        CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_HIGH,
        CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_LOW,
        CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_HIGH,
    ),
    BUCKET_EXTREME: (
        CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_LOW,
        CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_HIGH,
        CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_LOW,
        CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_HIGH,
    ),
}


def classify_bucket(
    delta: float,
    cool_max: float,
    mild_max: float,
    hot_max: float,
) -> BucketClass:
    """Classify delta into a BucketClass.

    Boundaries are inclusive on the upper edge:
        δ ≤ cool_max                         → COOL
        cool_max < δ ≤ mild_max              → MILD
        mild_max < δ ≤ hot_max               → HOT
        δ > hot_max                          → EXTREME

    Unit tests must cover off-by-one: δ=cool_max → COOL, δ=cool_max+ε → MILD,
    δ=mild_max → MILD is WRONG per spec — δ=mild_max → HOT? No:
    spec says -2 < δ ≤ +8 is MILD, so δ=+8 → HOT is WRONG.
    Per spec: "mild: -2 < δ ≤ +8" → δ=8.0 is MILD (≤ mild_max).
    Plan §B.B.1: "mild: -2 < δ ≤ +8°F", "hot: +8 < δ ≤ +18°F".
    So boundaries are: δ <= cool_max → COOL; cool_max < δ <= mild_max → MILD;
    mild_max < δ <= hot_max → HOT; δ > hot_max → EXTREME.
    """
    if delta <= cool_max:
        return BucketClass.COOL
    if delta <= mild_max:
        return BucketClass.MILD
    if delta <= hot_max:
        return BucketClass.HOT
    return BucketClass.EXTREME


def _passed_boundary_with_buffer(
    current_bucket: str,
    fresh_bucket: str,
    delta: float,
    cool_max: float,
    mild_max: float,
    hot_max: float,
    hysteresis_f: float,
) -> bool:
    """Return True if delta has crossed the boundary firmly enough (with hysteresis).

    Asymmetric: tighter buckets are easier to stay in than to enter.
    - Entering a tighter bucket (MILD→HOT, HOT→EXTREME): delta must exceed the
      strict boundary (no buffer needed on entry — just classification is enough).
    - Exiting a tighter bucket (HOT→MILD, EXTREME→HOT): delta must be past the
      boundary by hysteresis_f to confirm the exit.
    - COOL is the loosest bucket; transitions to/from COOL follow the same rules.

    Tightness order: COOL < MILD < HOT < EXTREME (EXTREME is tightest).
    """
    bucket_order = [BUCKET_COOL, BUCKET_MILD, BUCKET_HOT, BUCKET_EXTREME]
    try:
        cur_idx = bucket_order.index(current_bucket)
        fresh_idx = bucket_order.index(fresh_bucket)
    except ValueError:
        # Unknown bucket string — allow transition
        return True

    if fresh_idx > cur_idx:
        # Moving to a tighter (higher) bucket: entry is permitted by classification alone
        return True

    # Moving to a looser (lower) bucket: require hysteresis buffer
    # Find the boundary we're trying to cross (downward)
    # Boundary between current_bucket and the one below it
    if cur_idx == 3:  # EXTREME → HOT: must drop below hot_max - hysteresis
        return delta < hot_max - hysteresis_f
    if cur_idx == 2:  # HOT → MILD: must drop below mild_max - hysteresis
        return delta < mild_max - hysteresis_f
    if cur_idx == 1:  # MILD → COOL: must drop below cool_max - hysteresis
        return delta < cool_max - hysteresis_f
    # cur_idx == 0 (COOL → below? impossible, COOL is the lowest)
    return True


def compute_sleep_high(home_high: float, zone_offset: float) -> float:
    """Apply sleep-floor rule: sleep_high = max(SLEEP_FLOOR, home_high − 1) + offset.

    Per §B.B.5: floor applied BEFORE offset. Back Hallway (+1.0) sleep = 75
    when home_high=77 (floor: max(74, 76)=76, +1=77... wait, home_high-1=76≥74,
    so floor=76, +1=77). Hot bucket home_high=74: max(74,73)=74, +1=75.
    """
    raw = max(SLEEP_FLOOR_F, home_high - 1.0)
    return raw + zone_offset


class DynamicPresetOverrideSource:
    """Weather-forecast-driven per-zone preset-range override source.

    Lifecycle:
        __init__() — inject hass + options getter
        evaluate_and_emit(zone_id, zone_data, delta, house_state, now) → list[PresetOverride]
            Called per zone per EC decision tick (5-min cadence).
            Returns the list of overrides to register in OverrideEngine for this zone.
            Returns [] when: feature disabled, zone not opted-in, WPM has no forecast.

    State (per zone, cross-restart via RestoreEntity):
        _active_bucket[zone_id]: str  — current bucket
        _last_transition_at[zone_id]: datetime (UTC)  — when we last transitioned

    Bug class prevention:
    - #10: state stored in _active_bucket/_last_transition_at; sensor restores them
    - #11: all datetime via dt_util.utcnow(); never mix aware/naive
    - #19: no async_create_task calls
    - #42: no scheduler callbacks; evaluation is synchronous
    """

    def __init__(self, hass: HomeAssistant, get_options: Any) -> None:
        """Initialize.

        Args:
            hass: HomeAssistant instance
            get_options: callable returning current CM entry options dict
        """
        self.hass = hass
        self._get_options = get_options

        # Per-zone cross-restart state (Bug #10)
        self._active_bucket: dict[str, str] = {}
        self._last_transition_at: dict[str, datetime] = {}

        # Re-entrancy guard (WPM-C1 pattern; Bug class from plan)
        self._eval_lock: asyncio.Lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # State injection (used by RestoreEntity sensor on startup — Bug #10)
    # -------------------------------------------------------------------------

    def restore_zone_state(
        self,
        zone_id: str,
        bucket: str,
        last_transition_at: datetime,
    ) -> None:
        """Restore persisted bucket state for a zone (called by sensor on startup).

        All datetime values must already be UTC-aware (Bug #11).
        """
        if bucket in (BUCKET_COOL, BUCKET_MILD, BUCKET_HOT, BUCKET_EXTREME):
            self._active_bucket[zone_id] = bucket
        if last_transition_at is not None:
            # Ensure timezone-aware (defensive)
            if last_transition_at.tzinfo is None:
                last_transition_at = last_transition_at.replace(tzinfo=timezone.utc)
            self._last_transition_at[zone_id] = last_transition_at
        _LOGGER.debug(
            "DynamicPreset: restored zone=%s bucket=%s last_transition=%s",
            zone_id, bucket, last_transition_at.isoformat() if last_transition_at else None,
        )

    def get_zone_state(self, zone_id: str) -> dict[str, Any]:
        """Return current state for a zone (for sensor attribute rendering)."""
        now = dt_util.utcnow()
        bucket = self._active_bucket.get(zone_id)
        last_tx = self._last_transition_at.get(zone_id)
        options = self._get_options()
        dwell_min = float(options.get(CONF_DYNAMIC_PRESET_DWELL_MINUTES, DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES))
        dwell_remaining_min: float | None = None
        if last_tx is not None:
            elapsed = (now - last_tx).total_seconds() / 60.0
            remaining = dwell_min - elapsed
            dwell_remaining_min = max(0.0, remaining)
        return {
            "bucket": bucket,
            "last_transition_iso": last_tx.isoformat() if last_tx else None,
            "dwell_remaining_min": dwell_remaining_min,
        }

    # -------------------------------------------------------------------------
    # Core evaluation
    # -------------------------------------------------------------------------

    def evaluate_and_emit(
        self,
        zone_id: str,
        zone_data: dict,
        delta: float | None,
        house_state: str,
        apparent_high: float | None = None,
        baseline_high: float | None = None,
        now: datetime | None = None,
    ) -> list[PresetOverride]:
        """Evaluate bucket for a zone and return overrides to register.

        This method is SYNCHRONOUS and must be called from an async context
        only if the caller holds no Lock on _eval_lock (the async wrapper does that).

        Args:
            zone_id: canonical HVAC zone identifier
            zone_data: zone config dict from Zone Manager entry.options["zones"][name]
            delta: apparent_forecast_high − zone_home_cool_high (from WPM.baseline_delta_for_zone)
                   None = WPM has no forecast; return [] (Bug #5)
            house_state: current house state (for offset-reset check)
            apparent_high: raw apparent forecast high (for sensor attribute)
            baseline_high: zone's home baseline cool_high (for sensor attribute)
            now: UTC datetime (default: dt_util.utcnow())

        Returns:
            List of PresetOverride records for this zone (may be empty).

        Notes on skip_reason exposure (v4.7.7 B2): callers wanting the
        skip reason should use `evaluate_with_reason()` which returns
        `(overrides, skip_reason)`. The skip_reason taxonomy is one of:
        gate_disabled / no_forecast_delta / dwell_pending /
        unknown_bucket / home_range_not_configured / None.
        """
        overrides, _reason = self.evaluate_with_reason(
            zone_id=zone_id,
            zone_data=zone_data,
            delta=delta,
            house_state=house_state,
            apparent_high=apparent_high,
            baseline_high=baseline_high,
            now=now,
        )
        return overrides

    def evaluate_with_reason(
        self,
        zone_id: str,
        zone_data: dict,
        delta: float | None,
        house_state: str,
        apparent_high: float | None = None,
        baseline_high: float | None = None,
        now: datetime | None = None,
    ) -> tuple[list[PresetOverride], str | None]:
        """v4.7.7 B2: Like `evaluate_and_emit` but also returns the
        skip_reason when overrides is empty.

        Returns:
            (overrides, skip_reason)
            - overrides non-empty -> skip_reason is None
            - overrides empty -> skip_reason in {"gate_disabled",
              "no_forecast_delta", "dwell_pending", "unknown_bucket",
              "home_range_not_configured"}
        """
        if now is None:
            now = dt_util.utcnow()

        # Bug #11: ensure now is UTC-aware
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # --- Gate 1: zone opted-in
        if not zone_data.get(CONF_ZONE_DYNAMIC_PRESET_ENABLED, False):
            return [], "gate_disabled"

        # --- v4.7.17.2 fix-up (A-H1 + B-M3): winter gate is a calendar fact,
        # not a cross-coordinator PM-state fact. The previous PM-based check
        # (resolved_pm.current_season == SEASON_WINTER) silently failed open
        # on two paths:
        #   1. PresetManager._current_season is "" until determine_season()
        #      fires (HVAC setup + once daily), so cold-start ticks would
        #      skip the winter gate even in January.
        #   2. _current_season is never refreshed across season boundaries
        #      without an HA restart, so a Nov 1 boundary crossing on a
        #      long-running HA would also miss the gate.
        # Use dt_util.now() (HA local timezone) — "winter" is an
        # operator-facing-calendar concept, not UTC. Months per planning
        # doc §4 (Nov, Dec, Jan, Feb).
        month = dt_util.now().month
        if month in (11, 12, 1, 2):
            return [], "winter_season"

        # --- v4.7.17.2: resolve the coordinator-owned PresetManager ONCE
        # for the seasonal baseline lookup in `_build_overrides_with_reason`.
        # Pre-deploy Tier 1 H1: do NOT construct a fresh `PresetManager(
        # self.hass)` per tick — that loses `_current_season` continuity and
        # bypasses any CM override caching the resolved PM holds.
        resolved_pm = None
        try:
            from ..const import DOMAIN
            _cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if _cm is not None:
                _hvac = _cm.coordinators.get("hvac")
                if _hvac is not None:
                    resolved_pm = getattr(_hvac, "_preset_manager", None)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "DynamicPreset zone=%s: resolved_pm probe errored — proceeding (fail-open)",
                zone_id, exc_info=True,
            )

        # --- Gate 2: WPM has forecast / ring populated (v4.7.17.2: delta
        # is now relative_delta = forecast_apparent_high - 14d rolling median,
        # not the v4.7.16.4 forecast-vs-cool-target semantic).
        if delta is None:
            _LOGGER.debug("DynamicPreset zone=%s: no relative_delta — skipping", zone_id)
            return [], "no_forecast_delta"

        # --- Read config fresh (Bug #14)
        # v4.7.17.2: bucket boundary CONFs kept callable for diagnostic
        # `classify_bucket()` labelling only — they are no longer the
        # operator's primary tuning surface. The two new knobs below
        # (relax_f, tighten_f) drive the actual cool_high adjustment.
        options = self._get_options()
        cool_max = float(options.get(CONF_DYNAMIC_PRESET_DELTA_COOL_MAX, DEFAULT_DYNAMIC_PRESET_DELTA_COOL_MAX))
        mild_max = float(options.get(CONF_DYNAMIC_PRESET_DELTA_MILD_MAX, DEFAULT_DYNAMIC_PRESET_DELTA_MILD_MAX))
        hot_max = float(options.get(CONF_DYNAMIC_PRESET_DELTA_HOT_MAX, DEFAULT_DYNAMIC_PRESET_DELTA_HOT_MAX))
        dwell_min = float(options.get(CONF_DYNAMIC_PRESET_DWELL_MINUTES, DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES))
        hysteresis_f = float(options.get(CONF_DYNAMIC_PRESET_HYSTERESIS_F, DEFAULT_DYNAMIC_PRESET_HYSTERESIS_F))
        # v4.7.17.2: operator-facing knobs
        relax_f = float(options.get(CONF_DPM_COOL_DAY_RELAX_F, DEFAULT_DPM_COOL_DAY_RELAX_F))
        tighten_f = float(options.get(CONF_DPM_HOT_DAY_TIGHTEN_F, DEFAULT_DPM_HOT_DAY_TIGHTEN_F))
        # v4.7.17.2: compute the actual °F adjustment to apply to cool_high.
        # Drives override emission below; bucket label is now diagnostic.
        cool_high_adjustment_f = _compute_cool_high_adjustment(
            delta, relax_f, tighten_f,
        )

        # --- Classify fresh bucket
        fresh_bucket = classify_bucket(delta, cool_max, mild_max, hot_max)
        current_bucket = self._active_bucket.get(zone_id)

        # v4.7.7 B2: track whether a wanted transition was blocked by dwell.
        # We still emit the CURRENT bucket's overrides (no override change),
        # but if those come back empty for a config reason and dwell was
        # pending, we want the dwell reason surfaced to the user.
        dwell_was_pending = False

        # --- Check if transition is warranted
        if current_bucket is None:
            # First evaluation — initialize without dwell check
            _LOGGER.info(
                "DynamicPreset zone=%s: initial bucket=%s (delta=%.1f°F)",
                zone_id, fresh_bucket, delta,
            )
            self._active_bucket[zone_id] = str(fresh_bucket)
            self._last_transition_at[zone_id] = now
            current_bucket = str(fresh_bucket)
        elif str(fresh_bucket) != current_bucket:
            # Potential transition — check dwell and hysteresis
            last_tx = self._last_transition_at.get(zone_id, now)
            elapsed_min = (now - last_tx).total_seconds() / 60.0

            if elapsed_min < dwell_min:
                dwell_was_pending = True
                _LOGGER.debug(
                    "DynamicPreset zone=%s: bucket would change %s→%s "
                    "but dwell not elapsed (%.0f/%.0f min)",
                    zone_id, current_bucket, fresh_bucket,
                    elapsed_min, dwell_min,
                )
                # Stay in current_bucket; no override change
            elif not _passed_boundary_with_buffer(
                current_bucket, str(fresh_bucket), delta,
                cool_max, mild_max, hot_max, hysteresis_f
            ):
                _LOGGER.debug(
                    "DynamicPreset zone=%s: bucket would change %s→%s "
                    "but hysteresis buffer not cleared (delta=%.1f°F)",
                    zone_id, current_bucket, fresh_bucket, delta,
                )
                # Stay in current_bucket; no override change
            else:
                previous = current_bucket
                self._active_bucket[zone_id] = str(fresh_bucket)
                self._last_transition_at[zone_id] = now
                current_bucket = str(fresh_bucket)
                _LOGGER.info(
                    "DynamicPreset zone=%s: transitioned %s→%s (delta=%.1f°F)",
                    zone_id, previous, current_bucket, delta,
                )
                # Dispatch transition signal (non-blocking via dispatcher)
                try:
                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                    from .signals import SIGNAL_DYNAMIC_PRESET_TRANSITIONED
                    async_dispatcher_send(self.hass, SIGNAL_DYNAMIC_PRESET_TRANSITIONED, {
                        "zone_id": zone_id,
                        "previous_bucket": previous,
                        "new_bucket": current_bucket,
                        "delta_f": delta,
                        "now_iso": now.isoformat(),
                    })
                except Exception:  # pragma: no cover
                    _LOGGER.debug("DynamicPreset: signal dispatch failed", exc_info=True)

        # --- Build override records for the current bucket.
        # v4.7.7 B2: capture skip_reason from build path so the caller
        # can surface it (unknown_bucket / home_range_not_configured).
        # v4.7.17.2: cool_high_adjustment_f propagates the operator's
        # relax/tighten knob result into the override math. 0.0 → no
        # adjustment (typical day in the dead zone).
        overrides, build_reason = self._build_overrides_with_reason(
            zone_id=zone_id,
            zone_data=zone_data,
            bucket=current_bucket,
            house_state=house_state,
            cool_high_adjustment_f=cool_high_adjustment_f,
            resolved_pm=resolved_pm,
        )

        if overrides:
            return overrides, None
        # No overrides — prefer the build-path reason when present,
        # else fall back to dwell_pending if a transition was wanted.
        if build_reason is not None:
            return overrides, build_reason
        if dwell_was_pending:
            return overrides, "dwell_pending"
        # Should not happen — _build_overrides_with_reason returns a
        # reason when it returns []. Defensive fallback.
        return overrides, "home_range_not_configured"

    def _build_overrides(
        self,
        zone_id: str,
        zone_data: dict,
        bucket: str,
        house_state: str,
        cool_high_adjustment_f: float = 0.0,
    ) -> list[PresetOverride]:
        """Build PresetOverride records from zone_data for the given bucket.

        v4.7.7 B2: kept as thin wrapper around `_build_overrides_with_reason`
        for any out-of-tree callers; internal callers use the reason-aware
        variant directly.

        v4.7.17.2: cool_high_adjustment_f defaults to 0.0 for backward-compat
        with any out-of-tree callers. Internal calls now pass the
        operator-knob-driven adjustment value.
        """
        overrides, _ = self._build_overrides_with_reason(
            zone_id, zone_data, bucket, house_state, cool_high_adjustment_f,
        )
        return overrides

    def _build_overrides_with_reason(
        self,
        zone_id: str,
        zone_data: dict,
        bucket: str,
        house_state: str,
        cool_high_adjustment_f: float = 0.0,
        resolved_pm=None,
    ) -> tuple[list[PresetOverride], str | None]:
        """v4.7.7 B2: like `_build_overrides` but returns the skip_reason
        when overrides comes back empty.

        Returns:
            (overrides, skip_reason)
            - overrides non-empty -> skip_reason is None
            - overrides empty -> skip_reason in {"unknown_bucket",
              "home_range_not_configured"}
        """
        if bucket not in _BUCKET_CONF_KEYS:
            _LOGGER.warning("DynamicPreset: unknown bucket %r for zone=%s", bucket, zone_id)
            return [], "unknown_bucket"

        # v4.7.17.2 §6: per-bucket CONF cells (HOT_HOME_HIGH, etc.) remain
        # dormant in entry.options but are NOT read at runtime. The single
        # base preset comes from PresetManager seasonal defaults. Bucket
        # label still propagates as a diagnostic (assigned to override at
        # construction time).
        _ = _BUCKET_CONF_KEYS.get(bucket)  # presence-check only

        # Per-zone offset (§B.B.5)
        base_offset = float(zone_data.get(CONF_ZONE_DYNAMIC_PRESET_OFFSET, 0.0))
        reset_under_guest = zone_data.get(CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST, True)
        if reset_under_guest and house_state == "guest":
            zone_offset = 0.0
        else:
            zone_offset = base_offset

        # v4.7.17.2 P6: single base from PresetManager seasonal — the bucket
        # cell overlay (v4.7.x discrete-bucket mechanic) is retired in favor
        # of continuous adjustment off the seasonal baseline.
        #
        # Tier 1 H1: prefer the coordinator-resolved PM (passed in from
        # evaluate_with_reason) so we don't pay re-construction cost and
        # preserve `_current_season` continuity. Fall back to a fresh
        # construction only when the resolved PM is unavailable (e.g.,
        # direct call from a test or pre-coordinator-bringup path).
        home_low: float | None = None
        home_high: float | None = None
        try:
            _pm = resolved_pm
            if _pm is None:
                from .hvac_preset import PresetManager
                _pm = PresetManager(self.hass)
            _season_pair = _pm.get_seasonal_setpoints("home")
            if _season_pair is not None:
                # Tuple is (cool_setpoint, heat_setpoint) — Bug Class #49.
                home_high = float(_season_pair[0])
                home_low = home_high - 7.0
        except Exception:
            _LOGGER.debug(
                "DynamicPreset zone=%s bucket=%s: seasonal baseline lookup failed",
                zone_id, bucket, exc_info=True,
            )

        if home_low is None or home_high is None:
            _LOGGER.debug(
                "DynamicPreset zone=%s bucket=%s: seasonal baseline unavailable — no override",
                zone_id, bucket,
            )
            return [], "home_range_not_configured"

        # Apply per-zone offset to the high values, then layer the
        # v4.7.17.2 operator-knob adjustment on top. Order matters: zone
        # offset is per-room bias (e.g., Back Hallway +1°F because it
        # runs warmer); the adjustment is house-wide weather-driven.
        effective_home_high = float(home_high) + zone_offset + cool_high_adjustment_f
        effective_home_low = float(home_low)

        overrides: list[PresetOverride] = [
            PresetOverride(
                source=OVERRIDE_SOURCE_DYNAMIC_PRESET,
                preset="home",
                priority=DYNAMIC_PRESET_PRIORITY,
                cool_low=effective_home_low,
                cool_high=effective_home_high,
                active_when="dynamic_preset",
                zone_id=zone_id,
                bucket=bucket,
            )
        ]

        # Sleep preset (if enabled)
        sleep_enabled = zone_data.get(CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED, False)
        if sleep_enabled:
            # v4.7.17.2 §6: sleep bucket cells also dormant — derive sleep
            # range from home_high via the sleep-floor rule, then layer the
            # cool_high adjustment on top.
            effective_sleep_high = compute_sleep_high(
                float(home_high) + cool_high_adjustment_f, zone_offset,
            )
            effective_sleep_low = effective_home_low

            overrides.append(PresetOverride(
                source=OVERRIDE_SOURCE_DYNAMIC_PRESET,
                preset="sleep",
                priority=DYNAMIC_PRESET_PRIORITY,
                cool_low=effective_sleep_low,
                cool_high=effective_sleep_high,
                active_when="dynamic_preset",
                zone_id=zone_id,
                bucket=bucket,
            ))

        return overrides, None

    # -------------------------------------------------------------------------
    # Async wrapper (re-entrancy guard)
    # -------------------------------------------------------------------------

    async def async_evaluate_and_emit(
        self,
        zone_id: str,
        zone_data: dict,
        delta: float | None,
        house_state: str,
        apparent_high: float | None = None,
        baseline_high: float | None = None,
        now: datetime | None = None,
    ) -> list[PresetOverride]:
        """Async wrapper with re-entrancy guard (WPM-C1 pattern).

        If a prior evaluation is still running for another zone, this waits.
        Each zone evaluation is fast (no I/O), so contention is rare and brief.
        """
        async with self._eval_lock:
            return self.evaluate_and_emit(
                zone_id=zone_id,
                zone_data=zone_data,
                delta=delta,
                house_state=house_state,
                apparent_high=apparent_high,
                baseline_high=baseline_high,
                now=now,
            )

    async def async_evaluate_with_reason(
        self,
        zone_id: str,
        zone_data: dict,
        delta: float | None,
        house_state: str,
        apparent_high: float | None = None,
        baseline_high: float | None = None,
        now: datetime | None = None,
    ) -> tuple[list[PresetOverride], str | None]:
        """v4.7.7 B2: async wrapper around `evaluate_with_reason`.

        Same re-entrancy guard as `async_evaluate_and_emit` — the
        underlying eval is synchronous and fast.
        """
        async with self._eval_lock:
            return self.evaluate_with_reason(
                zone_id=zone_id,
                zone_data=zone_data,
                delta=delta,
                house_state=house_state,
                apparent_high=apparent_high,
                baseline_high=baseline_high,
                now=now,
            )
