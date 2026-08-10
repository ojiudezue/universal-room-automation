# URA v5.66.0 — BLE extends occupancy, never creates it — now without the create window (BLE-WARM-CREATE-1)

**Tier 3** — occupancy hotfix shipped alone by design ("it's occupancy so go big on reviews and
quality"). Four framing-disjoint reviews, fix-up, operator-adjudicated invariant boundary,
orchestrator mutation verification.

## The problem

v5.22.0's invariant ("BLE may EXTEND a motion-confirmed occupancy but NEVER CREATE one") shipped
with a deliberate exception: the **motion leg** admitted a BLE-only occupancy *create* within
`BLE_MOTION_CONFIRM_MULTIPLIER × occupancy_timeout` = **10 minutes** of real motion, documented as
covering "the handoff tick where motion just timed out."

Measured 2026-08-10 (Master Bathroom, recorder attrs): two BLE creates at 09:53:32 and 10:19:35 —
`occupancy_source=ble`, `tier1_provenance` all-False, fresh `became_occupied_time`, lights on,
off again ~40s later. **Reproducible on every toilet visit**: the pass-through guarantees fresh
motion (warm window always open), the toilet sits inside the bathroom's BLE scanner footprint, and
Bermuda flap re-fires inside the window. v5.22.0 fixed the cold strobe; this was the warm strobe
it admitted.

Operator challenge that drove the fix: *"Why break the extend-but-not-create rule at all? It seems
like it created it, no?"* — correct. Adjudicated: (1) the handoff tick is already covered by the
chain leg, whose `_last_occupied_state` read is still True at the timeout tick (**mutation-proven,
not comment-trusted** — the build's go/no-go); (2) the still-body case belongs to the chain leg +
mmWave; the motion leg could not distinguish flap-recovery from adjacent-room BLE bleed.

## What ships

- **Leg (b) deleted** (`coordinator.py` BLE admission): `ble_allowed = chain_unbroken`, gated by
  `BLE_MOTION_CONFIRM_MULTIPLIER > 0`. The 10-minute create window no longer exists.
- **The invariant in falsifiable form, anchored**: parameterized tests assert BLE cannot create
  occupancy at ANY motion age (None, 1s, 60s, 119s, 120s, 121s, 540s). Reintroducing any window
  turns them red (proven — orchestrator reintroduced a 600s window by hand → 10 failures).
- **Constant re-documented**: in the BLE block `BLE_MOTION_CONFIRM_MULTIPLIER` is now a pure kill
  switch (MULT=0 disables the chain hold; magnitude ignored); in the D2 mmWave-fan demotion block
  it remains a real staleness multiplier. Dual role documented at both sites (follow-up carded to
  split it into a boolean + a D2 multiplier).
- **Four false-mechanism comments retired** (block header, seeding ordering note, const doc — plus
  one INTRODUCED by this cycle's own rewrite and caught by Review A: "collapses the D2 threshold to
  0" described the wrong kill mechanism; D2 dies at its outer guard, the arithmetic never runs).
- **D-MEDIUM-1 pinned (operator option 1)**: extend-across-restart is INTENDED — a restored
  `_last_occupied_state=True` + BLE present re-admits on the first post-restart tick with no
  in-process Tier-1 evidence. Carved out of the invariant explicitly and pinned by
  `test_pin_restart_midhold_chain_readmits_without_inprocess_tier1`; option-2 tightening must flip
  that test consciously, never weaken it silently.
- Unreachable fossil branch removed (B M-B1) with a tombstone comment.

## Review provenance

A (local correctness): SHIP, 1 LOW (the false-mechanism doc line above — fixed). B (integration/
lifecycle): SHIP — **boot regression ruled out**: `_last_occupied_state` restores but
`_last_motion_time` does not, so leg (b) was already inert on the first post-restart tick; the 24
PIR-only rooms' informed acceptance verified (worst case: lights off until movement, PIR recovers).
C (test authority): SHIP, **zero findings** — own drill reintroduced a motion leg → 6/7 anchors
red with `[None]` correctly green; only ONE `"ble"` occupancy-source write site exists. D
(adversarial completeness): invariant HOLDS across the diff surface; the v5.65.0 capability seam
is CLOSED (BLE_PRESENCE is corroborator-only, never injected into detection lists); one
pre-existing MEDIUM at the restart boundary → operator option 1, pinned.

Suite at merge: **22 failed / 8545 passed / 45 skipped / 2 xfailed** — failing names are the
pre-existing wall-clock-coupled families (winter-gate boundary class; count drifts 21↔22 with the
date). +1 = the pin test.

## Acceptance criteria

- **Live:** integration loads; zero URA errors post-restart.
- **Live (the founding case):** a toilet visit — walk through the Master Bathroom, sit — does NOT
  strobe the bathroom light on via BLE after bathroom occupancy times out. `occupancy_source=ble`
  with `tier1_provenance` all-False and a fresh `became_occupied_time` must not appear in the
  recorder for a cold room.
- **Live (chain preserved):** a genuinely occupied BLE-held room (still body, BLE present at
  timeout) keeps its hold — no regression to the v5.22.0 sleep-hold.
- **Live (restart pin):** first post-restart tick re-establishes a BLE hold for a room that was
  occupied pre-restart (intended, pinned behavior).

## Live Validation

### Validated 2026-08-10 (v5.66.0 boot ~11:2x CDT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | `system_log` ERROR search for `universal_room` empty post-restart; 190 URA sensors up; house_state `home_day` |
| L2 | Founding case — no BLE strobe on toilet visits | **ORGANIC (open)** | Master Bathroom currently `off / src=none` (correct — vacant). Proof = absence of any `occupancy_source=ble` + `tier1_provenance` all-False + fresh `became_occupied_time` row in the recorder for a cold room across the coming days of toilet visits. The invariant is mutation-anchored in-suite at all seven motion ages. |
| L3 | Chain-hold preserved | **PASS (live signal)** | Master Bedroom `on / src=mmwave` holding normally post-restart; v5.22.0 sleep-hold test unchanged and green in-suite |
| L4 | Restart pin — extend-across-restart intended | **PASS (in-suite; live by construction)** | `test_pin_restart_midhold_chain_readmits_without_inprocess_tier1` green; this very deploy exercised the restart path with no anomalous room drops observed post-boot |

Board gate: `--cards BLE-WARM-CREATE-1` marked shipped_organic v5.66.0 + vibememo entry written
inside the release flow (second live run of the BOARD-CURRENCY-1 gate). PR #495: 23 files,
+544/−196 (non-empty verified).
