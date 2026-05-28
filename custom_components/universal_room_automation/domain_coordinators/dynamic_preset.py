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
    DYNAMIC_PRESET_PRIORITY,
)
from .preset_overrides import (
    OVERRIDE_SOURCE_DYNAMIC_PRESET,
    PresetOverride,
)

_LOGGER = logging.getLogger(__name__)

# Sleep floor: sleep_high = max(SLEEP_FLOOR, home_high - 1) + offset
SLEEP_FLOOR_F: float = 74.0


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
        """
        if now is None:
            now = dt_util.utcnow()

        # Bug #11: ensure now is UTC-aware
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # --- Gate 1: zone opted-in
        if not zone_data.get(CONF_ZONE_DYNAMIC_PRESET_ENABLED, False):
            return []

        # --- Gate 2: WPM has forecast
        if delta is None:
            _LOGGER.debug("DynamicPreset zone=%s: no forecast delta — skipping", zone_id)
            return []

        # --- Read config fresh (Bug #14)
        options = self._get_options()
        cool_max = float(options.get(CONF_DYNAMIC_PRESET_DELTA_COOL_MAX, DEFAULT_DYNAMIC_PRESET_DELTA_COOL_MAX))
        mild_max = float(options.get(CONF_DYNAMIC_PRESET_DELTA_MILD_MAX, DEFAULT_DYNAMIC_PRESET_DELTA_MILD_MAX))
        hot_max = float(options.get(CONF_DYNAMIC_PRESET_DELTA_HOT_MAX, DEFAULT_DYNAMIC_PRESET_DELTA_HOT_MAX))
        dwell_min = float(options.get(CONF_DYNAMIC_PRESET_DWELL_MINUTES, DEFAULT_DYNAMIC_PRESET_DWELL_MINUTES))
        hysteresis_f = float(options.get(CONF_DYNAMIC_PRESET_HYSTERESIS_F, DEFAULT_DYNAMIC_PRESET_HYSTERESIS_F))

        # --- Classify fresh bucket
        fresh_bucket = classify_bucket(delta, cool_max, mild_max, hot_max)
        current_bucket = self._active_bucket.get(zone_id)

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

        # --- Build override records for the current bucket
        overrides = self._build_overrides(
            zone_id=zone_id,
            zone_data=zone_data,
            bucket=current_bucket,
            house_state=house_state,
        )

        return overrides

    def _build_overrides(
        self,
        zone_id: str,
        zone_data: dict,
        bucket: str,
        house_state: str,
    ) -> list[PresetOverride]:
        """Build PresetOverride records from zone_data for the given bucket."""
        if bucket not in _BUCKET_CONF_KEYS:
            _LOGGER.warning("DynamicPreset: unknown bucket %r for zone=%s", bucket, zone_id)
            return []

        home_low_key, home_high_key, sleep_low_key, sleep_high_key = _BUCKET_CONF_KEYS[bucket]

        # Per-zone offset (§B.B.5)
        base_offset = float(zone_data.get(CONF_ZONE_DYNAMIC_PRESET_OFFSET, 0.0))
        reset_under_guest = zone_data.get(CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST, True)
        if reset_under_guest and house_state == "guest":
            zone_offset = 0.0
        else:
            zone_offset = base_offset

        # Read bucket table values.
        # v4.7.4 D3: When customize_buckets=False (or not set), bucket cells may be
        # absent from zone_data. Derive from seasonal baseline "home" setpoints + offset.
        home_low = zone_data.get(home_low_key)
        home_high = zone_data.get(home_high_key)
        if (home_low is None or home_high is None) and not zone_data.get(
            CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS, False
        ):
            # Derived fallback: use seasonal home baseline as the bucket range.
            # This gives a meaningful override (the seasonal home setpoints shifted by
            # the zone's offset) without requiring per-bucket customization.
            try:
                from .hvac_preset import PresetManager
                _pm = PresetManager(self.hass)
                _season_pair = _pm.get_seasonal_setpoints("home")
                if _season_pair is not None:
                    home_high = _season_pair[0]  # cool_setpoint
                    home_low = home_high - 7.0    # standard 7°F spread
                    _LOGGER.debug(
                        "DynamicPreset zone=%s bucket=%s: derived from baseline "
                        "(cool=%.1f low=%.1f)",
                        zone_id, bucket, home_high, home_low,
                    )
            except Exception:
                _LOGGER.debug(
                    "DynamicPreset zone=%s bucket=%s: baseline derivation failed",
                    zone_id, bucket, exc_info=True,
                )

        if home_low is None or home_high is None:
            _LOGGER.debug(
                "DynamicPreset zone=%s bucket=%s: home range not configured — no override",
                zone_id, bucket,
            )
            return []

        # Apply offset to high values
        effective_home_high = float(home_high) + zone_offset
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
            sleep_low = zone_data.get(sleep_low_key)
            sleep_high = zone_data.get(sleep_high_key)

            if sleep_low is not None and sleep_high is not None:
                effective_sleep_high = float(sleep_high) + zone_offset
                effective_sleep_low = float(sleep_low)
            else:
                # Auto-derive from home range
                effective_sleep_high = compute_sleep_high(float(home_high), zone_offset)
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

        return overrides

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
