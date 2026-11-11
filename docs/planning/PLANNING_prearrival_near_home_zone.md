# PLANNING: Pre-arrival "near home" zone (PREARRIVAL-NEAR-HOME-ZONE-1)

**Card:** PREARRIVAL-NEAR-HOME-ZONE-1 (thread hvac, Tier 2). **Status:** plan rev 1, written 2026-11-11, awaiting the one Tier-2 plan review. Not built.
**Operator pick (2026-11-11):** option A, "Near home is better than bigger": a separate near-home zone used ONLY as an earlier arrival signal for HVAC pre-cool. `zone.home` is not enlarged.
**Read first, completely, before this plan was written:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all of it, including the §10 corrections ledger C1-C39), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all of it, including §10 items 1-32) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No claim from either ledger is re-asserted here. No contradiction between those docs and the code read for this plan was found, with one note for the presence doc: §1 says the SC lock regime's "optional approach zone" is a P5 edge, and the code confirms it only works for a NON-passive zone (`security_lock_regime._is_approach_zone` compares `person.state` with the zone name, `:1266-1279`). The live option `security_lockout_approach_zone` is set to `zone.home` (CM entry, read 2026-11-11), so that edge is inert today. Recorded for the presence doc at build time, not a defect.

---

## 0. Summary and shape

Today HVAC pre-arrival fires on `SIGNAL_PERSON_ARRIVING` (sources `geofence` / `ble` / `camera_face`). The geofence source fires when `person.<x>` turns `home`, which happens at the `zone.home` edge (radius 150 m, live). Measured over 30 days (URA activity log, `hvac` `pre_arrival` rows): geofence 215 triggers, BLE 112; when both fired BLE came ~0.5 min after geofence (median; p90 22 min). So the geofence gives about 30 s of lead, and pre-cool starts roughly when the person is at the door.

This cycle adds ONE more pre-arrival source, `near_home`: the first GPS fix of a person INSIDE an operator-created, **passive** HA zone, after a fix OUTSIDE it. HVAC consumes it through its existing `_handle_person_arriving` entry, unchanged. Nothing else in URA sees it. `person.state` is not changed (that is why the zone must be passive, §2.1).

**Who it helps.** Only people with a GPS tracker. Live (2026-11-11): `person.oji_udezue` (`device_tracker.phalanxiphone15promaxcflare`, `source_type gps`) and `person.ezinne` (`device_tracker.zinny_s_iphone_15`, `gps`). **Jaya and Ziri have BLE-only person trackers** (`private_ble_device_249050` + `iphone_jaya_bermuda_tracker`; `ziri_iphone` is `source_type bluetooth_le` + `iphone_ziri_bermuda_tracker`), so their person entities carry no coordinates and near-home can never fire for them. Their "geofence" pre-arrivals are themselves BLE. This is accepted (operator: only tracked phones matter); it is stated in the README and the option help text.

**Falsifiable invariants:** §3. **Tier:** 2 (§9). **First deliverable is a read-only probe (D0) that gates the build.**

---

## 1. Institutional context verified

### 1.1 Greps run and results

| Search | Surfaces | Result |
|---|---|---|
| `SIGNAL_PERSON_ARRIVING` producers | whole package | `presence.py` `_handle_geofence_change` (geofence, `:5222-5253`), `person_coordinator.py:1100-1136` (ble, needs LOST ≥ `_min_away_minutes`), `presence.py` `_handle_face_arrival` (camera_face). Consumers: `hvac.py:1511` → `_handle_person_arriving` (`:7212`), `security.py:815` → `_handle_person_arriving_signal` (`:2348`), which feeds `security_lock_regime.on_person_arriving` (`:975`, P2 lock RELEASE) above its own gates |
| `pre_arrival_sources` / `CONF_PRE_ARRIVAL_SOURCES` | `hvac_const.py:349-350`, `hvac.py:881`, `:1431-1440`, `:7221`, `:8455`; `config_flow.py:7861`, `:8370-8380` | REUSED. Source filter; options geofence / ble / camera_face. Live CM value `['geofence','ble','camera_face']` (stored, so a new default does not reach this install; §6) |
| approach zone / proximity | `security_lock_regime.py` `_is_approach_zone` (`:1266`), `_on_distance_event` (`:1309-1328`), `distance_to_metres` (`:105-121`); `const.py:3731-3741` `CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS`, `CONF_SECURITY_LOCKOUT_APPROACH_ZONE`, `CONF_GARAGE_LOCKOUT_APPROACH_RADIUS_M` / `GARAGE_LOCKOUT_APPROACH_RADIUS_M = 1500`; `config_flow.py:9105-9210` | Prior art exists. Verdicts per piece in §1.6. Not fed into `SIGNAL_PERSON_ARRIVING`; it is the lock regime's own release path |
| HA proximity entry | live HA | EXISTS: `sensor.madronehaos_{oji_udezue,ezinne,jaya}_distance` + `_direction_of_travel` (created for the garage lockout, `PLANNING_sc_garage_remote_lockout.md` Q-A2 / rev 3). No Ziri sensor seen. Jaya's reads `unknown` (no GPS) |
| HA zones | live HA (`ha_get_zone`) | Only `zone.home` (yaml, lat 30.314635 / lon -98.015861, radius 150 m, non-passive). The `zone.home_approach` (1500 m, passive) that the garage plan said would be created at its D0 does NOT exist live. No near-home zone exists |
| `near_home` / `near home` / `NEAR_HOME` | `const.py`, `hvac_const.py`, `config_flow.py`, entity platforms, `domain_coordinators/*`, `docs/planning/*`, memory bodies | Nothing (only the card and kanban renders) |
| `gps_accuracy` constants | `const.py`, `person_coordinator.py`, `domain_coordinators/*` | None. NEW knob needed (§6) |
| raw `person.state` `"not_home"` / `"home"` readers | whole package | `arrival_edges.py:39` (`old == "not_home"` exactly), `transit_validator.py:1847`, `camera_census.py:4518`, `camera_census.py:6119`, `security_lock_regime.py:1155/1682/1881` + the away lock "exactly `not_home`", `presence.py` `_handle_geofence_change` departure branch (`new == "not_home" and old == "home"`), `person_coordinator.py:920-926`, `house_status.py:242`, plus the `person_state_for_trust` readers. These are why the zone must be passive (§2.1) |

### 1.2 HA source read (pinned HA 2026.2 in `.venv-ha`)
- `homeassistant/components/zone/__init__.py` `async_active_zone` (`:117-170`): **passive zones are skipped** when a tracker's zone is resolved, so a passive zone never becomes a device tracker's or a person's state. Among non-passive zones containing the point, the closest centre wins, ties to the smaller radius.
- Same file, `Zone._state_is_in_zone` (`:439-452`): a zone entity counts a person only when `person.state` equals the zone name. So a **passive zone's own state is always 0**: it carries geometry, not a signal. URA must test the geometry itself.
- `in_zone(zone_state, latitude, longitude, radius)` (`:197`): HA's own point-in-zone test. REUSED for the inside test.
- `homeassistant/components/person/__init__.py` `_update_state` (`:516-560`): with no non-GPS tracker reading `home`, the person's `source`, `latitude`, `longitude`, `gps_accuracy` come from the most recent GPS tracker. With no GPS tracker the coordinates come from a non-GPS tracker (usually none). So the person entity carries a GPS fix only when its `source` tracker has `source_type gps`; the detector checks that (§2.3).

### 1.3 Prior planning docs consulted
- `PLANNING_sc_garage_remote_lockout.md` (full read of the approach / P5 / D0 sections, `:52`, `:65`, `:128`, `:166`, `:319`, `:372`, `:428`, `:584`): the approach zone was demoted to optional because a passive zone gives no recorder signal; the proximity distance sensors carry "within 1.5 km"; D0 there recomputed distance offline from tracker lat/lon. This plan reuses that D0 method (§5 D0).
- `PLANNING_hvac_w1_w2_finish.md` (pre-arrival lifetime, D-L5 spent episode, Q7 arrival reference, knob 35): the interaction rules in §4.
- `PLANNING_hvac_fast_occupancy_response.md` (D2 fast path; pre-arrival is a separate decision trigger): unchanged.
- `PLANNING_sc_lock_exclude_and_door_regime.md` (away lock reads exactly `not_home`): one of the reasons for passive.
- Skimmed by filename + grep hit for pre-arrival: `PLANNING_hc_precool_toggle_oc_observability.md`, `PLANNING_egress_identity_producer.md`, `PLANNING_hvac_guest_as_zone_person.md`. No near-home or approach design.

### 1.4 Memory bodies pulled
- `feedback_marginal_benefit_pushback.md`, `feedback_measure_before_build.md`, `feedback_config_first_before_code.md`, `feedback_portability_imperative.md` (derive from HA config, never a hard-coded entity), `reference_hvac_state_of_play.md`, `reference_presence_state_of_play.md`, `project_operator_nz_travel_2026_11.md` (Oji abroad ~11-09 → 11-16: his recent recorder history has no arrivals; affects D0 sample).
- Kanban cards: PREARRIVAL-NEAR-HOME-ZONE-1, PERSON-OJI-HOME-FLAP-1 (iPad removed from `person.oji_udezue` 11-11; a flapping person entity would also flap coordinates: covered by the edge rule, §2.3), EGRESS-BLE-ARRIVAL-LATENCY-1 (adjacent: BLE arrival latency; not in scope).

### 1.5 Code locations surveyed (read end to end for the touched region)
`hvac.py` `_handle_person_arriving` + `_spend_pre_arrival_episode` (`:7211-7313`), `_expire_pre_arrival_zones` (`:7414-7491`), `_async_end_pre_arrival_borrows` (`:7493-7540`), pre-arrival init (`:807-881`, `:1408-1440`, `:1505-1515`); `presence.py` `_subscribe_geofence` / `_handle_geofence_change` (`:5187-5253`), `handle_geofence_event` (`:9412-9428`); `person_coordinator.py:1095-1140`; `security_lock_regime.py:95-130`, `:975-1005`, `:1100-1145`, `:1266-1330`; `security.py:2345-2360`; `arrival_edges.py:30-45`; `config_flow.py:8360-8385`, `:9180-9215`.

### 1.6 Prior-art scan: REUSE or BUILD per piece

| Piece | Verdict | Existing symbol |
|---|---|---|
| Pre-arrival consumer (zones, D-L5 spent episode, window, activity row, decision kick) | **REUSE unchanged** | `HVACCoordinator._handle_person_arriving` `hvac.py:7212`. The new path calls it with `{"person_entity": ..., "source": "near_home"}`; no edit to its body |
| Source filter | **REUSE + extend options** | `CONF_PRE_ARRIVAL_SOURCES` `hvac_const.py:349`; add option value `near_home` to the selector `config_flow.py:8370-8380` and to `DEFAULT_PRE_ARRIVAL_SOURCES` |
| Person → HVAC zone map | **REUSE** | `HVACCoordinator._person_zone_map` (`hvac.py:807`, rebuilt `:1408-1411`) |
| Zone geometry | **REUSE** HA | operator-created passive zone; HA `zone.in_zone` (`zone/__init__.py:197`) |
| Zone selector in config | **REUSE pattern, NEW key** | Selector pattern `EntitySelectorConfig(domain="zone")` from `config_flow.py:9207-9210`. Key `CONF_SECURITY_LOCKOUT_APPROACH_ZONE` NOT reused: it is a lock-RELEASE input that needs a non-passive zone; sharing one key would couple a security release to an HVAC comfort hint, and the two need opposite zone types |
| Crossing edge (outside → inside, first reading only seeds) | **REUSE shape, BUILD ~20 lines** | Same rule as `security_lock_regime._on_distance_event` (`:1318-1328`: `prev is None → no fire`, fire on `prev > R and cur <= R`). Not imported: that method is bound to lock state and resident filters. A helper of its own in HVAC |
| Proximity distance sensors as the signal | **NOT REUSED (rejected, §2.2)** | `sensor.madronehaos_<person>_distance` |
| Person state listener | **BUILD (HVAC-owned)** | Presence's `_subscribe_geofence` listener is NOT reused, because putting the detector in presence would need a new dispatcher signal and a second home for an HVAC-only input. HVAC registers `async_track_state_change_event` on the `person.*` keys of `_person_zone_map` |
| Observation-mode gate | **REUSE read pattern** | Producer-side presence observation gate as in `person_coordinator.py:1111-1124` |
| Distance/unit conversion | **not needed** | `in_zone` and `homeassistant.util.location.distance` work in metres; the lock's `distance_to_metres` is for proximity sensors |

---

## 2. Design decisions

### 2.1 Zone source: an operator-created PASSIVE HA zone, selected in config
- **Why an HA zone at all (vs a radius number):** the operator picked "a near-home zone"; a zone is visible and editable on the HA map, and it lets the area be off-centre (along the usual approach road). Portable: any install creates its own (§ portability memory).
- **Why passive (mandatory):** a non-passive zone becomes `person.state` while the person is inside it. That would move every raw `person.state` reader in §1.1: the presence departure branch (`home → near_home` is not `not_home`, so `geofence_leave` would not run), `arrival_edges.live_arrival_slug` (`near_home → home` is not a `not_home → home` edge, so face corroboration and perimeter D10.5 lose GPS arrivals), the SC away lock (exactly `not_home` ≥ 300 s), `transit_validator:1847`, `camera_census:4518`. A passive zone changes no state anywhere. The config step REJECTS a non-passive zone and `zone.home` (error text: "Pick a passive zone. Open Settings → Areas & zones, edit the zone and turn on Passive.").
- **Why not URA-created:** URA would own a zone's lifecycle (create, update, delete on unload) for one radius; the operator can draw it in HA in a minute. Rejected on marginal benefit.
- **Live config step (operator, not code):** create `zone.near_home` (name free), passive, centre near home, radius sized by D0; select it in the HVAC pre-arrival options; tick `near_home` in pre-arrival sources.

### 2.2 Why not the HA proximity sensors (marginal-benefit pushback)
The proximity entry already gives `distance` and `direction_of_travel` per GPS person. It is a real candidate. Rejected for this cycle because: it requires a proximity entry and a per-person sensor list (two more configured objects per install, sensor→person mapping by name suffix, as `security_lock_regime._person_for_sensor` does); its distance is to the proximity's own zone, so it cannot express an off-centre near-home area; and it is computed from the same GPS fixes, so it is never earlier. The passive zone needs one option. Revival trigger: if a later cycle wants direction-of-travel filtering (§2.4), proximity is where that data lives.

### 2.3 Trigger semantics
Evaluated on every `state_changed` event of a mapped `person.*` (HA writes the person on every tracker update, so attribute-only GPS updates arrive as events):
1. **Usable fix:** `new_state` readable; its `source` attribute names a tracker whose `source_type` is `gps`; `latitude` / `longitude` numeric; `gps_accuracy` ≤ `NEAR_HOME_MAX_GPS_ACCURACY_M` (0 = no accuracy check). Otherwise the event is ignored (no seed, no fire).
2. **Classify:** `inside` = `zone.in_zone(near_zone, lat, lon, 0)`; `outside` = haversine distance from the zone centre > radius + `NEAR_HOME_EXIT_HYSTERESIS_M`; else `band` (keeps the previous classification).
3. **Home resets to inside:** if `new_state.state == "home"`, the person's memory is set to `inside` and nothing fires. So a person leaving home is already "inside" and the first fix past the zone edge is not a crossing in.
4. **Fire** iff the previous classification for this person is `outside` AND this fix is `inside` AND `new_state.state != "home"`. Then set memory `inside` and call `_handle_person_arriving({"person_entity": pid, "source": "near_home"})` (unless presence observation mode is on: INFO line instead, same as the BLE producer).
5. **Seed:** no previous classification (boot, reload, option change, first fix) → store this one, never fire. `old_state is None` (person restore) → seed only.
6. Memory is RAM-only, per person; cleared on teardown and when the zone option changes. Not persisted: after a restart the first fix seeds (a restart during the approach loses that one early trigger; geofence still fires).

### 2.4 Direction / speed: not built (pushback)
The crossing edge already encodes "travelling toward home": outside → inside. Speed or heading filters would add a second noisy GPS-derived input and new knobs to filter the residual case (a drive-by, or a visit to a neighbour inside the zone). That residual costs one pre-cool of at most the pre-arrival window (live knob 35 = 20 min), ended by `timeout` with no spend (§4). D0 measures the drive-by rate; if it is material, revisit with proximity `direction_of_travel` (parked, §8).

### 2.5 Lock release and other consumers: NOT fed (security)
`near_home` is never dispatched on `SIGNAL_PERSON_ARRIVING`. That signal also reaches `security._handle_person_arriving_signal` → `security_lock_regime.on_person_arriving` (P2 garage/away-lock RELEASE for any non-face source after the really-away gate) and the "add expected arrival" path. A 1-2 km comfort hint must not unlock a house. The near-home detector lives in HVAC and calls HVAC's handler directly, so no other consumer can see it by construction (INV-NH-1). If the operator ever wants it for locks, that is a separate security plan.

### 2.6 Scope
House scope (one near-home zone per install), HVAC consumer only, person granularity, fans out to HVAC zones through `_person_zone_map` exactly like the other sources.

---

## 3. Falsifiable invariants

- **INV-NH-1 (isolation).** A `near_home` trigger can never reach any consumer other than `HVACCoordinator._handle_person_arriving` in any reachable path: it is never sent on `SIGNAL_PERSON_ARRIVING` or any other dispatcher signal, never changes a `person.*` / zone state, and never releases a lock. *Break it by:* finding a code path from the detector to `async_dispatcher_send`, to `security*`, or a config where the selected zone changes `person.state` (a non-passive zone accepted by the options step, or a zone switched to non-passive later in HA; see D2's runtime re-check).
- **INV-NH-2 (byte-identical off).** With the zone option empty, the zone missing / non-passive / unavailable, or `near_home` absent from `pre_arrival_sources`, HVAC pre-arrival behaviour, every activity row and every `person.*` reader is identical to today, and no `person.*` listener is registered by HVAC. *Break it by:* any extra row, listener, decision cycle or state write in those configs.
- **INV-NH-3 (no departure fire).** A person who leaves home and drives away never produces a `near_home` trigger before a later usable fix classified `outside` (beyond radius + hysteresis). *Break it by:* a fix sequence home → inside → band → inside, or a restart while inside, that fires.
- **INV-NH-4 (episode rules unchanged).** A `near_home` trigger obeys the existing D-L5 spent-episode rule, the knob-35 window and the source filter exactly as a `geofence` trigger does, because it enters through the same handler with no edit to it. *Break it by:* a diff to `_handle_person_arriving`, `_spend_pre_arrival_episode` or `_expire_pre_arrival_zones`.

---

## 4. Interaction with the existing pre-arrival lifecycle (read from code, no change)
- **Normal arrival:** near_home at T opens the episode (`_pre_arrival_zones`, `_pre_arrival_start = T`, decision kick → S12 pre-cool begins per the existing rules). The geofence at T + a few min is a repeat trigger: not spent, so it re-sets `_pre_arrival_start` (`hvac.py:7246-7249`). HVAC arrival in the zone clears it (`arrived`, `:7466-7475`) and ends the borrow (`pre_arrival_arrived`).
- **Drive-by / neighbour visit:** no arrival → `timeout` after the window (`:7477-7486`), fans off, borrow ends `pre_arrival_timeout`. **Timeout does not spend the episode**, so a real arrival later still triggers.
- **Spent episode (D-L5):** if the episode was spent (max age, person interrupt, master off), a `near_home` repeat inside the window only extends the spent time and logs "already ended", exactly as geofence does. Accepted: same rule, same reason.
- **Max age:** the pre-cool borrow's max age is the window (`_async_end_pre_arrival_borrows` passes `_pre_arrival_window_s()`); a near-home lead of minutes is far inside 20 min. If D0 shows typical near-home → home gaps approaching the window, the radius is too large; that is a D0 sizing output, not a code change.
- **Q7 arrival reference, interrupt latch, S12/S13 gates:** unchanged; they key on the zone's pre-arrival borrow, not on the source.

---

## 5. Deliverables

### D0 — Measure first: near-home lead and false-crossing probe (read-only, GO/NO-GO gate)
One-shot script `scripts/probes/near_home_lead_probe.py`, run over SSH against the HA recorder (`ssh ha "python3 -" < script`), read-only. Method as the garage plan's D0: recompute distance offline from GPS coordinates.
- Inputs: `person.oji_udezue`, `person.ezinne` latitude / longitude / gps_accuracy / source history and their GPS trackers (`device_tracker.phalanxiphone15promaxcflare`, `device_tracker.zinny_s_iphone_15`) over the whole recorder retention (expect ~7-10 days; Oji abroad since ~11-09, so his sample is pre-trip only). `zone.home` centre from config. Cross-check against `sensor.madronehaos_*_distance` history (exists since ~11-07) for the same instants.
- Outputs per person and per candidate radius R ∈ {400, 600, 800, 1000, 1500, 2000, 3000} m, centred on home: (a) arrivals (live `not_home → home` edges, excluding the PERSON-OJI-HOME-FLAP-1 same-second flaps); (b) lead = home edge − first usable fix inside R that follows a fix outside R + 100 m, using the §2.3 rule exactly; (c) arrivals with NO fix inside R before the home edge (the phone did not report in time: lead 0); (d) false crossings = crossings in not followed by `home` within 20 min (knob 35 live); (e) GPS fix cadence (seconds between fixes) inside 3 km; (f) accuracy distribution.
- Report goes in this doc (§10, appended) as a table.
- **GO** for a radius R if: median lead ≥ 2 min over the geofence across arrivals with a fix, AND at least half of arrivals get a non-zero lead, AND false crossings ≤ 2 per person per week. **NO-GO** (park the card with this data) if no R meets it, most likely because the iPhone does not report between significant-location updates outside its monitored regions.
- **What D0 cannot measure:** whether the iOS Companion app adds region monitoring for a passive zone (would give more timely fixes than the replay shows). UNVERIFIED; the replay is therefore a LOWER bound for the passive design. If D0 is borderline, an operator test (create the passive zone, drive in once, check the tracker's update time vs the crossing) settles it before build.

**Acceptance**
- **Verify:** report table present with n arrivals per person and the GO/NO-GO verdict per R; the chosen R recorded.
- **Discriminates:** under "near-home works" the lead column is minutes and (c) is a minority; under "phone does not report early" (c) dominates and lead is ~0 for every R. Different tables, different verdicts.
- **Test:** none (probe).
- **Live:** n/a.

### D1 — Config: zone option + `near_home` source value (rung 2)
- `hvac_const.py`: `CONF_PRE_ARRIVAL_NEAR_HOME_ZONE = "pre_arrival_near_home_zone"` (default empty = feature off); `"near_home"` appended to `DEFAULT_PRE_ARRIVAL_SOURCES`.
- `config_flow.py` HVAC options step (`:8370` block): option `{"label": "Near home zone (phone GPS)", "value": "near_home"}`; next to it `vol.Optional(CONF_PRE_ARRIVAL_NEAR_HOME_ZONE)` with `EntitySelectorConfig(domain="zone")` (suggested_value pattern of `:9207`). Validation: empty OK; `zone.home` rejected; a zone whose state attributes lack `passive: true` rejected (`error: near_home_zone_not_passive`); missing entity rejected.
- `strings.json` / `translations/en.json`: label "Near home zone"; help: "A passive zone around home. When a phone's GPS enters it from outside, URA starts pre-cooling early. Only people with phone GPS (not BLE-only trackers). Leave empty to turn off." Label style per `feedback_label_style_guide`.
- Reload-suppression: confirm whether the CM options writeback for this key triggers a reload; follow the existing `pre_arrival_sources` handling (the builder verifies at `hvac.py:1431-1440` how the source list is re-read and does the same).

**Acceptance**
- **Verify:** options round-trip: set, reopen, value kept; empty clears.
- **Verify:** non-passive zone and `zone.home` are refused with the error; a passive zone is accepted.
- **Test:** `test_prearrival_near_home_config.py::test_rejects_non_passive_zone`, `::test_rejects_zone_home`, `::test_accepts_passive_zone`, `::test_default_sources_include_near_home`.
- **Live:** options form shows the field and the new source; `sensor`/diagnostics attr `pre_arrival_sources` lists what is stored.

### D2 — HVAC near-home detector (BUILD, ~80-120 lines in `hvac.py` or a small `hvac_near_home.py`)
- Listener: `async_track_state_change_event` on the `person.*` keys of `_person_zone_map`, registered only when the zone option is set AND `near_home` is in `_pre_arrival_sources`; re-registered when the person map changes (`:1408-1411`) or the options change; unsubscribed at teardown (`_unsub_listeners` / `async_on_unload` pattern the coordinator already uses; the builder cites the exact list).
- Handler: §2.3 steps 1-6. Runtime zone check on every fire: zone state missing, unavailable, or `passive` not true → no fire, one WARNING per (zone, reason) per boot, memory cleared (INV-NH-1 holds even if the operator later flips the zone to non-passive in HA).
- On fire: presence observation mode → INFO "near-home pre-arrival would fire for %s" only; else `self._handle_person_arriving({"person_entity": pid, "source": "near_home"})` (synchronous `@callback`, same as the dispatcher would call it).
- Diagnostics (display): add `near_home_zone`, `near_home_last` (`{person, at, distance_m}`) and `near_home_fires_today` to the existing pre-arrival diagnostic attrs (`hvac.py:8455` neighbourhood); mark them unrecorded if that sensor has an `_unrecorded_attributes` set (builder checks).
- No new DB table, no new signal, no persisted state.

**Acceptance**
- **Verify:** fix sequence outside(2 km) → inside(500 m, not home) fires once with `source=near_home`; the activity row `hvac` `pre_arrival` carries `source: near_home`.
- **Verify:** home → inside → inside → band (no outside) never fires (INV-NH-3); outside → band → inside fires; restart while inside → first fix seeds, no fire.
- **Verify:** `gps_accuracy` above the knob, non-GPS `source`, missing coordinates → ignored (no seed change).
- **Verify:** zone option empty, or `near_home` not in sources → no listener registered, zero calls (INV-NH-2).
- **Verify:** zone flipped to non-passive / deleted at runtime → no fire + one WARNING.
- **Verify:** no `async_dispatcher_send` reachable from the detector; `security_lock_regime` receives nothing (INV-NH-1).
- **Discriminates:** a fire caused by geofence carries `source: geofence` and arrives at the home edge; a near-home fire carries `source: near_home` and precedes the geofence row for the same person by minutes. If the detector were wrongly firing on departure, rows with `source: near_home` would follow a `not_home` edge by seconds and no `home` edge would follow within the window.
- **Test:** `test_prearrival_near_home.py::test_outside_to_inside_fires_once`, `::test_departure_never_fires`, `::test_band_hysteresis`, `::test_seed_after_restart_no_fire`, `::test_bad_accuracy_ignored`, `::test_non_gps_source_ignored`, `::test_off_registers_no_listener`, `::test_runtime_non_passive_zone_stands_down`, `::test_observation_mode_logs_only`, `::test_lock_regime_not_called` (real `SecurityLockRegime` wired, asserts no release), `::test_spent_episode_rule_applies` (drives the real `_handle_person_arriving`, not a stub). Tests drive the production handler with HA `State` objects; the zone `State` is built with the HA attribute names (`latitude`, `longitude`, `radius`, `passive`).
- **Live:** see D4.

### D3 — Docs in the same commit as the build
- `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §2 trigger table: pre-arrival row gains the `near_home` source (HVAC-owned person listener, passive zone, not on `SIGNAL_PERSON_ARRIVING`).
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 consumer table: `person.*` latitude / longitude / `source` read by HVAC near-home (comfort trust only, never a release); plus the approach-zone note from the header of this plan (the lock's approach zone works only when non-passive; live value `zone.home` is inert).
- README for the release with the Jaya/Ziri limitation stated.

**Acceptance:** **Verify:** both docs updated in the build commit; reviewers check the §1 table row exists.

### D4 — Live validation (post-deploy, after the operator creates the zone)
- **Live:** `zone.<near_home>` exists with `passive: true`; CM options show it selected and `near_home` ticked.
- **Live:** for the next GPS-person arrival: one `ura_activity_log` `hvac` `pre_arrival` row with `details.source == "near_home"` BEFORE the `geofence` row for the same person; the gap is in the D0-predicted range. Proven by one DB query (`SELECT timestamp, details FROM ura_activity_log WHERE coordinator='hvac' AND action='pre_arrival' ORDER BY timestamp DESC LIMIT 20`).
- **Live:** for the next departure of a GPS person: no `near_home` row within 30 min after the `not_home` edge.
- **Live:** `person.oji_udezue` / `person.ezinne` states never read the near-home zone name (passive), checked in recorder for the validation window.
- **Live:** no `lock_regime` release with a near-home cause (there is no such trigger string; check SC lock activity rows show only existing causes).
- Trip-wire (no soak): none needed beyond the existing pre-arrival counters; the discriminator is binary on the first arrival and the first departure. If no GPS-person arrival happens within the disposal window, dispose by D0 data + in-suite proof and say so in the README.

---

## 6. Knobs (numbers get knobs)

| Name | Rung | Default | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `CONF_PRE_ARRIVAL_NEAR_HOME_ZONE` | 2 (CM options, HVAC step) | empty | per-install structure (which zone) | empty = feature off, no listener |
| `near_home` in `CONF_PRE_ARRIVAL_SOURCES` | 2 (existing field) | in default list; live install must tick it (stored list) | same field as the other sources | unticked = off, zone kept |
| Zone radius / centre | HA zone itself | sized by D0 | operator edits on the HA map; no URA number | — |
| `NEAR_HOME_EXIT_HYSTERESIS_M` | 1 (`hvac_const.py`) | 100 | GPS-noise guard; changing it should be reviewed against D0 jitter | 0 = no hysteresis (edge at the radius) |
| `NEAR_HOME_MAX_GPS_ACCURACY_M` | 1 (`hvac_const.py`) | 250 (D0 may adjust from the accuracy distribution) | sanity bound on fixes, not policy | 0 = accept any accuracy |

The pre-arrival window (knob 35, live 20 min) is reused, not duplicated.

---

## 7. Producer and consumer checks

**Value 1: the near-home trigger.**
- *Producer:* GPS fix on the person entity (`person/__init__.py:562-571`), which is the latest GPS tracker's coordinates when no non-GPS tracker reads `home`. Dependencies and their health today: the iPhone companion app fix cadence (UNKNOWN between monitored regions; D0 measures); `gps_accuracy` (live 11-37 m on the two GPS trackers, 2026-11-11); the person tracker list (Oji's trimmed 11-11 to iPhone app + Bermuda + private BLE, so the iPad no longer supplies coordinates: good for this feature); the zone (operator-created). Ground truth for D0 is the person's own later `home` edge, not another URA number.
- *Consumers:* exactly one, `HVACCoordinator._handle_person_arriving` (`hvac.py:7212`), a trust decision (starts a pre-arrival episode, pre-cool borrow S12, pre-arrival fans). Display: the activity row and diagnostics attrs.

**Value 2: `source == "near_home"` string.**
- *Producer:* D2 only. *Consumers:* the source filter (`hvac.py:7221`), the activity row details, `_last_pre_arrival_source` (diagnostics). Grep for any other reader of the payload `source` key under HVAC before build (builder re-runs `grep -n '"source"' hvac*.py`).

**Unchanged readers checked:** every raw `person.state` reader in §1.1 sees no change because the zone is passive (HA skips passive zones in `async_active_zone`).

---

## 8. Emission / decision-site enumeration
Sites a `near_home` value can flow through, re-run by the plan reviewer:
1. D2 handler → `_handle_person_arriving` (the only call).
2. Inside `_handle_person_arriving`: source filter `:7221`, D-L5 branch `:7238-7245`, zone set `:7247-7249`, activity log `:7258-7268`, diagnostics `:7271-7274`, decision kick `:7277-7281`. All existing, source-agnostic except the filter.
3. NOT reached: `SIGNAL_PERSON_ARRIVING` consumers (`security.py:815`, `security_lock_regime.on_person_arriving`), presence `handle_geofence_event`, `arrival_edges`, perimeter D10.5, census. Verified by construction (no dispatcher call) and by `test_lock_regime_not_called`.
4. Other pre-arrival producers (`presence.py` geofence / face, `person_coordinator.py` BLE) unchanged.

---

## 9. Tier classification
**Tier 2.** Trigger: a new input to an HVAC trust decision (pre-arrival → pre-cool borrow), new config field + listener, additive behind an empty default, no edit to the shared pre-arrival handler, no DB, no new signal. Not Tier 3: no value threaded through many emission sites (one call site), not cost-and-safety (a false fire costs at most one 20-min pre-cool). Not elevated to 2-DB: no house-state, lock or cross-coordinator write; the lock regime is isolated by construction (INV-NH-1). **If the builder finds it must edit `_handle_person_arriving` or the pre-arrival lifecycle, stop and re-tier to 2-DB.**
- Plan review: ONE adversarial plan review before build (operator dispatches).
- Build reviews: A = correctness + edge cases (fix classification, hysteresis, seed, accuracy, zone validation, departure); B = lifecycle + async (listener registration / re-registration on person-map and options change, teardown, restart, observation mode, runtime zone flips, INV-NH-1 isolation).
- Live validation D4; README write-back.

---

## 10. Non-goals
- Enlarging `zone.home` or changing what `home` means for anyone (operator chose A).
- Feeding near-home into the garage lockout / away lock / security expected-arrival (§2.5). Separate security plan if ever wanted.
- Anything for BLE-only people (Jaya, Ziri). EGRESS-BLE-ARRIVAL-LATENCY-1 owns BLE arrival speed.
- Direction-of-travel, speed or ETA filtering; route learning; per-person zones (§2.4).
- Changing the pre-arrival window, D-L5, Q7, pre-cool offset or S12/S13 rules.
- URA creating or managing the HA zone.
- Using the HA proximity entry (§2.2).
- Persisting crossing memory across restarts.
- Fixing PERSON-OJI-HOME-FLAP-1 (separate card; the edge rule already ignores same-position flaps because home resets memory to inside).

## 11. Parked (with revival triggers)
- **Direction-of-travel filter via proximity `direction_of_travel`.** Revive if D0 or D4 shows > 2 false crossings per person per week.
- **Feed near-home to the SC lock regime as an early garage release.** Revive only on an operator ask; needs its own security plan and the lock's really-away gate.
- **Non-passive approach zone for the lock (`CONF_SECURITY_LOCKOUT_APPROACH_ZONE`).** Not touched; its live value `zone.home` is inert. Card at build time if the operator wants it cleared or repurposed.

## 12. D0 report
_(to be appended by D0)_
