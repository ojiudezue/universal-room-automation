# v3.14.4: Simplified Grid Import Formula

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 28 in energy consumption suite

## Problem

Previous grid import model was overcomplicated (day/night split, solar window TZ math, SOC defaults) and produced -114 kWh — unrealistically high export. The math should be simple energy balance.

## Solution

Simple formula: solar powers the house, battery buffers the difference.

- **Surplus day** (solar > consumption): battery absorbs up to usable capacity, rest exports.
  `net = -(surplus - battery_absorbs)`
- **Deficit day** (solar < consumption): battery covers deficit up to usable capacity, rest imports.
  `net = deficit - battery_provides`

Where `usable_battery = capacity * (1 - reserve_pct / 100)`.

Example: 150 kWh solar, 31 kWh consumption, 40 kWh battery (10% reserve = 36 kWh usable):
- Surplus = 119, battery absorbs 36, export = 83 → **-83 kWh**

Removed: `_get_solar_window_hours()`, SOC default logic, day/night split.
