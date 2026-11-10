# v5.108.4: HVAC evidence-rule shadow recording (display only)

Card: `HVAC-GUEST-EVIDENCE-RULE-1`, phase 1. Operator approval 2026-11-10 ("HVAC recording ok").
Plan: `docs/planning/PLANNING_hvac_evidence_shadow_recording_2026_11.md` rev 2. Plan review: `docs/reviews/code-review/PLANREVIEW_hvac_evidence_shadow_recording.md`.
Tier 2-DB: three framing-disjoint reviews (A data integrity and DB, B INV-SHADOW and lifecycle, C per-site mutation and the verdict query fixture), then live validation.

## What changes

**Nothing HVAC does changes.** No thermostat write, preset, retreat, exit timer or sweep reads anything this release adds.

**What is new is a recorder.** Today the HVAC evidence rule (a room is HVAC-occupied while it has evidence, plus a short per-type hold after the last evidence) is live only in `home_day` / `home_evening`. Every other house state uses the older lighting-timeout tail. To decide later whether the evidence rule is safe in guest, sleep, away and the rest, URA now computes, on every producer pass in every house state, what the OTHER rule would have said:
- outside the evidence states, the evidence rule's answer (without the D5 entry wait and without the refresh-failure hold);
- in the evidence states, the old tail's answer, so `home_day` / `home_evening` give a reference rate measured the same way.

Per HVAC zone it records:
- **episode rows**: each time the two sides disagree for at least 60 s. `less` means the old tail holds the zone but evidence does not; `more` is the reverse. The outcome is `resumed` (evidence came back while the old tail still held, i.e. the evidence rule would have let the zone go too early), `released` (the old tail released too, including a release no pass saw because the person came back between passes), `flipped` or `interrupted` (house-state change or zone removed). Rows carry the rooms involved, plus any room that was pending on the D5 entry wait or had a failing refresh on any pass of the episode. The §7 query excludes those episodes.
- **exposure rows**: once per local day, the seconds each zone was occupied under the old tail, per house state. This is the denominator for "premature events per occupied zone-hour".

Nothing is recorded for 10 min after a restart (evidence stamps are empty until each room's first evidence). Episodes still open at a restart are lost, and so is the day's partial exposure. Both are accepted: the loss falls on every house state equally.

Rows go into a new table, `hvac_evidence_shadow`. They are batched (one `executemany` per drain) and pruned nightly at 180 days. Nothing is written to `ura_activity_log`, so the Last Activity sensor, the `ura_action` bus event and the logs websocket do not see them. No entity, attribute, switch, config field or signal is added.

**How to read it.** After a guest stay, `scripts/probes/hvac_evidence_shadow_verdict.py --db <db> --since <live date> --grace <knob 48 in s>` prints each house state as SAFE / NOT SAFE / INSUFFICIENT (rule in the plan §7 and the script's `--help`). Promoting a state is phase 2, a separate reviewed change.

## Knobs (all rung 1, `domain_coordinators/hvac_const.py`)
| Knob | Default | Why | Kill / edge |
|---|---|---|---|
| `HVAC_EVIDENCE_SHADOW_ENABLED` | `True` | Diagnostic recorder, turned at most once | `False` = no shadow work, no rows; the producer then matches the pre-build golden |
| `HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S` | `60` | Below a minute is pass jitter; under the 300 s grace, so decision-relevant episodes are kept | `0` = record all |
| `HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY` | `96` | Write-flood guard (2026-06-09 incident), ~10x expected | over it: one `capped` row, then that zone's episode rows stop until local midnight |
| `HVAC_EVIDENCE_SHADOW_RETENTION_DAYS` | `180` | Must outlast the wait for a guest stay; also purges a removed thermostat's rows | `< 1` clamped to 1 |
| `HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S` | `600` | First-evidence gap after restart, 2 ticks | `0` = no exclusion |
| `HVAC_EVIDENCE_SHADOW_MAX_ROOMS_PER_LIST` | `20` | Bounds a row's `details_json` | — |

## Files
- `domain_coordinators/hvac_zones.py`: E1 (shadow term computed before the legacy early return in `_evidence_rule_output`), E2 (per-pass room set), the zone tracker after the rollup, the daily exposure flush in `reset_daily_counters`, `drain_shadow_rows`. Live lines untouched.
- `domain_coordinators/hvac.py`: `_drain_hvac_evidence_shadow_rows`, called after each of the three `update_room_conditions` callers (boot, tick, fast run). Fire-and-forget, tracked task.
- `database.py`: table + index, `log_hvac_evidence_shadow` (batched), `prune_hvac_evidence_shadow` (batched DELETE).
- `nightly_maintenance.py`: prune registered.
- `scripts/probes/hvac_evidence_shadow_verdict.{sql,py}`: the settling query and its read-only runner.
- `domain_coordinators/hvac_const.py`: the knobs above.
- Docs: `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` header, §3.1, §4.3.

## Tests
- `quality/tests/test_hvac_evidence_shadow.py` (40): the INV-SHADOW golden (`golden/hvac_evidence_shadow_inv.json`, 150 passes over every house state, captured on the pre-build source `54a282b7`), compared with the recorder ON and OFF; D1 shadow terms; D2 tracker, exposure, boot window, unions, cap, zone removal; D3 table, batching, prune, nightly registration; D4 containment; D5 verdict-query branches on the real DDL.
- `quality/tests/test_hvac_evidence_shadow_drain.py` (5): each of the three drain call sites, driven through its enclosing method; no-database; sync and tracked.
- Per-site source mutations: 35 of 36 turn a named test red. The table is in the build report.

## Live validation (prospective; write the observed results back after restart)
| # | Criterion | How to check |
|---|---|---|
| L1 | Table exists, empty or growing; no other table changed | `SELECT name FROM sqlite_master WHERE name='hvac_evidence_shadow'`; `PRAGMA table_info` matches the plan D3 DDL |
| L2 | Within 24 h of restart: `episode` rows with `rule='night'` AND `rule='evidence'`; `exposure` rows after the first local midnight | `SELECT row_type, rule, COUNT(*) FROM hvac_evidence_shadow GROUP BY 1,2` |
| L3 | Discriminating: for one `less` episode in an evidence state, `started_at` matches, within one pass, the recorder flip of `sensor.ura_hvac_coordinator_zone_N_status` attribute `any_room_hvac_occupied` to false. A build reading the lighting denomination would be ~300 s off | recorder history of the zone status attribute vs the row |
| L4 | Volume within budget: < ~60 rows/day total, no `capped` row | `SELECT date(timestamp), row_type, COUNT(*) ... GROUP BY 1,2` |
| L5 | No actuation change: S1 `preset_change` and `climate_write` rates in the 24 h after restart are within normal day-to-day variation of the 24 h before | `ura_activity_log` counts by action |
| L6 | No `hvac_evidence_shadow` ERROR/WARNING in the HA log; no `ura_activity_log` row and no `ura_action` event for shadow rows | log scan; `ura_activity_log` has no new action names |
| L7 | First nightly maintenance runs the prune without error | log line `Pruned ... hvac_evidence_shadow` or none (nothing old yet), and no `Nightly hvac_evidence_shadow cleanup failed` |

Proven only in-suite: the INV-SHADOW byte-identity of every producer output (golden), restart and zone-removal handling, the cap, and every verdict-query branch.
