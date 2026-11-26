# AUDIT: named-notice "drop" (read-only, 2026-11-26 ~14:30 CST)

Answer: no regression found. Naming is gated by identity_confidence >= 0.75, and a single-camera face leg scores 0.6.
The "fell from ~40% to 20%" comparison is unsupported: notification_log only starts 2026-10-27, so no 10-16 notice baseline exists.
Named share ran ~5-10% on 10-27..11-13 and about 20% now.

## Producer/consumer
- Producer: `_resolve_egress_face_identity_ex` (transit_validator.py:1890) -> person_id + identity_confidence.
  `egress_identity_tier_labelled` (:146-179): 2 legs on distinct cameras = CONFIDENCE_HIGH (0.9); >=2 on one camera = BOOST; 1 leg = CONFIDENCE_MEDIUM (0.6).
- Consumer: `_arrival_departure_notify` (:3422-3480), called at :2696 right after the bus fire.
  Names only if (a) an S1 edge anchor has confidence >= 0.75 (verb forced "arrived"), or (b) person_id and identity_confidence >= CONSUMER_CLASS_MIN_CONFIDENCE[notification] = 0.75 (const.py:7470). Else "Someone".
- The DB column person_id (person_entry_exit_events) has NO threshold, so "crossing has person_id" and "notice named" are different gates. The vetoes (direction-aware away veto, provenance, pair guard) act in the resolver or anchor, not in the notify.
- Anchor not-anchored reasons (7d): provenance 70, no_live_face_legs 59, direction 50, no_own_edge 10, partner_blocked 1.

## Cross-tab (11-19..11-26; approximate join: egress_identity_outcome episode to presence notice, -5..+120 s)
Identified crossings (slug set), entry/exit:
- conf 0.6 (single face leg or BLE .72): ~51 matched or unmatched with no notice, 37 notice "Someone", 7 named (anchor path).
- conf >= 0.75 (0.9 two-camera face, 0.95 ble+face): 17 named, 1 "Someone".
- vetoed (slug known, person_id NOT attached): 6 "Someone", 18 no notice.
- no_leg / abstain / ambiguous (no slug): ~34 "Someone", 3 named (anchor).
Provenance mix of identified crossings: face@0.6 = 86, face@0.9 = 20, ble@0.72 = 10, ble+face@0.95 = 2, none = 24.
=> ~75% of identified crossings score 0.6, below the 0.75 bar, so they get "Someone".
Join caveats: 51 crossings had no matching notice, and 75 notices had no matching crossing. Cause unknown (NM dedup/cooldown or timing; not investigated).

## Why attach rose while named fell/flat
Attach (person_id column) rose via single-leg 0.6 faces, which pass no notify gate. The notify gate needs a second camera or the S1 anchor.
S1 anchored path fires 0 times ("anchored" never appears in edge_anchor_reason).

## Change that did it
None found. Commits to transit_validator.py since 10-10 that touch notify: 6b0401670 (11-17 S1 anchor), 07d205532 (11-20 verb "came in" vs "arrived"; text only, no naming change).
Falsifier run: `git log -S` on const.py shows the notification 0.75 entered only in 6b3b68911 (11-13, RA3), a refactor of the former ARRIVAL_NAME_CONFIDENCE_THRESHOLD = 0.75 (value unchanged). Threshold is the same before and after 10-16.

## Guest angle
Hypothesis "all 51 person_arrival rows are house_state=guest" is FALSE. memory_episodes person_arrival attrs.house_state, 7d: home_day 19, away 9, guest 9, home_evening 7, sleep 6, home_night 1; each equals house_state_log at that timestamp.
house_state_log 11-19..11-26: guest 23.7 h of ~168 h (14%); it cycles (e.g. 11-26 04:05 home_night, 12:03 guest). Not stuck.
Nothing in the notify reads house_state (:3422-3480).

## Fix candidates
1. Tier 1/2 policy: for notification class name at tier MEDIUM when the person's own phone corroborates (reuse anchor path; fix the "no_live_face_legs"/"provenance" reasons). Needs operator decision since it changes the 0.75 doctrine.
2. Tier 1 (display only): "Someone (probably Jaya)" hedge at 0.6. Falsifies no doctrine (named stays >= 0.75).
3. Tier 2: second-camera corroboration window widening to lift single legs to 0.9.
