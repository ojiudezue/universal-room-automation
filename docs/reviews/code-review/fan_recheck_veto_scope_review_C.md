# Review C: fan recheck veto scope (JAYA-FAN-STILL-PHANTOM-1), test authority via per-site source mutation

Commit under review: f2bdff61a (base b716228e9). Suites run per mutation: `test_fan_recheck_mode2_cycle.py` + `test_fan_recheck_observability.py` (baseline 121 passed). One site mutated at a time in `presence_fan_recheck.py`, `__pycache__` cleared and `PYTHONDONTWRITEBYTECODE=1` each run, file restored in `finally`, `git status` clean afterwards.

Docs: I read the presence STATE_OF_PLAY fan-recheck section (§3 Fan pause-recheck and the efficacy notes) and the plan, not all 694 lines of the state-of-play doc. The sensor-fleet doc was not read, because this review does not touch sensor classification.

## Site table

| # | Site / mutation | Result | First RED test(s) |
|---|---|---|---|
| M1 | eligibility sleep predicate back to bedroom-only | RED (8) | test_high_still_risk_rooms_refused_in_trust_states[*-media_room] |
| M1b | eligibility sleep veto removed | RED (21) | ...refused_in_trust_states[*-bedroom] and others |
| M2 | `_still_armed_eligible` predicate back to bedroom-only | RED (1) | test_sleep_begins_during_arm_delay_aborts_before_pause_media_room |
| M2b | `_still_armed_eligible` sleep abort removed | RED (2) | ..._bedroom, ..._media_room |
| M3 | mid-flight sleep cancel removed | RED (4) | test_sleep_edge_mid_pause_restores_fan_on, test_sleep_edge_mid_armed_cancels_to_cooldown |
| M3b | mid-flight predicate bedroom-only | RED (2) | same two, media_room param |
| M3c | mid-flight cancel ignores FAN_TRUST_STATES (cancels by day) | RED (1), incidental | test_l1_scanner_area_room_cancels_mid_flight only. No test directly pins "bedroom/media by day is NOT cancelled mid-flight". |
| M3d | mid-flight outcome VACATED instead of OCCUPIED_CONFIRMED | RED (2) | test_sleep_edge_mid_pause_restores_fan_on |
| M3e | `reason=` kwarg passed to `_cancel_and_restore_async` changed | **GREEN** | none |
| M3f | activity-log `details.reason` | **GREEN** | none |
| M3g | activity-log `action` | **GREEN** | none |
| M3h | activity-log description | **GREEN** | none |
| M3i | missing `return` after the sleep cancel (falls through to motion/L1, double cancel) | **GREEN** | none |
| M3j | ordering: sleep check after motion | **GREEN** | none |
| M3k | ordering: sleep check after L1 | **GREEN** | none |
| M4 | re-insert Tier-0/2 `high_still_risk` veto | RED (12) | test_high_still_risk_rooms_equivalent_to_generic_by_day |
| M5 | re-insert Tier-1 L2 `high_still_risk` | RED (5) | test_tier1_bedroom_l2_allowed_still_rejects_l2, test_tier1_media_room_l2_allowed_authorizes_l2_by_day, test_veto_high_still_risk_counts |
| M6 | live-path L1 uses room-only (drop `_l1_persons`) | RED (4) | test_l1_scanner_area_room_vetoes_by_day |
| M7 | mid-flight L1 uses room-only | RED (1) | test_l1_scanner_area_room_cancels_mid_flight |
| M8 / M8b | `_l1_persons` ignores scanner areas / wrong config key | RED (5) | scanner_area tests |
| M9 | normalized-area fallback (`lower().replace(" ","_")`) removed | **GREEN** | none |
| M10 | self-area skip (`seen={room_name}`) removed | GREEN, equivalent mutant | The persons dedupe makes it behavior-identical. |
| M10b | `seen` check removed entirely | GREEN, equivalent mutant | Same reason. |
| M11 | persons dedupe removed | GREEN, near-equivalent | Both callers use truthiness only. Only a direct return-value assert could catch it. |
| M12 | `scanner_areas` as `str` handling removed | **GREEN** | none |
| M13 | non-dict `_area_id_to_room` guard removed | RED (1) | test_l1_persons_ignores_non_dict_area_map |
| M14 | falsy-area `continue` removed | GREEN, equivalent mutant | `area_map.get(None)` returns None, and `str(None).lower()` is "none", which is not mapped. |
| M15 | live L1 layer stamp (`set_ladder_layer(LAYER_L1)`) removed | RED (4) | test_l1_scanner_area_room_vetoes_by_day |
| M16 | mid-flight L1 layer stamp removed | RED (1) | test_l1_scanner_area_room_cancels_mid_flight |
| M17 | inert probe uses `_LiveSink` (counter mutation) | RED (2) | test_is_recheck_eligible_d2_defer_bedroom_media |
| M19 | `_l1_persons` drops own-room persons | RED (9) | test_high_still_risk_rooms_l1_vetoes_by_day |
| M20 | `HIGH_STILL_RISK_ROOM_TYPES` drops media | RED (11) | refused_in_trust_states[*-media_room] |
| M21 | `sleep_state` veto reason renamed | RED (19) | refused_in_trust_states and others |

## Findings

- **MEDIUM-1 (M3i, #62 hollow coverage).** The missing `return` after the mid-flight sleep cancel is untested. Repro: PAUSED bedroom, `house_state=home_night`, `motion_detected=True`. Without the `return`, the code runs `_cancel_and_restore_async` twice and schedules two `_restore` tasks (double fan restore and a duplicate outcome row). No test combines sleep with motion or L1 mid-flight. Fix: a PAUSED test with sleep + motion (and L1) asserting `len(fc.restore_calls) == 1`. That one test also kills M3j and M3k if it asserts the reason on the ARMED/mem row or the activity row.
- **LOW-2 (M3e-M3h, M3j, M3k).** The sleep cancel's observable record is unpinned: the `reason="sleep_state"` kwarg (it feeds `_emit_aborted_mem` on the ARMED path), the activity-log `action`/`reason`/description, and the check order against motion and L1. The restore outcome is identical either way, so the damage is mislabelled analytics (a sleep cancel recorded as `motion` or `ble_l1`). Fix: assert `_emit_aborted_mem`/activity-log payload `reason == "sleep_state"` in the existing sleep-edge tests, plus a sleep + motion case that expects `sleep_state`.
- **LOW-3 (M9, M12).** The `_l1_persons` fallbacks have no test: the normalized-key lookup (e.g. area "Jaya Bathroom" mapped under "jaya_bathroom") and `scanner_areas` stored as a bare string. Fix: two direct `_l1_persons` unit tests, as `test_l1_persons_ignores_non_dict_area_map` already does for the guard.
- **LOW-4 (M3c).** "Bedroom/media by day is not cancelled mid-flight" is pinned only incidentally, through the L1 mid-flight test. Add an explicit bedroom `home_day` PAUSED case with `_evaluate_cancellation_during_tick` expecting no cancel.
- Equivalent or near-equivalent mutants (M10, M10b, M11, M14) are not findings. They show the self-area skip and dedupe are redundant guards, not load-bearing.

## Builder-claim cross-check

The load-bearing eligibility, twin, live-L1, mid-flight-L1, inert-parity, scanner-area and constant-membership sites are all authoritative (RED on neuter). The gaps are all in the review-fix-up additions (the mid-flight sleep-cancel's secondary effects and the `_l1_persons` fallbacks), which were added without a test pinning them.

## Verdict: FIX-REQUIRED (small)

Must fix: MEDIUM-1 (the M3i double-cancel test), which also covers the activity-log and ordering rows when asserted as above. LOW-2 to LOW-4 should be fixed in the same pass (about 30 LoC of tests, no production change). No production defect was found; M3i is an untested regression guard. The production code as it stands holds.
