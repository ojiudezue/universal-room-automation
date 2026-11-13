# Plan review: FACE-ARRIVAL-REBUILD-1, framing 2 (adversarial build-prediction)

Plan: `docs/planning/PLANNING_face_arrival_rebuild.md` rev 1. Reviewer: ura-reviewer, 2026-11-12.
The question here is what a builder will get wrong when reading this plan.

Read completely before review: `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`. The plan touches HVAC only at `hvac._handle_person_arriving`. I read that function
(`domain_coordinators/hvac.py:7212-7280`) and no HVAC logic finding depends on it, so I did not read the HVAC doc.
The builder still must (plan §11).

**Verdict: FIX-PLAN.** 2 HIGH, 7 MEDIUM, 5 LOW. The pushback and the split into a sighting signal plus derived
arrivals are sound. The two HIGHs are in the arrival semantics and the boot window. Each would ship arrivals that
are wrong or useless, and nothing in the current acceptance criteria would show it.

---

## HIGH

**H1. Egress `person_id` exists only for people the tracker already shows as home, so "egress_entry -> arrival
candidate" is a post-arrival duplicate.**
`transit_validator.py:1840-1854` vetoes the identity whenever `person.<slug>` reads `not_home` (the manual §4.3
fail-open veto). An `egress_entry` sighting therefore names someone whose raw state is already `home` or
unknown. That is the reverse of a was-away arrival. What the builder gets from §3.3 as written:
- HVAC `pre_arrival` fires after the geofence or BLE arrival already fired. It either restarts the episode or hits
  the spent guard. The comfort value is close to zero.
- The lock regime's `_really_away` is False, so nothing happens there.
- L4 ("egress entry produces an arrival and an HVAC pre_arrival row") passes. A useless arrival and a useful one
  look the same in that check, so it does not discriminate.
- The interior entry fusion (`[-300,+60s]`) means the "egress" identity may come from a family_room face up to
  5 min earlier. The same recognition can then produce an `interior_pick` sighting and an `egress_entry`
  sighting, and `room` is reported as the door's room.

Fix in the plan, choosing one:
- (a) apply the same was-away test to `egress_entry`, which mostly yields 0 and should be said out loud;
- (b) drop egress arrivals and keep egress sightings only.

In both cases D0-P2 must add "egress entries with person_id whose person was not_home within N s before", and the
`FaceSighting` field for egress must state that `camera` and `room` are where the crossing happened, not where the
face was seen.

**H2. Restart replay of face-sensor states (source b) is not excluded, and `ts` comes from a rewritten
`last_changed`.**
At HA start, Frigate `*_last_recognized_face` sensors restore and transition from no state or `unavailable` to
"Jaya". Source (b) reads "a transition to a real name is a sighting". `ts` = `last_changed` = boot time
(HA restore rewrites it; presence doc §1 lock row and §8). Consequences:
- one burst of sightings per restart;
- a not-home person (Jaya's 220 not-home faces) becomes an interior arrival at boot;
- HVAC has no boot guard. The lock is protected by its 600 s exclusion, and the new security gate is protected only
  if the builder copies the floor.

The plan handles retained MQTT for (a) but says nothing about (b).

Specify:
- (b) ignores `old_state is None` and `old_state.state in (unavailable, unknown)`. This is the same guard as
  `presence._handle_geofence_change` (presence doc header);
- a sighting boot exclusion window (rung 1 knob) for both sources;
- a test `test_boot_restore_not_a_sighting` with a mutation drill row.

---

## MEDIUM

**M1. Mapping a pick to a stem is unspecified.**
Picks are person binary sensors (`binary_sensor.family_room_person_occupancy`). The bridge keys on base stems
from `_compute_face_latch_stems(resolver, camname)`. "The stem must be a pick" has no defined join. A builder will
string-strip `_person_occupancy[_2]`, which is the exact `_2` hazard in manual §1.1. Specify a pick ->
(device -> face sensors -> `face_name_entities_for_stem` stems) resolution through the resolver, computed with the
same helper the latch uses. Also specify re-resolution, because the plan says "once":
- on resolver rebuild (`_resolver_dirty`);
- on `EVENT_HOMEASSISTANT_STARTED`, since Frigate can load after URA (after_dependencies incident);
- on a ZM `zone_cameras` options change.

Otherwise `face_sighting_picks_resolved` reads 0 after an ordinary boot, and L1 fails or, worse, passes on a lucky
boot order.

**M2. The trip-wire denominator is not a REUSE.**
`_frigate_face_msg_face_count` (`camera_census.py:5510`) counts every `type=face` message. That includes
"unknown" names (the counter increments before the sentinel drop at `:5521-5529`), unpicked cameras, and unmapped
names. The plan's "named face messages on picked stems" needs a new counter. As written:
- the page fires when only Oji (unmapped) or a guest's "unknown" faces are seen, because the producer correctly
  emits 0;
- conversely, if (a) is dead and (b) works, the denominator is 0 and the page never fires.

Specify a new counter: post-sentinel, mapped resident, picked stem. The §1.2 row should change to BUILD.

**M3. The security face gate has no stamps to read.**
`nonface_arrival_source` needs `tracker_arrivals` and `bermuda_moves`. These are the lock regime's private
`_arrival_edges` / `_bermuda_moves`, fed by its own listeners (`security_lock_regime.py:1385-1398`, `_on_pc_update`).
`SecurityCoordinator` has neither. A builder will do one of two things:
- reach into the lock regime's privates, which breaks when the lock regime is disabled or torn down; or
- hand-roll a second stamping path (a second path to a primitive).

Specify one public method on the lock regime, e.g. `face_input_corroborated(person, at_ts)`. Security calls it, and
it fails closed (reject) when the lock regime is absent. Also state the held-face case: lock re-checks a face once
on a later Bermuda move. Does security reject permanently, or re-check too? As written it is permanent, and that
should be explicit.

**M4. Observation mode.**
The v3.19 dispatch is gated on `self.observation_mode` (`presence.py:5622-5628`, Bug Class #23). The plan's D2
dispatch and the new `SIGNAL_FACE_SIGHTING` dispatch never mention it. A builder rewriting from §3.3 will drop it.
Specify: arrivals are gated by observation mode. Sightings are display or diagnostic, so say whether they are
gated or not. Add a test.

**M5. "Not home at ts" with a past `ts`.**
`ts` is the latch or sensor time, but presence has only current state at dispatch. For (a) the difference is ms.
For (b) after a fallback and for egress it can be seconds to minutes, and a `-> home` edge between `ts` and
dispatch flips the classification. Specify the reader: current raw state plus a RAM ring of each person's last
`-> home` edge time (presence already listens to `person.*` in `_subscribe_geofence`). Define "not home at ts"
from that ring. Without this the builder will call `hass.states.get` and P3 class (i)/(iii) will not match the
code.

**M6. Debounce semantics.**
- `FACE_SIGHTING_DEBOUNCE_S`: is the window fixed from the first emit, or sliding (refreshed by each duplicate)?
  Frigate sends repeated `type=face` updates for the same track. Sliding means a person sitting in family_room for
  2 h emits once, which defeats the "who is here now" value for personalization. Fixed means about 1 per minute.
  Pick one and test it.
- "A later non-synthetic copy clears `synthetic`": `FaceSighting` is frozen and already dispatched, so this cannot
  happen without a re-emit, which is forbidden. Delete the clause, or define a "last sighting" store that consumers
  read.
- The bridge fans one camname out to several stems (`for stem in base_stems`, `camera_census.py:5591`). Specify
  whether the hook is called once per stem or once per message.

**M7. Class (iii) and `FACE_ARRIVAL_RECENT_HOME_S` buy nothing.**
A face within 300 s after a `-> home` edge means geofence or BLE already dispatched `SIGNAL_PERSON_ARRIVING` for
that edge. HVAC either re-adds or hits the spent guard, and the lock already released through P1. Only class (i)
(face before the phone) adds value. Drop (iii) and the knob. This removes one D0 computation and one rule branch
(marginal-benefit rule). D0-P3 can still report (iii) as context.

---

## LOW

- **L1.** `FACE_ARRIVAL_EGRESS_MIN_CONF = 0.6` equals the producer's minimum (`CONFIDENCE_MEDIUM`), so it filters
  nothing (Bug Class #63). Moot if H1(b) is taken. Otherwise say it is a no-op today.
- **L2.** "`zone`: first house zone": tuple order follows ZM config dict order, so the result is
  non-deterministic across edits. Sort it, or say music must not rely on it.
- **L3.** Census rebuild or reload: the presence callback sits in a list on the old `PersonCensus`
  (`__init__.py:2949`). Re-register on census replacement, or have presence look it up from `hass.data` on each
  event.
- **L4.** The kill switch `switch.ura_name_people_at_doors` (manual §3.7): state whether interior sightings honour
  it. Egress already does through the producer.
- **L5.** `test_retired_flag_unread` is a source grep (Bug Class #62). Keep it as a lint, but do not count it as
  D5's test authority.

---

## Acceptance criteria and tests that would pass hollow

| Item | Problem | Fix |
|---|---|---|
| D1 "under the old failure (edge-read) the same input emits nothing" | The old code is deleted in D5, so there is nothing to run. | Replace with: name arrives 45 s after the edge AND the person sensor is already `off` -> emits. |
| M1 drop bridge hook -> `test_bridge_name_after_edge_emits` | Stays GREEN if the test also flips a face sensor, because (b) emits. | Test must stub (b) absent and assert `sighting_source`/path. |
| M2 "read face at edge only" | Not a mutation of any code that exists after the build. | Replace with: "producer drops names whose latch ts > person-edge + 30 s" -> RED on `test_bridge_name_after_edge_emits`. |
| M6 lock corroborated -> `test_egress_face_held_without_edge` | Per H1, an egress-named person is home, so `_really_away` is False and nothing releases with or without the mutation. Stays GREEN if the test asserts "no release". | Test asserts `_pending_faces` contains the person (the held path) with the person set really away; or drop the egress variant. |
| D4 "no NM with faces=0" | Passes trivially with the current counter even when the denominator is wrong (M2). | Add `test_unmapped_only_faces_silent`, `test_unknown_name_faces_silent`. |
| L4 egress arrival + HVAC row | Holds under both a useful and a useless arrival (H1). | Restate after H1. |
| New | No drill covers H2 or M4. | Add M10 "remove boot/restore guard" -> `test_boot_restore_not_a_sighting`, and M11 "drop observation-mode gate" -> `test_observation_mode_suppresses_arrival`. |

## Marginal-benefit pushback and the operator's goals

- **The pushback holds, and should go further.** After H1 and M7, the arrival derivation reduces to interior class
  (i), and D0 gates even that. The plan should say plainly that the likely outcome is sightings only plus zero
  live arrivals, and that D3's security gate is still worth shipping because it closes a latent sink. That is a
  good result, not a failure.
- **Personalization in shared spaces and hallways.** Met by `room`, `stem`, `house_zones` and `ts`, provided M6
  fixes the debounce. A sliding window starves "who is here now". Also add one consumer-facing accessor, a "last
  sighting per person" read. Without it every future consumer re-subscribes and keeps its own state.
- **Granularity down to room and camera.** Met. `room` is None when no URA room has the camera's area, which may
  be true of hallways. D0-P1 should report pick -> room hits.
- **Consumer-side action policy.** Met in principle (§3.4 table, enforced for the security sink). It is not yet a
  primitive. M3's public corroboration method should be the single helper every access-class consumer calls, and
  FACE-SIGHTING-CONSUMERS-1 should name it.

## Must-fix before build dispatch
H1, H2, M1, M2, M3, M4, M5, M6. M7 is strongly recommended. Rewrite the hollow-test rows in the table above.
LOWs are 1-line plan edits.
