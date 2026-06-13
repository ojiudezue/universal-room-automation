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

**Commit dd49fbb. Framing: pause-ownership / precedence / resume races + EVSE shed↔TOU collision.**

### Verdict
The CRIT (F1, shed↔TOU `_paused_by_us` collision) IS correctly fixed. Shed paths
mutate only `_paused_by_load_shed`; no remaining write to `_paused_by_us` from any
load-shed path (`energy.py` EV :3829-3852 / :3854-3886, plug :3893-3946; TOU/arbitrage
never read/write `_paused_by_load_shed` except the deliberate defer-checks). `load_shedding_active`
property (:5605) correctly reads the new set. BUT precedence is **incomplete on 3 EV
resume paths** and restart-resilience has a HIGH gap.

### Findings

**A-HIGH-1 — `determine_excess_solar_actions` EV resume skip-list omits `_paused_by_load_shed`.**
`energy_pool.py:747-752`. The defense-in-depth skip-list that prevents excess-solar
turn-on from overriding a stronger pause owner lists drain/fill-priority/grid-cap/arbitrage
but NOT load_shed. During off_peak/mid_peak with battery full + solar surplus, an EVSE
claimed by load-shed (cross-period escalation) is turned ON by excess-solar, defeating the
shed. Sibling release paths (:1019-1024, :1401-1404) DO include load_shed — this one was
missed. Bug class: **Precedence list incomplete (#47-adjacent / multi-owner resume)**.
Fix: add `or evse_id in self._paused_by_load_shed` to the :747 tuple.

**A-HIGH-2 — EV grid-cap resume omits `_paused_by_load_shed`.**
`energy_pool.py:832-850`. The grid_cap resume branch only defers to `_paused_by_battery_drain`
(:836) before issuing `turn_on`. If load-shed also claims the EVSE (both can claim the same
device — grid_cap and shed are independent owners), grid-cap resume blasts it ON while shed
still wants it off. The EV battery_drain resume (:1019) and fill-priority resume (:1217) both
check the full owner set; grid_cap is the one resume path that was never generalized (predates
the multi-owner pattern) and the cycle did not extend it. Bug class: **Precedence list incomplete**.
Fix: add load_shed (and ideally fill_priority/arbitrage/us for full symmetry) to the :836 guard.

**A-HIGH-3 — Bundle persisted ONLY at `async_teardown`; lost on watchdog/hard restart.**
`_save_load_shedding_level` (:1485) has a single caller — `async_teardown` :4570. It is NOT
in `_periodic_db_writes` (:4320-4330). D2's promise is "rebuild shed state on startup," but
the dominant restart mode on this house is the supervisor **watchdog kill** (no graceful
teardown — see the v5.2.2 / 2026-06-09 write-flood incident). On a watchdog restart the bundle
is whatever the last *clean* shutdown wrote (often empty), so `_restore_load_shedding_level`
repopulates `_paused_by_load_shed` from a stale/absent bundle while `_load_shedding_active_level`
also restores from the same stale row — coordinator believes shed is inactive while hardware
may still be shed (or vice-versa). This is the exact F2 failure the cycle set out to fix, just
relocated to the crash path. Note this is *not a regression* (legacy integer was teardown-only
too), but D2's acceptance ("restart mid-shed → re-populated") only holds for graceful restart.
Bug class: **Persisted-state staleness on non-graceful restart (#7 stale data-source family)**.
Fix: add `await self._save_load_shedding_level()` to `_periodic_db_writes`, or save on every
escalate/de-escalate transition (:3683 / :3724). Cheap — one KV/cycle, matches v5.2.2 batched-write budget.

### Owner × resume-path matrix (EV side) — defer-to-load_shed coverage
| Resume path | file:line | checks `_paused_by_load_shed`? |
|---|---|---|
| TOU off-peak ensure-on carry-over | 552-556 | YES |
| arbitrage release | 1401-1404 | YES |
| battery_drain release | 1019-1024 | YES |
| fill_priority release | 1217-1221 | **NO** (A-MED-1) |
| grid_cap resume | 836 | **NO** (A-HIGH-2) |
| excess_solar turn-on | 747-752 | **NO** (A-HIGH-1) |

**A-MED-1 — EV fill-priority release omits load_shed.** `energy_pool.py:1217-1221` defers to
grid_cap/battery_drain/us/arbitrage but not load_shed (plug-side equivalent :2050-2052 DOES
include it — asymmetric). Lower severity than A-HIGH-2 because fill-priority releases only
when SOC target met (rarely co-active with shed), but it is a genuine missing cell. Fix: add load_shed.

**A-LOW-1 — `_handle_emergency_shed_all` (:830-832) does not persist the bundle after
populating the sets.** Emergency hazard shed claims all tiers in RAM but relies on the
teardown-only save (A-HIGH-3). Folds into A-HIGH-3's fix. No separate action if A-HIGH-3 fixed.

### Verified-clean (no finding)
- No load-shed path writes `_paused_by_us`; no TOU/arbitrage path writes `_paused_by_load_shed`
  (repo-wide grep). The CRIT is genuinely fixed.
- Double-claim: same EVSE in shed AND TOU — proactive-claim (:3843-3852) adds to load_shed
  without a duplicate `turn_off`; shed release (:3861-3867) defers to `_paused_by_us`, so the
  device stays off while TOU still claims. Correct.
- Plug resume paths (TOU :1775, drain :1913, fill-priority :2052) all defer to load_shed. Plug
  side is complete — only the EV side has gaps.
- Cascade level counter (`_load_shedding_active_level`) stays consistent with per-tier set writes
  (escalate :3671→3683, de-escalate :3724→3725); each `_execute_shed_action` mutates exactly its
  target tier's owner set.

**Severity tally (Reviewer A): 0 CRITICAL (the CRIT was fixed), 3 HIGH, 1 MEDIUM, 1 LOW.**
A-HIGH-1/2 are real shed-defeating resumes; A-HIGH-3 unmet D2 promise on the house's main restart
mode. Recommend fixing all three HIGH before deploy.

## Reviewer B — restart resilience + manual-off-wins

**Commit dd49fbb. Framing: orphan-restore + manual-off-wins + restart resilience + DB/persistence.** Verified against live code. (Overlap note: my B-HIGH-1 = Reviewer A's A-HIGH-3, independently — expected convergence; B-CRIT-1/B-CRIT-2 are disjoint from A.)

### B-CRIT-1 — In-shed peak→off-peak transition NEVER releases; orphans EV/plug/pool OFF (no restart required)
`bug-class: #F2 orphan-restore / resume-suppression`
`_update_load_shedding` off-peak short-circuit (`energy.py:3608-3613`) sets `_load_shedding_active_level = 0`
and `return`s **without ever calling `_execute_shed_action(target, activate=False)` for the active tiers.**
The only release path that runs `_execute_shed_action(activate=False)` is the per-tick de-escalation
(`energy.py:3724`), which by construction only runs while `tou_period in ("peak","mid_peak")`. So whenever
shed is active and the period flips to off-peak (the COMMON exit — shed only escalates in peak/mid_peak),
the cascade zeroes the counter but leaves every `_paused_by_load_shed` claim populated and `_pool._original_speed`
unrestored. D1's new deference then makes the orphan PERMANENT: EV off-peak ensure-on carries over
`_paused_by_load_shed` (`energy_pool.py:551-563`, `continue`) and plug off-peak resume skips turn-on while
load-shed claims it (`energy_pool.py:1775-1781`, `continue`) — i.e. the very resume that would have rescued
the device pre-cycle is now suppressed because "load-shed owns the resume," but load-shed never issues it.
This is the F2 bug the cycle set out to kill, reproduced on a pure period-flip and made strictly worse by D1.
The restart path (B-HIGH-1) feeds the same trap. **Fix:** the off-peak short-circuit must iterate
`LOAD_SHEDDING_PRIORITY` calling `_execute_shed_action(t, activate=False)` for each active tier (it already
honors manual-off + precedence) BEFORE zeroing the level. Without this, D1+D2 net out to MORE stranded
devices than before the cycle.

### B-CRIT-2 — Pool orphaned at REDUCED across restart: D2 restore omits `_pool._state`
`bug-class: #F2 orphan-restore / partial-state-restore`
`_restore_load_shedding_level` repopulates `_pool._original_speed` (`energy.py:1431-1436`) but never sets
`_pool._state = POOL_STATE_REDUCED` (default `POOL_STATE_NORMAL`, `energy_pool.py:73`). The pool's OTHER owner,
TOU `PoolOptimizer.determine_actions`, gates its off-peak restore on `self._state != POOL_STATE_NORMAL`
(`energy_pool.py:128`). Post-restart that gate is FALSE → TOU won't restore; B-CRIT-1's off-peak path won't
restore; so the pool sits at `POOL_REDUCED_SPEED` until a fresh in-peak de-escalation happens to fire. The
bundle persists `pool_original_speed` but not the reduced flag — restore is structurally incomplete. (Pool
is uniquely exposed because D1 left it on shared `_original_speed`/`_state` with no dedicated owner set; the
EV/plug collision was separated, the pool one was not.) **Fix:** in restore, when the bundle implies the pool
tier is active (`pool_original_speed is not None`), set `_pool._state = POOL_STATE_REDUCED` so the existing
restore path can fire.

### B-HIGH-1 — Bundle persisted ONLY at `async_stop`; watchdog/crash restart restores stale state
`bug-class: #7 stale data-source / persistence-write-cadence`
`_save_load_shedding_level` has exactly ONE caller — `async_stop` (`energy.py:4570`); grep-confirmed no
per-escalate/de-escalate and no periodic-writes call site. D2 is sold as "rebuild on startup," but the
rebuild source is only written on CLEAN shutdown. The incident class that motivated this cycle was a
supervisor WATCHDOG kill (v5.2.2 / 2026-06-09) where `async_stop` does not run. On that path the bundle is
stale or empty; restore repopulates `_paused_by_load_shed` from data that does not match live hardware,
seeding B-CRIT-1. The write is cheap (own `energy_state` table, `INSERT OR REPLACE`, 1 row, NOT recorder —
`database.py:4128-4137`; no write-flood risk), so persist on every escalate/de-escalate transition and on
emergency-shed. (Same finding as A-HIGH-3 — surfaced independently.)

### B-HIGH-2 — Re-escalate cannot re-shed a manually-resumed device (idempotency clobber-hole)
`bug-class: #manual-override-wins (inverse) / stale-ownership`
`_execute_shed_action(activate=True)` EV branch reads `state = _get_evse_state(evse_id)` then `continue`s on
`if evse_id in _paused_by_load_shed` WITHOUT consulting `state["is_on"]` (`energy.py:3828-3831`); plug branch
identical (`energy.py:3894-3896`). Scenario the plan's D3 names ("operator turns a shed device back ON during
shed, then cascade escalates again"): the device stays in `_paused_by_load_shed`, so re-escalate skips it and
it keeps drawing through peak shed while URA believes it is shed. **Fix:** on activate, if already claimed but
`state` shows ON, re-issue `turn_off` (or drop+reclaim) rather than blind-skip.

### B-MED-1 — EV/plug release re-enables a manually-OFF device; `respect_manual_off` is a misnomer
`bug-class: #manual-override-wins (EV/plug gap)`
EV release skips `turn_on` only when `state["is_on"]` (`energy.py:3877-3880`) — per plan open-Q#3
(idempotency-only). If the operator manually turned the EV OFF mid-shed and left it off, release sees
`is_on == False` → re-issues `turn_on`, clobbering the operator. The plug branch reasons (`energy.py:3954-3963`)
that since `_release_pause_dispatch_owner` already wiped the ts, an off plug is "safe to turn_on" — so the plug
path ALSO turns a manually-off-then-left-off plug back on; the `respect_manual_off` reason fires only when
`state.state == "on"` (`energy.py:3970-3978`). So what D3 actually respects is manual-ON, not manual-OFF — the
label is inverted from the plan's intent ("operator-manual-off → do NOT turn on"). Either the detection or the
label needs reconciling; a per-EVSE/per-plug dispatch-ts compare (mirror `_observed_off_since_pause` grace at
`energy_pool.py:1841-1857`) is the real manual-off-wins fix.

### B-LOW-1 — Plug peak-shed guard omits `_paused_by_load_shed` (cosmetic re-pause)
`bug-class: #ownership-set-coverage`
Plug TOU peak pause guard checks `entity_id not in self._paused_by_us` only (`energy_pool.py:1757`), not
`_paused_by_load_shed`. Harmless (device already off) but asymmetric with the EV carry-over; add for symmetry.

### Positives confirmed
- Bundle corruption / partial / legacy-integer / None all degrade safely (`energy.py:1417-1483`) — no crash;
  legacy fallback intact. D2 corruption-resilience is sound.
- Single atomic bundle key, own table, `INSERT OR REPLACE`, no recorder/write-flood exposure.
- Restore correctly issues NO actuation (live-state authority) — that design choice is right; the bug is the
  MISSING release on condition-clear (B-CRIT-1), not the restore itself.
- D1 EV/plug release precedence (defer to drain/fill/grid-cap/arbitrage/TOU) preserves DURABLE EV philosophy
  (`energy.py:3861-3873`); dispatch-owner refcount balances claim↔release (`energy.py:3909-3933`), no leak.

**Severity tally (Reviewer B): 2 CRITICAL, 2 HIGH, 1 MEDIUM, 1 LOW.** B-CRIT-1 and B-CRIT-2 must block deploy —
together they mean the cycle ships MORE orphaned-OFF devices than the pre-cycle code (D1's deference + the
unfixed off-peak release + the incomplete pool restore). B-HIGH-1 (=A-HIGH-3) defeats D2 on the house's main
restart mode. Recommend: do not deploy until B-CRIT-1/2 + B-HIGH-1 fixed and a `test_inshed_peak_to_offpeak_releases_all_tiers`
+ `test_restore_then_offpeak_restores_pool_and_plugs` are added (current tests cover restart-restore and
graceful de-escalation but NOT the period-flip release path — see Reviewer C).

## Reviewer C — test authority + safe-test design

**Framing:** test authority + safe-test design + reseeded sibling + scope-creep audit.
**Verdict:** Tests have GENUINE authority (not vacuous). Scope is clean. Reseed is
legitimate. **One HIGH masked-gap** in D3 plug manual-off; two coverage gaps.

### Mutation re-run (independent) — kill-counts vs builder

| Mut | Builder claim | My result | Authority |
|---|---|---|---|
| M1 revert EV claim → `_paused_by_us` | 2 fail | **3 fail** (`…does_not_touch_paused_by_us`, `…release_during_peak_keeps_ev_off`, `…release_off_peak_defers_to_battery_drain`) | REAL — drives real `_execute_shed_action` over real `EVChargerController._evse`/`_get_evse_state` |
| M2 drop battery_drain from release precedence | 2 fail | 2 fail (EV + plug defer tests) | REAL — real release path reads real precedence sets |
| M3 restore re-issues turn_off | 1 fail | 1 fail (`…does_not_issue_turn_off_actions`) | REAL — real restore drives real `_execute_service_action` stub; asserts real `_service_calls` |
| M4 remove manual-off check | 1 fail | 1 fail (`…respects_manual_off`) | REAL but see C-HIGH-1 — only proves manual-**ON** |
| M5 restore pool speed w/o live-validate | 1 fail | 1 fail (`…respects_manual_speed_change`) | REAL — real pool release reads real `current_speed` |

All 5 mutations kill ≥1 test that drives PRODUCTION bytes (exec-extracted real
`_execute_shed_action` / `_save`/`_restore` / `load_shedding_status`). No mutation
killed only a vacuous test. Tests do NOT hand-assert their own set writes:
membership always flows through the real action fn; assertions check resulting
real-controller state + the real service-call list. Builder under-counted M1
(3 not 2) — in our favor.

### Findings

**C-HIGH-1 — D3 plug manual-OFF detection is a no-op; M4 test masks it.**
`energy.py:3954-3969` (bug-class: claimed-infra-never-read). Build notes +
docstring (`energy.py:3771-3773`) claim manual-off-wins uses
`_pause_dispatch_ts` / `_observed_off_since_pause`. Both are **written**
(`:3907-3908`) but **never READ** on the release path (grep-confirmed: only
write sites at :3907-3908, claim/release at :3909/:3931). When the plug is
currently OFF at release, production UNCONDITIONALLY issues `turn_on`
(`:3964-3968`). The "manual-off-after-restore" case D3 promised to respect is NOT
handled — only manual-**ON** (state currently on, `:3970-3978`) is. The M4 test
exercises only manual-ON, so it passes while the promised manual-OFF protection
silently doesn't exist. Fix: either (a) read `_observed_off_since_pause` in the
off-branch + add `test_plug_shed_release_respects_manual_off_when_off`, or
(b) downgrade docstring/build-notes to "manual-ON idempotency only" (matching the
EV disposition) and delete the dead `_pause_dispatch_ts`/`_observed_off_since_pause`
writes. As-is: dead infra + over-claiming docstring.

**C-MED-1 — `energy_pool.py` `determine_actions` precedence interactions untested.**
The plug TOU off-peak resume now does `_paused_by_us.discard(entity_id)` + `continue`
when `_paused_by_load_shed` claims the plug, and EV `determine_actions` carry-over
gained `_paused_by_load_shed`. NO test drives `EVChargerController.determine_actions`
/ `SmartPlugController.determine_actions` with a load_shed claim — these cross-owner
paths (Reviewer A's surface, where A found HIGH gaps) are proven only by
inspection. Since the EV tier is "dead + unsafe to live-test," the off-peak
carry-over win MUST have an in-suite test. Add
`test_ev_determine_actions_offpeak_carryover_respects_load_shed` + plug analogue.
(Note: this gap is exactly why Reviewer A's A-HIGH-1/2 precedence misses slipped
through — no `determine_actions` test would have caught them.)

**C-LOW-1 — veto reason string mislabel.** `energy.py:5378-5379`: `plugs_under_shed`
unions `_paused_by_us` (TOU) + `_paused_by_battery_drain` but always reports
`_last_veto_reason="smart_plug_under_load_shed"`. A TOU-only/drain-only paused
plug reports a load-shed reason. Pre-existing breadth, naming nit only. NOT a
masked breakage — sibling test still seeds `_paused_by_us` and passes correctly
via the broad union.

### Reseeded sibling test — LEGITIMATE
`test_oc_pillar_a_handshake.py::test_energy_honor_vetoes_evse_during_load_shed_any_period`:
reseed `_paused_by_us` → `_paused_by_load_shed` is correct, not masking.
`load_shedding_active` (`energy.py:5605-5609`) now reads `_paused_by_load_shed`;
the old `_paused_by_us` seed would no longer trip the EVSE veto → the reseed
restores true coverage of the new semantics. Confirmed the test drives
`honor_optimizer_intent` → `load_shedding_active` (real property), not its own
seed. The OTHER sibling (`…smart_plug_under_load_shed`, still `_paused_by_us`) is
correct per C-LOW-1 (broad union).

### Safe-test design — PASS (with one caveat)
Plan Live criteria use obs-mode + low fixed threshold + ONE smart plug; NO
criterion live-toggles the EV tier with obs OFF. EV collision is proven IN-SUITE
(M1 kills 3 EV tests). **Caveat:** C-HIGH-1 means the D3 plug manual-OFF Live
bullet ("plug stays off … `respect_manual_off`") would FAIL live if exercised via
the off-state path — fix C-HIGH-1 before Review D or the live check won't match
the code.

### Scope-creep audit (special charge) — CLEAN
Grepped the full prod diff for `CONF_`, deadband / `0.8`, forecast, sub-tier /
booster / infinity / spa / jets / blower, new sheddable domains (lighting / EV
current modulation), arbitrage-gate coupling. **Zero hits.** `energy_pool.py`
changes are pure precedence-tuple extensions + one new `set()` per controller.
No new operator-facing knob, no priority-order change. `_claim_pause_dispatch_owner`
REUSE verified real (`energy_pool.py:367`). Hard scope boundary HELD.

### Suite
New file solo: 11 passed. Combined w/ sibling (both orderings): 51 passed.
Full suite: 34 failed / 14 errors / 29 skipped — IDENTICAL to develop baseline
(no new regression). energy.py confirmed clean post-mutation (no leftover diff).

**Severity tally (Reviewer C): 0 CRITICAL, 1 HIGH, 1 MEDIUM, 1 LOW.**
Disposition: fix C-HIGH-1 (wire-or-honestly-downgrade) + add C-MED-1
`determine_actions` precedence tests before deploy. C-LOW-1 = defer
(pre-existing naming). Then Review D.

## Fix-up pass (consolidated A/B/C dispositions)

**Commits applied after Tier 2-DB Reviewers A/B/C.** Each finding mapped to disposition (FIXED / DEFERRED / NO-OP), code site, and the mutation-proof named test.

### CRITICAL

| ID | Disposition | Site | Mutation-proof test |
|---|---|---|---|
| B-CRIT-1 (off-peak short-circuit orphan) | FIXED | `energy.py` `_update_load_shedding` off-peak + disabled short-circuits now call new `_release_all_active_tiers()` helper BEFORE zeroing `_load_shedding_active_level`. Helper iterates `LOAD_SHEDDING_PRIORITY` top-down calling `_execute_shed_action(target, activate=False)` (existing fn already honors manual-off / other-owner precedence). | `test_period_flip_offpeak_releases_all_active_tiers_BCRIT1`, `test_period_flip_offpeak_release_honors_was_on_at_shed_CHIGH1_persist`, `test_disabled_short_circuit_also_releases_all_active_tiers_BCRIT1` |
| B-CRIT-2 (pool restart REDUCED state) | FIXED | `energy.py` `_restore_load_shedding_level` sets `_pool._state = POOL_STATE_REDUCED` when `pool_original_speed` non-None in bundle. Unblocks the TOU `PoolOptimizer.determine_actions` restore gate (`_state != POOL_STATE_NORMAL`). | `test_restore_sets_pool_state_reduced_BCRIT2` |

### HIGH

| ID | Disposition | Site | Mutation-proof test |
|---|---|---|---|
| A-HIGH-1 (excess solar skip-list omits load_shed) | FIXED | `energy_pool.py:747-757` skip-list now includes `_paused_by_load_shed`. | `test_excess_solar_skips_load_shed_evse_AHIGH1` |
| A-HIGH-2 (grid-cap resume omits load_shed) | FIXED | `energy_pool.py` grid-cap resume guard generalized to defer to `load_shed / fill_priority / arbitrage / us` in addition to existing `battery_drain` (full multi-owner symmetry). | `test_grid_cap_resume_defers_to_load_shed_AHIGH2` |
| A-HIGH-3 / B-HIGH-1 (bundle persisted only at teardown) | FIXED | `_save_load_shedding_level` added to `_periodic_db_writes` (every 3rd decision cycle, ~15min) with write-on-change throttle via cached `_last_load_shed_bundle_str` to honor v5.2.2 write-flood lesson. Bundle survives watchdog kill. | `test_periodic_db_writes_persists_bundle_for_watchdog_AHIGH3`, `test_save_load_shedding_level_throttles_on_unchanged_bundle` |
| B-HIGH-2 (re-escalate cannot re-shed manually-resumed device) | FIXED | EV + plug activate branches: if device is in `_paused_by_load_shed` AND live state is ON, re-issue `switch.turn_off` (operator turned it back on mid-shed). Refresh `was_on_at_shed=True` on the re-claim so subsequent release restores it. | `test_reescalate_reshed_manually_resumed_ev_BHIGH2`, `test_reescalate_reshed_manually_resumed_plug_BHIGH2` |
| C-HIGH-1 / B-MED-1 (manual-OFF protection no-op; dead `_pause_dispatch_ts` infra) | FIXED — semantics-revised | Replaced the unread `_pause_dispatch_ts` / `_observed_off_since_pause` writes (dead infra) with per-device `_load_shed_was_on_at_shed: dict[str, bool]` map on both `EVChargerController` and `SmartPlugController`. **Semantics implemented: release turns ON only devices we shed from ON.** Recorded at every claim/re-claim; cleared on release; persisted in the bundle so it survives restart. A device already off when load-shed claimed it (proactive claim, manual-off, TOU-off) carries `was_on_at_shed=False` and is NOT turned on at release. Both EV and plug release paths now honor by construction. Docstring updated. | `test_plug_shed_release_when_off_and_was_off_at_shed_does_not_turn_on_CHIGH1`, `test_ev_shed_release_when_off_and_was_off_at_shed_does_not_turn_on_CHIGH1`, `test_was_on_at_shed_survives_restart_in_bundle_CHIGH1` |

### MEDIUM / LOW

| ID | Disposition | Site | Test |
|---|---|---|---|
| A-MED-1 (EV fill-priority release omits load_shed) | FIXED | `energy_pool.py` fill-priority release defer tuple extended with `_paused_by_load_shed`. | `test_fill_priority_release_defers_to_load_shed_AMED1` |
| C-MED-1 (`determine_actions` precedence not driven in tests) | FIXED | Added in-suite tests driving REAL `EVChargerController.determine_excess_solar_actions`, `determine_grid_cap_actions`, `determine_fill_priority_actions`, and `SmartPlugController.determine_actions` with `_paused_by_load_shed` claim. Closes the gap that allowed A-HIGH-1/2 to slip through the original build. | tests for A-HIGH-1, A-HIGH-2, A-MED-1, `test_plug_tou_offpeak_carryover_respects_load_shed_CMED1` |
| B-LOW-1 (plug TOU peak guard omits load_shed) | FIXED | `energy_pool.py:1755-1768` peak guard now also skips when entity is in `_paused_by_load_shed`. | `test_plug_tou_peak_skip_when_load_shed_claims_BLOW1` |
| A-LOW-1 (emergency_shed_all doesn't persist) | FOLDED into A/B-HIGH-3 — periodic persist now covers this within ~15min of the emergency. No separate change. | — | covered by A-HIGH-3 test |
| C-LOW-1 (`plugs_under_shed` veto-reason mislabel) | DEFERRED — pre-existing breadth, naming nit only, no masked breakage. Ledger note: revisit when adding shed-class telemetry. | — | — |

### Manual-OFF semantics implemented

Operator-coined directive ("**release turns ON only devices that WE turned OFF — i.e. that were ON at shed-time**"). Concretely:

- At claim time, every EV/plug write to `_paused_by_load_shed` is paired with `_load_shed_was_on_at_shed[id] = bool(live_state_was_on)`.
- At release time, we discard our claim, defer to any other owner, and then **only emit `switch.turn_on` when `was_on_at_shed=True` AND live state is off AND no other owner remains**.
- Re-claim during shed (operator turned device back ON; cascade re-escalates) refreshes `was_on_at_shed=True` so subsequent release restores.
- The map is persisted in the JSON bundle (`ev_was_on_at_shed` / `plug_was_on_at_shed`) so a watchdog-kill restart preserves operator intent — a device that was off at shed-time and is still off post-restart stays off on release.
- The dead `_pause_dispatch_ts` / `_observed_off_since_pause` writes from the original D3 plug activate path (claimed by docstring, never read) were removed.

### Mutation evidence (executed against current tree)

| Mutation | Behavior reverted | Test that failed | Pass after restore |
|---|---|---|---|
| Skip off-peak release | drop `_release_all_active_tiers(reason="off_peak")` call | `test_period_flip_offpeak_releases_all_active_tiers_BCRIT1` FAILED | YES |
| Skip pool `_state=REDUCED` on restore | replace `_pool._state = POOL_STATE_REDUCED` with `pass` | `test_restore_sets_pool_state_reduced_BCRIT2` FAILED | YES |
| Drop load_shed from excess-solar skip-list | remove `or evse_id in self._paused_by_load_shed` from `:747-757` | `test_excess_solar_skips_load_shed_evse_AHIGH1` FAILED | YES |
| Drop periodic bundle persist | remove `await self._save_load_shedding_level()` from `_periodic_db_writes` | `test_periodic_db_writes_persists_bundle_for_watchdog_AHIGH3` FAILED | YES |
| Skip re-shed-on-manual-resume | revert EV activate branch to unconditional `continue` on set membership | `test_reescalate_reshed_manually_resumed_ev_BHIGH2` FAILED | YES |
| Release ignores `was_on_at_shed` | remove the `if not was_on_at_shed: continue` gate in plug release | `test_plug_shed_release_when_off_and_was_off_at_shed_does_not_turn_on_CHIGH1` FAILED | YES |

Original 5 build mutations (M1-M5) re-run green against the post-fix-up tree — all original tests still pass (no regression).

### Suite

- New file solo (27 tests): 27/27 PASS.
- Sibling-pillar ordering (`test_oc_pillar_a_handshake.py` + `test_energy_load_shedding_correctness.py`, both orders): 67/67 PASS.
- Full suite: 5842 passed / 34 failed / 14 errors / 29 skipped — failure/error IDs identical to develop baseline (34F/14E/29 cited in original build notes). No new regression. +16 passed (11 original + 5 new fix-up tests added).
- `py_compile` clean on `energy.py`, `energy_pool.py`, and the test file. No conflict markers.

### Reviewer disagreement vs code evidence

None material. Reviewer B's CRITs were both validated by code-grep (`_execute_shed_action` not called in off-peak short-circuit; `_pool._state` not set in restore) and the fixes reflect the proposed semantics directly. Reviewer C's C-HIGH-1 ("manual-OFF is a no-op; live-state authority dead infra") was confirmed — the chosen remediation is option (a) the reviewer offered (wire-or-honestly-downgrade), via the operator-directed `was_on_at_shed` semantic ("release ON only devices we shed from ON"). Reviewer A's owner × resume-path matrix used as the verification map; all six EV resume paths now contain the `_paused_by_load_shed` defer-check.

## Pass-2 Review (focused confirm)

**Scope: ONLY the fix-up diff `dd49fbb..9ec0ad1`. Verdict: SHIP.** All 2 CRIT + 5 HIGH + MEDs are correctly fixed; the fix-up did NOT introduce a new B-CRIT-1-style hole. One new LOW (fail-safe edge), one cosmetic NIT.

**Hunt 1 — `_release_all_active_tiers` (energy.py:3809).** Correct. Reads `level` once, iterates `range(level-1,-1,-1)` → tiers level-1..0; escalate uses `PRIORITY[level-1]` so level N ≡ tiers 0..N-1 — index symmetry verified. Delegates to `_execute_shed_action(activate=False)`, which honors `was_on_at_shed`, other-owner defer, and pool live-speed by construction (no bypass). `_execute_shed_action` reads but never mutates `_load_shedding_active_level` (3820); caller zeroes after — no double-release, no skipped tier. Grace-cycle guard lives only in the per-tick de-escalate path, NOT bulk-release — correct (hard period flip shouldn't wait grace). No new orphan: every tier's release pops its `was_on_at_shed` entries and clears the owner set. Per-tier `except` continues remaining tiers.

**Hunt 2 — `was_on_at_shed` lifecycle.** Set True on shed-from-ON (3944), False on proactive/off claim (3953), refreshed True on B-HIGH-2 re-claim (3925), `.pop(...,False)` on release (3967) — no leak (popped every release), no stale-read (read once post-pop). Bundle round-trip (1460-1469 restore / 1531-1536 save) symmetric. **Partial/legacy bundle (set present, was_on map absent): `.pop(id,False)`→False→device left OFF on release.** Fail-safe (never clobbers operator) but a legacy-window watchdog restart of a device shed-from-ON strands it off until manual re-enable → **NEW P2-LOW-1** (energy.py:1460/3967). Bites only the one-cycle dual-write back-out window the build created; defer.

**Hunt 3 — B-CRIT-2 pool.** `_state=POOL_STATE_REDUCED` set with `_original_speed` on restore (1444-1445), inside the same try that nulls speed on bad cast — consistent. TOU `PoolOptimizer` gate (`_state!=NORMAL`) now unblocks; release path resets `_state→NORMAL`. No double-restore, no stuck-REDUCED.

**Hunt 4 — B-HIGH-2 re-shed.** EV (3916) + plug (4022) re-issue `turn_off` only when in-set AND live ON, refreshing `was_on_at_shed=True`. Manual-OFF case is untouched (live OFF → blind-skip retained), so operator-OFF is NOT corrupted to True. Walked toggle sequences: claim-from-ON→manual-ON→re-shed restores True (correct); proactive-OFF→stays False unless operator turns ON and cascade re-sheds (then True, correct).

**Hunt 5 — periodic persist + throttle.** `_save_load_shedding_level` added to `_periodic_db_writes` (4471). Throttle via `_last_load_shed_bundle_str` with `json.dumps(..., sort_keys=True)` → dict-ordering stable, no false-skip on key reorder. `_last_...` updated only after successful write (1543); serialize-failure returns before write (no stale cache). No write-flood, no missed real change. **NIT:** unchanged-bundle path skips the legacy dual-write key too — harmless (legacy key only read as fallback, and bundle already persisted).

**Hunt 6 — tests.** New file 27/27. Mutations re-run: off-peak-skip-release, throttle-always-skip, EV was_on gate, B-HIGH-2 blind-skip — each kills the named test(s); originals stay green. Both orderings (sibling±new) 67/67. Full suite 5842P/34F/14E/29S; **failure-ID set diff vs develop = IDENTICAL** (verified via worktree, not just counts).

**New findings:** P2-LOW-1 (legacy-bundle fail-safe strand, defer) + 1 NIT. No CRIT/HIGH introduced. **SHIP.**

## Live Validation (Review D)

_To be filled post-restart._
