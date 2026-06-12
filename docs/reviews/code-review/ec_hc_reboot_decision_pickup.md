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

*(to be filled)*

### Review B — window/boundary/reboot races + Bug Class #51 sibling

*(to be filled)*

### Review C — EVSE interaction + test authority

*(to be filled)*

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
