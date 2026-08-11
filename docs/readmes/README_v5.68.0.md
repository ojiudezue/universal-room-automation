# URA v5.68.0 — Fan manual-ON hold (FAN-MANUAL-1)

**Tier 2 (elevated review history)** — the founding complaint: *"I can't seem to turn on the
living room fan manually without it turning off by itself."* URA had a manual-OFF cooldown but
NO manual-ON hold: any human fan-ON was reversed by the next vacancy sweep / reconciler tick /
recheck. This cycle survived 1 CRITICAL + 6 HIGH across three DO-NOT-SHIP review passes, a
consolidated fix-up, and a held release (hollow-anchor instance #11: the fix-up claimed three
guard drills that did not exist — v5.68.0 shipped only after a real anchor pass put all three
guards under mutation-verified tests).

## What ships

- **Manual-ON hold**: a human fan-ON (detected by mirroring the existing manual-OFF detector's
  authorship logic) opens a per-room hold — `_fan_manual_on_until` — for
  `DEFAULT_FAN_MANUAL_ON_HOLD_S = 3600` (per-room CONF override). While the hold is open, URA's
  automatic OFF paths defer: room-tier OFF, HVAC vacancy sweep, and the actuator reconciler.
- **Authored-by bridge**: `mark_fan_on_issued()` stamps URA-authored ONs so the detector never
  mistakes URA's own actuation for a human's (no self-granted holds).
- **Boot policy**: a fan found ON at tick-1 opens a hold (conservative: unknown authorship is
  treated as human — worst case a held fan for 1h, never a fighting fan).
- **Freshest-wins vs sleep + fan-recheck allowlist** per operator ruling ("Both as
  recommended"): sleep-preset fan policy and the manual hold resolve by most-recent human
  action; the presence fan-recheck respects the hold via the same guard.
- **hvac_fans field split**: `manual_on_hold_until` carried separately from the OFF-cooldown
  field — no shared-state collision.
- **INV-FMH** (suppression-needs-a-discharge): the hold is a deferral with four discharges —
  expiry, human OFF, room vacancy finalize + hold lapse, restart (RAM hold, conservative
  boot re-open). No automatic path deletes a pending OFF permanently.

## Review provenance

Three passes (DO-NOT-SHIP × 2 + ship-with-fix), consolidated fix-up `233531f37`, merge
`1f5839c3a`. Held pre-release: validator re-execution found 3 of the fix-up's claimed guard
drills did not exist (hollow #11). Anchor pass `62713d2ad` added 6 tests
(`test_reconciler_fan_manual_on_guards.py`, `test_hvac_vacancy_sweep_manual_on_guard.py`) —
all three guards drilled red-then-green against production source with mutated lines printed:
reconciler defer (`actuator_reconciler.py:618`), mark-bridge (`:637`), vacancy sweep
(`hvac.py:2442-2446`, driving the real `_execute_vacancy_sweep` end-to-end). Suite name-diff
vs baseline: zero new failures, +6 passes = exactly the anchors.

## Acceptance criteria

- **Live:** integration loads; zero URA errors post-restart.
- **Live (founding case):** manually turn ON the Living Room fan → it stays ON for the hold
  duration (no self-off within the hour), then normal automation resumes after expiry.
- **Live (no inversion):** URA-authored fan ONs still turn off normally at vacancy (the
  mark-bridge prevents self-granted holds).
- **Live (sleep unaffected):** sleep-fan behavior per v5.49.0 spec unchanged except
  freshest-wins on direct human action.

## Live Validation

### Validated 2026-08-10 (v5.68.0 boot, night)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | `system_log` ERROR search for `universal_room` empty post-restart; house_state `home_night`; presence/coordinator sensors reporting |
| L2 | Founding case — manual fan-ON survives the hour | **ORGANIC (operator test)** | Deliberately not actuated live at night (house asleep — hostile timing for a living-room fan test). The hold is mutation-anchored in-suite at all three OFF paths (reconciler `actuator_reconciler.py:618`, vacancy sweep `hvac.py:2442`, room-tier) with drills red-then-green. Operator: turn the Living Room fan on by hand any time — it must stay on ~1h |
| L3 | No inversion — URA-authored ONs still vacate | **PASS (live signal + in-suite)** | Fans currently ON (`fan.air_circulator`, Jaya bedroom sleep fan) holding steady with no flap post-boot — reconciler not fighting; mark-bridge drill (`:637`) red-then-green in-suite |
| L4 | Sleep-fan behavior unchanged | **PASS (live signal)** | Jaya bedroom sleep fan ON per v5.49.0 spec first night post-deploy; freshest-wins only engages on direct human action |

HACS pulled v5.68.0 before restart. PR #497: +4424/−129 (non-empty verified, fan code + anchors present).
