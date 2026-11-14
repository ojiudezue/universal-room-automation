# Plan review: scoped egress mute (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Plan: `docs/planning/PLANNING_perimeter_egress_mute_scoped.md` (develop 42fe480f). Tier 2-DB plan review: one
adversarial pass (framing 1, completeness and build-prediction) plus framing G (goal fidelity). Read-only: no
pytest, no HA state change. HVAC and presence state-of-play docs: not applicable (no HVAC or presence-sensor
surface; the change consumes F3 crossings only).

**Verdict: FIX-PLAN.** The design direction is right and the measurement re-derives exactly. Two HIGH findings
change what gets delivered: the crossing record lands 45 s after the door edge (most resident walk-outs will page),
and the planned lookup key does not match how records are keyed (the mute would silently never fire). Both are
fixable in the plan with code that already exists.

## Verified (holds)

- **Measurement method re-derived.** Recorder probe (read-only, `ssh ha python3 -` over `home-assistant_v2.db`,
  on-edges of `*_person_detected` + `*_person_occupancy_2`, egress = doorbell_lite, madrone_g6_entry,
  front_door_aerial, garage_a): per-camera muted/total = g5_bullet 135/208, rear_ptz 34/109, front_side_ptz 27/44,
  utilities_ptz 18/77. Exactly the plan's numbers. Script:
  `/Users/okosisi/Code/universal-room-automation/.claude/tmp/planrev_mute_probe.py`.
- **Mute is the only pre-gate edge drop on the person path** that reads an egress stamp. Stamp writers:
  `perimeter_alert.py:942` (global), `:945` -> `_note_egress_stamp` `:5126` (per camera). Readers: only
  `_egress_stamp_for` `:5133-5142`, called only at `:1370`. The global stamp is read at `:5137` only. Edge capture,
  leg-fire telemetry and linker feed (`:4378-4400`) run before the mute and are unaffected.
- **REUSE claims.** `presence.get_last_crossing` exists on 1fb058db (`presence.py:6009`, sync, never raises) ->
  `EgressDirectionTracker.get_last_crossing` (`transit_validator.py:1044`; note the file is top-level, not under
  `domain_coordinators/`). `CrossingRecord` (`transit_validator.py:944`) lacks the synthetic flag; the bus carries it
  (`:2227`). `ExteriorTrackLinker.adjacent_cameras` (`exterior_track_linker.py:1085`) normalizes, never raises,
  returns empty on unknown camera (fail-open is correct). `_record_gate` `:4639` -> `_persist_gate_decision` `:4676`
  is fire-and-forget, gated on `_active` and teardown. Census `_get_tracked_person_slugs` `camera_census.py:3899`,
  guests `:4016`.
- **INV-MUTE-KNOWN is falsifiable** (each of (a)-(e) is a separate testable condition, and "a drop with no row" is
  observable). INV-MUTE-FAILOPEN is falsifiable. D1's "raw egress edge alone, no record -> alert at 1 s" is a good
  discriminator against "the mute just got shorter".
- **Restart:** episode dict (RAM) and tracker records (RAM) both empty after restart, so the first post-restart
  minutes mute nothing. Safe direction. Plan should say so in one line (LOW-4).

## Findings

**HIGH-1 (framing G + build-prediction): the crossing record lands 45 s after the door edge, not "seconds".**
Plan section 4 says the record "lands seconds after the door camera's on-edge". It lands at
`EGRESS_ENTRY_WINDOW_SECONDS = 45` (`const.py:3355` on 1fb058db): the egress handler schedules
`async_call_later(self.ENTRY_WINDOW_SECONDS, _delayed_resolve)` (`transit_validator.py:1378-1397`) and the record
is written inside `_resolve_direction` after the bus fire (`:2244-2262`). Probe: of the 214 currently-muted edges,
**119 (56%) fall less than 45 s after the first egress edge in their window**, 178 (83%) less than 45 s after the
latest one. A resident walking out the front door reaches g5_bullet before any record exists, so the mute declines
and the resident is paged on their own departure. Add the 17% attach rate at >= 0.9 and the realistic outcome is
that almost every resident walk-out alerts. The plan's "about 8 alert-minutes a day" upper bound is therefore
the wrong framing (it is the expected value, not a bound), and section 7's latency row presents a real flood as a
non-issue. Fix in plan: (a) state this residual honestly with the 56% figure; (b) decide a resolution. Options
consistent with the latency rule: keep "send now" and accept the pages; or let the mute also accept an identity
already known on the door camera at the door edge (the D10.5 cache below sees the bus event, which carries identity
known at resolve time, so it does not help before +45 s either); or the operator accepts a per-edge alert for a
known walk-out. This is an operator decision, so it belongs in section 8 as Q3, not implied as solved.

**HIGH-2 (build-prediction): the lookup key does not match how crossing records are keyed.** D1 says
"read `presence.get_last_crossing(<that camera's sensor>)`". `CrossingRecord.camera = egress_camera_id`, which is
the triggering entity of whichever leg fired: Frigate `_person_occupancy_2`, Protect `_person_detected`, or a
`sensor.*_person_count` (`transit_validator.py:1370`, `:1418`, `_resolve_direction(entity_id, …)` `:1394`, `:1445`).
`_last_crossing_by_camera` keeps the last record per that entity id (`:1042`). A door camera has 2-3 legs, so a
builder picking "the" sensor will miss most records, and count-sensor records have no entry in perimeter's
`_sensor_to_camera` at all. Failure direction is toward alerts (safe), so tests built on one leg will pass and the
mute will never fire live. Fix: key by camera key, not entity id (see MEDIUM-1, which solves it).

**MEDIUM-1 (REUSE miss): perimeter already caches F3 identities per camera key with the synthetic flag.**
`_note_egress_identity` (`perimeter_alert.py:5155-5166`) listens to `ura_person_egress_event`, maps
`egress_camera` through `_egress_key` (`:5144`, handles binary_sensor and camera ids), keeps the last 16 entries per
camera key for 600 s, and stores `(ts, pid, conf, synthetic)` (`:5164-5165`). That is the record the mute needs:
keyed by camera key (fixes HIGH-2), a list rather than last-wins (fixes MEDIUM-2), already carries the synthetic
flag (removes D0 and the whole batch-1 sequencing dependency). Two gaps to extend: it drops events with no
`person_id` (`:5158-5159`; the mute needs unknown crossings for the veto in MEDIUM-2), and the listener registers
only when dual-role cameras exist (`:1017`; live = none). Plan section 1 rejects `_known_identity_for` but never
considers this cache. Fix: record a REUSE-or-BUILD verdict for `_recent_egress_identity`; recommended REUSE + extend
(store unknown crossings too, register when egress cameras exist), and drop D0 unless the read API is wanted for
another reason.

**MEDIUM-2 (framing G): "there exists a known crossing" mutes even when a stranger also crossed.** INV-MUTE-KNOWN
is existential: one tracked-resident record on an adjacent door mutes P. A resident and a stranger crossing the same
door (or two adjacent doors) in the window mutes the stranger's driveway edge. With batch-1's last-per-entity store
the outcome depends on which leg fired last. Fix: add condition (f): no crossing in the window on any adjacent door
lacks a >= 0.9 tracked-resident identity (any unknown crossing vetoes the mute). Test: `test_mute_vetoed_by_unknown_crossing`.

**MEDIUM-3 (framing G): the card's literal scenario is narrowed, not closed; name the residual.** "A stranger on
the driveway while a resident is at a door" is still muted for up to 120 s (cap 300 s) when the resident's crossing
is known and the stranger never crosses a door. That is what the card asked for ("suppress only for a known resident
crossing at a related door"), so it is acceptable, but section 3 or 7 must state it as the decided residual. Optional
cheap tightening to offer the operator: refuse the mute when P's person count exceeds the number of known crossers in
the window.

**MEDIUM-4 (garage seam question framed wrongly).** Q1 recommends "add seams by editing `exterior_seams.json`".
The live file's own `_egress_note` says garage_a/garage_b are interior egress cameras that "must NOT appear in the
ring", and the egress-adjacent set is derived from the exterior list only (`exterior_seams.py:306-325`
`derive_egress_adjacent`). Adding a garage seam would also change linker track linking and burst-demote adjacency
(`has_recent_adjacent_activity`, `exterior_track_linker.py:1098`), a side effect outside this card. Correct framing:
a garage crossing has no exterior neighbour by design; if the operator wants garage crossings to mute the driveway,
that needs a separate interior-egress-to-exterior mapping (a new spec key read only by the mute), not a seam. The
recommendation "accept, more alerts never fewer" stands; the "edit the seam file" advice must go.

**LOW-1: window is ~9 days, not 14.** The recorder returns edges only from 11-06 to 11-14 (purge horizon). 607 edges
over ~9 days is ~67/day, not ~43/day; per-day row and alert estimates in sections 2 and D3 ("~17/day") are low by
about 1.5x. The URA DB figures (226 crossings) may be a true 14 days; say which source spans what.

**LOW-2: D3 row-gating reads the global stamp the plan says the mute stops reading.** "A declined row is written
only when an egress on-edge occurred in the window" needs `_last_egress_time` or the per-camera stamp. Fine, but
section 4 should list it as a remaining reader, and it should use the adjacent doors' per-camera stamps, not the
global one, or declined rows will be written for non-adjacent door activity.

**LOW-3: `demoted: mute` overloads the row field.** In existing rows `demoted` means severity was lowered; a full
drop is a different outcome. Use `"suppressed": true` (or reason alone) and keep `demoted` False, so later queries do
not mix them.

**LOW-4: unstated details the builder will guess.** Direction is not conditioned (an `ambiguous` record with
identity mutes; say whether that is intended). Protect face names back-fill 1-2 min later and never upgrade a
record (identity is fixed at +45 s). Restart clears episodes and records (state it). D4 has a flood trip-wire but no
zero-fire trip-wire on the new gate (no `egress_mute` rows in 24 h while egress edges occurred = wiring broken);
add one per the fire-check rule.

**LOW-5: knob clamp.** `EGRESS_MUTE_MIN_IDENTITY_CONF` "values < 0.9 clamp to 0.9" mirrors `_known_identity_for`
`:5180`; good, but name the test that pins the clamp.

## Framing G summary

Security gap: closed for unknown, below-0.9, synthetic, non-adjacent and long-chained crossings (the 11-14
25-minute case is fixed by D2's no-chaining cap). Residual: known-resident crossing plus non-crossing stranger, up
to the window (MEDIUM-3), and resident-plus-stranger crossings until MEDIUM-2 is added. Notification flood: the plan
understates it. Because records land at +45 s (HIGH-1) and identity attaches at >= 0.9 only ~17% of the time, most
resident departures and many arrivals will now alert; that is the latency rule working as written, but the operator
should choose it knowingly. Doctrine: >= 0.9 floor, F3 only (never F4), guests never mute: all hold. Reconciliation
table: complete except the D10.5 cache reuse (MEDIUM-1) and the seam-file side effects (MEDIUM-4).

## Must-fix in the plan before build

1. HIGH-1: state the 45 s record latency and the 56% figure; add Q3 for the operator.
2. HIGH-2 + MEDIUM-1: key crossings by camera key; REUSE and extend `_recent_egress_identity` (or justify batch-1).
3. MEDIUM-2: add the unknown-crossing veto as condition (f) with its test.
4. MEDIUM-3: name the residual.
5. MEDIUM-4: rewrite Q1; no seam-file edits for garages.
6. LOWs 1-5 as one-line edits.
