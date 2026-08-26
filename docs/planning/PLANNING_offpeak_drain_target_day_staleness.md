# PLANNING — Off-peak drain target day-staleness (cross-midnight anchor)

- Card: `DRAIN-TARGET-DAY-STALENESS-1`
- Thread: `energy` / BatteryStrategy shared primitive
- Tier: **Tier 3** (reserve-affecting, shared primitive consumed by both an accessor and an emitter, one-missed-site shape Bug Class #53, cost-AND-safety impacting).
- Status: PLAN ONLY — awaiting explicit build-go after Tier-3 plan review. **2026-08-25: adopted additive D6/D7 (DP + per-EVSE telemetry) to ride with the cosmetic H-1 fix; those additions need a focused additive plan-review before build.** This revision (2026-08-24, midnight re-review pass) folds in the Tier-3 plan-review findings AND the orchestrator right-sizing of the blast-radius framing, PLUS the four surgical edits + three LOWs from the midnight re-review (H-1 shared-helper mandate, M-1 manual-edit sub-item, M-2 offset==1 scope, M-3 INV-DTDS-3 scoping).
- Sequencing: ships BEFORE `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` (DP fix). DP reads `current_offpeak_drain_target()` unchanged and mirrors the emitter; this fix corrects emitter + accessor + narration helpers together, so DP inherits the corrected value on the next tick.
- Probe (already run — see card `PROBE_RESULT_2026_08_24_BITES`): 536 days of long-term Solcast statistics; `class(D) != class(D+1)` on 37.4% of days; mean 9.9 / median 10 SOC-pt drain-target delta; worst 20; both directions. Measure-before-build satisfied.

---

## Drift re-verification (2026-08-25, orchestrator, by hand — post-DP 5.90.1 + solar-follow 5.91.0)

Plans drift with code; both shipped into `energy_battery.py`/`energy.py` after this plan was written (08-24). Re-verified against current develop:

- **Line numbers drifted ~+27** in the drain branch and helpers. CURRENT: drain-class derivation `5316-5330`; A-CRIT-1 partial_hold clamp `5340-5341`; `current_offpeak_drain_target` `1735`; `_get_offpeak_drain_target` `1731`; `classify_tomorrow_solar` `1699`; `classify_solar_day_n` `1811`; `_threshold_position` `5696`; `_next_action_estimate` `5727`. D3/H-1 must use THESE, not the stale 08-24 citations.
- **LOAD-BEARING NEW SITE the plan was blind to — the DP value-stamp at `5349`:** `self._offpeak_drain_branch_target = int(drain_target)` sits INSIDE D3's branch, AFTER the derivation (5330) and the partial_hold clamp (5340). It is how 5.90.1's DP fix consumes THIS tick's composed target. **D3 must replace ONLY the derivation (5316-5330) with `drain_target = self._drain_target_for(now)` and PRESERVE both the partial_hold clamp (5340) and the value-stamp (5349) below it.** After D3, the stamp carries the *peak-anchored* composed target to DP — the fix flowing downstream — so this is desired, but it means D3 is a Bug-Class-#53 site with a NON-obvious consumer (the DP tick) that the plan's original site enumeration missed.
- **Cross-cycle behavior change (must be stated):** because the stamp feeds DP, D3 silently changes DP's drain FLOOR from calendar-tomorrow to peak-anchored. The DP card (EVSE-DRAIN-PRECEDENCE-KNOB-80-1) is `shipped_organic` with an outstanding 2-tick-no-flap watch; this cycle re-touches the value DP drains toward, so DP's organic re-validation is implicated — the post-deploy live check MUST re-confirm the DP floor (via `command_trail`/`cloud_oracle`) equals the peak-anchored `_drain_target_for(now)`, not just that the accessor/narration agree.
- Arbitrage-OFF gating confirmed unchanged (comment at 5320: "when arbitrage is ON we never reach this branch"): D3 only affects the arbitrage-OFF drain path — matches the plan's `arbitrage_phase ∈ {n/a, WAIT}` acceptance framing.

**Design verdict: still sound; the fix needs the stamp-preservation sub-item + a DP-integration test added to D3 (below). Approved to build after the additive-D6/D7 plan-review, with these edits folded in.**

## Design-intent authority

`docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.2 is the governing authority: the daily solar class drives **the drain target** ("how low to allow battery to fall off-peak — if solar will refill tomorrow, drain deeper; if not, protect reserve") and §2.2 also spells out that **the reserve is a discharge FLOOR, not a charge ceiling** (operator-validated 2026-07-16). NOTE (M-1): §2.1 currently PARAPHRASES the drain target as set by "tomorrow's solar forecast" (`ENERGY_COORDINATOR_MANUAL.md:43-44`), which CONTRADICTS the peak-anchored (target-day) model the code is being aligned to. The AUTHORITY for this cycle is §2.2's substantive definition, not §2.1's stale paraphrase. §2.1:43-44 and §2.2:61-62 are updated as part of D5 (see below). Two consequences the plan takes as governing:

1. The class that produces the drain target is **the class of the target day of the next high-rate transition** (peak-anchored), i.e. `_classify_target_day(now)` — the exact helper the emitter already uses at `energy_battery.py:5112` for its `target_day_class` attribute. `current_offpeak_drain_target()` at `:1738` never adopted this and still reads `classify_tomorrow_solar()` (calendar-tomorrow). This cycle aligns the accessor with the documented model.
2. Because the reserve is a floor and the battery still charges from solar, the drain target is **behaviorally binding only when the battery is discharging** — i.e. during the DARK part of the off-peak window on nights where class disagreement inverts the target. The daylight part of off-peak is dominated by solar charging; the floor rarely binds there. This shapes both the blast-radius framing (below) and the live-validation choice (small-hours read is primary, daytime read is secondary and mostly moot).

---

## Blast-radius framing (right-sized)

Off-peak includes daytime in every season per the TOU table (summer 00-14, shoulder 00-17, winter 00-05 + 09-17). `_classify_target_day(now)` (and therefore `_resolve_target_day`) is called on EVERY tick (not only during off-peak — see `compose_release_floor:296`, `current_park_floor:1773`, sensor render `:6043`) and returns:

- **offset == 0** (target day = TODAY) whenever the NEXT high-rate transition is later today. This includes the pre-peak off-peak span (00:00 → today's peak boundary) AND any tick within off-peak on the SAME side of that boundary. Winter has an example: at `now = 05:30` in winter (mid-peak in progress, next PEAK at 17:00 today) → offset==0, class = today.
- **offset == 1** (target day = TOMORROW) whenever no high-rate transition remains today. This covers both (a) the 21:00–24:00 pre-midnight off-peak segment AND (b) any tick DURING an in-progress peak whose boundary has already passed (summer 14-21, shoulder 17-21, winter 17-21). Under (b) the accessor is called from `current_park_floor:1773` etc. — outside off-peak but on every tick — and returns tomorrow's class. This is harmless for correctness (offset==1 → `classify_tomorrow_solar()`, byte-identical to the pre-fix accessor), but the scope MUST be stated precisely so builder tests do not assume "offset==1 ⇔ 21:00–24:00" and miss the in-peak reads.
- **offset >= 2 is UNREACHABLE by construction:** every season has a daily high-rate window, so the next high-rate transition is always <= 1 calendar day away. The plan therefore removes the `offset >= 2` branch handling that the prior draft speculated about (no skip-guard, no D+2+ discussion — see §"Multi-day pairing" below).

**Mechanism reach:** the accessor / emitter split against calendar-tomorrow diverges on ~37% of days (probe) across essentially all off-peak hours where offset==0 (roughly the 00:00→peak-boundary span, ~17 wall-clock hours), NOT only the pre-fix "post-midnight" story the earlier draft implied.

**Money-impact reach (narrower):** the drain target is a discharge floor. During the daylight part of off-peak (roughly sunrise→peak boundary), the battery is typically charging from solar and the floor does not bind. The behaviorally-binding window is the DARK discharge hours (roughly 00:00→sunrise) on the subset of class-disagreement nights (~37% of days) where the battery is actively discharging. So the $-impact is a SUBSET of the probe's 37%, not the full 37%, and this is an actuarial gain on a narrower slice than the wall-clock reach suggests. Do **not** frame the fix as a "dominant-path" change — the mechanism is broad but the binding window is small-hours-only. The correctness fix still matters because the DISPLAY attribute (`sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target`) and the narration helpers (`_threshold_position`, `_next_action_estimate`) are ALSO wrong during the whole 17h span, and DP consumes the accessor on every tick.

---

## Institutional context verified

Every source claim below was verified by direct read in this session. File:line citations are exact.

### Greps run + results

| Proposed change | Verification | Result |
|---|---|---|
| Accessor `current_offpeak_drain_target()` calls `classify_tomorrow_solar()` | Read `energy_battery.py:1726-1747` | CONFIRMED at :1738 |
| `_get_offpeak_drain_target()` is a BARE dict lookup with NO multi-day max | Read `energy_battery.py:1722-1724` | CONFIRMED — `return self._drain_targets.get(tomorrow_class, DEFAULT_OFFPEAK_DRAIN_UNKNOWN)`. The multi-day max is OPEN-CODED TWICE — once in the accessor at :1740-1747, once in the emitter at :5306-5311. This is the Bug-Class-#53 closure surface (see H-1 shared-helper mandate in D3). |
| `classify_tomorrow_solar()` is calendar-blind | Read `energy_battery.py:1690-1720` | CONFIRMED — reads `self.solcast_tomorrow` and uses `(dt_util.now()+1day).month` for thresholds; no target-day anchoring |
| `_classify_target_day(now)` peak-anchored | Read `energy_battery.py:2395-2422` | CONFIRMED — offset<=0 → `classify_solar_day()`; ==1 → `classify_tomorrow_solar()`; falls back to `classify_tomorrow_solar()` when TOU unwired or no next high-rate transition |
| Emitter drain path at :5106-5112 uses `classify_tomorrow_solar` for drain while :5112 uses `_classify_target_day(now)` for the display `target_day_class` | Read `energy_battery.py:5106-5112` | CONFIRMED — literally adjacent lines |
| Multi-day max path uses `tomorrow_class` for D+1 + hardcoded `classify_solar_day_n(2)` for D+2 | Read `energy_battery.py:5300-5313` | CONFIRMED |
| Sibling render path at :5909-5911 (same adjacent split) | Read `energy_battery.py:5909-5911` | CONFIRMED |
| `_threshold_position` recomputes drain from `tomorrow_class` with hardcoded 40 fallback, UNCONDITIONAL (not phase-gated) | Read `energy_battery.py:5669-5698`, especially :5689 | CONFIRMED — `self._drain_targets.get(tomorrow_class, self._drain_targets.get("unknown", 40))`; called from `get_status` at :6079 with `tomorrow_class`; **narrates a drain target on every tick regardless of `_arbitrage_phase`** — so a live read of `threshold_position` on an arbitrage tick already shows drain narration today; the fix routes it through the shared helper but does NOT phase-gate it (see M-3 scoping of INV-DTDS-3) |
| `_next_action_estimate` phase-gated: only reaches drain fallback when phase is not CHARGE/ATTAIN/HOLD/WAIT/DISCHARGE | Read `energy_battery.py:5700-5734`, especially :5731 | CONFIRMED — same hardcoded 40 fallback and `tomorrow_class` key; the drain leg is behind an `if phase == ...` ladder so live reads during arbitrage phases return the phase narration, not drain |
| `DEFAULT_OFFPEAK_DRAIN_UNKNOWN = 40` is the canonical constant already used by `_get_offpeak_drain_target` | Read `energy_const.py:724` and `energy_battery.py:1724`, :471 | CONFIRMED — hardcoded 40 in the two helpers is a drift from the canonical constant |
| Real runtime consumers of `current_offpeak_drain_target()` | Read each cited site | `energy_battery.py:296` (compose_release_floor fallback), `:1773` (current_park_floor fallback), `:6043` (sensor attr). `energy.py:5831`, `energy_pool.py:1797`, `:3203` are DOCSTRING/COMMENT references only — NOT runtime calls |
| `_drain_targets` mutators (L-2) | Read `energy.py:8624-8652` | CONFIRMED — `offpeak_drain_targets` getter at :8625, `_check_threshold_ladder` reads `_drain_targets` at :8638, `set_offpeak_drain` mutates at :8651. These are the options/Number entity write path and belong in the Producer/Consumer table (see below). |
| `_recheck_forecast_on_charge_entry` pairs `_classify_target_day(now)` with hardcoded `classify_solar_day_n(2)` | Read `energy_battery.py:2441-2461` | CONFIRMED at :2454 / :2458 — analogous off-by-one on the arbitrage gate |
| `_gate_is_open` (`_evaluate_forecast_gate`) receives `target_day_class` and hardcodes `classify_solar_day_n(2)` for D+2 | Read `energy_battery.py:2870-2889` | CONFIRMED at :2878 — same analogous off-by-one |
| `classify_solar_day_n(days_ahead)` semantics | Read `energy_battery.py:1802-1849` | CONFIRMED — `<=0` → today; `==1` → tomorrow; `==2` → day_3; else falls back to tomorrow. Only relevant here for `n == 1` (offset==0 case, d2 = tomorrow) and `n == 2` (offset==1 case, d2 = day_3). |
| Fallback safety for `_resolve_target_day` | Read `_classify_target_day` fallbacks | CONFIRMED — TOU unwired or no next transition → `(classify_tomorrow_solar(), 1)`, byte-identical to prior accessor behavior |
| `inclement.py:432` calls `classify_tomorrow_solar()` (L-1 out-of-scope catch) | Read `inclement.py:428-434` | CONFIRMED — `_safe_tomorrow_class` genuinely wants calendar-tomorrow (inclement-weather policy is a next-day forecast, not a peak-anchored target-day quantity). Out of scope for this cycle, but framing-D MUST classify it explicitly to prove exhaustive enumeration (see D4 review framing). |
| No new CONF_ / knob introduced | n/a — the fix threads `now` into an existing accessor, swaps to an existing helper, adds ONE private shared helper (`_drain_target_for`), and reuses `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` | REUSED-ONLY |

### Prior planning docs consulted

- `docs/planning/PLANNING_dp_drain_target_mis_sourcing.md` — the paired DP fix; this cycle is its prerequisite per operator refinement 2026-08-24. DP reads the accessor unchanged (mirrors emitter after this cycle).
- Card body `DRAIN-TARGET-DAY-STALENESS-1` including `DEPENDS_ON_MIDNIGHT_FIX_2026_08_24`, `PROBE_RESULT_2026_08_24_BITES`, `BUILD_PAUSED_PLAN_ONLY_2026_08_24`.

### Memory bodies pulled

- `feedback_verify_claim_types_not_felt_uncertainty.md` — motivated the "card claims 5 consumers, 3 are comments" spot-check (confirmed).
- `feedback_falsify_before_asserting.md` + `feedback_hollow_test_anchors.md` — motivate discriminating cross-midnight tests using dated probe pairs (2025-05-01/02 and 2025-12-01/02), and the framing-C rule that every new test must construct a real / stubbed `_tou` (a `None` fixture routes to the same `classify_tomorrow_solar()` fallback as the pre-fix accessor and would leave the fix untested).
- CLAUDE.md — Tier-3 protocol; falsifiable invariant up front; Producer/Consumer symmetry; Numbers-Get-Knobs (no new knob here).

### Design docs read

- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.1 (contradicts — updated in D5) + §2.2 (governing authority — drain-target semantics + discharge-floor semantics). See §"Design-intent authority" above.

### Code locations surveyed end-to-end during scoping

- `energy_battery.py` §§1680-1850 (classifiers + accessor + `_get_offpeak_drain_target`), §§2395-2422 (`_classify_target_day`), §§2441-2461 (`_recheck_forecast_on_charge_entry`), §§2860-2889 (`_evaluate_forecast_gate` / `_gate_is_open`), §§5080-5340 (`_get_off_peak_decision` emitter incl. multi-day max + partial_hold clamp at :5322), §§5669-5734 (`_threshold_position`, `_next_action_estimate`), §§5880-5935 (sensor render + `forecast_outlook`; `now = dt_util.now()` at `:5910`), §§280-303 (`compose_release_floor`), §6030-6091 (`get_status` attribute pack).
- `energy.py` :5820-5846 (drain-actions caller — confirmed indirect only) and :8620-8654 (drain-targets mutators — L-2).
- `energy_pool.py` :1790-1810, :3195-3210 (docstrings only — confirmed).
- `inclement.py` :428-434 (L-1 — genuinely calendar-tomorrow, out of scope but framing-D must classify).

---

## The falsifiable invariants (Tier-3 requires this stated up front)

**INV-DTDS-1 (PRE-FIX BYTE-IDENTICAL WHERE OFFSET==1, RE-FRAMED — M-2 SCOPED):** For any `now` such that `_resolve_target_day(now)` returns offset == 1, `current_offpeak_drain_target()`, the emitter's `drain_class_for_target`, `_threshold_position`, and `_next_action_estimate` MUST all return values byte-identical to the pre-fix implementation. Offset == 1 IS NOT limited to the 21:00-24:00 pre-midnight off-peak segment — it ALSO covers any tick during an in-progress high-rate window whose boundary has already passed (summer 14-21, shoulder 17-21, winter 17-21), because on those ticks no high-rate transition remains today. Offset == 0 covers everything else in off-peak AND any pre-boundary tick within a same-day off-peak / mid-peak stretch (including winter 05-09, where the accessor returns today's 17:00 boundary target). Harmless for correctness (offset==1 → `classify_tomorrow_solar()`, byte-identical), but the SCOPE must be stated precisely so a builder test does not assume "offset==1 ⇔ evening off-peak" and skip the in-peak reads that the accessor still sees via `compose_release_floor:296` / `current_park_floor:1773` / sensor attr `:6043` on every tick.

Blast-radius framing (right-sized): the pre-fix `classify_tomorrow_solar()` reads calendar-D+1. Under offset==1 the target IS calendar-D+1, so all four sites are byte-identical. Under offset==0 (00:00→peak boundary, ~17 wall-clock hours during a pre-peak span) they diverge — accessor/emitter switch to today's forecast; the DISPLAY narration helpers switch too. Money-impact is concentrated in the dark discharge hours (roughly 00:00→sunrise) on class-disagreement nights (subset of ~37% of days); the daylight offset==0 span is dominated by solar charging and the floor rarely binds (manual §2.2). Correctness matters across the whole 17h span (display + DP consumption); dollars matter in the dark small hours.

**INV-DTDS-2 (OFFSET==0 CORRECTNESS):** For any `now` such that `_classify_target_day(now)` returns offset == 0 (target = TODAY's peak), `current_offpeak_drain_target()`, the emitter's `drain_class_for_target`, `_threshold_position`, and `_next_action_estimate` MUST all select from **today's** Solcast classification, NOT calendar-tomorrow's. All four MUST agree on every tick.

**INV-DTDS-3 (EMITTER-ACCESSOR-NARRATION PARITY — M-3 SCOPED):** For every off-peak tick **on which the emitter would take the drain-fallback branch of `_get_off_peak_decision`** (i.e. arbitrage_phase ∈ {`n/a`, `WAIT`} AND `decision.hold_depth == "allow_discharge"` — the branches that actually consume `drain_class_for_target` at :5300-5313 without further clamping), the PRE-CLAMP `drain_target` computed by `current_offpeak_drain_target(now)` == the PRE-CLAMP `drain_target` the emitter computes at that same `now` == the drain value narrated by `_threshold_position(soc, now)` == the drain value narrated by `_next_action_estimate(soc, now)` (when its phase gate falls through to the drain fallback). "PRE-CLAMP" matters because the emitter clamps up to `effective_reserve` under `partial_hold` at :5322, and the `arbitrage_charge` / `attain` / `full_hold` branches never reach the drain fallback at all — they command reserve via other paths. Comparing COMMANDED reserve, not the pre-clamp target, would false-fail on legitimate partial_hold or arbitrage ticks. NOTE (verified :5689): `_threshold_position` narrates a drain value UNCONDITIONALLY (not phase-gated) — so on an arbitrage tick its narration MAY legitimately cite the shared-helper drain even though the emitter does not command it; the invariant still holds (parity across the four derivations), but a live-validation read of `threshold_position` on an arbitrage tick is EXPECTED to show drain narration and is NOT a failure. `_next_action_estimate` IS phase-gated (:5709-5729) and reaches the drain fallback (:5731) only when phase is not one of the arbitrage phases.

**INV-DTDS-4 (MULTI-DAY PAIRING PRESERVED):** With `multi_day_horizon_enabled`, the conservative-max selection MUST be between the TARGET day (offset from `_resolve_target_day`) and TARGET+1, i.e. `d2 = classify_solar_day_n(offset + 1)`, NOT hardcoded `classify_solar_day_n(2)`. Because offset ∈ {0, 1} by construction (see blast-radius framing), `classify_solar_day_n(offset + 1)` reads either `classify_tomorrow_solar()` (offset==0) or `solcast_day_3` (offset==1) — both well-defined codepaths in the classifier.

**INV-DTDS-5 (OFFSET >= 2 UNREACHABLE):** No reachable `(now, TOU-state)` in production configuration produces an offset >= 2 from `_classify_target_day(now)` / `_resolve_target_day(now)`. Every season has a daily high-rate window; the next high-rate transition is always <= 1 calendar day away. The prior draft's discussion of an offset >= 2 skip-guard is removed as speculative — the plan does NOT add a skip-guard, and no test asserts offset >= 2 behavior (untestable-as-a-reachable-state).

Adversarial-completeness reviewer's job (framing D): re-enumerate every emission or consumer site of `classify_tomorrow_solar` on the drain path across the entire file, not the diff. INV-DTDS-3 must hold across every reachable site, including sites the plan did not touch. If any drain-related site still keys on calendar tomorrow after the fix, the invariant is violated. **Falsifiable form for D:** state `(now, TOU-state, Solcast state, arbitrage_phase, hold_depth)` tuples where the accessor, the emitter (drain-fallback branch), `_threshold_position`, and `_next_action_estimate` MUST agree on the PRE-CLAMP drain target; hunt for a tuple where any of them diverges.

---

## Deliverables

### D1 — Add a peak-anchored day resolver that returns (class, offset)

**Why:** `_classify_target_day(now)` returns only the class. The multi-day max re-pairing (INV-DTDS-4) needs the offset so d2 can be derived as `offset+1`. A parallel resolver keeps `_classify_target_day` byte-identical for its arbitrage callers.

**Change:** Introduce private helper (name TBD by builder — candidate `_resolve_target_day(now) -> tuple[str, int]`) at `energy_battery.py` near :2395. Body factors the offset computation from `_classify_target_day` so both share the same TOU read:

```
def _resolve_target_day(self, now: datetime) -> tuple[str, int]:
    """Return (class, offset_days) for the day of the next high-rate transition.

    Offset is clamped to >= 0 (offset<=0 means "today"). Falls back to
    (classify_tomorrow_solar(), 1) when TOU is unwired or no transition
    found — same fallback shape as _classify_target_day, so callers of
    _classify_target_day can be re-expressed as this[0] without changing
    behavior on the fallback path. In production configuration offset
    is always in {0, 1} (INV-DTDS-5); the resolver does not need to
    special-case deeper offsets.
    """
```

Reshape `_classify_target_day` to `return self._resolve_target_day(now)[0]` — one-line delegation, keeps all existing arbitrage callers (`_recheck_forecast_on_charge_entry` :2454, mid_peak :5026, off_peak :5112 and :5911) byte-identical.

**Non-goal:** do NOT change the fallback semantics ("no next high-rate transition" → tomorrow) — that would silently change the arbitrage path.

### D1b — Add the single shared drain-target helper (H-1 mandate)

**Why (H-1, load-bearing):** `_get_offpeak_drain_target()` at `energy_battery.py:1722-1724` is a BARE dict lookup with NO multi-day max — the max is OPEN-CODED TWICE, once in the accessor at `:1740-1747` and once in the emitter at `:5306-5311`. Routing the narration helpers through `_get_offpeak_drain_target()` alone would give D+1-only and FAIL INV-DTDS-3's equality assertion under `multi_day_horizon_enabled` (concrete repro: offset==0, today "excellent" → drain 10, D+1 "poor" → drain 30; accessor returns `max(10, 30) = 30`, but `_get_offpeak_drain_target(d1_class)` alone returns 10). The prior draft's "or refactor, decide during build" wording is DELETED — the shared helper is MANDATED, not optional.

**Change:** Introduce ONE private shared helper adjacent to `_get_offpeak_drain_target` (name TBD by builder — candidate `_drain_target_for(now) -> int`):

```python
def _drain_target_for(self, now: datetime) -> int:
    """Single source of truth for the peak-anchored drain target INCLUDING
    the multi-day-horizon conservative max. Replaces the two open-coded
    max() copies at :1740-1747 (accessor) and :5306-5311 (emitter). Every
    drain-target consumer — accessor, emitter drain-fallback branch,
    _threshold_position, _next_action_estimate — MUST call this helper.
    Do NOT open-code a second dict lookup or a second max().
    """
    d1_class, d1_offset = self._resolve_target_day(now)
    d1_target = self._get_offpeak_drain_target(d1_class)
    if not self._multi_day_horizon_enabled:
        return d1_target
    try:
        d2_class = self.classify_solar_day_n(d1_offset + 1)
    except Exception:  # noqa: BLE001
        return d1_target
    d2_target = self._get_offpeak_drain_target(d2_class)
    return max(d1_target, d2_target)
```

**All four consumer sites MUST route through `_drain_target_for(now)`:**

1. `current_offpeak_drain_target()` at `:1726` — body collapses to `return self._drain_target_for(now or dt_util.now())` (see D2 for the `now` threading).
2. Emitter drain path at `:5300-5313` — replace the open-coded d1/d2 max block with `drain_target = self._drain_target_for(now)`. `drain_class_for_target` is retained ONLY for log/reason interpolation; derive it as `d1_class` when a display string is needed (call `_resolve_target_day(now)[0]` locally).
3. `_threshold_position` at `:5669/:5689` — replace the `self._drain_targets.get(...)` lookup with `drain = self._drain_target_for(now)`.
4. `_next_action_estimate` at `:5700/:5731` — same replacement on the drain-fallback leg.

Collapsing the two open-coded max copies into the shared helper IS the actual Bug-Class-#53 closure — the accessor and emitter no longer have "two truths" that could drift under future edits.

**Framing-C mutation site (6th site added, H-1):** in addition to the five sites listed in the Tier-3 framing C, mutate `_drain_target_for` itself (e.g. hard-return `self._get_offpeak_drain_target(self.classify_tomorrow_solar())` to bypass BOTH the resolver AND the multi-day max) and confirm a SPECIFIC named test fails — the multi-day-max round-trip test (INV-DTDS-4) MUST be that test. A green suite under this mutation means the shared helper's max leg is untested = unacceptable.

### D2 — Thread `now` into `current_offpeak_drain_target()`; route through `_drain_target_for`

**Change at `energy_battery.py:1726-1747`:**

- Signature: `def current_offpeak_drain_target(self, now: datetime | None = None) -> int:` — default `None` for back-compat.
- Body: if `now is None: now = dt_util.now()`; `return self._drain_target_for(now)`.
- The MED-1 guarded-fallback try/except now lives INSIDE `_resolve_target_day` (called by `_drain_target_for`), not in the accessor — the fallback shape (`classify_tomorrow_solar()`, offset=1) is preserved; the accessor no longer open-codes any max.

**Callers of the accessor (real runtime, from the verified list):**

- `energy_battery.py:296` (`compose_release_floor` fallback) — pass no argument (accessor uses `dt_util.now()` internally). Threading `now` all the way through `compose_release_floor` is a SCOPE EXPANSION deferred to the DP cycle. For THIS cycle: sub-tick drift between caller and accessor is bounded to seconds — cannot cross a TOU boundary within a single decision tick.
- `energy_battery.py:1773` (`current_park_floor` fallback) — same: no arg passed.
- `energy_battery.py:6043` (sensor attr) — no arg passed.
- Sensor render at :5909-5911 already computes `now = dt_util.now()` at `:5910`; passing it to the accessor is a follow-on (parked; see D4).

**Acceptance criteria (D2):**

- **Verify:** grep `current_offpeak_drain_target(` — every runtime call site listed above still typechecks; no unintended callers surfaced (institutional-context re-run at review time).
- **Test:** `test_current_offpeak_drain_target_no_arg_defaults_to_now()` — call with no arg; monkeypatch `dt_util.now` to a fixed value; verify class read matches `_resolve_target_day(that_now)[0]`. **MUST wire a real / stubbed `_tou`** returning a controlled `get_next_high_rate_transition`; a `_tou = None` fixture falls back to `classify_tomorrow_solar()` and would leave the fix untested (framing-C hollow anchor).
- **Test (INV-DTDS-1 offset==1 in evening off-peak):** stub `now = <date> 22:30` so `get_next_high_rate_transition` returns calendar-D+1 boundary (offset==1); verify `current_offpeak_drain_target(now)` == `_get_offpeak_drain_target(classify_tomorrow_solar())` including multi-day max via `_drain_target_for`.
- **Test (INV-DTDS-1 offset==1 during in-progress peak, M-2 scope):** stub `now = <date> 16:00` in summer during in-progress peak (14-21) so `get_next_high_rate_transition` returns tomorrow's boundary (offset==1); verify accessor still returns calendar-tomorrow-based target. This is the "outside off-peak, called every tick" case — accessor called via `current_park_floor:1773`.
- **Test (INV-DTDS-2 offset==0):** stub `now = <date> 02:00` so `get_next_high_rate_transition` returns SAME-day 14:00 boundary (offset==0); with today Solcast="poor", tomorrow="excellent"; verify accessor keys today's class (poor), NOT tomorrow's. Repro-exact using probe-verified inversion pairs 2025-12-01→02 and 2025-05-01→02.
- **Test (INV-DTDS-2 winter mid-peak, M-2 scope):** stub `now = <date> 07:00` in winter (mid-peak 05-09 in progress, next PEAK at 17:00 today) so `get_next_high_rate_transition` returns 17:00 today (offset==0); verify accessor keys TODAY's class.
- **Test (MED-1 fallback):** stub `_tou.get_next_high_rate_transition` to raise; verify accessor returns the `classify_tomorrow_solar()` value without propagating the exception (via `_resolve_target_day`'s guarded fallback).
- **Live:** on next cross-midnight night, `sensor.ura_energy_coordinator_battery_strategy` attr `current_offpeak_drain_target` at ~02:00 CDT (small-hours; discharge active; class-disagreement night; arbitrage_phase ∈ {`n/a`, `WAIT`} AND `hold_depth == allow_discharge`) matches the drain the emitter would command (INV-DTDS-3, scoped to drain-fallback branch). See §"Live validation plan" for discrimination.

### D3 — Swap the emitter's drain-class computation AND the narration helpers onto `_drain_target_for`

**Emitter change at `energy_battery.py:5106-5112` and :5300-5313:**

- Preserve `tomorrow_class = self.classify_tomorrow_solar()` **for the DISPLAY attribute only** (the `tomorrow_solar_class` operator-facing telemetry name; renaming its meaning is out of scope).
- Introduce `d1_class, d1_offset = self._resolve_target_day(now)` for the log/reason string display. Compute `drain_target = self._drain_target_for(now)` (single call — replaces the open-coded d1/d2 max block at :5306-5311). `drain_class_for_target` is retained only if a display string names a class; when it does, use `d1_class` (or the class corresponding to `max(d1, d2)` — decide during build BUT the numeric `drain_target` MUST come from `_drain_target_for`, not from an open-coded re-lookup).
- The log/reason strings that interpolate `tomorrow_class` in the DRAIN-DECISION context (e.g. `:5328` "Off-peak drain — SOC {soc}% > target {drain_target}% (tomorrow {tomorrow_class})") — interpolate `d1_class` and rename the fragment to "target-day"; surface as an operator naming decision in plan review.

**Sibling render path at :5909-5911** (sensor render `get_status`): `tomorrow_class` there feeds `forecast_outlook.d1_class` at :6031 whose contract is calendar D+1. That contract is preserved. Confirm during review.

**Narration helpers — HIGH-1 addition (H-1 mandate):** `_threshold_position` (`energy_battery.py:5669-5698`, called from `get_status` at :6079) and `_next_action_estimate` (`:5700-5734`, called from `get_status` at :6080) INDEPENDENTLY recompute the drain target on the same sensor from `tomorrow_class` and would visibly contradict the fixed accessor on the SAME sensor. Route them through the corrected path:

- Change both helpers' signatures to take `now: datetime` instead of `tomorrow_class: str` (call sites at :6079 / :6080 already have `now` in scope from `:5910`).
- Inside each helper: `drain = self._drain_target_for(now)` — SINGLE call to the shared helper. Do NOT open-code a second `self._drain_targets.get(...)` lookup and do NOT open-code a second max(). If a display string cites a class name, compute it locally via `self._resolve_target_day(now)[0]`.
- The hardcoded `40` fallback is naturally killed — `_drain_target_for` routes through `_get_offpeak_drain_target` which already uses `DEFAULT_OFFPEAK_DRAIN_UNKNOWN`. If any surviving direct `_drain_targets.get()` lookup remains (it should not, per H-1), it MUST use `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (`energy_const.py:724`) — not a bare literal.
- Narration strings inside the helpers currently interpolate `tomorrow={tomorrow_class}`; rename to `target={d1_class}` (or similar) to match the corrected semantics; call out as an operator-facing string change in plan review.

**HIGH-2 (drift, 2026-08-25) — preserve the DP value-stamp; test the DP downstream.** D3 replaces the derivation at `5316-5330` with `drain_target = self._drain_target_for(now)`. It MUST NOT touch the partial_hold clamp (`5340`) or the value-stamp (`5349`) that follow — the stamp reads the local `drain_target` and is how DP (5.90.1) consumes this tick's floor. After D3, the stamp must carry the peak-anchored composed value.
- **Framing-C mutation site (7th):** re-point the derivation to the OLD calendar-tomorrow lookup (`drain_target = self._get_offpeak_drain_target(self.classify_tomorrow_solar())`) while leaving the stamp intact → a DP-integration test MUST fail, proving the stamp (and thus the DP floor) now routes through `_drain_target_for(now)`.
- **Test:** `test_dp_value_stamp_carries_peak_anchored_target()` — at stubbed `now` at offset 0 with today/tomorrow class disagreement, assert `_offpeak_drain_branch_target` after `determine_mode` equals `_drain_target_for(now)` (peak-anchored), NOT `_get_offpeak_drain_target(classify_tomorrow_solar())`.

**Acceptance criteria (D3):**

- **Verify (INV-DTDS-2):** at stubbed `now = 2026-02-01 02:00` with `get_next_high_rate_transition` returning `2026-02-01 14:00` (offset 0), Solcast today=poor / tomorrow=excellent — emitted drain target keys TODAY (poor). Repro-exact using probe inversion pairs 2025-12-01→02 (30→10) and 2025-05-01→02 (10→30).
- **Verify (INV-DTDS-3 parity, PRE-CLAMP, drain-fallback branch):** at the same stubbed `now` with arbitrage_phase set to `n/a` AND `hold_depth == allow_discharge`, all four sites — `current_offpeak_drain_target(now)`, emitter's PRE-CLAMP `drain_target` at :5313, `_threshold_position(soc, now)`, `_next_action_estimate(soc, now)` (when its phase gate falls through) — return EQUAL integers. Test asserts EQUALITY of the derived integers, not merely `!= stale`, and does NOT compare against the post-clamp commanded reserve.
- **Verify (INV-DTDS-3 parity survives multi-day):** repeat with `multi_day_horizon_enabled=True` and a today "excellent" / D+1 "poor" pair — accessor, emitter, and both narration helpers ALL return 30 (the max), not 10. This is the H-1 mandate's central proof.
- **Verify (INV-DTDS-4 multi-day re-pairing):** with `multi_day_horizon_enabled=True` and offset==0, multi-day max is between today (n=0) and tomorrow (n=1), NOT today and D+2.
- **Test:** `test_cross_midnight_selects_today_over_tomorrow()` — one row per probe-verified inversion pair.
- **Test:** `test_multi_day_max_repaired_across_midnight()` — INV-DTDS-4.
- **Test:** `test_drain_target_for_helper_is_single_source_of_truth()` — with `multi_day_horizon_enabled=True` and today "excellent" / D+1 "poor" / offset==0, assert accessor == emitter pre-clamp == `_threshold_position` derived drain == `_next_action_estimate` drain-fallback derived drain, all four == `_drain_target_for(now)` == `max(10, 30) = 30`. H-1 closure.
- **Test:** `test_display_attr_tomorrow_solar_class_still_calendar_tomorrow()` — INV-DTDS-1 for the DISPLAY axis; guards against a well-meaning collapse of the two variables.
- **Test (HIGH-1):** `test_threshold_position_uses_shared_helper()` and `test_next_action_estimate_uses_shared_helper()` — with `now` at offset==0 and today/tomorrow class disagreement, the narration string cites TODAY's class and drain, matching the accessor. Both tests require real/stubbed `_tou`; a `_tou=None` fixture is a hollow anchor and is disallowed.
- **Test (HIGH-1 constant):** `test_threshold_and_next_action_fallback_uses_default_constant()` — with an empty `_drain_targets` map, both helpers return `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (40 today), NOT a hardcoded literal. Assert against the imported constant, not the number.
- **Live pre-fix divergence CONFIRMED 2026-08-25 21:25 CDT (H-1 empirical repro):** on the live sensor, `next_action_estimate` narrated "drain to 10.0% (tomorrow=excellent)" while `current_offpeak_drain_target` (the accessor) read **15** and the decision commanded 15 to hardware (cloud_oracle=15.0). This is exactly the H-1 same-sensor contradiction (naive `_drain_targets.get(tomorrow_class)` vs the composed multi-day max). Post-fix, this divergence MUST be gone: both must read the shared-helper value. Use this observed pair (10 vs 15) as the concrete pre/post check.
- **Live:** on next cross-midnight class-disagreement night, at ~02:00 CDT read on the SAME sensor: `current_offpeak_drain_target`, `threshold_position`, `next_action_estimate` — all three MUST narrate today's class. Cross-check `forecast_outlook.d1_class` (contract: calendar tomorrow) — the two can legitimately disagree post-midnight; a session where they DO disagree and the drain narration cites today is the strong positive validation. Live-read the sensor's `arbitrage_phase` AND `hold_depth` attrs FIRST — treat the parity check as discriminating only when `arbitrage_phase ∈ {n/a, WAIT}` AND `hold_depth == allow_discharge`. On an arbitrage tick, `_threshold_position` will still narrate the shared-helper drain (it is not phase-gated at :5689) — that is expected and NOT a failure; the strong evidence is the drain-fallback tick.

### D6 — (ADOPTED 2026-08-25, ADDITIVE) Always-on DP decision telemetry
Surface the DP carrier decision as always-on attributes on `sensor.ura_energy_coordinator_ev_charging_status` (data already exists in the carrier / `command_trail`): `dp_state` (HOLD_ONLY / HOLD_PRE_EVAL / TRANSITIONED), `dp_latched_soc`, `dp_drain_floor` (the composed floor DP settled on), `dp_reason`/gate, `dp_eval_countdown_s`. Do NOT rely on the disabled `sensor.ura_energy_drain_precedence_state` (enabling it needs a reload → restart → warm-up hold — the exact trap on 2026-08-25). **Additive: no decision-path change.**

**Acceptance:** a plug-in latch reads `dp_state=HOLD_*` + `dp_latched_soc`=current SOC; after re-eval `dp_drain_floor` == the composed target (== `_drain_target_for(now)`), all without enabling a disabled entity or reading prose. Live: reproduces tonight's 21:26 sequence (latch 28 → floor 15) directly from these attrs.

### D7 — (ADOPTED 2026-08-25, ADDITIVE) Per-EVSE structured state (not prose)
Replace reliance on `pause_reason_human` prose with a structured per-bay record: `{state: paused|throttled|charging, owner, commanded_amps, actual_kw}`. Kills the pause-vs-throttle ambiguity (orchestrator misread "grid import cap" as throttle when it means paused) and is REQUIRED once solar-follow throttling is live (a bay at 24 A is neither paused nor charging). Same surface as the solar-follow `solar_follow_*` observability. **Additive: no decision-path change.**

**Acceptance:** for each bay, `state` matches actuator ground truth (switch on+power>threshold=charging; switch off=paused; solar-follow limit<48=throttled), `owner` names the controlling hold, `commanded_amps`/`actual_kw` present. Discriminating: a paused bay and a throttled bay are distinguishable without reading a prose string.

**Plan-review note (both D6/D7):** additive surfacing adopted after the base plan's Tier-3 review; per Plan Review tiering they get one focused additive plan-review pass (no drain-target-logic overlap; confirm no new decision-path read, no write-flood, and that the DP attrs read the carrier not a recompute) before build. keep the Tier-3 rigor on D1–D3.

### D4 — (Deferred / non-goal) Thread `now` through consumer paths

Threading `now` from every caller (`compose_release_floor`, `current_park_floor`, sensor render) is a scope expansion. **Non-goal for this cycle.** Justification: the accessor internally computes `dt_util.now()` when called with no arg; caller / accessor drift is sub-second and cannot cross a TOU boundary within a single tick. Parked-plan trigger: **revisit if** a diagnostic ever shows an accessor read whose classification disagrees with the emitter's within the same tick due to `dt_util.now()` drift.

### D5 — Docs / comment drift (INCLUDES manual edit per M-1)

- `energy_battery.py:1727-1737` docstring on `current_offpeak_drain_target()`: describe **peak-anchored target-day** (day of next high-rate transition), not "tomorrow"; cite manual §2.2 discharge-floor semantics. Also fix the stale citation in that docstring: it references the emitter as `:3101-3114`; the actual emitter drain path is `:5306-5313`. Update the file:line citation as part of the docstring rewrite (L-3).
- `energy.py:5831` comment referencing the accessor: update to peak-anchored.
- `energy_pool.py:1797` and `:3203` docstring mentions: same one-line update.
- Docstrings on `_threshold_position` and `_next_action_estimate`: replace `tomorrow_class` parameter description with `now` / target-day narration.
- **Manual edit (M-1) — TWO one-line updates to `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md`:**
  - `ENERGY_COORDINATOR_MANUAL.md:43-44` (§2.1): change "allow drain to a *drain target* set by tomorrow's solar forecast" → "allow drain to a *drain target* set by the class of **the target day of the next high-rate transition** (peak-anchored — TOMORROW's forecast when the next peak is tomorrow, TODAY's forecast when the next peak is later today)". §2.2 unchanged in substance.
  - `ENERGY_COORDINATOR_MANUAL.md:61-62` (§2.2 first bullet): change "if solar will refill tomorrow, drain deeper; if not, protect reserve" → "if solar will refill the target day (day of the next high-rate transition), drain deeper; if not, protect reserve". Preserves §2.2's discharge-floor framing verbatim, only re-anchors "tomorrow" → "target day".
  - Justification: §2.1's current paraphrase actively CONTRADICTS the peak-anchored model the code is being aligned to (see §"Design-intent authority"). Shipping code that aligns to §2.2 while §2.1 still says "tomorrow" leaves the manual internally inconsistent and re-opens the same misdesign the next time someone reads §2.1 first. The prior draft's "Non-goal: not editing the manual" is REPLACED by this sub-item.

---

## Multi-day pairing (the section plan review must scrutinize)

Today's emitter (at :5306-5311):

```python
if self._multi_day_horizon_enabled:
    d2_class = self.classify_solar_day_n(2)   # hardcoded calendar D+2
    d1_target = self._get_offpeak_drain_target(tomorrow_class)  # calendar D+1
    d2_target = self._get_offpeak_drain_target(d2_class)
    if d2_target > d1_target:
        drain_class_for_target = d2_class
```

And a byte-identical open-coded copy in the accessor at :1740-1747 (both computed independently → drift risk = Bug-Class-#53 surface).

Post-fix (both sites collapsed to a single call):

```python
# In the accessor (D2):
def current_offpeak_drain_target(self, now: datetime | None = None) -> int:
    return self._drain_target_for(now or dt_util.now())

# In the emitter drain-fallback branch (D3):
drain_target = self._drain_target_for(now)
# drain_class_for_target retained only for log/reason interpolation:
d1_class, _ = self._resolve_target_day(now)  # for the display string

# In _threshold_position and _next_action_estimate (D3, drain leg):
drain = self._drain_target_for(now)
```

And `_drain_target_for(now)` is the sole surface where `max(d1, d2)` lives (D1b). Because `d1_offset ∈ {0, 1}` by construction (INV-DTDS-5), `classify_solar_day_n(d1_offset + 1)` reads either `classify_tomorrow_solar()` (n=1, when offset==0) or `solcast_day_3` (n=2, when offset==1) — both well-defined. **No skip-guard is added**; the offset >= 2 branch of `classify_solar_day_n` (which would degrade to `classify_tomorrow_solar`) is UNREACHABLE from the drain path and therefore untested.

---

## Producer / Consumer map (mandatory rule, applied)

**PRODUCER side (post-fix):**

- `_drain_target_for(now)` — NEW helper (D1b); produces the integer drain target INCLUDING the multi-day-horizon conservative max. Sole surface for drain-target production. Depends on `_resolve_target_day(now)`, `_get_offpeak_drain_target()`, `_multi_day_horizon_enabled`, and `classify_solar_day_n(d1_offset+1)`.
- `_resolve_target_day(now)` — NEW helper (D1); produces `(class, offset)` with `offset ∈ {0, 1}` in production. Depends on `self._tou.get_next_high_rate_transition(now)` (health: production-wired for months) and `classify_solar_day() / classify_tomorrow_solar() / classify_solar_day_n(1|2)` (health: Solcast integration, primary + tomorrow + day_3 entities; day_3 optional and only touched under multi-day-horizon).
- Dependency health notes: `_tou is None` OR `get_next_high_rate_transition(now)` returns None OR raises → `(classify_tomorrow_solar(), 1)` (guarded fallback path inside `_resolve_target_day`). Preserves current behavior on the fallback path (INV-DTDS-1 holds).
- `_drain_targets` dict itself — mutated by the options / Number entity path at `energy.py:8651` (`set_offpeak_drain`), read by `energy.py:8625` (`offpeak_drain_targets` property surfacing the current map to callers), and read by `_check_threshold_ladder` at `energy.py:8638` for validator warnings. These are the operator-write surfaces that populate the numbers `_drain_target_for` looks up; the fix does not change them, but they belong in the map (L-2).

**CONSUMER + call-site check (verified real runtime consumers only):**

| Site | file:line | Trust vs display | Effect of fix |
|---|---|---|---|
| `compose_release_floor` fallback | `energy_battery.py:296` | TRUST (feeds `reserve_soc` on the EV drain-pause path) | Reads corrected value on every tick |
| `current_park_floor` fallback | `energy_battery.py:1773` | TRUST (feeds every consumer of the park floor when `_last_reserve_level` is None — boot path, restart) | Reads corrected value |
| Sensor attr `current_offpeak_drain_target` | `energy_battery.py:6043` | DISPLAY | Reads corrected value; visible in `sensor.ura_energy_coordinator_battery_strategy` |
| Off-peak emitter drain-fallback branch | `energy_battery.py:5300-5313` | TRUST (commands Enphase reserve when `hold_depth == allow_discharge`, phase ∈ {n/a, WAIT}) | Corrected — sole call to `_drain_target_for(now)`; open-coded max removed |
| Off-peak emitter partial_hold clamp | `energy_battery.py:5322` | TRUST | Unchanged — clamps `drain_target = max(drain_target, effective_reserve)`. Post-clamp value != pre-clamp; INV-DTDS-3 asserts on PRE-clamp |
| `_threshold_position` narration | `energy_battery.py:5669-5698`, called at `:6079` | DISPLAY (narration string on the same sensor as the accessor) | Corrected — routes through `_drain_target_for(now)`; hardcoded 40 gone; multi-day-aware; NOT phase-gated (narrates drain on every tick, which is pre-existing behavior — see M-3 note in INV-DTDS-3) |
| `_next_action_estimate` narration | `energy_battery.py:5700-5734`, called at `:6080` | DISPLAY | Corrected — same treatment; IS phase-gated (drain fallback only when phase ∉ arbitrage phases) |
| Sensor render `get_status` at `:5909-5911` (`now` computed at `:5910`) | Unchanged — `classify_tomorrow_solar` still populates `forecast_outlook.d1_class` (calendar-D+1 contract) | DISPLAY | Unchanged |
| `_drain_targets` map getter | `energy.py:8625` (`offpeak_drain_targets` property) | DISPLAY / API | Unchanged; feeds `set_offpeak_drain` UI and diagnostics |
| `_drain_targets` map validator read | `energy.py:8638` (`_check_threshold_ladder`) | POLICY (warns on ladder violation) | Unchanged |
| `_drain_targets` map mutator | `energy.py:8651` (`set_offpeak_drain`) | WRITE (options / Number entity) | Unchanged; next tick after write, `_drain_target_for` sees the new map |
| `energy.py:5831`, `energy_pool.py:1797/:3203` | Docstrings only, NOT runtime calls | n/a | Comment update only (D5) |

**Discriminating acceptance criterion:** on a small-hours post-midnight tick on a class-disagreement night, with `arbitrage_phase ∈ {n/a, WAIT}` AND `hold_depth == allow_discharge`, `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target` == the PRE-CLAMP derived drain from `threshold_position` == the PRE-CLAMP derived drain from `next_action_estimate` == the reserve floor the emitter has commanded (from log or `_last_reserve_level` snapshot). Pre-fix, these can differ.

---

## TOU-engine seam — boundary behavior

Re-target the boundary tests away from midnight literals (the drain gate does NOT change class at midnight — it changes at the peak boundary within the day):

- **T-boundary summer:** at `now = <date> 13:59:59` (last second of off-peak, target-day still today, offset==0) → drain target keys TODAY. At `14:00:00+` off-peak ends BUT the accessor is still callable from `current_park_floor:1773` (in-peak tick) and the next transition is now tomorrow 14:00 → offset==1 → drain reads calendar-tomorrow. No divergence within a tick.
- **T-boundary shoulder:** repeat with 17:00 boundary.
- **T-boundary winter:** repeat with 05:00 AND 17:00 boundaries (winter has two peak segments). At 05:30 (mid-peak in progress, next PEAK at 17:00 today) → offset==0 (M-2 scope confirmation).
- **T-boundary evening-into-offset==1:** at `now = <date> 21:00:00` (start of pre-midnight off-peak segment; next transition = tomorrow's peak) → offset==1 → INV-DTDS-1 byte-identical.
- **T-boundary in-progress-peak (M-2 scope):** at `now = <date> 16:00` in summer (peak 14-21 in progress; no transition today) → offset==1 → INV-DTDS-1 byte-identical.
- **No midnight-specific test** — midnight is NOT a class-changing boundary from the resolver's perspective (the class only changes when the next-transition target day rolls forward, which happens at the peak boundary, not at 00:00).

---

## Live validation plan (post-restart)

On the **next class-disagreement night** after deploy (per probe, ~37% of nights):

- **Primary read at ~02:00 CDT (small-hours, discharge active, offset==0 → target=today):**
  - PRE-READ: confirm `sensor.ura_energy_coordinator_battery_strategy` attrs `arbitrage_phase ∈ {n/a, WAIT}` AND `hold_depth == allow_discharge`. If either fails, the read is UNDISCRIMINATING for INV-DTDS-3 (see M-3 scoping — arbitrage/attain/full_hold branches never reach the drain fallback; partial_hold clamps up). Wait for a tick that meets the pre-conditions before treating the read as evidence.
  - `sensor.ura_energy_coordinator_battery_strategy` attrs: `current_offpeak_drain_target`, `reserve_level`, `tomorrow_solar_class` (contract: calendar tomorrow), `target_day_class` (contract: peak-anchored target day), `forecast_outlook.d1_class`, `forecast_outlook.d2_class`, `drain_targets`, `threshold_position`, `next_action_estimate`, `arbitrage_phase`, `hold_depth`.
  - Live Enphase commanded reserve (via `current_commanded_reserve` attr on the same sensor if exposed, or the write-leg reserve number).
  - **Cross-check (drain-fallback branch only):** `current_offpeak_drain_target` MUST equal the drain-target for TODAY's class. `threshold_position` and `next_action_estimate` MUST cite the same class + drain value. Commanded reserve MUST match `max(reserve_soc, current_offpeak_drain_target)` (drain-fallback commands exactly this).
  - **Cross-check (arbitrage tick, informational):** `_threshold_position` at :5689 is not phase-gated and will still narrate the shared-helper drain even on arbitrage ticks — that is expected and NOT a failure. `_next_action_estimate` IS phase-gated and will cite the phase, not drain. Comparing the accessor to the commanded reserve on an arbitrage tick will show mismatch — this is legitimate, not a bug.
- **Secondary read (mostly moot per §"Design-intent authority") at ~10:00 CDT (daylight offset==0):**
  - Same attribute set; expect the accessor to still read today's class. Note explicitly that the floor is unlikely to BIND at this hour because the battery is charging from solar (manual §2.2). This read validates the DISPLAY correctness across the wider offset==0 span; it does NOT prove a $-impact.
- **Discriminating case (per CLAUDE.md corollary):** if today and tomorrow classify identically (~63% of nights per probe), the observation is UNDISCRIMINATING. Wait for a class-disagreement night. Do NOT close the cycle on a same-class night.
- README post-restart validation table lists PASS/FAIL per criterion with observed entity attribute values, per operator-coined 2026-06-05 rule.

Non-goals for live validation:

- Not gating on DP transitioning (separate cycle).
- Not measuring $-value delta (probe already priced the actuarial gain; per-night measurement is noisy and gain is concentrated in a subset of the 37%).

---

## Non-goals (explicit)

- **Arbitrage-gate off-by-one is NOT fixed by this cycle.** Two analogous sites pair `_classify_target_day(now)` (target-day-anchored) with a hardcoded `classify_solar_day_n(2)` (calendar D+2) for the multi-day forecast leg — the same off-by-one this cycle fixes on the drain path:
  - `_recheck_forecast_on_charge_entry` at `energy_battery.py:2454` / `:2458`
  - `_evaluate_forecast_gate` / `_gate_is_open` receiving `target_day_class` at `:2870` and hardcoding `classify_solar_day_n(2)` at `:2878`
  Fixing these means threading offset through the arbitrage path — non-trivial, cost-affecting, deserves its own Tier-3 cycle. **Action:** file a card `ARBITRAGE-GATE-D2-OFFBYONE-1` with these two sites, this planning doc as reference, and the same probe as its measure-before-build. Do NOT bundle into this cycle.
- **Not renaming** the `tomorrow_solar_class` display attribute or `forecast_outlook.d1_class` contract (operator naming decision, out of scope).
- ~~**Not editing** the Energy Coordinator manual~~ — SUPERSEDED by D5's manual-edit sub-item (M-1). Two one-line edits are IN SCOPE.
- **Not fixing** `inclement.py:432` (`_safe_tomorrow_class` → `classify_tomorrow_solar`) — L-1: verified as genuinely calendar-tomorrow (inclement policy is a next-day quantity, not peak-anchored). Framing-D MUST classify this site explicitly to prove exhaustive enumeration.
- **Not threading** `now` through `compose_release_floor` / `current_park_floor` / sensor render (parked; see D4).
- **Not fixing** `classify_solar_day_n` deep-offset (`n >= 3`) degradation (unreachable from drain path, INV-DTDS-5).

---

## Tier 3 review framings

Per CLAUDE.md Tier-3 protocol (four framing-disjoint reviews, one MUST be adversarial-completeness):

- **A — local correctness / arithmetic.** The re-pairing `(d1_offset + 1)`; the guarded fallback in `_resolve_target_day`; the display-vs-trust split of `tomorrow_class`; the hardcoded-40 → `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` swap (implicit via `_drain_target_for` → `_get_offpeak_drain_target`); the narration-helper signature change from `tomorrow_class` to `now`; the shared-helper `_drain_target_for` body (H-1).
- **B — state-machine integrity / byte-identical.** INV-DTDS-1 holds across every reachable offset==1 tick (INCLUDING in-progress-peak reads via `current_park_floor:1773`, M-2 scope); no arbitrage caller of `_classify_target_day` behavior changed; sensor render byte-identical on the D+1 display axis; restart behavior (no timers introduced); the try/except in `_resolve_target_day` does not swallow a bug class that should surface; partial_hold clamp at :5322 still applies AFTER `_drain_target_for` returns; arbitrage/attain/full_hold branches unaffected (they never called the drain path).
- **C — test authority via REAL per-site source mutation.** For each of: (i) accessor `_drain_target_for(now)` call, (ii) emitter drain-fallback branch `_drain_target_for(now)` call, (iii) `_threshold_position` `_drain_target_for` call, (iv) `_next_action_estimate` `_drain_target_for` call, (v) `_resolve_target_day` call inside `_drain_target_for`, **(vi — H-1 6th site) the multi-day max leg inside `_drain_target_for` itself** (mutate to hard-return `d1_target` without max), mutate the production source to bypass the resolver/helper (e.g. hard-return `classify_tomorrow_solar()` at that ONE site, or hard-return `d1_target` from `_drain_target_for` to defeat the max) and confirm a SPECIFIC named test fails, then restore. A site whose bypass leaves the suite green is untested = unacceptable. **All C-tests MUST wire a real / stubbed `_tou`**; `_tou = None` routes to the pre-fix fallback path and is a hollow anchor. Follow `feedback_mutation_verification_pycache_staleness.md` — disable bytecode + clear cache before each drill.
- **D — adversarial completeness.** State INV-DTDS-3 in falsifiable form and BREAK it. Re-enumerate EVERY `classify_tomorrow_solar()` and `self._drain_targets.get(` call **across the whole `custom_components/universal_room_automation/` package, not only `energy_battery.py`** (L-1 widening) — including pre-existing sites the diff does not touch. Classify each: display-attr (must remain `classify_tomorrow_solar`), drain-related trust/narration (must have been swapped to `_drain_target_for`), or genuinely-calendar-tomorrow out-of-scope (e.g. `inclement.py:432` `_safe_tomorrow_class` — inclement policy is a next-day quantity, MUST be explicitly classified as out-of-scope, NOT silently skipped). Produce reachable repros for any leak: a `(now, TOU-state, Solcast state, arbitrage_phase, hold_depth)` tuple that legally produces a divergence between accessor, emitter drain-fallback branch, `_threshold_position`, or `_next_action_estimate`.

**Plus TWO plan reviews before build** per Tier-3 plan-review rule (CLAUDE.md 2026-08-11): (1) completeness re-enumeration of every drain-related consumer of `classify_tomorrow_solar` AND every `_drain_targets.get` open-code across the whole package; (2) adversarial build-prediction — candidate misfires: collapsing display `tomorrow_class` and trust `d1_class`; forgetting `d1_offset + 1` re-pairing; introducing a `now` parameter with a default that changes existing test call sites; open-coding a second `_drain_targets.get()` OR a second `max()` in the helpers instead of routing through `_drain_target_for()` (H-1 mandate — the whole point of the shared helper is that no consumer duplicates its logic); forgetting to import `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` in the helpers (already imported at module level per `:36`, so the risk is a shadow-literal not an import — flag it); phase-gating `_threshold_position` "to match `_next_action_estimate`" (it is pre-existingly unconditional and changing that is out of scope).

---

## What I could NOT verify in this planning session (flag for reviewer)

1. **Every `_result(...)` return in the off-peak branch that interpolates `tomorrow_class`.** I read :5224 and :5332 but did not enumerate every off-peak `_result` call between :5340 and :5900. Plan review must grep them all and decide per-site.
2. **Whether `get_next_high_rate_transition` returns tomorrow's boundary immediately AFTER a peak has begun.** Needs a code read of the TOU engine before the boundary tests are authored. Builder must confirm. Note (M-2): the INV-DTDS-1 in-progress-peak scope claim above ASSUMES it does; if it returns "no transition today, look tomorrow" during an in-progress peak, that IS offset==1 as claimed.
3. ~~**Whether `_get_offpeak_drain_target()` already applies the multi-day max**~~ — RESOLVED (H-1): verified at `:1722-1724`, it is a BARE dict lookup. The multi-day max is OPEN-CODED in the accessor and emitter. `_drain_target_for` (D1b) is mandated as the single source of truth to close this.
4. **`docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md`** — §2.1 (:38-51) and §2.2 (:53-67) read; the rest of §2 not re-read end-to-end. Confirm no other wording drift when applying the D5 M-1 edits.
5. **The TOU-table hours claim** (summer 00-14, shoulder 00-17, winter 00-05 + 09-17) is taken from the orchestrator's cite of the manual — not re-derived from the TOU engine source in this session. If the shoulder/winter split differs, INV-DTDS-5 still holds (the next high-rate transition is <= 1 day away in every reasonable US-utility TOU schedule) but the boundary-test hours may need adjustment.

---

## Fix-up-ready structure

If plan review or Tier-3 review D finds leaks:

- New drain-related site consuming `classify_tomorrow_solar` or open-coding `_drain_targets.get(...)` → add to D3 site list; author a mutation-anchored C-test; re-run D completeness.
- A consumer found open-coding `max(d1, d2)` outside `_drain_target_for` → treat as an H-1 violation; route through `_drain_target_for`; add a mutation-anchored test on the max leg.
- Sensor display attr rename requested → surface to operator as a naming decision; do not silently rename `tomorrow_solar_class`.

Ship gate: mandatory Tier-3 operator checkpoint BEFORE deploy (per CLAUDE.md), surfacing the review outcome + invariant proof + the "discriminating live check requires a class-disagreement night AND a small-hours read AND arbitrage_phase ∈ {n/a, WAIT} AND hold_depth == allow_discharge" caveat.
