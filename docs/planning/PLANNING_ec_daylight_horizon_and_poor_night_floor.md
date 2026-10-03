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
*Caveat:* I could not run `git log -S` or `git blame` in this session (no shell). The dates come from the review and
README record cited above and from the audit's commit hash. Builder step B0.1 confirms them with
`git log -S "_daylight_bounds" --reverse` and `git log -S "solar_mins_remaining" --reverse`.

### 0.2 REUSE-or-BUILD per piece

| Piece | Verdict |
|---|---|
| Sunrise/sunset source | **REUSED** `_daylight_bounds` `energy_battery.py:3887` |
| Day/night predicate | **REUSED** shape `sunrise <= now < sunset` from `energy.py:6290-6294` |
| Overlap window end `min(boundary, sunset)` | **REUSED** from `energy_battery.py:3844`. Fix 1 also adds the start gate (see D1 for why the start must be `now` *and* `now >= sunrise`, not `max(now, sunrise)`). |
| Projector bound | **EXTEND** `EnergyProjector.project_soc_at_boundary` with optional `sunrise_dt` (default `None` = byte-identical) |
| WAIT floor value | **REUSED** `_drain_target_for(now)` `energy_battery.py:1926` → `_get_offpeak_drain_target` → `_effective_drain_targets` (`:1881`; v5.103.35 ladder clamp, multi-day max). No second lookup (Bug Class #53). |
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
- "Mistake #7" source plan: not located in `docs/` (only the inline comment at `:3511`). Plan reviewer: if you know where it lives, cite it.

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

- **INV-H1 (daylight horizon):** for any `now` with `now < sunrise(now)` or `now >= sunset(now)`, `_classify_attain_rung` gives `projection_rung1_entry == projection_rung0` (the EV term contributes exactly 0). So rung_1 can **never latch** before sunrise or after sunset, for any EV load, SOC, rate, mins, season or class.
- **INV-H2 (byte-identity in daylight):** for `sunrise <= now < sunset`, every rung projection (rung0, rung1_entry, rung1_counterfactual) is byte-identical to pre-change.
- **INV-H3 (pre-midnight unchanged):** for `now >= sunset`, projections are byte-identical to pre-change. The old code already gave 0 there.
- **INV-W1 (poor-night floor):** on any off-peak tick whose emitted decision has `arbitrage_phase == "wait"`: `reserve_level >= min(drain_target_for(now), int(soc))` and `reserve_level >= reserve_soc` when soc ≥ reserve_soc. When `soc > drain_target_for(now)`: `reserve_level >= drain_target_for(now)`.
- **INV-W2 (no suppression of the legitimate action):** CHARGE and HOLD emissions (`:3459-3508`), completed-chunk HOLD (`:5547-5618`), attain branch, peak/mid-peak paths, and full_hold are byte-identical. WAIT never sets `charge_from_grid=True`.
- **INV-W3 (inclement):** under `partial_hold`, WAIT reserve `>= effective_reserve` (unchanged guarantee).
- **INV-W4 (DP unchanged):** `_offpeak_drain_branch_target` stays `None` on every arbitrage-path tick.

---

## D0: Measurement probe + replay fixtures (FIRST deliverable, go/no-go gate)

Read-only `ssh ha "python3 -" < probe.py` over the recorder (`sensor.ura_energy_coordinator_battery_strategy` attrs,
`sensor.garage_{a,b}_power_minute_average`, `sun.sun`) and URA DB `decision_log.dp_eval`, nights **09-28 → 10-03
06:00 CDT**.
- B0.1: run `git log -S` on `_daylight_bounds` / `solar_mins_remaining` and confirm the dates in §0.1.
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
base = drain_floor if (soc is None or soc > drain_floor) else int(soc)  # (corrected per text below) mirrors :5734/:5757
floored = self._floor_reserve(base, effective_reserve, hold_depth)
```
- `soc is None` is the blind path. Plan-review question: is the blind posture `drain_floor` (protective) or `reserve_soc`
  (legacy)? Recommended: `drain_floor`, because a higher floor is the safe direction. The rule for whether the
  `max(int(soc), reserve_soc)` term or the fallback's raw `int(soc)` applies must be settled in plan review. The
  fallback uses raw `int(soc)`. INV-W1 chooses ≥ reserve only when soc ≥ reserve, so use **raw `int(soc)`** to mirror
  `:5757` exactly unless the reviewer objects.
- The reason string becomes `"Arbitrage WAIT — holding drain floor {base}% (target_day=…, lead_time=…)"`.
- Delete or replace the "Mistake #7" comment with the operator ruling (2026-10-03): the floor lets solar fill faster, or
  attain catch up faster.
- `_drain_target_for` raising: wrap it in try/except falling back to `reserve_soc` (legacy behaviour) and WARN once.
  Decision paths elsewhere let it raise. Here, a raise must not stop WAIT from emitting. Plan review: confirm this.

**All reserve emission sites on the off-peak path, before → after:**

| # | Site | Owner | Before | After |
|---|---|---|---|---|
| 1 | `:5563` → `_get_attainability_hold_decision` | completed-chunk attain-hold | pbt-floored | unchanged |
| 2 | `:5596-5618` | completed-chunk HOLD | `_floor_reserve(pbt)` | unchanged |
| 3 | `:3466-3485` | arbitrage HOLD | `_floor_reserve(pbt)` | unchanged |
| 4 | `:3489-3508` | arbitrage CHARGE | `_floor_reserve(pbt)`, CFG on | unchanged |
| 5 | `:3515-3534` | **arbitrage WAIT** (all 6 WAIT returns of `_get_arbitrage_phase`: `:3302`, `:3316`, `:3349`, `:3401`, `:3414`) | `_floor_reserve(reserve_soc)` | **`_floor_reserve(drain-floor-or-int(soc))`** |
| 6 | `_run_attain_branch` (`:5643-5656`) incl. reboot-recovery release `:4528-4548` | attain | pbt / reserve_soc release | unchanged (release path is a distinct owner; reviewers confirm it cannot fire on a WAIT-eligible tick) |
| 7 | `:5734-5754` | drain fallback, above | `drain_target` | unchanged |
| 8 | `:5756-5774` | drain fallback, hold | `int(soc)` / partial_hold | unchanged |
| 9 | EVSE battery-hold overlay `energy.py:5939-5948` | post-strategy overlay | max(existing, hold_soc) | unchanged; now composes on a higher base |
| 10 | Peak/mid-peak release-to-reserve (`:5492` region and siblings) | high-rate | unchanged | unchanged (out of off-peak) |

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
- **Expected existing-test churn:** ~14 assertions in `test_energy_battery.py` plus `test_arbitrage_grid_import_guard_expose.py` (3) that pin WAIT = reserve_soc. Each one is updated with a one-line justification. **Not** a blanket regex replace. Use a name-diff baseline vs `pre-review-v<ver>`.
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
- **All sliders = reserve:** byte-identical to today. This is the operator's kill switch.

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
