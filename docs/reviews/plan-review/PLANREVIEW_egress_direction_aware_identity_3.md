# Plan review 3: direction-aware egress identity (rev 3)

Plan: `docs/planning/PLANNING_egress_direction_aware_identity.md` @ 7373b3d9 (develop). Answers review 2 (9148b4f6).
Reviewer: ura-reviewer, 2026-11-14. Code re-read on develop @ 7373b3d9 and on `release/batch-2` (worktree
`.claude/worktrees/batch-2` @ dbff8335, merges before step 7 builds). Presence/identity manuals not re-litigated; no
corrections-ledger claim re-asserted.

**Verdict: FIX-PLAN (narrow).** Review 2's four HIGHs are fixed in substance. Rev 3 introduces one new HIGH (the
perimeter follow-up extension spins at zero delay as written) and one HIGH layer conflict (the plan's private
`_amend_crossing` is a second amend path beside the contract's existing G3 seam). Batch-2 already ships part of A7 and
A8, so three §14 rows must flip to REUSED. Everything else is MEDIUM/LOW and can be fixed in the same edit; no new
review round is needed if the fixes land as stated below (orchestrator spot-check is enough).

Rev 3 does not reduce anything named today: attached names keep t_E + 45 s, perimeter keeps all four evidence paths on
door cameras (verified against `perimeter_alert.py:5213-5261`), and the declared deltas (QB zone entry, Q7 untracked)
are operator questions, not silent trades. One wording issue on that point is R3-M3.

## 1. Review 2 findings: fix present and correct?

| Finding | In body | Correct? | Evidence / note |
|---|---|---|---|
| B-H1 ring | §6.4, INV-RING, M62 | Yes | `_record_crossing` `transit_validator.py:1039-1042` keeps both assigns; amend is by exact `source_ref` (`:2259-2261` format `egress:{camera}:{iso}`), camera passed, not parsed. But see R3-H2 (amend path duplicates contract G3) |
| B-H2 pair vs bus | §6.6, INV-SECURITY-BAR (b), M65 | Yes in design; R3-H1 breaks the follow-up extension as written | Timing note verified: `_known_identity_for` matches `abs(edge − ts) ≤ MATCH_S` (`perimeter_alert.py:5214-5218`), record exists from t_E + 45 s (`transit_validator.py:2247`, after bus `:2215`), so the edge-time demote cannot see the record at default knobs; follow-up is the reachable path. Correct |
| B-H3 / G-H1 | §6.7, INV-NO-NAME-LOSS, M66 | Yes | Face-leg branch `:5237-5261` and synthetic branch `:5231-5236` stay; only the NM call moves, master-gated. Message is built by perimeter (`:5571-5573`, `_followup_person_name` uses `friendly_name`, not `display_of`) so byte-identity holds only if `send_perimeter_identity` receives the prebuilt message, which §6.7 says. Correct |
| B-H4 seam names | §3 row 3, §6.3 | Yes | `subscribe_person_edges(cb, *, persons, kinds)` matches contract :303; G6 polled. Correct |
| B-M1 | §6.2 K1-K5 | Yes | |
| B-M2 | §6.2 K1 predicate, M68 | Yes | |
| B-M3 | A7 | Partly wrong after batch-2 | `PersonArrivingPayload` exists on batch-2 (`domain_coordinators/signals.py:28-70`, `from_signal` only, no `ts`, no `to_signal`). Contract :186 citation is CORRECT for batch-2. See §3 |
| B-M4 | A8 | Wrong after batch-2 | `PersonCensus.tracked_person_slugs()` exists on batch-2 `camera_census.py:4061` (RA6). REUSED |
| B-M5 | §6.3 (i) vs supersede | Yes | D2 test named |
| B-M6 | §6.3 waiter start, M67 | Yes | Verified: between resolver `:2192` and INSERT `:2348` the only `await` is the INSERT. LOW: waiter registration must sit OUTSIDE the observational `try` around `_record_crossing` (`:2242-2264`) or a record-store exception silently drops a candidate; say so |
| B-M7 | §6.3 (c) | Yes | |
| B-M8 | A5, A6 | Fix present; A5 needs changing (§3) | |
| B-M9 | §6.8 | Yes | |
| B-M10 | §5.1, gate relabel | Yes | |
| B-L1 | §2 header, A7 | Wrong direction | Lines 5622/5881/1141 are develop; batch-2 (merging first) has 5678/5937/1172, which is what the contract says. Builder on post-merge develop will find the contract right and the plan wrong. Cite by symbol, not line |
| B-L2 | §3 row 5 | Yes | |
| B-L3 | A8 `egress_naming_enabled()` | Duplicate | batch-2 already has `PersonCensus.egress_identity_enabled()` `camera_census.py:4085` wrapping `_is_egress_identity_enabled`. REUSE it; drop the new name |
| B-L4 | §6.3 | Yes | |
| B-L5 | §6.7 | Yes | |
| B-L6 | §6.7 | Yes in intent; see A9 | |
| B-L7 | §15 exact row | Yes (orchestrator-owned) | |
| G-M1 | §0, §5.3, QA, D0 (j) | Yes | default = today's behaviour |
| G-M2 | §5.4, QB, D0 (i) | Yes | |

## 2. Fresh-eyes regression pass on rev 3 additions

### HIGH

**R3-H1. The perimeter follow-up "do not expire while pending" spins at zero delay.**
`_schedule_followup_tick` computes `delay = max(0, min(POLL_S, WINDOW_S − elapsed))` (`perimeter_alert.py:5505-5507`).
Once `elapsed ≥ 90`, delay is 0, and `_tick` adds `delay` (0) to `elapsed`, so §6.6's re-poll becomes
`async_call_later(hass, 0, ...)` in a loop until `pair_state` leaves `pending`: up to ~45 s (t_E + 120 vs edge + 90
with t_E ≤ edge + 15) of back-to-back event-loop callbacks, each running `_known_identity_for` (census reads + leg
resolution). A builder will add the `pending` check in `_followup_check` (`:5537`) and reuse the scheduler unchanged.
Also unbounded: if the pair timer never fires (teardown race, exception in the K5 check), `pending` never clears and
the loop never ends. Fix in the plan: in the extension, tick at `PERIMETER_IDENTITY_FOLLOWUP_POLL_S` (not the
window remainder), and hard-cap the extension at `WINDOW_S + EGRESS_PAIR_GUARD_WINDOW_S` elapsed (then expire as
today, counted `followup_pair_pending_expired`). Add a test (`::test_followup_pending_extension_ticks_at_poll_and_caps`)
and a mutation (delay = window remainder → RED). The pair-timer exception path must amend to `conflict` (fail-safe for
security), not leave `pending`.

**R3-H2. `_amend_crossing` is a second F3 amend path beside the contract's G3.**
Contract §2.3 ingest row (`CONTRACT_person_awareness_layer.md:124`) already names
`EgressDirectionTracker.attach_crossing_attribute(source_ref, key, value, provenance)` (G3) as the owner-side way to
change a crossing after resolution. Rev 3 adds `_amend_crossing(source_ref, **changes)` (§6.4) and A4 "owner-only
amend by `source_ref`" without mentioning G3. Two amend mechanisms on one record is exactly the "one ingest per fact"
leak the contract exists to stop, and crossing vision / step 8 will build against G3. Fix: one owner-side amend
primitive. Either A4 redefines G3 as the ring amend (identity fields written by the owner; attributes by
`attach_crossing_attribute` delegating to it) or `_amend_crossing` is stated to be G3's implementation. Pick one in
§14 and in §6.4.

### MEDIUM

**R3-M1. Pair gating on the egress record does not change the security outcome while the face legs are fresh.**
With the master on, a pending/conflict record is skipped, but the face-leg branch (`perimeter_alert.py:5237-5261`)
reads the SAME two-camera face entities that produced the 0.9 attach (`census._resolve_face_legs(cam_key)`), with the
same `last_changed ≥ edge − 15` freshness, and names Jaya anyway. INV-SECURITY-BAR (b) holds as worded ("from the
egress record"), and §12 declares the face-leg pair residual, so this is not a leak against the plan. But the D3
Verify "a perimeter follow-up on that door neither names Jaya from the egress record nor expires while pending"
will pass while perimeter still sends "that was Jaya" via `face_leg`. State in §6.6 that the H2 mechanism protects
only the record path, and make the D3 test assert the source label (`egress_event` absent), not "Jaya not named".
Put the residual in front of the operator with QA (it is the same Jaya/Ezinne swap risk on a security consumer).

**R3-M2. A9 puts a read on the tracker, outside the F3 read surface.** Contract §4.1 places every F3 pull on
`PresenceCoordinator` (`get_last_crossing` `presence.py:6009` develop / `:6043` batch-2 delegates to the tracker;
G5 `entry_areas` likewise). Perimeter calling `EgressDirectionTracker.door_camera_device_ids()` directly is a second
read surface. Expose it as a presence delegate next to `entry_areas`. Same for A3 `get_crossing` and G2: callers
(perimeter, `ArrivalNotifier`) go through presence, not `hass.data` to the tracker.

**R3-M3. INV-NO-NAME-LOSS leaves one change unlisted: master-on perimeter stops reading its cache, so any cache-only
match is lost.** The cache keeps 600 s / 16 entries per key (`perimeter_alert.py:5166-5174`); the ring keeps 1800 s /
32. Ring ⊇ cache for every record that the bus carried with `person_id` set, so no loss in practice, but the
INV-NOOP/INV-NO-NAME-LOSS replay must include a record that was written to the bus but whose `_record_crossing`
raised (the store is observational, `:2262-2263`): the cache names it, the ring does not. Either make the master-on
read fall back to the cache when the ring has no record for that key and window, or list it as a declared delta.

**R3-M4. `freshest_gps_fix` "registry-resolved trackers of that person" has no stated source.** A person's trackers
are in the person config / `person.*` `device_trackers` attribute, not in the entity registry. A builder will either
read the attribute (a `person.*` state read inside the F3 owner, which the contract §2.1 forbids outside the ingest
point) or name-guess `device_tracker.<slug>_*` (registry rule violation). Name the source in A13 (the person
collection storage or the attribute, as an allowlisted producer-internal read) and add a test that a tracker named
like the person but not attached to it is ignored.

**R3-M5. `notify_arrival(record)` depends on a record that may not exist.** Today the notify takes plain values
(`transit_validator.py:2278`) and runs even if the record store raised. If the moved function takes the record and
the store failed, the original arrival notification is lost (a name-loss on the master-off path, breaking INV-NOOP).
Build the record outside the `try`, or keep the value signature.

### LOW

- R3-L1. `ArrivalNotifier` RAM ledger TTL "= ring age": state it as `EGRESS_CROSSING_RING_MAX_AGE_S` by name.
- R3-L2. §6.6 "at most 75 s later": the real bound is t_E + 120 − (edge + 90) ≤ 45 s past the window given MATCH_S
  15; 75 s is safe but say what it bounds.
- R3-L3. Today's arrival notify uses `coordinator_id="presence"` (`:2698`); state that `notify_arrival` keeps it
  (byte-identity), not `"arrival_notify"`.
- R3-L4. Perimeter reads census privates today (`_get_tracked_person_slugs`, `_get_known_face_guests`,
  `_resolve_face_legs`, `perimeter_alert.py:5198-5240`); batch-2 RA6 adds the public wrappers. The master-on branch
  rev 3 writes should use the public names.

### Builder-prediction summary
Most likely wrong: the zero-delay extension (R3-H1); a new `_amend_crossing` built beside G3 (R3-H2); reading
`person.*` attributes for GPS trackers (R3-M4); new `egress_naming_enabled` / `tracked_person_slugs` duplicating
batch-2 wrappers (§3); line numbers off by ~56 after the batch-2 merge (B-L1).

## 3. Contract additions A1-A13 (layer check; batch-2 grepped per coordinator request)

Batch-2 grep (`.claude/worktrees/batch-2` @ dbff8335) for every §14 surface: present = `tracked_person_slugs`
(`camera_census.py:4061`), `egress_identity_enabled` (`:4085`), `PersonArrivingPayload` (`signals.py:28`,
`from_signal` only), `display_of` (`person_ids.py:56`). Absent = `get_person_edges_since`, `subscribe_person_edges`,
`location_moves_since`, `get_crossings_since`, `get_crossing`, `dispatch_person_arriving`, `door_camera_device_ids`,
`SIGNAL_EGRESS_ENTRY_CONFIRMED`, `IDENTITY_PROVENANCE_FACE_*`, `min_confidence`. Raw F5 sends still present on batch-2
(`presence.py:5678`, `:5937`, `person_coordinator.py:1172`).

| # | Verdict | Reason |
|---|---|---|
| A1 `get_person_edges_since` | ACCEPT | Same `ResidencyTracker.recent` ledger as G1; pull sibling, no second store. Contract must say it lives on presence next to G1 |
| A1b `counted` on G1 | ACCEPT | Field of the one ledger |
| A2 G6 shape | ACCEPT | Pull only; shape is additive |
| A3 `get_crossing` + G2 ring semantics | ACCEPT, CHANGE placement | On presence (delegating), not on the tracker (R3-M2) |
| A4 record fields + owner amend | CHANGE | Merge with G3 `attach_crossing_attribute` into ONE owner amend primitive (R3-H2) |
| A5 `SIGNAL_EGRESS_ENTRY_CONFIRMED` | CHANGE | A second F3 push channel. There is already an un-listed one, `SIGNAL_EGRESS_EXIT_BACKFILLED` (`signals.py:39`). Define ONE F3 amendment channel (e.g. `SIGNAL_EGRESS_RECORD_AMENDED`, payload carries `role` = `arrival_confirmed` / `exit_backfilled`), list it in contract §4.2 with its allowed listeners (four display sensors, sighting producer), and migrate EXIT_BACKFILLED to it or allowlist it with an owner card. Two near-identical channels is the drift the contract forbids |
| A6 provenance constants | ACCEPT | Additive values; note `IDENTITY_PROVENANCE_VALUES` has 0 readers so no gate breaks |
| A7 `PersonArrivingPayload` | REUSED + EXTEND | Exists on batch-2. Addition is only: additive `ts=None`, `to_signal()`, and the G4 `dispatch_person_arriving` that migrates the three raw sends. Drop "correct the citation" and the line corrections (batch-2 lines match the contract) |
| A8 census wrappers | REUSED | `tracked_person_slugs()` and `egress_identity_enabled()` exist on batch-2. Delete the NEW `egress_naming_enabled` name; §6.3 / §6.7 call `egress_identity_enabled()` |
| A9 `door_camera_device_ids` | CHANGE placement | Presence delegate (R3-M2). Registry-only is right |
| A10 `ArrivalNotifier` | ACCEPT | Matches contract §7 "notification consumer"; it is the single door-naming send site |
| A11 pair_state ≠ security | ACCEPT, with wording | Say it covers egress-derived identity only; the face-leg residual (R3-M1) is named, not covered |
| A12 cache allowlist (master-off) | ACCEPT | Owner card this one, max 1, retires with the master |
| A13 R3 GPS read | CHANGE | Name the tracker-list source (R3-M4); `person.*` attribute read must be allowlisted explicitly if used |

## Must-fix before build dispatch

R3-H1, R3-H2; A4/A5/A7/A8/A9/A13 changes above; R3-M1 (test assertion + QA wording), R3-M2, R3-M3, R3-M4, R3-M5;
B-L1 rewritten as symbol citations; B-M6 LOW (waiter outside the observational try). LOWs in the same edit.
