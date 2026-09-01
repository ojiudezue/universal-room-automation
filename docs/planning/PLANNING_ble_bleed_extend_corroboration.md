# PLANNING — BLE-BLEED-EXTEND-SLEEP-1: Body-corroborated BLE extend during sleep window

**Card:** `BLE-BLEED-EXTEND-SLEEP-1`
**Thread:** presence-fusion
**Tier:** **2-DB** (elevated — trust-hierarchy ripple, presence fusion is regression-prone; op-coined standing policy)
**Precedent:** BLE-WARM-CREATE-1 (v5.66.0) — this cycle addresses the EXTEND path; that cycle addressed the CREATE path. Distinct legs, distinct code region, but the same block and the same bug class (adjacent-room BLE bleed corrupting occupancy truth).
**Bug classes:** Coincidental Equality Masks a Concept Split (Class #63) — "person present" and "person present AND animate in this room" collapsed into one signal at extend-time; Trust-Hierarchy Ripple (unbounded BLE-solo extend refreshes the timeout that other consumers trust).

---

## 1. Institutional context verified

### 1.1 Greps run + results (producer / consumer / prior art)

**Extend-path producer (the code this cycle changes):**
- `custom_components/universal_room_automation/coordinator.py:3613-3752` — the `=== v3.8.8: BLE/Bermuda extends room occupancy ===` block. Post BLE-WARM-CREATE-1 the admission is CHAIN-ONLY:
  - `:3703-3706` — `ble_allowed = False; if BLE_CHAIN_HOLD_ENABLED: chain_unbroken = self._last_occupied_state; ble_allowed = chain_unbroken`
  - `:3708-3712` — on admit: `data[STATE_OCCUPIED]=True`, `STATE_OCCUPANCY_SOURCE="ble"`, `STATE_BLE_PERSONS`, `STATE_TIMEOUT_REMAINING=self._occupancy_timeout` (this is the refresh — the mechanism the bleed exploits).
  - `:3668-3680` (comment) — explicitly documents the FOUND problem: *"A still-body BLE hold extends INDEFINITELY through this leg while the BLE person keeps being reported present. The 4-hour failsafe does NOT bound BLE-sustained occupancy."*
- **This is the extend path, distinct from the create path** BLE-WARM-CREATE-1 fixed. Do NOT re-open the create leg. (Verified against `quality/tests/test_ble_extend_not_create.py::test_sleep_hold_pin_chain_extends_past_motion_window` — the sleep-hold pin is the intended extend behavior; we are constraining, not deleting it.)

**Body-signal producers (what corroboration reads):**
- `self._last_pir_motion_time` — coordinator.py:416 (init `_now`), :3524 (updated when PIR fires). REUSED as body signal — this is exactly what the D2 demotion block reads for the analogous "no real body signal" gate at :3797.
- mmWave: mmwave sensors already fold into `data[STATE_OCCUPIED]` upstream — a fresh mmwave hit ⇒ `_last_pir_motion_time` OR upstream occupancy already keeps the chain unbroken through the non-BLE path. The corroboration signal is *"has a body sensor produced evidence for this room within the corroboration window."* The probe on this card already established that the master-bath PIR+mmWave went **correctly quiet** during phantom holds — the discriminator is available and healthy.

**House-state producer (the "sleep / low-activity window" gate):**
- `coordinator.py:1960-1985` — `_d2_house_state_allows()` reads `presence.house_state` and identifies the sleep family as `HouseState.SLEEP`, `HouseState.WAKING`, `HouseState.HOME_NIGHT`. REUSED for the sleep-window gate on this cycle (semantically identical: "expected-stillness period where BLE bleed dominates real body signal").

**Kill / config knobs already in the region:**
- `const.py:575` — `BLE_CHAIN_HOLD_ENABLED: Final = True` (module constant, kill-switch semantics, reviewed-change rung — precedent for this cycle's new constant).
- `const.py:586` — `D2_PIR_STALENESS_MULTIPLIER: Final = 2` (staleness multiplier over `occupancy_timeout` — precedent for reusing the same *shape* of knob).

**Consumers of `data[STATE_OCCUPIED]` when source == "ble" (blast-radius map for the fix):**
- Zone `_room_occupied` roll-up (presence coordinator) → house-state contribution → HVAC preset selection, load-shed gates, guest-mode gates.
- Analytics / anomaly rows keyed to occupancy transitions (regime_detector, duty-cycle detector).
- Any occupancy-gated actuation on the master bath itself (lights, exhaust fan). Probe already measured ~zero *direct* actuation cost in this room; the operator's driver is truth-corruption reaching sibling consumers.
- `test_extend_path_ble_holds_still_body_when_chain_unbroken`, `test_sleep_hold_pin_chain_extends_past_motion_window` — anchor tests that must stay green outside the sleep window and must be joined by new tests INSIDE the sleep window.

**REUSED vs NEW summary:**
- REUSED: `_last_pir_motion_time` (body signal), `_d2_house_state_allows` house-state read pattern, `HouseState.{SLEEP,WAKING,HOME_NIGHT}` enum, existing `_run_ble_block` extraction harness for testing, `BLE_CHAIN_HOLD_ENABLED` knob-placement precedent.
- NEW (justified): **one** new module constant — `BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S` — grep of `const.py` for `BLE_*`, `CORROBORATION_*`, `EXTEND_*` returned no equivalent. Placed at the module-constant rung (per Numbers-Get-Knobs) because it is a fusion-safety threshold whose change must go through review, not a per-deployment tunable.

### 1.2 Prior planning docs consulted
- `docs/planning/PLANNING_ble_extend_not_create.md` — full read. Sibling cycle; defines the invariant surface and the mutation harness this cycle inherits.
- `docs/readmes/README_v5.66.0.md` — full read. BLE-WARM-CREATE-1 acceptance criteria and the D-MEDIUM-1 restart-pin carveout must remain intact.
- `docs/planning/AUDIT_shipped_organic_prune_2026_08_17.md` — skim (context on the state of BLE-related shipped work).

### 1.3 Memory bodies pulled
- `feedback_coincidental_equality_masks_concept_split.md` — this cycle's bug shape. "BLE person present" and "room actually occupied" are collapsed at extend-time; the fix restores the concept split.
- `feedback_suppression_needs_discharge.md` — the corroboration-window gate is a *conditional refresh*, not a suppression, but we must specify the DISCHARGE (see §5) so a genuine occupant with intermittent body signal does not fall off.
- `reference_ble_frigate*` and `feedback_disjoint_framings.md` — reviewer framing guidance.
- `feedback_marginal_benefit_pushback.md` — applied in §3 (why option A, not B or C).

### 1.4 Design docs read
- `docs/Coordinator/HOUSE_MANUAL.md` — sleep-family house-state semantics.
- Skimmed the extend block's own inline history at coordinator.py:3613-3752 (the doctrinal comment already anticipates this cycle's motivation).

### 1.5 Code locations surveyed end-to-end
- `coordinator.py:3413-3752` (entry actions, camera override, BLE extend block — read as one unit; the fix ONLY edits the BLE block).
- `coordinator.py:1960-1985` (`_d2_house_state_allows`).
- `const.py:560-600` (BLE / D2 knob region).
- `quality/tests/test_ble_extend_not_create.py` (full — this is the harness this cycle extends).

---

## 2. Problem statement (probe-confirmed)

**Symptom:** Master Bathroom reads `STATE_OCCUPIED=True, STATE_OCCUPANCY_SOURCE="ble"` for hours across a sleep window with NO body signal in the room (`_last_pir_motion_time` and mmwave both quiet). Measured: ~7h continuous pure-BLE hold; ~2 nights in 11.

**Mechanism (verified in source at coordinator.py:3703-3712):**
1. Sleeping phone in the adjacent master bedroom is within the master bath's BLE scanner footprint (a floor-plan artifact of THIS room; not house-wide).
2. Each `_async_update_data` tick, `person_coordinator.get_persons_in_room("Master Bathroom")` returns the sleeper.
3. `chain_unbroken = self._last_occupied_state` is True (last tick was True), so `ble_allowed = True`.
4. `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout` — refresh. The vacancy timer never expires.
5. Loop closes: this tick's True becomes next tick's `_last_occupied_state`, ad infinitum.

**Blast:** ~zero direct actuation cost in-room, but truth corruption reaches every consumer of Master-Bath occupancy (zone roll-up, HVAC contribution, anomaly rows). Operator: *"might show up in other ways."*

---

## 3. Fix — lever comparison (marginal-benefit decomposition)

Three candidate levers, ordered by scope:

| # | Lever | Delta | Risk / Why NOT |
|---|---|---|---|
| A | Require a body signal (PIR or mmwave) within a corroboration window for a BLE-only tick to REFRESH the timeout, **gated to sleep-family house_state**. Genuine occupant with periodic movement keeps refreshing; a bleed-only signal with no body decays out ~one `occupancy_timeout` after the last real body signal. | ~15 lines in one block; one new module constant; sleep-gate via reused helper pattern. | **Recommended.** Smallest correct fix. Directly addresses the concept split (BLE-present ≠ occupied-here). Reuses body signal already confirmed healthy in the probe. Reuses house-state pattern. No geometry, no per-room config. |
| B | Max BLE-solo-extend duration (hard cap on continuous chain-only BLE). | Similar LoC; one duration knob. | REJECTED as sole fix. A hard cap ALSO drops genuine sleepers (a still-body sleeper is exactly the case v5.22.0 protected). Discriminator "body vs no body" is what we have and what distinguishes bleed from real. A duration cap discriminates on nothing. |
| C | Exclude the bedroom-adjacent scanner from sustaining the bath's BLE. | Larger LoC; per-room config surface; new resolver semantics. | REJECTED as first move (marginal-benefit). Requires modelling BLE scanner adjacency per room; touches PersonCoordinator's room-resolution machinery; larger blast radius than the operator wants ("small + room-scoped"). Park for revisit if A does not eliminate the phantom holds. |

**Recommendation: A.** Sleep-window body-corroborated refresh — outside the sleep window, extend behaviour is byte-preserved (BLE-WARM-CREATE-1's sleep-hold pin unchanged); inside the sleep window, BLE-only refresh requires a body signal within `BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S`.

---

## 4. Falsifiable invariant

**INVARIANT (the property the cycle must guarantee, in falsifiable form):**

> During the sleep-family house_state (`SLEEP`, `WAKING`, `HOME_NIGHT`), the BLE chain-extend leg MUST NOT refresh `STATE_TIMEOUT_REMAINING` for a room unless a body signal (`_last_pir_motion_time` fresher than `now − BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S`, or upstream `_last_occupied_state=True` from a non-BLE source within the same window) exists for that room. Outside the sleep family, the chain-extend behaviour is byte-preserved from BLE-WARM-CREATE-1.

**Falsification observation:** in any sleep-family window, a room whose only tick-to-tick signal is BLE (no PIR fires, no mmwave fires) MUST time out approximately `occupancy_timeout` after its last body signal. If it holds indefinitely under those conditions, the invariant is broken.

**Key discriminator (per Producer/Consumer rule — the acceptance must DISCRIMINATE fix from new-failure):**
- **Bleed shape (the phantom):** `_last_pir_motion_time` older than window, `_last_mmwave` older than window, BLE persons continuously present → MUST exit ~`occupancy_timeout` after last body signal.
- **Real sleeper shape (must NOT regress):** BLE persons continuously present AND PIR/mmwave fires at least once every `BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S` (real occupants roll over, breathe past mmwave, brief bathroom trips, etc.) → hold sustains indefinitely (existing sleep-hold pin behaviour).
- **Restart mid-hold (D-MEDIUM-1 pin from BLE-WARM-CREATE-1):** re-admit on first post-restart tick regardless — the pin is untouched. This cycle's gate ONLY applies to REFRESH ticks that would otherwise sustain hold; it does not block chain re-admission at boot.

These three shapes are OBSERVATIONALLY DISTINCT — the acceptance test in §7 exercises each.

---

## 5. Deliverables

### D1 — New module constant

`const.py`, adjacent to `BLE_CHAIN_HOLD_ENABLED`:

```python
# Sleep-window body-corroboration window for BLE chain-extend
# (BLE-BLEED-EXTEND-SLEEP-1). During sleep-family house_state, a
# BLE-only tick may refresh the vacancy timer ONLY if a body signal
# (PIR/mmwave) has fired within this window. Outside sleep the
# window is not consulted (byte-preserved extend behaviour).
BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S: Final = 900  # 15 min — 3x default occupancy_timeout
```

**Rung:** module constant. Change-requires-review (fusion-safety threshold). Default 15 min chosen as ~3× the default occupancy_timeout (300s) so a genuine sleeper with any of {roll-over, bathroom trip, mmwave breathing tick} inside a 15-min window is preserved.

### D2 — Gated BLE-extend refresh

`coordinator.py:3703-3712`. Replace:
```python
ble_allowed = False
if BLE_CHAIN_HOLD_ENABLED:
    chain_unbroken = self._last_occupied_state
    ble_allowed = chain_unbroken
```
with a body-corroborated variant that ONLY takes effect in the sleep-family house_state. Sketch (final wording is a builder deliverable — reviewer verifies against invariant, not text):

```python
ble_allowed = False
if BLE_CHAIN_HOLD_ENABLED:
    chain_unbroken = self._last_occupied_state
    if chain_unbroken and self._in_sleep_family_house_state():
        # Sleep-window: require body corroboration within the window.
        body_fresh = self._body_signal_within(
            now, BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S
        )
        ble_allowed = body_fresh
    else:
        ble_allowed = chain_unbroken
```

- `_in_sleep_family_house_state()` — small helper mirroring `_d2_house_state_allows` (inverted membership); pulled out for testability and reuse.
- `_body_signal_within(now, window_s)` — reads `self._last_pir_motion_time` (already tracked) and — if trivially available — the most recent mmwave observation. Fail-safe: **fail-open** on missing data (return True) so a boot-transient does not drop a real hold — matches the D-MEDIUM-1 restart-pin philosophy.

### D3 — Test authority additions

Extend `quality/tests/test_ble_extend_not_create.py` (same harness, same source-extraction pattern):

- **T-BLEED-1 (fixture):** master-bath 08-29 phantom-hold replay. Sleep-family state, chain-unbroken, BLE present continuously, no PIR/mmwave firings → occupancy MUST drop within ~one occupancy_timeout after the last body signal.
- **T-BLEED-2 (real-sleeper regression pin):** sleep-family state, chain-unbroken, BLE present, PIR fires once every `WINDOW/2` → hold MUST persist across ≥8 timeouts (sleep-hold preserved).
- **T-BLEED-3 (non-sleep byte-identity):** house_state = `HOME_DAY` / `AWAY_STATE`, all other inputs as T-BLEED-1 → hold MUST persist (extend behaviour byte-preserved outside sleep).
- **T-BLEED-4 (restart-pin unchanged):** re-run `test_pin_restart_midhold_chain_readmits_without_inprocess_tier1` with sleep_family state — MUST stay green (fail-open on unset body signal).
- **T-MUTATION-BLEED:** mutate the sleep-family gate to always-True (i.e., always apply the corroboration check) — T-BLEED-3 MUST go red. Mutate the corroboration check to always-True — T-BLEED-1 MUST go red. Two anchors, two mutations, subprocess-isolated with pycache-clear (per Reviewer-C authority + `feedback_mutation_verification_pycache_staleness`).

### D4 — Producer / Consumer map for the changed value

Written into the README pre-deploy (per Producer/Consumer rule): the extend-refresh producer arithmetic (§5 D2), the body-signal dependency and its healthy-observed evidence (probe), and the enumerated consumers of Master-Bath occupancy (zone roll-up, HVAC contribution, analytics rows) with a note on which see the fix and which are indirect beneficiaries.

---

## 6. Non-goals

- **Not touching BLE-CREATE.** The chain-only admission at :3703-3706 stays chain-only. This cycle constrains the REFRESH; it does not re-open the create leg.
- **Not house-wide.** The knob is a global constant and the mechanism is house-state-gated, but the deployment consequence is room-scoped in effect (the master bath is the observed offender; other rooms without a floor-plan bleed will simply have body signal every tick they would have had before).
- **Not scanner-topology changes.** Option C (bedroom-scanner exclusion for the bath) is parked, not built.
- **Not touching D2 mmWave-fan demotion.** That block (coordinator.py:3753+) is byte-preserved.
- **Not the 4-hour failsafe.** Explicit non-goal — that path is unchanged.
- **Not per-room config surface.** No new options-flow field.

---

## 7. Acceptance criteria (DISCRIMINATING)

### Verify (in-suite)
- T-BLEED-1 green → phantom-hold shape exits ~occupancy_timeout after last body signal.
- T-BLEED-2 green → real-sleeper shape holds through the sleep window.
- T-BLEED-3 green → non-sleep windows are byte-preserved.
- T-BLEED-4 green → restart-pin behaviour preserved.
- Existing BLE-WARM-CREATE-1 suite (T1-T8, mutation anchors M1/M2/M3, sleep-hold pin, restart pin) ALL still green — regression proof.
- Mutation anchors: killing the sleep-family gate → T-BLEED-3 red; killing the corroboration check → T-BLEED-1 red.

### Live (post-deploy)
| # | Criterion | How to check |
|---|---|---|
| L1 | Integration loads, zero URA errors post-restart. | HA `system_log` search. |
| L2 | **Founding case:** replay a sleep-window night in the Master Bathroom. Recorder MUST show `STATE_OCCUPIED` transition to `off` within ~`occupancy_timeout + WINDOW` of the last PIR/mmwave firing, even while `person_coordinator.get_persons_in_room("Master Bathroom")` continued to return a sleeper. Concretely: the ~7h all-night hold shape MUST NOT reappear. | recorder query on `sensor.master_bathroom_occupancy_source`, `_last_pir_motion_time`, timeout_remaining across the sleep window; cross-check with BLE persons attribute. |
| L3 | **Real-sleeper preservation (discriminator):** the master BEDROOM (where the sleeper actually is, has body signal from mmwave/PIR) MUST retain its BLE hold across the same night. | recorder query on Master Bedroom occupancy across the same window — MUST show continuous hold. If both bedroom AND bathroom drop, we broke the discriminator. |
| L4 | No other room regresses to phantom drops in the sleep window. Sweep 24h of recorder for any room whose occupancy dropped-while-BLE-present-and-in-sleep — expected outcome: only bleed rooms (bath) drop, sleep-held bedrooms retain. | recorder cross-tab: per-room, in-sleep, ble-present, occupied_transitioned_false counts. Zero for bedrooms; nonzero only for known-bleed rooms. |
| L5 | Restart mid-hold: after next HA restart during a sleep window, BLE-held rooms re-admit on first post-restart tick (BLE-WARM-CREATE-1 D-MEDIUM-1 pin preserved). | recorder around next restart. |

Every "PASS" row cites the observed entity/attribute value or DB row — per README write-back rule.

---

## 8. Tier 2-DB review plan (three framing-disjoint reviews + live)

Elevated to Tier 2-DB per operator standing policy for regression-prone work; framings adapted to a strategy/fusion change (not a schema change):

- **Review A — local correctness + edge cases + concept-split integrity.** Verify the sleep-family gate and body-corroboration predicate implement the invariant in §4 for every combination of {house_state ∈ sleep-family / not}, {chain_unbroken T/F}, {body signal fresh / stale / None}, {BLE person present T/F}, {restart T/F}. Fail-open behaviour on missing body signal is intentional — verify it matches the D-MEDIUM-1 pin's rationale.
- **Review B — cross-coordinator + precedence + no-flap.** Enumerate every consumer of `STATE_OCCUPIED` and `STATE_OCCUPANCY_SOURCE=="ble"` for master-bath and confirm the fix does not induce flap (drops followed by re-creates within seconds), does not fight the D2 fan block, and does not interact adversely with zone roll-up, HVAC preset selection, or regime_detector rows. Confirm the sleep-family boundary (`HOME_DAY→HOME_NIGHT`, `HOME_NIGHT→WAKING`, `WAKING→HOME_DAY`) does not cause an artificial hold-drop at the transition tick.
- **Review C — test authority + day/cycle boundary + mutation.** Verify every new test drives production source (source-extracted block per existing harness). Verify mutation anchors go red on the specified mutations, subprocess-isolated with `.pyc` cleared. Verify no test couples to wall-clock. Verify T-BLEED-3 (byte-identity outside sleep) is a REAL discriminator, not a tautology of the fixture setup.

**Orchestrator independent verification before ship (per §Tier-3 discipline borrowed as belt-and-braces):** re-run grep for `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout` — MUST show only the BLE-extend site inside the sleep-gated branch. Re-run the two mutation drills by hand.

**Live Validation (Review D):** post-restart, run L1-L5 in §7 against the running instance; write results back into `README_v<version>.md` per the mandatory write-back rule.

---

## 9. Files touched (all others read-only)

- `custom_components/universal_room_automation/const.py` — one new constant.
- `custom_components/universal_room_automation/coordinator.py` — the BLE-extend block at :3703-3712 plus two small helper methods (`_in_sleep_family_house_state`, `_body_signal_within`) placed near `_d2_house_state_allows`.
- `quality/tests/test_ble_extend_not_create.py` — extend with T-BLEED-1..4 and two mutation anchors. (No new test file — same harness authority.)
- `docs/readmes/README_v<version>.md` — pre-deploy write, post-deploy Live table write-back.

Read-only during this plan (verified surfaces only): `person_coordinator.py`, `presence_coordinator.py`, `regime_detector.py`, `presence_fan_recheck.py`, `house_state.py`.

---

## 10. Open questions for the operator (before build dispatch)

1. **Window default (15 min / 900s).** Pick or ratify. Sensitivity: too short (≤ occupancy_timeout) risks dropping a genuine sleeper who happens not to twitch through mmwave for a spell; too long (≥ 1h) preserves multi-hour phantom holds. Recommendation: 15 min based on default occupancy_timeout of 300s.
2. **Body-signal set.** Confirmed: `_last_pir_motion_time`. Should mmwave age be tracked separately as a second admissible signal? Probe already showed the bath's mmwave went quiet during phantom holds — so in the founding case both agree. For robustness across rooms, add a `_last_mmwave_time` tracker if not already there (check during build).
3. **Fail-open on missing body-signal state (boot/restart).** Recommended, matches D-MEDIUM-1 restart-pin philosophy. Confirm.
