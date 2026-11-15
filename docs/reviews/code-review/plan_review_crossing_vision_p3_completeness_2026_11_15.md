# Plan review: crossing vision Phase 3, completeness framing (Tier 3 plan review 1 of 2)

Plan: `docs/planning/PLANNING_crossing_vision.md` @ 810075a3 (develop, includes v5.108.25). Scope: Phase 3 (P3-D0..P3-D7),
§0, §2, §3, §4 (INV-SCOPE, INV-ADDITIVE, INV-DIR-GATE, INV-F3-OWNER), D1 step 8, P2-D2 step 3, §6, §7, §8.
Reviewer framing: completeness. Every surface was re-enumerated independently with greps on develop.

Read-first disclosure: this pass did NOT read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, the charter, the ura-arc skill or
the contract completely. It read the contract's G3 and §4.2 rows, the plan, the audit's §3 and the census plan's ladder
and non-goals by grep. Findings rest on code at file:line, not on those docs. Goal fidelity is review 2's job (framing G).

**Verdict: PLAN-FIX-REQUIRED** (2 HIGH, 6 MEDIUM, 6 LOW).

## HIGH

**H1. `pass_key` = "the member's own Frigate event" cannot be built from `_match_event`, and the P3-D0 (d) gate is close to a tautology.**
`_match_event` (`crossing_vision.py:761-778`) scans every stem in the door group and returns the event with the highest
`top_score` within ±`EVENT_MATCH_S`. It does not look at the member's own camera. Two crossings on one door within about
20 s therefore resolve to the SAME best event almost every time, whether they are one pass or a real round trip. The gate
"≥ 0.80 of one-pass pairs share an event id AND no round trip shares one" then measures the matcher's selection rule,
not the physics. The 8 cross-camera pairs (G6 Entry vs Front Door Aerial) can only "share" an event through this
group-wide pick, because the two cameras have different Frigate events. Required fix:
- define `pass_key` exactly: either the event matched on the member's OWN stem (then cross-camera pairs never collapse,
  so say so and size the expected collapse share at 13 of 21, not 21), or the group-wide match plus a second physical
  discriminator, such as both members within the one event's [start, end];
- give P3-D0 (d) an explicit round-trip negative set taken from the fixture, and report the share under BOTH matchers.
A time-plus-group collapse with an event-id label is the "time-only collapse" the plan's own Live criterion forbids.

**H2. Census-plan seam: F-LEAD can flip on a ledger fed by a direction that is 35 % wrong, and the census plan still lists "vision direction" as a non-goal.**
`PLANNING_census_deconfliction.md:346` lists "vision direction" among its non-goals, and Phase 3 lifts that. The F-LEAD
bar (`:74`) is count-exactness only; there is no direction or term-sign bar. Under the default
`LEDGER_DIRECTION_SOURCE = tracker`, the ledger's term signs come from the tracker, measured wrong on 6 of 17 readable
clips. F-LEAD could still pass its count bars and promote that ledger. Phase 3 §0's card-overlap row and §7 do not name
the edit the census plan needs. Required fix: name the census-plan amendment (remove the non-goal, and add a
direction/term-sign bar to F-LEAD, or make F-LEAD require the P3-D6 verdict FLIP-READY or a measured tracker sign
accuracy). Also state that the `pipeline_version` bumps in P3-D2 and P3-D3 (not only P3-D7) restart the bars a-e and
F-LEAD windows. P3-D3 step 4 bumps the version, but the P3-D7 text says only P3-D7 resets.

## MEDIUM

**M1. The P3-D5 rehydrate has no DAO, and "DB error = start at the cap" cannot be built on the existing DAOs.** Rows
live in `memory_episodes` with `node_id = vision:<crossing_key>`, one node per crossing (`crossing_vision.py:1006-1013`).
`read_memory_episodes` is node-keyed (`database.py:11032-11050`). `read_distinct_nodes_for_episodes` (`:11143-11156`)
returns node ids only. `fetch_open_memory_episodes_of_type` (`:10859`) returns open rows only, and these rows have
`ended_at` set. "One query" therefore needs a NEW DAO (type + day range, returning attrs or a count by outcome). That is
a `database.py` change, which triggers Tier 2-DB, but P3-D5 is marked Tier 2. Every memory DAO swallows errors and
returns `[]` (`_mem_dao_warn`), so `test_rehydrate_db_error_starts_at_cap_safe` cannot tell an error from an empty day
unless the new DAO signals errors. Also: `started_at` is the crossing E (`ts_iso`), not the call time, and `since_iso`
is a string compare, so the plan should specify UTC-normalised bounds. The index `(node_id, episode_type, started_at)`
does not cover a type-only scan; say whether a full scan at setup is acceptable. The table exists; the "REUSED
rehydration pattern" (P2-D10) does not. It has 0 hits in code.

**M2. The P3-D4 hold discharge is incomplete.** It covers teardown and the late member. It does not cover:
(a) a member whose own match fails (`pass_key` None): state that None never equals None;
(b) the no-request term paths (`no_frigate_event` `:676-679`, primary left the ring `:681-690`, `skipped_cap` /
`skipped_busy` `:693-703`, disabled `:620-622`). These apply terms immediately and never enter a request, so a pass whose
two members hit these paths gets two terms with no collapse. Either state "collapse only inside a request (accepted
residual, counted)" or route these paths through the hold;
(c) restart: the timer is lost; harmless because the ledger boots `unknown`, but say so;
(d) the ledger unknown or disabled when the hold fires: `_ledger_terms` returns early (`:1062-1063`); say the term is
dropped, not deferred;
(e) the knob coupling: `_prune_requests` drops `done` requests after 2 × `CLUSTER_S` (`:780-787`). With `TERM_HOLD_S` >
120, a pruned request's timer still fires from its closure. Pin `TERM_HOLD_S ≤ 2 × CLUSTER_S` or exempt un-termed
requests from pruning;
(f) `term_done` must stay False until the hold fires, or `_join_cluster` (`:740-749`) sends members that arrive during
the hold down the late branch. Name it in step 2.
This is the "suppression needs a discharge" rule: every deferral needs a named discharge on every path.

**M3. P3-D3 step 3 stamps the primary's vision values onto every cluster member.** For an opposite-direction member
that is a real round trip, the primary's `vision_direction` and `vision_people_count` on the member's F3 record are
false facts on a display surface. `direction_agreement` per member is also undefined. Is it computed against the
member's own tracker direction or the primary's? `pass_key` is per member under P3-D4, which contradicts "the primary's
vision values". Specify per-member semantics. Also say whether a member that joins after the amend is amended.

**M4. Layer guard allowlist not named.** `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py:212` reserves R13
only for `crossing_vision.py '<fast stage>:attach_crossing_attribute'`. The P3-D3 caller is `amend_crossing` from the
slow path, so the layer guard test will flag it. The build must add an explicit R13 row (and the contract §4.2 role
row). The plan names the contract edits but not the guard.

**M5. INV-DIR-GATE metamorphic test: buildable, but specify the drive point.** The invariant is falsifiable, and the
mutation "read `vision_direction` under `tracker`" gives it teeth, because the `vision` branch exists from P3-D4 step 3.
The test must drive the production path (`_on_egress_event` → `_request_terms` / `_ledger_terms` with a stubbed
llmvision reply), not `cluster_terms` alone. Otherwise the no-request term paths (M2 b) and the late branch escape it.
Hold `people_count`, `outcome` and event ids fixed while permuting only `vision_direction`. Include `pass_key`
collisions in the generator.

**M6. P3-D0 thresholds versus the fixture.** The gates are 15/17 overall and 5/6 on tracker-wrong clips. That clears a
point accuracy of 88 %, but the Wilson 95 % lower bound at 15/17 is about 0.66. The runtime bar is 0.90 LB, so the probe
gate is a "worth building" gate, not evidence the bar will clear. State that, and estimate the scored-crossing count
needed at the measured accuracy. The group gate "undercount ≤ 1" on the 18:59 clip needs ≥ 8 against a human count of
"~9" (`AUDIT_door_vision_accuracy_2026_11_14.md`). Pin the human count, or mark that clip as uncertain and leave it out
of the pass/fail decision. Clip retention: (b) and (c) assume the 46 11-14 clips and recordings are still on disk at
probe time. Add a retention check as step 0, and commit the fixture before the clips age out.

## LOW

- L1. Knob gaps: the `crossing_vision_ambiguous_zero` threshold "≥ 5" (P3-D3 step 5) and the P3-D6 oracle windows
  [E−300, E+60] / [E−60, E+300] have no named constants. The PARK rule's "≥ 150 scored" is a literal. The P3-D0 gate
  numbers 15/17, 5/6 and "≤ 1" are unnamed while `PAIR_SAME_EVENT_MIN` is named. Be consistent.
- L2. INV-NOTIFY-LATENCY cites `transit_validator.py:2228`, but the Phase 3 reader table cites `_arrival_departure_notify`
  at `:2548` / `:2917`. Re-cite.
- L3. P3-D3 adds a `tracker_direction` row key while the row already carries `direction`, which is the tracker's value
  (`crossing_vision.py:968`). Either reuse `direction` or document the duplicate. The golden test must keep `direction`.
- L4. P3-D3 step 3 "a record aged out of the ring is counted": the ring is 1800 s / 32 per camera
  (`const.py:6707-6708`). That is far longer than the worst outcome latency (end wait 120 + timeout 90), so this is
  fine. Say so with numbers.
- L5. §3 says `SIGNAL_EGRESS_RECORD_AMENDED` readers ignore the role. Verified: `sensor.py:5092`, `:5231` gate on
  `exit_backfilled`. `perimeter_alert.py` and `person_sighting.py` do not subscribe. The amended payload carries the
  record's `person_id` (`transit_validator.py:1281-1290`); harmless today, but name it for future readers.
- L6. P3-D3 also makes ambiguous crossings eligible for the arrival record and the rung-2 follow-up. The plan does not
  say whether an ambiguous crossing with `vision_direction = in` produces an arrival record before P3-D7. State it,
  since the arrival record is F5-adjacent.

## Re-enumeration results (items 1-8)

1. Readers of the tracker's direction: `_arrival_departure_notify` and `register_egress_face` / `evict_egress_face`
   (`transit_validator.py:2542-2600`), `log_entry_exit_event` (`:2610`), bus listeners at `sensor.py:4915/5046/5160/5210`,
   `perimeter_alert.py:1110`, `person_sighting.py:59`, crossing_vision `:617`. Read API: `presence.py` returns the
   `CrossingRecord`, so additive fields surface automatically. `camera_census.py:5319` is the only production G3
   caller. The plan's unchanged-reader table is complete. Readers that change: the ledger, `crossing_vision_last` and
   the read API. Correct.
2. G3: `_check_crossing_changes` (`transit_validator.py:1069-1076`) rejects any key outside `_CROSSING_AMENDABLE_KEYS`.
   So the four fields must be added there AND on the frozen `CrossingRecord` (`:946-971`). The role string is free text,
   counted in `g3_calls` by role. G3 semantics are covered by `test_person_awareness_layer_ship3a.py`,
   `test_egress_display_reread_and_tz.py` and the layer guard. With the exit-backfill role as the one production
   caller, a first production writer with additive keys is adequately tested once M4 is fixed and the plan's
   `test_g3_never_sets_direction` is added. `source_ref` format verified to match (`:2525-2527` vs `crossing_vision.py:632`).
3. Discharge: see M2.
4. INV-DIR-GATE: falsifiable and buildable, with conditions; see M5.
5. P3-D0 versus the fixture: see M6.
6. Cap rehydrate table: `memory_episodes` exists, but no fitting DAO; see M1.
7. Quality: one clean document. Knob gaps in L1. Live criteria present on P3-D1 to P3-D5 and P3-D7. P3-D6 acceptance is
   a scorer run, which is acceptable. Non-goals explicit (§8).
8. Seams: census F-LEAD (H2). Interior plan: D5 pulls crossings through `get_crossings_since` / `get_crossing` (no
   listener), so it gains the new attributes passively, with no conflict. `analyze_crossing_images` is P2-D8 on the
   fast-stage branch, which Phase 3 does not touch. P3-D2's `frames_requested` change is in `analyze_crossing_frames`,
   the clip route that interior D3 / D5 also reuse. State that the group-frame branch is crossing-only (keyed on
   `camera_peak_count`), so interior callers keep 4 frames.

## Summary

| Severity | Found |
|---|---|
| HIGH | 2 |
| MEDIUM | 6 |
| LOW | 6 |

Bug classes: computed-but-not-consumed / one missed site (#53: M2 b no-request term paths); suppression without
discharge (M2); seam drift between sibling plans (H2); proxy measuring the selector instead of the physics (H1).
