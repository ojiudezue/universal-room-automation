# PLANNING — BLE Extends Occupancy, Never Creates It

- **Cycle name:** `ble_extend_not_create`
- **Target version:** TBD at deploy (successor to `develop` tip ~62e3ff58)
- **Tier:** **Tier 2-DB — three framing-disjoint reviews** (operator-elevated per standing policy 2026-06-08: regression-prone room-tier entry logic; touches every direct-BLE room; same class as June Jaya-bedroom Bermuda flap; upstream of light/HVAC actuation).
- **Author:** ura-planner
- **Filed:** 2026-07-17
- **Trigger fixture:** Live incident 2026-07-17 21:16–21:47 — Master Bathroom lights strobed 7+ times on 18–63s cycles. Trace evidence:
  - `ura_activity_log`: every cycle logged as `occupancy_entry (source: ble)` → `light_turn_on` → `Room vacated` (seconds) → `light_turn_off`.
  - Room PIR + mmWave (`binary_sensor.outlet_..._masterbath_motion` / `_occupancy`) SILENT 21:01→21:38.
  - `sensor.iphone_oji_area` (Bermuda): ping-ponged Master Bedroom ↔ Master Bathroom ↔ Ezinne Makeup; path sensor literally read "Master Bathroom → Master Bedroom → Master Bathroom → Master Bedroom".
  - `nearest_scanner` flipped between the two in-bathroom Shelly scanners.
  - Legacy automations disabled/exonerated. Same class as June Jaya-bedroom Bermuda flap.

---

## 1. Institutional context verified

### 1.1 Files read end-to-end during scoping

- `custom_components/universal_room_automation/coordinator.py:1700–1900` — failsafe (1700–1753), **v3.5.1 camera-extends-occupancy block (1755–1784)**, **v3.8.8/v3.8.9 BLE-extends-occupancy block (1786–1843)**, always-populate ble_persons diagnostic (1845–1854).
- `custom_components/universal_room_automation/coordinator.py:2340–2378` — exit path (`_delayed_exit_verify` dispatch at 2346–2351) and the **v3.16 ble → real-sensor re-trigger** (2353–2378). This block reads `STATE_OCCUPANCY_SOURCE == "ble"` on the *previous* tick to detect physical arrival after a BLE hold. Fix impact: with `ble_allowed` becoming false for cold rooms, the "ble" prev_source will only exist when a real sensor previously confirmed and then timed out — which is exactly the case v3.16 was designed for. Semantics preserved; no changes required at 2353–2378.
- `custom_components/universal_room_automation/person_coordinator.py:1196–1265` — `get_persons_in_room` and `is_room_direct_ble` (Tier 1 iff owns a scanner AND no `CONF_SCANNER_AREAS`).
- `custom_components/universal_room_automation/domain_coordinators/_ble_corroboration.py` (entire file) — `phone_trustworthy`, `trustworthy_persons_in_room`. Shared H2 carve-out (phone-left-behind fail-OPEN). **REUSE candidate** for the confirmation predicate below.
- `custom_components/universal_room_automation/domain_coordinators/presence.py:3251–3500, 4817` — v4.7.19 per-room/per-kind `_room_provenance`; L1 corroboration ladder (also uses BLE + recent motion). Confirms the "BLE + recent motion" pattern is already the house-wide predicate for elevating BLE-only evidence.

### 1.2 Institutional greps (proof-of-work)

| Proposed addition | Verdict | Evidence |
|---|---|---|
| Predicate "BLE-only with recent motion within 2× occupancy_timeout" | **REUSED** — already present at `coordinator.py:1809–1812` for the Tier-2 branch. The fix REMOVES the tier discriminator so the same predicate applies to Tier-1 rooms as well. No new logic. | `Grep occupancy_timeout \* 2` → single hit at :1811. `Grep is_room_direct_ble` → 1 read site at :1802 (the site being changed) + defs in person_coordinator. |
| Constant for the 2× multiplier / window | **NEW module-level `const.py`: `BLE_MOTION_CONFIRM_MULTIPLIER: Final = 2`.** Rung: **module constant** (Numbers Get Knobs rung 1). Rationale: safety bound on a truth-source-elevation predicate; operator should NOT tune this per-deployment (a fitted invariant of "recent means within-timeout-territory"). A code review is the correct gate. No existing constant — grep `BLE_CONFIRM|BLE_.*WINDOW` returned zero hits. |
| CONF for per-room BLE opt-out | **REJECTED — do not add.** See §6 marginal-benefit note. The correct failure direction is universal ("BLE alone never creates"), which no config knob would achieve without operator-per-room bookkeeping. |
| New sensor / attribute | **NONE.** Existing `STATE_BLE_PERSONS` diagnostic populated at :1836 already surfaces "BLE saw persons but override skipped". No new entity. |
| Signal / dispatch | **NONE.** Room-local predicate only. |
| Helper for the check | **REUSED** — existing inline predicate structure at :1809–1812; the change is one-line hoist (remove `if not direct_ble`). |

### 1.3 Prior planning docs skimmed / relevance

- `docs/planning/PLANNING_census_ble_cancel_unrecognized.md` — sibling BLE trust surface, different code path (`camera_census.py`). No collisions. Confirms the ambient "reduce false BLE-derived signals" theme.
- `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` — presence-tier L1/L2 BLE ladder; different code path (`presence.py`), zone-tier. **This is the presence-tier analogue** of what we are doing at the room tier. Vocabulary and predicate names should align.
- `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` — room-tier state machine using BLE gating. Reads `STATE_OCCUPANCY_SOURCE`; DOES NOT depend on BLE-being-a-creator. Fix is compatible.
- `docs/planning/PLANNING_zone_camera_person_only_guard.md` (referenced from census cycle) — zone-tier trust hygiene; adjacent theme.

### 1.4 Memory bodies pulled

- `project_presence_guest_latch_and_veto_gap.md` — Bermuda flap history and `unidentified_count`-adjacency.
- `project_v4_7_24_substrate_unification_live.md` — occupancy substrate discovers per-room/per-kind raw signals; BLE is NOT one of the substrate kinds (BLE is layered above via `person_coordinator`), so the fix does not alter substrate semantics.
- `project_v4714_live.md` — v4.7.14 away-veto keys off `unidentified_count == 0`, independent of this predicate; no interaction.
- `project_ev_charge_start_deadband.md`, `feedback_incident_diagnosis_verify_before_mechanism.md` — verify-before-mechanism discipline applied here (trace lines cited verbatim above).

### 1.5 Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — target for a short "Room-tier BLE trust: extend-never-create" note in the room-tier section (deliverable D3 doc-back).
- No dedicated room-coordinator design doc exists; `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` is the umbrella.

### 1.6 Code locations surveyed end-to-end

- `coordinator.py` lines 1700–1900, 2340–2380 (as above).
- `person_coordinator.py` lines 1196–1265, 550–616 (scanner-area classification).
- `_ble_corroboration.py` (all 95 lines).

---

## 2. Root cause (verified in source, not asserted)

`coordinator.py:1786–1843` (v3.8.8 hook + v3.8.9 hardening):

- The block's **docstring** (:1786–1789) states the intent: "If motion/mmWave/camera have timed out… override vacancy". This is EXTEND semantics.
- The **implementation** (:1808) is `ble_allowed = direct_ble` — for Tier-1 direct-BLE rooms BLE is admitted unconditionally, then :1815 sets `STATE_OCCUPIED = True, STATE_OCCUPANCY_SOURCE = "ble"`. This is CREATE semantics.
- Consequence for a cold empty Master Bathroom (own scanner ⇒ Tier 1 ⇒ `direct_ble = True`) with no recent motion: a Bermuda flap into the room's area alone flips STATE_OCCUPIED False→True, `handle_occupancy_change(True)` fires → `entry_light_action` → `light_turn_on`. On the flap-out tick the BLE-created occupancy has no motion timeout to hold it (motion/mmWave silent) — the block simply does not re-execute, STATE_OCCUPIED falls to False on the next was_occupied-and-not-occupied edge → `exit_light_action` → `light_turn_off`. Strobe cycle length = the Bermuda flap cadence (18–63s observed).

### 2.1 The `_last_motion_time` seeding line is load-bearing to the bug

`coordinator.py:1819–1820`:

```
if not self._last_motion_time:
    self._last_motion_time = now
```

Under the current code, if BLE is admitted for a Tier-1 room with no prior motion, this line **seeds `_last_motion_time = now`** — which then makes the *very next* tick's `motion_age < 2 * occupancy_timeout` predicate trivially true. Under the naive fix "just remove the tier gate", this creates a **self-confirmation loop**: BLE would fail the predicate on tick N (no prior motion → skip), but had it succeeded it would have seeded. Under the intended fix (BLE must not create) the seeding must be **gated on the same recent-motion predicate** — you only seed when you legitimately extended. Reviewer B's job is to verify seeding is inside the `ble_allowed` branch AND that the predicate is evaluated BEFORE any seeding occurs. Today it already is (order is fine: predicate at :1809–1812 reads `self._last_motion_time` *before* the seeding at :1819–1820) — but the fix must not accidentally reorder them.

### 2.2 STATE_OCCUPANCY_SOURCE consumers (checked)

- `coordinator.py:2361` — v3.16 ble→real-sensor re-trigger. Reads *previous* tick's source. Unchanged behavior: after the fix, "ble" prev_source only appears when BLE legitimately extended a real-sensor-confirmed occupancy that then timed out — exactly v3.16's intended trigger. No regression.
- `sensor.py` diagnostics that surface `ble_persons` / occupancy source — unaffected (still populated at :1836 in the "skipped" branch).
- No other consumers gate on `source == "ble"` for control logic.

### 2.3 Camera block (v3.5.1) — MUST NOT change

`coordinator.py:1755–1784` mirrors the BLE block structurally but for camera person sensors. Camera semantics **are** extend-only in intent AND today are also unconditional-create in implementation (no motion-recency predicate). This cycle **does not touch** the camera block — its failure mode is different (a real camera person detection is a stronger signal than a Bermuda area guess), and mixing the two invites blast-radius creep. If review C proposes symmetry, defer to a follow-up cycle with its own fixture. **Explicit non-goal.**

---

## 3. The falsifiable invariant (stated both ways, both directions)

**Invariant (a) — no create:** For any room R and any tick T, if immediately before T `STATE_OCCUPIED[R] == False` AND `_last_motion_time[R]` is either None OR older than `BLE_MOTION_CONFIRM_MULTIPLIER × occupancy_timeout[R]`, then no BLE evidence at tick T can flip `STATE_OCCUPIED[R]` to True or fire `entry_light_action`. (Camera person sensors and real motion/mmWave/occupancy are exempt — they can create. BLE cannot.)

**Invariant (b) — extend preserved:** For any room R where `_last_motion_time[R]` is within `BLE_MOTION_CONFIRM_MULTIPLIER × occupancy_timeout[R]` at tick T, the BLE hold path is **byte-identical** to today's behavior (source="ble", ble_persons populated, `_became_occupied_time` seeded if None, `_last_occupied_time` seeded if not last_occupied_state). v4.7.13 / v3.8.8 still-body scenario (someone in bed, motion timed out, BLE holds) MUST continue to hold indefinitely.

Reviewer D's sole task: falsify (a) with a legal-config reachable repro across ALL direct-BLE rooms, including edge cases (fresh-boot no `_last_motion_time`, clock skew making motion_age negative — see :1724–1729 defense pattern, room with occupancy_timeout=0/very small, guest mode, sleep state).

---

## 4. Deliverables

### D1 — Hoist the recent-motion predicate to apply to ALL rooms

**Change (single file):** `coordinator.py:1808–1812`. Remove the `if not direct_ble` gate; predicate the same recent-motion check for every room. The `direct_ble` classification is retained for the debug log tag ("direct+confirmed" vs "shared+confirmed") but no longer bypasses confirmation.

**Constant (D1a):** Add `BLE_MOTION_CONFIRM_MULTIPLIER: Final = 2` to `const.py`. Replace the literal `2` at :1811. Rung = **module constant** (Numbers Get Knobs rung 1: safety/trust bound; not operator-tuned). Kill-switch semantics: setting to `0` disables all BLE hold (predicate always false); this is the disable path and is documented on the constant.

**Seeding review (D1b):** Explicit code comment at :1819–1820 that seeding lives **inside** `if ble_allowed:` and MUST remain there — the seeding is the byte-preserving part of invariant (b), not a shortcut for (a).

### Acceptance Criteria — D1
- **Verify:** Diff shows exactly one predicate change + one constant introduction + one comment. No other logic change in the BLE block. Camera block byte-identical.
- **Test:** New `quality/tests/test_ble_extend_not_create.py` reproducing tonight's fixture: room with `_last_motion_time = None`, `_became_occupied_time = None`, BLE returns `["oji"]`, `is_room_direct_ble = True` → assert `STATE_OCCUPIED == False`, `STATE_OCCUPANCY_SOURCE != "ble"`, `ble_persons` still populated, no `handle_occupancy_change(True)` call.
- **Test:** Extend-preserved case: `_last_motion_time = now - 30s`, `occupancy_timeout = 60s`, BLE returns `["oji"]` → assert `STATE_OCCUPIED == True`, source="ble", `_became_occupied_time` seeded, `_last_occupied_time` seeded — byte-diff against a pre-fix golden.
- **Test:** v3.16 re-trigger unchanged — synthesize prev_source="ble" (via legitimate extend), current_source="motion" → assert `handle_occupancy_change(True)` still fires.
- **Test:** Clock-skew — `_last_motion_time = now + 60s` (future). Assert BLE does NOT create (predicate must reject negative `motion_age`).
- **Sensor:** `sensor.<room>_ble_persons` (via diagnostic) still lists BLE-detected persons even when override skipped.
- **Live:** Post-deploy, a Bermuda flap into a cold Master Bathroom (PIR/mmWave silent >2× occupancy_timeout) produces ZERO `light_turn_on` events in `ura_activity_log` with `source: ble`. Reproduce by walking past the room without entering.
- **Live:** Master Bedroom still-body hold under `sleep` state — someone in bed, motion timed out, BLE hold — verify next morning that lights/fans stayed correctly held (v4.7.13 acceptance).
- **Live:** `ura_activity_log` scan of 24h post-restart shows no `occupancy_entry (source: ble)` immediately followed by `Room vacated` within `occupancy_timeout` (the strobe signature).

### D2 — Regression test built from tonight's exact fixture

Encode the 21:16–21:47 Master Bathroom trace as a behavioral test. Room configured with own scanner (Tier 1), no `CONF_SCANNER_AREAS`, `occupancy_timeout` matching the live room. Drive `person_coordinator.get_persons_in_room` to return `["oji"]` for 6 consecutive ticks separated by 20–60s, with motion sensors held silent throughout. Assert:
- Zero `handle_occupancy_change(True, …)` calls to the room automation.
- Zero `STATE_OCCUPANCY_SOURCE == "ble"` transitions.
- `ble_persons` correctly reflects presence throughout (diagnostic preserved).

This test IS reviewer C's mutation anchor: with the fix reverted (one-line `ble_allowed = direct_ble`), this test MUST fail.

#### Acceptance Criteria — D2
- **Test:** `test_ble_extend_not_create.py::test_masterbath_2026_07_17_repro` passes on fixed code, fails on pre-fix code.
- **Test:** Reviewer C runs mutation: restore `ble_allowed = direct_ble` in production source → this test fails; other tests still pass appropriately (mutation isolates THIS site).

### D3 — Documentation write-back

- Add a short "Room-tier BLE trust: extend, never create" subsection to `docs/Coordinator/PRESENCE_COORDINATOR.md` referencing `coordinator.py:1786–1843` and stating the invariants from §3.
- README `docs/readmes/README_v<version>.md` (pre-deploy) carries prospective Live criteria from D1; validator writes them back with observed evidence per the mandatory README write-back rule.

#### Acceptance Criteria — D3
- **Verify:** `PRESENCE_COORDINATOR.md` diff includes the subsection; grep for "extend, never create" returns a hit.
- **Verify:** README post-Live table filed before cycle close.

---

## 5. Tier 2-DB review framings (three, disjoint)

- **Review A — Predicate correctness + non-interference.** BLE block predicate arithmetic; camera block (v3.5.1) byte-identical; failsafe path unchanged; ble_persons diagnostic still populated in skipped branch; STATE_OCCUPANCY_SOURCE consumers audited (grep `"ble"` across the package). Edge cases: `_last_motion_time` None; motion_age negative (clock skew); occupancy_timeout = 0; multiple persons; guest present.
- **Review B — Lifecycle / timeout / seeding interactions.** Exit path (`_delayed_exit_verify` :2346) under new predicate; v3.16 ble→real re-trigger at :2361; **the `_last_motion_time` seeding at :1819–1820 must not enable self-confirmation on the next tick** (validate order-of-operations: predicate before seeding, seeding only inside admitted branch); `_became_occupied_time` / `_last_occupied_time` seeding parity with pre-fix on the legitimate-extend path; failsafe timer behavior on BLE-held rooms; restart resilience (BLE holds are RAM-only — cold start correctly enters "cannot create" territory until first real motion, which is the desired behavior); interaction with fan-recheck (v4.7.22) and boot-settle gates (v4.7.21).
- **Review C — Test authority via real per-site source mutation.** Reviewer C edits `coordinator.py:1808` to the pre-fix line, runs the suite, confirms the D2 fixture test fails and no other test regresses spuriously. Reviewer C also verifies the D2 test drives PRODUCTION `_async_update_data` (or its refactor), not a hand-rolled shim. Reviewer C spot-checks that the constant `BLE_MOTION_CONFIRM_MULTIPLIER` is REFERENCED at :1811 (grep count == 2: def + use), not left as a literal.

**Optional Review D (adversarial completeness).** Given the tight blast radius (one predicate hoist, one constant, one file), a fourth pass is not mandated by Tier 2-DB. Recommend elevating to Tier 3 with a D pass ONLY if reviewer B or C surfaces any cross-coordinator ripple during their pass — otherwise the invariant surface here is small enough that three disjoint framings are sufficient. Orchestrator to decide at review time.

**Pre-review baseline tag:** `git tag pre-review-v<version>` before applying any review fixes.

---

## 6. Marginal-benefit decomposition — why this beats the alternatives

Per operator pushback duty:

1. **Simplest version captures the whole benefit.** One predicate hoist + one constant, single file, single line semantically. Eliminates the entire "BLE alone creates a cold-room occupancy" family of bugs across all Tier-1 rooms — Master Bathroom tonight, Jaya bedroom in June, and any future room upgraded to its own scanner.
2. **Alternatives priced:**
   - **Per-room `CONF_DISABLE_BLE_CREATE`** — pushes the fix to per-room operator config, guarantees the bug ships to any new room that forgets the knob. Rejected as introducing a config-combinatorics surface (Tier 3 territory) for zero net benefit.
   - **Bermuda tuning (increase area-hold, smooth flaps upstream)** — treats the symptom in a foreign integration. URA still trusts a single flap on any future noisy scanner. Doesn't survive scanner topology changes.
   - **Increase `census_hold_interior` / other mitigation timers** — masks the strobe cadence but does not fix the "BLE alone creates" semantic. Also already turned down 15→3 for other reasons; further increases regress guest UX.
3. **Marginal risk of the chosen fix:** Byte-preserving on the legitimate-extend path (invariant b). The only new failure mode is "BLE hold no longer creates in a genuinely-real-but-quirky scenario". No such scenario exists: real presence produces motion within 2× occupancy_timeout by definition of the timeout (or the room's timeout is misconfigured — an operator-tunable, correct rung for that concern).
4. **Non-parking:** Not parking anything — this IS the simple version.

---

## 7. Files touched (summary)

- `custom_components/universal_room_automation/coordinator.py` — lines 1808–1812 predicate change; comment at :1819–1820.
- `custom_components/universal_room_automation/const.py` — add `BLE_MOTION_CONFIRM_MULTIPLIER`.
- `quality/tests/test_ble_extend_not_create.py` — new test module (D2 fixture + D1 acceptance tests).
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — add extend-never-create subsection.
- `docs/readmes/README_v<version>.md` — pre-deploy prospective + post-Live write-back.

## 8. Explicit non-goals

- Not touching the v3.5.1 camera block (:1755–1784).
- Not changing `person_coordinator.is_room_direct_ble` semantics — still used for the log tag and unaffected callers (sensor.py diagnostics, presence.py L1 ladder).
- Not adding a per-room CONF for BLE behavior.
- Not touching the presence-tier BLE ladder in `presence.py` — that is the sibling `PLANNING_presence_fan_actuation_and_ble_ladder_deferred` surface.
- Not modifying the v3.16 re-trigger at :2353–2378.

---

## FIX-UP AMENDMENTS (2026-07-17, post-review, supersede invariant (b) above)

**Invariant (b) — chain formulation (B-HIGH-1 resolution, operator-ratified direction):**
BLE is admitted when EITHER (a) the occupancy CHAIN is unbroken (`_last_occupied_state`
= prev-tick occupied) — EXTEND, indefinite while the BLE person keeps being reported
present — OR (b) real motion within `BLE_MOTION_CONFIRM_MULTIPLIER × occupancy_timeout`
(the handoff tick). A room unoccupied last tick with stale motion REJECTS regardless of
scanner tier. `MULTIPLIER = 0` kills BOTH legs.

**Corrections from the B re-look:**
- The 4-hour failsafe does NOT bound BLE-sustained occupancy (it requires occupied=True
  at its check point, where BLE ticks read False). This was equally true pre-fix for
  Tier-1. True bound = BLE person presence per tick. Forgotten-phone mitigation =
  `PersonPhoneLeftBehindSensor` (existing, separate).
- Tier-2 shared-scanner rooms GAIN an indefinite chain hold they previously lacked
  (self-released at 2×timeout). Intended (uniform semantics), but a shared-scanner room
  is added to the live-validation checklist for phone-left-behind over-hold.
- Negative motion-age (clock skew) now rejects the motion leg — intentional hardening
  vs old Tier-2 behavior (A-LOW-1).

**Live-validation additions:** one shared-scanner room watched for over-hold; the
Master Bathroom cold-flap zero-actuation check; Master Bedroom still-body hold intact.
