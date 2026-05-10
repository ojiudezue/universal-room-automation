# v4.5.11 — AC Energy-Aware Ramp-Down (slice 1)

**Date:** 2026-05-10
**Type:** Tier 2 feature cycle (slice 1 of 2 — observability + manuals deferred to v4.5.12)
**Predecessor:** v4.5.10.1
**Reproducer:** 2026-05-10 manual observation — AC2 reached cooling setpoint, continued drawing >2 kWh past setpoint before user manually forced off→on. v3.8.3 AC Reset detection (`current > target`) never fires for this dominant Texas-summer waste pattern.

## Summary

Replaces the legacy AC Reset trigger (`current > target` — "AC can't reach setpoint", undersized-AC failure) with an energy-aware overshoot detector (`current <= target - 0.5°F AND kWh-rate sustained > threshold` — "AC reached setpoint but kept burning"). Adds a soft setpoint nudge action before the hard reset escalation path, with compressor-protection gates (daily cap + global min-interval) that survive HA restart.

**Master switch defaults OFF on first install** — feature is invasive (changes setpoints, can cycle compressors). User opts in after configuring per-zone `ac_load_sensor`.

## What's new

### Detection — energy-aware overshoot

9-gate detector in `OverrideArrester.check_ac_reset`:

1. Master kill-switch (`_ramp_master_enabled`)
2. Per-zone enable (`zone.ramp_zone_enabled`)
3. `ac_load_sensor` configured (else feature OFF for that zone)
4. HVAC action = cooling, valid temps known
5. Lockout flag not set (per zone per day)
6. **Overshoot:** `current <= target_temp_high - 0.5°F`
7. **kWh debounce:** rate exceeds zone-specific threshold for N consecutive samples (default 3)
8. **Time-sustained:** overshoot window held for `detection_time_gate` minutes (default 10)
9. Not already mid-nudge or mid-evaluation

All gates AND. Any failure → skip zone for this cycle.

### Action ladder — soft first, hard if needed

| Stage | Action | Daily cap | Min interval |
|---|---|---|---|
| Soft nudge | `target + 1.5°F` for 5 min, then restore | 6/day (informational only) | none |
| Evaluation | 10 min post-restore, re-read kWh rate | — | — |
| Hard reset | `off → 60s → restore_mode` (existing v3.18.x path) | **2/day** | **120 min** |

Decision rule: if `kwh_after >= kwh_before * 0.85`, nudge ineffective → escalate. 15% tolerance for natural fluctuation.

### Compressor protection (the load-bearing pieces)

- **Daily cap on hard resets** persists in SQLite (`ac_reset_state` table keyed by `(zone_id, date)`). Survives HA restart so restart loops can't bypass the cap.
- **Global min-interval gate** queries `MAX(last_hard_reset_ts)` without date filter, so day-rollover at 23:55 → 00:02 can't fire 2 resets in 7 minutes. Bug Class #2 catch from review 2.
- **Lockout flag** when cap hit. Persistent notification (deduped per zone). Auto-clears at midnight rollover.
- **Restart-during-nudge** safety: DB write happens BEFORE the `climate.set_temperature` service call. A crash between them leaves a benign no-op-restore record. The startup audit (`async_startup_ramp_audit`) reads in-flight rows on first decision cycle and either resumes the timer for remaining time or restores immediately if expired.

### Entities added

**Per-install (URA: HVAC Coordinator device):**
- 1 Switch — `switch.ura_hvac_ac_ramp_master` (default OFF)
- 6 Number sliders: Nudge Size, Nudge Duration, Sustained Samples, Detection Time Gate, Hard Reset Daily Limit, Hard Reset Min Interval

**Per AC zone** (3 for this install: 2× 3-ton + 1× 4-ton):
- 1 Number: AC kWh Rate Threshold (default 0.8 kW; raise to 1.0 for the 4-ton)
- 3 Buttons: Force AC Nudge, Cancel AC Nudge, Clear AC Ramp Lockout

**New zone form fields** (in Zone Manager → zone → 🌡️ Zone HVAC):
- AC Load Sensor (kW or kWh) — entity-picker filtered to `device_class: power | energy`
- AC Ramp-Down enabled for this zone — boolean (default ON, gates per-zone)

### Architecture

Three-layer gating model (matches v4.5.10 Solar Cover Management):

| Layer | Control | Default |
|---|---|---|
| **Master** | `Solar Cover Management`-style Switch | **OFF** on first install |
| **Per-zone** | `ac_ramp_zone_enabled` form field | **ON** when feature is master-on |
| **Per-decision** | 9-gate detector + caps | always evaluated |

### Persistent SQLite state

Two new tables in `database.py`:

- `ac_reset_state` — keyed by `(zone_id, date)`. Counters (`soft_nudge_count`, `hard_reset_count`), timestamps, in-flight nudge state, lockout flag. Day-rollover handled by date-keyed queries (no cron needed).
- `ac_ramp_events` — append-only log of every state transition. 10 event types: `detection_fired`, `nudge_started`, `nudge_restored`, `nudge_evaluated`, `hard_reset_started`, `hard_reset_completed`, `lockout_engaged`, `manual_override`, `cancel_invoked`, `startup_restore`. 30-day rolling retention (auto-prune at day rollover).

## What's NOT in this slice (deferred to v4.5.12)

- D7 — Per-zone state sensors (ramp_state, last_action, kwh_rate live read)
- D8 — House-wide impact sensors (nudges_today, kwh_avoided_today, false_positive_rate)
- D10 — Diagnostic-dump button (events are loggable via SQL query for now)
- D11 — HC + EC user manuals

**Why split:** the compressor-protection critical path is the safety-essential piece; observability is critical for tuning but not safety. v4.5.11 ships the protection now so we can run real-world data; v4.5.12 wraps observability + docs around what we learn after 1 week.

Documented in `docs/planning/PLANNING_v4.5.11_ac_energy_aware_ramp_down.md` ("Out of Scope" + plan-completion tracking section).

## Tier 2 Review

Pre-review baseline: `pre-review-v4.5.11`.

Two reviews (Core A bug-class adversarial + Core B race/lifecycle) in `docs/reviews/code-review/v4.5.11_review.md`.

| Severity | Found | Fixed | Deferred (accepted) |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 1 | 1 | 0 |
| MEDIUM | 1 | 1 | 0 |
| LOW | 3 | 0 | 3 |

**HIGH-1:** `cleanup_ac_ramp_events` cutoff used `dt_util.utcnow()` while row timestamps use `dt_util.now()` — text compare mismatch at retention edges (Bug Class #11). Fixed: cutoff now also uses `dt_util.now()`.

**MEDIUM-1:** Legacy `ENTRY_TYPE_ZONE` discovery fallback didn't read v4.5.11 form fields (Bug Class #33 — partial fix). Single-user URA doesn't use this path today, but fixed for consistency.

LOW findings (3) accepted as design trade-offs — full reasoning in review doc.

**Verdict: APPROVED for deploy.**

## Regression catch: AST-walk import resolution

The v4.5.11 test file's `TestImportResolution` AST-walks every `from .` import across number.py, switch.py, button.py, hvac_override.py and confirms each imported symbol is actually defined in the target module.

**This test caught a real bug during v4.5.11 build:** `_discover_ac_zones` (in both number.py + button.py) imported `CONF_ZONE_THERMOSTAT` from `domain_coordinators.hvac_const`, but the constant lives in `const.py`. Import would have failed at runtime — same shape as the v4.5.10 ImportError class (`SIGNAL_HVAC_ENTITIES_UPDATE`) that shipped to live HA.

Recommended for QUALITY_CONTEXT.md: promote AST-walk to a project-wide regression hook.

## Tests

139 new tests in `quality/tests/test_v4511_ac_energy_aware_ramp_down.py`:

- **Schema (6):** tables, indexes, in-flight columns, triggered_by column, batched retention, R2-safe global query
- **DB helpers (12 parametrized):** every public method on UniversalRoomDatabase
- **Critical DB properties (3):** R2 no-date-filter, R6 exclude-manual, batched DELETE
- **Constants (parametrized × 9 defaults + parametrized × 10 CONF keys + 6 misc):** 25 const tests
- **ZoneState fields (parametrized × 10):** all v4.5.11 fields present
- **Zone discovery wiring (4):** ac_load_sensor + ramp_zone_enabled in both primary + merge paths
- **Detection logic (8):** every gate, overshoot threshold, debounce, lockout
- **kWh reader (5):** staleness, watts unit, unavailable handling, rate-limited warning
- **Soft nudge (7):** **R1 ordering test (DB before setpoint)**, R11 suppression order, restore scheduled, event logged, counter incremented
- **Hard reset escalation (8):** 85% threshold, daily cap, R2 global min-interval, lockout at cap, reuses _perform_ac_reset
- **Lockout (4):** unique notification_id, event with flag, dismiss on clear
- **Startup audit (5):** R1 audit method + 4 sub-paths
- **Number entities (13 parametrized + 5 misc):** 6 house-wide + per-zone factory + discovery
- **AST import resolution (4):** number.py + switch.py + button.py + hvac_override.py
- **Master switch (4):** class, label, registered, default-off, cancel-on-off
- **Per-zone buttons (6 parametrized + 4 misc):** factory + 3 actions × routing
- **Form fields (6):** zone_hvac schema + strings + translations
- **HVAC integration (3):** set_database wired + startup audit called
- **Teardown (1):** timer cancellation
- **Plan completion (2):** planning doc exists + lists all D1-D11

**Test count progression:**
- v4.5.10.1: 93 tests, 0 isolated failures
- **v4.5.11: 232** (93 + 139), 0 isolated failures across modified surface

## Live validation plan (post-restart)

1. **Immediate:**
   - URA: HVAC Coordinator device shows: 1 new master switch (OFF) + 6 new house-wide Number sliders
   - Per AC zone: 1 new kWh threshold Number + 3 new buttons (Force Nudge, Cancel Nudge, Clear Lockout)
   - Zone Manager → each zone → 🌡️ Zone HVAC step shows new "AC Load Sensor" + "AC Ramp-Down enabled" fields
   - Zero new ERRORs in HA log
   - DB has new tables: `sqlite3 ~/ha-config/universal_room_automation/data/universal_room_automation.db ".schema ac_reset_state"` + `".schema ac_ramp_events"`

2. **Configure per-zone sensors:**
   - For each AC zone: set `ac_load_sensor` to the Span panel circuit sensor for that AC
   - For the 4-ton AC: raise the AC kWh Rate Threshold slider from 0.8 → 1.0 kW
   - Leave the 3-ton ACs at 0.8 kW default

3. **Master switch flip-test:**
   - Toggle master switch ON
   - Wait for next decision cycle (5 min)
   - Observe state via `sqlite3 ... "SELECT * FROM ac_reset_state"` — should show fresh date-keyed rows for each zone as decisions evaluate

4. **Force-nudge test:**
   - Press Force AC Nudge button for one zone
   - Verify `target_temp_high` increases by 1.5°F in HA dev tools immediately
   - Wait 5 min — verify `target_temp_high` restored
   - Run `sqlite3 ... "SELECT * FROM ac_ramp_events WHERE zone_id=? ORDER BY event_id DESC LIMIT 5"` — should show `nudge_started` + `nudge_restored` + `nudge_evaluated` events

5. **Cancel test:**
   - Press Force AC Nudge, then immediately press Cancel AC Nudge
   - Verify `target_temp_high` restored within ~1 second

6. **Lockout simulation:**
   - Direct SQL: `UPDATE ac_reset_state SET hard_reset_count = 2 WHERE zone_id = ? AND date = date('now')`
   - Trigger detection (e.g., force_nudge → ineffective → escalation attempt)
   - Verify persistent notification fires: "AC Ramp Lockout: <zone>"
   - Press Clear AC Ramp Lockout button — verify notification dismissed and counter zeroed

7. **Restart-during-nudge:**
   - Press Force AC Nudge
   - At ~30s in, `ha core restart`
   - Verify: on restart, target returns to original value within first-decision-cycle (~5 min) via startup audit

## Deploy notes

- **No DB schema breaking changes** — new tables only, append to existing 35+
- No migration cycle (bundled D4+D10)
- HACS download required after deploy.sh
- HA restart required (multiple files touched)
- Master switch defaults OFF — feature has NO effect until you flip it on
- Recommended observation period: 1 week of real data before tuning defaults

## Documents

- Plan: `docs/planning/PLANNING_v4.5.11_ac_energy_aware_ramp_down.md`
- Review: `docs/reviews/code-review/v4.5.11_review.md`
- Tech debt: `docs/TECH_DEBT.md` (kWh-avoided rough-estimate caveat — deferred to slice 2 ship)
- VibeMemo entry 011 captures decision trail (soft+hard ladder, kWh primary, restart safety, plan-completion split)

## Next

- **v4.5.12** — Observability slice 2 (D7-D11 — per-zone sensors + impact sensors + diagnostic dump + HC/EC user manuals). Informed by 1 week of v4.5.11 field data.
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation (unchanged from v4.5.0 roadmap)
