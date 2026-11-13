# v5.108.18 — Garage lockout no longer releases on body evidence alone

Card: LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1. Plan: `docs/planning/PLANNING_lock_release_on_arriving.md` rev 3.
Reviews: `docs/reviews/code-review/v_lock_release_arriving_{A,B,C,D}.md`. Tier 3, operator go 2026-11-13.

## What was wrong

The lock regime released the garage lockout whenever the house entered ARRIVING. ARRIVING fires on any occupancy after
AWAY, including a phantom zone sensor, so body evidence with no resident could unlock the house.

## What changed

- **ARRIVING holds.** An engaged lockout stays locked on ARRIVING (`arriving_hold`) unless an operator override drives it.
- **Taint.** An episode that passed through ARRIVING is tainted; a later HOME_* release is held unless an override or a
  resident arrival edge releases it. WAKING still releases only after a sleep-like engage.
- **D3 trip-wire.** A house-state release inside a tainted episode pages.
- **D4 pages.** Still locked after a resident arrival, and returns the regime could not count, page.
- **Boot.** The boot gap pages (D-L2); `garage_reason` persists across restart (D-H1).
- The morning backstop is never cancelled by an arrival, so a sleep episode always ends the same morning.

## Notes

- **Override includes services (B-I3).** "Override" means any `override_set`: the house-state select, the
  `ura.set_house_state` service (including HA automations calling it) and the boot restore of an operator override.
  All of them release.
- **Vacation phantom sleep (D-L3), accepted residual.** On a real vacation a phantom sensor can walk the house into SLEEP;
  the next WAKING releases. Carded LOCK-VACATION-PHANTOM-SLEEP-DAILY-UNLOCK-1; it matters only with the lockout ON.
- **Lockout unavailable at setup (D-L4), pre-existing.** Carded LOCK-BOOT-LOCKOUT-UNAVAILABLE-AT-SETUP-1.
- **Revisit on reshape.** When HOUSE-STATE-FIRST-PRINCIPLES-1 step 1a lands, this moves onto the new arrival signal and
  the taint workaround retires.

## Tests

`test_lock_release_arriving.py` (111). Full suite 21091 passed, 0 new failures. Orchestrator mutation drills
2026-11-13: removing the taint hold turns 20 tests red; making ARRIVING release turns 50 red; both restored clean.

## Validated 2026-11-13

Restart 08:48 CST with the house AWAY (`update.universal_room_automation_update` installed `v5.108.18`).

| Criterion | Result | Evidence |
|---|---|---|
| Loads without errors | PASS | `/api/error_log` has no URA or lock-regime ERROR or Traceback |
| `arriving_holds` visible | NOT EXPOSED | The counter is internal; no entity attribute carries it. Proven in-suite only |
| Hold on ARRIVING | PENDING (lockout OFF) | `switch.ura_security_coordinator_garage_lockout` is off, so no live decision can occur. In-suite: 111 tests plus the orchestrator mutation drills |

Revisit when the operator turns the lockout on (about 11-16): the next ARRIVING should log `arriving_hold`.
