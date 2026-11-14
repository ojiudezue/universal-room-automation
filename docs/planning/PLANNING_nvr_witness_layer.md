# PLANNING: NVR witness layer (one record of which NVR saw a person, where and when; policy stays with each feature)

Card: NVR-WITNESS-CONSOLIDATION-1 (batch person-sightings, parent VISION-CROSSING-ANALYSIS-1). Plan amendment for the
operator, 2026-11-13, rewritten after plan reviews 1 and 2 (`docs/reviews/plan-review/PLANREVIEW_nvr_witness_layer_1.md`,
`_2.md`). One clean doc; nothing here edits another plan (edits other plans need: §11).
Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Arc map: `ARC_identity_vision_census_map.md`.
Read for this plan: the card, `AUDIT_protect_clip_witness_probe_2026_11_13.md`, `AUDIT_protect_face_name_interfaces_2026_11_13.md`,
`AUDIT_frigate_face_name_latency_2026_11_13.md`, `AUDIT_crossing_vision_d0_2026_11_13.md`, `PLANNING_camera_input_stream_health.md`,
`PLANNING_crossing_vision.md`, `PLANNING_census_deconfliction.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1-§5.5, the ura-arc
skill, memories `reference_pooloverhead_four_integrations`, `reference_frigate_ghost_evidence_chain`. HVAC and presence
state-of-play docs were not read by the planner; W5b and W5c builders read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and
`SENSOR_FLEET_CLASSES.md` completely first.

## 1. Charter, operator words, decisions, goal

Operator, verbatim: "For all camera work I like to exercise both nvr platforms simultaneously, then cross compare to
reduce errors... How can protect be a separate witness? ...centralize the rules to deconflict to increase confidence."
"I generally favor consolidation so there's no drift and there is one place to make better... Bring me a plan amendment
but it's not necessary to disturb what's in flight. ...check to see if the protect mechanics will allow easy
implementation." On the per-camera agreement record: "Critical for learning. Has to be baked into the design. Note this."
Charter goals served: "Vision is to assist census accuracy. And assist arrivals accuracy... Especially when combined with
facial recognition from the nvr systems"; "guests should be both vision and frigate/protect person counts with
deconfliction"; settings "help with accuracy (first)". Hard constraint: "I need away to be fast acting" (nothing here
touches AWAY, house state or locks).

Decisions: Q2 YES (one paid llmvision call on a Protect clip before W4). Q4 YES (W1 ships ahead, alone).
PENDING operator yes: Q1 default `all`, Q3 default dedicated DB table (§12).

Goal: one evidence layer that (a) records every Frigate and Protect person fire per physical camera, (b) keeps a
per-camera agreement record, learned once, persisted, read by every feature (first-class; the plan cannot ship without
it), (c) classifies NVR family in one function, (d) gives crossing vision Protect as a real second witness. Each feature
keeps its own decision.

### 1.1 Critique of "centralize the evidence, keep policy per feature"

Today: four comparison sites with four windows (none / 10 s / 60 s / state now) and four meanings of "agree" (§4.2),
plus nine suffix or platform classifiers (§4.1). Centralising the decisions too would move census (how many), transit
(did two NVRs see this crossing), perimeter (demote a lone alert) and room fusion (is the camera evidence contested now)
together, across display, comfort and security classes: the opposite of a safe migration. So the evidence, the
classifier, the agreement record and the predicates (`corroborated`, `families_on_now`) are central; each feature
supplies its window and decides. Every window is a named knob in one const block. Every site is migrated or carries a
written KEEP reason.

## 2. F1-F5 and consumer classes

Produces F3/F4 evidence ("NVR family X saw a person on physical camera C at time t"). Names no one, attaches no
identity, writes no F2.

| Reader | Uses | Class |
|---|---|---|
| Transit crossing confidence (`transit_validator.py:2165`) | `corroborated(cam, t, 10)` | display (review 1: no decision reader of crossing `confidence`) |
| Perimeter single-source demote (`perimeter_alert.py:4924`), leg tags | `family_of`, families live, alert-sample rate | security (severity de-escalate) |
| Room camera fusion `agreement` (`binary_sensor.py:1827-1860`) → fan veto (`fan_veto.py:424-441`) | `families_on_now`, `family_of` | comfort |
| Crossing vision | Protect event entity, clip range, per-crossing family set | display (Phase 1); F2 input via census only (Phase 2) |
| Census (`_cross_validate_platforms`, `deconflict_house`) | `platform_for` mapping, families live, agreement provenance | F2 input; new reads awareness only |
| `sensor.ura_nvr_witness`, weekly scorer | agreement record | display |

## 3. Institutional context verified (REUSE or NEW per piece)

| Piece | Verdict | Where |
|---|---|---|
| Person legs per physical camera | REUSE `resolve_detection_legs`, `DetectionLeg` | `camera_resolver.py:1117`, `:165` |
| Engine tag from device integration | REUSE `_engine_tag` | `camera_resolver.py:1433` |
| NVR family from engine | REUSE `nvr_family`, moved into `nvr_witness.py`, re-exported from `perimeter_fp_gates.py:16` | |
| Frigate object name of a device | REUSE `_frigate_object_name_for_device` | `camera_resolver.py:1519` |
| Physical camera key | REUSE `canonical_camera_key` | `camera_resolver.py:460` |
| Agreement tracker shape | REUSE `AgreementTracker` semantics for alert samples | `perimeter_fp_gates.py:129` |
| DB table creation, batched DAO, nightly prune | REUSE `_create_table_safe` (`database.py:773`), `log_hvac_evidence_shadow` batched `executemany` shape (`:7739`), `prune_hvac_evidence_shadow` batched delete (`:7787`), writes through `_db()` (`:580`) and the serialized write path | |
| Stream-dead state | REUSE stream-health getter, camera-keyed form from S2 | `PLANNING_camera_input_stream_health.md` |
| Protect clip / event | REUSE HA proxy `/api/unifiprotect/video/{entry}/{camera}/{start}/{end}` (`views.py:275`); `event.*_smart_detection` `event_id` | probe Q1 (live 200) |
| Clip into llmvision | REUSE `video_analyzer` `video_file` `/api` path | llmvision 1.7.1 `media_handlers.py:629-642` |
| Crossing vision call contract | REUSE `perimeter_enrichment.analyze_crossing_frames` | crossing vision D1.7 |
| Zero-fire page | REUSE `fire_stuck_signal(..., severity=)` | `_stuck_signal_nm.py:165` |
| `nvr_witness.py`, fire ring, episodes, `family_of`, `platform_for`, predicates | NEW (no shared helper exists; probe Q5, review re-greps) | |
| Table `nvr_witness_records` + DAO | NEW (no equivalent among the 53 `CREATE TABLE` sites; perimeter history lives in `.storage`) | `database.py` |
| Protect event entity per device | NEW resolver helper by device id (grep `smart_detection`: none) | `camera_resolver.py` |

Prior art: perimeter FP build D5 tracker, crossing vision, census deconfliction, stream health, arc map M2/M4; ghost chain
(operator ruling: cross-corroboration over latency gates; this layer is its shared home); pool overhead (family from
device integration; Dahua, Amcrest, Reolink are their own families). Parked trigger fired: `PLANNING_crossing_vision.md:351`
(Protect clips when `no_frigate_event` > 25 %; D0 measured 26 %). W4 answers it.

## 4. Producer and consumer checks (fire check included)

### 4.1 Every family classifier site

`family_of(entity_id)` = `nvr_family(_engine_tag(...))` from the entity's device integration, cached per entity_id and
invalidated on the layer's one rescan path. No registry entry → suffix fallback inside `family_of` only, returning a
family or the sentinel `"unknown"`.

| Site | Decides | Decision | Ships |
|---|---|---|---|
| `transit_validator.py:2700-2710` substring test | platform per fired entity | MIGRATE | W2 |
| `perimeter_alert.py:578-583` `_leg_tag`; `:623-657, :671, :708` `base_engine` / `_e2` | leg engine (feeds every gate) | MIGRATE; "legacy" only when `family_of` is `"unknown"` | W2 |
| `perimeter_alert.py:4525-4528` `_is_frigate_person_entity`; `:2179` `platform == FRIGATE` | is this leg Frigate | MIGRATE | W2 |
| `camera_census.py:635-649, :985-990, :1143, :1171, :875-898` `CameraInfo.platform` | Frigate numeric vs binary platform (family vote in `_cross_validate_platforms` and snapshots `:2026, :2105, :2195, :2827, :3796, :3837, :5984, :6000`) | MIGRATE via `platform_for` (below) | W5b |
| `binary_sensor.py:1827-1860` room fusion `on_integrations` | agreement class | MIGRATE (4.2) | W5c |
| `camera_resolver._engine_tag` | engine from integration | KEEP: the source `family_of` wraps | n/a |
| `camera_resolver._has_any_suffix*` | which entity is the person sensor (slot pick) | KEEP: picks a sensor, does not vote | n/a |

Census value space (H3). `platform_for(entity_id) -> CAMERA_PLATFORM_*`: `frigate` → `CAMERA_PLATFORM_FRIGATE`; `protect`
→ `CAMERA_PLATFORM_UNIFI` (`"unifiprotect"`, `const.py:2432`); `reolink` / `dahua` → `_CAMERA_PLATFORM_REOLINK` /
`_CAMERA_PLATFORM_DAHUA`; any other integration → its integration string (as today); `"unknown"` → develop's rule kept:
a `_person_detected` suffix is UniFi-like (`CAMERA_PLATFORM_UNIFI`, `camera_census.py:648-650`), a `_person_occupancy`
suffix is Frigate, else `CAMERA_PLATFORM_UNIFI` (develop's default at `:898`). Census never stores a bare family string.

W0 lists every live person entity with its suffix class and its `family_of` / `platform_for` class; each mismatch is a
named behaviour change in the deliverable that migrates the site.

### 4.2 Every comparison site

| Site | Window | "Agree" | Decision |
|---|---|---|---|
| Census `_cross_validate_platforms` (`camera_census.py:2330`) | none (snapshot) | both counts > 0 | KEEP count policy (answers "how many"); classifier via `platform_for` and `families_live` provenance (W5b) |
| Transit `_count_platforms_fired` (`:2689`) | ±10 s around t | ≥ 2 families | MIGRATE to `corroborated` (W2) |
| Perimeter `_apply_single_source_gate` (`:4924`) + `AgreementTracker` | 60 s | other family fired; alert-sample rate ≥ 0.6 over ≥ 20 | MIGRATE behind opt-in; alert samples move into the table with unchanged semantics (W2 mirror, W5a read) |
| Room fusion `agreement` → fan veto | state now | all available sources on / split | MIGRATE: count families, not sources (W5c); fan veto policy unchanged |

### 4.3 Producer, fire check, forward trace

Fires today live in four private stores: transit `_recent_egress_events` (`:1365`), perimeter `_record_leg_fire` (`:2916`),
census snapshot counts (`camera_census.py:2140-2210`), room fusion state reads. Fire check, 7 days (probe Q4): door cameras
Frigate edges 107 / 93 / 35 / 67, Protect 85 / 85 / 37 / 37. Transit 0.9 over 14 days: doorbell_lite 51/76, front_door_aerial
13/28, madrone 14/53, **garage_a 0/71** (zero-fire leg, §5). Perimeter, census and room fusion agreement distributions: W0.
Forward trace: crossing confidence (DB/bus), perimeter severity (NM), census agreement and downgrade (house count, guest
mode), room fusion agreement (fan veto). No Protect input to crossing vision today. Rescan: `transit_validator.py:417`
rebuilds on `unifiprotect` registry events; the layer owns one rescan path and transit gains no second listener.

## 5. The garage_a Protect leg: cause and fix (W1)

Cause (code; registry confirmed by planner and review 1): `camera.garage_a_2` is the only door camera entity with `_2`.
Transit subscribes `person_binary_sensor` per `CameraInfo` from `resolve_cross_platform_sensors` (`transit_validator.py:1096`,
`camera_census.py:856-874`) → `resolve_operator_declaration` → `resolve_capabilities`. Rung 5 stem `garage_a_2`
(`camera_resolver.py:1531-1566`) misses the Protect stem `garage_a`; the guarded `_N` collapse (`:984-1004`) needs MAC,
identifier tuple or both-Frigate (`_shares_evidence_with_inputs`, `:1485`), none present. Fusion, not subscription.
Config-first: renaming the entity ripples into every list and does not help another install.

Fix, with a uniqueness condition so the A-MED-2 guard is not reopened. HA names a Frigate camera `X_2` exactly when a
`camera.X` already exists, so a shared name alone is not evidence. Accept a candidate device in the `_N` collapse only if
ALL hold: (1) the input device is Frigate and its object name (`_frigate_object_name_for_device`) equals the candidate's
dstem; (2) exactly one non-Frigate camera device in the registry has that dstem; (3) no other Frigate device has that
object name; (4) the candidate device has no Frigate identifier of its own. Otherwise refuse, as today. Residual: two
different cameras with one name, one on each NVR and no other camera of that name, still collapse. Nothing in the
registry distinguishes that from the true pair; it is the same residual the bare-name exact-stem rung (`:972-982`) already
carries for the three other door cameras, so W1 adds no new class of risk.

Callers (every path through `resolve_capabilities`): `__init__.py:647`, `binary_sensor.py:1596` (→ fan veto),
`camera_census.py:857` (→ transit `:547, :1093, :1180`), `transit_validator.py:2407`, `person_sighting.py:334, :503`,
`camera_resolver.py:829/833/863`, `perimeter_alert.py:2341` → `resolve_detection_legs` (`:1171`). W1 changes shipped
perimeter Part A input for garage_a (its egress wiring gains the Protect leg; `families_live` and tracker samples change).
`canonical_camera_key` for garage_a stays the Frigate id (`7c45...` < `f843...`).

## 6. Invariants (falsifiable)

- **INV-W-OPTOUT.** For each consumer, with its opt-in False, and for all consumers with `NVR_WITNESS_ENABLED` False, the
  decision output is byte-identical to develop on the fixed fire-sequence corpus.
- **INV-W-ONE-EPISODE.** One physical event on one camera (fires with every gap ≤ `NVR_WITNESS_EPISODE_GAP_S`, total span
  ≤ `NVR_WITNESS_EPISODE_MAX_S`) yields exactly one episode record and at most one agreement sample, whatever the legs,
  re-triggers or families. A restart never replays an episode: episodes closed by shutdown are stored with
  `close_reason = shutdown` and excluded from samples.
- **INV-W-ONE-CLASSIFIER (phased).** After each ship, every site migrated by that ship and every earlier ship derives
  family only through `family_of` / `platform_for` when its opt-in is on. Enforced two ways: (a) a grep test over
  `transit_validator.py`, `perimeter_alert.py`, `camera_census.py`, `binary_sensor.py` for `"_person_detected" in`,
  `"_person_occupancy" in`, `.endswith("_person_detected`, `.endswith("_person_occupancy` and `platform == CAMERA_PLATFORM_*`;
  every remaining hit is on an allowlist keyed by FUNCTION name (not line) with its reason: a §4.1 KEEP, a site not yet
  migrated (with its ship), or a legacy opt-out branch (with the knob that keeps it alive and the supersession step that
  deletes it). W2 lands the test with the transit and perimeter rows; W5b and W5c each move their rows from "not yet"
  to "legacy opt-out". After the last flip is validated, the supersession audit deletes legacy branches and the allowlist
  shrinks to the KEEP rows. (b) A behavioural test per migrated site: an entity whose suffix says Frigate but whose device
  is Protect classifies as Protect with the knob on, and as develop with it off. (a) without (b) would be hollow.
- **INV-W-EVIDENCE-ONLY.** The layer writes no consumer state, census field, house state, `person_id`, or NM alert other
  than its own zero-fire page.
- **INV-W-ONE-HEALTH.** Stream death comes only from the stream-health getter; the layer adds only leg-state availability
  (as perimeter does at `:4787`). Getter absent → health `unknown`, never derived.
- **INV-W-WINDOWS.** `NVR_WITNESS_EPISODE_GAP_S` ≥ every consumer corroboration window (transit, perimeter, W5 sites), and
  `NVR_WITNESS_RING_S` ≥ the largest window plus transit's resolve delay (`EGRESS_ENTRY_WINDOW_SECONDS`). Enforced by a
  const test; an inversion test (gap 5, window 10) documents the split it causes.
- **INV-W-CLIP-SCOPE.** Every Protect clip is for a camera in the crossing's own door group, range in
  [E − `CROSSING_VISION_PROTECT_PRE_S`, E + `CROSSING_VISION_PROTECT_POST_S`], under crossing vision's existing cap,
  concurrency, INV-SCOPE and INV-OFF.

## 7. The layer's data model and lifecycle (W2)

**Owner.** `NvrWitnessLayer` is built once in the integration-entry block of `__init__.py`, before transit (`:3464`),
perimeter (`:3509`) and census (`:2938-2950`), stored at `hass.data[DOMAIN]["nvr_witness"]`, unloaded with that entry.
Consumers fetch it lazily on every call (never cache the reference) and use their legacy path when it is absent. Room
fused sensors set up per room entry may run before it exists; they fall back until it appears.

**Fire.** A fire is any state update of a subscribed person leg whose new state is `on` / `true` / `1`, or a digit > 0 for
count sensors, the same predicate as transit (`transit_validator.py:1355-1359`, count sensors `:1393`). Each fire record
carries `edge = True` when the old state was not a fire. Timestamp = `dt_util.now()` at the callback (transit's clock).
Perimeter's own fire path is unchanged until W5a.

**Ring (short windows).** In memory, per (camera key, family), raw fire timestamps for `NVR_WITNESS_RING_S`.
`families_fired(cam, t, window_s)` = families with any fire in [t − window, t + window] (symmetric, as transit: it
resolves after the entry window, so later fires count). `corroborated(cam, t, window_s)` = ≥ 2 eligible families fired.
`families_on_now(cam)` = families with a leg whose current state is a fire. `families_live(cam)` = families with a leg
not `unavailable` / `unknown`, minus stream-dead (getter).

**Episodes (the persisted learning unit).** Per camera key: opened by the first edge; extended by any fire within
`NVR_WITNESS_EPISODE_GAP_S`; closed by a superseding tracked `async_call_later(gap)` per camera (`close_reason = gap`), or
when the span reaches `NVR_WITNESS_EPISODE_MAX_S` (`max`; the next fire opens a new one), or at teardown (`shutdown`,
excluded from samples). Record: camera key, device ids of the fusion, started / ended, `families` (sorted set of families
that fired), per-family first, last and fire count, `families_subscribed`, `families_live` at open, close reason. Any number
of families is representable (pool overhead has four).

**Agreement record.** `agreement(cam, *, pair=("frigate", "protect"), last_n, min_samples)` over the last `last_n` eligible
episodes of that camera: `samples`, `both` (pair ⊆ families), `per_family_only` counts, `rate = both / samples`, or
`ineligible` when the pair is not both subscribed and live at open. A camera with one family is `ineligible`: shown as such
in the sensor and scorer, excluded from W3. There is no pair window parameter: pairing is the episode. Perimeter's
alert-conditioned rate is a separate record kind (below), with its own `last_n` (`PERIMETER_SS_WINDOW_N`, 100) and
`min_samples` (`PERIMETER_SS_MIN_SAMPLES`, 20).

**Persistence (Q3 default, pending): table `nvr_witness_records`.** Created via `_create_table_safe`:
`id INTEGER PK, record_kind TEXT NOT NULL ('episode' | 'alert_sample'), camera_key TEXT NOT NULL, device_ids_json TEXT,
started_at TEXT, ended_at TEXT, families_json TEXT, per_family_json TEXT, families_subscribed_json TEXT,
families_live_json TEXT, close_reason TEXT, alert_family TEXT, corroborated INTEGER, imported INTEGER NOT NULL DEFAULT 0,
seq INTEGER, pipeline_version INTEGER NOT NULL`. Indexes `(camera_key, record_kind, started_at)`, `(record_kind, started_at)`.
DAO `log_nvr_witness_records(rows)`: one batched `executemany` per flush (shape of `log_hvac_evidence_shadow`), through
`_db()` and the serialized write path; closed records buffer in memory and flush every `NVR_WITNESS_FLUSH_S` and at
teardown; `DBShuttingDown` drops are counted, never retried in a loop. Boot load (after DB ready): last `last_n` records per
current camera key per kind, one query. Retention: `prune_nvr_witness_records` nightly batched delete past
`NVR_WITNESS_RETENTION_DAYS`. Sizing: probe Q4 gives about 80 Frigate edges a day on the four door cameras; W0 measures all
covered cameras; at an assumed ≤ 1,000 records/day and ~300 B/row, 90 days ≈ 27 MB; W0 replaces the assumption and a test
bounds rows written per flush.

**Perimeter history, one place.** At W2: a one-time idempotent import of `universal_room_automation.perimeter_agreement`
outcomes into `alert_sample` rows (`imported = 1`, `started_at` NULL, `seq` keeps order; a marker row prevents a second
import). From W2, perimeter's `finalize_due` also appends each finalised sample as an `alert_sample` row (additive; its
decision still reads its in-memory tracker until W5a). Alert samples are never mixed into episode rates. The `.storage`
file is read only by perimeter until the W5a flip and deleted in the supersession audit.

**Key change.** Records keyed by `canonical_camera_key`. On boot, keys not in the current fusion set are not loaded into
memory (orphaned); their rows stay for analysis via `device_ids_json` and age out by retention.

## 8. Deliverables

### W0: read-only probe (now)
Tables: fires/day per (camera, family) for all covered cameras (sizing); inter-fire gaps and episode spans (gap and max);
perimeter, census and room fusion agreement distributions; suffix vs `family_of` / `platform_for` class for every live
person entity; the W1 fixture (all four door cameras plus every `_N` camera entity and every same-name pair).
- **Verify:** `docs/planning/AUDIT_nvr_witness_w0_<date>.md` with all five tables. **Live:** none.

### W1: resolver Frigate object-name evidence with uniqueness (Tier 2-DB, ships first, alone; Q4)
- **Verify:** `resolve_cross_platform_sensors(["camera.garage_a_2"])` on the live-shape fixture returns
  `binary_sensor.garage_a_person_detected`; the three bare-named door cameras unchanged.
- **Verify (discriminating, HA naming):** Protect `camera.driveway` and Frigate `camera.driveway_2` (object name
  `driveway`) on DISTINCT cameras, plus a second non-Frigate `driveway` device → not collapsed (condition 2). Two Frigate
  devices with object name `driveway` → not collapsed (condition 3).
- **Tests:** `test_resolver_object_name_collapses_unique_protect_sibling`, `test_resolver_object_name_refuses_two_candidates`,
  `test_resolver_object_name_refuses_two_frigate_devices`, `test_resolver_knob_off_byte_identical_all_callers`,
  `test_fusion_callers_golden_except_garage_shape` (every §5 caller incl. perimeter; garage_a delta written out). Mutation:
  drop condition 2 → refuses-two-candidates red.
- **Live:** within a day a `person_entry_exit_events` row with `egress_camera = binary_sensor.garage_a_person_detected` or
  garage_a `confidence = 0.9`. A subscription fault would pass the resolver test with no live row: discriminates.

### W2: layer core, agreement record, table, transit and perimeter classifier (Tier 3; the table part reviewed Tier 2-DB)
§7 in full. Transit `_count_platforms_fired` → `len(families_fired(cam, ts, TRANSIT_PLATFORM_WINDOW_S))` with
`NVR_WITNESS_USE_TRANSIT`. Perimeter §4.1 rows via `family_of` with `NVR_WITNESS_USE_PERIMETER_CLASSIFIER` (pure if W0 finds
no mismatch). `sensor.ura_nvr_witness` (diagnostic, attributes unrecorded): per camera samples, both, per-family-only,
rate or `ineligible`, last 7 days.
- **Verify:** `occupancy_2` + `person_count` count one family; Protect + Frigate within 10 s count two; Dahua is its own family.
- **Verify:** Protect fires at 0 s and 280 s, Frigate at 140 s, transit query at 140 s with window 10 → one family (ring),
  though the episode holds both.
- **Tests:** `test_witness_one_episode_many_legs`, `test_episode_max_splits_continuous_activity` (20 min of fires 30 s
  apart → ⌈1200 / MAX⌉ episodes), `test_episode_closes_on_timer_quiet_camera`, `test_fire_wait_gap_restart_one_record`,
  `test_shutdown_episode_excluded_from_samples`, `test_ring_answers_short_window_inside_long_episode`,
  `test_family_from_device_not_suffix` (per migrated site, knob on and off), `test_one_classifier_grep_with_allowlist`,
  `test_windows_le_gap_and_ring`, `test_gap_inversion_documents_split`, `test_single_family_camera_ineligible`,
  `test_four_family_episode_recorded`, `test_layer_built_once_lazy_fetch_reload_no_orphan`, `test_single_rescan_per_registry_event`,
  `test_family_of_cache_invalidated_on_rescan`, `test_stream_health_absent_reports_unknown`, `test_transit_optout_golden`,
  `test_perimeter_classifier_optout_golden`, `test_master_kill_all_consumers_golden`, `test_transit_optin_matches_legacy_on_door_fixture`.
  DB (schema extracted from production DDL, real DAO): `test_records_batched_one_executemany_per_flush`,
  `test_perimeter_store_import_idempotent`, `test_alert_samples_not_in_episode_rate`, `test_prune_retention`,
  `test_orphan_key_not_loaded`. Mutation: count fires instead of episodes; drop the MAX close; drop the opt-out branch;
  reinstate one perimeter `endswith` tag; write per row → each a named red.
- **Live:** sensor lists per camera samples / both / per-family-only for 7 days; door-camera numbers within ±15 % of probe
  Q4; at least one `episode` row with non-null `families_json` within an hour of restart (sentinels only = broken shape);
  `alert_sample` rows equal the imported count plus new ones.

### W3: zero-fire trip-wire (with W2)
Eligible camera, one family 0 fires in 24 h while the other has ≥ `NVR_WITNESS_SILENT_FAMILY_MIN_OTHER`:
`fire_stuck_signal(kind="nvr_witness_silent_family", key=(cam, family), severity="HIGH")` (MEDIUM reaches no channel,
`_stuck_signal_nm.py:177-180`).
- **Tests:** `test_silent_family_pages_once_at_high`, `test_both_silent_no_page`, `test_ineligible_camera_no_page`.
- **Live:** no page on a healthy day.

### W4: crossing vision gets Protect as a second witness (Tier 2-DB, rides Phase 2)
(a) Gap fill: a crossing with no matched Frigate event (26 % at ±10 s) fetches the Protect range clip
`/api/unifiprotect/video/<entry id>/<Protect camera entity>/<E − pre>/<E + post>` (recording `always`), after `post + settle`.
Entry id from config entries; Protect camera entity and `event.*_smart_detection` resolved by DEVICE id from the fusion
(live: `event.garage_a_garage_doorbell_lite_smart_detection` is on the Doorbell Lite device). (b) Dual witness per
`CROSSING_VISION_DUAL_WITNESS_MODE` (pending default `all`). Rows record `frame_source` and, for dual calls, both counts
and the episode's `families`. Before build: the one approved paid dry call (Q2).
- **Verify:** no-Frigate-event crossing → one Protect call, row `frame_source = protect_range`.
- **Tests:** `test_protect_gap_fill_one_call`, `test_protect_range_in_door_group_only`, `test_dual_mode_per_setting`,
  `test_dual_mode_respects_daily_cap`, `test_protect_clip_url_from_registry`, `test_event_entity_by_device_doorbell_lite_vs_garage_a`,
  `test_crossing_vision_mode_off_golden`.
- **Live:** `no_frigate_event` share falls toward the Protect-covered share; dual rows carry both counts.

### W5: perimeter gate, census, room fusion read the layer (Tier 2-DB each, after ≥ 14 days of W2 records)
**W5a perimeter.** With `NVR_WITNESS_USE_PERIMETER`: `families_live`, `corroborated(cam, t, 60)`, and the alert-sample rate
from the table (same semantics as its tracker, `last_n` 100, `min_samples` 20). Pre-flip replay: every perimeter alert in
the window, count demote outcomes that change; non-zero → list to the operator, flip waits for ok.
**W5b census.** `CameraInfo.platform` via `platform_for`; `_cross_validate_platforms` arithmetic unchanged;
`deconflict_house` reads `families_live` (rule 5) and per-camera agreement as display provenance; `NVR_WITNESS_USE_CENSUS`.
**W5c room fusion.** `agreement` counts families via `families_on_now`; `NVR_WITNESS_USE_ROOM_FUSION`; fan veto unchanged.
- **Tests:** `test_perimeter_optout_golden`, `test_perimeter_replay_gate_lists_changed_alerts`, `test_census_snapshot_golden_optout`
  and `_optin` (every snapshot field and agreement tag, incl. the UniFi-like fallback), `test_platform_for_value_space`,
  `test_room_fusion_optout_golden`, `test_room_fusion_two_legs_one_family_not_split`, `test_fan_veto_policy_unchanged`.
- **Live:** gate rows carry `witness_rate`; census values equal develop; fused sensors carry `agreement_basis: family`.

## 9. Knobs

| Knob | Rung | Default | Why / kill |
|---|---|---|---|
| `NVR_WITNESS_ENABLED` | 1 | True | False = no subscriptions; all consumers legacy |
| `NVR_WITNESS_EPISODE_GAP_S` | 1 | 60 (W0) | ≥ every consumer window (test) |
| `NVR_WITNESS_EPISODE_MAX_S` | 1 | 300 (W0) | caps busy-camera chaining |
| `NVR_WITNESS_RING_S` | 1 | 120 | ≥ largest window + transit resolve delay (test) |
| `NVR_WITNESS_FLUSH_S` | 1 | 60 | batch size vs loss at crash |
| `NVR_WITNESS_RETENTION_DAYS` | 1 | 90 | table bound |
| `NVR_WITNESS_AGREEMENT_LAST_N` | 1 | 200 | episodes per camera for the record |
| `NVR_WITNESS_USE_TRANSIT` / `_PERIMETER_CLASSIFIER` / `_PERIMETER` / `_CENSUS` / `_ROOM_FUSION` | 1 | False until each flip | reviewed flip; False = develop |
| `TRANSIT_PLATFORM_WINDOW_S` | 1 | 10 | names `transit_validator.py:2705` |
| `NVR_WITNESS_SILENT_FAMILY_MIN_OTHER` | 1 | 20 / 24 h | 0 = trip-wire off |
| `RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` | 1 | True | False = W1 off (golden) |
| `CROSSING_VISION_PROTECT_GAP_FILL` | 3 (switch, config-flow entry) | on | off = Frigate only |
| `CROSSING_VISION_DUAL_WITNESS_MODE` | 3 (select) | `all` (pending Q1) | `off` / `disagreement` / `all` |
| `CROSSING_VISION_PROTECT_PRE_S` / `_POST_S` | 1 | 5 / 15 | clip range |

## 10. Order, tier, reviews, non-goals

Order: (1) W0 now. (2) W1 now, alone (Q4); independent of stream-health S1 (S1 uses same-device lookups, not
`resolve_capabilities`); whichever merges second rebases. (3) S2 delivers the camera-keyed getter; W2 may ship before it
under the absent-getter rule. (4) W2 + W3 after crossing vision Phase 1 (`feature/crossing-vision-shadow`, a10cd299) and
read-API ship 1. (5) W4 with crossing vision Phase 2, after Q1. (6) W5a-c after ≥ 14 days of W2 records; W5b after the
census plan's CD1. W1 is the only step that changes shipped Part A input (garage_a).

Tier: W2 Tier 3 (four code reviews A/B/C-mutation/D, framing G, orchestrator re-grep and mutation, operator checkpoint
before deploy); its table part also gets the Tier 2-DB framings: A data integrity (schema, indexes, write path batched, no
reader regression), B migration correctness (`.storage` import idempotent and order-preserving, alert samples kept apart
from episodes), C new surfaces and test authority (DDL extracted from production, real DAO). W1, W4, W5a-c Tier 2-DB each.

Non-goals: centralising consumer policy; a Protect face-name path (card `D1-PROTECT-FACE-BRIDGE-ADDON-1`); Reolink /
Dahua / Amcrest as pair witnesses (recorded as families, not in `pair`); ground truth for madrone_g6_entry (weekly
labelling, arc map M10); any AWAY, house-state, lock or HVAC change.

## 11. Edits other plans need (not made here)

- `PLANNING_crossing_vision.md` §8: the parked Protect clip lever (trigger fired) becomes W4; INV-SCOPE gains the range
  clip; `frame_source` gains `protect_range`; dual mode counts against `CROSSING_VISION_DAILY_CALLS`.
- `PLANNING_census_deconfliction.md` §2, §3.3 rule 5: witness layer is the families-live source; `aware_agreement` may carry
  witness provenance; `CameraInfo.platform` via `platform_for`.
- `PLANNING_camera_input_stream_health.md` S2: camera-keyed dead-stream getter from `_camera_unavail_since`.
- Perimeter docs: W1 changes garage_a egress legs; tracker samples mirrored from W2; `.storage` retired after W5a.
- `ARC_identity_vision_census_map.md`: row + merge entry M13 (four comparison and nine classifier sites → one layer).
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §3 (layer, `family_of`, record) and §4 (W1 uniqueness rule).
- Presence state-of-play and SENSOR_FLEET docs: W5c agreement basis (by the W5c build).

## 12. Open questions

1. **PENDING operator yes, blocks W4:** dual-witness mode. Recommended default `all`: analyse both clips on every
   crossing, about $0.18 a day extra under the existing `CROSSING_VISION_DAILY_CALLS` cap, and every crossing feeds the
   agreement record you called critical for learning.
2. Q2 answered YES: one paid llmvision call on a Protect clip before W4.
3. **PENDING operator yes:** persistence. Recommended default: the dedicated `nvr_witness_records` table (queryable for
   scoring, joins with weekly labels, retention), with perimeter's `.storage` samples imported so there is one history.
4. Q4 answered YES: W1 ships ahead, alone.

## 13. Plan completion tracking

Filled at each ship: delivered, deferred (reason and card); supersession audit of perimeter's `AgreementTracker` and
`.storage`, migrated classifiers and their legacy branches, room fusion source counting (DELETE / KEEP + WIRE / KEEP + DOCUMENT).
