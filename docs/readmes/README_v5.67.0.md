# URA v5.67.0 — P24 failsafe made real (safely) + D3 deletion + capability dropdowns + constant split

**Tier 2-DB batch** — three framing-disjoint reviews returned A DO-NOT-SHIP + C DO-NOT-SHIP + B
ship-with-fix; a consolidated fix-up (`f07a90e4c`) closed every finding, Review C's own drills were
re-run to red, and the orchestrator independently drilled the critical guard.

## Item 1 — P24 max-active failsafe: from structurally blind to actually armed, without the trap

Measured (7.3d recorder): P24's duration precondition fired 27× and its Tier-1 freshness skip
suppressed **27 of 27** — a theorem, not a statistic (the check read `_last_motion_time`, which the
same tick had just written). Override-held rooms could never accumulate duration at all
(Ziri Bathroom: occupied 10.79h, max recorded session 1.10h).

**Shipped fix:** freshness re-based on `_last_pir_motion_time` (real PIR only); the
`_became_occupied_time` clear deferred into a TRUE VACANCY FINALIZE block so override-rescued
sessions keep their original start (Review A traced every reader in the deferred window — sound);
the failsafe NM now names room + duration instead of the bare `[audit]` sentinel.

**The two traps the reviews caught before the house did:**
- **CRIT-A1**: PIR-based freshness would have **force-vacated the six no-PIR rooms at every 4h+
  session** — a sleeping child in Jaya's mmWave-only bedroom, nightly. The "27/27 tautological
  suppression" was, for mmWave-primary rooms, the sleeping-body protection *working*. Fix: the
  failsafe now simply does not apply to rooms with no PIR (`_d2_motion_sensors_present()` guard),
  invariant stated in code, pinned per-room-class (4 parameterized tests; orchestrator-drilled).
- **HIGH-A2**: a live camera/BLE override now **defers** the failsafe (invariant: fires only when
  PIR stale AND no live override) — previously it would have force-vacated a visibly-present person
  and the `_failsafe_fired` latch would have locked the camera override out.

**Hollow-anchor instance #10 (Review C):** the build's original P24 "tests" were source-grep
assertions plus a `_should_fire` mirror — inverting the load-bearing branch left 38/38 green. All
replaced with extract-and-exec tests driving production source; C's drills 3/4/5 now go red.

## Item 2 — D3 frozen-tracker detector deleted

Operator: "Kill it." Structurally unreachable (threshold 2.0 days vs 1.01-day max uptime at our
deploy cadence — it could never catch the Ezinne incident it was built for). Detector, constants,
NM kind, sensor attribute, and the v5.35.0 Ezinne repro test all removed with tombstones; Review B
verified zero live references (code, translations, latches). `_stuck_signal_nm` untouched (other
kinds remain).

## Item 3 — Per-sensor capability dropdowns (senscap UX v2)

One dropdown per configured sensor in the room options (kind: motion/pir/mmwave/occupancy/bed/
camera_presence/ble_presence), defaulting to the effective kind; selecting the CONF-derived default
persists nothing (byte-identity). JSON textarea remains the escape hatch for trust_class/
failure_mode; dropdown wins on kind. **MED-B2 fixed in-cycle:** an unchanged save no longer strips
a JSON-declared `trust_class` (the Master bed's `strong_evidence`-style declarations survive).
Round-trip pinned by 4 tests through the real merge block.

## Item 4 — `BLE_MOTION_CONFIRM_MULTIPLIER` clean-break split

Gone (no alias, per single-install no-backcompat). Replaced by `BLE_CHAIN_HOLD_ENABLED` (bool kill
switch, BLE chain hold) and `D2_PIR_STALENESS_MULTIPLIER` (real multiplier, D2 mmWave-fan demotion;
0 kills at the outer guard). **HIGH-B1 fixed:** `HOUSE_MANUAL.md`'s six kill-switch instructions
referencing the deleted symbol rewritten — the live runbook no longer instructs a no-op backout.

## Acceptance criteria

- **Live:** loads, zero URA errors post-restart.
- **Live (CRIT-A1 guard):** no `max_active_failsafe` NM / force-vacant for any of the six no-PIR
  rooms across normal nights (sleeping occupants hold).
- **Live (P24 armed):** the failsafe CAN now fire where it should — a PIR room with genuinely stale
  PIR and no live override past its failsafe duration produces a room-named NM (organic).
- **Live (dropdowns):** Master Bedroom options show per-sensor kind dropdowns; bed defaults to
  `bed`; unchanged save persists nothing new.
- **Live (split):** `BLE_CHAIN_HOLD_ENABLED`/`D2_PIR_STALENESS_MULTIPLIER` present; BLE chain-hold
  behavior unchanged from v5.66.0.

## Live Validation

### Validated 2026-08-11 (v5.67.0 boot, evening)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | ERROR search for `universal_room` empty post-restart; 190 URA sensors; house `home_evening`; watchdog sensor present (frozen_trackers attr gone) |
| L2 | CRIT-A1 guard — no-PIR rooms never force-vacated | **PASS (live signal) + ORGANIC** | Jaya's Bedroom `on / src=timeout / failsafe_fired=False` post-restart. Organic proof = zero `max_active_failsafe` NMs for the six no-PIR rooms across coming nights; guard is 4×-parameterized + orchestrator-drilled in-suite |
| L3 | P24 armed where it should be | **ORGANIC (open)** | First genuine firing (PIR room, stale PIR, no live override, 4h+) will carry room + duration in the NM title — previously impossible |
| L4 | Dropdowns round-trip | **PASS (in-suite; live spot-check pending next options visit)** | 4 merge tests incl. trust_class survival (MED-B2); Master bed declaration intact in storage |
| L5 | Constant split behavior-neutral | **PASS** | BLE chain-hold behavior unchanged post-restart (master off/none is correct — nobody in room); split constants live; HOUSE_MANUAL corrected |

Note: this deploy's pre-commit board regen fired the **first organic rung-3 STALE banner** (README newer
than last_reconciled) — cleared by the `--cards` gate's own reconcile, exactly per the currency-ladder
design. PR #496: 31 files, +1764/−922 (non-empty verified). Third live run of the deploy gate.
