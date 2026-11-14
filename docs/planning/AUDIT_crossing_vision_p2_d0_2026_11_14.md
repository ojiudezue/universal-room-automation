# AUDIT: crossing vision P2-D0 + census CD0 (read-only probe)

Run Sat 2026-11-14 00:01-00:15 CST (`date`), process count 591-599. Not committed. Plans read first: `PLANNING_crossing_vision.md` "P2-D0 read-only probe" (:172-179) and `PLANNING_census_deconfliction.md` CD0 (:248-252), both read in full for those sections. HVAC / presence STATE_OF_PLAY docs NOT read (measurement only, no behaviour change; (v) reads house_state rows but proposes nothing). Sources: URA DB via `ssh ha sqlite3 -readonly`, HA recorder via `ssh ha sqlite3 -readonly /config/home-assistant_v2.db`, mounted `.storage` lovelace files, local PWA repos. **Model calls made: 0** (budget 6; none spent). No services called, no state changed, no keys read.

Windows: "14 days" = 2026-10-31 06:00 UTC to 2026-11-14 06:00 UTC unless stated. All DB timestamps are UTC; times below are UTC unless marked CST.

## Answer first

| Item | Result | Verdict / gate effect |
|---|---|---|
| (i) residency fire check | **FIRES.** 3 resident edges since the v5.108.19 restart (11-13 11:44 CST) = 3 rows (2 `person_arrival`, 1 `person_departure`), 3/3 one-to-one | PASS. Bar b can use the producer. Oji's two-word name not yet exercised (Oji is in NZ) |
| (ii) empty anchors 14 d | camera zero AND no room entry AND no door entry term: **170 / 48 / 9 anchors** at 1800 / 3600 / 7200 s (last 7 d: 85 / 22 / 3) | 3600 s (the operator default) clears bar a's >= 10 anchors per 7 d (22); 7200 s does not (3). Only 19 % of 3600 s anchors fall while the house is AWAY |
| (iii) wrong-event rate at +-30 s | no ground truth exists; proxy: **22 / 97 = 22.7 %** of matched picks have an interval that does not cover E +-5 s (10.3 % at +-10 s); **>= 5 / 97 = 5.2 %** even counting only the 10 newly-matched | Does NOT clear `CROSSING_VISION_EVENT_MATCH_WRONG_MAX` 0.02. Keep `EVENT_MATCH_S` = 10 |
| (iv) D0a on Luna | **NOT RUN: needs operator ok for 4 paid calls** (described below) | blocked on operator |
| (v) AWAY latency baseline (CD0) | 7-day recorder window only: **n = 22 AWAY rows; median 44 s, p90 8758 s** (all). Fresh departures n = 17: **median 39 s, p90 853 s**. Paths: `active` 55 % / `nobody_home` 45 % (14-day, n = 30: 16 / 14); `lost_admitted` 0 | baseline for INV-P2-AWAY-LATENCY. The 14-day span is not reachable (recorder keeps 7 d) |
| (vi) timing simulation | F lands **p50 1.2 s / p90 7.9 s** after the camera edge E; B lands **p50 52.8 s / p90 60.6 s** after E (p50 7.8 / p90 15.6 s after t0). **F = B on 39/45 = 86.7 %** (Wilson 95 % low 76 %) | P2-D8 gate (F p90 <= 60 s AND F = B >= 85 %): both pass as measured; the share passes by 1.7 points with a wide interval |
| (vii) | closed in the plan (grading path cited there) | not re-done |
| (viii) name back-fill | reused: Frigate strict p50 2-8 s, p90 10-25 s, p99 17-50 s, max 55.5 s, recommend **90 s**. Protect: **no live URA path**; the only number is a 2026-08-29 single measurement of 40-80 s (memory), unverified here | `NAME_SETTLE_S` entry = p99 + 30 s = **80 s** (Frigate); 90 s recommended |
| (ix) dashboard / PWA references (CD0) | 9 lovelace dashboards, 2 PWA copies of `Presence.tsx`, 0 HA automations/packages | list below; **headline "people" cards: `ura_v8` Now + People + Rooms, PWA `Presence.tsx` cards at :369 and :377** |

## (i) Residency fire check

- Producer: `RESIDENCY_EVENT_LOG_PERSIST = True` writes one `memory_episodes` row per resident edge, types `person_arrival` / `person_departure` (`const.py:4042-4047`).
- SQL: `select started_at,episode_type,node_id,json_extract(attrs_json,'$.counted') from memory_episodes where episode_type in ('person_arrival','person_departure') order by started_at` returned:

| started_at (UTC) | type | node | counted |
|---|---|---|---|
| 2026-11-13 20:54:16 | person_departure | ezinne | null (departures carry no count) |
| 2026-11-14 00:13:01 | person_arrival | jaya | 1 |
| 2026-11-14 01:19:13 | person_arrival | ezinne | 1 |

- Independent oracle (falsifier): recorder `person.*` home <-> non-home edges for the four tracked persons since 11-13 17:44 UTC (restart 11:44 CST): ezinne home -> not_home 20:54:16, jaya not_home -> home 00:13:01, ezinne not_home -> home 01:19:13. Three edges, three rows, timestamps equal to the second. If the producer were dead the rows would be 0 (as the README_v5.108.19 reading at 11:53 CST showed, before any edge).
- Not covered: Oji (`person.oji_udezue`) had no edge (in NZ), so the two-word-name case README_v5.108.19 flagged is still unexercised. Rows only start after the restart; the producer was never in doubt over the earlier 14 days because it did not exist.
- Consumer note: bar b falls back to recorder `person.*` edges only if the producer is dead; it is not, so no fallback card.

## (ii) Independent empty anchors, 14 days

Method (producer): replay the plan's anchor rule (`PLANNING_crossing_vision.md:189-195`) over the house `census_snapshots` rows (15,018 rows, one per ~90 s; gap p50 82 s, p99 114 s, 38 gaps > 300 s which reset the window). A sample passes when `frigate_count = 0 AND unifi_count = 0` (proxy for the ledger's raw camera body total: it is a conservative proxy, since the real total is a cross-validated `camera_total` and any platform > 0 here fails the sample), and, in the edge variants, no `occupancy_events` `entry` row (all rooms; 3,470 rows in the window, so wider than "Tier-1 rooms") and no `person_entry_exit_events` `egress`/`entry` row (the ENTRY-term proxy) fell in the sample interval. A firing at `now - t_start >= R` sets `t_start = now`, as in the plan.

| Variant | R (s) | Anchors, 14 d | Per day | Last 7 d | Days with >= 1 | Distinct empty stretches | Fired while house_state = away | Median gap (h) | Max gap (h) |
|---|---|---|---|---|---|---|---|---|---|
| camera only | 1800 | 339 | 24.2 | 158 | 14 | 100 | 50 (15 %) | 0.52 | 9.9 |
| camera only | 3600 | 140 | 10.0 | 64 | 14 | 57 | 19 (14 %) | 1.02 | 18.4 |
| camera only | 7200 | 50 | 3.6 | 24 | 14 | 26 | 4 (8 %) | 2.16 | 20.9 |
| **camera + room entry + door entry (plan rule)** | 1800 | 170 | 12.1 | 85 | 14 | 106 | 30 (18 %) | 0.82 | 18.2 |
| **plan rule** | **3600** | **48** | 3.4 | **22** | 13 | 36 | 9 (19 %) | 2.7 | 48.6 |
| **plan rule** | 7200 | 9 | 0.6 | 3 | 6 | 8 | 3 (33 %) | 21.0 | 74.5 |

Reading:
- Bar a needs >= 10 independent anchors over its 7-day window (`CROSSING_VISION_GO_DRIFT_MIN_ANCHORS`). At the shipped 3600 s: 22 in the last 7 d (pass); at 1800 s: 85; at 7200 s: 3 (would fail bar a on volume).
- **Independence caveat (the finding):** 81 % of the plan-rule 3600 s anchors fire while the house is NOT AWAY (mostly the sleep / night hours: local hours 20-06 dominate the hour histogram). Truth "zero guests" at those anchors is not independent of the ledger: it is the resident-only assumption. The AWAY-time anchors (9 at 3600 s) are the only ones whose truth (nobody home) the census does not also assume. The bar-a oracle text says "truth 0"; this probe says that truth is only independently checkable on about 1 anchor in 5.
- Not measured: `camera_input_dark` history (not persisted; the recorder has the latch only as a live state), the stored-value staleness rule (2 x eval interval; snapshot cadence 90 s is not the 60 s eval clock), Tier-1-only room edges (used all rooms, so counts are a lower bound on anchors). The 7-day figures are inside the recorder window; the census and occupancy tables are not recorder-bound.

## (iii) Wrong-event rate at +-30 s (117 D0c clusters)

Fixture: `w/clusters.json` (117 clusters, door group garage_a / front) x `w/ev2.json` (Frigate person events), E = t0 - 45 s, rule `PLANNING_crossing_vision.md:114` (highest `top_score`, tie longest), groups from the live `door_groups` (doorbell_lite + garage_a, front_door_aerial + madrone_g6_entry). Coverage matches D0c exactly (87 / 97 / 103 of 117 at +-10 / 30 / 60 s), so the fixture is the same one.

There is **no ground truth** for "this event belongs to this crossing" (labelling needs the frames of each pair: model calls or operator time). The audit reports proxies, labelled as such:

| Window | Matched | Picks with >= 2 candidate events | Pick != nearest-start candidate | Pick interval does not cover E +-5 s |
|---|---|---|---|---|
| +-10 s | 87 | 35 | 20 | 9 (10.3 %) |
| +-30 s | 97 | 54 | 33 | **22 (22.7 %)** |
| +-60 s | 103 | 66 | 39 | 31 (30.1 %) |

Widening 10 -> 30 s: the pick **changes for 11 of the 87** already-matched crossings, and **10 crossings are newly matched**; of those 10, 5 have a pick whose interval covers E +-5 s (plausible) and 5 do not (likely wrong: start offsets +19.6, +11.1, +20.1, +26.2, +17.7 s with durations 7-25 s). So the lenient lower bound on wrong picks at +-30 s is 5 / 97 = 5.2 % (newly matched, not covering) and the proxy upper bound is 22.7 %. Both exceed `CROSSING_VISION_EVENT_MATCH_WRONG_MAX` 0.02.

Verdict: the plan's rule "-> 30 s if (iii) <= 0.02" is **not met** on either reading. Keep `CROSSING_VISION_EVENT_MATCH_S` = 10 (74.4 % coverage, 25.6 % `no_frigate_event`). A real rate would need the 97 picks graded (a clip frame check; operator time or ~97 paid calls, outside the 6-call budget).

## (iv) D0a on the Luna entry: NEEDS OPERATOR OK FOR 4 PAID CALLS

Not run. D0a = dry calls proving the second llmvision entry (`01M7B731T26P2HXVW77AQR62PP`, `gpt-6-luna`, temp 1.0 / top_p 1.0) accepts the production request on both service paths. D0-V showed the OLD default path 400s on `temperature` for gpt-6 models (`AUDIT_crossing_vision_d0_v_2026_11_13.md` table), which is why the new entry exists; no run on it is on record (`AUDIT_crossing_vision_d0_2026_11_13.md` "D0a skipped").

Proposed calls (4 of the 6 allowed), all `return_response`, `store_in_timeline` false, `use_memory` false, `max_frames` 4, `target_width` 768, structured schema from the plan D1, no naming prompt, on two already-fixtured crossings (a single-person garage_a event and the 2-person set #27):
1. `llmvision.image_analyzer`, provider = Luna entry, 3 frames of crossing #27 (2 people).
2. `llmvision.image_analyzer`, same entry, 3 frames of one single-person crossing.
3. `llmvision.video_analyzer`, same entry, `video_file` = instance-scoped `/api/frigate/frigate-f2/notifications/<event_id>/clip.mp4` of #27.
4. `llmvision.video_analyzer`, same entry, same URL form for the single-person crossing.
Records: HTTP status, latency, whether `structured_response` parses, `people_total` vs visual truth, no `response_text` key expected. Estimated cost under $0.01 total (D0-V estimate for Luna: input about $0.0003 per 3-frame call, output unknown). Needed for: P2-D1 (the Luna provider override) and for pricing levers L4 below. Two calls remain unspent for lever pricing.

## (v) AWAY latency baseline (CD0): last resident departure edge -> AWAY row

Producer / consumer: AWAY rows = `memory_episodes` `house_state_transition` with `new_state = away` (carries `trigger`, `snapshot.veto_path`, `snapshot.source`), matching `house_state_log` rows; written by the presence house-state machine (path label from `_note_away_entry`, `presence.py:9559-9573`; veto path set at `:1190`, `:1362-1363`). Consumer: the INV-P2-AWAY-LATENCY rung check (`PLANNING_census_deconfliction.md:74`).

Method: for each AWAY row, the "last resident departure edge" = the most recent recorder home -> non-home edge among the four tracked persons (`person.oji_udezue`, `.ezinne`, `.jaya`, `.ziri`; 4 = `tracked_persons_count_trusted` in the snapshot; `unavailable`/`unknown` ignored) before the AWAY row. **Window limit:** the recorder keeps 7 days (`purge_keep_days: 7`, `configuration.yaml:13`; person history starts 2026-11-06 10:26 UTC), so latency is measured on the 22 of the 29 AWAY rows after that; the `person_departure` rows only exist since 11-13 and are n = 1. The 14-day span the plan asks for is not reachable for latency; the path-label share is (all 30 rows in `house_state_transition` for 14 d).

| Cut | n | median (s) | p90 (s) | min / max (s) |
|---|---|---|---|---|
| All AWAY rows, 7 d | 22 | 44 | 8758 | 16 / 12085 |
| Fresh departures (no earlier AWAY row since the edge) | 17 | **39** | **853** | 16 / 1660 |
| Re-entries (house left AWAY and fell back in after the edge) | 5 | 8842 | 11219 | 649 / 12085 (all `active`, 4 of 5 on 11-13 evening) |
| Fresh, path `active` | 7 | 35 | 46 | |
| Fresh, path `nobody_home` | 10 | 41 | 1551 | |

Share of AWAYs per path label (`snapshot.veto_path`, 14 d, n = 30): `active` 16 (53 %), `nobody_home` 14 (47 %), `lost_admitted` 0, `lost_admitted_immediate` 0. 7-day cut (n = 22): active 12 (55 %), nobody_home 10 (45 %). By trigger (14 d): `census_update` 23, `periodic` 4, `deferred_retry` 2, `guest_room_occupancy` 1. Raw rows with latencies are reproducible from the SQL below.

- All 21 of 22 AWAY rows had every tracked person not-home at the AWAY time (the one exception, 11-12 16:55 UTC, had a resident home: 12,085 s after an earlier edge; it is a re-entry).
- The typical fresh latency (35-45 s) tracks one census tick; the p90 is dominated by 3 `nobody_home` rows at 395-1660 s.
- Side finding (not in scope, not carded): 5 AWAY entries in 3 h on 11-13 evening (20:54, 21:05, 23:07, 23:21, 23:39 UTC) while one resident was continuously away since 20:54 UTC: the house left AWAY and re-entered it four times (`guest_room_occupancy`, `census_update`, `deferred_retry` x2). That is AWAY flapping, and it inflates the re-entry cut.
- SQL: `select started_at, json_extract(attrs_json,'$.old_state'), json_extract(attrs_json,'$.new_state'), json_extract(attrs_json,'$.trigger'), json_extract(attrs_json,'$.snapshot.veto_path'), json_extract(attrs_json,'$.snapshot.source') from memory_episodes where episode_type='house_state_transition' and json_extract(attrs_json,'$.new_state')='away' and started_at>='2026-10-31T06:00' order by started_at` (30 rows); recorder `states` join `states_meta` for the four `person.*` ids.
- Falsifier of "baseline = ~40 s": a bias would come from a departure edge being earlier than what the machine reads (BLE-lost residents); fresh `active` rows (35 s) vs `nobody_home` (41 s) agree, so no evidence of it. The `person_departure` row for the only live case (ezinne, edge 20:54:16, AWAY 20:54:37 = 21 s) agrees.

## (vi) Timing simulation: F / B per stage, F = B share

Inputs: the 117 D0c clusters; Frigate events matched at +-10 s (87 matched; event start / duration from `ev2.json`); E = t0 - 45 s (`transit_validator.py:1274`, cited in the D0-FRAME audit); call latencies drawn (Monte Carlo, 400 draws per cluster, seed 20261114) from the measured samples: image path gpt-4o-mini n = 50 (p50 2.07, p90 2.70, max 3.44 s, `AUDIT_crossing_vision_d0_v`), video path gpt-4o-mini n = 45 (p50 7.5, p90 13.7, p99 17.8 s, `AUDIT_crossing_vision_d0`). Stage definitions: F = image call at the Frigate event start; B = video call at `max(t0, min(event end, t0 + 120 s))` (plan :116, `EVENT_END_WAIT_S` 120). 81 of the 87 matched events had already ended before t0, so B is gated by t0 in 93 % of cases.

| Stage / lever | Lands after E, p50 | p90 | p99 | Lands after t0, p50 / p90 |
|---|---|---|---|---|
| F (image at event start; also L2 snapshot-first) | **1.2 s** | **7.9 s** | 11.1 s | -43.8 / -37.1 s (before the crossing emit) |
| B (video at event end / t0) | **52.8 s** | **60.6 s** | 98.6 s | **7.8 / 15.6 s** |
| L1 video at event start + 5 s | 11.7 s | 19.8 s | 26.7 s | not measured: clip completeness at +5 s unverified |
| L5 video at E | 7.5 s | 13.7 s | 17.8 s | same caveat; open-event clip serving UNVERIFIED (`AUDIT_crossing_vision_d0` "Not tested") |
| L3 (3 frames), L4 (model / reasoning effort) | needs paid calls | | | see below |

F lands before B in 100 % of the simulated draws (expected: F at event start, B at t0 or later).

**F = B share** (D0-V image-path count vs D0b video-path count, same 45 scored crossings, same model): equal on **39 / 45 = 86.7 %** (Wilson 95 % low 76 %, high 91 %). Disagreements 6 (crossing, truth, F, B): (4,1,2,1) (6,1,2,1) (9,1,2,1) F over; (7,1,1,2) B over; (11,0,0,1) B over on the distant-only set; (27,2,2,1) B under on the only 2-person set. F alone = truth on 42 / 45 and B alone = truth on 42 / 45, both right on 39, **both wrong on 0**.

Gate (`PLANNING_crossing_vision.md:246`): "simulated F p90 <= 60 s" **passes** (7.9 s after E); "F = B share >= 85 %" **passes by 1.7 points** on n = 45 with a wide interval. Caveats that matter more than the margin: (a) the F frames in D0-V were extracted from the event clip, not the live snapshot + latest-frames input P2-D8 actually specifies (snapshot 404s on 17.5 % of doorbell_lite and 30 % of madrone_g6_entry events, D0-FRAME F3), so F accuracy on its real input is not measured; (b) both paths used gpt-4o-mini; P2-D8 says Luna; (c) multi-person n = 1.

Lever pricing (counts needed to adopt per plan :253, exact within 2 points of 93.3 %): L1, L5 change timing only on paper; their count accuracy needs a clip fetched before the event ends (unverified) and is not measurable offline. L3 (3 vs 4 frames), L4 (Luna reasoning effort) need calls: **needs operator ok for up to 2 further paid calls** (the 2 unspent of the 6) and cannot establish a 2-point accuracy difference on 2 calls; an accuracy decision on L3 / L4 would need the 45-crossing replay (45 calls) or operator labels.

## (vii)

Closed in the plan (`:178`, grading path cited there). Not re-done.

## (viii) Name back-fill p99 at the door cameras (reused, not re-measured)

- Frigate (`AUDIT_frigate_face_name_latency_2026_11_13.md`): strict event-start -> first name p50 2-8 s, p90 10-25 s, p99 17-50 s, max 55.5 s (n = 61 events over the four door cameras; doorbell_lite p99 50.1 s is the largest), lenient tail 60-283 s only under ambiguous burst attribution; recommended **90 s**, 120 s alternative.
- Protect: `AUDIT_protect_face_name_interfaces_2026_11_13.md` lead point 1: URA has NO live Protect face-name path (no poller; Protect face leg is KEEP + DOCUMENT, dead until D1-PROTECT-FACE-BRIDGE-ADDON-1), and Protect face recognition is enabled on only two cameras (Family Room, Madrone G6 Entry). Its 40-80 s figure (single 2026-08-29 manual measurement: websocket "no name yet" at 26 s, REST re-query ~82 s has `matchedName`) is a memory note, not a production metric. So there is **no Protect p99 to report**; for the one door with Protect faces (G6 entry) the plan's rule "p99 + 30 s" gives 80 s (Frigate strict p99 50.1 s) or ~112 s (the 82 s single Protect observation).
- Effect on the knob (`CROSSING_VISION_NAME_SETTLE_S`, `:324`, currently 180): 180 s is about 3x the measured Frigate p99. Entry value per the plan's own formula = 80 s; 90 s per the Frigate audit. No new measurement here.

## (ix) Dashboard / PWA references to the trust census entities (CD0)

Entity ids from `.storage/core.entity_registry` (platform `universal_room_automation`). Note: `sensor.universal_room_automation_guest_count` named in the census plan §3.6 is **not registered** in this install; only `sensor.zone_*_guest_count` and the house `unidentified` sensors exist (the census house guest count is carried by `sensor.universal_room_automation_unidentified_persons_in_house`). The plan's trust list also does not name `unidentified_persons_in_house`, `census_confidence`, `census_validation_age`, `persons_on_property_exterior`: included here because dashboards read them.

Lovelace occurrences (counts of the entity-id string per `.storage/lovelace.<name>`; live in the sidebar: `ura-v6`, `ura-v7`, `ura-v8`; the rest are retired-but-registered):

| Entity (trust view) | ura_v8 | ura_v7 | ura_v6 | ura_v5 | ura_v4 | ura_v2 | ura_diagnostics |
|---|---|---|---|---|---|---|---|
| `sensor.universal_room_automation_persons_in_house` | 13 | 12 | 1 | 2 | 2 | | |
| `sensor.universal_room_automation_identified_persons_in_house` | 2 | | | 1 | 1 | | 2 |
| `sensor.universal_room_automation_unidentified_persons_in_house` | 1 | 1 | 1 | | | | 1 |
| `sensor.universal_room_automation_total_persons_on_property` | 2 | | 1 | | | | 1 |
| `sensor.universal_room_automation_persons_on_property_exterior` | 1 | | 2 | | | | |
| `sensor.universal_room_automation_unidentified_persons` (house) | | | 3 | 4 | 4 | | |
| `binary_sensor.universal_room_automation_unexpected_person_detected` | 1 | 1 | 1 | | | | |
| `binary_sensor.universal_room_automation_census_mismatch` | 3 | 3 | 1 | 8 | 8 | | |
| `sensor.universal_room_automation_census_confidence` | 3 | 1 | 3 | 11 | 11 | 1 | |
| `sensor.universal_room_automation_census_validation_age` | 2 | | 1 | 4 | 4 | | |
| `sensor.zone_*_guest_count` | 19 | | | | | | |
| `sensor.zone_*_identified_persons` | 10 | | | | | | |
| `sensor.ura_presence_coordinator_people_home_census` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `binary_sensor.ura_presence_coordinator_visitors_present` | 1 | | | | | | |
| `sensor.ura_security_coordinator_outside_unidentified_people` | 1 | | 1 | | | | |

`ura_v8` cards by view (entity-string hits in the view's JSON): **Now** 1 (`persons_in_house`); **People** `persons_in_house` 3, `identified_persons_in_house` 3, `total_persons_on_property` 2, `census_mismatch` 2, `unexpected_person` 1, `visitors_present` 1, `zone_*_guest_count` 1+; **Rooms** `persons_in_house` 3, `zone_*_guest_count` 2. The headline "people" count is on `ura_v8` Now + People; the zone guest cards are on `ura_v8` Rooms and People.

PWA (two local copies of the same tab; I did not determine which one is the served build):
- `~/Code/ura-dashboard-pwa/src/components/tabs/Presence.tsx` (repo HEAD 6927f65, 2026-08-18): constants `:37-41` = persons_in_house, identified_persons_in_house, unidentified_persons_in_house, total_persons_on_property, persons_on_property_exterior; read at `:293-297`; headline card `:369` (`personsInHouse`, sub `:371-372` identified / unknown), property card `:377-379` (`totalProperty`, `exterior`, `personsInHouse`). `Security.tsx:152` text "When census drops to 0" (display string, no entity). `sensor.ura_security_coordinator_security_authorized_guests` (`Security.tsx:41`) is not a census entity.
- `~/Code/universal-room-automation/dashboard-v3/src/components/tabs/Presence.tsx` (last commit 4551da3a, 2026-11-09): same constants `:37-41`; reads `:285-288`; headline `:339`, property card `:347-349`. The census plan's path `dashboard-v3/src/components/tabs/Presence.tsx` resolves here. `src/_v3archive/tabs/PresenceTab.tsx` also matches (archive).
- No reference to `unexpected_person`, `census_mismatch`, `visitors_present`, `zone_*_guest_count` in either PWA.

HA-side YAML (`automations.yaml`, `scripts.yaml`, `configuration.yaml`, `packages/`): **no** reference to any of these entities (grep returned nothing). Python-side readers of `persons_in_house` state (presence boot seed, `CensusMismatchSensor`) are in the plan, not re-surveyed.

Repoint list for F-LEAD (if the operator keeps the plan): `ura_v8` Now headline + People headline + the two People identified cards (`ura_v7` and `ura_v6` are in the sidebar too and carry 12 and 1 hits); PWA `Presence.tsx` `:369` and `:377` in whichever copy is deployed. Everything else (census_mismatch, unexpected_person, visitors_present, zone guest counts, exterior) stays trust per plan §3.6.

## Not done / unknown

| Item | Status |
|---|---|
| (iv) D0a on Luna | blocked: needs operator ok for 4 paid calls (above) |
| (iii) true wrong-event rate | proxy only; real grading needs frames (~97 calls) or operator time |
| (v) 14-day latency | recorder retention 7 d; 22 of 29 AWAYs measured |
| (vi) F on its real input (snapshot + latest frames) and on Luna | not measured; D0-V frames came from clips and gpt-4o-mini |
| (vi) levers L3 / L4 | need paid calls; L1 / L5 clip completeness for an in-progress event UNVERIFIED |
| (ii) `camera_input_dark` history; Tier-1-only edges | not recoverable offline; all-room edges used |
| (viii) Protect p99 | no URA producer; only a memory-noted 40-80 s |
| (ix) which PWA copy is served | not determined |

## Files

- This audit: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_crossing_vision_p2_d0_2026_11_14.md`
- Scratch data and inline scripts (not in repo): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/p2/` (`snap.txt`, `occ.txt`, `pee.txt`, `hsl.txt`, `away_ep.txt`, `person_states.txt`, `lat.json`); fixtures reused from `.../scratchpad/w/` and `.../scratchpad/cv/`, `.../scratchpad/v/`.
