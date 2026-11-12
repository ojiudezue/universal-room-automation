# PLANNING — BLE "seen at home" arrival (EGRESS-BLE-ARRIVAL-LATENCY-1)

**Status:** plan, recommendation **DO NOT BUILD (DROP the build; close the card on evidence)**. Tier 2 as briefed; see §8.
**Author:** ura-planner, 2026-11-12. Base: `develop` @ e698e535.
**Card:** EGRESS-BLE-ARRIVAL-LATENCY-1 (finding_2026_11_12, refinement_2026_11_12, operator_decision_2026_11_12 read in full).

**Read-first compliance.** I read `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md` and `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` completely before scoping. This plan re-asserts nothing from the presence §10 corrections ledger. No code-vs-doc contradiction was found that this plan depends on. One doc gap is fixed by D1 below: neither doc says that the geofence arrival path is the BLE-seen arrival.

---

## 0. Headline: the faster arrival already exists

The operator approved "arrival fires when the phone is SEEN at home by any BLE scanner, without waiting for room resolution or the 30 s poll". That signal already ships, under `source="geofence"`:

1. **HA `person` gives a non-GPS `home` precedence.** `homeassistant/components/person/__init__.py:516-547` (HA 2026.2.3 in `.venv-ha`): any tracker whose `source_type` is not GPS and whose state is `home` sets `latest_non_gps_home`, and that wins over GPS (`:532-533`). Verified against the source, not recalled.
2. **Every resident's `person.*` includes a `bluetooth_le` Bermuda tracker** (live read, 2026-11-12):
   - `person.jaya`: `private_ble_device_249050`, `iphone_jaya_bermuda_tracker`
   - `person.ezinne`: `ezinne_iphone`, `ezinne_iphone_bermuda_tracker`, `zinny_s_iphone_15`
   - `person.ziri`: `ziri_iphone`, `iphone_ziri_bermuda_tracker`
   - `person.oji_udezue`: phone app, `iphone_oji_bermuda_tracker`, `private_ble_device_8ce182`

   `source_type: bluetooth_le` was confirmed live on the Jaya and Ezinne Bermuda trackers and on `private_ble_device_249050`. So the first scanner that hears a resident's phone flips `person.<x>` to `home`.
3. **Presence dispatches an arrival on that edge, ungated.** `presence.py:5259-5299` `_handle_geofence_change` sends `SIGNAL_PERSON_ARRIVING {"source": "geofence"}` on any `person.*` change from non-home to `home`. No was-away gate, no poll, no room needed.
4. **Measured, live `ura_activity_log` (HVAC handler rows, written after its source filter):**

| Arrival (card t0) | `geofence` row | `ble` row | BLE lag behind geofence |
|---|---|---|---|
| Jaya 22:29:58.8 | 22:29:58.77 | 22:30:33.47 | +34.7 s |
| Ezinne 22:30:01.2 | 22:30:01.23 | 22:30:33.46 | +32.2 s |
| Ezinne 23:32:21.7 | 23:32:21.71 | 23:32:33.46 | +11.8 s |
| Jaya 01:10:55.1 | 01:10:55.09 | 01:11:03.47 | +8.4 s |
| Ezinne 01:10:52.3 | 01:10:52.31 | 01:11:33.46 | +41.2 s |

The geofence row matches the card's t0 to the millisecond. The card's "8-41 s" is the lag of a **second, redundant** arrival (`source=ble`) behind an arrival every consumer already received at t0. The same pattern holds on 11-10, 11-11 and 11-12 14:33.

**Consequence:** building the approved detector would give no consumer an earlier arrival on this install. It would add a third writer to a cross-coordinator signal that releases locks, plus a new state listener on PersonCoordinator, for no measured benefit. Under the marginal-benefit duty I recommend not building it. The rest of this doc is the context-wide inventory the operator asked for, so the "no regression" question is answered on the record. A parked design is in §9 in case the revival trigger ever fires.

---

## 1. Institutional context verified

**Docs read in full:** the three read-first docs above. Card read in full.

**Prior-art scan, REUSE-or-BUILD for each piece the approved design would need:**

| Piece | Verdict | Existing symbol |
|---|---|---|
| "Phone seen at home" event source | **REUSED (already live)** | HA `person` non-GPS-home precedence + `presence._handle_geofence_change` (`presence.py:5259`) |
| Event-driven listener on person / tracker state | REUSED | `_track_geofence_persons` (`presence.py:5233`, `async_track_state_change_event`), plus late-person pickup through `async_track_state_added_domain` (`:5227`) |
| BLE tracker home/away transition listeners | REUSED (exit side) | `camera_census._register_ble_transition_listeners` (`camera_census.py:5139`), used for exit backfill (manual §4.3a) |
| Was-away / min-away refractory | REUSED | `PersonCoordinator._person_was_away` + `_min_away_minutes` (`person_coordinator.py:200, 1104-1159, 755-765`); lock regime `_really_away` (`security_lock_regime.py:1145`) |
| Fleet liveness gate | REUSED | `BLE_FLEET_LIVENESS_WINDOW_S` (`person_coordinator.py:67`), Active Proxy Count fleet floor (presence doc §3) |
| Arrival-edge TTL cache | REUSED | `arrival_edges.py` (`live_arrival_slug`, `record_bermuda_moves`, `nonface_arrival_source`) |
| HVAC repeat-arrival dedup | REUSED | `_pre_arrival_spent` (`hvac.py:7238-7246`) |
| New CONF / const / sensor | **NONE proposed** | nothing to add |

**Greps run** (on `custom_components/universal_room_automation`): `SIGNAL_PERSON_ARRIVING|ura_person_arriving|"pre_arrival"|_person_was_away|_register_ble_transition_listeners|UPDATE_INTERVAL`, `async_add_listener(`, `ura_person_location_change`, `_pre_arrival_sources|CONF_PRE_ARRIVAL_SOURCES|CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED|add_expected_arrival`. Results feed §2-§3.

**Memory consulted:** `feedback_marginal_benefit_pushback`, `feedback_config_first_before_code`, `feedback_extend_existing_never_rebuild`, `feedback_tier2plus_prior_art_scan`, `feedback_portability_imperative`, `reference_presence_state_of_play`, `feedback_ble_config_is_tuned_check_before_asserting`.

---

## 2. PRODUCER inventory: every arrival / away→present producer

| # | Producer | file:line | Trigger | Gate | Latency vs first BLE hearing |
|---|---|---|---|---|---|
| P-A | `SIGNAL_PERSON_ARRIVING(source=geofence)` | `presence.py:5281-5299` | **event**: `person.*` changes from non-home to `home` | observation mode only; skips `old_state None` (`:5270`) and unavailable/unknown new states | **~0 s** (HA person follows the BLE tracker) |
| P-B | `SIGNAL_PERSON_ARRIVING(source=ble)` | `person_coordinator.py:1101-1138` | **polled**, 30 s (`const.py:55`, `person_coordinator.py:163`) | `_person_was_away` (needs ≥ `_min_away_minutes` LOST/away), a resolved room, `_pre_arrival_enabled`, presence observation mode | Bermuda room resolution (5-15 s) + 0-30 s grid; measured 8-41 s **after P-A** |
| P-C | `SIGNAL_PERSON_ARRIVING(source=camera_face)` | `presence.py:5600-5640` (`_handle_face_arrival`) | event, face on any zone camera | 60 s debounce; no was-away gate; `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` False | n/a (camera) |
| P-D | `person.*` raw state edges | HA core | event | none | ~0 s |
| P-E | `ura_person_location_change` bus event + `person_visits` rows | `person_coordinator.py:1044-1066` | polled 30 s, on resolved-room change | none | room resolution + poll |
| P-F | PersonCoordinator `data[...]` (`location`, `previous_location`, `method`) | `person_coordinator.py:1080-1094` | polled 30 s | none | same as P-E |
| P-G | Presence `handle_geofence_event` → house-state ARRIVING path | `presence.py:5282` | event (same edge as P-A) | inference engine | ~0 s |
| P-H | Lock regime P5 proximity crossing | `security_lock_regime` (presence doc §1) | event on HA proximity | radius crossing | GPS-driven, before BLE |

There is no separate security geofence producer. Security consumes P-A, P-B and P-C through the signal.

---

## 3. CONSUMER inventory, with what an earlier, weaker arrival would change

The question for each consumer: what changes if an arrival fires 5-35 s earlier, from "seen" rather than "room resolved", including a seen-then-lost false arrival (drive-by, neighbour edge)? The answer turns on §0: **"seen" already produces P-A and P-D at t0 today.** The build's only possible effect is to move P-B (a duplicate) earlier.

| Consumer | file:line | Reads | Trust / display | Today at "seen" (t0) | Delta if the build ships | Regression risk |
|---|---|---|---|---|---|---|
| **Garage lockout release (lock regime P1)** | `security_lock_regime.py:1097-1143` `_on_person_event` → `_release` | raw `person.*` home edge, gated by `_arrival_counts` / `_really_away` (≥ `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN`) | **TRUST: unlock action** | releases at t0 on the BLE-driven person edge | none: P1 already fired | none new |
| **Garage lockout + away lock (P2)** | `security.py:2389-2393` → `security_lock_regime.py:975-1020` | `SIGNAL_PERSON_ARRIVING`; `ble` and `geofence` treated the same; only `camera_face` needs corroboration | **TRUST: unlock** | P-A already released at t0 through P2, and through P1 | an earlier `ble` copy hits `_apply_arrival`. `_really_away` is now False because `_last_real` was moved to `home` by P1, so it is a no-op | none. A "seen" false arrival is **already** live exposure through P-A/P-D; the build adds nothing |
| **Away lock (door locks) release** | `security_lock_regime` `_away_on_person` / `_away_release` (presence doc §1 row) | raw `person.*` reads `home`, no blip gate; also P2 | **TRUST: unlock** | releases at t0 | none | none new; existing street-edge exposure noted in §7 |
| **Face-corroboration arrival edges (lock `camera_face`)** | `security_lock_regime.py:1122-1124, 1172-1206, 1230-1260`; `arrival_edges.py` | live `person.*` not_home→home edges + Bermuda `previous_location ≠ location` stamps from PC updates | TRUST gate for a face unlock | the tracker edge is stamped at t0 | none with the recommended no-build. **If the build used `async_request_refresh`**, PC would update more often, so stamps would arrive earlier (lock unaffected: it listens to every update) | see perimeter row |
| **Perimeter D10.5 known-person demote + "That was <name>" follow-up** | `perimeter_alert._nonface_agrees` / `_known_identity_for` (manual §4.5; presence doc §1) | live PC `previous_location ≠ location` (no stamps) and its own `person.*` edges | TRUST: **de-escalate** alert | unchanged | **REAL RISK under a refresh-based build:** extra PC refreshes shorten the window in which `previous_location ≠ location` is visible to a live reader, so fewer below-0.9 faces get corroborated and fewer alerts are de-escalated or named. No risk under no-build | **face-naming regression path; see §5** |
| **Egress identity (`transit_validator._resolve_egress_face_identity`)** | `transit_validator.py:1120-1226` (manual §4.3) | face sensor time vs crossing time; `person.<slug>` `not_home` veto | ADVISORY id | unaffected (keyed off crossing time, not arrival) | none | none |
| **Frigate face sub-label / face bridge / census face latch** | `camera_census._resolve_face_legs`, `_get_face_recognized_person_names` (~`:5893-5940`), `frigate_ingress` | face time; `person_state_for_trust` | census trust | not keyed off arrival time | none. The build does not touch `_gps_home_overruled` or `person.*` | none |
| **Exit backfill** | `camera_census._on_crossing_tracker_state_change` (manual §4.3a) | `bluetooth_le` tracker home→away edges | display/DB | unaffected | none | none |
| **Census BLE count** | `camera_census._get_ble_persons` (presence doc §10 #26) | PC `location` not away/unknown | census trust | polled | none unless PC cadence changes (refresh design: census sees home a few seconds sooner, harmless) | low |
| **HVAC pre-arrival / pre-cool** | `hvac.py:1511` subscribe, `7212-7281` handler; `hvac_predict.py:700, 1311, 1382` | signal; source filter `_pre_arrival_sources` (default `["geofence","ble","camera_face"]`, `hvac.py:881`, CM `CONF_PRE_ARRIVAL_SOURCES` `:1431-1440`) | trust (comfort/cost) | the geofence row shows pre-cool already starts at t0 (§0 table, so geofence is in the live filter) | none: a later `ble` duplicate only refreshes `_pre_arrival_start` | none new. A seen-then-lost false arrival is already live via P-A (cost: one pre-cool episode, bounded by the window) |
| **Security expected arrivals (sanction checker)** | `security.py:2412-2422` | signal → `add_expected_arrival(window_minutes=5)` if `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED` (default False, `config_flow.py:10403`) | **TRUST: suppresses an entry alert** | P-A already adds at t0 (when enabled) | none | none new; existing exposure, §7 |
| **Music following** | `music_following.py:549-583` | signal | none (DEBUG log only; arrival-start not implemented) | — | none | none |
| **House state AWAY→ARRIVING→HOME** | `presence.handle_geofence_event` (`:5282`), inference engine | person edge + census | TRUST (house state) | unchanged | none (P-B is not an inference input) | none |
| **Guest mode** | `_compose_guest_gate` / stay latch (presence doc §2.3) | DB night walk | trust | not arrival-driven | none | none |
| **NM arrival notifications** | none exists (`ARRIVAL-DEPARTURE-NOTIFY-1` open, manual §6) | — | — | — | — | none |
| **Pre-arrival fans ON/OFF** | `hvac_fans` via HVAC pre-arrival (presence doc §4.5) | HVAC pre-arrival zones | actuation | from the geofence at t0 | none | none |
| **Diagnostics** | `sensor.py:14503`, `hvac.py:8455`, `_last_pre_arrival_source` (`hvac.py:7271-7274`) | last source | display | shows the last source, often `ble` (because it arrives last) | would show `ble` sooner | display only |
| **Transition detector / Bayesian / music transitions** | `transitions.py:93`, `__init__.py:3257` | `ura_person_location_change` (P-E) | display/learning | polled | none unless the cadence changes | low |
| **PC listeners (aggregation / sensors)** | `aggregation.py:2195, 5581, 5721, 6122, 6485, 6574, 6629`; `sensor.py:2951, 3049` | PC updates | display + zone status | 30 s | a refresh-based build multiplies their wakeups (recorder churn) | low-medium under a refresh design |

---

## 4. Explicit risk calls

**Locks (garage lockout + away door lock): no regression from the recommended no-build, and none even from the approved build.**
- Every lock release a "seen" arrival could cause already happens at t0 through P1 (the raw `person.*` edge, HA person follows the BLE tracker) and P2 through P-A.
- A drive-by or neighbour-edge false "seen" **already** flips `person.*` home and releases today, subject to the lock's own ≥ 15-minute really-away gate.
- A new `ble`-source copy would only reach `_apply_arrival` after `_last_real` reads `home`, so it is a no-op.
- The street-edge exposure is a pre-existing property of the person config, not of this card (§7, Q2).

**Face naming: no regression from the no-build. The approved build has one regression path if it is implemented the obvious way.**
- The obvious implementation is to call `PersonCoordinator.async_request_refresh()` on area or tracker state changes. Areas flip every few seconds after an arrival (card gate note).
- That shortens the life of `previous_location ≠ location` in PC data. Perimeter D10.5 reads this live (no stamps) to corroborate a below-0.9 face, and the follow-up re-checks it every 5 s for 90 s.
- Result: fewer known-person demotions and fewer "That was <name>" follow-ups. Silent, display/de-escalation only, but it is exactly the regression the operator named.
- The lock regime's stamping (review A MED-1) is immune because it records every update.
- Egress `person_id` and Frigate sub-label production are keyed off crossing/face time, not arrival, so they are unaffected either way.

---

## 5. Falsifiable invariant (for the record and for any revival)

**INV-ARR-1:** for any resident whose `person.*` includes a `bluetooth_le` tracker, URA dispatches `SIGNAL_PERSON_ARRIVING` within 1 s of that tracker's first not_home→home edge, in every reachable path, without depending on PersonCoordinator's poll or on room resolution.

On develop this holds today through P-A. It is falsified by any arrival whose first `pre_arrival` activity row is `source=ble`, or is > 1 s after the person's `home` edge, while the person has a `bluetooth_le` tracker. D0 below checks exactly that.

**INV-ARR-2 (no-regression, for any future build):** no change may alter PersonCoordinator's update cadence or the visibility of `previous_location ≠ location` to live readers (perimeter D10.5). Falsified by a perimeter replay with fewer `egress_*+bermuda` corroborations on the same events.

---

## 6. Deliverables

### D0: one-shot read-only confirmation probe (ura-prober, ~15 min)
Over 14 days of recorder + `ura_activity_log`, for every resident arrival (a `person.*` not_home→home edge):
- (a) the first `pre_arrival` row's source and its lag behind the person edge;
- (b) the lag of the `bluetooth_le` tracker home edge behind the person edge (≤ 1 s expected);
- (c) the count of person→home edges that revert to not_home within 10 min (street/neighbour "seen then lost"), per person.

**Acceptance**
- **Verify:** (a) is `geofence` with lag ≤ 1 s for ≥ 95% of arrivals. **Discriminates:** if the build were needed, (a) would be `ble` or show a lag > 5 s for some arrivals (for example a person with no BLE tracker, or a GPS-led home that trails BLE).
- **Verify:** (c) gives the existing false-arrival rate. It informs Q2 and changes nothing here.
- **Live:** none (read-only).
- **Test:** none.

**Gate:** D0 confirms → close the card with D1. D0 refutes (any resident arrival whose first trigger is `ble` or late) → revive §9 at Tier 2 with that person as the fixture.

### D1: doc write-back (orchestrator, same commit as the card disposition)
- Add a row to `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 and §3: "`SIGNAL_PERSON_ARRIVING(source=geofence)` is the BLE-seen arrival on any install where `person.*` carries a `bluetooth_le` tracker (HA person non-GPS-home precedence). `source=ble` (PersonCoordinator poll, room-resolved, min-away gated) is a later duplicate."
- Add a §10 ledger item: "BLE arrival trails the first home signal by 8-41 s" is **misleading**. The BLE-seen arrival already fires at t0 as `geofence`. Cite this plan.
- Cross-link from `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5.

**Acceptance**
- **Verify:** both docs carry the row; the card's `answer_to_card_question` is updated to say "BLE alone already releases at t0 via person/geofence".
- **Test:** n/a.
- **Live:** n/a.

No code deliverable.

---

## 7. Non-goals
- No new listener, refresh trigger or dispatch site in `person_coordinator.py`.
- No change to `UPDATE_INTERVAL` (a cadence change hits every PC listener in §3 and perimeter D10.5).
- No change to the source label vocabulary (`ble` / `geofence` / `camera_face`).
- No UniFi Wi-Fi association arrival (the refinement mentioned a probe). Same verdict: the t0 arrival already exists, so Wi-Fi could only add a source that is not earlier than BLE. Revisit only if D0 finds a late arrival.
- The pre-existing street/neighbour false-home exposure through `person.*` is **not** this card (Q2).
- Removing the redundant P-B dispatch is **not** proposed. It carries the min-away gate and is the only arrival for any person without a BLE tracker in `person.*`, so it stays (KEEP + DOCUMENT).

## 8. Numbers and knobs
None introduced. Existing knobs touched by this analysis, unchanged: `UPDATE_INTERVAL` 30 (rung 1), `_min_away_minutes` (CM option), `CONF_PRE_ARRIVAL_SOURCES` (rung 2), `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` (rung 1), `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED` (rung 2, default off).

## 9. Tier
- **As planned (D0 + D1):** Tier 1 (read-only probe + docs). No plan review needed.
- **Had the approved build gone ahead:** it would have been **Tier 2-DB minimum, elevated** under the standing policy, because it is a new writer to a cross-coordinator signal that releases locks (trust-hierarchy ripple: presence → security/locks → HVAC → perimeter de-escalation), and the obvious implementation regresses perimeter face naming (§4).

## 9a. Parked design (revival trigger: D0 finds a resident arrival whose first trigger is late or `ble`, or an install whose `person.*` has no `bluetooth_le` tracker)
- **Config-first answer:** add the Bermuda / private_ble tracker to that `person.*` in HA. Then P-A covers them with no code. This is portable (pure HA config, any install).
- **Code answer, only if config cannot do it:** in `PersonCoordinator`, an `async_track_state_change_event` on each tracked person's own `bluetooth_le` trackers and Bermuda area sensor. It calls a narrow `_check_seen_arrival(person)` that runs only the existing `was_away` → dispatch block (factored out of `:1101-1138`, so there is ONE dispatch body) and does **not** call `async_request_refresh` (preserves INV-ARR-2). Same min-away gate, observation-mode gate and `_pre_arrival_enabled`. Fleet-liveness is not needed for an arrival: hearing a phone is positive evidence.
- **Seen-then-lost:** do not pop `_person_lost_since` on a seen-arrival; let the next poll's resolved-room clear do it. That way a drive-by does not consume the 15-minute arming.
- **Mutation anchor:** the factored dispatch helper.
- **Tier:** 2-DB, elevated.

## 10. Open questions for the operator
1. **Close the card?** The approved "seen-at-home" arrival already fires at t0 for all four residents as `source=geofence` (measured: the geofence row equals t0 on all 5 arrivals). I recommend D0 + D1 and no build. OK to drop the build?
2. **Street-edge exposure (pre-existing, separate card if wanted):** because HA `person.*` goes home on ANY BLE hearing, a resident heard by a street-facing proxy without entering already flips `person.*` home. That releases the garage lockout and away lock (≥ 15 min away gate on the garage only; the away lock releases on any `home` reading). D0(c) measures how often this happens. Do you want a card to gate lock release on a second witness, or is the current behaviour accepted?
3. **Wi-Fi association probe (refinement):** park it with the same trigger as §9a?
