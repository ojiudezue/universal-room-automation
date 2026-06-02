"""WeatherProviderManager — ranked-list weather provider with failover + apparent-temp.

v4.7.x Cycle A: Replaces single-provider weather reliance with a ranked-list
manager that supports failover, staleness detection, and divergence flagging.

Bug class prevention:
- #5 (startup race): lazily initialized; returns None until first healthy probe
- #10 (cross-restart): no in-memory-only state; health re-derived from entity states
- #17 (unbounded retry): failover is state-driven, not timer-driven
- #19 (untracked tasks): all service calls awaited inline in event handlers
- #21 (timezone naive/aware): all datetime ops via dt_util only
- #22 (enum mismatch): WeatherProviderHealth as StrEnum
- #38 (async_listen unsub): every async_track_state_change_event unsub captured
- #42 (lambda + async_create_task): callbacks are @callback-decorated bound methods
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        def __str__(self) -> str:  # pragma: no cover
            return self.value
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .energy_const import (
    CONF_ENERGY_WEATHER_ENTITY,
    CONF_ENERGY_WEATHER_FALLBACK_1,
    CONF_ENERGY_WEATHER_FALLBACK_2,
    CONF_WEATHER_STALENESS_MAX_HOURS,
    CONF_WEATHER_DIVERGENCE_THRESHOLD_F,
    DEFAULT_WEATHER_ENTITY,
    DEFAULT_WEATHER_STALENESS_MAX_HOURS,
    DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F,
    # v4.7.17.2: rolling-median mechanic constants
    DPM_ROLLING_WINDOW_DAYS,
    DPM_ROLLING_WINDOW_MIN_DAYS,
)
from .signals import SIGNAL_WEATHER_PROVIDER_CHANGED, SIGNAL_WEATHER_DIVERGENCE_DETECTED

_LOGGER = logging.getLogger(__name__)

# Attribute names to probe for apparent temperature (provider-specific)
_APPARENT_TEMP_ATTRS = ("apparent_temperature", "temperature_feels_like")


class WeatherProviderHealth(StrEnum):
    """Health states for a weather provider."""

    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    NO_FORECAST = "no_forecast"
    # Provider has forecast but no apparent-temp attribute; still usable with fallback
    APPARENT_UNAVAILABLE = "apparent_unavailable"


@dataclass
class WeatherForecast:
    """Parsed forecast from a single provider."""

    raw_high: float | None
    raw_low: float | None
    apparent_high: float | None
    apparent_low: float | None
    provider_id: str
    # "high" | "fallback_raw" | "apparent_unavailable_fallback_raw" | "degraded_single"
    apparent_confidence: str
    divergence_f: float | None
    fetched_at: datetime = field(default_factory=dt_util.utcnow)


class WeatherProviderManager:
    """Ranked-list weather provider manager with failover and apparent-temp primitive.

    Singleton per integration entry, stored at hass.data[DOMAIN]["weather_manager"].

    Public API:
        async get_today_forecast() -> WeatherForecast | None
        current_apparent_temp() -> tuple[float | None, float]
        baseline_delta_for_zone(zone_id, preset) -> float | None
    """

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        """Initialize manager with current CM entry options.

        Does NOT set up state listeners — call async_setup() separately.
        """
        self.hass = hass
        self._options = dict(options)
        self._unsub_handles: list = []

        # Cached forecast — refreshed on each provider state-change event
        self._cached_forecast: WeatherForecast | None = None
        self._last_probe_at: datetime | None = None

        # Tracks which provider is currently "active"
        self._active_provider: str | None = None
        # Reason for last failover (for sensor attribute)
        self._failover_reason: str = ""
        # Per-provider health states (derived on state-change events)
        self._provider_health: dict[str, WeatherProviderHealth] = {}
        # Per-provider today-high values (used for divergence detection)
        self._provider_highs: dict[str, float] = {}
        # Divergence flag + transition tracking (WPM-C3: fire signal on enter only)
        self._divergence_f: float | None = None
        self._divergent: bool = False
        self._was_divergent: bool = False

        # WPM-C1: re-entrancy guard — serialises concurrent _refresh_all_providers calls
        self._refresh_lock: asyncio.Lock = asyncio.Lock()
        # WPM-C2: track tasks created by state-change handler (Bug #19)
        self._pending_refresh_tasks: set[asyncio.Task] = set()

        # v4.7.17.2: rolling 14-day median of forecast apparent_high.
        # In-memory list of (date_iso, value) tuples. Persisted via HA Store
        # under key 'ura_dpm_apparent_high_ring' (hydrated lazily in
        # async_setup; saved on every record). DPM's relative_delta semantic
        # (today vs rolling median) replaces the v4.7.16.4 indoor-target frame.
        self._apparent_high_ring: list[tuple[str, float]] = []
        self._apparent_high_store: Store = Store(
            hass, version=1, key="ura_dpm_apparent_high_ring"
        )

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Register state-change listeners on all configured provider entities."""
        providers = self._build_provider_list()
        if not providers:
            _LOGGER.warning(
                "WeatherProviderManager: no weather providers configured; "
                "using legacy CONF_ENERGY_WEATHER_ENTITY fallback"
            )
            legacy = self._options.get(CONF_ENERGY_WEATHER_ENTITY, DEFAULT_WEATHER_ENTITY)
            if legacy:
                providers = [legacy]

        # v4.7.17.2 fix-up B-H1: hydrate the ring BEFORE registering
        # state-change listeners. If listener registration happened first,
        # a provider state-change scheduled by HA core could fire
        # _handle_provider_state_change, which schedules a tracked refresh
        # task. That task races the in-flight Store.async_load(): the
        # refresh appends today's entry to a not-yet-hydrated empty ring
        # and persists, then the hydrate completes and overwrites the
        # in-memory ring with the OLD pre-race contents — silently
        # discarding today's entry. Bug Class #45 (concurrent reload race)
        # variant. Doing hydrate first closes the window — listeners are
        # registered against a fully-initialized ring.
        await self._hydrate_rolling_window_from_store()

        for entity_id in providers:
            if not entity_id:
                continue
            # Bug #38: capture unsub handle
            unsub = async_track_state_change_event(
                self.hass,
                [entity_id],
                self._handle_provider_state_change,
            )
            self._unsub_handles.append(unsub)

        _LOGGER.info(
            "WeatherProviderManager: watching %d provider(s): %s",
            len(providers),
            providers,
        )

        # Do an immediate probe so sensors have data before the first state change
        await self._refresh_all_providers()

    async def async_teardown(self) -> None:
        """Cancel all state-change listeners and in-flight refresh tasks."""
        for unsub in self._unsub_handles:
            unsub()
        self._unsub_handles.clear()

        # WPM-C2: cancel any in-flight refresh tasks (Bug #19)
        if self._pending_refresh_tasks:
            tasks = list(self._pending_refresh_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._pending_refresh_tasks.clear()

        _LOGGER.debug("WeatherProviderManager: listeners and tasks cancelled")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def get_today_forecast(self) -> WeatherForecast | None:
        """Return today's forecast from the active provider.

        Returns None until the first successful probe (Bug #5 — startup race).
        On divergence, returns median value with divergence_f populated.
        """
        # Probe freshly on each call so callers always get current state
        await self._refresh_all_providers()
        return self._cached_forecast

    def current_apparent_temp(self) -> tuple[float | None, float]:
        """Return (apparent_temp_value, age_seconds) from active provider state.

        Reads the weather entity's current state attributes directly — NOT the
        forecast response. Uses the same apparent-temp attribute probing order
        as the forecast path. Returns (None, 0.0) when unavailable.
        """
        active = self._active_provider
        if not active:
            return (None, 0.0)
        try:
            state = self.hass.states.get(active)
            if state is None or state.state in ("unavailable", "unknown"):
                return (None, 0.0)
            attrs = state.attributes
            apparent = _probe_apparent_temp_attrs(attrs)
            if apparent is None:
                # Fallback to raw temperature attribute
                apparent = attrs.get("temperature")
            now = dt_util.utcnow()
            age = (now - state.last_changed).total_seconds() if state.last_changed else 0.0
            return (apparent, age)
        except Exception:  # pragma: no cover
            _LOGGER.debug("WeatherProviderManager.current_apparent_temp: read failed", exc_info=True)
            return (None, 0.0)

    def baseline_delta_for_zone(self, zone_id: str, preset: str = "home") -> float | None:
        """Return (today's forecast_apparent_high − 14-day rolling median).

        v4.7.17.2 semantic change: the baseline is now the rolling 14-day
        median of forecast apparent_high (a self-tuning proxy for "what
        feels normal here"), NOT the operator's indoor cool_target. The
        operator framing memo rejected the indoor-target frame because
        it conflated "what I want indoors" with "what counts as a mild
        outdoor day."

        zone_id and preset args are retained for signature stability —
        the rolling median is house-wide (single location, single weather
        provider), so zone-level baselines no longer apply. Callers at
        sensor.py + energy.py do not need to change.

        Returns None when:
          - forecast is unavailable (provider unhealthy / startup race)
          - rolling window has < DPM_ROLLING_WINDOW_MIN_DAYS entries
            (just-deployed install; ring is filling)
        """
        forecast = self._cached_forecast
        if forecast is None or forecast.apparent_high is None:
            return None

        baseline_median = self._rolling_median_apparent_high()
        if baseline_median is None:
            return None
        return forecast.apparent_high - baseline_median

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _build_provider_list(self) -> list[str]:
        """Build ordered list of configured provider entity IDs (filtering empty)."""
        providers = []
        primary = self._options.get(CONF_ENERGY_WEATHER_ENTITY, "")
        fallback1 = self._options.get(CONF_ENERGY_WEATHER_FALLBACK_1, "")
        fallback2 = self._options.get(CONF_ENERGY_WEATHER_FALLBACK_2, "")
        for eid in (primary, fallback1, fallback2):
            if eid and eid not in providers:
                providers.append(eid)
        return providers

    def _staleness_max_hours(self) -> int:
        """Return configured staleness limit in hours."""
        return int(self._options.get(
            CONF_WEATHER_STALENESS_MAX_HOURS, DEFAULT_WEATHER_STALENESS_MAX_HOURS
        ))

    def _divergence_threshold_f(self) -> float:
        """Return configured divergence threshold in degrees F."""
        return float(self._options.get(
            CONF_WEATHER_DIVERGENCE_THRESHOLD_F, DEFAULT_WEATHER_DIVERGENCE_THRESHOLD_F
        ))

    @property
    def divergence_threshold_f(self) -> float:
        """Public accessor for the configured divergence threshold in degrees F."""
        return self._divergence_threshold_f()

    def priority_rank_for(self, entity_id: str) -> int | None:
        """Return 0-indexed rank of entity_id in the configured provider list.

        Returns 0 for primary, 1 for fallback_1, 2 for fallback_2.
        Returns None if entity_id is not in the configured provider list.
        """
        providers = self._build_provider_list()
        try:
            return providers.index(entity_id)
        except ValueError:
            return None

    def _check_provider_health(self, entity_id: str) -> WeatherProviderHealth:
        """Derive health status for a single provider from current HA state."""
        try:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unavailable", "unknown"):
                return WeatherProviderHealth.UNAVAILABLE

            # Staleness check — entity's last_changed timestamp
            last_changed = state.last_changed
            if last_changed is not None:
                now = dt_util.utcnow()
                # Make last_changed timezone-aware for comparison
                if last_changed.tzinfo is None:
                    last_changed = last_changed.replace(tzinfo=dt_util.UTC)
                age_hours = (now - last_changed).total_seconds() / 3600
                if age_hours > self._staleness_max_hours():
                    return WeatherProviderHealth.STALE

            # Apparent-temp presence check (soft — still usable via fallback)
            attrs = state.attributes
            apparent = _probe_apparent_temp_attrs(attrs)
            if apparent is None:
                return WeatherProviderHealth.APPARENT_UNAVAILABLE

            return WeatherProviderHealth.HEALTHY
        except Exception:
            _LOGGER.debug("WeatherProviderManager._check_provider_health error", exc_info=True)
            return WeatherProviderHealth.UNAVAILABLE

    async def _fetch_provider_forecast(self, entity_id: str) -> dict[str, Any] | None:
        """Call weather.get_forecasts for today's daily forecast.

        Returns the first daily forecast dict or None on any error.
        Bug #19: called inline (awaited), no fire-and-forget.
        """
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
            if not response:
                return None
            # Response shape: {entity_id: {"forecast": [...]}}
            forecasts = (response.get(entity_id) or {}).get("forecast", [])
            if not forecasts:
                return None
            return forecasts[0]
        except Exception:
            _LOGGER.debug(
                "WeatherProviderManager: weather.get_forecasts failed for %s",
                entity_id,
                exc_info=True,
            )
            return None

    async def _refresh_all_providers(self) -> None:
        """Re-derive health, fetch forecasts, elect active provider, check divergence.

        WPM-C1: guarded by _refresh_lock to prevent concurrent execution (e.g.
        3 providers updating in the same event-loop tick each firing a state-change
        callback). Each provider's forecast is fetched exactly once and cached in
        `_fetched_forecasts` — the active provider reuses that result rather than
        making a second service call.
        """
        async with self._refresh_lock:
            await self._refresh_all_providers_locked()

    async def _refresh_all_providers_locked(self) -> None:
        """Inner body of _refresh_all_providers, runs under _refresh_lock."""
        providers = self._build_provider_list()
        if not providers:
            legacy = self._options.get(CONF_ENERGY_WEATHER_ENTITY, DEFAULT_WEATHER_ENTITY)
            if legacy:
                providers = [legacy]

        previous_active = self._active_provider
        new_active: str | None = None
        provider_highs: dict[str, float] = {}
        provider_apparent_highs: dict[str, float] = {}
        health_map: dict[str, WeatherProviderHealth] = {}
        # WPM-C1: cache each provider's forecast so the active provider isn't re-fetched
        fetched_forecasts: dict[str, dict] = {}

        for eid in providers:
            if not eid:
                continue
            health = self._check_provider_health(eid)
            health_map[eid] = health

            is_usable = health in (
                WeatherProviderHealth.HEALTHY,
                WeatherProviderHealth.APPARENT_UNAVAILABLE,
            )
            if not is_usable:
                continue

            forecast_data = await self._fetch_provider_forecast(eid)
            if forecast_data is None:
                health_map[eid] = WeatherProviderHealth.NO_FORECAST
                continue

            # Cache result — reused below for the active provider (WPM-C1)
            fetched_forecasts[eid] = forecast_data

            raw_high = _parse_float(forecast_data.get("temperature"))
            apparent_high = _probe_apparent_temp_attrs(forecast_data)

            if raw_high is not None:
                provider_highs[eid] = raw_high
            if apparent_high is not None:
                provider_apparent_highs[eid] = apparent_high

            if new_active is None:
                new_active = eid

        self._provider_health = health_map
        self._provider_highs = provider_highs

        # Elect active provider
        self._active_provider = new_active

        # Compute divergence across healthy providers
        divergence_f, is_divergent = self._compute_divergence(provider_highs)
        self._divergence_f = divergence_f
        self._divergent = is_divergent

        # Build the cached forecast from the active provider's already-fetched data
        if new_active:
            # WPM-C1: reuse cached result — NO second service call
            forecast_data = fetched_forecasts.get(new_active)
            if forecast_data:
                raw_high = _parse_float(forecast_data.get("temperature"))
                raw_low = _parse_float(forecast_data.get("templow"))
                apparent_high = _probe_apparent_temp_attrs(forecast_data)
                apparent_low = None  # Most providers don't expose apparent_low

                if apparent_high is not None:
                    confidence = "high" if not is_divergent else "low_divergent"
                elif len(providers) == 1:
                    apparent_high = raw_high  # fallback to raw
                    confidence = "fallback_raw"
                else:
                    apparent_high = raw_high  # fallback to raw with flag
                    confidence = "apparent_unavailable_fallback_raw"

                # WPM-H3: divergence median uses apparent highs, falls back to raw
                if is_divergent and len(provider_apparent_highs) >= 2:
                    vals = sorted(provider_apparent_highs.values())
                    mid = len(vals) // 2
                    apparent_high = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
                    confidence = "low_divergent"
                elif is_divergent and len(provider_highs) >= 2:
                    # Fallback: not enough apparent values — use raw median
                    vals = sorted(provider_highs.values())
                    mid = len(vals) // 2
                    apparent_high = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
                    confidence = "low_divergent"

                self._cached_forecast = WeatherForecast(
                    raw_high=raw_high,
                    raw_low=raw_low,
                    apparent_high=apparent_high,
                    apparent_low=apparent_low,
                    provider_id=new_active,
                    apparent_confidence=confidence,
                    divergence_f=divergence_f,
                    fetched_at=dt_util.utcnow(),
                )
                # v4.7.17.2: record today's apparent_high into the rolling
                # window for DPM's relative_delta computation. Dedupe by
                # date inside _record_daily_apparent_high — same date called
                # twice in one day is a single ring entry.
                #
                # v4.7.17.2 fix-up A-H2: ring key uses UTC date, not local.
                # Semantic: one canonical reading per UTC day. WPM's other
                # datetimes (fetched_at, last_changed comparisons) are all
                # UTC; mixing local-date keys with UTC timestamps created a
                # DST/tz-boundary regression risk on the cycle's central
                # correctness anchor. NOTE: this is INTENTIONALLY different
                # from the DPM winter gate's dt_util.now() — winter is a
                # calendar/operator-facing concept, this ring key is a
                # canonical-day concept.
                if apparent_high is not None:
                    await self._record_daily_apparent_high(
                        dt_util.utcnow().date().isoformat(), float(apparent_high),
                    )
            else:
                self._cached_forecast = None
        else:
            self._cached_forecast = None

        # Log failover if active provider changed
        if new_active != previous_active:
            if new_active is None:
                reason = "all_stale_or_unavailable"
                self._failover_reason = reason
                _LOGGER.info(
                    "WeatherProviderManager: all providers stale/unavailable "
                    "(checked %d providers)",
                    len(providers),
                )
            else:
                reason = f"previous={previous_active or 'none'}"
                self._failover_reason = reason
                _LOGGER.info(
                    "WeatherProviderManager: active provider -> %s (reason: %s)",
                    new_active,
                    reason,
                )
            # Fire dispatcher signal (Bug #38 — listeners on this signal clean up
            # via their own unsub chains)
            try:
                from homeassistant.helpers.dispatcher import async_dispatcher_send
                from .signals import SIGNAL_WEATHER_PROVIDER_CHANGED
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_WEATHER_PROVIDER_CHANGED,
                    {"active": new_active, "reason": reason},
                )
            except Exception:
                _LOGGER.debug("WeatherProviderManager: dispatcher send failed", exc_info=True)

        # WPM-C3: fire divergence signal only on enter-divergence transition
        was_divergent = self._was_divergent
        self._was_divergent = is_divergent
        if is_divergent and not was_divergent:
            _LOGGER.warning(
                "WeatherProviderManager: divergence entered — %.1f°F exceeds threshold %.1f°F "
                "(providers: %s)",
                divergence_f or 0.0,
                self._divergence_threshold_f(),
                dict(provider_highs),
            )
            try:
                from homeassistant.helpers.dispatcher import async_dispatcher_send
                from .signals import SIGNAL_WEATHER_DIVERGENCE_DETECTED
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_WEATHER_DIVERGENCE_DETECTED,
                    {"divergence_f": divergence_f, "provider_highs": dict(provider_highs)},
                )
            except Exception:
                _LOGGER.debug("WeatherProviderManager: divergence dispatcher send failed", exc_info=True)
        elif was_divergent and not is_divergent:
            _LOGGER.info(
                "WeatherProviderManager: divergence cleared (providers now within %.1f°F threshold)",
                self._divergence_threshold_f(),
            )

    def _compute_divergence(
        self, provider_highs: dict[str, float]
    ) -> tuple[float | None, bool]:
        """Compute divergence across ≥2 providers.

        Returns (divergence_f, is_divergent).
        """
        if len(provider_highs) < 2:
            return (None, False)
        vals = list(provider_highs.values())
        delta = max(vals) - min(vals)
        threshold = self._divergence_threshold_f()
        return (delta, delta >= threshold)

    # -------------------------------------------------------------------------
    # v4.7.17.2: Rolling 14-day median of forecast apparent_high
    #
    # Replaces the v4.7.16.4 _get_zone_baseline_high path. The rolling
    # median is a self-tuning proxy for "what feels normal here" — no
    # operator config required, naturally adapts to seasonal transitions
    # and climate shift. Persisted across HA restarts via HA Store under
    # key 'ura_dpm_apparent_high_ring' (cap 14 entries, keyed by ISO date).
    # -------------------------------------------------------------------------

    def _rolling_median_apparent_high(self) -> float | None:
        """Return median of the ring; None if fewer than MIN_DAYS entries.

        Below DPM_ROLLING_WINDOW_MIN_DAYS (7), the median is too noisy
        to trust — DPM falls back to the existing 'no_forecast_delta'
        skip reason, identical UX to a stale forecast. After 7+ entries
        accumulate (one per day post-deploy), DPM begins emitting.
        """
        if len(self._apparent_high_ring) < DPM_ROLLING_WINDOW_MIN_DAYS:
            return None
        values = [v for _, v in self._apparent_high_ring]
        return float(statistics.median(values))

    async def _record_daily_apparent_high(
        self, date_iso: str, value: float,
    ) -> None:
        """Append today's apparent_high to the ring; dedupe by date; cap at
        DPM_ROLLING_WINDOW_DAYS; persist via Store.

        Called once per day from `_refresh_all_providers_locked` when a
        fresh forecast lands. Same-day calls update the existing entry
        rather than appending (forecast may be refreshed multiple times
        on the same calendar day).
        """
        # Dedupe by date — replace if today already recorded
        for i, (existing_date, _) in enumerate(self._apparent_high_ring):
            if existing_date == date_iso:
                if self._apparent_high_ring[i][1] != value:
                    self._apparent_high_ring[i] = (date_iso, value)
                    await self._persist_ring()
                return
        # New date — append, evict oldest if over cap
        self._apparent_high_ring.append((date_iso, value))
        while len(self._apparent_high_ring) > DPM_ROLLING_WINDOW_DAYS:
            self._apparent_high_ring.pop(0)
        await self._persist_ring()

    async def _persist_ring(self) -> None:
        """Save the ring to HA Store. Cap is 14 entries → tiny write.

        Pre-deploy Tier 1 M3: log Store failures at WARNING level so a
        silent disk/permission/schema-corruption failure surfaces in HA
        logs. Without this the rolling window would degrade to in-memory
        only and the operator would never know — across the next restart
        DPM would silently revert to the 7-day cold-start no-op state.
        """
        try:
            await self._apparent_high_store.async_save(
                {"ring": [list(entry) for entry in self._apparent_high_ring]}
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "WeatherProviderManager: DPM rolling-window persist failed — "
                "ring will not survive restart. Check disk/permissions.",
                exc_info=True,
            )

    async def _hydrate_rolling_window_from_store(self) -> None:
        """Load the ring from Store on startup; drop entries > 21 days old.

        The 21-day staleness threshold is wider than the 14-day window
        so a brief multi-day outage doesn't drop otherwise-valid entries.
        Entries older than that lose enough relevance (e.g., shoulder
        season transition) that we'd rather start fresh.
        """
        try:
            data = await self._apparent_high_store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "WeatherProviderManager: DPM rolling-window hydrate failed — "
                "starting with empty ring (DPM will no-op until 7 days collected).",
                exc_info=True,
            )
            return
        if not data or not isinstance(data, dict) or "ring" not in data:
            return
        # v4.7.17.2 fix-up A-H2: cutoff uses UTC to match the ring's UTC
        # date keys (recorded via dt_util.utcnow().date() at the
        # _record_daily_apparent_high call site).
        cutoff_date = dt_util.utcnow().date() - timedelta(days=21)
        cleaned: list[tuple[str, float]] = []
        for entry in data["ring"]:
            try:
                date_iso, value = entry[0], entry[1]
                entry_date = datetime.fromisoformat(date_iso).date()
            except (ValueError, TypeError, IndexError):
                continue
            if entry_date < cutoff_date:
                continue
            try:
                cleaned.append((date_iso, float(value)))
            except (ValueError, TypeError):
                continue
        # Cap to most-recent DPM_ROLLING_WINDOW_DAYS entries
        self._apparent_high_ring = cleaned[-DPM_ROLLING_WINDOW_DAYS:]
        _LOGGER.debug(
            "WeatherProviderManager: rolling window hydrated with %d entries",
            len(self._apparent_high_ring),
        )

    # -------------------------------------------------------------------------
    # State-change event handler (Bug #42: @callback-decorated bound method)
    # -------------------------------------------------------------------------

    @callback
    def _handle_provider_state_change(self, event) -> None:
        """Handle state-change event from a weather provider entity.

        Creates a task to re-probe all providers. Inline await inside a
        @callback is not allowed; we schedule the async work via
        hass.async_create_task with a named coroutine (not a lambda — Bug #42).
        """
        entity_id = event.data.get("entity_id", "")
        _LOGGER.debug("WeatherProviderManager: state change on %s", entity_id)
        # Bug #42: use hass.async_create_task with a named coroutine, NOT a lambda
        # WPM-C2: track the task so it can be cancelled on teardown (Bug #19)
        task = self.hass.async_create_task(
            self._refresh_all_providers(),
            name="ura_weather_manager_refresh",
        )
        self._pending_refresh_tasks.add(task)
        task.add_done_callback(self._pending_refresh_tasks.discard)

    # -------------------------------------------------------------------------
    # Read-only properties used by sensors
    # -------------------------------------------------------------------------

    @property
    def active_provider(self) -> str | None:
        """Return entity_id of current active provider, or None."""
        return self._active_provider

    @property
    def provider_status_str(self) -> str:
        """Return sensor state string: entity_id, 'none', or 'all_stale'."""
        if self._active_provider:
            return self._active_provider
        providers = self._build_provider_list()
        if not providers:
            return "none"
        return "all_stale"

    @property
    def is_divergent(self) -> bool:
        """Return True when provider divergence exceeds threshold."""
        return self._divergent

    @property
    def divergence_f(self) -> float | None:
        """Return divergence magnitude in °F, or None when <2 providers."""
        return self._divergence_f

    @property
    def failover_reason(self) -> str:
        """Return reason for last failover."""
        return self._failover_reason

    @property
    def provider_health_map(self) -> dict[str, str]:
        """Return {entity_id: health_str} for all configured providers."""
        return {eid: str(h) for eid, h in self._provider_health.items()}

    @property
    def healthy_provider_count(self) -> int:
        """Return count of currently-healthy providers."""
        return sum(
            1 for h in self._provider_health.values()
            if h in (WeatherProviderHealth.HEALTHY, WeatherProviderHealth.APPARENT_UNAVAILABLE)
        )

    @property
    def total_provider_count(self) -> int:
        """Return total count of configured providers."""
        return len(self._build_provider_list())

    @property
    def apparent_confidence(self) -> str:
        """Return apparent_confidence from the cached forecast, or 'unavailable'."""
        if self._cached_forecast is None:
            return "unavailable"
        return self._cached_forecast.apparent_confidence

    def current_apparent_forecast_high(self) -> float | None:
        """Return the last-known apparent forecast high without triggering a refresh.

        WPM-H2: non-blocking accessor for sensor reads — sensors must never call
        get_today_forecast() (which forces a full refresh on every HA state poll).
        Returns None until the first successful probe.
        """
        if self._cached_forecast is None:
            return None
        return self._cached_forecast.apparent_high


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _probe_apparent_temp_attrs(attrs: dict[str, Any]) -> float | None:
    """Probe a dict (forecast entry OR state.attributes) for apparent temperature.

    Provider mapping:
    - Met.no, Pirate Weather, OpenWeatherMap: apparent_temperature
    - NWS (older mapping): temperature_feels_like
    """
    for key in _APPARENT_TEMP_ATTRS:
        val = attrs.get(key)
        if val is not None:
            return _parse_float(val)
    return None


def _parse_float(val: Any) -> float | None:
    """Safe float parse; returns None on None or non-numeric."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
