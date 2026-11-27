# Review: EC-PREONSET-REASON-NARRATION-1 (unreleased, commit 1146d07c1)

Tier 1, framing A (local correctness and blast radius). Diff base: `develop...origin/fix/ec-preonset-reason-narration`. No pytest run (the orchestrator runs the name-diff).

## Verdict: SHIP

## Findings
| ID | Sev | Location | Finding | Bug class |
|---|---|---|---|---|
| A1 | LOW | energy_battery.py:7759 | When the floor is narrated, the `+ pre-onset floor {_folded_reserve}` suffix is suppressed. Folded equals the narrated floor on both legs: on the drain leg reserve_level is drain_target, which equals the floor. On the hold leg soc <= floor, so hold_reserve is the floor. The two can differ only if `_reserve_action` clamps the value, which is display-only. No real information is lost. | Narration drift |
| A2 | LOW | energy_battery.py:7355 | "storm floor" also labels the partial_hold floor from non-storm alerts (Freeze Warning, condition-only watch) and from blind holds. full_hold returns before this point. The label is cosmetic; it could say "hold floor". | Label accuracy |

## Checks
1. No behaviour change: PASS. `_base_drain_target` is read only by the narration. drain_target, hold_reserve, the stamp and mode are untouched.
2. Byte-identical when the floor is None or <= base: PASS. The else branch gives the legacy text, and tests cover floor None, equal and lower.
3. Suffix guard: PASS. `"storm floor "` is produced at exactly one place (7355), so the guard can't swallow another reason's suffix.
4. `_registered_floor` label: see A2.
5. Reason-text parsers: none found in custom_components (grep of `storm floor` and reason startswith/split near target or floor).
6. Golden fixture: PASS. Only `reason` lines changed (24, all "storm floor 60% (drain target 15%, good ...)"), consistent with floor 60 > base 15.
7. Test anchoring: PASS. The tests assert exact strings, which fail on revert. The Stage B test asserts the suffix is absent and the reserve writes are >= 80.

## Stats
| Sev | Found | Fixed | Deferred |
|---|---|---|---|
| CRIT/HIGH/MED | 0 | 0 | 0 |
| LOW | 2 | 0 | 2 (optional) |
