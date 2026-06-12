# EC/HC Reboot Decision-Pickup + Peak-Buffer Attainability — Review Ledger

**Planning doc:** `docs/planning/PLANNING_ec_hc_reboot_decision_pickup.md`
**Branch:** `feature/ec-hc-reboot-decision-pickup` off `develop` (tip `adb3717`).
**Tier:** Tier 2-DB (operator-elevated; strategy-change ripple + reboot-pickup primitive).

---

## Build notes (filled at build time)

### Files touched

| File | Lines (insertions / deletions) | Surface |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` | +~280 / 0 | D1 attainability branch: `ARBITRAGE_PHASE_ATTAIN` + `ATTAIN_RATE_WINDOW_TICKS` constants, `_attain_soc_history` window, `_record_attain_sample`, `_observed_net_charge_rate_per_hour`, `_minutes_to_high_rate_boundary`, `_should_attain_peak_buffer`, `_get_attainability_decision`; wired into off-peak branch between `_gate_is_open` and drain-target fallback; chunk-reset extension. |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | +13 / -1 | Bug Class #22 audit: arbitrage cycle savings accounting now counts ATTAIN as charging (energy.py:2069); EVSE pause gate at energy.py:2434 explicitly excludes ATTAIN per v1 observe-only scope. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_predict.py` | +29 / -1 | Bug Class #22 audit: `solar_intent` mapping treats ATTAIN like CHARGE → harvest; D2 #12 reboot-pickup pass in `update()` for `_pre_cool_triggered_today` + `_pre_heat_triggered_today`. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_covers.py` | +49 / 0 | D2 #15 reboot-pickup pass: `_reboot_pickup_seed_closed_set` helper invoked once on first `update()` to re-seed `_hvac_closed` from live cover positions when restarting mid-solar-window. |
| `quality/tests/test_attainability_branch.py` | +400 (new) | D1 tests: predicate math (6), precedence vs arbitrage (1), no-flap persistence (1), cold-boot defer (2), grid-import guard (1), late-start partial (1), Bug Class #22 audit (3), non-regression good-day (1). 16 tests total. |
| `quality/tests/test_reboot_pickup_d2.py` | +340 (new) | D2 tests: cover reboot pickup (2 — in-window seed + out-of-window no-op), pre-cool day-flag reboot pickup (3 — after-peak marks triggered, in-lead-window allows re-fire, idempotent). 5 tests total. |

### D2 inventory disposition

The planning table enumerated 20 surfaces. This build's verdicts:

| # | Surface | Plan verdict | Build verdict | Fix shipped? |
|---|---|---|---|---|
| 1 | Arbitrage chunk completion + reset | GAP candidate | **OK by analysis** | No — `_arbitrage_chunk_completed` is RAM-only, so reboot mid-chunk resets to False, which is the correct idempotent re-eval behavior. Phase 1 (SOC ≥ target → HOLD) wins on next tick if buffer is already attained, so no spurious re-CHARGE. Verdict change documented here. |
| 2 | Arbitrage CHARGE/HOLD/WAIT resolution | OK (verify) | **OK** | No — verified periodic re-eval each tick (`_get_arbitrage_phase` at `energy_battery.py:668-776`). |
| 3 | Charge-window-open primitive | OK | **OK** | No — stateless (`energy_battery.py:563-578`). |
| 4 | Off-peak drain-target hold/drain | OK | **OK** | No — pure function. |
| 5 | TOU period transitions (EVSE) | OK (verify) | **OK** | No — `energy_pool.py:459-568` reads `tou_period` each cycle. |
| 6 | EVSE off_peak ensure-on (v4.7.28) | OK | **OK** | No — already idempotent ensure-on. |
| 7 | EVSE force-charge override window | GAP partially closed by v4.7.28 | **DEFERRED** | No — KV-mirror verification deferred to a follow-up sweep. |
| 8 | EVSE fill-priority pause persistence | GAP partially closed by v4.7.28 | **DEFERRED** | No — same as #7. |
| 9 | EVSE arbitrage pause | OK by analysis | **OK** | No — one-cycle skew on reboot is acceptable per v4.7.28 plan §9. |
| 10 | EV grid-cap / battery-drain pause sets | OK | **OK** | No — already KV-restored. |
| 11 | TOU `get_next_transition` cross-day walk | GAP — OUT OF SCOPE | **DEFERRED** | No — v4.7.29 hygiene bucket. |
| 12 | HVAC weather pre-cool day-flag | GAP candidate | **GAP → FIXED** | **Yes** — D2 #12 reboot-pickup pass in `hvac_predict.update()`. Tests: `test_reboot_after_peak_marks_pre_cool_triggered`, `test_reboot_in_lead_window_allows_retrigger`, `test_reboot_pickup_is_idempotent`. |
| 13 | HVAC end-pre-cool at peak start | OK | **OK** | No — pure clock check. |
| 14 | HVAC solar-banking window | Verify | **OK (already covered)** | No — existing post-restart banking reconciliation handles the orphan case (`hvac_predict.py:422-448`, `_first_eval_done` one-shot). |
| 15 | HVAC cover solar-hour close window | OK (verify hysteresis state restore) | **GAP → FIXED** | **Yes** — D2 #15 reboot-pickup pass in `hvac_covers.update()`. Re-seeds `_hvac_closed` from live cover positions when restarting mid-window. Tests: `test_reseeds_closed_covers_post_reboot_in_window`, `test_no_reseed_outside_solar_window`. |
| 16 | HVAC pre-cool lead-time start | OK (verify) | **OK** | No — derived from `now ≥ peak_hour - lead`, re-evaluated each cycle. |
| 17 | HVAC dynamic preset dwell timer | Verify | **DEFERRED — exceeds 30 LoC budget** | No — `zone.current_session_start` is RAM-only at `hvac_zones.py:108`; a reboot mid-session resets it to `now` (boot time), restarting the dwell timer. Proper fix requires either RestoreEntity persistence on the per-zone session timestamp OR a derivation from the underlying room occupancy `last_changed` timestamps. Either approach is >30 LoC across `hvac_zones.py` + RestoreEntity wiring + tests, so deferred per plan budget. Follow-up cycle should pair this with the v4.7.25 dwell-Number persistence pattern. |
| 18 | Day-boundary mid_peak hold gate (v4.7.29) | OK (just shipped) | **OK** | No — already shipped. |
| 19 | HVAC max_runtime (uses get_next_transition) | GAP via dependency | **DEFERRED** | No — v4.7.29 hygiene bucket. |
| 20 | EC `_decision_timer_unsub` + HC `_decision_timer_unsub` | OK | **OK** | No — already validated by v5.3.7 always-register. |

**Net fixes shipped this cycle:** #12 (HVAC pre-cool day-flag), #15 (HVAC cover hysteresis state).
**Net deferrals:** #1 (reclassified as OK), #7-8 (verification follow-up), #11+#19 (v4.7.29 hygiene bucket), #17 (>30 LoC budget overrun).

### Mutation-authority evidence

Inverted the attainability predicate's `if projected < self._peak_buffer_target` comparison
(swapped True/False return tuples) and ran the new attainability test file:

```
8 failed, 8 passed in 0.03s
```

Reverted the inversion → 16/16 pass. The mutation-authority bar is ≥6 failures; we got 8. The failing tests span the math, no-flap persistence, cold-boot defer, grid-import guard, late-start, and good-day non-regression suites — coverage is not concentrated in one cluster.

### Operator decisions ratified in code

- **Phase token `attain`** — adopted as the literal string value of `ARBITRAGE_PHASE_ATTAIN`.
- **No late-start floor** — `_should_attain_peak_buffer` engages whenever projected < target, regardless of how few minutes remain. `test_late_start_30min_partial` proves a 30-min window with rate=0 still fires ATTAIN.
- **EVSE coordination OUT of v1 scope** — `energy.py:2434` arbitrage_charging gate explicitly stays `== ARBITRAGE_PHASE_CHARGE` only; ATTAIN does NOT pause EVSE. A code comment documents this so future cycles do not silently widen the gate. See backlog note below.
- **Reason string must explain WHY** — `_get_attainability_decision` builds: *"Peak-buffer attainability — projected SOC X% < target Y% at HH:MM (observed net rate +R%/h over K ticks, M min remaining; solar consumed by house/EV loads)"*.
- **Bug Class #22 sweep** — every code path that string-matches `arbitrage_phase` was audited and patched where ATTAIN is semantically equivalent (savings accounting, hvac_predict solar_intent). Test `TestBugClass22Audit` enforces the patches via plain-text file reads.

### Suite tally

- **Baseline (develop adb3717):** 37 failed / 5681 passed / 29 skipped / 14 errors.
- **Cycle tip:** 34 failed / 5705 passed / 29 skipped / 14 errors.
- **Failure-ID diff:** ZERO new failures. THREE baseline failures now pass (`test_envoy_auto_derive.py::TestHVACPredictorNetPower::*`) as a beneficial side-effect of the new test's hardened module-load pattern (it forces a real load of `hvac_predict` when a sentinel MagicMock was registered upstream).
- **New tests:** 21 (16 attainability + 5 reboot-pickup); all pass standalone, in full suite, and in reverse order against sibling files sharing module stubs.
- **py_compile:** clean across all touched files.
- **Conflict-marker grep:** clean.

### Plan deviations + WHY

1. **D2 inventory verdict for row #1 (arbitrage chunk reset)** changed from "GAP candidate" to "OK by analysis" — the planning doc itself flagged the same possibility ("verify whether `_arbitrage_chunk_completed` survives restart at all — if not, gap is the opposite"). Verified RAM-only at `energy_battery.py:142`; reboot → reset → Phase 1 (SOC≥target → HOLD) wins on next tick if buffer attained, so no spurious re-CHARGE. No fix needed.
2. **D2 #17 (dwell-timer)** deferred — proper fix to `zone.current_session_start` persistence exceeds the 30-LoC budget the plan set. Documented in the inventory table; follow-up cycle should pair with the v4.7.25 dwell-Number persistence pattern.
3. **Test file load pattern** — sibling test_hvac_fan_control.py registers `hvac_predict` as a MagicMock at sys.modules level. The cycle scope says "sys.modules setdefault-only", but for d2 we need the REAL module to instantiate via `object.__new__`. The compromise: `setdefault`-style for HA mocks (additive merge for missing attrs); for our own production modules, detect a sentinel MagicMock (no `__file__`) and force a real load. This is a SAFE relaxation — we never clobber a legitimately-loaded module, but we do replace a sentinel that would prevent real-method execution. Documented in `test_reboot_pickup_d2._load` docstring.

---

## Backlog — EVSE-coordination follow-up cycle (operator decision, deferred)

**Scope:** Add EVSE-coordination on top of v1 attainability — when the projection is severely
failing (e.g. projected SOC at boundary < 20% with EVs actively consuming), throttle EV
ensure-on briefly to let the battery catch up before grid-import.

**Why deferred (operator):** v1 is observe-only on EVs by explicit decision. Coupling EVSE
+ attainability requires a separate Tier 2-DB cycle with its own framing-disjoint reviews:

- **Reviewer A:** correctness — projection severity threshold tuning; what counts as
  "severely failing" without becoming a flap surface.
- **Reviewer B:** trust-hierarchy preservation — EV off-peak ensure-on is operator-durable
  intent ("solar-first → never drain battery into car → off_peak grid cheapest"). A
  coordination lever must NOT silently invert this default; the operator must opt in.
- **Reviewer C:** non-regression — confirm the v4.7.28 ensure-on, the v4.7.28 force-charge
  override, and the existing arbitrage CHARGE EVSE pause continue to behave correctly.

**Surface candidates (not built):**
- New CONF_ATTAINABILITY_EV_THROTTLE_ENABLED (default OFF — opt-in).
- New CONF_ATTAINABILITY_PROJECTION_SEVERITY_THRESHOLD (e.g. -50% deviation from target).
- A `paused_by_attainability` reason key on the EVSE-pause registry, distinct from
  `paused_by_arbitrage` so the sensor narrative + override behaviors stay legible.

**Recommended file location:** `domain_coordinators/energy_pool.py` (the EVSE-pause registry
already lives here). Wire from `energy.py` decision cycle similar to the existing
arbitrage/grid-cap/battery-drain interlocks.

**Tracked as:** this backlog note (the cycle did not file a separate planning doc — operator
should request one when prioritizing).

---

## Three-pass review framings (to be filled by Tier 2-DB reviewers)

### Review A — cost/strategy correctness + no-flap

**Reviewed:** commit 7d675e2, 2026-06-12. Framing: battery/cost strategy correctness + no-flap.

#### A-CRIT-1 — ATTAIN has no terminal latch; structurally oscillates on the Enphase cloud lever
**Severity: CRITICAL.** Bug class: *Missing terminal state in control loop / self-referential feedback*.
Three converging defects in `energy_battery.py`:
1. **Dead-code completion latch** (`energy_battery.py:1006-1009`). `_get_attainability_decision` marks `_arbitrage_chunk_completed` when `soc >= peak_buffer_target`, but it is only ever called when `_should_attain_peak_buffer` returned True, which requires `soc < peak_buffer_target` (`:962-963`). The latch the plan mandated ("Mark `_arbitrage_chunk_completed = True` once attainability CHARGE has brought SOC to peak_buffer_target ... so we don't oscillate") is unreachable.
2. **Release-on-projection mid-charge with a self-referential rate** (`:950-983` + `:1322-1325`). Once ATTAIN's grid charge flows (~16 kW per the addendum ≈ +40-60 %SOC/h on this pack), the K=3 trailing rate within 2-3 ticks projects `soc + (mins/60)×rate >= target` → predicate flips False at SOC far below target → falls through to drain/hold fallback, which issues `switch.turn_off` on charge_from_grid (`:1491-1502`) and drops reserve 80→`int(soc)`/drain_target. Charging stops, the rate decays over the next 2-3 ticks, projection fails again, ATTAIN re-fires. The projection uses a rate that is *contingent on the action it is deciding to release*. Each half-cycle is an Enphase cloud write with the measured 20-40 min actuation lag — the system can thrash indefinitely and never accumulate the buffer. This is exactly the manual-flip lesson the addendum recorded.
3. **No HOLD equivalent at target.** If SOC does reach target, the predicate exits at `:962-963` and the fallback DRAIN path (`:1410-1420`, `reserve_level=drain_target`) immediately releases the buffer *pre-boundary*; with EV/house load the SOC sags below target and ATTAIN re-fires. Arbitrage solves this with HOLD + chunk_completed (`:717-718`, `:822-827`); ATTAIN has neither.
**Fix shape:** consult `_arbitrage_chunk_completed` in the predicate; set it (and emit a HOLD-shaped decision: charge_from_grid=False, reserve=target) when `soc >= target` while ATTAIN was active; and gate release on `soc >= target` (or projection-pass with hysteresis computed from a rate that excludes the battery's own grid-charge power — `battery_power_w` is available via `_effective_import_kw`'s decomposition).

#### A-HIGH-1 — Grid-import-guard chunk lock is cosmetic for ATTAIN
**Severity: HIGH.** Bug class: *Mirrored-branch semantics divergence*.
`_should_attain_peak_buffer` never checks `_arbitrage_chunk_completed` (`:950-983`). After the consecutive-trip lock fires (`:1336-1353`, sets chunk_completed + logs "Chunk locked"), the next tick's predicate is still True: while still over-cap the WARNING re-logs and `_arbitrage_guard_aborted_at/_kw` are overwritten **every 5-min tick**; the first under-cap tick resets the streak (`:1373`) and ATTAIN re-fires **in the same chunk** — contradicting the "will retry next off-peak chunk" semantics arbitrage actually honors (`:723-724`). Adds a second flap axis: fire→trip→lock→under-cap→re-fire. Fix folds into A-CRIT-1 (predicate must honor the chunk lock).

#### A-HIGH-2 — Predicate fires on "solar hasn't happened yet", de-facto deleting the forecast gate
**Severity: HIGH.** Bug class: *Projection from stale regime* (clock-blind sibling of Bug Class #51).
At window-open (lead = 360 min default, `energy_const.py:423`: summer ~08:00; **winter ~23:00**, boundary 05:00 per `_is_charge_window_open` docstring `:584-599`) the trailing 15-min rate reflects overnight hold/drain (≈0 or negative — the hold path pins reserve=int(soc), so rate≈0), so `projected ≈ soc < target` and ATTAIN fires on **essentially every good/moderate/excellent day the battery enters the window below target** — including winter pre-dawn where solar cannot yet have "failed to deliver". Consequences: (a) the plan's "Arbitrage gate unchanged" guardrail is bypassed by another route — every good day becomes a grid-charge-to-80 day; (b) on genuinely good days the battery is full before solar ramps, so solar exports at the low rate while the 80% was bought from grid — a per-day cost regression relative to the prior "tomorrow good → hold, solar refills free" strategy. The projection has no solar-forecast/sunrise term; "realized divergence" (operator-ratified principle) is only measurable after the solar window begins. **Fix shape:** add an expected-solar term or gate the predicate on `now` past sunrise/solar-window-start (or restrict eligibility to a shorter window before the boundary on good days). Needs operator ratification either way — flag, don't silently widen.

#### A-MED-1 — ATTAIN savings accounting books solar-driven SOC rise as grid-displaced savings
**Severity: MEDIUM.** `energy.py:2073-2076` counts all positive SOC delta during ATTAIN toward arbitrage savings at `(displaced − off_peak) × RTE` (`:2100-2104`). But ATTAIN's premise is good-solar days where solar can resurge mid-charge (cloud lifts, EV finishes); with reserve held at 80, solar-driven SOC rise during ATTAIN is booked as grid arbitrage — the exact inflation the HOLD exclusion comment (`:2062-2066`) exists to prevent. Materially worse for ATTAIN than for CHARGE (poor-day, low-solar context). Fix: cap counted kWh by measured grid-charge power (battery_charge_kw is already computed in `_effective_import_kw`), or accept + document the skew.

#### A-LOW-1 — Per-tick INFO "Attainability CHARGE fired" log
`energy_battery.py:1374-1378` logs at INFO on **every** tick ATTAIN persists (arbitrage CHARGE has no per-tick equivalent). With A-CRIT-1's flap this becomes log churn. Log on phase entry only.

#### A-LOW-2 — Unknown TOU period fall-through reaches ATTAIN
`:1279-1281` treats an unrecognized period as off-peak (pre-existing v4.3.4 behavior); ATTAIN inherits it, so a TOU-engine glitch could grid-charge outside off_peak. Inherited risk, document only.

#### Verified OK (in-lane)
- **Units/signs:** rate is %SOC/h from SOC deltas; `soc + (mins/60)×rate` is dimensionally consistent; negative (discharging) rate projects *downward* → fires, correct direction (`:902-919`).
- **DST/day-boundary:** minutes via tz-aware `total_seconds()` (`:921-933`); no naive hour math. K=3 warm-up defers correctly (≥2 samples required; sample recorded before predicate, `:1321-1322`).
- **State-matrix invariant:** ATTAIN unreachable during peak/mid_peak — those branches return at `:1195-1275` before the off-peak block; storm/grid-disconnect/envoy-unavailable short-circuit upstream (`:1111-1191`).
- **Reserve restore path:** every tick re-emits reserve; at the boundary the mid_peak/peak branches command their own reserve and `_result()`'s default `charge_from_grid=False` issues turn_off (`:1491-1502`) — no stuck-at-80 path while the decision cycle runs.
- **EVSE observe-only scope:** energy.py:2447-2449 gate remains `== ARBITRAGE_PHASE_CHARGE`; ATTAIN excluded as planned.
- **Precedence vs arbitrage:** gate-open returns at `:1291-1299` before ATTAIN; no double-command path on poor days.
- **Rate-window per-chunk reset:** `reset_arbitrage_chunk` clears `_attain_soc_history` (`:1062`) — yesterday's rate cannot poison a new chunk.

**Summary: 1 CRITICAL, 2 HIGH, 1 MEDIUM, 2 LOW. Do not deploy before A-CRIT-1 + A-HIGH-1 are fixed; A-HIGH-2 needs an operator decision.**

### Review B — window/boundary/reboot races + Bug Class #51 sibling

**Reviewed:** commit `7d675e2` on `feature/ec-hc-reboot-decision-pickup`, 2026-06-12.
**Framing:** reboot-mid-window races, TOU boundary correctness (Bug Class #51 family), D2 fix idempotence. Written independently of Reviews A/C; convergences noted post-hoc.

#### Findings

**B-HIGH-1 — ATTAIN exit actively unwinds an in-flight charge → closed-loop bang-bang flap (no-flap AC violated; comment-code divergence). [Independently converges with A-CRIT-1 defect 2]**
`energy_battery.py:1311-1316` claims "the `attain` phase token stays asserted across ticks until projection succeeds OR the chunk completes" — nothing implements a latch. `_should_attain_peak_buffer` (:950-983) is memoryless and its observed rate INCLUDES attain's own grid charging (~16 kW per the addendum). Sequence: ATTAIN fires → charge onset 20-40 min later → K=3 window rate jumps → `projected ≥ target` at SOC far below target → predicate False → falls through to drain path, which emits `switch.turn_off` + reserve drop (`_result` :1491-1502, drain :1410-1432) → rate decays → re-fires. Duty-cycles the Enphase cloud lever until SOC reaches target, wasting roughly half the catch-up window. `test_persistence_then_completion` (test_attainability_branch.py:393) uses a flat rate=0 trajectory — structurally cannot exercise the feedback loop. **Fix:** latch attain-active; exit only on `soc ≥ target` (→ HOLD-shaped decision), window close, or guard lock.

**B-HIGH-2 — `_should_attain_peak_buffer` never consults `_arbitrage_chunk_completed` → guard lock is a no-op for ATTAIN. [= A-HIGH-1 / C-HIGH-1; three-way independent convergence]**
Guard-lock sets `_arbitrage_chunk_completed = True` (:1342) but the predicate has no chunk check — the first under-cap tick resets the streak (:1373) and re-fires ATTAIN in the same chunk, violating plan AC "locks the chunk identically to arbitrage CHARGE" (arbitrage consults it at :723). `test_guard_locks_chunk_after_consecutive_trips` (:461) stops at the lock tick. Corollary: the completion latch in `_get_attainability_decision` (:1006-1009) is dead code (= C-LOW-4). Bug class: latch-not-consulted.

**B-HIGH-3 — Reboot mid-ATTAIN: the one-tick rate-None "defer" actively unwinds the hardware, then re-arms (the exact reboot-mid-charge-window race this cycle exists to fix). [UNIQUE to B]**
Post-boot inside the charge window with hardware mid-charge (charge_from_grid ON, reserve 80 at the Envoy): `_attain_soc_history` is empty → tick 1 returns defer (:973-976) → execution FALLS THROUGH to the drain/hold fallback, whose `_result` reads cfg=ON and emits `switch.turn_off` plus a reserve drop to drain_target/`int(soc)` (:1410-1432). Ticks 2-3 the window seeds, ATTAIN re-fires → `turn_on` + reserve 80. Guaranteed OFF→ON round-trip + reserve thrash 80→~25→80 within 10 min of boot, against the measured 20-40 min Enphase actuation lag (commands may land mid-"enabling…" pending). The plan said cold-boot "defers (returns False) for one cycle" — defer ≠ unwind. Note: H1's RAM latch will NOT survive reboot, so this needs its own fix. **Fix:** when predicate conditions 1-3,5 hold but rate is None, emit a hold-current-state decision (no cfg-off, no reserve change) for the defer tick instead of falling through to drain. The plan's D2 Live criterion ("reboot mid-charge-window resumes within one cycle") will show *resumption* and look like a PASS while hiding the unwind — live validation must also assert NO turn_off was issued in the first post-boot cycle.

**B-MED-1 — No minimum-remaining-window floor: a fire at `mins < ~35` is pure-loss cloud churn.**
Predicate requires only `mins > 0` (:966-968). The operator's no-floor waiver ("reaching 50% beats holding 10%", plan Q2) predates the addendum's MEASURED ~35-min charge_from_grid enable lag: a 13:50 fire delivers ~zero off-peak charge before the 14:00 mid_peak branch commands turn_off. A floor ≈ the onset-lag constant isn't "declining to charge" — it's "don't issue commands physics cannot honor." Flag for operator re-decision against the new measurement; MEDIUM because operator-ratified.

**B-MED-2 — Covers reboot seed clobbers operator manual closes (override ledger is RAM-only).**
`_reboot_pickup_seed_closed_set` (hvac_covers.py:316-353) claims ANY cover at position ≤ 30 inside the window, but `manual_override_until` lives on the in-memory ManagedCover (:83) and is empty post-boot — a cover the OPERATOR closed pre-reboot (or during the outage) is adopted into `_hvac_closed` with no override stamp and auto-reopened at window end (:430-454). Pre-fix behavior left such covers alone. Amplified by CM entry reload: a fresh CoverController re-runs the seed mid-day AND loses accumulated override stamps on every reload. **Fix candidates:** persist override stamps, or stamp seeded covers with an override-grace, or seed only covers at the exact HVAC close position.

**B-MED-3 — Covers seed gate is narrower than the hold gate → the #15 gap persists in the hysteresis band.**
Seed requires `outdoor_temp >= _cover_close_temp` (:333), but live covers stay legitimately HVAC-closed through the hysteresis band — the hold condition is `temp > _cover_open_temp` (:407). Boot with `open_temp < temp < close_temp`: seed skips, `_hvac_closed` stays empty, covers are stranded closed past window end (the reopen loop iterates an empty set) — exactly the original #15 failure shape. Same miss for covers closed via the occupied-close path (:541), which doesn't gate on outdoor temp at all. **Fix:** seed condition should mirror the hold condition (`temp > _cover_open_temp`).

**B-LOW-1 —** Stale comment at hvac_covers.py:389: "See `_maybe_reboot_pickup()`" — no such method exists (it's `_reboot_pickup_seed_closed_set`).
**B-LOW-2 —** Lazy `getattr(self, "_reboot_pickup_done", False)` in hvac_covers copies hvac_predict's pattern without hvac_predict's justification (the 3000-char `__init__` test-window constraint). Declare the field in `CoverController.__init__`. (Verified: no reader of either module's flag before `update()` runs.)

#### Verified OK (framing checklist)

- **Boundary math vs Bug Class #51:** `get_next_high_rate_transition` (energy_tou.py:318-360) walks real datetimes deriving season per call — midnight-, month-, and season-schedule-safe; `_minutes_to_high_rate_boundary` uses real seconds. DST: absolute-hour stepping with per-step local-period reads stays self-consistent (≤1 h wall-clock skew twice yearly at 2 AM, hours from any boundary). No #51 recurrence in the new boundary math.
- **Reboot AT the boundary (13:58-14:02 class):** boot at 14:01 → `tou_period=mid_peak` → off-peak branch unreachable; the mid_peak `_result` reads cfg=ON and emits turn_off — a pre-reboot attain charge unwinds cleanly at the boundary. The `mins <= 0` guard (:967) is redundant-but-correct.
- **Inventory #1 reclassification (chunk reset → OK) is correct:** `_arbitrage_chunk_completed` is RAM-only; reboot resets it and Phase 1 `soc ≥ target → HOLD` (:717) prevents spurious re-CHARGE. No DB-persisted energy-state key feeds the chunk latch; the KV-restored EVSE pause sets are untouched by this cycle.
- **D2 #12 (pre-cool/pre-heat flags):** daily-reset-then-pickup ordering is correct (hvac_predict.py:195-232); once-per-process flag + date-keyed reset handles midnight rollover; boot inside the lead window leaves flags False (single re-fire, documented as acceptable); pre-heat hour math correct for [OFF_PEAK_END−lead, OFF_PEAK_END); CM-reload re-run is harmless (pure clock function); no reader of `_reboot_pickup_done` before `update()`.
- **EVSE non-interference (B checklist):** energy.py is savings-accounting inclusion of ATTAIN (:2065-2074) + a comment-only annotation on the :2436 pause gate, which stays `== ARBITRAGE_PHASE_CHARGE` — ATTAIN neither pauses nor resumes EVSE; no manually-paused-EVSE re-resume path; force-charge restore untouched (#7 deferred). Matches plan +13/-1 intent.
- **Degraded-Envoy boot:** `envoy_available` short-circuit precedes the branch (:1111); `_record_attain_sample` skips None SOC; guard `snap is None` → fires-without-guard, byte-parity with arbitrage CHARGE (:753-754). No false attain trigger from None telemetry.
- **Per-chunk rate-window reset:** `reset_arbitrage_chunk` clears `_attain_soc_history` (:1062) on TOU transition INTO off_peak — yesterday's rate cannot cross the day boundary into a new chunk.

#### Review B summary

| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 3 | B-HIGH-1 (flap/unwind; =A-CRIT-1.2), B-HIGH-2 (chunk lock not consulted; =A-HIGH-1/C-HIGH-1), B-HIGH-3 (reboot defer-unwind race — unique) |
| MEDIUM | 3 | B-MED-1 (late-start floor vs 35-min lag), B-MED-2 (cover override clobber), B-MED-3 (seed/hold gate mismatch) |
| LOW | 2 | B-LOW-1, B-LOW-2 |

The three HIGHs share one fix locus: give ATTAIN real chunk/latch semantics (consult `_arbitrage_chunk_completed`, latch active-until-complete, and hold — don't drain — on the defer tick). Three framings converged independently on the lock/latch defect — deploy blocker. Re-test with a closed-loop trajectory (rate responds to commanded charging); the current open-loop fixtures structurally cannot catch B-HIGH-1/3.

### Review C — EVSE interaction + test authority

**Reviewer C, 2026-06-12. Commit reviewed: `7d675e2`. Findings empirically verified (code traced + tests/mutation independently re-run). Written without sight of Review A; convergences noted post-hoc.**

#### C-HIGH-1 — Attain branch does not honor the guard chunk-lock; lock is decorative
**Severity: HIGH.** Bug class: *shared-primitive state divergence / no-flap violation*. **Independently converges with A-HIGH-1.**
`_should_attain_peak_buffer` (`energy_battery.py:976-1012`) never checks `_arbitrage_chunk_completed`. Empirically reproduced via the real `determine_mode` (4-tick trajectory, guard cap 12 kW, net 15 kW):
- Tick 2 locks the chunk → WARN "Chunk locked; falling through to drain-target path."
- Tick 3 (still over cap): branch RE-ENTERS, trips=3, **re-WARNs identically every 5-min tick** and overwrites `_arbitrage_guard_aborted_at/_kw`.
- Tick 4 (guard clears, chunk still locked): **ATTAIN fires anyway** (`arbitrage_phase=attain`, `charge_from_grid=True`).

Contradicts (a) the plan criterion "locks the chunk identically to arbitrage CHARGE" (arbitrage Phase 2 at `:723` returns WAIT on `chunk_completed`; attain has no equivalent), (b) the abort diagnostics, (c) the no-flap criterion. Cross-ripple: attain sets the SHARED `_arbitrage_chunk_completed`, so a mid-chunk forecast reclassification to poor would lock arbitrage CHARGE out via a flag attain itself ignores. Fix: pick ONE semantics — either honor the lock in the predicate, or (if retry-on-clear is the intended catch-up behavior) don't set the shared lock/diagnostics and demote the repeated WARN. **Test gap:** `test_guard_locks_chunk_after_consecutive_trips` stops at tick 2 — exactly before the divergence; extend to ticks 3-4.

#### C-MED-1 — The v1 observe-only EVSE guardrail has zero test authority
**Severity: MEDIUM.** Bug class: *untested load-bearing invariant + vacuous structural test*.
The cycle's central scope guard — `energy.py:2449` `arbitrage_charging == ARBITRAGE_PHASE_CHARGE` only, ATTAIN must NOT pause EVSE — is enforced solely by comments. `TestBugClass22Audit` text-greps the hvac mapping and savings inclusion but has NO assertion on the EVSE gate; a future edit adding ATTAIN to that comparison silently converts v1 into an EVSE-coordination lever with no failing test. Additionally `test_attain_recognized_in_arbitrage_cycle_savings` asserts only `"ARBITRAGE_PHASE_ATTAIN" in src` — vacuously satisfied by the comment block at `:2436` alone. Fix (small): structural assertion that the `arbitrage_charging` assignment excludes ATTAIN + tighten the savings grep to the actual tuple expression.

#### C-VERIFIED — EVSE guard math is NOT self-defeating (the framing's core question)
`_effective_import_kw` (`energy_battery.py:650-656`) subtracts `max(0, battery_power_w)` from `net_power_w` before the cap compare. With attain pulling ~16 kW battery charge + EV ensure-on active: the battery's own draw is excluded; only house+EV draw trips the 12 kW guard — v4.5.0 intent preserved; attain cannot abort its own chunk via its own draw. Fail-safe preserved (battery sensor None → no subtraction → guard tightens, never uncaps). **C-LOW-1 test gap:** no attain-path test exercises the subtraction (e.g. net 18 kW / battery charging 16 kW → effective 2 kW → no trip); the shipped guard test uses battery=0.

#### C-LOW-2 — Enum-consumer completeness sweep (exhaustive grep, custom_components + quality/tests)
- Patched correctly: `energy.py:2074` (savings), `hvac_predict.py:1138` (solar_intent), `energy_battery.py:1578` (`_describe` narrative). Intentionally excluded: `energy.py:2449` (see C-MED-1).
- `sensor.py:6781-6783` switches on decision `mode` (BATTERY_MODE_*), NOT `arbitrage_phase` — ATTAIN renders via the generic else branch identically to arbitrage CHARGE; not a #22 miss.
- `solar_intent` attain→harvest (`hvac_predict.py:1144`): **display-only** — `get_intent_attrs` feeds pre-cool likelihood sensor attributes; grep confirms NO actuation consumer of `solar_intent`, so it cannot enable HVAC solar-banking during a grid charge (`_should_solar_bank` is a separate path). "harvest" while grid-charging is semantically loose but byte-consistent with the pre-existing CHARGE→harvest mapping. OK.
- DB: `arbitrage_cycles` (database.py:1051) has no phase column → ATTAIN savings rows indistinguishable from CHARGE rows. Attribution/observability gap only (and see A-MED-1 for the math skew); schema + existing analytics shape unchanged. LOW.
- `ARBITRAGE_PHASE_ATTAIN` is a proper constant (`energy_battery.py:65`); the one bare `"attain"` literal in production (`hvac_predict.py:1138`) is pinned by `test_attain_phase_token_value`. INFO.
- No NM/notification/diagnostics consumer string-matches the phase. Sweep complete.

#### C-VERIFIED — Test authority (independent re-runs, this session)
- **Real code paths:** all 16 attainability tests drive the real `BatteryStrategy.determine_mode` + real `TOURateEngine`; D2 tests drive real `CoverController.update()` / `HVACPredictor.update()` via `object.__new__`. No mirror tests; no test asserts its own writes.
- **Mutation check re-run by Reviewer C:** inverted the `projected < peak_buffer_target` return tuples → **8 failed / 8 passed** (matches builder; bar ≥6; failures spread across math/no-flap/cold-boot/guard/late-start/non-regression). Reverted → 16/16; working tree clean post-revert.
- **Reverse-order proof re-run:** `test_reboot_pickup_d2.py` ↔ `test_hvac_fan_control.py` pass in BOTH orders (14/14 each way).
- **Relaxed loader (`_load`):** replaces a registered module only when `getattr(mod, "__file__", None) is None`. MagicMock raises AttributeError on dunder access → sentinel detection works; any file-loaded real module carries `__file__` and is never clobbered. Residual risk limited to hand-built `types.ModuleType` stubs lacking `__file__` — no sibling registers one for the loaded submodules (siblings use MagicMock). SAFE as documented.
- **3 newly-passing baseline tests (`TestHVACPredictorNetPower`):** pass for the RIGHT reason. Mechanism verified: `test_envoy_auto_derive.py:307` imports `hvac_predict` INSIDE the test method at run time, by which point `test_hvac_fan_control.py`'s module-level `setdefault(..., MagicMock())` had poisoned `sys.modules`; `test_reboot_pickup_d2._load("hvac_predict")` replaces that sentinel with the real module during collection. Empirically isolated: full-collection run ignoring only `test_reboot_pickup_d2.py` → 3 FAIL; including it → 3 PASS. **C-LOW-3 fragility:** those 3 baseline tests now depend on `test_reboot_pickup_d2.py` remaining in the suite; the underlying defect (run-time import resolving a sibling's sentinel) is unfixed in `test_envoy_auto_derive.py`. Document or fix there in a hygiene pass.

#### C-LOW-4 — Dead code in `_get_attainability_decision`
`energy_battery.py` — the `if soc >= self._peak_buffer_target: self._arbitrage_chunk_completed = True` inside `_get_attainability_decision` is unreachable: the predicate returns False when `soc >= target`, so the builder is never called in that state. Same root as A-CRIT-1 defect 1; fold into that fix.

#### Review C summary
| Severity | Count | Findings |
|---|---|---|
| CRITICAL | 0 | — (A-CRIT-1's oscillation axis was outside this framing; C concurs with its defect-1 via C-LOW-4) |
| HIGH | 1 | C-HIGH-1 (= A-HIGH-1, independently confirmed with a live repro) |
| MEDIUM | 1 | C-MED-1 observe-only EVSE guardrail untested + vacuous text-grep |
| LOW | 4 | C-LOW-1 guard-subtraction test gap; C-LOW-2 arbitrage_cycles phase attribution; C-LOW-3 NetPower pass fragility; C-LOW-4 dead code |

**Recommendation:** fix C-HIGH-1 (lock semantics — jointly with A-CRIT-1/A-HIGH-1) and C-MED-1 (one structural test) before deploy. EVSE observe-only scope, guard exclusion math, enum sweep, and test authority otherwise VERIFIED.

---

## Fix-up pass (2026-06-12)

Operator-ratified contract applied across all three reviews' CRITICAL/HIGH/MED/LOW findings.

### Dispositions

| Finding | Disposition | Evidence |
|---|---|---|
| A-CRIT-1 (no terminal latch / self-referential feedback) | **FIXED** | New `_attain_active` latch (`energy_battery.py:227`); entry predicate consulted only when NOT latched; exit conditions: SOC ≥ target → HOLD, chunk lock, window close, peak-handoff lead, reboot warm-up. `test_rising_rate_does_not_release_or_recommand` (closed-loop feedback test) + `test_persistence_then_completion` (HOLD at target). |
| A-HIGH-1 / B-HIGH-2 / C-HIGH-1 (chunk lock not consulted) | **FIXED** | Predicate consults `_arbitrage_chunk_completed` at `energy_battery.py:1118`; dead latch in `_get_attainability_decision` removed. Extended C's 4-tick repro: `test_chunk_lock_persists_through_4_ticks`. |
| A-HIGH-2 (projection has no solar term — fires on good days) | **FIXED** | `_expected_solar_surplus_pct` adds Solcast remaining × `SOLAR_CAPTURE_FACTOR=0.5`; stale/unavailable Solcast → 0 (fail toward charging). Named scenario tests: `test_good_day_solar_delivering`, `test_incident_shape_fires`. |
| B-HIGH-3 (reboot defer-unwind race) | **FIXED** | `_get_attainability_hold_current_decision` emits zero actions when latched + rate is None; `test_reboot_first_cycle_issues_zero_commands` asserts empty actions list. Note: `test_reboot_pickup_d2.py` is unchanged — the B-HIGH-3 test lives in `test_attainability_branch.py` as it exercises the strategy, not a D2 surface. |
| A-MED-1 (savings grid-attribution skew during ATTAIN) | **FIXED** | `energy.py:2106` skips arbitrage savings row when `battery_power_w <= solar_production_w` during ATTAIN (solar-driven SOC rise is not arbitrage-displaced). |
| B-MED-1 (no 30-min ENTRY floor) | **FIXED** | `ATTAIN_MIN_REMAINING_MIN=30` floor on ENTRY only; latched attain continues below floor. Tests: `test_entry_blocked_at_25min_to_boundary`, `test_entry_allowed_at_exactly_30min`. |
| B-MED-2 (covers seed clobbers operator closes) | **FIXED** | `_reboot_pickup_seed_closed_set` now stamps adopted covers with override grace using `_cover_override_hours`. |
| B-MED-3 (seed/hold gate band mismatch) | **FIXED** | Seed condition now mirrors hold condition (`outdoor_temp > _cover_open_temp`). |
| C-MED-1 (EVSE observe-only guardrail untested) | **FIXED** | Structural test `test_evse_pause_gate_excludes_attain_assignment` asserts the `== ARBITRAGE_PHASE_CHARGE` comparison and anti-asserts the gate never mentions both phases; savings test tightened to the actual tuple. |
| A-LOW-1 (per-tick INFO log) | **FIXED** | Log moved to entry transition + exit transition only (`Attainability ENTERED`, `Attainability HOLD entered`, `Attainability peak-handoff`); per-tick CHARGE re-emit is silent. |
| A-LOW-2 (unknown TOU fall-through) | **FIXED** | Predicate now explicitly guards unknown TOU at `energy_battery.py:1127-1130` (returns False). |
| B-LOW-1, B-LOW-2 (stale comment + lazy getattr) | **FIXED** | Stale `_maybe_reboot_pickup` comment updated; `_reboot_pickup_done` declared in `CoverController.__init__`. |
| C-LOW-1 (guard-subtraction test gap) | **FIXED** | `test_battery_charge_excluded_from_guard_during_attain` exercises net 18 kW / battery charging 16 kW → guard does not trip. |
| C-LOW-2 (arbitrage_cycles phase attribution) | **DEFERRED** | Schema column add is outside fix-up scope; tracked in backlog. |
| C-LOW-3 (NetPower test pass fragility) | **DEFERRED** | Documented in cycle ledger; fix belongs in `test_envoy_auto_derive.py` hygiene pass. |
| C-LOW-4 (dead latch code) | **FIXED** | Removed — folded into A-CRIT-1 fix; the completion latch now lives in `_get_attainability_hold_decision`. |

### D1b mid-peak continuation — invariant-change callout

The state-matrix invariant "battery does not charge during mid_peak" is REPLACED by:
**"battery may charge during mid_peak iff (a) attain latched OR entry predicate fires, (b) mid_peak rate < peak rate (read from live TOU engine, no hardcoding), (c) SOC < peak_buffer_target, (d) peak still ahead (`peak_ahead_before_offpeak`)."** Charging during PEAK remains structurally impossible — peak branch has no attain pathway. Reason string carries the stage name (`mid_peak→peak coverage`). Operator-mandated.

### Mutation-authority evidence (fix-up pass)

| Mutation | Result | Named tests breaking |
|---|---|---|
| (i) Invert entry predicate `<` → swap True/False | 13 failed | math, no-flap, late-start, good-day, latch tests, 30-min floor, mid-peak entry, guard-subtraction |
| (ii) Break the latch (`if self._attain_active and False`) | 3 failed | `test_persistence_then_completion`, `test_rising_rate_does_not_release_or_recommand`, `test_reboot_first_cycle_issues_zero_commands` |
| (iii) Bypass chunk-lock consult (`and False` in predicate) | 1 failed | `test_chunk_lock_persists_through_4_ticks` |
| (iv) Flip D1b rate-spread gate (`<` → `>=`) | 1 failed | `test_mid_peak_pre_peak_low_soc_enters_attain` |

All reverted; tree clean post-mutation; 31/31 cycle tests pass.

### Suite tally (fix-up pass tip)

- **Full suite:** 34 failed / 5715 passed / 29 skipped / 14 errors in 29.35s.
- **Failure-ID diff vs cycle baseline (34F/14E):** ZERO new failures. The +10 passes vs the cycle ledger's 5705 come from the new fix-up tests (latch feedback, reboot HOLD-CURRENT, 30-min floor, D1b mid-peak, EVSE-gate, guard-subtraction).
- **Reverse-order vs `test_hvac_fan_control.py`:** 40/40 in both orders.
- **py_compile:** clean across `energy_battery.py`, `energy.py`, `hvac_covers.py`, `test_attainability_branch.py`, `test_reboot_pickup_d2.py`.
- **Conflict-marker grep:** clean.
- **Debug-print grep:** clean.

### n/a root-cause note

The prior agent's mid-debug `n/a` was an ephemeral artifact — at the moment the agent stopped, the file (or interpreter state) yielded a False return where projected < target should yield True. Empirically resolved by an edit-and-revert touch of the predicate's return lines (file mtime change forced fresh source parse). No semantic code change was needed; the predicate as documented is correct. The test now passes deterministically (`test_incident_shape_fires` PASS, all 26 attainability tests + 5 D2 tests green).

---

## Live validation table (post-deploy)

*(to be filled after deploy + restart; per CLAUDE.md "Record Live Validation Back Into the README" — this ledger holds the cycle-internal record; the README write-back is the durable artefact)*

| Criterion | PASS/FAIL | Observed evidence |
|---|---|---|
| ATTAIN fires on incident-shape day | — | — |
| `arbitrage_phase=attain` on sensor | — | — |
| Reason string carries projection narrative | — | — |
| Simulated reboot mid-charge-window resumes within ≤5min | — | — |
| Cover reboot-pickup re-seeds `_hvac_closed` | — | — |
| Pre-cool day-flag correctly marked after restart-past-peak | — | — |
