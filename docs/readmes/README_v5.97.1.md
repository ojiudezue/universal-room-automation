# v5.97.1 — Exit identity: name BOTH co-departers (reconciliation)

**Card:** EGRESS-EXIT-COMULTI-DEPART-1. Accuracy upgrade to the v5.96.1 exit producer. **Tier:** 2 — plan-review (2 CRITs fixed in-plan) + 3 framing-disjoint build reviews (A ship / B B1 / D D-1 HIGH) + 2 fix-ups + orchestrator mutation-verify.

## Problem
v5.96.1 abstained (left `person_id` NULL) whenever >1 person departed together — the common family case — to avoid a wrong-name swap. But each resident carries their OWN bluetooth_le tracker, so two people leaving produce two distinct, self-identifying `not_home` edges: the WHO is certain per edge; only the camera-row binding is uncertain. We were dropping a solved who-problem as if it were an assignment problem.

## Solution — reconciliation, not a confirmation matrix
Each admissible BLE `not_home` edge names its OWN resident, claiming a distinct null exit row via a retry-claim loop (the SQL `IS NULL` guard is per-write, not per-claim, so on contention the edge re-SELECTs the next unconsumed row). Two co-departers → both named. The departer set = `dedup(BLE edges ∪ face-named crossings)`; we do NOT enumerate the who-confirmed-by-what matrix — set-correctness is the guarantee, row-binding is best-effort (a same-time different-door swap mis-binds person↔door but never person↔departed; almost no consumer joins person↔door). Exit naming now has three paths: **face at the crossing (real-time, primary), BLE edge (backfill fallback), both agree (higher confidence).**

Hardened across reviews:
- **Flap guard (D-1 HIGH — wrong-WHO):** the settle that confirms a durable departure is 300s (was mistakenly cut to 90s in a fix), so a multi-minute Bermuda BLE flap (resident home-asleep, tracker drops not_home then back) can NOT name a resident who never left. RED-on-neuter tested on the duration.
- **Co-departer coverage (B1):** retry budget 6 (household-sized) so a 4-person simultaneous departure names all four.
- **Case-2 disagreement:** a genuine face-vs-BLE same-row conflict keeps the real-time face name, records `ble_exit_row_lost_count` (honest name), never silently drops or overwrites.
- Honest counters (the kept ambiguity counter is wired to the map-drift drop; DB errors no longer pollute the contention counter).

### Acceptance
- **Test:** co-departure (2 and 4) names all; flap-within-settle aborts (no wrong-WHO); each edge names its own slug; Case-2 no-overwrite. Each RED-on-neuter.
- **Live:** a family leaving together → each resident's exit row named; a resident whose tracker flaps not_home while home is NOT recorded as departed.

## Non-goals
Precise person↔door row-binding under simultaneous different-door co-departure (best-effort; set-correct). True face-vs-BLE provenance discrimination on the disagreement counter (follow-up). No confirmation-matrix branching.

## Live Validation — Validated 2026-10-16

Source: `docs/planning/AUDIT_exit_backfill_d0.md` (read-only D0, 2026-10-16). Recorder covers 2026-10-08 09:12 UTC onward (~7.5 days); counters reset on restart, so the figures are **lower bounds**. journald was not reachable, so per-row log lines were not read.

| Criterion | Result | Evidence |
|---|---|---|
| Backfill path alive after the retry-claim change | **PASS** | `ble_exit_backfilled_count` ≥11 in 7.5 days on `sensor.universal_room_automation_persons_in_house`. `ble_exit_error_count` 0, `ble_exit_backfill_noop_count` 0 (retry budget never exhausted). |
| A real co-departure names both residents | **as-expected (inferred)** | Two backfill increments in the same recorder minute, 2026-10-12 15:36 UTC, consistent with two residents leaving together and both being named. Not confirmed row-by-row (no log access, no spot check). |
| Concurrent writer never overwritten | **as-expected** | `ble_exit_row_lost_count` = 2: two edges found their row already named and left it alone (keep-face rule). |
| Flap while home never names a departure (300 s settle) | **as-expected** | `ble_exit_flap_aborted_count` ≥15. No row-level wrong-WHO check was run (the 5-row spot check is still open). |

Named exits by person (14 d): oji_udezue 21, jaya 19, ezinne 15, ojini 4; 154 null.
