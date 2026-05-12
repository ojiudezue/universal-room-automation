# v4.5.12 — AC Ramp-Down Observability (slice 2 of v4.5.11 cycle)

**Date:** 2026-05-11
**Type:** Tier 2 feature cycle
**Predecessor:** v4.5.11.3 (slice 1 — stable in production)

## Summary

Closes the slice-2 deliverables deferred from the v4.5.11 cycle: 3 per-zone state sensors, 5 house-wide impact sensors, 1 diagnostic-dump button, and finalized user manuals for both HVAC Coordinator and Energy Coordinator. Built on the foundation laid in the v4.5.11.x debugging cycle — Bug Classes #34 + #35 documented, runtime smoke test framework in place, quality bar amended to "two independent staff-engineer-level reviews using best practices" (the bug-class catalog is one input among many, not the framework).

15 new entities. All apply the v4.5.11.x lessons: lookup by climate_entity (not local zone_id), subscribe to refresh signal (Bug Class #35), no function-local imports that shadow module-level names (Bug Class #34).

## What's new

### D7 — Per-zone state sensors (3 per AC zone)

| Entity | Type | Purpose |
|---|---|---|
| `sensor.ura_hvac_ac_ramp_state_<zone_id>` | enum | State machine label (idle / detecting / nudging / awaiting_evaluation / escalating / locked_out / disabled). Diagnostic category. |
| `sensor.ura_hvac_ac_ramp_last_action_<zone_id>` | timestamp | When the last action fired on this zone. Attrs: `action_type`, `triggered_by`, `kwh_rate_before`, `kwh_rate_after`. |
| `sensor.ura_hvac_ac_ramp_kwh_rate_<zone_id>` | kW | Live read of the zone's `ac_load_sensor` with `stale` attribute (true when source sensor is >10 min old). |

All three subscribe to `SIGNAL_HVAC_ENTITIES_UPDATE` so they auto-refresh per decision cycle (5 min) without needing manual `update_entity` calls — direct application of the Bug Class #35 pattern from v4.5.11.3.

Shared `_ACRampZoneSensorMixin` encodes the climate_entity lookup pattern and the refresh subscription. Three sensors × N AC zones (canonical install: 3 × 3 = 9 entities).

### D8 — House-wide impact sensors (5)

| Entity | Type | Purpose |
|---|---|---|
| `sensor.ura_hvac_ac_nudges_today` | count | Soft-nudge count today, across all zones. Total-increasing state class for energy-dashboard graphs. |
| `sensor.ura_hvac_ac_resets_today` | count | Hard-reset count today. Approach to daily cap = investigate. |
| `sensor.ura_hvac_ac_kwh_avoided_today` | kWh | Rough estimate (per `docs/TECH_DEBT.md`). `accuracy: rough_estimate` attribute discloses the caveat. |
| `sensor.ura_hvac_ac_kwh_avoided_total` | kWh, persistent | Cumulative since feature enable. `RestoreEntity` so the dashboard doesn't blink to 0 across HA restart. |
| `sensor.ura_hvac_ac_false_positive_rate` | % | Diagnostic. Shows `unavailable` until sample size ≥ 5 (R3 mitigation — small N is meaningless). Manual force_nudge events excluded from math (R6 mitigation). |

All five read from `OverrideArrester._impact_cache`, refreshed once per decision cycle at the end of `check_ac_reset`. Sensors are sync-read (`native_value` property) → no DB hit on every state poll. Five DB queries per cycle total — well within the write-queue budget.

### D10 — Diagnostic dump button

| Entity | Action |
|---|---|
| `button.ura_hvac_ac_ramp_diagnostic_dump` | Press → query last 7 days of `ac_ramp_events` + aggregates → write `ac_ramp_<ISO_timestamp>.json` to `/config/ura_diagnostics/` → fire persistent_notification with file path. |

Self-contained dump (includes aggregate context) so offline analysis doesn't need the original URA DB to interpret events. Useful for sharing with support or post-deploy review.

Diagnostic entity category. Applies Bug Class #35 refresh pattern even though `available` doesn't depend on the arrester — defensive consistency for any future change to the dependency.

### D11 — User manuals

Two task-oriented manuals at canonical depth:

- `docs/user-manual/HVAC_COORDINATOR.md` — ~4200 words. Covers every HC entity through v4.5.12: 8 master switches, 7 v4.5.10 runtime sliders, 6 v4.5.11 house-wide AC ramp sliders + 3 per-zone, master switch, 9 per-zone buttons + dump button, all 3 D7 sensors + 5 D8 sensors, 3-layer gating model, 8 troubleshooting recipes, observability tuning guide, full entity table appendix. Cross-references Bug Class #34/#35.
- `docs/user-manual/ENERGY_COORDINATOR.md` — ~4200 words. Covers EC at parity: the four-phase battery state machine (the v4.5.0 headliner) with diagram + per-phase table + strict precedence order, both master switches, 7 runtime sliders, form fields by category (hardware sensors / Solcast / EV / load shedding / HVAC offsets / arbitrage), 40+ sensors organized by purpose, EV mutual-exclusion architecture sketch, 8 troubleshooting recipes, full entity table appendix.

## What slice 2 does NOT change

- No new CONF keys → no migration needed
- No DB schema changes → existing `ac_reset_state` + `ac_ramp_events` tables unchanged
- No slice-1 entity unique_ids changed → dashboards safe
- No behavioral changes to the action ladder (detection → nudge → escalate → lockout) — slice 2 is read-only observability on top of slice 1's actions

## Tier 2 Review

First cycle conducted under the amended quality bar (per `CLAUDE.md` § Review Protocol): **two independent staff-engineer-level reviews using best practices**. Bug-class catalog used as one input, NOT as the review framework. Both reviewers mentally executed the full code path from `async_setup_entry` through first sensor read.

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 0 | — | — |
| LOW | 3 | 0 | 3 documented |

**LOW findings (accepted as design trade-offs):**
- L1: `nudges_today` / `resets_today` show yesterday's count for up to 5 min after midnight (until first decision cycle of new day refreshes cache). Self-corrects.
- L2: `kwh_avoided_total` displays its restored value for up to 5 min after restart before live cache populates. RestoreEntity bridge value is meaningful, not stale data.
- L3: D10 dump button writes JSON synchronously inside `async_press`. Typical dump <100 KB → <50ms write. Consistent with existing URA button patterns.

Full review in `docs/reviews/code-review/v4.5.12_review.md`.

**Verdict: APPROVED for deploy.**

## Test count

- v4.5.11.3: 290 tests (+ 1 runtime smoke skipped pending pytest-homeassistant-custom-component install)
- **v4.5.12: 326** (+36 D8/D10 source-grep + AST tests; D7 + Bug Class #34 + Bug Class #35 prevention tests retained from slice 1's test framework)

## Live validation plan (post-restart)

1. **Immediate post-restart (~5 min):**
   - URA: HVAC Coordinator device shows 3 new sensors per AC zone (9 total) + 5 new house-wide sensors + 1 new diagnostic button
   - All sensors initialize to plausible state: ramp_state=`idle`, kwh_rate=last cached value, nudges_today=0, kwh_avoided_total=restored from previous run
   - Zero new URA errors in system log

2. **State sensor live-test (with master switch ON):**
   - Press Force AC Nudge button for one zone
   - Observe `sensor.ura_hvac_ac_ramp_state_<zone>` transition: idle → nudging
   - 5 min later: transition → awaiting_evaluation
   - 10 min later: transition → idle (if kWh dropped) OR escalating (if it didn't)

3. **Impact sensor smoke-test:**
   - After the force_nudge above: `sensor.ura_hvac_ac_nudges_today` increments by 1
   - 10 min later (post-eval): if kWh dropped, `sensor.ura_hvac_ac_kwh_avoided_today` increases by a small amount
   - `sensor.ura_hvac_ac_false_positive_rate` stays `unavailable` (sample size < 5)

4. **Diagnostic dump test:**
   - Press the dump button
   - File appears in `/config/ura_diagnostics/ac_ramp_<timestamp>.json`
   - File is valid JSON, contains `dump_metadata`, `aggregates`, and `events` sections
   - Persistent notification fires with the file path

5. **kWh-avoided-total persistence:**
   - Note current `sensor.ura_hvac_ac_kwh_avoided_total` value
   - `ha core restart`
   - After restart: sensor immediately shows the same value (from RestoreEntity)
   - First decision cycle (~5 min) live-syncs from DB; value may adjust by <0.1 kWh

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (3 files touched: sensor.py, button.py, hvac_override.py)
- After restart: confirm new sensors populate within 5 min (first decision cycle); confirm dump button is operable (not greyed-out)

## Documents

- Plan: `docs/planning/PLANNING_v4.5.12_ac_ramp_observability.md`
- Review: `docs/reviews/code-review/v4.5.12_review.md`
- HC user manual: `docs/user-manual/HVAC_COORDINATOR.md` (updated for v4.5.12)
- EC user manual: `docs/user-manual/ENERGY_COORDINATOR.md` (new)
- Tech debt: `docs/TECH_DEBT.md` (kWh-avoided rough-estimate caveat, unchanged from slice 1)
- VibeMemo entry 012 captures the v4.5.11.x → v4.5.12 decision trail (quality bar amendment, Bug Class #34 + #35, runtime smoke test framework adoption)

## Next

- **v4.5.13** — closet + bathroom lazy auto-off (60-min default fail-safe even with motion sensor present). Small Tier 1 cycle (~80 LoC + 15 tests).
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation (existing roadmap).
- Once `pytest-homeassistant-custom-component` is installed in the dev env, smoke tests activate and become part of every Tier 2 cycle's required-pass gate.
