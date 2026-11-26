# AUDIT: identity arc gates re-measured 2026-11-26 (read-only)

Run 2026-11-26 13:25-13:45 CST. DB timestamps are UTC. Source: `ssh ha sqlite3 /config/universal_room_automation/data/universal_room_automation.db`, window = last 7 d (11-19 ~13:00 CST to now).
Read: ARC_identity_vision_census_map.md s4a, AUDIT_v6_milestone_candidates.md (10-16), kanban cards (grep).

| Gate | Threshold | Last recorded | Now | Verdict |
|---|---|---|---|---|
| Egress person_id attach (person_entry_exit_events, person_id non-empty) | rising; need ~complete for unnamed!=guest | 10-16: 27% 14d / 33% 7d | 7d 135/213 = 63.4% (entry 61/101 = 60.4%, exit 74/112 = 66.1%); prior 7d 75/207 = 36.2%. Residents only: jaya 98, oji_udezue 18, ezinne 8, ziri 11, unnamed 78 | HOLDING (improving), still 37% unnamed |
| Arrival/departure notifications named (notification_log, presence) | named majority | 10-16: ~40% named | 7d: 168 rows, 134 "Someone", 34 named (Jaya 32, Oji 2) = 20% | SLIPPING (attach 63% but named 20%; unreconciled gap, naming gate 0.75 / S1 partner_blocked likely, unverified) |
| F-K ledger known-time >= 25% / 7d | 25% | 11-24: 14.7-16.4% FAIL | 7d: last anchor 11-20 00:10 UTC, last applied term 11-20 23:26 UTC, since then 0 anchors, all terms applied=false reason=unknown (185 of 199 terms; latest 11-26 19:04 UTC). Known ~11-19 16:57 CST -> unclean restart 11-20 20:27 CST only, ~16% | SLIPPING / FAIL (unchanged); CROSSING-LEDGER-RESTART-RESTORE-1 awaits operator PICK |
| Restart discipline (<=1/day ~10:00) | | 7 restarts in 11-17..24 | recorder starts 11-19 14:14, 11-20 20:27 (no stop = unclean), 11-20 22:49, 11-22 21:49, 11-24 22:39, 22:46, 23:30 CST (7 in 7 d, none at 10:00; converted from UTC events in home-assistant_v2.db) | NOT KEPT |
| Row 6 score vision direction + names (due 11-20 18:00) | P3-D6 bar (Wilson LB) | 11-18: tracker 23/36, bar unmet; names unscorable (0 grades with who) | No later score found on cards or AUDIT_* (newest AUDIT is 11-19) | OVERDUE, nobody ran it |
| Row 3 person_profiles (v6.0.0 blocker) | profiles stored | 11-20: none | Exist now: Coordinator Manager entry `person_profiles` (modified 2026-11-26 07:07 CST) for ezinne, jaya, oji_udezue, ziri with rooms_bedroom/bathroom set, but auto_music=false and auto_scene=false for all four | CHANGED: blocker half-cleared; engine still inert until auto flags on + live MA test |
| Row 5 S1 names (anchored arrival) | anchored + name score | 11-24: 0 anchored rows, bounded by 12-01 | egress_identity_outcome 7d: attached 104, direction_ambiguous 107, no_leg 51, vetoed 24, abstain 7, ambiguous 7, attached_ble 6, ble_face_disagree_ble_wins 4, ble_face_corroborated 2. edge_anchor_reason: provenance 70, no_live_face_legs 59, direction 50, no_own_edge 10, partner_blocked 1; no "anchored" | NOT MEASURED (S1 anchored path still 0 fire) |

Zero-fire / low-fire: person_arrival episodes 51 in 7d but none carry source/person fields in the keys I queried (all arrivals logged house_state=guest, e.g. ziri 11-26 15:46 UTC); S1 "anchored" 0; face-arrival and sightings producers NOT queried (no clear table located); arrival engine inert (auto flags false).

Unknown: why named notifications fell to 20% while attach rose; whether recorder-event restart list is complete.
