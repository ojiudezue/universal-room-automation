# PLANNING — Per-person GPS axis: freshest-GPS-wins (PERSON-GPS-ANY-HOME-WINS-1)

**Card:** PERSON-GPS-ANY-HOME-WINS-1 (sibling of HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1).
**Tier:** 2 (presence producer, one function; no schema, no new entity, no config field).
**Branch:** `fix/person-gps-freshest-wins` (off `develop`). Not deployed.
**Decided direction (card `next`, 2026-10-18):** freshest-GPS-wins, NOT any-home-wins. Any-home-wins
lets a left-at-home iPad hold a person "home" forever.

## 1. Institutional context verified

Read completely before planning: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (§3
"Per-person tracker axes" names this exact gap and the iPad incident; §10 ledger checked, nothing
re-asserted) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (not affected: this is a tracker axis,
not a room sensor).

| Surface | Result |
|---|---|
| Producer | `person_coordinator.PersonTrackingCoordinator._read_source_inventory` (`person_coordinator.py:186-242` on develop). REUSED and extended in place; no new helper surface beyond a pure tie-break function. |
| HA precedent | HA's own `person` entity already picks the GPS tracker with the newest `last_updated` and skips `unknown`/`unavailable` (`.venv-ha/.../homeassistant/components/person/__init__.py:516-544`, `_get_latest` :596-600). This change aligns URA's axis with that rule. |
| Constants | grep `const.py` / `person_coordinator.py` for `GPS`, `FRESHEST`, `LAST_WINS`: nothing equivalent. NEW module constant `PERSON_GPS_FRESHEST_WINS_ENABLED` (rung 1 kill switch), placed next to `BLE_FLEET_LIVENESS_WINDOW_S` (the existing rung-1 precedent in this file). |
| Config flow / options | No field. `CONF_TRACKED_PERSONS`, distance and decay fields are unrelated. Config-first check: no knob or HA setting changes URA's per-tracker reduction. The operator's HA-side workaround (remove the iPad from `person.oji_udezue`, 2026-10-18) fixed this house; it does not generalise (Wigton `person.omonele`: 6 trackers, 1 reporting). |
| Prior plans | `PLANNING_house_state_sleep_mask_ble_memory_observability.md` §"Separate finding" (lines ~498-502): origin, recommends freshest over any-home. PATH-ALPHA D2a matrix plan (row vocabulary consumed below). |
| Memory | `reference_presence_state_of_play`, `feedback_extend_existing_never_rebuild`, `feedback_wire_in_anchor_mandatory`. |
| Code surveyed | `person_coordinator.py` 186-360 (inventory + classifier), 515-545 (row-1 call), 665-760 and 760-850 (no-room and no-Bermuda branches), `sensor.py:3192-3300`, `aggregation.py:5630-5700, 5960-6000`. |

## 2. Producer and consumer check

**Producer.** Per tick, for each person, `_read_source_inventory(person_state)` walks
`person.<x>.attributes.device_trackers` and builds `{gps, wifi, ble}`. Before this change, every GPS
tracker overwrote `sources["gps"]`, so the last GPS tracker in the list won. Dependencies: HA
`device_tracker.*` state + `source_type` + `last_updated` (all healthy; HA core fields).

**Consumers (call sites).** Three call sites, all in `_async_update_data`:
1. Row 1, BLE visible at a room (~`:545`): sources attached as `tracker_sources` only.
2. Bermuda-exists-no-room branch (~`:693`) → `_classify_matrix_row`.
3. No-Bermuda-sensor branch (~`:782`) → `_classify_matrix_row`.

`_classify_matrix_row` maps the GPS axis into `confidence`, `tracking_reason` and the
`tracker_sources` attribute. **Location is NOT decided by the GPS axis in branches 2/3:** the wrapper
forces location from `person.<x>.state` (home → home; unknown → LOST/no_signal; else → away). So the
axis feeds:
- `confidence` (e.g. GPS-only home 0.75 vs away_gps_only 0.92 rewritten to home_ble_silent) — read by
  `get_person_confidence` (`:1428`), room person lists (`sensor.py:3229`, `aggregation.py:5637`),
  the person snapshot DB write (`:851` area) — display/diagnostic.
- `tracking_reason` / `tracker_sources` — attributes on `sensor.<person>_location`
  (`aggregation.py:5975-5998`) and room/zone person lists. Display.

**Producer finding (honest scope).** The AWAY-relevant value is `person.<x>.state`, which HA already
computes freshest-GPS-wins (with non-GPS `home` taking precedence). So the iPad hurt URA's trust
decisions only through HA's own aggregate when the iPad's fix was the freshest; URA's last-wins axis
mis-stated the provenance (`tracker_sources.gps=away`, wrong `tracking_reason`/`confidence`) and
disagreed with the person entity. This cycle makes URA's provenance agree with HA's rule; it does not
by itself change any house-state decision. That is the expected, correct size of the change.

## 3. The rule

GPS axis = the reading of the GPS (`source_type == "gps"`) tracker with the newest `last_updated`
among trackers in a real state (`home` → home; `not_home` or a named zone → away).
- A tracker in `unknown` / `unavailable` / empty never beats a real reading, whatever its timestamp.
- If no GPS tracker has a real reading but at least one GPS tracker exists → `unknown`.
- No GPS tracker → `MISSING` (unchanged).
- Tie on `last_updated`, or both trackers lack a usable timestamp → the later tracker in the list wins
  (the legacy rule, so the no-timestamp case is byte-identical to before).
- A tracker with no usable timestamp (None / not a `datetime`) ranks oldest against a dated one.
- Naive/aware mix that cannot be compared → later-in-list (no crash).
- Non-GPS trackers (`router`, `bluetooth_le`, …) never feed the GPS axis (unchanged).

**Knob:** `PERSON_GPS_FRESHEST_WINS_ENABLED = True` (rung 1, `person_coordinator.py`). False = legacy
last-tracker-wins. Rung 1 because it is a policy choice with no per-house tuning value; changing it
should go through review.

## 4. Falsifiable invariant

**INV-GPS-FRESHEST:** for any person with ≥1 GPS tracker in a real state, `tracker_sources.gps` equals
the reading of the real-state GPS tracker with the greatest `last_updated`; an `unknown`/`unavailable`
GPS tracker can never change the axis away from a real reading. Falsified by any input where a staler
real reading or an unknown reading determines the axis while a fresher real reading exists.

## 5. Edge cases

| Case | Behaviour |
|---|---|
| Equal timestamps | Later in list wins (legacy order). |
| Unavailable / unknown tracker (fresh) | Ignored while any real GPS reading exists; all-unknown → `unknown`. Before: last-listed unknown erased a real reading. |
| Tracker with no `last_updated` | Ranks oldest; two undated → list order. |
| Restart | HA restores trackers with boot-time `last_updated`; freshness collapses to near-ties for a few seconds/minutes and the order of restore decides. Converges on the first real GPS update (phone app reports on movement / periodic). No URA state is persisted for this, so no stale-restore risk. |
| Non-GPS source_type | Unchanged: router → wifi axis; BLE → handled by Bermuda path. |
| Left-at-home device (why not any-home) | A stale `home` iPad loses to a fresher `not_home` phone → away. Pinned by test. |
| Wigton (6 trackers, 1 reporting) | Non-reporting trackers are either unavailable (ignored) or stale (lose to the reporting one). Correct by construction; verify live (below). |

## 6. Non-goals

- WiFi (`router`) axis keeps last-wins. No observed multi-router person; card it if one appears.
- No change to `_classify_matrix_row`, the location wrapper, I-α, or any AWAY path.
- No any-home-wins option.

## D1: Freshest-GPS-wins in `_read_source_inventory`

### Acceptance Criteria
- **Verify:** phone home (fresh) + iPad not_home (stale, listed last) → `gps == "home"`.
- **Verify:** phone not_home (fresh) + iPad home (stale) → `gps == "away"` in both list orders.
- **Verify:** fresher unknown/unavailable/empty never beats a real reading; all-unknown → `unknown`.
- **Verify:** ties and undated trackers follow list order; dated beats undated.
- **Verify:** kill switch False restores last-wins.
- **Test (unit):** `quality/tests/test_path_alpha_d2a_matrix_classifier.py::test_gps_*`.
- **Test (enclosing method):** `test_gps_freshest_wins_through_async_update_data` drives
  `_async_update_data` through the no-Bermuda branch; asserts `tracker_sources.gps == "home"` and
  `confidence == 0.75` (legacy would give `away` and 0.92).
- **Live:** for each tracked person, `sensor.<person>_location` attribute `tracker_sources.gps` agrees
  with the GPS `device_tracker` that has the newest `last_updated` (read both in one pass). For this
  house (one GPS tracker per person since 2026-10-18) the value is unchanged from pre-deploy — a
  no-op check. On Wigton, `person.omonele`: `tracker_sources.gps` must equal the reporting tracker's
  reading, not the last-listed one. Discriminates: under the old code the Wigton value tracks the
  last GPS tracker in the list; under a broken build (e.g. unknown participating) it reads `unknown`.
- **Live:** no new WARN/ERROR from `person_coordinator` in the 10 min after restart.

## 7. Plan completion

All items built. Deferred: WiFi-axis freshness (non-goal, no evidence). Live checks owed at deploy.
