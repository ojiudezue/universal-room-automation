# PLANNING: rebuild face arrival as one face-sighting signal, with action-class policy in each consumer

Card: **FACE-ARRIVAL-REBUILD-1** (tier 3, thread identity). Related: ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1,
PERSON-PROFILE-PREFERENCES-1, FRIGATE-DOOR-FACE-TUNING-1. Rev 1, 2026-11-12, ura-planner.
Status: plan only. Needs two framing-disjoint plan reviews (completeness + adversarial build-prediction),
then operator APPROVE. No version in this name; the version is assigned at deploy.

Read before writing (completely): `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`,
`CLAUDE.md` (incl. the fire-check corollary), `AUDIT_face_arrival_and_prearrival_fan_rooms.md`,
`AUDIT_face_production_after_nov_fixes.md`; `PLANNING_egress_identity_producer.md` and
`PLANNING_lock_suspicious_arrival_hold.md` by section (invariant, prior art, knobs, consumers). Nothing
here re-asserts a §10 ledger claim of the presence doc. HVAC is touched only at the pre-arrival entry
point (`hvac._handle_person_arriving`); see §11 for the HVAC doc requirement before build.

Paths below are relative to `custom_components/universal_room_automation/` unless stated.

---

## 0. Summary and the honest pushback first

**What is broken (verified this session).** The v3.19 path `presence._handle_camera_change` (`presence.py:5444`)
-> `_get_face_for_camera` (`:5487`) -> `_handle_face_arrival` (`:5581`) -> `SIGNAL_PERSON_ARRIVING(source=camera_face)`
(`:5632`) has fired 0 times in every activity-log window read (~90 days). Four independent defects, any one fatal:

1. **Wrong listener source.** It listens to zone-tracker cameras from `_discover_zone_cameras` (`presence.py:5060`),
   which filters by entity-level area; every camera here has its area on the device, so trackers have no cameras.
   The operator's actual picks (`zone_cameras` on the ZM entry, `config_flow.async_step_zone_cameras` `:11590`)
   are read only by `check_zone_occupancy_confidence` (`presence.py:2389`, called from `hvac.py:3089`).
2. **Edge race / freshness.** The face is read only at the person sensor's `on` edge and must be < 30 s old
   (`presence.py:5567-5574`). The name usually lands after the edge (audit: family_room 22 fresh-at-edge vs 89
   named within 60 s after).
3. **Producer disabled to protect one consumer.** `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED = False`
   (`const.py:3511`) returns None for every `_N` person sensor (`presence.py:5532-5535`), to protect the SC
   lock regime. This is the anti-pattern the fire-check corollary forbids.
4. **No arrival semantics.** No was-away test: an interior face of a resident who is home would be an "arrival"
   (STATE_OF_PLAY §1 table). Egress identity attaches `person_id` (~40 %) but emits no arrival.

**Live picks (read from `.storage/core.config_entries`, read-only, 2026-11-12):**

| House zone | `zone_cameras` | `zone_persons` |
|---|---|---|
| Back Hallway | `binary_sensor.staircase_person_occupancy`, `binary_sensor.garage_a_camera_person_detected` | none |
| Entertainment | `family_room_person_occupancy`, `foyer_fisheye_person_occupancy`, `master_hallway_person_occupancy` | ezinne, oji_udezue |
| Master Suite | `master_hallway_person_occupancy` | ezinne, oji_udezue |
| Upstairs | `upstairs_hall_person_occupancy_2`, `playroom_person_occupancy_2`, `stairs_top_person_occupancy` | ziri, jaya |

8 distinct cameras, one (`master_hallway`) in two zones. `garage_a_camera_person_detected` is a **UniFi Protect**
person sensor; the HA Protect integration exposes no face name (manual §1, §2.3), so that pick yields a face only
if a Frigate face sensor resolves for the same physical camera (D0 checks). Also read: CM `face_recognition_enabled
= True`, `pre_arrival_sources = [geofence, ble, camera_face]`, `face_name_aliases` absent (so Oji is unmapped:
Frigate says "Oji", the entity is `person.oji_udezue`), `security_on_arrival_add_expected` absent (default False,
`config_flow.py:10403`).

**Marginal-benefit decomposition (required before the spec).**

| Consumer | What face adds over today | Size |
|---|---|---|
| HVAC pre-arrival (comfort) | Today geofence + ble supply 337 of 337 pre-arrival triggers in 30 days. Face adds a trigger only when the phone is late or absent. | Small, unmeasured. D0-P3 measures it. |
| SC lock regime (access) | Needs an independent non-face arrival edge anyway (`_face_arrival_corroborated`, `security_lock_regime.py:1374`). A tracker edge already releases via P1. The face's only marginal effect is through the Bermuda-into-entry-area leg. | Near zero by design. |
| Security expected arrivals (access: alarm suppression) | Off by default; a face must never feed it (§2). | Zero (negative if allowed). |
| Music (`music_following.py:549`) | Logs only. | Zero. |
| Personalization (PERSON-PROFILE-PREFERENCES-1, not built) | Who is in which shared room/hallway, now. Needs BLE for private rooms. | Future. The main reason for the sighting signal. |
| Presence fusion (census) | Census already reads faces (S5/S6/S7, manual §1.1). | Zero this cycle. |

**Verdict.** The arrival itself is worth little: the lock cannot use it, HVAC rarely needs it. The durable value is
the **sighting signal**: a correct, timely, granular "who was seen where" that future consumers (personalization,
notifications, ARRIVAL-DEPARTURE-NOTIFY-1) read. So this plan builds the simple version:

- one sighting producer with correct sources, timing and granularity;
- `camera_face` arrivals derived from sightings by one fixed rule, gated by D0;
- per-consumer action-class policy, enforced in code;
- the trip-wire.

**Parked, with revival triggers:** the interior track sequence (§9 D7: D0-P4 decides; default PARK), and any
presence/census fusion of sightings.

---

## 1. Institutional context verified

### 1.1 Config-first check

| Could config fix it? | Finding |
|---|---|
| Add picks so the tracker discovers cameras | No. Discovery ignores device area; picks are not read by the face path at all. |
| Flip `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` | Rung-1 const (code change), and it would point camera_face at the doorbell/garage cameras without fixing (1), (2) or (4). It still does nothing while trackers are empty. |
| Add `face_name_aliases` `Oji=oji_udezue` | Yes, and needed. **Operator action, recommended now** (Camera Census, Advanced). It fixes the Oji mapping for census, perimeter D10.5 and this path. It does not make face arrival fire. |
| Disable `camera_face` in `pre_arrival_sources` | Hides the symptom. HVAC is not the problem. |

So code is required for (1), (2), (4) and the producer/consumer split. The alias is an operator action, listed in §13.

### 1.2 Prior-art scan: REUSE or BUILD (code, plans, analysis)

Greps run, all under `custom_components/universal_room_automation/` unless stated:
`grep -rn SIGNAL_PERSON_ARRIVING`; `grep -rn "zone_cameras\|CONF_ZONE_CAMERAS"`; `grep -n FACE_ const.py`;
`grep -rn "ura_person_egress_event"`; `grep -rn "face_sighting\|FACE_SIGHTING\|SIGNAL_FACE"` (**0 hits**);
`grep -n "def " arrival_edges.py`; `grep -rn fire_stuck_signal`; `grep -rn "adjacency"`;
`grep -rn "add_expected_arrival"`; `grep -rn "face_arrivals_today\|camera_face_arrivals_today\|_face_arrival_cooldown"`.

| Piece | Verdict | Existing symbol (file:line) | Note |
|---|---|---|---|
| Operator picks | **REUSE** | `hvac_const.CONF_ZONE_CAMERAS` `:348`; ZM entry `zones.<zone>.zone_cameras`; form `config_flow.async_step_zone_cameras` `:11590`; HVAC merge `hvac_zones.py:540-568` | Read per **house** zone from the ZM entry, not from the merged HVAC zone (compound names, §3.3). |
| Face name at recognition time | **REUSE** | census MQTT face bridge `camera_census._on_frigate_face_msg` `:5459`, latch `_frigate_face_latch` `:1530`, stems via `_compute_face_latch_stems` | Add one post-latch hook (D1). Retained messages are already skipped (`:5468`). |
| Face sensor resolution (fallback source) | **REUSE** | `_resolve_face_entity_id` `:3158`, `_device_derived_face_entity_id` `:3274`, `face_name_entities_for_stem` (`camera_resolver.py:698`) | Registry-first; never string-build (`_2` rule, manual §1.1). |
| Face producer suppression | **REUSE** | `census._face_suppressed_now` `:4458` | Same checkpoint as today (FS-4). |
| Name -> person | **REUSE** | `presence._find_person_entity_from_face` `:5644`; `census.face_alias_person_slug` `:4089`; `_canonical_person_slug` `:3903` | Salvaged. |
| Debounce | **REUSE (re-keyed)** | `presence._face_arrival_cooldown` `:1820`, 60 s, cleared at midnight `:8740` | Key becomes person + camera stem (was person + zone). |
| Camera -> area -> room -> zone | **REUSE** | `camera_resolver.resolve_area_id_for_entity` `:427` (entity area, then device area); presence `_room_to_zone` / `get_room_zone` (STATE_OF_PLAY §1) | No new registry walk. |
| Egress identity | **REUSE** | `transit_validator` fires `ura_person_egress_event` `:2016` (`person_id`, `identity_confidence`, `agreement_class`, `identity_synthetic_corroborated`) | Subscribe; do not modify the producer. |
| Independent arrival edge | **REUSE** | `arrival_edges.py`: `nonface_arrival_source` `:168`, `bermuda_arrival_into` `:90`, `stamped_bermuda_arrival` `:150`, `door_entry_areas` `:223`, `edge_in_window` `:85`; lock gate `security_lock_regime._face_arrival_corroborated` `:1374` | The access-class gate. LOCK-ENTRY-AREAS-WRONG-OBJECT-1 is fixed on develop (`_entry_areas` `:1364` reads `egress_tracker`). |
| Arrival signal + consumers | **REUSE** | `signals.SIGNAL_PERSON_ARRIVING` `:25` | Payload extended additively (§3.2). |
| Zone/HVAC counters | **REUSE (fix)** | tracker `_face_arrivals_today` `presence.py:653`; `ZoneState.camera_face_arrivals_today` `hvac_zones.py:176` | The HVAC counter matches `zstate.zone_name == zone_name` (`presence.py:5617`). That never matches a merged HVAC zone ("A + B"). Fix in D3. |
| Trip-wire NM | **REUSE** | `_stuck_signal_nm.fire_stuck_signal` `:165` (per-day dedup), presence D4 pattern (`presence.py:4337`) | |
| Face count denominator for the trip-wire | **REUSE** | `census._frigate_face_msg_face_count` `:1541` | |
| Track sequence | **REUSE pattern if built** | `exterior_track_linker.py` + `const.EXTERIOR_ADJACENCY_GRAPH` `:2948`; room adjacency `presence.get_adjacent_rooms` `:3407` | Parked by default (§9 D7). |
| **Face-sighting signal + payload** | **BUILD** | none: `face_sighting` / `SIGNAL_FACE` grep = 0 hits | `SIGNAL_FACE_SIGHTING` in `signals.py` + frozen dataclass `FaceSighting`. |
| **Sighting producer** | **BUILD (small)** | none | `face_sighting.py` (pure-ish module) + wiring in presence. Replaces the v3.19 listener. |
| **Arrival derivation rule** | **BUILD (small)** | none (v3.19 had no was-away test) | One function, one call site. |

**Plans and analysis consulted:** `PLANNING_egress_identity_producer.md` (the §0 invariant shape, the 0.9/0.75/0.6
confidence ladder, `base_stem` independence, abstain-on-conflict); `PLANNING_lock_suspicious_arrival_hold.md` (§4.2
lists every site that can unlock; held-edge rule in `_apply_arrival`); `PLANNING_exterior_track_linking.md`
(adjacency-as-data pattern for D7); the two audits above. Memory bodies: `reference_protect_face_latency_async`
(Protect names back-fill 1-2 min), `reference_frigate1_retired_2suffix_permanent`,
`reference_egress_face_coverage_7pct_not_a_ceiling` (+ amendments), `feedback_read_consumers_before_asserting_function`,
`project_house_zones_vs_hvac_zones`, `feedback_portability_imperative`.

### 1.3 Code surveyed end to end
`presence.py` 5040-5700 (discovery, camera handler, face helpers), 2308-2410 (zone confidence), 1350-1375 (ARRIVING);
`hvac.py` 1425-1440, 1507-1514, 7212-7290; `security.py` 249-330, 1580-1600, 2381-2430; `security_lock_regime.py`
996-1060, 1364-1460; `music_following.py` 549-585; `camera_census.py` 349-372, 5455-5605; `transit_validator.py`
1990-2035; `arrival_edges.py` 1-245; `const.py` 2660-2690, 3320-3340, 3495-3512.

---

## 2. Falsifiable invariants (reviewer D breaks these)

**INV-ACCESS (the load-bearing one).** In any reachable path, a face-derived input can never, on its own, cause:
garage-lockout release (`SecurityLockRegime._release`), away-lock unlock (`_away_release`), an expected-arrival entry
that turns a door-open into SANCTIONED (`SanctionChecker.add_expected_arrival`, `security.py:257`, consumed at
`:302`), or a security disarm (`SecurityCoordinator.handle_disarm`, `security.py:2472`).

- "Face-derived input" means a `FaceSighting`, or a `SIGNAL_PERSON_ARRIVING` whose `source` is `camera_face`
  (any `sighting_source`).
- Such an action needs an independent non-face arrival edge for the SAME person, per
  `arrival_edges.nonface_arrival_source`, within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120 s) and outside the
  boot exclusion.
- Falsifier: any legal config plus state where a face input reaches one of those four sinks without that edge.
  Configs include alias set or unset, `security_on_arrival_add_expected` True, lockout and away-lock switches ON,
  window 0, and egress `identity_confidence` 0.9 with a synthetic leg.
- **Scope, stated so D can attack it:** the pre-existing transitive path "camera body -> census count ->
  `has_people` -> AWAY -> ARRIVING (`presence.py:1367-1369`) -> lock release on ARRIVING / auto-follow disarm" is
  driven by body evidence, not a name. It exists today with or without this cycle and is not widened (no sighting
  feeds census or inference, §8 non-goal). D must confirm "not widened". If D finds that a NAMED face changes that
  path's outcome where a nameless body would not, that is a finding. The pre-existing path itself is carded
  (LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1, §12), not fixed here.

**INV-PRODUCER (fire-check).** The sighting producer is never disabled, filtered or narrowed to protect a consumer.
After this cycle no constant or branch in the producer reads a consumer's identity or action class.
`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` is retired (KEEP + DOCUMENT, no reader). Falsifier: a recognised
resident face on any picked camera, including a `_N` person sensor and the doorbell/garage cameras via egress, that
produces no `SIGNAL_FACE_SIGHTING` while `face_recognition_enabled`, `FACE_SIGHTING_ENABLED` and not
`_face_suppressed_now()`.

**INV-NOOP.** With `FACE_SIGHTING_ENABLED = False`, the four `SIGNAL_PERSON_ARRIVING` consumers see exactly the
dispatches they see on develop today, which is zero `camera_face`. No new listener is registered. Byte-identical
apart from the retired v3.19 listener, which is already inert.

---

## 3. Design

### 3.1 The one signal

`SIGNAL_FACE_SIGHTING = "ura_face_sighting"` (`signals.py`). Payload: frozen dataclass `FaceSighting`
(`face_sighting.py`):

| Field | Meaning |
|---|---|
| `person_entity` | `person.<slug>` after alias mapping. Unmapped names emit nothing and are counted in `unmapped_names`. |
| `slug`, `face_name` | Canonical slug; raw Frigate name. |
| `camera` | The picked person sensor (interior), or the egress camera id. |
| `stem` | Camera `base_stem` (physical-camera key, manual §5.2). |
| `area_id`, `room` | Via `resolve_area_id_for_entity`, then the URA room whose `CONF_AREA_ID` matches. None if no room. Always a shared space or hallway (operator: cameras are only there). |
| `house_zones` | Tuple of house-zone names whose picks include this camera (master_hallway gives 2). Egress: zone of `room`, else `()`. |
| `ts` | When the face was recognised (latch write time, or the face sensor's `last_changed`), NOT dispatch time. |
| `confidence` | Interior: `None` (Frigate gives no usable score in HA; do not invent one). Egress: `identity_confidence`. |
| `sighting_source` | `interior_pick` or `egress_entry` / `egress_exit`. |
| `synthetic` | True when the name came only from the MQTT latch (interior), or `identity_synthetic_corroborated` (egress). |
| `person_edge_age_s` | Seconds since the camera's person sensor was last `on` (None if unknown). Diagnostic and consumer-usable. |

Granularity: consumers choose camera, room or zone. Room-level means "seen in a shared room or hallway". **Private
rooms are never inferred from a sighting.** A personalization consumer must combine it with BLE
(`person_coordinator` location). The docstring and the design doc state this.

### 3.2 Producer (D1) — `face_sighting.py` + presence wiring

Sources:

- **(a) MQTT bridge hook.** After `_on_frigate_face_msg` writes the latch (`camera_census.py:5591-5592`), call one
  registered callback `(stem, name, now)`. Census does not know presence. The callback list is set by presence at
  setup, and a raising callback is caught.
- **(b) Face-sensor state change.** For each pick, resolve its face sensor(s) once (registry-first, `_2`-tolerant).
  Subscribe with `async_track_state_change_event`. A transition to a real name is a sighting.
  - (b) covers installs or moments where the bridge is down.
  - (a) and (b) for the same recognition dedupe on (slug, stem) inside `FACE_SIGHTING_DEBOUNCE_S`. First wins; a
    later non-synthetic copy clears `synthetic` only when it arrives inside the window. No re-emit.
- **(c) Egress.** A `ura_person_egress_event` with non-null `person_id` gives `egress_entry` or `egress_exit`.
  `ambiguous` gives nothing. Exit backfills (`SIGNAL_EGRESS_EXIT_BACKFILLED`) are NOT sightings (late, BLE-derived).

Filters (producer-side, about evidence quality only, never about consumers):

- face suppression (`_face_suppressed_now`);
- sentinel names;
- the stem must be a pick, or an egress camera for (c);
- `person.<slug>` raw `not_home` does NOT drop a sighting. A face of an away resident is exactly the arrival
  candidate. Mislabels are a consumer concern; the access gate handles them.

`_N` person sensors: picks are resolved through the device (`_device_derived_face_entity_id`) without the retired
flag. That is the INV-PRODUCER change.

The v3.19 listener chain (`_handle_camera_change` face branch `:5478-5481`, `_get_face_for_camera`,
`_handle_face_arrival`) is removed. The tracker camera-occupancy routing above it (`:5466-5471`) is unchanged
(ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 owns it).

Teardown: every unsub goes in `_unsub_listeners`. The census callback is deregistered on presence unload, and census
holds it in a list that tolerates a missing presence.

### 3.3 Arrival derivation (D2): one rule, one site

In presence, on each sighting, dispatch `SIGNAL_PERSON_ARRIVING` with payload
`{"person_entity", "source": "camera_face", "sighting": FaceSighting, "zone": <first house zone or "">}` iff
`arrival_candidate(sighting)`:

- `egress_entry` -> candidate.
- `egress_exit` -> never.
- `interior_pick` -> candidate iff the person's raw `person.<slug>` state was not `home` at `ts`, or went
  `-> home` within `FACE_ARRIVAL_RECENT_HOME_S` before `ts`.
  - It reads raw state, deliberately: the edge-triggered reader convention (STATE_OF_PLAY §1). It is NOT
    `person_state_for_trust`.

This is arrival SEMANTICS (what counts as an arrival event), not consumer policy. It fixes defect (4). The D0-P3
measurement sets `FACE_ARRIVAL_RECENT_HOME_S` and decides whether interior arrivals ship at all
(`FACE_ARRIVAL_INTERIOR_ENABLED`). Debounce per person (not per zone) for arrivals: `FACE_ARRIVAL_DEBOUNCE_S`.
The payload keeps `person_entity` and `source`, so every existing consumer parses it unchanged. The `zone` key
already exists in music's parser.

HVAC counters: tracker `_face_arrivals_today` is incremented per house zone in `house_zones`. The HVAC
`camera_face_arrivals_today` is matched by **zone membership**: the HVAC zone whose `rooms` contain `room`, or
whose `zone_name` split on `" + "` contains the house zone. Never by string equality. This salvages the counter and
fixes the compound-name miss.

### 3.4 Consumer policy by action class (D3) — enforced in each consumer

| Consumer | Class | Policy for `source == camera_face` | Change |
|---|---|---|---|
| `hvac._handle_person_arriving` `:7212` | comfort | Face alone OK (existing source filter `pre_arrival_sources`). | None to logic. The existing `pre_arrival_spent` episode guard bounds repeats. |
| `security_lock_regime.on_person_arriving` `:996` | access (unlock / lockout release) | Unchanged: `_face_arrival_corroborated`, plus the hold drop in `_apply_arrival`. | Tests only (new source mix, egress-sourced faces). |
| `security._handle_person_arriving_signal` -> `add_expected_arrival` `:2412-2419` | access (alarm suppression) | **Reject camera_face** unless `_face_arrival_corroborated`-equivalent (shared helper via `arrival_edges.nonface_arrival_source`) passes. Default: reject. | **Code change.** Today it would accept a face-only arrival when the toggle is on. A latent INV-ACCESS leak that this cycle would make reachable. |
| `music_following._handle_person_arriving` `:549` | personalization | Face OK (it only logs). | None. |
| Disarm | access | No arrival consumer disarms (grep `handle_disarm` callers: `security.py:1452` auto-follow on house state only). | Test pins that no sighting/arrival path reaches `handle_disarm`. |

A SIGHTING has no consumer in this cycle beyond the D2 adapter and diagnostics. New consumers (personalization,
notifications) are separate cards that must declare their action class and reuse this table.

### 3.5 Diagnostics and the zero-fire trip-wire (D4)

Attributes on the existing `sensor.ura_presence_coordinator_*` house-state sensor, or the presence diagnostics
sensor if attributes are already crowded (builder picks; unrecorded via `_unrecorded_attributes`):

- `face_sightings_today` and `face_sightings_by_source`;
- `face_arrivals_derived_today`;
- `face_sighting_last` (slug, camera, room, ts);
- `face_sighting_unmapped_names`;
- `face_sighting_picks_resolved` / `_unresolved` (picks with no face sensor, e.g. the Protect garage pick).

Trip-wire `face_sighting_zero`: one HIGH stuck-signal NM via `fire_stuck_signal` when, over the trailing
`FACE_SIGHTING_ZERO_WINDOW_H`, the bridge counted ≥ `FACE_SIGHTING_ZERO_MIN_FACES` named face messages on picked
stems, but sightings emitted = 0. It is a RAM counter pair, re-armed when sightings resume. That is the exact
signature of the v3.19 failure (faces exist, the producer emits nothing). A second, LOW, page fires when derived
arrivals = 0 for 14 days while sightings > 0. It covers arrival-rule starvation; the window is a knob, and 0 = off.

---

## 4. Producer and consumer checks

**Producer health (measured, not assumed).**

- Named Frigate faces: 855 in 11-05..11-12, 85 % interior (production audit).
- Per picked camera, named 11-05..12: family_room_2 419, master_hallway_2 126, upstairs_hall_2 38, staircase_2 28,
  playroom_2 25, stairs_top_2 17; foyer_fisheye not in the top list.
- Bridge live: `frigate_face_msg_face_count` 191 since the last restart.
- Egress `person_id` attach 40 %.
- Oji is unmapped until the alias exists.
- Rates track who is home (Oji is travelling): a quiet day is not a fault, hence the trip-wire's ratio form.

**Fire counts.**

- `camera_face` pre_arrival rows: 0 in all windows read.
- geofence 220, ble 117 (10-13..11-12).
- Lock-regime camera_face holds: 0 (no input).
- `face_arrivals_today`: 0 everywhere.
- After this cycle, the expected order of magnitude: sightings ~50-150 per day while people are home; derived
  interior arrivals set by D0-P3.

**Forward trace to every action.**

| Path | Actions |
|---|---|
| sighting -> D2 adapter -> `SIGNAL_PERSON_ARRIVING` -> HVAC | `_pre_arrival_zones` -> decision cycle -> pre-cool / pre-arrival fans (3 eligible rooms, audit Q2) |
| -> lock regime | gated release / unlock |
| -> security | expected arrival (now face-gated) |
| -> music | log |

No other subscriber (`grep -rn SIGNAL_PERSON_ARRIVING`: hvac `:1511`, security `:817`, music `:281`, plus the lock
via security). The person_coordinator `:1132` and presence `:5297` sites are producers.

---

## 5. Emission / decision-site enumeration

Producers of `SIGNAL_PERSON_ARRIVING`: `presence.py:5297` (geofence), `person_coordinator.py:1132` (ble),
`presence.py:5634` (camera_face, removed and replaced by the D2 site).

Consumers: `hvac.py:1511`, `security.py:817` (which feeds `security_lock_regime.on_person_arriving` `:996`),
`music_following.py:281`.

Sinks guarded by INV-ACCESS:

| Sink | Location |
|---|---|
| `_release` | lock regime; callers include `_apply_arrival`, house-state edges, P1/P5 |
| `_away_release` | lock regime |
| `add_expected_arrival` | callers `security.py:2276`, `:2286`, `:2419`, service `:2511` |
| `handle_disarm` | `security.py:2472`; caller `:1452` |

Reviewer D re-runs these greps independently. The plan's list is a hypothesis.

---

## 6. Numbers get knobs

All are rung 1 (module constants in `const.py`) unless stated: they are protocol windows or semantics that should
change only by review.

| Knob | Default | Rung | Why / kill semantics |
|---|---|---|---|
| `FACE_SIGHTING_ENABLED` | True | 1 | Kill switch for the whole producer. False = INV-NOOP. |
| `FACE_SIGHTING_DEBOUNCE_S` | 60 | 1 | Salvaged v3.19 value; per person + stem. 0 = no debounce. |
| `FACE_ARRIVAL_INTERIOR_ENABLED` | set by D0-P3 (default False until measured) | 1 | Interior-derived arrivals. Egress entries are unaffected. |
| `FACE_ARRIVAL_RECENT_HOME_S` | set by D0-P3 (placeholder 300) | 1 | How recently a home edge still counts as arriving. 0 = only not-home-at-ts. |
| `FACE_ARRIVAL_DEBOUNCE_S` | 600 | 1 | One arrival per person per episode; HVAC also bounds with its episode guard. |
| `FACE_ARRIVAL_EGRESS_MIN_CONF` | 0.6 | 1 | Egress identity floor for an arrival (comfort class; access classes still need the non-face edge). 1.01 = egress arrivals off. |
| `FACE_SIGHTING_ZERO_WINDOW_H` | 24 | 1 | Trip-wire window; 0 = off. |
| `FACE_SIGHTING_ZERO_MIN_FACES` | 10 | 1 | Bridge faces on picked stems needed before zero sightings is a fault. |
| `FACE_ARRIVAL_ZERO_DAYS` | 14 | 1 | Second trip-wire; 0 = off. |
| Security face gate window | REUSE `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120) + boot floor `max(..., GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S)` | 1 | Same coupling note as `const.py:2674`: widening it widens all three access consumers. |
| Picks | REUSE `zone_cameras` | 2 (options flow) | Operator-owned. |
| Aliases | REUSE `face_name_aliases` | 2 | Operator action. |

**Retired:** `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` (KEEP + DOCUMENT, no reader; comment points here), and
the inline 30 s literal at `presence.py:5572` (deleted with the function).

---

## 7. Measure before build — D0 (read-only probe, the go/no-go gate)

One script, `scripts/probes/face_sighting_d0.py`, run via `ssh ha "python3 -" <` against the recorder (7.5 days)
and the URA DB. The report goes into this doc as §7.1 before build dispatch.

- **P1, pick resolution.** For each of the 8 picks: resolved face sensor(s) through the registry/device path; named
  events in window. Is the Protect `garage_a_camera_person_detected` reachable to a Frigate face sensor? Go: at least
  5 picks resolve.
- **P2, sighting volume and timing.**
  - Per pick: named events per day, and the lag from the person `on` edge to the name (confirms trigger-on-name).
  - Count of (a) bridge vs (b) sensor-change double reports (sets the dedup expectation).
  - Egress events with `person_id` per day, by direction.
- **P3, arrival rule** (the critical gate). For each interior resident face event, classify it by the person's raw
  state at ts and the next `-> home` edge:
  - (i) not_home and a home edge follows within 10 min: **true arrival, phone lagging**;
  - (ii) not_home, no home edge within 30 min: **mislabel or phone-less**;
  - (iii) home with a home edge within X s before: **arrival just recorded**;
  - (iv) home otherwise: not an arrival.

  Report counts per person and per camera. The audit's 292 "not home" interior events (Jaya 220) must be explained
  here before any interior arrival ships.
  **Go rule:** `FACE_ARRIVAL_INTERIOR_ENABLED = True` only if (i) ≥ 1 per week AND (i) / ((i) + (ii)) ≥ 0.5.
  Otherwise ship sightings + egress arrivals only, and park interior arrivals with the trigger "a resident's tracker
  degrades so (i) rises". `FACE_ARRIVAL_RECENT_HOME_S` = p90 of the face-after-home-edge lag in class (iii), capped
  at 600.
- **P4, interior track sequence.** Over picked cameras: per ordered camera pair, the distribution of person-edge
  lags (A on -> B on within 120 s). Also the fraction of UNNAMED interior person edges that a named edge on an
  adjacent camera within 60 s could label (the only value of a track: propagating identity).
  **Go rule for D7:** propagation would add ≥ 25 % more named sightings with ≤ 10 % conflicting-name pairs.
  Otherwise park D7 (default expectation: park; interior cameras already carry 85 % of faces).
- **P5, consumer reality.** Live `security_on_arrival_add_expected`; lock regime garage lockout and away-lock switch
  states; HVAC `pre_arrival_enabled`. These say which consumers are live, not assumed.

Fixture: P3 output is hand-labelled for ~20 events (operator or BLE ground truth) and committed as
`quality/tests/fixtures/face_arrival_d0_labelled.json`. That table is the D2 acceptance oracle (hand-build before
automating).

---

## 8. Non-goals

- No change to Frigate config or face training (FRIGATE-DOOR-FACE-TUNING-1, homelab).
- No change to `_discover_zone_cameras` / tracker camera occupancy / `CameraInfo.area_id`
  (ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1; its census ripple is separate).
- No sighting feeds census, house-state inference, the guest gate, `check_zone_occupancy_confidence`, or NM.
- No private-room location from cameras. No personalization consumer (PERSON-PROFILE-PREFERENCES-1).
- No arrival/departure notifications (ARRIVAL-DEPARTURE-NOTIFY-1).
- No change to the egress producer, its windows, or the exit backfill.
- No change to the lock regime's corroboration rule or the suspicious-arrival hold. Tests only.
- No Protect face-name bridge (parked D1-PROTECT-FACE-BRIDGE-ADDON-1).
- No DB table or persistence for sightings (RAM + attributes). A sightings ledger is a future card if a consumer
  needs history.
- No fix to the pre-existing body-evidence ARRIVING -> unlock path (carded, §12).

---

## 9. Deliverables

### D0: Probe and labelled fixture (§7)
- **Verify:** §7.1 report committed with P1-P5 numbers. Go/no-go recorded for D2-interior and D7.
- **Test:** none (read-only).
- **Live:** n/a.

### D1: Sighting producer (sources a/b/c), signal, payload
- **Verify:** a named face on any of the 8 picks, including `upstairs_hall_person_occupancy_2` /
  `playroom_person_occupancy_2`, emits exactly one `SIGNAL_FACE_SIGHTING` per (slug, stem, debounce window) with
  the correct room and house_zones. `master_hallway` gives `("Entertainment", "Master Suite")`.
- **Verify (discriminating):**
  - Under the fix, a name arriving 45 s after the person edge emits, with `person_edge_age_s ≈ 45`.
  - Under the old failure (edge-read), the same input emits nothing.
  - A stale retained name emits nothing.
  - An `Unknown` state emits nothing.
- **Verify:** a non-picked camera's face emits nothing (interior source). An egress entry with `person_id` emits
  `egress_entry` with its `identity_confidence`.
- **Test:** `test_face_sighting.py::test_bridge_name_after_edge_emits`, `::test_sensor_change_fallback_emits`,
  `::test_bridge_and_sensor_dedup_single_emit`, `::test_n_suffix_pick_resolves_without_flag`,
  `::test_unpicked_camera_silent`, `::test_egress_entry_and_exit_sightings`, `::test_ambiguous_egress_silent`,
  `::test_backfill_not_a_sighting`, `::test_face_suppressed_silent`, `::test_unmapped_name_counted_not_emitted`,
  `::test_alias_maps_oji`, `::test_master_hallway_two_zones`, `::test_teardown_unsubscribes_all` (real hass).
- **Live:** after restart, `face_sighting_picks_resolved` ≥ the D0-P1 count. `face_sightings_today` > 0 within the
  first named face on a pick (compare to the recorder: every `*_last_recognized_face*` change to a resident name on
  a picked stem has a matching sighting, ±debounce).

### D2: Arrival derivation (one site)
- **Verify:**
  - `egress_entry` at or above `FACE_ARRIVAL_EGRESS_MIN_CONF` dispatches `SIGNAL_PERSON_ARRIVING(camera_face)`
    with a `sighting`.
  - `egress_exit` never does.
  - Interior: per D0 gate. When enabled, class (i)/(iii) events from the fixture dispatch and class (iv) do not.
    Class (ii) dispatches (comfort accepts it), and the lock and security consumers reject it, by D3.
- **Verify (discriminating):** a resident at home walking past family_room 10 times dispatches 0 arrivals. Under the
  v3.19 semantics it would be 10.
- **Test:** `test_face_arrival_rule.py::test_fixture_classes` (drives the labelled fixture),
  `::test_home_resident_no_arrival`, `::test_recent_home_edge_window`, `::test_exit_never_arrival`,
  `::test_arrival_debounce_per_person`, `::test_hvac_counter_matches_compound_zone`, `::test_kill_switch_noop`.
- **Live:** `face_arrivals_derived_today` and HVAC `camera_face_arrivals_today` move only on events that the
  recorder shows as class (i)/(iii) or as egress entries. An activity-log `pre_arrival` row with `source=camera_face`
  appears on the first qualifying event.

### D3: Consumer policy (security face gate; lock and HVAC pinned)
- **Verify:**
  - With `security_on_arrival_add_expected=True`, a camera_face arrival with no non-face edge leaves
    `_expected_arrivals` empty.
  - With a Bermuda entry-area move or a tracker home edge within 120 s, it adds.
  - geofence/ble arrivals are unchanged.
- **Verify:** the lock regime holds an egress-sourced camera_face arrival with no edge and releases with one (same as
  today's interior behaviour).
- **Test:**
  - `test_security_face_expected_arrival.py::test_face_only_rejected`, `::test_face_with_edge_accepted`,
    `::test_geofence_unchanged`;
  - `test_sc_lock_face_sighting.py::test_egress_face_held_without_edge`, `::test_interior_face_held_without_edge`,
    `::test_face_released_with_bermuda_entry_edge`;
  - `test_face_access_invariant.py::test_no_face_path_reaches_disarm`;
  - config extremes: window 0 (never), alias set/unset, `identity_confidence` 0.9 synthetic, toggle on with both
    lock switches on.
- **Live:** lock-regime snapshot `lock_regime_*` and security `expected_arrivals` show no face-only effect. Any
  `Lock regime: camera_face arrival for X held` INFO line is followed by no release unless a matching edge exists in
  the recorder.

### D4: Diagnostics and trip-wires
- **Verify:** the attributes in §3.5 exist and are unrecorded.
- **Verify (discriminating):** with sightings forced to 0 by mutating the D1 emit (test) and bridge faces ≥ 10, one
  HIGH `face_sighting_zero` NM fires within the window. With sightings > 0 nothing fires. With no faces (house
  empty) nothing fires.
- **Test:** `test_face_sighting_tripwire.py::test_zero_with_faces_pages`, `::test_zero_without_faces_silent`,
  `::test_rearm_after_recovery`, `::test_window_zero_off`.
- **Live:** no `face_sighting_zero` NM in the first day with residents home.

### D5: Retire the v3.19 path and flag; docs
- Remove the `_handle_camera_change` face branch, `_get_face_for_camera` and `_handle_face_arrival` (their salvaged
  parts move to D1/D2). `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` becomes KEEP + DOCUMENT.
- Update, in the same commit:
  - IDENTITY_FUSION_CAMERAS_MANUAL §1.1 (the S8 paragraph), §4.5 (lock face arrivals), §5.5 (consumer map);
  - PRESENCE_ARCHITECTURE_STATE_OF_PLAY §1 table (the `SIGNAL_PERSON_ARRIVING` row: "camera_face fires for any
    zone-camera face" becomes the D2 rule). Add a §10 entry: "face arrival worked since v3.19" is false, it never
    fired;
  - HVAC_ARCHITECTURE_STATE_OF_PLAY pre-arrival source line.
- **Test:** `grep` test that no production reader of the retired flag remains (`test_face_sighting.py::test_retired_flag_unread`).
- **Live:** n/a.

### D6: Real-HA integration test
One real-hass test: config entries with picks, census + presence + security + HVAC up. Fire a face sensor change and
an egress event. Assert the sighting, the arrival and each consumer's effect. Guards the v5.8.0 fake-coordinator
incident class. `quality/tests/test_face_sighting_realhass.py`.

### D7 (PARKED unless D0-P4 passes): interior track sequence
If P4 passes: an adjacency-as-data map of picked cameras (`INTERIOR_CAMERA_ADJACENCY` rung 1, modelled on
`EXTERIOR_ADJACENCY_GRAPH`). Propagate a name to an unnamed person edge on an adjacent camera within the measured lag.
Emit with `synthetic=True` and `sighting_source="interior_track"`, never an arrival. Revival trigger if parked: door
camera recognition stays below 20 % of crossings after FRIGATE-DOOR-FACE-TUNING-1 AND a personalization consumer
needs hallway continuity.

### Mutation drills (framing C; each must turn a named test RED; restore and check `git status` after each)

| # | Mutation | Expected RED test |
|---|---|---|
| M1 | Drop the bridge hook call | `::test_bridge_name_after_edge_emits` |
| M2 | Read the face at the edge only (v3.19 shape) | same |
| M3 | Remove the debounce key's stem | `::test_bridge_and_sensor_dedup_single_emit` |
| M4 | `arrival_candidate` returns True always | `::test_home_resident_no_arrival` |
| M5 | Security face gate bypassed | `::test_face_only_rejected` |
| M6 | Lock `_face_arrival_corroborated` returns True | `::test_egress_face_held_without_edge` |
| M7 | Re-add a `_N` skip in the producer | `::test_n_suffix_pick_resolves_without_flag` |
| M8 | Trip-wire compare inverted | `::test_zero_with_faces_pages` |
| M9 | HVAC counter back to string equality | `::test_hvac_counter_matches_compound_zone` |

### Live validation table (written back into the README after restart)
L1 picks resolved. L2 first sighting matches a recorder face change. L3 no arrival from a home resident's interior
sighting (pick one from the recorder). L4 an egress entry with person_id produces an arrival and an HVAC pre_arrival
row (or explain the HVAC skip reason). L5 no face-only lock release or expected arrival (snapshot plus log scan).
L6 no trip-wire NM. L7 INFO setup line `Face sighting: N picks resolved, M egress cameras`.

---

## 10. Marginal risk, priced in ingredients

| Ingredient | Assessment |
|---|---|
| New writer to a shared primitive (`SIGNAL_PERSON_ARRIVING`) | The rate rises from 0 to the D2 rate, and an access consumer is downstream. Containment: D3 plus INV-ACCESS. That is why this is Tier 3. |
| Cross-module callback (census -> presence) | One hook, list-held, exception-isolated, deregistered at unload. |
| Rare-fire path | Interior arrivals may be rare. Mitigated by the trip-wire and D0. |
| Synthetic time | None. Timestamps come from the latch/sensor, compared with wall clock only for debounce. |
| Config combinatorics | Picks × alias × three security toggles × window. Covered by the D3 extremes. |

---

## 11. Tier classification

**Tier 3.** Triggers:

- a value threaded into a signal consumed by four sites, one of them an unlock;
- the failure mode is one missed site (the expected-arrival sink would have been one);
- operator-flagged first-principles rebuild.

Process:

- Two plan reviews: completeness, and adversarial build-prediction.
- Build by `ura-super-builder` in a worktree.
- Four build reviews: A local, B integration/lifecycle, C per-site mutation (§9 drills), D adversarial completeness
  against INV-ACCESS / INV-PRODUCER including the pre-existing code.
- Orchestrator re-greps §5 and re-runs M5/M6.
- Operator checkpoint before deploy.

**HVAC touch:** only the pre-arrival entry point's input set changes. The builder and reviewer read
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely before touching `hvac.py` (this planner did not; the plan needs no
HVAC logic change. If a reviewer finds one is needed, the HVAC doc read is mandatory first).

## 12. Cards to mint (adjacency sweep before minting)
- **LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1** (investigate): AWAY -> ARRIVING from body evidence alone releases
  the garage lockout and can auto-follow disarm; review against the §5.5(a) doctrine.
- **FACE-SIGHTING-CONSUMERS-1** (backlog, after ship): personalization and notifications declare an action class
  and read sightings.

## 13. Operator actions (no code)
1. Add `face_name_aliases`: `Oji=oji_udezue` (Camera Census, Advanced). This also helps census and perimeter now.
2. Confirm the `garage_a_camera_person_detected` pick is intended (a Protect sensor; it gives no face name in HA).
   D0-P1 reports whether a Frigate face resolves for it.
