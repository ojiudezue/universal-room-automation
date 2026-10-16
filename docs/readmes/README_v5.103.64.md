# URA v5.103.64: exit naming respects the door-naming switch; Last Person Exit shows late names

Card: EGRESS-EXIT-IDENTITY-BACKFILL-1 residual R1. Plan: `docs/planning/PLANNING_egress_exit_identity_backfill.md`. D0: `docs/planning/AUDIT_exit_backfill_d0.md` (backfill working, not regressed; R2 window widening parked: 12 recoverable/7.5 days, no single miss pattern ≥50%). Tier 1: review SHIP (`docs/reviews/code-review/exit_backfill_r1_review.md`, 2 optional LOWs). Deploy risk: **LOW**. Active after the next HA restart.

## What changed
- `switch.ura_name_people_at_doors` (CONF_EGRESS_IDENTITY_ENABLED) now also gates the BLE exit backfill: read fresh in the departure handler (before the cooldown is stamped) and again just before the DB UPDATE. Skips counted in `ble_exit_identity_disabled_skip_count` on `sensor.universal_room_automation_persons_in_house`.
- "Last Person Exit" re-reads the newest exit row when a backfill names it (newest row only, camera must match, timestamp unchanged, no re-notify, no census change). New rung-1 constant `LAST_EXIT_BACKFILL_REREAD_SLACK_S = 300`. The sensor's bus listener is now unsubscribed on removal (leak fix).
- Identity manual gains §4.3a "Exit backfill". README_v5.96.1 / v5.97.1 now carry their Validated tables.

## Tests
- 5 new tests (3 backfill switch, 2 display); each fails on develop. Mutation drills: 6/6 RED.
- Full-suite name-diff vs develop 53b3ecb8f: **CLEAN**, 0 NEW / 0 GONE (119 failed / 15018 passed vs 119 / 15013).

## Live acceptance
- **Live:** with the switch on, an organic exit backfill names the row and Last Person Exit shows the name within ~5 min of the not_home edge.
- **Live:** 0 URA ERRORs after restart.
- **Open:** row-level wrong-person spot check of 5 backfilled exits vs BLE history (from the v5.96.1 table) before closing the card.
