# Plan review: PLANNING_identity_actions_v6.md rev 3 (arc step 8)

Reviewer: ura-planner (Mode 2, adversarial plan review, Tier 2-DB). 2026-11-14.
Target: branch `plan/identity-actions-v6-rev3`, commit `6282c9c9`. Rev 2 baseline: `docs/planning/archive/PLANNING_identity_actions_v6_rev2.md`.
Read: plan rev 3 and rev 2 in full, charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals, 2026-11-14 additions, drift table #15-#19).
This plan touches presence (BLE room, occupancy) and HVAC only by exclusion. The state-of-play docs were not re-read end to end for this review.
The findings below rest on code at the cited file:line, which wins over any doc.

**Verdict: FIX-PLAN.** 3 HIGH, 6 MEDIUM, 7 LOW. No CRITICAL. Scope: FOCUSED. The goal fidelity is good: nothing the operator asked for is deferred.
The two load-bearing mechanisms are mis-specified against the code, though. One is the arrival trigger site. The other is how the welcome scene "sticks".
As written, a builder would ship an INV-V6-ARRIVAL-REACHES that fails in common cases, and a scene test that discriminates nothing.

---

## Framing 1: completeness and build prediction

### Claims re-verified (PASS)

- `music_following.py:473` `_on_person_transition`; enabled-persons return `:511-518`; confidence return `:521-527`; `MIN_CONFIDENCE = 0.6` `:115`; 8 ft distance gate `:529-548` (records `low_confidence`, not `ble_too_far`). The wrapper `domain_coordinators/music_following.py:549` `_handle_person_arriving` subscribes `SIGNAL_PERSON_ARRIVING` at `:281`.
- `actuator_reconciler.py:500` `_note_manual_light_change`, `:516` URA-context skip, `:523` `automation.note_manual_light`, `:673-682` light manual-hold honour.
- `OPTIONS_RELOAD_SUPPRESS_KEYS` `__init__.py:7553`, `_NO_LIVE_ATTR_KEYS` `:7406`, subset decision `:8826`, snapshot advance `:8116`.
- `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4864`, form `config_flow.py:10414-10415`.
- HA core 2026.11.1 `homeassistant/data_entry_flow.py`, fetched from GitHub:
  - `class Required(probatio.Required)` and `class Optional(probatio.Optional)` take `visible: bool | FieldCondition | list[FieldCondition] | None`, stored as `VISIBLE_SCHEMA(visible)`.
  - `_strip_hidden_fields` exists ("Remove currently hidden fields from the schema and the submitted input").
  - `add_visible_conditions_to_serialized_schema(data_schema: probatio.Schema, ...)` writes `field["visible"]`.
  - `FlowResult.data_schema` is typed `probatio.Schema`.
  - The plan's §2 claim is accurate. It is honest that serialization inside a `vol.Schema` body is unverified (spike B0).

### Findings

**H1 (HIGH). The arrival hook inherits upstream suppressors and a race, so INV-V6-ARRIVAL-REACHES is falsifiable on legal paths.**
§5.4 places `_arrival_check` at the top of `_on_person_transition`. That function only runs when `PersonTransitionDetector` notifies listeners.
The detector drops or never emits the transition in several cases:
- First detection, with `previous_location` None or `"unknown"`: `transitions.py:182-185` returns without notifying. This is the post-restart case, and any path where the person coordinator has no previous room.
- Ping-pong: `transitions.py:240-253` suppresses the return leg. Hall → master → hall → master inside the window loses the master entry.
- Detection exception: `transitions.py:206-212`.
- Coordinator disabled (`music_following.py:485`) and same-room (`:496`), both of which come before the plan's "top" placement.
- Ordering: a BLE-sourced F5, or a slow geofence, can land after the person's room transition into their bedroom. The intent then opens with no further transition coming, and nothing ever runs.

Repro: Oji is in the garage zone, `previous_location="unknown"` after a midday restart, geofence fires, he walks to the master. No transition is emitted, there is no `started` and no counted skip. `arrival_action_zero` needs ten of these to notice.
Fix:
1. Drive the check from the layer's G6 room-change for the person, or the person-coordinator location event that feeds the detector, not from the transfer detector's listener list.
2. Evaluate the person's current G6 room once at the moment the intent opens.
3. Add `window_expired` (see M3) so a missed entry is counted.
4. Pin the hook placement relative to `:485` and `:496` if the transfer site is kept.
5. Add tests: `test_intent_opens_with_person_already_in_own_room` and `test_entry_after_restart_unknown_previous_location`.
6. Add mutation drill: "evaluate only on transitions".

**H2 (HIGH). The welcome-scene "stickiness" mechanism rests on a false premise. The real interaction is with the room's existing slot scene.**
- §5.5 says the reconciler "would pull the lights back to the computed level on its next pass". The reconciler only acts on an `unavailable → available` edge (`actuator_reconciler.py:461-467`) or a quarantine release (`:1208`). It has no periodic pass.
- The D3 discriminator ("without the hold: lights return to the computed level") will pass with or without the hold. That is a hollow test anchor, and INV-V6-SCENE-STICKS is mis-mechanized.
- The manual hold is direction-only. `light_hold_allowed(..., "on")` blocks only after a person's OFF (`automation.py:793-809`), so it cannot protect a scene's brightness or colour from a later URA `turn_on`.
- `note_manual_light` (`automation.py:811`) books a "person" change from the music engine. That makes the music engine a new writer to the LightPolicyOracle, contradicting "no new lighting owner" (§10).
- The real competitor is prior art the plan cites only as a picker pattern. Room entry already activates a per-slot scene in `_maybe_activate_slot_scene` (`automation.py:1740-1806`), dispatched on the same occupancy edge. That function already honours manual holds and already propagates URA context. A welcome scene issued `ARRIVAL_SCENE_SETTLE_S` later fires a second scene over it, so lights visibly double-step.

Fix (simpler and correct): make the welcome scene a per-person override inside `_maybe_activate_slot_scene`.
- When an open arrival intent for an owner targets this room and its gates pass, the entry path activates `welcome_scene` instead of `slot_scene(...)`.
- The music engine exposes a read-only `arrival_scene_for(room_entry_id)`. The lighting path reads it. There is no second write and no fake manual hold.
- `ARRIVAL_SCENE_SETTLE_S` is no longer needed.
- Re-state INV-V6-SCENE-STICKS as "the entry path applies at most one scene per entry, the welcome scene wins when eligible". Re-derive the D3 discriminator: without the override, the slot scene applies.
- If the operator wants it to survive a later slot change (day → evening while occupied), say so. Today nothing re-applies the slot scene mid-occupancy, so there is nothing to defend against.
- Correct the §2 "Light write marking / manual hold" row.

**H3 (HIGH). The "occupied before this person's entry" gate will self-trip on the person's own motion.**
§5.5 gate 3 skips when "before this person's entry the room coordinator read occupied". Room occupancy (motion, mmWave) routinely fires before the BLE room flips; BLE settles in seconds to tens of seconds.
At hook time `STATE_OCCUPIED` is already true because of this person, so the outcome is `skipped_occupied` in the common case. That breaks INV-V6-ARRIVAL-REACHES ("empty ... → started").
"Before entry" has no operational definition: neither a timestamp nor a tolerance.
Fix:
- Define the gate as room occupied-onset earlier than (person's G6 room-entry time minus `ARRIVAL_OCCUPIED_LEAD_S`). The knob sits on rung 1, default sized by D0.
- Add to D0(a) the distribution of motion-onset minus BLE-room-entry lag per own room.
- Test: `test_own_motion_before_ble_does_not_block`.
- Keep the tracked-person and camera-body legs as they are. They identify a different body.

**M1. `switch.ura_music_arrival_start` is listed as REUSED but does not exist, and the master default contradicts "ships ON".**
A grep of the integration finds no such switch. The only uses are const, config_flow and strings.
The form default is `False` (`config_flow.py:10415`). §9 says default "on" and §1 says ON day 1. A live install that ever saved this form has `False` stored.
Fix:
- Mark the switch NEW in §2, and put it in the reload-suppress set too.
- State the day-1 value explicitly. Either a one-time options migration sets it True, or the operator turns it on in the README live step. Read the live stored value first, config-first.
- Relabel strings.json and en.json, which currently say "welcome music in the entry area" and so describe a different behaviour.

**M2. Ambiguous room source.**
§5.4 says the room input is the G6 read "confirmed by `persons_in_room(room)`", while the hook still sits in a transition callback carrying `to_room`. The builder will use `transition.to_room`.
Fix: say G6 is authoritative. When it disagrees with `to_room`, wait for G6 (bounded by the window) and count `room_disagree`. This is moot if H1's fix moves the trigger to G6.

**M3. Outcome set lost `window_expired` (rev 2 §5.2) and the per-outcome observability contract.**
Rev 3 never names `window_expired`, "one decision-log line, one episode each" or the full outcome list. A missed entry is then invisible, and the zero-fire trip-wire's denominator ("intents with a qualifying own-room entry") cannot see the H1 failures.
Fix:
- List every outcome in one table, including `window_expired`, `skipped_no_rooms`, `scene_*`, `departure_*` and `room_disagree`.
- Restore one decision-log line plus one episode per outcome.
- Add a second trip-wire on intents opened with `window_expired` greater than or equal to N per 7 d.

**M4. MediaSelector browse source is unverified on 2026.11.1 and in the options flow.**
§2 verifies MediaSelector only in the 2026.2.3 venv. Its use inside a config-entry options flow, with no `accept`, the player picker, and the value shape on 2026.11.1, is not checked.
Fix: add it to spike B0 explicitly: "options-flow render on 2026.11.1; value shape; whether `entity_id` is required in the submitted value". The paste-URI fallback is already planned, so this is a test-plan gap, not a design one.

**M5. The `visible` path has no automated coverage that runs.**
The skipif test never runs on the 2026.2.3 venv, so the only check of the real marker is live.
Fix:
- Spike B0 must record the live serialized schema, the `visible` keys per field, as a fixture.
- Add a venv test that monkeypatches a fake `data_entry_flow.Optional` and asserts `_cond` output is inside the actual People `vol.Schema` and survives `voluptuous_serialize` without raising.
- State in D1 that a `vol.Schema` containing a probatio marker failing to serialize is a stop-and-redesign condition, not a silent fallback.

**M6. The repair-plan amendment (8 ft gate dropped from transfers) is a cross-plan scope change with no owner or test.**
§10(2) changes MUSIC-FOLLOWING-TRANSFER-REPAIR-1's behaviour, the `:529-548` gate.
Fix: name the deliverable that removes it (repair D1 or this plan), add the mutation drill "re-add distance read on the transfer path" there, and note the `CONF_MF_HIGH_CONFIDENCE_DISTANCE` option's fate: KEEP+DOCUMENT or remove from the form.

**L1.** Quiet-hours lookup path lost from rev 2 (`hass.data[DOMAIN]["notification_manager"]`, as `transit_validator.py:2679`). Restore it.

**L2.** `test_r7_and_perimeter_followup_same_crossing` (rev 2 §5.4) is dropped. Rev 3 still asserts at most 3 sends per crossing with no test. Restore the name in D5.

**L3.** The D5 live criterion lost "`get_last_arrival_record` returns it". Restore it.

**L4.** The D1 discriminator lost "today a new CM key reloads the entry". Restore it; it is what makes the no-reload test discriminating.

**L5.** "No bonus joins" (rev 2 §5.2) dropped. Restore it, or the builder may group-join on MA-first play.

**L6.** D0(a) dropped "classified confidence of the first transition (expected 0.50)". It is still useful as evidence for the hook-site choice. Restore it.

**L7.** §9 knob table: `ARRIVAL_SCENE_SETTLE_S` disappears under the H2 fix. Add `ARRIVAL_OCCUPIED_LEAD_S` (H3).

### Site enumeration (independent)

Emission sites the builder must touch or guard:
1. `_handle_person_arriving` `domain_coordinators/music_following.py:549`.
2. `_on_person_transition` `music_following.py:473`, with its early returns at `:485`, `:496`, `:511`, `:521` and `:540`.
3. Upstream detector suppressors at `transitions.py:177`, `:182`, `:188`, `:206` and `:240`. These are missing from the plan (H1).
4. `_maybe_activate_slot_scene` `automation.py:1740`. Missing from the plan (H2).
5. The LightPolicyOracle writer at `automation.py:811`.
6. The options-save path at `__init__.py:8826`.
7. The master form at `config_flow.py:10414`.

The plan's §7 enumeration names only music-file service calls.

**What a builder will get wrong:**
- Hook only on transitions (H1).
- Use `transition.to_room` (M2).
- Read `STATE_OCCUPIED` at hook time (H3).
- Fire a second scene after the slot scene plus a fake manual hold (H2).
- Assume the switch exists (M1).

---

## Framing 2 (G): goal fidelity

Checked against the operator's 2026-11-14 words and charter drift #17.

| Operator ask | Rev 3 | Verdict |
|---|---|---|
| "Don't want to defer too much... not a good trigger" | D0 no longer gates (§4); profile extras all in D1-D4; §14 "nothing parked" | Delivered |
| Bedroom / bathroom / owners | `rooms_bedroom`, `rooms_bathroom`, derived owners | Delivered |
| Per-room and time-of-day playlists | `music_by_room`, `music_day` / `music_evening`, `pick_media` | Delivered |
| Per-action opt-in | `auto_music`, `auto_scene` | Delivered |
| Welcome scene | D3 | Delivered, but the mechanism is wrong (H2) |
| Per-person temperature stays cut | §13 | Held |
| Shared rooms: none, including own room | Occupied gate with no knob, covers co-owner and scene | Delivered. H3 must not turn this into "never fires" |
| Departure pause | D4, pause not stop | Delivered |
| 8 ft gate dropped | Arrival path never reads distance; repair amendment | Delivered (M6 for the transfer half) |
| Form field hiding in 11.0 | `_cond` + `visible` | Delivered, with fallback |
| v6.0.0 = step 8, "get a move on" | §11 | At risk; see G1 |

**G1 (MEDIUM). Schedule fidelity.** v6.0.0 is hard-gated on layer ship 3 ("plan being written now"), step 7, step 6 and the repair D0 and D3-D7. "You better get a move on" is the operator's constraint.
Nothing is silently deferred, but no fallback is named if ship 3 slips. The fix is a fence: name which deliverables can build in parallel against the contract's stub signatures (D1 People step and store, D0, pick_media), and state that the guard test lands with ship 3. Do not add a raw-signal path. That would recreate drift #16.

**G2 (LOW, disclosed). Narrowing in §12.** These are not silent: §15 lists them, and they are surfaced as operator questions.
- Q1 defaults scenes to bedrooms only. The operator approved bathrooms as profile rooms, not as scene rooms.
- Q2 changed rev 2's "empty rooms = any speaker room" to "no rooms = no action".
Keep them as questions; do not bake them in before the answer.

H3 and H1 are goal-fidelity risks as much as correctness ones. The operator's "When needed it's beautiful" fails if the first real arrival logs `skipped_occupied` on the person's own motion, or nothing at all after a restart.
No risk reduction changed WHAT is delivered.

---

## Framing 3: equivalence (rev 2 → rev 3)

Rev 3 §15 against a manual diff of the two files:

| Rev 2 item | In rev 3? | Listed in §15? |
|---|---|---|
| Go/no-go ≥ 3 eligible starts/week (§4) | Removed (deliberate, operator) | No. Add a row |
| `window_expired`, `skipped_shared`, full outcome list, one log line + episode each (§5.2) | `window_expired` and the per-outcome contract lost; `skipped_shared` correctly gone | No (M3) |
| `test_r7_and_perimeter_followup_same_crossing` (§5.4) | Lost | No (L2) |
| D1 "new CM key reloads today: discriminates" | Lost | No (L4) |
| D4 live "`get_last_arrival_record` returns it" | Lost | No (L3) |
| "No bonus joins" | Lost | No (L5) |
| Quiet-hours lookup path | Lost | No (L1) |
| D0(a) first-transition confidence | Lost | No (L6) |
| D0(c) F-NOTIFY bar 0.50 note; §3 "equals trust until F-LEAD" | Lost | No (LOW, doc only) |
| Repair D1 + BERMUDA-DISTANCE-SENSORS-DEAD-1 prerequisite | Replaced by G6 | Yes (row 4) |
| Read API ship 1 prerequisite | Dropped (shipped) | No, harmless |
| Deliverable renumbering D3→D4, D4→D5, D5→D6, D6→D7 | Changed | No. Add a note, since the rev 2 review dispositions cite the old D numbers |
| New `ARRIVAL_SCENE_SETTLE_S`, master relabel "Arrival actions" | Added | Partly |

Rev 2 dispositions H1 and H2 are carried. The H1 disposition is itself now incomplete (H1 above).
**Fix:** restore L1-L6 and M3, and extend §15 with the unlisted rows.

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 3 | H1 trigger site, H2 scene mechanism, H3 self-occupancy |
| MEDIUM | 7 | M1-M6, G1 |
| LOW | 8 | L1-L7, G2 |

Bug classes: #53 one-missed-site (H1 upstream suppressors), hollow test anchor (H2 D3 discriminator), stale/ordering race (H3), prior-art miss (H2 slot scene), equivalence drift (§15 omissions).

**Verdict: FIX-PLAN.** Fix H1-H3 and M1-M3 in the plan, extend §15, then build. A re-review of the changed §5.4/§5.5 is enough; no full re-review is needed.
