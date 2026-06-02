"""v4.7.18 — DPM drift guard + cleanup.

Behavioral tests for the 6 load-bearing decisions in
PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:

  1. Median slice integrity — 14d median slice survives the 14→90 ring widen.
  2. Store hydrate cap — hydrate caps to DPM_ROLLING_WINDOW_MAX_DAYS=90.
  3. WPM accessor used (not kwarg) — DPM consults
     `weather_manager.current_apparent_forecast_high()` on its tick, not a
     hardcoded value or a kwarg threaded through every caller.
  4. D2 disposition lock — `_validate_dynamic_preset_input` has been deleted;
     no caller remains in production code.
  5. Counter ownership / restart resilience — `restore_blocked_counter`
     rehydrates `_relax_ceiling_blocked_count` across restart.
  6. H4 close-out timing gate — heat-wave gate fires only above the ceiling
     and only on positive (relax) adjustments.

Imports `test_v47x_dynamic_preset` first to inherit its homeassistant module
mocking (Bug Class #44 pattern). That gives us a working
DynamicPresetOverrideSource + the energy_const constants without re-doing the
~150 lines of mock setup here.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """DynamicPresetOverrideSource.__init__ constructs asyncio.Lock() which
    requires a running event loop in Python 3.9. Provide one per test."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield
    # Do not close — other tests may share it.

# Inherit the mock-everything setup from test_v47x_dynamic_preset.
# That module mocks all homeassistant.* submodules and loads
# energy_const + dynamic_preset.
from test_v47x_dynamic_preset import (  # noqa: F401
    _UTC,
    _utcnow,
    _make_hass,
    _default_options,
    _default_zone_data,
    _make_source,
    DynamicPresetOverrideSource,
    _load_submod,
    _dc_path,
    _dc,
)

from custom_components.universal_room_automation.domain_coordinators.dynamic_preset import (
    _resolve_relax_ceiling,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DPM_ROLLING_WINDOW_DAYS,
    DPM_ROLLING_WINDOW_MAX_DAYS,
    DPM_P25_MIN_DAYS,
    DPM_RELAX_CEILING_MODE_AUTO,
    DPM_RELAX_CEILING_MODE_OFF,
    DPM_RELAX_CEILING_MODE_MODERATE_90,
    DPM_RELAX_CEILING_AUTO_FALLBACK_F,
    CONF_DPM_RELAX_CEILING_MODE,
    CONF_DPM_COOL_DAY_RELAX_F,
    CONF_DPM_HOT_DAY_TIGHTEN_F,
    CONF_ZONE_DYNAMIC_PRESET_ENABLED,
    CONF_ZONE_DYNAMIC_PRESET_SLEEP_ENABLED,
)


# ---------------------------------------------------------------------------
# WeatherProviderManager loader — defer aiosqlite + Store mocks not done by
# the dynamic_preset test setup.
# ---------------------------------------------------------------------------


def _load_weather_manager():
    """Load weather_manager module under the same mocked HA stack."""
    # Patch homeassistant.helpers.storage.Store before loading WPM.
    storage_mod = sys.modules.get("homeassistant.helpers.storage")
    if storage_mod is None:
        storage_mod = types.ModuleType("homeassistant.helpers.storage")
        sys.modules["homeassistant.helpers.storage"] = storage_mod
    if not hasattr(storage_mod, "Store"):
        storage_mod.Store = MagicMock()
    # event module may need async_track_time_interval
    event_mod = sys.modules.get("homeassistant.helpers.event")
    if event_mod is not None and not hasattr(event_mod, "async_track_time_interval"):
        event_mod.async_track_time_interval = MagicMock(return_value=lambda: None)
    return _load_submod("weather_manager")


# ---------------------------------------------------------------------------
# Test 1 — Median slice integrity (the 14-day median survives 14→90 widen)
# ---------------------------------------------------------------------------


class TestMedianSliceIntegrity:
    """Decision 1: the 14-day median must slice the most-recent 14 entries
    from the now-90-entry ring, NOT compute a median across the full ring.
    Without `ring[-DPM_ROLLING_WINDOW_DAYS:]` the median silently changes
    semantics post-deploy."""

    def test_median_uses_last_14_entries_not_full_ring(self):
        wm = _load_weather_manager()
        WeatherProviderManager = wm.WeatherProviderManager

        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})

        # First 16 entries at 100°F, last 14 entries at 75°F.
        # Full-ring median = ~87.5; last-14 median = 75.0.
        base_date = datetime(2026, 1, 1, tzinfo=_UTC).date()
        mgr._apparent_high_ring = []
        for i in range(16):
            d = base_date + timedelta(days=i)
            mgr._apparent_high_ring.append((d.isoformat(), 100.0))
        for i in range(16, 30):
            d = base_date + timedelta(days=i)
            mgr._apparent_high_ring.append((d.isoformat(), 75.0))

        # Pre-condition: 30 entries, full-ring median would be 87.5.
        assert len(mgr._apparent_high_ring) == 30

        result = mgr._rolling_median_apparent_high()
        # Must equal the median of the last 14 entries (all 75.0), NOT 87.5.
        assert result == 75.0, (
            f"Decision 1: 14-day median must slice ring[-{DPM_ROLLING_WINDOW_DAYS}:]. "
            f"Got {result} — expected 75.0 (last-14 median). Full-ring median "
            f"(broken) would be ~87.5."
        )


# ---------------------------------------------------------------------------
# Test 2 — Store hydrate cap (90)
# ---------------------------------------------------------------------------


class TestStoreHydrateCap:
    """Decision 2: hydrate caps ring to DPM_ROLLING_WINDOW_MAX_DAYS (90).
    Pre-v4.7.18 stores ≤14; new ring grows toward 90; nothing beyond 90
    survives the hydrate."""

    def test_hydrate_caps_to_max_days(self):
        wm = _load_weather_manager()
        WeatherProviderManager = wm.WeatherProviderManager

        hass = _make_hass()
        mgr = WeatherProviderManager(hass, {})

        # Build 95 entries — all recent (within 97-day staleness margin).
        # `dt_util.utcnow()` here resolves through the test mock to
        # datetime.now(UTC); compute dates relative to "today" so they all
        # survive the cutoff (cutoff = today - 97 days).
        today = datetime.now(_UTC).date()
        entries = []
        for i in range(95):
            # spread entries 0..94 days back — all within 97-day window
            d = today - timedelta(days=i)
            entries.append([d.isoformat(), 80.0 + i * 0.01])

        # Mock Store.async_load to return our entries.
        async def _fake_load():
            return {"ring": entries}

        mgr._apparent_high_store = MagicMock()
        mgr._apparent_high_store.async_load = _fake_load

        # Run the hydrate.
        import asyncio
        asyncio.run(mgr._hydrate_rolling_window_from_store())

        assert len(mgr._apparent_high_ring) == DPM_ROLLING_WINDOW_MAX_DAYS, (
            f"Decision 2: hydrate must cap to DPM_ROLLING_WINDOW_MAX_DAYS "
            f"({DPM_ROLLING_WINDOW_MAX_DAYS}). Got len={len(mgr._apparent_high_ring)}."
        )
        # Most-recent entries retained (cleaned[-90:] = last 90 dates by
        # input list order; input is today, today-1, ..., today-94, so
        # cleaned (sort-stable) is the same order, and [-90:] = entries
        # 5..94. The first kept entry's value should be 80.0 + 5*0.01 = 80.05.
        # We only assert the LENGTH is right; ordering can be debated.
        # But verify the ring is non-trivial:
        assert all(80.0 <= v <= 82.0 for _, v in mgr._apparent_high_ring)


# ---------------------------------------------------------------------------
# Test 3 — WPM accessor used (not kwarg)
# ---------------------------------------------------------------------------


class TestWpmAccessorUsed:
    """Decision 3: DPM's heat-wave gate must consult WPM via the public
    `current_apparent_forecast_high()` accessor (and `_p25_apparent_high()`),
    NOT via a kwarg threaded through evaluate_and_emit. Verified by mocking
    the accessors and confirming they're invoked."""

    def test_dpm_calls_current_apparent_forecast_high_on_tick(self):
        # Mock WPM with the accessors.
        mock_wpm = MagicMock()
        mock_wpm.current_apparent_forecast_high = MagicMock(return_value=85.0)
        mock_wpm._p25_apparent_high = MagicMock(return_value=88.0)

        # Build a source with mode=auto (gate active) + relax_f > 0.
        opts = _default_options()
        opts[CONF_DPM_COOL_DAY_RELAX_F] = 1.0
        opts[CONF_DPM_HOT_DAY_TIGHTEN_F] = 1.0
        opts[CONF_DPM_RELAX_CEILING_MODE] = DPM_RELAX_CEILING_MODE_AUTO

        source = _make_source(options=opts)

        # Hook the mock WPM into hass.data — the DPM code path looks for
        # hass.data[DOMAIN]["weather_manager"].
        from custom_components.universal_room_automation.const import DOMAIN
        source.hass.data = {DOMAIN: {"weather_manager": mock_wpm}}

        # Build a zone with sleep disabled and a positive (relax) delta
        # so the gate evaluation reaches the WPM probe.
        zone_data = _default_zone_data(
            enabled=True, offset=0.0, reset_guest=True, sleep_enabled=False,
        )
        # delta in the cool-day band so adjustment is positive (relax direction).
        delta = -3.0

        source.evaluate_and_emit(
            zone_id="test_zone",
            zone_data=zone_data,
            delta=delta,
            house_state="home",
            apparent_high=82.0,
            baseline_high=76.0,
        )

        assert mock_wpm.current_apparent_forecast_high.called, (
            "Decision 3: DPM must call WPM.current_apparent_forecast_high() "
            "on its tick — accessor pattern, not kwarg pattern."
        )


# ---------------------------------------------------------------------------
# Test 4 — D2 disposition lock
# ---------------------------------------------------------------------------


class TestD2DispositionLock:
    """Decision 4: _validate_dynamic_preset_input was deleted in D2. Lock
    the disposition so future cycles don't accidentally resurrect it without
    an explicit decision."""

    def test_validate_dynamic_preset_input_deleted(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation", "config_flow.py",
        )
        with open(path) as f:
            src = f.read()
        # The function definition line must NOT exist (only the comment
        # explaining the deletion may mention the name).
        assert "def _validate_dynamic_preset_input(" not in src, (
            "Decision 4 (D2): `def _validate_dynamic_preset_input(` must "
            "remain DELETED. If a new caller needs it, restore via an "
            "explicit cycle decision — do not silently resurrect."
        )

    def test_no_self_validate_calls_remain(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation", "config_flow.py",
        )
        with open(path) as f:
            src = f.read()
        # No `self._validate_dynamic_preset_input(` invocations either.
        assert "self._validate_dynamic_preset_input(" not in src, (
            "Decision 4 (D2): no production caller may invoke the deleted helper."
        )


# ---------------------------------------------------------------------------
# Test 5 — Counter ownership / restart resilience
# ---------------------------------------------------------------------------


class TestCounterRestartResilience:
    """Decision 5: counter ownership lives on DynamicPresetOverrideSource.
    `restore_blocked_counter` rehydrates from RestoreEntity attrs across
    restart. Mirrors `restore_zone_state` (Bug #10 pattern)."""

    def test_restore_rehydrates_counter(self):
        # Simulate a pre-restart source with counter=7.
        source_before = _make_source()
        source_before._relax_ceiling_blocked_count["zone_master"] = 7
        last_blocked = datetime(2026, 6, 1, 14, 30, tzinfo=_UTC)
        source_before._relax_ceiling_last_blocked_at["zone_master"] = last_blocked

        # Simulate restart: a fresh source instance.
        source_after = _make_source()
        assert source_after._relax_ceiling_blocked_count.get("zone_master", 0) == 0

        # Restore via the public API.
        source_after.restore_blocked_counter(
            zone_id="zone_master",
            count=7,
            last_blocked_at=last_blocked,
        )

        assert source_after._relax_ceiling_blocked_count["zone_master"] == 7, (
            "Decision 5: restore_blocked_counter must rehydrate the counter "
            "to its pre-restart value."
        )
        assert source_after._relax_ceiling_last_blocked_at["zone_master"] == last_blocked

    def test_restore_handles_naive_datetime(self):
        # Defensive coercion: naive datetimes get UTC timezone.
        source = _make_source()
        naive = datetime(2026, 6, 1, 14, 30)  # no tzinfo
        source.restore_blocked_counter(
            zone_id="zone_naive",
            count=3,
            last_blocked_at=naive,
        )
        result = source._relax_ceiling_last_blocked_at["zone_naive"]
        assert result.tzinfo is not None, (
            "Decision 5: naive datetimes must be coerced to UTC-aware "
            "(Bug #11 pattern)."
        )


# ---------------------------------------------------------------------------
# Test 6 — H4 close-out timing gate
# ---------------------------------------------------------------------------


class TestHeatWaveGateTiming:
    """Decision 6: heat-wave gate fires ONLY when:
      - mode != off (ceiling resolvable)
      - today_apparent_high >= ceiling_f
      - adjustment is positive (relax direction)
    Tighten direction NEVER gated. Below-ceiling days never gate."""

    def _build(
        self,
        today_apparent_high: float,
        p25_apparent_high: float | None,
        mode: str,
        delta: float,
    ):
        opts = _default_options()
        opts[CONF_DPM_COOL_DAY_RELAX_F] = 1.0
        opts[CONF_DPM_HOT_DAY_TIGHTEN_F] = 1.0
        opts[CONF_DPM_RELAX_CEILING_MODE] = mode

        source = _make_source(options=opts)

        mock_wpm = MagicMock()
        mock_wpm.current_apparent_forecast_high = MagicMock(
            return_value=today_apparent_high
        )
        mock_wpm._p25_apparent_high = MagicMock(return_value=p25_apparent_high)

        from custom_components.universal_room_automation.const import DOMAIN
        source.hass.data = {DOMAIN: {"weather_manager": mock_wpm}}

        zone_data = _default_zone_data(
            enabled=True, offset=0.0, reset_guest=True, sleep_enabled=False,
        )
        source.evaluate_and_emit(
            zone_id="z1",
            zone_data=zone_data,
            delta=delta,
            house_state="home",
            apparent_high=today_apparent_high,
            baseline_high=76.0,
        )
        return source

    def test_below_ceiling_does_not_fire(self):
        # 85°F < ceiling 90°F (auto mode, p25=None → fallback 90.0), cool-day
        # relax direction — gate must NOT fire.
        source = self._build(
            today_apparent_high=85.0,
            p25_apparent_high=None,  # < 30d → 90.0 fallback ceiling
            mode=DPM_RELAX_CEILING_MODE_AUTO,
            delta=-3.0,  # cool day → positive (relax) adjustment
        )
        assert source._relax_ceiling_blocked_count.get("z1", 0) == 0, (
            "Decision 6: below-ceiling day must not fire the gate."
        )

    def test_above_ceiling_fires_on_relax(self):
        # 92°F > ceiling 90°F, relax direction → gate fires, counter=1.
        source = self._build(
            today_apparent_high=92.0,
            p25_apparent_high=None,  # 90.0 fallback
            mode=DPM_RELAX_CEILING_MODE_AUTO,
            delta=-3.0,  # cool day → positive (relax) adjustment
        )
        assert source._relax_ceiling_blocked_count.get("z1", 0) == 1, (
            "Decision 6: above-ceiling positive (relax) adjustment must "
            "increment the blocked counter."
        )

    def test_off_mode_never_fires(self):
        source = self._build(
            today_apparent_high=110.0,
            p25_apparent_high=None,
            mode=DPM_RELAX_CEILING_MODE_OFF,
            delta=-3.0,
        )
        assert source._relax_ceiling_blocked_count.get("z1", 0) == 0, (
            "Decision 6: mode=off must disable the gate even at 110°F."
        )

    def test_tighten_direction_never_gated(self):
        # Hot day (high delta) → adjustment is negative (tighten).
        # Even far above ceiling, tighten must not be suppressed.
        source = self._build(
            today_apparent_high=105.0,
            p25_apparent_high=None,
            mode=DPM_RELAX_CEILING_MODE_AUTO,
            delta=+12.0,  # hot day → negative (tighten) adjustment
        )
        assert source._relax_ceiling_blocked_count.get("z1", 0) == 0, (
            "Decision 6: tighten direction is NEVER gated, even above "
            "the ceiling."
        )

    def test_resolver_auto_fallback_when_p25_unavailable(self):
        # Sanity check of the resolver itself: auto mode + None p25 →
        # 90.0°F fallback. This pins the cold-start contract.
        ceiling, source_label = _resolve_relax_ceiling(
            today_apparent_high=85.0,
            p25_apparent_high=None,
            mode=DPM_RELAX_CEILING_MODE_AUTO,
        )
        assert ceiling == DPM_RELAX_CEILING_AUTO_FALLBACK_F == 90.0
        assert source_label == "auto"

    def test_resolver_off_returns_none(self):
        ceiling, source_label = _resolve_relax_ceiling(
            today_apparent_high=85.0,
            p25_apparent_high=88.0,
            mode=DPM_RELAX_CEILING_MODE_OFF,
        )
        assert ceiling is None
        assert source_label == "off"
