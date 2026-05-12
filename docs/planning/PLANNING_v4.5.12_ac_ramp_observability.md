# PLANNING v4.5.12 — AC Ramp-Down Observability (slice 2 of v4.5.11 cycle)

**Date:** 2026-05-10
**Type:** Tier 2 feature cycle
**Predecessor:** v4.5.11.3 (slice 1 of the AC ramp-down cycle, stable in production)
**Pre-review baseline:** `pre-review-v4.5.12` (tag before any code changes)
**Quality bar:** Two independent staff-engineer-level reviews using best practices. The bug-class catalog (now #1-#35) is a regression-prevention input, NOT the review framework. See `CLAUDE.md` § Review Protocol.

## Why a refreshed plan

The earlier draft was written before today's painful debugging cycle (5 deploys, 4 distinct bug shapes including 2 brand-new classes #34 + #35). This plan incorporates the lessons:

- **Runtime smoke tests are mandatory for this cycle.** The framework was built today (`quality/tests/test_runtime_smoke.py` + `runtime_harness.py`) but the test deps haven't been activated. v4.5.12's FIRST deliverable is enabling them.
- **Reviews must mentally-execute the code path, not just match patterns.** Both Tier 2 reviews must walk the actual setup → first-tick → steady-state behavior.
- **Bug Class #34 (function-local import shadow) and #35 (button missing refresh signal)** must be checked explicitly in review, alongside the existing 33 classes.

## Problem Statement

v4.5.11.3 (slice 1) shipped the AC ramp-down compressor-protection critical path. The integration is live and watching. It currently:

- Detects overshoot + sustained kWh waste
- Acts via soft nudge → hard reset escalation
- Persists daily caps + in-flight nudge state in SQLite
- Provides master switch + 6 house-wide Number sliders + per-zone kWh threshold + 9 per-zone buttons
- Logs every state transition to `ac_ramp_events`

What it does NOT do yet:

- Surface live state per zone (user can't see "what's the ramp-down doing right now?")
- Quantify cumulative impact (nudges today, kWh avoided estimate, false-positive rate)
- Provide a one-tap diagnostic dump (events are SQL-queryable but no button)
- Document any of it (no user manual for HC, no user manual for EC)

v4.5.12 closes those gaps with sensors, a dump button, and the HC + EC user manuals. **Informed by the first week of slice-1 field data** — we now know that the kWh-aware detection works (user's per-zone Span sensors are wired; master switch is ON), so we can write observability around real behavior, not modeled behavior.

## Design Goals

1. **Live state visibility per zone.** State-machine state, last action, current kWh rate.
2. **Cumulative impact quantification.** Daily + total counts. Rough kWh-avoided estimate with honest caveat.
3. **One-tap diagnostic dump.** Button → JSON file of recent events → user can share or analyze.
4. **Comprehensive user manuals for HC + EC.** Task-oriented; troubleshooting recipes informed by v4.5.11 field data.
5. **Don't break v4.5.11.3.** All slice-1 surface stays unchanged. No CONF renames, no entity_id changes, no DB schema migration beyond append-only.
6. **Slice 2 must not repeat slice 1's mistakes.** Runtime smoke tests run for every coordinator touched. Tier 2 reviews mentally-execute. Function-local imports audited via AST.

## Pre-Cycle Setup — MANDATORY before any deliverable code

These came out of slice 1's painful debugging. Do them FIRST.

### Pre-D0a: Activate runtime smoke tests
- Uncomment `pytest-homeassistant-custom-component` in `quality/requirements_test.txt`
- Run `pip install -r quality/requirements_test.txt` in the dev env
- Run `pytest quality/tests/test_runtime_smoke.py` — confirm all 5 smoke tests pass on v4.5.11.3 baseline
- These tests catch UnboundLocalError, ImportError, scope shadowing, missing refresh signals — bugs source-grep can never see

### Pre-D0b: Tag pre-review baseline
```bash
git tag pre-review-v4.5.12 -m "Pre-review baseline for v4.5.12 (slice 2 observability)"
```

### Pre-D0c: Verify v4.5.11.3 still stable
- HA running on v4.5.11.3 for >12 hours without incident
- HVAC coord state `normal`, decision cycle ran in last 5 min
- All buttons / numbers / switch operational
- No new URA errors in system log

## Deliverables

### D7 — Per-zone state sensors (3 per AC zone)

Three new sensors per AC zone, surfaced on URA: HVAC Coordinator device:

| Sensor | State value | Source |
|---|---|---|
| `sensor.ura_hvac_ac_ramp_state_<zone_id>` | enum (`idle` / `detecting` / `nudging` / `awaiting_evaluation` / `escalating` / `locked_out` / `disabled`) | `ZoneState.ramp_state` (already maintained by slice 1) |
| `sensor.ura_hvac_ac_ramp_last_action_<zone_id>` | ISO timestamp; attrs: `action_type`, `triggered_by`, `kwh_rate_before`, `kwh_rate_after` | Latest row from `ac_ramp_events WHERE zone_id=?` |
| `sensor.ura_hvac_ac_ramp_kwh_rate_<zone_id>` | float (kW); attrs: `source_entity`, `last_updated`, `stale` | `ZoneState.last_kwh_rate` + freshness check |

All three subscribe to `SIGNAL_HVAC_ENTITIES_UPDATE` to refresh on every decision cycle.

**Acceptance Criteria:**
- **Verify:** 3 sensors per AC zone post-restart (3 × 3 = 9 for canonical install)
- **Verify:** `ramp_state` transitions visible in HA state history during a real overshoot
- **Verify:** `last_action` attrs include `triggered_by` distinguishing `auto` from `manual`
- **Verify:** `kwh_rate` sensor exposes `stale: True` when source sensor `last_updated > 10min` ago
- **Test:** runtime smoke test asserts `async_added_to_hass` subscribes to the dispatcher signal
- **Test:** 9 source-grep tests covering state machine + freshness handling
- **Live:** trigger Force Nudge → observe state transitions on `sensor.ura_hvac_ac_ramp_state_<zone>`: idle → nudging → awaiting_evaluation → idle

### D8 — House-wide impact sensors (5)

| Sensor | Unit | Source |
|---|---|---|
| `sensor.ura_hvac_ac_nudges_today` | count | `SUM(soft_nudge_count)` from `ac_reset_state` WHERE date=today |
| `sensor.ura_hvac_ac_resets_today` | count | `SUM(hard_reset_count)` |
| `sensor.ura_hvac_ac_kwh_avoided_today` | kWh | `get_ac_ramp_kwh_avoided(days=1)` — already exists in slice 1 |
| `sensor.ura_hvac_ac_kwh_avoided_total` | kWh, persistent (RestoreEntity) | Cumulative since slice 1 enable |
| `sensor.ura_hvac_ac_false_positive_rate` | % (0-100) | `false_pos / total_nudge_evals` excluding `triggered_by='manual'` |

Update cadence: read on decision tick (every 5 min). Cached between ticks.

**Tech debt callout:** kWh-avoided is a rough estimate (point-in-time delta × capped 30-min projection). Already documented in `docs/TECH_DEBT.md`. Sensor entity description repeats the caveat; `_attr_extra_state_attributes["accuracy"] = "rough_estimate"`.

**Acceptance Criteria:**
- **Verify:** kWh-avoided is non-negative
- **Verify:** false-positive rate stays within [0, 100] OR shows `unavailable` when sample size <5
- **Verify:** kWh-avoided-total persists across HA restart
- **Verify:** manual-triggered events excluded from false-positive math (Risk R6 from v4.5.11 plan)
- **Verify:** `accuracy: rough_estimate` attribute on kWh-avoided sensors
- **Test:** 10 source-grep + AST tests
- **Live:** Force Nudge → 10 min later → `kwh_avoided_today` reflects the event

### D10 — Diagnostic dump button

| Entity | Action |
|---|---|
| `button.ura_hvac_ac_ramp_diagnostic_dump` | Query `get_ac_ramp_events_recent(days=7)` → write JSON to `/config/ura_diagnostics/ac_ramp_<ISO_timestamp>.json` → fire persistent_notification with file path |

Single button on URA: HVAC Coordinator device, `EntityCategory.DIAGNOSTIC`.

**MUST follow Bug Class #35 pattern** — subscribe to `SIGNAL_HVAC_ENTITIES_UPDATE` in `async_added_to_hass` so `available` re-evaluates. (The button's `available` is always True since it doesn't depend on the arrester being up — but the pattern is documented as the standard for ALL new buttons.)

**Acceptance Criteria:**
- **Verify:** button creates parseable JSON in `/config/ura_diagnostics/`
- **Verify:** dump contains last 7 days of events
- **Verify:** persistent_notification fires with the file path after dump
- **Verify:** button does NOT show as `unavailable` on first boot (Bug Class #35 regression check)
- **Test:** 4 source-grep tests + 1 runtime smoke test
- **Live:** press → file exists with valid JSON

### D11 — User manuals

Two new task-oriented documentation files. NOT changelogs. Written for the user reading them six months from now while trying to remember what every slider does.

#### `docs/user-manual/HVAC_COORDINATOR.md` (drafted; finalize as-is)

The slice-1-wait draft is ~3700 words — task-oriented, every entity has a what/when/default/watch-after sub-section, three-layer gating diagram, 8-recipe troubleshooting section, full entity table appendix. Treat this as the **reference depth** for user manuals.

Finalization tasks:
- Cross-check that every CONF in `hvac_const.py` is documented
- Add D7/D8/D10 sensor + button entries to the existing entity tables once those deliverables land
- Mention Bug Class #34/#35 patterns in the troubleshooting tier (so future tuning sessions reference them)

#### `docs/user-manual/ENERGY_COORDINATOR.md` (not started)

Energy Coordinator (battery strategy, arbitrage, solar surplus, EV mutual-exclusion). Outline:

1. Overview — what EC does
2. Master switches (Observation Mode, Automation switches)
3. Number sliders — every slider with what/when/default/watch-after sub-sections
4. Battery strategy — SOC floors, arbitrage windows, EV mutual-exclusion (v4.5.0 design)
5. Solar banking — SOC threshold, banking floor, banking offset
6. Grid charging — windows, rates, exclusions
7. Sensors — arbitrage state, battery_power, solar surplus
8. Per-room form fields — energy sensors, comfort settings
9. Troubleshooting recipes
10. Architecture sketches — arbitrage decision flow + EV mutual-exclusion logic

Target: **match HC depth (~3000-4000 words).** Same structure: every entity with what/when/default/watch-after sub-sections, decision flow diagrams, ≥6 troubleshooting recipes, full entity table appendix.

**Acceptance Criteria:**
- **Verify:** every CONF in `hvac_const.py` appears in HC manual
- **Verify:** every CONF in `energy_const.py` appears in EC manual
- **Verify:** every Switch entity on HC and EC devices is documented
- **Verify:** Bug Class #34/#35 patterns mentioned in HC troubleshooting (so future tuning sessions reference them)
- **Test:** parse-based coverage check (~6 meta-tests)

## Files Touched (estimated)

| File | LoC | What |
|---|---|---|
| `sensor.py` | ~280 | D7 (3 × N) + D8 (5) sensor classes + setup wiring |
| `button.py` | ~80 | D10 dump button (with Bug Class #35 refresh signal pattern) |
| `database.py` | minor | Aggregation methods already exist in slice 1; minor tweaks if needed |
| `domain_coordinators/hvac.py` | ~15 | Accessors if sensors need them |
| `strings.json` + `translations/en.json` | ~80 | Sensor descriptions + rough-estimate caveats |
| `quality/tests/test_v4512_*.py` | ~450 | ~40 tests |
| `quality/tests/test_runtime_smoke.py` | ~50 | Extend smoke tests for new D7/D8/D10 surfaces |
| `docs/user-manual/HVAC_COORDINATOR.md` | refresh | ~4000-5000 words (existing draft to revise) |
| `docs/user-manual/ENERGY_COORDINATOR.md` | new | ~3000-4000 words |
| `docs/TECH_DEBT.md` | minor | If new caveats emerge |

**Total:** ~900 LoC production + ~500 LoC tests + ~6500-8000 words docs (HC ~3700 + EC ~3000-4000 — full reference depth).

## Risks + Critique Targets for Code Review (apply both staff-engineer-level passes)

Both reviews must mentally execute. Bug-class catalog is one input among many.

| ID | Risk | Mitigation |
|---|---|---|
| R1 | DB read on every sensor tick stresses write queue | Cache aggregates on coord state; sensors read in-memory cache; assert in smoke test |
| R2 | `kwh_avoided` total grows unboundedly across years | RestoreEntity float; no DB growth concern |
| R3 | False-positive rate misleading when sample size tiny | Show `unavailable` until N ≥ 5 nudge_evaluated events |
| R4 | Per-zone state sensor stale if zone disappears mid-cycle | Sensor returns `unavailable` when `zone not in zone_manager.zones` |
| R5 | Manual user manual drifts from code | Coverage test parses manuals for every CONF/Switch — drift caught at test time |
| R6 | **Bug Class #34** (function-local import shadow) — any new `from X import Y` inside a function | AST regression test (already in `test_v4511_*.py`) catches; reviews must verify |
| R7 | **Bug Class #35** (button missing refresh signal) — D10's dump button | Pattern is part of D10 acceptance criteria; smoke test verifies subscription exists |

## Live Validation Plan (Post-Deploy)

1. **Immediate post-restart:**
   - URA: HVAC Coordinator device shows 3 new sensors per AC zone + 5 new house-wide sensors + 1 new diagnostic button
   - All sensors initialize to plausible state (idle / 0 / 0% / etc.)
   - Zero new URA errors in system log
   - Smoke tests pass in dev: `pytest quality/tests/test_runtime_smoke.py`

2. **State sensor live-test:**
   - Press Force AC Nudge for one zone
   - Observe `sensor.ura_hvac_ac_ramp_state_<zone>` transitions: idle → nudging → awaiting_evaluation → idle
   - `last_action` timestamp updates

3. **Impact sensor smoke-test:**
   - After force_nudge: `nudges_today` increments by 1
   - After 10 min eval: if kWh dropped, `kwh_avoided_today` increases
   - `false_positive_rate` stays at 0% (force_nudges excluded from FP math)

4. **Diagnostic dump test:**
   - Press dump button
   - File appears in `/config/ura_diagnostics/`
   - JSON is parseable; contains last 7 days
   - Persistent notification cites the file path

5. **Manual review:**
   - Read HC manual end-to-end; cross-reference with actual entity list (no drift)
   - Read EC manual end-to-end; same
   - Bug Class #34/#35 cross-referenced in troubleshooting sections

## Test Count Target

- v4.5.11.3: 160 tests
- **v4.5.12 target: ~210** (+50 — including new runtime smoke coverage for D7/D8/D10)

## Out of Scope (Explicit Non-Goals)

- True baseline-matched kWh-avoided analytics (tech debt — needs Span historical API)
- Per-zone kWh-avoided breakdown (house-wide rollup only; per-zone is backlog)
- Real-time dashboard / Lovelace cards (entities exposed; user composes own dashboard)
- Heating-mode equivalent of AC ramp-down (cool-only; heating overshoot is different failure mode)

## Plan-Completion Tracking

Per `CLAUDE.md` mandate: at end of cycle, EVERY deliverable above must have a status: shipped / deferred / dropped. No silent drops.

## Deferred to v4.5.12.1 — see BACKLOG.md

Two kWh-avoided sensors should be duplicated onto the whole-house integration device with explicit `ac_ramp_` feature-prefix naming, alongside a future cross-vector savings roll-up cycle. Full implementation sketch, naming rationale, and reference material filed in `docs/BACKLOG.md` under "v4.5.12.1 — kWh-avoided House Roll-up".

**Why not fold into v4.5.12:** v4.5.12 is reviewed + approved + ready to ship. Adding scope mid-flight is the v4.5.11.x failure mode. Ship v4.5.12 → validate live → start v4.5.12.1 with the live data already informing the new sensor's design.

## Notes from slice 1 (informs slice 2)

- The v4.5.11 → v4.5.11.3 chain took 5 deploys to stabilize. Three bug classes (#32 partial-fix, #34 function-local import shadow, #35 button missing refresh signal) were discovered during the cycle.
- The user invested ~6 hours in recovery. Slice 2's pre-cycle setup (runtime smoke tests + amended quality bar) is the direct response.
- **If at any point during slice 2 build the runtime smoke test fails on master, STOP and fix before continuing.** Smoke test failures = real bugs that will crash HA on deploy.
