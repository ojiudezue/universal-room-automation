# PLANNING v4.5.11 — AC Energy-Aware Ramp-Down + Observability

**Date:** 2026-05-10
**Type:** Tier 2 feature cycle
**Predecessor:** v4.5.10.1
**Pre-review baseline:** `pre-review-v4.5.11`

## Problem Statement

The existing AC Reset feature in `OverrideArrester` (`hvac_override.py:621-684`) detects the wrong failure mode for our climate. It triggers on `current_temperature > target_temp_high` while the unit is cooling — i.e., "AC running but room never reaches setpoint." That addresses undersized-AC / refrigerant-low scenarios.

The actual observed failure mode in this Texas install: **AC reaches setpoint, then keeps cooling and burning kWh past the natural cycle-end.** Manual observation 2026-05-10: AC2 hit setpoint, kept consuming >2 kWh past target before user manually forced `off→on` cycle. After manual reset, AC didn't ramp back up that night because the zone was holding temperature naturally.

Current detection never fires for this mode (current temp is *below* target, not above), so the controller silently wastes energy.

## Design Goals

1. **Detect overshoot + sustained energy waste**, not "can't reach setpoint."
2. **Soft-first action ladder.** A 1.5°F setpoint nudge gives the variable-speed Bryant compressor a smaller demand signal so it ramps down naturally — no compressor cycling.
3. **Hard reset retained as escalation only**, gated by daily cap + min interval, because rapid compressor cycling is the worst possible failure mode.
4. **kWh-aware as the primary gate.** Time-only triggers are too noisy for a variable-speed system that legitimately modulates near setpoint. Burning kWh past setpoint is the actual cost.
5. **Survives HA restart.** Daily counters, lockout flags, and in-flight nudge state must persist via SQLite — otherwise restart loops bypass the cap and fry the compressor.
6. **Full observability.** Every action logged. Every kWh-saved estimate visible. Every false-positive countable. Without this, we can't tell if the algorithm is working.
7. **End-user controls.** Master switch, per-zone enable, manual force/cancel/clear-lockout buttons. Defaults that preserve current behavior on first install (master = OFF).
8. **Don't break the existing Override Arrester.** This redesign only touches the AC Reset path inside `OverrideArrester`. Override grace/compromise/revert logic untouched.

## Architecture Overview

### Failure-mode flip

| | v4.5.10.1 (current) | v4.5.11 (new) |
|---|---|---|
| Trigger | `current_temp > target_temp_high` (still hot) | `current_temp <= target_temp_high - 0.5` AND `kwh_rate > threshold` debounced over 3 samples |
| Action | Hard reset: off → 60s → restore mode | Soft nudge: `target + 1.5°F` for 5min → restore |
| Escalation | None | After 1 failed nudge (10min observe, kwh still high), escalate to existing hard-reset logic |
| Daily cap | 2 hard resets/zone/day (in-memory, lost on restart) | 6 soft nudges + 2 hard resets per zone per day, persisted in SQLite |
| Min interval | None | 30 min between nudges, 2 hr between hard resets |
| Lockout | None | Per-zone, persists until midnight rollover; persistent notification |

### Three-layer gating model (matches v4.5.10 pattern)

| Layer | Control | Scope |
|---|---|---|
| Master | `Solar Cover Management`-style switch | House-wide on/off, default OFF |
| Per-zone | `ac_ramp_enabled` form field per room | Zone-level opt-out |
| Per-decision | overshoot + kWh + sustained-time gates | Per-action |

### Persistence (D4 + D10 SQLite tables)

Two new tables added to `database.py` following the existing `CREATE TABLE IF NOT EXISTS` pattern (no migration framework needed — confirmed via `database.py:349-1038` which already has 35+ tables built this way).

**`ac_reset_state`** — keyed by (zone_id, date). One row per zone per day. Counters reset by date-key (no cron):

```sql
CREATE TABLE IF NOT EXISTS ac_reset_state (
    zone_id TEXT NOT NULL,
    date TEXT NOT NULL,                          -- YYYY-MM-DD
    soft_nudge_count INTEGER DEFAULT 0,
    hard_reset_count INTEGER DEFAULT 0,
    last_soft_nudge_ts TEXT,                     -- ISO timestamp
    last_hard_reset_ts TEXT,                     -- ISO timestamp
    last_overshoot_ts TEXT,                      -- when current sustained-overshoot window started
    in_flight_nudge_original_target REAL,        -- so we can restore on restart
    in_flight_nudge_started_ts TEXT,             -- restart-detection
    lockout_flag INTEGER DEFAULT 0,
    PRIMARY KEY (zone_id, date)
);
```

**`ac_ramp_events`** — append-only log of every state transition. 30-day rolling retention (auto-prune):

```sql
CREATE TABLE IF NOT EXISTS ac_ramp_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,                     -- ISO
    event_type TEXT NOT NULL,                    -- detection_fired | nudge_started | nudge_restored
                                                 -- | nudge_evaluated | hard_reset_started | hard_reset_completed
                                                 -- | lockout_engaged | manual_override | cancel_invoked
    current_temp REAL,
    target_high REAL,
    kwh_rate_before REAL,
    kwh_rate_after REAL,                         -- NULL on the "before" event, populated on the "after" event
    action_taken TEXT,                           -- nudge_size, off_duration, etc.
    soft_nudge_count_today INTEGER,
    hard_reset_count_today INTEGER,
    lockout_triggered INTEGER DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_ac_ramp_events_zone_ts
    ON ac_ramp_events (zone_id, timestamp);
```

## Deliverables

### D1: Detection redesign — overshoot + sustained kWh-rate

**Replaces** `OverrideArrester.check_ac_reset` trigger condition (`hvac_override.py:651-656`).

New logic:
```python
# Overshoot: current cooled below the cooling setpoint
overshoot = (
    zone.hvac_action == "cooling"
    and zone.target_temp_high is not None
    and zone.current_temperature is not None
    and zone.current_temperature <= zone.target_temp_high - 0.5
)
if not overshoot:
    zone.last_overshoot_started = ""
    zone.kwh_samples_above_threshold = 0
    continue

# Read configured ac_load_sensor for this zone
kwh_rate = self._read_kwh_rate(zone)         # kW
if kwh_rate is None:
    continue                                  # graceful degrade — feature OFF for this zone

# Debounce: 3 consecutive samples above threshold
if kwh_rate > self._kwh_rate_threshold:
    zone.kwh_samples_above_threshold += 1
else:
    zone.kwh_samples_above_threshold = 0
    continue

if zone.kwh_samples_above_threshold < self._sustained_samples:
    continue

# Sustained-time gate: detection only fires after detection_time_gate minutes
# from the first overshoot sample
if not zone.last_overshoot_started:
    zone.last_overshoot_started = now.isoformat()
    continue
overshoot_minutes = (now - datetime.fromisoformat(zone.last_overshoot_started)).total_seconds() / 60
if overshoot_minutes < self._detection_time_gate:
    continue

# All gates passed → escalation entry
await self._handle_overshoot_detected(zone, kwh_rate)
```

**Acceptance Criteria:**
- **Verify:** `current == target` (at setpoint, modulating) → no detection fires (gap protects against flap)
- **Verify:** `current = target - 1.0` AND `kwh_rate = 0.3 kW` (efficient overshoot) → no detection
- **Verify:** `current = target - 1.0` AND `kwh_rate = 1.2 kW` for 3 samples + 10min sustained → detection fires
- **Verify:** `ac_load_sensor` unset for zone → feature short-circuits OFF, no false trigger
- **Verify:** sensor returns `unavailable` / `None` → graceful skip, no crash
- **Test:** `test_v4511_detection_*` — 8 unit tests
- **Live:** force a setpoint above current → 30 min later detection fires (visible in `sensor.ura_hvac_ac_ramp_state_<zone>`)

### D2: Soft nudge action — setpoint + restore

New methods on `OverrideArrester`:

```python
async def _perform_soft_nudge(self, zone: ZoneState, kwh_rate_before: float) -> None
async def _restore_after_nudge(self, zone: ZoneState) -> None
async def _evaluate_nudge_outcome(self, zone: ZoneState, kwh_rate_before: float) -> None
```

Restore handler scheduled via `async_call_later` (matches existing pattern at `hvac_override.py:194` etc.). Restore callback unsubscribe stored in `self._nudge_restore_timers: dict[str, CALLBACK_TYPE]`.

**Restart safety:** before scheduling restore, write `in_flight_nudge_original_target` + `in_flight_nudge_started_ts` to `ac_reset_state`. On `OverrideArrester.async_startup_audit` (or new `async_startup_nudge_audit`), check for any zone with non-NULL `in_flight_nudge_original_target` and either:
- If restart was within nudge_duration: schedule restore for the remaining time
- If restart exceeded nudge_duration: restore immediately

After restore completes, write `nudge_restored` event + clear in_flight fields.

**Acceptance Criteria:**
- **Verify:** `target_temp_high` goes from 73 → 74.5 (default 1.5°F) when nudge fires
- **Verify:** `target_temp_high` returns to 73 after `nudge_duration` minutes (default 5)
- **Verify:** HA restart 2 minutes into a 5-minute nudge → on coordinator init, restore schedules for the remaining 3 minutes (not 5)
- **Verify:** HA restart 10 minutes into a 5-minute nudge → restore fires immediately on init
- **Verify:** `soft_nudge_count` increments + persists; visible in `sensor.ura_hvac_ac_nudges_today`
- **Test:** `test_v4511_soft_nudge_*` — 6 tests including restart-during-nudge scenarios
- **Live:** trigger via force-nudge button → observe target change in HA dev tools, restore 5 min later

### D3: Hard reset escalation — single-nudge then escalate

After a soft nudge restores, schedule an evaluation `nudge_duration + 10min` later. If `kwh_rate > kwh_rate_threshold` still holds at evaluation time → escalate to hard reset.

Hard reset reuses existing `_perform_ac_reset` (`hvac_override.py:686-727`) and `_restore_after_reset` (`hvac_override.py:729-831`) — both already have verify+retry logic for the off→restore lifecycle. Only the gating wrapper changes.

Pre-flight gates before `_perform_ac_reset`:
1. `hard_reset_count_today < hard_reset_daily_limit` (default 2)
2. `last_hard_reset_ts` is NULL OR `(now - last_hard_reset_ts) >= hard_reset_min_interval` (default 120 min)
3. `lockout_flag != 1`

If gates fail → write `lockout_engaged` event (if cap hit), set `lockout_flag = 1`, fire persistent notification (D6).

**Acceptance Criteria:**
- **Verify:** if kwh_rate dropped after nudge → no escalation (false-positive counter increments)
- **Verify:** daily cap respected across HA restart (tag a zone with hard_reset_count = 2 in DB, restart, verify 3rd attempt blocked)
- **Verify:** min-interval respected across HA restart (tag last_hard_reset_ts = now-30min, restart, verify hard reset blocked until 90min later)
- **Verify:** when daily cap hit, persistent notification fires + `lockout_flag` set; `clear_lockout` button clears
- **Test:** `test_v4511_escalation_*` — 8 tests
- **Live:** force 2 hard resets manually via SQL update, verify 3rd attempt blocked + notification visible

### D4: Persistent state — `ac_reset_state` table

**Acceptance Criteria:**
- **Verify:** table created on first init after deploy (no migration version split)
- **Verify:** counters survive HA restart
- **Verify:** new day rolls over counters automatically (date-keyed query returns 0 for new date — no explicit reset needed)
- **Verify:** in-flight nudge state restored correctly on restart per D2
- **Test:** `test_v4511_persistence_*` — 5 tests
- **Live:** check DB row exists after first nudge: `sqlite3 ... "SELECT * FROM ac_reset_state"`

### D5: Number entities + per-zone form field

**6 house-wide Number entities** added to URA: HVAC Coordinator device via the existing `_hvac_tunable_number_factory` from v4.5.10:

| Entity | Range | Default | Step | Unit |
|---|---|---|---|---|
| AC Nudge Size | 0.5–3.0 | 1.5 | 0.5 | °F |
| AC Nudge Duration | 1–15 | 5 | 1 | min |
| AC Sustained Samples | 2–10 | 3 | 1 | — |
| AC Detection Time Gate | 5–30 | 10 | 1 | min |
| AC Hard Reset Daily Limit | 0–5 | 2 | 1 | — |
| AC Hard Reset Min Interval | 30–360 | 120 | 30 | min |

**Per-zone Number entity** (one per AC zone — for this install: 3 sliders for 3 AC zones, but generalized to N):

| Entity | Range | Default | Step | Unit |
|---|---|---|---|---|
| AC kWh Rate Threshold (`<zone>`) | 0.3–3.0 | **0.8** (3-ton heuristic) | 0.1 | kW |

Per-zone threshold is the only slider that's tightly coupled to AC tonnage — keep the rest house-wide because nudge behavior + cap policy should be uniform across zones (tuning multiple values per zone is a UX trap when only one variable actually depends on hardware).

**Default-tuning recommendation** for this install (manual post-deploy adjustment):
- AC zones backed by 3-ton units: leave at 0.8 kW
- AC zone backed by 4-ton unit: raise to 1.0 kW

Uses the sizing heuristic `threshold ≈ 25-30% of rated_kw` (compressor minimum modulation floor — anything above that at setpoint is energy that should be ramping down but isn't).

All RestoreEntity-backed; URA mirror pattern (form value = install-time seed; slider = runtime source of truth). 10 new CONFs + DEFAULTS in `hvac_const.py` (the per-zone CONF follows existing per-zone naming convention from `hvac_const.py:22` — pattern `hvac_zone_{n}_kwh_rate_threshold`).

**Per-zone storage:** threshold pushed to `ZoneState.kwh_rate_threshold` field on slider change via a per-zone factory variant. Detection logic reads `zone.kwh_rate_threshold` instead of `self._kwh_rate_threshold`.

**1 new room-level form field** in the room config flow:

- `ac_load_sensor` — entity-picker filtered to `sensor` domain with `device_class: power` or `device_class: energy`. Optional. When unset, ramp-down feature is OFF for that zone (graceful degrade).

**Acceptance Criteria:**
- **Verify:** all 6 house-wide Number entities appear post-restart
- **Verify:** N per-zone kWh threshold sliders appear (1 per AC zone, e.g., 3 for this install)
- **Verify:** changing a per-zone slider only affects that zone's detection (not house-wide)
- **Verify:** sliders persist across restart (RestoreEntity)
- **Verify:** room config flow shows ac_load_sensor field; selection saves and reads back
- **Verify:** v4.5.10.1 AST-walk import test still passes (regression guard)
- **Test:** `test_v4511_entities_*` — 14 house-wide tests + 4 per-zone-isolation tests = 18
- **Live:** confirm 6 house-wide + 3 per-zone sliders show; tune the **zone-1** threshold to 1.0 kW post-deploy (**zone 1 is the 4-ton unit**); restart; value preserved
  <br>*(corrected 2026-08-21 — this line originally read "zone-3 … (4-ton unit)", which is FALSE. See the correction note below.)*

> **⚠️ CORRECTION 2026-08-21 — the line above has been FIXED IN PLACE.**
> It originally said zone **3** was the 4-ton unit. It is not. Operator (authoritative oracle for hardware
> facts, 2026-08-20): **zone 1 is the 4-ton; zones 2 and 3 are 3-ton.** The
> tonnage-based 0.8 / 1.0 scheme in this section was never applied in production
> either — live values are 1.3 / 1.3 / 1.2, tuned by observation. Operator on the
> 0.8 default: *"Arbitrary. Do better if you can."*
> **Why this one was dangerous:** it is a *live acceptance criterion*, so it reads
> as already-verified. A planning doc is authoritative for code and decisions,
> **never for physical facts about the house** — those have exactly one oracle,
> the operator or a measurement.
> See memory `reference-hvac-zone-tonnage` for the number-vs-name tuning trap.

### D6: Lockout notification + day rollover

When `hard_reset_count == hard_reset_daily_limit`, fire `persistent_notification.create` with zone-specific message. Set `lockout_flag = 1` in DB.

```
Title: "AC Ramp Lockout: <zone_name>"
Message: "AC <zone_name> hit max hard resets today (<N>). Controller may need
         manual investigation. Resets resume tomorrow. Use the Clear Lockout
         button if this was a false positive."
notification_id: f"ura_ac_ramp_lockout_{zone_id}"
```

`notification_id` per zone = no spam (HA dedupes by id). Auto-clears on date rollover because the next day's row has `lockout_flag = 0`.

**Acceptance Criteria:**
- **Verify:** notification fires exactly once per zone per day
- **Verify:** notification text identifies zone + reset count
- **Verify:** new day → no stale lockout notification (notification_id persists in HA but new-day query returns lockout_flag=0)
- **Test:** `test_v4511_lockout_*` — 3 tests

### D7: Per-zone state sensors (live status)

3 sensors per AC zone (added to `sensor.py` setup). Reads from `ZoneState` + `OverrideArrester._nudge_in_flight_zones`:

| Sensor | States | Source |
|---|---|---|
| `sensor.ura_hvac_ac_ramp_state_<zone>` | `idle` / `detecting` / `nudging` / `awaiting_evaluation` / `escalating` / `locked_out` | OverrideArrester state |
| `sensor.ura_hvac_ac_ramp_last_action_<zone>` | ISO timestamp; attrs: action_type, kwh_rate_before, kwh_rate_after | DB latest event |
| `sensor.ura_hvac_ac_ramp_kwh_rate_<zone>` | float kW (live) | configured `ac_load_sensor` state |

**Acceptance Criteria:**
- **Verify:** state transitions visible in HA history during live overshoot
- **Verify:** sensors survive restart (DB-backed)
- **Test:** 6 tests including state-machine + restart restoration

### D8: Daily / cumulative impact sensors (efficacy)

| Sensor | Unit | Source |
|---|---|---|
| `sensor.ura_hvac_ac_nudges_today` | count | sum(soft_nudge_count) for today across zones |
| `sensor.ura_hvac_ac_resets_today` | count | sum(hard_reset_count) for today across zones |
| `sensor.ura_hvac_ac_kwh_avoided_today` | kWh | computed (see math) |
| `sensor.ura_hvac_ac_kwh_avoided_total` | kWh, persistent | running sum since feature enabled |
| `sensor.ura_hvac_ac_false_positive_rate` | % | (nudges with kwh_after >= kwh_before) / total_nudges |

**kWh-avoided math** (rough estimate — flagged as such in entity description AND tech debt):

```
On nudge_started: capture kwh_rate_before
On nudge_restored + 5min settle: capture kwh_rate_after
delta_kw = max(0, kwh_rate_before - kwh_rate_after)
estimated_remaining_overshoot_minutes = min(30, current_overshoot_minutes_at_nudge)
kwh_avoided_this_event = delta_kw * (estimated_remaining_overshoot_minutes / 60)
```

If `delta_kw <= 0`: credit zero AND increment false_positive_count.

**Tech debt note** (added to `docs/TECH_DEBT.md`):

> v4.5.11 kWh-avoided estimate uses point-in-time delta × capped 30-min projection. Not baseline-matched against comparable-day data. Acceptable for trend-watching ("did we save anything this month?"), NOT for billing accuracy or true comparable-day analytics. Revisit when Span historical API gives us baseline-day matching.

**Acceptance Criteria:**
- **Verify:** kwh_avoided is non-negative
- **Verify:** false_positive sensor increments when nudge had no effect
- **Verify:** values persist across restart (cumulative_total reads from DB sum)
- **Test:** 8 tests including math + restart

### D9: Manual controls

| Control | Type | Behavior |
|---|---|---|
| `switch.ura_hvac_ac_ramp_master` | Switch | House-wide kill-switch; default OFF on first install |
| `ac_ramp_enabled` per room | Form bool | Per-zone opt-out; default ON when feature is master-on |
| `button.ura_hvac_ac_ramp_force_nudge_<zone>` | Button | Force a nudge now. **Respects master switch** (off=blocked). **Ignores daily caps** (so it counts toward day's budget but doesn't block). Used for testing. |
| `button.ura_hvac_ac_ramp_cancel_<zone>` | Button | Abort in-flight nudge, restore original target immediately |
| `button.ura_hvac_ac_ramp_clear_lockout_<zone>` | Button | Reset that zone's counters today + clear lockout_flag |

**Three-layer gating verified at every detection cycle.**

**Acceptance Criteria:**
- **Verify:** master OFF → no zone acts (force_nudge button blocked too)
- **Verify:** master ON, per-room OFF → that zone skipped
- **Verify:** force_nudge increments soft_nudge_count_today (counts toward budget for observability)
- **Verify:** cancel button aborts in-flight nudge within 1s + restores target
- **Verify:** clear_lockout resets only that zone's counters
- **Test:** 9 tests covering all 5 controls + 3-layer gating

### D10: Event log + diagnostic dump

`ac_ramp_events` table (schema in Architecture Overview).

`button.ura_hvac_ac_ramp_diagnostic_dump` — when pressed:
1. Query last 7 days from `ac_ramp_events`
2. Write to `/config/ura_diagnostics/ac_ramp_<ISO_timestamp>.json`
3. Fire `persistent_notification` with file path
4. (Honors `docs/diagnostics/` workflow — directory may already exist per gitStatus)

**30-day retention:** during daily-rollover query (when D4 reads/writes ac_reset_state for a new date), also issue `DELETE FROM ac_ramp_events WHERE timestamp < datetime('now', '-30 days')`. Bounded growth.

**Acceptance Criteria:**
- **Verify:** every state transition writes a row
- **Verify:** dump button creates parseable JSON file
- **Verify:** rows older than 30 days auto-pruned
- **Test:** 6 tests

### D11: HC + EC user manuals

Two new task-oriented documentation files. Not changelogs. Written for the user reading them six months from now while trying to remember what every slider does.

**`docs/user-manual/HVAC_COORDINATOR.md`** (~3000-5000 words):
- Overview: what HVAC Coordinator does, decision cycle cadence
- Master switches: AC Ramp Master, Solar Cover Management, Per-Zone HVAC Control, Vacancy Auto-Off — what each kills
- Number entities: every entity from v4.5.10 (Cover Close Threshold, Cover Close Temp, etc.) + v4.5.11 (7 AC Ramp sliders) — what does it do, when to change it, default rationale, what to watch after changing
- Form fields: per-room HVAC + cover settings, ac_load_sensor field
- Sensors: ramp_state, kwh_avoided, false_positive_rate — how to read
- Three-layer gating model (cover management + AC ramp)
- Troubleshooting recipes:
  - "AC kept cooling past setpoint" → check ac_load_sensor, kwh_rate_threshold, sustained_samples
  - "Lockout fired but it was a false positive" → clear_lockout button, then tune threshold up
  - "Nudges fire too often" → raise kwh_rate_threshold or sustained_samples
  - "Nudges never fire but I see waste" → lower threshold; check kWh sensor freshness
- kWh-avoided methodology with rough-estimate caveat

**`docs/user-manual/ENERGY_COORDINATOR.md`** (~3000-5000 words):
- Overview: what EC does (battery strategy, arbitrage, solar surplus, EV mutual-exclusion)
- Battery strategy: SOC floors (charge / discharge), arbitrage windows, EV mutual-exclusion (v4.5.0 redesign)
- Solar banking: SOC threshold, banking floor, banking offset
- Grid charging: charge windows, rates, exclusions
- Number entities: every EC slider — what / when / default / what to watch
- Form fields: per-EC config
- Sensors: arbitrage state, battery_power, solar surplus, etc.
- Troubleshooting recipes per common symptom
- Architecture sketches: arbitrage decision flow, EV mutual-exclusion logic

**Acceptance Criteria:**
- **Verify:** every Number entity on URA: HVAC Coordinator + URA: Energy Coordinator devices is documented (cross-check: every CONF in hvac_const.py + energy_const.py appears in the manual)
- **Verify:** every Switch is documented
- **Verify:** every troubleshooting recipe references the actual sensor/entity to inspect
- **Test:** Test scaffolding parses each `## ` section heading and asserts coverage of all CONF_* keys in the corresponding const file. (~4 meta-tests.)

## Files Touched (estimated)

| File | LoC | What |
|---|---|---|
| `domain_coordinators/hvac_override.py` | ~400 | D1-D3, D6, restart audit for nudge state |
| `domain_coordinators/hvac_const.py` | ~30 | 10 new CONFs + DEFAULTS |
| `domain_coordinators/hvac_zones.py` | ~40 | New ZoneState fields: kwh_samples_above_threshold, last_overshoot_started, in_flight_nudge_original_target, kwh_rate_threshold (per-zone) |
| `database.py` | ~80 | 2 new tables + retention DELETE |
| `domain_coordinators/hvac.py` | ~50 | Wire D5 sliders + D9 master switch into OverrideArrester init/runtime |
| `number.py` | ~110 | 6 house-wide factory invocations + per-zone factory variant (× N AC zones) |
| `switch.py` | ~30 | Master switch + per-zone enable mirroring |
| `button.py` | ~80 | 3 new button entities × N zones + diagnostic dump button |
| `sensor.py` | ~150 | 3 per-zone state sensors + 5 house-wide impact sensors |
| `config_flow.py` | ~30 | ac_load_sensor field + ac_ramp_enabled per-room form |
| `strings.json` + `translations/en.json` | ~60 | All new entity labels + helper text |
| `quality/tests/test_v4511_*.py` | ~700 | ~70 tests |
| `docs/user-manual/HVAC_COORDINATOR.md` | new | ~3000-5000 words |
| `docs/user-manual/ENERGY_COORDINATOR.md` | new | ~3000-5000 words |
| `docs/TECH_DEBT.md` | ~10 | kWh-avoided rough-estimate caveat |

**Total:** ~1400 LoC production + ~700 LoC tests + ~6000-10000 words docs.

## Risks + Critique Targets for Code Review

| ID | Risk | Mitigation |
|---|---|---|
| R1 | Restart-during-nudge leaves +1.5°F drift | DB-persisted in_flight_nudge_original_target + startup audit on coordinator init |
| R2 | Day rollover at 11:59 → counter resets → second hard reset 3min later | Min-interval gate (default 2hr) protects compressor even if daily cap allows |
| R3 | kWh sensor goes stale → kwh_rate stuck → no detection ever fires | Acceptable graceful degrade. Log warning every 6 hours when sensor `last_updated > 10min` ago. |
| R4 | Bryant doesn't respond to 1.5°F nudge | Acceptable — escalation to hard reset still fires. 1-week observation period before tuning. Slider is runtime so no redeploy needed. |
| R5 | 30-min cap on kWh-avoided projection underestimates wins | Acceptable for v4.5.11 (tech debt note). Revisit with Span historical data. |
| R6 | False-positive rate calculation includes manual force_nudge events that legitimately had no overshoot | Exclude `manual_override` events from false-positive math. |
| R7 | DB writes inside detection cycle could slow decision tick | Use existing async DB pattern from database.py; writes are ~5ms. Profile if cycle exceeds budget. |
| R8 | Zone with multiple ac_load_sensor candidates (room shares circuit with non-AC load) | Per-zone field — user is responsible for pointing at AC-only sensor. Documented in HC user manual. |
| R9 | Master switch state collision with v4.5.10 Solar Cover Management switch (similar pattern) | Reuse the v4.5.10 switch factory pattern (`_ec_switch_factory`-style) but with separate CONF + entity_id |

## Bug-Class Watch (from QUALITY_CONTEXT.md)

Specifically guard against:
- **#7 Stale data source:** kwh_rate read must check `state.last_updated` freshness
- **#22 Enum mismatch:** state machine state strings (`idle` / `detecting` / etc.) must be defined as a Final dict and asserted in tests
- **#23 Observation mode gating:** force_nudge button must respect master switch (kill-switch contract)
- **#32 Form field with no runtime reader:** every new CONF gets a 4-layer test (defined / in form / read in init / accepted as kwarg) — same as v4.5.10
- **#33 Partial fix — sibling helpers skipped:** when adding new state to ZoneState, audit all reset paths (midnight rollover, manual reset, etc.)

## Live Validation Plan (Post-Deploy)

1. **Immediate post-restart:**
   - URA: HVAC Coordinator device shows: 1 new master switch + 7 new Number entities + 5 new house-wide sensors
   - Each AC zone has 3 new state sensors + 3 new buttons
   - Coordinator Manager → Per-Room HVAC step shows new ac_load_sensor + ac_ramp_enabled fields
   - Master switch is OFF by default
   - Zero new ERRORs in HA log
   - DB has new tables: `sqlite3 ... ".schema ac_reset_state"` + `".schema ac_ramp_events"`

2. **Master switch flip-test:**
   - Toggle master ON
   - For each zone, set `ac_load_sensor` to its corresponding Span circuit sensor
   - Wait for next decision cycle, observe `ramp_state` sensor transitions

3. **Force-nudge test:**
   - Press force_nudge button for zone X
   - Verify target_temp_high increases by 1.5°F in HA dev tools
   - Wait 5 min
   - Verify target_temp_high restored
   - Verify `ac_nudges_today` sensor incremented
   - Verify event row in `ac_ramp_events`

4. **Cancel test:**
   - Press force_nudge, then immediately press cancel
   - Verify target_temp_high restored within 1 second

5. **Lockout simulation:**
   - SQL update: `UPDATE ac_reset_state SET hard_reset_count = 2 WHERE zone_id = ? AND date = today`
   - Trigger detection (force kwh_rate above threshold)
   - Verify lockout notification fires
   - Press clear_lockout, verify notification cleared and counter reset

6. **Restart-during-nudge:**
   - Press force_nudge
   - 30 seconds in, restart HA
   - Verify on restart: target_temp_high returns to original within 30s of coordinator init

## Test Count Target

- v4.5.10.1: 93 tests, 0 isolated failures
- **v4.5.11 target: ~163** (+70), 0 isolated failures across 60 files

## Documents

- This plan: `docs/planning/PLANNING_v4.5.11_ac_energy_aware_ramp_down.md`
- Review (post-build): `docs/reviews/code-review/v4.5.11_review.md`
- README (pre-deploy): `docs/readmes/README_v4.5.11.md`
- User manuals (D11): `docs/user-manual/HVAC_COORDINATOR.md` + `ENERGY_COORDINATOR.md`
- Tech debt: append to `docs/TECH_DEBT.md` (creating if not present)
- VibeMemo entry 011

## Out of Scope (Explicit Non-Goals)

- True baseline-matched kWh-avoided analytics (deferred per tech debt note)
- Multi-circuit AC load aggregation (per-zone single-sensor only; user can sum externally if needed)
- Heating-mode equivalent (this cycle is cool-only; heating overshoot is a different failure mode)
- Bryant-specific ramp control (no service surface exists; revisit if Bryant integration adds one)
- v4.5.10 cover-livability L2-L7 (already deferred to backlog from v4.5.9 plan)

## Plan-Completion Tracking

Per CLAUDE.md mandate, every planned item is explicitly accounted for here:

### Shipped in v4.5.11 (slice 1)

| Deliverable | Status |
|---|---|
| D1 — Detection redesign | ✅ Shipped |
| D2 — Soft nudge action (with R1 restart-safe ordering) | ✅ Shipped |
| D3 — Hard reset escalation (with R2 day-rollover-safe min-interval) | ✅ Shipped |
| D4 — SQLite tables + helper methods | ✅ Shipped |
| D5 — Number entities (6 house-wide + per-zone × N) + zone_hvac form fields | ✅ Shipped |
| D6 — Lockout + persistent notification | ✅ Shipped |
| D9 master switch | ✅ Shipped |
| D9 per-zone buttons (force / cancel / clear_lockout) | ✅ Shipped |
| D10 retention prune + event log table | ✅ Shipped (dump button deferred — see below) |

### Deferred to v4.5.12 (slice 2)

| Deliverable | Why deferred | Tracked where |
|---|---|---|
| **D7** — Per-zone state sensors (ramp_state, last_action, kwh_rate live) | Need 1 week of slice-1 field data to design useful state-machine sensor semantics. Without observation, we'd guess at what state transitions matter to surface. | v4.5.12 planning doc (TBD) |
| **D8** — House-wide impact sensors (nudges_today, kwh_avoided, false_positive_rate) | Needs slice-1 data to validate kWh-avoided estimate accuracy before exposing as a user-facing number. Premature exposure of a wrong number is worse than no number. | v4.5.12 planning doc (TBD); tech debt note (docs/TECH_DEBT.md) for the rough-estimate caveat |
| **D10 dump button** | Event log table + retention IS shipped. Only the user-facing diagnostic dump button is deferred. SQL access via `sqlite3` covers slice-1 needs. | v4.5.12 planning doc (TBD) |
| **D11** — HC + EC user manuals (~6000-10000 words) | Slice-1 ships features that need 1 week of real behavior before we write user-facing docs about them. Better to document what the system actually does than what we modeled. EC manual not blocked by slice-1 but bundled for cycle efficiency. | v4.5.12 planning doc (TBD) |

### Why slice/2 split

User direction: "2. Is fine. I'm relying on the 2x review to spot check so just follow our quality protocols and don't skimp." (where 2 = ship two slices: safety first, observability second).

Slice 1 ships the compressor-protection critical path. Slice 2 wraps observability around 1 week of field data. This is the "minimum viable safety + iterate on observability" pattern. Documented in VibeMemo entry 011.
