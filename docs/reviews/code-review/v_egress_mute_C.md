# Review C (test authority, real per-site source mutation) — PERIMETER-GLOBAL-EGRESS-MUTE-1

Branch `feature/perimeter-egress-mute-scoped`, HEAD 9e7af15e, diff base `1eb0308b` (merge-base with develop, verified).
Method: one production-source mutation at a time, run 11 files (the two new files + linker, seam loader, part3 seams,
fp_gates, nm_routing, gate_log, burst_demotion, identity_followup, identity_annotation; baseline 430 passed), restore,
`git status` clean. 107 independent mutations (mine) + the builder's 41 drill entries re-run (all 41 RED, none green).
Sites where the mutation is behaviourally equivalent are marked EQUIV (not findings).

## Verdict: FIX-REQUIRED (MEDIUM only; no CRITICAL/HIGH)

The security-relevant decision path (cover scoping, window upper bound, veto, resident/floor/synthetic/direction,
episode cap/reset/no-chaining, fail-open, restart clear, listener registration, door-key map, schema validation) is
authoritatively tested: every load-bearing mutation goes RED on a named test. The holes are in the trip-wire
*discipline* (cooldown, non-fire discriminator, anomaly persistence, task tracking), diagnostics, and a few
boundaries. Bug class for all rows below: #62 hollow/absent test anchor (untested site).

## GREEN-on-neuter findings (each = untested site)

| # | SEV | Site (perimeter_alert.py unless noted) | Mutation | Why it matters |
|---|---|---|---|---|
| F1 | MEDIUM | `_fire_mute_tripwire` cooldown `if last is not None and ts - last < ...: return` and `_egress_mute_tw_last[kind] = ts` | both neutered (T3, T4) | Re-alarm cooldown unproven: a ratio alarm that stays true would page NM on EVERY subsequent mute row. |
| F2 | MEDIUM | `_check_mute_ratio_tripwire` `ratio = sum(1 for _t, s in rows if s) / len(rows)` | count all rows (T16) | No test proves the alarm stays QUIET when most rows are declines. Discriminating non-fire case missing. |
| F3 | MEDIUM | `_fire_mute_tripwire._go` `database.save_anomaly_event(...)` | renamed to a nonexistent method (T6) | Anomaly-row persistence unasserted (tests see only the NM call); the exception is swallowed so a broken save is silent. Also `kind` strings (T17/T18) and NM severity (T19) unasserted. |
| F4 | MEDIUM | `_fire_mute_tripwire` task tracking `self._gate_log_tasks.add(task)` + done-callback | removed (T8) | Untracked background task (teardown drain not proven). `if not self._active: return` also untested (T5). |
| F5 | MEDIUM | `exterior_track_linker.py` file-absent branch `self.egress_mute_covers = {}` | removed (L3) | A deleted seam file leaves the previous coverage map live (stale mute) until restart; only the label is tested. Note: a REJECTED file also keeps prior covers (by design, consistent with graph) but is untested either way. |
| F6 | MEDIUM | `sensor.py` `_VOLATILE` additions (`egress_mute_counts_by_reason`, `egress_mute_covers`, `egress_mute_episodes`) | removed (G5) | Diagnostic attrs would silently stop updating the entity; no test. `egress_mute_episodes` stats field (G4) and `egress_mute_stats` try/except (G7) also untested. |
| F7 | LOW | dual-role INV-EGRESS-SELF window `seconds_since_egress <= float(EGRESS_MUTE_WINDOW_S)` | `<= 99999` (A3) | Dual-role upper bound untested; only the perimeter-only boundary has a parametrized test. |
| F8 | LOW | `_egress_mute_decide` `0.0 <= age` lower bound on crossing age | removed (A4) | A future-dated crossing (clock skew) would qualify and mute; untested. |
| F9 | LOW | `stamped` list bounds (A5, A5b) | each bound dropped | Only gates decline-row emission (display), untested. |
| F10 | LOW | residents/pid `.lower()` (A7, A7b) | one side un-lowered | Case-mismatch of census slug vs `person_id` untested (both lowercase in fixtures). |
| F11 | LOW | `door, ref = max(qualifying, key=...)` | `min` (A10) | Reported reference crossing (row/diagnostic) not asserted to be the latest. |
| F12 | LOW | `_door_key_for` fallback `or self._egress_key(...)` (D2); setup `_egress_key` fallback (D12); `_base` seed (D11); `_egress_door_key_by_entity = {}` reset on re-setup (D15); `setdefault` first-wins (D16) | each neutered | Unmapped-camera fallback and re-setup map reset untested (stale map after reconfigure). |
| F13 | LOW | `if self._dual_role_cameras:` guarding the arrival listener | widened to `or egress_infos` (D18) | Plan says arrival listener + `_fp_setup_ts` stay dual-role only; nothing pins it. |
| F14 | LOW | `exterior_track_linker.py` `normalize_camera` on door and cams (L1, L2) | removed | Alias/case normalisation of covers untested; fixtures use already-normal names. |
| F15 | LOW | trip-wire window filters and bounds: ratio `>` vs `>=` (T1), ratio cutoff (T9), zero-fire window filters (T13, T14), `need <= 0` disable (T11), min-rows `<` boundary partially (T2 is RED) | each neutered | Boundary and disable semantics untested. |
| F16 | LOW | exterior_seams `all(isinstance(c, str) and c ...)` (S3) | `c` emptiness dropped | Empty-string camera name only caught indirectly. |
| F17 | LOW | const defaults `EGRESS_MUTE_RATIO_ALARM` 0.5 (C5), `EGRESS_MUTE_TRIPWIRE_WINDOW_S` (C8) | values changed | Shipped defaults of two knobs unpinned (the floor 0.9 default, C2, is EQUIV by the clamp). |

EQUIV (not findings): A12 (episode pop; overwritten on next mute), A26/A27/A28/A29 (outer fail-open wrapper gives the same alert
outcome; A26 only loses the veto row), D10 (`""` pid already fails `pid.lower() not in known`), L7 (covers doors already in the
egress set), S2 (JSON keys are strings; empty key caught by the egress-membership rule), S5, S10, A31 (unreachable fallback).

## Per-site table (RED = named test goes red)

| Site | Result | First failing test(s) |
|---|---|---|
| wire-in `elif self._egress_mute_decision(` (A1) | RED (32) | test_mute_known_resident_covered_camera, test_mute_window_boundary[119-0] |
| dual-role branch forced True/False (A2/A2b) | RED | test_mute_dual_role_keeps_inv_egress_self, test_egress_only_stamp_suppresses_dual_role |
| dual-role reason key (A3b) | RED | same |
| (a) cover scoping (A6) | RED | test_mute_not_covered_alerts, test_mute_stamp_on_uncovering_door_writes_no_row |
| (b) window upper bound (A4b) | RED | test_mute_window_boundary[121-1] |
| (c) veto (A17, A21) | RED | test_mute_vetoed_by_unknown_crossing, test_mute_stranger_after_unknown_crossing_alerts |
| floor `<=` (A8), conf read (A25) | RED | test_mute_below_floor_alerts[0.9-0], test_mute_min_conf_clamps_to_0_9 |
| synthetic (A9) | RED | test_mute_synthetic_alerts |
| direction tuple (A22) | RED | test_mute_ambiguous_direction_alerts[-1] |
| episode last/store/cap/cap row/cap `>=` (A11, A13, A19, A20) | RED | test_mute_episode_cap_no_chaining, test_knob_cap_below_window |
| mute row, suppressed flag, gate name, record_suppression, row fields (A14-A16, A23, A24) | RED | test_mute_known_resident_covered_camera |
| no_record row / stamped gate (A18, D1) | RED | test_mute_no_record_alerts_now |
| fail-open wrapper (A30) | RED | test_mute_failopen_errors |
| door memory: key map, identity key, direction, synthetic, keep-16, prune-600, unknown store (D3-D9, D13, D14) | RED | test_egress_memory_keys_all_legs_to_one_door, test_egress_memory_stores_unknown_crossing, test_mute_synthetic_alerts |
| listener registration (D17) | RED (60) | test_egress_listener_registers_without_dual_role |
| boot-since (D19) | RED | test_mute_zero_fire_quiet_when_rows_exist_or_boot |
| ratio `>`/min rows/NM call/counts (T2, T7, T10) | RED | test_mute_ratio_tripwire_fires, test_mute_counts_by_reason_on_diagnostic |
| zero-fire `>=`, record (T12, T15) | RED | test_mute_zero_fire_tripwire_fires |
| diagnostics merge/counts/covers, gate attr `suppressed` (G1-G3, G6) | RED | test_mute_counts_by_reason_on_diagnostic, test_mute_row_suppressed_field_not_demoted |
| seams: rule call, raw-none, notdict, known gate, unknown cams, sorted, egress set (S1, S4, S6-S9) | RED | test_mute_covers_* , test_shipped_example_covers_validate_with_live_cameras |
| linker: label, status key, covers kept out of graph, init default (L4-L6, L8) | RED | test_mute_covers_absent_means_no_mute, test_mute_covers_valid_loads, test_mute_covers_not_in_adjacency_graph |
| const window/cap/reset/min-rows/zf (C1, C3, C4, C6, C7) | RED | test_mute_window_boundary[121-1], test_mute_episode_cap_no_chaining |
| builder's 41 drills (M1-M31b, P1, P2, S1-S6, L1, L2) | all RED | per builder script |

Tree: only untracked scratch (`.claude-*`) remains; no tracked file modified after any drill.

## Must-fix before SHIP
F1-F6: add tests for the trip-wire cooldown (fire twice in window -> one NM), the quiet-when-mostly-declines case,
the persisted anomaly row (type/severity), task tracking/teardown drain, the file-absent covers reset (and the
rejected-file keep-covers behaviour, either way pinned), and the `_VOLATILE` diagnostic keys. LOWs (F7-F17) are
1-10 LoC each and per project policy should be fixed in the same fix-up pass.
