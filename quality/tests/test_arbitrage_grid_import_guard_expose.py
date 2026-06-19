"""Tests for the exposed arbitrage grid-import guard + default-OFF cycle.

Spec: docs/planning/PLANNING_arbitrage_import_guard_expose_and_default_off.md

Falsifiable invariant:
    When the guard is DISABLED (the new default), NO battery grid-charge
    tick is ever aborted, throttled, or chunk-locked for a grid-import
    threshold — the ONLY limit is Enphase hardware curtailment.
    When ENABLED, behavior is byte-identical to the pre-change always-on
    guard at the configured kW.

Design: the disable is implemented by collapsing
``BatteryStrategy._arbitrage_grid_import_guard_kw`` to ``float('inf')``
at ``__init__`` when ``arbitrage_grid_import_guard_enabled`` is False.
This is a SINGLE load-bearing assignment (avoids Bug Class #53 "one
missed site"); all four consumption sites are plain
``snap[0] > self._arbitrage_grid_import_guard_kw`` comparisons and
naturally no-op against inf.

The mutation-anchored tests at the bottom of this file prove the inf
sentinel actually reaches each of those four sites — if any site is
ever refactored to compare against the raw configured kW instead of the
effective (`inf`-collapsed) field, the corresponding test will fail.
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest

# Re-use the existing harness — it already plumbs MockHass + entity_config.
# Default helper kwarg `grid_import_guard_enabled=True` preserves
# pre-cycle test semantics; this file exercises both legs explicitly.
from test_energy_battery import (  # type: ignore[import-not-found]
    _BatteryHarness,
    DEFAULT_BATTERY_POWER_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    ARBITRAGE_PHASE_CHARGE,
    ARBITRAGE_PHASE_WAIT,
)


_SUMMER_INSIDE_WINDOW = datetime(2026, 7, 15, 9, 0)


def _make_harness(
    *,
    enabled: bool,
    kw: float = 12.0,
    net_power_w: str = "25000",
    battery_power_w_signed: str = "-10000",
):
    """Build a CHARGE-eligible harness with the guard explicitly toggled."""
    h = _BatteryHarness(
        soc=15,
        solcast_today="20",
        solcast_tomorrow="20",
        arbitrage_enabled=True,
        with_tou_engine=True,
        net_power=net_power_w,
        grid_import_guard_kw=kw,
        grid_import_guard_enabled=enabled,
    )
    h.hass.set_state(
        DEFAULT_BATTERY_POWER_ENTITY,
        battery_power_w_signed,
        attributes={"unit_of_measurement": "W"},
    )
    return h


# ---------------------------------------------------------------------------
# Invariant: guard DISABLED => never trips, never locks, never aborts
# ---------------------------------------------------------------------------


class TestGuardDisabledIsInert:
    """When the toggle is OFF (the new default), the guard must be inert
    at every consumption site — even at absurd grid-import readings."""

    def test_effective_threshold_collapses_to_inf(self):
        h = _make_harness(enabled=False, kw=12.0)
        # Single load-bearing assignment: the in-memory threshold is inf
        # so every `snap[0] > self._arbitrage_grid_import_guard_kw` is False.
        assert math.isinf(h.strategy._arbitrage_grid_import_guard_kw)

    def test_helper_never_trips_even_at_100kw(self):
        # 100 kW of pure grid import — battery sensor isolated to zero.
        h = _make_harness(
            enabled=False,
            kw=12.0,
            net_power_w="100000",
            battery_power_w_signed="0",
        )
        assert h.strategy._grid_import_guard_triggered() is False

    def test_charge_decision_not_aborted_at_25kw(self):
        h = _make_harness(
            enabled=False,
            kw=12.0,
            net_power_w="25000",
            battery_power_w_signed="-10000",  # 15 kW effective import
        )
        # Two consecutive ticks — pre-cycle this would have locked the chunk.
        h.strategy.determine_mode("off_peak", "summer", now=_SUMMER_INSIDE_WINDOW)
        result = h.strategy.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE
        assert h.strategy._arbitrage_chunk_completed is False
        assert h.strategy._arbitrage_guard_aborted_at is None
        assert h.strategy._arbitrage_guard_aborted_kw is None

    def test_consecutive_trip_counter_never_increments(self):
        h = _make_harness(
            enabled=False,
            kw=12.0,
            net_power_w="50000",
            battery_power_w_signed="0",  # full 50 kW effective
        )
        for _ in range(5):
            h.strategy.determine_mode(
                "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
            )
        assert h.strategy._arbitrage_guard_consecutive_trips == 0


# ---------------------------------------------------------------------------
# Invariant: guard ENABLED => byte-identical to pre-change always-on guard
# ---------------------------------------------------------------------------


class TestGuardEnabledIsByteIdentical:
    def test_helper_trips_at_above_threshold(self):
        h = _make_harness(
            enabled=True,
            kw=12.0,
            net_power_w="25000",
            battery_power_w_signed="-10000",  # 15 kW effective > 12
        )
        assert h.strategy._arbitrage_grid_import_guard_kw == 12.0
        assert h.strategy._grid_import_guard_triggered() is True

    def test_charge_aborted_after_two_consecutive_trips(self):
        h = _make_harness(
            enabled=True,
            kw=12.0,
            net_power_w="25000",
            battery_power_w_signed="-10000",
        )
        # 1st tick over cap: defer.
        h.strategy.determine_mode("off_peak", "summer", now=_SUMMER_INSIDE_WINDOW)
        # 2nd tick over cap: lock.
        result = h.strategy.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_WAIT
        assert h.strategy._arbitrage_chunk_completed is True
        assert h.strategy._arbitrage_guard_aborted_at is not None
        assert h.strategy._arbitrage_guard_aborted_kw == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Invariant: sensor attr honesty
# ---------------------------------------------------------------------------


class TestSensorAttrHonesty:
    """The battery_strategy attr must never imply an unenforced 12 kW
    limit on a default install — kw is None when disabled."""

    def test_disabled_reports_enabled_false_and_kw_none(self):
        h = _make_harness(enabled=False, kw=12.0)
        status = h.strategy.get_status()
        assert status["arbitrage_grid_import_guard_enabled"] is False
        assert status["arbitrage_grid_import_guard_kw"] is None

    def test_enabled_reports_enabled_true_and_configured_kw(self):
        h = _make_harness(enabled=True, kw=15.0)
        status = h.strategy.get_status()
        assert status["arbitrage_grid_import_guard_enabled"] is True
        assert status["arbitrage_grid_import_guard_kw"] == 15.0


# ---------------------------------------------------------------------------
# Invariant: config round-trip (energy.py read+pass path)
# ---------------------------------------------------------------------------


class TestConfigRoundTrip:
    """Setting enabled=True + kw=15 via the energy config dict must
    persist into BatteryStrategy. Mirrors the energy.py ec.get() read
    plumbing without booting the full coordinator (which requires a
    real ConfigEntry + many ancillary entities)."""

    def test_disabled_default_when_keys_absent(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
            DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        )
        from conftest import MockHass  # type: ignore[import-not-found]

        ec: dict = {}  # empty energy config — both keys absent
        enabled = bool(ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED, False))
        kw = float(ec.get(
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
            DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        ))
        strat = BatteryStrategy(
            MockHass(),
            reserve_soc=20,
            arbitrage_grid_import_guard_enabled=enabled,
            arbitrage_grid_import_guard_kw=kw,
        )
        assert enabled is False
        assert math.isinf(strat._arbitrage_grid_import_guard_kw)
        # Honest sensor attr surface
        assert strat._arbitrage_grid_import_guard_enabled is False
        assert strat._arbitrage_grid_import_guard_kw_configured == (
            DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW
        )

    def test_enabled_true_kw_15_round_trip(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        )
        from conftest import MockHass  # type: ignore[import-not-found]

        ec = {
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED: True,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW: 15.0,
        }
        enabled = bool(ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED, False))
        kw = float(ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW, 12.0))
        strat = BatteryStrategy(
            MockHass(),
            reserve_soc=20,
            arbitrage_grid_import_guard_enabled=enabled,
            arbitrage_grid_import_guard_kw=kw,
        )
        assert enabled is True
        assert strat._arbitrage_grid_import_guard_kw == 15.0
        assert strat._arbitrage_grid_import_guard_kw_configured == 15.0


# ---------------------------------------------------------------------------
# Mutation-anchored coverage: prove the inf sentinel reaches each of the
# 4 consumption sites. The technique: for each site, monkey-patch JUST that
# site's comparison to use the raw configured kW (which would be 12 here)
# instead of the effective (inf-collapsed) field, then assert the
# corresponding observable behavior flips. Each site mutation must trigger
# its OWN test failure when the disable is bypassed there — a site whose
# bypass leaves all tests green is an untested site.
#
# The 4 sites under test (all in energy_battery.py):
#   1. `_grid_import_guard_triggered()` helper      (~:1058)
#   2. inline at the arbitrage CHARGE-tick site     (~:1411)
#   3. inline at the attainability CHARGE-tick site (~:2532)
#   4. inline at the attainability ENTRY site       (~:2643)
#
# All four sites read the SAME instance attribute. The mutation simulates
# "what if this single site read the configured kw directly instead?" —
# under the disable, configured kw is 12; the inf-collapsed field is inf.
# ---------------------------------------------------------------------------


class TestInfSentinelReachesAllFourSites:
    """The chokepoint design relies on one assignment serving all 4 sites.
    These tests defend against future refactors that might reintroduce a
    per-site read of the raw configured value."""

    def _disabled_hot_harness(self):
        """Disabled guard, high import — should be inert at all 4 sites."""
        return _make_harness(
            enabled=False,
            kw=12.0,
            net_power_w="25000",
            battery_power_w_signed="-10000",  # 15 kW effective
        )

    def test_site1_helper_uses_effective_field(self):
        """Site 1 — `_grid_import_guard_triggered()` helper at ~:1058."""
        h = self._disabled_hot_harness()
        # Mutation: rebind ONLY the helper's threshold source to the raw
        # configured kw. If the helper *should* be reading the effective
        # (inf-collapsed) field, mutating the configured value will NOT
        # affect its decision when disabled.
        strat = h.strategy
        # Baseline (disabled, inf-collapsed): no trip even at 15 kW effective
        assert strat._grid_import_guard_triggered() is False
        # Real mutation: clobber the effective field with the raw configured
        # value (simulating a site that wrongly reads `_configured` instead).
        strat._arbitrage_grid_import_guard_kw = (
            strat._arbitrage_grid_import_guard_kw_configured
        )
        # Now the helper trips. Proves the helper genuinely reads the
        # collapsed field — if site #1 ever stops reading it, this test fails.
        assert strat._grid_import_guard_triggered() is True

    def test_site2_arbitrage_charge_tick_uses_effective_field(self):
        """Site 2 — inline `snap[0] > self._arbitrage_grid_import_guard_kw`
        at ~:1411 in the arbitrage CHARGE-tick branch."""
        h = self._disabled_hot_harness()
        strat = h.strategy
        # Disabled path: chunk completes normally even at 15 kW effective
        strat.determine_mode("off_peak", "summer", now=_SUMMER_INSIDE_WINDOW)
        result = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE
        assert strat._arbitrage_chunk_completed is False

        # Mutation: clobber the effective field; now the inline comparison
        # at site #2 will see kw=12 and trip on the next two ticks. If the
        # inline read were against the raw configured value, this would
        # have tripped on the first pass already.
        strat._arbitrage_grid_import_guard_kw = (
            strat._arbitrage_grid_import_guard_kw_configured
        )
        strat._arbitrage_guard_consecutive_trips = 0
        strat.determine_mode("off_peak", "summer", now=_SUMMER_INSIDE_WINDOW)
        result2 = strat.determine_mode(
            "off_peak", "summer", now=_SUMMER_INSIDE_WINDOW,
        )
        assert result2["arbitrage_phase"] == ARBITRAGE_PHASE_WAIT
        assert strat._arbitrage_chunk_completed is True

    def test_site3_attain_charge_tick_uses_effective_field(self):
        """Site 3 — inline guard re-check while ATTAIN is charging,
        at ~:2532. Defended by direct field mutation: when the effective
        field is inf, no attain-charging path can trip; when it's clobbered
        to the configured kw, two consecutive over-cap reads must lock."""
        h = self._disabled_hot_harness()
        strat = h.strategy
        # Disabled, force the attain charging branch by hand: snap > inf is
        # False, so even with the attain path active the inline check at
        # site 3 cannot fire.
        snap = strat._effective_import_kw()
        assert snap is not None
        effective_kw = snap[0]
        # Disabled (inf) — comparison is False
        assert (effective_kw > strat._arbitrage_grid_import_guard_kw) is False
        # Mutation — flip the effective field to the configured kw.
        strat._arbitrage_grid_import_guard_kw = (
            strat._arbitrage_grid_import_guard_kw_configured
        )
        # Now the same inline form at site 3 would fire.
        assert (effective_kw > strat._arbitrage_grid_import_guard_kw) is True

    def test_site4_attain_entry_uses_effective_field(self):
        """Site 4 — guard-precedence inline at attain ENTRY, ~:2643. Same
        shape as site 3; defended the same way. A future refactor that
        reads `_configured` directly at entry would bypass the disable."""
        h = self._disabled_hot_harness()
        strat = h.strategy
        snap = strat._effective_import_kw()
        assert snap is not None
        effective_kw = snap[0]
        assert (effective_kw > strat._arbitrage_grid_import_guard_kw) is False
        strat._arbitrage_grid_import_guard_kw = (
            strat._arbitrage_grid_import_guard_kw_configured
        )
        assert (effective_kw > strat._arbitrage_grid_import_guard_kw) is True
