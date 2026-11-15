# PLANNING: crossing vision (the producer: per-crossing counts, the crossing ledger, the arrival record)

Card: VISION-CROSSING-ANALYSIS-1 (thread identity, batch person-sightings; Phase 1 build card VISION-CROSSING-SHADOW-1).
Clean consolidation 2026-11-13 of rev 7.1 (`plan/crossing-vision` @ 1e76c98a), producer side only. History, not
instructions: `docs/planning/archive/HISTORY_crossing_vision_rev3_to_7_1.md`,
`HISTORY_crossing_vision_partB_record_rev3_to_5.md`. The census side (two views, deconfliction, entities, the
promotion ladder, bars a-e, F-LEAD / F-NOTIFY) is `PLANNING_census_deconfliction.md`; the read surface is
`PLANNING_person_awareness_read_api.md`. Design origin: `PLANNING_person_sighting_layer.md` §15 (incl. §15.7, §15.9).
Status: Phase 1 (D1-D3) built on `feature/crossing-vision-shadow` (18e3ba59; reviews A and B SHIP). Phase 2 P2-D1-D3
built on `feature/census-deconfliction-p2-ledger`; the 2026-11-14 ruling (arrival credit, held-input anchor, review
fix-ups) is built there (fix-up commit after a6567765). Final Tier-3 fix-up 2026-11-14 (same branch) built the operator
decisions (anchor window 900 s, switch "Vision Assisted Census" defaulting ON on a camera install), rulings Q1 (an
anchor clears the applied-exit store) and Q2 (no Tier-1 map = anchor BLOCKED), the never-in-registry Tier-1 rule, and
review C's test findings; open builder questions are listed after P2-D3. Phase 3 (§5, P3-D0..P3-D7, cards
VISION-AMBIGUOUS-CROSSINGS-1 and DOOR-VISION-GROUP-UNDERCOUNT-1, written 2026-11-15) feeds the ground-truth evaluation
`AUDIT_door_vision_accuracy_2026_11_14.md` back into this plan: direction, group counts, the daily cap. Operator rule
2026-11-15: "The things we see not working have to be reasoned through and fed back into our new plans ie the direction
issue". History of the text Phase 3 replaced: `docs/planning/archive/PLANNING_crossing_vision_history.md` (NOT A BUILD
SPEC). **P3-D0 results folded in 2026-11-15 (`AUDIT_crossing_vision_p3_d0_2026_11_15.md`, decisions on run 2):** the cap
(93) and `max_tokens` 4000 are built on `feature/crossing-p3-first` with P3-D1, P3-D5 and P3-D8; LLM direction failed
the probe gate (13/17 and 3/6 against 15 and 5, one direction change on the same clip between the two runs, which differed in `max_tokens`) and, by operator ruling ("build and
hold off and measure. We need reps"), is BUILT and RECORDED behind a closed gate and scored per door group on
production volume with a stability measure (P3-D3, P3-D6; flip only via P3-D7); the count path is kept and sharpened
(P3-D2); a deterministic second direction source is measured beside it (P3-D0b, then P3-D9c at the tracker); the event-window pass key failed, so collapse stays off and a new pass mechanism is measured first (P3-D0d).
Two operator direction designs added 2026-11-15 (after P3-D9): retroactive approach clips (P3-D0e → P3-D10) and the
anticipatory crossing (P3-D0f → P3-D11), both measurement-first, scored only on operator labels, behind INV-DIR-GATE.

Read first (done by the planners of rev 1-7.1, completely): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md`. Phase 3 planner (2026-11-15): read completely the
three audits, both cards, the charter incl. the 11-15 additions, the ura-arc skill, arc map step 2b, the census plan
§3.2-§3.4, the layer contract §2.3 / §4.2 / G3; read `SENSOR_FLEET_CLASSES.md`; read the presence state-of-play doc and
the identity manual by section (egress, crossing, vision, §5.5 and the §10 corrections ledger), NOT every line, a
disclosed gap. No claim below rests on those two docs; every code claim is cited to file:line read on develop @
8e1f0e27. P3-D0 fold-in planner (2026-11-15, develop @ 94f276e5): read completely the P3-D0 audit (runs 1 and 2), the
door-vision audit, the charter incl. the 11-15 additions, the ura-arc skill and `PLANNING_stuck_sensor_truth.md` §3
S1-S3 and §6; read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` completely (nothing in
their corrections ledgers bears on egress direction; no contradiction found). New code claims cited on develop
94f276e5.

## 0. Institutional context verified (Phase 3)

Greps re-run on develop 8e1f0e27 (`custom_components/` + `docs/planning/*.md`):

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Vision direction field on the vision call | REUSED schema slot, re-measured, recorded behind the gate | The D0 schema had `direction in/out/unsure` (`AUDIT_crossing_vision_d0_2026_11_13.md:40`) scored against the validator, not truth; the build dropped it (`crossing_vision.py:102-103`). P3-D0 (b) scored it against human truth: 13/17 and 3/6 (run 2), and one clip flipped between identical calls. Recorded on every crossing and scored (P3-D3, P3-D6) |
| Corrected direction as an F3 attribute | REUSED G3 | `amend_crossing` `transit_validator.py:1036`, `attach_crossing_attribute` `:1232`; `direction` is a FORBIDDEN key (`:977-979`), so the tracker's own `direction` is never rewritten. NEW additive amendable fields `vision_direction`, `vision_people_count`, `direction_agreement`, `vision_direction_confidence` (`:946-971`, `:980-983`): 0 hits in code |
| Direction from Frigate's own track (NEW use of a value URA already receives) | REUSED payload, NEW reader | Every Frigate `events` `after` dict carries `path_data`, `entered_zones`, `current_zones`, `velocity_angle`, `average_estimated_speed` (keys of the committed fixture `quality/tests/fixtures/frigate_events_mqtt_live.json`; `AUDIT_frigate_mqtt_d0_day_2026_11_09.md:16`). URA already reads `entered_zones` in the perimeter D3 zone-agreement gate (`perimeter_alert.py:4528-4531`, `:4999-5025`). Crossing vision's ring keeps none of them (`crossing_vision.py:575-580`). Door cameras carry ONE Frigate zone each (`<cam>_property` on front_door_aerial, madrone_g6_entry, doorbell_lite; none listed for garage_a; `AUDIT_perimeter_settings_and_masks_2026_11_13.md:76`), so zone ORDER cannot give direction today. 0 hits for `path_data` / `velocity_angle` in `custom_components/` |
| Door contact as a direction / pass input | NEW reader of existing entities | The tracker reads no contact (`transit_validator.py`, 0 hits for `contact`); direction is interior-camera timing only (`:2401-2423`). Exterior-door contacts exist live (garage-hallway Aqara contact, patio-hallway contact, unifi_access door, garage cover; `AUDIT_crossing_pipeline_after_v5_108_24.md:17`); which door group each belongs to is resolved by registry area/device in P3-D0b, never by name |
| Ring lookup of an ambiguous crossing | REUSED | Ambiguous crossings ARE stored in the ring (`_record_crossing` is unconditional, `transit_validator.py:2514-2530`); `source_ref = egress:<camera>:<iso>` (`:2525-2527`), derivable from the vision `crossing_key = <camera>@<iso>` (`crossing_vision.py:632`) |
| Watching ambiguous crossings | CHANGE of an existing skip | `crossing_vision.py:616-618` |
| Opposite-pass collapse | EXTEND `cluster_terms` (build parked until a pass key passes P3-D0d); pass key NEW, ONE function owned by the tracker (P3-D9a, harmonization C5), not `_match_event`'s group-wide pick `crossing_vision.py:761-778`. The event-window rule (ii) FAILED P3-D0 (d) (4 of 14 one-pass pairs) | `crossing_ledger.py:172-203` (mixed directions today give one camera term per member); `_join_cluster` late-joiner branch `crossing_vision.py:740-749`; cluster loop `:664-672`. 0 hits for `PAIR_COLLAPSE` / `TERM_HOLD` |
| Event-centred frames | REUSED proxy route | HA Frigate `RecordingProxyView` `/api/frigate/<instance>/recording/<camera>/start/<s>/end/<e>` (`/config/custom_components/frigate/views.py:245-266`, read on the live mount) proxies Frigate `api/<camera>/start/<s>/end/<e>/clip.mp4`. VERIFIED by P3-D0 (c): llmvision fetched it (HTTP 200, 7 frames, 10.9 s), 20 more calls on it all 200; recording complete ≥ 5 s after the window end |
| More frames for groups | REUSED knob path | `analyze_crossing_frames(max_frames=...)` `perimeter_enrichment.py:410-427`; `CROSSING_VISION_MAX_FRAMES` `const.py:3594` |
| Error text on error rows | REUSED value already returned | `analyze_crossing_frames` returns `{"status": error, "error": str(exc)[:200]}` (`perimeter_enrichment.py:452-457`); `_run` drops it (`crossing_vision.py:917-918`, `parsed = {"outcome": OUTCOME_ERROR}`) |
| Restart-durable cap counter | NEW DAO (Tier 2-DB) | The P2-D10 rehydration is planned, not built (0 code hits); the memory DAOs are node-keyed or open-row-only and swallow errors (`database.py:10859`, `:11032-11050`, `:11143-11156`), so P3-D5 adds one error-reporting count DAO; counter today is RAM (`crossing_vision.py:287`, `:495`, `:884`); cap Number `number.py:4309`, max `CROSSING_VISION_DAILY_CALLS_MAX` 200 (`const.py:3569`) |
| Direction scoring | EXTEND D4 / P2-D6 scorer + P2-D10 grading | NOT BUILT: no `scripts/probes/crossing_vision_score_weekly.py`, 0 hits for `GRADE_URA` in code. Phase 3 scoring therefore lands in the scorer build, not as a new tool |
| `pipeline_version` on rows | FINDING | Plan §5 D1.9 and P2-D8 say rows carry it; 0 hits in code. P3-D3 adds it (needed to separate pre/post-Phase-3 rows in every bar) |
| Card overlap | sweep | Board: VISION-AMBIGUOUS-CROSSINGS-1, DOOR-VISION-GROUP-UNDERCOUNT-1 (this plan); EGRESS-DIRECTION-AWARE-IDENTITY-1 changes identity attach on the same `_resolve_direction`, not direction (arc map M3); CENSUS-DECONFLICTION-LEDGER-1 consumes the terms. No card fixed the tracker's direction itself: EGRESS-TRACKER-DIRECTION-1 is now carded (planned, Tier 3) and sequenced as P3-D9 |

Prior-art scan, plans and analysis: `AUDIT_door_vision_accuracy_2026_11_14.md` (ground truth, 46 clips),
`AUDIT_crossing_vision_day_2026_11_14.md` (§2a sign, §6 skipped ambiguous), `AUDIT_crossing_pipeline_after_v5_108_24.md`
(ambiguous 42/79 on 11-13, 20/101 on 11-14; ledger `unknown` since boot), `AUDIT_crossing_vision_d0*_2026_11_13.md`
(direction vs validator 51 %), `PLANNING_census_deconfliction.md` §3.2 ladder / §3.4 bars, `CONTRACT_person_awareness_layer.md`
§2.3 / §4.2 / G3, arc map step 2b, charter (11-15 additions; "gates sized to real error rates, not calendar").

## 1. Objective and charter

Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Goals served, verbatim: "Vision is to
assist census accuracy. And assist arrivals accuracy and personalization. Especially when combined with facial
recognition from the nvr systems. Frankly our job is to make it faster and faster until it can eventually be used in
security applications too."; "make census almost bullet proof at entry... You could even essentially base census
entirely on this"; "focus on that technical part of the design. When to fast sample, how fast that comes back. What
the later batch tells us and how fast that comes back and when the complete synthesis lands. We need to simulate this";
"We should do the hard parts sooner and learn faster". Hard constraint: "I need away to be fast acting."

Objective: for every entry/exit crossing on a watched door, count the people with a vision model on frames of the
matching Frigate event; keep a house crossing ledger from those counts; fuse the count with the existing egress identity
into an arrival record ("n came in, k recognised"); make it fast (fast sample, batch, synthesis) and measured. This plan
produces evidence. Whether and where it acts is the census plan's ladder.

Phase 3 scope, stated plainly (after P3-D0 and the operator's 2026-11-15 ruling): vision COUNTS, and it RECORDS a
direction on every crossing that nobody acts on yet. P3-D0 measured an LLM on frames at 13/17 readable directions and
3/6 on the clips the tracker gets wrong, with one clip changing direction between the two runs (which differed in `max_tokens`, so not an identical repeat); 17 clips is too few to judge, so the
direction is built, held behind INV-DIR-GATE, and measured per door group on production volume for accuracy AND
stability (P3-D6); a door group flips to vision for the LEDGER only, at an operator checkpoint (P3-D7). Beside it,
P3-D0b measures a deterministic source (Frigate's own track / zones, door contacts, interior-timing variants), scored
the same way; if one passes it goes INTO THE TRACKER (P3-D9c), which fixes direction for every reader at resolution
time, which a model result arriving 10-200 s later never can. Until then every reader, the ledger included, keeps
the tracker's direction. Pass collapse stays off until a pass key passes P3-D0d.

## 2. F1-F5: produced and consumed

| Fact | Role |
|---|---|
| F1 | consumed: residency departures (ledger reconcile), `R` handed in by the census |
| F2 | none written here. The ledger hands `guest_vis` to the census through `census_tick`; the census owns F2 |
| F3 (owner `EgressDirectionTracker`, `transit_validator.py:1079`) | consumed: `ura_person_egress_event` (entry, exit AND, from Phase 3, ambiguous) and the crossing ring. Produced here: the vision count on this module's own rows, `term_source`, the arrival record `n` / `k` / `guests_unnamed`. PRODUCED as attributes of the crossing, written only through G3 `amend_crossing` (role `vision_direction`): `vision_direction`, `vision_people_count`, `direction_agreement`, `vision_direction_confidence`. A deterministic better direction, if P3-D0b finds one, is produced BY THE F3 OWNER at resolution (P3-D9c), as is any `pass_key` (P3-D9a). The tracker's `direction` is never rewritten by this module. No second crossing record, no second identity attach |
| F4 | none: vision names no one and emits no sighting |
| F5 | none produced; the one D2 site may annotate an arrival tied to a crossing with `n` / `guests_unnamed` |

## 3. Readers by consumer class

| Output | Readers | Class |
|---|---|---|
| `crossing_vision_shadow` rows, counters, `crossing_vision_today` / `_last` attributes | weekly scorer, trip-wires, diagnostic attribute; generic pre-existing readers `URAMemoryStatusSensor` (`get_memory_status_counts`, `database.py:11152`), `memory_query` (node-keyed), writer-health check (`database.py:11491`) | display |
| Ledger (`guest_vis`, healthy) | the census only, through `census_tick` | F2 input (census plan) |
| Vision count of an ambiguous crossing; F3 attributes `vision_direction` / `vision_people_count` / `direction_agreement` / `vision_direction_confidence` (G3) | read API `get_crossing` / `get_crossings_since` (`presence.py:6142-6155`), `crossing_vision_last`, the scorer; the ledger reads its own copy, used for a term only in a door group flipped by P3-D7 (INV-DIR-GATE). `SIGNAL_EGRESS_RECORD_AMENDED` readers ignore the role (`sensor.py:5092`, `:5231`) | display (ledger after the gate) |
| `pass_key` (creation, P3-D9a, parked until P3-D0d passes) | P3-D4 when built | ledger input |
| `crossing_vision_ledger` rows, `crossing_ledger` attribute | scorer, diagnostics | display |
| Arrival record (`crossing_vision_arrival` rows, `get_last_arrival_record`) | `crossing_vision_last`, personalization suggestions | display |
| Arrival count follow-up | the operator | notification (ladder rung 2) |
| Grades | scorer | operator |

No access, house-state, security or HVAC reader. No `MEMORY_COMPACTION_RULES` entry for these types.

## 4. Invariants

- **INV-SHADOW.** For any crossing and any vision result (success, blank, error, timeout, refusal, malformed JSON, cap
  skip), no reachable path changes an actuator, house state or any inference input, any census value, `person_id`,
  `identity_confidence`, `identity_provenance` or any `person_entry_exit_events` column, any `SIGNAL_PERSON_SIGHTING`,
  or the text, severity or routing of any NM alert other than this module's own pages and the rung-2 follow-up. The
  ledger reaches F2 only through `census_tick`. Break it by any other reader of the rows, counters or hass.data object,
  or a compaction rule for the types.
- **INV-OFF.** With `switch.ura_crossing_vision_shadow` off, `LLMVISION_ENRICHMENT_KILL` True, or the daily cap 0: zero
  `llmvision.*` calls and zero Frigate media requests from this module, no row, no term (the ledger goes `unknown`). Gates
  are re-read at call time.
- **INV-SCOPE.** Every frame sent belongs to a Frigate camera in the crossing's own door group (live `door_groups`; no
  entry = a group of one): either that camera's matched event clip, or that camera's recording window
  [E − `CROSSING_VISION_FRAME_WINDOW_BEFORE_S`, E + `_AFTER_S`] (P3-D2). Every crossing the tracker resolves (entry,
  exit or ambiguous) is eligible while `CROSSING_VISION_WATCH_AMBIGUOUS` is True (P3-D3). Calls per local day ≤
  `CROSSING_VISION_DAILY_CALLS`, counted across restarts (P3-D5: the counter is rehydrated at setup from today's call
  rows), in flight ≤ `CROSSING_VISION_MAX_CONCURRENT`, nothing queued beyond (counted skip). Stability repeats (P3-D3 step 8) have their own daily budget
  (`CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX`), never the primary cap, and count toward the in-flight bound. Residual: a call in flight
  at a restart that wrote no row is not counted; bound ≤ `MAX_CONCURRENT` per restart.
- **INV-ADDITIVE.** For every non-ambiguous crossing the DB `peak_person_count` equals the bus `peak_person_count` (one
  sample, one local). Ambiguous: bus key None, no DB row, no sample (unchanged by Phase 3); its vision row carries
  `camera_peak_count = None`.
- **INV-DIR-GATE (Phase 3, the falsifiable invariant).** While a door group's entry in
  `CONF_CROSSING_VISION_LEDGER_DIRECTION_SOURCE` reads `tracker` (missing = `tracker`; set to `vision` only at an
  operator checkpoint after that group's P3-D6 disposition is FLIP-READY on accuracy AND stability), vision's direction never
  changes a ledger term or any reader: for any crossing sequence, any vision result (primary or repeat row) and any
  cluster shape, replacing every `vision_direction` / `vision_direction_confidence` with any other value (valid,
  out-of-enum, or missing)
  leaves the ledger's term stream (kind, sign, `n`, `crossing_key`, `term_source`), every `L` / `guest_vis`, the
  arrival records and every tracker-direction reader identical; an ambiguous crossing yields no term in a `tracker`
  door group. **Repeat clause (review finding 2):** the presence or absence of any repeat call leaves every
  primary's outcome, count, cap / busy skip and term identical. Break it with a sequence where a `vision_direction`
  value, a malformed direction field, or a repeat moves a term, an arrival record, a primary's outcome or a reader
  while the group's source is `tracker`.
- **INV-F3-OWNER (Phase 3).** Vision's direction exists only as G3 attributes on the tracker's record; no path writes
  `CrossingRecord.direction`, the bus `direction`, the `person_entry_exit_events.direction` column, the census
  `register_egress_face` / `evict_egress_face` choice or `_arrival_departure_notify` from vision. Every reader of the
  tracker's direction is byte-identical with Phase 3 on or off. (P3-D9c changes the tracker's own rule inside the F3
  owner, under its own Tier-3 plan.)
- **INV-APPROACH-DARK and INV-ONE-F3 (P3-D10, P3-D11; stated in full there).** Approach direction is a G3 attribute that
  moves nothing until a gate flips or the tracker adopts it; every crossing record still comes only from the extended
  tracker's `_resolve_direction`, one per pass per door group.
  INV-SCOPE's frame set is widened for P3-D10 only to the frozen, registry-resolved approach set of the crossing's
  door group (door-group cameras, their `EXTERIOR_ADJACENCY_GRAPH` neighbours, one inside camera).
- **INV-BLANK.** All-zero (or absent) per-frame counts → `outcome = blank`, `people_count = None`, never 0, never in the
  accuracy numerator. No matching Frigate event → `no_frigate_event`, no call.
- **INV-P2-DISCHARGE.** For any crossing sequence, terms, missed exits, vision errors, cap skips, restarts or resident
  tracker state (incl. a phone left at home): once the camera body total is 0, the fleet is not dark, no Tier-1 input
  is held (P2-D2 step 2: reads `on`, or is dead with a last known-good `on` or no known-good reading), no room rising
  edge has occurred and no entry term arrived, continuously for `CROSSING_VISION_LEDGER_EMPTY_RESET_S`, the anchor sets
  `L = R`, clears every arrival credit and `guest_vis` is 0 at the next evaluation. Bound: reset window + one eval
  interval + one census interval. The predicate reads no house state, census output, resident set or ledger value. A
  held input (a still guest on a radar, a stuck-on sensor, a dead input) blocks the anchor by design; the surplus then
  waits, and `crossing_ledger_anchor_zero` pages naming the holders. Late terms (crossing E before the last anchor) are
  recorded, not applied; a restart never restores `known`.
- **INV-P2-ONCE.** Every person is counted in `L` at most once per arrival and removed at most once per departure: a
  resident arrival raises `L` once whether the resident edge or the door entry term comes first; a resident departure
  lowers it once whether the exit term or the departure edge comes first; one exit term pays for at most `n` departure
  reconciles. Break it by any order of (edge, term, census tick) in the P2-D2 worked examples (W1-W8) that ends with
  `guest_vis ≠` the true guest count once the transient window (step 5) has passed. No identity attach is read.
- **INV-P2-IDENTITY.** The ledger and the arrival record never change `identified_count`, `identified_persons`, any
  `person_id`, any resident's home/away, or any input of `get_residents_home` (PLB included); names are read, never
  re-decided.
- **INV-NOTIFY-LATENCY.** The arrival notification is never delayed for a count: `_arrival_departure_notify` fires
  synchronously at direction resolution (call `transit_validator.py:2548`, def `:2917`); the count goes in a separate quiet follow-up.

## 5. Deliverables

### Phase 1 (built; acceptance carried for the ship)

**D0 probe (done):** D0a GPT-6 dry calls on the second llmvision entry; D0b `video_analyzer` frame source on the 45 D0-V
crossings (pass: exact ≥ 85 %, 0 multi-person undercounts, 0 errors; fail → `image_analyzer` on snapshot + thumbnail,
fail twice = park); D0c door-camera fixture `FIXTURE_crossing_vision_door_cameras.md` (stems → Frigate camera, Frigate
entry count incl. disabled, `notification_proxy_enable`, instance ids, ±10 s coverage, llmvision automations list);
D0d per-frame guard 24/30 (not a blocker: D1 uses the set-level guard, 0 false blanks in 38 person crossings, 6/6 true
blanks). Results: `AUDIT_crossing_vision_d0_2026_11_13.md`, `AUDIT_crossing_vision_d0_v_2026_11_13.md`.

Config-first: llmvision Temperature / Top P are per provider entry, no per-call override (llmvision 1.7.1
`providers.py:466-484, :690-710`, `config_flow.py:536-652`). GPT-6 needs temperature 1.0. Operator added the second
entry "OpenAI Madrone Vision" (`01M7B731T26P2HXVW77AQR62PP`, `gpt-6-luna`, 1.0 / 1.0); the perimeter entry
(`01KHB0EV5AP8ANWQ7RWT30M2CC`, gpt-4o-mini, 0.5 / 0.9) is untouched. The id is never hard-coded
(`CONF_CROSSING_VISION_PROVIDER_ID`).

**D1 shadow producer `crossing_vision.py`** (`CrossingVisionShadow`, built in `__init__.py` beside `ExteriorTrackLinker`,
`hass.data[DOMAIN]["crossing_vision"]`, teardown: `_torn_down` latch first, unsubscribe, cancel timers, gather in-flight
tasks bounded by `CROSSING_VISION_TEARDOWN_GATHER_S`).
1. Frigate ring via `register_frigate_consumer(hass, "crossing_vision", fn)` (sync callback); per door-group camera the
   last `CROSSING_VISION_EVENT_RING` person events. Camera → stem derived at runtime through the validator's
   `_extract_camera_stem` (honouring `_2`), then `door_groups` by stem via a public getter on the tracker; the D0c
   fixture is the test oracle, never a source of names.
2. Trigger: `ura_person_egress_event`, direction entry/exit; `crossing_key = f"{egress_camera}@{timestamp}"` (the
   outcome-log `source_ref`).
3. Cluster: a crossing whose door group has any open or completed request with |E − E'| ≤ `CROSSING_VISION_CLUSTER_S`,
   or whose matched event was already analysed, makes no call but writes its own `clustered` row with
   `primary_crossing_key`; the primary row lists `crossing_keys`. Not counted against the cap.
4. Gates at schedule AND call time: switch, kill, cap, concurrency. Recorded skips `skipped_cap`, `skipped_busy`; off =
   no row.
5. Match: person event on the group with start in [E − `CROSSING_VISION_EVENT_MATCH_S`, E + same]; highest
   `top_score`, tie → longest; none → `no_frigate_event`.
6. Wait: call at event end or `CROSSING_VISION_EVENT_END_WAIT_S` after the bus event, whichever first.
7. Call: `perimeter_enrichment.analyze_crossing_frames(...)` (same contract as `enrich_dispatched_alert`: kill check,
   `wait_for`, never raises), `llmvision.video_analyzer`, `use_memory` false, `store_in_timeline` false, `expose_images`
   per `CROSSING_VISION_KEEP_FRAMES`, provider = `CONF_CROSSING_VISION_PROVIDER_ID` else the perimeter provider. Clip URL
   `/api/frigate/<instance_id>/notifications/<event_id>/clip.mp4` when the instance id is known (perimeter discovery
   `perimeter_alert.py:3840-3858`); `event_id` default URL only with exactly one Frigate entry (the default entry is None
   with more than one, `frigate/views.py:47-57`). HA-signed; no Frigate credentials in URA.
8. Parse + guard: schema `{frames: [{index, people}], people_total, group, desc}` as built (`crossing_vision.py:96-118`;
   Phase 3 P3-D3 adds `direction`, `direction_confidence`); prompt forbids naming;
   outcomes `ok` (`people_count` clamped to [max frame, max frame × frames]), `blank`, `unparseable`, `error`, `timeout`,
   `refused`.
9. Record: one `log_memory_episode(node_id=f"vision:{crossing_key}", episode_type="crossing_vision_shadow",
   source_ref=crossing_key, started_at=E, dedup_source_ref=False)`, tracked task. Attrs: `outcome`, `crossing_keys`,
   `door_group`, `direction`, `people_count`, `frame_counts`, `group`, `desc`
   (≤ `CROSSING_VISION_DESC_MAX_CHARS`), `camera_peak_count`, `frigate_events_in_window` ([E − match, E +
   `EGRESS_ENTRY_WINDOW_SECONDS`]), `event_id`, `event_camera`, `model`, `frame_source`, `latency_s`, `person_id`,
   `identity_provenance`, `agreement_case` (A-D on counts), `stage`, `pipeline_version`.
10. Diagnostics on the Outside: Open Tracks sensor (unrecorded): `crossing_vision_today`, `crossing_vision_last`.
- **Tests:** `test_crossing_vision_shadow.py`: `test_one_call_one_row_per_crossing`, `test_switch_off_no_call_no_row`,
  `test_switch_off_after_schedule_no_call`, `test_kill_const_no_call`, `test_ambiguous_ignored`,
  `test_interior_camera_event_never_matched`, `test_cap_skip_recorded`, `test_busy_skip_recorded`,
  `test_cluster_one_call`, `test_blank_not_zero`, `test_no_frigate_event_no_call`,
  `test_failure_classes_recorded_never_raise`, `test_runtime_camera_map_matches_fixture`,
  `test_cluster_completed_request_no_second_call`, `test_clip_url_instance_scoped`, `test_use_memory_false`,
  `test_teardown_cancels_pending`, `test_node_id_unique_per_crossing`, `test_no_census_or_sighting_reader`. Real `hass`,
  real `log_memory_episode` on the production schema.
- **Mutation:** remove the call-time switch re-read → `test_switch_off_after_schedule_no_call`; drop the door-group
  filter → `test_interior_camera_event_never_matched`; blank as 0 → `test_blank_not_zero`.
- **Live:** within 4 h of daytime with the switch on: ≥ 1 `ok` row with non-null `people_count` and `camera_peak_count`;
  every `source_ref` matches an `egress_identity_outcome` row; `calls` ≤ crossings; no `crossing_vision` ERROR.

**D2 `peak_person_count` on the bus:** in `_resolve_direction`, sample `_sample_peak_person_count` once before the bus
fire; the same local goes to the event and to `log_entry_exit_event`. Ambiguous: key None, no sample.
- **Tests:** `test_transit_validator_peak_on_bus.py`: `test_bus_and_db_peak_identical` (stub returns a different value
  per call; asserted called once, both sinks carry the first), `test_ambiguous_peak_none_no_sample`,
  `test_sampler_exception_none_both`, `test_existing_bus_keys_unchanged` (golden of every pre-existing key).
- **Live:** a new `person_entry_exit_events` row's `peak_person_count` equals that crossing's `camera_peak_count`.

**D3 trip-wires:** `crossing_vision_zero` (≥ `CROSSING_VISION_ZERO_MIN_CROSSINGS` crossings in 24 h and 0 `ok` → HIGH,
hourly, RAM latch re-armed on `ok`); `crossing_vision_errors` (error + timeout + unparseable + refused >
`CROSSING_VISION_ERROR_RATE_MAX` of ≥ `CROSSING_VISION_ERROR_MIN_CALLS` calls → MEDIUM); the type joins
`MEMORY_WRITER_BACKED_EPISODE_TYPES` (0 rows in 7 days pages; switch off long term = add to the exempt set).
- **Tests:** `test_zero_fire_pages_once`, `test_zero_fire_rearms_after_ok`, `test_error_rate_pages`,
  `test_switch_off_no_page`. Mutation: remove the latch → `test_zero_fire_pages_once`.
- **Live:** attributes present; no page on day one with rows flowing.

**D4 weekly scorer** `scripts/probes/crossing_vision_score_weekly.py` (read-only): joins shadow rows to
`egress_identity_outcome` (1:1 by `source_ref`; clustered rows take the primary's count), `person_entry_exit_events`,
resident edges within ±120 s; reports per door / direction / day-night exact-count (vision and camera), case A-D shares,
blank / no-event / error rates, false-guest proxy, cost proxy. Disposition audit
`AUDIT_crossing_vision_shadow_disposition_<date>.md`.

Cost (estimate; llmvision returns no usage): gpt-4o-mini 4 frames ~$0.013/call, ~$0.18/day mean, ~$0.50/day at cap 40;
gpt-6-luna < $0.02/day.

### Phase 2 (producer side)

**P2-D0 read-only probe** (gates flips, not builds; ≤ 6 model calls): (i) residency fire check (first resident edge after
the v5.108.19 restart writes a `person_arrival` / `person_departure` row); (ii) independent empty anchors over 14 days at
1800 / 3600 / 7200 s; (iii) wrong-event rate at ±30 s on the 117 D0c clusters; (iv) D0a on the Luna entry
(`image_analyzer` and `video_analyzer`); (vi) timing simulation: replay the 117 clusters with Frigate event start/end and
the D0b call-latency distribution, per stage p50 / p90 and the share where F's count equals B's (D0-V image-path accuracy
for F); (viii) Protect name back-fill p99 at door cameras. Census-side items (v) AWAY baseline and (ix) dashboard list
are in the census plan. (vii) is closed (grading path cited below). **Acceptance:** audit
`AUDIT_crossing_vision_p2_d0_<date>.md`, one row per item with numbers.

**P2-D1 Luna (Tier 1):** `CONF_CROSSING_VISION_PROVIDER_ID` (rung 2, options Advanced) names the llmvision entry;
`CROSSING_VISION_MODEL = gpt-6-luna`. Ships before the shadow switch goes on so all bar data is one model. Resolution
(review A-HIGH-3; the option is empty on this install until someone opens the form): option set → that entry; option
empty → the rung-1 install default `CROSSING_VISION_PROVIDER_ID` (`01M7B731T26P2HXVW77AQR62PP`, the Luna entry; kept, not
deleted) only if an `llmvision` config entry with that id exists on THIS install (the Phase 1 portability check); else
the perimeter provider. Another house never has that id, so it falls through to its perimeter provider. The model
stamped on each row is the model sent.
**Tests:** `test_provider_override_used`, `test_empty_option_uses_install_present_default` (option empty, entry
`01M7…PP` present with domain `llmvision` → that id), `test_empty_override_falls_back` (option empty, default id absent
or not `llmvision` → perimeter provider). **Live:** ≥ 1 `ok` row with `model = gpt-6-luna` and no
`crossing_vision_errors` page in the first day.

**P2-D2 `crossing_ledger.py` pure core (Tier 3).** No HA import, time passed in. One house ledger, RAM, state `known` /
`unknown`; holds `L ≥ 0` (people in the house, residents and guests, unattributed), `L_raw` (unclamped, diagnostic),
`R_prev` (the resident term at the previous census tick), arrival credits, applied exits, anchor time, counters.
`guest_vis = max(0, L − R)`. No step reads identity attach (≈ 17 % of crossings carry a confident name); residents and
guests are told apart only through `R`.
1. Boot = `unknown` (`guest_vis` None) until the first anchor. No replay (parked; revival: median anchor gap > 24 h).
2. Anchor, evaluated every `CROSSING_VISION_LEDGER_EVAL_S` by a tracked interval. The window `[t_start, now]` holds iff
   at every sample: the camera body total is a number and 0; `camera_input_dark` is False; no Tier-1 input is held; no
   Tier-1 room rising edge was noted (`OccupancySubstrate.subscribe`, catches a motion pulse shorter than the eval
   interval); no ENTRY term arrived (any entry term, applied, late or while unknown: review A-MED-2). Any failure sets
   `t_start = None`; the next passing sample sets `t_start = now`. Fires at `now − t_start ≥
   CROSSING_VISION_LEDGER_EMPTY_RESET_S`: `L = R_last`, `L_raw = R_last`, `R_prev = R_last`, credits cleared, `known`,
   residue = `L_before − R_last`, `t_start = now`. Exit terms, reconciles and floor lifts do not restart the window.
   **Held input (review D-M1, operator 2026-11-14 "a dead input holds instead of releasing").** The wiring passes
   `held` (a set of entity ids) to `evaluate(now, held)`. A Tier-1 input (every entity in the substrate's Tier-1 map,
   the map `_kind_on_now` ORs; levels, so a presence radar holding a still person counts) is held when it reads `on`,
   or when it is dead (`unavailable`, `unknown`, missing, or `camera_input_stream_dead(eid)` True once S2 is built)
   and its last known-good reading (RAM map in the wiring, updated from every `on` / `off` reading) was `on`, or it
   has no known-good reading since setup. A dead input therefore blocks, never enables, the anchor. A stuck-on sensor
   also blocks (accepted: the anchor-zero page names it; this replaces the earlier "edges, not levels" rule).
   Kill switch `CROSSING_VISION_LEDGER_ANCHOR_NEEDS_NO_HOLD` (rung 1, True; False = the edge-only predicate).
   **No Tier-1 map = blocked (ruling Q2, 2026-11-14):** no occupancy substrate, a torn-down one, or a failing
   `tier1_entity_ids()` returns the pseudo-holder `tier1_map_unavailable` as held (and dead): unknown is not empty.
   A live substrate with an empty map is an available map with nothing to hold. **Never-existed input (2026-11-14
   window sweep finding):** a Tier-1 entity with no entity-registry entry AND no state (live example
   `binary_sensor.mmwave_zigbee_gameroom_presence`, since reconfigured) is ignored for the held set, listed as
   `tier1_not_in_registry` (+ `_count`) on the ledger diagnostics and logged once per entity (WARNING). A registered
   entity with no state still holds; a registry read error ignores nothing.
   **Freshness:** a sample whose stored body value is older than `2 × max(eval_s, 1)` fails; `EVAL_S = 0` means a 1 s
   interval, not "never anchor" (review D-L2). While dark or the body total is None, `census_tick` returns
   `healthy = False`. A body seen only between samples is missed (accepted; bound carries + 1 interval).
   **Measured (read-only replay, 2026-11-14, 14 days of `census_snapshots` + `occupancy_events` entry/exit episodes
   as the held proxy (room `STATE_OCCUPIED`, so it over-blocks) + door entry rows; script
   `.claude/tmp/anchorprobe/replay.py`, not in the repo):** anchors 14 d / last 7 d / during AWAY: edge rule at 3600 s
   48 / 22 / 9 (reproduces P2-D0 (ii)); held rule at 3600 s 6 / 5 / 6; at 1800 s 20 / 13 / 18; at 900 s 55 / 31 / 48.
   The night anchors the edge rule fired (81 % outside AWAY) were exactly the D-M1 shape: held rooms (top holders
   Jaya Bedroom, Garage B, Master Bedroom). The default was first moved to 1800 s, then set to **900 s by the operator
   (2026-11-14, "15 mins")** on the actual-Tier-1 sweep `AUDIT_ledger_checkpoint_window_sweep_2026_11_14.md` (15
   checkpoints / 7 d, 4 empty episodes / wk, 0 unexplained resurfacings at R = 60 min once arrival precursors are
   excluded; all 7-d checkpoints in AWAY). At 1800 s, 18 of 20 proxy anchors fell in AWAY, where "zero guests" is independently true (resolves the P2-D0 (ii) independence
   caveat). No configured Tier-1 input read dead on 2026-11-14 (the five rooms with unavailable entities list only
   actuators and non-occupancy sensors), so the dead rule costs no anchors today.
3. Term per outcome. **Direction of a term** = the tracker's direction while the door group's source is `tracker`
   (INV-DIR-GATE); with `vision` (P3-D7), the crossing's `vision_direction` when it is `in` / `out`, else the
   tracker's. An `ambiguous` crossing has no term under `tracker`; under `vision` it gets one when `vision_direction`
   is `in` / `out`. `n`: vision `people_count` when `ok` (`term_source = vision`; ≥ 1 by INV-BLANK), else
   `max(1, camera_peak_count)` with None as 1 (`term_source = camera`; `blank` falls back too; a resolved direction is
   at least one person: review A-MED-1). **Cluster (P3-D4 when built; until then only the "as before" rule below applies):** members are first grouped into physical passes
   (`pass_key`; `None` never matches; every key is None until a pass mechanism passes P3-D0d); one pass gives at most
   ONE term: a pass whose entry/exit members disagree gives no term (`pair_collapsed`, both directions recorded; effect
   named in P3-D4 step 8, W9-W11) in a `tracker` door group; in a door group flipped to `vision` (P3-D7) it takes
   vision's direction (P3-D4 step 5). Terms are built only at the P3-D4 release site once P3-D4 is built. Then, as before: one term with the primary's count if all remaining
   terms share a direction, else per-member camera terms. Policy `CROSSING_VISION_LEDGER_FALLBACK` (`camera` / `skip`).
   While `unknown`, terms are recorded, `L` stays unknown. Late terms (E before the last anchor) are recorded, not
   applied.
   - **Entry** (applied): `c` = consumable credit, the sum of open credits whose window contains E (step 4); consume
     `m = min(n, c)` oldest first; `L += n − m`, `L_raw += n − m`.
   - **Exit** (applied): `L_raw −= n`, `L = max(0, L − n)`; store `(E, n)` in the applied-exit store for step 5. Late
     or unknown exits are never stored (review D-L1: a reconcile cannot be cancelled by an exit the ledger never paid).
4. **Resident floor = arrival credit (reviews A-HIGH-1, A-HIGH-2; replaces "every census tick `L = max(L, R)`").** At
   `census_tick` while `known`, with `r` the new resident term: if `r > R_prev` and `L < r`, lift `k = r − L`:
   `L += k`, `L_raw += k`, and open a credit `(t = now, k)`. Then `R_prev = r`. The floor never runs when `R` is flat
   or falling, and never lowers `L`. A credit is consumable by an entry term with E in
   [`t − CROSSING_VISION_GO_ARRIVAL_WINDOW_BEFORE_S`, `t + CROSSING_VISION_GO_ARRIVAL_WINDOW_AFTER_S`] (REUSED 300 / 60:
   the same "this entry term is this arrival" match bar b scores) and expires at `t + AFTER_S + reconcile_delay_s`
   (the term's outcome delay, already passed in); an expired credit's lift stays in `L` (a resident who came in
   through a door the cameras did not count). Why this and not the alternatives: not writing the floor at all (read-time
   `max(L, R)`) leaves a missed resident entry as a hidden deficit that absorbs the next guest until the next anchor; a
   floor on every tick re-lifts after an exit term (A-HIGH-2). The credit fixes both repros, keeps INV-P2-DISCHARGE
   (the anchor clears credits) and needs no identity.
5. Departure reconcile: a resident departure edge at `t_e` is judged at `t_e + LAG + CROSSING_VISION_TIMEOUT_S +
   EVENT_END_WAIT_S` (one tracked timer per pending departure, superseded per person, cancelled in teardown). Judging
   consumes one person from the earliest applied exit with E ∈ [`t_e − LEAD`, `t_e + LAG`] and `n_left ≥ 1` (cancel);
   else `L = max(0, L − 1)`, `L_raw −= 1`, counted. One exit term of `n` cancels at most `n` reconciles (review
   A-MED-4). Only while `known`; an anchor at or after `t_e` voids it; an anchor also clears the applied-exit store
   (ruling Q1: it already paid them, so an exit before the anchor cannot cancel a later departure); restart drops pending. **Transient (accepted,
   measured by bar d):** when the departure edge lands before the exit term's outcome, `guest_vis` reads + 1 for up to
   `reconcile_delay_s` (≈ 210 s); when an entry term's outcome lands before the arrival edge, + 1 until the edge.
   Parked: "a pending departure counts as a provisional exit" (revival: bar d fails, or > half its false-guest time
   sits within `reconcile_delay_s` of a resident edge).
6. `census_tick(now, resident_term, camera_bodies, camera_input_dark) → (guest_vis | None, healthy)`; the module stores
   what it is given and never reads the census or presence. `evaluate(now, held)` takes the held set from the wiring.

Worked examples (start: anchored, `L = R = 1`, resident A home; term outcomes land ≈ 210 s after E; census tick 30 s):

| # | Case | Sequence | Result |
|---|---|---|---|
| W1 | Resident B arrives alone | edge t=0 → tick R 1→2: lift k=1, `L = 2`, credit (0,1); entry term E=−20, n=1 → consumes 1, `L = 2` | `guest_vis 0` (old floor: 1) |
| W1b | same, term first | entry E=−200 applied at 10 → `L = 2`; tick R 1→2, `L ≥ r` no lift | `guest_vis 0` |
| W2 | B arrives with a guest | edge → lift `L = 2`, credit 1; entry n=2 → consume 1, add 1, `L = 3`, R = 2 | `guest_vis 1` |
| W3 | Guest arrives alone | entry n=1, no credit → `L = 2`, R = 1 | `guest_vis 1` |
| W4 | Resident departs (A-HIGH-2 repro) | `L = R = 2`; exit E=200 → `L = 1`; tick at 290, R = 2 flat → no lift; departure t_e=500, R = 1; judge consumes E=200 | `L = 1`, `guest_vis 0` (old floor: 1) |
| W5 | Resident departs with guest | `L = 3`, R = 2; exit n=2 → `L = 1`; departure R = 1; judge consumes 1 of 2 | `guest_vis 0` |
| W6 | Resident's phone stays home, resident walks out | `L = R = 2`; exit n=1 → `L = 1`; no edge, R = 2 flat, no lift → `guest_vis 0`; returns: entry n=1 → `L = 2` | `guest_vis 0` throughout (old floor: 1 after return). A guest arriving while the resident is out is absorbed (undercount, safe direction; PLB `on` lowers R and removes it) |
| W7 | Residents B and C arrive together, one edge each | edges at 0 and 40 → lifts to `L = 2`, `L = 3`, credits 1 + 1; entry n=2 → consumes 2, `L = 3`, R = 3 | `guest_vis 0`. Camera undercounts n=1: consumes 1, the other credit expires, its lift stays, `L = 3`, still 0 |
| W8 | B arrives through an uncounted door | lift `L = 2`, credit expires; later B exits through a counted door: exit → `L = 1`, departure R = 1, judge consumes | `guest_vis 0` |

Named residuals: a guest's entry within the arrival window of a resident who came through an uncounted door consumes
that credit (guest missed until the next entry/anchor, safe direction); a guest's exit inside a resident's departure
window, when the resident's own exit was missed, cancels that reconcile (guest-side `L` one high until the anchor);
`R = max(residents_home, identified_count)` rising on a face rather than an arrival opens a credit that only an entry
in the window can consume.

- **Tests** (`test_crossing_ledger.py`; inputs as in the table, defaults otherwise):
  `test_boot_unknown_until_anchor`; `test_anchor_needs_zero_bodies_and_no_edge_for_window`;
  `test_anchor_sets_L_to_resident_term`; `test_entry_term_restarts_anchor_window`;
  `test_entry_term_while_unknown_restarts_window` (unknown, window 600, bodies 0, entry E=290 → no anchor at 600, anchor at
  ≥ 890); `test_exit_term_does_not_restart_window`; `test_dark_fleet_stops_window`; `test_none_bodies_is_failing_sample`;
  `test_rising_edge_restarts_anchor_window`; `test_held_radar_blocks_anchor` (D-M1 repro: R=2, guest entry L=3, bodies 0,
  no edges for 2 h, `held = {radar_gb1}` → no anchor, `guest_vis 1`); `test_dead_input_last_on_blocks_anchor`
  (input `on` then `unavailable` → held); `test_dead_input_last_off_does_not_block` (`off` then `unavailable` → not
  held); `test_dead_input_no_known_good_blocks` (unavailable since setup → held); `test_stuck_on_sensor_blocks_anchor`
  (replaces `test_stuck_on_sensor_does_not_block_anchor`); `test_no_hold_kill_switch_restores_edge_rule`;
  `test_eval_zero_means_one_second` (EVAL_S 0, sample 1.5 s old → fresh, anchor fires);
  `test_resident_arrival_before_entry_term_counted_once` (W1, A-HIGH-1 repro: `(guest_vis) == 0`, was 1);
  `test_entry_term_before_arrival_edge_no_lift` (W1b); `test_resident_with_guest_counts_guest` (W2 → 1);
  `test_guest_alone_counts` (W3 → 1); `test_exit_term_before_departure_edge_no_phantom` (W4, A-HIGH-2 repro: `L = 1`,
  `guest_vis 0`, reason `exit_term`); `test_resident_and_guest_depart_together` (W5 → 0);
  `test_phone_home_walk_out_and_back_no_phantom` (W6 → 0 at every step); `test_two_residents_one_term_two_edges` (W7 → 0,
  both n=2 and n=1 variants); `test_uncounted_door_arrival_lift_persists` (W8 → 0); `test_credit_expires_lift_stays`
  (lift, no entry by `t + 60 + delay` → `L` keeps the lift, a later guest entry adds 1); `test_floor_only_on_rise`
  (R flat at 2 while `L = 1` for 10 ticks → `L` stays 1); `test_floor_never_lowers`;
  `test_exit_consumed_once_by_reconciles` (A-MED-4: two departures, one exit n=1 → first cancels, second applies,
  `L` drops by 1 net of the exit); `test_late_exit_does_not_cancel_reconcile` (D-L1: exit E, anchor at E+30, outcome
  late, departure t_e = E+300 → reconcile applies, `guest_vis 0`); `test_camera_peak_zero_is_one` (A-MED-1: peak 0 and
  None → n = 1); `test_exit_clamps_at_zero_raw_kept`; `test_reconcile_only_without_exit_term`;
  `test_reconcile_waits_for_late_exit_outcome`; `test_anchor_voids_pending_reconcile`; `test_anchor_clears_credits`;
  `test_ambiguous_no_term`; `test_cluster_one_term_same_direction`; `test_cluster_mixed_direction_per_member`;
  `test_fallback_camera_then_one`; `test_residue_recorded_before_reset`; `test_anchor_independent_of_house_state`;
  `test_guest_surplus_discharges_with_resident_phone_home`; `test_stuck_page_resident_independent`; config extremes
  `test_reset_window_zero_means_instant_anchor`, `test_reconcile_window_zero_disables`, `test_fallback_skip_policy`,
  `test_arrival_window_zero_credit_unconsumable` (BEFORE = AFTER = 0 → only E == t consumes; the lift stays).
- **Mutation:** remove the rising-edge restart → `test_rising_edge_restarts_anchor_window`; read house state in the
  predicate → `test_anchor_independent_of_house_state`; drop the held check → `test_held_radar_blocks_anchor`; treat a
  dead input as off → `test_dead_input_last_on_blocks_anchor`; restore the per-tick floor →
  `test_exit_term_before_departure_edge_no_phantom`; skip credit consumption →
  `test_resident_arrival_before_entry_term_counted_once`; drop the floor →
  `test_uncounted_door_arrival_lift_persists`; remove the entry-term restart → `test_entry_term_restarts_anchor_window`;
  return before the restart while unknown → `test_entry_term_while_unknown_restarts_window`; `any()` instead of consume →
  `test_exit_consumed_once_by_reconciles`; store late exits → `test_late_exit_does_not_cancel_reconcile`; re-add a
  residents-empty conjunct → `test_guest_surplus_discharges_with_resident_phone_home`; judge reconcile at `t_e + LAG` →
  `test_reconcile_waits_for_late_exit_outcome`.

**P2-D3 ledger wiring (Tier 3).** Terms from every outcome path (`off` excluded: switch off → ledger `unknown`);
subscribe residency departures and substrate rising edges (unsubscribed in teardown); build `held` per eval from the
substrate's Tier-1 entity map, `hass.states` and the RAM last-known-good map (P2-D2 step 2; the map is updated on every
eval from `on` / `off` readings, never persisted); one `crossing_vision_ledger` episode per term / anchor / reconcile /
lift (kind, n, `term_source`, L before/after, residue, credit consumed, crossing_key), batched.
Diagnostics: `crossing_ledger` {state, L, L_raw, last_anchor, residue_last, terms_today by source, reconciled_today,
open_credits, held (first 5 entity ids)}.
Trip-wires: `crossing_ledger_stuck` HIGH (`guest_vis ≥ 1` while every sample for `CROSSING_VISION_LEDGER_STUCK_S` passed
the anchor predicate except the entry-term conjunct, held inputs included, so a still guest on a radar never pages it
and a term stream that blocks the anchor IS paged; resident-independent; RAM latch re-armed at `guest_vis` 0);
`crossing_ledger_anchor_zero` LOW (no anchor in `CROSSING_VISION_LEDGER_ANCHOR_ZERO_S`; the text names the holders seen
most in that span, dead ones first, since a dead input is faulty equipment to fix; suppressed, with the cause named in
diagnostics, while no `census_tick` has ever arrived, e.g. enhanced census off: reviews A-LOW-1 / D-L3). The type joins
`MEMORY_WRITER_BACKED_EPISODE_TYPES`.
- **Tests:** `test_every_outcome_yields_one_term_or_documented_none`, `test_switch_off_sets_unknown`,
  `test_teardown_unsubscribes_ledger_feeds` (asserts the dispatcher listener sets hold no entry for the instance, review
  B-L2), `test_ledger_episode_per_term_batched`, `test_stuck_ledger_pages_once`, `test_stuck_not_paged_while_held`,
  `test_anchor_zero_pages`, `test_anchor_zero_names_dead_holder`, `test_anchor_zero_silent_without_census_tick`,
  `test_held_set_from_substrate_map_and_lkg`. Mutation: remove the stuck latch → `test_stuck_ledger_pages_once`; drop the
  LKG lookup → `test_held_set_from_substrate_map_and_lkg`.
- **Live:** ≥ 1 `crossing_vision_ledger` term row with non-null `L_after`; `crossing_ledger.state` reads `known` after
  the first anchor. Phase 1 merged to develop is a precondition.
- **Build notes (fix-up 2026-11-14).** Held is computed by a pure `crossing_ledger.classify_held(readings, lkg)`
  (so the dead-input tests are pure) called from `CrossingVisionShadow._held_inputs`; the Tier-1 map comes from a new
  read-only `OccupancySubstrate.tier1_entity_ids()` (hass.data `occupancy_substrate`); dead-stream = any room
  coordinator's S1 `camera_input_stream_dead(eid)` True (S2's house getters replace this lookup). Lifts are a row kind
  `lift`; terms carry `credit_consumed`. The B-L4 writer-health exemption is a rung-1 map
  `MEMORY_WRITER_HEALTH_SWITCH_GATED_TYPES` (type -> hass.data switch key): the ledger type is not checked while the
  shadow switch is off. **Open questions (not built, for the planner):** (Q1) applied exits with E before an anchor
  stay in the exit store, so an exit at E, an anchor at E + Δ (resident's phone still home) and the departure edge
  after it cancel that reconcile: phantom + 1 until the next anchor (≤ one window; D-L1's shape for an applied exit);
  fix would clear the exit store at the anchor. (Q2) no `occupancy_substrate` in hass.data (presence not set up) =
  an empty Tier-1 map = nothing held; the plan does not say whether a missing map should hold.

**P2-D6 scorer extension + disposition (read-only).** Dark-ledger replay through `crossing_ledger` from shadow rows (bars
compute before Phase 2 deploys); bars a-e (census plan §3.4); per-crossing §15.7a numbers; reports per door / direction /
day-night. Disposition audit `AUDIT_crossing_vision_ledger_disposition_<date>.md`: FLIP-READY / HOLD (named bar, revival
number) / PARK (bar a or b fails twice). One query.

**P2-D7 group sample (operator, ~15 min):** ten staged crossings of 2-3 residents (garage A and front, ≥ 3 at night);
labels `quality/tests/fixtures/crossing_vision_groups_labelled.json`.

**P2-D8 fast stage (Tier 2-DB; only if P2-D0 (vi) shows simulated F p90 ≤ 60 s AND F = B share ≥ 85 %).** Two-stage
latency (person-sighting §15.5 F/B/S): F at the Frigate event START on the door group, `image_analyzer` on 1-3 frames
(snapshot + latest frames via the Frigate proxy), Luna, `stage = provisional`, recorded on the shadow row and shown only
on the awareness entities' `last_crossing` attribute, never applied to the ledger. B = the Phase 1 call, `stage = final`.
S at `max(B outcome, E + CROSSING_VISION_NAME_SETTLE_S)` joins F, B, names and camera counts into the arrival record and
the ONE ledger term (final count; F only if B failed); F vs B disagreement recorded (`revised`). Dispatch blocked until
the P2-D0 (vi) audit row exists. The same simulation also prices the single-call levers (L1 call at event start + fixed
delay, L2 snapshot-first, L3 3 frames, L4 model / reasoning effort, L5 call at E before direction resolves); a lever is
adopted if p90 drops and exact-count stays within 2 points of the D0b 93.3 %. If the F gate fails, the audit names the
failing number and the operator decides between an adopted lever, a re-measure, or parking F with a card and revival
trigger; F is never dropped silently. Adopting F or any model change resets the bar window (rows carry `pipeline_version`).

**P2-D9 arrival record (Tier 2-DB) + count follow-up (rung 2).** NEW type `crossing_vision_arrival`, written once per
crossing (cluster: once, keyed by the primary, members listed) at `max(vision outcome, E + CROSSING_VISION_NAME_SETTLE_S)`
for entries and `E + CROSSING_VISION_EXIT_NAME_SETTLE_S` for exits; one tracked timer per crossing, cancelled at
teardown; restart drops pending (counted). The type joins `MEMORY_WRITER_BACKED_EPISODE_TYPES`. `node_id = vision_arrival:<crossing_key>`, `source_ref = egress_camera@E`,
`dedup_source_ref=False` (with True, the global `source_ref` check at `database.py:10765-10770` would skip every row
because the shadow and outcome rows already hold that key). `named` = union, canonicalised through
`_canonical_person_slug`, of: each member's bus `person_id`; for exits the backfilled `person_id` re-read from
`person_entry_exit_events`; fresh resident names on the door group's face-name entities resolved registry-first
(`face_name_entities_for_stem`, manual §1.1) with `last_changed` ∈ [E − `FACE_MATCH_WINDOW_S`, settle]. `guest:*` names
count toward `k` and are listed separately. `n` from the ledger term; `k = len(named)`; `guests_unnamed = max(0, n − k)`.
Read through `get_last_arrival_record()` (read-API plan). `k` comes only from the F3 attach and NVR names (~30 % of
entries carry `person_id` today), so `k` means "recognised so far".
Count follow-up: under rung 2 only (census plan §3.2), when the record is written with `term_source = vision` and
`n > k`: ONE `async_notify(..., quiet=True)`, severity LOW. NM has no tag / replace (`notification_manager.py:1531-1545`;
`_arrival_departure_notify` calls it with `coordinator_id`, `severity`, `title`, `message` only,
`transit_validator.py:2652-2657`); the pattern is PERIMETER-IDENTITY-FOLLOWUP-1's quiet follow-up
(`notification_manager.py:1544-1554`). Per crossing at most 2 arrival sends plus the perimeter alert and its one identity
follow-up, unchanged.
- **Tests:** `test_arrival_record_waits_for_late_protect_name`, `test_arrival_record_one_row_per_cluster`,
  `test_exit_record_reads_backfilled_person_id`, `test_arrival_record_teardown_cancels`,
  `test_arrival_row_written_despite_existing_shadow_row`, `test_arrival_notify_not_delayed_by_vision`,
  `test_r7_and_perimeter_followup_same_crossing` (arrival sends ≤ 2, follow-up `quiet=True`, perimeter sends unchanged).
  Mutation: write at the vision outcome without the settle → the first test red.
- **Live:** one `crossing_vision_arrival` row with `n`, `k`, `guests_unnamed`; `crossing_vision_last` shows them.

**P2-D10 metric sensors + grading (Tier 2-DB).** Five display sensors on the Crossing Vision device, values from RAM rings
rehydrated from shadow / ledger rows at setup (no new table), window `CROSSING_VISION_METRIC_WINDOW_DAYS`:
`sensor.ura_crossing_vision_exact_count_rate` (from grades), `_blank_rate`, `_ledger_drift` (last residue + 7-day share of
zero-residue anchors), `_match_coverage`, `_latency_p90` (provisional and final; `t_provisional − E`, `t_final − E`,
`t_synthesis − E`; target `CROSSING_VISION_LATENCY_TARGET_P90_S` 60, later ≤ 15 for security; p90 above target
`CROSSING_VISION_LATENCY_TRIPWIRE_DAYS` running → LOW page). Grading: up to `CROSSING_VISION_GRADE_DAILY_N` crossings a
day (disagreements and groups first), one Companion actionable notification each, action ids
`GRADE_URA_<crossing_key_hash>_<n>` for n in 0..4 plus `_more`; one `startswith("GRADE_URA_")` branch in
`_handle_companion_action` (`notification_manager.py:1330`, handler `:3781`; no second listener; never the free-text
`_process_inbound_reply` path `:4055`); RAM map of pending grades (TTL `CROSSING_VISION_GRADE_PENDING_TTL_S`); one
`crossing_vision_grade` episode per grade (`node_id = vision_grade:<crossing_key>`, `dedup_source_ref=False`). Fallback
if Companion actions are unavailable: a dashboard select per pending crossing. The weekly identity labelling
(EGRESS-OUTCOME-WEEKLY-LABEL-1) and grading run as one operator session per crossing key (operator approved 2026-11-13).
- **Tests:** `test_grade_action_writes_episode`, `test_grade_unknown_hash_ignored`, `test_metric_sensors_rehydrate`.
- **Live:** the five sensors have states; one grading notification delivered.

### Phase 3: count path, a better direction instrument, cap (cards VISION-AMBIGUOUS-CROSSINGS-1 + DOOR-VISION-GROUP-UNDERCOUNT-1, EGRESS-TRACKER-DIRECTION-1)

Charter goals served: "Vision is to assist census accuracy"; "make census almost bullet proof at entry"; "Vision on
crossing with no clear direction - of course. No brainer"; "Is Vision working as designed is the central question";
gates "sized to real error rates, not calendar"; "We should do the hard parts sooner and learn faster". Hard
constraint kept: "I need away to be fast acting" (AWAY reads the trust view only; nothing here touches it). Operator
rule 2026-11-15: "The things we see not working have to be reasoned through and fed back into our new plans". Facts:
consumes F3 (bus + ring) and, through the ledger, feeds F2-A only; produces F3 attributes through G3 (P3-D3); a
deterministic direction fix, if P3-D0b passes, is produced by the F3 owner (P3-D9c). No F1, F4 or F5 output. Consumer classes: display now;
ledger (F2 input) behind INV-DIR-GATE; the census ladder (census plan §3.2) unchanged except the
F-LEAD direction precondition (census plan §3.2, amended with this plan).

**P3-D0 results and what each one changes** (`AUDIT_crossing_vision_p3_d0_2026_11_15.md`; decisions rest on run 2,
`max_tokens` 4000, because run 1 was measured through a truncation defect; the two runs agree on every verdict).

| Gate | Result | Reasoning | Plan change |
|---|---|---|---|
| (a) volume | GO: max simulated 62 calls/day (11-14, ambiguous included) → cap 93; busy collisions 0-1 of 137; `memory_episodes` 18,855 rows | Cap sized from the busiest measured day; no index needed below 200,000 rows | Built on `feature/crossing-p3-first` (`CROSSING_VISION_DAILY_CALLS` 93) |
| (b) direction | NO-GO: 13/17 readable (gate 15), 3/6 tracker-wrong (gate 5). 15:12:14 answered `in` in run 1 (`max_tokens` 1500) and `out` in run 2 (4000): same clip and prompt, not an identical call, so this is a flip across a parameter change, not yet a measured repeat-call flip | Not close on the clips that matter (the tracker-wrong ones), and possibly unstable: the provider entry runs at temperature 1.0 (GPT-6 requires it, §5 Config-first), so a re-call can differ. A direction that flips on identical calls cannot be scored once and trusted, so stability is measured on true repeats (P3-D3 step 8); voting over N calls multiplies calls by N for a model already below the bar. On this evidence an LLM on frames is not a direction instrument | Operator 2026-11-15: "Is the bar right? I'd not park and instead build and hold off and measure. We need reps." Direction is built and recorded behind INV-DIR-GATE (P3-D3), scored per door group with a stability measure (P3-D6), flipped only per door group at a checkpoint (P3-D7). P3-D0b adds a second, deterministic source scored the same way |
| (b) group count | NO-GO on the ≤ 1 bar: of 30 clips with a human count, 25 exact, 1 over, 4 under; 18:43 (5 vs 7) and 21:24 (2 vs 4) under by 2. False blank fixed (16:19:36 4 vs 4). Empty replies at 1500 tokens were truncation; 0 of 31 empty at 4000 | Vision is right on 1-2 people and short by 1-2 on groups of 3+; that is a bias to state and use, not a reason to stop counting (the camera peak is no better on groups: 18:43 peak 5, 18:59 peak 4, 21:28 peak 1) | P3-D2 keeps the count path with 8 frames and 4000 tokens; the group bias is a named property with a census use rule (P3-D2 "Known bias") |
| (c) recording route | GO: llmvision fetched the recording proxy (200, 7 frames, 10.9 s); window complete ≥ 5 s after its end; the R3 window [E−10, E+15] led with empty frames | The route bounds clip size; the event-clip route took 86.6 s on a 289 MB clip against the 90 s timeout | P3-D2 uses `recording_window` (bounded), BEFORE 5 s, LAG 10 s; group counts on that route at 4000 tokens are unmeasured, so P3-D0c measures them first |
| (d) pass mechanism | HOLD: ≤ 19 labelled round trips possible (< 20); rule (ii) shares a pass key on 4 of 14 one-pass pairs (bar 0.80) | Fails on mechanism, not sample size: pairs sit 17-58 s apart while Frigate events last 5-60 s, and the two front cameras run separate events, so one physical pass spans two events | Collapse stays off; P3-D4 and P3-D9a builds park; P3-D0d measures other pass keys |
| (e) errors | Not reproduced (0 of 4) | Transient; P3-D1 records the next one | none (P3-D1 built) |

**What this amendment fixes, for which readers (plain statement, review G2).**

| Finding (`AUDIT_door_vision_accuracy_2026_11_14.md`, P3-D0) | Ledger + awareness view | Every other reader (notify, census egress-face union, entered/exited + DB rows, perimeter, sightings) |
|---|---|---|
| Direction wrong on 6 of 17 readable clips (35 %); vision 13/17 on one run | Measured on production (P3-D3, P3-D6); per door group, fixed by P3-D7 after FLIP-READY, or for every reader by P3-D9c if a P3-D0b instrument passes | Fixed only by P3-D9c |
| One pass emits exit + entry (21 of 25 clustered members) | Collapse waits for a pass key that passes P3-D0d (P3-D4). A right direction makes it one ledger term when the members are within the 60 s cluster (same-direction cluster rule) | Only members within `DOOR_STEM_DEDUP_S` (30 s, `const.py:3391`) on one door group (door-group scoped only when `CONF_DOOR_GROUPS` is set, `transit_validator.py:2394-2399`) are deduped at the source; pairs 30-58 s apart stay two events for these readers until P3-D9b |
| Groups of 3+ undercounted; false blank | False blank fixed (4000 tokens); groups improved but short by 1-2 on 4 of 6 pinned clips: named bias, use rule in P3-D2 | Not a reader of vision counts |
| 20-53 % of crossings never watched | Watched (P3-D3); a term only through vision direction after P3-D7, or a tracker direction after P3-D9c | Unchanged (ambiguous stays ambiguous for them) |

Until P3-D9c or P3-D9b ships, the census egress-face union (`register_egress_face` / `evict_egress_face`), the arrival
notification, the entered / exited counts and `person_entry_exit_events`, and perimeter keep the tracker's direction,
wrong on about a third of readable crossings: an arrival labelled exit evicts the arriving face from the union.

**Design answers per finding.**

| Finding | Mechanism (code) | Phase 3 answer |
|---|---|---|
| Direction 35 % wrong; 4 arrivals as exits (~12 people) vs 2 exits as entries (3) | Interior-camera timing only (`transit_validator.py:2401-2423`): an interior event 0-45 s after E = entry, 0-30 s before = exit, nearest wins. Plausible bias, unproven: someone inside walking to greet an arrival fires the interior camera BEFORE E, so the arrival reads exit | P3-D0b measures deterministic instruments (Frigate track geometry, door contacts, interior-timing variants) on the same 17 clips; a passing one goes into the tracker (P3-D9c). Vision direction recorded and scored per door group (P3-D3, P3-D6), flipped for the ledger only (P3-D7) |
| 20 of 101 (11-14), 42 of 79 (11-13) ambiguous, never watched | Skip `crossing_vision.py:616-618` | P3-D3 (count and recorded direction) |
| 21 of 25 clustered members opposite-direction | Direction-keyed dedup (`transit_validator.py:2425-2438`); direction-blind clustering (`crossing_vision.py:664-672`, `:740-749`); `cluster_terms` +n / −n (`crossing_ledger.py:194-203`) | P3-D0d (pass key), then P3-D4 (ledger) and P3-D9b (source); P3-D9c helps every reader only for pairs within 30 s on one door group, the ledger for pairs within 60 s |
| Every 3+ group undercounted; 1 false blank; 24 of 41 calls had an empty sampled frame | 4 frames evenly over a 5-466 s event; 1500 output tokens truncated the big-party replies to empty | P3-D2 (built in part: 4000 tokens) |
| 4 errors, cause unknown | Error string dropped (`crossing_vision.py:917-918`) | P3-D1 (built) |
| 46 calls vs cap 40 | RAM counter reset by two restarts | P3-D5 (built, cap 93) |

**Why a model result cannot fix the tracker's readers, and why the direction fix belongs in the tracker.** The
tracker's direction is consumed synchronously at resolution, 10-200 s before any vision result; `direction` is a
forbidden G3 key (contract §4.2, `transit_validator.py:977-979`). Even a perfect LLM direction could only ever have
fixed the ledger. Frigate's track data (path, zones) arrives on the same MQTT stream as the person event, BEFORE the
tracker resolves (resolution is E + up to 45 s), so an instrument built on it can decide at resolution, inside the F3
owner, for every reader (P3-D9c). Readers this module leaves byte-identical (INV-F3-OWNER):

| Reader | Site | Class |
|---|---|---|
| Arrival / departure notification | call `transit_validator.py:2548`, def `:2917` | notification |
| Census egress-face union: entry registers, exit evicts | `transit_validator.py:2575-2600` | F2 trust input |
| `person_entry_exit_events`, Persons Entered / Exited Today, last entry / exit sensors | `log_entry_exit_event` `:2610`; bus listeners `sensor.py:4915`, `:5046`, `:5160`, `:5210` | display |
| Perimeter identity cache, scoped egress mute | `perimeter_alert.py:1110`; manual, scoped egress mute | security |
| Sighting producer | `person_sighting.py:59`, `:155` | F4 |
| Read-API crossing getters | `presence.py:6068-6155` (return the `CrossingRecord`, so the new attributes surface passively) | display |

**Producer check.** (1) Tracker direction: 101 resolutions on 11-14 (81 resolved, 20 ambiguous), 79 on 11-13 (42
ambiguous); rule = nearest interior event in [−30 s, +45 s]; health = 35 % wrong on readable clips, so it is not an
oracle for vision (the D0 51 % agreement measured the tracker, not vision). (2) Vision count: 46 calls on 11-14, 41 `ok`,
33/41 exact against human truth; healthy for 1-2 people, not for 3+. (3) Vision direction: measured offline only (P3-D0 b: 13/17, 3/6; one clip changed between runs that differed in `max_tokens`); produced live from P3-D3.
(4) Ledger terms: zero term rows since the v5.108.24 boot (ledger `unknown`, anchor blocked by held inputs,
`AUDIT_crossing_pipeline_after_v5_108_24.md` §5), so scoring uses the P2-D6 dark replay, never the live ledger. (5) G3:
`g3_calls = {}` live; the one production G3 caller is `camera_census.py:5319` (exit backfill); Phase 3 adds none.
(6) Frigate track fields (`path_data`, `entered_zones`, `velocity_angle`): delivered on every `events` message to the
shared ingress (fixture keys above), read today only by the perimeter D3 gate (`entered_zones`); fire count for door
cameras unmeasured (P3-D0b step 1 measures how many 11-14 door events carry a usable path). **Consumer check:** tables
above; forward trace: `vision_direction` → G3 attribute → display and the P3-D6 scorer now → a ledger term only in a
door group flipped by P3-D7 → `guest_vis`; ambiguous-crossing count → its row → `crossing_vision_last` (no term before
the flip, no arrival record); a P3-D9c direction → the tracker's `direction` → every reader in the table above and the ledger term
→ `guest_vis` → awareness (F-LEAD needs a P3-D6 FLIP-READY or TRACKER-READY verdict for the source in use) → F-NOTIFY. No path to house state, access,
security or HVAC from this module. New producers get zero-fire trip-wires (P3-D3 step 8; P3-D9c in its own plan).

**Pass (one pass key, owned by the F3 owner; harmonization C5; review H1).** **Status after P3-D0 (d): the event-window
rule below FAILED** (shares a key on 4 of 14 labelled one-pass pairs; bar 0.80). It is kept as the specification of a
measured, failed candidate; the replacement is chosen by P3-D0d, and `pass_identity` implements whichever candidate
passes, under the same ownership and the same consumers. `_match_event`
(`crossing_vision.py:761-778`) picks the best event across the whole door group, so it cannot tell one pass from a
round trip; it is not the pass key. ONE function, `pass_identity(...)`, pure, in `transit_validator.py`, computed by
`EgressDirectionTracker` at resolution (P3-D9a) and stamped on the `CrossingRecord` (creation-time field `pass_key`,
not a G3 amend) and on the bus event (additive key `pass_key`). P3-D4, P3-D3, P3-D6, interior D5 and NVR W2 consume it;
none computes its own. Rule:
- A crossing's **pass event** is a Frigate person event on a camera of its door group whose [`start` −
  `CROSSING_VISION_PASS_EVENT_PAD_S`, `end` + pad] contains the crossing's E, read from the tracker's own Frigate
  person-event ring (`register_frigate_consumer`, the same ingress crossing vision uses). **`end is None`** (event still
  running at resolution, which is E + up to 45 s): the window is [`start` − pad, resolution time], i.e. an open event
  spans E if it started before E + pad. Preference: an event on the crossing's own camera (the Frigate camera paired to
  the egress camera by the W1 device pairing, `camera_resolver.py:895`; no name inference), else the door-group event
  with the latest `start` ≤ E. No such event: `pass_key = None`.
- `pass_key` = the pass event's id. Two crossings are **one pass** iff same door group AND same non-None `pass_key`.
  `None` never equals `None`. A pass may hold k ≥ 2 crossings (exit, entry, exit on one event = one pass) and ambiguous
  ones (they contribute no tracker direction).
- Cross-camera pairs (G6 Entry vs Front Door Aerial) are one pass only when one camera's single event spans both;
  expected share before measurement: the 11 same-camera pairs (8 same device + 3 W1 twins) plus those cross-camera
  pairs an event spans, not all 21.
- A pass split across two clusters (crossings > `CLUSTER_S` apart) is not collapsed (counted `pass_split`).
- **Named residual, the one-event round trip:** a resident who steps out and back in while staying in one Frigate event
  (events run 5-466 s) is one pass by this rule, though the tracker comment calls exit → entry inside 30 s a real round
  trip (`transit_validator.py:2425-2427`). Effect per consumer: P3-D4 under `tracker` no term (`L` unchanged, the same
  net as today's +1 −1, but no credit consumed and no exit stored); P3-D4 under `vision` (after P3-D7) one term in
  vision's direction, so `L` off by one until the anchor; P3-D9b would suppress the re-entry for every reader, so the
  census egress-face union evicts on the exit and never re-registers, and the arrival notice for the return is lost.
  P3-D0 (d) bounds its rate; P3-D9b may not ship unless the bound holds.

**P3-D0 probe (DONE 2026-11-15).** Results, verdicts and the plan changes they drive: the table at the top of
Phase 3. Audit `AUDIT_crossing_vision_p3_d0_2026_11_15.md`; fixture `quality/tests/fixtures/crossing_vision_door_eval_2026_11_14.json`
(46 events, 17 readable directions, 6 tracker-wrong, 25 pairs, 43 mined pairs; 18:59:36 human count unpinned, 8-10).
120 of 120 Luna calls spent. Its full specification moved to the history archive.

**P3-D0b direction instrument probe (read-only, 0 model calls; a second, independent direction source,
scored the same way as vision in P3-D6; gates P3-D9c).** Question: is there a deterministic signal that gets direction right where the tracker does not? Steps:
0. **Hand-build the door references first** (measure-before-build corollary). For each Frigate door camera in a door
   group (`after.camera` names from the fixture events, not entity ids), mark the door threshold as a polygon in
   Frigate's normalised image coordinates from one snapshot; commit
   `quality/tests/fixtures/crossing_door_reference_frigate.json` with the snapshot time. Resolve each door group's
   exterior contact or cover (if any) through the entity / device registry by area and device class, never by name,
   and record the mapping in the same fixture.
1. **Data availability.** For every fixture event read the stored Frigate event (`frigate/events/get` over the HA
   websocket, instance `frigate-f2`, as P3-D0 did) and record whether it carries a track path (`path_data` or its
   stored equivalent) and zones. UNVERIFIED today whether stored events keep the path: the live MQTT payload does
   (fixture keys). If stored events do not, step 1b: a read-only MQTT capture of door-camera `events` messages on the
   operator's laptop for `CROSSING_DIRECTION_PROBE_CAPTURE_H` (48) hours, no HA change, and hand-label direction on
   those clips by the same rubric (first and last position against the door) until ≥ 17 readable are labelled.
2. **Instruments**, each scored against the human labels on the 17 readable clips and separately on the 6 the
   tracker gets wrong:
   - **I1 track vs door:** `in` when the track starts outside the door polygon and ends inside it (or ends within
     `CROSSING_DIRECTION_DOOR_PAD` (0.05, normalised) of it and the object is lost there); `out` the reverse; else
     `unclear`. Scored on the path TRUNCATED to points with timestamp ≤ E + 45 s (the latest resolution time P3-D9c
     would have; review finding 10), never on the stored final path; also reports the share of crossings whose event
     is still open at E + 45 s.
   - **I2 zone order:** `entered_zones` order across two zones per door camera. N/A today (one `<cam>_property` zone
     per camera). Reported as a config-first option: adding a `<cam>_threshold` zone per door camera is a Frigate
     (homelab) config change, not URA code; if the operator adds them, I2 is scored on new events.
   - **I3 door contact order** (door groups with a contact or cover): exterior camera event start before the door
     opens = `in`; door opens before the exterior event starts = `out`; within `CROSSING_DIRECTION_CONTACT_TIE_S` (2)
     = `unclear`.
   - **I4 interior-timing variants** (Frigate interior person events back to 11-02): (v0) today's rule, must reproduce
     11/17; (v1) prefer `entry` when both windows hold an event; (v2) use interior track START for entry and END for
     exit instead of any detection time.
   - **I5 combination:** I1, else I3, else the tracker (the fallback a P3-D9c build would actually use).
3. **Determinism** check: each instrument run twice on the same inputs gives identical output (the property the LLM
   failed).
4. **Coverage:** on all 101 crossings of 11-14 (ambiguous included), the share each instrument decides (in / out).
- **Gate (reuses the P3-D0 "worth building" numbers):** an instrument, or I5, right on ≥ `CROSSING_VISION_P3_DIR_GATE_OK`
  (15) of 17 AND ≥ `CROSSING_VISION_P3_DIR_GATE_TRACKER_WRONG_OK` (5) of 6, deterministic, and deciding ≥
  `CROSSING_DIRECTION_INSTRUMENT_COVERAGE_MIN` (0.50) of crossings on its OWN decisions, before any tracker fallback
  (review finding 17: I5 with the tracker fallback covers ≥ 81 % by construction, so its fallback share is reported,
  not gated). Bias controls: door polygons and the contact mapping are frozen and committed before any label is
  read; the labeller does not see instrument outputs; choosing the best of about six instruments on n = 17 inflates the
  winner's score, so P3-D6 on production volume, not this gate, decides adoption. Pass → P3-D9c is planned on that instrument. Fail on every instrument → direction stays the tracker's;
  the operator is asked whether to add Frigate threshold zones (I2) or a door contact where none exists, then re-run.
  At n = 17 this is evidence that building is worth it, not the runtime bar (P3-D6 decides that on scored passes).
- **Acceptance:** `AUDIT_crossing_direction_instrument_<date>.md`, one row per instrument with right / tracker-wrong-
  right / coverage / determinism, plus the door-reference fixture committed before scoring. Discriminates: an
  instrument that copies the tracker's bias scores ≤ 11/17 and 0/6; v0 must reproduce 11/17 or the replay is wrong.

**P3-D0c recording-window group check (≤ `CROSSING_VISION_P3_D0C_CALLS` (14) Luna calls; gates the P3-D2 route
default; operator budget yes needed).** P3-D0 measured groups on the event-clip route at 4000 tokens (run 2) and the
recording route only at 1500 tokens with BEFORE 10 s, whose leading frames were empty. Run once: recording window
[E − 5, E + 15], 8 frames, `max_tokens` 4000, on the 6 pinned group clips (18:43:18, 21:24:08, 21:28:01, 16:19:36,
16:16:11, 16:23:52), 18:59:36 (reported, excluded), and 7 one- or two-person clips including 16:30:44 and the 289 MB
13:40:36. **Gate:** total undercount on the 6 pinned ≤ run 2's (6), no pinned clip worse than run 2 by more than 1,
no new over-count on the 7 small clips. Pass → `recording_window` is the default for every call. Fail → `event_clip`
for events no longer than `CROSSING_VISION_LONG_EVENT_S` (60), `recording_window` above it (a long event's clip is
both slow and badly sampled). **Acceptance:** a section appended to the P3-D0 audit with per-clip counts beside run 2,
latency (separately for clips longer than 40 s, the fail branch's timeout risk), and the route verdict.

**P3-D0d pass key probe (read-only, 0 model calls; gates P3-D4, P3-D9a, P3-D9b).** The event-window rule failed on
mechanism (pairs 17-58 s apart, events 5-60 s, two front cameras with separate events). Frigate events carry no
cross-camera track id (the fixture's `after` keys hold the per-camera event `id` only), so a "Frigate track id across
cameras" is not available. Candidates, each scored on the labelled pairs:
- **K1 door-contact cycle:** crossings of one door group inside one open → close cycle of its contact (padded by
  `CROSSING_VISION_PASS_CONTACT_PAD_S` (5)) share the cycle as the pass key. Door groups without a contact get None.
  Named residual: a door held open across a step-out-and-back merges a round trip.
- **K2 right direction instead of collapse:** with the best P3-D0b instrument, the share of `one_pass` pairs whose two
  members get the SAME direction, reported as two shares (review finding 9): pairs within `DOOR_STEM_DEDUP_S` (30 s)
  on one configured door group, which the source dedup then makes one event for EVERY reader, and pairs within
  `CLUSTER_S` (60 s), which become one ledger term only; plus the share of `round_trip` pairs that keep opposite
  directions. If K2 passes on the 60 s share, ledger collapse may not be needed; the 30 s share says how much of
  P3-D9b it replaces.
- **K3 chained door-group events:** the union of the door group's person events whose intervals overlap or sit within
  `CROSSING_VISION_PASS_CHAIN_GAP_S` (5) of each other, across both cameras; the chain's first event id is the key.
Labels first: label the 15 `not_viewed` mined pairs, then mine every pair back to Frigate retention (from 11-02). If
fewer than `CROSSING_VISION_PASS_ROUND_TRIP_MIN_N` (20) labelled round trips exist in retention, mining cannot meet
the round-trip gate: the operator stages them (about 10 step-out-and-back walks per door group, ~15 min, beside
P2-D7), or accepts the residual by name. **Gate (unchanged numbers):** ≥ 0.80 of `one_pass` pairs share the key (K2:
get one direction); ≥ 20 labelled round trips; Wilson 95 % upper bound of round trips merged (K2: given one
direction) ≤ 0.15. **Acceptance:** `AUDIT_crossing_pass_key_<date>.md`, per candidate the three numbers, and the
recommendation. Collapse stays off (`CROSSING_VISION_LEDGER_PASS_COLLAPSE` False) until one candidate passes.

**P3-D1 error text on error rows (Tier 1; BUILT on `feature/crossing-p3-first`, 48d4bc94).** `_run` keeps
`reply["error"]`; `_record` writes `error` (≤ `CROSSING_VISION_ERROR_TEXT_MAX_CHARS`, 200) on `error` rows only.
- **Tests:** `test_error_row_carries_error_text`, `test_error_text_truncated`, `test_ok_row_has_no_error_key`.
- **Live:** the next `error` row has a non-empty `error` (with zero errors in the window the test is the proof; the
  README says so).

**P3-D2 crossing-centred frames, 8 frames, 4000 tokens (Tier 2; route default from P3-D0c).** Part built:
`CROSSING_VISION_MAX_TOKENS` 4000 for every crossing call (`feature/crossing-p3-first`, 3925c18f; the global
constant, not only an 8-frame path: on Luna the extra output costs nothing measurable and removes the truncation
defect for any reply). Remaining:
1. `CROSSING_VISION_FRAME_ROUTE`: `recording_window` if P3-D0c passes, else the long-event split (P3-D0c). The URL is
   `/api/frigate/<instance>/recording/<camera>/start/<E − BEFORE>/end/<E + AFTER>` where `<camera>` is the matched
   event's Frigate camera name from the event payload (`after.camera`, `crossing_vision.py:562`) and `<instance>`
   comes from the event's MQTT source / `discover_frigate_instance_ids` (`:543-548`) as `_clip_reference` does today;
   never from the egress stem or entity id (registry rule). BEFORE 5 s (P3-D0 R3: the 10 s lead was empty frames),
   AFTER 15 s.
2. **Fire time (review finding 6).** On `recording_window` the request fires once at max(bus arrival,
   E + AFTER + `CROSSING_VISION_RECORDING_LAG_S`) = max(bus arrival, E + 25 s), WITHOUT waiting for the Frigate event
   end: scheduling that fire cancels `req.unsub_timer` (the event-end timer) and an event `end` arriving later does not
   fire the request again (`_fire_request` runs once per request). The event-end wait (`:713-726`, outer bound
   `EVENT_END_WAIT_S` 120) applies only to the `event_clip` route.
3. **Large clips.** The recording window bounds the clip to BEFORE + AFTER (20 s) whatever the event length, which is
   the fix for the 289 MB / 86.6 s case. `CROSSING_VISION_TIMEOUT_S` stays 90 (it sits above llmvision's own request
   timeout so cancelling never orphans its ffmpeg; recording-window calls measured 10.9 s). An event-clip call (pre-call
   fallback, or a short event under the P3-D0c fail branch) that times out is a `timeout` row, no second call. A long
   event (> `CROSSING_VISION_LONG_EVENT_S`) never uses the event clip unless the window route is unavailable before the
   call, and then the row records `frame_route = event_clip_long` so the scorer can count them.
4. **Fallback semantics (one call, always):** failures detectable before the call (no instance, no camera name, the
   window end not reachable inside the outer bound) use `event_clip` for that same single call. A fetch failure inside
   llmvision is an `error` row with the P3-D1 text; no second call.
5. **Frames: 8 on every crossing call** (`CROSSING_VISION_CROSSING_FRAMES` 8; replaces the planned peak ≥ 3 branch).
   Why not the branch: run 2 sent 8 frames on all 31 clips with no change on any 1- or 2-person clip (median latency
   12.7 s against the production 4-frame p50 9.7 s), and the peak branch misses the cases that need frames most: an
   ambiguous crossing has `camera_peak_count = None`, and 21:28:01 had peak 1 with 3 people. The branch adds a rule
   and a test surface to save a few seconds on singles. `analyze_crossing_frames` keeps taking `max_frames` from its
   caller, so interior clip callers (VISION-INTERIOR D3 / D5) keep their own frame count.
6. Rows record `frame_route`, `frames_requested`, `pipeline_version`.
7. **Known bias (named; not a gate).** On groups of 3+ vision is short by 1-2 people on 4 of 6 pinned clips and over by
   1 on one (16:23:52); exact on 1-2 people. **Census use rule:** the ledger term `n` stays the vision count (the
   recorded value, `term_source = vision`); vision's count is treated as a near-floor for groups, and the camera peak
   is recorded beside it, NOT maxed into it. Why not `max(vision, camera_peak)`: on the 11-14 clips it fixes one (21:24,
   peak 4) and creates three over-counts (16:30:44 peak 3 vs 2, 16:23:52 4 vs 3, 16:20:48 peak 3 vs 2); the camera peak
   over-counts lone people in the garage. Both legs matter (review finding 8): an over-count on an entry, or an
   undercount on an exit (7 guests leave, 5 counted), leaves `L` high, a phantom guest until the anchor; an undercount
   on an entry or an over-count on an exit leaves `L` low (a missed guest); a group under-counted the same on both legs
   cancels. Vision's errors are mostly undercounts on groups, which roughly cancel over a visit; max adds over-counts
   that do not. So the choice stands on the totals (25/30 exact; max creates three over-counts to fix one), and P3-D6
   reports signed net error per group visit (entry n − exit n). Display may show a group as
   "n+" when `n ≥ CROSSING_VISION_GROUP_PEAK_MIN` (3). Revival of the max rule: a P3-D6 graded sample where `max`
   beats vision alone on total absolute error without adding over-counts on 1-2 person crossings.
- **Tests:** `test_recording_window_url_centred_on_crossing` (BEFORE 5, AFTER 15), `test_recording_url_camera_from_event_payload`,
  `test_crossing_call_uses_eight_frames`, `test_ambiguous_crossing_uses_eight_frames`, `test_long_event_never_event_clip_when_window_available`,
  `test_precall_route_failure_uses_event_clip_one_call`, `test_fetch_failure_is_error_row_no_second_call`,
  `test_timeout_row_no_second_call`, `test_window_route_fires_once_at_e_plus_25_event_open`, `test_frame_window_stays_in_door_group`, `test_interior_caller_frames_unchanged`,
  `test_term_n_is_vision_count_not_max_with_peak`.
- **Mutation:** window from event start instead of E → `test_recording_window_url_centred_on_crossing`; camera from
  the stem → `test_recording_url_camera_from_event_payload`; frames from `CROSSING_VISION_MAX_FRAMES` (4) →
  `test_crossing_call_uses_eight_frames`; `max(n, peak)` in the term → `test_term_n_is_vision_count_not_max_with_peak`.
- **Live:** within 2 days, ≥ 1 row with `frames_requested = 8`, `frame_route = recording_window` and `ok`; no
  `timeout` row whose clip was the event clip of a long event; the P3-D6 scorer's exact rate on graded 3+ crossings
  reported beside the 11-14 baseline (0 of 4) and run 2 (1 of 5 pinned exact). Discriminates: a build still sending 4
  frames shows `frames_requested = 4`; a build still on the event clip shows latency tails near 90 s on long events.

**P3-D3 watch every crossing; record vision's count AND direction behind the gate (Tier 3: removes an INV-SCOPE
clause, adds a production G3 writer).** Operator 2026-11-15, overruling the park: "Is the bar right? I'd not park and
instead build and hold off and measure. We need reps." P3-D0 ran 17 readable clips once; that is too few to judge a
model, and production volume gives the reps. Direction is recorded on every crossing, ambiguous included, as an F3
attribute, and scored (P3-D6); it reaches no term and no reader until P3-D7 (INV-DIR-GATE). What the count on an
ambiguous crossing is for until then: display (`crossing_vision_last`, "3 people at the front door, direction
unknown"), the scorer's coverage numbers, and the `n` for the term an ambiguous crossing gets if P3-D7 flips its door
group. Cost: inside the measured cap (93 includes ambiguous); the stability repeats have their own budget (step 8).
1. `_on_egress_event` accepts `ambiguous` while `CROSSING_VISION_WATCH_AMBIGUOUS` is True; same match, gates, cap.
   The row's existing `direction` key keeps the tracker's value (now possibly `ambiguous`; no new `tracker_direction`
   key); ambiguous rows have `camera_peak_count = None`.
2. **An ambiguous request never adopts a later resolved member (review finding 3).** The cluster test (`:664-672`) and
   the analysed-event test (`:711`) skip a request whose primary is ambiguous when the arriving crossing is entry or
   exit: that crossing opens its own request (its own match, its own call, its own count), exactly as it would have
   with ambiguous crossings unwatched. An ambiguous crossing may still join a resolved or an ambiguous request. So
   watching ambiguous crossings changes no resolved crossing's term; the only cost is a possible second call on the
   same Frigate event (counted `ambiguous_shared_event`).
3. **Late joiner direction (review finding 1, moved from P3-D4 step 4 without its `pass_key` clause).** The request
   stores `term_direction` = the direction of the term actually built at its outcome (None when no term was built,
   e.g. every folded member ambiguous). A member joining after the outcome: if it is ambiguous → no term; else if
   `term_direction` is None or differs from the member's direction → its own camera term; else no term. This replaces
   `prim_dir = primary.members[0]["direction"]` (`crossing_vision.py:745-747`), which reads `ambiguous` once an
   ambiguous crossing can be a primary and would double-count a late entry.
4. Schema and prompt add `direction` ∈ {`in`, `out`, `passing`, `unclear`} from each person's first and last position
   against the door (the P3-D0 prompt; `in` = goes into the building) and `direction_confidence` ∈ {`high`, `medium`,
   `low`}. **Both are optional in the llmvision `structure` (review finding 5):** missing or out-of-enum maps to
   `unclear` / None, and neither ever changes `outcome`, `people_count` or the clamp. A reply that parses for counts
   is `ok` whatever its direction fields say.
5. **Per-member attributes (review M3).** `vision_direction` and `vision_people_count` = the result's values for every
   member while no pass key exists (`pass_key` None until P3-D9a); once P3-D9a ships, only for members whose
   `pass_key` equals the analysed event's pass, else None. `direction_agreement` against the member's OWN tracker
   direction: `agree`, `disagree`, `vision_only` (tracker ambiguous), `unclear`, or `not_analysed`. **Deliberate
   relaxation (review finding 13a):** 50bffd62 pinned `test_round_trip_member_not_given_primary_direction`; with no
   pass key a round-trip member cannot be told apart, so it may carry the primary's direction, flagged
   `member_inherited = True`, and the scorer scores primaries only. The test and its mutation return with P3-D9a.
6. **G3 write, one function (review finding 14).** Every amend goes through `_amend_vision_direction(req_or_member)`,
   called at the vision outcome and from `_join_cluster` for a late joiner; it calls ONE `amend_crossing(hass,
   source_ref, {vision_direction, vision_people_count, direction_agreement, vision_direction_confidence}, None,
   camera=<egress camera>, role="vision_direction")` per crossing key. `source_ref` is built from the bus event's
   `egress_camera` and `timestamp` exactly as `transit_validator.py:2525-2527` does (`egress:<camera>:<iso>`).
   try/except, failures counted `vision_amend_failed`. Ring retention (1800 s / 32 per camera, `const.py:6707-6708`)
   exceeds the worst outcome time (E + 45 + 120 + 90 s); `crossing_record_aged_out` counted, never retried.
7. **Contract and guard (reviews M4, B9, B10; closure MEDIUM-3; harmonization C7).** The build adds the four fields
   (default None) to `CrossingRecord` (`transit_validator.py:946-971`) and `_CROSSING_AMENDABLE_KEYS` (`:980-983`;
   `attach_crossing_attribute` raises on unknown keys, `:1074-1076`). Contract §2.3 / §4.2 amended once by the
   orchestrator (C7; `vision_direction_confidence` is new). NEW layer-guard row `('R13', 'crossing_vision.py',
   'CrossingVisionShadow._amend_vision_direction:amend_crossing')` (max 1, which holds because both call sites go
   through that one function) in `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py`, beside the reserved
   fast-stage row (`:212`, unchanged). Delta against develop at merge time: +1 row, `len(A.ROWS)` +1,
   `LAYER_ALLOWLIST_TOTAL` +1, `_PROVISIONAL` +1 (today 228 / 256 / 259, `test_person_awareness_layer_guard.py:62`);
   the `("R13", 8)` floor (`:147`) stays valid; only P3-D3 changes the totals in this plan. The amended signal carries
   the record's `person_id` (`:1281-1290`); today's readers (`sensor.py:5092`, `:5231`) act on `exit_backfilled` only.
8. **Sampled repeat call (the stability measure, P3-D6; review findings 2 and 4).**
   - Selection: `int(hashlib.sha1(crossing_key.encode()).hexdigest()[:8], 16) % 1000 < rate × 1000` with
     `CROSSING_VISION_DIRECTION_REPEAT_RATE` (0.2), on a primary whose outcome is `ok` (never Python `hash()`, which is
     salted per process).
   - Own budget: repeats count against `CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX` (15) and NEVER against
     `CROSSING_VISION_DAILY_CALLS`: the primary cap gate (`crossing_vision.py:693`) does not see them, so a repeat can
     never turn a primary into `skipped_cap`. Rehydrated at setup like the primary counter (P3-D5 DAO, filtered to
     repeat rows).
   - Slots: a repeat never holds a primary slot. It starts only when `_pending()` is 0 (no primary in flight or
     waiting) and is counted in `_pending()` while it runs, so INV-SCOPE's in-flight bound holds; a primary that
     arrives while a repeat runs waits for it like any in-flight call and is never `skipped_busy` because of it (the
     busy gate counts primaries only). No free slot within `CROSSING_VISION_DIRECTION_REPEAT_WAIT_S` (120) → skipped,
     counted `repeat_skipped_busy`.
   - Lifecycle: a tracked task started after `_record` and `_amend_vision_direction`, never awaited by them, gathered
     and cancelled in teardown.
   - Row identity: `node_id = vision-repeat:{crossing_key}`, `source_ref = crossing_key` of the primary, attribute
     `call_kind = repeat` (primary rows gain `call_kind = primary`; `stage` stays the fast-stage field). Never amended,
     never a term, never an arrival record.
   - Readers: the trip-wires (`crossing_vision_zero`, `_errors`, `_direction_zero`), the P3-D5 primary rehydrate, the
     arrival record and the ledger read `call_kind = primary` only; the scorer reads repeats for stability only;
     `memory_query` and the status counts see them under their own node prefix. Cost ≤ 15 calls a day; 0 = off.
9. Trip-wires: `crossing_vision_direction_zero` (≥ `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` (10) primary `ok` rows in
   24 h and none with `vision_direction` in/out → MEDIUM, RAM latch); `crossing_vision_ambiguous_zero` (≥
   `CROSSING_VISION_AMBIGUOUS_ZERO_MIN` (5) ambiguous bus events counted by the bus listener in 24 h, and 0 rows with
   `direction = ambiguous` → MEDIUM). Bus count, not `egress_identity_outcome` rows.
10. `pipeline_version` (rung-1 `CROSSING_VISION_PIPELINE_VERSION`) on every row; P3-D2 and P3-D3 each bump it.
11. Arrival record and the rung-2 follow-up (P2-D9): an ambiguous crossing produces NO arrival record and no follow-up
    unless P3-D7 has flipped its door group; then one with `vision_direction = in` is an entry.
- **Tests:** `test_ambiguous_crossing_gets_row_and_call`, `test_watch_ambiguous_off_restores_skip`,
  `test_ambiguous_row_peak_none`, `test_ambiguous_request_never_adopts_resolved_member` (entry 30 s after an ambiguous
  primary on the same event opens its own request, call and vision term), `test_ambiguous_primary_late_joiner_no_double_term`
  (B1 repro: ambiguous A, entry B folds in, entry C late → one entry term), `test_vision_direction_parsed_and_unclear_default`,
  `test_direction_fields_optional_never_change_outcome` (missing, null, out-of-enum `direction` / `direction_confidence`
  → same `outcome` and `people_count`), `test_direction_confidence_recorded`, `test_direction_agreement_cases` (5),
  `test_g3_amend_once_per_crossing_key` (incl. a late joiner, both through `_amend_vision_direction`),
  `test_g3_source_ref_from_bus_fields`, `test_g3_never_sets_direction`, `test_amend_failure_counted_never_raises`,
  `test_amended_signal_ignored_by_exit_backfill_readers`, `test_repeat_selection_stable_across_processes` (sha1),
  `test_repeat_never_spends_primary_cap` (full primary cap at rate 0 and at 0.2: identical primary outcomes and terms),
  `test_repeat_waits_for_free_slot_never_busies_primary`, `test_repeat_row_identity_and_readers` (node prefix,
  `call_kind`, excluded from trip-wires and rehydrate), `test_repeat_task_cancelled_on_teardown`,
  `test_ambiguous_member_in_cluster_no_term_under_tracker`, `test_ambiguous_no_arrival_record_before_flip`,
  `test_direction_zero_pages_once`, `test_ambiguous_zero_counts_bus_events`, `test_pipeline_version_on_every_row`,
  `test_inv_dir_gate_metamorphic` (production path `_on_egress_event` → stubbed llmvision reply → term → real
  `CrossingLedger`; outcome, counts and event ids fixed; permutes `vision_direction` / confidence over valid, invalid
  and missing values, and toggles repeats on / off; generator includes ambiguous primaries, late joiners and the
  no-request paths; term stream, every `L`, arrival records identical under `tracker`), layer guard green with the
  new row. Golden: every pre-existing row key (incl. `direction`) and the bus payload unchanged.
- **Mutation:** keep the old skip → `test_ambiguous_crossing_gets_row_and_call`; `prim_dir` from `members[0]` →
  `test_ambiguous_primary_late_joiner_no_double_term`; let an ambiguous request adopt a resolved member →
  `test_ambiguous_request_never_adopts_resolved_member`; make `direction` required → `test_direction_fields_optional_never_change_outcome`;
  pass `direction` into G3 → `test_g3_never_sets_direction`; read `vision_direction` at the member-dict build site under
  `tracker` → `test_inv_dir_gate_metamorphic`; count repeats in the primary cap → `test_repeat_never_spends_primary_cap`;
  `hash()` for selection → `test_repeat_selection_stable_across_processes`; drop the latch → `test_direction_zero_pages_once`.
- **Live:** within 1 day with crossings: ≥ 1 row with `direction = ambiguous` and a `vision_direction`; ≥ 1 `call_kind =
  repeat` row; `g3_calls` shows role `vision_direction`; `get_crossing(<source_ref>)` shows `vision_direction`; no
  ledger term on an ambiguous crossing; no `skipped_cap` primary on a day with repeats below the primary cap;
  Persons Entered / Exited Today unchanged in definition. Discriminates: a build that wrote direction into the record
  would move those counts and the `person_entry_exit_events.direction` of a disagreeing crossing; this one moves
  neither.

**P3-D4 one physical pass = one term or none (Tier 3; BUILD WAITS until a P3-D0d candidate passes and P3-D9a ships
it).** Why parked rather than built with collapse off: with every `pass_key` None the hold timer, the single release
site and the anchor block change no term, yet they add a timer, a new release path and an anchor-blocking condition
to the ledger (state machine × time, the riskiest ingredient class). Built when there is a key to collapse on. If K2
(right direction instead of collapse) passes P3-D0d, P3-D4 may not be needed at all; P3-D0d's audit says which. The
spec below is the build spec at that point; its `vision` branches apply per door group after P3-D7, and
`test_inv_dir_gate_metamorphic` already exists from P3-D3 and is extended with `pass_key` collisions.
1. Every member takes `pass_key` from the bus event (stamped by P3-D9a, which ships first); crossing vision computes
   none. `CROSSING_VISION_LEDGER_PASS_COLLAPSE` is True after the P3-D0d gate.
2. **One release site (reviews B3, M2 f; closure MEDIUM-1, -2).** `_release_terms(req)` is the only setter of
   `req.term_done` and the only builder of REQUEST terms; it replaces `_request_terms` (`crossing_vision.py:1073-1078`,
   today's setter at `:1077`), which is removed. The no-request paths (step 7) and the late joiner (step 4) still call
   `_ledger_terms` directly. It keeps today's set-before-apply order: `term_done = True` first, then the terms, so an
   exception in apply still counts as released. It fires at max(the request's outcome, E_primary + `CROSSING_VISION_TERM_HOLD_S`). Every
   path that sets `term_done` today (disabled at call time `:869-871`, cap `:873-876`, no clip `:878-882`, outcome
   `:928`, kill `:906`, the `finally` `:935-939`) records its outcome on the request and calls `_release_terms`, which
   applies the terms at once if the hold has elapsed, else leaves them for the hold timer. Members that join before
   release fold in (because `term_done` is still False).
3. **Hold timer.** Its own slot `req.unsub_hold` (not `req.unsub_timer`, which `_fire_request` clears); teardown cancels
   both and DROPS held terms (ledger is RAM; a restart boots `unknown`, so nothing a restart would keep is lost), counted
   `term_hold_dropped_teardown`. At release the gates are re-read: switch off / kill → no term, `_ledger_disabled()`
   (INV-OFF); ledger `unknown` → the term is recorded and not applied to `L`, as for any term while unknown (it is
   dropped from the ledger value, not deferred). `_prune_requests` (`:780-787`) never drops a request whose terms are
   unreleased, and `TERM_HOLD_S ≤ 2 × CLUSTER_S` is asserted at setup (110 ≤ 120). If the hold timer is lost (its
   callback raises, scheduling fails), the next `_prune_requests` or eval tick past the request's deadline (step 6)
   calls `_release_terms` itself, counted `term_hold_deadline_release`.
4. **Late joiner.** The `term_direction` rule is built in P3-D3 step 3 (review finding 1). P3-D4 adds only the pass
   clause: a member joining after release whose `pass_key` equals a member's of the request → no term (same pass,
   counted `late_member_same_pass`); otherwise P3-D3 step 3 applies.
4b. **Named residual:** a one-event round trip (Pass block) is one pass here: no term under `tracker`, one term in
   vision's direction under `vision` (P3-D7).
5. **Pass step in `cluster_terms`.** Group members by `pass_key` (None = its own pass). Per pass: under `tracker`, if
   its entry/exit members all share one direction → that direction; if mixed → no term (`pair_collapsed`, both
   directions and `n` recorded); under `vision` → vision's direction if the pass is the analysed one and vision says
   in/out, else the tracker rule. Then the existing rule over passes: one term with the primary's count if all
   resulting directions agree, else per-pass camera terms.
6. **Held terms block the anchor (review B2).** While any request has unreleased terms, the anchor predicate fails as if
   an entry term had arrived at E_primary (restarts `t_start`); so an anchor cannot fire between the bus event and
   release, and no held term becomes "late" through the hold (an anchor in the 10-200 s between E and the bus event can
   still make a term late, as today). The block is bounded by a deadline `E_primary + TERM_HOLD_S (110) +
   EVENT_END_WAIT_S (120) + TIMEOUT_S (90) = E + 320 s`; setup asserts it is ≥ the worst outcome bound
   `EGRESS_ENTRY_WINDOW_SECONDS (45) + EVENT_END_WAIT_S (120) + TIMEOUT_S (90) = E + 255 s`; past it the block lapses and the request is force-released,
   counted `anchor_block_deadline_expired`. Held terms do NOT block the stuck-ledger sample (`entry_blocks=False`,
   `crossing_ledger.py:491`): `crossing_ledger_stuck` judges released terms only, so a hold never suppresses that page.
7. **No-request paths (review M2 b).** These apply terms immediately, outside the hold, and never collapse; each is
   counted `collapse_skipped_<path>` (both cap / busy members of one pass keep camera terms +n_entry −n_exit, which need
   not net 0 when their camera peaks differ; P3-D0 (a) measures the busy-collision rate): `no_frigate_event` (`:676-679`, `pass_key` None anyway), primary left the ring
   (`:681-690`, a late member), `skipped_cap` / `skipped_busy` (`:693-703`), disabled (`:620-622`, no term at all).
   Accepted residual: a pass whose members both hit cap or busy keeps two terms; the cap is sized so this is rare
   (P3-D5) and the counter shows it.
8. **INV-P2-ONCE effect of collapse under `tracker` (review B6), named, not term-neutral.** Today a collapsed pass gives
   +n and −n: `L` nets 0, but the entry may consume an arrival credit and the exit is stored to cancel a departure
   reconcile. After collapse neither happens. Worked examples (start `L = R = 2`):
   - **W9 resident B walks out, the pass emits exit + entry:** today exit −1 (`L = 1`, stored), entry +1 (`L = 2`),
     departure edge R 2 → 1, the reconcile consumes the stored exit (cancel): `L = 2`, `guest_vis 1` until the anchor.
     Collapsed: no terms (`L = 2`); the reconcile finds no applied exit and lowers `L` to 1: `guest_vis 0`. Change: the
     phantom guest goes; one more reconcile is counted (bar a2 load rises).
   - **W10 resident C arrives, the pass emits entry + exit (ordering: the R edge lands before the terms; with terms
     first, today also ends `L = 3`):** today edge R 2 → 3 lifts `L = 3` with a credit; the entry
     consumes it, the exit −1 → `L = 2`: `guest_vis 0` but `L` one low, so the next guest is absorbed until the anchor.
     Collapsed: lift `L = 3`, the credit expires, the lift stays: `guest_vis 0`, `L` right.
   - **W11 guest arrives, pass emits entry + exit:** today +1 −1 = 0; collapsed: no term = 0. Same value (guest missed,
     safe direction), no credit consumed.
   So collapse changes which reconciles and credits fire and removes W9's phantom; INV-P2-ONCE still holds (each person
   counted at most once). Tests below pin W9-W11.
- **Tests:** `test_same_pass_opposite_pair_no_term_under_tracker`, `test_same_pass_one_term_under_vision`,
  `test_triple_exit_entry_exit_one_pass`, `test_round_trip_distinct_own_camera_events_keeps_two_terms` (two events on one
  door group with distinct ids inside ± 10 s, so the group-wide pick cannot mask it), `test_none_pass_key_never_collapses`,
  `test_term_hold_collects_member_that_resolves_45s_later`, `test_single_release_site_sets_term_done`,
  `test_late_vision_after_hold_releases_once`, `test_term_hold_teardown_drops_counted`,
  `test_release_rereads_switch_off_no_term`, `test_release_while_unknown_not_applied`, `test_anchor_waits_for_held_term`,
  `test_unreleased_request_not_pruned`, `test_ambiguous_primary_late_joiner_no_double_term`,
  `test_late_member_same_pass_no_term`, `test_no_request_paths_counted_no_collapse`,
  `test_w9_walk_out_pass_no_phantom`, `test_w10_arrival_pass_lift_stays`, `test_w11_guest_pass_zero`,
  `test_collapse_off_byte_identical_terms`, `test_inv_dir_gate_metamorphic` (drives the production path:
  `_on_egress_event` → stubbed llmvision reply → release → real `CrossingLedger`; holds outcome, counts and event ids
  fixed, permutes only `vision_direction`; generator includes `pass_key` collisions, ambiguous primaries, no-request
  paths and late joiners; asserts the term stream and every `L` identical under `tracker`), config extremes
  `test_term_hold_zero_is_pre_phase3`, `test_cluster_s_zero_no_pass`, `test_term_hold_above_two_cluster_rejected`.
- **Mutation:** key the pass on `_match_event`'s pick → `test_round_trip_distinct_own_camera_events_keeps_two_terms`;
  read `vision_direction` under `tracker` (at the release site) → `test_inv_dir_gate_metamorphic`; drop the hold →
  `test_term_hold_collects_member_that_resolves_45s_later`; drop the anchor block → `test_anchor_waits_for_held_term`;
  `prim_dir` from `members[0]` → `test_ambiguous_primary_late_joiner_no_double_term`.
- **Live:** ≥ 1 `crossing_vision_ledger` row of kind `pair_collapsed` within 2 days of crossings, every one with both
  members' `pass_key` equal. Discriminates: a group-pick or time-only collapse would show `pair_collapsed` rows whose
  members' own pass events differ.

**P3-D5 daily cap from measured volume; counter survives restarts (Tier 2-DB: a new `database.py` read).**
1. Default `CROSSING_VISION_DAILY_CALLS` = ceil(max daily simulated calls over 14 days from P3-D0 (a) ×
   `CROSSING_VISION_CAP_HEADROOM` (1.5)), ≤ `CROSSING_VISION_DAILY_CALLS_MAX` (200): measured 62 → 93. Cost on Luna is
   trivial, so the cap is a runaway guard. An operator-set Number value wins over the new default.
2. NEW DAO `count_memory_episodes_by_type_ended_between(episode_type, start_utc_iso, end_utc_iso, attr_outcomes)` →
   `(count, ok)`: `SELECT COUNT(*) FROM memory_episodes WHERE episode_type = ? AND ended_at >= ? AND ended_at < ? AND
   json_extract(attrs_json, '$.outcome') IN (?, ?, ?, ?, ?, ?)` (column `attrs_json` TEXT, `database.py:2010`;
   `json_extract` precedent `:8438`) over the call outcomes `ok`, `blank`, `error`, `timeout`, `unparseable`, `refused`,
   by `ended_at`, which is written at the outcome (`crossing_vision.py:1012`), i.e. by call time, not crossing time
   `started_at`. Bounds: the local day of `_roll_day` (`:491-500`) converted to UTC and rendered with
   `datetime.isoformat()` on an aware UTC datetime with microseconds, the same shape the writer produces
   (`dt_util.utcnow().isoformat()`, `+00:00` suffix), so the lexical compare is exact. Read path: a read connection
   like the other memory readers, never the `_write_queue`. Unlike the existing memory DAOs (which swallow errors via
   `_mem_dao_warn`, `database.py:11077`, and return `[]`), it returns `ok = False` on any error. Index:
   `idx_episodes_node_type (node_id, episode_type, started_at)` (`:2013-2014`) does not cover it; if P3-D0 (a) shows
   `memory_episodes` > `CROSSING_VISION_CAP_REHYDRATE_INDEX_ROWS` (200 000) rows, the build adds
   `CREATE INDEX IF NOT EXISTS idx_episodes_type_ended ON memory_episodes(episode_type, ended_at)` to the same
   `_create_table_safe` statement list as the existing index (idempotent at every setup, no versioned migration);
   below that a once-per-setup scan is accepted.
3. **Setup order (review B7).** The bus listener registers immediately with the counter at the cap sentinel (no calls,
   crossings still recorded as `skipped_cap`). A tracked background task runs the DAO with a timeout
   `CROSSING_VISION_CAP_REHYDRATE_TIMEOUT_S` (30) and one retry after `CROSSING_VISION_CAP_REHYDRATE_RETRY_S` (60); on
   success the counter = the count; on a second failure the counter stays at the cap until the next local midnight,
   counted `cap_rehydrate_failed` and paged LOW. Teardown cancels the task. Why rehydrate: the restart-storm history
   (memory `project_reload_storm_refuted_restart_storm_live`) turns a RAM cap into no cap.
4. Residual: rows still in the write queue at a restart and calls in flight are not counted; bound ≤
   `MAX_CONCURRENT` + the queue's unflushed crossing rows per restart. Also not counted (build reviews A2, D-L2):
   call rows whose `log_memory_episode` write failed (swallowed, WARNING only), a call that returned but raised in
   `_run` before `_record`, and calls in flight at stop that the teardown gather cancels (billed, no row; ≤
   `MAX_CONCURRENT` per restart).
- **Tests:** `test_cap_counter_rehydrated_from_today_rows`, `test_rehydrate_counts_by_ended_at_not_started_at`,
  `test_rehydrate_ignores_yesterday_and_non_call_rows`, `test_rehydrate_slow_db_no_calls_until_done`,
  `test_rehydrate_error_retries_once_then_cap`, `test_dao_reports_error_distinct_from_empty`,
  `test_cap_holds_across_simulated_restart`; DB tests on the production schema.
- **Mutation:** skip the rehydrate → `test_cap_holds_across_simulated_restart`; return `[]`-style success on error →
  `test_dao_reports_error_distinct_from_empty`.
- **Live:** after the deploy restart, `crossing_vision_today.calls` equals the count of today's call rows within one
  minute (not 0). Discriminates: a RAM-only counter reads 0 after the restart.
- **Status:** BUILT on `feature/crossing-p3-first` (48d4bc94, review fix-ups 9992f3f3); default cap 93 from P3-D0 (a)
  (3925c18f); no index (18,855 rows < 200,000).

**P3-D6 direction scoring, every source scored the same way (Tier 2, read-only; lands in the D4 / P2-D6 scorer build
and P2-D10 grading, neither built yet).** Sources scored side by side on the same crossings: the tracker, vision
(P3-D3, primaries only, plus the repeat rows), and any P3-D0b instrument (I1 track vs door, I2 zone order once threshold
zones exist, I3 contact order), computed offline by the scorer from the same Frigate events, so a non-LLM source
earns its own verdict on production volume, not only on 17 clips. Oracles, strongest first: operator grade (P2-D10
grade actions gain `_in` / `_out` / `_pass`); a named resident's `person.*` edge, not_home → home in [E −
`CROSSING_VISION_DIRECTION_ORACLE_BEFORE_S` (300), E + `_AFTER_S` (60)] = in, home → not_home in [E − 60, E + 300] =
out, with a name attached by F3 or the NVR on that crossing; the P3-D0 fixture. Interior-camera timing is the
tracker's own input and never an oracle. **The oracle never scores groups or guests:** the bar measures
single-resident crossings; group direction stays unmeasured until graded group crossings exist. Scored per crossing
primary until a pass key exists, then per PASS (review B12: a pass contributes one scored row); `member_inherited`
members and repeat rows are excluded from accuracy (review finding 13b). Reports per door group AND day / night,
with n per cell (no confidence or day/night cell is read below n = 10). Counts: exact rate and signed net error per
group visit (entry n − exit n), per door group (review finding 8).
**Bar (operator 2026-11-15 "Is the bar right?"; chosen and why).** Two failures, two measures, judged PER DOOR GROUP so
a door that works can flip before one that does not (the cameras, angles and the tracker's interior neighbours differ
per door; one house-wide number hides a good door behind a bad one):
- **Accuracy (wrong):** Wilson 95 % lower bound of accuracy on oracle-scored crossings ≥
  `CROSSING_VISION_DIRECTION_ACC_LB_MIN` (0.90) over ≥ `CROSSING_VISION_DIRECTION_SCORED_MIN_N` (30) in that door
  group, AND right on ≥ `CROSSING_VISION_DIRECTION_DISAGREE_WIN_MIN` (0.80) of ≥ `_DISAGREE_MIN_N` (15) scored
  crossings where it and the tracker disagree. The 0.90 bound is right for changing a census term: a wrong sign moves
  `L` by `n` until the next anchor.
- **Stability (flips on identical input):** repeat-call agreement (same `in` / `out` / other class on the P3-D3 step 8
  repeat) with a Wilson 95 % lower bound ≥ `CROSSING_VISION_DIRECTION_REPEAT_AGREE_LB_MIN` (0.80) over ≥
  `CROSSING_VISION_DIRECTION_REPEAT_MIN_N` (20) repeats in the door group. Needs no oracle, so it accrues on every
  sampled crossing, groups and guests included. Why separate: a model can be right on average and still flip on one
  clip; a flipping source makes a term's sign depend on which call you happened to make. Deterministic sources (tracker,
  P3-D0b instruments) pass it by construction.
- **Confidence is recorded, not gated:** model self-reported confidence is uncalibrated; the scorer reports accuracy
  per confidence level, and if `high` is reliably better it can become a per-crossing filter in a later reviewed change.
- Baseline (P3-D0 run 2): 13/17 overall (76 %), 3/6 tracker-wrong. Run-to-run 16/17 same direction, but runs 1 and 2
  differed in `max_tokens` (1500 / 4000), so that is not a repeat-call measurement; true repeat agreement is unmeasured.
  At 76 % the accuracy bound never reaches 0.90; it needs the true rate near 95 %+.
**Reps from production, per door group, in days.** ~62 crossings on the busiest day (P3-D0 (a)), 5-12 oracle-scored a
day house-wide (≤ 5 grades plus named resident edges at ≈ 44 % attach). The split is NOT even (review finding 16): 15
of the 17 readable fixture clips and all 6 tracker-wrong ones are front-door, and all 4 vision misses are front (11/15,
73 %); the garage is 2/2, too few to say. The scorer uses the measured per-group volume; the front door is expected to
be the binding group, the garage the slow one. As a guide, at ≈ 3-6 scored a day in a group: N ≥ 30 in 5-10 days;
≥ 15 disagreements (≈ 35 % of scored) in 7-15 days; the 0.90 lower bound in ≈ 10-20 days at 97 % true accuracy
(≈ 60 scored), ≈ 25-50 days at 95 % (≈ 150), never below ≈ 92 %; and at the measured front-door 73 % the Wilson UPPER
bound falls below 0.90 at about n ≈ 35-45, so PARK can be called in ≈ 1-2 weeks rather than riding. Stability at 0.2
sampling (≤ 15 repeats a day house-wide): the 0.80 lower bound at n = 20 needs 20/20 (19/20 gives ≈ 0.76), so 20
repeats (≈ 4-7 days in the front group) suffices only with zero disagreements; at 95 % true agreement it needs about
35-40 repeats (≈ 1-2 weeks). Raising `CROSSING_VISION_GRADE_DAILY_N` during the measurement shortens the accuracy
clock most.
Disposition `AUDIT_crossing_direction_disposition_<date>.md`, per source and door group:
- **vision:** FLIP-READY (accuracy AND stability bars met) / HOLD (bar named, scored crossings still needed at the
  measured rate) / PARK, sized by error (review finding 11): the accuracy Wilson 95 % UPPER bound is below 0.90 at ≥
  `CROSSING_VISION_DIRECTION_SCORED_MIN_N` (30) scored in that door group, or the stability upper bound is below 0.80
  at ≥ `CROSSING_VISION_DIRECTION_REPEAT_MIN_N` (20) repeats; `CROSSING_VISION_DIRECTION_PARK_N` (150) stays as a hard
  stop (HOLD never runs past 150 scored).
- **tracker:** TRACKER-READY (accuracy bar met; stability trivially) / TRACKER-BELOW-BAR. Today 11/17 (65 %).
- **P3-D0b instrument:** INSTRUMENT-READY on the same accuracy bar → feeds P3-D9c.
The census F-LEAD needs FLIP-READY or TRACKER-READY for the source the ledger uses in that door group.
- **Acceptance:** a scorer run on ≥ 1 day of Phase 3 rows writes every number above per door group and reproduces the
  fixture's 11/17 tracker accuracy on the 11-14 clips.

**P3-D7 vision direction leads the ledger, per door group (Tier 3, gated; operator checkpoint).** A reviewed change
of `CONF_CROSSING_VISION_LEDGER_DIRECTION_SOURCE` (rung 2, review finding 7: an options-flow map, one select per
door group, default `tracker`; keyed by the `CONF_DOOR_GROUPS` group key, an ungrouped stem keyed `stem:<stem>` as
`crossing_vision.py:646` builds `group_key`; a missing key reads `tracker`, so a new install or a new door is safe
and nothing is keyed by this house's names) to `vision` for a door group whose P3-D6 disposition is FLIP-READY; the
change is still a checkpointed operator decision. Substitution site: the ONE member-dict build at
`crossing_vision.py:658-661`, before `cluster_terms` (the ledger is direction-blind except `m["direction"]`), which
also threads `group_key` onto the member; it is the INV-DIR-GATE mutation target; bumps `pipeline_version`; operator checkpoint before
deploy. Under `vision` the term takes `vision_direction` when `in` / `out`, else the tracker's; an ambiguous crossing
gets a term when vision says `in` / `out`. Post-flip trip-wire: the rolling `GO_REGRESSION_DAYS` (14) accuracy or
stability bar below threshold in that door group → NM "revert vision direction". Named residual: a round trip merged
under one pass becomes one term in vision's direction, `L` off by one until the anchor. If a P3-D0b instrument is
INSTRUMENT-READY first, P3-D9c (tracker) is preferred over P3-D7, because it fixes every reader, not only the ledger.
- **Tests:** `test_direction_source_vision_uses_vision_direction`, `test_direction_source_per_door_group`,
  `test_vision_unclear_falls_back_to_tracker`, `test_ambiguous_with_vision_in_gets_entry_term`,
  `test_repeat_row_never_term_after_flip`, `test_direction_regression_pages_revert`.
- **Live:** after the flip, ≥ 1 term row with `direction_source = vision` on a `direction_agreement = disagree`
  crossing in the flipped door group whose sign follows vision, and none in an unflipped group.

**P3-D8 the anchor honours the room's stuck exclusion (Tier 2; harmonization C1; BUILT on `feature/crossing-p3-first`
48d4bc94 + 3ee33775 (the P22 gate fails closed when house state is unknown); operator APPROVED 2026-11-15 ("Door vision stuck sensor - yes"); sequenced before P3-D3).** Why: the ledger has never been `known` since boot; the held set on an AWAY
house is mostly inputs the rooms have already excluded as stuck (media room Matter radar on 18 h, excluded by the room
at 4 h; the flapping Meross bit), so bars a and e, F-LEAD and every census use of P3-D3 / P3-D4 cannot fire.
`_held_inputs` (`crossing_vision.py:1110-1177`) reads raw `hass.states` and ignores the room's exclusion.
1. **Source: the room's real exclusion set, not the label map (final review H1).** `get_stuck_sensor_kinds()`
   (`coordinator.py:1942`) is a LABEL map: a duty-cycle hit is labelled but deliberately NOT excluded, because a
   sleeping person reads ~100 % mmWave duty cycle (`coordinator.py:3801-3808`; exclusion only after
   `_promote_dutycycle_to_exclusion`, `:3813`), and chatter is labelled in shadow mode without promotion (`:3073-3084`).
   P3-D8 never reads it. It reads the room's `SensorExclusionSet` narrowed to the stuck clients
   `CROSSING_VISION_ANCHOR_STUCK_CLIENTS` = {`p22_continuous` (`:3762`), `chatter` (promoted only in act mode, `:3076`),
   `stuck_dutycycle` (promoted, `:3830`)}; never `CAMERA_STREAM_EXCLUSION_CLIENT` (`:2626`, a dead stream) or any other
   client. Build: a NEW room getter `camera_input_room_stuck_excluded(input_eid)` beside
   `camera_input_room_quarantined` (`coordinator.py:2790-2796`), returning True iff
   `self._exclusion_set.clients_for(input_eid)` (`domain_coordinators/sensor_exclusion.py:145`) intersects the stuck
   clients, else None; and a module wrapper `input_room_stuck_excluded(hass, eid)` beside `input_room_quarantined`
   (`camera_stream_health.py:1235-1242`) using the existing `_ask` room sweep (`:1091-1103`, over
   `_room_coordinators`, the same coordinator set `aggregation._get_room_coordinators` gives `sensor.py:5724`).
   `crossing_vision` calls the wrapper through its existing `_csh` import; no new access path. Guard delta: 0 rows
   expected (the guard has no `crossing_vision` → room-coordinator rule; the build confirms).
2. **Dead vs stuck-excluded, explicit.** `_held_inputs` already has each input's state and stream view
   (`crossing_vision.py:1170-1176`). P3-D8 applies only when `state == "on"` AND the stream view is None AND
   `input_room_stuck_excluded` is True: that input does not hold. Dead = `unavailable` / `unknown` / missing / a non-None
   stream view; the operator rule "a dead camera/sensor is faulty equipment ... hold, never release" covers it and P3-D8
   does not change it: a dead input holds (last known-good `on`, or no known-good reading) even when it is also
   stuck-excluded. A duty-cycle-labelled but unpromoted sensor (a sleeper) and a shadow-chatter sensor still hold. Kill
   switch `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK` (rung 1, True, operator approved 2026-11-15; False = today's rule).
   Ignored inputs are listed on the ledger diagnostics as `held_ignored_stuck` (+ count).
3. The `crossing_ledger_anchor_zero` page keeps naming holders and also lists `held_ignored_stuck`.
- **Tests:** `test_stuck_excluded_on_input_does_not_hold` (p22 client), `test_act_chatter_excluded_does_not_hold`,
  `test_dutycycle_label_without_exclusion_still_holds`, `test_shadow_chatter_still_holds`,
  `test_dead_input_still_holds_even_if_stuck_excluded`, `test_camera_stream_client_only_still_holds`,
  `test_stuck_getter_failure_keeps_holding`, `test_ignores_stuck_kill_switch_restores_rule`,
  `test_held_ignored_stuck_listed`.
- **Mutation:** read `get_stuck_sensor_kinds()` instead of the exclusion set → `test_dutycycle_label_without_exclusion_still_holds`
  and `test_shadow_chatter_still_holds` RED; drop the dead check (let dead + excluded release) →
  `test_dead_input_still_holds_even_if_stuck_excluded` RED; widen to any client (`camera_input_room_quarantined`) →
  `test_camera_stream_client_only_still_holds` RED; drop the exclusion read → `test_stuck_excluded_on_input_does_not_hold` RED.
- **Live:** with the media room radar promoted `p22_continuous` and the house AWAY, `crossing_ledger.held` no longer
  lists it, `held_ignored_stuck` does, and the first anchor fires within `LEDGER_EMPTY_RESET_S` + one eval once no
  other holder remains; any duty-cycle-labelled bedroom sensor stays in `held`. Discriminates: the label-map bug would
  also drop sleeping-bedroom sensors from `held`.

**P3-D8 prerequisites (review D/G of 48d4bc94: G-1, G-2, D-M1; plan `PLANNING_stuck_sensor_truth.md` S1-S3).** P3-D8
alone would not have produced an anchor on 11-15 for either live case. Three prerequisites, sequenced before P3-D3:
- **S1 (K2, Tier 2-DB, operator approved):** a P22 off pulse shorter than `STUCK_P22_OFF_GAP_TOLERANCE_S` (10 s) does not
  restart the 4 h clock (motion-class inputs), so the upguest ZV stays P22-excluded (G-1).
- **P3-D8b = S2 (EDGE, Tier 2, built on this branch, reviewed with P3-D8):** `_on_substrate_edge` drops a (room, kind)
  rising edge when every `on` input of that kind is a live input its room stuck-excludes (same client set, dead inputs
  still count). The substrate keeps ignoring room exclusions (STEP-EXCLUDE-4); policy lives in this consumer (G-2).
  D-M1 default taken: a `p22_continuous`-only exclusion is not honoured, for levels or edges, in SLEEP, WAKING or
  HOME_NIGHT (one rule in the room getter `camera_input_room_stuck_excluded`, `_d2_house_state_allows`; knob
  `CROSSING_VISION_ANCHOR_P22_SLEEP_GATE`).
- **S3a + S3b (MEDIA, Tier 2 each):** chatter has never acted (the select writes the integration entry, rooms read the
  CM entry; card CHATTER-MODE-SELECT-NOT-WIRED-1), so S3a wires the room resolver to the select's entry (operator Q-A:
  act house-wide, recommended); S3b resolves the registry `model` `ms600-un` to the radar family. Order: S3b before S1.
- **Same-run rule (P3-D8 + P3-D8b):** an exclusion releases a level or drops an edge only for the run it was computed on;
  a new rising edge after an off always counts; an input listed by two rooms is stuck only if both say so; the sleep-state
  read fails closed.
Invariants, knobs, tests and Live criteria: that plan (rev 2). Seam: S1 changes `_sensor_on_since`, which P3-D8 consumes through
the `p22_continuous` client (seam, not merge).

**P3-D9 EGRESS-TRACKER-DIRECTION-1: direction and the pass key at the source (Tier 3; P3-D9c is now P3-D11, below;
harmonization C5, review G1).** After P3-D0 this card carries the direction fix itself, not only the pass dedup: the
F3 owner is the only place a direction fix reaches every reader in time. Three steps, each gated by a probe:
- **P3-D9c better direction at resolution (MERGED 2026-11-15 into P3-D11, the extended tracker: the text below is its direction input list; P3-D11 is the build spec).** `_resolve_direction`
  decides with the P3-D0b instrument that passed (I1 track vs door, I3 contact order, an I4 interior-timing variant,
  or the I5 combination), falling back to today's interior-timing rule when the instrument abstains. Inputs come from
  a tracker-owned Frigate person-event ring (`register_frigate_consumer`, `frigate_ingress.py:582`; the same ring
  P3-D9a needs) holding each door event's track (`path_data`, zones) and from registry-resolved door contacts; the
  door references are configuration the operator owns (Frigate threshold zones for I2, or a per-camera door polygon:
  the plan decides which rung after P3-D0b, preferring Frigate-side zones so URA stores no geometry). It changes
  every synchronous reader's input (notify, census egress-face union, entered / exited, DB, perimeter, sightings, the
  ledger) at once, so its plan names each reader's change, keeps the bus and DB shape (a new additive key
  `direction_source`), adds a zero-fire trip-wire for the instrument (decided-share below a floor over 24 h of
  crossings → page), and reads `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` completely. Its runtime bar is P3-D6
  TRACKER-READY, scored before and after by `pipeline_version`. A right direction also merges twin passes, but only
  within the 30 s same-direction source dedup on a configured door group for every reader, and within the 60 s
  cluster for the ledger (P3-D0d K2 measures both shares).
- **P3-D9a pass-key producer (PARKED until a P3-D0d candidate passes; then before P3-D4; additive, byte-identical for
  every existing reader).** At resolution `_resolve_direction` computes `pass_identity(...)` with the P3-D0d candidate
  that passed, from the same tracker-owned ring (and the contact cycle for K1), and stamps `pass_key` on the new
  `CrossingRecord` (creation-time field) and as an additive bus key, beside `peak_person_count`. Golden test: every
  pre-existing bus key and DB column unchanged. Lifecycle: the tracker's `register_frigate_consumer` (its first Frigate
  consumer) is unsubscribed in the tracker's teardown; the ring keeps `CROSSING_VISION_TRACKER_FRIGATE_RING` events
  per Frigate camera, pruned by count and age on every append. Tests `test_tracker_frigate_consumer_unsubscribed_on_teardown`,
  `test_tracker_frigate_ring_bounded`, `test_pass_key_on_bus_and_record`. Guard delta: 0 rows expected (a consumer
  registration inside the F3 owner; the build confirms). Why parked: P3-D0 (d) showed the event-window key fails on
  mechanism, so stamping it would publish a value known to be wrong; if K2 passes, no key is needed.
- **P3-D9b pass-level dedup (after P3-D4; gated on P3-D0d PASS including the round-trip merge bound).** The
  direction-keyed dedup (`transit_validator.py:2425-2438`) gains a pass check, with `pass_identity` computed BEFORE the
  dedup block (the dedup `return` is at `:2428-2434`; P3-D9a's stamp at record creation `:2515` is too late for it): a
  crossing whose `pass_key` equals that of a crossing already resolved on the same door group inside
  `DOOR_STEM_DEDUP_S` is not emitted again, whatever its direction. That fixes "one pass emits both" for every reader.
  It does not choose which label is right (P3-D9c does). Named residual: a round trip the key merges loses its
  re-entry for every reader. Baseline: the P3-D0 (a)/(d) numbers and the P3-D6 tracker verdict.
The card's own Tier-3 plan covers all three. Until P3-D9a ships, `pass_key` is None everywhere and P3-D4 collapses
nothing; until P3-D9c ships, every reader keeps today's direction.

**P3-D10 and P3-D11: two operator direction designs (added 2026-11-15; both measurement-first, both behind
INV-DIR-GATE).** Operator, 2026-11-15, verbatim: "Arriving: when we detect a door crossing we can go back in history
and get clips of the approach inside and outside the house. Alternatively we can treat motion near an egress door as
an anticipatory crossing and collect clips from/frames to check if it was a crossing. If it a crossing we look to
determine direction and if not discard". Starting point: every direction instrument so far scored 13-14 of 17 against
an agent-made answer key (vision run 2 13/17; I1 v2 10/17; I6 5/17; ensemble R1 14/17;
`AUDIT_crossing_vision_p3_d0bcd_2026_11_15.md`), and at least two labels (21:42:22, 15:12:14) are doubtful. So the
truth changes first: **every new instrument is scored ONLY against operator labels**
(`quality/tests/fixtures/crossing_operator_grades.json`, written by `scripts/grading/pull_grades.py` from the
CROSSING-GRADING-PAGE-1 batch; the file does not exist yet on develop), never the agent key. The gates below are the
P3-D0b numbers re-expressed as shares so they survive a changed readable count: right on ≥ 0.88 of operator-readable
clips (15/17), ≥ 0.83 of the tracker-wrong ones (5/6), deciding ≥ 0.50 of the 101 crossings of 11-14 on its own.
Both deliverables produce F3 ATTRIBUTES or tracker INPUTS only; neither creates a crossing record.

*Institutional context verified (P3-D10 / P3-D11; greps re-run on develop 77414215, `custom_components/` +
`docs/planning/*.md`):*

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Recording pull of any camera around E | REUSED | HA Frigate proxy `/api/frigate/<inst>/recording/<cam>/start/<s>/end/<e>` (§0 row; P3-D0c: 14 of 14 calls 200, ~11 s, long events included). P3-D2 already resolves `<cam>` from the event payload and `<inst>` from `discover_frigate_instance_ids` (`crossing_vision.py:543-548`, `:562`), never from an entity id |
| Approach-camera set (outside) | REUSED graph, NEW reader | `EXTERIOR_ADJACENCY_GRAPH` `const.py:3026` (Frigate camera names; symmetrised and optionally replaced from `exterior_seams.json` by `ExteriorTrackLinker`, `exterior_track_linker.py:232`, `:443`; `exterior_seams.py:55`, `:371`). Keys are ratified config, not a guess; the door-group camera's Frigate name is reached from the registry (entity `platform == frigate`, its `unique_id`/device), never from the stem string. Portability: an install without a seam file has no graph, so P3-D10 then uses the door group only (named residual) |
| Door-group cameras + interior neighbours | REUSED (G5) | `door_group_members` `transit_validator.py:1545`, `door_entry_entities` `:1308`, `door_neighbours_for_stem` `:1317` (`CONF_DOOR_GROUPS` `const.py:3395`, `CONF_DOOR_INTERIOR_NEIGHBOURS` `:3399`); interior cameras near a door `_get_interior_cameras_near` `:2981` |
| Interior path map | REUSED, read only | `async_setup_path_map` (`__init__.py:3476`), status `path_map_status` (`sensor.py:4667`); `FIXTURE_camera_paths_interior.md`. Supplies "nearest inside camera" when `CONF_DOOR_INTERIOR_NEIGHBOURS` is empty |
| Tracker direction windows | REUSED rule, unchanged | `_resolve_direction` `transit_validator.py:2373`; interior event in [0, 45 s] after E = entry, [−30 s, 0) = exit, nearest wins (`:2401-2423`; `EGRESS_ENTRY_WINDOW_SECONDS` 45, `EGRESS_EXIT_WINDOW_SECONDS` 30, `const.py:3381-3382`); direction-keyed dedup 30 s (`:2425-2438`) |
| Fast stage (Frigate event START trigger) | REUSED design, not built | P2-D8 (this plan; `CROSSING_VISION_FAST_STAGE_ENABLED` False); shares `analyze_crossing_images` with interior D5; G8 rule: a non-B stage writes provisional rows only, never a term (`CONTRACT_person_awareness_layer.md:367`) |
| B-stage chains | ADJACENT, not reused | Moved to `PLANNING_vision_interior_sightings.md` D5 (`:712`): interior hop chains after a crossing, pulled from the crossing ring (`:95`, no new listener). P3-D10's inside leg is ONE camera around E, not a chain; if D5 ships first, P3-D10 reads its first hop instead of pulling again (seam, not merge) |
| Frigate person-event ring in the tracker | REUSED plan | `register_frigate_consumer` `frigate_ingress.py:582`; ring `CROSSING_VISION_TRACKER_FRIGATE_RING` (P3-D9a / P3-D9c, not built) |
| Door contacts / egress-zone motion as a trigger | NEW reader of existing entities | Tracker reads no contact (0 hits); egress trigger is the egress camera's person state (`_on_egress_state_change` `transit_validator.py:1628`). Front group: no registry-mapped contact ever opened in the P3-D0b window (`AUDIT_crossing_vision_p3_d0bcd_2026_11_15.md:155`; the Elk zone mapping is by name and is a sensitivity only). Per-room `CONF_DOOR_SENSORS` (`const.py:1111`) exists but is room-scoped, not door-group-scoped |
| Single F3 ingest | CONSTRAINT | `CONTRACT_person_awareness_layer.md:124`: ONE ingest point, `_resolve_direction` → `_record_crossing` + bus fire; amendments only through G3 `attach_crossing_attribute` (`:362`, `transit_validator.py:1232`) |
| Knob names `CROSSING_DIRECTION_APPROACH_*`, `CROSSING_ANTICIPATORY_*` | NEW | 0 hits in `const.py` / plans before this edit |

A finding from the scan that changes the brief: the 26 % `no_frigate_event` at ±10 s is NOT crossings the tracker
missed. Every one of them is a crossing the tracker resolved and put on the bus; it is crossing vision that found no
Frigate person event on a door-group camera to match (`crossing_vision.py:675-679`, `OUTCOME_NO_EVENT`). On the
recording route (P3-D2, GO) the window [E − 5, E + 15] exists whether or not Frigate made an event, so the cheapest
recovery of those 26 % is a P3-D2 change (resolve the door-group camera from the registry and pull its window when no
event matches), not an anticipatory trigger. That lever is recorded as P3-D2 follow-up **P3-D2b** (Tier 2, after
P3-D2; measured inside P3-D0e step 4). Crossings the tracker misses entirely (the egress camera's person sensor never
fired) are a separate number nobody has measured; P3-D0f measures it.

**P3-D0e approach-clip probe (read-only; gates P3-D10; model calls ≤ `CROSSING_DIRECTION_APPROACH_PROBE_CALLS` (60),
operator budget yes needed for the R-c leg only).** Question: does the ORDER of person presence across the outside
approach cameras and the nearest inside camera, read from the recordings themselves (not from Frigate events, the I6
failure), give the right direction? Steps:
0. **Retention first.** Frigate events reach back only ~13 days (from 11-02) and recording retention per camera is
   UNVERIFIED (it may be shorter, or motion-only, so a recording may not exist where no event did). Read each
   approach camera's record mode / retain from the Frigate config (read-only `/api/config` through the HA proxy) and
   download the windows for the graded clips at once into `.claude/tmp/` (gitignored) before they expire. A camera
   recording on `motion` only cannot see a still person: recorded as a named limit.
1. **Freeze the camera sets before any label is read** (bias control from P3-D0b): per door group, the outside
   approach set = the door-group cameras plus their `EXTERIOR_ADJACENCY_GRAPH` neighbours, the inside camera = the
   first `door_neighbours_for_stem` entry, else the nearest path-map camera. All resolved by registry; committed as
   `quality/tests/fixtures/crossing_approach_cameras.json` with the resolution trail (entity id → registry
   `platform` / `unique_id` → Frigate name).
2. **Windows:** each camera's recording [E − `_WINDOW_BEFORE_S` (30), E + `_WINDOW_AFTER_S` (30)].
3. **Three inference tiers, cheapest first, each scored on the operator-graded clips** (the 46 answer-key clips in
   batch g20261115-1716 that the operator marks readable, and separately the tracker-wrong ones):
   - **R-a Frigate's own stored records, 0 model calls, 0 frame work:** for every camera in the set, Frigate's
     per-object records over the window, including objects that never became a reviewable event (the stored event
     list with `has_clip` false, plus recording segments present / absent), not only event STARTS within 60 s as
     I6 did. Rule (frozen): first outside presence before the first inside presence = `in`, the reverse = `out`,
     overlap within `_ORDER_TIE_S` (3) = unclear.
   - **R-b a person detector on the window frames, 0 model calls.** Measurement may run offline on the laptop (a
     stock COCO person model at 2 fps; frame differencing as a weaker baseline). At runtime it uses only what any URA
     install can have: (i) Frigate's own tracked objects and stored detections (R-a; Frigate is required for camera
     features anyway); (ii) an OPTIONAL operator-configured HA-side detector selected in config
     (`CONF_CROSSING_DETECTOR_ENTITY`, an `image_processing` entity, rung 2; empty = R-a only), called with
     `image_processing.scan`, never hard-wired and never this house's homelab. Verified in HA core 2026.2.3 (the
     `.venv-ha` package): the `image_processing` domain exists; its core object-detection platforms are `doods`
     (needs a DOODS server the operator runs) and `sighthound` (cloud); `microsoft_face_*`, `openalpr_cloud`,
     `seven_segments` are not person detectors. No local in-process person detector ships in core that I could
     verify; an add-on endpoint would be reached through such an entity. Same rules on its output: the order rule and
     the G6 main-lens motion rule from the I1 v2 review, a thin door strip [(0.82,0.74),(1.0,0.74),(1.0,1.0),(0.88,1.0)],
     points with y < 0.74 ignored, x moving ≥ `_X_DISPLACEMENT` (0.15) toward the strip and ending inside or within
     0.05 = `in`, starting in the strip and ending ≥ 0.15 further left = `out`, else unclear; on front_door_aerial
     "toward / away from the mat centre" with a polygon frozen from a viewed snapshot in step 1. Hazards: lingering on
     the mat reads unclear; a step-out-and-back reads by its last move.
   - **R-c an LLM on a montage, one Luna call per clip:** 2 frames per camera in the set in time order on one sheet,
     asking only "first seen outside or inside, moving toward or away from the door"; ≤ 46 primaries plus ≤ 14 true
     repeats for stability.
4. **Coverage** on the 101 crossings of 11-14 for each tier on its own decisions, and the share of the 26 %
   `no_frigate_event` crossings where the door-group camera's recording shows a person in [E − 5, E + 15] (the P3-D2b
   number).
5. **Independence:** per-clip miss overlap with V (vision run 2), C (contact), I1 v2 and the tracker, re-scored on
   operator labels; an instrument whose misses sit on the same front `in` clips as V and C adds nothing (the ensemble
   lesson).
- **Gate:** the shares above on operator labels, deterministic (R-a, R-b; R-c reports repeat agreement against the
  P3-D6 stability bar), and errors not concentrated on V's misses. **Recommendation: build the cheapest tier that
  passes, in the order R-a, R-b (through the configured HA detector entity; installs without one keep R-a), R-c.**
  Operator 2026-11-15: a person detector is approved, delivered through an install-agnostic HA/Frigate route
  ("Why in homelab and not ha. That's not agnostic of operator."); URA itself still extracts no frames. R-c rides the existing P3-D3 primary call (approach
  frames added to the same request), so it costs no extra call; if it needs its own call, it gets its own budget.
- **Acceptance:** `AUDIT_crossing_approach_clips_<date>.md`: per tier right / tracker-wrong-right / coverage /
  determinism / overlap, the retention table, the P3-D2b share, the frozen fixture committed before scoring.
  Discriminates: an instrument that copies the tracker scores the tracker's own number on operator labels and 0 on
  the tracker-wrong set; one that copies vision misses V's clips.

**P3-D10 retroactive approach clips (Tier 2 to record; Tier 3 if it feeds the tracker; BUILD WAITS on P3-D0e PASS).**
On every crossing the tracker resolves (entry, exit or ambiguous), at E + `_WINDOW_AFTER_S` + `CROSSING_VISION_RECORDING_LAG_S`,
pull the frozen camera set's windows (or Frigate records for R-a) and compute `approach_direction` ∈ {`in`, `out`,
`unclear`} with the passing tier.
- **Output (F3 attribute, display class):** written through G3 `attach_crossing_attribute` with role
  `approach_direction`, fields `approach_direction`, `approach_direction_tier`, `approach_cameras_seen` (count only).
  It reaches the P3-D6 scorer and the awareness display. It reaches the ledger only as a source in
  `CONF_CROSSING_VISION_LEDGER_DIRECTION_SOURCE` (new value `approach`) after its own P3-D6 FLIP-READY at a checkpoint
  (P3-D7), and every reader only through P3-D9c (the tracker adopts it as its instrument), which is preferred: one fix
  for every reader.
- **Approach COUNT (operator 2026-11-15: where the vision extension of counting accuracy fits, "i.e. the before and
  after clips/frames").** The same windows also yield `approach_people_count`: for an entry, distinct people on the
  outside approach cameras before E plus the inside camera after E; for an exit, the inside camera before E plus the
  outside approach after E. Target: P3-D2's named residual, a group arriving over more than 20 s is undercounted by
  the [E − 5, E + 15] door window (P3-D0c: 16:23:52, a 48.7 s event, frames `[0,0,1,1,1,1,1]`; 18:59:36 still
  arriving). Same handling as direction: a G3 attribute attached after resolution (INV-TRACKER-LATENCY), scored in
  P3-D0e against the operator's graded counts, and reaching a ledger term only through the existing vision-count rule
  after its own P3-D6 scoring.
  **Combination rule against the door-window count (a hypothesis P3-D0e scores, frozen before scoring):** the term
  `n` = the door-window vision count, EXCEPT when the door count is ≥ `CROSSING_VISION_GROUP_PEAK_MIN` (3) or the
  matched door event is longer than the 20 s window: then `n` = max(door count, approach count). Why not a plain max:
  P3-D2 step 7 measured that max(vision, camera peak) fixes one clip and creates three over-counts (16:30:44 3 vs 2,
  16:20:48 3 vs 2, 16:23:52 4 vs 3), and vision's undercounts roughly cancel over a visit while over-counts do not.
  The gate restricts the max to the regime where the measured undercount lives (groups of 3+ and long events; 1-2
  people were exact on the door window), which excludes two of the three over-counts (both 2-person clips). Named
  risk: 16:23:52 is a long 3-person event and stays inside the gate, so P3-D0e must show the approach count is not
  over there. Gate: on graded 3+ crossings the rule's exact rate beats the door count alone, and it adds no
  over-count on graded 1-2 person crossings; else the approach count stays recorded only.
- **Producer check:** inputs are recordings of cameras whose Frigate events were sparse (front_side_ptz 21 events,
  utilities_ptz 7, ArmCrest none in 28 h, P3-D0bcd I6); recording coverage is what P3-D0e step 0 measures. Arithmetic:
  first-presence order and the displacement rule only.
- **Consumer check:** P3-D6 scorer (trust decision for the flip), awareness `last_crossing` (display), P3-D9c (if
  adopted). No other reader; `SIGNAL_EGRESS_RECORD_AMENDED` readers ignore the role (`sensor.py:5092`, `:5231`).
- **Fire check / trip-wire:** `crossing_direction_approach_zero`: ≥ `CROSSING_VISION_ZERO_MIN_CROSSINGS` crossings in
  24 h and zero `in`/`out` decisions → page. Its decided share is shown on the crossing-vision metric sensor.
- **Cost per day:** R-a 0 model calls; per crossing ≤ |set| (3-5) proxy reads, ~62 crossings on the busiest day →
  ≤ 310 reads/day. R-c inside the primary call: 0 extra calls, ~+6 frames per call on a 93-call cap; if run as its own
  call, `CROSSING_DIRECTION_APPROACH_DAILY_CALLS` (default 0 = off until P3-D0e says otherwise; never the primary cap;
  repeats only through the P3-D3 step 8 budget).
- **Invariant INV-APPROACH-DARK (falsifiable):** while no door group's source reads `approach` and P3-D9c has not
  adopted it, replacing every `approach_direction` with any value (or deleting it) leaves the term stream, `L`,
  `guest_vis`, arrival records, the tracker's `direction` and every reader identical; and every pulled window belongs
  to a camera in the frozen, registry-resolved approach set for that crossing's door group. Break it with a crossing
  whose approach value moves a term, or a pull of a camera outside the set (for example one chosen by a name match).
- **Tests:** `test_approach_set_resolved_from_registry_not_name`, `test_approach_direction_written_via_g3_only`,
  `test_inv_approach_dark_metamorphic`, `test_approach_no_pull_when_off`, `test_approach_zero_tripwire`.
- **Live:** within a day of ship, ≥ 1 G3 amend with role `approach_direction` on a real crossing, its
  `approach_cameras_seen` ≥ 1, and the term stream for that crossing unchanged against a replay with the field
  deleted; the trip-wire entity exists and is quiet.

**P3-D0f anticipatory candidate probe (read-only, 0 model calls; gates P3-D11).** Question: how often does motion
near an egress door happen, how often is it a crossing, and how many crossings does the tracker miss? Steps:
1. **Resolve the candidate sources by registry and freeze them:** per door group, door-group cameras' person and
   motion entities (registry `platform`, device), exterior contacts and covers by device class in the group's area
   (never by name; front group currently has none mapped), motion / occupancy sensors in the door group's interior
   area (`SENSOR_FLEET_CLASSES.md`: an mmWave ZV is a motion source, a radar is presence; classed by capability).
2. **Candidates** over 11-02..11-15 from the recorder: a candidate opens on any source's rising edge and closes after
   `CROSSING_ANTICIPATORY_WINDOW_S` (60) with no further edge; per door group count candidates/day.
3. **Outcome per candidate:** matched to a tracker crossing (E inside the candidate ± `_MATCH_S` (30)) = `crossing`;
   no tracker crossing = `unmatched`. On a sample of `unmatched` candidates the operator grades (CROSSING-GRADING-PAGE-1
   format, a new batch) whether a person actually crossed: those are the tracker misses.
4. **Lead time:** for matched candidates, candidate open → E (is it anticipatory at all, or the same moment as the
   egress trigger and the P2-D8 fast stage).
5. **Direction value:** does the source ORDER (contact before exterior camera, interior motion before exterior) beat
   the tracker on the operator-graded clips (same gates as P3-D0e; this is I3 generalised to motion).
- **Gate:** P3-D11 is built only if (a) graded tracker misses ≥ `CROSSING_ANTICIPATORY_MISS_MIN_PER_WEEK` (3) per
  door group, or (b) step 5 passes the direction gate; and candidates/day ≤ `CROSSING_ANTICIPATORY_MAX_PER_DAY` (150)
  per group (above that the trigger is noise). Neither → park with this revival trigger: a graded tracker-miss rate
  above the threshold on a later batch.
- **Acceptance:** `AUDIT_crossing_anticipatory_<date>.md` with per door group candidates/day, crossing share,
  graded misses, lead time, direction score and the frozen source fixture.

**P3-D11 = P3-D9c: the egress tracker extended (Tier 3; card EGRESS-TRACKER-DIRECTION-1, folded in; BUILD WAITS on
P3-D0f, and its direction part on P3-D0e or P3-D0b).** Operator ruling 2026-11-15, verbatim: "Maybe we need to extend
it instead of thinking about it like a second trigger." So there is no separate candidate producer.
`EgressDirectionTracker` (`transit_validator.py:1079`) is extended in its two existing steps, and stays the one F3
owner with one bus event and one dedup. INV-ONE-F3 then holds by construction.
- **Today:** the tracker triggers only on a door-camera person sensor turning on, or its person count going 0→N
  (`_on_egress_state_change` `:1628`, `_on_egress_count_change` `:1672`, both scheduling resolution after
  `EGRESS_ENTRY_WINDOW_SECONDS` 45 s, `:1648-1667`, `:1718`; `const.py:3381`). `_resolve_direction` (`:2373`) decides from
  interior-camera events only: within +45 s = entry, within −30 s (`EGRESS_EXIT_WINDOW_SECONDS`) = exit, else
  ambiguous (`:2401-2423`), then the direction-keyed 30 s dedup (`:2425-2438`) and `_record_crossing` + bus fire.
- **(a) Trigger evidence, widened.** Besides the door camera, a door-group contact or cover opening (registry device
  class `door` / `garage_door` / cover, mapped to the door group by registry area and device, never by name) and
  motion near the door from egress-area sensors classed by capability (`SENSOR_FLEET_CLASSES.md`) open a PENDING
  candidate inside the tracker. A candidate becomes a tracker trigger (the same resolution timer, the same E) only
  when it is confirmed: the door-group camera's recording window shows a person (R-a Frigate records, else the
  configured detector route of P3-D10), or a camera trigger joins it inside `CROSSING_ANTICIPATORY_MATCH_S`. An
  unconfirmed candidate is discarded after `CROSSING_ANTICIPATORY_WINDOW_S` (a counter only, no record). A candidate
  that a camera trigger joins is ONE trigger, E = the earliest confirmed evidence time (one crossing, not two). The
  "confirmed but no camera trigger" case is simply a tracker trigger now: a crossing the tracker used to miss.
- **(b) Direction evidence, widened, one rule.** `_resolve_direction` combines, in one function
  `combine_direction(evidence) -> (direction, direction_source)`: interior timing (today's rule, unchanged as one
  input), door contact order (I3), outside-approach presence and motion (P3-D10 `approach_direction`), and the
  candidate's pre-E source order. The rule itself (priority order, or agreement-required) is chosen by P3-D0b / P3-D0e
  / P3-D0f on operator labels and frozen before build; abstaining inputs fall back to today's rule. A resolution that
  waits for P3-D10's window (E + 30 s + lag) still fits inside today's 45 s only if `_WINDOW_AFTER_S` ≤ 45 − lag; the
  build chooses the window from P3-D0e, never lengthens the 45 s silently (it is a knob, and lengthening it delays
  every reader below).
- **Dedup / double-count guard:** the existing dedup runs AFTER the combined direction, so a candidate and a camera
  trigger on one door group within `DOOR_STEM_DEDUP_S` give one record; candidate-to-trigger joining happens before
  resolution is scheduled (one pending entry per door group, keyed like `dedup_base`), so a contact-open plus a
  person-sensor-on can never schedule two resolutions. Test `test_candidate_and_camera_trigger_one_record`.
- **What changes for each reader** (all read the tracker's record or bus event; additive key `direction_source`;
  shapes unchanged):
  - arrival notify `_arrival_departure_notify` (`:2548`, def `:2917`): fires on more crossings (recovered misses) and
    with the combined direction; still synchronous at resolution (INV-NOTIFY-LATENCY);
  - census egress faces `register_egress_face` / `evict_egress_face`: the entry/exit choice follows the combined
    direction; a recovered crossing with no face attaches nothing (no identity is invented);
  - entered / exited sensors and the exit backfill: counts change by the recovered crossings and corrected signs;
  - DB `person_entry_exit_events`: more rows, `direction` from the combined rule, new nullable `direction_source`
    column (Tier 2-DB rider: migration, written through the existing write queue, batched);
  - perimeter (`perimeter_alert.py`) and sightings: receive the same bus event; a recovered crossing is a new event for
    them; the perimeter D3 zone gate is unchanged;
  - crossing vision / ledger: watches the recovered crossings like any other (P3-D3), counts against the 93 cap.
  Each reader gets a named before/after test; scored before and after by `pipeline_version` (P3-D6 TRACKER-READY).
- **Fire check / trip-wires:** per source fire counts from P3-D0f; `egress_trigger_source_zero` (a source silent 24 h
  while that door group has crossings) and `egress_direction_combined_zero` (instrument decides none) page NM.
- **Cost per day:** 0 model calls for triggers and confirmation on R-a; proxy reads ≤ one window per candidate
  (≤ `CROSSING_ANTICIPATORY_MAX_PER_DAY` per group). A confirm through an HA-side detector entity is one
  `image_processing.scan` per candidate, local to that install. No LLM in the tracker.
- **INV-TRACKER-LATENCY (P3-D11, falsifiable; operator 2026-11-15: "The thing to be wary of in crossing logic is
  speed. Because naming and vision are on top of this, we need to make sure the expansion doesn't slow it too much.").**
  For every crossing whose trigger includes a door-camera person-on or count 0→N, `_resolve_direction` runs at
  E + `EGRESS_ENTRY_WINDOW_SECONDS` (45 s, today's time) and fires `ura_person_egress_event` in that same call, with no
  new `await` on I/O before the fire. `combine_direction` reads only evidence already in the tracker's memory at that
  moment (contact edges, outside-camera Frigate presence already received, candidate source edges, interior timing).
  Slower evidence never delays the bus event: the recording-window confirmation (~25 s recording lag + ~11 s fetch),
  the P3-D10 approach direction and count, and any `image_processing.scan` arrive afterwards as G3 amendments
  (`direction_source`, `approach_direction`, `approach_people_count`). The late-correction path: if late evidence
  disagrees with the fired direction, the tracker writes G3 attributes `late_direction` and `late_direction_source`
  only (role `direction_late_evidence`); the record's `direction`, the bus event, the DB `direction` column, the
  census face choice and the notification are never rewritten (`direction` stays a FORBIDDEN G3 key); the P3-D6 scorer
  reads `late_direction`, and only a later reviewed change could let it act. A candidate with no camera trigger
  (contact or motion only) resolves at most `EGRESS_CANDIDATE_RESOLVE_MAX_S` (90 s, rung 1) after its first edge,
  or is discarded at that bound. Arrival notify, census `register_egress_face` / `evict_egress_face` and identity
  attach (naming) see, for camera-triggered crossings, the same call time relative to E as today. Break it with any
  camera-triggered crossing whose bus fire, notify, face register/evict or identity attach happens later than today's
  for the same event sequence, or a contact-only candidate that resolves after its bound.
  - Worst-case added latency: camera-triggered 0 s (by construction; evidence not in hand is ignored at the
    deadline); camera trigger joined by an earlier contact or motion edge: 0 s after the camera's E + 45 s (E is the
    earliest confirmed evidence only for contact-only candidates; when a camera trigger exists the resolution timer
    stays the camera's, so the join can never push it later); contact or motion only: ≤ 90 s after the first edge
    (recording lag 25 s + fetch ~11 s + detector call + margin), against today's infinite (never resolved).
  - Trip-wire `egress_resolution_latency_p95`: p95 of (bus fire time − E) over 24 h of camera-triggered crossings
    above `EGRESS_RESOLUTION_P95_MAX_S` (50 s, rung 1; 0 = off) pages NM; contact-only p95 reported beside it against
    the 90 s bound.
  - Tests: `test_camera_crossing_bus_fires_at_e_plus_45`, `test_notify_timing_unchanged`,
    `test_census_face_register_evict_timing_unchanged`, `test_identity_attach_timing_unchanged`,
    `test_late_evidence_is_amend_never_rewrite`, `test_contact_only_candidate_resolves_within_bound`,
    `test_resolution_latency_tripwire`.
- **Invariant INV-ONE-F3 (falsifiable):** every `CrossingRecord`, `ura_person_egress_event` and
  `person_entry_exit_events` row is created by `_resolve_direction` → `_record_crossing`, and any physical pass
  produces at most one per door group within `DOOR_STEM_DEDUP_S` whatever mix of contact, motion and camera triggers
  fired; a discarded candidate creates nothing. Break it with a trigger mix (contact then person-on, count 0→N then
  contact, motion with no person) that yields two records, or one record from an unconfirmed candidate.
- **Tests:** `test_candidate_and_camera_trigger_one_record`, `test_unconfirmed_candidate_discarded_no_record`,
  `test_trigger_sources_registry_resolved_not_name`, `test_combine_direction_fallback_is_todays_rule`,
  `test_reader_<each>_before_after`, `test_direction_source_on_bus_and_db`, `test_inv_one_f3_metamorphic`.
- **Live:** a day's crossing count = camera triggers + confirmed candidates, no door group with two records inside
  30 s; `direction_source` present on every new bus event and row; trip-wires quiet.
- Reads `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` completely at plan time (its own Tier-3 plan, two plan reviews incl.
  framing G, four code reviews).

**Phase 3 decisions (taken by the orchestrator 2026-11-15 on the recommended defaults; the operator may override).**
1. P3-D0 spent its 120 Luna calls (done). P3-D0c may spend up to 14 more (operator yes asked; Luna cost is trivial).
2. A collapsed pass gives no ledger term until its door group flips (P3-D4 step 5, W9-W11 name the effect).
3. The 110 s term hold applies only to the ledger and awareness path; the arrival notification, the census trust view
   and AWAY are untouched (P3-D4, when built).
4. The cap is 93 from the P3-D0 (a) volume probe (built).
5. EGRESS-TRACKER-DIRECTION-1 is the home of the direction fix (P3-D9c) and of the pass key (P3-D9a / b), each gated on
   its probe (P3-D0b, P3-D0d), not parked.
6. **Operator-visible tradeoff (closure MEDIUM-4, updated):** census F-LEAD needs a direction verdict (P3-D6
   TRACKER-READY). The tracker is measured at 65 %, so F-LEAD waits, per door group, for vision FLIP-READY (P3-D7; ≈ 10-50 days of
   production per group, P3-D6) or a P3-D9c instrument with TRACKER-READY, or for the operator to accept the tracker's
   signs for F-LEAD.
7. **APPROVED (operator 2026-11-15, "Door vision stuck sensor - yes"):** P3-D8, a stuck-excluded live input stops
   holding the anchor while a dead input still holds (built with the knob True on `feature/crossing-p3-first`).
8. **M2 (unchanged numbers):** a pass-key candidate needs ≥ 20 hand-labelled round trips and a Wilson upper bound
   ≤ 0.15; below 20 the verdict is HOLD and collapse stays off. Mining is capped by Frigate's ~13-day event retention,
   so staged round trips may be the only way to 20 (operator question).
9. **Operator ruling 2026-11-15 on P3-D0 (b), verbatim: "Is the bar right? I'd not park and instead build and hold off
   and measure. We need reps."** Vision direction is built and recorded on every crossing (P3-D3), scored per door group
   for accuracy (Wilson lower bound ≥ 0.90, unchanged: right for changing a census term) and stability (repeat-call
   agreement, new), with confidence recorded only (P3-D6); INV-DIR-GATE stays closed until P3-D7's operator checkpoint.
   Sampled repeat rate 0.2, at most 15 repeats a day on their own budget, never the primary cap or a primary's slot.
13. **OPEN OPERATOR QUESTION: absolute or relative direction bar (P3-D6 FLIP-READY).**
    - **(A) Absolute (as written):** vision's Wilson 95 % lower bound ≥ 0.90 in the door group, plus disagreement win
      ≥ 0.80 and the stability bar. Implication: a door flips only if vision is truly ≈ 95 %+; at the measured front
      73 % it never flips and PARKs in about 1-2 weeks. The ledger keeps a 65 % tracker in the meantime. Simple to
      explain; the same bar the tracker must meet for TRACKER-READY.
    - **(B) Relative:** vision's lower bound above the TRACKER's upper bound on the SAME scored crossings in that door
      group, plus disagreement win ≥ 0.80 and the stability bar. Implication: a door could flip at about 85 % vision
      against a 65 % tracker, which materially improves the ledger's signs (`L` error falls with every corrected sign);
      it needs roughly as many scored crossings (the two intervals must separate), and it makes the ledger only "better
      than today", not "good": F-LEAD (census awareness leading) would still need its own absolute bar, so (B) moves
      the dark ledger and the awareness display, not the census value.
    - **Recommendation: (B) for the ledger flip (P3-D7), (A) kept for F-LEAD.** Reasons: the 0.90 argument ("a wrong
      sign moves `L` by `n` until the anchor") applies equally to the tracker the ledger already uses, so refusing a
      clearly better source keeps more wrong signs; the disagreement-win and stability conjuncts still block a source
      that is better on average but wrong where it matters or flips; nothing behind the ledger acts until F-LEAD, which
      keeps the absolute bar; no hard constraint is touched (AWAY reads the trust view). The operator decides; until
      then the plan builds the scorer to report both verdicts.
10. **P3-D2 frames:** 8 on every crossing call instead of the peak ≥ 3 branch (run 2 evidence; operator may prefer the
    branch).
11. **Group count use rule:** vision count alone in the term (a near-floor), camera peak recorded beside it, not maxed
    (P3-D2 step 7).
12. **P3-D3 watches ambiguous crossings** for count and recorded direction (operator: "of course. No brainer").
14. **Operator design 2026-11-15, verbatim: "Arriving: when we detect a door crossing we can go back in history and
    get clips of the approach inside and outside the house."** Planned as P3-D0e → P3-D10, scored only on operator
    labels; cheapest passing tier (R-a Frigate records, R-b a person detector APPROVED, delivered through an install-agnostic
    HA/Frigate route: Frigate detections, else an operator-configured `image_processing` entity; operator: "Why in
    homelab and not ha. That's not agnostic of operator."; R-c LLM in the primary call). OPEN: operator yes for ≤ 60 Luna calls on the R-c leg (recommended: yes).
15. **Operator design 2026-11-15, verbatim: "Alternatively we can treat motion near an egress door as an anticipatory
    crossing and collect clips from/frames to check if it was a crossing. If it a crossing we look to determine
    direction and if not discard"; ruling, verbatim: "Maybe we need to extend it instead of thinking about it like a
    second trigger."** Planned as P3-D0f → P3-D11 = the extended `EgressDirectionTracker` (P3-D9c merged in, card
    EGRESS-TRACKER-DIRECTION-1): widened trigger evidence and one combined direction rule inside the one F3 owner; a
    confirmed candidate IS a tracker trigger (INV-ONE-F3 by construction). OPEN: grade ~20 unmatched candidates on the
    grading page (recommended: yes).
16. **No-frigate-event recovery is a P3-D2 change (P3-D2b), not P3-D11:** the 26 % are tracker-resolved crossings with
    no matched Frigate event; on the recording route the door camera's window can be pulled without an event.
    Recommended: build P3-D2b after P3-D2 if P3-D0e step 4 shows a person in most of those windows.

17. **Operator constraint 2026-11-15, verbatim: "The thing to be wary of in crossing logic is speed. Because naming and
    vision are on top of this, we need to make sure the expansion doesn't slow it too much."** INV-TRACKER-LATENCY:
    camera-triggered crossings fire at today's E + 45 s; slower evidence is a G3 amendment; contact-only candidates
    bounded at 90 s; p95 trip-wire.
18. **Operator 2026-11-15: counting accuracy from "the before and after clips/frames".** P3-D10 also yields
    `approach_people_count`, combined with the door count only for groups of 3+ or long events, scored first.
Tier: P3-D0 / P3-D0b / P3-D0c / P3-D0d probes (read-only; P3-D0c spends ≤ 14 model calls); P3-D1 Tier 1 (built); P3-D2,
P3-D6, P3-D8, P3-D2b Tier 2; P3-D10 Tier 2 to record (G3 writer, display only), Tier 3 when adopted by P3-D9c; P3-D11 (= P3-D9c, the extended tracker) Tier 3 with a Tier 2-DB rider (`direction_source` column); P3-D0e / P3-D0f probes; P3-D5 Tier 2-DB (built); P3-D3, P3-D4, P3-D7 and P3-D9 (a / b / c) Tier 3 (P3-D3: a production G3
writer and an INV-SCOPE change) (ledger input surface, the F3 source): two plan reviews incl. framing G,
four code reviews, orchestrator re-grep of every term-construction site (`cluster_terms`, `_release_terms`,
`_ledger_terms`, `_join_cluster` late branch, the no-request paths `:620-622`, `:676-707`, the call-time paths
`:869-882`, `:906`, `:928`, `:935-939`) and a real source mutation of the INV-DIR-GATE site (the term's sign), operator
checkpoint before deploy.

## 6. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `switch.ura_crossing_vision_shadow` | off at ship | 3 | Master; off = INV-OFF |
| `LLMVISION_ENRICHMENT_KILL` (REUSED) | False | 1 | All llmvision use |
| `CROSSING_VISION_DAILY_CALLS` | 93 (P3-D0 (a): ceil(62 × 1.5), ≤ 200; built) | 3 (Number) | 0 = no calls; counter rehydrated at setup from today's call rows (P3-D5), local midnight |
| `CROSSING_VISION_MODEL` | `gpt-4o-mini` → `gpt-6-luna` (P2-D1) | 1 | Dry call first |
| `CONF_CROSSING_VISION_PROVIDER_ID` | empty = install default if present, else perimeter provider | 2 | Portable provider |
| `CROSSING_VISION_PROVIDER_ID` (kept) | `01M7B731T26P2HXVW77AQR62PP` | 1 | Used only when the option is empty AND this id is an `llmvision` entry on the install (P2-D1) |
| `CROSSING_VISION_MAX_FRAMES` / `_TARGET_WIDTH` | 4 / 768 | 1 | D0b / D0-V; crossing calls use `CROSSING_VISION_CROSSING_FRAMES` (P3-D2) |
| `CROSSING_VISION_CROSSING_FRAMES` | 8 | 1 | P3-D2: every crossing call (run 2: no change on 1-2 person clips, median 12.7 s); 4 = the pre-Phase-3 count |
| `CROSSING_VISION_MAX_TOKENS` | 4000 (was 1500; built) | 1 | P3-D0: 1500 truncated big-party replies to empty (`refused`); 0 of 31 empty at 4000 |
| `CROSSING_VISION_TIMEOUT_S` | 90 | 1 | ≥ 1.5 × measured p99, above llmvision's request timeout (cancelling can orphan its ffmpeg) |
| `CROSSING_VISION_EVENT_MATCH_S` | 10 (→ 30 if P2-D0 (iii) ≤ `CROSSING_VISION_EVENT_MATCH_WRONG_MAX` 0.02) | 1 | Coverage vs mismatch |
| `CROSSING_VISION_EVENT_END_WAIT_S` | 120 | 1 | Longest event 134 s |
| `CROSSING_VISION_CLUSTER_S` | 60 | 1 | Same-door share |
| `CROSSING_VISION_MAX_CONCURRENT` | 2 | 1 | Measured max |
| `CROSSING_VISION_EVENT_RING` | 20 per camera | 1 | Bounded memory |
| `CROSSING_VISION_KEEP_FRAMES` | True | 1 | Frames kept locally for labelling; False = none |
| `CROSSING_VISION_ZERO_MIN_CROSSINGS` / `_ERROR_RATE_MAX` / `_ERROR_MIN_CALLS` | 5 / 0.25 / 8 | 1 | Trip-wires; rate > 1 = off |
| `CROSSING_VISION_TRIPWIRE_WINDOW_S` / `_EVAL_S` | 86400 / 3600 | 1 | Trip-wire window / cadence |
| `CROSSING_VISION_DESC_MAX_CHARS` / `_TEARDOWN_GATHER_S` | 200 / 5 | 1 | Row size / unload bound |
| `CROSSING_VISION_LEDGER_EMPTY_RESET_S` | 900 (operator 2026-11-14 "15 mins"; basis `AUDIT_ledger_checkpoint_window_sweep_2026_11_14.md`) | 1 | Anchor window; 0 = instant |
| `CROSSING_VISION_LEDGER_ANCHOR_NEEDS_NO_HOLD` | True | 1 | Held-input conjunct (P2-D2 step 2); False = edge-only predicate |
| `CROSSING_VISION_LEDGER_EVAL_S` | 60 | 1 | Anchor cadence; 0 = 1 s (interval and freshness) |
| `CROSSING_VISION_GO_ARRIVAL_WINDOW_BEFORE_S` / `_AFTER_S` (REUSED from the census plan bar b) | 300 / 60 | 1 | Arrival-credit match window (P2-D2 step 4); 0 / 0 = a lift is never consumed (old double count returns only for exact-time terms) |
| `CROSSING_VISION_LEDGER_RECONCILE_LEAD_S` / `_LAG_S` | 900 / 60 | 1 | 0 / 0 = reconcile off |
| `CROSSING_VISION_LEDGER_FALLBACK` | `camera` | 1 | `skip` = vision-only terms |
| `CROSSING_VISION_LEDGER_STUCK_S` / `_ANCHOR_ZERO_S` | 7200 / 172800 | 1 | Pages; 0 = off |
| `CROSSING_VISION_NAME_SETTLE_S` / `_EXIT_NAME_SETTLE_S` | 180 / 660 | 1 | Arrival record write times; entry set to P2-D0 (viii) p99 + 30 s |
| `CROSSING_VISION_FAST_STAGE_ENABLED` / `_FAST_MAX_FRAMES` | False / 3 | 1 | F stage |
| `CROSSING_VISION_LATENCY_TARGET_P90_S` / `_LATENCY_TRIPWIRE_DAYS` | 60 / 3 | 1 | Latency target / page; 0 days = off |
| `CROSSING_VISION_METRIC_WINDOW_DAYS` | 7 | 1 | Metric sensors |
| `CROSSING_VISION_GRADE_DAILY_N` | 5 | 3 | 0 = off |
| `CROSSING_VISION_GRADE_PENDING_TTL_S` | 86400 | 1 | Pending grade map |
| `CROSSING_VISION_INTERIOR_ENABLED` | reserved, not added | — | VISION-INTERIOR-SIGHTINGS-1 |
| `CROSSING_VISION_ERROR_TEXT_MAX_CHARS` | 200 | 1 | P3-D1 row size |
| `CROSSING_VISION_FRAME_ROUTE` | `recording_window` if P3-D0c passes, else `event_clip` for events ≤ `LONG_EVENT_S` and `recording_window` above (P3-D0 (c) GO) | 1 | P3-D2; `event_clip` = the pre-Phase-3 route |
| `CROSSING_VISION_FRAME_WINDOW_BEFORE_S` / `_AFTER_S` | 5 / 15 | 1 | Recording window around E; P3-D0 R3 showed the 10 s lead as empty frames; bounds the clip to 20 s |
| `CROSSING_VISION_GROUP_PEAK_MIN` / `_LONG_EVENT_S` | 3 / 60 | 1 | Display shows a vision count ≥ 3 as "n+" (named group bias, P3-D2 step 7); events longer than 60 s never use the event clip when the window route is available. `_GROUP_MAX_FRAMES` dropped (8 frames on every call) |
| `CROSSING_VISION_RECORDING_LAG_S` | 10 (P3-D0 (c): complete from 5 s) | 1 | Wait so the recording window is complete; bounded by `EVENT_END_WAIT_S` |
| `CROSSING_VISION_PASS_EVENT_PAD_S` | 2 (not built) | 1 | The failed event-window pass rule (P3-D0 (d)); kept only as the record of that candidate |
| `CROSSING_VISION_PASS_CONTACT_PAD_S` / `_PASS_CHAIN_GAP_S` | 5 / 5 | probe gate (P3-D0d) | K1 contact-cycle pad; K3 event-chain gap; become rung 1 if the candidate passes |
| `CROSSING_VISION_AMBIGUOUS_ZERO_MIN` | 5 | 1 | `crossing_vision_ambiguous_zero` trip-wire (bus count); 0 = off |
| `CROSSING_VISION_CAP_HEADROOM` | 1.5 | probe rule (plan number) | P3-D5 cap sizing |
| `CROSSING_VISION_CAP_REHYDRATE_TIMEOUT_S` / `_RETRY_S` | 30 / 60 | 1 | P3-D5 background rehydrate; failure twice = counter stays at cap until midnight |
| `CROSSING_VISION_DIRECTION_ORACLE_BEFORE_S` / `_AFTER_S` | 300 / 60 (mirrored for exits) | 1 | P3-D6 resident-edge oracle window (same as the arrival-credit window) |
| `CROSSING_VISION_DIRECTION_PARK_N` | 150 per door group | 1 | P3-D6 hard stop; PARK itself fires earlier on the upper bound |
| `CROSSING_VISION_P3_DIR_GATE_OK` / `_TRACKER_WRONG_OK` / `_GROUP_UNDERCOUNT_MAX` | 15 of 17 / 5 of 6 / 1 | probe gate (plan numbers) | P3-D0 (b) (failed: 13, 3); reused by P3-D0b; a "worth building" gate, not the runtime bar |
| `CROSSING_DIRECTION_INSTRUMENT_COVERAGE_MIN` | 0.50 | probe gate | P3-D0b: share of crossings the instrument decides on its OWN, before tracker fallback (the fallback share is reported) |
| `CROSSING_DIRECTION_DOOR_PAD` / `_CONTACT_TIE_S` / `_PROBE_CAPTURE_H` | 0.05 (normalised) / 2 / 48 | probe gate | P3-D0b I1 door proximity, I3 tie band, step 1b capture length; become rung 1 in P3-D9c if adopted |
| `CROSSING_VISION_P3_D0C_CALLS` | 14 | probe budget | P3-D0c recording-window group check |
| `CROSSING_VISION_DIRECTION_REPEAT_RATE` | 0.2 | 1 | P3-D3 step 8 sampled repeat (sha1 of the crossing key); 0 = off |
| `CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX` / `_REPEAT_WAIT_S` | 15 / 120 | 1 | Own repeat budget (never the primary cap); a repeat waits ≤ 120 s for a free slot, else skipped; 0 max = off |
| `CROSSING_VISION_DIRECTION_REPEAT_AGREE_LB_MIN` / `_REPEAT_MIN_N` | 0.80 / 20 per door group | 1 | P3-D6 stability bar (Wilson lower bound of repeat agreement; 20/20 needed at n = 20); PARK on the upper bound < 0.80; no true-repeat baseline yet |
| `CROSSING_VISION_WATCH_AMBIGUOUS` | True | 1 | P3-D3; False = the pre-Phase-3 skip |
| `CROSSING_VISION_PIPELINE_VERSION` | bumped per Phase 3 ship | 1 | Separates rows in every bar |
| `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` | 10 | 1 | `crossing_vision_direction_zero` trip-wire; 0 = off |
| `CROSSING_VISION_LEDGER_PASS_COLLAPSE` | False until a P3-D0d candidate passes and P3-D4 is built, then True | 1 | P3-D4; False = per-member terms as before |
| `CROSSING_VISION_PASS_SAME_EVENT_MIN` | 0.80 | probe gate (plan number, not runtime) | P3-D0 (d) (failed: 0.29), P3-D0d |
| `CROSSING_VISION_PASS_ROUND_TRIP_MIN_N` | 20 | probe gate | P3-D0 (d): fewer hand-labelled one-event round trips = HOLD (collapse off, P3-D9b waits) |
| `CROSSING_VISION_PASS_ROUND_TRIP_MERGE_UB_MAX` | 0.15 (Wilson 95 % upper bound) | probe gate | P3-D0 (d): one-event round-trip merge share; above it collapse stays off and P3-D9b does not ship |
| `CROSSING_VISION_PASS_MINE_MAX_DAYS` | 30 | probe gate | Mining horizon; Frigate keeps ~13 days of events, which is the real limit |
| `CROSSING_VISION_ANCHOR_STUCK_CLIENTS` | {`p22_continuous`, `chatter`, `stuck_dutycycle`} | 1 | P3-D8: exclusion clients that stop an `on` input holding; never the camera-stream client |
| `CROSSING_VISION_TRACKER_FRIGATE_RING` | 20 per Frigate camera, 1800 s | 1 | P3-D9c / P3-D9a tracker event ring bound (count and age, same as the crossing ring age) |
| `CROSSING_VISION_DAILY_CALLS_MAX` (existing, `const.py:3569`) | 200 | 1 | Upper bound of the cap Number |
| `CROSSING_VISION_CAP_REHYDRATE_INDEX_ROWS` | 200 000 | probe rule (plan number) | P3-D5: above it the build adds `idx_episodes_type_ended` |
| `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK` | True (P3-D8, operator approved 2026-11-15) | 1 | False = a stuck-excluded live `on` input still holds and its edges count (P3-D8b) |
| `CROSSING_VISION_ANCHOR_P22_SLEEP_GATE` | True | 1 | P3-D8 / P3-D8b: a `p22_continuous`-only exclusion is not honoured in SLEEP / WAKING / HOME_NIGHT (D-M1); False = honoured always |
| `CROSSING_VISION_TERM_HOLD_S` | 110 (cluster 60 + entry window 45 + 5) | 1 | P3-D4 hold; must be ≤ 2 × `CLUSTER_S` (asserted at setup); 0 = build terms at the vision outcome (pre-Phase-3) |
| `CONF_CROSSING_VISION_LEDGER_DIRECTION_SOURCE` | per door group (`CONF_DOOR_GROUPS` key, else `stem:<stem>`); missing = `tracker` | 2 (options flow; flip per group at an operator checkpoint, P3-D7) | INV-DIR-GATE; `vision` for a group only after its FLIP-READY. Portable: no install names in code |
| `CROSSING_VISION_DIRECTION_ACC_LB_MIN` / `_SCORED_MIN_N` | 0.90 / 30 | 1 | P3-D6 accuracy bar (every source, per door group): Wilson 95 % lower bound on oracle-scored crossings; sized from error rates, not days |
| `CROSSING_VISION_DIRECTION_DISAGREE_WIN_MIN` / `_DISAGREE_MIN_N` | 0.80 / 15 per door group | 1 | Source right where it and the tracker disagree |
| `CROSSING_VISION_P3_PROBE_CALLS` | 120 (spent) | probe budget | P3-D0 model calls |
| `CROSSING_DIRECTION_APPROACH_PROBE_CALLS` | 60 (46 primaries + 14 repeats) | probe budget | P3-D0e R-c leg; operator yes |
| `CROSSING_DIRECTION_APPROACH_WINDOW_BEFORE_S` / `_AFTER_S` | 30 / 30 | probe gate, then 1 | P3-D0e / P3-D10 window around E; the approach takes longer than the 20 s count window |
| `CROSSING_DIRECTION_APPROACH_ORDER_TIE_S` / `_X_DISPLACEMENT` | 3 / 0.15 (normalised) | probe gate, then 1 | First-presence order tie band; G6 strip displacement rule (I1 v2 review proposal) |
| `CROSSING_DIRECTION_APPROACH_DAILY_CALLS` | 0 | 3 (Number) | P3-D10 only if R-c needs its own call; own budget, never the primary cap; 0 = off |
| `CROSSING_DIRECTION_APPROACH_ENABLED` | False until P3-D0e PASS | 1 | P3-D10 kill switch: False = no pulls, no amend |
| `CROSSING_ANTICIPATORY_WINDOW_S` / `_MATCH_S` | 60 / 30 | probe gate, then 1 | P3-D0f / P3-D11 candidate lifetime; match to a tracker E |
| `CROSSING_ANTICIPATORY_MISS_MIN_PER_WEEK` / `_MAX_PER_DAY` | 3 / 150 per door group | probe gate | P3-D0f build gate (miss rate worth it; trigger not noise) |
| `EGRESS_CANDIDATE_RESOLVE_MAX_S` | 90 | 1 | INV-TRACKER-LATENCY bound for contact / motion-only candidates; 0 = such candidates never resolve (camera triggers only) |
| `EGRESS_RESOLUTION_P95_MAX_S` | 50 | 1 | `egress_resolution_latency_p95` trip-wire over 24 h of camera-triggered crossings; 0 = off |
| `CONF_CROSSING_DETECTOR_ENTITY` | empty | 2 (options flow) | Optional HA `image_processing` entity for R-b confirm / approach; empty = Frigate records only |
| `CROSSING_ANTICIPATORY_ENABLED` | False until P3-D0f PASS | 1 | P3-D11 kill switch |

Census-side knobs (class set, F-LEAD, notify bars, bars a-e) live in the census plan.

## 7. Dependencies and sequence

1. Phase 1 (built): three framing-disjoint reviews (A correctness; B async lifecycle, teardown, write queue, restart,
   `wait_for` cancellation into llmvision, payload shape per listener incl. `person_sighting.py` and the recorder; C
   per-site mutation) + README; operator turns the switch on; live rows; README write-back.
2. P2-D0 probe and P2-D1 Luna now; operator schedules P2-D7.
3. Read-API ship 1; then P2-D2 / P2-D3 (with the census plan's CD1), P2-D9, P2-D10 in parallel with collection; ship dark.
4. P2-D8 only after P2-D0 (vi) passes.
5. P2-D6 disposition after ≥ 7 days and bar minimums; flips per the census plan's ladder.
6. Phase 3, in order (rewritten 2026-11-15 after P3-D0):
   1. **Anchor prerequisites first** (`PLANNING_stuck_sensor_truth.md` S1-S3): S3 step 0 and S1 step 0, then S3 (Tier
      1 + config) and S1 (Tier 2-DB) in parallel; S2 (= P3-D8b) on the P3-D8 branch, reviewed with P3-D8. Without an
      anchor the ledger stays `unknown` and no ledger use of Phase 3 can be measured.
   2. **P3-D2 with P3-D0c ahead of it.** P3-D0c (≤ 14 calls, operator yes) sets the route default; then the P3-D2
      remainder (8 frames, recording window, large-clip handling). Ships with the `feature/crossing-p3-first` set
      (P3-D1, P3-D5, P3-D8, cap 93, 4000 tokens), after S1 so P3-D8 is relied on only once S1 is live.
   3. **P3-D0b and P3-D0d** (read-only, no model calls) in parallel with step 2; the operator answers the door-zone
      and staged-round-trip questions they raise.
   4. **P3-D3** (Tier 3: ambiguous watched, count and direction recorded behind the gate, sampled repeat), after P3-D2;
      then P3-D6 with the scorer build (P2-D10 grading, harmonization C10) so reps accrue from the first day.
   5. **P3-D9c** (Tier 3, EGRESS-TRACKER-DIRECTION-1 plan) if P3-D0b passes. Then P3-D6 with the scorer build (P2-D10
      grading built there, harmonization C10) to score the tracker before / after by `pipeline_version`.
   6. **P3-D9a → P3-D4 → P3-D9b** only if a P3-D0d candidate passes (and not at all if K2 makes collapse unnecessary).
   7. P3-D7 per door group after its FLIP-READY, at an operator checkpoint (P3-D9c preferred if both are ready).
   8. **After the operator's grades land** (`crossing_operator_grades.json` pulled): first re-score every existing
      instrument (V, I1 v2, I6, ensemble, tracker) on operator labels; then P3-D0e step 0 at once (retention) and
      P3-D0e / P3-D0f in parallel (read-only; P3-D0e R-c needs the call budget yes). Then P3-D2b if its share holds;
      P3-D10 (record) on P3-D0e PASS, scored by P3-D6, into the tracker through P3-D9c; P3-D11 (the extended tracker, P3-D9c merged) on P3-D0f PASS (direction part on P3-D0e / P3-D0b), the
      tracker-trigger part only inside the EGRESS-TRACKER-DIRECTION-1 plan.
   The census plan's F-LEAD cannot promote before a P3-D6 TRACKER-READY verdict (census plan §3.2, amended with this
   plan) unless the operator accepts the tracker's signs; the `pipeline_version` bumps in P3-D2, P3-D3 and P3-D9c each
   restart the census bars a-e and the F-LEAD windows. Phase 3 builds never change the `deconflict_house` signature
   (harmonization C2; interior ship 5 owns that).

## 8. Non-goals

Vision supplying a name or any `identity_provenance = "vision"`; vision rewriting the tracker's `direction` or any
reader of it (notify, census egress-face union, DB rows, perimeter, sightings: INV-F3-OWNER; the tracker fix is
EGRESS-TRACKER-DIRECTION-1, P3-D9c); vision direction in a term or reader before its door group's FLIP-READY (P3-D7);
voting over repeated model calls to stabilise direction (the sampled repeat measures stability, it never decides); maxing
the vision count with the camera peak (P3-D2 step 7); URA editing Frigate config (threshold zones are the operator's
homelab change); cross-camera re-identification (Frigate events carry no cross-camera id); a second model call per
crossing, except the sampled stability repeat (P3-D3 step 8; group frames and P3-D10 approach frames ride the same call); frame extraction or a detector running inside URA (detection comes from Frigate or an operator-configured HA `image_processing` entity); any dependency on this house's homelab; a second crossing producer beside the tracker (INV-ONE-F3); naming unenrolled people (charter 11-15); B-stage chains across cameras and
interior head counts (VISION-INTERIOR-SIGHTINGS-1); crossings with no matched Frigate event (all four door cameras run Frigate; 26 % unmatched at ±10 s, 17 % at ±30 s,
12 % at ±60 s per `AUDIT_crossing_vision_d0_2026_11_13.md`; recorded `no_frigate_event`; first lever is widening
`CROSSING_VISION_EVENT_MATCH_S`, then a probe of Protect event clips; revival: `no_frigate_event` > 25 % of a door
group's crossings); two models per crossing; ledger replay across restarts; frame
extraction inside URA; any house-state, security, lock, perimeter or HVAC change (the census plan's ladder governs reach);
the parked Rev 4 guard A / veto B (operator: stay parked).
