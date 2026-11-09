# PLANNING: perimeter false-positive build (URA side of the joint plan)

**Card:** PERIMETER-FP-STREET-NOISE-1 (related: PERIMETER-PHANTOM-XCORR-1, WA-BRIDGE-DOMAIN-1).
**Rev 2 (2026-11-08):** plan review 1 fixes applied (`docs/reviews/code-review/perimeter_fp_build_plan_review_1.md`):
H1 D5 settle holds the in-flight key; H2 D5 counts prior alerts itself; H3 D1 exclusion at all five wiring sites incl.
`_rescan_siblings`; H4 D10.2 PARKED; H5 dual-role egress cameras ignore each other's stamps; M1-M9 and L1-L4 as marked
`(rev 2)` below. Operator additions folded in: D10.5 (egress alerts page only for an unknown, corroborated person),
D10.6 (sonoffwindow confirmed), new D11 (camera-list live rewire, Tier 3, own branch). Verdict after rev 2: BUILD for
D1-D10; D11 BUILD on its own Tier-3 track.

**Status:** PLANNED. Operator approved all phases 2026-11-08 ("build as many as possible without pausing in btw unless
absolutely necessary for measurement... If measurement is needed but not a prerequisite, build it"). D10 added by the
operator the same day.
**Inputs:** `PLAN_perimeter_fp_joint_2026_11.md` (77368438), `AUDIT_perimeter_fp_street_noise_2026_11.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md` (read in full; no contradiction with code found, one addition noted in §0.6),
`AUDIT_xcorr_engine_corroboration_probe.md`, `PLANNING_consol_1_alerting_llmvision.md`, `PLANNING_snap1_at_detection_snapshots.md`.
HVAC and presence state-of-play docs were not read: this cycle touches neither (no room occupancy, BLE, motion or
HVAC code). D10's resident-identity step reads the identity manual only.

**Tier: Tier 2-DB review protocol (three framing-disjoint reviews + live validation), no DB schema change.**
Trigger: regression-prone alert path (standing policy 2026-06-08). Several new demote gates are threaded into one
decision path (`_async_handle_perimeter_trigger`) that already has five severity stages, and NM channel-health
semantics change. Not Tier 3: nothing here is cost-or-safety actuation, every new gate only demotes and never
silences, and every behaviour change is behind a knob that ships off. If the builder finds a gate has to sit
somewhere other than the single severity block (a second emission path), stop and re-tier to 3.
Suggested framings: A = local correctness per gate (parsing, fail-open, knob-off byte identity); B = gate ordering,
async/timer lifecycle (D5 settle timer, D7 pre-send probe), restart, teardown; C = test authority by per-site source
mutation on every demote site plus the D7 delivered flag.

---

## 0. Institutional context verified

### 0.1 Greps run (main checkout, develop, 2026-11-08)

```
grep -n "frigate_events\|FRIGATE_EVENTS_BUS_EVENT" -r custom_components/   -> perimeter_alert.py:252,779-814; exterior_track_linker.py:53,240-273; __init__.py:3517
grep -n "best_score" *.py                                                   -> exterior_track_linker.py:91,473,564,574,671 (display only, linker hop dict)
grep -n "score=0.0" perimeter_alert.py                                       -> :2640 (_feed_linker), :3905 (_on_perimeter_event fallback observe)
grep -n "PERIMETER_BURST_" const.py                                          -> :2469-2491
grep -n "_SOLE_FIRE_WINDOW_S\|_recent_fires\|_record_leg_fire" perimeter_alert.py -> :1891, :326, :2479-2514, :2305-2325
grep -n "EXTERIOR_CAMERA_KEY_ALIASES" const.py                               -> :2984-2989
grep -n "INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS" __init__.py              -> :7699 (+ perimeter keys block :88-100)
grep -n "_IntegrationOptionsSwitch" switch.py                               -> :561-661, used :206-227
grep -n "Store(" -r custom_components/                                       -> hvac.py:967 (pattern), person_coordinator.py:492, security.py:706
grep -n "_send_whatsapp(" notification_manager.py                           -> :2044, :3102, :4475, :5443, :5470, :5796 (def :2427)
grep -n "connection_status\|Bridge not connected" ~/ha-config/custom_components/wa_bridge/client.py -> :30,53,69,85,88,91; :103
grep -n "zone\|unique_id\|device_info" ~/ha-config/custom_components/frigate/binary_sensor.py -> :45-51,72-139 (frigate 5.15.6)
grep -n "ATTR_CONFIG" ~/ha-config/custom_components/frigate/{const,__init__}.py -> const.py:34, __init__.py:378-385
grep -n "zone_agree\|single_source\|vlm\|ZONE_LEG\|ZONE_SENSOR" const.py config_flow.py switch.py number.py select.py perimeter_*.py -> no hits
grep -n "agreement_rate\|AGREEMENT" perimeter_alert.py domain_coordinators/*.py -> no perimeter hits; census CENSUS_AGREEMENT_* only (different meaning)
```

### 0.2 REUSE-or-BUILD per piece

| Piece | Verdict | Where |
|---|---|---|
| Frigate event ingress | REUSE `_on_frigate_event` | perimeter_alert.py:779-814 |
| Real score to the linker | **ALREADY DONE, no work.** The linker subscribes to `frigate_events` itself and passes `after.score`. The two `score=0.0` calls are the rising-edge fallback; the dedup fold keeps the max | exterior_track_linker.py:245-268, :465-476 |
| Per-camera event cache | EXTEND `_frigate_last_event_id` into a richer per-camera record (keep the old dict for the snapshot readers) | perimeter_alert.py:290 |
| Camera-key collapse for zone sensors | REUSE `EXTERIOR_CAMERA_KEY_ALIASES` via `_camera_key_for_sensor` (alias applied at :1872) | const.py:2984; perimeter_alert.py:1840 |
| Zone-to-camera map | BUILD small helper `_zone_camera_map()`: naming-convention prefix match, then alias. (rev 2) The private Frigate config read is dropped (load-order nondeterminism, private shape); parked in D1 | new, perimeter_alert.py |
| Zone leg config field | NEW `CONF_PERIMETER_ZONE_SENSORS` (binary_sensor multi-select). No equivalent: the camera lists are camera.* selectors and `resolve_camera_entity` only finds same-device sensors (camera_census.py:548-611); a zone sensor sits on its own Frigate zone device | config_flow.py camera step (next to CONF_PERIMETER_CAMERAS) |
| Sibling corroboration | REUSE `_recent_fires` + `_record_leg_fire` | perimeter_alert.py:2479-2514 |
| Burst demote | REUSE `_evaluate_burst_demotion`; constant change only | perimeter_alert.py:2208-2348; const.py:2481,2491 |
| Adjacent activity | REUSE `linker.has_recent_adjacent_activity` | exterior_track_linker.py:925 |
| Agreement tracker | BUILD `_AgreementTracker` (per camera, last-N outcomes). Pattern only from `camera_census._cross_validate_platforms` (camera_census.py:2294); its BOTH/CLOSE/DISAGREE vocabulary is census-specific, so it is not reused. (rev 2) Existing `_leg_fire_counts` / `_leg_sole_fire_counts` (perimeter_alert.py:320-321, :2492-2510, surfaced :2455-2470) are NOT reusable as the tracker: they count edges per engine string (not alerts per NVR family), look backward only, and are not persisted. They stay as-is | new |
| Tracker persistence | REUSE HA `Store` pattern | hvac.py:967 |
| Gate switches | REUSE `_IntegrationOptionsSwitch` (options key, no reload when the key is in the suppress set) | switch.py:561, :204-227 |
| VLM call | REUSE `enrich_dispatched_alert`; add a verdict-prompt variant | perimeter_enrichment.py:127-259 |
| Decision surfacing | REUSE `burst_demotion_stats()` / `_last_burst_decision` idiom and the exterior open-tracks diagnostic sensor | perimeter_alert.py:2392-2423 |
| WhatsApp health | REUSE `_update_channel_health` | notification_manager.py:6336 |
| Snapshot tier | ALREADY RECORDED. The filename encodes it (`<cam>_<frigate-event-id>.jpg` vs `<cam>_<epoch>_<hex6>.jpg`, :3516 vs :3543) and so does the log line `PerimeterSnapshot: wrote=... engine=...` (:3674). D8 needs no runtime code | perimeter_alert.py |
| Egress self-suppression | EXTEND the egress gate at :1074 (role-aware) | perimeter_alert.py:756-774, :1073-1090 |
| Resident identity at a door | (rev 2) PARKED with D10.2. The annotation at :1397-1447 stays display-only | camera_census.py; perimeter_alert.py:1397 |

### 0.3 Prior plans and memory consulted
- `PLANNING_perimeter_consolidation.md`, `PLANNING_consol_1_alerting_llmvision.md`: INV-ENRICH-NEVER-SILENCES, enrichment rung placement. Kept.
- `PLANNING_snap1_at_detection_snapshots.md`: capture tiers, `protect_thumb` not viable. Kept.
- `AUDIT_xcorr_engine_corroboration_probe.md` + PERIMETER-PHANTOM-XCORR-1 card: the 2026-09-12 fence (no blanket single-source demote) is relaxed only for dual-NVR cameras by operator 2026-11-08. The card's 09-28 measure already **refuted "snapshot taken late"** for that window (7/7 empties matched the Frigate ON second). D8 is therefore a confirmation probe, not an open hypothesis.
- Memories: `reference_frigate_ghost_evidence_chain` (cross-corroboration over duration gates, so no dwell gate here), `reference_frigate1_retired_2suffix_permanent`, `feedback_parent_entry_reload_watchdog_hazard`, `feedback_no_restart_during_sleep`, `project_envoy_boot_incident_2026_06_12` (`after_dependencies` stranding, relevant to parking D9).

### 0.4 Design docs read
`IDENTITY_FUSION_CAMERAS_MANUAL.md` in full (§1.1 `_2` rules, §1.3 doctrine, §4.5, §5.5 safety doctrine).

### 0.5 Code read end to end for scoping
perimeter_alert.py:260-1000, 1064-1880, 1887-2660, 3191-3700, 3759-3982; perimeter_enrichment.py (all);
exterior_track_linker.py:55-94, 238-537; config_flow.py:5290-5457; notification_manager.py:2020-2130, 2427-2487,
5400-5480, 6336-6357; switch.py:195-229, 561-661; __init__.py:85-100, 7680-7740; const.py:2395-2500;
wa_bridge 3.1.1 `client.py` and `__init__.py:97-232`; frigate 5.15.6 `binary_sensor.py:40-140`, `__init__.py:280-316, 378-385`.

### 0.6 Findings that change the brief
1. **D2's linker score is already done** (above). D2 shrinks to the cache plus an observability counter.
2. **Zone sensors are NOT discovered by today's wiring.** Frigate puts each zone on its own device, named after the zone
   (`binary_sensor.py:123-133`), so `resolve_camera_entity` (same-device) misses it, and the resolver's name-stem rung
   matches only when the zone stem equals a camera stem or an alias. A config-only switch is impossible: the
   perimeter config holds camera.* entities, not sensors.
3. **Zone entities will almost certainly be bare (no `_2`).** `_2` came from collisions with Frigate-1 entities. Frigate-1
   is removed from the registry (manual §1.1) and no camera ever had zones, so `binary_sensor.<zone>_person_occupancy`
   has nothing to collide with. The camera-level perimeter legs stay `_person_occupancy_2`. **Unverified until HomeLab
   creates them**; D1 must resolve both spellings and gate on state, never string-build one.
4. **Engine-string identity is not NVR identity.** The burst sibling check treats any different engine string as
   corroboration (:2317). A bare zone leg defaults to tag `frigate` (:487) while the camera leg is `frigate2`, so the
   two would "corroborate" each other. D1/D5 introduce an NVR-family function (`frigate*` → frigate, `protect*` →
   protect, else the tag itself) and the sibling check must use it. This is a latent pre-existing hazard that becomes
   live the day a bare zone leg is subscribed next to a `_2` leg.
5. **The snapshot offset (5 s) does not delay capture.** Capture starts at the rising edge (:3889). The offset only
   delays dispatch on the URL fallback when no local file exists (:1340-1346, :3798-3808).
6. **WhatsApp lies are wider than the bridge.** `_send_whatsapp` swallows its own exceptions and returns nothing, and every
   caller appends `"whatsapp"` to `channels_fired` and logs `delivered=1` regardless (:2044-2050). In the digest
   first-wins chain (:5467-5471) a failed WhatsApp send sets `sent=True` and blocks the iMessage fallback.
7. **Identity manual addition:** §4.5 should note that perimeter alerts now carry D3/D5/D6 demote reasons, and that
   egress cameras raise perimeter alerts (D10). Update the manual in the build commit.

---

## 1. Falsifiable invariants

**INV-FP-DEMOTE-ONLY.** For every rising edge that reaches dispatch, the new gates (D3 zone agreement, D5 single
source, D6 VLM) can only lower severity, never below `Severity.LOW`, and never prevent the NM dispatch. With every new
knob at its ship default, the severity, message, channels and `route_reason` of every alert are byte-identical to
develop at 77368438. Break it by finding any reachable config, including knob extremes and inversions, where
(a) an alert does not dispatch because of a new gate, (b) severity rises because of a new gate, or (c) with defaults,
any field differs. (rev 2) Carve-outs, the only allowed differences: the D4 `PERIMETER_BURST_NIGHT_ONLY` flip if D4a is GO
(it changes a default on purpose); D7 (no knob; `channels_fired`/log rows change only when WhatsApp actually failed);
a dispatch dropped because teardown or HA shutdown happened during a D5 settle (same rule as today's :1513). The vehicle
path (:2835-3033) is byte-identical under every knob value.

**INV-FP-FAIL-OPEN.** Each new gate demotes only on positive evidence: D3 only on a fresh Frigate event for that
camera whose zones are known and exclude the property zone; D5 only when both NVR families are live, the camera's
learned agreement rate is at or above threshold with at least the minimum sample count, and no other-family edge or
adjacent activity appeared within the settle window; D6 only on a strict `NO` verdict on a `frigate_event`-tier
snapshot. Missing, stale, malformed, timed-out or ambiguous input leaves severity unchanged. Break it with any input
where a gate demotes without that evidence.

**INV-FP-EXEMPTION.** A dispatch let through by the classification-transition exemption with an approach or circling
class is never demoted by D3/D5/D6 (same rule as the burst gate, :2256-2270).

**INV-ZONE-LEG.** For a perimeter camera with a mapped zone sensor, the camera-level Frigate person legs are not
subscribed at setup OR by the post-HA_STARTED `_rescan_siblings` (rev 2), every subscribed leg for that camera collapses to one camera key, and removing the mapping restores
exactly today's leg set.

**INV-WA-TRUTH.** A WhatsApp send is counted as delivered (`channels_fired`, `log_notification(...,1)`, channel health
`ok`, digest `sent`) only when the pre-send check did not say the bridge was down and the service call did not raise.
The check can only turn a send into a failure. It never blocks a send unless it got a known-bad answer, so an unknown
answer means today's behaviour.

**INV-EGRESS-SELF.** (rev 2) A person edge from a dual-role camera (in both the perimeter and egress lists) is never
suppressed by an egress stamp from ANY dual-role camera, its own or a co-viewing one. Stamps from egress-only cameras
still suppress it. Perimeter-only cameras keep today's egress suppression against all stamps.

---

## 2. Producer and consumer checks

| Value | Producer (and health today) | Consumers |
|---|---|---|
| Frigate `after` payload (score, box, current_zones, entered_zones, stationary) | HA automation "Frigate MQTT to frigate_events bridge", automations.yaml:6578-6595, both hosts (audit §0.3). Healthy: snapshots and the linker depend on it today | `_on_frigate_event` (:779, snapshot id), linker `_on_frigate` (:245). New: D3 gate (trust), D2 counter (display) |
| Zone sensor state | Frigate integration MQTT topic `<prefix>/<zone>/person` (binary_sensor.py:95-99). Does not exist yet (HomeLab Phase 1) | New: perimeter subscription (trust: it raises the alert) |
| Leg engine tag | `_wire_camera` (:487-512) + resolver legs. Hazard in §0.6.4 | `_record_leg_fire`, burst sibling check (:2309-2319), new D5 tracker |
| Agreement rate per camera | New D5 tracker, computed from `_recent_fires` after the pairing window | D5 gate (trust), diagnostic sensor (display) |
| VLM verdict | llmvision `image_analyzer` `{"response_text"}` (perimeter_enrichment.py:247-252). Live for 14 sensors since 2026-11-08 | D6 gate (trust), decision dict (display) |
| Snapshot tier | `_capture_precedence` (:3409); filename + log line | D6 trust filter; D8 probe |
| Bridge connection status | wa_bridge `WhatsAppBridge.connection_status` (client.py:30-91), private. Values seen: `disconnected`, `connected`, `auth_failed`, `error`, `reconnecting` | New D7 pre-send check (trust) |
| `_last_egress_time` | `_on_egress_state_change` (:758-766) | Egress gate (:1074, trust) |

---

## 3. Gate order (the single severity block)

Today: contextual severity (:1189) → linker coercion (:1216-1288) → burst demote (:1295-1322) → snapshot (:1325-1346)
→ messages → enrichment (:1468-1507) → dispatch. New gates slot in as:

1. after burst: **D3 zone agreement** (needs no snapshot)
2. after D3: **D5 single-source**. It may schedule its settle; see D5. (rev 2) The settle runs BEFORE today's in-flight
   add at :1509, so D5 must add `cooldown_key` to `_dispatch_in_flight` itself before it awaits (see D5.4).
3. after enrichment: **D6 VLM** (needs the snapshot and the verdict)

Each writes `{gate, would_demote, demoted, reason, inputs}` into one per-camera `_last_gate_decisions[cam]` dict,
surfaced next to `burst_demotions_by_camera` on the exterior open-tracks diagnostic sensor. `would_demote` is
computed even when the knob is off (shadow), so every gate collects evidence from day one. For D6, shadow mode needs
the verdict prompt (see D6). Severity is changed only when the knob says enforce.

---

## D1. Frigate zone sensors as the Frigate person leg (Phase 1b)

Config-first verdict: not possible by config alone (§0.6.2). Minimal code:

1. New rung-2 option `CONF_PERIMETER_ZONE_SENSORS` (binary_sensor multi-select, default `[]`), shown next to
   `CONF_PERIMETER_CAMERAS`. Label: "Property zone sensors". Help text: "Frigate zone person sensors to use instead of
   the whole-camera sensor, so a person on the street does not alert."
2. `_zone_camera_map()` resolves each selected sensor to a configured perimeter camera key, in this order:
   (a) the zone stem (via `_strip_person_family_suffixes`, which also strips `_2`) starts with `<camera_key>_` for exactly
   one configured camera key (longest match wins, ties mean no match). (b) `EXTERIOR_CAMERA_KEY_ALIASES` entry for the
   zone stem. No match: WARN once, do not subscribe that sensor, and keep the camera's legs as today.
   (rev 2) The rev-1 rung "read the private Frigate config from `hass.data["frigate"]`" is PARKED: whether Frigate is
   loaded at URA setup depends on load order (no dependency is added), so the map could differ boot to boot, and the
   HomeLab naming convention plus an alias already cover every case. Revival trigger: zone names that follow no
   convention and cannot be aliased.
   (rev 2) The map's value MUST be the lowercase Frigate camera name. That name is the key of `_frigate_last_event_id`
   (:806, read at :1779 and :3450) and of the D2 cache. The map is built, and `_zone_key_overrides` filled, BEFORE the
   first `_wire_camera` call: the F7 tripwire (:573-584) and the linker allowlist (:607-612) derive keys during wiring.
3. In `_wire_camera` (perimeter role only): when the camera has a mapped zone sensor, drop the camera's Frigate-family
   person legs (engine family frigate) from the subscription and add the zone sensor with engine tag `frigate2` if it
   comes from the Frigate-2 entry (registry `config_entry_id`), else `frigate`. Protect and native legs stay.
   `_sensor_to_camera[zone] = cam_entity_id`, `_sensor_platforms[zone] = "frigate"`.
   (rev 2) The exclusion is one predicate, `_is_excluded_zone_camera_leg(cam_entity_id, entity_id, engine)`, applied at
   EVERY wiring site: (i) the configured-base union :490, (ii) resolver legs :493-497, (iii) the `_2` safety net :504-512,
   (iv) the legacy fallback :543-546, (v) **`_rescan_siblings` :2532-2544** (post-HA_STARTED; without it the dropped leg
   comes back after every boot). The builder re-greps `async_track_state_change_event` in perimeter_alert.py and adds any
   other person-leg subscription site. Portability note: the census full scan (camera_census.py:1133) would treat zone
   sensors as cameras, but only on installs with no configured camera lists (:1063-1072). Not this house; no change.
4. Camera key: `_camera_key_for_sensor` must return the camera key for the zone sensor. Add a runtime overlay
   `self._zone_key_overrides: dict[zone_slug, camera_key]` consulted before the static alias table (do not mutate the
   const).
5. Every site that derives a camera stem from a sensor id must route through `_camera_key_for_sensor` (Bug Class #53).
   Enumerated: `_camera_key_for_sensor` (:1840), `_resolve_snapshot_url_and_delay` (:1772, **today strips suffixes
   directly with no alias, so it must change**), `_maybe_start_edge_capture` (:3207), `_await_edge_capture` (:3274),
   `_capture_at_detection_snapshot` (:3380), `_record_leg_fire` (:2488), `_feed_linker` (:2633), `_on_perimeter_event`
   linker observe (:3899), linker allowlist build (:607-612), F7 distinct-key tripwire (:573-584), the cooldown, in-flight
   and burst keys in the handler. The builder re-greps `_strip_person_family_suffixes\|_person_occupancy` and adds any
   site found.
6. `_warn_if_not_leg_superset` (:1922) must ignore the deliberately excluded camera-level legs, or it warns every boot.
7. The "no `_2` sibling" WARN (:513-525) must not fire for a camera whose Frigate leg is a zone sensor.
8. Engine-family helper `_nvr_family(engine)`; the burst sibling check (:2317) compares families, not strings (§0.6.4).
   With today's legs (frigate2 + protect only) this is byte-identical.
9. Enrichment allowlist is keyed by sensor entity_id (perimeter_enrichment.py:121-124, handler :1498). Operator
   action at enable time: add the zone sensors to `perimeter_enrichment_person_sensors`.

Reload: the new key, like the camera lists, is structural (it changes subscriptions), so it is NOT added to the
suppress set. Saving it reloads the parent entry, which is the watchdog hazard. **Apply it as a planned change at a
deploy restart (awake hours), not as a live save.**

Knobs: `CONF_PERIMETER_ZONE_SENSORS` (rung 2, empty = off = today). No numbers.

### Acceptance
- **Verify:** with `[]`, the subscribed sensor set equals develop for the 11 live perimeter cameras (snapshot test).
- **Verify:** with `binary_sensor.utilities_property_person_occupancy` mapped to utilities_ptz, `utilities_ptz_person_occupancy_2`
  is not subscribed, `utilities_ptz_person_detected` (Protect) is, and the zone sensor's camera key is `utilities_ptz`
  for cooldown, edge capture, linker and snapshot URL.
- **Verify:** a zone sensor spelled `_2` resolves the same as a bare one; a zone with no unique camera match is not
  subscribed and the camera keeps its camera-level leg (discriminates "silently lost coverage" from "kept").
- **Verify:** zone leg (tag frigate) plus camera Protect leg: the burst sibling check sees them as different families;
  zone leg plus a leftover `frigate2` leg do NOT count as corroboration.
- **Test:** `test_zone_leg_replaces_camera_frigate_leg`, `test_zone_leg_camera_key_all_sites` (parametrized over every site
  in item 5), `test_zone_map_frigate_config_then_prefix_then_alias`, `test_zone_map_private_shape_miss_falls_back`,
  `test_zone_leg_bare_and_suffixed`, `test_nvr_family_sibling_check`, `test_zone_sensors_empty_byte_identical`,
  (rev 2) `test_rescan_siblings_keeps_zone_exclusion` (run `_rescan_siblings` with the `_2` leg in the registry; it stays
  unsubscribed), `test_zone_overlay_installed_before_wiring` (no F7 WARN; zone key in the linker allowlist).
- **Live:** after HomeLab creates the zones and the field is set at a restart: the boot log's "person-leg coverage by
  engine" line for utilities_ptz shows the zone sensor and Protect, and not the `_2` camera leg; within 24 h a street walker
  seen on `binary_sensor.utilities_ptz_person_occupancy_2` (recorder) produces no `notification_log` row from the
  Frigate leg. Discriminator: under failure, the `[audit]` row's `location` is the `_2` camera leg.

---

## D2. Cache the Frigate event payload (Phase 3.1)

Extend `_on_frigate_event` to keep, per lowercase camera key, the latest person event:
`{id, type, score, top_score, box, current_zones, entered_zones, stationary, received_at}`. Missing keys stay `None`.
Keep `_frigate_last_event_id` exactly as is (the snapshot readers depend on it). On `type == "end"`, update the record
(final `entered_zones`) but keep today's "do not clear the id" rule (:797-804).

Also: count `frigate_events` person messages per camera, and Frigate person-leg rising edges per camera, over a rolling
24 h, both surfaced on the diagnostic sensor (display only). If Frigate legs rose ≥ `PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES`
times in 24 h with zero bus events, WARN once. That WARN is the trip-wire that the bridge automation broke, and the
revival trigger for D9.

No linker change: the linker already gets the real score (§0.6.1).

Knobs: `PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES = 20` (rung 1, observability only; 0 disables the WARN).
(rev 2) `PERIMETER_FRIGATE_BUS_WINDOW_S = 86400` (rung 1, the rolling window for both counters).

### Acceptance
- **Verify:** a replayed live payload (capture one real `frigate_events` event into a fixture, do not hand-write it)
  populates every field; a payload missing `entered_zones` stores `None` and does not raise.
- **Verify:** no alert field changes (byte-identical dispatch test).
- **Test:** `test_frigate_event_cache_fields_from_live_fixture`, `test_frigate_event_cache_missing_keys`,
  `test_frigate_bus_silent_warn`.
- **Live:** the diagnostic sensor shows a non-zero `frigate_events_24h` for back_yard within an hour of restart, and
  its cached record has a numeric `score` and a list for `current_zones`. Sentinel-only (`None` everywhere) means the payload shape is wrong.

---

## D3. Zone-agreement demote (Phase 3.2)

Applies only to cameras that have a mapped zone (from D1's map, so a camera without a property zone can never
qualify). On an alert, take the camera's cached Frigate record. If it is fresh (age ≤ `PERIMETER_ZONE_AGREEMENT_MAX_AGE_S`
before or after the edge), and `entered_zones` is a list that does not contain the mapped zone, then `would_demote`.
Enforce → LOW. `entered_zones` (anywhere during the event) is used, not `current_zones`, so a person who stepped onto
the property and back is not demoted. With no fresh event there is no evidence, so no demote. This matters because
the street walkers Frigate masks never produce an event (rear_ptz, 6 of 8).
(rev 2) `entered_zones` holds Frigate zone names; the D1 map holds HA sensor slugs. Compare `slugify(x).lower()` on both
sides. Look the cache up by the D1 map's value (the lowercase Frigate camera name).

Marginal benefit, stated plainly: once D1 is on, the Frigate leg on zoned cameras is already zone-gated. D3's residual
reach is Protect-leg alerts on zoned cameras where Frigate tracked the person but outside the zone. Once HomeLab
masks the road bands, Frigate will not track them, and D3 goes quiet. It is cheap (it reads D2's cache) and ships off
in shadow, so it stays. The shadow `would_demote` count decides whether it is ever enforced.

Knobs: `CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE` (rung 3 entity, options-backed via `_IntegrationOptionsSwitch` (rev 2 label), `switch.ura_perimeter_zone_agreement_demote`,
default off; add to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` because it is read fresh per alert).
`PERIMETER_ZONE_AGREEMENT_MAX_AGE_S = 20` (rung 1; 0 disables the gate).

### Acceptance
- **Verify:** zoned camera, fresh event, `entered_zones=[]` → LOW when on, unchanged when off, `would_demote=True` both ways.
- **Verify:** `entered_zones=["utilities_property"]` → unchanged; stale event (age 25 s) → unchanged; unzoned camera → unchanged.
- **Verify:** exemption approach/circling → unchanged.
- **Verify (rev 2):** Frigate zone name `Utilities_Property` in `entered_zones` matches sensor slug `utilities_property` → unchanged.
- **Test:** `test_zone_agreement_*` (on/off, in-zone, stale, unzoned, missing field, exemption, zone-name case), with a mutation drill
  on the demote line.
- **Live:** with the switch off, `_last_gate_decisions[*].zone_agreement` appears on the diagnostic sensor with a
  reason for each alert on zoned cameras.

---

## D4. Burst demote all day (Phase 3.3)

The build ships the replay probe. The constant flip is decided by its result **in the same cycle**: the probe is
offline and takes minutes, so it does not block the build.

1. **D4a probe** `scripts/probe_perimeter_burst_replay.py` (read-only, run via `ssh ha "python3 -" < script`). Inputs:
   `notification_log` `[audit]` rows for `exterior_person` for 30 days (dispatched history per camera); recorder
   ON edges for every perimeter person leg (sibling engine within 60 s); the adjacency graph from const.py (adjacent
   activity approximated as another camera's audit row in the window, with the approximation stated in the report).
   Rule mirrored from `_evaluate_burst_demotion` with `NIGHT_ONLY=False`. Output: per camera and hour, counts of
   would-demote alerts and the matching snapshot file (camera + epoch join, as in the audit).
2. **Go/no-go.** View a stratified sample of ≥ 30 would-demote snapshots that still exist (7-day retention).
   The harmful class is a **true person on property whose previous alert on that camera in the window was a phantom**,
   meaning a new real arrival masked by an earlier ghost. Repeats of an already-paged real visit are acceptable (the
   first page went out). GO = 0 in the sample. Record the result in this doc and in the README.
3. GO: set `PERIMETER_BURST_NIGHT_ONLY = False` (const.py:2481), leaving `PERIMETER_BURST_NIGHT_WINDOW` alone, and fix the stale
   comment at :2475-2478 ("redundant today because dispatch is gated" is false since CONSOL-1). NO-GO: ship unflipped
   and card the reason.

Knobs: existing rung-1 constants. A daytime flip of a burst constant should require review.

### Acceptance
- **Verify:** probe report committed (counts per camera, sample labels, verdict).
- **Verify (if GO):** at 13:00, second isolated back_yard alert within 30 min → LOW; first → unchanged; a sibling-corroborated
  second → unchanged.
- **Test:** `test_burst_demote_daytime_when_not_night_only`, existing XCORR tests stay green.
- **Live (if GO):** within 24 h, `notification_log` shows LOW-severity `exterior_person` rows between 07:00 and 19:00 with
  `burst_isolated` reasons on the diagnostic sensor. Discriminator: under failure, every daytime LOW has reason
  `outside_night_window`.

---

## D5. Single-source first-alert demote (Phase 3.4)

1. **Switch** (rung 3 entity, options-backed) `CONF_PERIMETER_SINGLE_SOURCE_DEMOTE`, `switch.ura_perimeter_single_source_demote` via `_IntegrationOptionsSwitch`,
   default off, fresh-read, added to the suppress set. One system-wide switch. The operator turns it on for this house after D5a.
2. **Eligibility per camera, automatic, re-evaluated per alert:**
   - both NVR families have at least one subscribed person leg whose state is not `unavailable` or `unknown`;
   - agreement tracker: samples ≥ `PERIMETER_SS_MIN_SAMPLES` and rate ≥ `PERIMETER_SS_MIN_AGREEMENT`.
   A single-NVR camera never has two families, so it can never qualify. Single-NVR homes get nothing from D5, by design.
3. **Agreement tracker.** One sample per alert that passes the cooldown while both families are live. Outcome
   "corroborated" = an edge from the other NVR family on that camera within ±`_SOLE_FIRE_WINDOW_S` (60 s) of the alert
   edge. It is evaluated lazily once 60 s have passed (at the next fire or a one-shot `async_call_later` held in a tracked
   handle and cancelled at teardown). The tracker keeps the last `PERIMETER_SS_WINDOW_N` outcomes per camera and persists
   them through `Store(hass, 1, f"{DOMAIN}.perimeter_agreement")` with a delayed save
   (`PERIMETER_AGREEMENT_SAVE_DELAY_S = 30`, rung 1). (rev 2) `_record_leg_fire` prunes `_recent_fires` to 60 s on every
   write (:2496), so the −60 s half may be gone by the time the +60 s evaluation runs. Record
   `(alert_ts, other_family_seen_in_lookback)` at alert time; at +60 s add only the forward scan. Without persistence, frequent
   restarts would keep every camera below the minimum sample count. Load failure means an empty tracker, so the camera
   is not eligible (fail-open).
4. **Decision** (first alert only; repeats belong to D4). (rev 2) "First" is computed by D5 itself: zero entries in
   `_recent_alerts_by_camera[cam]` (:330) inside `PERIMETER_BURST_WINDOW_S`. Do NOT read the burst decision's
   `prior_alerts_in_window`: it stays at its initial 0 when the burst gate returns early (disabled :2243, exemption
   :2269, outside the night window :2288), so every daytime repeat would read "first". If the
   camera is eligible and no other-family edge exists from `-60 s` up to now: when enforcing, (rev 2) first add
   `cooldown_key` to `_dispatch_in_flight` (today's add at :1509 comes after this point, so without this the second
   engine's edge passes :1149 and dispatches in parallel), then wait `PERIMETER_SS_SETTLE_S` (tracked `async_call_later`,
   cancelled at teardown). Every exit from the settle (teardown, `hass.is_stopping`, exception) discards the key; the
   normal path keeps it through to :1509 (idempotent add). Then re-check `_recent_fires` and adjacent activity
   (`has_recent_adjacent_activity`). Still single-source → LOW. Corroborated during the settle → unchanged. When not
   enforcing (switch off), record `would_demote` from the lookback alone with no wait. The tracker later reports whether
   the other engine arrived, so the shadow false-demote rate can be read off.
   Rejected alternative (parked): dispatch LOW at once and send an upgrade if corroboration arrives. It needs a second
   dispatch plus a cooldown exemption. Revival trigger: the measured settle latency hurts.
5. **Diagnostic, display only:** per camera, Frigate's own event count (D2's `frigate_events_24h`) against Frigate leg
   edges, plus the agreement rate and sample count. Protect's own event log is not reachable from HA (no event-list
   API in the integration; SNAP-1 verified that the thumbnail and event APIs are private), so the Protect comparison is
   done in the D5a probe through the Protect API from the dev box, not at runtime. Revival trigger for a runtime Protect
   count: HA exposes a public Protect event list.
6. **D5a probe** `scripts/probe_perimeter_engine_lag.py` (read-only, recorder + Protect API): per dual-leg camera, the
   distribution of the second engine's lag after the first, and the 30-day agreement rate. Sets the defaults below and
   is the go/no-go for turning the switch on. It does not block the build.

Expected reach: rear_ptz and g5_bullet (F2 corroborated 33/44 on rear_ptz, audit §8). back_yard (Protect 4 vs Frigate
116) and hot_tub will NOT qualify, so their empty-frame noise is left to Phase 1 filters, D4 and D6. That is the
operator's design, and it is stated here so nobody expects D5 to fix back_yard.

Knobs (all rung 1 until D5a measures them):
- `PERIMETER_SS_SETTLE_S = 8` (p90 of measured engine lag, rounded up; 0 = lookback only, no wait);
- `PERIMETER_SS_MIN_AGREEMENT = 0.6`;
- `PERIMETER_SS_MIN_SAMPLES = 20`;
- `PERIMETER_SS_WINDOW_N = 100`.

The kill switch is the switch itself. `PERIMETER_SS_MIN_SAMPLES = 0` is not allowed (clamped to ≥ 1).

### Acceptance
- **Verify:** switch off → byte-identical; no settle timer is ever scheduled (assert no `async_call_later`).
- **Verify:** eligible camera, Protect-only edge, no Frigate edge within settle → LOW; Frigate edge at +5 s with settle 8 →
  unchanged; Frigate leg `unavailable` → unchanged (not eligible); rate 0.59 → unchanged; samples 19 → unchanged; repeat
  alert → unchanged by D5.
- **Verify:** tracker survives a simulated restart (Store round-trip); a corrupt store → empty tracker, not eligible.
- **Verify:** teardown during a settle cancels the timer and releases the in-flight key.
- **Verify (rev 2):** sibling Frigate edge at +5 s during an 8 s settle → exactly ONE `async_notify` call, severity
  unchanged (discriminates "guard held" from "parallel dispatch": the failure shows two calls).
- **Verify (rev 2):** 13:00 with `PERIMETER_BURST_NIGHT_ONLY=True`, a second Protect-only alert 10 min after the first →
  unchanged by D5 (discriminates "own prior count" from "read the burst field": the failure shows LOW).
- **Test:** `test_single_source_*` (each bullet), `test_agreement_tracker_window_and_persistence`,
  `test_single_source_config_extremes` (threshold 0 and 1, settle 0, window 1).
- **Live:** with the switch off, the diagnostic sensor shows `agreement_rate`/`samples` per dual-leg camera, growing
  over the day, and a `single_source.would_demote` reason on alerts. After D5a and switch-on: a Protect-only
  street-walker alert on rear_ptz logs LOW with reason `single_source`.

---

## D6. VLM gate (Phase 3.5)

1. Select `CONF_PERIMETER_VLM_GATE` = `off` | `shadow` | `enforce` (rung 3, options-backed select entity
   `select.ura_perimeter_vlm_gate`, fresh-read, suppress set). Default `off`. The select is NEW: no
   `_IntegrationOptions` select exists, so the builder adds a minimal sibling of `_IntegrationOptionsSwitch` in select.py.
   A tri-state is needed because shadow must change the prompt.
2. Off: enrichment prompt and flow are untouched (byte-identical). Shadow/enforce: when enrichment runs for this
   sensor, the person handler calls a new sibling `enrich_with_verdict(hass, snapshot_path, entity_id)` (rev 2: one
   mechanism), which calls `enrich_dispatched_alert(..., prompt=_VERDICT_PROMPT)` once and returns
   `(text_without_verdict_line, verdict)`. The prompt asks for a first line exactly `PERSON: YES`, `PERSON: NO` or
   `PERSON: UNSURE`, then the description. `enrich_dispatched_alert`'s default prompt and return contract are unchanged,
   and the vehicle call at :2909 keeps calling it directly (byte-identical).
3. Parse strictly (case-insensitive regex on the first non-empty line). Anything else is `UNSURE`. The verdict line is
   stripped from the description shown to the user.
4. Demote only if verdict is `NO` **and** the snapshot tier was `frigate_event` (Frigate's own stored frame of the
   detection). A `live_grab` frame can miss a person who already left, and Phase 1's `snapshots.required_zones` will
   make street events fall back to live grab, so those frames are never trusted. The tier comes from the capture
   ledger (`_last_snapshot_capture[cam]["engine"]`) checked against the `snapshot_path` actually returned.
5. Timeout, exception, empty text, `UNSURE`, no snapshot → unchanged (INV-ENRICH-NEVER-SILENCES holds). The existing
   timeout knob applies; no new wait.
6. Enforce → `severity = LOW`. The message still carries the description, so the operator can see why it was quiet.

Knobs: `CONF_PERIMETER_VLM_GATE` (rung 2, off = kill). `PERIMETER_VLM_TRUSTED_TIERS = ("frigate_event",)` (rung 1).

### Acceptance
- **Verify:** off → the exact prompt and message of develop (string-equality test against the old prompt).
- **Verify:** enforce + `PERSON: NO` + frigate_event → LOW; same with live_grab → unchanged; `PERSON: no.` parses; `Person: maybe`
  → UNSURE → unchanged; timeout → unchanged and the base message is used.
- **Verify:** shadow → severity unchanged, `would_demote` recorded, verdict line stripped from the message.
- **Verify (rev 2):** with the select at shadow and at enforce, a vehicle alert's enrichment prompt and message equal develop.
- **Test:** `test_vlm_gate_*`, `test_vlm_gate_vehicle_path_untouched` (rev 2), plus a mutation drill on the tier filter (removing it must fail a test).
- **Live:** set shadow on the 14 enriched sensors; within a day the diagnostic shows verdicts. Cross-check 10 `NO`
  frigate_event snapshots by eye before anyone sets enforce. Discriminator: if the parse is broken, every verdict reads `UNSURE`.

---

## D7. WhatsApp silent-failure fix

1. `_send_whatsapp` returns `bool`. Before the service call, `_wa_bridge_ready()`:
   - Public signal first: the `wa_bridge` config entry(ies) via `hass.config_entries.async_entries("wa_bridge")`. If one
     exists and none is `ConfigEntryState.LOADED`, return `False` (known bad).
   - Private signal second, fully guarded: for each value in `hass.data.get("wa_bridge", {})`,
     `getattr(obj, "connection_status", None)`. `connected` → ready. `auth_failed`, `error`, `reconnecting`,
     `disconnected` → not ready. Any other value, a missing attribute, a missing dict or an exception → **unknown, treated
     as ready** (today's behaviour), with a one-shot INFO and a counter `whatsapp_probe_unknown`.
   - Only applies when the chosen domain is `wa_bridge`. The 2.x `whatsapp` path is unchanged.
   Not ready → skip the call, `_update_channel_health("whatsapp", False)`, WARN with the status, return `False`.
   Exception → `False` (as today, but now returned). Success → `True`.
   Known gap, stated: `connected` means the HA-to-bridge websocket is up, not that the bridge's WhatsApp session is
   logged in. `send_message` returns no ack (client.py:100-130), so a logged-out phone session still reads as success.
   Revival trigger for an ack-based check: wa_bridge adds a send result or a session-status field.
2. (rev 2) Callers, per site (all in `domain_coordinators/notification_manager.py`; no callers outside NM):

   | Site | Today | Change |
   |---|---|---|
   | :2044 immediate alert | appends `channels_fired`, `log_notification(...,1)` | append + log 1 only on `True`; else log 0, no append |
   | :5443 digest, selected set | `sent_any = True` | set only on `True` |
   | :5470 digest, first-wins chain | `sent = True` | set only on `True`, so the chain falls through to iMessage |
   | :3102 CRITICAL repeat | no append, no log | ignore the result; add NO new rows |
   | :4475 menu reply | no append, no log | ignore the result |
   | :5796 test send | no append, no log | ignore the result |

   The dry-run early return (:2450) returns `True` (today's callers treat it as sent).
3. Immediate alerts already fan out to every allowed channel in parallel, so no new fallback is added there. The fix is
   truthful health and truthful logs. Config check owed (not blocking): confirm no person has WhatsApp as their only
   immediate channel; if one does, card a per-recipient fallback.
4. The per-recipient audit row (:2092-2095) computes `per_person_fired` from the gate config, not from what fired.
   (rev 2) `channels_fired` is per notify (declared once at :1831, outside the person loop), so it cannot be used as is.
   Keep a per-recipient `fired_for_person` list, appended next to each channel's existing append, and build
   `per_person_fired` from it. This changes `channel`/`delivered`/`bucket_outcome` on persisted `[audit]` rows for every
   channel. The README records the first changed row's timestamp so the D4a/D8 probes and later analytics do not
   straddle the change unknowingly.
5. (rev 2) D7 lands as its own commit(s) on the cycle branch so it can be reverted alone; it shares no code with D1-D6.

Knobs: none (behavioural truth, not policy).

### Acceptance
- **Verify:** fake bridge with `connection_status="auth_failed"` → no service call, health failures +1, `channels_fired`
  lacks whatsapp, notification_log row delivered=0.
- **Verify:** fake bridge object with no `connection_status` attribute, or `hass.data["wa_bridge"]` absent → call made,
  as today (discriminates "guard too strict" from "guard working").
- **Verify:** digest with pushover off and WhatsApp `auth_failed` → iMessage sent.
- **Test:** `test_wa_ready_*` (each status, missing attr, odd value, entry not loaded), `test_wa_callers_use_result`
  (parametrized over the six sites per the table; the three "ignore" sites assert no new `log_notification` call),
  `test_digest_falls_through_on_wa_fail`, `test_audit_row_per_recipient_fired` (rev 2: two recipients, WhatsApp fails
  for one; that recipient's row lacks whatsapp, the other's has it).
- **Live:** with the bridge connected, an NM test notification arrives and `sensor` channel health shows whatsapp `ok`.
  Stop the bridge add-on for one test send (operator OK, awake hours): health counts a failure and the WARN names the status. Restart the add-on.

---

## D8. Snapshot tier and detection duration probe (read-only, no runtime code)

`scripts/probe_perimeter_snapshot_tier.py`: for alerts in the last 7 days, join `notification_log` `[audit]` rows to
`/media/ura/snapshots` files (camera + epoch, as in the audit) and classify the tier from the filename (Frigate event id
pattern `\d+\.\d+-\w+` = frigate_event, `_<epoch>_<hex6>` = live_grab, none = no file). Join the recorder ON period of
the triggering leg for duration. Output a table of tier × duration bucket × camera for the audit's 21 labelled empties
and 10 trues, plus totals for all alerts.

Discriminator: if empty frames are mostly `frigate_event`, the detector saw nothing (true phantoms, and D6's tier rule is
sound). If they are mostly `live_grab` with short ON periods, capture missed a real subject (snapshot lag), so D6 must
not trust those frames and the capture path needs a look. The 09-28 card measure already favours the first. The offset
of 5 s is irrelevant to capture (§0.6.5) and is not changed.

### Acceptance
- **Verify:** report committed in this doc's appendix with the table; the verdict feeds D6's `PERIMETER_VLM_TRUSTED_TIERS`.
- **Live:** n/a (offline).

---

## D9. Direct Frigate MQTT subscription: PARKED

Marginal benefit this cycle is zero: the bridge automation works on this house, and D2 adds the trip-wire for when it
stops. The ingredients are risky: a second ingress beside the bus listener (double feed into the snapshot cache and the
linker, which needs dedup), an `mqtt` dependency in the manifest (the 2026-06-12 `after_dependencies` stranding
incident), and topic-prefix discovery per Frigate host (`frigate` / `frigate2`). The value is portability for other
installs.

**Revival trigger:** a second URA install without the bridge automation, OR D2's bus-silent WARN fires on this house.
Design note for then: discover prefixes from the Frigate config entries, subscribe `<prefix>/events`, and publish into
the same handler with a source tag, deduplicating by event id.

---

## D10. Egress cameras raise perimeter alerts with descriptions

Scope: `camera.madrone_g6_entry`, `camera.doorbell_lite`, `camera.front_door_aerial`. garage_a_2/garage_b_2 are out of
scope: they are interior-garage views whose crossings are the residents' own, and the retired automation did not cover
them.

Why config alone fails (verified): adding them to `perimeter_cameras` makes the same sensor fire both listeners.
`_on_egress_state_change` (:758-766) stamps `_last_egress_time` synchronously, and the handler task's check at :1074
(120 s, :247) then suppresses the camera's own alert. The camera-list save is unsafe-structural (__init__.py:88-98) and
takes the parent reload path.

1. **Role-aware egress suppression (code).** Record `_last_egress_time_by_key[cam_key]` alongside the global
   timestamp. (rev 2) When the alerting camera is dual-role (in both lists), the egress gate ignores stamps from ANY
   dual-role camera, not only its own: madrone_g6_entry and front_door_aerial are adjacent (const.py:2734) and both see
   the front entry, so with a self-only rule each one's stamp would suppress the other's alert and D10 would not work for
   the cameras it targets. Stamps from egress-only cameras (garage_a_2/b_2) still suppress a dual-role camera. A
   perimeter-only alerting camera is unchanged: every stamp suppresses it for `EGRESS_SUPPRESSION_WINDOW_SECONDS` (120 s,
   :247), so a resident walking out the front door still silences the side cameras.
2. **(rev 2) PARKED: residents at their own door should not page.** Not built this cycle. Protect resolves a face name
   40-80 s or more after the detection, and the websocket never pushes it (memory `reference_protect_face_latency_async`).
   At dispatch, the leg for the current crossing usually has no name, but it may still hold a name latched from an
   earlier crossing. The freshness filter at :1419-1425 keeps legs with no timestamp (lenient, display-only). Used for
   severity, that would demote a stranger to LOW under a resident's earlier name. The benefit is small: the contextual
   LOW for home_day already covers the common case. **Revival trigger:** a probe shows an identity matched to the
   detection time (leg `event_start` within a named window of the edge) readable before dispatch for these cameras.
   The "Identified: X" annotation is unchanged. Original rev-1 text, kept for revival:
   What exists: the identity annotation at :1397-1447
   (`census._resolve_face_legs`, display-only, floor 0.60 for Frigate), the egress `person_id` producer with confidence
   0.9 / 0.75 / 0.6 (manual §5.3), and contextual severity that is already LOW in home_day/evening first sightings when
   trusted persons_home ≥ 1 (const.py:2589). Under the §5.5(a) doctrine, identity may de-escalate only at ≥ 0.9. Rule: on
   an egress-role camera's own alert, if a resident slug is resolved for that camera with confidence ≥
   `PERIMETER_EGRESS_RESIDENT_DEMOTE_MIN_CONF` (0.9), demote to LOW and keep the "Identified: X" annotation. Frigate legs
   carry no numeric confidence (treated as 0.60), so in practice this fires only on Protect-named faces (two cameras,
   manual §2.3) or a future fused 0.9. Most resident crossings will still alert at contextual severity. That is honest
   and per doctrine; the contextual LOW for home_day already softens the daytime case.
   Open (not blocking): the egress producer's 0.9 is stamped in transit_validator, possibly after this dispatch.
   Whether the perimeter path can read it in time is for the builder to measure; if not, only the face-leg path
   applies.
3. **Vehicle and animal.** The retired automation also sent vehicle and animal alerts. URA's vehicle path is deep-night
   only (vehicle hours knob) and the animal path is digest-only. Extending them all day on the doorbells reintroduces
   the street-traffic noise the audit found in `doorbell_alerts` ("Garage_Doorbell_Vehicle"). Plan: person alerts in this
   cycle. Vehicle/animal on egress cameras is an operator decision, carded as PERIMETER-EGRESS-VEHICLE-ANIMAL-1 and not built.
   (rev 2) Adding the cameras to `perimeter_cameras` would subscribe their vehicle legs anyway: the vehicle/animal loop
   iterates `perimeter_infos` (:827-858). So the build skips dual-role cameras in the VEHICLE loop until that card
   decides. Animal legs stay subscribed: they only feed the linker (:2620), with no NM dispatch.
4. **Config at deploy restart (planned reload):** add the three cameras to `perimeter_cameras` and their person sensors
   to `perimeter_enrichment_person_sensors`, in the same save as D1's zone field if that is ready, at the deploy restart
   during awake hours. One parent reload, not two.

Knobs: none new (rev 2: `PERIMETER_EGRESS_RESIDENT_DEMOTE_MIN_CONF` parked with D10.2). No new switch: the role is
derived from both lists.

### Acceptance
- **Verify:** doorbell_lite in both lists; its own edge → alert dispatches (not `egress_suppression`); a front_side_ptz edge 30
  s after a doorbell_lite egress edge → suppressed as today.
- **Verify (rev 2):** madrone_g6_entry and front_door_aerial both dual-role; front_door_aerial stamps at t=0, madrone_g6_entry's
  edge at t=+3 s → dispatches. A garage_a_2 (egress-only) stamp 30 s before → madrone_g6_entry suppressed.
- **Verify:** a camera only in `perimeter_cameras` → byte-identical egress behaviour.
- **Verify (rev 2):** dual-role doorbell vehicle leg is not subscribed; its animal leg is.
- **Test:** `test_egress_self_not_suppressed`, `test_egress_dual_role_cross_stamp_not_suppressed`,
  `test_egress_other_still_suppresses`, `test_egress_only_stamp_suppresses_dual_role`, `test_dual_role_vehicle_leg_skipped`.
- **Live:** after the planned restart, a person at the front door produces a `notification_log` `exterior_person` row with
  `location` = the doorbell's person sensor and a description in the message; `suppressions_by_camera` shows no
  `egress_suppression` for that camera's own edge.

---

### D10.5 (rev 2, operator 2026-11-08): egress-camera alerts page only for an unknown, corroborated person

Operator: "it should only alert if it doesn't know someone and it should be cross correlated." This replaces the parked
D10.2. It applies only to a dual-role camera's own person alert (the D10.1 role). Every other camera is unchanged.

**Pieces, all reused:**
- *Identity sources*, freshness-matched to the edge (this closes the H4 latched-name hazard):
  (i) the `ura_person_egress_event` bus event (transit_validator.py:2005; fields `egress_camera`, `timestamp` =
  detection time, `person_id`, `identity_confidence`) for the same camera key, with `timestamp` within
  ±`PERIMETER_EGRESS_IDENTITY_MATCH_S` of the edge; (ii) `census._resolve_face_legs(stem)` (camera_census.py:3177)
  legs whose `last_changed` is at or after `edge − PERIMETER_EGRESS_IDENTITY_MATCH_S`, and whose `event_start`
  attribute (if the bridge publishes one) falls in the same window. A leg without a timestamp is NOT fresh for this
  use (the lenient rule at :1419-1425 stays display-only).
- *Known* = the slug is a configured resident or is in `known_face_guests` (`_get_known_face_guests`,
  camera_census.py:3776), at confidence ≥ `PERIMETER_EGRESS_KNOWN_MIN_CONF`. **Doctrine:** manual §5.5(a) allows
  identity to de-escalate only at ≥ 0.9. So the knob is clamped to ≥ 0.9, and Frigate face legs (no score, ranked 0.60)
  and 0.75 scored legs count as *unknown*. Result: a resident recognised only by Frigate still pages if corroborated.
  Relaxing that is a change to the doctrine, which is the operator's call and is not made here.
- *Corroborated* = an edge from the other NVR family on the same camera within ±`_SOLE_FIRE_WINDOW_S` (the D1
  `_nvr_family` check over `_recent_fires`), OR `linker.has_recent_adjacent_activity` (exterior_track_linker.py:925).
  These are the XCORR-1 inputs, with no new signal.
- *Second leg down:* if the camera has no live leg from a second NVR family (D5's liveness test), corroboration is
  waived and only the unknown test applies. This is logged as `xcorr_waived_single_nvr`.

**Decision (after the wait below), demote-only, floor LOW:**

| Identity | Corroboration | Result | reason |
|---|---|---|---|
| known ≥ 0.9 | any | LOW | `egress_known_person` |
| unknown | corroborated | contextual severity (unchanged) | `egress_unknown_corroborated` |
| unknown | not corroborated, second leg live | LOW | `egress_uncorroborated` |
| unknown | second leg down | contextual severity (unchanged) | `xcorr_waived_single_nvr` |

INV-FP-EXEMPTION holds: an approach/circling exemption dispatch is never demoted. D5 is skipped on dual-role cameras,
because D10.5 subsumes it, so the two waits never stack.

**Bounded identity wait, with its discharge.** Protect back-fills the name 40-80 s or more after the detection
(memory `reference_protect_face_latency_async`). So when a dual-role camera's alert would page (unknown so far), the
handler holds it for up to `PERIMETER_EGRESS_IDENTITY_WAIT_S`, using the same in-flight hold as D5 (H1: the key is
added before the await). Discharges, whichever comes first:
(1) a matching known identity arrives (a bus listener on `ura_person_egress_event`, or a state change on that
camera's face legs) → LOW, dispatch now; (2) the deadline timer fires → dispatch per the table with identity unknown;
(3) teardown or HA stopping → cancel the timer, release the key and the exemption seed (today's :1513 rule). The
timer is a tracked `async_call_later` handle, and the listener unsubscribes on every discharge. Cost, stated plainly:
a real stranger's page arrives up to 90 s late. `PERIMETER_EGRESS_IDENTITY_WAIT_S = 0` means no wait (only an
identity already present at dispatch counts).
Rejected (parked, as in D5): dispatch LOW first and upgrade later. It needs a second dispatch plus a cooldown
exemption. Revival trigger: the measured wait cost is unacceptable AND Protect's name latency drops below ~10 s.

**PRECONDITION (rev 2, H6): LOW is NOT "logged, not pushed" today.** `exterior_person` is in `NM_SECURITY_HAZARDS`
(const.py:2542). Any alert with a snapshot sets `_force_immediate_for_security_image`
(notification_manager.py:1557-1560) and is delivered IMMEDIATELY (:1904-1909). Which channels it reaches comes from the
per-person severity gate (`_gate_channels_for_notify`, :1888). So a LOW perimeter alert still pushes on whatever
channels each person's matrix allows for LOW. That holds for every demote in this plan, not just D10. Config-first:
the build's first task is a read-only check of each person's LOW channel gate for `exterior_person`. If the operator
wants "LOW = no push", set that in the matrix (a config change). If the matrix cannot express it per hazard, card a
change. Do not add a second suppression path in this cycle.

Knobs (rev 2): `CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE` (rung 3 options-backed switch,
`switch.ura_perimeter_egress_known_xcorr_gate`, default ON because these cameras page nothing today, so the gate can
only make their new alerts quieter; off = D10.1 behaviour at contextual severity; added to the suppress set, read fresh);
`PERIMETER_EGRESS_IDENTITY_WAIT_S = 90` (rung 1; 0 = no wait); `PERIMETER_EGRESS_IDENTITY_MATCH_S = 15` (rung 1);
`PERIMETER_EGRESS_KNOWN_MIN_CONF = 0.9` (rung 1, clamped to ≥ 0.9, 1.01 disables the known demote).

#### Acceptance (D10.5)
- **Verify:** known resident at 0.9 via `ura_person_egress_event` at t=+70 s within a 90 s wait → one dispatch, LOW,
  reason `egress_known_person`, sent at about +70 s (discharge 1, not the deadline).
- **Verify:** unknown, Protect + Frigate edges 4 s apart → contextual severity after the 90 s deadline (discharge 2).
- **Verify:** unknown, Protect only, Frigate leg live → LOW `egress_uncorroborated`; Frigate leg `unavailable` →
  contextual `xcorr_waived_single_nvr` (discriminates "waived" from "demoted").
- **Verify:** a resident name latched 5 min before the edge (no new event) → treated as unknown (H4 regression test).
- **Verify:** Frigate face leg for a resident (conf None) → unknown; knob set to 0.5 → behaves as 0.9.
- **Verify:** teardown mid-wait → timer cancelled, listener unsubscribed, in-flight key released, no dispatch.
- **Verify:** a second edge during the wait → exactly one `async_notify`.
- **Test:** `test_egress_gate_known_discharges_early`, `test_egress_gate_deadline_unknown_corroborated`,
  `test_egress_gate_uncorroborated_low`, `test_egress_gate_single_nvr_waiver`, `test_egress_gate_latched_name_ignored`,
  `test_egress_gate_doctrine_floor`, `test_egress_gate_teardown_discharge`, `test_egress_gate_single_dispatch`,
  `test_egress_gate_switch_off_is_d10_1`; mutation drills on the freshness check and the corroboration check.
- **Live:** after enable, a resident walking out the front door produces either no `exterior_person` row on that
  camera or a LOW row with reason `egress_known_person` on the diagnostic sensor; a stranger produces a row at
  contextual severity with `egress_unknown_corroborated`. Discriminator: under a broken identity match, every
  resident crossing shows `egress_unknown_*`.

### D10.6 (rev 2): camera.sonoffwindow wiring confirmation (no work)
Verified in the live registry (`~/ha-config/.storage/core.entity_registry`): `camera.sonoffwindow` (platform frigate,
device 01f7f0e7) and `binary_sensor.sonoffwindow_person_occupancy` on the same device, bare (no `_2`) because nothing
collides. `_wire_camera` subscribes it as the configured base with engine tag `frigate` (:487-492). Two side effects,
neither of which needs work now: the boot WARN "no `_2` sibling found ... F2 host detections will not alert" fires for
it every boot (:513-525; a false alarm here, since the bare entity IS the live host's leg), and it is single-NVR, so
D5 never qualifies it. Optional LOW follow-up: suppress that WARN when the base sensor's config entry is the only live
Frigate entry. Not built.

---

## D11. Camera-list options save without a parent reload (rev 2, operator 2026-11-08)

**Tier: Tier 3, own branch and review set.** It changes a shared primitive (`CameraIntegrationManager`'s
`_cameras_by_area`/`_camera_by_entity` maps), consumed by the room occupancy path (sensor.py:2809), presence
(presence.py:5006, :5014), census, transit_validator and perimeter. The failure mode is one missed consumer or one
empty-map window. The reload path also carries the watchdog history (`feedback_parent_entry_reload_watchdog_hazard`).
D11 does not block D1-D10. If it lands first, D10's camera-list change can be a live save instead of a restart.

Marginal benefit, stated: camera-list edits are rare, and the restart path works. D11 removes one restart per
camera-list change and the watchdog risk of a live save. It is worth doing because the operator asked and because the
hazard has caused real outages, but it is the riskiest piece in this document. That is why it is split out.

Prior art (REUSED): `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (const.py:3075; transit_validator subscribes at :364 and
rebuilds); the per-key discharge table `_INTEGRATION_KEY_SIGNAL_TABLE` (__init__.py:7797); the allowlist
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (__init__.py:7699); the audit's parked follow-up #1
(`AUDIT_integration_options_reload_classification.md:78-79,125`). No `SIGNAL_CAMERA_LIST_CHANGED` exists (grep: no hits).

Consumers of the two keys (grep, rev 2): `__init__.py:2913-2914` (setup-time discover), camera_census.py:1663, :2223-2224
(fresh reads), transit_validator.py:476 (via camera_manager, discharged by the signal), perimeter_alert.py:419-420
(CACHED at setup, the gap), :1719-1720 (fresh), optimization.py:2648-2649, :3298-3299 (fresh per call; builder confirms).

1. **Atomic rediscover.** `async_discover` clears the maps and THEN awaits (camera_census.py:1057-1069). Run live, that
   leaves a window where `get_cameras_for_area` returns `[]` to the occupancy path. Add
   `async_rediscover(...)`: build into locals, then swap all four maps in one synchronous block, with no await between
   clear and assign. Setup keeps calling `async_discover` (byte-identical).
2. **Perimeter rewire.** Split the wiring part of `PerimeterAlertManager.async_setup` (:387-~1000) into
   `_async_wire_legs()`. `async_rewire()` unsubscribes the perimeter, egress, vehicle and animal listeners only (NOT the
   `frigate_events` listener or the linker-ready listener), clears `_sensor_to_camera`/`_sensor_platforms`/
   `_sensor_engine`/`_perimeter_allowlist`, re-runs `_async_wire_legs()`, and re-installs the linker allowlist.
   Pending dispatches, cooldowns and the burst/agreement histories are kept. A dispatch already in flight finishes on its
   own closure state.
3. **One orchestrator, fixed order.** Signal subscribers have no guaranteed order, so the reload-suppress branch runs one
   NEW coroutine `_async_camera_lists_changed(hass)` (NEW: no equivalent orchestrator exists). It does: (a) await
   `camera_manager.async_rediscover`, (b) await `perimeter.async_rewire()`, (c) dispatch
   `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` for transit_validator. Any exception falls back to today's parent reload
   (fail-safe to current behaviour).
4. **Admit the keys.** Add `CONF_PERIMETER_CAMERAS` and `CONF_EGRESS_CAMERAS` to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`
   and update the comments at __init__.py:88-98, :7689, :7770. Kill switch: the existing
   `INTEGRATION_RELOAD_SUPPRESS_ENABLED` (:7787) plus a NEW module const `CAMERA_LIST_LIVE_REWIRE_ENABLED = True` (rung 1;
   False = keys behave as today, parent reload).

**Falsifiable invariant INV-CAMLIST-LIVE:** after a camera-list save with no parent reload, the subscribed leg set,
`_cameras_by_area`, and transit_validator's subscriptions all equal what a fresh restart with the same options would
produce, and no reader of `get_cameras_for_area` ever sees an empty or partial map during the swap.

#### Acceptance (D11)
- **Verify:** add a camera via options → no `async_reload` of the parent entry; the new camera's legs subscribed; leg
  set equals a fresh-setup snapshot (set-equality test).
- **Verify:** remove a camera → its legs are unsubscribed, and an edge on them produces no handler call.
- **Verify:** a reader polling `get_cameras_for_area` concurrently with `async_rediscover` never sees `[]` for an area
  that has cameras before and after.
- **Verify:** an orchestrator exception → parent reload path taken (fallback test).
- **Verify:** `frigate_events` listener count unchanged after 3 rewires (no listener leak).
- **Test:** `test_camera_list_save_no_reload`, `test_rewire_equals_fresh_setup`, `test_rediscover_atomic_swap`,
  `test_camera_list_orchestrator_fallback_reload`, `test_rewire_no_listener_leak`; Tier-3 per-site mutation on the swap
  and on each unsubscribe.
- **Live:** an options save adding `camera.doorbell_lite` during awake hours → no "Setting up universal_room_automation"
  log line and no watchdog restart; the boot-style coverage log line appears for the new camera; the room occupancy
  sensors for areas with cameras keep their state across the save.

## 4. Numbers and knobs (summary)

| Knob | Rung | Default | Kill / off |
|---|---|---|---|
| `CONF_PERIMETER_ZONE_SENSORS` | 2 | `[]` | empty |
| `PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES` | 1 | 20 | 0 |
| `PERIMETER_FRIGATE_BUS_WINDOW_S` (rev 2) | 1 | 86400 | n/a |
| `CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE` (switch) | 3 (options-backed) | off | off |
| `PERIMETER_ZONE_AGREEMENT_MAX_AGE_S` | 1 | 20 | 0 |
| `PERIMETER_BURST_NIGHT_ONLY` (existing) | 1 | True; False if D4a GO | True |
| `CONF_PERIMETER_SINGLE_SOURCE_DEMOTE` (switch) | 3 (options-backed) | off | off |
| `PERIMETER_AGREEMENT_SAVE_DELAY_S` (rev 2) | 1 | 30 | n/a |
| `PERIMETER_SS_SETTLE_S` | 1 | 8 (D5a sets) | 0 = lookback only |
| `PERIMETER_SS_MIN_AGREEMENT` | 1 | 0.6 (D5a sets) | 1.01 |
| `PERIMETER_SS_MIN_SAMPLES` | 1 | 20 | n/a (≥ 1) |
| `PERIMETER_SS_WINDOW_N` | 1 | 100 | n/a |
| `CONF_PERIMETER_VLM_GATE` (select) | 3 (options-backed) | off | off |
| `PERIMETER_VLM_TRUSTED_TIERS` | 1 | `("frigate_event",)` | `()` |
| ~~`PERIMETER_EGRESS_RESIDENT_DEMOTE_MIN_CONF`~~ | parked with D10.2 (rev 2) | | |
| `CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE` (switch, rev 2) | 3 (options-backed) | on | off = D10.1 |
| `PERIMETER_EGRESS_IDENTITY_WAIT_S` (rev 2) | 1 | 90 | 0 = no wait |
| `PERIMETER_EGRESS_IDENTITY_MATCH_S` (rev 2) | 1 | 15 | n/a |
| `PERIMETER_EGRESS_KNOWN_MIN_CONF` (rev 2) | 1 | 0.9 (clamped ≥ 0.9) | 1.01 |
| `CAMERA_LIST_LIVE_REWIRE_ENABLED` (D11, rev 2) | 1 | True | False = parent reload |

The rung-1 numbers stay rung 1 because each is either measurement-fitted (D5a) or a doctrine floor. Promote to a
Number entity only if the operator tunes them by observation after the probes.

## 5. Non-goals
- No change to Frigate or Protect config (HomeLab and operator own Phases 1 and 2), census/person counting, the linker's
  algorithm, contextual severity tables, cooldown, or capture tiers.
- No duration or dwell gate (ghost doctrine).
- No DB schema change. No new notification channel or per-recipient fallback.
- No Protect runtime event counting (D5.5), no direct MQTT (D9), no vehicle/animal on egress cameras (D10.3).
- (rev 2) No change to the vehicle alert path (:2760-3033): D3/D5/D6 never touch its severity, enrichment prompt or
  dispatch. No identity-based demote (D10.2 parked). No private Frigate config read (D1 rung parked).
- Phase 4 storage (`doorbell_alerts`) is HA-automation scope, not URA.

## 6. Build order and probes
1. D8, D4a, D5a probes (read-only, parallel; ura-prober). D4a's verdict decides the constant before review.
2. D2 → D1 → D3 (shared cache and map) → D5 → D6 → D10 (incl. D10.5) → D7 (independent, NM file, own commits). One
   branch, one Tier 2-DB review set. (rev 2) Before D10.5: the read-only LOW channel-gate check (H6 precondition).
   D11 goes on its own branch with a Tier-3 review set (four framings + operator checkpoint) and does not block this one.
3. Config at the deploy restart: D1 zone field (once HomeLab names exist), D10 camera lists and enrichment allowlist,
   gates left off or in shadow. Turning gates on is a later knob turn by the operator, read off the shadow data.

## 7. Open questions (none block the build)
1. HomeLab zone names. The convention `<frigate_camera>_property` (e.g. `utilities_ptz_property`) makes the prefix map
   exact. Other names work through the Frigate config read or an alias entry.
2. Whether any person has WhatsApp as their only immediate channel (D7.3).
3. ~~Whether the egress 0.9 identity is readable before dispatch~~ (rev 2: D10.2 parked; this is now its revival probe).
4. Operator decision on vehicle/animal alerts for the doorbells (D10.3).
5. (rev 2) Should LOW perimeter alerts push at all? Today they do, on whatever channels each person's matrix allows for
   LOW (H6). The operator's "logged, not pushed" needs a matrix setting.
6. (rev 2) The §5.5(a) doctrine means Frigate-only face matches (0.60) cannot silence an egress page. Keep it, or relax it
   for this one consumer? Operator decision; the plan keeps it.
