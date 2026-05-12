# HVAC Coordinator — User Manual

**Device:** `URA: HVAC Coordinator`
**Last updated:** 2026-05-10 (v4.5.11.1 — slice 1 of AC ramp-down cycle)
**Scope:** every control, sensor, switch, and form field on the HVAC Coordinator surface

This is a task-oriented manual: skim the section headings to find what you need, read the troubleshooting recipes when something feels wrong. The reasoning behind each default is included so you can judge edge cases without re-deriving from first principles.

---

## 1. What the HVAC Coordinator does

URA: HVAC Coordinator is the brain that decides, every 5 minutes, what every climate-related entity in your house should do. It runs four loosely-coupled controllers under one decision cycle:

- **Preset Manager** — picks the cooling/heating setpoint range for each zone based on house state (home / sleep / away / vacation) and season (summer / shoulder / winter)
- **Cover Controller** — closes covers/shades during solar-gain hours to reduce cooling load; reopens them when conditions allow
- **Fan Controller** — runs fans for circulation when zones are above setpoint or humidity is high
- **Override Arrester** — detects manual thermostat overrides and reverts them after a grace period; also runs the **AC ramp-down** (energy-aware overshoot detection)

All four controllers share the same `ZoneManager` (one HVAC zone per thermostat) and a single decision cycle (every 5 min). Each controller has a master kill-switch — you can disable any single domain without disabling the others.

**Decision cadence:** 5-minute polling cycle, plus event-driven response to thermostat state changes (override detection).

---

## 2. The kill-switches (master toggles)

Eight switches live on the HVAC Coordinator device. Each gates a specific subsystem. **All eight are independent** — you can flip any combination.

### `Override Arrester`
**Default:** ON
**What it does:** detects manual thermostat changes that deviate from URA's expected setpoint, then reverts them after a grace period (2-5 min) or applies a compromise (move halfway between user's value and expected, hold for 30 min, then revert).
**When to disable:** if you want manual thermostat changes to stick indefinitely (no automatic revert). Useful during testing or when family members complain that "Claude keeps changing my temperature."

### `AC Reset`
**Default:** ON (legacy v3.8.3 trigger — "current > target while cooling")
**What it does:** the legacy stuck-cycle detector. Fires when AC is actively cooling but the room temperature hasn't moved toward setpoint after 10 minutes. Backstop for undersized AC / low refrigerant scenarios.
**When to disable:** if you don't want any automatic AC restart cycling at all.
**Note:** v4.5.11 added the new `AC Ramp-Down (Energy-Aware)` switch which is the modern path for AC-related interventions. Both can coexist.

### `Fan Control`
**Default:** ON
**What it does:** runs zone fans for circulation when room is N°F above the cooling setpoint (Fan On Threshold), turns off when it falls below setpoint - hysteresis (Fan Off Hysteresis).
**When to disable:** if you don't want URA controlling fans at all (you prefer manual / thermostat-controlled fan operation).

### `Solar Cover Management`
**Default:** ON (v4.5.10 added the master toggle)
**What it does:** closes covers/shades during solar-gain hours (Cover Solar Start Hour to Cover Solar End Hour) when outdoor temp exceeds Cover Close Temp. Reopens when conditions allow.
**When to disable:** during testing, when the algorithm gets a cover wrong, or seasonally when you want all covers open all day.
**Three-layer gating:** Master OFF → no covers move. Master ON + per-room `cover_hvac_managed` OFF → that room's covers skipped. Master ON + per-room ON → per-decision logic evaluates.

### `Per-Zone HVAC Control` (renamed from "Zone Intelligence" in v4.5.10)
**Default:** ON
**What it does:** lets each HVAC zone independently track presets based on its own occupancy and presence state. When OFF, all zones follow whole-house preset state uniformly.

### `Vacancy Auto-Off` (renamed from "Zone Sweep" in v4.5.10)
**Default:** ON
**What it does:** moves a zone to a wider setpoint band when it's been vacant for `Vacancy Grace Minutes` (default 15). Returns to normal when occupancy returns.

### `Pre-Arrival`
**Default:** ON
**What it does:** pre-conditions zones (~30 min ahead) when a person's geofence or BLE signal indicates they're arriving home.

### `AC Ramp-Down (Energy-Aware)` (v4.5.11 — NEW)
**Default:** OFF on first install (opt-in)
**What it does:** detects when an AC reached setpoint but kept burning kWh past the natural cycle-end, then applies a soft setpoint nudge (target + 1.5°F for 5 min) to coax the variable-speed compressor to ramp down. Escalates to hard reset only if the nudge is ineffective. Daily cap + 2hr min-interval gates protect the compressor from rapid cycling.
**When to enable:** after you've configured per-zone `AC Load Sensor` fields (Zone Manager → zone → 🌡️ Zone HVAC) and reviewed the recommended threshold for your AC tonnage.
**When to disable:** if you suspect false triggers, want to pause for diagnostics, or are doing AC maintenance. Toggling OFF also restores any in-flight nudge to its original target.
**Three-layer gating:** Master switch → per-zone `AC Ramp-Down enabled` → per-decision (overshoot + kWh thresholds + sustained-time gate).

---

## 3. Runtime sliders (Number entities)

Every Number entity on URA: HVAC Coordinator is **runtime-tunable** — change the slider value and the next decision cycle picks it up. No reload needed. The slider's value survives HA restart (RestoreEntity-backed). Form-level CONF values are install-time seeds only.

### Cover Controller sliders (v4.5.10)

#### `Cover Close Threshold` — 0.5–5.0°F, default 2.0°F
How far above the cooling setpoint a room must be (when occupied) before HVAC closes its covers for solar-gain reduction.
**Raise** if covers close too aggressively when room temp is only slightly elevated.
**Lower** for tighter solar-gain management at the cost of more cover movement.

#### `Cover Close Temp` — 75–95°F, default 85°F
Outdoor temperature at which HVAC starts closing covers in the solar-gain window.
**Raise** for hotter climates (covers close only on the hottest days).
**Lower** for milder climates (close earlier).

#### `Cover Open Temp` — 70–90°F, default 80°F
Outdoor temperature at which HVAC reopens covers it previously closed. **Must be at least 3°F below Cover Close Temp** (hysteresis floor — form-save rejects invalid pairs).

#### `Cover Override Duration` — 0.5–24 hr, default 2 hr
How long HVAC respects a manual cover touch before resuming its own management. If you manually open a cover that URA closed, URA won't close it again for this duration.

#### `Solar Banking Cool Floor` — 65–80°F, default 72°F
The coolest setpoint solar banking will drive zones to during high-SOC + sunny conditions (uses surplus solar to "bank" thermal capacity).
**Raise** if banking makes the house too cold.
**Lower** for more aggressive solar surplus utilization.

### Fan Controller sliders (v4.5.10)

#### `Fan On Threshold` — 0.5–5.0°F, default 2.0°F
How far above cooling setpoint a zone must be for the fan to turn on.

#### `Fan Off Hysteresis` — 0.5–5.0°F, default 1.5°F
How far below the on-threshold the zone must drop for the fan to turn off. Prevents rapid on/off cycling.

### AC Ramp-Down sliders (v4.5.11 — NEW)

#### `AC Nudge Size` — 0.5–3.0°F, default 1.5°F
When an overshoot is detected, AC ramp-down adds this many °F to the cooling setpoint for the nudge duration. Bryant's variable-speed compressor sees a smaller demand error and ramps down.
**Raise** if 1.5°F nudges are ineffective (kWh doesn't drop after nudge → feature escalates to hard reset every time). Try 2.0 or 2.5°F.
**Don't raise above 3.0°F** without observing — large nudges may cause comfort impact while still being ineffective.

#### `AC Nudge Duration` — 1–15 min, default 5 min
How long the +nudge_size offset is held before restore.
**Raise** if Bryant's polling cadence (~60-90s) means 5 min is only 3-5 polls and the compressor doesn't fully ramp down before restore. 7-10 min may give cleaner ramp-down.
**Lower** for tighter comfort impact at the cost of less time for the compressor to respond.

#### `AC Sustained Samples` — 2–10, default 3
How many consecutive 5-min cycle samples must show `kwh_rate > threshold` before detection fires. This is the noise debounce.
**Raise** if you see false positives during normal cooling cycles.
**Lower** if you want faster detection at higher noise risk.

#### `AC Detection Time Gate` — 5–30 min, default 10 min
How long the overshoot window (current temp <= target - 0.5°F) must hold before any action fires.
**Raise** for tighter false-positive control.
**Lower** if you observe waste continuing for too long before action.

#### `AC Hard Reset Daily Limit` — 0–5, default 2
Maximum hard resets (off→60s→restore) allowed per zone per day. Critical compressor-protection cap.
**Set to 0** to make the feature soft-only (no escalation ever fires).
**Don't raise above 2** without strong reason — Bryant's spec tolerates ~2 starts/hour absolute max; 2/day is well within safe.

#### `AC Hard Reset Min Interval` — 30–360 min, default 120 min
Minimum gap between hard resets on the same zone, regardless of daily cap. Prevents the 23:59 → 00:01 day-rollover race where the daily counter resets but the compressor is still warm.
**Don't lower below 120 min** without strong reason. The 2-hour minimum is calibrated for variable-speed compressor cycle-rate spec.

#### `AC kWh Rate Threshold (<zone>)` — per AC zone, 0.3–3.0 kW, default 0.8 kW
The kWh rate above which a zone's cooling is considered "wasteful" (sustained burning past setpoint). Scales with AC tonnage:
- **3-ton unit:** 0.8 kW (default — matches ~25-30% of rated power = compressor minimum-modulation floor)
- **4-ton unit:** raise to 1.0 kW
- **2-ton unit:** lower to 0.5–0.6 kW
- **5-ton unit:** raise to 1.5 kW

Each AC zone has its own slider — your 3-ton zones can use 0.8 while the 4-ton uses 1.0. No need for uniform tuning.

### Override Arrester (legacy v3.8.3)
These don't have sliders — they're internal constants. If you ever need to tune, file an issue.

---

## 4. Per-zone buttons (v4.5.11 — NEW)

Each AC zone gets three buttons. They appear on URA: HVAC Coordinator device, named per zone (e.g. "Force AC Nudge (Zone 1)").

### `Force AC Nudge (<zone>)`
Immediately fires a soft nudge for that zone — regardless of whether detection conditions are met. Respects the master switch (won't fire if `AC Ramp-Down (Energy-Aware)` is OFF). Counts toward today's nudge budget so it can't be used to mask runaway loops.
**Use for:** testing whether a 1.5°F nudge produces a measurable kWh drop on your AC. Press, wait 5 min for restore + 10 min for evaluation, check the event log.

### `Cancel AC Nudge (<zone>)`
Aborts an in-flight nudge for that zone and restores the original setpoint within ~1 second.
**Use for:** mistake recovery if you pressed Force Nudge by accident or the timing doesn't suit you.

### `Clear AC Ramp Lockout (<zone>)`
Clears today's hard-reset counter + lockout flag for that zone, dismisses the lockout notification.
**Use for:** false-positive recovery — if the lockout fired because the kWh threshold was too sensitive, clear the lockout AND raise the threshold slider so it doesn't re-fire.

---

## 5. Form fields (per-zone, via Zone Manager → zone → 🌡️ Zone HVAC)

These are configured at install time (or via the integration's options flow). Unlike sliders, they require a reload to take effect.

### `Zone Thermostat`
Climate entity that controls this zone. If unset, URA falls back to the first room's thermostat. Required for HVAC ZoneManager to discover the zone.

### `AC Load Sensor (kW or kWh)` (v4.5.11 — NEW)
Entity that measures this AC unit's power draw. Required for AC Ramp-Down to work for this zone.
- **Span panel:** pick the circuit sensor labeled for this AC's outdoor unit
- **Emporia Vue:** pick the per-circuit power sensor
- **Sense:** pick the device-recognized "AC compressor" sensor if Sense identified it; otherwise raw circuit if available
- **Other CT clamps:** any `sensor.*` with `device_class: power` (kW preferred) or `device_class: energy` (kWh totalizer)

If unset, the AC Ramp-Down feature short-circuits OFF for this zone (no false triggers).

### `AC Ramp-Down enabled for this zone` (v4.5.11 — NEW)
Per-zone opt-out. When OFF, this zone is skipped even when the master AC Ramp-Down switch is ON.
**Use for:** AC units on shared circuits with non-AC loads (dryer, oven), where the kWh sensor would show false spikes. Disable for that zone, leave master ON for the others.

### (Plus zone-energy, zone-persons, zone-cameras steps — out of scope for this section)

---

## 6. Form fields (CM-level, via Coordinator Manager → 🌡️ HVAC)

Set-and-forget tunables that don't need a runtime slider:

- **Solar Cover Start Hour** — when HVAC starts watching for solar conditions (default 13)
- **Solar Cover End Hour** — when HVAC stops + reopens HVAC-closed covers (default 18)
- **Solar Banking Battery Threshold** — SOC above which surplus solar drives thermal banking (default 95)
- **Pre-Cool Trigger Temp** — forecast-high above which HVAC pre-cools (default 90°F)
- **Pre-Heat Trigger Temp** — outdoor-low below which HVAC pre-heats (default 35°F)

Plus the legacy CONF_HVAC_* tunables (Compromise Minutes, AC Reset Timeout, Fan Min Runtime, etc.).

---

## 7. Three-layer gating model

Two features use the same gating shape: **Solar Cover Management** and **AC Ramp-Down**. Memorize this once, apply to both.

```
┌─────────────────────────────────────────────────────────────┐
│  Master switch (house-wide)                                  │
│    ↓ OFF -> feature does nothing, regardless of any setting │
│    ↓ ON -> evaluate next layer                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Per-zone (or per-room) opt-out                              │
│    ↓ OFF -> this zone/room skipped this cycle                │
│    ↓ ON -> evaluate per-decision logic                       │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Per-decision gates                                          │
│    ↓ (overshoot? kWh threshold? sustained time? etc.)        │
│    ↓ ALL gates pass -> action fires                          │
└─────────────────────────────────────────────────────────────┘
```

**Why three layers:** lets you (1) disable entire features house-wide with one toggle, (2) exclude specific zones/rooms that are problematic, (3) trust the algorithm for the rest.

---

## 8. Troubleshooting

### "AC kept cooling past setpoint and burned kWh"

This is the v4.5.11 raison d'être. Check in order:

1. **Is the master switch ON?** Settings → Devices → URA: HVAC Coordinator → `AC Ramp-Down (Energy-Aware)` switch
2. **Is the per-zone setting enabled?** Zone Manager → that zone → 🌡️ Zone HVAC → `AC Ramp-Down enabled for this zone`
3. **Is the AC Load Sensor configured AND reporting?** Pick the entity in the same form, check its state — should show live kW value
4. **Is the kWh threshold appropriate for AC size?** Default 0.8 kW is for 3-ton. If you have a 4-ton, raise the per-zone slider to 1.0 kW
5. **Has the lockout fired?** Check for a persistent notification "AC Ramp Lockout: <zone>" — if present, press the Clear Lockout button for that zone

### "Nudges fire too often / I see false positives"

1. Raise `AC kWh Rate Threshold` for the affected zone(s)
2. Raise `AC Sustained Samples` (default 3) to require more consecutive over-threshold samples
3. Raise `AC Detection Time Gate` (default 10 min) for longer overshoot-confirmation window
4. Check `AC Load Sensor` — does it report only AC's draw, or does it include another load on the same circuit? If shared circuit, disable AC Ramp-Down for that zone via the per-zone toggle

### "Nudges fire but kWh doesn't drop afterward"

Nudge is ineffective for your specific Bryant unit. Try:
1. Raise `AC Nudge Size` from 1.5°F → 2.5°F
2. Raise `AC Nudge Duration` from 5 min → 7-10 min (gives more polling cycles for Bryant to respond)
3. If both fail repeatedly: the feature still works via hard-reset escalation, just with the daily cap. Accept this mode and use the lockout notification as a signal to investigate.

### "Lockout fired but I think it was a false positive"

1. Press the **Clear AC Ramp Lockout** button for that zone
2. Tune the per-zone `AC kWh Rate Threshold` up by 0.2 kW to reduce sensitivity
3. If it keeps recurring: drop the threshold check by raising `AC Sustained Samples` instead

### "Solar Cover Management is closing covers I don't want closed"

Use the three-layer gating:
- **House-wide off (emergency):** flip `Solar Cover Management` switch OFF — no covers move regardless
- **Per-room off:** Zone Manager → room → per-room form → `cover_hvac_managed` OFF for just that room
- **Per-cover tuning:** raise `Cover Close Threshold` (require more occupancy-deviation before closing)

### "Vacancy sweep is too aggressive / wakes presets early"

Raise `Vacancy Grace Minutes` (default 15) in the CM HVAC form. Or disable `Vacancy Auto-Off` switch entirely.

### "Override Arrester reverted my manual change too fast"

Either disable the `Override Arrester` switch entirely, or increase the legacy `Compromise Minutes` value in the CM HVAC form (default 30). Note: large overrides (>3°F) always use the short-grace severe path; this can't be tuned via slider.

### "How do I see what AC Ramp-Down is doing right now?"

Slice 1 ships with state visible via:
1. `sensor.ura_hvac_coordinator_mode` attributes — see `arrester_state`, `ac_reset_enabled`
2. Direct SQL: `sqlite3 /config/universal_room_automation/data/universal_room_automation.db "SELECT * FROM ac_ramp_events ORDER BY event_id DESC LIMIT 10"`

**Slice 2 (v4.5.12) ships dedicated state sensors** per zone + house-wide impact sensors (nudges_today, kwh_avoided, false_positive_rate). Until then, SQL is the readout.

---

## 9. kWh-avoided methodology (slice-2 sensor, preview)

When v4.5.12 ships, the `sensor.ura_hvac_ac_kwh_avoided_today` and `..._total` will show approximate energy savings from the AC ramp-down feature.

**The math is a rough estimate:**
```
On nudge_started: capture kwh_rate_before
On nudge_restored + 10min: capture kwh_rate_after
delta_kw = max(0, before - after)
estimated_remaining_overshoot = min(30, overshoot_minutes_when_nudge_fired)
kwh_avoided_for_event = delta_kw × (estimated_remaining_overshoot / 60)
```

**The 30-minute cap is a sanity bound.** It prevents the math from claiming wild savings (e.g., "we saved 4 hours of runtime" when really the AC was about to cycle off naturally in 5 min anyway).

**This is NOT baseline-matched.** A precise estimate would compare today's kWh against a similar-weather day with the feature disabled. We don't have that data (yet). The current estimate is conservative — it under-counts savings rather than over-counts.

**Use the kWh-avoided number for trend-watching ("is the feature working?"), not for billing accuracy.** Tech debt note in `docs/TECH_DEBT.md` documents the limitation; future Span historical-API integration could replace the rough estimate with true comparable-day matching.

---

## 10. Reading the event log

`/config/universal_room_automation/data/universal_room_automation.db` table `ac_ramp_events` is an append-only log of every AC ramp-down state transition. Useful for understanding what the system did over the past N hours/days.

```sql
SELECT
  event_id, zone_id, timestamp, event_type, triggered_by,
  current_temp, target_high,
  kwh_rate_before, kwh_rate_after, action_taken,
  soft_nudge_count_today, hard_reset_count_today,
  lockout_triggered, notes
FROM ac_ramp_events
WHERE timestamp > datetime('now', '-1 day')
ORDER BY event_id DESC;
```

**Event types you'll see:**
- `detection_fired` — all 9 gates passed; about to act
- `nudge_started` — soft nudge issued; setpoint bumped
- `nudge_restored` — 5 min later; setpoint restored
- `nudge_evaluated` — 10 min after restore; kWh measured; decision to escalate or not
- `hard_reset_started` — escalation fired; AC mode set to off
- `hard_reset_completed` — restore mode after 60s
- `lockout_engaged` — daily cap hit; notification fired
- `manual_override` — Force Nudge button pressed by user (excluded from false-positive math)
- `cancel_invoked` — Cancel Nudge button pressed
- `startup_restore` — restart-during-nudge audit fired

The `triggered_by` column distinguishes `auto` (detection-fired) from `manual` (button-fired) from `startup` (audit). Reports filter on this.

**Retention:** 30 days, auto-pruned during day rollover.

---

## 11. Architecture sketch (decision flow per cycle)

Every 5 minutes, the HVAC Coordinator does, in order:

1. **Detect day rollover** — if new date, reset daily counters, flush yesterday's predictor outcome, recalculate season
2. **Update zone states** — read each thermostat's current temp, humidity, hvac_action, target_temp_high/low
3. **Update room conditions** — aggregate from URA rooms in each HVAC zone
4. **First-cycle audit** (once per init) — check for stale overrides + in-flight nudges that survived a restart, restore as needed
5. **Apply house-state presets** — set each zone to the right cooling/heating range based on house state (home / sleep / away)
6. **Update override arrester energy state** — let arrester widen tolerance during energy coast
7. **Run AC Ramp-Down detection** — `check_ac_reset` evaluates 9 gates per zone, fires actions as needed
8. **Fan controller update** — set each managed fan based on temp deltas
9. **Cover controller update** — close/open covers based on solar-gain logic

Each step is idempotent — running it twice produces the same state. Race-safe.

---

## 12. Related entities (not on this device but relevant)

- **Per-room HVAC settings** — Zone Manager → room → 🌡️ HVAC. `cover_hvac_managed` (per-room cover opt-out), `comfort_temp_min/max`, etc.
- **Energy Coordinator** — sets `energy_constraint_mode` (normal / shed / coast). HVAC tightens / loosens tolerance based on this. See `ENERGY_COORDINATOR.md` user manual.
- **Notification Manager** — fires alerts for HVAC events (override detection, AC ramp lockout). Acknowledge via the NM button.

---

## Appendix: full entity list (URA: HVAC Coordinator device)

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ura_hvac_coordinator_mode` | Sensor | Mode + comprehensive attributes |
| `sensor.ura_hvac_coordinator_zone_N_status` | Sensor | Per-zone HVAC status (one per zone) |
| `switch.ura_hvac_coordinator_hvac_override_arrester` | Switch | Master |
| `switch.ura_hvac_coordinator_hvac_ac_reset` | Switch | Master |
| `switch.ura_hvac_coordinator_hvac_fan_control` | Switch | Master |
| `switch.ura_hvac_solar_cover` | Switch | v4.5.10 master |
| `switch.ura_hvac_coordinator_hvac_zone_intelligence` | Switch | Renamed to "Per-Zone HVAC Control" |
| `switch.ura_hvac_coordinator_zone_sweep` | Switch | Renamed to "Vacancy Auto-Off" |
| `switch.ura_hvac_pre_arrival` | Switch | Master |
| `switch.ura_hvac_ac_ramp_master` | Switch | **v4.5.11 NEW** |
| `number.ura_hvac_coordinator_cover_close_threshold` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_cover_close_temp` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_cover_open_temp` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_cover_override_duration` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_solar_bank_floor` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_fan_on_threshold` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_fan_off_hysteresis` | Number | v4.5.10 |
| `number.ura_hvac_coordinator_ac_nudge_size` | Number | **v4.5.11 NEW** |
| `number.ura_hvac_coordinator_ac_nudge_duration` | Number | **v4.5.11 NEW** |
| `number.ura_hvac_coordinator_ac_sustained_samples` | Number | **v4.5.11 NEW** |
| `number.ura_hvac_coordinator_ac_detection_time_gate` | Number | **v4.5.11 NEW** |
| `number.ura_hvac_coordinator_ac_hard_reset_daily_limit` | Number | **v4.5.11 NEW** |
| `number.ura_hvac_coordinator_ac_hard_reset_min_interval` | Number | **v4.5.11 NEW** |
| `number.ura_hvac_ac_kwh_threshold_<zone_id>` | Number | **v4.5.11 NEW** (per AC zone) |
| `button.ura_hvac_ac_ramp_force_nudge_<zone_id>` | Button | **v4.5.11 NEW** (per AC zone) |
| `button.ura_hvac_ac_ramp_cancel_nudge_<zone_id>` | Button | **v4.5.11 NEW** (per AC zone) |
| `button.ura_hvac_ac_ramp_clear_lockout_<zone_id>` | Button | **v4.5.11 NEW** (per AC zone) |
| `sensor.ura_hvac_ac_ramp_state_<zone_id>` | Sensor | **v4.5.12 NEW** — per-zone state machine label (idle / detecting / nudging / awaiting_evaluation / escalating / locked_out / disabled) |
| `sensor.ura_hvac_ac_ramp_last_action_<zone_id>` | Sensor (timestamp) | **v4.5.12 NEW** — when the last ramp-down action fired on this zone; attrs carry action_type + triggered_by + kwh_before/after |
| `sensor.ura_hvac_ac_ramp_kwh_rate_<zone_id>` | Sensor (kW) | **v4.5.12 NEW** — live read of the zone's configured ac_load_sensor with a `stale` attribute |
| `sensor.ura_hvac_ac_nudges_today` | Sensor (count) | **v4.5.12 NEW** — house-wide soft-nudge count today |
| `sensor.ura_hvac_ac_resets_today` | Sensor (count) | **v4.5.12 NEW** — house-wide hard-reset count today |
| `sensor.ura_hvac_ac_kwh_avoided_today` | Sensor (kWh) | **v4.5.12 NEW** — rough estimate (see TECH_DEBT.md) |
| `sensor.ura_hvac_ac_kwh_avoided_total` | Sensor (kWh, persistent) | **v4.5.12 NEW** — cumulative since feature enable |
| `sensor.ura_hvac_ac_false_positive_rate` | Sensor (%) | **v4.5.12 NEW** — diagnostic; `unavailable` until ≥5 nudge evaluations |
| `button.ura_hvac_ac_ramp_diagnostic_dump` | Button (diagnostic) | **v4.5.12 NEW** — dumps last 7 days of `ac_ramp_events` to `/config/ura_diagnostics/` |

### Reading the v4.5.12 observability surface

The three per-zone state sensors auto-refresh on every HVAC tick (5 min). Watch them during initial tuning:
- **`ramp_state`** transitioning from `idle` → `detecting` → `nudging` confirms the kWh threshold is calibrated correctly for that zone's AC tonnage.
- **`last_action`** (timestamp sensor) gives a single dashboard line per zone showing when the most recent action fired and what it did.
- **`kwh_rate`** is the live signal driving detection — pin this next to its threshold slider to see how close you are to firing.

The five house-wide impact sensors update at the same cadence. The two that matter most:
- **`nudges_today`** — should be 0–5 on a typical day. Above 10 means either the threshold is too low or your AC is genuinely running away. Cross-reference `false_positive_rate`.
- **`kwh_avoided_today`** — trend-watching only. Don't compare to your utility bill directly; the math is documented in `docs/TECH_DEBT.md`.

When tuning **after the first week**:
- If `false_positive_rate` shows ≥30%, raise the per-zone kWh threshold (your AC's idle/coast draw is above the slider, so legit cycling triggers the detector).
- If `nudges_today` stays at 0 across multiple hot days when you SUSPECT waste, lower the threshold OR drop the sustained-samples count.
- Press the **AC Ramp Diagnostic Dump** button to capture a 7-day JSON for offline pattern analysis.

### Known quality-control patterns (Bug Class catalog reference)

Two bug shapes from the v4.5.11.x debugging cycle are documented in `docs/QUALITY_CONTEXT.md` and apply to any future tuning / extension of this device:

- **Bug Class #34** (function-local import shadows module-level) — when adding new code paths to `OverrideArrester` or any HVAC coord method, avoid adding `from X import Y` inside a function body when `Y` is already imported at module level. AST regression tests catch this at PR time.
- **Bug Class #35** (button without refresh signal) — any new Button entity whose `available` depends on a runtime resource must subscribe to `SIGNAL_HVAC_ENTITIES_UPDATE` in `async_added_to_hass`. Otherwise it caches `available: False` forever after a restart timing-race. All v4.5.11.3+ buttons follow this pattern.

These are documented for both maintenance (when adding new buttons / coord setup code) and for context if you observe the related symptoms (UnboundLocalError tracebacks, or buttons stuck greyed-out).
