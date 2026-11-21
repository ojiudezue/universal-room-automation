# v5.108.20: Perimeter gate evidence (Part A)

PATCH. Branch `feature/perimeter-gate-evidence`, merged to develop 2026-11-13.
Reviews: A, B (SHIP), C mutation (SHIP), D cross-work reconciliation with crossing vision (no conflicts).
Pre-merge gate: full mutation name-diff vs 528fb5d9 0 NEW; D7 hygiene 58 passed; isolated run 18 files 0 failing.
Plan: `docs/planning/PLANNING_perimeter_gate_evidence_and_input_health.md` (Part A only; Part B / D4 is a
separate cycle). Cards: PERIMETER-ZONE-AGREEMENT-FIX-OR-REMOVE-1 (daylight + vlm_location residuals),
PERIMETER-GATE-DECISIONS-NOT-PERSISTED-1.

## What changes

- **D1 — single-source demote only in daylight.** The D5 gate (`switch.ura_perimeter_single_source_demote`)
  no longer lowers a first alert to LOW after sunset. Sun below 0° or unreadable means no demote, no 8 s
  hold. If the sun sets during the 8 s hold the alert keeps its severity (`night_after_settle`). Night alerts
  still feed the agreement tracker.
- **D1b — same rule on door cameras.** The D10.5 "unknown, uncorroborated, other NVR live" demote
  (`egress_uncorroborated`) applies only in daylight; at night the reason is `egress_uncorroborated_night`,
  the alert goes out at full severity, and the "that was <name>" follow-up can fire. Known-person
  de-escalation is unchanged.
- **D2 — every gate decision is a DB row.** `memory_episodes`, `episode_type = perimeter_gate_decision`,
  one row per decision (D3 zone, D5, D6, D10.5, follow-up), carrying sun elevation and is_day. ~100-300
  rows/day (1-3 per alert), ~30-90 MB/year, unbounded (no pruning of `memory_episodes`); retention is carded
  as MEMORY-EPISODES-PERIMETER-GATE-RETENTION-1. `started_at` is UTC like the other episode writers;
  `attrs.at` keeps the local stamp. Weekly scorer: `ssh ha "python3 -" < scripts/probes/perimeter_gate_scorer_weekly.py`.
- **D3 — VLM location question: built, DARK.** The D0-B replay was a no-go (street recall 8/26 = 31%,
  g5 0/15; PERSON parity failed on 2 frames; 7 replies echoed "Line 1:"; max latency 4.18 s over the 4.0 s
  timeout; own-property bar passed). `PERIMETER_VLM_LOCATION_ASK` ships **False**: every select mode sends
  today's `_VERDICT_PROMPT`, byte-identical. Dark pending a better prompt/model; re-run D0-B first.

## Knobs (all rung 1, `const.py`)

| Knob | Default | Off / kill |
|---|---|---|
| `PERIMETER_SS_DAYLIGHT_ONLY` | True | False = all-hours D5 |
| `PERIMETER_SS_DAYLIGHT_MIN_ELEVATION_DEG` | 0.0 | 90.0 = never demote |
| `PERIMETER_EGRESS_UNCORROBORATED_DAYLIGHT_ONLY` | True | False = all-hours D10.5 |
| `PERIMETER_GATE_LOG_PERSIST` | True | False = no rows (also exempt the type from writer health) |
| `PERIMETER_GATE_LOG_TEARDOWN_TIMEOUT_S` | 5.0 | 0 = do not wait |
| `PERIMETER_VLM_LOCATION_ASK` | **False** (D0-B no-go) | True = shadow asks LOCATION |
| `PERIMETER_VLM_LOCATION_ASK_IN_ENFORCE` | False | True only after D0-B PERSON parity |

## Live validation — Validated 2026-11-21 (overnight soak exit, read-only)

Queries: `ssh ha sqlite3 -readonly` on the URA DB, 02:0x CST; logs via the HA MCP `ha_get_logs source=system`.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Rows flow | PASS | `memory_episodes` `perimeter_gate_decision` rows every day 11-14..11-20 (62, 61, 236, 119, 125, 76, 50); 729 rows total |
| L2 | Payload not sentinel-only | PASS | newest `single_source` row 11-20 23:26 UTC: camera `rear_ptz`, reason `single_nvr`, severity_before `HIGH`, nvr_family `protect`, sun_elevation 1.22, is_day true, inputs populated |
| L3 | Night rule | PASS | 11 rows with reason `night`, all `is_day=0`, 0 demoted; 0 `single_source` demotes with `is_day=0`. The 6 demotes (g5_bullet 4, back_yard 1, pool_equipment 1) were all daytime |
| L4 | D1b at night | not observable | 0 `egress_identity` gate rows in the window |
| L5 | D3 dark | not checked | — |
| L6 | Scorer runs | PASS | `scripts/probes/perimeter_gate_scorer_weekly.py` printed the per-camera table (729 rows since 11-14 08:05 UTC) |
| L7 | No errors | PASS for the current boot only | system_log has no `perimeter gate` or `unregistered` entries, but it holds only the boot since the 11-20 22:47 restart; earlier boots not scanned (not a week-wide all-clear) |

## Not done / deferred

- D0-A (night share of the 18 g5 candidates) and D0-B (VLM replay): orchestrator-owned; D0-B result above.
- Q4 (`select.ura_perimeter_vlm_gate` -> shadow): operator action; moot for location while D3 is dark.
- Part B (D4 camera-input stream health): separate cycle.
- The 11-09 07:24 daylight own-property case is NOT covered by D1 (PERIMETER-FP-GATES-DISPOSE-1).
