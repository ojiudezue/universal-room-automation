# URA v5.79.0 — Guest/census separation: guest rooms lead, the count corroborates

The cycle that stops GUEST mode from being a function of a decaying measurement — and,
in the course of proving it, discovered that guest mode's only identity safety check had
**never worked in production**.

**Review chain (Tier 2-DB escalated to a Tier-3 fuller pass):** plan rev-2 + plan review
+ 3 framing-disjoint build reviews (A SHIP / B SHIP-with-notes / C FIX-THEN-SHIP) + fix-up
+ **orchestrator-found HIGH in the fix-up itself** + operator-ordered **fuller pass (D/E/F,
all three DO-NOT-SHIP)** which found the dead oracle + **CRIT fix + re-review (D2/E2/F2, all
three SHIP)**. Six framing-disjoint reviews total. Nothing about this cycle was routine.

## The problem this closes

On **2026-08-16 the house sat in `guest` for 7 hours 2 minutes** (13:38:33 → 20:40:59)
with four known residents and zero guests. Measured from the recorder, the mechanism was:

1. **Census entry, not guest-room entry.** `guest_gate_armed` was an OR of Path A
   (census `unidentified_count`) and Path B (guest-room occupancy). Census hit 6 at
   13:38:03; the house flipped `guest` 30 seconds later. No guest room was involved.
2. **The count was wrong because the enhanced ADDITIVE derivation
   (`total = identified + camera_unrecognized`, default ON) overwrites the raw
   SUBTRACTIVE one**, while both of its dedup defences are inert — face recognition is
   effectively dead, and per-area BLE-cancel returns zero. Residents the cameras see are
   counted twice: census read up to **10 for 5 people**.
3. **Guest could not exit** while the count stayed elevated, because the exit predicate
   required `unidentified_count == 0`. Guest released 5 minutes after census finally
   reached 4 — seven hours later.

Measured decay constants that made a transient permanent: `CENSUS_PEAK_SUSTAIN_SECONDS=15`
to latch, `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES=3`, then `CENSUS_DECAY_STEP_SECONDS=300`
(−1 person per **5 minutes**). A 15-second phantom buys ~33 minutes of elevated count at
the observed peak — and the peak **self-refreshes when `fresh == peak`**, so a recurring
artifact never decays at all.

## What shipped

**D1 — clamp the additive path (`camera_census.py`).** `total` is bounded by the
**PRE-BLE-cancel** camera body count:
`clamped_total = min(identified + held_unidentified, max(camera_total_pre_cancel, identified))`.
The ceiling MUST be the pre-cancel scalar — plan review rejected rev-1's post-cancel
`camera_unrecognized` ceiling because it would suppress a *real* guest once dedup is
repaired. Regression-guarded by `test_clamp_repaired_defenses_preserves_guest`.

**D2 — invert the guest composition (`presence.py`).** Guest entry is now
`guest_armed = guest_room_gate_armed` — **guest rooms lead, the census does not arm at
all**. Path A remains as a diagnostic only. This is the change that makes the 7-hour
episode unrepeatable.

**D2b — decouple guest exit from the count.** Exit no longer requires
`unidentified_count == 0`; it is `current_state == GUEST and not guest_gate_armed`.
Without this, D2 would have made GUEST **terminal** (entry via rooms, exit gated on a
count that D1 predicts stays ≥ 2, with no alternative exit path).

**D3 — registry-based guest-room resolution.** Guest-room occupancy entities are resolved
via `entity_registry.async_get_entity_id(...)` on `f"{entry_id}_occupied"` rather than a
constructed slug. Verified live: this genuinely repairs **Upstairs Guestroom**, whose
pre-cycle slug did not exist.

**G2 — diagnostics.** `camera_total_pre_cancel`, `area_raw_max_pre_cancel`, `ble_by_area`,
`ble_cancel_enabled` on the census sensor, so a future debugger can tell *cancel-ran* from
*cancel-off* instead of guessing.

### Fix-up (post-review)

- **B-MEDIUM-1** — `_guest_room_state` is RAM-only. Pre-cycle a mid-visit restart re-armed
  guest in ~5 min via Path A; post-D2 only Path B arms, so a restart cost a genuine guest a
  fresh 30-minute window. Boot-seeds `first_seen` from the occupancy entity's `last_changed`.
- **HIGH (orchestrator-found, not by any reviewer)** — that boot-seed introduced a
  **false-guest path at boot**: a *resident* in a guest room with `person_coordinator` not yet
  populated seeded `first_seen` to hours ago, so the gate fired **immediately** on the first
  tick. Both claimed mitigations were the same event-driven mechanism (`current_occupancy_known`
  is only ever written inside the state-change listener) and both were inert for a resident
  sitting still. Fixed two ways: the gate now performs a **live identity re-check** at
  evaluation time (consumer verifies producer), and the boot seed is **clamped** so it can
  never be already-expired (`GUEST_BOOT_SEED_MIN_RESIDUAL_S`, rung 1).
- **C-MED-1 / C-MED-2** — two hollow test anchors. `test_unresolvable_room_warns` passed with
  the production WARNING deleted (variant-7: the string survived in a comment); now a real
  `caplog` behavioural test. `test_confidence_bump_when_both_gates_fire` anchored on a bare
  `"0.95"` substring; now regex-pinned to the assignment site.
- **A-LOW-1** dropped a masking `or 0`; **B-LOW-2** added a log-only canary on the
  D2-unreachable branch; **C-LOW-1** added the missing explicit negative assertion.

### The dead oracle (fuller pass — the real story of this cycle)

Because D2 makes the guest-room gate the **sole** arm for GUEST, the operator ordered a
Tier-3 fuller pass. Three more framing-disjoint reviews (D adversarial-completeness,
E lifecycle, F test-authority) **all returned DO-NOT-SHIP.** D and E independently found the
same CRITICAL by different routes, and it was **two distinct bugs in one 20-line helper**,
`_is_known_person_in_room` — the "is a *known resident* the one in this guest room?" check:

1. `manager.coordinators.get("person")` — the person coordinator is **never** registered in
   that manager; all 7 sibling call-sites in the same file use `hass.data[DOMAIN]["person_coordinator"]`.
2. `getattr(person_coord, "_tracked_persons", {})` — `_tracked_persons` exists **nowhere**;
   the real store is `person_coord.data[name]["location"]`.

It short-circuited on the first, masking the second. The consequence: the "known person →
don't treat as guest" disarm had **never fired since v4.7.2**. Harmless while guest entry was
`census OR rooms`; about to become **false-guest-on-residents** the instant D2 made rooms the
sole arm. This was **live, not latent** — the house has designated guest rooms (see below),
so any 30-minute occupancy of one, by a resident, would have armed GUEST. It very likely
explains the measured finding that **72% of guest minutes carried `unidentified_count == 0`**:
Path B firing on residents through the dead check, with no census involvement.

**CRIT fix (`_is_known_person_in_room` repaired):** canonical `hass.data[DOMAIN]["person_coordinator"]`
lookup + real `data[name]["location"]` shape (vocabulary verified live: person `location`
values are `CONF_ROOM_NAME` verbatim). Plus a **sticky latch** (`GUEST_KNOWN_STICKY_S`, 120 s)
because BLE room-location **flaps** (prior art: Jaya Bedroom on Bermuda noise) — without it, a
flap during the gate re-check would fire GUEST on a resident. All four drills red-then-green,
including both revert-drills (each original bug independently caught). Re-review D2/E2/F2 all SHIP.

**F2-MED-1 (oracle-echo, Bug Class #64 — the third variant coined this cycle):** the
sticky-latch test derived its expiry window from the production constant, so it passed for
any value including the kill-switch. De-echoed to a test-local literal + a contract assertion;
drilled (constant→0 now fails the named test).

### Config correction (done, not code)

A **bathroom** — "Down Guest Bathroom" (`room_type=bathroom`) — was flagged `is_guest_room=True`,
a misconfiguration the operator caught. Under the dead oracle that meant any 30-minute bathroom
occupancy armed GUEST — the worst possible member of the designated set. **Unflagged.** The
designated set is now exactly **Guest Bedroom 1** and **Upstairs Guestroom** (both bedrooms).
Pre-deploy check confirmed both resolve `location == CONF_ROOM_NAME` for present residents, so
the repaired exclusion is live for them (`GUEST-ROOM-LOCATION-MATCH-1`).

## Knobs

**Two new, both rung 1 (module constants), no config-flow fields, no new entities:**
- `GUEST_BOOT_SEED_MIN_RESIDUAL_S` (300 s) — minimum dwell that must remain after a boot-seed,
  so an erroneous seed can never fire instantly. Kill-switch: `≥ threshold` disables the seed;
  `0` disables only the clamp.
- `GUEST_KNOWN_STICKY_S` (120 s) — sticky-latch window absorbing BLE room-location flap in the
  identity re-check. Kill-switch: `0` disables the latch (base check still runs).

Both rung 1 because they are safety margins on the sole guest-arming safety check; changing
either should require review.

## What this cycle does NOT fix — read this before judging the count

**The census number is still wrong.** D1 bounds the additive path to the camera body count;
when that body count is *itself* inflated — which tonight's data says is the common case —
**the clamp is a no-op**. Review A's per-value table at tonight's live inputs (identified=4,
held=6):

| `camera_total_pre_cancel` | emitted total / unidentified |
|---|---|
| 0 / unset / 4 | 4 / 0 |
| 5 | 5 / 1 |
| 6 | 6 / 2 |
| 10 | **10 / 6** |

`total ≥ identified` is arithmetically guaranteed, so the count can never drop below the
people we can name. But **expect the headcount to still read high after this deploy** — this
cycle fixes GUEST MODE, not the count. Interior count accuracy is the next cycle
(`CENSUS-ACCURACY-1`): the decay/self-refresh separation (a measured **74.5%** of over-count
time was the decay tail with no live camera evidence) and the `_2`-suffix fresh-face
resolution fix (fresh-face `−1` has fired **zero** times in 7 days — a missed Frigate-1→2
migration residue). A separately-measured probe **rejected** the original dedup-repair scope:
per-area BLE-cancel is not broken code, it is camera-area coverage (an operator config task).

## Acceptance criteria

Every criterion below is written to **discriminate** — to distinguish this fix from a
plausible different failure. The v5.78.0 cycle was masked precisely because its criterion
("census exceeds identified") was satisfied by both the fix and a fresh bug.

- **Test:** `test_guest_census_correctness.py` (D1/D2/D2b/D3 + boot-seed + oracle-repair
  regression suite). **Authoritative baseline-diff:** develop = 25 failed / 9161 passed;
  cycle tip `9cae3c9d5` = 25 failed / 9193 passed; regression name-diff **EMPTY** (the 25
  failures are identical and pre-existing; +32 are the cycle's own new tests). One flaky
  board-state test (`test_real_board_idempotent_reship`) excluded — it depends on live kanban
  edits, not the cycle.
- **Live L1:** boot clean, zero URA ERROR lines.
- **Live L2 (the point of the cycle):** with residents only and **no guest present**, the
  house does **not** enter `guest`, *even while `unidentified_count > 0`*.
  Discriminator: `unidentified_count ≥ 1` with house state ≠ `guest` proves D2 is live. If
  the house is merely `home_*` because the count happens to be 0, the criterion is
  **not** satisfied — it must hold with a non-zero count.
- **Live L3 (the boot regression, directly observable on this deploy):** a resident is
  currently staging items in a designated guest room with occupancy `on`. After the deploy
  restart, the house must **not** flip to `guest`. Under the pre-fix code this fires within
  one inference tick; under the fix it must not fire at all.
- **Live L4:** `binary_sensor.upstairs_guest_bedroom_occupied` resolves and registers —
  log shows D3 registration, **not** the unresolvable-room WARNING.
- **Live L5 (count, honest):** census compared against **operator-stated ground-truth
  headcount**, never against `identified_count`. Expected outcome is **still over-counting** —
  recorded as a number, not a pass/fail, and carried into cycle 2/3 as the baseline.
- **Live L6 (organic, guest exit):** when a genuine guest leaves, GUEST exits on the room
  clearing, without waiting for the count to drain. Proves D2b.
- **Live L7 (organic, genuine guest entry):** a real guest in one of the two designated guest
  rooms (**Guest Bedroom 1**, **Upstairs Guestroom**) for ≥ 30 min arms GUEST. Proves D2 did
  not simply disable guest detection — the failure mode of over-correcting.
- **Live L8 (the dead-oracle repair — the headline of this cycle):** a **known resident** in a
  designated guest room for ≥ 30 min must **not** arm GUEST. Under the pre-fix dead oracle
  `_is_known_person_in_room` always returned False, so this would have armed. Discriminator vs
  L3: L3 tests the boot path (person_coord unpopulated); L8 tests steady-state (person_coord
  populated, resident's `location` resolves to the room). Both must hold. Evidence: with a
  resident's BLE placing them in the room, `sensor.ura_presence_coordinator_presence_house_state`
  stays `home_*`, and the boot INFO log shows the known-person verdict = True for that room.

## Live Validation

### Validated 2026-08-17 (~22:05 CT, post-restart) — house EMPTY (residents away until Wed PM)

**Context:** the operator confirmed the house is empty from 21:53 CT until Wed afternoon, and
that absence over this window is expected. The discriminating dead-oracle tests (L3, L8) require
a resident physically in a designated guest room, so they are **organic-pending** — the headline
correctness proof cannot be produced against an empty house and must NOT be claimed from it.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA ERROR | **PASS** | `system_log` ERROR count for `universal_room_automation`: 0. No `RecursionError` in error_log (v5.8.0 setup-crash class absent). |
| — | No setup crash / watchdog restart | **PASS** | All **42** URA config entries `state: loaded` (0 setup_error / setup_retry / not_loaded). The v5.8.0 incident crashed all rooms; here all loaded. |
| L2 | House does not false-enter guest | **PASS (weak — empty house)** | House reads `away`, `all_tracked_persons_away: true`, census 0. NOTE: with nobody home this is NOT the discriminating test (the dead oracle would not fire on an empty house either) — recorded as weak, not proof. |
| L3 | Resident staging in guest room does not flip guest at boot | **ORGANIC-PENDING** | Requires an occupied designated guest room; house empty. Re-check on return. |
| L4 | `face_recognized_count` + `path_alpha_gate_source` on house-state sensor | **PASS** | Attributes present: `face_recognized_count: 0`, `path_alpha_gate_source: "face_recognized_count"`. |
| L5 | Census vs ground-truth headcount | **N/A tonight (empty)** | census 0 for 0 residents present — correct but trivial. The over-count baseline needs occupancy; carried to cycle 2. |
| L6 | Guest exits on room clearing (D2b) | **ORGANIC-PENDING** | Needs a real guest visit ending. |
| L7 | Genuine guest arms GUEST after 30 min (not over-corrected) | **ORGANIC-PENDING** | Needs a real guest in a designated room ≥ 30 min. |
| L8 | **Repaired identity check excludes a known resident in a guest room** | **ORGANIC-PENDING (the headline)** | The discriminating proof the dead oracle is alive. Needs a resident in Guest Bedroom 1 or Upstairs Guestroom; boot INFO log will carry the known-person verdict. Re-check on return (Wed PM at latest). |

**Config correction verified live:** the designated guest-room set is now exactly **Guest Bedroom 1**
and **Upstairs Guestroom** (both `state: loaded`); **Guest Bedroom 1 Bathroom** loaded and unflagged.

**Deploy-machinery note:** BOARD-CURRENCY-1's post-push write path executed for real for the
first time on this release — `kanban_ship` marked the cards shipped and `vibememo_ship` wrote
entry 055 automatically. The forcing function is proven working.

**Cycle stays open until L3/L8 land** on resident return — a cycle is not closed until its
README carries the discriminating post-restart evidence, and here that evidence is occupancy-gated.
