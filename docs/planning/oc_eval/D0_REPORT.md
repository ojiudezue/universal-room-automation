# D0 report: case freeze probe (2026-11-01, CST; read-only)

Plan: docs/planning/PLANNING_oc_live_eval_and_context_pack.md rev 2 (51c81530), D0. HVAC SoP read completely before C4/C7.
Files: live_cases/Lnn_*.json, live_answers/Lnn_*.json, live_cases/Lnn_evidence/. Evidence passed a secret/email/lat-long regex scan (clean) and a conclusion-phrase scan (clean). Live-source leak probe (L-4): 0 hits for all leakage_keywords across 13 URA DB tables and 1,527,193 recorder state_attributes rows. kanban_search/read_doc/list_changes_since remain leak paths (listed in each case's leak_paths).

| Case | Result | Expiry | Notes |
|---|---|---|---|
| L01 (C1) | verified, key reworded | rolling (oldest night 10-28) | "production.json socket timeouts / meters answer" has no tool path -> nice_to_mention. Must-mention is the nightly same-minute native-entity drop (21-55 min), second path mostly up, no restarts. |
| L02 (C2) | verified | 11-06 | Local witness 20 at 21:00:46; cloud 10.0 until 23:08:25; re-dispatch 23:06:24.098, page 0.3 s later. Code at e47c7082. |
| L03 (C3) | verified | 11-04, EXPORTED | Downtime 30.6 min (not 27). Key line cite corrected to coordinator.py:4070-4090 @e47c7082. |
| L04 (C4) | verified, numbers dropped | rows persist; recorder windows exported | Mechanism confirmed on 6 timeouts; 19-35 min figure replaced (10-31 was ~48 min). 15/39 confirmed. |
| L05 (C5) | verified, EXPORTED | 11-02 | Log item has no tool path (journald unreachable) -> nice_to_mention. Single surviving instance (10-21 already purged); fix shipped v5.103.94 so no new instances. |
| L07 (C7) | verified | rolling | No table records a sweep's effect; inferred from recorder edges (187 fires, 10 with on->off). Opt-out overwrite is code-only (switch.py:4039,:4067). |
| L08 (C8 control) | written | 11-06 | Guest Bedroom 1 light: vacant since 10-30 19:35, all sensors off. |
| C6 | DROPPED | n/a | Live config now has zero duplicate energy sensors across rooms/zones/house (68 checked); pre-change config backup contains secrets and is not servable. |

## Findings for the plan
1. D1 `ha_get_logs` backend is infeasible as written: `ssh ha` has no journalctl, `ha host logs`/`ha core logs` return 401. Only ha-mcp (~2 min window) works. Log-only must-mention items must stay nice_to_mention.
2. Incident-time commit for every case is e47c7082 (v5.103.92) except the 10-25 L04 instances (dbb80f8f); hvac.py clear logic identical.
3. Host clock: DST ended 11-01 02:00, recorder 'localtime' conversion is correct for Oct dates (checked against URA UTC rows).
