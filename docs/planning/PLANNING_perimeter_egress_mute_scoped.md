# Planning: scoped egress mute for perimeter alerts (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Status: plan, pre-review. Card: `PERIMETER-GLOBAL-EGRESS-MUTE-1` (kanban.data.yaml:34864). Tier: 2-DB (see section 9).
Identity model: this CONSUMES F3 (door crossing + identity attach, EgressDirectionTracker). Consumer class: SECURITY
(de-escalate only at identity >= 0.9; never act on F4 alone). It produces no new fact.

## 1. Institutional context verified

Read in full: `AUDIT_perimeter_silence_post_v5_108_20.md`, the card, `perimeter_alert.py` :300-301, :331-485,
:936-960, :1358-1400, :2265-2295, :2787-2806, :4639-4750, :4812-4821, :5120-5440; `exterior_track_linker.py`
:227-241, :1085-1130; `exterior_seams.py` :290-322; live `/config/universal_room_automation/exterior_seams.json`;
release/batch-1 `transit_validator.py` :944-961, :1039-1053, :2215-2262 and `presence.py` :6009-6020.
Skimmed: `PLANNING_perimeter_fp_build_2026_11.md` D10 (:555-610), `PLANNING_perimeter_consolidation.md`,
`PLANNING_nvr_witness_layer.md`, `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (charter),
memory `feedback_cross_work_reconciliation_review.md`, `feedback_alert_latency_over_precision.md`,
`reference_identity_model_f1_f5.md`. The "perimeter gate evidence plan" is not a file on develop (`grep -l
PERIMETER-GATE-EVIDENCE docs/planning/*.md` = empty); its shipped code (v5.108.20 `_persist_gate_decision`) is read
directly. Presence/HVAC state-of-play docs: not applicable (no presence or HVAC surface touched).

| Piece | Verdict | Where |
|---|---|---|
| Mute site | REUSED, rewritten in place | `perimeter_alert.py:1367-1387` |
| Window constant | REUSED, renamed role | `EGRESS_SUPPRESSION_WINDOW_SECONDS` :301 |
| Global stamp + per-camera stamp | REUSED (per-camera kept, global no longer read by the mute) | :942-947, `_note_egress_stamp` :5126 |
| Dual-role rule INV-EGRESS-SELF | REUSED unchanged (live `dual_role_cameras = []`) | `_egress_stamp_for` :5133 |
| Last F3 crossing per door camera | REUSED, read API ship 1 | `presence.get_last_crossing(camera)` (batch-1 presence.py:6009) -> `EgressDirectionTracker.get_last_crossing` (batch-1 transit_validator.py:1044) |
| Synthetic-latch flag on the record | NEW field, additive | `CrossingRecord` lacks it; bus already carries `identity_synthetic_corroborated` (batch-1 :2227) |
| Known-resident set | REUSED | census `_get_tracked_person_slugs()` as used by `_known_identity_for` :5180-5187 (guests excluded here, see D2) |
| Door-to-perimeter relation | REUSED, operator-ratified seams | `ExteriorTrackLinker.adjacent_cameras` (exterior_track_linker.py:1085) loaded from `exterior_seams.json` |
| Sensor -> configured camera | REUSED, config-built map | `self._sensor_to_camera` filled at wiring :575, :1076, :1085 |
| Gate row writer | REUSED | `_record_gate` :4639 -> `_persist_gate_decision` :4676, episode `perimeter_gate_decision` (const.py:2658) |
| Suppression diagnostic | REUSED | `_record_suppression` :2787, exposed as `suppressions_by_camera` |
| Mute episode cap state | NEW, in-memory dict | no equivalent (grep `mute_started\|suppress.*episode\|_mute_` = none) |
| Knobs | NEW consts, section 6 | grep const.py `EGRESS_MUTE\|EGRESS_SUPPRESSION` = only :301 |

Not reused, on purpose: `_known_identity_for` (:5168). It also accepts face legs, unscored Frigate faces plus a
non-face edge, and a 600 s cache; that is right for D10.5 demote-one-level, too wide for a full SILENCE. The mute
requires an F3 crossing with identity attached.

## 2. Measured (read-only, 2026-11-13, 14-day window)

Recorder (`home-assistant_v2.db`, person on-edges of `*_person_detected` / `*_person_occupancy_2`, perimeter
cameras only; egress set = the 4 door cameras):
- 607 perimeter person on-edges; **243 (40%) had an egress on-edge in the prior 120 s** = muted today. They fall in
  115 distinct minutes. Worst cameras: g5_bullet 135/208, rear_ptz 34/109, front_side_ptz 27/44, utilities_ptz 18/77.
- If only seam-related doors could mute: 196 of 243 still muted. **Seam scoping alone buys little**; g5_bullet sits
  next to doorbell_lite. The identity condition is the load-bearing filter.
- URA DB `person_entry_exit_events`, 14 days: 226 crossings, 95 with person_id, **38 (17%) with confidence >= 0.9**.
  `memory_episodes` `egress_identity_outcome` since 11-13 08:25: 79 rows, 1 attach at >= 0.9.
- Fire check of the current mute: it fires on ~40% of perimeter edges, and nothing durable records it (only the last
  suppression per camera, in RAM). Zero `perimeter_gate_decision` rows can exist for a muted edge.
- Caveat: edges are sensor edges (two NVR legs per camera), not alerts; cooldown and later gates would have folded
  many. Upper bound on extra alerts after the fix: about 8 alert-minutes a day.

## 3. Falsifiable invariant

**INV-MUTE-KNOWN:** a perimeter person edge on camera P is dropped by the egress mute ONLY IF, at the edge time,
there is an F3 crossing record on a door camera D such that (a) D is seam-adjacent to P in the loaded seam graph,
(b) the record carries a person_id that is a tracked resident, (c) identity_confidence >= 0.9 and the attach did not
rely on a synthetic latch leg, (d) the crossing is within `EGRESS_MUTE_WINDOW_S` before the edge, and (e) P's current
mute episode has lasted less than `EGRESS_MUTE_MAX_EPISODE_S`. Every drop writes one `perimeter_gate_decision` row.
Break it with: any reachable path where an unknown, unnamed, below-0.9, synthetic, non-adjacent, stale, or
over-cap crossing silences a perimeter edge, or a drop with no row.

**INV-MUTE-FAILOPEN:** any error, missing presence/linker/census, empty seam graph, or unmapped camera means NO mute.

## 4. Producer and consumer checks

- **Producer: F3 crossing record.** Written at the `ura_person_egress_event` fire (batch-1 :2244-2262), after the
  direction resolves, so it lands seconds after the door camera's on-edge. Consequence: a perimeter edge in that gap
  is not muted and alerts. That matches the latency rule (send now). Dependency health: identity attach is 17% at
  >= 0.9, so most crossings will not mute. Ground truth: `person_entry_exit_events` rows, not display prose.
- **Producer: seam graph.** `exterior_seams.json`, 21 seams, operator-ratified; `garage_a` and `garage_b` are not in
  it, so a garage_a crossing mutes nothing (operator call, section 8 Q1).
- **Consumer: the mute site** :1367 (trust decision, security class). Other readers of `_last_egress_time`: only
  `_egress_stamp_for` :5137. Readers of `_last_egress_time_by_camera`: `_egress_stamp_for` :5138-5142. Both stay.
- **Forward trace:** a non-muted edge continues to cooldown :1405, gates :1626-1637 (single-source demote, burst,
  D10.5 for dual-role), dispatch, `notification_log`. A muted edge reaches only `_record_suppression` + the new row.
- **Zero-fire trip-wire:** D4.

## 5. Deliverables

### D0: precondition, sequencing on the read API
Build on a branch from `release/batch-1` (holds ship 1, commit 1fb058db), merged after batch-1 lands on develop.
Add `identity_synthetic_corroborated: bool = False` to `CrossingRecord` and fill it from the same value the bus
carries (one line at batch-1 :2247). Additive; ship-1 readers ignore it.
- **Verify:** record and bus event carry the same flag for one crossing.
- **Test:** `test_crossing_record_carries_synthetic_flag`.

### D1: replace the global mute with a scoped, known-resident mute
At :1367-1387, replace `_egress_stamp_for` + window with `_egress_mute_decision(cam_key, now)` returning
`(mute: bool, detail: dict)`. For each door camera in the configured egress list whose seam key is adjacent to
`cam_key` (`linker.adjacent_cameras(cam_key)`), read `presence.get_last_crossing(<that camera's sensor>)` and apply
INV-MUTE-KNOWN (a)-(d). Door camera to seam key goes through `_sensor_to_camera` plus the existing
`_camera_key_for_sensor` (pre-existing derivation; the new code adds no name parsing; REGISTRY-NOT-NAMES-1 owns
migrating it). Dual-role keeps INV-EGRESS-SELF: a dual-role P never mutes on a dual-role D.
- **Verify:** stranger on g5_bullet 30 s after an UNKNOWN doorbell_lite crossing -> alert dispatches.
- **Verify:** g5_bullet edge 30 s after a doorbell_lite crossing by a tracked resident at 0.95 -> muted.
- **Verify:** same resident crossing at garage_a (no seam) -> g5_bullet alerts; at 0.85 -> alerts; synthetic 0.9 -> alerts.
- **Verify (discriminates vs "mute just got shorter"):** an egress on-edge with NO crossing record -> alert, even at 1 s.
- **Test:** `test_mute_unknown_crossing_alerts`, `test_mute_known_resident_adjacent_door`, `test_mute_non_adjacent_door_alerts`,
  `test_mute_below_floor_alerts`, `test_mute_synthetic_alerts`, `test_mute_raw_egress_edge_alone_alerts`,
  `test_mute_failopen_no_presence_or_linker`. Each mutation-anchored on its condition.
- **Live:** next resident-free driveway walk during door activity produces a `notification_log` exterior_person row.

### D2: bounded episode
Per perimeter camera keep `mute_episode_start`. First mute opens an episode; mutes after
`EGRESS_MUTE_MAX_EPISODE_S` from the start are refused (reason `egress_mute_cap`) until a quiet gap of
`EGRESS_MUTE_EPISODE_RESET_S` with no mute. A fresh crossing does not reset the start (no chaining). Guests
(`_get_known_face_guests`) never mute: a guest at the door with a stranger on the driveway is the case this card fixes.
- **Verify:** known crossings every 60 s for 15 min -> mutes stop at the cap; the next edge alerts.
- **Test:** `test_mute_episode_cap_no_chaining`, `test_mute_episode_resets_after_quiet`, `test_mute_guest_never_mutes`.

### D3: every mute decision is a gate row
At the decision, `_record_gate(cam_key, {"gate": "egress_mute", "at", "entity_id", "reason", "demoted": mute,
"inputs": {door camera, person_id, identity_confidence, synthetic, crossing_ts, seconds_since, episode_age_s}})`.
Reasons: `egress_mute_known_resident` (muted), `egress_mute_declined_unknown`, `_below_floor`, `_synthetic`,
`_stale`, `egress_mute_cap`. A declined row is written only when an egress on-edge occurred in the window (keeps row
volume at the measured ~17/day, not every edge). `_record_suppression` stays for the diagnostic attribute.
- **Verify:** muted edge -> one row with reason `egress_mute_known_resident`; declined -> one row and an alert.
- **Test:** `test_mute_writes_gate_row`, `test_declined_writes_gate_row_and_dispatches`.
- **Live:** `memory_episodes` gains `perimeter_gate_decision` rows with gate `egress_mute` within a day; every
  `egress_suppression` entry in `suppressions_by_camera` has a matching row (sentinel-only attrs = broken payload).

### D4: trip-wires
Counters on the diagnostic sensor: `egress_mute_counts_by_reason`. Anomaly to NM if muted / (muted + declined)
exceeds `EGRESS_MUTE_RATIO_ALARM` over 24 h (the old blanket behaviour returning), or if any mute occurs while
the seam graph is empty.
- **Test:** `test_mute_ratio_tripwire_fires`.

## 6. Knobs

| Knob | Rung | Value | Why / kill |
|---|---|---|---|
| `EGRESS_MUTE_WINDOW_S` (renames :301) | 1 module const | 120 | measured walk-out time; 0 = mute never fires (all alerts send) |
| `EGRESS_MUTE_MIN_IDENTITY_CONF` | 1 module const | 0.9 | security doctrine floor; values < 0.9 clamp to 0.9; > 1 = kill |
| `EGRESS_MUTE_MAX_EPISODE_S` | 1 module const | 300 | bounds silence after one arrival; 0 = no mute |
| `EGRESS_MUTE_EPISODE_RESET_S` | 1 module const | 120 | quiet gap that ends an episode |
| `EGRESS_MUTE_RATIO_ALARM` | 1 module const | 0.5 | trip-wire; > 1 disables |
Rung 1 for all: they gate a security silence, so a change should need review. No new config-flow field or entity.

## 7. Reconciliation with other perimeter, egress and camera work

| Work | Conflict | Decided resolution |
|---|---|---|
| PERIMETER-FP D10 / INV-EGRESS-SELF (fp_build :555) | D10 kept "every stamp mutes a perimeter-only camera" | Superseded for perimeter-only cameras; dual-role rule kept verbatim inside D1 |
| D10.5 egress identity gate `_apply_egress_identity_gate` :5339 | Two identity rules on one edge | D10.5 stays a demote for dual-role cameras with its wider evidence; the mute is the stricter F3-only silence. No shared code change |
| PERIMETER-IDENTITY-FOLLOWUP-1 | A muted edge sends nothing, so no follow-up | Intended: a muted edge is a known resident already |
| PERSON-AWARENESS-READ-API-1 ship 1/2 | Plan reads its API before develop has it | D0 branches from batch-1; merge after batch-1. If ship 2 changes `CrossingRecord`, D0's field merges as additive |
| NVR-WITNESS-CONSOLIDATION-1 (W1 pairing on batch-1, W5 perimeter) | W5 rewires perimeter evidence | Mute reads crossings, not NVR legs; W5 does not touch it. W1 re-pairs garage_a_2 keys: D1 tests include a `_2` door camera |
| REGISTRY-NOT-NAMES-1 | `_camera_key_for_sensor` is name stripping | Not widened; new code uses `_sensor_to_camera` first; migration stays on that card |
| PERIMETER-ZONE-AGREEMENT-FIX-OR-REMOVE-1 | Same handler, later gate | Independent; mute runs before it, unchanged order |
| Exterior seams (exterior_seams.json) | Seams now also gate a silence; a wrong seam silences | Fail direction is safe: a missing seam only means more alerts. Seam file `_readme` already warns; no seam edits here |
| Census deconfliction / F2 | None: the mute reads residents, writes no census input | n/a |
| Alert latency rule | Waiting for the crossing record would delay alerts | No wait added: no record yet = alert now |

## 8. Open operator questions (plan proceeds on the recommendation)
- Q1: garage_a has no seam, so a resident leaving by garage_a never mutes g5_bullet / garage_b. Rec: accept (more
  alerts, never fewer); add seams by editing `exterior_seams.json` if wanted (config-first, no code).
- Q2: cap 300 s. Rec: accept; tune by observing `egress_mute_cap` rows.

## 9. Tier
Tier 2-DB (elevated from the card's 2 under the standing regression-prone rule): it changes a security silence that
fires on ~40% of perimeter edges, adds a new gate row family to `memory_episodes` (payload shape), and reads a new
cross-coordinator API. No schema change, no new writer. Reviews: A local correctness of each mute condition and
fail-open; B cross-coordinator and lifecycle (batch-1 API, linker seam reload, restart clears episodes, row volume);
C test authority by per-site mutation of each INV-MUTE-KNOWN condition. Plan review: one adversarial pass plus
framing G (goal fidelity: does it close the stranger-on-driveway gap without paging residents at their own door).

## 10. Non-goals
No change to cooldown, gates, severity, D10.5, vehicle path, or seams. No new config-flow fields or entities. No
census or HVAC change. No Protect face-name work. No migration of `_camera_key_for_sensor`. No soak.

## 11. Plan completion tracking
Builder lists each of D0-D4 as done or deferred with reason and destination card. Known deferrals now: none.
README write-back table after live validation: D1 and D3 Live rows, plus row-count-by-reason for the first day.
