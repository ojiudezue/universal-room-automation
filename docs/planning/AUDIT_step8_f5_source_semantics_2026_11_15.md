# AUDIT: what the F5 `geofence` and `ble` sources really are (step 8 D0 re-read), 2026-11-15

Read-only. Question (operator): does "geofence" just wrap GPS and BLE, so the D0 split measures the wrong thing?
Sources read: `custom_components/universal_room_automation` code (cited), `~/ha-config/.storage/{person,core.entity_registry,
core.config_entries}` (selected fields), recorder + URA DB via `ssh ha "python3 -" < .claude/tmp/f5src_semantics_probe.py`
(opened `mode=ro`; recorder window 2026-11-08 10:12 UTC to now, about 7 days). D0 under test:
`.claude/worktrees/builder-step8/docs/planning/AUDIT_identity_actions_d0_2026_11_15.md` (commit 470b760c). HA person logic read from
`.venv-ha/.../homeassistant/components/person/__init__.py:516-560`. Doc coverage: I read the PRESENCE state-of-play sections on
GPS/BLE axes and the manual §5.5 / arrival-source passages (grep-targeted), NOT both docs end to end; the verdict rests on code + data.

## Verdict: (b) the D0 split measures the wrong thing

`geofence` is not GPS. It is the composed raw `person.*` state flipping to `home`, and that state includes BLE trackers.
`ble` is a second view of the same arrival, fired 2-60 s after the `person.*` edge. The two F5 sources are not independent.

## 1. Producers (code)

| F5 source | Producer | Trigger |
|---|---|---|
| `geofence` | `presence.py:5684-5720` `_handle_geofence_change`, subscribed to every `person.*` (`presence.py:5600`, `_subscribe_geofence`) | `new_state.state == "home"` and `old_state.state != "home"` (live edge; restore/add excluded, `presence.py:5688`). Payload `source="geofence"` at `presence.py:5720` |
| `ble` | `person_coordinator.py:1219-1226` | Bermuda resolves a ROOM for a person flagged `_person_was_away` (LOST for >= `_min_away_minutes`, or the BLE-overrule path), `_pre_arrival_enabled` on, presence not in observation mode (`person_coordinator.py:1190-1226`). Payload `source="ble"` |
| `camera_face` | `presence.py:5981` | Face sighting while raw `person.*` is not home. Not in scope |

"Geofence" is NOT an HA zone-enter event, NOT a specific app, and NOT an iCloud3 hook. It is a state-change listener on `person.*`.
The F5 labels in D0 come from HVAC `ura_activity_log action='pre_arrival'` rows (`scripts/probes/identity_actions_d0.py:227-242`), so each
row is "HVAC accepted an F5 of this source".

## 2. Trackers behind each person (`.storage/person` + entity registry platform, not names)

| person | device_trackers (registry platform) | GPS? |
|---|---|---|
| oji_udezue | `phalanxiphone15promaxcflare` (mobile_app), `iphone_oji_bermuda_tracker` (bermuda), `private_ble_device_8ce182` (private_ble_device), `okosisipadmini6_2` (mobile_app, iPad) | yes |
| ezinne | `zinny_s_iphone_15` (mobile_app), `ezinne_iphone` (private_ble_device), `ezinne_iphone_bermuda_tracker` (bermuda) | yes |
| jaya | `private_ble_device_249050` (private_ble_device), `iphone_jaya_bermuda_tracker` (bermuda) | NO GPS |
| ziri | `iphone_ziri_bermuda_tracker` (bermuda) | NO GPS |

Bermuda tracker `source_type = BLUETOOTH_LE` (`~/ha-config/custom_components/bermuda/device_tracker.py:72`); `private_ble_device` the same
(`.venv-ha/.../private_ble_device/device_tracker.py:72`). No router/ping tracker exists on any person. Note: `iphone` iCloud3 shows up as a
`source` on ziri in the recorder (1 arrival, 2 departures) but is not in `.storage/person` now, so it is a former tracker (unknown why it is gone).

HA composition (`person/__init__.py:516-545`): a tracker whose `source_type == GPS` is a GPS tracker; ANY non-GPS tracker reading `home`
(`latest_non_gps_home`) wins and sets the person `home`; GPS is used only when no non-GPS tracker is home. So `person.* == home` is
"GPS home OR any BLE tracker home". For jaya and ziri it is 100% BLE by construction. The `source` attribute names the tracker that set the state.

"Has home" (operator): the only URA match is `hvac_zones.py:2708 zone_has_home_person`, which reads `first_person_home_for_trust`
(raw `person.*`, with the BLE-overrule). I take the operator's remark as "HA's person uses both underneath": confirmed above.

## 3. Measurement (recorder, 7 days; `.claude/tmp/f5src_semantics_probe.py`)

`person.*` arrival edges (not_home/zone -> home) by the registry platform of the edge's `source` tracker: mobile_app (GPS) 62, private_ble_device 13,
bermuda 3, icloud3 1. Per person: oji 49 GPS / 2 BLE; ezinne 13 GPS / 3 BLE; jaya 0 GPS / 9 BLE; ziri 0 GPS (2 bermuda + 1 icloud3).
Because a BLE tracker at home outranks GPS, a `mobile_app` source on an edge means no BLE tracker was home then, so the attribution of cause is sound.

| Finding | Number |
|---|---|
| `geofence` F5 (recorder window) edges whose source tracker is GPS vs BLE-family | 61 GPS / 17 BLE-family of 78 |
| geofence F5 lag from the `person.*` edge | 0 s for all 78 (same call) |
| `ble` F5s with a `person.*` arrival edge within 120 s | 31 of 31; none without one |
| `ble` F5 lag after that edge | 2-60 s (all positive) |
| That edge's source for the 31 `ble` F5s | 14 GPS, 17 BLE-family |
| `geofence` F5s followed by a `ble` F5 (same person, <=120 s) | 31 of 78 |
| Away-under-15-min flaps among arrival edges | 19 of 80, all 19 GPS; all 17 BLE-family arrivals were counted returns |

So every `ble` F5 duplicates a `geofence` F5 of the same arrival. Of the 6 D0 geofence "not counted" rejects, the 19-flap pool is GPS-only (the
6 are GPS flaps; BLE-family edges never flapped under 15 min in this window).

## 4. Counted-return gate re-read

- The gate reads residency rows (`memory_episodes person_arrival/person_departure`, written by `presence.py:5361-5420` `_feed_residency` from the SAME
  `_handle_geofence_change` stream, `presence.py:5684`). A "departure seen" is a `person.*` home -> not_home edge, which is composed state: it
  fires only when GPS is away AND every BLE tracker is away (or only BLE exists).
- Residency rows exist from 2026-11-13 20:54 UTC. 11 `ble` F5s in that span (D0 reported 9 judged): person-edge source GPS in 6 (ezinne x3, oji x3),
  BLE-family in 5 (jaya x3 private_ble, ziri x2 bermuda). Examples: 11-14 00:13 UTC jaya edge private_ble lag 6 s, `ble` F5 same arrival; 11-14 01:19
  ezinne edge mobile_app lag 37 s.
- D0's reading "later arrival edge first (GPS led)" is true for 6 of 11 only. For the other 5 the leading edge is BLE evidence and the `ble` F5 is the
  same BLE evidence a second time (private_ble/Bermuda trackers feed `person.*`; `ble` F5 comes from Bermuda room resolution of the same IRK).
- The split was therefore: geofence 9/15 pass = the one `person.*` edge judged by its own residency record (self-referential, "same call, 0 s");
  ble 0/9 = the same arrivals judged by "a later arrival edge exists", which is always true because the arrival edge precedes the `ble` F5.
  The `ble` 0/9 is an artefact of ordering, not evidence BLE is weak. The geofence 9/15 is mostly a GPS-flap filter (all 19 flaps are GPS).

## 5. Corrected framing for step 8

Real independent sources are GPS (mobile_app zone state) and BLE (IRK/Bermuda), both folded into `person.*` by HA. There is no independent "geofence"
vs "ble" arrival: one physical arrival yields one `person.*` edge plus, 2-60 s later, a `ble` F5 in 31 of 78 cases.

Recommendations (design input, not decisions):
1. Treat the arrival trigger as ONE event per physical arrival: the counted `person.*` arrival edge (residency record). Key the intent on it; treat the
   `ble` F5 as a duplicate (`intent_duplicate_source` already exists for this) rather than a separate source with its own departure-side gate.
2. If the plan wants source awareness, read the edge's `source` attribute through the registry platform (GPS `mobile_app` vs BLE-family), not the F5
   label. Per-person coverage differs: jaya and ziri have no GPS tracker, so for them "geofence" is BLE only and counted-return = BLE away >= 15 min.
3. Drop the plan premise that `ble` "contributes nothing today" and the 15-min departure bar for `ble`; both come from the double view. A real BLE-first
   pre-arrival (before the `person.*` edge) did not occur in this window (0 of 31 `ble` F5s lacked a prior edge, lag always >= 2 s after).
4. The 19 GPS flaps (<15 min away) are the true thing the counted gate filters; keep it, applied to the `person.*` edge.
5. D0 headline "geofence 10.8/day vs BLE 4.4/day" should be restated as: arrivals/day by person.* edge source (GPS vs BLE-family), with `ble` F5s as a subset.

Falsifier attempted: a `ble` F5 with no `person.*` arrival edge within 120 s (would show BLE as an independent early source): found 0 of 31.
Limits: recorder holds ~7 days; the HVAC `pre_arrival` rows are a lower bound on F5s; the `icloud3` source is unexplained; the 9 vs 11 judged-row count
differs from D0 (I did not rerun its exact filter).
