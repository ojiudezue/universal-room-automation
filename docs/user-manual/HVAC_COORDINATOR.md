# HVAC Coordinator — User Manual

**Device:** `URA: HVAC Coordinator`
**Last updated:** 2026-06-16 (v5.5.1)
**Scope:** every control, sensor, switch, and form field on the HVAC Coordinator surface — plus the cross-cutting presence interfaces it consumes

This is a task-oriented manual: skim the section headings to find what you need, read the troubleshooting recipes when something feels wrong. The reasoning behind each default is included so you can judge edge cases without re-deriving from first principles. Where a behavior is non-obvious or could be mistaken for a bug, the source location is cited (`file:line`) so you can verify it.

### Changelog since last revision (v4.5.11.1 → v5.5.1)

| Cycle | What it added to the HVAC surface |
|---|---|
| v4.7.13 | SLEEP-state zone person-trust — phone/BLE tracker suppresses the away-flip while you sleep |
| v4.7.14 | AWAY-state person-tracker veto (whole-house; lives in Presence, affects HVAC presets) |
| v4.7.20–22 | Fan-noise mitigation — mmWave interference handling so a running fan doesn't flap occupancy |
| v4.7.24 | Occupancy substrate — the raw per-room/per-kind presence layer HVAC ultimately reads through |
| v4.7.25 | Presence-timer knobs exposed as Number entities (48 Zone Vacancy Delay, 49 Energy-Saving, 50 Max Zone Occupied Time) + a Reset button |
| v4.7.31 | HVAC zones resolved by NAME in the person-trust fallback (Bug Class #53 — the trust was silently dead for thermostat'd zones before this) |
| v4.7.32 / .33 | OverrideArrester re-asserts `heat_cool` on revert + AC-reset restore (not just `off`); 5s suppression TTL window |
| v5.4.0 | HC Pre-Conditioning master toggle — "28 · HVAC Predictive Conditioning" (unique_id `ura_hvac_pre_conditioning_enabled`). Gates the WHOLE pre-conditioning chain (weather pre-cool + solar banking + pre-arrival + pre-heat), not just forecast pre-cool/pre-heat |
| v5.5.0 | (Battery/inclement-weather cycle — no direct HVAC-device surface change; noted for completeness) |

The big structural truth that did NOT change: HVAC still calls `climate.set_preset_mode(<name>)` per zone every cycle and lets the thermostat resolve the range. Direct `set_temperature` writes happen only for the energy-constraint offset path and AC nudges.

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

## 1b. The two pillars: house-state presets + seasonal defaults

Every HVAC decision starts from two lookups:

**1. House state → preset name** (`HOUSE_STATE_PRESET_MAP` in `hvac_const.py`):

| House state | → Preset |
|---|---|
| `home_day` / `home_evening` / `home_night` / `arriving` / `waking` / `guest` | `home` |
| `sleep` | `sleep` |
| `away` | `away` |
| `vacation` | `vacation` |

URA's presence + house-state machine picks the state; this table maps it to one of 4 preset names. The same preset name is applied to every URA-managed zone unless that zone is opted out.

**2. Preset name + season → setpoint range** (`SEASONAL_DEFAULTS`):

Summer (Jun-Sep):

| Preset | Cool ≤ | Heat ≥ |
|---|---|---|
| home | 77 | 70 |
| sleep | 76 | 70 |
| away | 82 | 60 |
| vacation | 85 | 58 |

Shoulder (Mar-May, Oct-Nov): home 70-74 / sleep 68-73 / away 62-80 / vacation 58-82
Winter (Dec-Feb): home 70-72 / sleep 68-70 / away 60-78 / vacation 58-80

URA's per-cycle preset apply does NOT directly set `target_temp_high/low` — it calls `climate.set_preset_mode(preset_name)` (`hvac.py:1255-1262`) and relies on the thermostat's own preset machinery to resolve the range. Direct `set_temperature` writes are reserved for two narrower paths: the **energy-constraint offsets** (§6b, which add °F to the active range) and the **AC ramp-down nudge** (§3). The seasonal base ranges themselves are operator-editable as baseline presets (the `CONF_HVAC_BASELINE_<season>_<preset>_<dim>` config fields, `hvac_const.py:388-442`).

**Override Arrester is suppressed during URA writes** — so the arrester doesn't fight URA's own legitimate preset changes. The suppression is a 5-second TTL window (`hvac_override.py:79`, `SUPPRESS_TTL_SECONDS=5`), wide enough to cover the multiple settle events a single `set_hvac_mode` + `set_preset_mode` produces.

---

## 1c. Presence is an INPUT, not an HVAC feature (cross-cutting)

The HVAC Coordinator does not measure presence itself. Occupancy is produced by the **Presence Coordinator** and the room/zone layers, and HVAC *consumes* it. Understanding this boundary is the key to reading the override behavior below.

**The chain, bottom to top:**

1. **Occupancy substrate** (v4.7.24) — a raw per-room, per-kind presence layer (motion / mmWave / occupancy / camera-person / BLE) maintained by the Presence Coordinator. The curated CONF sensor lists you set per room are the single source of truth for what feeds it.
2. **Per-room occupancy** — each room coordinator derives a single `occupied` bool from its substrate signals (with the v4.7.20–22 fan-noise handling layered in — see §1d).
3. **Per-zone occupancy** — `Zone.any_room_occupied` is simply the **OR of the per-room `occupied` bools** for the rooms in that HVAC zone (`hvac_zones.py:146-148`). One occupied room → the whole zone is occupied. `last_occupied_time` and `continuous_occupied_since` are stamped from this (`hvac_zones.py:554-559`).
4. **HVAC presets** — the preset decision (§1b) and the override paths (§1e) read `any_room_occupied` plus, for the failsafe and trust paths, the Presence Coordinator's confidence helper.

**The confidence helper** (`presence.check_zone_occupancy_confidence`, `presence.py:1559-1663`) is what HVAC asks "is this zone *really* occupied, or is a sensor stuck?" It counts up to **4 independent source types**:

| # | Source | Confirms when |
|---|---|---|
| 1 | Motion / mmWave | a room in the zone had motion in the last 30 min (`presence.py:1618`) |
| 2 | **BLE person** | a tracked phone is detected in the zone (`presence.py:1626-1637`) |
| 3 | Camera person | a configured zone camera entity is `on` (Frigate/Protect person classification, `presence.py:1639-1647`) |
| 4 | Multiple rooms | 2+ rooms in the zone are occupied (`presence.py:1649-1661`) |

It returns `(confirmed, possible)`. Because **BLE counts as one of these sources**, a live phone in the zone is a veto on the 8-hour stale failsafe (§1e, D6).

**Camera caveat (carried over from the presence design):** HVAC's confidence check reads camera **person-classified** detection only, not raw camera *motion*. Camera motion is deliberately not trusted as occupancy here — a shadow or a passing car shouldn't keep a zone "occupied." This is the same person-vs-motion distinction the Presence Coordinator enforces house-wide.

---

## 1d. Fan-noise occupancy handling (v4.7.20–22) — why a running fan doesn't flap presets

A ceiling/box fan's blades shake mmWave radar enough to read as "motion," and the periodic re-evaluation used to cause a visible fan pause. The mitigation lives in the room/presence layer (`hvac_fans.py`, `presence_fan_recheck.py`), beneath HVAC's preset logic:

- **Layer 1 (silent):** a fan-interference confidence discount + decay that can only *extend* occupancy, never fabricate it — provenance (a real motion/person signal) short-circuits first.
- **Layer 2 (BLE-gated recheck):** when a fan is the *only* thing shaking mmWave, the room briefly pauses the fan, rechecks, and only vacates if truly empty. This recheck path is deliberately **SLEEP-only** (`presence_fan_recheck.py`) so it can't disturb a daytime room.

For you as an operator: this is why a fan running over a still occupant does not cause the HVAC zone to flip to `away` mid-evening — the occupancy that HVAC reads stays `True` through the noise.

---

## 1e. The two "away while occupied" override paths (and their guard)

This is the most-asked-about HVAC behavior: "someone is home but the zone went to `away`." There are two distinct code paths that can flip a zone home→away, plus one suppression that vetoes them. All three live in the per-zone loop in `hvac.py`.

### D1 — Vacancy override (`hvac.py:1094-1104`)
Flips a zone from `home`/`sleep` preset to `away` when `any_room_occupied` has been **vacant past the grace period** (`DEFAULT_VACANCY_GRACE_MINUTES=15`, `hvac_const.py:146`; tightened to 5 min during energy coast/shed). This is the normal, intended energy-saving path. Because it keys off the OR-of-rooms occupancy, it can **flap** if the underlying room sensors flap — the grace timer is the only damping.

### D6 — Stale-occupancy failsafe (`hvac.py:1112-1162`)
A backstop against a *stuck-on* sensor. If a zone reports **continuous** occupancy for more than `DEFAULT_MAX_OCCUPANCY_HOURS=8` hours (`hvac_const.py:148`) — and the house isn't in `sleep` — HVAC asks `check_zone_occupancy_confidence` (§1c) whether the occupancy is real. With an adaptive threshold (`min(2, possible)`), if **confirmed < threshold** the zone is latched to `away` as a "stuck sensor" (`hvac.py:1150-1162`); if confirmed meets the threshold, the timer is simply reset and nothing changes. **A live BLE phone (Source 2) or a person-classified camera (Source 3) supplies confirmation here — so BLE/camera are a veto on the 8-hour path.**

### Person-trust suppression (`hvac.py:1205-1237`)
Before either path's `away` is committed, this branch can suppress it: if any of the zone's configured `zone_persons` phone/BLE trackers reports `home`, the away-flip is skipped. **But it only runs when the house is in one of `FAN_TRUST_STATES = ("home_night", "sleep", "waking")`** (`hvac_const.py:329`). The rationale: in those night-window states the room sensors degenerate (mmWave drops a motionless body in bed, PIR can't fire on a still person, a dark room blinds the camera), so the stable phone tracker becomes the trusted signal. v4.7.31 fixed a latent bug (Bug Class #53) where this fallback resolved zones by NAME against an id-keyed dict and silently never matched — meaning before v4.7.31 the trust was *dead* for every thermostat'd zone.

> **See §13 Known limitations** for the honest gap: this person-trust veto does NOT cover `home_day` / `home_evening` / `guest`, and the OverrideArrester does not catch a bare `hvac_mode→cool` drift. Both are observed, real, and unfixed as of v5.5.1.

---

## 2. The kill-switches (master toggles)

Eight switches live on the HVAC Coordinator device. Each gates a specific subsystem. **All eight are independent** — you can flip any combination.

### `Override Arrester`
**Default:** ON
**What it does:** detects manual thermostat changes that deviate from URA's expected setpoint, then reverts them after a grace period (2-5 min) or applies a compromise (move halfway between user's value and expected, hold for 30 min, then revert).
**Detection trigger (precise):** the arrester fires on a **preset change to `manual`** (`hvac_override.py:659`). A bare temperature change while still on a named preset is treated as URA's own range adjustment and ignored (`hvac_override.py:661-664`).
**Mode restore (v4.7.32/.33):** when it reverts, the arrester now re-asserts `heat_cool` whenever the zone's mode has drifted away from it — not just from `off`, but also from a single mode like `cool` or `heat` — but only on thermostats that advertise `heat_cool` (`hvac_override.py:929-948`, `_supports_heat_cool`). The same re-assert applies after an AC stuck-cycle reset restore (`hvac_override.py:548`). The operator runs zones in ranges/presets, so a stuck single-mode is corrected.
**When to disable:** if you want manual thermostat changes to stick indefinitely (no automatic revert). Useful during testing or when family members complain that "Claude keeps changing my temperature."

### `AC Reset`
**Default:** ON (`CONF_HVAC_AC_RESET_ENABLED`, `hvac_const.py:107/139`)
**What it does:** gates the **hard-reset escalation** path (off → 60s → restore). The original standalone v3.8.3 "current > target while cooling after 10 min" detector was **replaced** in v4.5.11 — `check_ac_reset` now drives detection off sustained kWh-rate overshoot, and the old "still hot despite cooling" trigger no longer fires on its own (`hvac_override.py:969-975`). The hard reset survives only as the escalation step the AC Ramp-Down state machine reaches when a soft nudge proves ineffective. With AC Ramp-Down master OFF, this hard-reset path is currently unreachable (no auto-detection feeds it, and there is no manual force_reset button — `hvac_override.py:979-986`).
**When to disable:** if you want to forbid the hard-reset escalation entirely (soft nudges still allowed via the ramp-down feature).

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

### `HVAC Predictive Conditioning` (v5.4.0 — NEW) — name "28 · HVAC Predictive Conditioning", unique_id `ura_hvac_pre_conditioning_enabled`
> The device uses `has_entity_name`, so HA derives the entity_id from the device + friendly name (e.g. `switch.ura_hvac_coordinator_28_hvac_predictive_conditioning`). Match on the unique_id/friendly name if your generated entity_id differs.

**Default:** ON
**What it does:** master gate for the **entire pre-conditioning decision chain** inside `HVACPredictor._check_pre_conditioning` — forecast pre-cool, forecast pre-heat, solar thermal banking, AND pre-arrival (gated by `CONF_HVAC_PRE_CONDITIONING_ENABLED`, `hvac_const.py:92`; short-circuit at `hvac_predict.py:423-472`). When OFF, every one of those branches is skipped. It sits ABOVE (is a coarser parent of) the Solar HVAC Banking toggle — turning this OFF disables banking too, even if Solar HVAC Banking is still ON.
**When to disable:** if you don't want URA reaching ahead of weather/solar for ANY zone (e.g. you're managing comfort manually for the day).
**Flip-OFF behavior:** toggling OFF mid-condition releases in-flight pre-cool / pre-heat / banked zones back to their baseline range within one cycle (via `_release_banked_zones`; the daily-once "triggered_today" flags are also cleared, `hvac_predict.py:438-467`). Flipping back ON the same day re-arms.
**Scope (important):** this gates URA's *predictive* conditioning. The Energy Coordinator's **reactive** TOU offsets (`pre_cool` / `pre_heat` / `coast` / `shed` — see §6b) are a separate setpoint path and are intentionally NOT suppressed by this switch.

### `Solar HVAC Banking` (v5.3.6 — on the Energy Coordinator device)
**Default:** ON
**What it does:** the master toggle for solar thermal banking (`CONF_HVAC_SOLAR_BANK_ENABLED`, `hvac_const.py:81`) — driving zones cooler than normal on high-SOC, sunny days to "bank" thermal capacity from surplus solar. Lives on the **EC device** card (not HVAC), because the operator reaches for it on a good-solar day.
**When to disable:** if banking is over-cooling the house.

### `Egress Window HVAC Pause` (v4.7.8)
**Default:** ON (`CONF_HVAC_EGRESS_PAUSE_ENABLED`, `hvac_const.py:529`)
**What it does:** when a room's window opens AND the room is flagged `is_egress=True`, URA pauses the canonical HVAC zone serving that room (`climate.set_hvac_mode: off`), snapshots the prior mode + preset, and restores on resume. Covers the kid-left-the-window-open / 8.5h-of-AC-waste case. Pause fires after the window is open `DEFAULT_HVAC_EGRESS_THRESHOLD_MIN=3` min; resume fires `DEFAULT_HVAC_EGRESS_RESUME_DELAY_MIN=1` min after all egress windows close. A manual thermostat touch during a pause engages a 1-hour cooldown so URA stops fighting you (`hvac_const.py:544-546`).
**State sensor:** per-zone state machine (`idle / counting / paused / resume_countdown / cooldown`).
**Interaction note:** zones paused by egress are explicitly skipped by both the mode-restore loop and the preset-apply loop (`hvac.py:1035`, `hvac.py:1087`) so HVAC doesn't undo the pause.

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

### Presence-timer knobs (v4.7.25 — NEW)

These three Number entities expose the zone-presence timing constants that drive the §1e override paths. Unlike the cover/fan/AC sliders, these are **`entry.options`-backed (no RestoreEntity)** — `entry.options` is the sole source of truth, pushed live to the running coordinator (`number.py:451-491`).

#### `48 · Zone Vacancy Delay (minutes)` — 0–60, default 15
Minutes a zone must stay empty before HVAC backs off to the `away` preset. This is the D1 vacancy-override grace (`DEFAULT_VACANCY_GRACE_MINUTES`).
**Raise** if zones go `away` too eagerly during brief absences.

#### `49 · Zone Vacancy Delay · Energy-Saving (minutes)` — default 5
The tighter grace used while the house is in energy `coast`/`shed`. **Must be ≤ the normal Zone Vacancy Delay** (the form clamps it bidirectionally; setting #48 below #49 pulls #49 down).

#### `50 · Max Zone Occupied Time (hours)` — default 8
The D6 stale-occupancy failsafe threshold (`DEFAULT_MAX_OCCUPANCY_HOURS`). After this many hours of *continuous* reported occupancy, HVAC runs the confidence check (§1c) and latches `away` if presence can't be confirmed.
**Raise** if you legitimately occupy a zone for very long stretches and the failsafe is firing falsely.

There is also a **Reset button** on the device that returns these presence timers to their defaults.

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
How long the overshoot window (current temp ≤ target, at-or-below setpoint) must hold before any action fires.
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

## 6b. Energy Constraint integration (EC → HVAC)

EC dispatches `SIGNAL_ENERGY_CONSTRAINT` to HVAC each decision cycle. Payload modes + default offsets:

| Mode | Default offset | Trigger (from EC) | HVAC response |
|---|---|---|---|
| `normal` | 0 | Baseline (no constraint active) | Apply preset setpoints as-is |
| `pre_cool` | −2.0°F | Forecast high ≥ `hvac_precool_forecast_high` (default 90°F) AND peak window coming | Lower setpoints to chill house ahead of peak |
| `pre_heat` | +2.0°F | Forecast low < `hvac_preheat_forecast_low` (default 35°F) | Raise heat setpoints early to warm house ahead of peak |
| `coast` | +3.0°F | Load-shedding cascade reached level 4 (HVAC tier) | Widen deadband, reduce cycling |
| `shed` | +5.0°F | Sustained import + aggressive shed | Aggressive setpoint relaxation |

Offsets ADD to the current preset range. Summer `home` is 70-77; with `coast` +3°F it becomes 70-80°F. Reverts on `mode=normal`.

**Diagnostic sensor:** `sensor.ura_energy_coordinator_hvac_constraint` — current mode + offset + reason + forecast_high. Watch this to see what EC is asking HVAC to do.

**Configured via CM options:**
- `energy_constraint_coast_offset` (default 3.0°F)
- `energy_constraint_precool_offset` (default −2.0°F)
- `energy_constraint_preheat_offset` (default 2.0°F)
- `energy_constraint_shed_offset` (default 5.0°F)

---

## 6c. AC Ramp-Down state machine (v4.5.11) — visual

Per-zone state machine (`hvac_override.py:check_ac_reset`). Default OFF at master; enable per-zone.

```
IDLE
  │ overshoot + kwh_rate > threshold
  ▼
DETECTING (counting consecutive samples + minutes)
  │ all gates pass → samples ≥ sustained_samples AND elapsed ≥ detection_time_gate
  ▼
NUDGING  (setpoint raised by ac_nudge_size for ac_nudge_duration)
  │ nudge timer expires
  ▼
AWAITING_EVALUATION  (10 min, sensor settles)
  │ post-nudge kwh_rate STILL above threshold
  ▼
ESCALATING  (hard reset: climate.turn_off → wait → climate.turn_on)
  │
  ├─→ succeeded → IDLE
  └─→ daily limit exceeded → LOCKED_OUT (until next day rollover OR manual clear)
```

Each per-zone state is exposed at `sensor.ura_hvac_coordinator_<zone>_ac_ramp_state`.

---

## 6d. Pre-Cool Likelihood predictor

`HVACPredictor` produces a 0-100% likelihood that today's peak window will trigger a pre-cool action. Inputs:
- Forecast peak outdoor temp (today)
- Forecast peak time (anchor period)
- Current TOU period
- House state + occupancy

**Sensor:** `sensor.ura_hvac_coordinator_pre_cool_likelihood`
- State: integer percent (0-100)
- Attributes: `forecast_peak_outside_f`, `forecast_peak_time_iso`, `anchor_period` (e.g. `peak_4pm_8pm`), `anchor_starts_in_minutes`, `solar_intent`, `prior_day_at_this_hour_f`

User-facing as a "will URA pre-cool today?" dashboard hint. Not a control surface — informational.

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

**v4.5.12 shipped dedicated state sensors** per zone + house-wide impact sensors (nudges_today, kwh_avoided, false_positive_rate) — see §10 and the Appendix. SQL remains available for deeper event-log forensics.

---

## 9. kWh-avoided methodology

`sensor.ura_hvac_ac_kwh_avoided_today` and `..._total` (shipped v4.5.12) show approximate energy savings from the AC ramp-down feature.

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

## 10. Sensor reference (URA: HVAC Coordinator device)

### Mode + status

| Sensor | Value |
|---|---|
| `sensor.ura_hvac_coordinator_mode` | Current overall mode (normal / pre_cool / pre_heat / coast / shed) |
| `sensor.ura_hvac_coordinator_zone_<n>_status` | Per-zone status (idle / cooling / heating / fan_only / off) |
| `sensor.ura_hvac_coordinator_zone_preset_<n>` | Per-zone effective preset right now |
| `sensor.ura_hvac_coordinator_arrester_state` | Override arrester per-zone state |

### Diagnostics + telemetry

| Sensor | Value |
|---|---|
| `sensor.ura_hvac_coordinator_anomaly` | Active anomaly count (kWh-rate, runtime, override-frequency) |
| `sensor.ura_hvac_coordinator_compliance` | % of decisions complied with (no manual override) |
| `sensor.ura_hvac_coordinator_override_frequency` | Manual overrides per 24h (rolling window) |
| `sensor.ura_hvac_coordinator_comfort_risk` | Current comfort-risk class (low / medium / high) |
| `sensor.ura_hvac_coordinator_pre_cool_likelihood` | 0-100% predictor (see §6d) |

### AC Ramp-Down (per-zone, v4.5.11)

| Sensor | Value |
|---|---|
| `sensor.ura_hvac_coordinator_<zone>_ac_ramp_state` | State machine state (idle / detecting / nudging / awaiting_evaluation / escalating / locked_out) |
| `sensor.ura_hvac_coordinator_<zone>_ac_ramp_last_action` | ISO timestamp of last nudge/reset/lockout |
| `sensor.ura_hvac_coordinator_<zone>_ac_ramp_kwh_rate` | Live kWh-rate reading from `ac_load_sensor` |
| `sensor.ura_hvac_coordinator_<zone>_ac_nudges_today` | Count |
| `sensor.ura_hvac_coordinator_<zone>_ac_resets_today` | Count |

### Mirror on Energy device

`sensor.ura_energy_coordinator_hvac_constraint` — what EC is currently asking HVAC to do (mode + offset + reason).

---

## 11. Architecture

```
HVACCoordinator (hvac.py)              priority 30
├── PresetManager (hvac_preset.py)     — seasonal defaults + house_state → preset map
├── ZoneManager (hvac_zones.py)        — per-zone state, per-zone managed opt-out
├── CoverController (hvac_covers.py)   — motorized blinds, solar gain, solar banking
├── SwitchFanController (hvac_fans.py) — per-zone fan on/off with hysteresis
├── HVACPredictor (hvac_predict.py)    — pre-cool / pre-heat likelihood + predictive pre-conditioning (gated by the v5.4.0 master toggle)
├── EgressManager (hvac_egress.py)     — window-open → pause/restore per zone (v4.7.8)
└── OverrideArrester (hvac_override.py) — user-override detection + AC ramp-down state machine + heat_cool re-assert (v4.7.32/.33)
```

**Presence interface (cross-cutting — see §1c):** HVAC reads occupancy produced by the Presence Coordinator and room/zone layers. `Zone.any_room_occupied` (OR of room bools) drives the D1/D6 paths; `presence.check_zone_occupancy_confidence` supplies the multi-source veto (incl. BLE + camera-person). HVAC does not produce presence itself.

**Signals consumed:**
- `SIGNAL_HOUSE_STATE_CHANGED` (from Presence) — triggers preset re-evaluation
- `SIGNAL_ENERGY_CONSTRAINT` (from Energy) — applies setpoint offsets
- `SIGNAL_SAFETY_HAZARD` (from Safety) — emergency-heat-off on smoke/CO

**Decision interval:** 5 minutes. Re-issuing the same `set_preset_mode` for an already-active preset is idempotent.

---

## 11b. Reading the event log

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

## 11c. Architecture sketch (decision flow per cycle)

Every 5 minutes, the HVAC Coordinator does, in order:

1. **Detect day rollover** — if new date, reset daily counters, flush yesterday's predictor outcome, recalculate season
2. **Update zone states** — read each thermostat's current temp, humidity, hvac_action, target_temp_high/low
3. **Update room conditions** — aggregate from URA rooms in each HVAC zone
4. **First-cycle audit** (once per init) — check for stale overrides + in-flight nudges that survived a restart, restore as needed
5. **Restore stray `off` zones to `heat_cool`** — except zones mid-AC-reset or paused by EgressManager (`hvac.py:1034-1061`)
6. **Apply house-state presets per zone** — map house_state → preset (§1b), then run the per-zone overrides in order: D1 vacancy (`hvac.py:1094`), D6 stale failsafe (`hvac.py:1112`), D5 duty-cycle, entry-dwell, then the person-trust suppression (`hvac.py:1205`, night-window only) before committing `set_preset_mode` (§1e). Egress-paused zones are skipped (`hvac.py:1087`).
7. **Update override arrester energy state** — let arrester widen tolerance during energy coast
8. **Run AC Ramp-Down detection** — `check_ac_reset` evaluates its per-zone gates, fires nudge/reset actions as needed
9. **Fan controller update** — set each managed fan based on temp deltas (with fan-noise handling, §1d)
10. **Cover controller update** — close/open covers based on solar-gain logic
11. **Egress window evaluation** — pause/resume zones whose egress windows are open (§2)

Each step is idempotent — running it twice produces the same state. Race-safe.

---

## 12. Related entities (not on this device but relevant)

- **Per-room HVAC settings** — Zone Manager → room → 🌡️ HVAC. `cover_hvac_managed` (per-room cover opt-out), `comfort_temp_min/max`, etc.
- **Energy Coordinator** — sets `energy_constraint_mode` (normal / shed / coast). HVAC tightens / loosens tolerance based on this. See `ENERGY_COORDINATOR.md` user manual.
- **Notification Manager** — fires alerts for HVAC events (override detection, AC ramp lockout). Acknowledge via the NM button.

---

## 13. Known limitations (verified, unfixed as of v5.5.1)

These are real, code-confirmed gaps — documented honestly so you can recognize the symptom and not mistake it for a one-off glitch. Both have been observed live.

### Gap 1 — Daytime "away while occupied": no person-trust veto outside the night window
The person-trust suppression (§1e) that protects a still occupant from a wrongful `away` flip **only runs when the house is in `home_night` / `sleep` / `waking`** (`FAN_TRUST_STATES`, `hvac_const.py:329`; gate at `hvac.py:1205`). In `home_day`, `home_evening`, and `guest`, there is **no person-trust veto on the D1 vacancy path**. So a person who sits still through the 15-min vacancy grace during the day — with a live BLE phone in the zone that *would* confirm presence — can still be flipped to `away`, because the daytime path never consults the tracker.

- **Observed:** Zone-1 during `home_night` (the original v4.7.31 finding) — genuine D1 case: the master-bedroom room actually flapped vacant (mmWave-sole, the still body dropped past timeout).
- **NOT this gap — Zone-2 `home_day` (re-audited 2026-06-16):** the Zone-2 "away while occupied" was re-root-caused and is **NOT a D1 presence gap** — it is **D5 duty-cycle enforcement in COAST energy-mode** (`hvac.py:1165`: `if zone.runtime_exceeded and house_state != "sleep": away`). The room `occupied` bool was rock-solid (0 transitions/3h) while the AC duty-cycle thrashed the preset home↔away during the high-rate window. That is intentional thermal load-shedding, not a presence failure — do not "fix" it with a person-trust change. (A separate UX improvement would be to de-rate via setpoint instead of an `away` flip; not yet built.)
- **Symptom (D1 / Zone-1):** zone retreats to the relaxed `away` setpoint while someone is demonstrably in the room; returns to `home` once a sensor re-triggers.
- **Workaround today (D1):** raise `48 · Zone Vacancy Delay` so the grace outlasts typical still periods, or rely on the camera/multi-room sources keeping `any_room_occupied` true.
- **Note:** the D6 8-hour failsafe *does* honor BLE/camera confirmation in every non-sleep state — this gap is specific to the D1 vacancy path's trust veto, not the failsafe.

### Gap 2 — bare `hvac_mode→cool` drift not restored — ✅ FIXED in v5.5.2
*(historical — kept for context)* The arrester reverts on a **preset change to `manual`** (`hvac_override.py:659`); the old mode-restore loop only caught **`off`**. A thermostat whose `hvac_mode` drifted to `cool`/`heat` with an unchanged preset (e.g. set by the manufacturer's cloud app) was restored by **no** path.

**v5.5.2 fix:** the decision-cycle restore loop (`hvac.py::_apply_house_state_presets`) now enforces `heat_cool` on **any** non-heat_cool mode for heat_cool-capable zones (not just `off`), every cycle, wrapped in the suppress() handshake. Egress-paused (`off`) and AC-reset (`off`) zones are still skipped. **Behavioral note:** this also means a Safety-Coordinator emergency-heat (single-mode `heat` on a freeze) is reverted to `heat_cool` next cycle — intended (you run via ranges; heat_cool heats via the low setpoint). The queued `PLANNING_freeze_safety_range_shift.md` makes the freeze response range-based so even that is consistent.

Gap 1 remains a candidate for a future cycle; Gap 2 is resolved.

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
| `switch.ura_hvac_ac_ramp_master` | Switch | v4.5.11 |
| "28 · HVAC Predictive Conditioning" (uid `ura_hvac_pre_conditioning_enabled`) | Switch | **v5.4.0 NEW** — master gate for the WHOLE pre-conditioning chain (pre-cool/pre-heat/solar-banking/pre-arrival). `has_entity_name` derives the entity_id from device+name; match on uid |
| Egress Window HVAC Pause (uid `…_hvac_egress_window_pause`) | Switch | v4.7.8 |
| 48 · Zone Vacancy Delay (uid `…_hvac_vacancy_grace_minutes`) | Number | **v4.7.25** |
| 49 · Energy-Saving Vacancy Delay (uid `…_hvac_vacancy_grace_constrained`, ≤ #48) | Number | **v4.7.25** |
| 50 · Max Zone Occupied Time (uid `…_hvac_max_occupancy_hours`) | Number | **v4.7.25** |
| `button.ura_hvac_coordinator_reset_presence_timers` | Button | **v4.7.25** — reset presence timers to defaults |
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

---

## §6b. Energy Constraint Integration + WeatherProviderManager (v4.7.x Cycle A)

HVAC pre-cool likelihood (`sensor.ura_hvac_pre_cool_likelihood`) uses `forecast_high_temp` from the `EnergyConstraint` signal dispatched by the Energy Coordinator. As of v4.7.x Cycle A, this field continues to carry **raw forecast high** (°F dry-bulb) sourced via `WeatherProviderManager` — the same value as before, but now coming from the ranked-list manager instead of a single provider.

A new field `apparent_forecast_high_temp` was added additively to `EnergyConstraint`. HVAC does not yet consume this field — that migration is deferred to a future Cycle C ("Comfort Primitive Migration") per the plan. For now, HVAC pre-cool likelihood behavior is unchanged.

**What this means for you:** pre-cool likelihood numbers should remain stable post-v4.7.x deploy. If your primary weather provider goes stale or offline, the manager will automatically failover to the secondary/tertiary provider, so pre-cool continues to get a forecast high without intervention.
