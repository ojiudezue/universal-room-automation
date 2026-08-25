# v5.89.0 — AC ramp pipeline hardening

**Tier 3.** Four framing-disjoint code reviews (all returned DO-NOT-SHIP on first pass),
two orchestrator-run independent mutation drills, one serial full-suite name-diff.
Branch `feature/ac-ramp-pipeline-hardening`, 8 commits, 64 cycle tests.

**Ships LIVE.** The headline change (Gate 4) uses the new draw-based predicate
from first boot. Rollback path is the Select's `legacy` value (documented
under Rollout / Rollback). 2026-08-23 operator decision: shadow-then-flip
was rejected — "I don't have time for shadows. It works or not and we can
fix or rip."

---

## Why this cycle exists

The AC ramp-down lever was partly disconnected. Gate 4 vetoed the whole ramp pipeline
on `hvac_action == "cooling"`, a value derived from a 30-minute cloud poll that goes
stale and reports `idle` while the compressor runs.

Measured over the recorder window, per zone, as a fraction of high-draw time:

| zone | blind fraction | nudges during blind time | baseline nudge rate |
|---|---|---|---|
| zone_1 | 12.2% | 0 | 0.76-1.61 /h |
| zone_2 | 7.1% | 0 | " |
| zone_3 | 12.9% | 0 | " |

Blindness was sustained (91-95% of it inside episodes >10 min), not sampling noise.

## What ships

| # | Deliverable | Status on ship |
|---|---|---|
| D-GATE4 | Draw-based cooling predicate replacing the stale cloud veto | **LIVE** (rollback: Select -> `legacy`) |
| D-SCORE | `durable` / `durable_minutes` / `truncated` per-nudge durability | LIVE, telemetry only — no trust consumer |
| D2 | Day/night partitioned reset budgets (2 day / 2 night) | LIVE |
| D3 | Soft-nudge daily BACKSTOP (default 40, was 50) | LIVE |
| D-PARTITION | Partition denial no longer engages lockout | LIVE |
| D-ESC-SIG | `triggered_by` on hard-reset escalation | LIVE — force-button writes `"manual"` |
| D5 | Hard-reset row enrichment + `preset_restore_ok` | LIVE |
| D6 | Reset outcome (`floor_survived` / `justified_ramp`) + `kwh_rate_settle` | LIVE |
| D7 | `AC_RESET_OFF_DURATION_SECONDS` promoted to a live knob | LIVE |
| D8 | Declined trail + NM alert wording | LIVE |
| A1 | Five per-zone display sensors | LIVE |
| A2 | Init seeding of new knobs from CM options | LIVE |
| A3 | Bounded restart resumption of in-flight durability | LIVE |

## NOT in this release — stated so it is not assumed

- **D-ESC-CONSUME (automatic escalation on repeated nudge failure) — DROPPED.** Four
  probes proposed three different triggers; none survived. The decisive test was a
  negative control: recomputing the trigger with the durability measurement deleted
  changed its behaviour by 1-2 events and detected the pathological night identically.
  It was a nudge-*spacing* detector. See `AC-RAMP-NO-RECURRENCE-ESCALATION-1` for the
  probe that would settle the question properly.
- **D9 (Carrier stale-poll refresh) — CUT.** `update_entity` calls the same fetch path
  as the periodic poll; measured blind episodes spanned 3-4 polls without clearing.
  Tracked as `CARRIER-STALE-POLL-REFRESH-1`.
- **D10 (actuation-lag columns) — DEFERRED.** The probe ran and did NOT cancel it:
  measured command→physical-response is p50 72/83/101s (zones 1/2/3), p90 ~130-160s,
  against a plan cancel-threshold of p50 < 2s. Worth building; not tonight.
- **The nudge settled-restore verdict is ENABLED (F8 REVERSED 2026-08-23).**
  The 2026-08-22 decision that disabled this sample was built on an unmeasured
  number — `DEFAULT_UPDATE_INTERVAL_MINUTES = 30` from `ha_carrier/const.py:46`
  was read as the actual refresh cadence. The recorder shows the climate
  entities update every 42-79 s median (p90 167-323 s). The sample now fires
  at 3 min — past the refresh envelope, inside the 25-min inter-nudge cadence.
  A re-nudge before the sample fires cancels it and back-fills `settled_reason
  = cancelled_by_renudge`; a missing entity at settle writes
  `entity_missing_at_settle`. Otherwise `restore_ok` carries a real True/False.

  **Measured defect the instrument now exposes:** across 47 paired nudges
  (2026-08-22) with `intent` set to a real preset (away/home/sleep), the
  restore matched at T+1m in 0/10 cases and 1/10 (10%) from T+5m onward.
  When there is a real preset to restore, the restore does NOT take at any
  delay out to 30 min. More time does not help — time was never the
  variable. This is pre-existing and very likely explains the per-zone
  dwell in `manual` (62/46/26%). Owned by `HVAC-MANUAL-PRESET-CONTRACT-1`;
  out of scope for this release.

  **Every settled restore verdict recorded before this release is inadmissible
  and must not be cited as evidence that preset restore failed** — they
  were taken at 12 s under the pre-fix-up delay.

## Rollout

Default is `live` (2026-08-23 flip): the new draw-based predicate decides
Gate 4 from first boot. Gate 4 previously vetoed 7-13% of high-draw time
(measured; zone_1 12.2%, zone_2 7.1%, zone_3 12.9%), so post-flip nudge/reset
counts should RISE relative to the historical envelope. A flat count would
mean the new predicate is not firing.

1. Boot. Confirm the AC Gate 4 Predicate Mode Select reads `live` and
   `sensor.ac_ramp_state_<zone>` cycles through DETECTING / NUDGING as
   normal.
2. Watch nudge / reset counts across the first 24 h — a rise vs the prior
   week's envelope confirms the predicate is working.
3. `sensor.ac_gate4_blind_fraction_7d_<zone>` (both wall-clock and
   high-draw denominators) should trend well below `GATE4_MAX_BLIND_FRACTION
   = 0.01` after 7 days.
4. Kill switch: set the Select to `legacy` — the pre-cycle cloud-reported
   `hvac_action` decides Gate 4 verbatim. Cold-boot legacy path is tested
   (see `TestGate4DefaultLive::test_legacy_mode_still_kills_new_predicate_cold_boot`).

## Rollback

`git revert` the merge, or set the predicate Select to `legacy` (behavioural revert of
the headline change without a deploy). Every other deliverable is additive telemetry
or a gate that fails toward the pre-existing behaviour.

**Schema note:** this cycle adds columns via the guarded-ALTER pattern
(`durable`, `durable_minutes`, `truncated`, `reset_outcome`, `kwh_rate_settle`,
`current_temp_settle`, `preset_restore_ok`, `preset_settled`, `mode_settled`,
`settled_reason` on `ac_ramp_events`; `day_reset_count`, `night_reset_count`,
`night_session_date`, `in_flight_durable_started_ts`, `in_flight_durable_event_id` on
`ac_reset_state`). A code revert leaves the columns in place, unread. That is safe.

## Live validation — PARTIAL, validated 2026-08-23 11:11-11:45 CDT

Restart 11:07, HA responsive 11:11, manifest v5.89.0 verified on disk BEFORE restart.
This table records what has ACTUALLY been observed. Criteria needing elapsed time or an
organic event remain open and are marked so — they are not assumed.

| # | Criterion | Verdict | Observed evidence |
|---|---|---|---|
| L1 | Boot clean, no URA errors | **PASS** | `system` log, level=ERROR, search=universal_room_automation -> 0 entries since restart |
| L-live | Gate 4 predicate mode | **PASS** | `select.ura_hvac_ac_gate4_predicate_mode` = `live` on cold boot. The operator's explicit choice survived startup — this was the specific seed-race risk flagged when the default was flipped from `shadow`, and it did NOT silently downgrade |
| L-sensors | Five A1 sensors exist | **PASS** | All three `sensor.ura_hvac_coordinator_82_ac_gate4_blind_fraction_7d_*` present (back_hallway / entertainment_master_suite / upstairs), reading 0.0 — correct starting value for a 7-day window opened minutes ago, NOT a defect |
| F2 | Migration must not inflate upgrade-day budget | **PASS** | `ac_reset_state` newest zone_1 row reads `hard_reset_count=1, day_reset_count=1, night_reset_count=0` — the new day counter was SEEDED from the existing count rather than starting at 0. A zone that had already spent budget did not receive a fresh 2+2. This is the fix for the defect three reviewers flagged |
| L-schema | New columns present | **PASS** | `durable`, `truncated`, `kwh_rate_settle`, `reset_outcome`, `settled_reason` all queryable on `ac_ramp_events`; `day_reset_count`, `night_reset_count`, `night_session_date` on `ac_reset_state` |
| L4 | Day/night buckets separately populated; 22:00 and post-midnight charge the SAME night | **OPEN** | Needs an overnight. Day bucket confirmed populating (F2 row above); night bucket untested — no reset has fired at night since install |
| L7 | `durable` populated with BOTH values; `truncated` distinguishes branches | **OPEN** | 0 `ac_ramp_events` rows since restart — the AC has been idle (zone_1 circuit at 10.8 W). Nothing to measure yet. **All-zero `durable` when rows DO appear = the threshold bug regressed** |
| L8 | `kwh_rate_settle` not uniformly zero | **OPEN** | No hard reset since install. **Uniform ~0.0 kW = still sampling inside the 72-101s actuation lag** |
| L9 | Blind fraction <= 0.01 after 7 days live | **OPEN** | Window opened 11:11 today. Compare the high-draw-denominated attribute against the pre-fix baseline (zone_1 12.2%, zone_2 7.1%, zone_3 12.9%) — the wall-clock `native_value` is NOT comparable to it |
| L10 | `triggered_by` discriminates manual vs auto | **OPEN** | Needs a hard reset to fire |
| L6 | New knobs survive a restart | **NOT YET TESTED — SETUP OWED** | This restart could not test it: no non-default value was set beforehand, so seeding from defaults is indistinguishable from seeding from options. To test: set a non-default reset budget NOW, then verify it survives the NEXT restart. **This is the one diagnosis taken on trust during the cycle** (the builder concluded the seeding tests had a stale harness rather than F16/A2 breaking seeding) and it is the restart path for compressor-protection settings |

**The signal to watch over the next 24h:** nudge counts should RISE. Gate 4 was vetoing 7-13% of
high-draw time. A flat count means the new predicate is not firing — that is the rip signal, and
the rip is flipping the Select to `legacy`, no deploy required.

### Original prospective criteria (retained for reference)

Per the standing rule, this section is rewritten post-restart with a
`Validated <date>` table carrying observed evidence. It is NOT done until then.

- **L1 — boot clean.** No URA ERROR entries referencing `hvac_override` or
  `ac_ramp` within 15 min of restart.
- **L2 — live predicate is firing.** Predicate Select reads `live`. Nudge/reset
  counts across the first 24 h are ABOVE the historical envelope (zone_1 ~14/night
  pre-flip). A flat count means the new predicate is silently rejecting where the
  cloud used to say cool — the shadow measurement showed 7-13% blind time per zone
  during pre-fix operation, so a real rise is the discriminating observation.
  L2-negative: flat/lower counts under `live` are a fail (rip candidate — flip to
  `legacy` for the rollback).
- **L3 — divergence rows are LATCHED, not per-tick.** `gate4_divergence_shadow` rows
  appear at transitions only. Dozens per zone per day = the per-tick bug.
- **L4 — day/night partition is real.** After the first overnight,
  `sensor.ac_reset_day_count_<zone>` and `..._night_count_<zone>` are separately
  populated. **Discriminating check:** a reset at 22:00-23:59 and another after
  midnight must charge the SAME night bucket. This is the CRITICAL found by three
  reviewers; the observation that would show it still broken is a night counter
  reading 0 shortly after midnight when a reset fired before it.
- **L5 — the daily-limit knob is live again.** Set the AC Hard Reset Daily Limit
  Number to 0; confirm a declined row with reason `feature_disabled` and NO lockout.
  Restore it afterward.
- **L6 — new knobs survive a restart.** Set a non-default reset budget, restart,
  confirm it persists. This is A2; if it fails, compressor-protection settings are
  reverting on restart.
- **L7 — durability telemetry is populated and not degenerate.** Within 24h,
  `ac_ramp_events` has non-NULL `durable` with BOTH values present across zones, and
  `truncated` distinguishes the two branches. **All-zero `durable` = the threshold bug
  regressed.** Compare `sensor.ac_ramp_durability_rate_<zone>` against zone_1's
  measured 85-97% non-durable baseline.
- **L8 — `kwh_rate_settle` is not uniformly zero.** It samples 150s post-restore,
  past the measured 72-101s lag. **Uniform ~0.0 kW means it is still sampling inside
  the lag** — the exact defect this fixed.
- **L9 — blind fraction, after the LIVE flip + 7 days.**
  `sensor.ac_gate4_blind_fraction_7d_<zone>` ≤ 0.01. The high-draw-denominated
  attribute is the one comparable to the 12.2 / 7.1 / 12.9% pre-fix baseline; the
  wall-clock `native_value` is not.
- **L10 — `triggered_by` discriminates.** A force-button reset writes `"manual"`;
  an automatic escalation writes `"auto"`. Required by the escalation probe.

## Verification performed pre-ship

- 4 framing-disjoint reviews: 1 CRITICAL + 9 HIGH found, all fixed.
  The CRITICAL (night budget resetting at midnight → 4 resets/night against a budget
  of 2) was found independently by three reviewers.
- 10 mutation drills, all binding, source restored clean after each.
- 2 orchestrator-run independent drills. **One found a wire-in the builder's own drill
  could not see** (`_backfill_restore_ok` deletable at the call site with 60/60 green)
  — fixed and re-verified.
- Serial full-suite name-diff vs freshly re-baselined develop:
  **158 failing test IDs on both sides, identical sets. Zero regressions.**
