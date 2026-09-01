# PLANNING — BLE-BLEED-EXTEND-SLEEP-1: Belt-and-suspenders body-corroboration + general BLE-solo cap

**Card:** `BLE-BLEED-EXTEND-SLEEP-1`
**Thread:** presence-fusion
**Tier:** **2-DB** (elevated — trust-hierarchy ripple, presence fusion is regression-prone; op-coined standing policy)
**Precedent:** BLE-WARM-CREATE-1 (v5.66.0) — this cycle addresses the EXTEND path; that cycle addressed the CREATE path. Distinct legs, distinct code region, same bug class (adjacent-room BLE bleed corrupting occupancy truth).
**Bug classes:** Coincidental Equality Masks a Concept Split (Class #63) — "person present" and "person present AND animate in this room" collapsed into one signal at extend-time; Trust-Hierarchy Ripple (unbounded BLE-solo extend refreshes the timeout that other consumers trust).

> **Rev 2 (2026-09-01) — BELT-AND-SUSPENDERS.** Rev 1 picked Lever A (sleep-gated body corroboration) alone. Operator direction 2026-09-01: *"consider a timeout for BLE extend after body not seen IN ADDITION to the sleep gate. That way it's generalized away from sleep alone. Can be a long timeout."* This revision adopts BOTH levers:
> - **Lever A** — tight, sleep-window-scoped body corroboration (~15 min). Drops the founding phantom within the sleep window.
> - **Lever B** — general, house-state-agnostic hard cap on BLE-solo-extend-since-last-body (~3–4 h). Backstop that catches any pure-BLE hold anywhere, anytime.
>
> The three previously-open operator questions are now baked in as defaults (corroboration window 900s; mmwave-age accepted as a second body signal; fail-open on boot). Read-only outside this plan doc.

---

## 1. Institutional context verified

### 1.1 Greps run + results (producer / consumer / prior art)

**Extend-path producer (the code this cycle changes):**
- `custom_components/universal_room_automation/coordinator.py:3613-3760` — the `=== v3.8.8: BLE/Bermuda extends room occupancy ===` block. Post BLE-WARM-CREATE-1 the admission is CHAIN-ONLY:
  - `:3713-3716` — `ble_allowed = False; if BLE_CHAIN_HOLD_ENABLED: chain_unbroken = self._last_occupied_state; ble_allowed = chain_unbroken`
  - `:3718-3722` — on admit: `data[STATE_OCCUPIED]=True`, `STATE_OCCUPANCY_SOURCE="ble"`, `STATE_BLE_PERSONS`, `STATE_TIMEOUT_REMAINING=self._occupancy_timeout` (the refresh — the mechanism the bleed exploits).
  - `:3682-3690` (comment) explicitly documents the FOUND problem: *"A still-body BLE hold extends INDEFINITELY through this leg… The 4-hour failsafe does NOT bound BLE-sustained occupancy."*
- This is the extend path, distinct from the create path BLE-WARM-CREATE-1 fixed. Do NOT re-open the create leg. (Verified against `quality/tests/test_ble_extend_not_create.py::test_sleep_hold_pin_chain_extends_past_motion_window` — the sleep-hold pin is the intended extend behavior; we are constraining, not deleting it.)

**Body-signal producers (what corroboration reads):**
- `self._last_pir_motion_time` — coordinator.py:416 (init `_now`), :3524 (updated when PIR fires). REUSED as body signal — exactly what the D2 demotion block reads at :3797.
- **mmwave age** — no direct `_last_mmwave_time` tracker exists today (grep for `_last_mmwave|last_mmwave_time` returned only `_mmwave_fan_demoted_since` at :425, unrelated). Two options: (i) add a small tracker updated wherever mmwave is folded into `data[STATE_OCCUPIED]` upstream, or (ii) rely on the fact that a fresh mmwave hit sets `_last_occupied_state=True` via a non-BLE source, which the corroboration predicate reads. **Decision (baked in per operator direction):** add `self._last_mmwave_time`, updated at the upstream mmwave-fold site the D2 block already reads; the corroboration predicate accepts either PIR or mmwave age fresh within window. Rationale: robustness across rooms — the founding case had both signals agree, but a room where PIR is sparse and mmwave carries the body signal must not be a bleed hole.

**House-state producer (Lever A's sleep-window gate):**
- `coordinator.py:1960-1985` — `_d2_house_state_allows()` reads `presence.house_state` and identifies the sleep family as `HouseState.SLEEP`, `HouseState.WAKING`, `HouseState.HOME_NIGHT`. REUSED via a small `_in_sleep_family_house_state()` sibling helper (semantically identical: "expected-stillness window where BLE bleed dominates real body signal").

**Kill / config knobs already in the region:**
- `const.py:575` — `BLE_CHAIN_HOLD_ENABLED: Final = True` (module constant, kill-switch semantics, reviewed-change rung — precedent for BOTH new constants).
- `const.py:586` — `D2_PIR_STALENESS_MULTIPLIER: Final = 2` (staleness threshold — precedent for reusing the *shape* of knob).

**Consumers of `data[STATE_OCCUPIED]` when source == "ble" (blast-radius map):**
- Zone `_room_occupied` roll-up → house-state contribution → HVAC preset selection, load-shed gates, guest-mode gates.
- Analytics / anomaly rows keyed to occupancy transitions (regime_detector, duty-cycle detector).
- Any occupancy-gated actuation on the master bath itself (lights, exhaust fan). Probe measured ~zero *direct* actuation cost; operator driver is truth-corruption reaching sibling consumers.
- `test_extend_path_ble_holds_still_body_when_chain_unbroken`, `test_sleep_hold_pin_chain_extends_past_motion_window` — anchor tests that must stay green outside the sleep window (Lever A) AND under short BLE-solo runs (Lever B).

**REUSED vs NEW summary:**
- REUSED: `_last_pir_motion_time`, `_d2_house_state_allows` house-state read pattern, `HouseState.{SLEEP,WAKING,HOME_NIGHT}` enum, existing `_run_ble_block` extraction harness for testing, `BLE_CHAIN_HOLD_ENABLED` knob-placement precedent.
- NEW (justified):
  - `BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S` — **Lever A** window; grep of `const.py` for `BLE_*`, `CORROBORATION_*`, `EXTEND_*` returned no equivalent. Module-constant rung (fusion-safety threshold).
  - `BLE_SOLO_EXTEND_MAX_S` — **Lever B** hard cap; likewise no equivalent (`MAX_*`, `SOLO_*` grep clean in const.py). Module-constant rung (safety bound; must go through review).
  - `self._last_mmwave_time` state tracker — no equivalent; added minimal.

### 1.2 Prior planning docs consulted
- `docs/planning/PLANNING_ble_extend_not_create.md` — full read. Sibling cycle; defines the invariant surface and the mutation harness this cycle inherits.
- `docs/readmes/README_v5.66.0.md` — full read. BLE-WARM-CREATE-1 acceptance criteria and the D-MEDIUM-1 restart-pin carveout must remain intact.
- `docs/planning/AUDIT_shipped_organic_prune_2026_08_17.md` — skim.

### 1.3 Memory bodies pulled
- `feedback_coincidental_equality_masks_concept_split.md` — this cycle's bug shape.
- `feedback_suppression_needs_discharge.md` — the corroboration gate and the MAX cap are both conditional-refresh limits; §5 specifies the discharge (a fresh body signal re-arms both windows; restart fail-opens).
- `feedback_marginal_benefit_pushback.md` — Rev-1 rejected Lever B as a *sole* fix on this ground. Rev 2 adds Lever B ALONGSIDE A: the marginal cost is one more knob at the same rung; the marginal benefit is a general-case backstop that fires *outside* the sleep window (where A is silent by design). Operator judged the marginal risk acceptable and the generalization worth it.
- `reference_ble_frigate*`, `feedback_disjoint_framings.md` — reviewer framing guidance.

### 1.4 Design docs read
- `docs/Coordinator/HOUSE_MANUAL.md` — sleep-family house-state semantics.
- Skimmed the extend block's own inline history at coordinator.py:3613-3760 (the doctrinal comment already anticipates this cycle's motivation).

### 1.5 Code locations surveyed end-to-end
- `coordinator.py:3413-3760` (entry actions, camera override, BLE extend block — read as one unit; the fix ONLY edits the BLE block).
- `coordinator.py:1960-1985` (`_d2_house_state_allows`).
- `const.py:560-600` (BLE / D2 knob region).
- `quality/tests/test_ble_extend_not_create.py` (full — this is the harness this cycle extends).

---

## 2. Problem statement (probe-confirmed)

**Symptom:** Master Bathroom reads `STATE_OCCUPIED=True, STATE_OCCUPANCY_SOURCE="ble"` for hours across a sleep window with NO body signal in the room (`_last_pir_motion_time` and mmwave both quiet). Measured: ~7h continuous pure-BLE hold; ~2 nights in 11.

**Mechanism (verified in source at coordinator.py:3713-3722):**
1. Sleeping phone in the adjacent master bedroom is within the master bath's BLE scanner footprint.
2. Each `_async_update_data` tick, `person_coordinator.get_persons_in_room("Master Bathroom")` returns the sleeper.
3. `chain_unbroken = self._last_occupied_state` is True (last tick was True), so `ble_allowed = True`.
4. `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout` — refresh. Vacancy timer never expires.
5. Loop closes: this tick's True becomes next tick's `_last_occupied_state`, ad infinitum.

**Blast:** ~zero direct actuation cost in-room; truth corruption reaches every consumer of Master-Bath occupancy. Operator: *"might show up in other ways."*

---

## 3. Fix — belt-and-suspenders (both levers)

Rev 1 considered three candidate levers. Rev 2 (per operator direction 2026-09-01) adopts A + B together; C stays parked.

| # | Lever | Scope | Role |
|---|---|---|---|
| A | **Sleep-window body-corroborated refresh.** In sleep-family house_state, a BLE-only tick may REFRESH the vacancy timer ONLY if a body signal (PIR or mmwave) has fired within `BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S`. Outside the sleep window, extend is byte-preserved. | Tight, narrow, fast-acting. | Drops the founding phantom ~15 min into the sleep window. |
| B | **General BLE-solo-extend hard cap.** Regardless of house_state, if BLE has been the ONLY sustaining signal (no PIR/mmwave fresher than `BLE_SOLO_EXTEND_MAX_S`), the extend leg refuses to refresh the timeout — occupancy drops via the normal vacancy path. Any fresh body signal re-arms the window. | Loose, general, slow-acting. | Backstop for any pure-BLE hold anywhere, anytime — including HOME_DAY / AWAY-family / unexpected states A never gates. |
| C | Bedroom-adjacent scanner exclusion for the bath. | Per-room geometry; larger. | **Parked** (marginal-benefit). Revisit only if A+B leave residual phantom holds. |

### 3.1 How the two levers compose

- **In sleep-family house_state:** A fires first. Body-signal freshness is checked against the tight 15-min window; a bleed with no body drops within ~one `occupancy_timeout` after the last body signal. B is silent here because A has already denied refresh — the MAX-S timer keeps counting but never has to fire.
- **Outside sleep family (HOME_DAY, AWAY_STATE, etc.):** A is silent by design (extend byte-preserved). B is the sole guard: if BLE has been the only sustaining signal for longer than `BLE_SOLO_EXTEND_MAX_S`, refresh is refused and the vacancy path drops the room.
- **Boundary transitions (`HOME_DAY→HOME_NIGHT`, `WAKING→HOME_DAY`):** A activates/deactivates at the transition tick; B's since-last-body counter is a pure elapsed-time measurement and is unaffected by house-state transitions. If a room is mid-hold at the transition INTO sleep and body signal is stale, A drops it on the very next tick (correct — the sleep-window rule now applies).
- **Discharge (per suppression-needs-discharge):** a fresh PIR or mmwave observation resets the "since-last-body" clock for BOTH levers. There is no separate discharge event; the body signal itself is the discharge. Restart fail-opens both levers (see D2).

### 3.2 Why belt-and-suspenders (marginal-benefit stated)

- **A alone** (Rev 1) leaves BLE-solo phantoms *outside* the sleep window unbounded. If house_state is stuck in `HOME_DAY` (or transitions unexpectedly), or if a bleed appears in a daytime pattern (a nap, a working-from-home stillness), A cannot fire.
- **B alone** (Rev 1's rejected sole fix) at any reasonable duration is slower than the sleep-window discriminator — it protects but wastes hours of truth corruption per night.
- **A + B** — A wins in the common case (the founding phantom drops fast); B is a general safety net whose default (~3–4 h) tolerates real-world stillness in any house_state but bounds ANY pure-BLE hold in absolute time. Two knobs at the same reviewed-change rung; one additional predicate; no new consumers, no new signals, no schema.

---

## 4. Falsifiable invariant (covers BOTH levers)

**INVARIANT (single property the cycle must guarantee, in falsifiable form):**

> The BLE chain-extend leg MUST NOT refresh `STATE_TIMEOUT_REMAINING` for a room when EITHER of the following holds:
>
> **(A)** the current house_state is in the sleep family (`SLEEP`, `WAKING`, `HOME_NIGHT`) AND no body signal (`_last_pir_motion_time` OR `_last_mmwave_time` fresher than `now − BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S`) exists for the room;
>
> **(B)** in ANY house_state, no body signal has been fresher than `now − BLE_SOLO_EXTEND_MAX_S` for the room (i.e., BLE has been the sole sustaining signal for longer than MAX_S).
>
> Outside these two conditions, the chain-extend behaviour is byte-preserved from BLE-WARM-CREATE-1.

**Falsification observations (per lever):**
- **A-falsifier:** in any sleep-family window, a room whose only tick-to-tick signal is BLE (no PIR/mmwave fires) MUST time out approximately `occupancy_timeout` after its last body signal. If it holds for MAX_S under those conditions, A is broken.
- **B-falsifier:** in any non-sleep window, a room whose only tick-to-tick signal is BLE for longer than `BLE_SOLO_EXTEND_MAX_S` MUST drop. If it holds indefinitely, B is broken.

**Key discriminators (per Producer/Consumer rule — acceptance must DISCRIMINATE fix from new-failure):**
- **Bleed shape in sleep (the founding phantom):** PIR/mmwave both stale, BLE persons continuously present, house_state ∈ sleep family → drops via A within ~`occupancy_timeout + WINDOW_S` after last body signal.
- **Bleed shape outside sleep (Lever-B-only case):** PIR/mmwave both stale, BLE continuous, house_state ∈ {HOME_DAY, AWAY_STATE, …} → drops via B at MAX_S after last body signal.
- **Real sleeper (must NOT regress):** BLE continuous AND PIR/mmwave fires at least once every `WINDOW_S` → hold sustains indefinitely (sleep-hold pin preserved).
- **Real daytime occupant with periodic motion (must NOT regress):** BLE continuous AND PIR/mmwave fires at least once every `MAX_S` → hold sustains indefinitely.
- **Restart mid-hold (D-MEDIUM-1 pin, unchanged):** re-admit on first post-restart tick regardless — fail-open on unset body-signal state applies to BOTH levers.

These shapes are OBSERVATIONALLY DISTINCT — the acceptance tests in §7 exercise each.

---

## 5. Deliverables

### D1 — Two new module constants

`const.py`, adjacent to `BLE_CHAIN_HOLD_ENABLED`:

```python
# Lever A — sleep-window body-corroboration window for BLE chain-extend.
# During sleep-family house_state, a BLE-only tick may refresh the
# vacancy timer ONLY if PIR or mmwave has fired within this window.
# Outside sleep this window is not consulted (Lever B still applies).
BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S: Final = 900  # 15 min — ~3x default occupancy_timeout

# Lever B — GENERAL max continuous BLE-solo extend (any house_state).
# If BLE has been the ONLY sustaining signal for longer than this,
# extend refuses to refresh the vacancy timer. Any fresh PIR/mmwave
# observation resets the since-last-body clock. Long by design: the
# common case (real occupants with periodic motion) refreshes far
# more often than this; the cap is a safety bound on pure-BLE holds.
BLE_SOLO_EXTEND_MAX_S: Final = 4 * 60 * 60  # 4 hours
```

**Rung (both):** module constant. Change-requires-review (fusion-safety thresholds), per Numbers-Get-Knobs.

**Default reasoning:**
- **900s (A):** ~3× the default `occupancy_timeout` (300s). A genuine sleeper who twitches through mmwave, rolls over past PIR, or makes a brief bathroom trip inside a 15-min window is preserved. Shorter than this risks dropping quiet sleepers; longer preserves the phantom shape well into a sleep window.
- **4h (B):** longer than any realistic single-sitting stillness in a non-sleep window (WFH desk sits, long meetings, extended reading) — real occupants overwhelmingly trip PIR or mmwave inside 4h. Shorter than the ~7h founding phantom shape (so B would have caught it even absent A). Same order as the existing 4-hour failsafe rhetoric in the block comment (§coordinator.py:3684-3688), keeping the mental model consistent. If operator observation shows real daytime holds legitimately spanning >4h without any body signal, revisit upward.

### D2 — Gated BLE-extend refresh (both levers)

`coordinator.py:3713-3722`. Replace:

```python
ble_allowed = False
if BLE_CHAIN_HOLD_ENABLED:
    chain_unbroken = self._last_occupied_state
    ble_allowed = chain_unbroken
```

with a body-corroborated, MAX-capped variant. Sketch (final wording is a builder deliverable — reviewer verifies against invariant, not text):

```python
ble_allowed = False
if BLE_CHAIN_HOLD_ENABLED:
    chain_unbroken = self._last_occupied_state
    if chain_unbroken:
        # Lever B (general): reject refresh if BLE has been the sole
        # sustaining signal longer than MAX_S. Fail-open on unset
        # body-signal state (boot/restart) per D-MEDIUM-1 philosophy.
        body_within_max = self._body_signal_within(
            now, BLE_SOLO_EXTEND_MAX_S
        )
        # Lever A (sleep-window): during sleep family, tighten to
        # the corroboration window.
        if self._in_sleep_family_house_state():
            body_within_window = self._body_signal_within(
                now, BLE_SOLO_EXTEND_CORROBORATION_WINDOW_S
            )
            ble_allowed = body_within_max and body_within_window
        else:
            ble_allowed = body_within_max
```

New helpers, placed near `_d2_house_state_allows`:

- `_in_sleep_family_house_state() -> bool` — sibling of `_d2_house_state_allows`; returns True iff house_state ∈ {`SLEEP`, `WAKING`, `HOME_NIGHT`}.
- `_body_signal_within(now, window_s) -> bool` — returns True iff `self._last_pir_motion_time` OR `self._last_mmwave_time` is fresher than `now − window_s`. **Fail-open:** if BOTH trackers are unset (boot/restart) → return True. Matches D-MEDIUM-1 restart-pin philosophy for BOTH levers.
- `self._last_mmwave_time` — new attribute, initialized `None` in `__init__` alongside `_last_pir_motion_time`; updated at the upstream mmwave-fold site the D2 block already inspects. Minimal — one write site plus init.

### D3 — Test authority additions

Extend `quality/tests/test_ble_extend_not_create.py` (same harness, same source-extraction pattern):

- **T-BLEED-A1 (Lever A fixture — 08-29 phantom-hold replay):** sleep-family state, chain-unbroken, BLE present continuously, no PIR/mmwave firings → occupancy MUST drop within ~one `occupancy_timeout + WINDOW_S` after the last body signal.
- **T-BLEED-A2 (real-sleeper regression pin — A must NOT drop them):** sleep-family state, chain-unbroken, BLE present, PIR fires once every `WINDOW/2` → hold MUST persist across ≥8 timeouts.
- **T-BLEED-B1 (Lever B fixture — non-sleep, long BLE-solo):** `house_state = HOME_DAY`, chain-unbroken, BLE present continuously, no PIR/mmwave firings → occupancy MUST drop at approximately `BLE_SOLO_EXTEND_MAX_S` after last body signal. Use a scaled MAX_S in the fixture (test-injected small constant) so the test runs in seconds; assert against the injected value.
- **T-BLEED-B2 (daytime occupant regression pin — B must NOT drop them):** `house_state = HOME_DAY`, chain-unbroken, BLE present, PIR fires once every `MAX_S/2` → hold MUST persist indefinitely.
- **T-BLEED-BOUNDARY (sleep-family transition):** enter sleep-family with body signal already stale > WINDOW_S → A drops on the transition tick (correct — sleep-window rule now applies). Enter sleep-family with body signal fresh → hold sustained by A until body goes stale > WINDOW_S.
- **T-BLEED-MMWAVE (mmwave-only body signal):** PIR permanently stale, mmwave fires within WINDOW_S (Lever A) / MAX_S (Lever B) → hold sustains under both levers.
- **T-BLEED-RESTART (fail-open unchanged):** re-run `test_pin_restart_midhold_chain_readmits_without_inprocess_tier1` with BOTH levers active and body-signal trackers unset → chain re-admits on first tick, both levers fail-open.
- **T-MUTATION-BLEED:** four anchors, subprocess-isolated with `.pyc` cleared (per `feedback_mutation_verification_pycache_staleness`):
  1. Mutate the sleep-family gate to always-True (always apply A) → T-BLEED-B2 (non-sleep byte-identity in the region A shouldn't touch) MUST go red.
  2. Mutate A's corroboration check to always-True → T-BLEED-A1 MUST go red.
  3. Mutate B's MAX check to always-True → T-BLEED-B1 MUST go red.
  4. Mutate the fail-open branch to return False → T-BLEED-RESTART MUST go red.

### D4 — Producer / Consumer map for the changed value

Written into the README pre-deploy: the extend-refresh producer arithmetic (§5 D2), the two body-signal dependencies (PIR + mmwave) and their healthy-observed evidence (probe), and the enumerated consumers of Master-Bath occupancy (zone roll-up, HVAC contribution, analytics rows) with a note on which see the fix directly and which are indirect beneficiaries.

---

## 6. Non-goals

- **Not touching BLE-CREATE.** Chain-only admission at :3713-3716 stays chain-only. This cycle constrains REFRESH; it does not re-open create.
- **Not house-wide re-plumbing.** Both knobs are global constants; deployment consequence is room-scoped in effect (rooms without a floor-plan bleed get body signal every tick they would have had before).
- **Not scanner-topology changes.** Option C parked, not built.
- **Not touching D2 mmWave-fan demotion.** That block (coordinator.py:3753+) is byte-preserved.
- **Not the 4-hour failsafe.** Explicit non-goal — that path is unchanged. Lever B is a different mechanism (per-room since-last-body cap), not a modification of the failsafe.
- **Not per-room config surface.** No new options-flow field.

---

## 7. Acceptance criteria (DISCRIMINATING, per lever)

### Verify (in-suite)
- T-BLEED-A1 green → sleep-window phantom exits ~`occupancy_timeout + WINDOW_S` after last body signal (Lever A).
- T-BLEED-A2 green → real sleeper with periodic motion held through sleep window.
- T-BLEED-B1 green → non-sleep BLE-solo hold drops at MAX_S (Lever B).
- T-BLEED-B2 green → daytime occupant with periodic motion held indefinitely.
- T-BLEED-BOUNDARY green → sleep-family transitions behave per §3.1.
- T-BLEED-MMWAVE green → mmwave counts as a body signal under both levers.
- T-BLEED-RESTART green → fail-open preserves BLE-WARM-CREATE-1 D-MEDIUM-1 pin under both levers.
- Existing BLE-WARM-CREATE-1 suite (T1–T8, mutation anchors M1/M2/M3, sleep-hold pin, restart pin) ALL still green — regression proof.
- Mutation anchors all four flip the specified test red.

### Live (post-deploy)
| # | Criterion | Lever | How to check |
|---|---|---|---|
| L1 | Integration loads, zero URA errors post-restart. | — | HA `system_log` search. |
| L2 | **Founding case (Lever A):** replay a sleep-window night in the Master Bathroom. Recorder MUST show `STATE_OCCUPIED` transition to `off` within ~`occupancy_timeout + WINDOW_S` of the last PIR/mmwave firing, even while `person_coordinator.get_persons_in_room("Master Bathroom")` continued to return a sleeper. The ~7h all-night hold shape MUST NOT reappear. | A | recorder query on `sensor.master_bathroom_occupancy_source`, `_last_pir_motion_time`, `_last_mmwave_time`, timeout_remaining across the sleep window; cross-check with BLE persons attribute. |
| L3 | **Real-sleeper preservation (discriminator):** the master BEDROOM (where the sleeper actually is; has body signal from mmwave/PIR) MUST retain its BLE hold across the same night. | A | recorder query on Master Bedroom occupancy across the same window — MUST show continuous hold. If both bedroom AND bathroom drop, we broke the A-side discriminator. |
| L4 | **General cap (Lever B):** sweep 7 days post-deploy for any room where `STATE_OCCUPANCY_SOURCE=="ble"` was continuously True for longer than `BLE_SOLO_EXTEND_MAX_S` with PIR/mmwave both stale for the same span → MUST be zero. Any non-zero result is a B-side leak (or an unknown body-signal source we didn't wire). | B | recorder cross-tab: per-room, ble-source-continuous-span, body-signal-max-age. |
| L5 | **Daytime occupant preservation (discriminator):** occupied rooms across daytime windows with periodic PIR/mmwave firings MUST retain occupancy across the same span (no unexpected drops driven by B). | B | recorder sweep of HOME_DAY windows for BLE-source rooms with fresh body signals — expected outcome: continuous hold. |
| L6 | No other room regresses to phantom drops in the sleep window. Per-room, in-sleep, ble-present, occupied_transitioned_false counts — zero for bedrooms with real bodies; nonzero only for known-bleed rooms. | A | recorder cross-tab. |
| L7 | Restart mid-hold: after next HA restart during ANY house_state, BLE-held rooms re-admit on first post-restart tick (D-MEDIUM-1 pin preserved; fail-open under both levers). | A+B | recorder around next restart. |

Every "PASS" row cites the observed entity/attribute value or DB row — per README write-back rule.

---

## 8. Tier 2-DB review plan (three framing-disjoint reviews + live)

Elevated to Tier 2-DB per operator standing policy for regression-prone work; framings adapted to a strategy/fusion change with TWO composed levers.

- **Review A — local correctness + edge cases + concept-split integrity, per lever.** Verify the sleep-family gate (Lever A) and the MAX cap (Lever B) each implement their piece of the invariant in §4 for every combination of {house_state ∈ sleep-family / not}, {chain_unbroken T/F}, {body signal fresh in WINDOW / fresh in MAX only / stale beyond MAX / None}, {BLE person present T/F}, {restart T/F}. Confirm the AND composition (`body_within_max AND body_within_window` in sleep) is correct — a room stale beyond MAX must drop in sleep even if paradoxically fresh in window (unreachable in practice; verify predicate handles it). Fail-open on missing body-signal state is intentional under BOTH levers — verify it matches D-MEDIUM-1.
- **Review B — cross-coordinator + precedence + no-flap + boundary.** Enumerate every consumer of `STATE_OCCUPIED` and `STATE_OCCUPANCY_SOURCE=="ble"` for master-bath and confirm neither lever induces flap (drops followed by re-creates within seconds), does not fight the D2 fan block, and does not interact adversely with zone roll-up, HVAC preset selection, or regime_detector rows. Confirm the sleep-family boundary (`HOME_DAY→HOME_NIGHT`, `HOME_NIGHT→WAKING`, `WAKING→HOME_DAY`) behaviour per §3.1 — specifically that an at-transition A-drop (body already stale entering sleep) is correct and NOT flap. Confirm Lever B's since-last-body clock is measured against absolute elapsed time and is unaffected by house-state transitions.
- **Review C — test authority + mutation + real-vs-mock body-signal + day/cycle boundary.** Verify every new test drives production source (source-extracted block per existing harness). Verify all four mutation anchors go red on the specified mutations, subprocess-isolated with `.pyc` cleared. Verify no test couples to wall-clock (both levers use time deltas — fixtures inject `now`). Verify T-BLEED-B2 and T-BLEED-A2 are REAL discriminators (a mutation that neuters the corresponding lever must fail them; a mutation that neuters the OTHER lever must NOT fail them — proves lever independence). Verify the mmwave tracker is wired at the upstream fold site the D2 block reads (grep the fold site, confirm one write, confirm no double-count).

**Orchestrator independent verification before ship (borrowed Tier-3 discipline as belt-and-braces on a delicate primitive):** re-grep for `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout` — MUST show only the BLE-extend site inside the new gated branch. Re-grep for writes to `self._last_mmwave_time` — MUST show init + exactly one fold-site write. Re-run all four mutation drills by hand.

**Live Validation (Review D):** post-restart, run L1–L7 in §7 against the running instance; write results back into `README_v<version>.md` per the mandatory write-back rule.

---

## 9. Files touched (all others read-only)

- `custom_components/universal_room_automation/const.py` — two new constants (A window, B max).
- `custom_components/universal_room_automation/coordinator.py` — the BLE-extend block at :3713-3722; two helpers (`_in_sleep_family_house_state`, `_body_signal_within`) near `_d2_house_state_allows`; `self._last_mmwave_time` init + one upstream fold-site write.
- `quality/tests/test_ble_extend_not_create.py` — extend with T-BLEED-A1/A2/B1/B2/BOUNDARY/MMWAVE/RESTART and four mutation anchors. (No new test file — same harness authority.)
- `docs/readmes/README_v<version>.md` — pre-deploy write, post-deploy Live table write-back.

Read-only during this plan (verified surfaces only): `person_coordinator.py`, `presence_coordinator.py`, `regime_detector.py`, `presence_fan_recheck.py`, `house_state.py`.

---

## 10. Baked-in defaults (Rev 2 — previously open questions closed)

Per operator direction 2026-09-01, the three Rev-1 open questions are resolved and baked into this plan:

1. **Corroboration window (Lever A) = 900s (15 min).** Reasoning in D1.
2. **Body-signal set = PIR OR mmwave age.** New `self._last_mmwave_time` tracker added; `_body_signal_within` accepts either. Rationale in §1.1 (robustness across rooms whose primary body signal is mmwave, not PIR).
3. **Fail-open on missing body-signal state (boot/restart).** Both levers fail-open when trackers are unset. Matches BLE-WARM-CREATE-1 D-MEDIUM-1 restart-pin philosophy. Prevents a boot transient from dropping a real hold before sensor history exists.

**Lever B default = `BLE_SOLO_EXTEND_MAX_S = 4h`.** Reasoning in D1. Both knobs remain module-constant rung (reviewed change only) per Numbers-Get-Knobs — they are fusion-safety thresholds, not per-deployment tunables.
