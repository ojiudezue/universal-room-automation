# v5.108.22: release batch 2 (read API ship 2, scoped egress mute, perimeter labels, stream health S2, BLE person registry)

Branch `release/batch-2`, from develop 4b1d392b. Five reviewed branches merged with `--no-ff`, plus small
fixes on top. Each section below is condensed from its draft README (kept in `docs/readmes/*_DRAFT.md` for
the full record: change tables, byte-identity evidence, mutation drills, not-done lists).

| Section | Card | Tier | Reviews |
|---|---|---|---|
| 1. Person-awareness read API, ship 2 | PERSON-AWARENESS-READ-API-1 | 2 | A / B / C SHIP |
| 2. Scoped egress mute for perimeter alerts | PERIMETER-GLOBAL-EGRESS-MUTE-1 | 2-DB | A / B / C / D, fix-ups through a04b7110 |
| 3. Perimeter switch names + options-flow parity | PERIMETER-SWITCH-LABELS-AND-FLOW-PARITY-1 | 1 | A |
| 4. Camera input stream health S2 | CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 | 2-DB | A / B / C + D re-verify, through d8f4b473 |
| 5. BLE person sensors resolved through the registry | BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 | 2 | A / B SHIP, LOW fix-up 477c8dbf |

Fixes added in the batch:

- Read API review C1: test pinning the person coordinator's main update loop on a `person.*` tracked entry
  (reverting to the old `person.{...}` builder goes RED); C2: direct `slug_of` blank / whitespace test.
- Stream health: the S1 per-input 1800 s page is suppressed for an input whose camera already sent the S2
  hold-release page in the same outage (one HIGH page per outage).
- Merge seam: the egress mute read `census._get_tracked_person_slugs()`, which the read API's RA6 guard
  forbids outside `camera_census.py`; it now calls the public `tracked_person_slugs()`.
- Read API README count fix (review A-L1): of 71 tests, 44 pass on base.

## 1. Person-awareness read API, ship 2

Identity model: produces no fact; migrates readers of F1 (zone "any person home", trust), F2 (house census,
display), F3 producers' census access and F5 payload reads. Invariant INV-RA-BYTE-IDENTICAL: under the live
config every migrated reader returns what develop returned.

- RA6: public `PersonCensus` surface (thin delegates); transit validator, perimeter, sighting producer,
  `__init__` and the egress sensor attributes call it instead of privates. AST guard
  `test_no_private_census_reads_outside_module`.
- RA7: one F2 read, `census_view.house_census_view`, for the unidentified-persons, unexpected-person,
  phone-left-behind and zone guest-count sensors.
- RA8: `persons_home_for_trust` / `first_person_home_for_trust` for the HVAC night-trust hold, fan night
  hold, `zone_has_home_person` and the aggregation person fallbacks (same rule, same order).
- RA9: id copies through `person_ids` (`tracked_person_entity_id`, `slug_of`, `display_of`, frozen
  `entity_key_slug`). A `person.*` entry in `tracked_persons` no longer becomes `person.person.*`.
- RA10: `PersonArrivingPayload.from_signal` for the security, lock-regime and music-following handlers.

Live (prospective):
- Census sensors (`sensor.universal_room_automation_unidentified_persons`, zone guest counts, unexpected-person
  and phone-left-behind binary sensors) read the same values as before deploy.
- NM arrival text names the same people; HVAC night-trust and fan night holds fire as before (activity log
  `home_persons` same shape).
- No new WARNING/ERROR lines from `camera_census`, `transit_validator`, `perimeter_alert`, `person_sighting`,
  `person_coordinator` (in particular no `Person entity not found: person.person.*`).

## 2. Scoped egress mute for perimeter alerts

Identity model: consumes F3 (door crossing + identity attach), security consumer class (>= 0.9).

Before, any egress camera on-edge muted every perimeter-only camera for 120 s, with no identity check and
no record (243 of 607 perimeter person edges over ~9 days, 40%). Now a perimeter edge on camera P is dropped
only when a door that lists P in `egress_mute_covers` has a stored crossing at most 120 s earlier that is
entry/exit, a tracked resident, identity >= 0.9 and not synthetic. Any unknown, guest, below-floor,
synthetic or ambiguous crossing at a covering door vetoes the mute; a late non-qualifying crossing re-sends
the edges the mute dropped. Episode cap 300 s. Every mute and every decline writes a
`perimeter_gate_decision` row (`gate: egress_mute`). Door groups (`CONF_DOOR_GROUPS`) widen a door at read
time. Fail-open everywhere. Trip-wires: mute ratio > 0.5 over 24 h (`perimeter.egress_mute_ratio`) and zero
mutes despite 5+ covered crossings (`perimeter.egress_mute_zero_fire`). Knobs are rung-1 constants
(`EGRESS_MUTE_*`, table in the draft).

Live (prospective):
- `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`: `mute_covers_source` =
  `loaded (3 door(s))`, `seam_validation` starts with `ok`, `seam_count` / `seam_egress_adjacent` unchanged.
- Over the first day the share of perimeter person on-edges on covered cameras that are muted is far below 40%.
- Every `suppressed=true` `egress_mute` row has a tracked resident `person_id`, confidence >= 0.9, entry/exit,
  and a matching `person_entry_exit_events` crossing on that door within 120 s before.
- A driveway edge during door activity with no qualifying crossing alerts (`exterior_person`
  `notification_log` row) with an `egress_mute_no_record` or veto decline row.
- No `perimeter.egress_mute_ratio` / `perimeter.egress_mute_zero_fire` anomaly rows on day one.
- `egress_mute_unmapped_producer_legs` = `[]`, `egress_mute_door_key_fallbacks` = `{}` after a day.
- Confirm `perimeter_gate_decision` rows persist live (0 rows at review time) before relying on them.

## 3. Perimeter switch names + options-flow parity

New names, same entity and unique ids: `switch.ura_perimeter_zone_agreement_demote` Lower Road Alerts;
`switch.ura_perimeter_single_source_demote` Lower Single-Sourced Alerts;
`switch.ura_perimeter_egress_known_xcorr_gate` Unknown Person Door Alert;
`switch.ura_perimeter_identity_followup` Add Names to Alerts; `select.ura_perimeter_vlm_gate` AI Person Check
(options Off / Watch only / On; stored values unchanged). New House options step **Perimeter Alert Filters**
with all five settings; it merges into existing options and does not reload the integration. The
single-sourced switch and field exist only when a camera has both a Frigate and a Protect leg
(`CameraResolver.has_frigate_and_protect_camera()`; 19 such cameras live).

Live (prospective):
- The five entities show the new names with unchanged entity ids.
- Settings > URA > Configure > Perimeter Alert Filters shows five fields with the current switch values;
  saving does not reload the integration.

## 4. Camera input stream health S2

S1 stopped a dead camera's frozen input from holding its room. S2 makes the readers outside the room
follow the same getter under one rule (operator 2026-11-14): a dead input holds. It cannot create or end
occupancy; the zone keeps its level until a live input in the room goes `on -> off`, the camera streams
again, or the cap passes (`CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` zone 900 s,
`CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S` census 900 s, measured in
`AUDIT_camera_outage_durations_2026_11_14.md`). Past the first cap ONE HIGH page names the camera (kind
`camera_stream_hold_released`, LOW on recovery); the S1 1800 s per-input page no longer follows it. Readers:
zone substrate, zone camera tier, night switch-off limb, census interior and guest counts, HVAC D6 Source 3,
presence fan-interference gate, comfort-fan AWAY veto (legacy camera leg only; the fused sensor path is
carded). An input that goes unavailable together with its camera (Protect disconnect) is held from t0.
Quarantined sensors cannot end a hold. Kill switch `CAMERA_INPUT_STREAM_HEALTH_ENABLED` False = develop.
New getters for later consumers: `camera_stream_dead`, `entity_stream_view`, `input_stream_view`.

Live (prospective):
- Now: no change while the panels stream (substrate kinds and census counts match before deploy).
- Next panel outage (organic, judged at the zone): within ~2.5 min `sensor.<room>_unavailable_entities`
  lists the panel input under `camera_stream_dead_inputs`; the zone does not drop then (held); it releases at
  the first live sensor `on -> off` in that room or at 900 s, with exactly one HIGH `camera_stream_hold_released`
  page and no later `camera_stream_dead` page for that outage. Fail = zone drops within minutes with no live
  sensor off, stays held past ~16 min, no page, or two HIGH pages.
- Interior census camera outage only: the dead camera keeps its count in `area_contributions` for 900 s,
  then is absent (missing term).
- HVAC D6: proven in-suite (`test_source3_dead_zone_camera_confirms_nothing`).

## 5. BLE person sensors resolved through the registry

Operator 2026-11-14: "That Bermuda registry fix is clutch. Approved." Full record:
`docs/readmes/drafts/BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1.md`; plan `PLANNING_ble_person_sensor_registry_resolve.md`
rev 2; audit `AUDIT_ble_person_sensor_resolution_2026_11_14.md`.

**What was wrong.** PersonCoordinator found each person's Bermuda sensors by entity_id substrings. Scanners named
after a person (`jaya_3`, `...ezinnemakeup`) matched too, so Ezinne, Ziri and Jaya each picked up 12 distance
sensors on other people's phones and Oji matched none (fixed 0.5). The match also enabled disabled sensors, which
reloads Bermuda. `aggregation._find_bermuda_sensors` had matched nothing since v3.6.

**What changed.**
- `_bermuda_device_for_person` resolves the person's Bermuda device through the registries only: (a) the one
  `bermuda`-platform tracker in the person's `device_trackers`; (b) only when (a) finds none, the one
  `private_ble_device` tracker's identifier, then the one other device carrying it that owns a Bermuda entity.
  Zero or two-plus candidates resolve to nothing. No cache across ticks; one resolve per person per tick.
- Sensors are typed by registry unique_id on that device: the area sensor, and one distance sensor per scanner
  (filtered `_range`, raw only as fallback). Names are never parsed. No code writes `disabled_by`.
- `aggregation._find_bermuda_sensors` and its state listener are deleted.
- Fire check: unrecorded attribute `bermuda_resolve` on the Person Tracking Status diagnostic sensor (per person:
  resolved, misses by reason, last route); one WARN per (person, reason) on the second consecutive miss, one INFO on
  recovery.

**Expected effect.** Oji's BLE confidence 0.5 -> 0.3; Ezinne, Ziri, Jaya stay 0.3 and each lose the 12 foreign
sensors. Area sensors unchanged. No decision changes: the only trust reader is the `< 0.3` filter in
`get_room_occupants`, which 0.3 passes (review B traced room occupancy, fan veto, transitions, census, music).

**Residuals (carded or display-only).** Scanner name still read from the entity_id inside the confidence loop
(BLE-CONFIDENCE-SCANNER-NAME-PARSE-1; inert until the per-scanner sensors return); warn-once streak resets on an
alternating miss reason (counters still show it); removed persons keep counters until reload.

**Live acceptance.**
- `bermuda_resolve`: each home resident `last_route: a`, `resolved` rising, `unresolved: 0`.
- Boot log: zero `No Bermuda area sensor` WARNs, zero `Auto-enabled Bermuda distance sensor` INFOs, zero
  `No Bermuda sensors found` WARNs, no Bermuda config-entry reload in the boot window.
- Enabled `bermuda` entity count identical before and after restart.
- `sensor.<person>_location` for home residents matches their `sensor.*_area`.

## Operator steps (after deploy; done by the orchestrator)

1. Add `egress_mute_covers` to the live `/config/universal_room_automation/exterior_seams.json` (copy from
   `docs/examples/exterior_seams.example.json`; `doorbell_lite` is an egress camera and is not coverable):

   ```json
   "egress_mute_covers": {
     "garage_a": ["g5_bullet", "rear_ptz"],
     "madrone_g6_entry": ["sonoffwindow", "front_side_ptz", "utilities_ptz"],
     "front_door_aerial": ["sonoffwindow", "front_side_ptz", "utilities_ptz"]
   }
   ```
2. Press `button.ura_reload_exterior_seams` (or restart).
3. Check the diagnostic: `mute_covers_source` = `loaded (3 door(s))`, `seam_validation` `ok`, seam counts
   unchanged. Until this is done the mute never fires and every edge alerts.

## Not done (accounted)

- Each section's draft README lists its own residuals and carded follow-ups (fused `camera_person_detected`
  stream health, census face reads, perimeter ring cameras watched by no room, `_CensusBaseSensor` rich
  reads, orphaned single-sourced switch on an install that loses its last dual camera).
- Stream-health page de-duplication covers only the S2-then-S1 order (caps 900 s < 1800 s). If the caps are
  raised above 1800 s, the S1 page fires first and the hold page still follows.

## Validated 2026-11-14

Observed restart: HA core booted 2026-11-14 20:38-20:39 UTC (14:38-14:39 CST; the briefed "about 14:50" is 11 min
later than the entity and DB-directory timestamps). Reads taken 21:37-21:43 UTC (15:37-15:43 CST), so most
post-boot evidence is roughly 1 hour old. Log windows: the `system_log` WARNING and ERROR buffers hold everything
since boot. The raw `error_log` window starts about 14:42 CST, so the first ~4 minutes of boot are not in it.
`ha core logs` returns 401 from the SSH path; logs were read with `ha_get_logs`.

| Criterion | Result | Evidence |
|---|---|---|
| S1 census sensors read the same values | PARTIAL | Slug format unchanged. House census snapshot 21:40:39 UTC: identified 3 `["ezinne","jaya","ziri"]`, unidentified 0. Last pre-restart snapshot 20:37:20 UTC: identified 2 `["ezinne","jaya"]`, unidentified 1. Ziri is a current arrival (BLE Jaya Bedroom), not a slug change. No pre-deploy sensor-value baseline was recorded, so value equality cannot be proven. |
| S1 NM arrival text names the same people; HVAC night-trust and fan holds fire as before | PENDING | Next resident arrival or night hold. Last `presence` "Someone arrived" (LOW) at 21:12:59 UTC carries generic text. |
| S1 no new WARN/ERROR from camera_census, transit_validator, perimeter_alert, person_sighting, person_coordinator; no `person.person.*` | PASS | None of those modules in the system_log WARNING (30 entries since boot) or ERROR (20 entries) buffers. Raw `error_log` search `person.person` returns 0 lines. |
| S2 Perimeter diagnostic: `mute_covers_source` = `loaded (3 door(s))` | PASS | `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` attributes (21:37 UTC publish): `mute_covers_source = loaded (3 door(s))`. |
| S2 `seam_validation` ok; seam counts unchanged | PARTIAL | `seam_validation = ok`, `seam_count = 21`, `seam_egress_adjacent` 6 cameras. `seam_file_sha256` 44f5cb55... matches the live `exterior_seams.json` on disk. Pre-restart seam counts were not recorded, so "unchanged" cannot be proven. |
| S2 `perimeter_gate_decision` rows appear after restart | PASS | 11 rows since 20:38 UTC in `memory_episodes` (8 `gate: egress_mute` declines, 3 `single_source`). 7 earlier rows are from 14:06-19:40 UTC, before this restart. |
| S2 mute share below 40% over first day | PENDING | Day one not complete. Post-boot egress-mute decisions: 8, of which 0 muted (6 `egress_mute_vetoed_unknown`, 2 `egress_mute_no_record`). Closes at the first 24 h after 20:38 UTC. |
| S2 every `suppressed=true` egress_mute row has a resident, conf >= 0.9, entry/exit, matching crossing within 120 s | PENDING | 0 suppressed rows so far (the criterion holds vacuously). Pending the first covered-door mute. |
| S2 driveway edge with no qualifying crossing alerts, with a decline row | PASS | Perimeter alerts sent: 21:23:14, 21:30:55 and 21:30:56 UTC (`notification_log`, perimeter_alert MEDIUM). Decline rows in the same window: `egress_mute_vetoed_unknown` 21:24:13 and 21:25:51 UTC. |
| S2 no `perimeter.egress_mute_ratio` / `zero_fire` anomaly on day one | PASS so far | `anomaly_log` rows with `anomaly_type` LIKE `perimeter%` since 20:38 UTC: 0. The 24 h window is still open. |
| S2 `egress_mute_unmapped_producer_legs` = `[]`, `egress_mute_door_key_fallbacks` = `{}` after a day | PENDING | Currently `[]` and `{}`. Closes at 24 h. |
| S3 five perimeter entities show new names, unchanged ids | PASS | `switch.ura_perimeter_zone_agreement_demote` "Lower Road Alerts"; `switch.ura_perimeter_single_source_demote` "Lower Single-Sourced Alerts"; `switch.ura_perimeter_egress_known_xcorr_gate` "Unknown Person Door Alert"; `switch.ura_perimeter_identity_followup` "Add Names to Alerts"; `select.ura_perimeter_vlm_gate` "AI Person Check" (options off/shadow/enforce). |
| S3 options step "Perimeter Alert Filters" exists (strings and translations only) | PASS | `translations/en.json` and `strings.json` each contain `perimeter_alert_filters`. `select` labels: shadow = "Watch only", enforce = "On". |
| S3 options step shows 5 fields with current values; saving does not reload | PENDING | Requires opening and saving the flow. Not opened per the brief. |
| S4 no `camera_stream_hold_released` / `camera_stream_dead` page without a real outage | PASS | `notification_log` since 20:38 UTC: 21 rows, none stream-kind (security, energy, presence, perimeter_alert, stuck_signal shadow-only). |
| S4 S2 attributes present on room unavailable-entities sensors | PASS | All 21 `sensor.*_unavailable_entities` carry `camera_stream_dead_inputs` and `camera_stream_inputs_resolved`. No dead inputs now. |
| S4 hold then release, one HIGH page, on a real panel outage | PENDING | Next organic panel or camera outage. |
| S5 `bermuda_resolve`: each home resident `last_route: a`, `resolved` rising, `unresolved: 0` | PASS | `sensor.universal_room_automation_person_tracking_status` attribute: Ezinne, Jaya, Ziri `last_route a`, `unresolved 0`, `resolved` 122 at 21:41:39 UTC and 124 at 21:42:01 UTC. Oji Udezue also `a`, unresolved 0 (location Away). |
| S5 boot log: zero "No Bermuda area sensor" WARNs | PASS | Zero in the system_log WARNING buffer and in the raw `error_log` window (from 14:42 CST). |
| S5 boot log: zero "Auto-enabled Bermuda distance sensor" INFOs | PASS, caveat | Zero in the raw `error_log` window from 14:42 CST. INFO is not in the system_log buffer. The first ~4 min of boot are outside the window. |
| S5 boot log: zero "No Bermuda sensors found" WARNs | PASS | Zero in both windows (as above). |
| S5 no Bermuda config-entry reload in the boot window | PASS, caveat | No Bermuda reload line in the raw window. No Bermuda entity has a `disabled_by` change since boot. |
| S5 enabled `bermuda` entity count identical before/after | PARTIAL | Now 391 enabled / 105 disabled (496 total) in `core.entity_registry`. Pre-restart count was not recorded. Four Bermuda rows were stamped at 20:39:23 UTC (`sensor.ezinne_iphone_area`, `..._last_seen`, `sensor.iphone_jaya_area`, `..._last_seen`); all four enabled. |
| S5 `sensor.<person>_location` matches `sensor.*_area` for home residents | PASS | Ezinne "Master Bathroom" = `sensor.ezinne_iphone_area` "Master Bathroom". Jaya "Jaya Bedroom" = `sensor.iphone_jaya_area` "Jaya Bedroom". Ziri "Jaya Bedroom" = `sensor.iphone_ziri_area` "Jaya Bedroom". Oji "Away" with area `unknown` (not home). |
| Operator step 1: `egress_mute_covers` in live `exterior_seams.json` | PASS | Live file has `egress_mute_covers` with the three doors (garage_a; madrone_g6_entry and front_door_aerial). File sha256 matches the diagnostic. |
| Operator step 2: reload or restart | PASS | Restart 20:38-20:39 UTC (see header). |
| Operator step 3: diagnostic check | PASS | See the S2 rows above. |

**Section 2 of the log scan (since boot, 20:38 UTC).** `system_log` WARNING: 30 entries; ERROR: 20 entries.

- URA-origin WARNING groups (occurrences): `energy_circuits` Span Right Double Oven anomaly (2); `coordinator` Media Room Closet energy sensor unavailable (1); `optimization_llm` Anthropic quota 400, "regain access 2026-12-01" (4); `energy_battery` SOC divergence (1), SOC stream-tier trust (1), SOC cloud fallback stale (1), SOC primary+LKG unavailable (1); `energy` battery capacity fallback 40 kWh (1); `helpers.entity` slow state update for `zone_upstairs_presence_status` (0.48 s) and `appliance_census` (0.54 s) (2); `helpers.frame` deprecations for `entity.py:86` and `_devices.py:627` (count shared with other integrations).
- URA-origin ERROR: 0. URA tracebacks: 0.
- New in the v5.108.22 modules (`camera_census`, `transit_validator`, `perimeter_alert`, `person_sighting`, `person_coordinator`): 0 WARN, 0 ERROR.
- Non-URA ERRORs (not this release): WhatsApp bridge 401 (733 repeats); Anthropic quota (4); tuya_local network errors (506); Shelly fetch errors; WiiM unreachable; ESPHome BLE; elkm1 decode; icloud3 KeyError (1).
- Boot-only transients dismissed: the `assist_satellite` duplicate-setup ERRORs for five ESPHome panels (20:38 UTC, `config_entries`); Bermuda's own "Unexpectedly got 4 device registry matches" WARNs for two Shelly devices (Bermuda, not URA); recorder attribute-size WARNs (`zone.home`, a Zigbee network map, `frigate_events`).
- Not verifiable here: whether the URA WARN groups above are new relative to v5.108.1. No pre-restart log snapshot was kept. `zone_upstairs_presence_status` is in `aggregation.py`, which this batch touched, so it should be watched.

**Open items to close.** Day-one rows (S2 mute ratio, unmapped legs, door fallbacks, anomaly window), the first covered-door mute (suppressed-row criterion), the first organic stream outage (S4 hold, release and one page), the first resident arrival or night hold (census and NM text), and the options-flow save (S3 field values and no reload). The Bermuda registry before/after count stays PARTIAL until a pre-restart count is available.
