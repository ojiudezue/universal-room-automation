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
SPEC).

Read first (done by the planners of rev 1-7.1, completely): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md`. Phase 3 planner (2026-11-15): read completely the
three audits, both cards, the charter incl. the 11-15 additions, the ura-arc skill, arc map step 2b, the census plan
§3.2-§3.4, the layer contract §2.3 / §4.2 / G3; read `SENSOR_FLEET_CLASSES.md`; read the presence state-of-play doc and
the identity manual by section (egress, crossing, vision, §5.5 and the §10 corrections ledger), NOT every line, a
disclosed gap. No claim below rests on those two docs; every code claim is cited to file:line read on develop @
8e1f0e27.

## 0. Institutional context verified (Phase 3)

Greps re-run on develop 8e1f0e27 (`custom_components/` + `docs/planning/*.md`):

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Vision direction field on the vision call | REUSED schema slot, re-measured | The D0 schema had `direction in/out/unsure` (`AUDIT_crossing_vision_d0_2026_11_13.md:40`); D0 scored it against the VALIDATOR's direction (51 %, :71), not against truth, and the build dropped it (`crossing_vision.py:102-103`, "no direction field: D0 found no usable direction signal"). The 11-14 hand count shows the validator itself wrong on 6 of 17 readable clips, so D0's comparison does not measure vision. P3-D0 (b) measures it against human truth |
| Corrected direction as an F3 attribute | REUSED G3 | `amend_crossing` `transit_validator.py:1036`, `attach_crossing_attribute` `:1232`; `direction` is a FORBIDDEN key (`_CROSSING_FORBIDDEN_KEYS` `:977-979`), so the tracker's own `direction` is never rewritten. NEW additive amendable fields `vision_direction`, `vision_people_count`, `direction_agreement` on `CrossingRecord`, and a creation-time `pass_key` set by the tracker (P3-D9a) (`:946-971`) + `_CROSSING_AMENDABLE_KEYS` (`:980-983`): 0 hits for `vision_direction` / `direction_agreement` in code or plans |
| Ring lookup of an ambiguous crossing | REUSED | Ambiguous crossings ARE stored in the ring (`_record_crossing` is unconditional, `transit_validator.py:2514-2530`); `source_ref = egress:<camera>:<iso>` (`:2525-2527`), derivable from the vision `crossing_key = <camera>@<iso>` (`crossing_vision.py:632`) |
| Watching ambiguous crossings | CHANGE of an existing skip | `crossing_vision.py:616-618` |
| Opposite-pass collapse | EXTEND `cluster_terms`; pass key NEW, ONE function owned by the tracker (P3-D9a, harmonization C5), not `_match_event`'s group-wide pick `crossing_vision.py:761-778` | `crossing_ledger.py:172-203` (mixed directions today give one camera term per member); `_join_cluster` late-joiner branch `crossing_vision.py:740-749`; cluster loop `:664-672`. 0 hits for `PAIR_COLLAPSE` / `TERM_HOLD` |
| Event-centred frames | REUSED proxy route | HA Frigate `RecordingProxyView` `/api/frigate/<instance>/recording/<camera>/start/<s>/end/<e>` (`/config/custom_components/frigate/views.py:245-266`, read on the live mount) proxies Frigate `api/<camera>/start/<s>/end/<e>/clip.mp4`. Whether llmvision's `video_file` can fetch it (it is an authenticated view; the notifications view we use today is not) is UNVERIFIED: P3-D0 (c) |
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

Phase 3 scope, stated plainly: it measures and gates vision's direction, collapses one physical pass into one ledger
term, fixes group frames and the cap. It fixes direction for the LEDGER only, and only after the INV-DIR-GATE bar
(about 1-2 weeks of scored crossings at 97 % accuracy, 2-4 weeks at 95 %; the oracle never scores groups or guests).
The census egress-face union, the arrival notification, the entered / exited counts and DB rows, perimeter and
sightings keep the tracker's direction (wrong on about a third of readable crossings) until EGRESS-TRACKER-DIRECTION-1
(P3-D9b) ships its pass-level dedup, and even then only the one-pass-two-labels error is fixed for them.

## 2. F1-F5: produced and consumed

| Fact | Role |
|---|---|
| F1 | consumed: residency departures (ledger reconcile), `R` handed in by the census |
| F2 | none written here. The ledger hands `guest_vis` to the census through `census_tick`; the census owns F2 |
| F3 (owner `EgressDirectionTracker`, `transit_validator.py:1079`) | consumed: `ura_person_egress_event` (entry, exit AND, from Phase 3, ambiguous) and the crossing ring. PRODUCED as attributes of the crossing, written only through G3 `amend_crossing` (role `vision_direction`): `vision_direction`, `vision_people_count`, `direction_agreement`; `pass_key` is set by the tracker itself at creation (P3-D9a); plus the vision count, `term_source`, the arrival record `n` / `k` / `guests_unnamed`. The tracker's `direction` is never rewritten (forbidden G3 key). No second crossing record, no second identity attach |
| F4 | none: vision names no one and emits no sighting |
| F5 | none produced; the one D2 site may annotate an arrival tied to a crossing with `n` / `guests_unnamed` |

## 3. Readers by consumer class

| Output | Readers | Class |
|---|---|---|
| `crossing_vision_shadow` rows, counters, `crossing_vision_today` / `_last` attributes | weekly scorer, trip-wires, diagnostic attribute; generic pre-existing readers `URAMemoryStatusSensor` (`get_memory_status_counts`, `database.py:11152`), `memory_query` (node-keyed), writer-health check (`database.py:11491`) | display |
| Ledger (`guest_vis`, healthy) | the census only, through `census_tick` | F2 input (census plan) |
| F3 attributes `vision_direction` / `vision_people_count` / `direction_agreement` (G3) and `pass_key` (creation) | read API `get_crossing` / `get_crossings_since` (`presence.py:6142-6155`), `crossing_vision_last`; the ledger reads its own copy, used for a term only when `CROSSING_VISION_LEDGER_DIRECTION_SOURCE = vision` (INV-DIR-GATE). `SIGNAL_EGRESS_RECORD_AMENDED` readers ignore the role (`sensor.py:5092`, `:5231` act on `exit_backfilled` only) | display (ledger after the gate) |
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
  rows), in flight ≤ `CROSSING_VISION_MAX_CONCURRENT`, nothing queued beyond (counted skip). Residual: a call in flight
  at a restart that wrote no row is not counted; bound ≤ `MAX_CONCURRENT` per restart.
- **INV-ADDITIVE.** For every non-ambiguous crossing the DB `peak_person_count` equals the bus `peak_person_count` (one
  sample, one local). Ambiguous: bus key None, no DB row, no sample (unchanged by Phase 3); its vision row carries
  `camera_peak_count = None`.
- **INV-DIR-GATE (Phase 3, the falsifiable invariant).** While `CROSSING_VISION_LEDGER_DIRECTION_SOURCE = "tracker"`
  (the default, changed only by a reviewed constant edit after the P3-D6 disposition shows the direction bar passed),
  vision's direction never changes a ledger term: for any crossing sequence, any vision result and any cluster shape,
  replacing every `vision_direction` with any other value (incl. None) leaves the ledger's term stream (kind, sign, `n`,
  `crossing_key`, `term_source`) and every `L` / `guest_vis` value identical. The bar is sized from error rates, not
  days: Wilson 95 % lower bound of vision direction accuracy ≥ `CROSSING_VISION_DIRECTION_ACC_LB_MIN` (0.90) over
  ≥ `CROSSING_VISION_DIRECTION_SCORED_MIN_N` (30) oracle-scored crossings, AND vision right on ≥
  `CROSSING_VISION_DIRECTION_DISAGREE_WIN_MIN` (0.80) of ≥ `CROSSING_VISION_DIRECTION_DISAGREE_MIN_N` (15) scored
  crossings where vision and the tracker disagree. At 97 % true accuracy the bound clears 0.90 near 60 scored crossings;
  at 95 % near 150; below about 92 % it never clears (P3-D6 gives the expected days). Break it with a sequence where a `vision_direction` value moves a
  term while the source is `tracker`.
- **INV-F3-OWNER (Phase 3).** Vision's direction exists only as G3 attributes on the tracker's record; no path writes
  `CrossingRecord.direction`, the bus `direction`, the `person_entry_exit_events.direction` column, the census
  `register_egress_face` / `evict_egress_face` choice or `_arrival_departure_notify` from vision. Every reader of the
  tracker's direction is byte-identical with Phase 3 on or off.
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
   Phase 3 P3-D3 adds `direction`); prompt forbids naming;
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
3. Term per outcome. **Direction of a term** = the tracker's direction while `CROSSING_VISION_LEDGER_DIRECTION_SOURCE =
   tracker` (INV-DIR-GATE); with `vision`, the crossing's `vision_direction` when it is `in` / `out`, else the
   tracker's. An `ambiguous` crossing has no term under `tracker`; under `vision` it gets one when `vision_direction`
   is `in` / `out`. `n`: vision `people_count` when `ok` (`term_source = vision`; ≥ 1 by INV-BLANK), else
   `max(1, camera_peak_count)` with None as 1 (`term_source = camera`; `blank` falls back too; a resolved direction is
   at least one person: review A-MED-1). **Cluster (rewritten P3-D4):** members are first grouped into physical passes
   (`pass_key`, the Pass rule in Phase 3; `None` never matches); one pass gives at most ONE term: under `tracker` a pass
   whose entry/exit members disagree gives no term (`pair_collapsed`, both directions recorded; effect named in P3-D4
   step 8, W9-W11), under `vision` it takes vision's direction. Terms are built only at the P3-D4 release site. Then, as before: one term with the primary's count if all remaining
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

### Phase 3: direction, groups, cap (cards VISION-AMBIGUOUS-CROSSINGS-1 + DOOR-VISION-GROUP-UNDERCOUNT-1)

Charter goals served: "Vision is to assist census accuracy"; "make census almost bullet proof at entry"; "Vision on
crossing with no clear direction - of course. No brainer"; "Is Vision working as designed is the central question";
gates "sized to real error rates, not calendar". Hard constraint kept: "I need away to be fast acting" (AWAY reads the
trust view only; nothing here touches it). Facts: produces F3 attributes (G3); consumes F3 (bus + ring) and, through
the ledger, feeds F2-A only. No F1, F4 or F5 output. Consumer classes: display now; ledger (F2 input) behind
INV-DIR-GATE; the census ladder (census plan §3.2) unchanged except the F-LEAD direction precondition (census plan §3.2,
amended with this plan).

**What this amendment fixes, for which readers (plain statement, review G2).**

| Finding (`AUDIT_door_vision_accuracy_2026_11_14.md`) | Ledger + awareness view | Every other reader (notify, census egress-face union, entered/exited + DB rows, perimeter, sightings) |
|---|---|---|
| Direction wrong on 6 of 17 readable clips (35 %) | Measured now (P3-D3, P3-D6); fixed only after the INV-DIR-GATE bar passes (P3-D7) | NOT fixed by this plan. Fixed for one-pass-two-labels only by EGRESS-TRACKER-DIRECTION-1 (P3-D9, sequenced right after P3-D4) |
| One pass emits exit + entry (21 of 25 clustered members) | Fixed by P3-D4 (one pass, one term or none) | Fixed by P3-D9b (pass-level dedup at the source); until it ships these readers see both labels |
| Groups of 3+ undercounted; false blank | Fixed if P3-D0 (b) and P3-D2 pass | Not a reader of vision counts |
| 20-53 % of crossings never watched | Watched (P3-D3); a term only through vision direction after the bar | Unchanged (ambiguous stays ambiguous for them) |

Until P3-D9b ships, the census egress-face union (`register_egress_face` / `evict_egress_face`), the arrival
notification, the entered / exited counts and `person_entry_exit_events`, and perimeter keep the tracker's direction,
wrong on about a third of readable crossings: an arrival labelled exit evicts the arriving face from the union.

**Design answers per finding.**

| Finding | Mechanism (code) | Phase 3 answer |
|---|---|---|
| Direction 35 % wrong; 4 arrivals as exits (~12 people) vs 2 exits as entries (3) | Interior-camera timing only (`transit_validator.py:2401-2423`); vision supplies none (`crossing_vision.py:102-103`) | P3-D3 vision direction, P3-D6 scoring, P3-D7 gated use; P3-D9 tracker pass dedup |
| 20 of 101 (11-14), 42 of 79 (11-13) ambiguous, never watched | Skip `crossing_vision.py:616-618` | P3-D3 |
| 21 of 25 clustered members opposite-direction | Direction-keyed dedup (`transit_validator.py:2425-2438`); direction-blind clustering (`crossing_vision.py:664-672`, `:740-749`); `cluster_terms` +n / −n (`crossing_ledger.py:194-203`) | P3-D4 (ledger), P3-D9 (source) |
| Every 3+ group undercounted; 1 false blank; 24 of 41 calls had an empty sampled frame | 4 frames evenly over a 5-466 s event (`CROSSING_VISION_MAX_FRAMES`, `perimeter_enrichment.py:410-427`) | P3-D2 |
| 4 errors, cause unknown | Error string dropped (`crossing_vision.py:917-918`) | P3-D1 |
| 46 calls vs cap 40 | RAM counter reset by two restarts | P3-D5 |

**Why vision cannot fix the tracker's readers.** The tracker's direction is consumed synchronously at resolution,
10-200 s before any vision result; `direction` is a forbidden G3 key (contract §4.2, `transit_validator.py:977-979`).
Readers Phase 3 leaves byte-identical (INV-F3-OWNER):

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
33/41 exact against human truth; healthy for 1-2 people, not for 3+. (3) Vision direction: zero fires (not produced).
(4) Ledger terms: zero term rows since the v5.108.24 boot (ledger `unknown`, anchor blocked by held inputs,
`AUDIT_crossing_pipeline_after_v5_108_24.md` §5), so scoring uses the P2-D6 dark replay, never the live ledger. (5) G3:
`g3_calls = {}` live; the one production G3 caller is `camera_census.py:5319` (exit backfill); `vision_direction` is the
second. **Consumer check:** tables above; forward trace `vision_direction` → G3 attribute → display now → ledger term
after P3-D7 → `guest_vis` → awareness (F-LEAD, which now also requires P3-D6 FLIP-READY) → F-NOTIFY. No path to house
state, access, security or HVAC. New producers get zero-fire trip-wires (P3-D3 step 6).

**Pass (one pass key, owned by the F3 owner; harmonization C5; review H1).** `_match_event`
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

**P3-D0 probe (go/no-go "worth building" gate; read-only plus ≤ `CROSSING_VISION_P3_PROBE_CALLS` (120) Luna calls, decided
in the Phase 3 decisions below).** It is evidence that building is worth it, NOT evidence the runtime bar will pass: at
15/17 the Wilson 95 % lower bound is about 0.66; the runtime bar (0.90) is decided only by P3-D6.
0. **Retention check first:** list which of the 46 11-14 event clips and the recording segments for each E ± 30 s are
   still retrievable through the HA Frigate proxy; commit the fixture
   `quality/tests/fixtures/crossing_vision_door_eval_2026_11_14.json` (46 events: event id, camera, crossing key, tracker
   direction, human count, human direction or `unreadable`, confidence flag, pair id, `one_pass` / `round_trip` /
   `unknown` per pair) BEFORE any replay. Missing clips are listed and excluded, not replaced.
(a) **Volume:** 14 days of `egress_identity_outcome` per day: crossings, ambiguous, simulated calls with ambiguous
   included and clustering applied, crossings with camera peak ≥ 3, HA restarts per day, and the `memory_episodes` row
   count (for the P3-D5 index decision), and the busy-collision rate (crossings that would have found
   `MAX_CONCURRENT` calls in flight; review L4). Output: the cap (P3-D5 rule).
(b) **Direction + count replay** on the retained clips with the P3-D3 prompt, both routes (event clip at 4 and 8 frames;
   recording window if (c) passes). Gates: direction right on ≥ `CROSSING_VISION_P3_DIR_GATE_OK` (15) of the 17
   readable clips AND on ≥ `CROSSING_VISION_P3_DIR_GATE_TRACKER_WRONG_OK` (5) of the 6 tracker-wrong ones; else the
   direction part of P3-D3, P3-D6 and P3-D7 parks (card, revival: a new model or route re-run on the same fixture) and
   watching ambiguous crossings ships count-only. Group gate for P3-D2, on the 4 group clips and the false blank:
   undercount ≤ `CROSSING_VISION_P3_GROUP_UNDERCOUNT_MAX` (1) against the human count, where the human count is a pinned
   integer; the 18:59 clip (human "~9", low confidence) is re-counted frame by frame in step 0 and, if it cannot be
   pinned to one integer, is reported but excluded from pass/fail. Plus no new over-count on the 33 exact clips.
(c) **Route check:** one call with `video_file` = the recording proxy path; record whether llmvision fetches it (status,
   frames returned) and the recording segment lag (time from E + AFTER until the window plays).
(d) **Pass mechanism:** for the 21 opposite pairs and the 4 same-direction pairs of 11-14, the share sharing a pass
   event under BOTH rules: (i) `_match_event`'s group-wide pick, (ii) the Pass rule. **Negative set (review HIGH-1):**
   mine 14 days of `egress_identity_outcome` for opposite-direction crossings on one door group within `CLUSTER_S` whose
   Es are BOTH inside one Frigate event's [start, end]; hand-label each from its clip as `one_pass` or `round_trip`
   (committed in the fixture), mining back up to `CROSSING_VISION_PASS_MINE_MAX_DAYS` (30) days until enough are found.
   Gate for P3-D4 collapse and P3-D9b: at least `CROSSING_VISION_PASS_ROUND_TRIP_MIN_N` (20) hand-labelled one-event
   round trips; under rule (ii) ≥ `CROSSING_VISION_PASS_SAME_EVENT_MIN` (0.80) of `one_pass` pairs share a `pass_key`;
   and the Wilson 95 % UPPER bound of the share of labelled round trips that rule (ii) merges (the one-event residual)
   ≤ `CROSSING_VISION_PASS_ROUND_TRIP_MERGE_UB_MAX` (0.15). Why not 5: at n = 5 even 0 merges has an upper bound of
   ≈ 0.43, so 5 cannot show any ceiling near 0.10. Fewer than 20 = **HOLD**: P3-D4 ships with
   `CROSSING_VISION_LEDGER_PASS_COLLAPSE` False (the kill path; terms as today) and P3-D9b waits; the rest of Phase 3
   is not blocked. Report rule (i) beside it to show the selector bias,
   and the `end is None` share at resolution time. Also the interior near-door events around 14:17:23 / 14:17:54 (the
   audit's open falsifier).
(e) Re-run the 4 error clips once and record llmvision's error text.
- **Acceptance:** `AUDIT_crossing_vision_p3_d0_<date>.md`, one row per item with numbers and every gate verdict; the
  fixture committed first. Discriminates: a model that copies the tracker's bias scores ≤ 11/17 and 0/6; a selector
  artefact shows rule (i) sharing on round trips while rule (ii) does not.

**P3-D1 error text on error rows (Tier 1).** `_run` keeps `reply["error"]`; `_record` writes `error` (≤
`CROSSING_VISION_ERROR_TEXT_MAX_CHARS`, 200) on `error` rows only.
- **Tests:** `test_error_row_carries_error_text`, `test_error_text_truncated`, `test_ok_row_has_no_error_key`.
- **Live:** the next `error` row has a non-empty `error` (with zero errors in the window the test is the proof; the
  README says so).

**P3-D2 event-centred frames and group frames (Tier 2; route and numbers from P3-D0 (b)/(c)).**
1. `CROSSING_VISION_FRAME_ROUTE`: `recording_window` only if P3-D0 (c) passed, else `event_clip` (today). The URL is
   `/api/frigate/<instance>/recording/<camera>/start/<E − BEFORE>/end/<E + AFTER>` where `<camera>` is the matched
   event's Frigate camera name from the event payload (`after.camera`, `crossing_vision.py:562`) and `<instance>` comes
   from the event's MQTT source / `discover_frigate_instance_ids` (`:543-548`) as `_clip_reference` does today; never
   from the egress stem or entity id (registry rule).
2. The call waits until `E + AFTER + CROSSING_VISION_RECORDING_LAG_S` (from P3-D0 (c)) so the window is complete; the
   existing `EVENT_END_WAIT_S` remains the outer bound.
3. **Fallback semantics (one call, always):** failures detectable before the call (no instance, no camera name, the
   window end not yet reachable inside the outer bound) use `event_clip` for that same single call. A fetch failure
   inside llmvision is an `error` row with the P3-D1 text; no second call.
4. Frames: `CROSSING_VISION_MAX_FRAMES` (4) normally; `CROSSING_VISION_GROUP_MAX_FRAMES` (8) when `camera_peak_count`
   ≥ `CROSSING_VISION_GROUP_PEAK_MIN` (3) or the matched event is longer than `CROSSING_VISION_LONG_EVENT_S` (60). One
   call. The branch is crossing-only (keyed on the crossing's `camera_peak_count` inside `crossing_vision.py`);
   `analyze_crossing_frames` keeps taking `max_frames` from its caller, so interior clip callers (VISION-INTERIOR
   D3 / D5) keep their own frame count.
5. Rows record `frame_route`, `frames_requested`, `pipeline_version`.
- **Tests:** `test_recording_window_url_centred_on_crossing`, `test_recording_url_camera_from_event_payload`,
  `test_group_peak_uses_group_frames`, `test_long_event_uses_group_frames`, `test_single_person_keeps_four_frames`,
  `test_precall_route_failure_uses_event_clip_one_call`, `test_fetch_failure_is_error_row_no_second_call`,
  `test_frame_window_stays_in_door_group`, `test_interior_caller_frames_unchanged`.
- **Mutation:** window from event start instead of E → `test_recording_window_url_centred_on_crossing`; camera from
  the stem → `test_recording_url_camera_from_event_payload`; drop the peak branch → `test_group_peak_uses_group_frames`.
- **Live:** within 2 days, ≥ 1 row with `frames_requested = 8` and `ok`; the P3-D6 scorer's exact rate on graded 3+
  crossings reported beside the 11-14 baseline (0 of 4). Discriminates: a change that only helped singles leaves 3+ at 0.

**P3-D3 watch every crossing, record vision's direction (Tier 3: removes an INV-SCOPE clause, adds a production G3
writer).**
1. `_on_egress_event` accepts `ambiguous` while `CROSSING_VISION_WATCH_AMBIGUOUS` is True; same match, cluster, gates,
   cap. The row's existing `direction` key keeps the tracker's value (now possibly `ambiguous`; no new
   `tracker_direction` key); ambiguous rows have `camera_peak_count = None`.
2. Schema and prompt add `direction` ∈ {`in`, `out`, `passing`, `unclear`} from each person's first and last position
   against the door (prompt fixed by P3-D0 (b); `in` = goes into the building). Anything else = `unclear`.
3. **Per-member attributes (review M3).** The vision result describes the analysed event. Each crossing key in the
   request carries its `pass_key` from the bus event / record (P3-D9a; None before P3-D9a ships); `vision_direction` and `vision_people_count` = the result's values
   only if its `pass_key` equals the analysed event's id, else None; `direction_agreement` against the member's OWN
   tracker direction: `agree`, `disagree`, `vision_only` (tracker ambiguous), `unclear` (vision unclear / passing), or
   `not_analysed` (different pass). A real round-trip member never carries the primary's direction.
4. **G3 write.** At the release site (P3-D4 step 2; with collapse off, at the vision outcome), ONE
   `amend_crossing(hass, source_ref, {vision_direction, vision_people_count, direction_agreement}, None,
   camera=<egress camera>, role="vision_direction")` per crossing key; `source_ref` is built from the bus event's
   `egress_camera` and `timestamp` exactly as `transit_validator.py:2525-2527` builds it (`egress:<camera>:<iso>`), not
   parsed from `crossing_key`. A member that joins after its request's release is amended at join time with
   `not_analysed`. Wrapped in try/except, failures counted `vision_amend_failed`. Ring retention (1800 s / 32 per camera,
   `const.py:6707-6708`) exceeds the worst release time (E + 110 s hold, or outcome ≤ E + 45 + 120 + 90 s), so
   `crossing_record_aged_out` is not expected; it is counted, never retried.
5. **Contract and guard (reviews M4, B9, B10; closure MEDIUM-3; harmonization C7).** The build adds
   `vision_direction`, `vision_people_count`, `direction_agreement` (default None) to `CrossingRecord`
   (`transit_validator.py:946-971`) and to `_CROSSING_AMENDABLE_KEYS` (`:980-983`); `pass_key` is a creation-time
   `CrossingRecord` field added by P3-D9a and is NOT amendable. The contract §2.3 field list and §4.2 role list are
   amended once by the orchestrator for all Phase 3 and step-7 fields and roles (harmonization C7), so neither build
   edits the contract. NEW layer-guard row `('R13', 'crossing_vision.py',
   'CrossingVisionShadow._release_terms:amend_crossing')` (max 1; `amend_crossing` is already in `R13_CALLEES`,
   `_layer_guard_engine.py:154-157`) in `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py` beside the
   reserved fast-stage row (`:212`, unchanged). Guard change, as a DELTA against develop at merge time (never an absolute number; other ships move the
   totals, e.g. the music repair merge lowers them by 3): P3-D3 = +1 R13 row, `len(A.ROWS)` +1, `LAYER_ALLOWLIST_TOTAL`
   +1, `LAYER_ALLOWLIST_TOTAL_PROVISIONAL` +1, and the assertion in `test_person_awareness_layer_guard.py:62` set to the
   re-read values; the `("R13", 8)` floor (`:147`) stays valid. Each builder re-reads the current totals on develop
   when it merges. Only P3-D3 changes the totals in this plan (P3-D8, P3-D9a: 0 rows expected); the interior branch's
   delta is 0, so a merge after P3-D3 keeps P3-D3's +1 and never undoes it. The amended signal payload carries the record's
   `person_id` (`transit_validator.py:1281-1290`); today's readers (`sensor.py:5092`, `:5231`) act on
   `exit_backfilled` only; perimeter and sightings do not subscribe.
6. `pipeline_version` (rung-1 `CROSSING_VISION_PIPELINE_VERSION`) on every row; P3-D2 and P3-D3 each bump it.
7. Trip-wires: `crossing_vision_direction_zero` (≥ `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` (10) `ok` rows in 24 h and none
   with `vision_direction` in/out → MEDIUM, RAM latch); `crossing_vision_ambiguous_zero` (≥
   `CROSSING_VISION_AMBIGUOUS_ZERO_MIN` (5) ambiguous bus events counted by the bus listener in 24 h, and 0 rows with
   `direction = ambiguous` → MEDIUM). Bus count, not `egress_identity_outcome` rows (rows and bus differ under dedup).
8. Arrival record and the rung-2 follow-up (P2-D9): an ambiguous crossing produces NO arrival record and no follow-up
   before P3-D7, whatever `vision_direction` says; after P3-D7 an ambiguous crossing with `vision_direction = in` is an
   entry for P2-D9.
- **Tests:** `test_ambiguous_crossing_gets_row_and_call`, `test_watch_ambiguous_off_restores_skip`,
  `test_ambiguous_row_peak_none`, `test_vision_direction_parsed_and_unclear_default`, `test_direction_agreement_cases`
  (5 cases), `test_round_trip_member_not_given_primary_direction`, `test_g3_amend_once_per_crossing_key` (incl. a late
  joiner), `test_g3_source_ref_from_bus_fields`, `test_g3_never_sets_direction` (record `direction`, bus and DB row
  unchanged), `test_amend_failure_counted_never_raises`, `test_amended_signal_ignored_by_exit_backfill_readers`,
  `test_ambiguous_member_in_cluster_no_term_under_tracker`, `test_ambiguous_primary_late_joiner_no_double_term` (B1, see
  P3-D4 step 4), `test_ambiguous_no_arrival_record_before_flip`, `test_direction_zero_pages_once`,
  `test_ambiguous_zero_counts_bus_events`, `test_pipeline_version_on_every_row`, layer guard green with the new row.
  Golden: every pre-existing row key (incl. `direction`) and the bus payload unchanged.
- **Mutation:** keep the old skip → `test_ambiguous_crossing_gets_row_and_call`; pass `direction` into G3 →
  `test_g3_never_sets_direction`; copy the primary's values to all members →
  `test_round_trip_member_not_given_primary_direction`; drop the latch → `test_direction_zero_pages_once`.
- **Live:** within 1 day with crossings: ≥ 1 row with `direction = ambiguous` and a `vision_direction`; `g3_calls`
  shows role `vision_direction`; `get_crossing(<source_ref>)` shows `vision_direction`; Persons Entered / Exited Today
  unchanged in definition. Discriminates: a build that wrote direction into the record would move those counts and the
  `person_entry_exit_events.direction` of a disagreeing crossing; this one moves neither.

**P3-D4 one physical pass = one term or none (Tier 3; only if P3-D0 (d) passed).**
1. Every member takes `pass_key` from the bus event (stamped by P3-D9a, which ships first); crossing vision computes
   none. `CROSSING_VISION_LEDGER_PASS_COLLAPSE` is True after the P3-D0 (d) gate.
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
4. **Late joiner (review B1).** The request stores `term_direction` = the direction of the term actually built (None
   when no term was built, e.g. every folded member ambiguous or a collapsed pass). A member joining after release: if
   it is ambiguous → no term; if its `pass_key` equals a member's of the request → no term (same pass, counted
   `late_member_same_pass`); else if `term_direction` is None or differs from the member's direction → its own camera
   term; else no term. The key of a term built when the primary is ambiguous is the first entry/exit member's key (as
   `cluster_terms` does today).
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
   `CROSSING_VISION_CAP_HEADROOM` (1.5)), ≤ `CROSSING_VISION_DAILY_CALLS_MAX` (200); expected ≈ 100. Cost on Luna is
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
   `MAX_CONCURRENT` + the queue's unflushed crossing rows per restart.
- **Tests:** `test_cap_counter_rehydrated_from_today_rows`, `test_rehydrate_counts_by_ended_at_not_started_at`,
  `test_rehydrate_ignores_yesterday_and_non_call_rows`, `test_rehydrate_slow_db_no_calls_until_done`,
  `test_rehydrate_error_retries_once_then_cap`, `test_dao_reports_error_distinct_from_empty`,
  `test_cap_holds_across_simulated_restart`; DB tests on the production schema.
- **Mutation:** skip the rehydrate → `test_cap_holds_across_simulated_restart`; return `[]`-style success on error →
  `test_dao_reports_error_distinct_from_empty`.
- **Live:** after the deploy restart, `crossing_vision_today.calls` equals the count of today's call rows within one
  minute (not 0). Discriminates: a RAM-only counter reads 0 after the restart.

**P3-D6 direction scoring (Tier 2, read-only; lands in the D4 / P2-D6 scorer build and P2-D10 grading, neither built
yet).** Scored per PASS (`pass_key`; a pass contributes one scored row, review B12), not per member. Oracles, strongest
first: operator grade (P2-D10 grade actions gain `_in` / `_out` / `_pass`); a named resident's `person.*` edge, not_home
→ home in [E − `CROSSING_VISION_DIRECTION_ORACLE_BEFORE_S` (300), E + `_AFTER_S` (60)] = in, home → not_home in
[E − 60, E + 300] = out, with a name attached by F3 or the NVR on that crossing; the P3-D0 fixture. Interior-camera
timing is the tracker's own input and never an oracle. **The oracle never scores groups or guests** (a resident edge
names one resident; grades are capped per day): the bar measures single-resident crossings, and group direction
stays unmeasured until graded group crossings exist. Reports per door / day-night: vision accuracy with Wilson bounds,
tracker accuracy on the same passes, disagreement win rate, ambiguous coverage, the INV-DIR-GATE verdict, scored
passes per day. Disposition `AUDIT_crossing_vision_direction_disposition_<date>.md`, one verdict per direction source:
- **vision:** FLIP-READY (INV-DIR-GATE bar met) / HOLD (bar named, passes still needed at the measured rate) / PARK
  (bound below 0.90 at ≥ `CROSSING_VISION_DIRECTION_PARK_N` (150) scored).
- **tracker (closure MEDIUM-4):** TRACKER-READY when the tracker's own direction accuracy on scored passes has a Wilson
  95 % lower bound ≥ `CROSSING_VISION_DIRECTION_ACC_LB_MIN` (0.90) over ≥ `_SCORED_MIN_N`; else TRACKER-BELOW-BAR. The
  census F-LEAD needs FLIP-READY for vision or TRACKER-READY for the tracker, whichever source the ledger uses. With
  the tracker measured at 11/17 (65 %), TRACKER-READY is not expected, so in practice F-LEAD waits for P3-D7.
**Expected gate time (review G3):** about 5-12 scored passes a day (≤ 5 grades plus named resident edges at ≈ 44 %
attach): 30 scored in 3-6 days; ≥ 15 disagreements at the tracker's 35 % error needs ≈ 43 scored, 4-9 days; the 0.90
lower bound needs ≈ 60 scored at 97 % accuracy (about 1-2 weeks) or ≈ 150 at 95 % (about 2-4 weeks); below ≈ 92 % it
never passes. Sized by error rates; no calendar minimum.
- **Acceptance:** a scorer run on ≥ 1 day of Phase 3 rows writes every number above and reproduces the fixture's 11/17
  tracker accuracy on the 11-14 clips.

**P3-D7 vision direction leads the ledger (Tier 3, gated; operator checkpoint).** A reviewed change of
`CROSSING_VISION_LEDGER_DIRECTION_SOURCE` to `vision` after FLIP-READY; bumps `pipeline_version`; post-flip trip-wire:
the rolling `GO_REGRESSION_DAYS` (14) direction bar below threshold → NM "revert vision direction". Named residual: a
one-event round trip (Pass block) becomes one term in vision's direction, `L` off by one until the anchor; its rate is
the P3-D0 (d) merge share.
- **Tests:** `test_direction_source_vision_uses_vision_direction`, `test_vision_unclear_falls_back_to_tracker`,
  `test_ambiguous_with_vision_in_gets_entry_term`, `test_direction_regression_pages_revert`.
- **Live:** after the flip, ≥ 1 term row with `direction_source = vision` on a `direction_agreement = disagree` pass
  whose term sign follows vision.

**P3-D8 the anchor honours the room's stuck exclusion (Tier 2; harmonization C1; OPERATOR DECISION PENDING,
recommended yes; sequenced before P3-D3).** Why: the ledger has never been `known` since boot; the held set on an AWAY
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
   switch `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK` (rung 1, True after the operator's yes; False = today's rule).
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

**P3-D9 EGRESS-TRACKER-DIRECTION-1: the pass key at the source, then pass-level dedup (Tier 3, own plan; carded,
planned; harmonization C5, review G1).** The F3 owner owns the one pass key; P3-D4, P3-D3, P3-D6, interior D5 and NVR
W2 consume it. Two steps:
- **P3-D9a pass-key producer (before P3-D4; additive, byte-identical for every existing reader).** At resolution
  `_resolve_direction` computes `pass_identity(...)` (the Pass rule) from a tracker-owned Frigate person-event ring
  (`register_frigate_consumer`) and stamps `pass_key` on the new `CrossingRecord` (creation-time field) and as an
  additive bus key, beside `peak_person_count`. Golden test: every pre-existing bus key and DB column unchanged.
  Lifecycle: the tracker's `register_frigate_consumer` (`frigate_ingress.py:582`; its first Frigate consumer) is
  unsubscribed in the tracker's teardown; the ring keeps `CROSSING_VISION_TRACKER_FRIGATE_RING` events per Frigate
  camera, pruned by count and age on every append. Tests `test_tracker_frigate_consumer_unsubscribed_on_teardown`,
  `test_tracker_frigate_ring_bounded`, `test_pass_key_on_bus_and_record`. Guard delta: 0 rows expected (a consumer
  registration inside the F3 owner; the build confirms).
  Gated only on P3-D0 (d)'s rule (ii) measurement being reported (not on its pass verdict): the key is a value, not
  a behaviour.
- **P3-D9b pass-level dedup (after P3-D4; gated on P3-D0 (d) PASS including the round-trip merge bound).** The
  direction-keyed dedup (`transit_validator.py:2425-2438`) gains a pass check, with `pass_identity` computed BEFORE the
  dedup block (the dedup `return` is at `:2428-2434`; P3-D9a's stamp at record creation `:2515` is too late for it): a crossing whose `pass_key` equals that
  of a crossing already resolved on the same door group inside `DOOR_STEM_DEDUP_S` is not emitted again, whatever its
  direction. That fixes "one pass emits both" for every reader (notify, census egress-face union, entered / exited,
  DB, perimeter, sightings, crossing vision). It does not choose which label is right; that stays the interior-timing
  rule until vision's scored direction shows a better source. Named residual: the one-event round trip (Pass block)
  loses its re-entry for every reader. Baseline: the P3-D0 (a)/(d) numbers and the P3-D6 tracker verdict.
Its own Tier-3 plan reads `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` completely and names every synchronous reader's
change. Until P3-D9a ships, `pass_key` is None everywhere and P3-D4 collapses nothing.

**Phase 3 decisions (taken by the orchestrator 2026-11-15 on the recommended defaults; the operator may override).**
1. P3-D0 may spend up to 120 Luna calls on the replay.
2. A collapsed pass gives no ledger term until the direction gate passes (P3-D4 step 5, W9-W11 name the effect).
3. The 110 s term hold applies only to the ledger and awareness path; the arrival notification, the census trust view
   and AWAY are untouched.
4. The cap default is sized from the P3-D0 (a) volume probe.
5. EGRESS-TRACKER-DIRECTION-1 is filed now and sequenced (P3-D9a before P3-D4, P3-D9b after it), not parked.
6. **Operator-visible tradeoff (closure MEDIUM-4):** census F-LEAD now needs a direction verdict (P3-D6). The tracker is
   measured at 65 %, so in practice F-LEAD waits for P3-D7 (vision FLIP-READY, about 1-4 weeks of scored crossings
   after P3-D3). The operator may instead accept the tracker's signs for F-LEAD.
7. **Pending operator decision:** P3-D8, a stuck-excluded live input stops holding the anchor while a dead input still
   holds (recommended yes).
8. **M2 (taken by the orchestrator, operator may override):** the one-event round-trip gate needs ≥ 20 hand-labelled
   round trips (mined from up to 30 days) and a Wilson upper bound ≤ 0.15; below 20 the verdict is HOLD and P3-D4
   ships with collapse off rather than blocking Phase 3.

Tier: P3-D0 probe; P3-D1 Tier 1; P3-D2, P3-D6, P3-D8 Tier 2; P3-D5 Tier 2-DB; P3-D3, P3-D4, P3-D7, P3-D9 Tier 3 (ledger input
surface, a production G3 writer, the F3 source): two plan reviews incl. framing G, four code reviews, orchestrator
re-grep of every term-construction site (`cluster_terms`, `_release_terms`, `_ledger_terms`, `_join_cluster` late
branch, the no-request paths `:620-622`, `:676-707`, the call-time paths `:869-882`, `:906`, `:928`, `:935-939`) and a real
source mutation of the INV-DIR-GATE site, operator checkpoint before deploy.

## 6. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `switch.ura_crossing_vision_shadow` | off at ship | 3 | Master; off = INV-OFF |
| `LLMVISION_ENRICHMENT_KILL` (REUSED) | False | 1 | All llmvision use |
| `CROSSING_VISION_DAILY_CALLS` | 40 → P3-D0 (a) value (ceil(max simulated daily calls × 1.5), ≤ 200; expected ≈ 100) | 3 (Number) | 0 = no calls; counter rehydrated at setup from today's call rows (P3-D5), local midnight |
| `CROSSING_VISION_MODEL` | `gpt-4o-mini` → `gpt-6-luna` (P2-D1) | 1 | Dry call first |
| `CONF_CROSSING_VISION_PROVIDER_ID` | empty = install default if present, else perimeter provider | 2 | Portable provider |
| `CROSSING_VISION_PROVIDER_ID` (kept) | `01M7B731T26P2HXVW77AQR62PP` | 1 | Used only when the option is empty AND this id is an `llmvision` entry on the install (P2-D1) |
| `CROSSING_VISION_MAX_FRAMES` / `_TARGET_WIDTH` | 4 / 768 | 1 | D0b / D0-V |
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
| `CROSSING_VISION_FRAME_ROUTE` | `event_clip` → `recording_window` only if P3-D0 (c) passes | 1 | P3-D2; `event_clip` = today's route |
| `CROSSING_VISION_FRAME_WINDOW_BEFORE_S` / `_AFTER_S` | 10 / 15 (set by P3-D0 (b)) | 1 | Recording window around E; covers the ±10 s match and the walk-up |
| `CROSSING_VISION_GROUP_PEAK_MIN` / `_GROUP_MAX_FRAMES` / `_LONG_EVENT_S` | 3 / 8 / 60 | 1 | Every 3+ group was undercounted at 4 frames; still one call; crossing-only (interior callers pass their own `max_frames`); group max frames 4 = off |
| `CROSSING_VISION_RECORDING_LAG_S` | from P3-D0 (c) | 1 | Wait so the recording window is complete; bounded by `EVENT_END_WAIT_S` |
| `CROSSING_VISION_PASS_EVENT_PAD_S` | 2 | 1 | Pass rule: E inside the pass event's [start, end] ± pad; 0 = strict |
| `CROSSING_VISION_AMBIGUOUS_ZERO_MIN` | 5 | 1 | `crossing_vision_ambiguous_zero` trip-wire (bus count); 0 = off |
| `CROSSING_VISION_CAP_HEADROOM` | 1.5 | probe rule (plan number) | P3-D5 cap sizing |
| `CROSSING_VISION_CAP_REHYDRATE_TIMEOUT_S` / `_RETRY_S` | 30 / 60 | 1 | P3-D5 background rehydrate; failure twice = counter stays at cap until midnight |
| `CROSSING_VISION_DIRECTION_ORACLE_BEFORE_S` / `_AFTER_S` | 300 / 60 (mirrored for exits) | 1 | P3-D6 resident-edge oracle window (same as the arrival-credit window) |
| `CROSSING_VISION_DIRECTION_PARK_N` | 150 | 1 | P3-D6 PARK rule |
| `CROSSING_VISION_P3_DIR_GATE_OK` / `_TRACKER_WRONG_OK` / `_GROUP_UNDERCOUNT_MAX` | 15 of 17 / 5 of 6 / 1 | probe gate (plan numbers) | P3-D0 (b); a "worth building" gate, not the runtime bar |
| `CROSSING_VISION_WATCH_AMBIGUOUS` | True | 1 | P3-D3; False = the pre-Phase-3 skip |
| `CROSSING_VISION_PIPELINE_VERSION` | bumped per Phase 3 ship | 1 | Separates rows in every bar |
| `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` | 10 | 1 | `crossing_vision_direction_zero` trip-wire; 0 = off |
| `CROSSING_VISION_LEDGER_PASS_COLLAPSE` | False until P3-D0 (d) passes, then True | 1 | P3-D4; False = per-member terms as before |
| `CROSSING_VISION_PASS_SAME_EVENT_MIN` | 0.80 | probe gate (plan number, not runtime) | P3-D0 (d) |
| `CROSSING_VISION_PASS_ROUND_TRIP_MIN_N` | 20 | probe gate | P3-D0 (d): fewer hand-labelled one-event round trips = HOLD (collapse off, P3-D9b waits) |
| `CROSSING_VISION_PASS_ROUND_TRIP_MERGE_UB_MAX` | 0.15 (Wilson 95 % upper bound) | probe gate | P3-D0 (d): one-event round-trip merge share; above it collapse stays off and P3-D9b does not ship |
| `CROSSING_VISION_PASS_MINE_MAX_DAYS` | 30 | probe gate | P3-D0 (d) mining horizon |
| `CROSSING_VISION_ANCHOR_STUCK_CLIENTS` | {`p22_continuous`, `chatter`, `stuck_dutycycle`} | 1 | P3-D8: exclusion clients that stop an `on` input holding; never the camera-stream client |
| `CROSSING_VISION_TRACKER_FRIGATE_RING` | 20 per Frigate camera, 1800 s | 1 | P3-D9a tracker event ring bound (count and age, same as the crossing ring age) |
| `CROSSING_VISION_DAILY_CALLS_MAX` (existing, `const.py:3569`) | 200 | 1 | Upper bound of the cap Number |
| `CROSSING_VISION_CAP_REHYDRATE_INDEX_ROWS` | 200 000 | probe rule (plan number) | P3-D5: above it the build adds `idx_episodes_type_ended` |
| `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK` | True after operator yes (P3-D8) | 1 | False = a stuck-excluded live `on` input still holds |
| `CROSSING_VISION_TERM_HOLD_S` | 110 (cluster 60 + entry window 45 + 5) | 1 | P3-D4 hold; must be ≤ 2 × `CLUSTER_S` (asserted at setup); 0 = build terms at the vision outcome (pre-Phase-3) |
| `CROSSING_VISION_LEDGER_DIRECTION_SOURCE` | `tracker` | 1 (reviewed flip, P3-D7) | INV-DIR-GATE; `vision` only after FLIP-READY |
| `CROSSING_VISION_DIRECTION_ACC_LB_MIN` / `_SCORED_MIN_N` | 0.90 / 30 | 1 | Wilson 95 % lower bound on oracle-scored crossings; sized from the measured 35 % tracker error, not days |
| `CROSSING_VISION_DIRECTION_DISAGREE_WIN_MIN` / `_DISAGREE_MIN_N` | 0.80 / 15 | 1 | Vision right where it and the tracker disagree (mirrors F-LEAD's 80 %) |
| `CROSSING_VISION_P3_PROBE_CALLS` | 120 | probe budget | P3-D0 model calls |

Census-side knobs (class set, F-LEAD, notify bars, bars a-e) live in the census plan.

## 7. Dependencies and sequence

1. Phase 1 (built): three framing-disjoint reviews (A correctness; B async lifecycle, teardown, write queue, restart,
   `wait_for` cancellation into llmvision, payload shape per listener incl. `person_sighting.py` and the recorder; C
   per-site mutation) + README; operator turns the switch on; live rows; README write-back.
2. P2-D0 probe and P2-D1 Luna now; operator schedules P2-D7.
3. Read-API ship 1; then P2-D2 / P2-D3 (with the census plan's CD1), P2-D9, P2-D10 in parallel with collection; ship dark.
4. P2-D8 only after P2-D0 (vi) passes.
5. P2-D6 disposition after ≥ 7 days and bar minimums; flips per the census plan's ladder.
6. Phase 3, in order: P3-D0 probe (retention check and fixture first; gates the P3-D2 route, the P3-D3 direction part,
   P3-D4 and P3-D9b). P3-D8 (anchor honours stuck exclusion, operator yes pending) before P3-D3, because without an
   anchor no ledger use of Phase 3 can be measured. P3-D1 + P3-D5 any time. P3-D3 (direction first: it dominates the
   net, audit §3c) with P3-D2. **P3-D9a (tracker pass key) before P3-D4**, so the ledger consumes the one F3-owned key
   and never computes its own. P3-D4. **P3-D9b (tracker pass dedup) right after P3-D4**, gated on P3-D0 (d) incl. the
   round-trip merge bound. P3-D6 with the scorer build (P2-D10 grading built there, harmonization C10). P3-D7 only after
   FLIP-READY. The census plan's F-LEAD cannot promote before a P3-D6 direction verdict for the source in use (census
   plan §3.2, amended with this plan); the `pipeline_version` bumps in P3-D2, P3-D3 and P3-D7 each restart the census
   bars a-e and the F-LEAD windows. Phase 3 builds never change the `deconflict_house` signature (harmonization C2;
   interior ship 5 owns that).

## 8. Non-goals

Vision supplying a name or any `identity_provenance = "vision"`; vision rewriting the tracker's `direction` or any
reader of it (notify, census egress-face union, DB rows, perimeter, sightings: INV-F3-OWNER; the tracker fix is
EGRESS-TRACKER-DIRECTION-1); vision direction in a ledger term before the INV-DIR-GATE bar; a second model call per
crossing (group frames ride the same call); naming unenrolled people (charter 11-15); B-stage chains across cameras and
interior head counts (VISION-INTERIOR-SIGHTINGS-1); crossings with no matched Frigate event (all four door cameras run Frigate; 26 % unmatched at ±10 s, 17 % at ±30 s,
12 % at ±60 s per `AUDIT_crossing_vision_d0_2026_11_13.md`; recorded `no_frigate_event`; first lever is widening
`CROSSING_VISION_EVENT_MATCH_S`, then a probe of Protect event clips; revival: `no_frigate_event` > 25 % of a door
group's crossings); two models per crossing; ledger replay across restarts; frame
extraction inside URA; any house-state, security, lock, perimeter or HVAC change (the census plan's ladder governs reach);
the parked Rev 4 guard A / veto B (operator: stay parked).
