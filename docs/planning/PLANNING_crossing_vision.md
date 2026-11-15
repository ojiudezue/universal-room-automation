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
| Corrected direction as an F3 attribute | REUSED G3 | `amend_crossing` `transit_validator.py:1036`, `attach_crossing_attribute` `:1232`; `direction` is a FORBIDDEN key (`_CROSSING_FORBIDDEN_KEYS` `:977-979`), so the tracker's own `direction` is never rewritten. NEW additive fields `vision_direction`, `vision_people_count`, `direction_agreement`, `pass_key` on `CrossingRecord` (`:946-971`) + `_CROSSING_AMENDABLE_KEYS` (`:980-983`): 0 hits for `vision_direction` / `direction_agreement` in code or plans |
| Ring lookup of an ambiguous crossing | REUSED | Ambiguous crossings ARE stored in the ring (`_record_crossing` is unconditional, `transit_validator.py:2514-2530`); `source_ref = egress:<camera>:<iso>` (`:2525-2527`), derivable from the vision `crossing_key = <camera>@<iso>` (`crossing_vision.py:632`) |
| Watching ambiguous crossings | CHANGE of an existing skip | `crossing_vision.py:616-618` |
| Opposite-pass collapse | EXTEND `cluster_terms` | `crossing_ledger.py:172-203` (mixed directions today give one camera term per member); `_join_cluster` late-joiner branch `crossing_vision.py:740-749`; cluster loop `:664-672`. 0 hits for `PAIR_COLLAPSE` / `TERM_HOLD` |
| Event-centred frames | REUSED proxy route | HA Frigate `RecordingProxyView` `/api/frigate/<instance>/recording/<camera>/start/<s>/end/<e>` (`/config/custom_components/frigate/views.py:245-266`, read on the live mount) proxies Frigate `api/<camera>/start/<s>/end/<e>/clip.mp4`. Whether llmvision's `video_file` can fetch it (it is an authenticated view; the notifications view we use today is not) is UNVERIFIED: P3-D0 (c) |
| More frames for groups | REUSED knob path | `analyze_crossing_frames(max_frames=...)` `perimeter_enrichment.py:410-427`; `CROSSING_VISION_MAX_FRAMES` `const.py:3594` |
| Error text on error rows | REUSED value already returned | `analyze_crossing_frames` returns `{"status": error, "error": str(exc)[:200]}` (`perimeter_enrichment.py:452-457`); `_run` drops it (`crossing_vision.py:917-918`, `parsed = {"outcome": OUTCOME_ERROR}`) |
| Restart-durable cap counter | REUSED rehydration pattern | P2-D10 metric sensors rehydrate RAM rings from shadow rows at setup (§5 P2-D10); counter today is RAM (`crossing_vision.py:287`, `:495`, `:884`); cap Number `number.py:4309`, max `CROSSING_VISION_DAILY_CALLS_MAX` 200 (`const.py:3569`) |
| Direction scoring | EXTEND D4 / P2-D6 scorer + P2-D10 grading | NOT BUILT: no `scripts/probes/crossing_vision_score_weekly.py`, 0 hits for `GRADE_URA` in code. Phase 3 scoring therefore lands in the scorer build, not as a new tool |
| `pipeline_version` on rows | FINDING | Plan §5 D1.9 and P2-D8 say rows carry it; 0 hits in code. P3-D3 adds it (needed to separate pre/post-Phase-3 rows in every bar) |
| Card overlap | sweep | Board: VISION-AMBIGUOUS-CROSSINGS-1, DOOR-VISION-GROUP-UNDERCOUNT-1 (this plan); EGRESS-DIRECTION-AWARE-IDENTITY-1 changes identity attach on the same `_resolve_direction`, not direction (arc map M3); CENSUS-DECONFLICTION-LEDGER-1 consumes the terms. No card fixes the tracker's direction itself: P3 proposes EGRESS-TRACKER-DIRECTION-1 (§5 P3-D7) |

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

## 2. F1-F5: produced and consumed

| Fact | Role |
|---|---|
| F1 | consumed: residency departures (ledger reconcile), `R` handed in by the census |
| F2 | none written here. The ledger hands `guest_vis` to the census through `census_tick`; the census owns F2 |
| F3 (owner `EgressDirectionTracker`, `transit_validator.py:1079`) | consumed: `ura_person_egress_event` (entry, exit AND, from Phase 3, ambiguous) and the crossing ring. PRODUCED as attributes of the crossing, written only through G3 `amend_crossing` (role `vision_direction`): `vision_direction`, `vision_people_count`, `direction_agreement`, `pass_key`; plus the vision count, `term_source`, the arrival record `n` / `k` / `guests_unnamed`. The tracker's `direction` is never rewritten (forbidden G3 key). No second crossing record, no second identity attach |
| F4 | none: vision names no one and emits no sighting |
| F5 | none produced; the one D2 site may annotate an arrival tied to a crossing with `n` / `guests_unnamed` |

## 3. Readers by consumer class

| Output | Readers | Class |
|---|---|---|
| `crossing_vision_shadow` rows, counters, `crossing_vision_today` / `_last` attributes | weekly scorer, trip-wires, diagnostic attribute; generic pre-existing readers `URAMemoryStatusSensor` (`get_memory_status_counts`, `database.py:11152`), `memory_query` (node-keyed), writer-health check (`database.py:11491`) | display |
| Ledger (`guest_vis`, healthy) | the census only, through `census_tick` | F2 input (census plan) |
| F3 attributes `vision_direction` / `direction_agreement` / `pass_key` (G3) | read API `get_crossing` / `get_crossings_since` (`presence.py:6142-6155`), `crossing_vision_last`; the ledger reads its own copy, used for a term only when `CROSSING_VISION_LEDGER_DIRECTION_SOURCE = vision` (INV-DIR-GATE). `SIGNAL_EGRESS_RECORD_AMENDED` readers ignore the role (`sensor.py:5092`, `:5231` act on `exit_backfilled` only) | display (ledger after the gate) |
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
  at 95 % near 150; below about 92 % it never clears. Break it with a sequence where a `vision_direction` value moves a
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
  synchronously at direction resolution (`transit_validator.py:2228`); the count goes in a separate quiet follow-up.

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
   (`pass_key`: opposite-direction members whose own matched Frigate event is the same event id, P3-D4); one pass gives
   ONE term: under `tracker` a pass whose members disagree gives no term (`pair_collapsed`, both directions recorded),
   under `vision` it takes the vision direction. Then, as before: one term with the primary's count if all remaining
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
INV-DIR-GATE; the census ladder (census plan §3.2) unchanged.

**What the evaluation found, and the design answer.**

| Finding (`AUDIT_door_vision_accuracy_2026_11_14.md`) | Mechanism (code) | Phase 3 answer |
|---|---|---|
| Direction wrong on 6 of 17 readable clips (35 %), 4 arrivals labelled exit (~12 people) vs 2 exits labelled entry (3); ~9-person swing in to out | Direction comes only from interior-camera timing (`transit_validator.py:2401-2423`); vision supplies none (`crossing_vision.py:102-103`) | Vision states a direction on every call (P3-D3); scored against later evidence (P3-D6); used for terms only after the bar (P3-D7, INV-DIR-GATE) |
| 20 of 101 (11-14) and 42 of 79 (11-13) crossings `direction_ambiguous`, never watched | Skip `crossing_vision.py:616-618` | Watch them (P3-D3); a term only through vision's direction after the bar |
| 21 of 25 clustered members are opposite-direction; mostly one pass emitting exit + entry (8 same device twice, 8 two cameras of one door, 3 W1 twins, 2 Doorbell Lite pair) | Direction-keyed dedup never merges opposite labels (`transit_validator.py:2425-2438`); clustering is direction-blind (`crossing_vision.py:664-672`, `:740-749`); `cluster_terms` gives +n and −n (`crossing_ledger.py:194-203`) | Collapse a physical pass to one term (P3-D4) |
| Every group of 3+ undercounted (18:59 4 vs ~9; 18:43 6 vs 7; 21:24 2 vs 4; 21:28 2 vs 3); one false blank (4 people, 1 frame returned); 24 of 41 calls had an empty sampled frame | 4 frames evenly over the whole event, 5-466 s (`CROSSING_VISION_MAX_FRAMES` 4, `perimeter_enrichment.py:410-427`) | Event-centred frames + more frames when the camera peak ≥ 3 (P3-D2) |
| 4 errors at ~2.2 s, cause unknown | Error string dropped at `crossing_vision.py:917-918` | Store it (P3-D1) |
| 46 calls vs cap 40 | RAM counter reset by two restarts | Size from measured volume; counter rehydrated (P3-D5) |

**Does Phase 3 fix the tracker's direction for every consumer? No.** It gives vision a corrected direction as an F3
attribute; it does not change `EgressDirectionTracker`'s direction. Reasons: the tracker's direction is consumed
synchronously at resolution, 10-200 s before any vision result; `direction` is a forbidden G3 key (contract §4.2,
`transit_validator.py:977-979`), and making it amendable would retro-change readers that already acted. Readers of the
tracker's direction that Phase 3 leaves byte-identical (INV-F3-OWNER), all wrong whenever the tracker is wrong:

| Reader | Site | Class |
|---|---|---|
| Arrival / departure notification | `_arrival_departure_notify` `transit_validator.py:2548`, `:2917` | notification |
| Census egress-face union: entry registers, exit evicts | `register_egress_face` / `evict_egress_face` `transit_validator.py:2575-2600` | F2 trust input |
| `person_entry_exit_events` rows (and the Persons Entered / Exited Today sensors, last-entry / last-exit sensors) | `log_entry_exit_event` `:2611-2630`; bus listeners `sensor.py:4915`, `:5046`, `:5160`, `:5210` | display |
| Perimeter identity cache, scoped egress mute (stored entry/exit crossing) | `perimeter_alert.py:1110`; manual, scoped egress mute | security |
| Sighting producer | `person_sighting.py:155` | F4 |
| Read API crossing getters | `presence.py:6068-6155` | display (they gain the vision attributes, not a new direction) |

Readers that DO change: the crossing ledger (P3-D4 collapse now; vision direction only after P3-D7), the awareness
view through the ledger (F-LEAD gated, census plan), `crossing_vision_last` and the read-API attributes (display).
Fixing the tracker for every consumer is its own card, EGRESS-TRACKER-DIRECTION-1 (P3-D7 files it): candidate levers
are a pass-level dedup (one physical pass = one resolved crossing) and vision's scored direction as the oracle that
measures the tracker; it touches notify, census, perimeter and DB at once and is Tier 3 on its own.

**Producer check.** (1) Tracker direction: fired 101 times on 11-14 (81 resolved, 20 ambiguous) and 79 on 11-13 (42
ambiguous); arithmetic = nearest interior event in [−30 s, +45 s]; health = 35 % wrong on readable clips, so it is NOT
an oracle for vision (the D0 51 % agreement measured the validator, not vision). (2) Vision count: 46 calls on 11-14, 41
`ok`, exact 33/41 against human truth; healthy for 1-2 people, unhealthy for 3+. (3) Vision direction: zero fires (not
produced). (4) Ledger terms: zero term rows since the v5.108.24 boot (ledger `unknown`, anchor blocked by held inputs,
`AUDIT_crossing_pipeline_after_v5_108_24.md` §5); so scoring cannot depend on the live ledger: the P2-D6 dark replay
scores from shadow rows. (5) G3: `g3_calls = {}` live, so the `vision_direction` role is the first G3 writer in
production. **Consumer check:** above table; forward trace: `vision_direction` → G3 attribute → display now → ledger
term after P3-D7 → `guest_vis` → awareness (F-LEAD) → F-NOTIFY. No path to house state, access, security or HVAC.
New producers get zero-fire trip-wires (P3-D3).

**P3-D0 probe (go/no-go gate; read-only plus ≤ `CROSSING_VISION_P3_PROBE_CALLS` (120) model calls on the Luna entry,
operator approves the spend).** Hand-built fixture first: `quality/tests/fixtures/crossing_vision_door_eval_2026_11_14.json`
from the audit table (46 events: event id, camera, crossing key, tracker direction, human count, human direction or
`unreadable`, confidence flag). Items:
(a) volume: 14 days of `egress_identity_outcome` per day: crossings, ambiguous, simulated calls with ambiguous included
and clustering applied, crossings with camera peak ≥ 3, HA restarts per day; output the cap (P3-D5 rule);
(b) direction + count replay on the 46 clips with the P3-D3 prompt, both frame routes (whole-event clip with 4 and 8
frames; recording window if (c) passes). **Gate:** vision direction right on ≥ 15 of the 17 readable clips AND on ≥ 5
of the 6 tracker-wrong ones; else the direction part of P3-D3 and P3-D6/D7 park (card + revival: a new model or route
re-run on the same fixture) and watching ambiguous crossings ships count-only. Group gate for P3-D2: on the 4 group
clips + the false blank, undercount ≤ 1 person on each, and no new over-count on the 33 exact clips;
(c) route check: one call with `video_file` = the recording proxy path; record whether llmvision fetches it (HTTP
status, frames returned). Fail = the event-clip route with more frames;
(d) pass mechanism: for the 21 opposite pairs, whether each member's OWN matched Frigate event is the same event id
(share), plus the interior near-door events around 14:17:23 / 14:17:54 (the audit's open falsifier). **Gate for
P3-D4:** ≥ `CROSSING_VISION_PAIR_SAME_EVENT_MIN` (0.80) of hand-confirmed one-pass pairs share an event id AND no
hand-confirmed round trip shares one; else P3-D4 parks with the measured share;
(e) re-run the 4 error clips once and record llmvision's error text.
- **Acceptance:** `AUDIT_crossing_vision_p3_d0_<date>.md`, one row per item with numbers and the gate verdicts; the
  fixture committed. Discriminates: a pass on (b) with the tracker-wrong clips right cannot come from a model that
  copies the tracker's bias (which would score ≤ 11/17 and 0/6).

**P3-D1 error text on error rows (Tier 1).** `_run` keeps `reply["error"]` and `_record` writes `error` (≤
`CROSSING_VISION_ERROR_TEXT_MAX_CHARS`, 200) on `error` rows; nothing else changes.
- **Tests:** `test_error_row_carries_error_text`, `test_error_text_truncated`, `test_ok_row_has_no_error_key`.
- **Live:** the next `error` row has a non-empty `error` attribute (or, with zero errors in the window, the test is
  the proof; say so in the README).

**P3-D2 event-centred frames and group frames (Tier 2; route and numbers from P3-D0 (b)/(c)).**
1. Route `CROSSING_VISION_FRAME_ROUTE`: `recording_window` = `video_file =
   /api/frigate/<instance>/recording/<event_camera>/start/<E − BEFORE>/end/<E + AFTER>` on the matched event's camera
   (same door group, INV-SCOPE), only if P3-D0 (c) passed; else `event_clip` (today's route).
2. Frames: `CROSSING_VISION_MAX_FRAMES` (4) normally; `CROSSING_VISION_GROUP_MAX_FRAMES` (8) when the crossing's
   `camera_peak_count` ≥ `CROSSING_VISION_GROUP_PEAK_MIN` (3) or the matched event is longer than
   `CROSSING_VISION_LONG_EVENT_S` (60). Same single call (no second call, no cap cost).
3. A `no_clip_url` or route failure on `recording_window` falls back to `event_clip` in the same request (one call).
4. Rows record `frame_route`, `frames_requested`, `pipeline_version` (P3-D3).
- **Tests:** `test_recording_window_url_centred_on_crossing`, `test_group_peak_uses_group_frames`,
  `test_long_event_uses_group_frames`, `test_single_person_keeps_four_frames`, `test_recording_route_fallback_one_call`,
  `test_frame_window_stays_in_door_group`.
- **Mutation:** compute the window from event start instead of E → `test_recording_window_url_centred_on_crossing`;
  drop the peak branch → `test_group_peak_uses_group_frames`.
- **Live:** within 2 days, ≥ 1 row with `frames_requested = 8` and `ok`; the P3-D6 scorer's group exact rate on graded
  3+ crossings reported beside the 11-14 baseline (0 of 4). Discriminates: a frame change that only helped singles
  leaves the 3+ rate at 0.

**P3-D3 watch every crossing, record vision's direction (Tier 3: removes an INV-SCOPE clause, adds the first G3
writer in production).**
1. `_on_egress_event` accepts `ambiguous` while `CROSSING_VISION_WATCH_AMBIGUOUS` is True; same match, cluster, gates,
   cap; row carries `tracker_direction` (entry / exit / ambiguous); ambiguous rows have `camera_peak_count = None`.
2. Schema and prompt add `direction` ∈ {`in`, `out`, `passing`, `unclear`} from the first and last position of each
   person against the door (prompt text fixed by P3-D0 (b); "in" = goes into the building). Parsed as
   `vision_direction`; anything else = `unclear`. `direction_agreement` ∈ {`agree`, `disagree`, `vision_only` (tracker
   ambiguous), `unclear`}.
3. After the row: ONE `amend_crossing(hass, "egress:<camera>:<iso>", {vision_direction, vision_people_count,
   direction_agreement, pass_key}, None, camera=<egress camera>, role="vision_direction")` per crossing key (cluster
   members included, with the primary's vision values). Additive `CrossingRecord` fields default None; the contract
   §2.3 additive-field list and §4.2 role list are updated in the same build commit. A record aged out of the ring is
   counted (`crossing_record_aged_out`), never retried.
4. Rows carry `pipeline_version` (rung-1 `CROSSING_VISION_PIPELINE_VERSION`, bumped by P3-D2/P3-D3), so the scorer
   never mixes pre- and post-Phase-3 rows in a bar.
5. Trip-wires: `crossing_vision_direction_zero` (≥ `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` (10) `ok` rows in 24 h and
   none with `vision_direction` in/out → MEDIUM, RAM latch) and `crossing_vision_ambiguous_zero` (≥ 5 ambiguous
   crossings in 24 h and 0 rows with `tracker_direction = ambiguous` → MEDIUM), same machinery as D3.
- **Tests:** `test_ambiguous_crossing_gets_row_and_call`, `test_watch_ambiguous_off_restores_skip`,
  `test_ambiguous_row_peak_none`, `test_vision_direction_parsed_and_unclear_default`,
  `test_direction_agreement_cases` (4 cases), `test_g3_amend_once_per_crossing_key`,
  `test_g3_never_sets_direction` (the record's `direction`, the bus and the DB row unchanged),
  `test_aged_out_record_counted_not_retried`, `test_amended_signal_ignored_by_exit_backfill_readers`,
  `test_ambiguous_member_in_cluster_no_term_under_tracker`, `test_direction_zero_pages_once`,
  `test_pipeline_version_on_every_row`. Golden: every pre-existing row key and the bus payload unchanged.
- **Mutation:** keep the old skip → `test_ambiguous_crossing_gets_row_and_call`; pass `direction` into G3 →
  `test_g3_never_sets_direction`; drop the latch → `test_direction_zero_pages_once`.
- **Live:** within 1 day with crossings: ≥ 1 row with `tracker_direction = ambiguous` and a `vision_direction`; ≥ 1
  G3 call with role `vision_direction` in the layer diagnostics (`g3_calls`); `read_api.get_crossing(<source_ref>)`
  shows `vision_direction`; `persons_entered_today` / `_exited_today` unchanged in definition (no ambiguous crossing
  counted). Discriminates: a build that wrote direction into the record would change the entered/exited counts and
  the `person_entry_exit_events` row direction for a disagreeing crossing; this one changes neither.

**P3-D4 one physical pass = one term (Tier 3; only if P3-D0 (d) passed).**
1. Every crossing matches its OWN Frigate event before the cluster loop (`_match_event`, RAM ring, no call); the
   member dict keeps `event_id`. `pass_key` = that event id; members of one cluster with the same `pass_key` and
   opposite tracker directions form one pass (`CROSSING_VISION_LEDGER_PAIR_COLLAPSE`, True after the gate).
2. Term hold: a request's terms are built at max(vision outcome, E_primary + `CROSSING_VISION_TERM_HOLD_S`) so every
   member that can join has joined (members arrive at bus time ≈ E + up to `EGRESS_ENTRY_WINDOW_SECONDS` 45, cluster
   window 60). Discharge: one tracked timer per request; teardown cancels (ledger RAM, nothing lost that a restart
   would keep); a member arriving after the hold keeps today's late-joiner rule (`crossing_vision.py:740-749`), counted
   `late_member`. The arrival notification is untouched (INV-NOTIFY-LATENCY). The hold delays only the ledger's
   display value by ≤ 110 s, inside the existing ≈ 210 s reconcile delay.
3. `cluster_terms` gains the pass step (P2-D2 step 3 as rewritten): under `tracker` a collapsed pass gives no term
   (recorded `pair_collapsed` with both directions and `n`); under `vision` one term in vision's direction.
- **Tests:** `test_same_event_opposite_pair_one_pass_no_term_under_tracker`,
  `test_same_event_opposite_pair_one_term_under_vision`, `test_different_events_round_trip_keeps_two_terms`,
  `test_term_hold_collects_member_that_resolves_45s_later`, `test_term_hold_teardown_cancels`,
  `test_late_member_after_hold_old_rule_counted`, `test_collapse_off_byte_identical_terms`,
  `test_inv_dir_gate_metamorphic` (random sequences: permuting `vision_direction` under `tracker` leaves the term stream
  and every `L` identical), config extremes `test_term_hold_zero_is_pre_phase3` and `test_cluster_s_zero_no_pass`.
- **Mutation:** collapse by time only (ignore `pass_key`) → `test_different_events_round_trip_keeps_two_terms`; read
  `vision_direction` under `tracker` → `test_inv_dir_gate_metamorphic`; drop the hold →
  `test_term_hold_collects_member_that_resolves_45s_later`.
- **Live:** ≥ 1 `crossing_vision_ledger` row of kind `pair_collapsed` within 2 days of crossings, and the day's
  opposite-direction clustered members with a shared event id appear as one pass, not two terms. Discriminates: a
  time-only collapse would also collapse different-event pairs (visible as `pair_collapsed` rows whose members carry
  different `event_id`); the gate forbids any.

**P3-D5 daily cap from measured volume; counter survives restarts (Tier 2).** Default `CROSSING_VISION_DAILY_CALLS` =
ceil(max daily simulated calls over 14 days from P3-D0 (a) × 1.5), capped at `CROSSING_VISION_DAILY_CALLS_MAX` (200);
expected about 100 (11-14: 46 calls + ≈ 12 ambiguous clusters ≈ 58; 11-13 had 42 ambiguous). Cost stays trivial on
Luna (< $0.02/day at cap 40, §5 D1), so the cap is a runaway guard, not a budget. At setup the counter is rehydrated
from today's (local) shadow rows whose outcome is a call outcome (`ok`, `blank`, `error`, `timeout`, `unparseable`,
`refused`), one query, before the bus listener is registered. Why rehydrate rather than accept the residual: the house
has a restart-storm history (memory `project_reload_storm_refuted_restart_storm_live`), and a storm turns a RAM cap into
no cap. The live Number keeps its value (an operator-set value wins over the new default).
- **Tests:** `test_cap_counter_rehydrated_from_today_rows`, `test_rehydrate_ignores_yesterday_and_non_call_rows`,
  `test_rehydrate_db_error_starts_at_cap_safe` (DB error = counter at the cap, calls resume next local day; a failing
  read never grants a fresh cap), `test_cap_holds_across_simulated_restart`.
- **Mutation:** skip the rehydrate → `test_cap_holds_across_simulated_restart`.
- **Live:** after the deploy restart, `crossing_vision_today.calls` equals the count of today's call rows (not 0).
  Discriminates: a RAM-only counter reads 0 right after the restart.

**P3-D6 direction scoring (Tier 2, read-only; lands in the D4 / P2-D6 scorer build, P2-D10 grading).** Oracles,
strongest first: operator grade (P2-D10 grade actions gain `_in` / `_out` / `_pass`); a named resident's
`person.*` not_home → home edge in [E − 300, E + 60] (in) or home → not_home in [E − 60, E + 300] (out) with a
name attached by F3 or the NVR on that crossing; the P3-D0 fixture. Interior-camera timing is the tracker's own input
and never an oracle. Reports per door / day-night: vision accuracy with Wilson bounds, tracker accuracy on the same
crossings, the disagreement win rate, coverage of ambiguous crossings, and the INV-DIR-GATE bar verdict. Disposition
audit `AUDIT_crossing_vision_direction_disposition_<date>.md`: FLIP-READY / HOLD (bar named, crossings still needed at
the measured rate) / PARK (bound below 0.90 at ≥ 150 scored).
- **Acceptance:** scorer run on ≥ 1 day of Phase 3 rows writes every number above; reproduces the fixture's 11/17
  tracker accuracy on the 11-14 clips.

**P3-D7 vision direction leads the ledger (Tier 3, gated; operator checkpoint).** A reviewed change of
`CROSSING_VISION_LEDGER_DIRECTION_SOURCE` to `vision` after FLIP-READY; bumps `pipeline_version` (resets the census
bars a-e window); post-flip trip-wire: the rolling `GO_REGRESSION_DAYS` (14) direction bar below threshold → NM
"revert vision direction". Files EGRESS-TRACKER-DIRECTION-1 (tracker fix for every consumer, see above) with the scored
tracker accuracy as its baseline.
- **Tests:** `test_direction_source_vision_uses_vision_direction`, `test_vision_unclear_falls_back_to_tracker`,
  `test_ambiguous_with_vision_in_gets_entry_term`, `test_direction_regression_pages_revert`.
- **Live:** after the flip, ≥ 1 term row with `direction_source = vision` and a `direction_agreement = disagree`
  crossing whose term sign follows vision.

Tier: P3-D0 probe; P3-D1 Tier 1; P3-D2, P3-D5, P3-D6 Tier 2; P3-D3, P3-D4, P3-D7 Tier 3 (they change the ledger's input
surface and add the first production G3 writer): two plan reviews incl. framing G (goal fidelity), four code reviews,
orchestrator re-grep of every term-construction site (`cluster_terms`, `_ledger_terms`, `_request_terms`, `_join_cluster`
late branch, the no-event / cap / busy / no-clip / disabled paths at `crossing_vision.py:676-707`, `:873-882`) and a
real source mutation of the INV-DIR-GATE site, operator checkpoint before deploy.

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
| `CROSSING_VISION_GROUP_PEAK_MIN` / `_GROUP_MAX_FRAMES` / `_LONG_EVENT_S` | 3 / 8 / 60 | 1 | Every 3+ group was undercounted at 4 frames; still one call; group max frames 4 = off |
| `CROSSING_VISION_WATCH_AMBIGUOUS` | True | 1 | P3-D3; False = the pre-Phase-3 skip |
| `CROSSING_VISION_PIPELINE_VERSION` | bumped per Phase 3 ship | 1 | Separates rows in every bar |
| `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` | 10 | 1 | `crossing_vision_direction_zero` trip-wire; 0 = off |
| `CROSSING_VISION_LEDGER_PAIR_COLLAPSE` | False until P3-D0 (d) passes, then True | 1 | P3-D4; False = per-member terms as before |
| `CROSSING_VISION_PAIR_SAME_EVENT_MIN` | 0.80 | probe gate (plan number, not runtime) | P3-D0 (d) |
| `CROSSING_VISION_TERM_HOLD_S` | 110 (cluster 60 + entry window 45 + 5) | 1 | P3-D4 hold; 0 = build terms at the vision outcome (pre-Phase-3) |
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
6. Phase 3: P3-D0 probe first (gates P3-D2 route, P3-D3 direction part, P3-D4). Then P3-D1 + P3-D5 (small, any time);
   P3-D3 (direction first: it dominates the net, audit §3c) with P3-D2; P3-D4; P3-D6 with the scorer build; P3-D7 only
   after FLIP-READY. Direction work comes before group work because the 11-14 net error was mainly direction labels.
Tier: Phase 1 Tier 2-DB; ledger, wiring and the rung-2 follow-up Tier 3 (two plan reviews incl. goal fidelity, four code
reviews, orchestrator re-grep and mutation, operator checkpoint).

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
