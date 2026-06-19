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
    kw: float | None = 12.0,
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
    real ConfigEntry + many ancillary entities).

    v5.5.x cycle design (c): NO silent finite default for the kW. When
    both keys are absent (the default install) the read path passes
    kw=None, and BatteryStrategy keeps the configured surface as None
    while collapsing the effective threshold to inf.
    """

    def test_disabled_default_when_keys_absent(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        )
        from conftest import MockHass  # type: ignore[import-not-found]

        ec: dict = {}  # empty energy config — both keys absent
        enabled = bool(ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED, False))
        # v5.5.x (c): NO default — pass None when absent. Mirrors the
        # production energy.py read path.
        raw = ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW)
        kw = None if raw is None else float(raw)
        strat = BatteryStrategy(
            MockHass(),
            reserve_soc=20,
            arbitrage_grid_import_guard_enabled=enabled,
            arbitrage_grid_import_guard_kw=kw,
        )
        assert enabled is False
        assert math.isinf(strat._arbitrage_grid_import_guard_kw)
        # Honest sensor attr surface — no silent 12 kW default
        assert strat._arbitrage_grid_import_guard_enabled is False
        assert strat._arbitrage_grid_import_guard_kw_configured is None
        # Sensor attr round-trip
        status = strat.get_status()
        assert status["arbitrage_grid_import_guard_enabled"] is False
        assert status["arbitrage_grid_import_guard_kw"] is None

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
        raw = ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW)
        kw = None if raw is None else float(raw)
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
# v5.5.x cycle (c): cross-field validation + runtime defence
# ---------------------------------------------------------------------------


class TestConfigFlowRequiresKwWhenEnabled:
    """Config-flow validation: enabling the toggle with a blank/missing kW
    must be REJECTED by the energy options step — the form is re-shown
    (errors populated, config NOT written).

    Reuses the existing HA-stub harness from
    `test_v4743_no_eager_migration` which already loads config_flow
    against mock homeassistant modules. The harness restores sys.modules
    after loading, so to invoke the real step body we have to re-pin the
    HA stubs around the call (mirrors the `_call_build_schema` pattern
    in that file).
    """

    def _make_flow(self):
        from test_v4743_no_eager_migration import (  # type: ignore[import-not-found]
            _OptionsFlow,
        )
        from unittest.mock import MagicMock

        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        flow = _OptionsFlow.__new__(_OptionsFlow)
        flow._config_entry = entry
        flow._selected_zone_entry_id = None
        flow._pending_delete_rule_id = None
        flow.hass = MagicMock()
        flow.hass.data = {}
        return flow

    async def _invoke_step(self, flow, user_input):
        """Pin HA stubs around the call so the step's lazy `from
        homeassistant.data_entry_flow import section` resolves."""
        import sys
        import types as _types

        ha_def = _types.ModuleType("homeassistant.data_entry_flow")
        ha_def.section = lambda schema, options=None: schema
        ha_parent = _types.ModuleType("homeassistant")
        ha_parent.data_entry_flow = ha_def

        saved = {
            "homeassistant": sys.modules.get("homeassistant"),
            "homeassistant.data_entry_flow": sys.modules.get(
                "homeassistant.data_entry_flow"
            ),
        }
        sys.modules["homeassistant"] = ha_parent
        sys.modules["homeassistant.data_entry_flow"] = ha_def
        try:
            return await flow.async_step_coordinator_energy(user_input=user_input)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    @pytest.mark.asyncio
    async def test_enabled_without_kw_is_rejected(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        )

        flow = self._make_flow()
        result = await self._invoke_step(
            flow,
            user_input={
                CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED: True,
                # NO kw — operator left it blank.
            },
        )

        # FakeOptionsFlow.async_show_form (from harness) returns
        # {"type": "form", **kw}, so the result carries the errors dict.
        assert result["type"] == "form"
        errors = result.get("errors") or {}
        assert errors, "errors dict must be populated"
        assert (
            errors.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW)
            == "guard_kw_required_when_enabled"
        )
        # `base` summary also present (mirrors envoy-validation convention).
        assert errors.get("base") == "guard_kw_required_when_enabled"

    @pytest.mark.asyncio
    async def test_enabled_with_kw_15_is_accepted(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        )

        flow = self._make_flow()
        result = await self._invoke_step(
            flow,
            user_input={
                CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED: True,
                CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW: 15.0,
            },
        )

        # Accepted path: FakeOptionsFlow.async_create_entry returns
        # {"type": "create_entry", **kw} — config is written, no form re-show.
        assert result["type"] == "create_entry"
        data = result.get("data", {})
        assert data[CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED] is True
        assert data[CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW] == 15.0


class TestRuntimeDefenceNonPositiveOrNonFiniteKw:
    """FIX 2: a hand-edited config with `enabled=True` and a kW that is
    None, ≤0, NaN, or inf MUST be treated as DISABLED (effective inf +
    configured surface None). Without this, kw=0 would trip the guard
    on every tick and brick arbitrage grid-charge."""

    @pytest.mark.parametrize("bad_kw", [0, 0.0, -5, -5.0, float("nan"), float("inf")])
    def test_enabled_with_bad_kw_collapses_to_inf(self, bad_kw):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        from conftest import MockHass  # type: ignore[import-not-found]

        strat = BatteryStrategy(
            MockHass(),
            reserve_soc=20,
            arbitrage_grid_import_guard_enabled=True,
            arbitrage_grid_import_guard_kw=bad_kw,
        )
        # Effective threshold collapses to inf (guard inert).
        assert math.isinf(strat._arbitrage_grid_import_guard_kw)
        # Configured surface reports None — sensor never implies a
        # finite limit that isn't enforced.
        assert strat._arbitrage_grid_import_guard_kw_configured is None
        # Sensor attr round-trip — kw is null on the sensor.
        status = strat.get_status()
        assert status["arbitrage_grid_import_guard_enabled"] is True
        assert status["arbitrage_grid_import_guard_kw"] is None


class TestRuntimeDefenceEnabledWithNoneKw:
    """Belt-and-suspenders: a hand-edited config that sets enabled=True
    without a kW (bypassing config-flow validation) MUST still be inert —
    treated as DISABLED (effective inf), never silently re-imposing any
    default threshold."""

    def test_enabled_with_none_kw_collapses_to_inf(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        from conftest import MockHass  # type: ignore[import-not-found]

        strat = BatteryStrategy(
            MockHass(),
            reserve_soc=20,
            arbitrage_grid_import_guard_enabled=True,
            arbitrage_grid_import_guard_kw=None,
        )
        assert math.isinf(strat._arbitrage_grid_import_guard_kw)
        assert strat._arbitrage_grid_import_guard_kw_configured is None

    def test_enabled_with_none_kw_helper_never_trips_at_100kw(self):
        h = _make_harness(
            enabled=True,
            kw=None,  # type: ignore[arg-type]
            net_power_w="100000",
            battery_power_w_signed="0",
        )
        # Effective threshold is inf — helper cannot trip.
        assert math.isinf(h.strategy._arbitrage_grid_import_guard_kw)
        assert h.strategy._grid_import_guard_triggered() is False


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
        """Site 3 — inline guard re-check while ATTAIN is charging, at
        ~:2564 inside ``_run_attain_branch``. Drive the REAL method:
        construct a CHARGING-state harness with the guard DISABLED,
        invoke ``_run_attain_branch`` end-to-end, and observe the
        production trip counter / chunk-completed flag — NOT a
        comparison evaluated in the test body."""
        h = self._disabled_hot_harness()
        strat = h.strategy
        # Stub upstream gates the attain CHARGING route consults so
        # the guard re-check at site 3 is the only thing that can
        # decide WAIT vs CHARGE on this tick.
        strat._maybe_run_reboot_recovery = (
            lambda *a, **kw: None  # type: ignore[assignment]
        )
        strat._attain_target_boundary = (
            lambda now, period: (now, "peak", 60)  # type: ignore[assignment]
        )
        strat._midpeak_rate_lt_peak = lambda now: True  # type: ignore[assignment]
        strat._attain_target_period_at_or_above_current = (
            lambda *a, **kw: False  # type: ignore[assignment]
        )
        strat._observed_net_charge_rate_per_hour = (
            lambda: 5.0  # type: ignore[assignment]
        )
        strat._expected_solar_surplus_pct = (
            lambda now, mins: 0.0  # type: ignore[assignment]
        )
        # charge_from_grid observed ON so M5 drift policy stays quiet.
        strat._get_state_bool = lambda eid: True  # type: ignore[assignment]
        # Force the CHARGING route + reset counters / completed flag.
        strat._attain_state = "charging"
        strat._arbitrage_chunk_completed = False
        strat._arbitrage_guard_consecutive_trips = 0
        strat._attain_charging_ticks = 0
        strat._attain_cfg_observed_on = False

        kwargs = dict(
            soc=15.0,
            now=_SUMMER_INSIDE_WINDOW,
            tou_period="off_peak",
            target_day_class="poor",
            tomorrow_class="poor",
            current_mode="self_consumption",
            season="summer",
            effective_reserve=20,
            hold_depth="allow_discharge",
        )

        # Baseline — guard DISABLED (inf). Two ticks at 15 kW effective:
        # the production inline at site 3 evaluates False against inf,
        # so the trip counter MUST stay at 0 and the chunk MUST stay open.
        strat._run_attain_branch(**kwargs)
        strat._run_attain_branch(**kwargs)
        assert strat._arbitrage_guard_consecutive_trips == 0
        assert strat._arbitrage_chunk_completed is False
        assert strat._arbitrage_guard_aborted_at is None

        # Mutation — clobber the effective field with the raw configured
        # kw (simulates a refactor where site 3 reads `_configured`).
        # Reset trip-counter + completed flag, re-drive the SAME method.
        # The production site MUST now advance the counter and lock the chunk.
        strat._arbitrage_grid_import_guard_kw = (
            strat._arbitrage_grid_import_guard_kw_configured
        )
        strat._arbitrage_chunk_completed = False
        strat._arbitrage_guard_consecutive_trips = 0
        strat._arbitrage_guard_aborted_at = None
        strat._arbitrage_guard_aborted_kw = None
        strat._attain_state = "charging"
        strat._attain_charging_ticks = 0
        strat._attain_cfg_observed_on = False
        strat._run_attain_branch(**kwargs)
        strat._run_attain_branch(**kwargs)
        # Production site 3 fired: counter advanced past lock threshold
        # AND chunk was locked AND aborted_at was stamped.
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK,
        )
        assert (
            strat._arbitrage_guard_consecutive_trips
            >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK
        )
        assert strat._arbitrage_chunk_completed is True
        assert strat._arbitrage_guard_aborted_at is not None
        assert strat._arbitrage_guard_aborted_kw == pytest.approx(15.0)

    def test_site4_attain_entry_uses_effective_field(self):
        """Site 4 — guard-precedence inline at attain ENTRY, at ~:2675
        inside ``_run_attain_branch``. Drive the REAL method with state
        forced to ``inactive`` so the entry-precedence path executes,
        and assert against the production trip counter."""
        h = self._disabled_hot_harness()
        strat = h.strategy
        # Stub upstream so the ENTRY branch is reached and the guard
        # check at site 4 is the only decisive logic on this tick.
        strat._maybe_run_reboot_recovery = (
            lambda *a, **kw: None  # type: ignore[assignment]
        )
        # _should_attain_peak_buffer returns (should, projected, rate, mins).
        strat._should_attain_peak_buffer = (
            lambda soc, now, tou_period="off_peak": (True, 30.0, 5.0, 60)
        )  # type: ignore[assignment]
        # Drive the ENTRY route.
        strat._attain_state = "inactive"
        strat._arbitrage_chunk_completed = False
        strat._arbitrage_guard_consecutive_trips = 0

        kwargs = dict(
            soc=15.0,
            now=_SUMMER_INSIDE_WINDOW,
            tou_period="off_peak",
            target_day_class="poor",
            tomorrow_class="poor",
            current_mode="self_consumption",
            season="summer",
            effective_reserve=20,
            hold_depth="allow_discharge",
        )

        # Baseline — guard DISABLED (inf). Two ENTRY attempts must NOT
        # advance the trip counter (snap > inf is False at site 4) and
        # MUST instead transition to attain charging.
        strat._run_attain_branch(**kwargs)
        # After entry, state flipped to charging; reset it back to
        # exercise site 4 again on tick 2.
        strat._attain_state = "inactive"
        strat._run_attain_branch(**kwargs)
        assert strat._arbitrage_guard_consecutive_trips == 0
        assert strat._arbitrage_chunk_completed is False
        assert strat._arbitrage_guard_aborted_at is None

        # Mutation — clobber the effective field, re-drive the SAME
        # method. Site 4 must now advance the counter to lock and abort.
        strat._arbitrage_grid_import_guard_kw = (
            strat._arbitrage_grid_import_guard_kw_configured
        )
        strat._attain_state = "inactive"
        strat._arbitrage_chunk_completed = False
        strat._arbitrage_guard_consecutive_trips = 0
        strat._arbitrage_guard_aborted_at = None
        strat._arbitrage_guard_aborted_kw = None
        strat._run_attain_branch(**kwargs)
        strat._attain_state = "inactive"
        strat._run_attain_branch(**kwargs)
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK,
        )
        assert (
            strat._arbitrage_guard_consecutive_trips
            >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK
        )
        assert strat._arbitrage_chunk_completed is True
        assert strat._arbitrage_guard_aborted_at is not None
        assert strat._arbitrage_guard_aborted_kw == pytest.approx(15.0)
