# PLANNING — Fan-Stop Suppression (Occupied-Fan Trust) State Extension

**Tier:** **2-DB (operator-elevated)** — see §Tier Classification.
**Triggering intent (2026-06-11):** Operator request — *"Extend fan stop control from 'sleep' house state to home_night and wake. We did some work to make sure fans don't turn off if presence blips during sleep. Find it and make a plan."*
**Estimated size:** ~60–100 LoC across 3 production files + ~8 cycle tests.
**Branch:** `feature/fan-trust-state-extension`

---

## 1. Problem statement

URA already protects bedroom fans against mmWave-presence blips **during `HouseState.SLEEP`** via four cooperating sites (cited below). The protection does NOT extend to the two states that flank sleep — `HOME_NIGHT` (winding down, often in bed before official sleep) and `WAKING` (groggy, still in bed, mmWave equally unreliable). The same sensor-degeneration mechanism (mmWave loses a still body in bed) exists in those windows, but the temperature-off-path, the vacancy-hold extension, and the v3.18.1 speed cap are all gated `house_state == "sleep"`.

The companion HVAC-side gap is documented live: `project-zone-away-when-occupied-home-night-gap.md` — Zone 1 (master) flipped to `away` preset 7+ times in 6 h on 2026-06-05 during `home_evening`/`home_night`/`guest`, because the v4.7.13 person-trust at `hvac.py:1151` is also sleep-only. The fix candidate identified there ("extend trust to home_night [and likely waking]") is the HVAC-side sibling of this fan cycle and is **in-scope** for this cycle (see §3 Decisions).

---

## 2. Institutional context verified

### 2.1 Greps run + results (each proposed addition tagged REUSED or NEW)

| Surface | grep | Finding |
|---|---|---|
| Existing sleep-gated trust sites | `house_state == "sleep"` across `domain_coordinators/` + `automation.py` + `aggregation.py` | **8 files matched**. Authoritative sites for THIS cycle: `hvac_fans.py:268, 373, 418`; `hvac.py:1151`; `presence_fan_recheck.py:251` (intentionally sleep-only — see §3); `aggregation.py:1472` (zone-aggregator anti-flap — out of scope, different concern). |
| HouseState vocabulary | `HouseState\.` in `house_state.py` | **Verified canonical tokens: `HouseState.HOME_NIGHT = "home_night"`, `HouseState.WAKING = "waking"`** (`house_state.py:29, 31`). Not "wake", not "home_night_state". String comparison uses bare lowercase values. |
| Room-type gate | `ROOM_TYPE_BEDROOM` in `hvac_fans.py` | **REUSED** — already imported & used at `hvac_fans.py:64, 375`; same gate reused in `automation.py:1554-1558`. |
| Vacancy-hold constant | `DEFAULT_FAN_VACANCY_HOLD` | **REUSED** — defined `const.py:657` + `hvac_const.py:293`, used `hvac_fans.py:436`. Not changing. |
| Sleep mode helper | `is_sleep_mode_active` in `automation.py` | **REUSED but EXPANDED.** `automation.py:500-513` is a **per-room TIME-WINDOW** (sleep_start_hour..sleep_end_hour), NOT the house_state machine — must NOT conflate with `house_state == "sleep"`. The `automation.py:1556` sleep_occupied_hold already keys off this time-window helper. See §3 Decision D-AUT. |
| Trust constant (new helper proposed?) | `FAN_TRUST_STATES` / `OCCUPIED_FAN_TRUST_STATES` / similar | **NEW** — no equivalent set exists. See §4 D1 for justification (single source of truth across 4 sites). |
| Speed cap predicate | `FAN_SPEED_LOW_PCT` at `hvac_fans.py:269` | **REUSED**; only the *gating predicate* expands. |
| Existing tests | `test_hotfix_sleep_occupied_fan_trust.py` | **REUSED + expanded.** Existing source-grep tests anchor on `"Sleep-state occupied fan trust"` comment — extending tests must update anchors or add sibling tests, not break the existing pass. |
| Mode-2 BLE recheck gate | `presence_fan_recheck.py:245-252` | **NEW DECISION POINT** — explicit comment at `:248-249` says "WAKING is NOT covered by the v4.7.13 contract (SLEEP-only) — allow recheck during the groggy transition." See §3 Decision D-MODE2. |

### 2.2 Prior planning docs consulted (skim or full read)

- `PLANNING_v4.7.13_sleep_state_zone_presence_trust.md` — full read; problem-statement table (sensor degeneration matrix) directly applies here, just extended to two more states.
- `PLANNING_v4.7.14_away_state_person_tracker_trust.md` — skim; same person-tracker veto pattern; v4.7.14 is the AWAY-side sibling, this cycle is HOME_NIGHT/WAKING-side.
- `PLANNING_v4.7.18.1_sleep_wake_deadlock.md` — skim; documents the waking-state transition machinery; relevant to D-WAKING release semantics.
- `PLANNING_v4.7.15_universalize_bug_class_48_veto.md` — skim; precedent for extending a single-state gate to a state-set.
- `PLANNING_fan_noise_mitigation_layers1_2.md` + `PLANNING_presence_provenance_split_and_fan_diagnostic.md` — skim; clarifies how v4.7.20 provenance hold interacts with this layer.

### 2.3 Memory bodies pulled (full file, not index lines)

- `project_zone_away_when_occupied_home_night_gap.md` — **load-bearing.** Documents the live `hvac.py:1151` gap fix candidate now folded into this cycle (D2).
- `project_v4_7_22_fan_recheck_mode2_live.md` — **load-bearing.** Documents the deliberate SLEEP-only choice at `presence_fan_recheck.py:251` and the `HIGH_STILL_RISK_ROOM_TYPES` safety guard. Drives Decision D-MODE2.
- `project_v4_7_18_1_sleep_wake_deadlock.md` — skim; sleep→waking deadlock context; informs WAKING release path.
- `project_v4_7_20_fan_noise_layer1_live.md` — skim; v4.7.20 provenance hold can only EXTEND occupancy → cannot fight this layer; safe interaction confirmed.

### 2.4 Design docs read

- `docs/Coordinator/hvac.md` (skim) — preset-resolution flow, D1 vacancy override, D6 stale-failsafe sleep-skip precedent at `hvac.py:1076-1122` (mirror pattern).
- `docs/Coordinator/presence.md` (skim) — house_state machine contract; provenance split context.

### 2.5 Code locations surveyed end-to-end during scoping

- `domain_coordinators/hvac_fans.py` (full read: dataclass §40-86; controller `_house_state` field :110, setter :198; speed cap :267-269; sleep-occupied trust block :360-400; vacancy hold sleep extension :413-435; vacancy expiry :436).
- `domain_coordinators/hvac.py` lines 1040-1220 (D1 vacancy override; v4.7.13 sleep person-trust at :1151-1170; preset apply).
- `domain_coordinators/house_state.py` lines 1-100 (HouseState enum, VALID_TRANSITIONS, hysteresis).
- `domain_coordinators/presence_fan_recheck.py` lines 230-300 (gate evaluation, sleep-only comment).
- `automation.py` lines 498-513 (is_sleep_mode_active = time-window), :1500-1600 (sleep_occupied_hold block).
- `quality/tests/test_hotfix_sleep_occupied_fan_trust.py` (full read).

---

## 3. Decisions (each accounted for under §8 Plan Completion Tracking)

| ID | Question | Decision | Rationale |
|---|---|---|---|
| **D-EXTEND** | Which sites extend from `sleep` to `{home_night, sleep, waking}`? | `hvac_fans.py:373` (sleep_occupied_hold), `hvac_fans.py:418` (vacancy-hold extension during sleep). | Symmetric ON-side + OFF-side trust. Same mechanism (mmWave drops still body in bed). |
| **D-CAP** | Does the v3.18.1 speed cap at `hvac_fans.py:268` extend? | **YES, extend to `{home_night, sleep, waking}`.** | Night-comfort consistency — operator already accepts LOW-cap at sleep; the cap is the same comfort contract people-in-bed expect during home_night/waking. Coupling cap to trust window prevents abrupt speed jump at state-boundary. |
| **D-HVAC** | Include the `hvac.py:1151` person-trust sibling (zone preset away-flip suppression) in-cycle? | **YES — in-cycle.** | Same family, same risk surface, same review framings catch the same blind spots. Excluding it splits a coherent fix across two cycles for no isolation benefit and leaves the master-bedroom `away`-flip live for another cycle. Operator memory `project_zone_away_when_occupied_home_night_gap.md` explicitly identifies this as the lead fix candidate. |
| **D-AUT** | Extend the per-room time-window `automation.py:1556` sleep_occupied_hold? | **NO — keep using `is_sleep_mode_active()` (time-window).** | This site keys off the **per-room sleep time-window**, NOT the house_state machine. Extending it to `home_night`/`waking` house_states would mix two distinct semantics (per-room schedule vs. house aggregate) and risk holding fans in non-bedroom rooms whose schedule disagrees. The time-window already covers the realistic bed-time hours. **Document explicitly in code comment.** |
| **D-MODE2** | Does the v4.7.22 BLE-gated fan pause+recheck sleep-only gate at `presence_fan_recheck.py:251` extend? | **NO — KEEP sleep-only.** | Deliberate safety choice (memory `project_v4_7_22_fan_recheck_mode2_live.md`): Mode-2 PAUSES a fan to verify presence — exactly the wrong operation during `home_night`/`waking` when people are awake, mobile, and would notice a fan pause. The `HIGH_STILL_RISK_ROOM_TYPES` guard is sleep-focused. Extension would change daytime-adjacent behavior. Code comment updated to make this explicit. |
| **D-AGGR** | Does `aggregation.py:1472` zone-aggregator sleep-anti-flap extend? | **NO — out of scope.** | Different concern (zone-aggregator vs. fan/preset trust); should it ever extend, it deserves its own cycle (occupancy aggregation correctness, not HVAC trust). Noted in §8. |
| **D-CONST** | New `FAN_TRUST_STATES` constant or repeat the tuple inline? | **NEW constant** in `hvac_const.py`: `FAN_TRUST_STATES: Final = (HouseState.HOME_NIGHT, HouseState.SLEEP, HouseState.WAKING)`. | Single source of truth across 4 sites (3 in `hvac_fans.py`, 1 in `hvac.py`). Prevents future drift; documented mapping to ROOM_TYPE_BEDROOM gate. |

---

## 4. Deliverables

### D1: Define `FAN_TRUST_STATES` constant
**File:** `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
- Add `from .house_state import HouseState` (verify no import cycle — `hvac_const.py` is currently leaf-level; if HouseState import causes a cycle, fall back to a tuple of literal strings `("home_night", "sleep", "waking")` with a code comment cross-referencing `HouseState`).
- Add `FAN_TRUST_STATES: Final = ("home_night", "sleep", "waking")` (string tuple to avoid import cycle risk; bare strings already match `HouseState` values which are StrEnum-derived).
- Add `FAN_TRUST_DOC: Final[str]` one-line docstring constant or block comment explaining: "States where bedroom-occupant fan-stop suppression applies. Extends v4.7.13 sleep-only trust to flank states where mmWave equally degrades on still bodies."

### Acceptance Criteria
- **Verify:** `from domain_coordinators.hvac_const import FAN_TRUST_STATES` succeeds without ImportError under `py_compile`.
- **Verify:** `set(FAN_TRUST_STATES) == {"home_night", "sleep", "waking"}` (no drift).
- **Test:** `test_fan_trust_states_constant_shape` asserts membership + ordering documented.

### D2: Extend `hvac_fans.py` to use `FAN_TRUST_STATES`
**File:** `domain_coordinators/hvac_fans.py`
- Line 268 (v3.18.1 speed cap): `if should_on and self._house_state == "sleep":` → `if should_on and self._house_state in FAN_TRUST_STATES:` (D-CAP).
- Line 373 (sleep_occupied_hold block, currently `self._house_state == "sleep"`): expand to `self._house_state in FAN_TRUST_STATES`. Update the block's leading comment from "Sleep-state occupied fan trust" to **"Night-window occupied fan trust"** (anchor change — update existing test).
- Trigger label: replace `sleep_occupied_hold` / `sleep_occupied_activate` with parameterized labels `night_trust_hold` / `night_trust_activate` that include the state for diagnostics — e.g., return `f"night_trust_hold:{self._house_state}"`. Keep label stable enough for downstream consumers (search for label usage first — grep `sleep_occupied_hold` confirms it's only used as a `room_fan.trigger` string, not switched-on; safe to rename).
- Line 418 (vacancy-hold sleep extension, `if self._house_state == "sleep":`): expand to `if self._house_state in FAN_TRUST_STATES:`. Log message updated from "sleep" to a state-formatted message.

### Acceptance Criteria
- **Verify:** Bedroom fan stays ON through a simulated mmWave blip in unit test for each of `{HOME_NIGHT, SLEEP, WAKING}`.
- **Verify:** Non-bedroom (`ROOM_TYPE_GENERIC`) fan in same state does NOT get held by the trust block (gate preserved).
- **Verify:** Speed cap (LOW) applies in all 3 states for an active temp-fan.
- **Verify:** Vacancy-hold person-trust extends in all 3 states; expires normally if person tracker goes not-home.
- **Test:** Add `test_night_trust_extends_to_home_night`, `test_night_trust_extends_to_waking`, `test_night_trust_excludes_home_evening` (boundary), `test_speed_cap_extends_to_home_night_and_waking`, `test_vacancy_hold_person_trust_extends`.
- **Live:** During next `home_night→sleep→waking` cycle on the live house, `sensor.master_bedroom_power` shows continuous fan operation (no power-band oscillations correlated with `binary_sensor.master_bedroom_occupied` flapping). Fan **DOES** turn off in genuinely-vacated bedroom (master bedroom emptied for >5 min) within `DEFAULT_FAN_VACANCY_HOLD = 300 s` after person tracker goes not-home.

### D3: Extend `hvac.py:1151` zone-preset person-trust (HVAC sibling — D-HVAC)
**File:** `domain_coordinators/hvac.py`
- Line 1151: `if effective_preset == "away" and self._house_state == "sleep":` → `if effective_preset == "away" and self._house_state in FAN_TRUST_STATES:`.
- Update comment block at :1142-1150 from "Sleep-state zone presence trust" to "Night-window zone presence trust"; preserve the precedent citation (D6 stale-failsafe, D5 duty-cycle).
- **CAUTION:** preserve D5 duty-cycle and D6 stale-failsafe sleep-skips at `hvac.py:1076-1124` AS-IS — those are deliberate sleep-only safeguards against runaway timers; expanding them is a SEPARATE risk surface not covered by this cycle's review framings. Documented in §8.

### Acceptance Criteria
- **Verify:** Zone 1 preset does NOT flip to `away` during `home_night` when at least one `zone_persons` member is `home`.
- **Verify:** D5/D6 sleep-skip semantics unchanged (regression test).
- **Test:** `test_zone_preset_person_trust_extends_to_home_night`, `test_zone_preset_person_trust_extends_to_waking`, `test_d5_duty_cycle_skip_still_sleep_only`, `test_d6_stale_failsafe_skip_still_sleep_only`.
- **Live:** Watch `sensor.ura_hvac_coordinator_hvac_zone_preset_zone_1` overnight. Pre-fix baseline (2026-06-05): 7 `away` flips in 6 h during home_night/home_evening. Post-fix: 0 `away` flips during home_night while `person.oji_udezue == home`. AC retreat correlated with the flap stops.

### D4: Re-affirm Mode-2 BLE recheck stays sleep-only (D-MODE2)
**File:** `domain_coordinators/presence_fan_recheck.py:245-252`
- **No behavior change.** Update the existing comment to: "SLEEP-only is intentional: this layer PAUSES the fan to verify presence — the wrong operation during home_night/waking when people are awake and would notice. v4.7.13-family trust (hvac_fans + hvac) DOES extend; this pause-based mechanism does NOT. See PLANNING_fan_trust_state_extension.md §D-MODE2."

### Acceptance Criteria
- **Verify:** Comment cross-references this planning doc.
- **Test:** `test_mode2_gate_remains_sleep_only` asserts the file contains `house_state == HouseState.SLEEP` and an explicit NOT-extending comment.

### D5: Per-room `automation.py:1556` audit (D-AUT)
**File:** `automation.py:1545-1559`
- **No behavior change.** Update the comment to make the time-window vs. house_state distinction explicit: "Uses per-room is_sleep_mode_active() time-window — NOT the house_state machine. Deliberately distinct from hvac_fans FAN_TRUST_STATES; this site's sleep window already covers the realistic bed-time hours and mixing the two semantics would over-extend non-bedroom common-area rooms."

### Acceptance Criteria
- **Verify:** Comment present; `test_automation_sleep_block_remains_time_window_keyed` source-grep test passes.

### D6: Update existing test anchors
**File:** `quality/tests/test_hotfix_sleep_occupied_fan_trust.py`
- The existing anchor string `"Sleep-state occupied fan trust"` will change to `"Night-window occupied fan trust"`. Update the existing test to either match the new anchor OR keep a backward-compat alias comment. **Preferred:** rename anchor + add a regression test that asserts BOTH the new state-set and ROOM_TYPE_BEDROOM gate are in the same block (gate preserved).

### Acceptance Criteria
- **Verify:** `pytest quality/tests/test_hotfix_sleep_occupied_fan_trust.py` passes.
- **Verify:** Suite baseline (`pre-review-<version>` tag) shows no NEW failures vs. baseline.

---

## 5. Tier classification (operator-elevated 2-DB)

**Tier: 2-DB (operator-mandated).** Per CLAUDE.md standing policy: this cycle modifies the **presence ↔ HVAC trust hierarchy** — the canonical regression-prone cross-coordinator ripple. The 'DB' in Tier 2-DB is historical; what we need is **three framing-disjoint reviews** because two same-framing reviewers converge on the same blind spots.

**Why elevation is correct here:**
- Touches 4 production sites across 2 coordinators (`hvac_fans` + `hvac`).
- Changes a shared primitive (the trust-state gate) consumed by ON-side (sleep_occupied_hold), OFF-side (vacancy-hold extension), speed cap, AND zone-preset evaluator.
- Ripple risk: HVAC preset ↔ fan controller ↔ presence provenance hold (v4.7.20) ↔ Mode-2 pause machine (v4.7.22). A small surgical fix could silently extend behavior into states that have their own contracts (Mode-2 SLEEP-only safety, D5/D6 sleep-skips).
- "Long-standing logic that other code has come to depend on" — the sleep-only gate has been live since v4.7.13/v3.18.1; behavior in `home_night`/`waking` has been the prior contract for ~10+ minor releases.

### 5.1 Three review framings (disjoint, not the canonical DB axes)

| Review | Framing | What it MUST cover |
|---|---|---|
| **A — Trust correctness + state-vocabulary + bedroom-gate edges** | "Does the new state-set match HouseState's actual tokens? Is the bedroom-only gate still load-bearing? Does WAKING release the trust at the right moment? What about guest rooms (`ROOM_TYPE_BEDROOM` for a guest)? Non-bedroom fans in common areas during home_night?" | Verify exact HouseState string values; verify ROOM_TYPE_BEDROOM gate survives at all 3 hvac_fans sites; trace trigger-label rename for downstream string-equality consumers; guest-room edge case (a guest-bedroom fan is correctly held — desired or undesired?); verify VALID_TRANSITIONS graph (home_night→sleep→waking only — no back-edges that would re-arm in unexpected order). |
| **B — Cross-coordinator ripple + no-flap + energy** | "When multiple holds overlap (v4.7.20 provenance hold + v4.7.22 pause machine + this trust block), what wins? Is real vacancy still detected? Are fans running longer at home_night a measurable energy cost? Does the v4.7.22 SLEEP-only gate stay correct now that hvac_fans extends? Does the D5/D6 sleep-skip remain sleep-only (preserve runaway-timer guard)?" | Trace every interaction matrix cell: trust+provenance hold; trust+Mode-2 pause; trust+D5 duty cycle; trust+D6 stale failsafe. Verify trust **still releases** on real vacancy (vacancy-hold expiry path at hvac_fans.py:436 unchanged). Compute worst-case energy delta: fans-on for vacancy_hold (300s) longer per state-extension × bedroom count. Verify no flap from home_night ↔ sleep ↔ waking transitions causing trust toggle. |
| **C — Test authority + day-boundary / state-transition coverage** | "Are the new tests source-grep AST or true behavioral? Do they cover the transition chains (home_night→sleep→waking, home_night→away mid-state, waking→home_day)? Restart mid-state? Existing test anchor rename without false-pass?" | Audit every new test: behavioral simulator-driven preferred over source-grep where feasible; chain tests covering all transitions documented in `house_state.py:VALID_TRANSITIONS` that touch the trust window; restart-resilience (RoomFanState restore + house_state restore both produce correct trust evaluation on first post-restart tick); day-boundary (sleep_start_hour ≠ HOME_NIGHT entry — verify D-AUT distinction preserved). |

**Run all three in parallel. Fix all CRITICAL/HIGH from any framing before deploy.** If fix-up is substantial, re-verify the affected framing.

### 5.2 Pre-deploy baseline + post-deploy live validation (Review D)

- Pre-deploy: `git tag pre-review-<version>`. Snapshot pre-fix baseline counts of `away` preset flips per zone per 6-h window (from recorder). Snapshot fan power oscillation pattern for master bedroom.
- Live Validation (Review D), post-restart: see D2/D3 Live criteria. Required PASS evidence to close the cycle per the **README write-back** rule.

---

## 6. Files changed

| File | Lines (approx) | Change kind |
|---|---|---|
| `domain_coordinators/hvac_const.py` | +5 | NEW constant `FAN_TRUST_STATES` |
| `domain_coordinators/hvac_fans.py` | ~15 modified | Replace `== "sleep"` at :268, :373, :418; rename trigger labels; update comments + log strings |
| `domain_coordinators/hvac.py` | ~5 modified | Replace `== "sleep"` at :1151; preserve D5/D6 sleep-skips at :1076-1124 |
| `domain_coordinators/presence_fan_recheck.py` | ~3 modified | Comment-only (cross-reference) |
| `automation.py` | ~3 modified | Comment-only (D-AUT clarification) |
| `quality/tests/test_hotfix_sleep_occupied_fan_trust.py` | ~10 modified | Anchor rename + gate-preservation regression assertion |
| `quality/tests/test_fan_trust_state_extension.py` | NEW ~150 LoC | D1–D5 acceptance tests |

---

## 7. Acceptance criteria (consolidated)

### Static
- `pytest quality/tests/test_fan_trust_state_extension.py -v` — all pass.
- `pytest quality/tests/test_hotfix_sleep_occupied_fan_trust.py -v` — all pass (regression).
- Full suite baseline-diff vs `pre-review-<version>` — zero new failures.
- `py_compile` clean for all 5 modified files.
- `grep -n 'house_state == "sleep"' custom_components/universal_room_automation/domain_coordinators/hvac_fans.py custom_components/universal_room_automation/domain_coordinators/hvac.py` returns **zero matches** after the change (all replaced with FAN_TRUST_STATES); other files retain their existing sleep-only gates per Decisions D-MODE2/D-AUT/D-AGGR.

### Live (post-restart)
- **Live-1 (HOME_NIGHT trust):** Master bedroom fan power continuous through any mmWave blip while house_state=home_night AND person.oji_udezue=home. No fan stop correlated with `binary_sensor.master_bedroom_occupied` flapping.
- **Live-2 (WAKING trust):** Same as Live-1 for waking window (typically 06:00–06:15 CDT).
- **Live-3 (Real vacancy still works):** Bedroom emptied for >5 min during home_night → fan turns off within DEFAULT_FAN_VACANCY_HOLD (300 s) after person tracker goes not-home. Verified via recorder timeline.
- **Live-4 (Zone preset stops flapping):** `sensor.ura_hvac_coordinator_hvac_zone_preset_zone_1` shows zero `away` flips during home_night while person home (pre-fix baseline: 7 flips/6h on 2026-06-05).
- **Live-5 (Speed cap applies in flank states):** If a temp-fan activates during home_night/waking, dispatched speed_pct ≤ FAN_SPEED_LOW_PCT.
- **Live-6 (Mode-2 unchanged):** Mode-2 fan_recheck does NOT arm during home_night/waking (sleep-only gate preserved). Verified via `fan_interference_*` diagnostic attrs.

### README write-back (mandatory)
Per CLAUDE.md "Record Live Validation Back Into the README — MANDATORY": pre-deploy README written with prospective Live criteria; post-restart, REPLACE with `Validated <date>` table containing observed evidence (entity_id + attribute, log scan, recorder timeline). Cycle is NOT closed until README carries the post-restart validation table.

---

## 8. Plan Completion Tracking (explicit deferrals)

| Item | Status | Where tracked |
|---|---|---|
| `aggregation.py:1472` zone-aggregator sleep-anti-flap extension | **NOT IN SCOPE** (D-AGGR) | Backlog: occupancy aggregation correctness cycle (separate concern from HVAC trust). Memory entry to be created on close. |
| `automation.py:1556` per-room time-window sleep_occupied_hold extension | **NOT IN SCOPE** (D-AUT) | Comment added in code; not deferred — explicitly decided NO. |
| `presence_fan_recheck.py:251` Mode-2 SLEEP-only gate extension | **NOT IN SCOPE** (D-MODE2) | Comment added in code; not deferred — explicitly decided NO. Safety choice. |
| `hvac.py:1076-1124` D5 duty-cycle + D6 stale-failsafe sleep-skip extension | **NOT IN SCOPE** | These are runaway-timer guards, not occupancy trust. Extending them would change safety semantics. Separate cycle if ever needed. |
| Bed-presence sensor wiring into master-bedroom room occupancy | **NOT IN SCOPE** | Memory `project_zone_away_when_occupied_home_night_gap.md` fix candidate #2. Deferred — this cycle delivers fix candidate #1 (the smaller, more durable surface change). |
| Plumbing FAN_TRUST_STATES through to a per-house Number / per-room config knob | **NOT IN SCOPE** | Per `feedback_parsimonious_room_config.md`: don't expose every internal timing/state constant as a runtime entity. Constant is sufficient. |

---

## 9. Risk register

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Trigger-label rename breaks downstream string-equality consumer | Low | Medium | Pre-build grep `sleep_occupied_hold|sleep_occupied_activate` across whole repo; if any non-test consumer matches, add backward-compat alias. |
| Import cycle on `HouseState` into `hvac_const.py` | Low | Low | Fall back to literal string tuple with cross-reference comment (D1 already specifies this). |
| Energy cost: fans run 300s longer during home_night vacancy on every false-vacant blip | Medium | Low | Vacancy-hold extension only fires while `person.oji_udezue == home` — bounded by real person tracker; releases on real not-home. |
| WAKING window includes morning shower / leaving-bed motion that DOES want fan-off | Low | Low | Vacancy-hold expiry (300s) still fires once person actually leaves; trust block only holds, doesn't activate. Morning shower turning fan off via manual_off cooldown still wins (line 350-358 ABOVE the trust block — verified). |
| Guest in guest-bedroom during home_night experiences trust extension | Medium | Low | Desired behavior — guest bedrooms ARE ROOM_TYPE_BEDROOM and SHOULD get the same trust. If undesired, guest-specific gate is a follow-up cycle, not this one. |

---

## 10. Out-of-band notes

- Versioning: per `feedback_versioning_convention.md`, no version number on this planning doc; version assigned at deploy time.
- Branch + Tier 2-DB review dispatch + README write-back follow CLAUDE.md standing protocol; no deviations requested.

---

## 11. Operator amendments 2026-06-11 (supersede plan where they conflict)

### Amendment 1 — Speed cap must honor per-room `CONF_FAN_SLEEP_POLICY`

The v3.18.1 speed cap at `hvac_fans.py:268` previously hardcoded the
"reduce" behavior (cap at FAN_SPEED_LOW_PCT) and ignored the existing
per-room `CONF_FAN_SLEEP_POLICY` (`const.py:601`, values `off` /
`reduce` / `normal`, default `reduce`). That key was only being read by
the room-level path in `automation.py:1515/1697` — a split-brain.

**Decision:** at the cap site, resolve the room's policy and branch:
- `normal` → no cap (operator opted out of the speed cap)
- `reduce` → cap at FAN_SPEED_LOW_PCT (legacy behavior, default)
- `off`    → leave to the room-level path in `automation.py`; do NOT add
  a coordinator-side force-off (would duplicate / obscure attribution).

`RoomFanState` gains a `fan_sleep_policy: str` field, populated in
`FanController.discover_fans()` from
`merged.get(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)` — same
plumbing pattern used for `room_type` per v4.7.16.2 (`hvac_fans.py:154`).

The cap's state gate still extends to `FAN_TRUST_STATES` per plan D-CAP
— the operator amendment is about WHAT the cap does once the gate
fires, not WHEN it fires. **REUSED** existing `CONF_FAN_SLEEP_POLICY` /
`DEFAULT_FAN_SLEEP_POLICY` / `FAN_SLEEP_OFF` / `FAN_SLEEP_REDUCE` /
`FAN_SLEEP_NORMAL`; **no new CONF key**.

### Amendment 2 — Bidirectionality is a first-class acceptance criterion

Operator: *"If there is no one there, we want it away for sure and
especially for HVAC."*

The trust must ONLY suppress off-paths while positive occupancy /
person evidence exists. Genuinely-vacated rooms must still hit normal
vacancy timeouts; an empty house must still reach `away`. The v4.7.14
all-trackers-away veto path (`StateInferenceEngine` → `HouseState.AWAY`)
must be UNAFFECTED.

The fix preserves bidirectionality structurally:
- **hvac_fans sleep_occupied_hold (`:373` block):** gated on
  `and occupied` — when `occupied` is False the branch does not fire.
- **hvac_fans vacancy-hold person-trust (`:418` block):** only returns
  hold when at least one `zone_persons` member's state is `"home"`. When
  all trackers are away the loop falls through and the existing
  `vacancy_seconds >= DEFAULT_FAN_VACANCY_HOLD` timer fires normally.
- **hvac.py zone-preset trust (`:1151`):** only `continue`s when
  `home_persons` (computed by filtering `zone_persons` on
  `state == "home"`) is non-empty. With all trackers away, `home_persons`
  is `[]` and the away preset is applied normally.

**Explicit tests added** in
`quality/tests/test_fan_trust_state_extension.py`:
- `TestD2_SleepOccupiedHoldExtends.test_bedroom_occupied_holds_fan_on_in_each_trust_state`
  — occupied bedroom + presence blip at home_night/sleep/waking → fan stays.
- `TestD2_VacancyHoldPersonTrustExtends.test_genuinely_vacated_bedroom_at_home_night_stops_at_normal_timeout`
  — bedroom truly vacated at home_night → fan stops at normal timeout.
- `TestBidirectionalityEmptyHouse.test_zone_preset_falls_through_when_all_trackers_away`
  — house empties during home_night → zone away preset still applies.
- `TestBidirectionalityEmptyHouse.test_fan_vacancy_hold_falls_through_when_all_trackers_away`
  — fan-layer mirror: all trackers away → vacancy expires normally.
- `TestD2_VacancyHoldPersonTrustExtends.test_vacancy_hold_releases_when_all_persons_away`
  — parametric across all three trust states.

### Pollution defense (build-time institutional lesson)

The test file uses spec-loaded modules under explicit suite-friendly
gates and a `_skip_no_real_fans` marker — **no `sys.modules` assignment
over shared paths** for stubbing, and **never silently mock past the
truth** (mirrors the `aiosqlite` lesson at `quality/tests/conftest.py`).
When a prior test in the suite ordering has already partial-stubbed the
shared package path, behavioral tests SKIP with an explicit reason
rather than falsely pass against the stub. Source-grep tests are
ordering-robust and always run.
