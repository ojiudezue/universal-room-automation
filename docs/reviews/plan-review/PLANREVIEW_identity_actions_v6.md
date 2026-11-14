# Plan review: identity actions (arc step 8, v6.0.0)

Plan: `docs/planning/PLANNING_identity_actions_v6.md` @ develop 9834ace1. Framings: completeness + G (goal fidelity).
Reviewer: ura-reviewer, 2026-11-14. Verdict: **FIX-PLAN** (2 HIGH, 6 MEDIUM, 5 LOW). No code changed; plan not edited.

Read-first note: this review touches presence inputs (BLE room transitions, F5). I read the code paths it depends on
(`music_following.py`, `transitions.py`, `person_coordinator.py:1031-1070`, `presence.py:5984-6026`, `const.py`
consumer-class table) and the plan's cited plans; I did not re-read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and
`SENSOR_FLEET_CLASSES.md` end to end in this pass, and no finding below relies on a claim from them. No HVAC input is
touched (confirmed: no hvac*.py site in scope).

## HIGH

**H1. Arrival start cannot fire through the existing transition gates, and the plan drops the repair deliverable that
removes them.** Plan §5.2 opens the start "on the person's next room transitions (`_on_person_transition`)"; §10 says
music-repair D1 "is not needed here and stays blocked". But `MusicFollowing._on_person_transition`
(`music_following.py:473`, the top-level file, not the coordinator) returns early on (a) `_enabled_persons`
(`:511-518`) and (b) `confidence < MIN_CONFIDENCE` (0.6, `:115`, `:521-527`). The first transition after coming home
is `away`/last room -> room after hours (`person_coordinator.py:1045-1065` fires with `old_location`), so
`transitions.py:293-381` classifies it `separate` -> 0.50, or `_detect_transition` with no history -> 0.5
(`:275-285`). Both < 0.6: every arrival transition is booked `low_confidence` and the arrival hook never runs if it
sits after the gate. Repro: Oji not_home 4 h, geofence arrival, BLE `away -> master_bedroom` -> confidence 0.50 ->
return at `:527`. Day-1 failure of the one personalization behaviour (charter, no-shadow memory). Fix in plan: either
make D1 (dwell gate removal) a hard prerequisite, or specify the arrival-intent check runs at the top of
`_on_person_transition`, before the enabled-persons and dwell gates, with its own BLE gates; and state which object
holds intent state (coordinator vs `MusicFollowing` singleton) and how the transition reaches it.

**H2. Profile save reloads the CM entry.** §7 says "re-read profiles live, no reload, INV-MF-4 style" but names no
mechanism. CM options changes that are not in the reload-suppress allowlist fall through to a full reload
(`__init__.py:8506`, `:8848-8854`; table `:7081`). A new `person_profiles` key from a new "People" step is not in it.
A parent/CM reload is the known watchdog hazard (memory `feedback_parent_entry_reload_watchdog_hazard`). D1's
`test_profile_save_live_no_reload` must name the allowlist admission and the apply-in-place site (`:8045`), and the
discharge (who re-reads the profile: fresh-read at intent open is simplest).

## MEDIUM

**M1. Seam with music repair D7 is mis-sequenced.** §10 relies on repair `set_preference_provider` (repair plan D7
item 5, `PLANNING_music_following_repair.md:279`) and amends D7 item 3 (`:276`, retire `music_on_arrival_start`), yet
lists only D0, D3, D4, D5, D6 as prerequisites. Either D7 is a prerequisite (and its item 3 must be amended in the
repair plan before it ships, or it deletes the master key's form field), or the hook is built here. Arc rule 6:
amend the repair plan, not only this one.

**M2. "Phone-free confirmation" contradicts step 7.** §5.2 says `camera_egress` "exists only after phone-free
confirmation (step 7 D2)". Step 7 §5.5 (`PLANNING_egress_direction_aware_identity.md:170-173`) dispatches only
GPS-led confirmations. INV-V6-NO-FACE-ALONE rests on that being a phone/GPS edge; fix the wording so the builder does
not accept a vision-only confirmation.

**M3. Never-interrupt checks the wrong entity.** INV-V6-NEVER-INTERRUPT reads "the player" as playing. With MA-first
play (repair D0 map), the native `CONF_ROOM_MEDIA_PLAYER` and the MA entity can disagree (MA idle while native Sonos
plays from the Sonos app, or vice versa). Specify: skip if EITHER the native primary or its mapped MA entity reads
`playing` (or is a member of a playing group). Same for the departure `media_content_id` match: name which entity's
attribute.

**M4. Shared-room gate sees only tracked people.** `get_persons_in_room` (`person_coordinator.py:2199`) returns tracked
persons; a guest or untracked child already in the room passes the gate and music starts on them. Add the room's
occupancy before the person's entry (room coordinator occupied with no tracked occupant = `skipped_occupied`), or
record the accepted gap as a non-goal with the operator.

**M5. Tier downgrade not surfaced to the operator.** Arc map step 8 is "2-DB / 3 / 2" with the profile at Tier 3
(`ARC_identity_vision_census_map.md:150`), and P2-D9 belongs to the crossing-vision plan under Tier-3 re-review
(`:40`). §11 decides the downgrade itself. Charter rule 3 (`ARC_DRIFT_ANALYSIS...:66`): put it in §12 as an operator
question. I agree on substance (comfort, reversible, no money/safety path); P2-D9 should keep its own plan's review
bar for the count/name rendering.

**M6. Milestone definition delta not recorded.** CLAUDE.md 6.0.0 lists three things; "guest gate consuming
door-identity" is not delivered (parked, §1 table). The operator's "step 8 is fine" covers it, but the plan should
quote it as the decision that redefines the milestone and D5 should update the CLAUDE.md Version-level cadence text in
the same commit, or the next session will dispute the 6.0.0 tag.

## LOW

- **L1.** Comfort class REUSE should cite `CONSUMER_CLASS_COMFORT` `const.py:6498` (exists; comfort adds no identity
  threshold, `:6508`). `is_quiet_hours_active` lives in `domain_coordinators/notification_manager.py:4772` (plan path
  omits the directory); name how MF reaches the NM instance.
- **L2.** `started` stamp is RAM; a restart between start and departure loses the departure pause silently. Count it
  (`departure_stamp_lost_restart`) or state it.
- **L3.** P8-0 (a) sizes starts "for the residents the operator opts in", who do not exist before build. Gate on all
  residents with a primary-player room, then report per-resident.
- **L4.** `sensor.ura_person_profile_<slug>` publishes `last_arrival_music` (an arrival timestamp) as live state to every
  HA user/dashboard; unrecorded attributes do not make it private. Fine for this household; note it in privacy.
- **L5.** Window 900 s vs "first of their rooms": if `rooms` = bedroom and the person sits in the kitchen 20 min, no
  start, `window_expired`. Intended? P8-0 sizes it; keep the outcome visible in the digest.

## Framing G

Delivers personalization the operator will feel: yes, if H1 is fixed (otherwise it ships dead, exactly the "features
die and are not switched on" failure in `feedback_no_shadow_mode_day1_correct.md`). Quiet staging found:
- §12 Q1 "Oji only first, others after one week of episodes" is a probation stage; the no-shadow memory says do not
  add one unless the operator asks. Recommend opting in every resident who supplies media on day 1.
- Profile slice drops bedroom/bathroom owners, welcome scene and "automate my entries" (memory
  `project_hyper_personalization_person_profile.md`). §14 cards them with triggers, which is correct, but charter rule
  4 needs the operator's yes; add it to §12.
- P8-0 go/no-go (>= 3 starts/week) returns to the operator, not a silent swap: acceptable.
- INV-V6-AWAY and the hard constraint "away fast acting": holds (no house-state write planned).
Verified as stated: handler no-op `domain_coordinators/music_following.py:549-583`, subscription `:281`;
`get_last_crossing` `presence.py:6009`; `get_last_arrival_record` returns None today `:6021-6026` (D4 must fill it);
`view_for_class` `:5984`; `notification` already legal `const.py:6525-6528`; `notify_arrival_followup` spec and 2-amend
cap step 7 §5.4; `PatternLearner.predict_next_room` `pattern_learning.py:143`; `person_visits` `database.py:995`;
no People step exists (`config_flow.py` only `async_step_person_tracking` `:4804`).

## Must-fix before build
H1, H2, M1, M2, M3; M4-M6 and the G items as operator questions in §12.
