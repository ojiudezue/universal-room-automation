# PLANNING — EC daylight-bounded rung horizon + poor-night WAIT floor

**Cards:** EC-RUNG1-WAIT-EV-PINGPONG-1 (fix 1), plus a WAIT-floor card to mint at build dispatch after the adjacency sweep
(SPEC_ec_behaviour_contract Q2 / D7, operator ruling (a) on 2026-10-03).
**Root cause:** `docs/planning/AUDIT_ec_drain_floor_and_pingpong_2026_10_03.md`.
**Tier: 3.** Both fixes change reserve emission inside the off-peak arbitrage state machine, which is the shared primitive
behind cost and EV behaviour. The failure mode is one missed site (Bug Class #53), and this area has a history of
multiple fix-up rounds (v5.3.8 attain, v5.17.x). The operator approved the build. The Tier-3 rules still apply: 2 plan
reviews, 4 framing-disjoint build reviews (A/B/C/D), orchestrator re-verification, and an operator checkpoint before deploy.
**Status:** plan only. No code edited.

---

## 0. Institutional context verified

### 0.1 Prior-art scan: EC day/night machinery (code)

| Machinery | Location | First seen (evidence) | Relation to the rung horizon |
|---|---|---|---|
| `_daylight_bounds(anchor)`: `sun.sun` next_rising/next_setting projected to anchor's local date, with a conservative fallback envelope | `energy_battery.py:3887-3958`; fallback hours `energy_const.py:1677-1682` (`DAYLIGHT_FALLBACK_SUNRISE_HOUR/SUNSET_HOUR`) | Cited as existing at `energy_battery.py:1700-1740` in `docs/reviews/code-review/v5.5.0_inclement_reviewA_detection_fusion.md:80` (v5.5.0, June 2026). The P3-HIGH-2 UTC→local fix inside it dates from the M4 attain cycle. | **The primitive the rung site calls.** It returns sunrise, and the rung site throws it away. |
| `_expected_solar_surplus_pct(now, mins)`: daylight-overlap slicing. Today branch `window = [max(now, sunrise), min(boundary, sunset)]`; tomorrow branch `[sunrise_tom, min(boundary, sunset_tom)]` | `energy_battery.py:3798-3885` (overlap at `:3843-3845`, `:3876-3878`) | M4 (pre-v5.5.0) | Already correct at both ends. This is the overlap primitive the operator asked us to reuse. |
| `_solar_replenishing_pct` wrapper (EVSE solar gate) | `energy_battery.py:~3738-3754` | evse-offpeak-fill-release | Consumer of the overlap primitive. Correct ("~0 at night"). |
| Time-anchored `is_daylight = sunrise <= now < sunset` | `energy.py:6289-6296`, consumed by `energy_pool.py:2650`, `:4203` | fill-priority-daylight-restoration (`PLANNING_fill_priority_daylight_restoration.md`, README_v5.28.0) | **The house's existing day/night predicate.** Fix 1 reuses this exact predicate shape. |
| Inclement `_minutes_to_sunset`, `_minutes_to_today_sunset`, tomorrow-sunrise legs | `inclement.py:446-480` | v5.5.0 | Same primitive. Handles the post-dusk roll explicitly. |
| `EnergyProjector.project_soc_at_boundary(bound_to_solar_horizon=True, sunset_dt=…)` | `energy_projector.py:107-208` (bound at `:185-192`) | R7 unification (`docs/reviews/code-review/r7_projection_unification_tier3.md`); this is a byte-identical lift of v5.17.4 | Carries the sunset-only bound into the singleton primitive. |
| v5.17.4 "bound rung projection to solar-capable hours" | `energy_battery.py:2981-3003` | commit b35189448, 2026-07-15 (audit §3; `README_v5.17.4.md`; `v5_17_4_rung_projection_solar_bound.md`) | **The defect.** `_sr_today, sunset_today = self._daylight_bounds(now)` at `:2993` discards `_sr_today`. |
| `energy_forecast._get_sunrise` (separate `sun.sun` parse) | `energy_forecast.py:211-230` | E5 predictor | Duplicate daylight parse. Out of scope (KEEP + DOCUMENT, no change). |

**Prior-art verdict: BYPASSES, not predates.** The daylight primitive (`_daylight_bounds`) and the two-sided overlap
logic (`_expected_solar_surplus_pct`) both existed at least a month before v5.17.4 (v5.5.0 or earlier vs 2026-07-15).
v5.17.4 calls the primitive, unpacks sunrise into `_sr_today`, and never uses it. It reimplemented a one-sided
`sunset − now` bound instead of reusing the overlap that already sat 800 lines below. R7 then copied that one-sided
shape into `EnergyProjector`. Before midnight the bound works by accident because today's sunset has passed. After
midnight it covers the whole night.
*Verified by plan review #1 (`git log -S … --reverse`):* `_daylight_bounds` first appears in 696824a59 (2026-06-12,
attainability tri-state HOLD; the local-time fix in 66050be23 the same day). `solar_mins_remaining` first appears in
b3870b83e (2026-06-15, inclement). The rung use is b35189448 (2026-07-15 01:41 CDT, v5.17.4), then ec60f1e25
(2026-07-16, R7). So the primitive predates the defect by 33 days. Verdict BYPASSES stands. B0.1 is done.

### 0.2 REUSE-or-BUILD per piece

| Piece | Verdict |
|---|---|
| Sunrise/sunset source | **REUSED** `_daylight_bounds` `energy_battery.py:3887` |
| Day/night predicate | **REUSED** shape `sunrise <= now < sunset` from `energy.py:6290-6294` |
| Overlap window end `min(boundary, sunset)` | **REUSED** from `energy_battery.py:3844`. Fix 1 also adds the start gate (see D1 for why the start must be `now` *and* `now >= sunrise`, not `max(now, sunrise)`). |
| Projector bound | **EXTEND** `EnergyProjector.project_soc_at_boundary` with optional `sunrise_dt` (default `None` = byte-identical) |
| WAIT floor value | **REUSED** `_drain_target_for(now)` `energy_battery.py:1926` → `_get_offpeak_drain_target` → `_effective_drain_targets` (`:1881`; ladder clamp from commit eca576f22, 2026-10-02 "EC SOC ladder split" — the v5.103.35 label is unverified by review #1; multi-day max). No second lookup (Bug Class #53). |
| WAIT at/below-floor park semantics | **REUSED** drain-fallback hold leg `energy_battery.py:5756-5774` (`reserve = int(soc)`) |
| Inclement clamp | **REUSED** `_floor_reserve` `energy_battery.py:3418-3432` |
| Re-entry cooldown (SPEC INV-1) | **NOT BUILT.** See D3 (marginal-benefit pushback). |
| New knobs | **None.** See §5. The poor/very_poor drain sliders already work as the policy knob and the kill switch. |

### 0.3 Docs, plans and memory consulted
- `docs/planning/AUDIT_ec_drain_floor_and_pingpong_2026_10_03.md`: full read (root cause, per-night table, why-now).
- `docs/planning/SPEC_ec_behaviour_contract.md`: rows A3/A4/A5, INV-1/2/7/8, Q1/Q2.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md`: §2.1-2.4 read. §2.2 promises that poor days "protect reserve", so the code diverges from the manual.
- `PLANNING_fill_priority_daylight_restoration.md` (is_daylight provenance); v5.17.4 README and review; R7 tier-3 review; v5.5.0 inclement reviews A and B.
- Memory: *attain solar aggression CLOSED, keep 0.5*. `SOLAR_CAPTURE_FACTOR` and `_expected_solar_surplus_pct` are **not touched**. *Charge-onset correct site*: ensure-on gating is untouched. *EV drain precedence shipped*: the DP stamp is deliberately not extended (D2).
- "Mistake #7" source (located by plan review #2): `docs/planning/PLANNING_v4.5.0_TRANSITION_NOTES.md:105-111` ("WAIT phase needs a drain target floor" — rejected on round-trip grounds) and `PLANNING_v4.5.0_battery_strategy_redesign.md:90,:135`. Fix 2 **deliberately reverses** that ruling by operator decision 2026-10-03; the replacement comment must cite both the old note and the new ruling.

### 0.4 Code read end-to-end for this plan
`energy_battery.py` `:1875-2030`, `:2960-3200` (`_classify_attain_rung`), `:3285-3534` (phase + decision), `:3738-3958`,
`:4505-4548`, `:5490-5775` (`_get_off_peak_decision`), `:6135-6163`, `:6490-6533`; `energy_projector.py:100-208`;
`energy.py:4552-4612`, `:5887-5948`, `:6286-6296`; `compose_release_floor` `energy_battery.py:320-359`.

---

## 1. Producer / Consumer

**Rung projection (fix 1).**
- **Producer:** `p = soc + (rate + extra) * rate_hours + solar_surplus`.
- `rate` is the observed K-tick net-charge rate. At night with the battery parked at reserve it is about 0.
- `extra` = +EV load for rung_1 entry, −assumed EV load for the counterfactual. 11.6 kW is about 29 %/h.
- `rate_hours` is the defect.
- **Consumers:** `_classify_attain_rung`, then `_gate_is_open` (`:3202`), then the gate outcome. `closed_rung_1` leads to the EV pause (`redirect`) and the off-peak fallback (`hold_reserve=int(soc)`). `rung_2` leads to arbitrage WAIT. These are trust decisions. `arb_projection_rung0/1` attrs are display only.

**Arithmetic finding that changes the operator's literal fix.** The operator proposed bounding to
`[max(now, sunrise), min(sunset, boundary)]`. It is not enough on its own. On 10-01 at 01:14 with sunrise ~07:20 and
shoulder boundary 17:00, that window is ~9.7 h. With `rate ≈ 0` (battery at reserve) and EV 29 %/h:
`8.9 + 29 × 9.7 + surplus ≫ 83` gives p1 = 100, so **rung_1 still fires and the flap survives.**
The flaw is not only the window length. A rate observed at night (with the EV added back) gets extrapolated into
daylight hours it says nothing about. Rung 0/1 are solar predicates (v5.17.4's own comment at `:2986-2988`). A night
rate holds no solar information. Before sunrise, the only valid solar evidence is the forecast surplus term, and that
term is already sliced correctly. **Fix:** the rate term is extrapolated only while now is in daylight:
`rate_mins = min(mins, sunset − now)` iff `sunrise <= now < sunset`, else 0.
This makes post-midnight behave exactly like pre-midnight, which v5.17.4 already gets right by accident. It also
satisfies SPEC INV-7 ("rung claiming solar redirect fires only while solar is producing").

**WAIT reserve (fix 2).**
- **Producer:** `_get_arbitrage_decision` WAIT leg `:3510-3534` = `_floor_reserve(reserve_soc, effective_reserve, hold_depth)`.
- **Consumers:**
  - `_result` sets `reserve_level`. Then the EVSE battery-hold overlay (`energy.py:5939-5948`, raises only), then the reserve write leg, then the `_last_reserve_level` ledger.
  - The ledger feeds `current_park_floor()` (`:2001`) and `compose_release_floor` (`:320`). That is the EV drain-release floor, a trust decision.
  - Display: `current_park_floor`, `park_floor_source`, `effective_release_floor`, `next_action_estimate` (`:6150-6155`), `threshold_position`.
  - The DP stamp `_offpeak_drain_branch_target` is **not** written on the arbitrage path (`:5732` only, reset `:5011`). DP declines on WAIT ticks today, and stays that way.

---

## 2. Falsifiable invariants (Reviewer D falsifies these)

- **INV-H1 (daylight horizon):** for any `now` with `now < sunrise(now)` or `now >= sunset(now)` (sunrise/sunset = `_daylight_bounds(now)` output, not astronomical truth), `_classify_attain_rung` gives `projection_rung1_entry == projection_rung0` (the EV term contributes exactly 0). So rung_1 can never be **entered from an unlatched state** before sunrise or after sunset, for any EV load, SOC, rate, mins, season or class. (A rung_1 latch taken in daylight may persist past sunset while `exit_band <= p0 < entry_band` — pre-existing, `:3044-3117`; out of scope, see review #2 F6.)
- **INV-H2 (byte-identity in daylight):** for `sunrise <= now < sunset`, every rung projection (rung0, rung1_entry, rung1_counterfactual) is byte-identical to pre-change.
- **INV-H3 (pre-midnight unchanged):** for `now >= sunset`, projections are byte-identical to pre-change. The old code already gave 0 there.
- **INV-W1 (poor-night floor):** on any off-peak tick whose emitted decision has `arbitrage_phase == "wait"`: `reserve_level >= max(min(drain_target_for(now), int(soc)), reserve_soc)`. When `soc > drain_target_for(now)` or soc is None: `reserve_level >= drain_target_for(now)`.
- **INV-W0 (raise-only; = review #2 F1, stated here so D falsifies it):** for every input, the new WAIT `reserve_level` is ≥ the legacy WAIT `reserve_level` (`_floor_reserve(reserve_soc, …)`). In particular, WAIT never emits below `reserve_soc` (10-01 sat at SOC 7-9 < reserve 10 for hours; legacy WAIT emitted 10 there). Corollary: with all drain sliders = reserve_soc the WAIT emission is byte-identical to legacy for every SOC, including SOC < reserve (the §4 kill-switch claim depends on this).
- **INV-W2 (no suppression of the legitimate action):** CHARGE and HOLD emissions (`:3459-3508`), completed-chunk HOLD (`:5547-5618`), attain branch, peak/mid-peak paths, and full_hold are byte-identical. WAIT never sets `charge_from_grid=True`.
- **INV-W3 (inclement):** under `partial_hold`, WAIT reserve `>= effective_reserve` (unchanged guarantee).
- **INV-W4 (DP unchanged):** `_offpeak_drain_branch_target` stays `None` on every arbitrage-path tick.

---

## D0: Measurement probe + replay fixtures (FIRST deliverable, go/no-go gate)

Read-only `ssh ha "python3 -" < probe.py` over the recorder (`sensor.ura_energy_coordinator_battery_strategy` attrs,
`sensor.garage_{a,b}_power_minute_average`, `sun.sun`) and URA DB `decision_log.dp_eval`, nights **09-28 → 10-03
06:00 CDT**.
- B0.1: ~~run `git log -S`~~ done by plan review #1 (see §0.1).
- B0.2: per tick, record `soc, target_day_class, arbitrage_gate, arbitrage_rung, arbitrage_phase, arb_projection_rung0/1, reserve_soc, current_commanded_reserve, ev_load_w, sun next_rising/next_setting`, plus whatever rate or surplus attrs exist. **Gate:** if the recorder lacks `rate` and `solar_surplus`, back-solve `surplus` from `p0` at a known `rate_hours` and record the assumption. Prove from data that `rate ≈ 0` at 01:14 on 10-01. If `rate` was materially non-zero, re-check the arithmetic finding in §1 before building.
- B0.3: hand-build the fixture `quality/tests/fixtures/ec_nights_2026_09_28_10_02.json` (≈5-min cadence). Commit it as the acceptance oracle.
- B0.4: investigate the live 10-03 `park_floor_source=planned_fallback` (the `_last_reserve_level` ledger was `None` while 10 was commanded). If the ledger is not set on WAIT ticks, fix 2's truth claim depends on it. Fold it into D2, or card it if it has a distinct cause.

### Acceptance Criteria
- **Verify:** fixture committed. Each row cites the recorder `last_updated`.
- **Verify:** the probe report is appended to this doc as §9, with the rate/surplus decomposition at 10-01 01:14.

## D1: Daylight-gated rung rate horizon (fix 1)

**Changes:**
1. `energy_projector.py:107-192`: add kwarg `sunrise_dt: datetime | None = None`. In the `bound_to_solar_horizon` branch, `solar_mins_remaining = 0` when `sunrise_dt is not None and now < sunrise_dt`. Otherwise keep the existing logic. Update the docstring expression. `None` keeps every non-rung caller byte-identical (`test_energy_projector_parity.py`).
2. `energy_battery.py:2992-3003`: keep `_sr_today` as `sunrise_today` (also `None` on except). Compute `solar_mins_remaining = (sunset_today − now)` iff `sunrise_today <= now < sunset_today`, else 0. This is the `energy.py:6290` predicate. `rate_hours` feeds the kill-switch fallback and the defensive rescues (`:3025`, `:3034`, `:3078`, `:3087`, `:3174`, `:3183`), so they stay consistent.
3. Pass `sunrise_dt=sunrise_today` at all three primitive calls: `:3011-3021` (rung0), `:3064-3074` (rung1 counterfactual), `:3160-3170` (rung1 entry). **Three sites. Each one gets its own mutation drill.**
4. Rewrite the v5.17.4 comment at `:2981-2991` to state the daylight gate and cite this plan.
5. **Not touched:** `_expected_solar_surplus_pct` (attain CLOSED memo), `ARB_LADDER_SOLAR_NEGLIGIBLE_PCT_PER_H` guard, latch logic.

**Before → after (rate_hours):**

| now | sunrise / sunset / boundary | Before | After |
|---|---|---|---|
| 22:00 | passed sunset | 0 | 0 |
| 01:14 (10-01) | 07:20 / 19:10 / 17:00 | 945 min (bounded by min(mins, sunset−now)) | **0** |
| 06:30 | 07:20 / … | ~630 | **0** |
| 09:00 | daylight | min(mins, sunset−now) | identical |
| sun.sun down | fallback 07:00/19:00 envelope | per envelope | gated per envelope |

### Acceptance Criteria
- **Test:** `test_rung1_never_latches_pre_sunrise_any_ev_load` (parametrised over EV 1-20 kW, SOC 5-80, rate −20..+20, mins 60-1000, summer and shoulder boundaries): asserts INV-H1.
- **Test:** `test_rung_projection_daylight_byte_identical` (INV-H2) and `test_rung_projection_post_sunset_unchanged` (INV-H3), with an oracle copied from the pre-change expression and written independently, not imported.
- **Test:** `test_projector_sunrise_none_byte_identical` (parity suite extension).
- **Test:** `test_replay_2026_10_01_no_rung1_flap`: drive `_classify_attain_rung` / `_gate_is_open` over the D0 fixture. 10-01 01:14-06:11 yields **zero** `rung_1` ticks and zero `closed_rung_1` gate outcomes. The other nights stay identical to recorded rungs on daylight ticks.
- **Mutation (Reviewer C):** neuter the `sunrise_dt` arg at each of the 3 sites one at a time. A named test must fail at each. Clear `__pycache__` with `PYTHONDONTWRITEBYTECODE=1`.
- **Live:** first poor post-midnight night with EV draw: `arbitrage_rung` stays `rung_2` and `arb_projection_rung1` ≈ `arb_projection_rung0` before sunrise. Zero `evse_paused_by_arbitrage` entries between sunset and sunrise. EV turn-on count ≤ 2/h (SPEC INV-1).
- **Discriminating observation:** under the fix, p1 == p0 pre-dawn. Under a different failure (e.g. latch residue), p1 ≠ p0 or rung_1 appears with p1 < 83.

## D2: Poor-night WAIT honours the forecast drain floor (fix 2)

**Single emission change, `_get_arbitrage_decision` WAIT leg `energy_battery.py:3510-3534`:**
```
drain_floor = self._drain_target_for(now)            # effective, ladder-clamped, multi-day max
base = drain_floor if (soc is None or soc > drain_floor) else max(self.reserve_soc, int(soc))  # plan review #2 F1
floored = self._floor_reserve(base, effective_reserve, hold_depth)
```
- `soc is None` is the blind path. Plan-review question: is the blind posture `drain_floor` (protective) or `reserve_soc`
  (legacy)? Recommended: `drain_floor`, because a higher floor is the safe direction. The rule for whether the
  `max(int(soc), reserve_soc)` term or the fallback's raw `int(soc)` applies must be settled in plan review. The
  fallback uses raw `int(soc)`. INV-W1 chooses ≥ reserve only when soc ≥ reserve, so use **raw `int(soc)`** to mirror
  `:5757` exactly unless the reviewer objects. **Superseded by plan review #2 F1: use `max(reserve_soc, int(soc))`; SOC None → `drain_floor` (operator ruling).**
- The reason string becomes `"Arbitrage WAIT — holding drain floor {base}% (target_day=…, lead_time=…)"`.
- Delete or replace the "Mistake #7" comment with the operator ruling (2026-10-03): the floor lets solar fill faster, or
  attain catch up faster.
- ~~`_drain_target_for` raising: wrap it in try/except~~ **Superseded by plan review #2 F3 (confirmed by #1): no
  try/except.** `_resolve_target_day(now)` already ran unguarded at `:5502` (`_classify_target_day`), so a raise never
  reaches WAIT; decisions observe the raise (`:1989`).

**All reserve emission sites on the off-peak path, before → after:**

| # | Site | Owner | Before | After |
|---|---|---|---|---|
| 1 | `:5563` → `_get_attainability_hold_decision` | completed-chunk attain-hold | pbt-floored | unchanged |
| 2 | `:5596-5618` | completed-chunk HOLD | `_floor_reserve(pbt)` | unchanged |
| 3 | `:3466-3485` | arbitrage HOLD | `_floor_reserve(pbt)` | unchanged |
| 4 | `:3489-3508` | arbitrage CHARGE | `_floor_reserve(pbt)`, CFG on | unchanged |
| 5 | `:3515-3534` | **arbitrage WAIT** (all **5** WAIT returns of `_get_arbitrage_phase`: `:3302` chunk-locked, `:3316` recheck-abort, `:3349` degraded-entry refusal, `:3401` guard-abort, `:3414` pre-window; plan review #2 corrected "6") | `_floor_reserve(reserve_soc)` | **`_floor_reserve(drain-floor-or-int(soc))`** |
| 6 | `_run_attain_branch` (`:5643-5656`) incl. reboot-recovery release `:4528-4548` | attain | pbt / reserve_soc release | unchanged (release path is a distinct owner; reviewers confirm it cannot fire on a WAIT-eligible tick) |
| 7 | `:5734-5754` | drain fallback, above | `drain_target` | unchanged |
| 8 | `:5756-5774` | drain fallback, hold | `int(soc)` / partial_hold | unchanged |
| 9 | EVSE battery-hold overlay `energy.py:5939-5948` | post-strategy overlay | max(existing, hold_soc) | unchanged; now composes on a higher base |
| 10 | Peak/mid-peak release-to-reserve (`:5381`, `:5388`, `:5457`, `:5477`, `:5492`; mid-peak attain call `:5417`) | high-rate | unchanged | unchanged (out of off-peak) |
| 11 | Blind de-escalation `:5157-5173` (writes `reserve_soc` + CFG off) | into-peak blind guard | fires only when `tou_period=="peak"` or `tou_transition_into=="peak"` AND CFG live/commanded on | unchanged. Can fire on the last off-peak tick before peak; WAIT ticks have CFG off, so it cannot overwrite a WAIT floor unless CFG was left on (then it is a CHARGE/attain residue, not WAIT). Plan review #1 addition. |
| 12 | `force_redispatch` `:6230-6297` (re-dispatches `_last_reserve_level_desired`) | write-verify recovery | verbatim re-emit of the strategy desire | unchanged; consumes the new WAIT value verbatim. Plan review #1 addition. |
| 13 | Inclement `full_hold` `:5292-5366` (`decision.reserve_floor`) | inclement | short-circuits before off-peak logic | unchanged (WAIT unreachable under full_hold). |

Reviewer D must re-enumerate this table from scratch, including pre-existing code. The list is a hypothesis.

**Truthful display:**
- `next_action_estimate` WAIT text (`:6153-6155`): `"waiting for charge window, holding {floor}% floor"`.
- `current_park_floor` / `effective_release_floor` become truthful automatically once the commanded value equals the floor. This depends on the B0.4 ledger finding.
- `current_offpeak_drain_target` (`:1962`) already equals the WAIT floor because both use `_drain_target_for`.
- No new attr unless B0.4 shows the ledger is unset on WAIT.

**Explicit non-change:** do NOT stamp `_offpeak_drain_branch_target` on WAIT. That would arm drain-precedence EV pausing on
poor nights, a behaviour change the operator did not ask for. The EV release floor still rises (via the ledger), which
is the intended "hold the floor".

### Acceptance Criteria
- **Test:** `test_wait_emits_drain_floor_when_soc_above` and `test_wait_parks_at_soc_when_below_floor` (INV-W1).
- **Test:** `test_wait_floor_uses_effective_ladder_clamp`: raw poor < reserve, raw poor < moderate (inverted). The emission equals the `_effective_drain_targets` value.
- **Test:** `test_wait_floor_multi_day_max` (D+2 worse class raises the floor).
- **Test:** `test_wait_partial_hold_floor_dominates` (extends `test_battery_inclement_arbitrage_floor.py`).
- **Test:** `test_charge_hold_byte_identical` and `test_completed_chunk_hold_unchanged` (INV-W2); `test_wait_does_not_stamp_dp_target` (INV-W4).
- **Test:** `test_replay_poor_nights_hold_floor`: D0 fixture 10-01 and 10-02. From 21:00 (SOC ≈28-30) the emitted reserve is ≥ min(30, soc) every tick until CHARGE, and never 10 while soc > 10.
- **Expected existing-test churn:** ~14 assertions in `test_energy_battery.py` plus `test_arbitrage_grid_import_guard_expose.py` (3) that pin WAIT = reserve_soc, **plus** `test_battery_inclement_arbitrage_floor.py:259` (allow_discharge WAIT == reserve_soc) and possibly `test_arbitrage_completed_chunk_hold_precedence.py`, `test_attainability_branch.py`, `test_v4_6_9_hvac_intent_attrs.py` (review #2 F4 — enumerate by running, not by this list). Each one is updated with a one-line justification. **Not** a blanket regex replace. Use a name-diff baseline vs `pre-review-v<ver>`.
- **Mutation (C):** revert site 5 to `self.reserve_soc`. The WAIT-floor tests must fail. Neuter the `_floor_reserve` wrap. The partial_hold test must fail.
- **Live:** next poor-target night. `arbitrage_phase=wait` with `current_commanded_reserve` == `current_offpeak_drain_target` (30) while SOC > 30, `hold_owner=arbitrage_wait`, `park_floor_source=commanded`. Morning CHARGE still fires at lead time and reaches pbt by boundary.
- **Discriminating observation:** under the fix, commanded=30 with SOC parked at about 30 overnight. Under an "overlay masked it" failure, commanded=30 but SOC still falls to 10, which means the hardware write is not landing. Check `command_trail`.

## D3: Re-entry cooldown (SPEC INV-1): NOT built, recommended

**Marginal-benefit decomposition:** D1 removes the only observed flap mechanism (night rung_1) at its root, and INV-H1
makes it unreachable. A daytime rung_1 ⇄ rung_2 oscillation would need a counterfactual hovering at the 83 band in real
daylight. That has never been observed (the audit found no daytime flap in 5 weeks). A cooldown adds a time-coupled
latch, which belongs to the state machine × time seam (the worst bug family per CLAUDE.md), and buys almost nothing.
**Instead:** keep the SPEC INV-1 *trip-wire* (anomaly: >2 strategy-caused EV toggles/h → NM). Card it separately as
detection, not control. **Revival trigger:** that trip-wire fires on a daylight tick.

---

## 4. Config-extreme matrix (tests parametrise; ✓ = covered by named test)

| Axis | Values |
|---|---|
| drain sliders | defaults {10,15,20,30,30}; inverted {poor 5 < reserve 10}; {poor 15 < moderate 20}; all = reserve (legacy-equivalent); poor = 100 |
| reserve_soc | 5, 10, 40, 60 (> poor raw) |
| peak_buffer_target | 25 (< poor floor 30), 80, 100 |
| arbitrage_enabled | on / off (off → fallback path, byte-identical) |
| season / TOU | summer (boundary 14:00/16:00), **shoulder (mid_peak 17-21)**, winter, **no high-rate transition** (mins None → rung early-return; WAIT unreachable, gate path) |
| target class | very_poor, poor (gate open); moderate (gate closed; regression only) ; multi-day D+2 poor with D+1 moderate |
| sun | sun.sun present; unavailable (fallback envelope); polar-ish (sunrise > boundary) |
| time | 22:00, 00:05, 01:14, 06:59 / sunrise−1min, sunrise, 12:00, sunset−1min, sunset |
| inclement | allow_discharge, partial_hold (effective_reserve 50), full_hold |
| SOC | None (blind), 5, 9, 30, 31, 79, 85 |

Key expected cells:
- **pbt 25 < floor 30:** WAIT only occurs while soc < pbt, so the floor resolves to `int(soc)`, then HOLD at pbt. No inversion bug. Asserted.
- **reserve 60 > poor 30:** the effective floor is 60, equal to legacy. Asserted.
- **All sliders = reserve:** byte-identical to today **only with the review-#2 F1 formula** (`max(reserve_soc, int(soc))` below the floor). With raw `int(soc)` it is NOT (soc 8 → 8 vs legacy 10). This is the operator's kill switch.

## 5. Knobs (Numbers Get Knobs)

No new numbers.
- The WAIT floor value is the existing poor/very_poor **drain-target Number entities** (rung 3, live-tunable). Setting them equal to `reserve_soc` restores pre-change WAIT exactly. That is the documented kill switch, so no new constant or flag is needed.
- Sunrise/sunset come from `sun.sun`, with the existing fallback constants `DAYLIGHT_FALLBACK_*` (rung 1).
- Config-first check: no existing setting fixes fix 1. Fix 2's policy *could* have been "amend the manual". The operator rejected that.

## 6. Manual / doc updates (same commit)
- `ENERGY_COORDINATOR_MANUAL.md` §2.2: add "On poor/very_poor target days with arbitrage on, the battery holds the poor drain floor overnight while waiting for the charge window. This lets solar fill faster, or attain catch up faster."
- §2.3: add a WAIT step 0. §5.6: drain sliders = reserve is the WAIT-floor kill switch. §4: `current_park_floor` is now truthful on WAIT. §6: version history row.
- Add a solar-horizon note: rung projections extrapolate the observed rate only in daylight.
- SPEC rows A3/A4/INV-7/Q1/Q2: mark resolved and cite the version.
- AUDIT §7: add a closure pointer.

## 7. Review plan
- **Plan reviews (2, Tier 3):** (1) completeness. Re-enumerate the reserve emission sites and the rung projection sites, and re-grep every `bound_to_solar_horizon` caller. (2) Build-prediction. Likely builder errors: using `max(now, sunrise)` (the operator's literal fix, which fails per §1); forgetting `rate_hours` for the fallbacks; a regex rewrite of WAIT tests; stamping DP.
- **Build reviews:** A local arithmetic; B state-machine/integration (CHARGE/HOLD/attain/DP/EVSE overlay/restart); C per-site source mutation (3 projector sites + WAIT site + `_floor_reserve`); D adversarial vs INV-H1/INV-W1 over the whole off-peak surface incl. pre-existing code.
- Orchestrator re-greps the sites and re-runs the mutations. Operator checkpoint before deploy. No restart while the house sleeps.

## 8. Non-goals
`SOLAR_CAPTURE_FACTOR` / `_expected_solar_surplus_pct`; the ensure-on charge-onset site; DP semantics; EV-ARBITRAGE-RELEASE
fill priority; degraded-data policy; Envoy stream; the duplicate `energy_forecast._get_sunrise` parser.

---

## Plan review #2 (build-prediction) — 2026-10-03

Framing: "what will the builder get wrong reading this?" Every claim below was checked against source on `develop`
(`f9379a1c5`). Small fixes were applied in-place above (marked "review #2"); the rest are binding build instructions.

### Findings

| # | Sev | Finding | Evidence | Resolution |
|---|---|---|---|---|
| F1 | HIGH | Raw `int(soc)` below the floor makes WAIT emit **below `reserve_soc`** when SOC < reserve (10-01 flap night sat at SOC 7-9: legacy WAIT emitted 10, new would emit 7-9), and it falsifies §4's "sliders = reserve is byte-identical" kill-switch claim. The `:5757` fallback mirror is the wrong precedent: that leg was never the WAIT leg. | `energy_battery.py:3515-3517` (legacy `_floor_reserve(self.reserve_soc, …)`), `:5757` | **Fixed in plan:** `base = drain_floor if (soc is None or soc > drain_floor) else max(reserve_soc, int(soc))`, then `_floor_reserve`. New invariant **INV-W0: new WAIT reserve ≥ legacy WAIT reserve on every input; equal when all drain sliders = reserve_soc.** That makes fix 2 a raise-only change and gives D a one-line oracle. Test `test_wait_floor_never_below_legacy` parametrised over the §4 matrix incl. SOC 5/9 with reserve 10. |
| F2 | HIGH | Hollow-oracle trap in test churn. The easy edit is `assert reserve == strat._drain_target_for(now)` / `strat.current_offpeak_drain_target()`: the expectation reads the implementation (Bug Class #62). Also, fixtures with no forecast resolve the target class to `unknown` → effective **40** (`DEFAULT_OFFPEAK_DRAIN_UNKNOWN`, `:1911`), and multi-day D+2 unknown raises the floor via `max()` (`:1949-1960`). A builder seeing "40" will "fix" the fixture or the code. | `:1881-1960` | Every updated/new assertion uses a **literal** derived by hand from the fixture's sliders (comment shows the arithmetic, e.g. `# poor=30, reserve=10 → eff 30`). Fixtures that hit WAIT must pin target class explicitly. A churned test that now expects 40 must say why (unknown class), not be re-stubbed silently. |
| F3 | MEDIUM | The proposed `try/except` around `_drain_target_for` is effectively dead (the same `_resolve_target_day(now)` already ran unguarded at `:5501` via `_classify_target_day`, and `classify_solar_day_n` is already guarded inside the helper) and it is a hollow-test magnet: a mis-mocked fixture raises → silently emits legacy `reserve_soc` → old assertions stay green for the wrong reason. | `:5501`, `:2761-2769`, `:1949-1958` | **Do not add the try/except.** Match the decision-path convention (`_safe_current_offpeak_drain_target` docstring `:1967-1972`: "decisions must observe the raise"). If the builder believes a raise is reachable, they must show the repro first. |
| F4 | MEDIUM | Churn list under-counts files (see in-plan edit). Blanket regex edits will be tempting. | `grep` of `ARBITRAGE_PHASE_WAIT`/`"Arbitrage WAIT"` in `quality/tests/` | Procedure: apply D2, run cycle + affected files, list every red by name, classify each as (a) intended policy change → per-assertion edit with literal + one-line `# v<ver> WAIT floor:` justification, or (b) surprise → STOP and report. Record the list in the build report. Name-diff vs `pre-review-v<ver>`. |
| F5 | MEDIUM | Projector/local predicate drift. The plan writes the daylight gate twice: in `EnergyProjector` (`now < sunrise_dt → 0`, plus the existing `sunset_dt > now`) and in the battery-local `rate_hours` (used only by the R7-off kill-switch branch and None-rescues). With `R7_USE_UNIFIED_PROJECTOR=True` in prod, a mutation of the local predicate will leave the suite GREEN (Reviewer C will flag it). Off-by-one risks: `now <= sunrise_dt` (wrong) vs `now < sunrise_dt`; `sunrise_today is None` compared with `<=` → `TypeError` (the except path at `:2994` must set **both** to `None`). | `energy_projector.py:185-192`; `energy_battery.py:2992-3003`, `:3025`, `:3034` | Boundary semantics fixed: in daylight iff `sunrise <= now < sunset`; `None` sunrise **with non-None sunset** → legacy sunset-only bound (byte-identical, matches projector default). Except path sets `sunrise_today = sunset_today = None` → 0 (unchanged). Required tests: exactly-at-sunrise (rate counts), sunrise−1s (0), exactly-at-sunset (0); one test with `R7_USE_UNIFIED_PROJECTOR` monkeypatched False asserting the gated local path, so the local predicate has an anchor. |
| F6 | MEDIUM | D1 does not kill the mechanism, it removes the **pre-dawn window**. At sunrise+1 min with the EV still drawing, `rate` is a K-tick trailing value dominated by night ticks (~0 or negative), and the entry adds +29 %/h × `min(mins, sunset−now)` (≈9.6 h shoulder) → p1 = 100 → rung_1 → the same pause/release loop (§3 of the audit: WAIT phase does not hold the EV). It did not show on 10-01 only because the session ended 06:11, before sunrise ~07:20. Winter sessions running past sunrise would reproduce it. Also a daylight-taken rung_1 latch persists past sunset while `exit_band ≤ p0 < entry_band` (`:3044-3117`). D3's "never observed in daylight" is true but under-sampled (the gate opened for the first time on 09-30). | `:3044-3117`, `_observed_net_charge_rate_per_hour` `:3718-3736` | Not a plan blocker (fix 1 is still correct and necessary). **Required:** (a) the D0 fixture includes 10-01 05:30-08:30 so the sunrise transition is replayed; (b) a test `test_rung1_post_sunrise_ev_draw_documented` pins the current post-sunrise behaviour (expected rung_1 is allowed; it is documentation of the residual, not an assertion of correctness); (c) the SPEC INV-1 trip-wire card (>2 strategy-caused EV toggles/h → NM) is minted **in this cycle's card set**, not "later". D3's revival trigger then has a detector. |
| F7 | LOW | DST quirk in `_daylight_bounds`: it projects `next_rising` HH:MM onto the anchor's date. After today's sunrise, `next_rising` is tomorrow's; on the Saturday before spring-forward it is ~1 h later in wall time, so `now < projected sunrise` for up to ~1 h of real daylight → rate term gated to 0 (conservative; rung_0/rung_1 suppressed). Fall-back is harmless. Pre-existing for `_expected_solar_surplus_pct` too. | `:3929-3936` | Accept. Tests define sunrise as `_daylight_bounds` output (INV-H1 wording updated). Do NOT "fix" `_daylight_bounds` in this cycle (shared by attain/inclement/pool). |
| F8 | LOW | `sun.sun` missing/unparseable → fallback envelope (`DAYLIGHT_FALLBACK_*`), never `None`; polar/inverted projection (sunset HH:MM ≤ sunrise HH:MM) makes the predicate never true → 0. Both conservative. | `:3920-3957` | Matrix cell "sun unavailable" asserts the envelope is used for both ends; add one inverted-bounds cell asserting rate term 0. |
| F9 | LOW | Chunk-locked WAIT (`:3302`/`:3316`/`:3401`) now also holds the drain floor, e.g. after a grid-import guard abort the battery parks at 30 instead of draining to 10 for the rest of the chunk. Consistent with the operator ruling, but it is a behaviour change on an abort path the plan doesn't name. `_next_action_estimate` has **two** WAIT strings (`:6151-6155`, chunk-completed and pre-window); the plan only rewrites one. | `:3298-3414`, `:6150-6155` | Name it in the README. Update both strings ("… holding {floor}% floor"). Test one abort-path WAIT emits the floor. |
| F10 | LOW | Operator decisions confirmed consistent with code: (i) no DP stamp on WAIT — `_offpeak_drain_branch_target` is only written at `:5732` (fallback), so not adding a line is sufficient; test INV-W4 must assert it is `None` after a WAIT tick that follows a fallback tick in the same test (entry-reset at `determine_mode` top), not just on a fresh object. (ii) SOC `None` → `drain_floor` matches the fallback's blind posture (`:5757` `else drain_target`). `soc is None` reaches WAIT via phase 1 being skipped (`:3292`). | as cited | Keep. |

### D0 replay fixture — concrete acceptance (binding)

Fixture `quality/tests/fixtures/ec_nights_2026_09_28_10_02.json`: one row per recorder strategy update (≈5-min cadence
is acceptable only if no rung transition is lost — keep **every** row where `arbitrage_rung` or `arbitrage_phase` changes),
fields per B0.2 plus `garage_a/b` minute-average power, `next_rising/next_setting` raw strings, recorder `last_updated`
(UTC ISO), and per-night `drain_targets`/`reserve_soc`/`peak_buffer_target` as configured that night. Nights covered: 09-28
21:00 → 10-03 08:30 CDT, **including each 05:30-08:30 sunrise window** (F6).

The replay drives the real `_classify_attain_rung` → `_gate_is_open` → `_get_off_peak_decision` with `now`, SOC, rate
history, EV load and sun state injected per row (rate: inject the K-tick SOC history so `_observed_net_charge_rate_per_hour`
recomputes it — do not stub the rate if the fixture has the SOC series; if stubbed, say so in the test docstring).

| Test | Pass condition (all must hold) |
|---|---|
| `test_replay_2026_10_01_no_rung1_flap` | (1) 10-01 00:00-07:19 (before that day's projected sunrise): **0** ticks with `arbitrage_rung == "rung_1"`, **0** `closed_rung_1` gate outcomes, 0 decisions with reason starting `"Off-peak hold — SOC"` (the rung_1 fallback leg). (2) On every pre-sunrise tick with `ev_load_w > 0`: `arb_projection_rung1 == arb_projection_rung0` (exact float). (3) Sanity anchor that the fixture really contains the bug: running the same replay with `sunrise_dt` forced to `None` (pre-fix behaviour) yields **≥ 10** rung_1 ticks in 01:14-03:20 (recorder shows 15 cycles). If this anchor fails, the fixture is wrong, not the fix. |
| `test_replay_daylight_ticks_unchanged` | On every fixture tick with `sunrise <= now < sunset`, all three projections equal the pre-change oracle (independently written expression, not imported) to 1e-9. |
| `test_replay_poor_nights_hold_floor` | 10-01 and 10-02 nights (target poor, gate open, rung_2, phase wait), from the first WAIT tick after 21:00 until the first CHARGE tick: (1) emitted `reserve_level == 30` on every tick with recorded SOC > 30; (2) `== max(10, int(soc))` on every tick with SOC ≤ 30; (3) **never 10 while SOC > 10** and never < 10 at all; (4) `charge_from_grid` is False on every WAIT tick; (5) the first CHARGE tick and its reserve (80) are identical to the recorder. 09-30 night (SOC 9 at 21:00): every WAIT tick emits **10** (F1 — not 9/8/7). |
| `test_replay_nonpoor_nights_byte_identical` | 09-28 (good → 15) and 09-29 (moderate → 20) nights: every emitted decision (mode, reserve, CFG, phase) equals the recorder's commanded values. Proves D1+D2 leave closed-gate nights untouched. |

Recorder SOC under the fix would differ (battery parks at 30 instead of draining), so the replay asserts **emitted
decisions per recorded input**, not a re-simulated SOC trajectory. State this in the test docstring so nobody "fixes" it
into a simulation.

### Mutation drills the builder must pre-run (Reviewer C will repeat)
`sunrise_dt` neutered at each of the 3 call sites (3 drills); projector `now < sunrise_dt` gate neutered; battery-local
predicate neutered with the R7-off test (F5); WAIT `base` → `self.reserve_soc`; `max(reserve_soc, …)` → raw `int(soc)`
(must fail `test_wait_floor_never_below_legacy` + the 09-30 replay row); `_floor_reserve` wrap removed (partial_hold test).
Each must turn a **named** test red.

### Verdict: **BUILD-READY** with F1-F6 as binding build instructions (F1 already folded into the D2 pseudocode and §4).
No plan restructuring is needed. F6(c) adds one card to the dispatch set.

---

## Plan review #1 (completeness) — 2026-10-03

Framing: independent re-enumeration of every surface the plan claims to cover. All greps re-run on `develop`
(`f9379a1c5`); the plan's lists were treated as hypotheses. Review #2 landed concurrently; overlapping findings are
cross-referenced, not duplicated.

### Re-enumeration results

| Surface | Plan claim | Re-grep result | Verdict |
|---|---|---|---|
| `bound_to_solar_horizon=True` callers | 3 rung sites | `energy_battery.py:3017`, `:3070`, `:3166`. Other `project_soc_at_boundary` callers `:4129` (attain) and `:4864` both pass `False` → `sunrise_dt` default `None` keeps them byte-identical. No caller outside `energy_battery.py`. | **Complete** |
| Inline rate-horizon arithmetic | 6 rescue/fallback lines | `:3025`, `:3034`, `:3078`, `:3087`, `:3174`, `:3183`, all on the shared local `rate_hours`. Note `test_energy_projector_grep_singleton.py:221` pins the `R7-SINGLETON-EXEMPT` marker count: the builder must not add new inline projection lines. | **Complete** |
| `_daylight_bounds` / `solar_mins_remaining` dates | asserted from docs, unverified | `git log -S`: 696824a59 (2026-06-12), b3870b83e (2026-06-15), b35189448 (2026-07-15), ec60f1e25 (2026-07-16). §0.1 updated. | **Verified: BYPASSES** |
| Off-peak reserve emission sites | 10 | `grep reserve_level=` + every `reserve_soc_number` writer: plan's 10, **plus** blind de-escalation `:5157-5173`, `force_redispatch` `:6230-6297`, inclement full_hold `:5292-5366`, mid-peak attain call `:5417`. Rows 11-13 were added to the table. None changes and none can overwrite a WAIT floor (see the row notes). | **Was incomplete, fixed** |
| WAIT returns of `_get_arbitrage_phase` | "6" | 5 (`:3302`, `:3316`, `:3349`, `:3401`, `:3414`). Already corrected by #2. The `ARBITRAGE_PHASE_NA` return at `:3289` would also fall into the WAIT leg's `else`, but it is unreachable there because `_gate_is_open` is per-tick cached (`_arb_rung_cache_tick`, `:2918-2921`) and returned True at `:5626`. | **Holds** |
| `_drain_target_for` consumers | emitter + display | `:1980` (accessor), `:5703` (fallback emitter), `:6115` (`_threshold_position`), `:6159` (`_next_action_estimate`); the new WAIT read makes 5. All read the same helper, so there is no second lookup (Bug Class #53 holds). | **Complete** |
| Ladder clamp seam | `_get_offpeak_drain_target` → `_effective_drain_targets` | `:1914` → `:1881` (cumulative max anchored at `reserve_soc`, cap 100). So `drain_floor >= reserve_soc` always, which is why the INV-W0 formula `max(reserve_soc, int(soc))` is the only path below reserve. | **Holds** |
| Inclement routing | `_floor_reserve` on WAIT | `full_hold` short-circuits at `:5293`, so WAIT is unreachable. `partial_hold` → `_floor_reserve` `:3430` raises only. INV-W3 holds by construction. | **Holds** |
| Release-floor / EV interplay | "EV release floor rises via the ledger" | `compose_release_floor` (`:320`) has ONE production caller, `energy.py:6196`, which feeds `determine_battery_drain_actions(reserve_soc=_release_floor)` at `energy.py:6238` and `:6402`. **Behaviour change the plan doesn't name:** on poor nights the EV drain-pause `battery_out_of_capacity` release now fires at the ~30 floor (+2) instead of ~10. That is consistent with "hold the floor" (the EV runs on grid, not battery), but it must be named in the README and get a test. **Pre-existing inconsistency the fix resolves:** with the ledger `None` (post-restart, deadband-skipped dispatch) `current_park_floor()` already returned 30 via `planned_fallback` (`:2025`) while the hardware held 10. | **Gap → R1-1** |
| Ledger stamping (B0.4) | open question | `_last_reserve_level` is stamped only by the dispatch tap (`energy.py:8185-8196`), the EVSE overlay (`energy.py:5067`, `:5156`), `force_redispatch` (`energy_battery.py:6291`) and boot restore (`energy.py:1866`, only when the persisted payload has `commanded`). `_result` skips the dispatch when `abs(current − target) < 2` (`energy_battery.py:~5867`). So after a restart, with hardware already at 10 and WAIT emitting 10, nothing stamps → `None` → `planned_fallback`. This is the likely B0.4 cause; B0.4 should confirm it, not re-investigate. After the fix, WAIT 30 vs hardware 10 dispatches and stamps. The `int(soc)` ratchet below the floor moves in 1 % steps under a 2 % deadband, so the ledger can lag by ≤ 1 pt. That is acceptable and should be documented. | **Explained, R1-2** |
| Display consumers outside the integration | "dashboards/PWA too" | `~/Code/ura-dashboard-pwa`: no consumer of `current_park_floor` / `effective_release_floor` / `current_offpeak_drain_target` / `arbitrage_phase` (planning doc only). Live Lovelace: `.storage/lovelace.ura_v6` and `lovelace.ura_v8` render "Night drain to {current_offpeak_drain_target}%" plus `arbitrage_phase`; `lovelace.ura_v7` renders `current_park_floor`, `effective_release_floor`, `arbitrage_phase`. These were all display-only, and they were **lying on poor nights** (showing 30 while commanding 10). After the fix they tell the truth. No dashboard edit is needed. | **Complete (display only)** |
| DP / drain-precedence | stamp untouched | `_offpeak_drain_branch_target` is written only at `:5732` and reset at `:5011`. The arbitrage path never reaches `:5732`. INV-W4 holds by construction (see #2 F10 for the test shape). | **Holds** |

### Invariant falsifiability check

- **INV-H1:** falsifiable and complete for *entry*. The proof sketch holds against the code: rung-0 is evaluated first (`:3119-3134`). With `rate_hours = 0` the projector gives `soc + 0 + surplus` for every `extra`, so p1 == p0 exactly, as long as `rate` is finite. A NaN rate would make the projections NaN, all comparisons False, and the result rung_2, so the invariant is still not falsified. The latched-carry case is correctly scoped out (#2 F6). The residual after sunrise (#2 F6) is outside INV-H1's premise by design; the post-sunrise test and trip-wire card cover it.
- **INV-H2 / H3:** falsifiable through the independent-oracle tests. One nuance: after today's sunrise passes, `_daylight_bounds` reports *tomorrow's* rising HH:MM (in autumn ~1 min later). So "daylight" begins up to ~1 min late on non-DST days, and up to ~1 h late on spring-forward eve (#2 F7). H2 is defined on `_daylight_bounds` output, so it stays consistent.
- **INV-W0 (= #2 F1) / W1:** falsifiable. W1 was rewritten so the bound is `max(min(floor, int(soc)), reserve_soc)`, which is consistent with W0. The old W1 text allowed a sub-reserve emission and contradicted the §4 kill-switch claim.
- **INV-W2 / W3 / W4:** falsifiable and hold by construction on current code (site table rows 1-4, 11-13).
- **Missing invariant (R1-1):** none states the EV release-floor consequence. Added below as a required test rather than a new INV, because it is a consumer of W1, not a separate guarantee.

### Findings

| # | Sev | Finding | Resolution |
|---|---|---|---|
| R1-1 | MEDIUM | The EV drain-release floor change is unnamed (above). It is a cross-coordinator behaviour change (battery → EVSE) on poor nights. | **Binding:** add `test_wait_floor_composes_into_release_floor`: after a WAIT tick that dispatched 30, `compose_release_floor(battery, "off_peak") == (30, True)`; on a WAIT tick with SOC 9 and reserve 10 it is `(10, True)`. Name it in the README "behaviour changes" list. Live check: on a poor night with EV draw, `effective_release_floor == 30`, and the EV is not paused by the drain rule while the battery is parked. |
| R1-2 | LOW | B0.4 has a code-level explanation already (deadband skip + ledger stamped only on dispatch). | B0.4 scope reduced to confirming it against the live `command_trail`. Do not build a WAIT-specific ledger stamp unless the confirm fails. |
| R1-3 | LOW | The emission table missed 3 pre-existing reserve writers and 1 non-off-peak attain call. | Added as rows 11-13 plus a row-10 expansion. None changes. Reviewer D still re-enumerates. |
| R1-4 | LOW | §0.2 attributed the ladder clamp to "v5.103.35" without evidence. | Re-cited to commit eca576f22 (2026-10-02). |
| R1-5 | LOW | Stale D2 text (raw `int(soc)` recommendation, try/except) contradicted #2 F1/F3 in the same doc. | Struck through in place, and the superseding ruling cited. |
| R1-6 | INFO | `_classify_attain_rung` reads `soc` from `self.battery_soc` (`:3249`), while the WAIT leg uses the `soc` parameter of `determine_mode`. Under LKG/degraded telemetry the two can differ, so the rung and the floor could see different SOCs on the same tick. This is pre-existing, and the floor only uses `soc` for the ≤-floor branch, which is raise-only via W0. | No change. Reviewer A should note it if it finds a divergent-SOC path. |

### Verdict: **BUILD-READY** (completeness), with R1-1 binding alongside review #2's F1-F6.
The surface enumeration is now complete: 3 projector sites, 6 rescue lines, 13 emission/writer rows, 5 `_drain_target_for`
consumers, 1 release-floor caller with 2 drain calls, and 3 Lovelace dashboards (display only). Invariants are falsifiable.

---

## 9. D0 probe report (builder, 2026-10-03)

**Source.** Read-only extract of the HA recorder (`ssh ha`, `home-assistant_v2.db` opened `mode=ro`), window
2026-09-28 21:00 → 2026-10-03 14:30 CDT: `sensor.ura_energy_coordinator_battery_strategy` attrs (13 160 rows),
`sensor.garage_{a,b}_power_minute_average`, Solcast remaining/today/tomorrow, `sensor.envoy_482543015950_battery_capacity`
(as-of joins). Fixture: `quality/tests/fixtures/ec_nights_2026_09_28_10_02.json` (1 417 rows; each row carries the
recorder `last_updated` as `t`; provenance block inside the file).

**Findings that shaped the fixture.**
- **`sun.sun` attributes are not recorded** (the recorder strips `next_rising` / `next_setting`; only the state is
  kept). The fixture's `sun_next_rising` / `sun_next_setting` are DERIVED with astral at the HA `core.config`
  location (30.314635, -98.015861, elevation 320 m, observer elevation as HA's sun helper uses). 10-01 sunrise
  07:23:45, sunset 19:19:05 CDT.
- **Decisions run every ~5 min; the strategy sensor republishes every ~30 s.** Rows were therefore selected by a
  change in a decision-only attribute (`arb_projection_rung0/1`, `reason`, `command_trail…live_desire`,
  `arbitrage_rung/phase`, hardware-noncompliance `discharge_w_observed/consecutive_ticks`), with gaps > 450 s filled
  at anchor + k·300 s. Every rung/phase transition row is kept. (A naive 5-min thinning put a "decision" at
  10-02 14:01 that never happened; production's 14:03 decision was a degraded-SOC (`lkg`) entry refusal.)
- **No `rate` / `solar_surplus` attrs exist** in the recorder. The replay recomputes the rate with the real
  `_observed_net_charge_rate_per_hour` from the injected SOC series and the surplus with the real
  `_expected_solar_surplus_pct` from the recorded Solcast + capacity (capacity LKG 40 kWh when the entity was
  unavailable, as production caches it). SOC tier (`soc_source`) and net/battery power are injected so the real
  degraded-entry refusal sees what production saw.
- **Fidelity of the D1-pre-fix replay against the recorder** (D1 reverted by discarding sunrise at the rung site;
  D2 stays active): rung agreement 664/673 gate-evaluated ticks. Desired reserve 936/1006: of the 70 differences,
  57 are the intended D2 WAIT floor, 6 are recorded rung_1 fallback-hold rows the replay classified rung_2/WAIT (part
  of the 9 rung disagreements: rate reconstruction from 0.1 %-rounded SOC), 7 are attain charging/hold or
  restart-recovery rows (attain latch history before the window is not replayed). None fall in the asserted sets.
  At 10-01 01:14:50 the pre-fix replay reproduces the recorder exactly: `p0 = 46.2`, `p1 = 100.0`, `rung_1`.

**B0.2 rate/surplus decomposition at 10-01 01:14:50** (SOC 8.9 %, EV 11 659 W = 29.1 %/h on 40 kWh, boundary
17:00 → mins 945, sunset 19:19): rate = **-0.24 %/h** (≈ 0, confirmed), surplus = **41.1 %** (today branch,
overlap 07:24-17:00). Pre-fix: horizon min(945, 1084) = 15.75 h → p0 = 8.9 - 3.8 + 41.1 = 46.2, p1 = clamp(8.9 +
(29.1 - 0.24)·15.75 + 41.1) = 100 → rung_1. Fixed: horizon 0 pre-sunrise → p0 = p1 = 50.0 → rung_2. The §1
arithmetic finding holds (a `[max(now, sunrise), …]` window alone would still give p1 = 100).

**Replay results** (`test_ec_daylight_horizon_poor_night_floor.py`):

| Check | Pre-fix replay | Fixed replay |
|---|---|---|
| rung_1 ticks 10-01 01:14-03:20 | 11 | **0** |
| rung_1 ticks 10-01 before sunrise | 13 | **0** |
| closed_rung_1 / "Off-peak hold — SOC" decisions before sunrise | present | **0** |
| p1 == p0 on pre-sunrise EV-drawing ticks | no (100 vs ~46) | **yes (exact)** |
| Daylight ticks: p0/p1/rung | — | identical to pre-fix on every tick; p0 within rounding of an independent oracle |
| 09-30 night WAIT (SOC 6.4-10) | 10 / rung_1 hold 7-8 | **10 on every tick** (never 7-9) |
| 10-01 / 10-02 night WAIT | 10 on every tick | **max(10, int(SOC)) down from 30 / 28**, 50 under partial_hold, never grid charge |
| First CHARGE tick | 10-01 14:01 (80), 10-02 15:53 (80) | identical |
| 09-28 (good → 15) / 09-29 (moderate → 20) drain-fallback decisions | — | identical to recorder `live_desire` |

**B0.4 confirmed (R1-2).** 10-03 00:37 CDT restart → `park_floor_source = planned_fallback`, ledger `None`, while
WAIT emitted 10 and the hardware already held 10 (2 % deadband → no dispatch → no stamp). Mechanism exactly as
review #1 explained; no WAIT-specific ledger stamp built. Residual (pre-existing, unchanged): after a restart with
SOC already ≤ floor and hardware == WAIT emission, the ledger stays `None` and `current_park_floor` reports the 30
planned fallback until the first dispatch.
