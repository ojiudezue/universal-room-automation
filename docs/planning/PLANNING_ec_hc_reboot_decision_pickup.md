# PLANNING — EC/HC Time-Anchored Decision Pickup After Reboot + Peak-Buffer Attainability

**Status:** Planning only — no build, no deploy. Filename carries no version (assigned at deploy time).
**Authoring date:** 2026-06-12
**Branch:** `develop` (v5.3.7 just shipped).
**Tier classification — operator-elevated Tier 2-DB.** This cycle changes battery/cost
*strategy* (peak-buffer attainability is a new decision branch in the off-peak path) AND
audits time/window-anchored decisions across EC + HC for reboot-pickup correctness. Both
risks are textbook regression-prone per the standing policy (CLAUDE.md, 2026-06-08): the
attainability branch sits on the battery ↔ grid ↔ cost ↔ EV ripple surface, and the
reboot-pickup inventory edits a *shared primitive* (decision idempotence) consumed by
multiple coordinators. **3 framing-disjoint reviews + live validation + README write-back.**

**Proposed framings (disjoint by construction):**
- **A — Cost / strategy correctness + no-flap.** Attainability projection math (rate
  estimator window, units, signs), interaction with the existing arbitrage gate (must NOT
  shadow or duplicate it on poor/very_poor days), the WAIT→CHARGE→HOLD transition can't
  oscillate as the projection wobbles cycle-to-cycle, charge-from-grid action is
  idempotent (same lever as arbitrage path), guard precedence (storm, grid-import guard,
  reserve floors) preserved. Includes the late-start partial-charge case ("reaching 50%
  beats holding 10%") — what happens at the high-rate boundary if attainability fires
  with only minutes to spare.
- **B — Window/boundary/reboot races + Bug Class #51 sibling.** The reboot-pickup
  inventory is this reviewer's primary surface: every flagged GAP must have its proposed
  fix reviewed for cold-boot, warm-reload, mid-window, and TOU-boundary cases. Day-
  boundary semantics (the v4.7.29 fix established the bug class) must not regress: a fix
  that makes a decision "re-evaluate idempotently from current state" cannot accidentally
  re-arm a chunk that already completed, re-resume an EVSE the operator manually paused,
  or double-restore a force-charge window. Includes interaction with v5.3.7's always-
  register pattern (degraded-Envoy boot must not falsely trigger attainability
  charge-from-grid because `net_power_w` is None).
- **C — EVSE interaction + test authority.** The incident root cause was EV off-peak
  ensure-on (a correct, durable behavior) eating all morning solar. This reviewer owns:
  (1) the v1 *observe-only* scope guard is real — attainability reads net rate, does NOT
  signal EVSE to back off, does NOT add an EVSE coupling lever; (2) the inventory's
  treatment of `energy_pool.py`'s EVSE off_peak ensure-on (v4.7.28) boot path is
  correct; (3) test fixtures drive production decision paths (no hand-written
  arbitrage/attainability state mutation), use the real schedule from `energy_const.py`,
  cover both incident-shape (good solar day, EV chewing through it) and "good solar
  delivers as expected" non-regression, and prove mutation-authority (inverting the
  attainability predicate breaks ≥N tests).

---

## Institutional context verified

Per CLAUDE.md, this section is the proof-of-work that the planner consulted prior art
before scoping. Reviewers verify during review pass.

### Greps run + reads — REUSED vs NEW

| Proposed surface | Verdict | Evidence |
|---|---|---|
| Attainability decision branch in `BatteryStrategy.determine_mode` off-peak path | **NEW behavior, REUSED scaffolding.** Reuses `_get_arbitrage_decision` action shape (charge_from_grid + reserve_level + result dict at `energy_battery.py:778-855`) and the `_result()` action emitter (`energy_battery.py:1163-1248`). NEW: the projection helper itself + the gate predicate; new arbitrage_phase token (see "no new CONF" caveat). | `energy_battery.py:1092-1161` off-peak branch read end-to-end. `_gate_is_open` (`:650-666`) currently restricts arbitrage to `poor/very_poor` only — the incident's "good" day is the literal hole. Attainability lives as a *parallel* off-peak branch BETWEEN `_gate_is_open` and the drain-target fallback (see D1). |
| Charge window primitive (`_is_charge_window_open`) | **REUSED** at `energy_battery.py:563-578` (next-high-rate-transition minus lead time; correctly midnight-crossing per v4.5.0 D8). Same primitive answers "are we in the pre-peak window" for both arbitrage CHARGE and the new attainability branch — no new clock state. |
| Charge-from-grid action emitter | **REUSED** at `energy_battery.py:1207-1231`. Same lever, same idempotence (diffs against current state of `charge_from_grid` switch). Attainability does NOT add a parallel actuation path. |
| Grid-import guard (`arbitrage_grid_import_guard_kw`) | **REUSED** at `energy_battery.py:637-648` + the consecutive-trip lock at `:730-768`. Attainability CHARGE goes through the SAME guard (per D1: attainability sets `arbitrage_phase` = a new token that the existing guard still inspects via the CHARGE branch). |
| Reserve floor / storm short-circuit / grid-disconnect | **REUSED.** Storm and disconnect short-circuit upstream of the off-peak branch (`energy_battery.py` peak/storm branches near `:1010-1090`); attainability sits *after* those checks. |
| `peak_buffer_target` config | **REUSED** at `energy_battery.py:131-134` + sensor surface at `:1394`. **No new CONF.** Attainability projects against the existing target — same number, new gate. |
| EV off-peak ensure-on (v4.7.28) | **READ ONLY** (`energy_pool.py:488-561`). Verified per the v4.7.28 plan that this is durable + intentional ("solar-first → never drain battery into car → off_peak grid cheapest"). v1 attainability *observes* the consequence (net rate < projection slope); does NOT signal EVSE. C-axis reviewer enforces this guardrail. |
| `arbitrage_phase` token namespace | The existing tokens are `n/a / wait / charge / hold / discharge` (`energy_battery.py:53-75`). **NEW token proposed:** `attain` (or `peak_buffer_catchup`) so the sensor reason string and the existing guard branch can distinguish "arbitrage path CHARGE" from "attainability CHARGE" without renaming anything. *Single new enum value, no new CONF_*, no new entity.* |
| New CONF_*, sensor, entity, signal | **NONE.** Attainability surfaces via existing `arbitrage_phase` + `reason` on `sensor.ura_energy_battery_strategy`. The inventory deliverable (D2) is descriptive — each GAP fix scopes its own surface (if any), but the *default* design is "make the existing periodic re-eval idempotent" with zero new surfaces. |
| Always-register pattern (v5.3.7) | **REUSED CONCEPTUALLY.** D2's preferred fix template is the same philosophy: a decision should be a periodic idempotent re-evaluation of current-time state, not a transition-only event listener. The v5.3.7 ledger codified this for EC startup; D2 extends it to time-anchored decisions inside EC + HC. |

### Prior planning docs consulted

- `docs/planning/PLANNING_v4.5.0_battery_strategy_redesign.md` + `PLANNING_v4.5.0_TRANSITION_NOTES.md` — full read of the arbitrage four-phase state machine (the surface we're adding a fifth branch alongside). Confirms `peak_buffer_target` semantics, `_gate_is_open` rationale (poor/very_poor only), and the explicit "good day = solar fills the battery" assumption the incident invalidated.
- `docs/planning/PLANNING_ev_offpeak_proactive_charging_and_persistence.md` (v4.7.28) — full read. Confirms EV ensure-on is the *correct* behavior the operator wants kept; attainability must not regress it. Confirms `_ev_tou_enabled` is the existing gate.
- `docs/planning/PLANNING_day_boundary_blind_tou_decision.md` (v4.7.29) — full read. Bug Class #51 (day-boundary-blind decisions). The reboot inventory is an explicit sibling sweep of the same risk class, but for *reboot-mid-window* rather than *day-rollover-mid-decision*. Reuses framing language.
- `docs/readmes/README_v5.3.7.md` — full read. Always-register / degraded-Envoy pattern is the canonical example of "make decisions idempotent re-evals of current state" that D2 GAP fixes should mirror.

### Memory bodies pulled

- `feedback_db_sensitive_3x_targeted_reviews.md` + `feedback_tier2db_for_regression_prone.md` — confirms elevated-tier framing requirement.
- `feedback_pre_deploy_zero_bugs_gate.md` — applies at deploy.
- `feedback_fix_lows_in_cycle.md` — LOWs fixed in the same fix-up pass.
- `feedback_parsimonious_room_config.md` — informs the "no new CONF_*" guardrail.
- `project_ev_offpeak_cycle_pickup.md` + `project_ev_pause_post_peak_midpeak_decision.md` — durable EV philosophy ("solar-first → never drain battery into car → off_peak grid cheapest"). v1 attainability is observe-only by explicit operator decision.
- `project_day_boundary_tou_live.md` — Bug Class #51 sibling framing reuse.

### Design docs read

- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` — decision-cycle ordering invariants (TOU → arbitrage → excess_solar → grid_cap → drain → fill_priority). Attainability slots **alongside arbitrage in the off-peak branch**, sharing the same precedence neighborhood, NOT a new layer.
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — for D2 HC surfaces (pre-cool, solar-banking, covers).

### Code locations surveyed end-to-end during scoping

- `energy_battery.py` — full off-peak branch (`:1092-1161`), arbitrage state machine (`:531-855`), charge-window primitive (`:563-578`), grid-import guard (`:602-648`), `_result` emitter (`:1163-1248`), `get_status` (`:1328-1416`).
- `energy.py` — decision timer + interval (`:697-731`), `_decision_interval`, restoration paths for envoy / evse / energy_state KV.
- `energy_pool.py` — EVSE TOU + ensure-on (`:423-568`), excess-solar / fill-priority paths (referenced from v4.7.6 + v4.7.28).
- `energy_tou.py` — `get_next_transition` + `get_next_high_rate_transition` (the v4.7.29 plan flagged the former as a separate suspect; OUT OF SCOPE here unless an inventory GAP hits it).
- `hvac.py` — decision timer (`:619-626`), `_async_decision_cycle` is periodic 5-min interval.
- `hvac_predict.py` — pre-cool/pre-heat triggers (`_should_weather_pre_cool` and `_check_pre_conditioning`), `PEAK_HOUR_START` gate (`:389`), solar-banking (`:441-468`), end-pre-cool flag-clear (`:386-391` / `:536-541`).
- `hvac_covers.py` — solar-hour cover-close window (`:340-369`); hour-based decision inside the periodic HVAC cycle.

---

## D1 — Peak-Buffer Attainability (the strategy gap)

### Problem statement (concrete, from the incident)

Good summer solar day, `arbitrage_enabled=true`, `peak_buffer_target=80`,
`charge_window_opens_at=08:00`, mid_peak starts 14:00 CDT. Battery entered mid_peak at
~12% SOC despite 6-10 kW solar production all morning, because:
- `_gate_is_open` returns False for `target_day_class="good"` (`energy_battery.py:660-666`)
  → arbitrage CHARGE is *structurally* unreachable on good days.
- The fallback path (drain-target) just *holds* SOC when SOC ≤ drain_target
  (`energy_battery.py:1151-1161` — the literal "Off-peak hold — SOC X% <= target Y%
  (tomorrow good)" reason string in the incident logs).
- EV off-peak ensure-on (correct, durable behavior) consumed essentially all production
  → net charge rate ≈ 0 → SOC crawled.
- The implicit "good day → solar will fill the battery" assumption was never
  re-validated against actual loads. By the time anyone noticed, the high-rate window
  arrived with the buffer empty.

### Design

Add a new off-peak decision branch — **attainability gate** — that runs when
`_gate_is_open` is False AND the charge window is open (or projected to close before
the high-rate boundary). Single new helper, single new arbitrage_phase token, no new
CONF, no new entity.

**Insertion point.** `energy_battery.py:1106` — between the existing `_gate_is_open()`
arbitrage branch and the drain-target fallback. Pseudocode shape (NOT final code, for
review framing only):

```
if self._gate_is_open(now, target_day_class):
    return self._get_arbitrage_decision(...)          # existing (poor/very_poor)
if self._should_attain_peak_buffer(soc, now):         # NEW
    return self._get_attainability_decision(soc, now, ...)
# existing drain-target fallback unchanged
```

**Predicate (`_should_attain_peak_buffer`).** Returns True iff ALL of:
1. `self._peak_buffer_target` is set AND `soc is not None` AND `soc < peak_buffer_target`.
2. `self._is_charge_window_open(now)` — i.e. we are within `arbitrage_charge_lead_time_min`
   of the next high-rate transition. This is the SAME primitive the arbitrage CHARGE
   path uses; reusing it means the window semantics are byte-identical.
3. Projected SOC at the high-rate boundary, given observed net charge rate (or a
   conservative forecast surplus), is `< peak_buffer_target`. The projection is:
   `projected_soc = soc + (minutes_to_boundary / 60) × observed_net_charge_rate_per_hour`.
4. Storm/grid-disconnect short-circuit upstream guards already exited (we're past those
   branches by construction).

**Projection — observed net charge rate.** Use a short trailing-window estimate of the
delta in `battery_power_w` net-of-discharge sign, smoothed across the last K decision
cycles (e.g. K=3 at 5-min cadence = 15 minutes). On the cold-boot case where the
window is empty, the predicate **defers** (returns False) for one cycle to let the
window seed — this avoids a false trigger from an unknown rate. *Reviewer A owns the
math, sign conventions, and stale-rate edge cases. Reviewer B owns the cold-boot
behavior.*

**Action (`_get_attainability_decision`).** Same shape as `_get_arbitrage_decision`:
- `arbitrage_phase = ARBITRAGE_PHASE_ATTAIN` (new enum value in `energy_battery.py:53-75`).
- `charge_from_grid = True` (idempotent via existing `_result()` emitter).
- `reserve_level = self._peak_buffer_target` (same lock the arbitrage path uses).
- `reason = f"Peak-buffer attainability — projected SOC {projected:.0f}% < target {target}% "
  f"at high-rate window (observed net rate {rate:+.1f}%/h, {mins} min remaining)"`.
- `arbitrage_active = True` (so the sensor and downstream consumers see "battery is in
  a managed-charge state", same as arbitrage CHARGE).

**Reuse the existing chunk-completion + grid-import-guard machinery.** When the
projection eventually passes (rate improves; e.g. EV finishes; solar surges) the
predicate returns False, the branch is not taken, and behavior falls through to the
drain-target fallback (which on a good day with SOC ≥ drain_target just drains/holds
normally). Mark `_arbitrage_chunk_completed = True` once attainability CHARGE has
brought SOC to `peak_buffer_target`, mirroring the arbitrage path so we don't oscillate.

**Late-start partial charge.** If the predicate fires with `< arbitrage_charge_lead_time_min`
remaining (operator manually toggling arbitrage on late, or a long window where
observed rate stayed at zero for hours), the branch still triggers and pulls grid for
whatever time is left. Operator stated: "reaching 50% beats holding 10%." No floor on
how late attainability can engage; it just engages until the boundary.

### Scope guardrails (operator-mandated)

- **No new CONF knobs.** Use existing `peak_buffer_target`, `arbitrage_charge_lead_time_min`,
  `arbitrage_grid_import_guard_kw`. The K-window for rate observation = a module
  constant in `energy_const.py`, NOT a configurable.
- **No EVSE coupling.** v1 is observe-only. Attainability reads the net rate (which
  reflects whatever EV / pool / HVAC is doing) and acts on the battery side only. A
  future cycle may add coordination — explicitly out of scope here.
- **Arbitrage gate unchanged.** Do NOT widen `_gate_is_open` to include "good" days; the
  arbitrage path remains forecast-class-only. Attainability is a *separate* branch with
  *different* semantics ("the assumption failed, catch up") and a *different* phase token.

### Acceptance criteria

- **Verify (math):** unit tests on `_should_attain_peak_buffer` with synthetic
  `(soc, minutes_to_boundary, observed_rate, target)` tuples cover (a) good-day
  incident shape (soc=12, rate≈0, mins=180, target=80 → True), (b) good-day true
  (soc=12, rate=+10%/h, mins=180, target=80 → False, will arrive at 42% naturally —
  but 42 < 80, so True; calibrate predicate to project AT-target), (c) high SOC nop
  (soc=82, target=80 → False), (d) post-window (mins ≤ 0 → predicate False; arbitrage
  CHARGE / discharge owns this region).
- **Verify (precedence):** test that on a `poor`-class day, `_gate_is_open=True` and
  the arbitrage CHARGE branch wins (attainability branch never reached). Mutation
  authority: if the branch order is swapped in production, ≥1 test fails.
- **Verify (no-flap):** simulated trajectory across 12 decision cycles where the
  projection wobbles around target — `arbitrage_phase` does not oscillate ATTAIN↔WAIT
  more than once.
- **Verify (guard precedence):** grid-import guard trip on consecutive ticks while in
  ATTAIN locks the chunk identically to arbitrage CHARGE (reuses the same machinery).
- **Sensor:** `sensor.ura_energy_battery_strategy.arbitrage_phase = "attain"` and the
  `reason` attribute shows the projection narrative during the incident shape.
- **Test:** `test_attainability_predicate_*`, `test_attainability_precedence_*`,
  `test_attainability_no_flap`, `test_attainability_grid_import_guard_lock`,
  `test_attainability_late_start_partial_charge`, `test_good_day_solar_delivers_no_attainability`.
- **Live:** Reproduce incident shape on a good solar day with EV ensure-on consuming
  morning production. Verify `arbitrage_phase` flips to `attain` within one decision
  cycle once the projection drops below target, `charge_from_grid` switches ON via the
  EC, SOC trajectory turns positive, phase moves to `hold` (or attainability completes
  → falls through to drain) before the 14:00 boundary. Validated entries in the README:
  entity attribute reads + at least one decision-log row showing the attainability
  reason string.

---

## D2 — Reboot Decision-Pickup Inventory (operator-mandated)

### Goal

A complete inventory of EVERY time-anchored or window-anchored decision in EC + HC,
classified by whether it re-evaluates correctly when a reboot lands MID-window. For
each: `(file:line, trigger mechanism, verdict OK | GAP, proposed fix if GAP)`. The
inventory IS the deliverable — even where no code change results. Bug Class #51
(day-boundary blind) is the sibling: this is the *reboot-mid-window* class.

### Fix-shape philosophy

Reviewer B's preferred default: **make decisions idempotent re-evaluations of
current-time state**, the same philosophy as the v5.3.7 always-register fix. Examples:
- BAD pattern: "on transition into off_peak, do X" (a reboot inside off_peak misses X).
- GOOD pattern: "every cycle, if `tou_period == off_peak` AND `state X is not the
  applied state`, apply X" (any cycle re-converges; reboot pickup is automatic).

Some decisions are intrinsically transition-only (e.g. snapshot-and-store
for-restoration-later); for those the fix is to persist enough state to re-derive on
boot, or to also drive the same path from a periodic re-eval, not just the transition.

### Inventory table (to be filled by the build; planning shows the surfaces and the
required column shape)

| # | Surface | File:line | Trigger | Verdict | Proposed fix (if GAP) |
|---|---|---|---|---|---|
| 1 | Arbitrage chunk completion + reset | `energy_battery.py:857-877` (reset on TOU transition INTO off_peak) | Transition event (TOU period change) | **GAP candidate** | A reboot landing inside off_peak skips the reset because the TOU transition fired before reboot. Reset is currently the *only* clear path. Fix: also reset on boot when `tou_period == off_peak` AND `_arbitrage_chunk_completed` was restored True AND we cannot prove the chunk was actually completed this off-peak chunk (timestamp restored < off-peak-start). Investigate persistence of `_arbitrage_chunk_completed` first (verify whether it survives restart at all — if not, gap is the opposite: chunk gets reset for free on boot, which may itself be a *different* gap on the arbitrage path). |
| 2 | Arbitrage CHARGE/HOLD/WAIT phase resolution | `energy_battery.py:668-776` | Periodic 5-min decision cycle | **OK** (verify) | Phase is recomputed every tick from current SOC + window + gate. Reboot mid-window picks up on next cycle. Verify nothing depends on a phase-transition *event* (signal dispatch) that would be missed. |
| 3 | Charge-window-open primitive | `energy_battery.py:563-578` | Read on every tick | **OK** | Stateless; reads next-high-rate-transition fresh each call. |
| 4 | Off-peak drain-target hold/drain | `energy_battery.py:1124-1161` | Periodic 5-min decision cycle | **OK** | Pure function of current SOC + drain_target. |
| 5 | TOU period transitions (EVSE pause/resume) | `energy_pool.py:459-568` | Period change detected by reading current `tou_period` each cycle | **OK** (verify boot path) | The branch is `if tou_period in (peak, mid_peak): pause; elif tou_period == off_peak: ensure-on`. A reboot in mid_peak re-pauses; a reboot in off_peak re-ensures-on. Verify the first cycle after boot reads a real `tou_period` (not None / "unknown"). |
| 6 | EVSE off_peak ensure-on (v4.7.28) | `energy_pool.py:488-561` | Periodic re-eval each cycle | **OK** (validated live v4.7.28) | Per the v4.7.28 README this is already idempotent ensure-on. Cite live evidence + sanity-check the boot path under degraded-Envoy (v5.3.7 condition: `net_power` None → the ensure-on path must still run, not silently no-op). |
| 7 | EVSE force-charge override window | `energy_pool.py:525-534` + Switch RestoreEntity (`switch.py:802-854`) + KV mirror (v4.7.28) | Persisted; checked each cycle | **GAP partially closed by v4.7.28** | Verify the v4.7.28 KV-mirror landed for `_force_charge_until` (the plan documented it as proposed). If reboot mid-override doesn't restore, fix is to use `dt_util.parse_datetime` (Bug Class #13/#21) and consult the KV value as the canonical source. |
| 8 | EVSE fill-priority pause persistence | `energy_pool._paused_by_fill_priority` | Per v4.7.28 plan, mirrored to `energy_state` KV | **GAP partially closed by v4.7.28** | Verify it actually shipped. If not, plan to mirror per v4.7.28 D-section. |
| 9 | EVSE arbitrage pause | `energy_pool._paused_by_arbitrage` | NOT persisted (v4.7.28 deferred) | **OK by analysis** — re-derives from next tick's `decision["arbitrage_phase"]`. One-cycle attribution skew on reboot is acceptable per v4.7.28 plan §9. Document the verdict, don't fix. |
| 10 | EV grid-cap / battery-drain pause sets | `energy_pool._paused_by_grid_cap` / `_paused_by_battery_drain` | KV-restored (`energy.py:876-894`) | **OK** | Already persisted + restored. Verify restore staleness guard exists or is added per v4.7.28 D-section. |
| 11 | TOU `get_next_transition` cross-day walk | `energy_tou.py:199-235` | Stateless; called by HVAC `max_runtime` (`energy.py:3105`) | **GAP — flagged by v4.7.29 plan, OUT OF SCOPE for this cycle; hygiene-bucket** | Wrap-to-next-day branch reads today's season-rate table. Sibling of Bug Class #51. Inventory documents and references the v4.7.29 hygiene-bucket deferral. |
| 12 | HVAC weather pre-cool trigger | `hvac_predict.py:541-560` + `_check_pre_conditioning` (`:344-410`) | Periodic via HVAC decision cycle (5-min `async_track_time_interval`) + day-flag `_pre_cool_triggered_today` | **GAP candidate** | The day-flag prevents re-triggering AFTER pre-cool completed today. A reboot mid-day re-initializes the flag to False; if the conditions are still met post-reboot, pre-cool re-fires (possibly desirable). If pre-cool *already happened* and the flag is lost, we get a double pre-cool. Verify: does `flush_daily_outcome` (`hvac_predict.py:170`) persist the flag? Fix: drive flag from a clock — `if hour >= PEAK_HOUR_START: flag = True` — making it a pure function of current time + completion state, not a transition event. |
| 13 | HVAC end-pre-cool at peak start | `hvac_predict.py:386-391` + `:536-541` | `hour >= PEAK_HOUR_START` checked each cycle | **OK** | Pure clock check; reboot at hour 17 correctly observes peak has started and clears the flag. |
| 14 | HVAC solar-banking window | `hvac_predict.py:441-468` (`_should_solar_bank`) | Periodic + condition check | Verify | If banking decisions snapshot baselines, ensure baseline restoration on reboot mid-banking works (sibling of `_resolve_baseline_range` at `:621-639`). |
| 15 | HVAC cover solar-hour close window | `hvac_covers.py:340-369` (`solar_start_hour ≤ hour < solar_end_hour`) | Pure hour check each HVAC cycle + hysteresis | **OK (verify hysteresis state restore)** | The `_hvac_closed` set is in-memory. Reboot mid-window with covers already closed: does the close-action re-fire (idempotent? — `set_cover_position` would be a no-op if already at target), or do we leave covers open at the cover-open temp threshold? Verify: on first cycle after boot, code path observes current cover position + outdoor temp + window membership → re-decides. If the existing code already converges, mark OK; if it relies on the in-memory set to gate the action, document and propose: re-seed `_hvac_closed` by reading current cover positions at startup. |
| 16 | HVAC pre-cool lead-time start (`PRECOOL_LEAD_HOURS`) | `hvac_predict.py:42` + caller | Periodic, recomputed each cycle | **OK** (verify) | If the start-time is a derived "now ≥ peak_hour - lead", a reboot inside the lead window re-triggers correctly. Verify no transition-only listener gates it. |
| 17 | HVAC dynamic preset dwell timer | (HC dwell-timer surface — read `hvac.py` / `hvac_preset.py`) | Timer-based | Verify | Bug Class #32 has prior art (v4.7.25 retrofit). Dwell-Number persistence was added; verify reboot mid-dwell does the right thing (dwell remaining time / restart-from-zero semantics). |
| 18 | Day-boundary mid_peak hold gate (v4.7.29) | `energy_battery.py` summer mid_peak branch + `peak_ahead_before_offpeak` helper | Per-cycle re-eval | **OK** (just shipped) | Reference v4.7.29 as the canonical fix shape — listed here to confirm the inventory's coverage of mid_peak-boundary surfaces. |
| 19 | HVAC max_runtime (uses `energy_tou.get_next_transition`) | `energy.py:3105-3110` | Per-cycle read | Sibling of #11; **GAP via dependency on a buggy primitive** | Document; defer fix to the v4.7.29 hygiene bucket. |
| 20 | EC `_decision_timer_unsub` and HC `_decision_timer_unsub` setup | `energy.py:697-700`, `hvac.py:619-623` | Periodic 5-min `async_track_time_interval` | **OK** (validated by v5.3.7 always-register) | The timer fires unconditionally on the configured interval; the first cycle after boot is the pickup. Foundational guarantee that all the OK verdicts above depend on. |

**Process for filling the table during build.** Each row gets:
1. Exact `file:line` re-verified against current `develop` HEAD.
2. The trigger mechanism named precisely (`async_track_time_interval` / `async_track_time_change` / signal listener / event listener / property read).
3. Verdict OK / GAP / DEFERRED. OK requires explicit evidence (cite the periodic re-eval line); GAP requires the proposed fix shape; DEFERRED requires a citation to where it tracks (e.g. v4.7.29 hygiene bucket).
4. For each GAP that this cycle WILL fix (subset to be selected at build time), a one-paragraph design that matches the v5.3.7 always-register philosophy.

### Acceptance criteria

- **Verify (inventory completeness):** The table covers EVERY `async_track_time_change`,
  `async_track_point_in_time`, and TOU/time-of-day branch in `energy*.py` and `hvac*.py`.
  Build phase greps the codebase for `async_track_time_change`,
  `async_track_point_in_time`, `tou_period ==`, `hour ==`, `hour >=`, `at_time`,
  `_today` flag patterns; every match has a row.
- **Verify (GAP fixes):** Each GAP this cycle fixes has (a) a unit test that simulates
  reboot mid-window (initialize coordinator with the persisted state that would exist,
  run one decision cycle, assert the correct action), (b) the fix uses the
  always-register / idempotent-re-eval pattern unless explicitly justified otherwise.
- **Test:** Per-GAP `test_<surface>_reboot_pickup` with mutation authority (revert the
  fix → test fails).
- **Live:** Simulated reboot mid-charge-window (operator-coordinated: restart HA between
  08:30 and 13:00 on a good solar day with the attainability branch armed); within ONE
  decision cycle (≤5 min) post-boot, attainability resumes (or arbitrage CHARGE
  resumes, depending on day class). Validated entries in the README: `arbitrage_phase`
  reads from before-reboot and after-reboot, log scan for the attainability reason
  string in the first post-boot cycle.

---

## D3 — Tests + ledger conventions

- New tests live under `quality/tests/` per CLAUDE.md.
- Test fixtures drive REAL `energy_const.py` schedule + REAL `BatteryStrategy.determine_mode` — no hand-mutated internal state on the production object (Tier 2-DB Review C invariant).
- Mutation-authority bar: ≥6 tests must fail when a key production-side invariant is inverted (the attainability predicate, the inventory GAP fixes, the precedence-vs-arbitrage check).
- Review ledger at `docs/reviews/code-review/<deploy-version>_ec_hc_reboot_decision_pickup.md` per the standard Tier 2-DB shape: A/B/C findings, validator, fix-up, plus the rendered inventory table (D2 IS the durable artefact).

---

## Plan Completion Tracking (to be filled at end of cycle per CLAUDE.md)

- [ ] D1 attainability branch + new phase token + tests
- [ ] D2 inventory table — every row filled with file:line + verdict + evidence
- [ ] D2 GAP fixes — subset selected at build time (NOT all 20+ rows; prioritize GAP candidates #1, #7-8 if not already shipped, #12, #14, #15, #17)
- [ ] Items explicitly deferred to v4.7.29 hygiene bucket (rows #11, #19) documented with pointer
- [ ] README post-deploy validation table (live attainability fire + simulated reboot pickup)

---

## Open Questions (for operator before build)

1. **Attainability phase token name.** `attain` vs `peak_buffer_catchup` vs reuse
   `charge` (the latter blurs the sensor narrative). Recommendation: `attain`.
2. **Late-start floor.** Should there be a *minimum* SOC delta below which attainability
   declines to engage (e.g. "if projection says we'd only reach 18% by boundary, don't
   bother charging from grid")? Operator instinct from incident note: NO floor —
   "reaching 50% beats holding 10%". Confirm.
3. **Inventory GAP fix scope.** The table will surface more GAP candidates than this
   cycle should reasonably fix in one Tier 2-DB pass. Operator picks the subset at
   end-of-planning review; default recommendation listed in Plan Completion Tracking.
4. **Day-class field in `target_day_class` after attainability fires.** Attainability
   does NOT change `target_day_class` (still reads "good"). Confirm the sensor narrative
   is acceptable: `arbitrage_phase=attain` + `target_day_class=good` + `reason="Peak-
   buffer attainability — projected SOC ..."`.
5. **EVSE-coordination follow-up cycle.** v1 is observe-only. Should a follow-up cycle
   be filed now (backlog memo) for "attainability briefly throttles EV ensure-on when
   the projection is severely failing"? Recommendation: file a backlog memo, do not
   build.

## Addendum — 2026-06-12 live manual-arbitrage test (operator + assistant)

Measured constants from the manual buffer-build (SOC 10%→45%, off-peak):
- Enphase reserve-bump → solar-surplus charging onset: **~22 min** (cloud write → Encharge execution)
- charge_from_grid enable → grid-rate unlock: **~35 min** (app showed "enabling…" pending state throughout)
- Full-rate charge with 8 Encharges: **~16 kW** (battery intake; grid contributed ~8.4 kW on top of solar)
- EC enforcement reverts manual charge_from_grid flips within ~30 s (one decision tick) — manual override CANNOT coexist with EC running.
- **Toggling `switch.ura_energy_coordinator_enabled` to escape enforcement is a watchdog hazard** — the 14:03 CDT re-enable stalled the event loop and the supervisor restarted core. The attainability decision MUST live inside EC's decision loop; there is no safe external override path.

Implications for D1 acceptance criteria:
- Charge onset lags the decision by 20-40 min — the attainability branch must fire EARLY in its window (first qualifying tick), not wait for certainty.
- Projection math should treat commanded-but-not-yet-flowing as in-flight (don't re-command every tick during the onset lag; the `attain` phase token persisting across ticks covers this).
- Operator-ratified principle (2026-06-12): "no solar reaching the battery → need for arbitrage" — forecast gate stays for the planned path; attainability catches realized divergence regardless of cause (clouds or EV load).
