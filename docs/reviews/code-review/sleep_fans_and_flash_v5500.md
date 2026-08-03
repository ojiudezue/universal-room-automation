# Sleep-Onset Fans + Warning Flash (v5.50.0) — Tier 2-DB Review Record

Revives the operator-removed 2026-06-11 sleep_occupied_activate with both
original objections addressed (72°F temp gate; v5.48.0 manual-intent
cooldowns). Build 03f5195a3 + mid-flight operator contracts (both-tier
coverage; running fans untouchable; ladder speed) + experience-hardening
(flap-proof latch, stagger, manual-off both tiers, config temp source,
activity rows). Fix-up 5841e05d0.

| Sev | Finding | Source | Disposition |
|---|---|---|---|
| HIGH | Boot/restart during sleep = false onset edge; lost (unpersisted) manual-off cooldowns → wife-incident class via the boot door | A | FIXED — observed-transition gate (prior != "") both tiers + boot tests |
| MED | Code shipped fixed LOW/MED speeds; operator-communicated contract was temp-delta ladder | A (adjudicated: behavior fix) | FIXED — shared ladder mapping, policy-capped; mutation-red |
| MED | Latch shadowed by re-arm guard — latch-neuter left flap tests green | B + C independently | FIXED — isolating tests (re-arm neutered) + converse re-arm red, both directions |
| HIGH(C) | Latch-on-skip contract untested (cool-at-bedtime room latches; warm-up must route via temp path) | C | FIXED — 2 tests pin skip-latches + trigger attribution |
| MED | Stagger unanchored (single-room fixtures) | C | FIXED — 2-room fixture, sleep-recorder, red on stagger removal |
| MED | Cross-tier exactly-once untested with dual fixture | C | FIXED |
| MED | check_auto_off_warning test was #62 hybrid | C | FIXED — production-driving (honest pollution-skip disclosed) |
| CLEARED | Inline stagger sleep inside update() — SAFE: decision-cycle lock holds; async_call_later would break the no-overlap contract | B | Keep as built |
| LOW | Switch-relay flash opt-out per room | B | BACKLOG B-2026-08-03-8 |

## Orchestrator drills
Running-fan guard neutered → 1 red. Boot-edge guard removed → 1 red.
Threshold gate removed (aimed at the real code line after two mis-aimed
attempts hit docstring/comment text — drill hygiene lesson: verify the
mutation landed on executable code) → 4 red. Byte-restored; 42/42 clean.

## Suite
42 cycle tests; full 19-failure baseline, zero drift (8102 passed).
