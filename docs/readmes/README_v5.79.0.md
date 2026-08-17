# URA v5.79.0 — Guest/census separation: guest rooms lead, the count corroborates

The cycle that stops GUEST mode from being a function of a decaying measurement.
Tier 2-DB: plan rev-2 + plan review + **3 framing-disjoint build reviews** (A SHIP /
B SHIP-with-notes / C FIX-THEN-SHIP) + fix-up + **orchestrator-found HIGH in the fix-up
itself** + focused re-review.

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

## Knobs

**One new, rung 1 (module constant):** `GUEST_BOOT_SEED_MIN_RESIDUAL_S` — the minimum dwell
that must remain after a boot-seed, so an erroneous seed can never fire instantly. Rung 1
because it is a safety margin whose change should require review. **No new config-flow fields,
no new entities.**

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
people we can name. But expect the headcount to still read high after this deploy.
Repairing the camera body total is **cycle 3** (`CENSUS-DEDUP-REPAIR-1`); the latch/decay
asymmetry is **cycle 2** (`CENSUS-DECAY-SEPARATION-1`).

## Acceptance criteria

Every criterion below is written to **discriminate** — to distinguish this fix from a
plausible different failure. The v5.78.0 cycle was masked precisely because its criterion
("census exceeds identified") was satisfied by both the fix and a fresh bug.

- **Test:** `test_guest_census_correctness.py` (D1/D2/D2b/D3 + boot-seed regression suite).
  Suite baseline to beat: **9182 passed / 26 failed**, name-diff empty.
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
- **Live L7 (organic, genuine guest entry):** a real guest in a designated guest room for
  ≥ 30 min arms GUEST. Proves D2 did not simply disable guest detection — the failure mode
  of over-correcting.

## Live Validation

_To be completed post-restart. Per the mandatory write-back rule, this section is replaced
with a `Validated <date>` results table carrying observed evidence per criterion before the
cycle is closed._
