# v5.89.0 — AC ramp pipeline hardening

**Tier 3.** Four framing-disjoint code reviews (all returned DO-NOT-SHIP on first pass),
two orchestrator-run independent mutation drills, one serial full-suite name-diff.
Branch `feature/ac-ramp-pipeline-hardening`, 8 commits, 64 cycle tests.

**Ships in SHADOW.** The headline change (Gate 4) does not alter behaviour until the
operator flips a Select. See "Rollout" below.

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
| D-GATE4 | Draw-based cooling predicate replacing the stale cloud veto | **SHADOW** (operator flips to LIVE) |
| D-SCORE | `durable` / `durable_minutes` / `truncated` per-nudge durability | LIVE, telemetry only — no trust consumer |
| D2 | Day/night partitioned reset budgets (2 day / 2 night) | LIVE |
| D3 | Soft-nudge daily cap | LIVE |
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
- **The nudge settled-restore verdict is DISABLED, deliberately.** `ha_carrier`'s
  `async_set_preset_mode` writes no HA state and requests no refresh
  (`climate.py:381`), and the coordinator polls every 30 min (`const.py:46`). A verdict
  must therefore sample >30 min after the write, but the measured inter-nudge cadence
  is 25 min — the window is unsatisfiable. `restore_ok` is now written as NULL with
  `settled_reason = "poll_interval_30min_exceeds_nudge_cadence_25min"`.
  **Every settled restore verdict recorded before this release is inadmissible and must
  not be cited as evidence that preset restore failed.**

## Rollout

Default is `shadow`: legacy Gate 4 still decides; the new predicate is computed and a
latched `gate4_divergence_shadow` row is written on disagreement.

1. Boot. Confirm mode is `shadow` and divergence rows appear.
2. Let `sensor.ac_gate4_blind_fraction_7d_<zone>` accumulate.
3. Flip the Select to `live` when the divergence data looks right.
4. Kill switch: set the Select to `legacy` — the new predicate is never called.

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

## Live validation — PROSPECTIVE (to be replaced with observed results)

Per the standing rule, this section is rewritten post-restart with a
`Validated <date>` table carrying observed evidence. It is NOT done until then.

- **L1 — boot clean.** No URA ERROR entries referencing `hvac_override` or
  `ac_ramp` within 15 min of restart.
- **L2 — shadow is inert.** Predicate Select reads `shadow`. Nudge/reset counts for
  the first full day are within the historical envelope (zone_1 ~14/night). A step
  change in shadow would falsify the shadow contract.
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
