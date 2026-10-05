# PLANNING — EC-SOC-LADDER-FULL-WIRING-1: route the 3 unconsumed SOC-ladder invariants through safe seams

**Card:** EC-SOC-LADDER-FULL-WIRING-1 (`docs/planning/kanban.data.yaml:2726`)
**Parent:** EC-SOC-LADDER-XVALIDATE-1 (shipped v5.103.6, consumed half #4/#5)
**Written:** 2026-10-02 by ura-planner. **No code edited.**
**Recommended tier:** **Tier 3** (see §8). Plan review: TWO framing-disjoint plan reviews before build.
**TOU context at writing:** shoulder season (Oct, `energy_const.py:36-50`) — `off_peak` 0-17 & 21-24, `mid_peak` 17-21, **no `peak` period**.

---

## 0. TL;DR — the card's "~25 site migration" framing is wrong; the real shape is 3 seams + 1 raw-vs-effective split

Re-enumeration (greps re-run, not harvested) shows:

| Invariant | Raw decision readers | Real seam count | Reachable today by a legal write? | Severity |
|---|---|---|---|---|
| #1 drain monotone + `reserve <= excellent` | **1** — `_get_offpeak_drain_target` (`energy_battery.py:1874-1876`); everything else (emitter, DP stamp, park floor, pool, status) flows through `_drain_target_for` → that line | **1** | **YES** — drain Number min is 5 (`number.py:71-77`), `reserve_soc` default 10 (`energy_const.py:181`) → drain_excellent=5 emits Enphase reserve **5% < reserve 10%** at `energy_battery.py:5701` | **SAFETY** (sub-reserve write) |
| #2 `peak_buffer_target > max(poor, very_poor)` | ~24 reads of `self._peak_buffer_target` in `energy_battery.py` + 1 log in `energy.py:3424` | **1 if done as a property** (§D2) | **YES** — peak buffer Number 30-95 (`number.py:81`), drain poor/very_poor 5-80 → peak=40, poor=50 legal | **COST** (arbitrage holds/charges to less than the non-arbitrage drain path) |
| #6 `inclement_partial_hold_reserve_floor >= reserve` | emission already clamped (`inclement.py:730-732` `_partial_floor_value = max(reserve, floor)`); **one** raw reader left: `inclement.py:368` `permitted_discharge_pct` | **1** | **Low** — both values are options-flow (constructor/options) and saved together under the save-time reject (`config_flow.py:4729,4949`); reachable only via pre-validator legacy options or hand-edit. Live: floor 50 / reserve 10 (healthy) | **SAFETY-adjacent** (overstates permitted discharge → can pick partial over full hold) |

So: #1 and #6 are single-line seams; #2 has many readers but **all live in one class, read one attribute, inside one synchronous method** (`determine_mode`, `energy_battery.py:4924`, plain `def`). Converting `_peak_buffer_target` into a **read-clamped property with a raw backing field** makes all ~24 readers consume the safe value with zero per-site edits — and it makes "one missed site" structurally impossible, which is exactly what the prior residual failed at.

The **one real trap** this design introduces (and the one the build will most likely get wrong): the three validator/anomaly readers MUST read the RAW value, otherwise the clamp masks the violation and `threshold_ladder_violation` never fires again (detect-and-swallow). That is invariant I-2 below and gets its own mutation anchor.

---

## 1. Institutional context verified

### 1.1 Prior planning / review history consulted
- `docs/planning/PLANNING_ec_soc_ladder_xvalidate.md` (full read) — parent plan. Its D1 proposed clamping all 6 invariants inside `EnergyCoordinator.safely_ordered_ladder()`; its D2 table listed only ~8 sites in energy.py/energy_pool.py and **never enumerated the BatteryStrategy readers**. That is the under-scope that failed review.
- Card history `kanban.data.yaml:24661-24708` — `REVIEWS_AC_2026_09_16`, `REVIEW_B_2026_09_16`, `FIXUP_DONE_2026_09_16`. Findings harvested:
  - **C-HIGH**: newly-clamped #1/#2/#6 had **zero consumers** (Bug Class #53 dead clamp) + the diff **deleted the Bug-Class-53 warning and added a false "inversions impossible" docstring**.
  - **A-MED-1**: peak_buffer clamp could emit >100 → needs `min(100, …)`.
  - **A-MED-2 / B-MED-2**: drain accessor **dropped the reachable `"unknown"` class** (shape divergence).
  - **B-HIGH-1 / C4 / C5**: **hollow anchors** — tests mirrored the readout instead of invoking production; per-site neuter left 4/5 sites GREEN.
  - **Process miss owned**: build dispatched without a Tier-2-DB plan review.
  - C also hit the `python3`-vs-`.venv-ha` harness trap.
- **Review records were NOT persisted** under `docs/reviews/code-review/` for v5.103.6 (grep for `ladder|XVALIDATE|safely_ordered_ladder` there returns no XVALIDATE file). Lessons above are harvested from the card. This cycle MUST write `docs/reviews/code-review/v<ver>_ec_soc_ladder_full_wiring.md` (CLAUDE.md Post-Review Documentation).
- `docs/readmes/README_v5.103.6.md` — deferred-scope statement; confirms #1/#2/#6 are detect-only today.
- `docs/reviews/code-review/arbitrage_solar_attainability_ladder.md` — filename-match only (the rung "ladder" is a different concept; not consulted further).

### 1.2 Design docs read
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.1-2.4b (lines 36-185): drain target is peak-anchored; arbitrage grid-charges to `peak_buffer_target` then completed-chunk HOLD (v5.17.1, I-AH1); §2.4b audit lists "no runtime clamp yet between fill_priority/excess_solar/drain targets" as a known follow-up (`:180-184`) — this cycle closes the drain half; update that bullet.
- HVAC state-of-play: not applicable (no HVAC surface).

### 1.3 Memory bodies relevant (from index; applied)
`feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`, `feedback_unrestored_mutation_drill_poisons_evidence`, `feedback_mutation_verification_pycache_staleness`, `feedback_coincidental_equality_masks_concept_split` (Bug Class #63: very_poor==poor default), `feedback_tier2db_for_regression_prone`, `feedback_marginal_benefit_pushback`, `project_inclement_arbitrage_wait_floor_gap` (v5.5.3 Tier-3 floor — `_floor_reserve` sites), `feedback_serialise_suite_runs_across_agents`.

### 1.4 Code surveyed (read, not trusted)
- `energy.py:9237-9460` — `offpeak_drain_targets`, `_check_threshold_ladder`, `safely_ordered_ladder` (#4/#5 only, honest docstring at :9343-9373), `set_offpeak_drain`, `arbitrage_target`/`peak_buffer_target` properties, `set_peak_buffer_target` (writes `_peak_buffer_target` AND `_arbitrage_target`).
- `energy_battery.py:325-360` (`compute_release_floor` park → `current_offpeak_drain_target`), `:505-551` (ctor: `_drain_targets` incl. `"unknown"`, `_peak_buffer_target`), `:1842-1980` (classify, `_get_offpeak_drain_target`, `_drain_target_for`, `current_offpeak_drain_target`), `:2101-2275` (`_inclement_config`, `_inclement_decision` → `InclementFusion`), `:2633-2721` (`_resolve_target_day`), `:2870-2935` (rung), `:3230-3255` (arbitrage phase), `:3369-3460` (`_floor_reserve`, arbitrage HOLD/CHARGE emission), `:3912-4103` (attain boundary, `_midpeak_rate_lt_peak`, `_should_attain_peak_buffer`), `:4395-4422`, `:4600-4630`, `:4900-4914`, `:5350-5370`, `:5495-5565`, `:5600-5726` (drain-fallback emission), `:5728-5790` (`_result` clamps only `[0,100]`), `:6240-6270` (`get_status` validator call).
- `inclement.py:326-384` (`compute_solar_horizon`), `:551-560`, `:600-735` (fusion; `_partial_floor_value`).
- `energy_write_verify.py:1451-1473` (`_inclement_partial_hold_floor` reads the already-clamped `decision.reserve_floor` — not a raw reader).
- `energy_tou.py:645-687` (`get_next_high_rate_transition` returns mid_peak OR peak), `energy_const.py:36-50` (shoulder table), `:181,525,790-830` (defaults), `:1156-1326` (validator + canonical doc).
- `number.py:71-81` (Number ranges), `:1327-1530` (OffPeakDrain/PeakBuffer Numbers; options write-back, no RestoreEntity).
- Live config (`/Users/okosisi/ha-config/.storage/core.config_entries:375`): reserve 10, drains 10/15/20/30/30, peak_buffer 80, inclement floor 50, arbitrage ON, multi-day horizon ON → **healthy ladder; every clamp below is identity on live config** (note `excellent == reserve == 10` — boundary equality must stay identity).

### 1.5 REUSE-or-BUILD per proposed piece
| Piece | Verdict | Cite |
|---|---|---|
| Cross-field validator (all 6) | **REUSED, unchanged** | `energy_const.py:1156-1306` |
| Save-time reject | **REUSED, unchanged** | `config_flow.py:4729,4949` |
| Runtime anomaly `threshold_ladder_violation` | **REUSED; inputs re-pointed to RAW fields** | `energy.py:9242-9341` |
| Drain-target single seam | **REUSED — `_get_offpeak_drain_target` is already the documented single source** (`_drain_target_for` docstring :1882-1888 forbids open-coded lookups) — EXTEND with clamp | `energy_battery.py:1874-1876` |
| Peak-buffer seam | **NEW (small)**: property `_peak_buffer_target` over raw field `_peak_buffer_target_raw` on `BatteryStrategy`. Nothing equivalent exists; EC-level `safely_ordered_ladder()` is unreachable from BatteryStrategy and would require ~24 edits | — |
| Inclement floor seam | **REUSED pattern** — `InclementFusion._partial_floor_value` (`inclement.py:730`) already does `max(reserve, floor)`; pass that into `compute_solar_horizon` | `inclement.py:666` |
| `safely_ordered_ladder()` | **NOT extended** — stays #4/#5 (EC-level EV-band knobs). Docstring updated to point at the battery-side seams for #1/#2/#6 (do NOT claim "inversions impossible") | `energy.py:9343` |
| `_arbitrage_target` alias | **Supersession triage: KEEP + DOCUMENT** — write-only in production (only writer `energy.py:9458`, zero production readers); one test fixture sets it (`test_part2_ec_hc_writeback.py:1086`). Add a one-line comment; do not delete this cycle (deletion is not needed for the invariant and only one-way) | `energy.py:9458` |
| New knobs | **NONE** — see §5 | — |

### 1.6 Config-first check
No setting solves this: the hazard is precisely that the existing Numbers can legally be set to an inverted combination. Live config is healthy, so there is **no urgency** — this is defence-in-depth against a future slider move, plus one real safety leak (#1 drain < reserve) that is legal on today's Number bounds. An alternative config-only mitigation (raise drain Number `min` to 10) was considered and rejected: `reserve_soc` is operator-set in the options flow, so a static Number min cannot track it.

---

## 2. Producer and Consumer checks

### 2.1 PRODUCERS
- **Drain targets**: ctor seed from options (`energy.py:202` → `energy_battery.py:520-531`, incl. `unknown` default 40, no Number for unknown) + runtime `set_offpeak_drain` (`energy.py:9397-9405`, from `OffPeakDrainNumber` `number.py:1416-1453`). Mutated in place on `_drain_targets[quality]`.
- **peak_buffer_target**: ctor (`energy_battery.py:538-541`) + `set_peak_buffer_target` (`energy.py:9453-9460`, from `PeakBufferTargetNumber` and from `__init__.py:6815` options write-back map).
- **reserve_soc**: ctor only (`energy_battery.py:405`); no runtime setter anywhere (`grep '\.reserve_soc\s*='` → single hit). Changes only via options-flow → reload.
- **inclement floor**: options only, re-read every tick via `_inclement_config()` (`energy_battery.py:2167`).
- Dependency health: all healthy on live config (§1.4).

### 2.2 CONSUMERS — exhaustive enumeration (re-run greps: `_peak_buffer_target`, `_drain_targets`, `_get_offpeak_drain_target`, `_drain_target_for`, `current_offpeak_drain_target`, `_offpeak_drain_branch_target`, `partial_hold_reserve_floor`, `_partial_floor`, `\.peak_buffer_target\b`, `\.arbitrage_target\b`, `offpeak_drain_targets\b` across `custom_components/`)

Legend: **D** = decision gate, **E** = actuation emission (reserve / charge_from_grid written to Enphase), **N** = narration/log/status, **V** = validator/anomaly input (MUST stay RAW).

**#2 peak_buffer_target — all in `energy_battery.py` unless noted**

| # | file:line | Kind | What |
|---|---|---|---|
| P1 | 2882 | D | rung: None guard |
| P2 | 2893 | D | rung: `soc >= target` → rung_2 |
| P3 | 2929 | D | rung entry/exit bands from target |
| P4 | 3247 | D | arbitrage phase HOLD predicate |
| P5 | 3419, 3423, 3427 | E+N | arbitrage HOLD `_floor_reserve(target)` → `reserve_level`; suffix compare; reason |
| P6 | 3442, 3446, 3450 | E+N | arbitrage CHARGE emission (charge_from_grid=True) |
| P7 | 4039, 4041 | D | attain entry: None guard, `soc >= target` |
| P8 | 4101 | D | attain entry: `projected < target` |
| P9 | 4170 | E | attain CHARGE `target = …` |
| P10 | 4192, 4194 | E+N | attain `_floor_reserve(target)` + suffix |
| P11 | 4239, 4243 | N | attain hold reason |
| P12 | 4246, 4248 | E+N | attain HOLD `_floor_reserve(target)` + suffix |
| P13 | 4406-4407, 4416-4417 | D | attain restart adoption holding/charging |
| P14 | 4616-4617, 4622 | D+N | attain charging→holding transition |
| P15 | 4910 | N | attain-entered log |
| P16 | 5360-5362 | D | summer mid_peak attain continuation gate (`season == "summer"` — **dormant in shoulder**) |
| P17 | 5501, 5525 | D | completed-chunk HOLD None guards |
| P18 | 5549, 5555 | E+N | completed-chunk HOLD `_floor_reserve(target)` (v5.17.1 I-AH1 site) |
| P19 | 5628 | N | rung_0/1 drain-fallback suffix |
| P20 | 6062, 6065, 6091, 6096, 6100 | D(display)+N | `_threshold_position` / next-action strings |
| P21 | 6377, 6378 | N | `get_status` `arbitrage_target` / `peak_buffer_target` attrs → **must expose BOTH effective and raw** (new attr `peak_buffer_target_operator`) |
| P22 | `energy.py:3424` | N | arbitrage-cycle-start log |
| **V1** | 6265 | **V** | `get_status` `validate_threshold_ladder(peak_buffer_target=…)` → **RAW** |
| **V2** | `energy.py:9272` | **V** | `_check_threshold_ladder` → **RAW** |
| **V3** | `energy.py:9317` | **V** | anomaly payload → **RAW** (plus optionally effective) |
| R1 | `energy.py:9437, 9451` | API | `arbitrage_target` / `peak_buffer_target` properties — **decision: return RAW** (they back the operator-facing Number round-trip semantics; no production decision consumer — grep `\.peak_buffer_target\b` / `\.arbitrage_target\b` returns zero callers). Add `effective_peak_buffer_target` property for display. |
| W1 | `energy.py:9456, 9458` | writer | setter → writes raw (via property setter) |
| W2 | `energy_battery.py:538` | writer | ctor → raw |

**#1 drain targets**

| # | file:line | Kind | What |
|---|---|---|---|
| D-seam | 1876 | D | `_get_offpeak_drain_target(cls)` — **THE seam**; clamp here |
| via seam | 1897, 1911 | D | `_drain_target_for` d1/d2 + multi-day max |
| via seam | 1932, 1945, 1977 | D/N | `current_offpeak_drain_target`, `_safe_…`, park fallback |
| via seam | 352 (`compute_release_floor`) | D | EV/plug drain-release floor |
| via seam | 5655 → 5684 → `energy.py:5912` | E+D | drain-fallback target → DP value stamp → DP tick |
| via seam | 5701 | **E** | `reserve_level=drain_target` — the sub-reserve leak site |
| direct (OK) | 5662-5663 | N | display class bump compares two `_get_offpeak_drain_target` calls — both through seam |
| via seam | `energy_pool.py:2234,3920` (threaded param from caller) | D | pool drain consumers receive the seam output |
| **V4** | 6263 | **V** | `get_status` validator → RAW dict |
| **V5** | `energy.py:9270, 9316` | **V** | `_check_threshold_ladder` + payload → RAW dict |
| N | 6428 | N | `get_status` `drain_targets` → RAW dict (operator values); add `drain_targets_effective` |
| N | `energy.py:9240` | API | `offpeak_drain_targets` property → RAW (no production consumer besides display) |

**#6 inclement floor**

| # | file:line | Kind | What |
|---|---|---|---|
| I-seam | `inclement.py:368` | D | `permitted_discharge_pct = max(0, soc - partial_hold_reserve_floor)` — **raw**; fed from `inclement.py:666` `partial_hold_reserve_floor=self._partial_floor` |
| already safe | `inclement.py:626, 677, 704` | E | `_partial_floor_value()` = `max(reserve, floor)` |
| already safe | `energy_write_verify.py:1534, 1739` | D | read `decision.reserve_floor` (post-clamp) |
| already safe | `energy_battery.py:5674, 5714` | E | `max(drain_target, effective_reserve)` |
| **V6** | `energy.py:9265, 9276, 9315` | **V** | validator/anomaly → RAW `_inclement_config()` value |

---

## 3. Falsifiable invariants (state before build — Reviewer D breaks these)

- **I-1 (consumption).** For ANY legal combination of `{reserve_soc ∈ options range, drain_{excellent..very_poor} ∈ [5,80], drain_unknown (options), peak_buffer ∈ [30,95], inclement_floor (options)}` and ANY TOU season (summer / shoulder-no-peak / winter), **no reserve_level emitted by `BatteryStrategy.determine_mode` on the off-peak drain-fallback DRAIN leg (`soc > drain_target`, `energy_battery.py:5686-5701`) is < `reserve_soc`, and the DP value stamp `_offpeak_drain_branch_target` (`:5684`) is never < `reserve_soc`** (scope note, plan review 2026-10-02: the HOLD leg `:5707-5726` emits `hold_reserve = int(soc)` — hold-at-current-SOC — which is < `reserve_soc` whenever SOC already sits below reserve, e.g. after an options reserve raise 10→20 at SOC 12. That is pre-existing, not a drain below reserve (it stops discharge), and is OUT of this cycle's scope; Reviewer D must not count it as an I-1 leak, but the builder must not "fix" it either — raising it to reserve would turn the hold into a grid-charge target), **no decision gate in §2.2 compares SOC against a peak-buffer value ≤ `max(eff_poor, eff_very_poor)`**, and **the inclement recoverability math never uses a floor < `reserve_soc`**.
  Falsify with: a legal Number write sequence + season + SOC where one enumerated D/E site reads the raw value and the action differs from the clamped one.
- **I-2 (detection not swallowed).** For every inverted combination in I-1, `_check_threshold_ladder` still returns a violation code and emits `threshold_ladder_violation` (rate-limited) — i.e. the clamp is **detect-AND-clamp**, never detect-and-swallow. Falsify with: any inversion for which `validate_threshold_ladder` is fed an already-clamped value.
- **I-3 (identity on healthy ladder).** On any ladder that passes `validate_threshold_ladder`, every effective value equals its raw value bit-for-bit (incl. boundary equalities `excellent == reserve`, `poor == very_poor`). Falsify with: a valid ladder where any D/E site's input changes.
- **I-4 (per-tick coherence).** Within one `determine_mode` call, every #2 reader observes the same effective peak-buffer value (no gate/emission split such as "gate says HOLD at raw 40, emission locks reserve at clamped 51").

---

## 4. Deliverables

### D0 — Measure-before-build (one-shot, read-only, ~10 min)
Query the URA DB `anomaly_log` (and `ura_activity_log`) for any `threshold_ladder_violation` ever, and the recorder history of `number.*offpeak_drain_*` / `number.*peak_buffer_target` for any value ever set that violates I-1. Purpose: confirm whether the inversion has ever occurred live (expected: none since 09-16 per card disposition `kanban.data.yaml:24662`). **Gate:** the result does not cancel D1 (the #1 sub-reserve leak is legal on current Number bounds), but it bounds urgency and feeds the Tier decision checkpoint.

**Acceptance**
- **Verify:** probe output recorded in this doc's §9 with row counts and the max/min values ever written per Number.

### D1 — Drain-target seam clamp (#1)
At `energy_battery.py:1874-1876`, `_get_offpeak_drain_target(cls)` returns the **effective** target:
1. Build effective chain over the five ordered classes `excellent → good → moderate → poor → very_poor`: `eff[c] = max(reserve_soc, raw[c], eff[prev])` (cumulative max anchored at reserve; raises only, never lowers).
2. `unknown` (and any class not in the five, e.g. a stray key): `max(reserve_soc, raw.get(cls, DEFAULT_OFFPEAK_DRAIN_UNKNOWN))` — **floored at reserve, NOT monotonised, NOT dropped** (A-MED-2 lesson; `unknown` is a sentinel the validator does not order).
3. Cap at 100.
4. Helper: new private `BatteryStrategy._effective_drain_targets() -> dict[str,int]` returning all six keys (used by the seam and by `get_status` `drain_targets_effective`). `_drain_targets` dict stays RAW (validator input V4/V5 and `set_offpeak_drain` unchanged).

Does NOT collapse a coincidental `poor == very_poor` (identity) and does NOT pull `very_poor` down (Bug Class #63).

**Acceptance**
- **Test (enclosing-method behavioural anchor):** `reserve=10, excellent=5`, tomorrow class `excellent`, off_peak, SOC 50 → `determine_mode` emits `reserve_level == 10` (raw would be 5). Neuter drill: revert the seam to `self._drain_targets.get(...)` → this named test goes RED.
- **Test:** `poor=50, very_poor=30` (very_poor below poor), class very_poor → emitted drain-fallback `reserve_level == 50` at SOC 60; and `_offpeak_drain_branch_target == 50` (DP stamp path).
- **Test:** multi-day horizon ON, d1=`good`(raw 60) d2=`moderate`(raw 20): effective moderate = 60 → `_drain_target_for == 60`.
- **Test:** `unknown` raw 5, reserve 10 → effective 10; `unknown` raw 40 with poor 80 → effective 40 (not monotonised).
- **Test:** `compute_release_floor` off_peak with no park yet → returns `max(reserve, effective)`; plus pool consumer receives the effective value (one pool-path anchor through the real caller, not a re-implementation).
- **Test (I-3):** live config (10/15/20/30/30, reserve 10) → `_effective_drain_targets() == raw` including `unknown`.
- **Live:** `sensor.ura_energy_coordinator_battery_strategy` attr `drain_targets_effective` == `drain_targets` on the healthy live ladder.

### D2 — Peak-buffer property seam (#2)
On `BatteryStrategy`:
- Rename the storage to `self._peak_buffer_target_raw` (ctor `:538`).
- Add `@property _peak_buffer_target` → `None` if raw is None, else `min(100, max(raw, top + 1))` where `top = max(eff["poor"], eff["very_poor"])` from `_effective_drain_targets()` **only when `raw <= top`**; else raw (identity). Strict `>` mirrors validator invariant #2.
- Add `@_peak_buffer_target.setter` → writes `_peak_buffer_target_raw` (keeps the 19 test-fixture assignments and `set_peak_buffer_target` working unchanged).
- Add public `effective_peak_buffer_target` / `peak_buffer_target_operator` read-only properties for display.
- **Re-point V1/V2/V3 to `_peak_buffer_target_raw`** (`energy_battery.py:6265`, `energy.py:9272, 9317`). This is the single most important edit in the cycle (I-2).
- `get_status` (`:6377-6378`): `peak_buffer_target` = effective (what the strategy acts on), new `peak_buffer_target_operator` = raw. Keep `arbitrage_target` = effective (alias).
- `energy.py` `arbitrage_target` / `peak_buffer_target` properties (`:9437, 9451`): return RAW (operator value; zero production decision consumers) — document why.
- `_arbitrage_target` (`energy.py:9458`): KEEP + one-line "write-only alias, no readers" comment.

**Why a property and not ~24 call-site edits:** all readers are in one class and one sync call stack; a property makes I-4 hold by construction (drains cannot change mid-`determine_mode` because Number setters run on the event loop between ticks and `determine_mode` is a plain `def`, `:4924`). Per-site edits would re-create the exact "one missed site" failure mode this card exists to close. Reviewers: this is deliberately "magic"; the docstring must say so and point here.

**Acceptance**
- **Test (emission, arbitrage HOLD P5):** drains poor=very_poor=50, peak raw=40, target-day `poor`, arbitrage ON, SOC 52, charge window open → phase HOLD? No: effective peak = 51 → SOC 52 ≥ 51 → HOLD with `reserve_level == 51`. Raw path would give HOLD at 40. Neuter drill: make the property return raw → RED.
- **Test (gate, P4 + P6 CHARGE):** same config, SOC 45 → CHARGE (charge_from_grid True) to 51; raw path → HOLD at 40 (45 ≥ 40). Discriminating: action differs (grid charge vs none).
- **Test (attain entry P7/P8):** SOC 45, projected 48 → attain enters (48 < 51); raw → does not (45 ≥ 40 short-circuit).
- **Test (completed-chunk HOLD P18, v5.17.1 I-AH1 site):** chunk completed, boundary ahead → `reserve_level == 51`.
- **Test (rung P2/P3):** `_arbitrage_rung` returns non-rung_2 at SOC 45 (raw short-circuits to rung_2).
- **Test (I-2, MANDATORY, the anti-swallow anchor):** with peak raw 40 / poor 50, `_check_threshold_ladder()` emits code for invariant #2 and the anomaly payload `peak_buffer_target == 40`. Mutation drill: point V2 at the property → this test RED. Same for `get_status()["threshold_warning"]` (V1).
- **Test (>100 / A-MED-1):** poor=very_poor=100 (via direct attr; beyond Number max but reachable via options/legacy) → effective 100, never 101.
- **Test (I-3):** live config peak 80, drains top 30 → effective 80 == raw; `poor==very_poor==30`, peak 31 → 31 (strict boundary identity).
- **Test (fixture compatibility):** `test_battery_inclement_arbitrage_floor.py:548-580` set `_peak_buffer_target = 30` with default drains poor=very_poor=30 — **these become clamped to 31**. Builder must NOT silently update expected values; for each affected test decide: (a) the test intends a legal ladder → set drains below 30 explicitly in the fixture so the test keeps exercising its original subject (the v5.5.3 floor), or (b) assert the new clamped behaviour. Record each decision in the review doc. Name-diff must show these as intentional.
- **Live:** strategy sensor `peak_buffer_target == peak_buffer_target_operator == 80`.

### D3 — Inclement recoverability floor (#6)
`inclement.py:666`: pass `partial_hold_reserve_floor=self._partial_floor_value(current_soc)` (existing method, `inclement.py:730-732`, = `max(self._reserve_soc, self._partial_floor)`; do not add a second formula or a new helper). `compute_solar_horizon` signature unchanged.

**Acceptance**
- **Test:** `InclementFusion(reserve_soc=20, partial_hold_reserve_floor=10)`, mid_peak watch-corroborated, SOC 60 → `solar_horizon.permitted_discharge_pct == 40` (not 50). Discriminating case: pick surplus such that 40+margin < surplus < 50+margin flips `recoverable` → assert hold_depth differs from raw path (partial vs full). Neuter drill → RED.
- **Test (I-3):** floor 50, reserve 10 → unchanged.
- **Live:** none needed beyond no-regression (hold_depth `allow_discharge` on clear weather).

### D4 — Docstrings + manual + no false claims
- `safely_ordered_ladder()` docstring (`energy.py:9343-9373`): keep #4/#5 scope; replace "Full wiring of #1/#2/#6 is tracked as a separate cycle" with pointers to the three battery/inclement seams. **Must not state inversions are impossible** — they remain possible in operator values; consumers act on clamped values and the anomaly still fires.
- `CANONICAL_SOC_LADDER_DOC` neighbourhood (`energy_const.py:1309-1326`): add "enforcement: #1 seam `_get_offpeak_drain_target`, #2 property `_peak_buffer_target`, #4/#5 `safely_ordered_ladder`, #6 `_partial_floor_value` + recoverability; #3 detect-only (no consumer)".
- `ENERGY_COORDINATOR_MANUAL.md:180-184` follow-up bullet: update; add the new status attrs to §5 table (`:336`).

**Acceptance**
- **Verify:** reviewer greps the diff for "impossible" / "cannot be inverted" → zero.

### D5 — Test-authority drill (Tier-3 Reviewer C input, also run by orchestrator)
Per-site source mutation under `.venv-ha` with `PYTHONDONTWRITEBYTECODE=1` + `__pycache__` cleared:
1. D1 seam → raw lookup: ≥1 named test RED.
2. D2 property → returns raw: ≥1 named test per site class RED — specifically P4/P5 (arbitrage), P7/P8 (attain), P18 (completed chunk), P2 (rung).
3. V1, V2 each → property (effective): I-2 test RED.
4. D3 → raw `self._partial_floor`: RED.
5. Restore + `git status` clean after each.

### Non-goals
- No new CONF_*, Number, Select, Switch, sensor entity. Two new **attributes** on the existing strategy sensor only (`drain_targets_effective`, `peak_buffer_target_operator`).
- Invariant #3 (`arbitrage_trigger`) stays detect-only — field removed in v4.5.0 (`energy_battery.py:533-535`), no consumer.
- No change to `safely_ordered_ladder()` clamps (#4/#5), the save-time reject, or the anomaly rate-limit.
- No write-back of clamped values into options / Numbers (the operator's value stays what they set; the strategy acts on effective). Rejected alternative: clamping in the Number setter — stale as soon as the *other* knob moves.
- `_arbitrage_target` not deleted.

---

## 5. Knobs on the ladder
**No new behavioural numbers.** The clamp offsets are structural, not tunable:
- `+1` in the peak-buffer clamp — **rung 1 (inline is acceptable only because it is the literal encoding of the validator's strict `>`); name it `PEAK_BUFFER_ABOVE_TOP_DRAIN_MIN_GAP_PCT: Final = 1` in `energy_const.py` next to the validator** so the two cannot drift. Not operator-tunable: changing it changes the meaning of invariant #2 and must be reviewed.
- `min(100, …)` cap — physical bound, not a knob.
- Existing knobs consumed, unchanged rungs: drain Numbers (rung 3), peak buffer Number (rung 3), reserve_soc (rung 2 options), inclement floor (rung 2 options).

---

## 6. Season behaviour (shoulder = no peak, mid_peak 17-21)
Checked against code:
- `get_next_high_rate_transition` returns the **mid_peak** 17:00 transition in shoulder (`energy_tou.py:683-684`). So drain targets (via `_resolve_target_day`), arbitrage phase, charge window, rung, and off_peak attain all **target the mid_peak boundary** — #1 and #2 are fully LIVE in shoulder. The `peak_buffer_target` is effectively the mid-peak buffer.
- `_midpeak_rate_lt_peak` returns False (no `peak` rate) → mid_peak attain entry (P7 via `_should_attain_peak_buffer` mid_peak leg) and the summer continuation P16 are **dormant** in shoulder. Restart adoption P13 `in_midpeak_window` also False.
- Inclement: `compute_solar_horizon` short-circuits off_peak; D3 matters only during shoulder mid_peak 17-21 — still live.
- Winter (two high-rate windows) and summer (peak 16-20 + mid_peak brackets) exercise P16 and the mid_peak attain legs.

**Acceptance (season matrix)** — the D1/D2 discriminating tests are parametrised over a TOU stub for `summer`, `shoulder` (no peak), `winter`: each asserts the clamped action at an off_peak tick before the next high-rate transition. Additionally one shoulder test at 17:30 (mid_peak) asserting attain does NOT enter regardless of clamp (no-peak dormancy preserved — I-3 for the dormant path).

---

## 7. Config-extreme combinatorics (Tier-3 requirement — test the invariant at extremes and inversions)
Parametrised matrix over the enclosing `determine_mode` (not helpers), each row asserting I-1 + I-2 + (where valid) I-3:

| Case | reserve | exc/good/mod/poor/vpoor | unknown | peak | inc floor | Expect |
|---|---|---|---|---|---|---|
| X1 live healthy | 10 | 10/15/20/30/30 | 40 | 80 | 50 | identity everywhere, no anomaly |
| X2 drain below reserve | 20 | 5/5/5/5/5 | 40 | 80 | 50 | all drains eff 20; emission ≥20; anomaly |
| X3 fully inverted drains | 10 | 80/60/40/20/5 | 40 | 95 | 50 | eff all 80; peak 95 ok (95 > 80); anomaly #1 |
| X4 peak at Number min, drains at max | 10 | 10/15/20/80/80 | 40 | 30 | 50 | peak eff 81; anomaly #2 |
| X5 peak == top drain (strict boundary) | 10 | 10/15/20/30/30 | 40 | 30 | 50 | peak eff 31; anomaly #2 |
| X6 very_poor < poor (concept split) | 10 | 10/15/20/50/30 | 40 | 80 | 50 | vpoor eff 50; poor unchanged; anomaly #1 |
| X7 coincidental equality | 10 | 10/15/20/30/30 | 40 | 31 | 50 | identity (31 > 30) |
| X8 >100 guard | 10 | 100/100/100/100/100 (direct attr) | 40 | 95 | 50 | peak eff 100 |
| X9 inclement inverted | 30 | 30/30/40/50/50 | 40 | 80 | 10 | recoverability uses 30; anomaly #6 |
| X10 unknown below reserve | 20 | 20/25/30/40/40 | 5 | 80 | 50 | unknown eff 20 |
| X11 everything inverted at once | 20 | 25/20/30/30/25 + vpoor<poor | 5 | 28 | 15 | each site reads clamped; one anomaly per code (rate-limit per code) |

× seasons {summer, shoulder, winter} for X2, X4, X6 (the reachable-by-Number cases).

---

## 8. Tier verdict: **Tier 3**
It meets three CLAUDE.md Tier-3 triggers:
1. It threads a clamp through a **state machine with many decision/emission sites** (arbitrage WAIT/CHARGE/HOLD, attain latch, completed-chunk HOLD, rung) — the failure mode is one missed site (Bug Class #53). The property design mitigates this structurally but introduces the inverse risk (validator reading effective → swallowed detection).
2. It is **cost-AND-safety impacting**: changes `reserve_level` written to Enphase and whether grid charging fires (D2), and fixes a reachable sub-reserve write (D1). It touches the same `_floor_reserve` sites as the v5.5.3 Tier-3 arbitrage-WAIT floor fix and the v5.17.1 I-AH1 HOLD contract.
3. History: the predecessor residual failed 3/3 reviews on exactly this scope; the arbitrage/attain area has a multi-fix-up record.

Therefore: **two framing-disjoint plan reviews** (completeness re-enumeration; adversarial build-prediction), build by **ura-super-builder**, **four review framings** (A local arithmetic incl. boundaries/unknown/>100; B state-machine integrity + byte-identical healthy path + restart (raw field survives reload via options seed); C per-site real source mutation per D5; D adversarial completeness diff-blind against I-1..I-4 incl. pre-existing code), orchestrator independent re-grep + mutation re-run, **operator checkpoint before deploy**, live validation, README write-back, review record in `docs/reviews/code-review/`.

**Marginal-benefit note for the operator (pushback, per CLAUDE.md):** D1 (safety, 1 seam) and D3 (1 line) are cheap and clearly worth it. D2 is the expensive part (Tier-3 ceremony for a cost-only hazard that has never occurred live and that the save-time reject + anomaly already surface). If the operator prefers, a defensible split is: **ship D1+D3+D4 as Tier 2-DB now** (they don't touch the arbitrage state machine; D1 does touch the drain-fallback emission, so keep 3 reviews), and **keep #2 detect-only** with the D2 design parked here, revival trigger = any `threshold_ladder_violation` with code for invariant #2 in `anomaly_log`. The planner's recommendation is the split; full Tier-3 D2 only if the operator wants #2 closed now.

---

## 9. Measurement results (D0)
Run 2026-10-02 (~21:10 local), read-only, via `ssh ha "python3 -"` (`?mode=ro`). Note: the Samba-mounted URA DB could not be opened `mode=ro` from the Mac (WAL `-shm` over SMB), so both DBs were read on-host.

**URA DB** (`/config/universal_room_automation/data/universal_room_automation.db`):
- `anomaly_log`: 48,437 rows, span 2026-05-15 → 2026-10-03T02:09Z. Rows with `ladder` in `metric_name` / `anomaly_type` / `context_json`: **0**. The emitter (`energy.py:9320-9328`, `type="threshold_ladder_violation"` → `db.save_anomaly_event`) has therefore **never persisted a violation** since it shipped (v5.103.6, 2026-09-16).
- `ura_activity_log`: 0 rows mentioning `threshold_ladder`. (The 688/1054 `ladder` substring hits are all HVAC `S1_reason_ladder` preset writes — unrelated.)
- Full-table sweep for `%ladder%` across every column of every table: only the HVAC hits above.

**Recorder** (`/config/home-assistant_v2.db`, `states`; span ≈ 7.7 days, 2026-09-25 → 2026-10-03) — distinct non-`unavailable` values ever recorded:

| Entity | Values |
|---|---|
| `number.ura_energy_coordinator_off_peak_drain_excellent` | 10.0 only |
| `…_off_peak_drain_good` | 15.0 only |
| `…_off_peak_drain_moderate` | 20.0 only |
| `…_off_peak_drain_poor` | 30.0 only |
| `…_off_peak_drain_very_poor` | 30.0 only |
| `number.ura_energy_coordinator_peak_buffer_target` | 80 only |
| `number.enpower_…_reserve_battery_level` | 10.0 only |
| inclement partial floor | no Number entity (options-only; live 50 per §1.4) |

(`number.iq_battery_hacs_battery_reserve` 6-97 is the HACS IQ reserve echo of URA's emitted `reserve_level`, not a ladder knob; its min of 6 predates nothing actionable here — the drain-fallback path never emitted < 10 because excellent=10.)

**Conclusion:** no inversion has ever occurred live in the observable window, and the anomaly has never fired. Urgency is LOW; D1 is still justified (sub-reserve write reachable by one legal Number move to excellent=5), D2 stays parked per the split. Limitation: recorder retention is ~8 days, so pre-09-25 Number history is unobservable; anomaly_log covers the full v5.103.6+ period.

## Plan review (2026-10-02, ura-reviewer, scoped to the RECOMMENDED SPLIT: D1 + D3 + D4 at Tier 2-DB; D2 parked detect-only)

**Verdict: BUILD-READY** (after the in-plan fixes below, already applied).

Independent re-enumeration (greps re-run, not trusted):
- `_drain_targets` readers across `custom_components/`: `energy_battery.py:1876` (the seam), `:6263` (V4 validator), `:6428` (status, raw display); `energy.py:9240` (`offpeak_drain_targets` property — **zero external callers**, grep `\.offpeak_drain_targets\b` empty), `:9270`/`:9316` (V5 validator + payload), `:9403` (writer). Ctor `:521`. **No other direct dict read.** `_get_offpeak_drain_target` is the only decision lookup; callers `:1897, :1911` (`_drain_target_for`), `:5662-5663` (display class bump). All decision/emission consumers (`:352` release floor, `:5655→5684` DP stamp → `energy.py:5912`, `:5701` emission, `:6067/:6111` narration, pool via threaded param) route through `_drain_target_for`. **Seam claim CONFIRMED.**
- I-2 for D1 holds structurally: validator V4/V5 read the `_drain_targets` dict, which D1 leaves RAW. Must-not: builder writing effective values back into the dict (plan §D1.4 already forbids; Reviewer C should mutation-drill "write-back into dict" → I-2 anomaly test RED).
- #6: `compute_solar_horizon` has exactly one caller (`inclement.py:660-667`); `energy_battery.py:2259` feeds the RAW floor into the `InclementFusion` ctor (correct — `_partial_floor_value` clamps inside); validator `energy.py:9276` reads raw. Seam CONFIRMED.
- Tests driving `determine_mode` exist in ≥10 files (`test_energy_battery.py`, `test_dp_drain_target_value_stamp.py`, `test_offpeak_drain_target_day_staleness.py`, …) — enclosing-method anchors are feasible with existing fixtures.

Findings (all fixed in-plan or recorded here):
1. **MED (fixed)** — D3 named a non-existent helper `_partial_floor_value_raw_floor()`; a builder would have invented a second formula. Re-pointed to the existing `_partial_floor_value(current_soc)` (`inclement.py:730`).
2. **MED (fixed)** — I-1 as written ("no reserve_level on the drain-fallback path < reserve") is falsifiable by the pre-existing HOLD leg `hold_reserve = int(soc)` (`energy_battery.py:5707`) at SOC < reserve — a Reviewer-D false-positive and a builder temptation to "fix" it into a grid-charge. Scoped I-1 to the drain leg + DP stamp and fenced the hold leg as out-of-scope.
3. **LOW (build note)** — Under the split, §7 matrix rows X4, X5, X7, X8 and the peak-buffer parts of X3/X11 are D2-only: drop them (or assert "peak unchanged = raw, anomaly #2 still fires" — i.e. detect-only preserved). Keep X1, X2, X3 (drains), X6, X9, X10, X11 (drain+inclement parts) × seasons for X2/X6. The `floor > target` inversion analogues are X2 (reserve > all drains), X6 (very_poor < poor), X9 (inclement floor < reserve), X10 (unknown < reserve) — coverage of inversions is adequate.
4. **LOW (build note)** — D2's fixture-compat concern (`test_battery_inclement_arbitrage_floor.py:548-580`) disappears under the split; D2 status-attr work (`peak_buffer_target_operator`) is NOT built. `drain_targets_effective` attr IS built (D1).
5. **LOW (build note)** — D4 `CANONICAL_SOC_LADDER_DOC` enforcement line must say "#2 detect-only (design parked in PLANNING_ec_soc_ladder_full_wiring.md §D2; revival trigger: any `threshold_ladder_violation` with the #2 code)", not "#2 property".
6. **INFO** — D0 shows no inversion and no anomaly ever (§9); D1's value is the reachable-by-one-slider sub-reserve write, not observed harm. Tier 2-DB for the split is appropriate (D1 touches the drain-fallback emission + DP stamp; D3 changes a hold-depth decision input).

## 10. Plan-completion tracking
_To be filled post-build: delivered / deferred / why / where tracked._
