# NOT A BUILD SPEC: crossing vision plan rev 3 to 7.1 (history)

Archived 2026-11-13 from `plan/crossing-vision` @ 1e76c98a. Superseded by the clean documents `docs/planning/PLANNING_crossing_vision.md` (producer side) and `docs/planning/PLANNING_census_deconfliction.md` (census side). Kept so the equivalence reviewer can diff; nothing here is an instruction.

---

# PLANNING: crossing vision, shadow first

Card: **VISION-CROSSING-ANALYSIS-1** (thread identity, batch person-sightings). Sibling of
`PLANNING_person_sighting_layer.md` (FACE-ARRIVAL-REBUILD-1); its §15 (rev 12, incl. §15.9) is the design this plan builds
from, and this plan wins where they differ (stated per item).
Rev 2, 2026-11-13 (rev 2 = plan-review fixes F1-F13, `docs/reviews/plan-review/PLAN_crossing_vision_review.md`). Operator 2026-11-13: "Why not cue this faster. We should do the hard parts sooner and learn faster."
**Rev 3, 2026-11-13: Phase 2 (census ledger) planned in Part B (§14-§24).** Operator rulings 2026-11-13 (verbatim): "The
deferred thing person frame detection that I debunked, put it back in the cycle or its implications. We need
completion." and "Why wouldn't counting people at crossings be enough for vision census? Also your not ready doesn't
hold up. It depends on error rates you don't have." Rev 3 changes to Part A: D0d is no longer a Phase 2 blocker (§14.1
correction C1); the shadow model is the new llmvision entry (§2a); §9 and §11 point at Part B. D0 results:
`docs/planning/AUDIT_crossing_vision_d0_2026_11_13.md`.
**Rev 5, 2026-11-13: plan review #2 (adversarial build-prediction) applied to Part B.** Operator answers Q1-Q7 recorded
in §24. Binding build spec for the ledger, the anchor input and the four AWAY-entry sites is §16b; it wins over every
earlier Part B section. Text marked **[SUPERSEDED]** is kept for the record only: do not build from it.

**Shape in one paragraph.** Phase 1 builds a SHADOW producer: for every entry/exit crossing on a watched door, call the
existing llmvision OpenAI provider once on frames of the matching Frigate event, ask for a structured per-frame people
count, and write one `memory_episodes` row with the vision count next to the camera count the transit validator already
samples. Nothing reads the result except a diagnostic sensor attribute, a weekly read-only scorer and two trip-wires. No
census, guest, identity, sighting, NM-content or actuation change. The census fusion (§15.7 deconfliction live, ledger,
time-lapse B stage, interior head count, `vision_led`) is Phase 2, planned after Phase 1's scorer has ≥ 100 crossings with
resident ground truth. Phase 1 is independent of house-state step 1a. (Rev 2 F2: `person_sighting.py` is ON develop, `FACE_SIGHTING_ENABLED`
True, `const.py:3362`; it is a live listener of the egress event, not an unmerged branch.)

**Read first (mandatory, done by this planner, completely):** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. No corrections-ledger
claim is re-asserted. HVAC is not touched, so the HVAC state-of-play doc was not required. Contradictions found: none
between those docs and the code read here. One between `PLANNING_person_sighting_layer.md` §15.9.1 and code is
recorded in §1.6.

---

## 0. Answer first

1. **Tier:** Phase 1 = **Tier 2-DB** (new cloud call path, new `memory_episodes` writer through the write queue, one
   additive key on the `ura_person_egress_event` payload). One adversarial plan review before build. Phase 2 (census
   fusion) = Tier 3, separate plan revision, house-state rule applies.
2. **Temperature blocker: solvable by configuration, no code.** llmvision exposes Temperature and Top P on the OpenAI
   entry's reconfigure form; the values are entry-wide and there is no per-call override. Fix = the operator adds a
   SECOND llmvision OpenAI entry with temperature 1.0 and top_p 1.0 (leave the perimeter's entry at 0.5 / 0.9). Details
   and sources in §2.
3. **Phase 1 does not need GPT-6.** It runs on `gpt-4o-mini` (D0-V: 42/45 = 93 % exact count, 0 errors, p50 2.1 s)
   through the provider entry URA already uses. Luna is a later Tier-1 knob turn after the config fix passes a dry call.
4. **Frame guard judges pixels, not Frigate.** The hand-label (Frigate proxy agreed 22/30 = 73 %) fails the §15.9.7 bar,
   so the Frigate on/off proxy is not used to choose or reject frames. The model returns a per-frame person count in the
   same call (no extra call, no extra cost); a crossing whose frames all read 0 is recorded `blank`, never as a count of
   0. D0d measures this guard against the operator's 30 labels before it is trusted.
5. **Frame source: reuse llmvision `video_analyzer` with the Frigate `event_id`** (llmvision fetches the clip through HA's
   Frigate proxy and extracts frames with ffmpeg). URA writes no frame-extraction code. D0b measures it on the same 45
   crossings D0-V scored; if it fails, the fallback is `image_analyzer` on the Frigate best snapshot + thumbnail (§5 D1).
6. **Cost:** about **$0.18/day mean, $0.50/day at the 40-call cap** on gpt-4o-mini (≈ $5.4/month mean, $15 worst).
   On gpt-6-luna after the config fix: under $0.02/day. Estimates, not measured (llmvision returns no usage); §7.
7. **Can start now:** D0 (probe + one operator config action) and the D1/D2/D3 build scaffolding in parallel, as soon as
   the plan review passes. D0 decides one function body (frame source) and gates DEPLOY, not build start. §9.

---

## 1. Institutional context verified

### 1.1 Prior planning / audit docs (read)

| Doc | Read | Relevance |
|---|---|---|
| `PLANNING_person_sighting_layer.md` §15.1-§15.9 (rev 12) | full §15 | The design; §15.9 re-anchor (E vs t0, group guard, source chain, windows, cap 40) |
| `AUDIT_vision_d0_frame_sim_2026_11_13.md` | full | t0 = E + 45 s; edge-anchored frames; volume 14.1/day, max 30; concurrency 2; 12 % no Frigate event, 22 % Protect-only |
| `AUDIT_crossing_vision_d0_v_2026_11_13.md` | full | GO for counting on gpt-4o-mini (93 %) / gpt-5-mini (87 %); GPT-6 blocked (temperature 400); clip pre-roll 0-7 s; 14 % of event-anchored sets blank |
| Hand-label result (orchestrator brief, 2026-11-13) | given | Frigate proxy vs operator labels 22/30 = 73 %: proxy fails, guard must judge frames |
| `PLANNING_consol_1_alerting_llmvision.md` | header + §1 | Origin of `perimeter_enrichment.py` adapter, its kill / enable / timeout rungs |
| `AUDIT_consol_1_d0_probe.md` | referenced in §15.1 | gpt-4o-mini single-image latency 1.4-2.0 s, return shape `{"response_text": ...}` |
| `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.3, §3, §4.3, §4.5, §5.5 | full | Cross-corroboration doctrine; graceful-anonymous; egress event fields; outcome log pattern; consumer-class thresholds |
| `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1-§11 | full | Census / guest / house-state consumers that Phase 1 must NOT feed; §10 #34 (a producer that never fired) |
| Board card VISION-CROSSING-ANALYSIS-1 (`kanban.data.yaml:34765`) | full | Origin, gates D0-FRAME / D0-SIM / D0-V, trust bar 100 crossings / 7 days |

Memory bodies consulted: `reference_frigate_ghost_evidence_chain` (cross-corroboration over latency gates),
`feedback_fire_check_and_forward_trace`, `feedback_measure_before_build`, `feedback_marginal_benefit_pushback`,
`feedback_config_first_before_code` (all via CLAUDE.md / MEMORY.md index; their rules are applied below).

### 1.2 Code surveyed (develop @ ac664761)

`perimeter_enrichment.py` (whole), `frigate_ingress.py:147-215, :535-560`, `transit_validator.py:1298-1392, :2096-2320,
:2540-2600`, `perimeter_alert.py:3800-3990`, `database.py:10686-10770` (`log_memory_episode`), `const.py:2509-2545,
:3139-3145, :3299-3318, :3442, :3460, :6018-6092`, `domain_coordinators/_stuck_signal_nm.py:165-180`,
`camera_census.py:305-321`. llmvision 1.7.1 on the live mount (`/Users/okosisi/ha-config/custom_components/llmvision/`):
`config_flow.py`, `providers.py:466-484, :608-710, :798-809`, `__init__.py:90-110, :460-480, :718-740`,
`media_handlers.py:440-480, :610-700, :919-934`. Frigate integration views (`custom_components/frigate/views.py:137-215,
:313-330`).

### 1.3 Prior-art scan: REUSE or BUILD per piece

| Piece | Verdict | Existing symbol (file:line) |
|---|---|---|
| Crossing trigger | **REUSE** | `ura_person_egress_event` bus event, fired once per resolved crossing (`transit_validator.py:2191`); `timestamp` field = camera edge E (`:2194`, stamped `:1362`); fires at E + 45 s (`:1387-1388`, `EGRESS_ENTRY_WINDOW_SECONDS` `const.py:3299`) |
| Crossing key | **REUSE** | `f"{egress_camera}@{E iso}"`, the key the egress outcome log already writes (`transit_validator.py:2560`, `source_ref`) so the scorer joins vision rows to `egress_identity_outcome` rows with no new key |
| Frigate event id per camera | **REUSE** | `FrigateEventIngress` via `register_frigate_consumer` (`frigate_ingress.py:543-560`, consumer API `:175`); exterior linker is the precedent caller (`exterior_track_linker.py:305`) |
| Door group of a crossing | **REUSE** | `EgressDirectionTracker._door_group_by_stem` / `_door_group_for_stem` (used by `_sample_peak_person_count`, `transit_validator.py:1312-1318`), config `CONF_DOOR_GROUPS` (`const.py:3313`). D1 adds one public read-only getter, no new config |
| Camera count beside vision | **REUSE + additive key** | `_sample_peak_person_count` (`transit_validator.py:1298`), today written only to the DB row (`:2298-2313`). D2 samples it once and puts the same value on the bus event |
| Vision call adapter | **REUSE pattern, new function** | `perimeter_enrichment.enrich_dispatched_alert` (`perimeter_enrichment.py:127-259`): kill → gate → call with `wait_for` → non-empty → never raise. D1 adds a sibling function in the same module for `video_analyzer` (that service has no adapter today: grep `video_analyzer` in URA = 0 hits) |
| Kill switch | **REUSE** | `LLMVISION_ENRICHMENT_KILL` (`const.py:2509`), rung 1 |
| Provider entry id | **REUSE** | `CONF_PERIMETER_ENRICHMENT_PROVIDER_ID` (`const.py:2527`), read the same way (`perimeter_enrichment.py:190`) |
| Frame extraction | **REUSE (external)** | llmvision `video_analyzer` with `event_id` → `/api/frigate/notifications/<id>/clip.mp4` (`media_handlers.py:932-934`), signed and fetched internally (`:630-643`), ffmpeg I-frames, first frame + SSIM-diverse frames up to `max_frames` (`:463-480`). The no-instance Frigate URL resolves to the default Frigate entry (`frigate/views.py:317`, `_get_config_entry_for_request` falls back to `get_default_config_entry`) |
| Fallback frames | **REUSE** | Frigate snapshot / thumbnail fetch via `PerimeterAlertManager._http_get_bytes` (`perimeter_alert.py:3979`) and the multi-instance URL forms (`:3848-3858`); only if D0b fails |
| Result persistence | **REUSE** | `Database.log_memory_episode` (`database.py:10686`), write queue; per-crossing `node_id` so the 60 s `(node_id, type)` dedup (`:10722-10740`) cannot merge crossings (same reasoning as `transit_validator.py:2547-2549`) |
| Episode type registry | **NEW entry** | `crossing_vision_shadow` added to `MEMORY_EPISODE_TYPES` (`const.py:6018`) and `MEMORY_WRITER_BACKED_EPISODE_TYPES` (`:6064`). Grep `crossing_vision` in `custom_components/` = 0 hits |
| Zero-fire / error trip-wire | **REUSE** | `fire_stuck_signal(hass, kind, key, diagnosis, ...)` (`_stuck_signal_nm.py:165`), once per (kind, key) per day; plus the weekly memory-writer health check that pages on 0 rows in 7 days (`database.py:11443-11482`) |
| Master switch | **NEW entity** | `switch.ura_crossing_vision_shadow`, `SwitchEntity, RestoreEntity` like `EgressIdentityFaceFailsafeDrillSwitch` (`switch.py:913`). No existing switch gates door-camera vision: `perimeter_enrichment_enabled` gates the 14 perimeter sensors and stays separate (different cameras, different privacy decision) |
| Daily cap | **NEW Number** | name fixed by §15.9.5: `CROSSING_VISION_DAILY_CALLS`, Number entity like `PerimeterEnrichmentTimeoutNumber` (`number.py:4229`) |
| Weekly scorer | **REUSE pattern** | `scripts/probes/egress_outcome_label_weekly.py` (read-only, labels from tracker edges); D4 adds a sibling script |
| Agreement vocabulary | **REUSE** | §15.7 cases A/B/C/D; `CENSUS_AGREEMENT_*` names stay for Phase 2 (`camera_census.py:317`) |
| Provenance constant | **REUSE (Phase 2)** | `IDENTITY_PROVENANCE_VISION` (`const.py:3442`); Phase 1 attaches no identity, so it is not read |

Greps run (develop): `grep -rn "image_analyzer\|video_analyzer" custom_components/` (1 module, image only);
`grep -rn "ura_person_egress_event" custom_components/` (consumers: `sensor.py:4761, :4892, :5002, :5052`,
`perimeter_alert.py:1006`, `person_sighting.py:56` (on develop, live; registered from `presence.py:5533`)); `grep -rn "register_consumer(" custom_components/`
(ingress + linker); `grep -n "CROSSING_VISION\|crossing_vision" const.py config_flow.py number.py switch.py select.py
sensor.py` (0); `grep -n "LLMVISION\|PERIMETER_ENRICH" const.py` (`:2509-2545`).

### 1.4 Config-first check (before any code)

| Question | Setting that could answer it | Finding |
|---|---|---|
| Can a knob make GPT-6 work? | llmvision OpenAI entry Temperature / Top P | **Yes, by configuration** (§2). Not needed for Phase 1 |
| Can a knob turn on door-camera vision today? | `perimeter_enrichment_person_sensors` allowlist | No: that path enriches perimeter ALERTS (dispatched NM), one snapshot, prose; it has no crossing trigger, no count schema, no record. Adding door sensors there would change NM alert text, which Phase 1 must not do |
| Is there an existing llmvision automation doing this? | HA automations | Not checked live; the D0 prober lists automations calling `llmvision.*` (read-only) so we do not duplicate one |
| Can the count be had from Frigate alone? | `sensor.<cam>_person_count` | That IS the camera count we compare against (`_sample_peak_person_count`); the point of the cycle is an independent second count |

Code is needed for the trigger, the record and the trip-wires; nothing else is.

### 1.5 Measure-before-build status

Already measured (no re-run): volume, concurrency, edge anchor, event coverage (D0-FRAME/SIM); count accuracy on
image_analyzer clip frames for gpt-4o-mini and gpt-5-mini (D0-V). Not measured and needed before DEPLOY: the
`video_analyzer` frame source, the per-frame guard against operator labels, the gpt-6 config fix (optional for Phase 1).
Those are D0b / D0d / D0a.

### 1.6 Plan-vs-code note

`PLANNING_person_sighting_layer.md` §15.9.1 says capture is anchored at E and frames are "taken retrospectively at t0 from
what Frigate retains". This plan keeps that, and changes WHEN the call is made: at the matched Frigate event's END (or
`CROSSING_VISION_EVENT_END_WAIT_S` after t0, whichever is first), because a clip requested while the event is still
open may be short or absent (event duration p90 42 s, max 134 s, D0-FRAME F2/F3). Latency does not matter in shadow.
UNVERIFIED: whether Frigate serves `clip.mp4` for an in-progress event; D0b records it.

---

## 2. Config-first finding: the llmvision temperature blocker

**Source:** llmvision 1.7.1 on the live HA mount, `/Users/okosisi/ha-config/custom_components/llmvision/`.

1. Temperature and Top P are **per provider entry**, stored in `entry.data` and copied into the provider config at setup
   (`__init__.py:101-102`).
2. Every OpenAI call reads them through `_get_default_parameters` (`providers.py:466-484`: `config.get(CONF_TEMPERATURE,
   0.5)`, `config.get(CONF_TOP_P, 0.95)`) and puts both in the payload (`providers.py:690-696`). They are removed only for
   the exact model names `gpt-5`, `gpt-5-mini`, `gpt-5-nano` (`providers.py:706-710`). That is why gpt-6-luna /
   gpt-6.1-sol get HTTP 400 "temperature does not support 0.5 ... Only the default (1) value is supported".
3. **No per-call override exists.** `services.yaml` has no temperature field; `ServiceCallData` initialises
   `self.temperature = float()` (`__init__.py:476`) and the OpenAI provider ignores it (it reads the entry).
4. **The knob is in the entry's UI.** The OpenAI step (`config_flow.py:536-652`) shows a "model" section with Temperature
   (number selector, min 0, max 1, step 0.1, default 0.5) and Top P (same range, default 0.9), plus Reasoning Effort.
   Reconfigure prefills the current values (`config_flow.py:600-615`) and saves with `async_update_reload_and_abort`.
   1.0 is inside the allowed range. Validation sends one "Hi" with the default model and no temperature
   (`providers.py:798-807`), so an entry whose default model is a GPT-6 model validates.
5. **A second OpenAI entry is allowed.** The OpenAI step has no `async_set_unique_id` / `_abort_if_unique_id_configured`
   (grep of `config_flow.py`: no `unique_id` match), and creates `async_create_entry(title="OpenAI", ...)`.

**Recommended action (operator, config only, no code):** add a second llmvision provider entry (Settings → Devices &
Services → LLM Vision → Add entry → OpenAI), enter the API key yourself, default model `gpt-6-luna`, Temperature **1.0**,
Top P **1.0**, Reasoning Effort none. Rename it "OpenAI reasoning". Do NOT reconfigure the existing "OpenAI" entry: it
serves the perimeter enrichment (`gpt-4o-mini`, incl. the D6 `PERSON: YES/NO` verdict prompt) and would move that to
temperature 1.0. Top P 1.0 is a precaution: the 400 text named only temperature; whether GPT-6 also rejects top_p 0.9 is
UNVERIFIED and the dry call settles it.

**Then (D0a):** one dry `image_analyzer` call per model with `provider` = the new entry's id. Pass = HTTP 200 with
non-empty `response_text`. Agents never read, print or copy the key (the brief and D0-V rule).

**What it unlocks:** D5 only (Luna as the shadow model). Phase 1 does not wait for it.

### 2a. Rev 3: the entry exists; crossing vision uses it

Operator 2026-11-13: the second entry is live, id `01M7B731T26P2HXVW77AQR62PP`, title "OpenAI Madrone Vision", model
`gpt-6-luna`, temperature 1.0, top_p 1.0. Crossing vision uses it (D5 / P2-D1); the old entry
`01KHB0EV5AP8ANWQ7RWT30M2CC` (gpt-4o-mini) stays on perimeter enrichment and the 3 HA automations (D0c). The entry id
is never hard-coded: it goes in `CONF_CROSSING_VISION_PROVIDER_ID` (rung 2), so another install picks its own.
D0a's dry call still runs once against this id (image and video) before the shadow switch goes on.

---

## 3. Falsifiable invariants (reviewer D breaks these)

**INV-SHADOW (load-bearing).** For any crossing, any vision result (success, blank, error, timeout, refusal, malformed
JSON, cap skip), no reachable path changes: an actuator; house state or any inference input; any census value
(`unidentified_count`, identified set, `face_recognized_count`, guest gate, stay latch, `visitors_present`); `person_id`,
`identity_confidence`, `identity_provenance` or any `person_entry_exit_events` column; any `SIGNAL_PERSON_SIGHTING`; the
text, severity or routing of any NM alert other than the module's own trip-wire pages. The module's only writes are one
`memory_episodes` row per analysed crossing, its own counters / diagnostic attributes, files under llmvision's media
directory created by llmvision, and its own `fire_stuck_signal` pages.
Allowed readers (rev 2 F3, re-grepped `FROM memory_episodes`): the diagnostic sensor attribute, the weekly scorer script,
the trip-wires, and three generic pre-existing readers that are display / operator-query only: `URAMemoryStatusSensor`
via `get_memory_status_counts` (`database.py:11152`, count by type), the `memory_query` service via `MemoryFacade.episodes` /
`narrative` (`__init__.py:6395-6411`, node-keyed; `vision:*` nodes are reached only by an explicit query), and the
writer-health check (`database.py:11491`). Phase 1 adds NO `MEMORY_COMPACTION_RULES` entry (`const.py:6155`) for the type.
Break it by: finding any other reader of `crossing_vision_shadow` rows, of the module's counters, or of the hass.data
object, or any compaction rule / fact derived from the type.

**INV-OFF.** With `switch.ura_crossing_vision_shadow` off, or `LLMVISION_ENRICHMENT_KILL` True, or the daily cap at 0:
zero `llmvision.*` service calls and zero Frigate media requests originate from this module, and it writes no row. The transit validator's bus event values and DB rows are identical to develop except the one
additive bus key (INV-ADDITIVE).
Break it by: a crossing that reaches the service call with the switch off (e.g. a call scheduled before the switch
turned off and executed after; the gate must be re-read at call time, not only at schedule time).

**INV-SCOPE (privacy and cost).** Every frame sent belongs to a Frigate event on a camera in the crossing's own door group
as configured in live `door_groups` (a stem with no group entry = a group of one: its own camera only); never a camera
outside that set, never an ambiguous crossing. Code cannot know a configured member is "interior"; D0c verifies the live
`door_groups` holds only door cameras (rev 2 F13). Calls per local
day ≤ `CROSSING_VISION_DAILY_CALLS`; calls in flight ≤ `CROSSING_VISION_MAX_CONCURRENT`; nothing is queued beyond them
(over = counted skip).
Break it by: a door group containing a camera that is also an interior neighbour or perimeter camera (legal config);
two crossings of one cluster both calling; a restart mid-day resetting the cap counter (accepted residual if documented:
the counter is RAM, so a restart can allow up to one extra cap's worth that day; rev 2 F7 names it, §6).

**INV-ADDITIVE.** For every non-ambiguous crossing, the DB `peak_person_count` equals the bus `peak_person_count` (one
sample, one local, consumed by both). Ambiguous crossings carry `peak_person_count: None` on the bus and write no row
(develop behaviour).
Break it by: a path where the sampler runs twice, or the DB write uses a value sampled after an await.

**INV-BLANK.** A crossing whose returned per-frame counts are all 0 (or absent) is recorded `outcome = blank` with
`people_count = None`; it is never recorded as a count of 0 and never enters the count-accuracy numerator. A crossing with
no matching Frigate event is `outcome = no_frigate_event` and makes no call.

---

## 4. Producer and consumer checks

### 4.1 Values this cycle touches

| Value | Producer (arithmetic, dependency health) | Consumers |
|---|---|---|
| `ura_person_egress_event` (trigger) | `EgressDirectionTracker._resolve_direction`, one fire per crossing at E + 45 s. Health: ~14.1 crossings/day on garage A + front (D0-SIM V1, 13 days), so it fires daily | Existing: 4 display sensors (`sensor.py:4761, :4892, :5002, :5052`), perimeter D10.5 (`perimeter_alert.py:1006`), (branch) person sightings. NEW: crossing vision (display/record only) |
| `peak_person_count` (camera count) | `_sample_peak_person_count`: MAX over the door group's buffered Frigate `person_count` samples in [E − `DOOR_STEM_DEDUP_S`, E + 45 s], seeded by the last pre-window value. Protect has no count entity, so this is a Frigate count. Health: written on rows since R3.6; D0-FRAME saw 1:126, 2:53, 3:4, none:6 of 189 | Today: DB column only. NEW: bus key (D2) → crossing vision row (display). No trust reader added |
| Matched Frigate event | Ingress consumer ring: events on door-group cameras with `label == person` whose `start_time` ∈ [E − `CROSSING_VISION_EVENT_MATCH_S`, E + `CROSSING_VISION_EVENT_MATCH_S`]. Pick rule: highest `top_score`, tie → longest. Health: 88 % of crossings have a clip-bearing Person event within ±60 s (D0-FRAME F5); ±10 s coverage is measured in D0c | Crossing vision only |
| Vision count (`people_count`, per-frame counts, direction, desc) | llmvision `video_analyzer` on the matched event, structured JSON; guard = per-frame counts (INV-BLANK). Health: unmeasured on this source (D0b) | Diagnostic sensor attribute (display), weekly scorer (offline), trip-wires |

### 4.2 Fire check (has it ever fired?)

| Producer | Fired? | Evidence |
|---|---|---|
| Egress crossing event | Yes, ~14/day | D0-SIM V1 from `person_entry_exit_events` |
| `peak_person_count` | Yes, on 183 of 189 rows | D0-FRAME V1 |
| Frigate ingress events on door cameras | Yes | D0-FRAME F2 (103 of 117 clusters matched) |
| llmvision OpenAI calls from URA | Yes (perimeter) | `AUDIT_consol_1_d0_probe.md`; D0-V 150 calls |
| `video_analyzer` via event_id on this install | **Never** | No caller exists. D0b is its first fire |
| NEW crossing vision producer | n/a | Zero-fire trip-wire D3 from day 1 |

### 4.3 Forward trace

Phase 1 output reaches no action by design (INV-SHADOW). Its forward path is: row → weekly scorer → the §15.7a trust
numbers → Phase 2 plan decides whether vision may feed the census `unidentified_count` (which then reaches the guest gate,
house state GUEST, HVAC guest mode, lock regime guest night). That chain is listed so Phase 2 plans the consumer-side
policy there (access consumers never act on vision, §15.3 item 5), not in the producer.

---

## 5. Deliverables

### D0: probe and one config action (read-only + operator; starts immediately; gates DEPLOY of D1)

Runs as one `ura-prober` pass, ≤ 60 calls, scratchpad only, no URA or HA writes except llmvision's own media files
(deleted afterwards).

- **D0a. GPT-6 config fix.** After the operator adds the second OpenAI entry (§2): one dry `image_analyzer` call each for
  `gpt-6-luna`, `gpt-6.1-sol` with `provider` = that entry. Record status, latency, `response_text` non-empty.
- **D0b. Frame source = `video_analyzer`.** Re-run the 45 crossings D0-V scored (same Frigate event ids, still inside
  retention 2026-10-30+; any that aged out are listed) with `video_analyzer`, `event_id`, `max_frames` 4,
  `target_width` 768, `response_format: json`, the D1 `structure` schema and prompt, provider = the existing OpenAI entry,
  model gpt-4o-mini, `store_in_timeline` false, `expose_images` true (to see the frames llmvision chose). Score exact
  count vs D0-V's visual labels, blank-set behaviour, refusal / error / unparseable, latency p50/p90, and whether the
  response carries the frame file paths. Also call once on an event that is still open (if one occurs) and once on an
  ended event, to answer §1.6.
  **Pass:** exact count ≥ 85 % (§15.4 rev-5 fast-stage bar) with 0 undercounts on the multi-person set, 0 errors.
  **Fail:** D1 uses the fallback frame source (best snapshot + thumbnail via `image_analyzer`, 2 frames); D0b reruns on
  that source with the same bar. Fail twice = park the cycle with the numbers.
- **D0c. Fixture, by hand.** Table of door-group stems (`door_groups` keys) → Frigate camera name in the event payload
  `after.camera`, for the 4 live door cameras; record `len(hass.config_entries.async_entries("frigate"))` counting ALL entries incl. disabled (the default-entry
  URL returns None when > 1, rev 2 F4), each entry's `notification_proxy_enable` (the clip proxy refuses when off), and
  the instance id per door camera; event-match coverage at ±10 s (share of the 117 clusters with a door-group Person event whose
  start is within ±10 s of E). Commit the table as `docs/planning/FIXTURE_crossing_vision_door_cameras.md`; D1's tests
  use it. Also list HA automations that call `llmvision.*` (read-only) so nothing duplicates them.
- **D0d. Pixel guard vs operator labels.** Send each of the 30 operator-labelled frames
  (`scratchpad/handlabel/f01-f30.jpg`) as a single-frame `image_analyzer` call with the D1 per-frame prompt. **Pass:** the
  model's `people > 0` agrees with the operator's label on ≥ 29/30. **Fail:** the guard is not trusted; D1 still ships
  (shadow), but the scorer reports every blank / non-blank verdict as unvalidated and Phase 2 is blocked until a guard
  passes.
  **Rev 3: SUPERSEDED, not a Phase 2 blocker (§14.1 C1).** Result 24/30 (per-frame form). D1 uses the SET-level guard
  (all frame counts 0), which D0b measured at 0 false blanks in 38 person crossings and 6/6 true blanks. Phase 2 is
  gated on ledger-level bars (§17), which absorb any residual guard error.

**Acceptance:**
- **Verify:** audit `docs/planning/AUDIT_crossing_vision_d0_shadow_prep_2026_11.md` has one row per sub-item with pass/fail
  and the raw numbers; D0b reports per camera and day/night.
- **Discriminates:** D0b distinguishes "video frames work" (≥ 85 % exact) from "pre-roll first frame poisons the count"
  (undercounts or blanks concentrated where the first frame is pre-roll) by recording per-frame counts per position.
- **Live:** none (no production change).

### D1: shadow producer `crossing_vision.py` (Tier 2-DB build)

New module, one class `CrossingVisionShadow`, built in `__init__.py` next to the `ExteriorTrackLinker` construction
(`__init__.py:3569-3586`, same integration-entry lifecycle, after the egress tracker `:3471` and Frigate ingress exist),
stored at `hass.data[DOMAIN]["crossing_vision"]`, torn down in unload (unsubscribes, cancels timers, gathers in-flight
tasks with a 5 s bound, sets a `_torn_down` latch first, the `transit_validator` outcome-log pattern).

1. **Frigate ring.** `register_frigate_consumer(hass, "crossing_vision", fn)` (`fn` is a sync callback, no await; an `end`
   for a waited event cancels the timer and schedules the call as a tracked task); keep, per door-group Frigate camera, the
   last `CROSSING_VISION_EVENT_RING` events: id, camera, start, end (when an `end` arrives), top_score, has_clip.
   Non-person labels and non-door cameras dropped on arrival.
   **Camera → stem map is derived at runtime, never hard-coded (rev 2 F1, portability):** Frigate `after.camera` →
   stem through the SAME normalisation the validator uses for its count-sensor stems
   (`CameraIntegrationManager._extract_camera_stem`, reached via `EgressDirectionTracker._extract_camera_stem`
   `transit_validator.py:1465`, applied to `sensor.<after.camera>_person_count`, honouring the `_2` rule in
   `IDENTITY_FUSION_CAMERAS_MANUAL.md`), then `door_groups` by stem via the D1 public getter. The D0c fixture is the test
   ORACLE the runtime map is diffed against (`test_runtime_camera_map_matches_fixture`), not a source of camera names.
2. **Trigger.** `hass.bus.async_listen("ura_person_egress_event", ...)`. Ignore `direction` not in (entry, exit). Compute
   `crossing_key = f"{egress_camera}@{timestamp}"` verbatim from the event (same string the outcome log writes).
3. **Cluster (rev 2 F5).** A crossing whose door group has ANY request (open or completed) with |E − E'| ≤
   `CROSSING_VISION_CLUSTER_S`, or whose matched Frigate event id was already analysed, makes no call. It still writes its
   OWN row (`node_id=f"vision:{crossing_key}"`, `outcome = clustered`, `primary_crossing_key` = the request's key), so
   every crossing has exactly one row and the scorer joins 1:1 by `source_ref`. The primary row carries `crossing_keys`
   (all members). Clustered rows do not count against the cap.
4. **Gates, re-read at schedule AND at call time:** switch on, kill const False, cap not reached, in-flight <
   `CROSSING_VISION_MAX_CONCURRENT`. A failed gate records a skip outcome (`off` is not recorded: no row while off, per
   INV-OFF; `skipped_cap`, `skipped_busy` are recorded).
5. **Match.** Pick the event per §4.1; none = row with `outcome = no_frigate_event`, no call.
6. **Wait.** Call when the matched event has ended, or `CROSSING_VISION_EVENT_END_WAIT_S` after the bus event, whichever
   first (one `async_call_later`, tracked; an `end` arriving earlier fires it).
7. **Call.** New function `perimeter_enrichment.analyze_crossing_frames(hass, event_id, *, model, max_frames,
   target_width, timeout_s, structure, prompt) -> dict | None`, same contract as `enrich_dispatched_alert` (kill check,
   `wait_for`, never raises, flat `response_text`), service `llmvision.video_analyzer`, `provider` =
   `CONF_PERIMETER_ENRICHMENT_PROVIDER_ID`, `store_in_timeline` false, `use_memory` false (explicit; llmvision memory
   images go out only when it is true, `llmvision/providers.py:759-761`), `expose_images` per `CROSSING_VISION_KEEP_FRAMES`.
   **Clip URL (rev 2 F4):** pass `video_file = /api/frigate/<instance_id>/notifications/<event_id>/clip.mp4` when the
   instance id is known (reuse the perimeter's discovery, `perimeter_alert.py:3840-3858`, `_frigate_instance_ids` /
   learned per-camera instance); fall back to `event_id` (default URL) only when there is exactly one Frigate config
   entry. Reason: llmvision's `event_id` path uses `/api/frigate/notifications/...` (`media_handlers.py:932-934`), and
   the Frigate view's default entry is None when `async_entries("frigate")` has more than one entry, including disabled
   ones (`frigate/views.py:47-57`), which would turn every call into an error. Both forms are HA-signed
   (`async_sign_path`, `media_handlers.py:630-643`) and go through HA's Frigate integration proxy: no URA code holds or
   sends Frigate credentials.
   If D0b failed: the same function with `image_analyzer` on the snapshot + thumbnail fetched through
   `PerimeterAlertManager._http_get_bytes` (no new HTTP code).
8. **Parse + guard.** Schema `{frames: [{index, people}], people_total, direction: in|out|unsure, group: bool,
   desc: str}`. Prompt forbids naming or identifying anyone (same wording as D0-V). Outcome: `ok` (≥ 1 frame with
   people > 0; `people_count = people_total` clamped to [max(frame counts), max(frame counts) × len(frames)]), `blank`
   (INV-BLANK), `unparseable`, `error`, `timeout`, `refused` (empty `response_text`).
9. **Record.** One `log_memory_episode(node_id=f"vision:{crossing_key}", episode_type="crossing_vision_shadow",
   source_ref=crossing_key, started_at=E, ended_at=now, attrs={...}, dedup_source_ref=False)` as a tracked task. Attrs:
   `outcome`, `crossing_keys`, `door_group`, `direction` (validator's), `vision_direction`, `people_count`,
   `frame_counts`, `group`, `desc` (≤ 200 chars), `camera_peak_count` (D2), `frigate_events_in_window` (count of distinct
   Person events on the group in [E − 10, E + 45]), `event_id`, `event_camera`, `model`, `frame_source`, `latency_s`,
   `person_id` and `identity_provenance` copied from the bus event (for the scorer only), `agreement_case`
   (A agree / B vision higher / C camera higher / D one side missing, §15.7, computed on counts not guests).
10. **Diagnostics (display only, unrecorded attributes).** On the existing Outside: Open Tracks sensor (where the ingress
    and path-map diagnostics already live): `crossing_vision_today` (calls, ok, blank, no_event, errors, skipped_cap,
    skipped_busy, clustered), `crossing_vision_last` (outcome, people_count, camera_peak_count, case, age). No new sensor entity.
11. **Knobs:** §6.

**Acceptance:**
- **Verify:** with the switch on, a test crossing on a door-group camera with a matched ended event produces exactly one
  service call with `event_id`, the configured model and provider, and one row whose `source_ref` equals the bus event's
  `egress_camera@timestamp`.
- **Verify (INV-OFF):** switch off → 0 service calls, 0 rows; switch turned off between schedule and call → 0 calls.
- **Verify (INV-SCOPE):** a Frigate event on an interior-neighbour camera inside the window is never picked; an
  `ambiguous` crossing makes no call; the 41st crossing of a day with cap 40 records `skipped_cap` and makes no call.
- **Verify (INV-BLANK):** all-zero frame counts → `outcome=blank`, `people_count` None.
- **Verify (never raises):** service raising, timing out, returning `{}`, a nested envelope, or non-JSON each yields one
  row with the right outcome and no exception escapes the listener.
- **Discriminates:** `frigate_events_in_window` vs `camera_peak_count` separates "Frigate saw two tracks" from "count sensor
  said 2", so a vision-higher case can be traced to tailgating vs a count-sensor lag later.
- **Tests:** `quality/tests/test_crossing_vision_shadow.py`: `test_one_call_one_row_per_crossing`,
  `test_switch_off_no_call_no_row`, `test_switch_off_after_schedule_no_call`, `test_kill_const_no_call`,
  `test_ambiguous_ignored`, `test_interior_camera_event_never_matched`, `test_cap_skip_recorded`,
  `test_busy_skip_recorded`, `test_cluster_one_call`, `test_blank_not_zero`, `test_no_frigate_event_no_call`,
  `test_failure_classes_recorded_never_raise`, `test_runtime_camera_map_matches_fixture`, `test_cluster_completed_request_no_second_call`,
  `test_clip_url_instance_scoped`, `test_use_memory_false`, `test_teardown_cancels_pending`, `test_node_id_unique_per_crossing`,
  `test_no_census_or_sighting_reader` (greps production code for readers of the episode type / hass key outside the
  allowed set, plus a behavioural check that a census tick before and after a vision row is identical). Real `hass`
  fixture, real `log_memory_episode` against the production schema (Tier 2-DB fixture rule).
- **Mutation drills (framing C):** remove the call-time switch re-read → `test_switch_off_after_schedule_no_call` fails;
  drop the door-group filter → `test_interior_camera_event_never_matched` fails; treat blank as 0 →
  `test_blank_not_zero` fails.
- **Live:** after deploy with the switch on, within 4 h of daytime: ≥ 1 `crossing_vision_shadow` row with `outcome=ok`
  and non-null `people_count` and `camera_peak_count` (sentinel-only rows = payload broken, Tier 2-DB rule); every row's
  `source_ref` matches an `egress_identity_outcome` row's `source_ref`; `crossing_vision_today.calls` ≤ crossings today;
  HA log has no `crossing_vision` ERROR.

### D2: additive `peak_person_count` on `ura_person_egress_event`

In `_resolve_direction`, for a non-ambiguous crossing, call `_sample_peak_person_count` ONCE before the bus fire, put the
local on the event as `peak_person_count`, and pass the SAME local to `log_entry_exit_event` (today it is sampled inside
the DB block, `transit_validator.py:2298`). Ambiguous: key present with None, no sample (develop wrote no row and sampled
nothing). Sampler exceptions keep today's behaviour (None, debug log).

**Acceptance:**
- **Verify:** for an entry crossing the bus `peak_person_count` equals the DB row value; for an ambiguous crossing the key
  is None and no row is written.
- **Discriminates (rev 2 F10):** there is no await between the bus fire and the DB write today, so a buffer-mutation test
  cannot tell one sample from two. Instead the test wraps `_sample_peak_person_count` with a stub returning a different
  value per call and asserts it was called exactly once and both sinks carry the first value.
- **Tests:** `quality/tests/test_transit_validator_peak_on_bus.py`: `test_bus_and_db_peak_identical`,
  `test_ambiguous_peak_none_no_sample`, `test_sampler_exception_none_both`, `test_existing_bus_keys_unchanged` (golden of
  every pre-existing key).
- **Live:** one new `person_entry_exit_events` row after deploy has the same `peak_person_count` as the next
  `crossing_vision_shadow` row's `camera_peak_count` for that crossing.

### D3: trip-wires (code, not calendar)

- `crossing_vision_zero`: with the switch on, if ≥ `CROSSING_VISION_ZERO_MIN_CROSSINGS` (5) entry/exit crossings were seen
  in the last 24 h and 0 calls returned `ok`, `fire_stuck_signal(kind="crossing_vision_zero", key=("house",), ...)`,
  HIGH. Evaluated hourly (tracked `async_track_time_interval`), RAM latch re-armed when an `ok` arrives.
- `crossing_vision_errors`: error + timeout + unparseable + refused > `CROSSING_VISION_ERROR_RATE_MAX` (0.25) of calls over
  the last 24 h with ≥ 8 calls → MEDIUM page, same latch rule.
- `crossing_vision_shadow` joins `MEMORY_WRITER_BACKED_EPISODE_TYPES`, so the weekly health check pages on 0 rows in 7
  days (switch off for a week also pages; add it to the exempt set only if the operator wants the switch off long term:
  that is the documented discharge).

**Acceptance:**
- **Verify / Tests:** `test_zero_fire_pages_once`, `test_zero_fire_rearms_after_ok`, `test_error_rate_pages`,
  `test_switch_off_no_page`. Mutation: remove the latch → `test_zero_fire_pages_once` fails.
- **Live:** `crossing_vision_today` attributes present; no page on the first day with the switch on and rows flowing.

### D4: weekly scorer (read-only script) and the first disposition

`scripts/probes/crossing_vision_score_weekly.py` (sibling of `egress_outcome_label_weekly.py`): joins
`crossing_vision_shadow` rows to `egress_identity_outcome` (by `source_ref`, 1:1 since every crossing has its own row;
`clustered` rows take their count from `primary_crossing_key`), `person_entry_exit_events`, and resident
tracker / Bermuda edges within ±120 s (the D10.5 rule). Ground truth per crossing = number of residents whose own edge
matches the crossing direction, when no non-resident is suspected (the §15.7a resident stream); operator-labelled guest
days add the non-resident set. Reports, per door group, direction and day/night: exact-count rate (vision and camera
separately), case A/B/C/D shares and which side matched truth in B and C, blank / no-event / error rates, false-guest
proxy (vision > known residents on resident-only crossings), cost proxy (calls × §7 per-call estimate).

**Disposition (binary, the soak exit):** run once when the rows hold ≥ 100 crossings with ground truth AND ≥ 10 with a
non-resident (expected ~7-10 days at 14/day). Outcome is one of: **GO Phase 2** (all §15.7a bars met: vision exact ≥ 95 %
overall, ≥ 90 % night, wins ≥ 80 % of B/C disagreements, false guest ≤ 2 %, healthy ≥ 95 %), **GO Phase 2 as
evidence-only** (count bars met, disagreement bar not), or **PARK** with the failing numbers and the revival trigger. Not
a watch: one query.

**Acceptance:**
- **Verify:** the script runs read-only (`sqlite3 -readonly`), prints the table, writes nothing in the repo except when
  asked for a fixture; committed audit `docs/planning/AUDIT_crossing_vision_shadow_disposition_<date>.md`.
- **Discriminates:** reports camera exact-count on the same crossings, so "vision is good" is separated from "everything
  is easy this week".
- **Live:** n/a (offline).

### D5 (conditional on D0a pass): Luna as the shadow model

Add `CONF_CROSSING_VISION_PROVIDER_ID` (rung 2, integration options, Advanced, empty = reuse the perimeter provider) and
flip `CROSSING_VISION_MODEL` to `gpt-6-luna`. Tier 1. A two-model A/B (both models per crossing) is NOT done in shadow by
default (doubles calls); D4 compares the week before and after the flip instead.

**Acceptance:** **Verify:** with the option set, calls carry the new provider id and model; **Live:** ≥ 1 `ok` row with
`model=gpt-6-luna`; **Test:** `test_provider_override_used`, `test_empty_override_falls_back`.

---

## 6. Numbers get knobs

| Knob | Value | Rung | Why / kill semantics |
|---|---|---|---|
| `switch.ura_crossing_vision_shadow` | off at ship | 3 (Switch, RestoreEntity) | Master; the operator turns it on after deploy. Off = INV-OFF |
| `LLMVISION_ENRICHMENT_KILL` | False (REUSED) | 1 | Code kill for all llmvision use |
| `CROSSING_VISION_DAILY_CALLS` | 40 | 3 (Number) | §15.9.5: max day 30 + headroom; 0 = no calls. Counter is RAM, reset at local midnight (rev 2 F7, decided: no Store). Named residual: each HA restart can allow up to one more cap that day (≤ $0.50 per restart on gpt-4o-mini); the D3 error / zero trip-wires are unaffected |
| `CROSSING_VISION_MODEL` | `gpt-4o-mini` | 1 | Changing model changes cost and accuracy and needs a dry call first; reviewed one-line change (D5) |
| `CROSSING_VISION_MAX_FRAMES` | 4 | 1 | First (pre-roll) + 3; D0b may set 3 or 5 |
| `CROSSING_VISION_TARGET_WIDTH` | 768 | 1 | D0-V measured at 768 |
| `CROSSING_VISION_TIMEOUT_S` | 90 | 1 | Video fetch + ffmpeg + call; shadow, latency irrelevant. Rev 2 F6: `wait_for` cancels llmvision's handler in place (HA awaits the handler coroutine directly for `blocking=True`), which can orphan its ffmpeg subprocess and leak its `delete=False` temp clip; so the bound sits above llmvision's own request timeout (entry `request_timeout`, default 60 s, `providers.py:502-507`) and D0b sets it to ≥ 1.5 × measured p99 |
| `CROSSING_VISION_EVENT_MATCH_S` | 10 | 1 | §15.9.1 window [E − 10, E + 10]; D0c measures coverage |
| `CROSSING_VISION_EVENT_END_WAIT_S` | 120 | 1 | Longest measured event 134 s; call anyway after this |
| `CROSSING_VISION_CLUSTER_S` | 60 | 1 | Same-door crossings inside 60 s of E share a call (D0-SIM V2: 133 sequences at 60 s) |
| `CROSSING_VISION_MAX_CONCURRENT` | 2 | 1 | Measured max 2 (§15.9.4) |
| `CROSSING_VISION_EVENT_RING` | 20 per camera | 1 | Bounded memory; ~10 events/h/camera peak |
| `CROSSING_VISION_KEEP_FRAMES` | True | 1 | llmvision `expose_images`, local `/media/llmvision/snapshots` (not `www`), so the operator can label frames in shadow. Retention of that folder is llmvision's; D0b reports whether it prunes. False = no frames kept |
| `CROSSING_VISION_ZERO_MIN_CROSSINGS` | 5 | 1 | Trip-wire floor |
| `CROSSING_VISION_ERROR_RATE_MAX` | 0.25 | 1 | Trip-wire bar; > 1 = off |
| `CROSSING_VISION_ERROR_MIN_CALLS` | 8 | 1 | Rev 2 F8: error trip-wire needs this many calls in the window before it can page |
| `CROSSING_VISION_TRIPWIRE_WINDOW_S` | 86400 | 1 | Rev 2 F8: the 24 h look-back of both trip-wires |
| `CROSSING_VISION_TRIPWIRE_EVAL_S` | 3600 | 1 | Rev 2 F8: hourly evaluation interval |
| `CROSSING_VISION_DESC_MAX_CHARS` | 200 | 1 | Rev 2 F8: cap on the stored `desc` |
| `CROSSING_VISION_TEARDOWN_GATHER_S` | 5 | 1 | Rev 2 F8: bound on gathering in-flight tasks at unload |
| (window for `frigate_events_in_window`) | reuse | 1 | Rev 2 F8: [E − `CROSSING_VISION_EVENT_MATCH_S`, E + `EGRESS_ENTRY_WINDOW_SECONDS`], no new literal |
| `CONF_CROSSING_VISION_PROVIDER_ID` | empty | 2 | D5 only; empty = reuse `CONF_PERIMETER_ENRICHMENT_PROVIDER_ID` |

Not added (stay Phase 2 names from §15): `CROSSING_VISION_WINDOW_GARAGE_A_S`, `_FRONT_S`, `CROSSING_VISION_COUNT_AUTHORITY`,
`CROSSING_VISION_DISAGREE_*`, `CROSSING_VISION_HEALTH_MAX_AGE_S`, `CROSSING_VISION_HEADCOUNT_INTERVAL_S`,
`CROSSING_VISION_INTERIOR_ENABLED`.

---

## 7. Cost per day (estimate; llmvision returns no usage)

Basis: D0-V token rules (OpenAI pages fetched 2026-11-13) and D0-SIM volume (14.1 crossings/day mean, cap 40).
gpt-4o-mini tile rule: base 2,833 + 5,667 per 512 px tile; 768 px frames are 2 tiles landscape (14,167 tokens) or 4 tiles
portrait (25,501); door mix 30/20 portrait/landscape → ~21,000 per frame. 4 frames ≈ 84,000 input tokens ≈ $0.0126 per
call at $0.15/1M; output ~150 tokens negligible.

| Model | Per call | Per day mean (14.1) | Per day at cap (40) | Per month mean |
|---|---|---|---|---|
| gpt-4o-mini, 4 frames (Phase 1 default) | ~$0.013 | ~$0.18 | ~$0.50 | ~$5.4 |
| gpt-4o-mini, 2 frames (fallback source) | ~$0.006 | ~$0.09 | ~$0.25 | ~$2.7 |
| gpt-6-luna, 4 frames (D5; patch rule × 1.2 assumed, $0.10/$0.50) | ~$0.0005 | < $0.01 | ~$0.02 | < $0.30 |
| D0 one-off (≤ 60 calls) | | ~$0.70 total | | |

Clustering lowers calls to ~10/day; `no_frigate_event` (~12 %) makes no call. These are upper-side estimates. The
§15.4 go rule (single-digit dollars/month) holds on gpt-4o-mini; Luna makes it negligible.

---

## 8. Emission / decision-site enumeration

| Site | File:line | Change |
|---|---|---|
| Bus fire `ura_person_egress_event` | `transit_validator.py:2191` | D2: +1 key |
| DB write `log_entry_exit_event(peak_person_count=...)` | `transit_validator.py:2298-2313` | D2: consumes the hoisted local |
| `_sample_peak_person_count` callers | `transit_validator.py:2298` (only caller; grep) | D2: moved, called once |
| `ura_person_egress_event` listeners | `sensor.py:4761, :4892, :5002, :5052`; `perimeter_alert.py:1006` (+ `live_arrival_slug(event.data)` `:5081`); `person_sighting.py:454-492` (develop, live) | unchanged; all read named keys via `.get` (plan review re-grepped, no `**event.data` splat). HA recorder stores the event payload (one more key per row; read by `scripts/probes/face_sighting_d0.py`, named keys) |
| llmvision call sites | `perimeter_enrichment.py:214` (image) | +1 (`video_analyzer`), same module |
| Frigate ingress consumers | `exterior_track_linker.py:305`, `perimeter_alert.py` (via `frigate_ingress`), census face bridge (topic handler) | +1 consumer `crossing_vision` (unique name, `frigate_ingress.py:183` warns on collision) |
| `memory_episodes` writers | many; this type is new | +1 type |
| Readers of the new type / hass key | none allowed beyond §3 INV-SHADOW list | reviewer D greps |

---

## 9. Sequencing: what can start now

1. **Now, in parallel (after this plan's review passes):**
   - Operator: add the second llmvision OpenAI entry (§2); confirm garage_a bay frames may go to OpenAI (D0-V already
     sent them; it is a semi-interior view).
   - `ura-prober`: D0a (once the entry exists), D0b, D0c, D0d.
   - `ura-builder`: D1 + D2 + D3 on `feature/crossing-vision-shadow` in `.claude/worktrees/builder-crossing-vision`. The
     frame-source function is written for `video_analyzer` first; if D0b fails, the fallback body replaces it before
     review. The builder uses the D0c fixture when it lands (stub map from §15.9.6 until then).
2. **Before deploy:** D0b and D0c pass (D0d may fail without blocking shadow; rev 3: it does not block Phase 2, §14.1 C1). Three framing-disjoint
   reviews (A correctness + edge cases; B async lifecycle, teardown, write queue, restart, wait_for cancellation into
   llmvision (F6), AND the Tier 2-DB payload-shape duty: field-by-field comparison of the egress event before/after
   for every listener in §8 incl. `person_sighting.py` and the recorder; C test authority by per-site mutation) + README.
3. **After deploy:** operator turns the switch on; live validation (Review D) per the Live rows; README write-back.
4. **~7-10 days later:** D4 disposition query; then Phase 2 plan revision or park. D5 any time after D0a passes.

No dependency on house-state step 1a or LOCK-RELEASE-ON-ARRIVING (Phase 1 reads only develop surfaces; the
`identity_provenance` key it copies already exists on develop's bus event; person sightings is already on develop).

---

## 10. Non-goals (Phase 1)

- Any census input, ledger, guest count, `vision_led` authority, or §15.7 deconfliction that changes a value (Phase 2).
- B stage time-lapse, chain cameras, interior head count, interior frames (Phase 2; `CROSSING_VISION_INTERIOR_ENABLED`
  not added).
- Naming or re-identifying anyone; llmvision memory with resident faces (§15.2: never).
- Person sightings at 0.3, `vision_consistent` flags on identity (Phase 2).
- Protect-only crossings (22 %): no live grab at E, no Protect thumbnail. Recorded as `no_frigate_event`. Revival
  trigger: D4 shows `no_frigate_event` > 25 % of crossings on a door group.
- A pre-t0 fast call (parked in §15.9.1).
- Two models per crossing (A/B) in shadow.
- Any NM message for a crossing; perimeter enrichment unchanged.
- Any frame extraction (ffmpeg) inside URA.

---

## 11. Tier classification

**Phase 1: Tier 2-DB.** Triggers: changes the payload shape of a dispatched event (D2 additive key) and adds a DB writer
(new `memory_episodes` type through the write queue). Standing policy (regression-prone) also applies: it rides the
crossing path that feeds census, perimeter D10.5 and arrival notifications. Not Tier 3: no value is threaded through a
state machine consumed by many sites, nothing cost-or-safety acts on it, and INV-SHADOW keeps it out of every decision.
Plan review: one adversarial review (Tier 2 rule); recommended framing = completeness (re-grep §8 and every reader of the
new type) because the failure mode that would matter is a hidden reader.

**Phase 2: Tier 3 + house-state rule** (vision feeding `unidentified_count` reaches GUEST, HVAC guest mode and the lock
regime guest night). Separate plan revision, two plan reviews, four code reviews, operator checkpoint before deploy.
Rev 3: planned in Part B; the reach above is corrected in §14.1 C2 (code wins: it reaches AWAY / ARRIVING, not GUEST).

---

## 12. Marginal benefit, priced

- **Simplest version that captures the learning:** one call per crossing on frames llmvision already knows how to pull,
  logged next to the existing camera count. That is Phase 1. It answers the operator's question ("can vision count
  arrivals and departures better than Frigate/Protect?") from live crossings within about a week, for under $1.50.
- **What the fancier pieces would add now:** B stage and chains (55-67 % chain-coverage ceiling, D0-SIM V5), head count,
  ledger, live grabs. Each adds a cloud call class, timing machinery or a second capture path, and none changes what
  Phase 1 measures. They wait for the D4 numbers.
- **Ingredient risk in Phase 1:** a cloud dependency and off-site door frames (privacy, already accepted for perimeter
  and D0-V), one additive bus key on a shared path (bounded by INV-ADDITIVE and a golden test), and a new writer
  (bounded by the per-crossing node id and the write queue). No synthetic time, no shared primitive change, no access path.

---

## 13. Cards to mint or update (orchestrator, after adjacency sweep)

- Update VISION-CROSSING-ANALYSIS-1: `status` → planned; link this plan; Phase 1 tier 2-DB, Phase 2 tier 3.
- New: VISION-CROSSING-SHADOW-1 (D1-D3 build), VISION-CROSSING-SCORER-1 (D4 + disposition), VISION-LUNA-PROVIDER-1 (D5,
  operator config action + Tier 1), VISION-CROSSING-PROTECT-ONLY-1 (parked, trigger in §10).
- Operator action card: LLMVISION-SECOND-OPENAI-ENTRY-1 (§2).

---
---

# PART B. Phase 2 (rev 6): vision for census accuracy, arrivals and speed

**Rev 6, 2026-11-13. Supersedes the rev 3-5 design (moved to `PLANNING_crossing_vision_partB_record.md`, an appendix that is NOT a build spec; only §B1 items bind). **§B10 wins over §B0-§B9: where §B2 / §B3 / §B6 / §B7 / §B9 below still say CONSUME for rows 7 / 15-18, list `test_away_entry_sites_ignore_vision` / `vision_led` / `evidence_only`, or name P2-F3, read §B10 instead.** Operator, rejecting the AWAY-hold design (verbatim): "We don't have an away problem. ... Away Provenance is
fine. Vision is to assist census accuracy. And assist arrivals accuracy and personalization. Especially when combined
with facial recognition from the nvr systems. Frankly our job is to make it faster and faster until it can eventually
be used in security applications too." And: "it seems like it will delay away and I need away to be fast acting.
That's how it saves $ on energy treatment."

**Shape in one paragraph.** The census keeps its existing numeric fields exactly as develop computes them (camera / BLE /
face): every house-state, AWAY, ARRIVING, security and lock reader keeps reading those, untouched. Beside them the census
publishes a vision-informed count set with provenance (`vision_unidentified`, `vision_total`, `count_provenance`), built
from the crossing ledger (record §16 rules, §16b B1/B2/B4/B8, unchanged). Each consumer opts in by verdict (§B3); policy
lives in the consumer. Arrivals gain "n came in, k recognised, n − k guests" by fusing the crossing count with the
existing egress identity. Speed is a first-class metric with a measured target and a probe before any latency build.
Everything ships dark (empty consumer-class set); each consumer class flips separately with operator approval. Tier 3.

**Dropped from rev 5:** the four AWAY-entry hold sites (§16b B5 `vision_hold`, B6, B9, §16a R3), INV-P2-NO-ACCESS as
"hold-only", Q6's answer. The census numeric fields are never changed by vision, so no AWAY interaction remains.

## B0. Anchored on the existing framework (rev 6.1; wins over §B3-§B6 wording)

> **FENCED (rev 7.1): §B0-§B10 are HISTORY, not instructions.** Build only from §B11. Where §B0-§B10 name
> `vision_unidentified`, `vision_total`, `vision_case`, `sensor.ura_census_vision_*`, `CROSSING_VISION_COUNT_AUTHORITY`,
> new `SIGNAL_CENSUS_UPDATED` keys, the R-7 "same NM tag" follow-up, or a `suggestion` class, §B11.0 says what replaces
> each. A rule from §B0-§B10 binds only if §B11.0 lists it as KEPT.

No new taxonomy. Two existing frameworks place every piece:
`IDENTITY_FUSION_CAMERAS_MANUAL.md` §5.5 (doctrine (a), classes (b), measure-first (c)) and
`PLANNING_person_sighting_layer.md` §2A (one identity model F1-F5, no-duplicates checklist).

**Placement in §2A.**

| Fact | Vision's role | Rule honoured |
|---|---|---|
| F1 P home | none | vision never moves a resident (INV-P2-IDENTITY) |
| F2 who is in the house (`PersonCensus`) | contribution through ONE census site (`_apply_enhanced_house_census`, `census_tick`) as the provenance-tagged `vision_unidentified` / `vision_total`; the existing F2 numeric fields are unchanged | census stays the single owner; it reads no sighting; `R = max(residents_home, identified_count)` subtracts the census's own union (incl. `register_egress_face`), so a named crossing person is not counted twice |
| F3 a door crossing + identity attach (`TransitValidator` / `EgressDirectionTracker`) | the vision count is an ATTRIBUTE of the F3 crossing: `n`, `term_source`, `k` (from the existing F3 attach and NVR names joined by the existing producer, never re-decided), `guests = n − k`, keyed by the crossing's `source_ref` (`egress_camera@E`) on the `crossing_vision_shadow` row | one crossing producer; vision adds no second crossing record and no second attach |
| F4 P seen at X at T | none: vision names no one, so it emits no sighting; source (c) egress projection is unchanged | a crossing is not a sighting; census and sightings never feed each other |
| F5 P is arriving | only through the existing single D2 site: when D2 emits an arrival tied to a crossing (egress arrivals are D0-gated and off today, `not_arrival_role`), its payload may carry that crossing's `n` / `guests` as an annotation. Vision creates no arrival of its own | F5 from F4 only through D2; access never reads F4 alone (INV-ACCESS) |

**Consumer classes = §5.5(b), plus the operator's AWAY rule.** §B3's verdict column maps as follows (no other class
exists):

| §5.5(b) class | Bar for vision-derived values | §B3 rows |
|---|---|---|
| Display (no confidence minimum) | flip after bars a, b, d, e | 15-18 census displays, 7 Path A → `visitors_present` / `guest_reason`, 22 residency / sightings annotation, 23 personalization suggestions (suggestion = display: it shows, never acts) |
| Notification naming (≥ 0.75 for a NAME) | names unchanged (identity confidence from F3, ≥ 0.75); the count phrase ("with N others") is a count annotation, gated by bars a-e + c + exact-count ≥ 90 % on ≥ 30 graded crossings | 21 `_arrival_departure_notify` (F3's one notification site; no second site) |
| Security suppress / de-escalate (≥ 0.9, de-escalate or annotate only; never escalate, actuate or suppress below 0.9, doctrine (a)) | EXCLUDED this cycle: a crossing count carries no identity confidence, so it cannot meet 0.9; a later Tier-3 security cycle sets its own bars | 9 SC auto-follow, 10 lock regime, 11 SanctionChecker, 12 perimeter severity |
| (trust readers of F2 outside §5.5(b): house-state inference) | EXCLUDED by the operator's hard rule (never delay AWAY) and because ARRIVING / WAKING would make a count an actuation trigger (doctrine (a)) | 1-6, 8, 13, 14, 19 |

§5.5(c) measure-first: the five metric sensors (§B5) and bars a-e ARE the measured production rate; no class flips
before its rate is measured. The authority class set in §B6 is therefore `{display, notification}`; `suggestion`
folds into `display`.

## B1. Kept from the reviewed record (binding unless restated here)

| Item | Where | Status |
|---|---|---|
| Ledger rules: terms (validator direction, vision count else camera peak else 1), clamp, floor `L = max(L, R)`, `unknown` at boot, late terms not applied | record §16 rules 1, 3, 4, 6; §16.2 | kept |
| Reset anchor: camera bodies 0 + not dark + no room rising edge + no entry term for 3600 s → `L = R` | record §16a R1, §16b B1-B3 | kept |
| `R = max(residents_home, identified_count)` | record §16a R4, §16b B4 | kept |
| Departure reconcile with late-outcome wait | record §16 rule 5, §16b B8 | kept |
| Census ↔ ledger single sync call `census_tick` | record §16b B4 | kept; returns `(guest_vis, healthy)`; no `vision_hold` |
| Stuck page (resident-independent) | record §16b B7 | kept |
| Bars a-e | record §17 | kept as the census-class flip gate (§B6) |
| PLB loop fix | record §16a R2 | kept, now by construction: `total_persons` is never vision-derived, PLB (`binary_sensor.py:2185-2189`, `:2232`) reads it |
| Corrections C1-C5, prior-art scan, fire check, P2-D0 (i)-(iv), P2-D1 Luna, P2-D7 groups | record §14, §15, §18 | kept |

## B2. Invariants (falsifiable)

**INV-P2-AWAY-LATENCY (hard, operator).** For any ledger value, vision result, authority setting or consumer flip, the
time at which the house enters AWAY is identical to develop for the same inputs. Mechanism: no AWAY-entry predicate reads
a vision-derived value (§B3 rows 1-4); `census_count`, `unidentified_count`, `total_persons` are byte-identical to
develop. Break it by: any read of `vision_*` / ledger / `guest_vis` in `presence.py` inference; any write of the ledger
into the existing census fields. [Superseded by §B10 R-3; do not build these two tests or drills.] Tests: `test_away_entry_sites_ignore_vision` (parametrised over the 4 sites: drive
`vision_unidentified = 3` / `vision_total = 5` with existing inputs that enter AWAY; AWAY returned on the same tick as
develop), `test_census_fields_byte_identical_vision_led` (golden replay, every existing numeric field equal to develop
under `vision_led`). Mutation drills (framing C): at each of the 4 sites, substitute the vision field for the existing
one → that parameter fails. Live: AWAY transition latency (last resident departure edge → AWAY row in
`house_state_log`) median and p90 over 7 days after the census-class flip within 10 % of the P2-D0 (v) baseline, and
identical tick-for-tick on a replay of the same inputs.

**INV-P2-DISCHARGE.** As record §16a R5 / §16b B1: after camera bodies 0, not dark, no rising edge, no entry term for
the window, `guest_vis` is 0 at the next evaluation, for any crossing sequence or resident tracker state.

**INV-P2-IDENTITY.** The ledger never changes `identified_count`, any `person_id`, `identity_provenance`, any resident's
home/away, or any input of `get_residents_home` (PLB included). Vision supplies counts, never names (§15.7 rule 2);
names come from NVR face / BLE only.

**INV-P2-EXCLUDED.** A consumer marked EXCLUDED (§B3) reads no vision-derived field. Break it by a reviewer-D grep hit
for `vision_unidentified|vision_total|count_provenance|guest_vis|crossing_ledger` outside the census producer, the
consumers marked CONSUME / GUARD, diagnostics and scripts.

## B3. Census output and consumer verdicts

**Producer (one site, `_apply_enhanced_house_census`, `camera_census.py:6407-6560`).** After `identified_count`: one
`census_tick` (record B4) → `(guest_vis, healthy)`. NEW `CensusZoneResult` fields (default so every other zone and
fixture is unchanged): `vision_unidentified: int | None` = `guest_vis` when `healthy` and the ledger is `known`, else None;
`vision_total: int | None` = `identified_count + vision_unidentified`; `count_provenance: str` ∈ `camera` (no vision value)
/ `vision` (vision value present) plus the per-crossing `term_source` tally in diagnostics; `vision_case` (A/B/C/D,
`CENSUS_AGREEMENT_*` vocabulary). Published in the `SIGNAL_CENSUS_UPDATED` payload as additive keys. Existing fields
unchanged. `vision_*` fields are populated in `evidence_only` too (consumers decide); the authority knob governs only
which consumer classes may READ them (§B6).

Verdicts (CONSUME = reads the vision field when its class is flipped; GUARD = reads it under a stated guard; EXCLUDED =
never reads it in this cycle):

| # | Consumer | File:line (develop) | Class | Verdict |
|---|---|---|---|---|
| 1 | Nobody-home AWAY | `presence.py:1181-1189` | AWAY entry | **EXCLUDED (INV-P2-AWAY-LATENCY)** |
| 2 | Path α | `presence.py:1227-1239` | AWAY entry | **EXCLUDED** |
| 3 | Path β | `presence.py:1300-1370` | AWAY entry | **EXCLUDED** |
| 4 | D2 external-empty ticks | `presence.py:7887-7895` | AWAY entry | **EXCLUDED** |
| 5 | ARRIVING from AWAY (`has_people`) | `presence.py:1349-1370` | house state | **EXCLUDED** (would make vision an arrival trigger; revisit in the security cycle) |
| 6 | SLEEP / HOME_* / WAKING, wake backstop, re-arm bypass, boot settle | `presence.py:199-204`, `:7027-7050`, `:7136-7150` | house state | **EXCLUDED** |
| 7 | Path A guest gate → `visitors_present`, `guest_reason` | `presence.py:6665-6693` | display | **CONSUME** (accuracy class) |
| 8 | GUEST night-stay latch | `_refresh_guest_stay` (DB walk) | house state | **EXCLUDED** (does not read the census) |
| 9 | SC auto-follow (`arriving → DISARMED`) | `security.py:189-195` | alarm | **EXCLUDED** (unreachable: rows 5/6 excluded) |
| 10 | Lock regime (garage lockout, away lock) | `security_lock_regime.py` | access | **EXCLUDED** (reads house state / person edges only) |
| 11 | `SanctionChecker unknown_present` | `security.py:282-346` | security | **EXCLUDED**, stays unwired |
| 12 | Exterior-person severity | `perimeter_alert.py:2004-2015` | NM severity | **EXCLUDED** |
| 13 | `PersonPhoneLeftBehindSensor` | `binary_sensor.py:2185-2189`, `:2232` | trust input | **EXCLUDED** (PLB loop, record R2) |
| 14 | HVAC (house state, zone persons) | `hvac.py` (no census read; `:8110` is a comment) | comfort | **EXCLUDED** (no read today; reaches HVAC only via house state, which is excluded) |
| 15 | `persons_in_house` / census sensors | `sensor.py:3753, :3776, :4148, :4216-4217, :5159-5220` | display | **CONSUME**: publish the vision fields as attributes; the state follows the existing field until the display class flips, then `guest_count` / `persons_in_house` show the vision value with `count_provenance` |
| 16 | `URAUnexpectedPersonSensor` | `binary_sensor.py:1891-1990` | display | **CONSUME** |
| 17 | `ZoneGuestCountSensor` | `aggregation.py:6696-6778` | display | **CONSUME** |
| 18 | `house_status.py` people field | `:206-210` | display | **CONSUME** (with provenance) |
| 19 | Presence `census_count` sensor | `sensor.py:5798, :6302-6316` | display of the AWAY input | **EXCLUDED** (it shows what AWAY uses; a vision count is shown on rows 15-18) |
| 20 | Census DB snapshot | `database.py:4485-4524` | record | existing columns unchanged; vision fields go to `crossing_vision_ledger` episodes (no schema change) |
| 21 | Arrival notification | `transit_validator._arrival_departure_notify` `:2603` | notification | **GUARD** (§B4: count annotation only, ≥ 0.75 naming bar unchanged) |
| 22 | Residency / person sightings | `residency.py`, `person_sighting.py` | display | **CONSUME** (arrival record annotation, §B4) |
| 23 | Personalization (PERSON-PROFILE-PREFERENCES-1, `pre_planning`) | none yet | suggestion | **GUARD**: suggestion-only reads of the arrival record; no actuation in this cycle |

Classes and flip order: **display** (15-18, 7, 22) first; **notification** (21) second; **suggestion** (23) when that
card builds. Security / locks / alarm / house state stay EXCLUDED until a later Tier-3 security cycle with its own bars
(§B8 non-goal).

## B4. Arrivals and identity: "n came in, k recognised"

Prior art (REUSE, nothing rebuilt):

| Piece | Existing symbol |
|---|---|
| Crossing identity | `_resolve_egress_face_identity_ex` → `EgressResolution`, `person_id`, `identity_confidence`, `identity_provenance` on `ura_person_egress_event` (manual §4.3) |
| NVR face sources | Frigate `sub_label` via the MQTT ingress (manual §4.5, FRIGATE-SUBLABEL-FACE-BRIDGE-1 done) and face-name sensors (registry-first, §1.1); Protect face name back-fill (~1-2 min, memory `reference_protect_face_latency_async`) |
| Second-name join | interior-fusion + asymmetric window (manual §5.2), abstain on conflict |
| Exit identity late-binding | exit backfill (manual §4.3a) |
| Sightings | `person_sighting` source (c) egress projection |
| Provenance | `IDENTITY_PROVENANCE_VISION` (`const.py:3442`): NOT used as an identity provenance (vision supplies no name). Used? No; KEEP + DOCUMENT. Count provenance is the new `count_provenance` |
| Arrival notify | `_arrival_departure_notify` (`transit_validator.py:2603`), naming bar `ARRIVAL_NAME_CONFIDENCE_THRESHOLD` 0.75 |

**NEW: the arrival record.** On each Phase 1 outcome for an entry (or exit) crossing, `CrossingVisionShadow` writes the
fused record into its existing `crossing_vision_shadow` row attrs (no new type): `n` (term count, with `term_source`),
`named` = the set of distinct resident slugs attached to this crossing or its cluster by the existing producer (bus
`person_id` of each member, plus any Protect / Frigate name that lands within `FACE_MATCH_WINDOW_S` of E on the door
group, read from the census's existing face ring, never re-decided), `k = len(named)`, `guests = max(0, n − k)`,
`identity_complete: bool`. Exit records update when the exit backfill names a row (listen to the existing
`SIGNAL_EGRESS_EXIT_BACKFILLED`). Display: `crossing_vision_last` gains `n`, `k`, `guests`. Notification (GUARD, class 2):
when the arrival notification fires, it may append "with N others" / "N people" from `n` when `term_source = vision`;
the name rule is unchanged. Personalization: the record is the input PERSON-PROFILE-PREFERENCES-1 reads (arrival room,
who, with how many), suggestion-only.

Discriminates: `k` vs `n` separates "vision miscounted" from "face missed": a resident-only crossing with `k = n` from
BLE/face confirms the count; `k < n` with BLE showing no extra resident is a guest candidate.

## B5. Speed: crossing-to-count latency

**Metric.** `latency_total = t_count − E` (E = camera edge; `t_count` = vision outcome applied to the ledger) per
crossing, split into `wait` (E → call start: t0 = E + 45 s, then event end or `EVENT_END_WAIT_S`), `call` (llmvision
p50 7.5 s, p99 17.8 s in D0b), and `apply`. Today's design total ≈ 45 s + up to 120 s + call: worst > 3 min.

**Target (proposed, operator to set):** p90 `latency_total` ≤ 60 s now (census accuracy and arrival annotation), with a
stated path to ≤ 15 s (security-grade, later cycle). Knob `CROSSING_VISION_LATENCY_TARGET_P90_S` (rung 1, 60) for the
trip-wire and sensor.

**Levers, each measured in P2-D0 (vi) before any build** (≤ 40 calls, read-only, same 45 crossings):

| Lever | Expected gain | Measure |
|---|---|---|
| L1 trigger at event START + fixed delay instead of event END | removes up to 120 s wait | count accuracy vs clip length at E + 10 / 20 / 30 s (open-event clip availability, Part A §1.6, unverified) |
| L2 snapshot-first (`image_analyzer` on Frigate best snapshot, 1 frame) then clip as confirmation | call p50 ~2 s (D0-V image path 2.1 s) | exact-count of snapshot-only vs clip on the same crossings |
| L3 fewer frames (`max_frames` 3 vs 4) | smaller payload | accuracy delta (keep ≥ 3, D0b) |
| L4 model / reasoning effort (gpt-6-luna effort none vs low; gpt-4o-mini) | call latency | p50/p99 and exact-count per model |
| L5 call at E, not t0 (do not wait for the validator's 45 s direction window; attach direction when it resolves) | removes 45 s | requires L1; ordering risk: count before direction (term applied at t0) |

Go rule per lever: adopt if p90 latency drops and exact-count stays within 2 points of the D0b 93.3 %. Build of adopted
levers = P2-D8 (Tier 2-DB, Phase 1 code path, shadow).

**Sensors (operator ask), one per metric, display, on the Crossing Vision device:** `sensor.ura_crossing_vision_exact_count_rate`
(7-day, from operator-graded crossings), `_blank_rate`, `_ledger_drift` (last residue + 7-day share of zero-residue
anchors), `_match_coverage` (share of crossings with a matched Frigate event / a vision term), `_latency_p90`. Values
computed from RAM rings rehydrated from `crossing_vision_shadow` / `crossing_vision_ledger` rows at setup (no new table).

**Grading page.** Once per day (knob `CROSSING_VISION_GRADE_DAILY_N`, rung 3, default 5; 0 = off), NM sends the operator
up to N crossings to grade (the kept key frame from `expose_images`, the vision count, the camera count), sampling
disagreements (case B/C) and groups first. Reply = the true count, recorded as a `crossing_vision_grade` episode keyed by
`crossing_key` (NEW type). Exact-count rate and bar c read the grades. Reuses NM actionable notifications (prior art:
NM reply / action handling, builder to cite the existing reply path; if NM has no free-text reply path, the grade is a
number select per crossing on a small dashboard card instead, decided in P2-D0 (vii)).

## B6. Ship dark, flip per class

`CROSSING_VISION_COUNT_AUTHORITY` (rung 1) becomes a set of enabled consumer classes, shipped empty (`evidence_only`):
`{"display", "notification"}` are the only legal members in this cycle (rev 6.1: suggestion is display, §B0) (a test pins that `security`,
`house_state` are rejected at import). `switch.ura_crossing_vision_census_authority` (rung 3) stays the downgrade-only
kill: OFF = no class reads vision. Flip per class = one reviewed const edit + operator approval at a Tier 3 checkpoint.
Gates: **display** = bars a, b, d, e (record §17); **notification** = display gates + bar c (groups) + exact-count rate
≥ 90 % on ≥ 30 graded crossings; **suggestion** = whenever PERSON-PROFILE-PREFERENCES-1 builds, display gates.

## B7. Deliverables and tiers

| ID | What | Tier |
|---|---|---|
| P2-D0 | Read-only probe: record (i)-(iv) + **(v) AWAY latency baseline** (last resident departure edge → AWAY row, 14 days, median/p90, plus the share of AWAYs via each path label) + **(vi) latency levers L1-L5** + (vii) NM reply-path prior-art check for grading | read-only |
| P2-D1 | Luna provider (record) | 1 |
| P2-D2 | `crossing_ledger.py` pure core (record §18 + B1/B8) | 3 |
| P2-D3 | Ledger wiring in `crossing_vision.py` (record §18, minus `vision_hold`) | 3 |
| P2-D4 | Census producer: `census_tick` + new `vision_*` / `count_provenance` fields + payload keys; existing fields byte-identical; INV-P2-AWAY-LATENCY tests and 4 mutation drills | 3 |
| P2-D5 | Authority class set, downgrade switch, trip-wires (record B7 stuck page; disagreement → AnomalyDetector NM; anchor-zero; bar regression per flipped class; latency p90 > target 3 days running → LOW) | 3 |
| P2-D6 | Scorer + disposition per class (record) | read-only |
| P2-D7 | Group walks (operator) | op |
| P2-D8 | Adopted latency levers (after P2-D0 vi) | 2-DB |
| P2-D9 | Arrival record n/k/guests + backfill listener + display attrs + notification annotation (guarded) | 3 (notification flip) / 2-DB (record + display) |
| P2-D10 | Five metric sensors + grading page + `crossing_vision_grade` episodes | 2-DB |
| P2-F1..F3 | Flips: display, notification, suggestion | each an operator-approved Tier 3 checkpoint |

Consumer-site tests: one per CONSUME / GUARD row (reads vision when its class is enabled, existing field otherwise), and
`test_excluded_consumers_never_read_vision` (grep + behavioural: excluded readers produce identical outputs with vision
fields at extreme values: 0, 50, None). Config extremes: authority empty vs all classes; switch OFF with classes on;
ledger `unknown`; grade N = 0.

Live rows (feed post-deploy validation): census payload carries `vision_*` and `count_provenance` with non-null values
after the first anchor; AWAY latency vs the P2-D0 (v) baseline (INV-P2-AWAY-LATENCY); existing census fields equal to
their pre-deploy values on a replayed hour; one `crossing_vision_shadow` row with `n`, `k`, `guests`; the five sensors
have states; one grading page delivered.

## B8. Non-goals

House-state, security, lock, alarm, sanction, perimeter severity and HVAC consumption of vision counts (a later Tier-3
security cycle with its own bars, revival trigger: notification class live ≥ 30 days with bars held and p90 latency at
its security target); vision supplying a name; vision direction; B-stage chains / interior head count; changing the
existing census fields; the AWAY-hold design (dropped, operator).

## B9. Open questions (defaults)

1. **Latency target.** Default p90 ≤ 60 s now; ≤ 15 s named as the security-cycle target.
2. **Display flip behaviour.** Default: `persons_in_house` / `guest_count` states switch to the vision value with a
   `count_provenance` attribute; alternative: keep states and add separate vision sensors.
3. **Grading volume.** Default 5 per day, disagreements and groups first.
4. **Notification wording.** Default append "with N others" only when `term_source = vision` and the display class
   is live; alternative: wait for the notification-class gates even for the count phrase.
5. **Grading UI.** Default NM reply if an existing reply path exists (P2-D0 vii), else a dashboard select card.

---

## B10. Rev 6.2: resolutions of the two rev-6.1 plan reviews (WINS over §B0-§B9 where they differ)

Reviews: `docs/reviews/code-review/plan_crossing_vision_p2_rev6_completeness.md` (8c793338),
`plan_crossing_vision_p2_rev6_buildpred.md` (1aa7b75d). Every finding is resolved below; nothing is deferred.

**R-1 Display: separate vision sensors (Q2 default changed; completeness HIGH-2, build-pred M1, M3).** Recommended and
adopted: no existing entity changes state. `sensor.universal_room_automation_persons_in_house`, `guest_count`,
`sensor.zone_*_guest_count`, `URAUnexpectedPersonSensor`, `CensusMismatchSensor` and `identified_persons_in_house` keep
develop's states and attributes (no new attributes on them). Why: `CensusMismatchSensor` (`binary_sensor.py:2043-2045`)
and the presence boot seed (`presence.py:3233-3239`) read census entity STATES, the dashboards (`ura_v7` 12x, `ura_v8` 13x,
v4-v6, PWA presence page) chart them, and a flipped state would silently change meaning, break recorded history and flap
whenever vision is None. NEW display entities (Census device, house level only; no per-zone vision value exists):
`sensor.ura_census_vision_guest_count` (state `vision_unidentified`), `sensor.ura_census_vision_total` (state
`vision_total`). State when the value is None (ledger `unknown`, unhealthy, dark, switch off, class not enabled):
`unknown`, with attribute `vision_status` in {`unknown_ledger`, `dark`, `switch_off`, `class_off`} and never a fallback to
the camera value (no source flapping). Attributes `count_provenance`, `vision_case`, `ledger_state`, `last_anchor` are in
`_unrecorded_attributes`; the states are recorded (two small ints). Before the display flip the entities exist and read
`unknown` / `class_off`, so dashboards can be added in advance. Rows 15-18 of §B3 become EXCLUDED (unchanged);
`house_status.py` (row 18) is EXCLUDED (it reads `presence.census_count`, the AWAY input; no second source added).

**R-2 Path A EXCLUDED (completeness MED-3, build-pred H1).** Row 7 is EXCLUDED: `_guest_gate_armed` (`presence.py:6917-6990`,
called `:7511-7515`) has a persistence latch, a recheck timer that schedules `_run_inference` (`:7003-7017`) and feeds
`_d5_guest_confidence` (`:7579-7582`, written `:8176`). `visitors_present` and `guest_reason` stay develop's. No vision key
is added to the presence run-inference trigger (`:5676-5685`). Consequence: **`presence.py` reads no vision value at all**;
that is now the INV-P2-AWAY-LATENCY mechanism. Revival (parked): a side-effect-free vision visitors leg, if the display
sensors prove useful.

**R-3 INV-P2-AWAY-LATENCY restated and re-anchored (completeness HIGH-1, build-pred hollow table).** For any vision
result, ledger value, class set or switch state, the AWAY entry time AND the number and timing of `_run_inference` calls
are identical to develop. Break it by any vision value reaching: (1) the `SIGNAL_CENSUS_UPDATED` keys presence reads
(`camera_census.py:1868-1900`: `interior_count`, `unidentified_count`, ...), (2) `PresenceCoordinator._handle_census_update`
(`presence.py:5609-5662`) or its trigger list, (3) the existing `CensusZoneResult` fields `total_persons` /
`unidentified_count` / `identified_count` in `_apply_enhanced_house_census`, (4) the boot seed (`presence.py:3224-3242`,
which reads `last.house.total_persons` or the `identified_persons_in_house` STATE), (5) `_inference_engine._confidence`.
Tests (replace the §B2 list):
- `test_away_tick_identical_with_vision_payload`: real `async_dispatcher_send(SIGNAL_CENSUS_UPDATED, payload)` with the
  vision keys at 50 and at None → `_handle_census_update` → `_run_inference`; scenario HOME_DAY, last resident leaves,
  camera 0; assert the AWAY transition tick and the count of `_run_inference` calls equal a golden captured from develop
  (committed fixture `quality/tests/fixtures/away_latency_golden_develop.json`). Golden provenance (rev 6.2.1): the
  fixture is generated by the test's own harness run against the develop merge-base in a commit that precedes every
  production change on the branch (a generator script under `scripts/`, re-runnable), with time frozen and the periodic
  inference timer driven explicitly so the `_run_inference` count is deterministic. The test ALSO asserts a same-build
  differential: payload without vision keys vs with them at 50 vs None → identical AWAY tick and call count. A golden
  regenerated on the branch after the build is a hollow oracle (#62) and a review finding.
- `test_census_existing_fields_golden_all_classes`: census-input replay with the class set = {display, notification} and
  switch ON vs the committed develop golden; every existing numeric field equal, AND the existing keys of the real
  `SIGNAL_CENSUS_UPDATED` payload the producer dispatches (captured by a dispatcher listener, `interior_count`,
  `unidentified_count`, `identified_count`, ...) equal to the golden (this is drill (1)'s red test).
- `test_boot_seed_ignores_vision_sensors`: vision sensors at 50 at setup; `_census_count` seeded as develop.
- `test_census_mismatch_sensor_unchanged`: vision at 50; `CensusMismatchSensor` state equal to develop.
Mutation drills (framing C), one per choke point: (1) publish `vision_total` under `interior_count`; (2) read
`vision_unidentified` in `_handle_census_update`; (3) assign `guest_vis` to `unidentified_count` in the producer; (4) seed
from `sensor.ura_census_vision_total`. Each must turn its named test red: (1) → `test_census_existing_fields_golden_all_classes` (payload half); (2) →
`test_away_tick_identical_with_vision_payload`; (3) → `test_census_existing_fields_golden_all_classes`; (4) →
`test_boot_seed_ignores_vision_sensors`. Grep anchor (supporting, not the test):
`grep -n "vision" domain_coordinators/presence.py` = no new hits (develop already has 1, unrelated).
Live: AWAY latency (last resident departure → AWAY row) median / p90 over 7 days after each flip within 10 % of the
P2-D0 (v) baseline (acceptance criterion, not a knob).

**R-4 INV-P2-EXCLUDED extended to state readers (completeness HIGH-2).** Mechanism: no existing entity changes (R-1), so a
state reader cannot see vision. Enumeration duty in review D: `grep -rn "states.get(" custom_components/` for the two NEW
vision entity ids must return only diagnostics; the PWA and dashboards may add them (display). Behavioural test:
`test_excluded_consumers_never_read_vision` injects vision values at 0 / 50 / None at TWO points (the census payload and
`CensusZoneResult`) and asserts identical outputs for: presence inference inputs, PLB, `CensusMismatchSensor`, the four
existing census sensors, `house_status`, SC auto-follow, lock regime, perimeter severity.

**R-5 Payload plumbing (build-pred M4).** The vision keys (`vision_unidentified`, `vision_total`, `count_provenance`,
`vision_case`) are added by hand to the literal dict at `camera_census.py:1868-1900`, values `int | None` as-is. Only
the two new sensors read them (from `census.last_result.house`, not the payload).

**R-6 Arrival record: one row per crossing after a bounded name wait (build-pred H3; Tier 2-DB writer, no new DAO).**
NEW episode type `crossing_vision_arrival`, written ONCE per crossing (clusters: once per cluster, keyed by the primary
`crossing_key`, member keys listed) by `CrossingVisionShadow` at `max(vision outcome time, E + CROSSING_VISION_NAME_SETTLE_S)`
for entries and `E + CROSSING_VISION_EXIT_NAME_SETTLE_S` for exits. Defaults: entry settle 180 s (covers Protect's 1-2 min
name back-fill, memory `reference_protect_face_latency_async`; P2-D0 (viii) measures Protect back-fill p99 and the knob is
set to p99 + 30 s), exit settle 660 s (the exit backfill window `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` 600 + 60). One tracked
`async_call_later` per crossing, cancelled at teardown; a restart drops pending records (counted, not replayed). `named` =
the union, canonicalised through `_canonical_person_slug`, of: the F3 bus `person_id` of each member crossing; the exit
backfill `person_id` re-read from `person_entry_exit_events` for exits; and fresh resident names on the door group's
face-name entities resolved registry-first (`face_name_entities_for_stem`, manual §1.1; covers Frigate and any Protect
face-name entity) whose `last_changed` ∈ [E − `FACE_MATCH_WINDOW_S`, settle time]. Read, never re-decided; `guest:*` names
count toward `k` as identified guests and are listed separately. `n` from the ledger term; `k = len(named residents ∪
named guests)`; `guests_unnamed = max(0, n − k)`. The Phase 1 shadow row is not updated (no UPDATE DAO). Readers:
`crossing_vision_last` display, the notification annotation (notification class), the scorer. Tier 2-DB (new writer,
new type in `MEMORY_WRITER_BACKED_EPISODE_TYPES`). Tests: `test_arrival_record_waits_for_late_protect_name`,
`test_arrival_record_one_row_per_cluster`, `test_exit_record_reads_backfilled_person_id`,
`test_arrival_record_teardown_cancels`. Mutation: write at the vision outcome without the settle → the first test fails.

**R-7 Notification gate, one rule (completeness MED-5, build-pred M5).** Timing (rev 6.2.1): `_arrival_departure_notify`
fires synchronously at direction resolution (`transit_validator.py:2228`), before the vision outcome exists (t0 = E + 45 s,
then event end + call). The arrival notification is NEVER delayed for a count (memory: alert latency over precision). The
count is delivered as a follow-up notification when the arrival record is written (R-6), only if the record has
`term_source = vision` and `n` > `k`; whether the follow-up replaces the original (NM tag) is for the builder to cite in NM
or omit. Test: `test_arrival_notify_not_delayed_by_vision` (notify call count and time unchanged with vision pending).
The "with N others" phrase is gated ONLY by the
notification class (display gates + bar c + exact-count ≥ `CROSSING_VISION_NOTIFY_EXACT_MIN` on ≥
`CROSSING_VISION_NOTIFY_MIN_GRADED` graded crossings). §B9 Q4's display-class default is withdrawn.

**R-8 Grading (build-pred M6).** One Companion actionable notification per crossing, action ids
`GRADE_URA_<crossing_key_hash>_<n>` for n in 0..4 plus `_more`; the handler maps the hash back through a RAM map of
pending grades (TTL 24 h) and writes one `crossing_vision_grade` episode. Never the free-text `_process_inbound_reply` /
safe-word path (`notification_manager.py:4055`). If Companion actions are unavailable for the operator's device, the
fallback is a dashboard select per pending crossing. Prior art (verified on develop 8d723d0f): `mobile_app_notification_action` → `_handle_companion_action`
(`notification_manager.py:1330`, handler `:3781`) dispatches on exact action ids (`ACKNOWLEDGE_URA`, `STATUS_URA`,
`SILENCE_URA`, `ACKNOWLEDGE_URA_CRITICAL`); the builder adds one `startswith("GRADE_URA_")` branch there (no second
listener). P2-D0 (vii) is closed by this cite.

**R-9 Latency levers vs bar data (build-pred M7).** Adopting any P2-D8 lever (or any model change) resets the bar window
(bars a-e and the exact-count rate restart their 7-day / sample counts; rows carry `pipeline_version`). P2-D8 dispatch is
blocked until the P2-D0 (vi) audit row exists.

**R-10 Knobs (completeness MED-6).** Added to the ladder (all rung 1 unless stated):

| Knob | Default | Why / kill |
|---|---|---|
| `CROSSING_VISION_CONSUMER_CLASSES` (replaces `CROSSING_VISION_COUNT_AUTHORITY`) | `frozenset()` | Legal members `display`, `notification`; any other member raises at import (`test_consumer_classes_rejects_illegal`). Empty = dark |
| `switch.ura_crossing_vision_census_authority` (rung 3) | ON | OFF = treat the class set as empty; downgrade only |
| `CROSSING_VISION_NOTIFY_EXACT_MIN` / `_NOTIFY_MIN_GRADED` | 0.90 / 30 | Notification class gate |
| `CROSSING_VISION_LATENCY_TARGET_P90_S` | 60 | Latency sensor target and trip-wire |
| `CROSSING_VISION_LATENCY_TRIPWIRE_DAYS` | 3 | p90 above target this many days running → LOW page; 0 = off |
| `CROSSING_VISION_METRIC_WINDOW_DAYS` | 7 | Window of the five metric sensors |
| `CROSSING_VISION_GRADE_DAILY_N` (rung 3) | 5 | Grading pages per day; 0 = off |
| `CROSSING_VISION_NAME_SETTLE_S` / `_EXIT_NAME_SETTLE_S` | 180 / 660 | Arrival record write times (R-6) |
| `CROSSING_VISION_GRADE_PENDING_TTL_S` | 86400 | Pending grade map TTL |

**R-11 LOWs.** `vision_case` uses the `CENSUS_AGREEMENT_*` values (`both_agree` / `close` / `disagree` / `single_source`),
mapped from the per-crossing A-D case (A → `both_agree`, B/C → `disagree` or `close` per `CROSSING_VISION_DISAGREE_FLAG_MIN`,
D → `single_source`); A-D stays only in the per-crossing row. `IDENTITY_PROVENANCE_VISION` is at `const.py:3458`;
INV-P2-IDENTITY adds `test_no_vision_identity_provenance_stamped` (no Phase 2 path writes `identity_provenance = "vision"`).
Phase 1 (`feature/crossing-vision-shadow`, 18e3ba59) merged to develop is a precondition for P2-D3 / D9 / D10. P2-F1
checkpoint includes a check of `automations.yaml` and dashboards for the two new entity ids (none exist yet).
Reconcile vs anchor: an anchor at or after a departure edge `t_e` voids that pending reconcile
(`test_anchor_voids_pending_reconcile`). The `suggestion` class and P2-F3 are dropped (suggestion = display). P2-D2 test
list adds `test_anchor_independent_of_house_state` and `test_guest_surplus_discharges_with_resident_phone_home` (their
drills had no named test).

**Updated verdict summary (supersedes §B3 rows 7, 15-18).** CONSUME (display): the two NEW vision sensors, the
`crossing_vision_last` diagnostic, the arrival record, personalization suggestions. CONSUME (notification):
`_arrival_departure_notify` count phrase. EXCLUDED: everything else in §B3, plus `CensusMismatchSensor`, the presence boot
seed, Path A / `visitors_present`, `house_status`, and every existing census entity.

**Updated deliverables (supersedes §B7 where different).** P2-D4 = census producer fields + payload keys + the two new
vision sensors + R-3/R-4 tests (Tier 3). P2-D9 = arrival record per R-6 (Tier 2-DB) + notification phrase (flip at
P2-F2). P2-D10 = five metric sensors + R-8 grading (Tier 2-DB). Flips: P2-F1 display, P2-F2 notification, each an
operator-approved Tier 3 checkpoint. P2-D0 adds (viii) Protect name back-fill p99 at door cameras.

---

## B11. Rev 7: split the census output by use (WINS over §B0-§B10 where they differ)

Operator decision 2026-11-13: "Do it. Let's get it right." The census publishes two views of F2. The house acts on the
trust view; people, notifications and personalization see the awareness view. Built on 56078763 (rev 6.2.1). Every
rev 6.2 rule not restated here stands (the AWAY choke-point tests in R-3, the ledger, bars a-e, R-6 settle times, R-8
grading, R-9, R-10 knobs except as renamed below).

### B11.0 Supersession map (rev 7.1; the builder's only list of what still binds from §B0-§B10)

| Earlier text | Status in rev 7 |
|---|---|
| §B3 producer fields `vision_unidentified`, `vision_total`, `vision_case` | REPLACED by `aware_guests`, `aware_total`, `aware_agreement` (§B11.1). Do not add `vision_*` fields |
| §B10 R-5 payload keys on `SIGNAL_CENSUS_UPDATED` | DROPPED. No new key is added to the payload dict (`camera_census.py:1868-1900`); awareness readers use `get_house_census` only. The payload stays byte-identical (R-3 drill (1) still applies) |
| §B10 R-1 `sensor.ura_census_vision_guest_count` / `_vision_total`, state `unknown` when no vision | REPLACED by `sensor.ura_census_guests_around` / `_people_around`, never `unknown` (§B11.2) |
| §B6 `CROSSING_VISION_COUNT_AUTHORITY`, `suggestion` class, P2-F3 | REPLACED by `CROSSING_VISION_CONSUMER_CLASSES` (R-10) + `CROSSING_VISION_AWARENESS_VISION_LEADS` (§B11.1); suggestion = display |
| §B2 / §B7 4-site AWAY tests | REPLACED by R-3 choke-point tests, run per §B11.4 |
| §B10 R-7 / §B11.5 "same NM tag" amend | REPLACED by the quiet follow-up (§B11.5, NM has no tag) |
| §B9 Q2, Q4 | WITHDRAWN (§B11.2, §B11.5) |
| §B1 ledger rules, §B10 R-3 choke points + golden provenance, R-4, R-6 (plus §B11.5 writer rules), R-8, R-9, R-10 (renamed), R-11 except `vision_case` | KEPT |

### B11.1 The two-view contract (F2, single writer `PersonCensus`)

| | Trust view (F2-T) | Awareness view (F2-A) |
|---|---|---|
| Question | Who does the house act on? | Who is around, best estimate? |
| Value | today's `CensusZoneResult` fields `identified_count`, `identified_persons`, `unidentified_count`, `total_persons`, payload keys at `camera_census.py:1868-1900`, existing entities | NEW fields on the house `CensusZoneResult`: `aware_guests`, `aware_total = identified_count + aware_guests`, `aware_identified` (= trust `identified_persons`, same union, no second identity path), `count_provenance`, `aware_agreement` |
| Arithmetic | develop, byte-identical | §15.7 deconfliction (person-sighting plan §15.7, operator rule "both vision and Frigate/Protect person counts with deconfliction until we trust vision"): `guest_cam` = the trust view's post-hold `unidentified_count`; `guest_vis` = ledger `max(0, L − R)`. Case A agree → shared value; B vision higher / C camera higher → `guest_cam` while vision is untrusted, `guest_vis` once `CROSSING_VISION_AWARENESS_VISION_LEADS` is True; D one side missing → while untrusted `guest_cam` (the camera estimate always exists; a camera-dark tick yields the trust view's held value, so `vision_only` cannot raise anything), once leading the side that exists. Rule while untrusted, all cases: `aware_guests = guest_cam`. `aware_agreement` uses `CENSUS_AGREEMENT_*` (`const.py:2439-2446`): A → `both_agree`, B/C within `CROSSING_VISION_DISAGREE_FLAG_MIN` → `close`, else `disagree`, D → `single_source` |
| Provenance | implicit (camera / BLE / face) | `count_provenance` ∈ {`camera`, `vision`, `agree`}: which estimate produced `aware_guests` |
| Readers (§5.5(b) class) | house-state trust (AWAY, ARRIVING, SLEEP, WAKING, GUEST latch, Path A, boot seed), PLB, `CensusMismatchSensor`, `house_status`, security de-escalate (SC, locks, SanctionChecker, perimeter severity), HVAC, every existing census entity and dashboard card | display (new awareness entities, `crossing_vision_last`, PWA when repointed), notification naming (arrival count phrase, names still ≥ 0.75 from F3), personalization (PERSON-PROFILE-PREFERENCES-1, suggestion = display class) |
| Invariant | INV-P2-AWAY-LATENCY, R-3 choke-point tests unchanged | INV-P2-AWARE-NO-TRUST (below) |

At ship, vision does not lead (`CROSSING_VISION_AWARENESS_VISION_LEADS = False`), so `aware_guests == guest_cam` in every
case and the awareness view equals the trust view plus agreement metadata. That is the dark state. The rev 6.2 consumer
class set `CROSSING_VISION_CONSUMER_CLASSES` stays and now means "which classes may READ the awareness view"; while a class
is not enabled its readers fall back to the trust view (byte-identical behaviour).

Two flips, each an operator-approved Tier 3 checkpoint:
- **F-LEAD**: `CROSSING_VISION_AWARENESS_VISION_LEADS = True` (rung 1). Gate: bars a, b, d, e (record §17) AND every
  §15.7a number (≥ 100 graded crossings over ≥ 7 days incl. ≥ 10 with a non-resident; exact ≥ 95 % overall, ≥ 90 % at
  night, per door; vision wins ≥ 80 % of B/C disagreements; false guest ≤ 2 %; healthy ≥ 95 %). After the flip the
  same numbers over a rolling 14 days are a trip-wire (AnomalyDetector → NM, "revert F-LEAD"), built in P2-D5.
  Affects only awareness readers, and changes the visible number on any card repointed under §B11.9 Q1.
- **F-NOTIFY**: add `notification` to the class set. Gate: R-7 (bar c + exact-count ≥ 0.90 on ≥ 30 graded) AND
  EGRESS-DIRECTION-AWARE-IDENTITY-1 shipped or its entry attach rate measured ≥ `CROSSING_VISION_NOTIFY_MIN_ATTACH`
  (0.50) (§B11.6).
`CROSSING_VISION_CONSUMER_CLASSES` ships as `frozenset({"display"})` (rev 7.1; supersedes R-10's `frozenset()` default): the awareness entities equal trust until F-LEAD, so enabling display at deploy protects nothing by staying off. `notification` is added only at F-NOTIFY.

### B11.2 Per-entity decision: existing entities stay on the trust view

Evidence that switching is unsafe: `CensusMismatchSensor` reads the `persons_in_house` STATE (`binary_sensor.py:2043-2045`)
as "camera count"; the presence boot seed reads the `identified_persons_in_house` STATE into `_census_count`, an AWAY
input (`presence.py:3233-3239`); `ura_v7` (12x) / `ura_v8` (13x) / v4-v6 dashboards and the PWA presence page chart
`persons_in_house`; `ZoneGuestCountSensor` (`aggregation.py:6696-6778`) mirrors a house value into every zone (no per-zone
vision value exists). Re-pointing every state reader is possible for the two code readers but not for recorded history and
external dashboards, and the trust view must stay visible to diagnose AWAY. Decision:

| Entity | View | Note |
|---|---|---|
| `sensor.universal_room_automation_persons_in_house` | trust | unchanged |
| `guest_count`, `identified_persons_in_house`, `total_persons_on_property` | trust | unchanged |
| `sensor.zone_*_guest_count` | trust | unchanged (house value mirrored; no per-zone awareness value) |
| `URAUnexpectedPersonSensor`, `CensusMismatchSensor` | trust | unchanged |
| Presence `census_count` sensor, `visitors_present` | trust | unchanged |
| NEW `sensor.ura_census_people_around` | awareness | state `aware_total`; replaces rev 6.2's `ura_census_vision_total` |
| NEW `sensor.ura_census_guests_around` | awareness | state `aware_guests`; replaces `ura_census_vision_guest_count` |

The awareness entities are the canonical "who is around" set (house level; per-zone awareness waits for
VISION-INTERIOR-SIGHTINGS-1). Their state is never `unknown` (they always have the camera estimate); attributes
`count_provenance`, `aware_agreement`, `vision_status` (`unknown_ledger` / `dark` / `switch_off` / `ok`), `ledger_state`
are unrecorded. Operator action at deploy: repoint the headline "people" cards on `ura_v8` and the PWA to the awareness
entities (list produced by P2-D0 (ix): every dashboard / PWA reference to the trust entities).

### B11.3 Read API: PERSON-AWARENESS-READ-API-1 (recommend: minimal slice first, in this cycle; full migration parallel)

Recommendation: land a MINIMAL read slice as the first build step of this cycle (Tier 2, byte-identical, before P2-D4),
and run the card's full migration (the ~40 private `PersonCensus` reads and 14+ id-normalisation copies, inventory
`AUDIT_person_awareness_interface_inventory_2026_11_13.md` §4-§5) as a parallel Tier 2 cycle. Why: every NEW consumer in
this plan (awareness entities, arrival notify count, personalization) should be born on the API, so no new ad-hoc field
reads appear; the full migration is a refactor of existing readers that need not gate vision.

Slice (on `PresenceCoordinator`, the inventory's recommended home, §0 item 2):
- `get_house_census(view: Literal["trust", "awareness"]) -> HouseCensusView` (frozen dataclass: `identified`,
  `unidentified_or_guests`, `total`, `provenance`, `agreement`, `as_of`), reading `census.last_result.house`
  (never `_census_count`), sync, never raises (missing census → None).
- `view_for_class(cls: str) -> str`: returns `awareness` ONLY when `cls` ∈ {`display`, `notification`} AND `cls` is in
  `CROSSING_VISION_CONSUMER_CLASSES` AND the downgrade switch is ON; every other input (`house_state`, `security`,
  `hvac`, any unknown or misspelt string, switch entity missing) → `trust`. Allow-list, never a deny-list.
- Callers in this cycle: the two awareness entities, `crossing_vision_last`, `_arrival_departure_notify` count phrase,
  and the PERSON-PROFILE-PREFERENCES-1 read seam. The inference path never calls it (INV-P2-AWAY-LATENCY break rule
  amended: a vision value may exist in `presence.py` only inside `get_house_census`; mutation drill: in
  `_handle_census_update`, assign `get_house_census("awareness").total` to the value it currently takes from
  `interior_count` → `test_away_tick_identical_with_vision_payload` fails. Calling and discarding is not a drill).
Tests: `test_get_house_census_trust_equals_last_result`, `test_view_for_class_security_always_trust`,
`test_view_for_class_display_follows_class_set`, `test_get_house_census_missing_census_none`.

### B11.4 Invariants (rev 7)

- **Non-hollow test configuration (rev 7.1, #63).** At the dark default `aware_guests == guest_cam`, so any leak of an
  awareness value into a trust reader is invisible. Every INV-P2-AWAY-LATENCY and INV-P2-AWARE-NO-TRUST test and drill
  runs with `CROSSING_VISION_AWARENESS_VISION_LEADS = True`, class set `{display, notification}`, switch ON, and a
  ledger state where `guest_vis ≠ guest_cam` (e.g. camera 0, ledger L = R + 3), in addition to the dark default.
- **INV-P2-AWAY-LATENCY**: unchanged (rev 6.2 R-3), plus the read-API drill above. Grep anchor extended: `aware_` in
  `presence.py` appears only inside `get_house_census` / `view_for_class`.
- **INV-P2-AWARE-NO-TRUST (new)**: no reader in the house-state, security or HVAC classes, and no existing entity, reads
  an awareness field (`aware_*`, `count_provenance`) or `get_house_census("awareness")`; `view_for_class` returns
  `trust` for those classes under every config. Break it by a grep hit outside the slice callers, or a config that makes
  `view_for_class("security")` return `awareness`. Test: `test_excluded_consumers_never_read_vision` (R-4) extended to
  the awareness fields; `test_view_for_class_security_always_trust` parametrised over every class-set and switch value and over classes `house_state`, `security`, `hvac`, `""`, `"Display"`, `"suggestion"`.
- **INV-P2-AWARE-DECONFLICT (new)**: while `CROSSING_VISION_AWARENESS_VISION_LEADS` is False, `aware_guests == guest_cam`
  for every input (cases A-D). Test: `test_awareness_equals_trust_until_lead` (golden over the four cases). Mutation:
  let case B pick `guest_vis` → red.
- **INV-P2-DISCHARGE**, **INV-P2-IDENTITY**: unchanged.

### B11.5 Review-D amendments (reconciliation review `v_perimeter_vision_reconciliation_D.md`, 47579bac, items 8-9)

- **R-6 / R-8 writers:** `crossing_vision_arrival` and `crossing_vision_grade` rows are written with
  `dedup_source_ref=False` and per-crossing `node_id` `vision_arrival:<crossing_key>` / `vision_grade:<crossing_key>`.
  `source_ref` stays `egress_camera@E` for the scorer join. "Once" is enforced by the producer (one tracked
  `async_call_later` per crossing), not the DAO: with `True`, the global `source_ref` check at `database.py:10765-10770`
  (no type filter) would skip every row because the shadow and egress-outcome rows already hold that key. Test:
  `test_arrival_row_written_despite_existing_shadow_row` (seed a shadow and an outcome row with the same `source_ref`;
  the arrival row is written).
- **R-7 count follow-up (rev 7.1, verified):** NM has NO tag / replace-by-tag on any channel. `async_notify`
  (`notification_manager.py:1531-1545`) takes no tag parameter and the module contains no `tag` key;
  `_arrival_departure_notify` calls it with `coordinator_id`, `severity=LOW`, `title`, `message` only
  (`transit_validator.py:2652-2657`). The existing late-information pattern is a separate `quiet=True` follow-up
  (PERIMETER-IDENTITY-FOLLOWUP-1, `notification_manager.py:1544-1554`; memory: alert latency over precision). Decision:
  the count follow-up is ONE `async_notify(..., quiet=True)` call, severity LOW, sent when the arrival record is written,
  only under F-NOTIFY and only if `term_source = vision` and `n > k`; no replace, no new NM mechanism. Per crossing: at
  most 2 arrival sends (original + quiet follow-up) plus the perimeter alert and its one identity follow-up, unchanged.
  Test: `test_r7_and_perimeter_followup_same_crossing` (arrival sends ≤ 2, the follow-up has `quiet=True`, perimeter
  sends unchanged vs develop).

### B11.6 Operator goals restored

**(i) Two-stage latency (fast sample → time-lapse batch → synthesis), person-sighting plan §15.5 F/B/S.**
- F (fast): at the Frigate event START on the door group (not end), `image_analyzer` on 1-3 frames (event snapshot +
  latest frames via the Frigate proxy), Luna; result `stage = provisional`, recorded on the shadow row and shown on the
  awareness entities' `last_crossing` attribute only. Never applied to the ledger.
- B (batch): today's Phase 1 `video_analyzer` call at event end (or `EVENT_END_WAIT_S`); `stage = final`.
- S (synthesis): at `max(B outcome, E + NAME_SETTLE_S)` (R-6) join F, B, names, camera counts → the arrival record and
  the ONE ledger term (final count; F is used only if B failed). F vs B disagreement is recorded (`revised`).
- Latency metrics: `t_provisional − E` (target p90 ≤ `CROSSING_VISION_LATENCY_TARGET_P90_S` 60 → later ≤ 15),
  `t_final − E`, `t_synthesis − E`; the five metric sensors report provisional and final.
- **P2-D0 (vi) becomes a timing simulation, not only a lever list:** replay the 117 D0c clusters with their Frigate
  event start/end times and the D0b call-latency distribution to compute, per stage, the arrival-time distribution and
  the share of crossings where F's count would equal B's (using D0-V image-path accuracy for F). Output: per-stage p50 /
  p90 and the F=B share. Gate: build F (P2-D8) only if simulated F p90 ≤ 60 s AND F=B share ≥ 85 %. Adopting F resets
  the bar window (R-9).

**(ii) Arrival accuracy depends on EGRESS-DIRECTION-AWARE-IDENTITY-1.** `k` (recognised) comes only from the F3 attach
and NVR names; about 30 % of entries carry `person_id` today, so most arrival records will show "n came in, k < n
recognised" with residents among the unnamed. Sequence: the arrival record (P2-D9) and display ship regardless (k is
honest as "recognised so far"); F-NOTIFY waits for that card or a measured entry attach ≥ 0.50
(`CROSSING_VISION_NOTIFY_MIN_ATTACH`, rung 1), so a notification never calls a resident a guest at scale. Card dependency:
VISION-CROSSING-ANALYSIS-1 Phase 2 notification flip `blocked_by` EGRESS-DIRECTION-AWARE-IDENTITY-1.

**(iii) Personalization is a named consumer.** PERSON-PROFILE-PREFERENCES-1 reads the awareness view and the arrival
record through the read API (`get_house_census(view_for_class("display"))` and a `get_last_arrival_record()` getter
added to the slice), suggestion-only (display class): "Oji arrived with 2 others → suggest the guest scene", never
actuation in this cycle.

**(iv) VISION-INTERIOR-SIGHTINGS-1 is the next step; nothing here forecloses it.** The awareness deconfliction takes its
vision estimate through one function (`_awareness_vision_estimate`) that can later add an interior head-count source;
per-zone awareness is left to that card; unnamed interior sightings are F4 evidence and will not feed the census
directly (§2A: census and sightings never feed each other), so that card must add its count through the same awareness
function, not through sightings. The parked name `CROSSING_VISION_INTERIOR_ENABLED` stays reserved.

### B11.7 F and class map, per section

| Section | Produces | Consumes | Readers and §5.5(b) class |
|---|---|---|---|
| Part A D1-D3 shadow producer | F3 attribute (vision count per crossing) | F3 bus event | scorer, diagnostics: display |
| Record ledger rules / §B1 | F2-A input (`guest_vis`) | F3 crossing terms, F1 departures (reconcile), F1 residents (`R`) | census awareness site only |
| §B11.1 census | F2-T (unchanged), F2-A | ledger, census camera counts | trust: house-state / security / HVAC; awareness: display, notification |
| §B11.2 entities | — | F2-T or F2-A per row | display (both), trust-state readers on F2-T |
| §B11.3 read API | read surface for F1, F2-T, F2-A | census `last_result` | by class (`view_for_class`) |
| R-6 arrival record | F3 attribute (n, k, guests) | F3 attach, NVR names, F2-A | display; notification (count phrase) |
| §B11.6 (i) F stage | F3 attribute (provisional) | Frigate event | display only |
| F5 | none produced; annotation only through the D2 site (§B0) | — | per D2 |
| R-8 grading | grades (scorer input) | operator | display / operator |

### B11.8 Deliverables (rev 7 deltas)

| ID | Change | Tier |
|---|---|---|
| P2-RA | NEW: read-API slice (§B11.3), lands first | 2 |
| P2-D0 | adds (vi) timing simulation, (ix) dashboard / PWA reference list for the trust entities | read-only |
| P2-D4 | census: awareness fields + deconfliction + the two awareness entities (replace the rev 6.2 vision sensors) + INV tests | 3 |
| P2-D8 | F stage (only if the simulation gate passes) | 2-DB |
| P2-D9 | arrival record with B11.5 writer rules; count follow-up per B11.5 | 2-DB (record) / 3 (F-NOTIFY) |
| F-LEAD, F-NOTIFY | the two flips (§B11.1) | Tier 3 operator checkpoints |
| PERSON-AWARENESS-READ-API-1 | full migration, parallel | 2 (own plan) |

New knobs (rung 1): `CROSSING_VISION_AWARENESS_VISION_LEADS` (False; the F-LEAD switch), `CROSSING_VISION_NOTIFY_MIN_ATTACH`
(0.50), `CROSSING_VISION_DISAGREE_FLAG_MIN` (1, §15.7: |guest_vis − guest_cam| below it = `both_agree`, else `close` / `disagree` per §B11.1), `CROSSING_VISION_DISAGREE_PERSIST_N` (5 in 24 h per camera → AnomalyDetector NM; 0 = off), `CROSSING_VISION_FAST_STAGE_ENABLED` (False until P2-D8), `CROSSING_VISION_FAST_MAX_FRAMES` (3). Renamed entities
per §B11.2.

### B11.9 Open questions (defaults)

1. **Headline entity on dashboards:** default repoint the `ura_v8` / PWA (in-repo `dashboard-v3/src/components/tabs/Presence.tsx`) "people" headline to `people_around` at deploy
   (equal to trust until F-LEAD; the new entity starts with no history). The house-visible change happens at F-LEAD, so the
   F-LEAD checkpoint lists the repointed cards. Keep trust entities on a diagnostics card.
2. **Read API sequencing:** default minimal slice first in this cycle, full migration parallel (§B11.3).
3. **F-NOTIFY dependency:** default wait for EGRESS-DIRECTION-AWARE-IDENTITY-1 or measured entry attach ≥ 0.50.
4. **Count follow-up:** decided (rev 7.1): one quiet follow-up, NM has no replace-by-tag (§B11.5).
5. **Fast stage:** default build only if the simulation shows p90 ≤ 60 s and F=B ≥ 85 %.
