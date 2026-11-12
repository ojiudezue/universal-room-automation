# Live validation: v5.107.1 to v5.107.6 (combined release)

Validated 2026-11-09 10:37 CST by ura-prober (read-only). HA stopped 10:32:02 CST, API up 10:32:54 (state NOT_RUNNING), state RUNNING 10:35:45.
`/config/custom_components/universal_room_automation/manifest.json` reads `"version": "v5.107.6"`.
Sources: HA REST `/api/states`, WS `repairs/list_issues`, supervisor core logs (`ssh ha`, `http://supervisor/core/logs`, post-10:32 slice, 3237 lines), URA DB via `ssh ha sqlite3 ...?mode=ro` (timestamps UTC; restart = 16:32 UTC).

Log limit: URA INFO lines are not emitted at this house's log level (0 `INFO ... universal_room` lines in the post-restart slice), so INFO-based criteria are a log-read gap, not a FAIL.

## Global checks
| Check | Result | Evidence |
|---|---|---|
| URA setup errors / tracebacks since restart | PASS (none) | 0 ERROR/CRITICAL lines from `custom_components.universal_room_automation` after 10:32:02 (the only 3 at 10:32:02.151-.176 are the pre-restart shutdown "write worker is closed"). 19 tracebacks in slice; none reference URA (mazda_cs, music_assistant, etc.). URA WARNINGs are known/benign: device_registry deprecations (`_devices.py:287`, `camera_resolver.py:567`, `__init__.py:5184/5262`), boot "sensors unavailable" holds, `no _2 sibling` for madroneptultra/sonoffwindow, Coverage rating INCOMPLETE at 10:35:07 (post_restart). |
| External-URL check ran | PASS by absence + probe, run itself not directly observed | Wired at `__init__.py:2393-2394`. No WARNING `External URL ... not reachable` in the log; WS `repairs/list_issues` (43 issues) has no `external_url_unreachable` and no URA-domain issue. Falsifier: a GET from the HA host to `https://madronehaos.phalanxmadrone.com/manifest.json` returns 200 in 0.109 s, so a real check would pass. The check logs nothing on success (INFO invisible), so "ran" is inferred, not seen. HA `external_url` = `https://madronehaos.phalanxmadrone.com`. |
| `face_source_*` on `sensor.universal_room_automation_persons_in_house` (state 1, updated 16:36:54Z) | see below | `face_source_registry_hits=14`, `face_source_pattern_fallbacks=0`, `face_source_pattern_fallback_stems=[]`, `face_source_device_derived_reads=13`, `face_source_skipped_person_sensors=0`, `face_source_skipped_cameras=[]`, `face_producer_health=live`, `source_agreement=both_agree`, `face_lookup_missing_count=27`, `face_recognized_persons=[]`. `face_source_device_derived_cameras` = 12 ids, all `*_person_occupancy_2`: armcrest, back_yard, doorbell_lite, front_door_aerial, front_side_ptz, g5_bullet, garage_a, hot_tub, madrone_g6_entry, playroom, pool_equipment, reolinkstudybporchptz. The entity registry holds 17 enabled `_person_occupancy_2` sensors; the 5 not listed on this tick are armcrestash41b, madrone_g6_entry_package, rear_ptz, upstairs_hall, utilities_ptz. Counters are lookup counts, so absence here is not proof of non-reading (note: README says upstairs_hall is not in the interior list). |

## v5.107.1 FACE-SOURCE-REGISTRY-DISCOVERY-1
| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| L1 | registry hits > 0, no Frigate fallback stems | PASS | hits 14, fallbacks 0, stems `[]` |
| L2 | derived cameras only `*_person_occupancy_2`; skipped == 0 | PASS | 12 derived, all `_2`; skipped 0, skipped_cameras `[]`; no bare id in list. 12 of 17 on this tick (see above) |
| L3a | S6 exterior face does not corroborate lone playroom count | PENDING | needs fresh exterior face + lone playroom count; `source_agreement` is `both_agree` now |
| L3 | guest count = count-1 only with fresh playroom face | PENDING | `sensor.playroom_last_recognized_face_2` = Unknown; `area_raw_max_pre_cancel` = {} |
| L4 | `contributor_engines` says `frigate`; confidence values within known set | PENDING | 0 `person_entry_exit_events` rows since 16:32Z; `last_attach` null. Pre-restart rows are 0.8/0.9 (0.8 is not in the README's 0.6/0.72/0.75/0.9 list, but those rows predate this release so not attributable) |
| L5 | INFO `D2 frigate last_camera map built: 6 entries` | PENDING (log gap) | string at `camera_census.py:3689`; INFO not visible in journald slice |
| L6 | alias field present, empty; person_id subset | PARTIAL / PENDING | `CONF_FACE_NAME_ALIASES` at `const.py:3363`, default `[]`; no URA entry has an alias set in `.storage/core.config_entries`. Options-flow UI render not inspected; no new egress rows |
| L7 | no `Camera face arrival:` INFO for the 17 cameras | PENDING (log gap) | INFO not logged. Indirect: no `ura_activity_log` face-arrival row since restart (the only arrival row is `hvac pre_arrival person.oji_udezue source=geofence` 16:35:48Z, not a camera_face) |

## v5.107.2 SNAP-1 internal URL
| Criterion | Verdict | Evidence |
|---|---|---|
| New Frigate-event-named file after a Frigate-leg alert | PENDING | Newest `/media/ura/snapshots` files after 16:32Z are all live-grab shaped (`rear_ptz_1794242178_b72fc6.jpg` etc., from 10:35-10:36 CST). Frigate-shape files exist (7 total, newest `utilities_ptz_1794238266.899886-jbjhk5.jpg` = pre-restart); none post-restart. Whether the post-restart front_side_ptz / utilities_ptz captures should have taken tier 1 is unknown (no INFO ledger). Falsifier needed: a Frigate-leg alert (e.g. pool_equipment, g5_bullet) after restart. |
| INFO ledger `engine=frigate_event` | PENDING (log gap) | INFO not visible |
| Pushover/WA links keep external URL | PENDING | no perimeter notification since restart (`notification_log` max 16:33:34Z = LOW EVSE) |

## v5.107.3 External-URL self-check
| Criterion | Verdict | Evidence |
|---|---|---|
| No Repairs issue and no WARNING after restart with the corrected URL | PASS | see Global checks (repairs list, log scan, 200 probe). Provoke-a-failure path not exercised (would change settings). |

## v5.107.4 Lock regime face corroboration
| Criterion | Verdict | Evidence |
|---|---|---|
| `held` INFO lines only for faces without an edge | PENDING (log gap; no face arrival yet) | 0 camera_face arrivals recorded; INFO invisible |
| Car arrival (GPS not_home to home) still unlocks, `last_action=release` | PENDING | no arrival since restart. `person.oji_udezue` went `not_home` 16:35:50Z (not an arrival). `lock.master_bedroom_lock` unlocked since 16:33:01Z, garage `lock.ratgdov25i_dbfe2a_lock_remotes` / `lock.konnected_f0f5bd523b00_lock` unlocked since 16:33:10Z: boot-time state, within the 600 s boot exclusion; cause not investigated |
| arriving_signal release after camera_face has a same-person edge | PENDING | no camera_face dispatch |
| Perimeter D10.5 `gate_decisions_by_camera` still reports `face+ble` / `face+person_tracker` | PENDING | attribute not found on any entity in `/api/states`; no alert since restart |
| In-suite only: 10-24 mislabel shape | n/a | as README |

## v5.107.5 Identity follow-up
| Criterion | Verdict | Evidence |
|---|---|---|
| Follow-up arrives after unknown dual-role page + ID within 90 s | PENDING | 0 `notification_log` rows titled `%Identified%`; no perimeter alert since restart (`sensor.universal_room_automation_last_perimeter_alert` = unknown) |
| No follow-up after LOW/demoted | PENDING (vacuous: 0 rows) | same |
| Every Identified row acknowledged = 1 | PENDING (vacuous: 0 rows) | same |
| Switch present | PASS (supporting) | `switch.ura_perimeter_identity_followup` = on, last_changed 16:33:37Z |

## v5.107.6 Entry areas from egress tracker
| Criterion | Verdict | Evidence |
|---|---|---|
| Garage face + Bermuda move into garage/neighbour releases, no fail-safe hold | PENDING | needs an arrival; none since restart |
| Doorbell D10.5 + BLE move into neighbour records `demoted = True` | PENDING | needs a doorbell perimeter alert |
| (supporting) no URA errors from the new lookup | PASS | no URA ERROR/traceback; the old failure mode was swallowed AttributeError, so absence of errors is weak evidence |

## Summary
PASS: global (no URA errors), external-URL check outcome, v5.107.1 L1 and L2, v5.107.3. PENDING (needs events or INFO logs): everything door/arrival/alert-driven, and L5/L7/ledger criteria which are a log-read gap. FAIL: none. Re-run L3/L3a/L4, v5.107.2 file shape, v5.107.4-6 after the next door arrival or perimeter alert; the DB queries above are the one-shot dispositions. Setting the URA logger to INFO is the only way to close L5/L7/ledger checks from logs, and I did not touch it.

Note: probing overwrote `p.json` and created `states9.txt`, `q9.sql` in the shared session scratchpad (not repo files).
