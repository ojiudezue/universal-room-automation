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

## D1 — DAO (one SELECT via `_db_read`, one UPDATE via `_db`)
- SELECT `find_unnamed_exit_crossings(t_lo_iso: str, t_hi_iso: str) -> list[tuple[int,str,str]]` using the READ context `_db_read` (database.py:470, transient query_only — NOT the write queue): `SELECT id, timestamp, egress_camera FROM person_entry_exit_events WHERE person_id IS NULL AND direction = 'exit' AND timestamp > ? AND timestamp <= ? ORDER BY timestamp DESC, id DESC` (deterministic tie-break — F5). Existing `timestamp` index (database.py:803) covers it; **no new index**.
- UPDATE `backfill_entry_exit_person_id(row_id: int, person_id: str, confidence: float) -> bool` via the WRITE context `_db` (database.py:322, the write queue — as `update_transition_validation` does): `UPDATE person_entry_exit_events SET person_id = ?, confidence = ? WHERE id = ? AND person_id IS NULL`. The `AND person_id IS NULL` makes it idempotent (a second backfill of the same row is a no-op → returns False/0-rows). `id` is the `INTEGER PRIMARY KEY AUTOINCREMENT` (database.py:794).
- **Acceptance:** UPDATE sets person_id on a null exit row, no-op if already set; SELECT returns only null-person exit rows in the window, nearest first, deterministic on ties.

## D2 — backfill matcher on the departing edge (async, tz-safe)
The departing branch of `_on_crossing_tracker_state_change` (camera_census.py:~3974) is `@callback` (sync) — it CANNOT await. So on any admitted departing edge (F4: `old=="home"` and new is any non-`_BAD` value — INCLUDING `home→<named zone>`, which is a real departure — not only `home→not_home`) for slug S:
- schedule `t = self.hass.async_create_task(self._backfill_exit_identity(S, t_edge))`; add `t` to a tracked `self._backfill_tasks: set`, `t.add_done_callback(self._backfill_tasks.discard)`; cancel all pending in census teardown (F1 — this IS the untracked-task class; track it).
- **`_backfill_exit_identity(slug, t_edge)` (async helper) does the DB work:**
  1. **TZ CONTRACT (F2 — CRITICAL, the silent-zero-match trap):** the INSERT writes `datetime.utcnow().isoformat()` = **naive-UTC, no offset** (database.py:3919). The edge `t_edge` is tz-aware (`dt_util.utcnow()`), and nearby egress code uses LOCAL (`dt_util.now()`). Derive the SELECT bounds to match the INSERT byte-for-byte: `t_hi = t_edge.astimezone(timezone.utc).replace(tzinfo=None); t_lo = t_hi - timedelta(seconds=BLE_EGRESS_EXIT_BACKFILL_WINDOW_S); bounds = t_lo.isoformat(), t_hi.isoformat()` (no offset suffix). An acceptance test MUST fail if a tz-aware or local bound is used.
  2. rows = `find_unnamed_exit_crossings(t_lo_iso, t_hi_iso)`. If empty → `_ble_exit_edge_no_match_count += 1`, return (fail-safe, row stays null).
  3. **Cross-resident guard (invariant e — F3):** if `self._ble_zero_tracker_slugs` is non-empty (a tracked resident who currently derives ZERO bluetooth_le trackers — see D-note), abstain → `_ble_exit_ambiguity_abstain_count += 1`, return. `_ble_zero_tracker_slugs` is a NEW set REBUILT each derive pass (NOT the ever-accumulating `_ble_zero_tracker_warned`, which would permanently disable backfill after one boot blip).
  4. pick `row_id` = the nearest (first row). `backfill_entry_exit_person_id(row_id, slug, BLE_TRANSITION_ONLY_CONFIDENCE)`; on True → `_ble_exit_backfilled_count += 1`. (The SQL `IS NULL` guard is the single-use mechanism — no separate in-memory consumed-set needed; a concurrent double-fire loses the race harmlessly.)
- INV-EGRESS-ID is already enforced upstream at camera_census.py:~3945 (`slug not in tracked → return` before the departing branch) — do NOT add a second unreachable guard (F6).
- Sibling null rows (F5): a physical departure may leave 1 named + N null exit rows (multi-camera-stem, dedup is per-stem/5s only); the null siblings STAY null (fail-safe). Accepted.
- **Acceptance:** D0-shaped case (exit row null at T; S's not_home edge at T+369s) → row.person_id==S at the correct UTC-naive bound; a LOCAL/tz-aware bound → zero match (RED); two residents' edges each backfill their own nearest; `home→zone` departure is eligible; no in-window null exit row → no-op+counter.

## D3 — observability + knob + the zero-tracker set
- `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S = 600` (const.py, module rung; comment cites D0 p90 612).
- Surface `_ble_exit_backfilled_count`, `_ble_exit_edge_no_match_count`, `_ble_exit_ambiguity_abstain_count` on the persons-in-house sensor.
- **`_ble_zero_tracker_slugs: set[str]` (NEW)** — REBUILT on every `_derive_ble_crossing_trackers` pass (add a slug when its bluetooth_le count is 0 that pass; the set is freshly constructed each pass, never accumulated). This is the live "who is BLE-invisible right now" signal the (e) guard reads. Do NOT reuse `_ble_zero_tracker_warned` (ever-warned, never cleared — F3).

## Non-goals
- Crossings resolved `ambiguous` never produce a row at all (INSERT gate `direction != "ambiguous"`, transit_validator.py:1829) → permanently unbackfillable. Accepted.
- Startup sweep of pre-restart unnamed exits (a not_home edge during downtime is missed → row stays null; acceptable fail-safe).
- Face exit naming (separate). Multi-departer-within-seconds perfect ordering (attribute nearest; ambiguity abstains).

## Tier-3 review framings (framing-disjoint)
- **A correctness:** the matcher (nearest, window sign — crossing BEFORE edge), the UPDATE idempotence (`IS NULL` guard), INV-EGRESS-ID.
- **B integration/lifecycle:** DB write-queue interaction, no double-backfill across the SQL guard + in-memory set + restart, the SELECT cost per departing edge, no regression to entry path or the INSERT.
- **C test-authority:** per-site source mutation RED-on-neuter for {UTC-naive bound (a tz-aware/local bound → zero match), window match, nearest-with-deterministic-tiebreak, IS-NULL idempotence, cross-resident abstain via `_ble_zero_tracker_slugs`, home→zone eligibility}. Do NOT target the backfill-site INV-EGRESS-ID (unreachable — guarded upstream at :3945, F6); if an INV anchor is wanted, mutate the upstream :3945 guard.
- **D adversarial:** falsify the invariant — double-backfill, one edge → 2 rows, backfill a crossing AFTER the edge, wrong-name when true departer is BLE-invisible, non-tracked slug, a race where the row isn't written yet when the edge fires (crossing+45s INSERT vs edge at +369s — confirm ordering holds; what if the resolver INSERT is delayed?).

## Acceptance criteria (cycle)
- **Test:** D1/D2/D3 anchors, each RED-on-neuter.
- **Live:** next real departure → the exit crossing row (null at +45s) gets `person_id` filled ~5-6 min later; `_ble_exit_backfilled_count` moves; an exit with no BLE edge stays null.
- **Live (discriminating):** the backfilled name is the departer, not a co-present resident; a second exit isn't double-named.
