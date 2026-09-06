# PLANNING — Egress EXIT identity via backfill

**Card:** EGRESS-EXIT-IDENTITY-BACKFILL-1. **Tier:** 3 (new DB row-UPDATE write path on the mission-critical egress producer; wrong attribution = corrupted person_id).
**Follows:** v5.96.0 (BLE entry producer, entry-only). Operator chose backfill: *"someone exited; that someone is 'person' after 5 min is ok — timeliness AND accuracy."*

## Institutional context verified (prior-art scan — mandatory per CLAUDE.md Tier-2+ rule)
Greps run 2026-09-05:
- **`person_entry_exit_events` DAO** — INSERT `database.log_entry_exit_event` (database.py:3903), SELECT (:3946), table + indexes (:793-808, indexed on `timestamp` and `(person_id,timestamp)`). **No UPDATE method.** → **BUILD** `backfill_entry_exit_person_id`, REUSING the row-UPDATE pattern already used ~15× (canonical: `update_transition_validation` UPDATE room_transitions, database.py:3872-3899).
- **not_home departing edge** — already detected + counted in `_on_crossing_tracker_state_change` else-branch (camera_census.py:3856-3976, `_ble_departing_edge_seen_count` at :3976). → **REUSE/EXTEND** this handler; the departure signal exists, we only add the backfill lookup+UPDATE.
- **`BleTransitionLeg.direction`** already has `"departing"` (camera_census.py:244). → REUSE (no new struct).
- **async_call_later supersession** (`energy_write_verify` precedent) — **NOT NEEDED**: backfill is edge-reactive (the not_home edge fires ~369s after the crossing, when the null exit row already exists from the +45s resolver INSERT), not timer-deferred. Simpler; no untracked-task hazard.
- **INV-EGRESS-ID** (`PLANNING_egress_identity_producer.md`) — person_id must be a canonical `tracked_persons` slug. Enforce at backfill.
- **D0 probe** — exit `not_home` edge lags the crossing by median +369s, p90 +612s → window `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S = 600`.
- **Reuse ledger:** REUSE the departing-edge handler, the SELECT/table, the UPDATE pattern, the derived bluetooth_le tracker map + sticky classification (v5.96.0), the D-2 cross-resident guard shape, INV-EGRESS-ID. BUILD: the UPDATE DAO + the backfill matcher.

## Falsifiable invariant (Tier-3)
> An exit crossing row's `person_id` is set to R **iff** one of R's bluetooth_le trackers makes a `home→not_home` edge within `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` **after** that crossing, and the row was previously NULL and `direction`==exit. (a) each crossing is backfilled **at most once**; (b) each not_home edge backfills **at most one** crossing (the nearest unnamed exit crossing in-window); (c) the backfilled slug ∈ `tracked_persons`; (d) an unmatched edge, or a crossing with no matching edge, leaves `person_id` **NULL** (fail-safe — never a wrong name); (e) when a tracked resident with zero bluetooth_le trackers could be the departer, abstain/record ambiguity rather than mislabel (the D-2 guard, exit side).

Falsified by: a row backfilled twice; one edge backfilling ≥2 rows; a backfill where the crossing is AFTER the edge or outside the window; a non-tracked slug written; a wrong-name write when the true departer is BLE-invisible.

## D1 — UPDATE DAO
`database.backfill_entry_exit_person_id(rowid: int, person_id: str) -> bool` — UPDATE person_entry_exit_events SET person_id=?, (confidence/agreement columns as appropriate) WHERE rowid=? AND person_id IS NULL (the `IS NULL` guard makes it idempotent — a second backfill of the same row is a no-op). Follow update_transition_validation's shape (write-queue, error handling). Also a SELECT helper `find_unnamed_exit_crossings(t_lo, t_hi) -> list[(rowid, timestamp, egress_camera)]` ordered by nearest.
- **Acceptance:** UPDATE sets person_id on a null exit row and is a no-op if already set; SELECT returns only null-person exit rows in the window.

## D2 — backfill matcher on the departing edge
Extend `_on_crossing_tracker_state_change` departing branch (camera_census.py:~3976): on a `home→not_home` edge for slug S at `t_edge`:
1. Query `find_unnamed_exit_crossings(t_edge − BLE_EGRESS_EXIT_BACKFILL_WINDOW_S, t_edge)`.
2. If ≥1 match: pick the NEAREST (largest timestamp ≤ t_edge). Cross-resident guard (invariant e): if a tracked resident currently derives zero bluetooth_le trackers, abstain (record ambiguity counter) — can't be sure the BLE-visible S is the departer. INV-EGRESS-ID: confirm S ∈ tracked_persons.
3. `backfill_entry_exit_person_id(rowid, S)`; on success increment `_ble_exit_backfilled_count`; mark that rowid consumed for this process (in-memory set) so the same edge/row can't double-backfill (belt with the SQL `IS NULL` guard).
4. If no match: increment `_ble_exit_edge_no_match_count` (fail-safe, row stays null).
- Must NOT fire on arriving edges (entry is v5.96.0's path). Must NOT touch a non-exit row.
- **Acceptance:** the D0-shaped case (exit crossing at T null; S's not_home edge at T+369s) → row.person_id == S; two residents' edges each backfill their own nearest crossing; an edge with no in-window null exit row → no-op + counter.

## D3 — observability + knob
- `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S = 600` (const.py, module rung; comment cites D0 p90 612).
- Surface `_ble_exit_backfilled_count`, `_ble_exit_edge_no_match_count`, `_ble_exit_ambiguity_abstain_count` on the persons-in-house sensor.

## Non-goals
Startup sweep of pre-restart unnamed exits (a not_home edge during downtime is missed → row stays null; acceptable fail-safe). Face exit naming (separate). Multi-departer-within-seconds perfect ordering (attribute nearest; ambiguity abstains).

## Tier-3 review framings (framing-disjoint)
- **A correctness:** the matcher (nearest, window sign — crossing BEFORE edge), the UPDATE idempotence (`IS NULL` guard), INV-EGRESS-ID.
- **B integration/lifecycle:** DB write-queue interaction, no double-backfill across the SQL guard + in-memory set + restart, the SELECT cost per departing edge, no regression to entry path or the INSERT.
- **C test-authority:** per-site source mutation RED-on-neuter for {window match, nearest pick, IS-NULL idempotence, single-use, cross-resident abstain, INV-EGRESS-ID}.
- **D adversarial:** falsify the invariant — double-backfill, one edge → 2 rows, backfill a crossing AFTER the edge, wrong-name when true departer is BLE-invisible, non-tracked slug, a race where the row isn't written yet when the edge fires (crossing+45s INSERT vs edge at +369s — confirm ordering holds; what if the resolver INSERT is delayed?).

## Acceptance criteria (cycle)
- **Test:** D1/D2/D3 anchors, each RED-on-neuter.
- **Live:** next real departure → the exit crossing row (null at +45s) gets `person_id` filled ~5-6 min later; `_ble_exit_backfilled_count` moves; an exit with no BLE edge stays null.
- **Live (discriminating):** the backfilled name is the departer, not a co-present resident; a second exit isn't double-named.
