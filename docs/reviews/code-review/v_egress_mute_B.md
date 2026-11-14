# Review B: scoped egress mute (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Branch `feature/perimeter-egress-mute-scoped` @ 9e7af15e. Diff base `git merge-base develop HEAD` = 1eb0308b (verified).
Framing B: lifecycle, cross-module, data/DB, notification volume. No pytest run (not needed for this framing).

## Findings

| Sev | Where | Finding | Class |
|---|---|---|---|
| MEDIUM | perimeter_alert.py:5704-5710 (`_note_egress_identity`) + :590-609 (`_check_mute_zero_fire_tripwire`) | Zero-fire counts crossings from EVERY door, but mute rows can only come from doors listed in `egress_mute_covers`. Repro: covers = `{garage_a: [driveway]}`, garage unused for a day, 5+ crossings at doorbell/front door (live: ~79 crossings over 9 days on 5 doors, about 9/day) gives "Perimeter egress mute never ran" once a day even though the wiring is fine. Fix: count only crossings whose door key is a key of `_mute_covers()`. | Trip-wire false page (#53 scope mismatch: numerator and denominator at different scopes) |
| LOW | perimeter_alert.py:611-663 (`_fire_mute_tripwire`) | Checks `_active` but not `_gate_log_torn_down`. A trip-wire scheduled after teardown snapshots `pending` (:1412) is dropped from the set by `.clear()` but still runs, so an NM page or anomaly write can land after unload. The window is narrow (only in-flight handlers). Fix: also return when `_gate_log_torn_down`. | Untracked background task at teardown |
| LOW | perimeter_alert.py:1091 | The listener now registers on every install with egress cameras (it used to need dual-role). Setup does not unsub an existing `_unsub_egress_identity` before re-listening. Teardown unsubs correctly (:1376-1381), and a reused instance goes teardown then setup, so this is only a double-setup-without-teardown hazard. That hazard existed before; the change widens its scope. A double listener would store duplicate entries (harmless to the decision) and double the zero-fire crossing count. | Duplicate listener |
| LOW | exterior_track_linker.py:534-541 | A rejected seam file keeps the last-good `egress_mute_covers`, the same rule the graph follows. One effect: a covers typo now also blocks adjacency-graph updates (one file, one verdict), and an edit that narrows the covers but has an error leaves the wider old mute in place. Visible in `seam_validation`, and fine as designed. Worth one sentence in the README. | Config coupling |
| LOW | quality/tests/test_perimeter_egress_mute_scoped.py:541-620 | The trip-wire tests check NM titles only. With no `database` in the rig, the `AnomalyEvent` → `save_anomaly_event` path never runs against the real schema. I read the construction by hand: fields valid, `AnomalySeverity.WARNING`=1 and `AnomalyType.POINT_IN_TIME` exist, `observed_value` and `sample_size` are set (not sentinels-only). Add one real-DB anomaly row assertion. | Test authority gap (Tier 2-DB) |

## Cleared (holds because)

- **Unload/reload:** teardown unsubs the listener (:1376) and gathers `_gate_log_tasks` (which trip-wire tasks join) with a bounded wait (:1412-1423).
- **Fail toward alerting on restart:** setup resets `_recent_egress_identity` and `_mute_episodes` (:1090-1092). Tests `test_mute_restart_memory_empty` and `test_mute_restart_clears_episodes` cover it. A missing linker, missing census or an exception all return no mute (:422-427, :403-408).
- **Event loop and memory bounds:** the decision is synchronous over small lists. Per-door identity memory is capped at 16 (:5703). Door stamps, episodes and counts are bounded by camera or door count. Rolling row and crossing logs are capped at 4096 and pruned by window. `census._get_tracked_person_slugs` (camera_census.py:3899) is a config read with no I/O.
- **Trip-wires at boot / repeat:** zero-fire needs a full 24 h of uptime since setup (:596). Ratio needs 10 or more rows. Both have a 24 h per-kind cooldown (:613-616). With no map, zero-fire returns early (:592) and the ratio check never gets rows (decision returns at (a) before any row).
- **Gate-row shape (Tier 2-DB):** the change is additive. `suppressed` is written only when present (:4791). `scripts/probes/perimeter_gate_scorer_weekly.py` aggregates `camera/gate/reason/demoted` and keeps working. Mute rows show `demoted=False`, and `reason` tells a mute from a decline. No other reader of `perimeter_gate_decision` exists in custom_components or scripts. The row test uses a real `UniversalRoomDatabase` (test file :649+).
- **Row volume:** one row per covered-camera person edge that falls in a window with door activity. These rows run before cooldown (step 2 precedes step 3), so per-leg duplicates are possible but bounded by edge rate. Writes go through the existing tracked `log_memory_episode`.
- **Identity follow-up:** the mute runs at step 2, before cooldown, dispatch and `_arm_identity_followup` (:2010). A non-muted resident edge takes the unchanged alert path and gets the follow-up name. A mute sets no cooldown, so a later leg whose crossing is vetoed alerts once. I found no path that sends two alerts for one edge.
- **D10.5 / dual-role:** the dual-role branch is unchanged except for the window constant, which is 120 both before and after. D10.5 skips entries with an empty person id (:5718). Burst demote, single-source demote and the v5.108.20 gates sit after step 2 and are untouched.
- **Loader:** RULE 7 validates covers separately from the graph. `graph_from_spec` never reads them. The reload button calls `async_load_seam_file` (button.py:2381), which refreshes covers and the graph together. An absent file clears covers to `{}` (no mute).

## Live quantification (read-only, 9 days)

- `egress_identity_outcome`: about 79 crossings across 5 door entities. About 30 were `direction_ambiguous`, which now vetoes. Only **1** crossing had identity_confidence ≥ 0.9 (a doorbell entry).
- So the scoped mute will almost never fire on the current fleet. Edges the old global stamp silenced (120 s on every perimeter camera after each egress on-edge) will now alert, subject to cooldown. That matches what the operator chose.
- The count of edges the old stamp silenced cannot be measured. `_record_suppression` lives only in memory, and `perimeter_gate_decision` has **0 rows** in the live DB, so either gate-row persistence is not deployed live or it is writing nothing. The validator should check this before relying on gate rows for the live acceptance check.

## Verdict

**SHIP after the MEDIUM fix** (zero-fire crossing scope). The LOWs are 1-5 LoC each; fix them in the same pass.

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 4 |
