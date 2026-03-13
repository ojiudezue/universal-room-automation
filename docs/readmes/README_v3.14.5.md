# v3.14.5: Consumption Baseline Fix

**Date:** 2026-03-13
**Branch:** develop -> main

## Problem

The consumption prediction (30.9 kWh) was far too low because:
1. Default baseline was 30 kWh — too low for a large home with AC/pool
2. The accuracy tracker was loading 7 rows of garbage data from `energy_daily` (near-zero consumption from the net-consumption CT bug)
3. The Bayesian adjustment factor was being skewed by bad historical data

## Changes

### `domain_coordinators/energy_forecast.py`
- **Default baseline:** 30 → 45 kWh/day (better reflects large home with AC/pool)

### `domain_coordinators/energy.py`
- **`_restore_accuracy_from_db()`:** Filters out energy_daily rows with consumption < 10 kWh (artifacts of the pre-v3.14.0 net-consumption CT bug). Prevents poisoned data from skewing the Bayesian adjustment factor.

## Effect on Grid Import Prediction

With 45 kWh consumption baseline:
- `net = -(150 - 45 - 36) = -69 kWh` (net export)
- More realistic than -83 kWh at 31 kWh consumption

As v3.14.0's fixed consumption tracking accumulates clean data over the coming days, the day-of-week baselines and temperature regression will replace this default with learned values.
