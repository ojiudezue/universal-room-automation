# Code Review — Load-Shedding Correctness Fixes

**Branch:** `feature/load-shedding-correctness` (off `develop`)
**Plan:** `docs/planning/PLANNING_load_shedding_correctness.md`
**Tier:** Tier 2-DB (operator-elevated — trust-hierarchy ripple Energy load-shed
↔ EVSE TOU ↔ battery-drain / fill-priority / arbitrage / grid-cap).

---

## Build notes

### Scope shipped (per plan D1-D4)

- **D1 (CRIT) — Separate `_paused_by_load_shed` ownership.** New dedicated
  pause-owner sets on both `EVChargerController` (`energy_pool.py` near :205)
  and `SmartPlugController` (near :1684). Load-shed action paths in
  `energy.py:_execute_shed_action` (EV branch ~ :3699-3748, plug branch
  ~ :3749-3812) migrated OFF `_paused_by_us` onto the new sets. Activate is
  a proactive claim when the device is already off (mirrors v5.3.9 arbitrage
  claim-when-off). Release defers to ANY other owner still claiming
  (`_paused_by_us` / `_paused_by_battery_drain` / `_paused_by_fill_priority`
  / `_paused_by_grid_cap` / `_paused_by_arbitrage` — preserves DURABLE EV
  PHILOSOPHY: battery-drain wins on EV side). Precedence extended in EV
  TOU off-peak ensure-on (`energy_pool.py:542-555`) and arbitrage release
  (`energy_pool.py:1388-1396`). Smart-plug TOU resume (`energy_pool.py:1749-1763`),
  drain resume (`:1882-1888`), and fill-priority resume (`:2020-2024`) now
  also defer to `_paused_by_load_shed`.

- **D2 (HIGH) — Atomic JSON bundle persistence + live-state-authority restore.**
  `_save_load_shedding_level` now writes a single `load_shedding_bundle` JSON
  KV via the existing `save_energy_state` (level + pool_original_speed +
  ev_set + plug_set). Legacy `load_shedding_level` integer key kept for one
  cycle of dual-write back-out safety. `_restore_load_shedding_level` reads
  bundle first, repopulates `_paused_by_load_shed` sets + `_pool._original_speed`,
  arms 3-cycle grace, sets `_last_release_reason="restart_restored"`. Falls
  back to legacy integer-only restore when bundle absent. Restore does NOT
  re-issue any service actions (live state is authority).

- **D3 (HIGH) — Manual-off-wins on shed release.**
  - **Plugs:** release reads live state. If live state is on (operator
    manually re-enabled mid-shed) — discard our claim, do NOT clobber,
    record `_last_release_reason="respect_manual_off"`. Uses the REUSED
    multi-owner `_pause_dispatch_ts` infra via
    `_claim_pause_dispatch_owner("load_shed")` at dispatch.
  - **Pool:** release reads live `current_speed`. If it has diverged from
    `POOL_REDUCED_SPEED` (operator changed mid-shed), discard the stale
    `_original_speed`, do NOT restore, record
    `_last_release_reason="respect_manual_speed_change"`.
  - **EVs:** simplified to idempotency only — no per-EVSE `_pause_dispatch_ts`
    equivalent exists. Resume skips `turn_on` if state already on; defers
    to any other pause-owner. (Plan open question #3 — accepted disposition.)

- **D4 — Status sensor + activity log additions.**
  `load_shedding_status` (sensor at `energy.py:5328`) now exposes
  `paused_by_load_shed_ev`, `paused_by_load_shed_plugs`, `pool_pre_shed_speed`,
  `last_release_reason`. Activity-log writes a notable row for
  release reasons in {`respect_manual_off`, `respect_manual_speed_change`,
  `deferred_to_other_owner`}.

### Other affected sites

- `EnergyCoordinator.load_shedding_active` property updated to read
  `_paused_by_load_shed` (was `_paused_by_us` — wrong semantics, conflated
  load-shed with TOU).
- Optimizer-veto path (`energy.py:5364-5368`) extended to include
  `_paused_by_load_shed` in the `plugs_under_shed` veto set.
- `test_oc_pillar_a_handshake.py::test_energy_honor_vetoes_evse_during_load_shed_any_period`
  updated to seed `_paused_by_load_shed` rather than `_paused_by_us`
  (the prior seeding only worked because the collision conflated the two).

### Plan open questions — resolved dispositions

1. **Pool `_original_speed` TTL on restart.** Resolved per operator
   directive: NO TTL. Restore the bundle but discard `_original_speed`
   if live `current_speed` doesn't match the expected shed value (live
   state validates on first release attempt).
2. **`_pause_dispatch_ts` for load_shed dispatch.** Resolved: use the
   multi-owner refcount (`_claim_pause_dispatch_owner("load_shed")`) at
   shed-dispatch time. Implemented at `energy.py` plug-activate branch.
3. **EV-side `_pause_dispatch_ts` equivalent.** Resolved: absent — EV D3
   simplifies to IDEMPOTENCY only (skip `turn_on` if already on, defer to
   precedence). Per operator directive.
4. **Single bundle vs split KV keys.** Resolved: SINGLE atomic bundle —
   one KV per cycle, mirrors the v5.2.2 batched-write lesson.

### Out-of-scope parked (guard against reviewer scope-creep)

These were considered and EXPLICITLY NOT built — the cycle's hard scope
boundary holds them in the foundations / IP-grade track or a future small
cycle:

| Item | Where it lives |
|---|---|
| Progressive pool sub-tiers (booster / infinity-edge / spa / jets) | `project_load_shedding_ip_capability_hold.md` |
| Forecast-coupled proactive shedding | same |
| New sheddable domains (lighting, EV current modulation) | same |
| Release deadband at ~0.8× threshold (audit MEDIUM) | future backlog memo |
| HVAC `max_runtime` re-verify (audit MEDIUM) | watch-only, de-risked by v4.7.29 |
| HVAC tier fire-and-forget state drift (audit LOW) | future backlog |
| Medical / safety allowlist guard | UNVERIFIED — own cycle if real |
| Coordinate-with-battery-before-shedding optimization | foundations track |
| Cost / comfort weighted tier order | foundations track |
| New operator-facing CONF knobs | none added (parsimony default holds) |

If a reviewer finds a defect OUTSIDE D1-D4 that meets CRITICAL/HIGH bar
in `docs/QUALITY_CONTEXT.md`, file it; otherwise defer.

### Test authority

- New file: `quality/tests/test_energy_load_shedding_correctness.py` (11 tests).
- Drives REAL `EnergyCoordinator._execute_shed_action`, real
  `_save_load_shedding_level` / `_restore_load_shedding_level`, real
  `load_shedding_status` property via AST-extract → exec into a minimal
  host class (avoids the full EnergyCoordinator constructor cost while
  still executing the production bytes).
- Real `EVChargerController` / `SmartPlugController` / `PoolOptimizer`
  instances throughout — no hand-mutated state to fake reachability.
- Mutation evidence (executed during build):
  - **M1** revert load-shed to `_paused_by_us` →
    `test_ev_shed_during_peak_does_not_touch_paused_by_us` FAILS.
  - **M2** drop `_paused_by_battery_drain` from EV release precedence →
    `test_ev_shed_release_off_peak_defers_to_battery_drain` FAILS.
  - **M3** make orphan-restore re-issue turn_off →
    `test_restore_does_not_issue_turn_off_actions` FAILS.
  - **M4** remove the manual-off live-state check →
    `test_plug_shed_release_respects_manual_off` FAILS.
  - **M5** restore pool `_original_speed` without live-validation →
    `test_pool_shed_release_respects_manual_speed_change` FAILS.

### Suite

- New tests solo: 11 passed.
- Reverse-order isolation (sibling pillar + new tests, swapped):
  51 / 51 passed both orderings.
- Full suite vs `develop` baseline:
  baseline 34 failed / 14 errors / 29 skipped; post-change identical
  (34 / 14 / 29). +11 passed from the new file; one existing test
  (`test_energy_honor_vetoes_evse_during_load_shed_any_period`) updated
  to seed the new dedicated `_paused_by_load_shed` set — the original
  seeding only worked because the collision conflated load-shed with TOU.

---

## Reviewer A — pause-ownership / precedence / resume races

_To be filled by reviewer._

## Reviewer B — restart resilience + manual-off-wins

_To be filled by reviewer._

## Reviewer C — test authority + safe-test design

_To be filled by reviewer._

## Live Validation (Review D)

_To be filled post-restart._
