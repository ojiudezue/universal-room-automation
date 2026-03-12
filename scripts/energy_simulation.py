#!/usr/bin/env python3
"""
URA Energy Management Simulation — 365-Day Monte Carlo Optimization

Simulates a full year of home energy management at hourly resolution using
PEC TOU rates and real solar production distributions from the URA project.
Runs Monte Carlo optimization to find optimal battery drain targets, arbitrage
thresholds, and EVSE parameters.

Usage:
    python scripts/energy_simulation.py
    python scripts/energy_simulation.py --trials 5000 --seed 123 --verbose
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# Attempt numpy for performance, fall back to stdlib random
try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    import random

    HAS_NUMPY = False

# ---------------------------------------------------------------------------
# Import URA constants — use importlib to load the file directly, bypassing
# __init__.py which depends on homeassistant (not available standalone).
# ---------------------------------------------------------------------------
import importlib.util
import os
import types

_project_root = os.path.join(os.path.dirname(__file__), "..")
_const_path = os.path.join(
    _project_root,
    "custom_components", "universal_room_automation",
    "domain_coordinators", "energy_const.py",
)

# Stub out the annotations import target (energy_const only needs `Final` from typing)
_spec = importlib.util.spec_from_file_location("energy_const", _const_path)
_energy_const = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_energy_const)

PEC_TOU_RATES = _energy_const.PEC_TOU_RATES
PEC_FIXED_CHARGES = _energy_const.PEC_FIXED_CHARGES
SOLAR_MONTHLY_THRESHOLDS = _energy_const.SOLAR_MONTHLY_THRESHOLDS
DEFAULT_RESERVE_SOC = _energy_const.DEFAULT_RESERVE_SOC
DEFAULT_OFFPEAK_DRAIN_EXCELLENT = _energy_const.DEFAULT_OFFPEAK_DRAIN_EXCELLENT
DEFAULT_OFFPEAK_DRAIN_GOOD = _energy_const.DEFAULT_OFFPEAK_DRAIN_GOOD
DEFAULT_OFFPEAK_DRAIN_MODERATE = _energy_const.DEFAULT_OFFPEAK_DRAIN_MODERATE
DEFAULT_OFFPEAK_DRAIN_POOR = _energy_const.DEFAULT_OFFPEAK_DRAIN_POOR
DEFAULT_ARBITRAGE_SOC_TRIGGER = _energy_const.DEFAULT_ARBITRAGE_SOC_TRIGGER
DEFAULT_ARBITRAGE_SOC_TARGET = _energy_const.DEFAULT_ARBITRAGE_SOC_TARGET
DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD = _energy_const.DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD
DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD = _energy_const.DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATTERY_CAPACITY_KWH = 40.0
BATTERY_EFFICIENCY = 0.95  # round-trip
BATTERY_MAX_CHARGE_KW = 10.0
BATTERY_MAX_DISCHARGE_KW = 10.0
RESERVE_SOC_PCT = DEFAULT_RESERVE_SOC  # 20%

EV_CHARGE_POWER_KW = 11.5
BASE_DAILY_CONSUMPTION_KWH = 30.0

HOURS_PER_DAY = 24
DAYS_PER_YEAR = 365

# Season lookup built from PEC_TOU_RATES
MONTH_TO_SEASON: dict[int, str] = {}
for _season_name, _season_data in PEC_TOU_RATES.items():
    for _m in _season_data["months"]:
        MONTH_TO_SEASON[_m] = _season_name


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SimParams:
    """Tunable optimization parameters."""

    drain_target_excellent: float = float(DEFAULT_OFFPEAK_DRAIN_EXCELLENT)
    drain_target_good: float = float(DEFAULT_OFFPEAK_DRAIN_GOOD)
    drain_target_moderate: float = float(DEFAULT_OFFPEAK_DRAIN_MODERATE)
    drain_target_poor: float = float(DEFAULT_OFFPEAK_DRAIN_POOR)
    arbitrage_soc_trigger: float = float(DEFAULT_ARBITRAGE_SOC_TRIGGER)
    arbitrage_soc_target: float = float(DEFAULT_ARBITRAGE_SOC_TARGET)
    excess_solar_soc_threshold: float = float(DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD)
    excess_solar_kwh_threshold: float = float(DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD)


@dataclass
class DailyResult:
    """Results for a single simulated day."""

    date_index: int
    month: int
    season: str
    solar_kwh: float
    consumption_kwh: float
    ev_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    cost: float


@dataclass
class SimResult:
    """Aggregate simulation result."""

    params: SimParams
    annual_cost: float
    monthly_costs: list[float] = field(default_factory=lambda: [0.0] * 12)
    daily_results: list[DailyResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Random number helpers (numpy or stdlib)
# ---------------------------------------------------------------------------


def set_seed(seed: int) -> None:
    if HAS_NUMPY:
        np.random.seed(seed)
    else:
        random.seed(seed)


def rand_uniform(low: float, high: float) -> float:
    if HAS_NUMPY:
        return float(np.random.uniform(low, high))
    return random.uniform(low, high)


def rand_normal(mean: float, std: float) -> float:
    if HAS_NUMPY:
        return float(np.random.normal(mean, std))
    return random.gauss(mean, std)


def rand_int(low: int, high: int) -> int:
    """Return random int in [low, high] inclusive."""
    if HAS_NUMPY:
        return int(np.random.randint(low, high + 1))
    return random.randint(low, high)


def rand_poisson(lam: float) -> int:
    if HAS_NUMPY:
        return int(np.random.poisson(lam))
    # Simple Knuth algorithm for small lambda
    l_val = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p < l_val:
            break
    return k - 1


# ---------------------------------------------------------------------------
# TOU rate lookup
# ---------------------------------------------------------------------------


def get_tou_info(month: int, hour: int) -> tuple[str, float, float]:
    """Return (period_name, import_rate, export_rate) for a given month and hour."""
    season = MONTH_TO_SEASON[month]
    season_data = PEC_TOU_RATES[season]
    for period_name, period_data in season_data["periods"].items():
        for start, end in period_data["hours"]:
            if start <= hour < end:
                return period_name, period_data["import_rate"], period_data["export_rate"]
    # Should not reach here if TOU tables are complete
    raise ValueError(f"No TOU period found for month={month}, hour={hour}")


def get_season(month: int) -> str:
    """Return season name for a given month."""
    return MONTH_TO_SEASON[month]


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------


def day_of_year_to_month(day: int) -> int:
    """Convert 0-based day-of-year to 1-based month (non-leap year)."""
    month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    cumulative = 0
    for m_idx, days_in_month in enumerate(month_days):
        cumulative += days_in_month
        if day < cumulative:
            return m_idx + 1
    return 12


def generate_solar_hourly(day: int, month: int) -> list[float]:
    """Generate 24 hourly solar production values (kWh) for a given day.

    Uses SOLAR_MONTHLY_THRESHOLDS to derive a daily total from a distribution
    centered on the P50 value, then distributes across hours using a bell curve
    peaking between 9am and 5pm.
    """
    p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS[month]
    # Daily total: normal distribution around P50, std ~(P75 - P25)/2
    std = (p75 - p25) / 2.0
    daily_total = max(0.0, rand_normal(p50, std * 0.6))

    # Distribute across hours with bell curve centered at solar noon (1pm)
    hourly = [0.0] * 24
    solar_center = 13.0  # 1 PM
    solar_width = 3.5  # hours (std dev of bell curve)
    # Generate raw bell weights for hours 5-20 (sunrise to sunset roughly)
    raw_weights = []
    for h in range(24):
        if 5 <= h <= 20:
            w = math.exp(-0.5 * ((h - solar_center) / solar_width) ** 2)
            # Add small noise
            w *= max(0.1, 1.0 + rand_normal(0, 0.05))
        else:
            w = 0.0
        raw_weights.append(w)

    total_weight = sum(raw_weights)
    if total_weight > 0:
        for h in range(24):
            hourly[h] = daily_total * (raw_weights[h] / total_weight)

    return hourly


def generate_temperature(day: int) -> list[float]:
    """Generate 24 hourly temperatures (F) for Raleigh NC.

    Seasonal sine curve: winter low ~35F, summer high ~95F.
    Daily variation: cooler at night, warmer mid-afternoon.
    """
    # Seasonal mean: sine curve peaking at day ~196 (mid-July)
    # Range: 35 (winter low avg) to 95 (summer high avg), midpoint 65
    seasonal_mean = 65.0 + 20.0 * math.sin(2 * math.pi * (day - 80) / 365)

    hourly = []
    for h in range(24):
        # Daily variation: ~10F swing, peak at 3pm (hour 15), min at 5am (hour 5)
        daily_offset = 5.0 * math.sin(2 * math.pi * (h - 9) / 24)
        temp = seasonal_mean + daily_offset + rand_normal(0, 2.0)
        hourly.append(temp)

    return hourly


def generate_base_load_hourly() -> list[float]:
    """Generate 24 hourly base consumption values (kWh).

    Total ~30 kWh/day with realistic profile: lower at night, higher
    morning and evening.
    """
    # Hourly profile weights (relative consumption)
    profile = [
        0.6, 0.5, 0.5, 0.5, 0.5, 0.6,  # 0-5: sleeping
        0.8, 1.2, 1.3, 1.1, 1.0, 1.0,  # 6-11: morning
        1.0, 1.0, 1.1, 1.2, 1.3, 1.5,  # 12-17: afternoon
        1.6, 1.5, 1.4, 1.2, 0.9, 0.7,  # 18-23: evening
    ]
    total_profile = sum(profile)
    hourly = []
    for h in range(24):
        base = BASE_DAILY_CONSUMPTION_KWH * (profile[h] / total_profile)
        base *= max(0.5, 1.0 + rand_normal(0, 0.05))
        hourly.append(base)
    return hourly


def generate_ev_sessions(day: int) -> list[tuple[int, int]]:
    """Generate EV charging sessions for a day.

    Returns list of (start_hour, duration_hours) tuples.
    0-2 sessions per day, usually off-peak, 2-4 hours each.
    """
    n_sessions = min(rand_poisson(0.8), 2)
    sessions = []
    for _ in range(n_sessions):
        # Prefer off-peak: 80% chance of starting 22-05, 20% any time
        if rand_uniform(0, 1) < 0.8:
            start = rand_int(22, 28) % 24  # wrap around midnight
        else:
            start = rand_int(0, 23)
        duration = rand_int(2, 4)
        sessions.append((start, duration))
    return sessions


def classify_solar_day(daily_kwh: float, month: int) -> str:
    """Classify a day's solar production using monthly thresholds."""
    p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS[month]
    if daily_kwh >= p75:
        return "excellent"
    elif daily_kwh >= p50:
        return "good"
    elif daily_kwh >= p25:
        return "moderate"
    else:
        return "poor"


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------


def simulate_year(params: SimParams, verbose: bool = False) -> SimResult:
    """Run a full 365-day hourly simulation with the given parameters.

    Returns the aggregate annual result including per-month and per-day costs.
    """
    battery_soc_pct = 50.0  # start at 50%
    annual_cost = 0.0
    monthly_costs = [0.0] * 12
    daily_results: list[DailyResult] = []

    # Pre-generate tomorrow's solar for lookahead
    # We generate all 365 days of solar totals first so we can look ahead
    solar_daily_totals: list[float] = []
    solar_hourly_all: list[list[float]] = []
    for d in range(DAYS_PER_YEAR):
        month = day_of_year_to_month(d)
        hourly_solar = generate_solar_hourly(d, month)
        solar_hourly_all.append(hourly_solar)
        solar_daily_totals.append(sum(hourly_solar))

    for day in range(DAYS_PER_YEAR):
        month = day_of_year_to_month(day)
        season = get_season(month)

        solar_hourly = solar_hourly_all[day]
        solar_today = solar_daily_totals[day]
        temps = generate_temperature(day)
        base_load = generate_base_load_hourly()
        ev_sessions = generate_ev_sessions(day)

        # Tomorrow's solar forecast (for drain/arbitrage decisions)
        tomorrow = (day + 1) % DAYS_PER_YEAR
        tomorrow_month = day_of_year_to_month(tomorrow)
        tomorrow_solar = solar_daily_totals[tomorrow]
        tomorrow_class = classify_solar_day(tomorrow_solar, tomorrow_month)

        # Remaining solar forecast (decreases through the day)
        remaining_solar = solar_today

        # Build EV schedule for the day
        ev_schedule = [0.0] * 24
        for start_h, duration in ev_sessions:
            for offset in range(duration):
                h = (start_h + offset) % 24
                ev_schedule[h] = EV_CHARGE_POWER_KW

        daily_cost = 0.0
        daily_solar = 0.0
        daily_consumption = 0.0
        daily_ev = 0.0
        daily_grid_import = 0.0
        daily_grid_export = 0.0

        for hour in range(HOURS_PER_DAY):
            period, import_rate, export_rate = get_tou_info(month, hour)
            temp = temps[hour]
            solar_kw = solar_hourly[hour]

            # HVAC-driven consumption
            hvac_extra = 0.0
            if temp > 75.0:
                hvac_extra = 0.3 * (temp - 75.0) / HOURS_PER_DAY * HOURS_PER_DAY
                # Per-hour contribution: 0.3 kWh per degree above 75 per day
                # Distribute mostly during hot hours
                hvac_extra = 0.3 * (temp - 75.0) / 6.0  # spread over ~6 AC hours
            elif temp < 45.0:
                hvac_extra = 0.2 * (45.0 - temp) / 8.0  # spread over ~8 heat hours

            house_load = base_load[hour] + hvac_extra

            # Update remaining solar forecast
            remaining_solar -= solar_kw
            remaining_solar = max(0.0, remaining_solar)

            # --- EVSE logic ---
            ev_this_hour = 0.0
            if ev_schedule[hour] > 0:
                # During off-peak: always charge EV
                if period == "off_peak":
                    ev_this_hour = ev_schedule[hour]
                # During peak/mid-peak: only if excess solar conditions met
                elif (
                    battery_soc_pct >= params.excess_solar_soc_threshold
                    and remaining_solar >= params.excess_solar_kwh_threshold
                ):
                    ev_this_hour = ev_schedule[hour]

            total_consumption = house_load + ev_this_hour

            # --- Battery strategy ---
            battery_delta_kwh = 0.0  # positive = discharge, negative = charge

            # Determine drain target based on tomorrow's solar class
            drain_target = {
                "excellent": params.drain_target_excellent,
                "good": params.drain_target_good,
                "moderate": params.drain_target_moderate,
                "poor": params.drain_target_poor,
            }.get(tomorrow_class, params.drain_target_moderate)

            reserve_kwh = BATTERY_CAPACITY_KWH * (RESERVE_SOC_PCT / 100.0)
            current_kwh = BATTERY_CAPACITY_KWH * (battery_soc_pct / 100.0)
            drain_target_kwh = BATTERY_CAPACITY_KWH * (drain_target / 100.0)

            if period == "off_peak":
                if battery_soc_pct > drain_target:
                    # Discharge stored solar during cheap off-peak
                    max_discharge = min(
                        BATTERY_MAX_DISCHARGE_KW,
                        current_kwh - drain_target_kwh,
                    )
                    battery_delta_kwh = max(0.0, min(max_discharge, total_consumption))
                else:
                    # Hold — import cheap grid
                    battery_delta_kwh = 0.0

                # Arbitrage: charge from grid if tomorrow is poor and SOC low
                if (
                    tomorrow_class in ("poor",)
                    and battery_soc_pct < params.arbitrage_soc_trigger
                ):
                    target_kwh = BATTERY_CAPACITY_KWH * (
                        params.arbitrage_soc_target / 100.0
                    )
                    charge_needed = target_kwh - current_kwh
                    if charge_needed > 0:
                        charge_amount = min(
                            BATTERY_MAX_CHARGE_KW, charge_needed
                        )
                        # Charging = negative delta (energy into battery)
                        battery_delta_kwh = -charge_amount / BATTERY_EFFICIENCY

            elif period == "mid_peak":
                if season == "summer":
                    # Hold SOC in summer mid-peak (save for peak)
                    battery_delta_kwh = 0.0
                else:
                    # Shoulder/winter mid-peak: discharge to reserve
                    if current_kwh > reserve_kwh:
                        max_discharge = min(
                            BATTERY_MAX_DISCHARGE_KW,
                            current_kwh - reserve_kwh,
                        )
                        battery_delta_kwh = max(
                            0.0, min(max_discharge, total_consumption)
                        )

            elif period == "peak":
                # Always discharge during peak (summer only has peak)
                if current_kwh > reserve_kwh:
                    max_discharge = min(
                        BATTERY_MAX_DISCHARGE_KW,
                        current_kwh - reserve_kwh,
                    )
                    battery_delta_kwh = max(
                        0.0, min(max_discharge, total_consumption)
                    )

            # --- Apply battery delta to SOC ---
            if battery_delta_kwh > 0:
                # Discharging
                actual_discharge = battery_delta_kwh
                battery_soc_pct -= (actual_discharge / BATTERY_CAPACITY_KWH) * 100.0
                battery_soc_pct = max(RESERVE_SOC_PCT, battery_soc_pct)
            elif battery_delta_kwh < 0:
                # Charging (delta is negative, so abs gives charge amount)
                actual_charge = abs(battery_delta_kwh) * BATTERY_EFFICIENCY
                battery_soc_pct += (actual_charge / BATTERY_CAPACITY_KWH) * 100.0
                battery_soc_pct = min(100.0, battery_soc_pct)

            # --- Solar charges battery if excess ---
            net_load = total_consumption - battery_delta_kwh  # load after battery
            solar_surplus = solar_kw - net_load
            if solar_surplus > 0 and battery_soc_pct < 100.0:
                charge_room = BATTERY_CAPACITY_KWH * (
                    (100.0 - battery_soc_pct) / 100.0
                )
                solar_to_battery = min(
                    solar_surplus,
                    BATTERY_MAX_CHARGE_KW,
                    charge_room,
                )
                battery_soc_pct += (
                    solar_to_battery * BATTERY_EFFICIENCY / BATTERY_CAPACITY_KWH
                ) * 100.0
                battery_soc_pct = min(100.0, battery_soc_pct)
                solar_surplus -= solar_to_battery

            # --- Grid calculation ---
            net_grid = total_consumption - solar_kw - battery_delta_kwh
            if net_grid > 0:
                grid_import = net_grid
                grid_export = 0.0
            else:
                grid_import = 0.0
                grid_export = abs(net_grid)

            # Also account for arbitrage charging as grid import
            if battery_delta_kwh < 0:
                grid_import += abs(battery_delta_kwh)

            hour_cost = grid_import * (
                import_rate
                + PEC_FIXED_CHARGES["delivery_per_kwh"]
                + PEC_FIXED_CHARGES["transmission_per_kwh"]
            ) - grid_export * export_rate

            daily_cost += hour_cost
            daily_solar += solar_kw
            daily_consumption += total_consumption
            daily_ev += ev_this_hour
            daily_grid_import += grid_import
            daily_grid_export += grid_export

        # Add fixed monthly service charge (prorated daily)
        daily_cost += PEC_FIXED_CHARGES["service_availability"] / 30.0

        annual_cost += daily_cost
        monthly_costs[month - 1] += daily_cost

        daily_results.append(
            DailyResult(
                date_index=day,
                month=month,
                season=season,
                solar_kwh=daily_solar,
                consumption_kwh=daily_consumption,
                ev_kwh=daily_ev,
                grid_import_kwh=daily_grid_import,
                grid_export_kwh=daily_grid_export,
                cost=daily_cost,
            )
        )

    return SimResult(
        params=params,
        annual_cost=annual_cost,
        monthly_costs=monthly_costs,
        daily_results=daily_results,
    )


def simulate_no_strategy() -> SimResult:
    """Simulate a year with NO battery strategy (baseline).

    Battery just self-consumes solar, no TOU-aware drain/charge.
    """
    params = SimParams(
        drain_target_excellent=50.0,
        drain_target_good=50.0,
        drain_target_moderate=50.0,
        drain_target_poor=50.0,
        arbitrage_soc_trigger=0.0,  # never triggers
        arbitrage_soc_target=0.0,
        excess_solar_soc_threshold=100.0,  # never triggers
        excess_solar_kwh_threshold=999.0,
    )
    return simulate_year(params)


# ---------------------------------------------------------------------------
# Monte Carlo optimization
# ---------------------------------------------------------------------------

# Parameter ranges: (name, min, max)
PARAM_RANGES: list[tuple[str, float, float]] = [
    ("drain_target_excellent", 5.0, 30.0),
    ("drain_target_good", 10.0, 40.0),
    ("drain_target_moderate", 20.0, 60.0),
    ("drain_target_poor", 40.0, 80.0),
    ("arbitrage_soc_trigger", 15.0, 50.0),
    ("arbitrage_soc_target", 60.0, 95.0),
    ("excess_solar_soc_threshold", 85.0, 100.0),
    ("excess_solar_kwh_threshold", 2.0, 10.0),
]


def random_params() -> SimParams:
    """Generate a random set of simulation parameters within defined ranges."""
    kwargs: dict[str, float] = {}
    for name, low, high in PARAM_RANGES:
        kwargs[name] = rand_uniform(low, high)
    return SimParams(**kwargs)


def run_optimization(
    n_trials: int, seed: int, verbose: bool
) -> tuple[SimResult, SimResult, SimResult]:
    """Run Monte Carlo optimization.

    Returns (best_result, default_result, baseline_result).
    """
    set_seed(seed)

    # --- Baseline (no strategy) ---
    if verbose:
        print("Running baseline (no-strategy) simulation...")
    baseline_result = simulate_no_strategy()
    if verbose:
        print(f"  Baseline annual cost: ${baseline_result.annual_cost:,.2f}")

    # --- Default parameters ---
    set_seed(seed)  # reset seed for fair comparison
    if verbose:
        print("Running default parameters simulation...")
    default_result = simulate_year(SimParams())
    if verbose:
        print(f"  Default annual cost: ${default_result.annual_cost:,.2f}")

    # --- Monte Carlo search ---
    set_seed(seed)
    best_result: SimResult | None = None
    best_cost = float("inf")

    start_time = time.time()
    report_interval = max(1, n_trials // 10)

    for trial in range(n_trials):
        params = random_params()
        result = simulate_year(params)

        if result.annual_cost < best_cost:
            best_cost = result.annual_cost
            best_result = result

        if verbose and (trial + 1) % report_interval == 0:
            elapsed = time.time() - start_time
            rate = (trial + 1) / elapsed
            eta = (n_trials - trial - 1) / rate
            print(
                f"  Trial {trial + 1}/{n_trials} | "
                f"Best: ${best_cost:,.2f} | "
                f"Rate: {rate:.1f} trials/s | "
                f"ETA: {eta:.0f}s"
            )

    assert best_result is not None
    elapsed = time.time() - start_time
    if verbose:
        print(f"Optimization complete in {elapsed:.1f}s")

    return best_result, default_result, baseline_result


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------


def run_sensitivity(
    optimal_params: SimParams, seed: int
) -> list[tuple[str, float, float, float, float]]:
    """Vary each parameter +/- 20% from optimal and measure cost impact.

    Returns list of (param_name, optimal_value, cost_minus20, cost_optimal, cost_plus20).
    """
    # First get optimal cost
    set_seed(seed)
    optimal_cost = simulate_year(optimal_params).annual_cost

    results: list[tuple[str, float, float, float, float]] = []

    for name, low, high in PARAM_RANGES:
        optimal_val = getattr(optimal_params, name)

        # -20%
        val_minus = max(low, optimal_val * 0.8)
        params_minus = SimParams(
            **{
                n: (val_minus if n == name else getattr(optimal_params, n))
                for n, _, _ in PARAM_RANGES
            }
        )
        set_seed(seed)
        cost_minus = simulate_year(params_minus).annual_cost

        # +20%
        val_plus = min(high, optimal_val * 1.2)
        params_plus = SimParams(
            **{
                n: (val_plus if n == name else getattr(optimal_params, n))
                for n, _, _ in PARAM_RANGES
            }
        )
        set_seed(seed)
        cost_plus = simulate_year(params_plus).annual_cost

        results.append((name, optimal_val, cost_minus, optimal_cost, cost_plus))

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def print_report(
    best: SimResult,
    default: SimResult,
    baseline: SimResult,
    sensitivity: list[tuple[str, float, float, float, float]],
    n_trials: int,
    seed: int,
) -> None:
    """Print markdown-formatted optimization report."""

    print()
    print("# URA Energy Simulation Report")
    print()
    print(f"- **Trials:** {n_trials}")
    print(f"- **Seed:** {seed}")
    print(f"- **Battery:** {BATTERY_CAPACITY_KWH} kWh, {BATTERY_EFFICIENCY*100:.0f}% efficiency")
    print(f"- **Reserve SOC:** {RESERVE_SOC_PCT}%")
    print(f"- **Backend:** {'numpy' if HAS_NUMPY else 'stdlib random'}")
    print()

    # --- Section 1: Optimal parameters ---
    print("## 1. Optimal Parameters")
    print()
    print("| Parameter | Optimal | Default | Range |")
    print("|-----------|---------|---------|-------|")
    default_params = SimParams()
    for name, low, high in PARAM_RANGES:
        opt_val = getattr(best.params, name)
        def_val = getattr(default_params, name)
        unit = "%" if "threshold" not in name.split("_")[-1] or "soc" in name else ""
        if name == "excess_solar_kwh_threshold":
            unit = " kWh"
            print(f"| `{name}` | {opt_val:.1f}{unit} | {def_val:.1f}{unit} | {low:.0f}-{high:.0f} |")
        else:
            unit = "%"
            print(f"| `{name}` | {opt_val:.1f}{unit} | {def_val:.1f}{unit} | {low:.0f}-{high:.0f} |")
    print()

    # --- Section 2: Annual cost comparison ---
    print("## 2. Annual Cost Comparison")
    print()
    savings_vs_default = default.annual_cost - best.annual_cost
    savings_vs_baseline = baseline.annual_cost - best.annual_cost
    pct_vs_default = (savings_vs_default / default.annual_cost * 100) if default.annual_cost > 0 else 0
    pct_vs_baseline = (savings_vs_baseline / baseline.annual_cost * 100) if baseline.annual_cost > 0 else 0

    print("| Strategy | Annual Cost | Savings vs Optimized |")
    print("|----------|-------------|----------------------|")
    print(f"| **Optimized** | **${best.annual_cost:,.2f}** | -- |")
    print(f"| Default params | ${default.annual_cost:,.2f} | ${savings_vs_default:,.2f} ({pct_vs_default:.1f}%) |")
    print(f"| No strategy (baseline) | ${baseline.annual_cost:,.2f} | ${savings_vs_baseline:,.2f} ({pct_vs_baseline:.1f}%) |")
    print()

    # --- Section 3: Monthly breakdown ---
    print("## 3. Monthly Cost Breakdown (Optimized)")
    print()
    print("| Month | Cost | Solar (kWh) | Consumption (kWh) | Grid Import (kWh) | Grid Export (kWh) |")
    print("|-------|------|-------------|-------------------|-------------------|-------------------|")

    for m in range(12):
        month_days = [r for r in best.daily_results if r.month == m + 1]
        solar = sum(d.solar_kwh for d in month_days)
        consumption = sum(d.consumption_kwh for d in month_days)
        grid_import = sum(d.grid_import_kwh for d in month_days)
        grid_export = sum(d.grid_export_kwh for d in month_days)
        cost = best.monthly_costs[m]
        print(
            f"| {MONTH_NAMES[m]} | ${cost:,.2f} | {solar:,.0f} | {consumption:,.0f} | "
            f"{grid_import:,.0f} | {grid_export:,.0f} |"
        )

    total_solar = sum(d.solar_kwh for d in best.daily_results)
    total_consumption = sum(d.consumption_kwh for d in best.daily_results)
    total_import = sum(d.grid_import_kwh for d in best.daily_results)
    total_export = sum(d.grid_export_kwh for d in best.daily_results)
    print(
        f"| **Total** | **${best.annual_cost:,.2f}** | **{total_solar:,.0f}** | "
        f"**{total_consumption:,.0f}** | **{total_import:,.0f}** | **{total_export:,.0f}** |"
    )
    print()

    # --- Section 4: Sensitivity analysis ---
    print("## 4. Sensitivity Analysis (+/- 20% from optimal)")
    print()
    print("| Parameter | Optimal | Cost at -20% | Cost at Optimal | Cost at +20% | Impact |")
    print("|-----------|---------|-------------|-----------------|-------------|--------|")

    for name, opt_val, cost_m, cost_o, cost_p in sensitivity:
        max_impact = max(abs(cost_m - cost_o), abs(cost_p - cost_o))
        if name == "excess_solar_kwh_threshold":
            print(
                f"| `{name}` | {opt_val:.1f} kWh | ${cost_m:,.2f} | "
                f"${cost_o:,.2f} | ${cost_p:,.2f} | ${max_impact:,.2f} |"
            )
        else:
            print(
                f"| `{name}` | {opt_val:.1f}% | ${cost_m:,.2f} | "
                f"${cost_o:,.2f} | ${cost_p:,.2f} | ${max_impact:,.2f} |"
            )
    print()

    # Sort by impact descending
    sorted_sens = sorted(sensitivity, key=lambda x: max(abs(x[2] - x[3]), abs(x[4] - x[3])), reverse=True)
    print("**Most sensitive parameters** (by max cost impact):")
    for i, (name, opt_val, cost_m, cost_o, cost_p) in enumerate(sorted_sens[:3], 1):
        max_impact = max(abs(cost_m - cost_o), abs(cost_p - cost_o))
        print(f"{i}. `{name}` -- ${max_impact:,.2f} impact")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="URA Energy Management 365-Day Monte Carlo Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Simulates a full year of home energy management with PEC TOU rates,\n"
            "solar production, battery storage, and EV charging. Uses Monte Carlo\n"
            "optimization to find optimal battery drain targets and arbitrage thresholds.\n"
            "\n"
            "Imports PEC_TOU_RATES and SOLAR_MONTHLY_THRESHOLDS from\n"
            "custom_components/universal_room_automation/domain_coordinators/energy_const.py"
        ),
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1000,
        help="Number of Monte Carlo trials (default: 1000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress during optimization",
    )
    args = parser.parse_args()

    print(f"URA Energy Simulation — {args.trials} trials, seed={args.seed}")
    print(f"Using {'numpy' if HAS_NUMPY else 'stdlib random (install numpy for ~10x speedup)'}")
    print()

    # Run optimization
    best, default, baseline = run_optimization(args.trials, args.seed, args.verbose)

    # Run sensitivity analysis
    if args.verbose:
        print("Running sensitivity analysis...")
    sensitivity = run_sensitivity(best.params, args.seed)

    # Print report
    print_report(best, default, baseline, sensitivity, args.trials, args.seed)


if __name__ == "__main__":
    main()
