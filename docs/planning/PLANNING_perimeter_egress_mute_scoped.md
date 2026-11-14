# Planning: scoped egress mute for perimeter alerts (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Status: plan, reviewed (FIX-PLAN findings applied, `docs/reviews/plan-review/PLANREVIEW_perimeter_egress_mute_scoped.md`).
Card: `PERIMETER-GLOBAL-EGRESS-MUTE-1`. Tier 2-DB (section 9).
Identity model: CONSUMES F3 (door crossing + identity attach, EgressDirectionTracker via `ura_person_egress_event`).
Consumer class: SECURITY (silence only at identity >= 0.9; never on F4). Produces no new fact.

## 1. Institutional context verified

Read: `AUDIT_perimeter_silence_post_v5_108_20.md`, the card, the plan review, `perimeter_alert.py` :300-301,
:936-960, :1010-1030, :1358-1400, :2265-2295, :2787-2806, :4639-4750, :5120-5440; `exterior_seams.py` :93-325;
`exterior_track_linker.py` :227-241, :479-500, :1085-1130; live `exterior_seams.json`; transit_validator egress
resolve path. Skimmed: `PLANNING_perimeter_fp_build_2026_11.md` D10, `PLANNING_perimeter_consolidation.md`,
`PLANNING_nvr_witness_layer.md`, the arc charter, memory `feedback_cross_work_reconciliation_review.md`,
`feedback_alert_latency_over_precision.md`, `reference_identity_model_f1_f5.md`. HVAC/presence state-of-play docs:
not applicable.

| Piece | Verdict | Where |
|---|---|---|
| Mute site | REUSED, rewritten in place | `perimeter_alert.py:1367-1387` |
| Per-camera door identity memory | REUSED + extended | `_note_egress_identity` :5155-5166 into `_recent_egress_identity` (keyed by camera key via `_egress_key` :5144, 16 entries, 600 s, synthetic flag) |
| Its listener | REUSED, registration widened | :1017-1023 (today: dual-role only, live = none) |
| Per-door on-edge stamps | REUSED | `_note_egress_stamp` :5126 into `_last_egress_time_by_camera` |
| Dual-role rule INV-EGRESS-SELF | REUSED unchanged | `_egress_stamp_for` :5133 |
| Tracked residents / guests | REUSED | census `_get_tracked_person_slugs` (camera_census.py:3899), `_get_known_face_guests` (:4016) |
| Door -> covered cameras | NEW section `egress_mute_covers` in `exterior_seams.json` | no equivalent: the ring is exterior-only and garage cameras are kept out of it by design |
| Section validation | NEW, inside `validate_seam_spec` (exterior_seams.py:145) | reuses the reject-whole-file contract and `known_cameras` check |
| Gate row writer | REUSED | `_record_gate` :4639 -> `_persist_gate_decision` :4676, episode `perimeter_gate_decision` (const.py:2658) |
| Identity follow-up after an alert | REUSED | PERIMETER-IDENTITY-FOLLOWUP-1 (`perimeter_identity_followup`, "Add Names to Alerts") |
| Mute episode state | NEW, RAM dict | grep `_mute_\|mute_episode` = none |
| Read API `get_last_crossing` | NOT used | keyed per triggering leg entity and last-wins; the existing cache is keyed per camera and keeps a list. No batch-1 dependency |

## 2. Measured (read-only)

Recorder (`home-assistant_v2.db`) holds edges only from 11-06 to 11-14 (~9 days, purge horizon). Perimeter person
on-edges (`*_person_detected`, `*_person_occupancy_2`): 607 (~67/day); 243 (40%, ~27/day) had an egress on-edge in
the prior 120 s and were muted. Worst: g5_bullet 135/208, rear_ptz 34/109, front_side_ptz 27/44, utilities_ptz 18/77.
Nothing durable records a mute today; no gate row exists for any muted edge.
URA DB `person_entry_exit_events` (true 14 days): 226 crossings, 95 with person_id, 38 (17%) at confidence >= 0.9.
Crossing latency: the record and bus event land at `EGRESS_ENTRY_WINDOW_SECONDS` = 45 s after the door edge
(const.py:3355, `async_call_later` in the egress handler). Of muted edges, 56% fell under 45 s after the first
egress edge in their window.

## 3. Behaviour and invariants

Decision A (operator): **alert now, name it afterwards.** No hold. A perimeter edge alerts at once unless a
qualifying crossing is already in memory. A qualifying crossing mutes LATER edges on the cameras its door covers.

A crossing on door D **qualifies** when: direction is `entry` or `exit` (ambiguous never qualifies); person_id is a
tracked resident (guests never); identity_confidence >= `EGRESS_MUTE_MIN_IDENTITY_CONF`; not synthetic-corroborated.

**INV-MUTE-KNOWN:** a perimeter edge on camera P is dropped by the egress mute ONLY IF (a) some door D lists P in
`egress_mute_covers`; (b) D has a qualifying crossing within `EGRESS_MUTE_WINDOW_S` before the edge; (c) NO crossing
on any door covering P in that window fails to qualify (one unknown, below-floor, synthetic or ambiguous crossing
vetoes); (d) P's mute episode is younger than `EGRESS_MUTE_MAX_EPISODE_S`. Every drop writes one gate row.
Break it with any reachable path where an edge is dropped without (a)-(d), or dropped without a row.

**INV-MUTE-FAILOPEN:** any error, missing census, invalid or absent `egress_mute_covers`, or unmapped camera = no
mute. Restart clears the memory and episodes, so the first minutes after boot mute nothing (safe direction).

Residuals, decided and stated:
- Resident walk-outs mostly alert: the record lands at +45 s and only ~17% carry >= 0.9, so a resident reaching
  g5_bullet before the record exists is paged, then named by the identity follow-up. Expect most of the ~27/day
  muted edges to become candidate alerts (cooldown and later gates fold many). Egress naming (arc step 7) is what
  reduces them; this plan does not.
- A stranger who never crosses a door is muted for up to the window after a known resident's crossing, only on
  that door's covered cameras, and never longer than the episode cap.
- Protect names that back-fill later never upgrade a crossing; identity is fixed when the record lands.

## 4. Producer and consumer checks

- **Producer: `ura_person_egress_event`** (transit_validator, at +45 s). Fields used: `egress_camera`, `timestamp`,
  `direction`, `person_id`, `identity_confidence`, `identity_synthetic_corroborated`. Ground truth: `person_entry_exit_events`.
- **Producer: `egress_mute_covers`.** Operator-declared config; health surfaced on the diagnostic sensor.
- **Consumers of `_recent_egress_identity`:** the new mute, and `_known_identity_for` :5168 (D10.5, dual-role only).
  D10.5 must stay byte-identical: it skips entries with no person_id (D1 test).
- **Consumers of stamps:** `_egress_stamp_for` :5137-5142 (dual-role, kept); declined-row gating (D3) reads the
  covering doors' per-camera stamps, never the global one. The global `_last_egress_time` is no longer read by the
  perimeter-only mute.
- **Forward trace:** a non-muted edge goes to cooldown :1405, gates :1626-1637, dispatch, `notification_log`, and the
  identity follow-up. A muted edge reaches only `_record_suppression` and the gate row.

## 5. Deliverables

### D1: door identity memory keeps every crossing
Extend `_note_egress_identity`: store crossings with no person_id (pid `""`, conf 0.0) and the direction. Key by
physical door camera: map `egress_camera` through the configured egress camera infos (`_sensor_to_camera` built at
wiring) for every leg of that camera (Frigate `_2` occupancy, Protect detected, person-count sensor), falling back to
`_egress_key` only when the map lacks it. Register the listener whenever egress cameras are configured; the arrival
listener and `_fp_setup_ts` in that block stay dual-role only. `_known_identity_for` skips empty-pid entries.
- **Verify:** crossings from all three legs of garage_a land under one key; an unknown crossing is stored.
- **Test:** `test_egress_memory_keys_all_legs_to_one_door`, `test_egress_memory_stores_unknown_crossing`,
  `test_d10_5_ignores_unknown_entries`, `test_egress_listener_registers_without_dual_role`.

### D2: `egress_mute_covers` section
New top-level key in `exterior_seams.json`: `{"garage_a": ["g5_bullet","doorbell_lite","rear_ptz"],
"madrone_g6_entry": ["sonoffwindow","front_side_ptz","utilities_ptz"], "front_door_aerial": ["sonoffwindow",
"front_side_ptz","utilities_ptz"]}`. Doors not listed (doorbell_lite as a door, garage_b) mute nothing.
Validation in `validate_seam_spec`: object of door -> non-empty list; each door must be a configured egress camera
and each covered camera a configured perimeter camera (`known_cameras`, resolved from config/registry, never from
entity names); any error rejects the whole file and keeps the previous good spec. Absent section = no mute. The
linker loads it into a separate attribute; `graph_from_spec`, `derive_egress_adjacent`, track linking, burst-demote
(`has_recent_adjacent_activity`) and circling never read it. The ring stays as ratified.
- **Verify:** ring, seam count and `seam_egress_adjacent` unchanged after adding the section.
- **Test:** `test_mute_covers_valid_loads`, `test_mute_covers_unknown_camera_rejects_file`,
  `test_mute_covers_absent_means_no_mute`, `test_mute_covers_not_in_adjacency_graph`.
- **Live:** diagnostic sensor shows `mute_covers_source` loaded and the seam attributes unchanged.

### D3: the scoped mute
Replace :1367-1387 with `_egress_mute_decision(cam_key, now)` applying INV-MUTE-KNOWN (a)-(d) for perimeter-only
cameras; dual-role cameras keep INV-EGRESS-SELF. Episodes: first mute opens an episode for P; mutes after the cap are
refused (`egress_mute_cap`) until `EGRESS_MUTE_EPISODE_RESET_S` passes with no mute; a fresh crossing never resets
the start. Gate row on every decision where a covering door had an on-edge stamp or a crossing in the window:
`gate: "egress_mute"`, `suppressed: true|false`, `demoted: false`, `reason` one of `egress_mute_known_resident`,
`egress_mute_vetoed_unknown`, `egress_mute_no_record`, `egress_mute_below_floor`, `egress_mute_synthetic`,
`egress_mute_ambiguous`, `egress_mute_cap`, plus inputs (door, person_id, confidence, direction, crossing_ts,
seconds_since, episode_age_s).
- **Verify:** stranger on g5_bullet 30 s after a garage_a crossing with no identity -> alert + row `no_record`/`vetoed_unknown`.
- **Verify:** g5_bullet edge 60 s after a garage_a exit by a tracked resident at 0.95 -> muted + row.
- **Verify (discriminates vs "window got shorter"):** door on-edge with no crossing yet -> alert at 1 s.
- **Verify:** resident 0.95 and an unknown crossing at a covering door in the window -> alert.
- **Verify:** madrone_g6_entry resident crossing -> g5_bullet still alerts (not covered); doorbell_lite crossing mutes nothing.
- **Test:** `test_mute_known_resident_covered_camera`, `test_mute_not_covered_alerts`, `test_mute_no_record_alerts_now`,
  `test_mute_vetoed_by_unknown_crossing`, `test_mute_below_floor_alerts`, `test_mute_synthetic_alerts`,
  `test_mute_ambiguous_direction_alerts`, `test_mute_guest_never_mutes`, `test_mute_episode_cap_no_chaining`,
  `test_mute_episode_resets_after_quiet`, `test_mute_min_conf_clamps_to_0_9`, `test_mute_failopen_errors`,
  `test_mute_row_suppressed_field_not_demoted`. Each condition mutation-anchored.
- **Live:** a driveway edge during door activity with no qualifying crossing produces a `notification_log`
  exterior_person row and a gate row; a later identity follow-up names the resident when known.

### D4: trip-wires
Diagnostic counters `egress_mute_counts_by_reason`. NM anomaly when: suppressed / (all egress_mute rows) exceeds
`EGRESS_MUTE_RATIO_ALARM` over 24 h (blanket mute returning); or zero `egress_mute` rows in 24 h while egress
crossings occurred (wiring broken, zero-fire rule).
- **Test:** `test_mute_ratio_tripwire_fires`, `test_mute_zero_fire_tripwire_fires`.

## 6. Knobs (all rung 1 module constants: they gate a security silence, changes need review)

| Knob | Value | Why / kill |
|---|---|---|
| `EGRESS_MUTE_WINDOW_S` (replaces :301) | 120 | walk-out time after a crossing; 0 = never mute |
| `EGRESS_MUTE_MIN_IDENTITY_CONF` | 0.9 | security floor; below 0.9 clamps to 0.9; above 1 = kill |
| `EGRESS_MUTE_MAX_EPISODE_S` | 300 | bounds silence; 0 = never mute |
| `EGRESS_MUTE_EPISODE_RESET_S` | 120 | quiet gap ending an episode |
| `EGRESS_MUTE_RATIO_ALARM` | 0.5 | trip-wire; above 1 disables |
The coverage map is config (seam file), not a knob.

## 7. Reconciliation

| Work | Conflict | Decided resolution |
|---|---|---|
| PERIMETER-FP D10 / INV-EGRESS-SELF | D10 kept "every stamp mutes a perimeter-only camera" | Superseded for perimeter-only cameras; dual-role rule kept verbatim |
| D10.5 `_apply_egress_identity_gate` | Shares `_recent_egress_identity` | D10.5 byte-identical: skips unknown entries; its listener now always on, which only feeds the cache |
| PERIMETER-IDENTITY-FOLLOWUP-1 | Alert-now means residents get paged | Intended (decision A): the follow-up names them |
| Arc step 7, egress naming | Owns the resident-page reduction | Not done here; this plan states the residual |
| PERSON-AWARENESS-READ-API-1 | Plan no longer reads `get_last_crossing` | No dependency; read API migration of this cache can follow later |
| NVR-WITNESS-CONSOLIDATION-1 W1 | Re-pairs `garage_a_2` keys | D1 keys by configured camera across all legs; test includes the `_2` leg |
| REGISTRY-NOT-NAMES-1 | `_egress_key` stem fallback | New code uses the config map first; the fallback stays on that card |
| Exterior seams / linker | New section in the same file | Separate attribute; ring, linking, burst-demote, circling untouched (D2 test) |
| PERIMETER-ZONE-AGREEMENT-FIX-OR-REMOVE-1 | Same handler | Independent; mute runs first, order unchanged |
| Census / F2 | None | Mute reads residents, writes no census input |

## 8. Operator decisions recorded
1. Alert now, name afterwards (decision A). 2. Coverage map as given, in `egress_mute_covers`, registry-resolved.
Optional tightening offered, not built: refuse the mute when P's person count exceeds known crossers in the window.

## 9. Tier
Tier 2-DB: a security silence on 40% of perimeter edges, a new gate row family (payload shape), a shared config
file loader, and a shared identity cache. No schema change, no new writer. Build reviews: A local correctness of each
mute condition and fail-open; B lifecycle and cross-module (listener registration, seam reload, D10.5 byte-identity,
restart, row volume); C per-site source mutation of every INV-MUTE-KNOWN condition and the validator.

## 10. Non-goals
No change to cooldown, gates, severity, vehicle path, the seam ring, or D10.5 behaviour. No hold or wait. No egress
naming work. No config-flow fields or entities. No census or HVAC change. No soak.

## 11. Plan completion tracking
Builder reports D1-D4 as done or deferred with reason and destination card. README write-back table after live
validation with the D2/D3 Live rows and first-day row counts by reason.
