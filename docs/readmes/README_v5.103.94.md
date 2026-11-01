# v5.103.94: Energy Coordinator restore no longer zeroes today's counters after a slow boot

Card: EC-DB-RESTORE-TIMEOUT-1. Tier 2 (reviews A correctness, B lifecycle; both MEDIUMs fixed). Deploy risk: LOW (changes only how the boot-time restore handles slow steps).

## Problem
The Energy Coordinator restored 14 things from its DB at boot under one shared 15 s timeout. If any step stalled (boot-time DB contention), every later step was skipped and it started from defaults: on 10-21 and 10-26 (2 of 19 restarts) today's import and cost reset to 0 until midnight.

## Fix
- Each restore step has its own 10 s limit (`EC_RESTORE_STEP_TIMEOUT_S`), inside a 45 s overall budget (`EC_RESTORE_TOTAL_BUDGET_S`; soft: a cancelled step's DB close can wait behind its 30 s lock). A slow step no longer skips the rest.
- Today's counters step (`midnight_snapshot`) gets one immediate second try before the first decision cycle. It now reads everything first and applies state only after all reads succeed, so a timeout leaves nothing half-set and the normal new-day path runs.
- Skipped steps that are safe to run late retry once after HA has started (billing cycle via reseed, peak import and bill ledger guarded, power profiles). Steps whose live values would be overwritten stay boot-only (EVSE, circuits, Envoy cache, load shedding, solar follow, today's counters).
- While the power-profile restore is skipped, profile saves are blocked so the stored history is not wiped.
- One-shot startup listeners remove their own handle when they fire (no teardown traceback).

## Tests
`test_ec_restore_per_step_timeout.py` (42), 23 mutation drills all RED. Full-suite name-diff vs 107f1400e: 0 new failures (22 pre-existing on both).

## Known limits
- If both tries of today's counters time out (a ≥20 s stall on that step), today's import/cost still reset until midnight.
- Worst-case coordinator setup in a stall grows from 15 s to ~45 s (plus a soft close wait); HA logs a slow-setup warning, nothing fails.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| Counters survive restart | `energy_import_today` / `energy_cost_today` after restart ≈ value before (not 0) |
| No restore ERROR | No "Energy DB restore timed out" ERROR; any slow step logs a WARNING naming it |
| Load clean | No URA ERROR after restart |
