# URA v5.84.0 — Fan-interference recheck actually works now (5-day-old deadlock fixed)

The fan-interference recheck — the mechanism that pauses a fan to test whether a room's mmWave
presence is real (fan-shake) or a person — **had never worked.** This fixes the deadlock that
prevented it from ever arming, so it can finally clear fan-ghosted rooms.

## The bug this closes (confirmed live)

Two mechanisms target the same fan-ghosted, mmWave-sole rooms and **deadlocked**:
- **D2 mmWave-fan demotion** (`MMWAVE_FAN_CORROBORATION_ENABLED`, default on) sets `occupied=False`
  for exactly these rooms (`coordinator.py:3451`).
- **The fan-recheck** needs `occupied=True` to leave `idle` and arm (`presence_fan_recheck.py:378`);
  D2's "defer to the recheck" guard only yields once the recheck is *already* running.

So D2 stripped occupancy every tick before the recheck's 60s arm could read it → the recheck never
armed → D2's deferral never engaged. **Live proof:**
`sensor.living_room_living_room_fan_recheck_state` = `veto_counts:{not_occupied:1}`, `eval_count:1`,
last real arm 2026-08-13, **never once vacated a room.**

**Why it shipped broken and lived 5 days:** the test suite drove a hand-fed `_FakeRoomCoord` with
`occupancy_source` hardcoded — it never exercised the real occupancy-source production where the
deadlock happens. A hollow anchor.

## What shipped

**D1 (the fix) — D2 defers to the recheck for recheck-eligible rooms.** New read-only
`FanRecheckManager.is_recheck_eligible(room)` is OR-composed into D2's pre-demotion guard
(`if recheck_in_flight or recheck_eligible: skip`). Now D2 yields → within ≤60s the recheck arms →
`recheck_in_flight` keeps D2 deferred through arm+pause+window → the recheck can finally **vacate**
a fan-ghosted empty room (bounded T ≤ ~210s). Every ineligibility path returns `False` → D2 fires as
the backstop, so **no inverse deadlock** (a real fan-ghost the recheck can't clear still gets
demoted — verified across all 9 gates + all recheck terminal states).

`is_recheck_eligible` is **side-effect-free** via an inert-sink refactor of the eligibility
evaluator (the live path keeps all 15 veto-counter writes; the probe path suppresses every one),
mutation-anchored by a purity test.

**D2 (secondary) — sleep-veto scoped to bedrooms.** The recheck's house-wide `SLEEP` veto is
narrowed to `house_state in FAN_TRUST_STATES and room_type == BEDROOM` (reusing the v4.7.13
keep-bedroom-fans-on predicate), so empty **non-bedroom** rooms get rechecked during sleep while the
bedroom keep-on contract is byte-preserved.

**D3 — per-room loop isolation.** The per-room recheck fan-out shared one `except→DEBUG`, so one
room raising silently skipped all rooms after it. Now each room is isolated (`try/except` at
WARNING), proven by a real behavioral test (extracted injectable helper, mutation-drilled).

## Review

Tier 2-DB: plan → plan review (PLAN-READY) → build → **3 framing-disjoint reviews all SHIP**
(A correctness / B integration+state-machine: *deadlock-break proven, no inverse deadlock* /
C test-authority) + F-C-2 hollow-test fix. 58 tests, purity + sleep-scope + D3 mutation-drilled.

**Test-authority note (honest):** the end-to-end *deadlock-broken / room-vacates* behavioral proof
could **not** be built in-suite — it needs a real `UniversalRoomCoordinator`, which re-opens the
v5.8.0 setup-RecursionError incident. Review C adjudicated this seam as **real and acceptable**: the
bug was confirmed *live* (not in-suite), and the fix is *live-observable* via the same
`fan_recheck_state` sensor. So the authoritative behavioral proof is the live-validation below.
(`is_recheck_eligible`, purity, sleep-scope, and D3 are all real in-suite tests.)

## Acceptance criteria — LIVE VALIDATION IS THE BEHAVIORAL PROOF (Review C spec)

Requires occupancy (a real fan-ghost episode). Watch `sensor.<room>_fan_recheck_state`:

**Fix works (O1–O6):**
- O1: `fan_recheck_eval_count` increments (was frozen at 1).
- O2: `veto_counts.not_occupied` climb rate drops ≥10× (D2 no longer starves it).
- O3: state reaches `IDLE → ARMED` on a fan-ghosted room (never happened before).
- O4: a real `fan_recheck_release` / vacate provenance appears on an empty fan-ghosted room.
- O5: DEBUG log `D2 defer → fan-recheck-defer:eligible` emitted.
- O6: D3 — a per-room recheck exception logs at WARNING and does not skip sibling rooms.

**Fix doesn't over-defer (O7–O8, the discriminators):**
- O7: a **bedroom** during sleep still gets D2-demoted, with `veto_counts.sleep_state` climbing
  (proves the probe returned False and D2 fired as backstop — not a naive "always defer").
- O8: a room with its fan **off** still gets demoted (proves the probe answers per-room, not
  universally True).

## Live Validation

_Pending — staged, deploy HELD for non-hostile timing (residents asleep at build time; an HA
restart is a ~5-min whole-house outage). L-observations O1–O8 to be captured on the next real
fan-ghost episode post-deploy and written back here._
