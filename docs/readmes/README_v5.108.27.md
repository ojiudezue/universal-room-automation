# v5.108.27: crossing vision Phase 3, first set (P3-D1, P3-D5, P3-D8) + P3-D0 knobs

Cards: VISION-P3-FIRST-SET-1 (this release; child of VISION-AMBIGUOUS-CROSSINGS-1, which stays open for P3-D2/D3/D10/D11). Work items: VISION-AMBIGUOUS-CROSSINGS-1 (P3-D8, P3-D5, P3-D1), DOOR-VISION-GROUP-UNDERCOUNT-1 (max_tokens 4000,
cap 93 from the P3-D0 volume probe). Parent: VISION-CROSSING-ANALYSIS-1.
Plan: `docs/planning/PLANNING_crossing_vision.md` Phase 3 (50bffd62). Probe:
`docs/planning/AUDIT_crossing_vision_p3_d0_2026_11_15.md`. Branch `feature/crossing-p3-first`.
Tier: P3-D1 Tier 1, P3-D8 Tier 2, P3-D5 Tier 2-DB; reviewed as Tier 3 (four framings + G).

Shadow / display only. Nothing here changes AWAY, house state, the census trust view, any actuator or any
`person_id`. The ledger reaches the census only through `census_tick`, and its awareness output is display-only
while `CROSSING_VISION_AWARENESS_VISION_LEADS` is False.

## What ships

- **P3-D1: error text on error rows.** `crossing_vision_shadow` rows with `outcome = error` carry `error`:
  llmvision's error text, with secrets scrubbed (`key=` values in any case, `sk-` keys and `Bearer` tokens), then
  cut to `CROSSING_VISION_ERROR_TEXT_MAX_CHARS` (200). No text gives None. Other rows have no `error` key.
- **P3-D5: restart-safe daily cap.**
  - New read-path DAO `Database.count_memory_episodes_by_type_ended_between`, counting by `ended_at` (call time)
    over today's local-day UTC bounds. It returns `(count, ok)`, so a failed read is never mistaken for an empty
    day.
  - At setup the listeners register at once, with the counter held at the cap: crossings are recorded as
    `skipped_cap` and no calls are made.
  - A tracked background task then counts today's call rows. Each read is bounded by `CAP_REHYDRATE_TIMEOUT_S`
    (30 s) and retried once after `_RETRY_S` (60 s).
  - If both reads fail, the counter stays at the cap until local midnight and a LOW page fires
    (`crossing_vision_cap_rehydrate_failed`).
  - The new attribute `crossing_vision_cap_rehydrate` is unrecorded. Teardown cancels the task.
  - **Cap default 93** = ceil(62 × 1.5), sized by P3-D0 (a); the maximum stays 200. An operator-set Number value
    still wins.
  - No index was added: the live `memory_episodes` table has 18,855 rows and the count query takes 0.01 s.
- **P3-D8: the anchor honours the room's stuck exclusion** (operator yes 2026-11-15).
  - A Tier-1 input that reads `on`, has no stream view, and is excluded by its room under a stuck client no longer
    holds the empty-house anchor. The stuck clients are `CROSSING_VISION_ANCHOR_STUCK_CLIENTS`:
    `p22_continuous`, act-mode `chatter` and promoted `stuck_dutycycle`.
  - The rule is read through the new room getter `camera_input_room_stuck_excluded` and the house wrapper
    `camera_stream_health.input_room_stuck_excluded`.
  - These still hold:
    - a dead input (unavailable, unknown, or any stream view);
    - a duty-cycle label that was never promoted;
    - shadow-mode chatter;
    - an input excluded only by the camera-stream client.
  - An input listed in several rooms is released only when every room that lists it excludes it.
  - **P22 sleep gate (review D-M1, conservative default; the operator may override):** a `p22_continuous`
    exclusion does not release while the house state is in `CROSSING_VISION_ANCHOR_P22_HOLD_STATES` (sleep,
    waking, home_night).
  - It also does not release while the house state is unknown (no manager, no presence, empty, or the read
    raises). The gate fails closed.
  - Kill switch: `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK`. Ignored inputs are listed as `held_ignored_stuck`
    (with a count) in the `crossing_ledger` diagnostics and named on the `crossing_ledger_anchor_zero` page.
- **max_tokens 4000** (`CROSSING_VISION_MAX_TOKENS`, rung 1).
  - At 1500, llmvision returned empty text on all 6 calls for the two large-group clips (18:43 and 18:59). At 4000
    those clips returned 5 and 8 people.
  - An empty reply is recorded as `refused`, with no count and never 0.
  - Cost: more output tokens, on large groups only. P3-D0 measured a p50 of about 25-30 s on 8 frames; the live
    path sends 4 frames. This stays within `TIMEOUT_S` (90 s).

## Reviews

| Review | Verdict | Outcome |
|---|---|---|
| A+B (local correctness, lifecycle) | SHIP, 3 LOW | A1: call-time gate reads the held counter (fixed). A2: undercount residuals (named in the plan). A3: index measured, not needed. |
| D (adversarial) + G (goal) | SHIP on correctness; goal not met alone | D-L3 scrub (fixed). D-M1 P22 sleep gate + unknown fails closed (fixed). D-L1 all-rooms fold (fixed). D-L2 residual (named). G-1 / G-2: see below. |
| C (per-site source mutation) | FIX-REQUIRED, tests only | 117 mutations, 88 RED. All 18 non-equivalent GREEN rows (1 MEDIUM, the rest LOW) are now RED after the test fix-up. The remaining GREEN rows are equivalent mutants. |

## Not delivered (and why)

- **The anchor is not yet unblocked on the live house (G-1, G-2).** On 11-15 P3-D8 alone would not have released
  it. Three prerequisites are planned in `PLANNING_stuck_sensor_truth.md`:
  - the upguest ZV's P22 timer is reset by 1.8 s off pulses (K2, off-pulse debounce);
  - the anchor's rising-edge feed ignores room exclusions (stuck-aware edge filter, P3-D8b);
  - the media room's Meross bit (chatter mode or reclassification).
- **P3-D2, D3, D4, D6, D7, D9a, D9b:** later Phase 3 builds, not in this set.
- **Named residuals:**
  - A still, phone-less guest who is awake for more than 4 h outside sleep, waking and home_night is P22-excluded
    and the anchor drops them. Effect is display only today.
  - Calls that are not counted on restart: calls in flight at stop, row writes that fail and are swallowed, and a
    call that raised before its row was written. The undercount is at most `MAX_CONCURRENT` plus unflushed rows per
    restart.

## Validated 2026-11-15 (restart 18:5x CST, house home_evening)

| Criterion | Result | Evidence |
|---|---|---|
| Installed and booted | PASS | manifest v5.108.27 on disk (78 entries), `camera_input_room_stuck_excluded` present in coordinator.py; `update.universal_room_automation_update` installed_version v5.108.27 |
| P3-D5 restart-safe counter | PASS | after restart `crossing_vision_today.calls` = 2 on `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`; DB today (local day) has exactly 2 call rows (`outcome=ok`) plus 2 `clustered` non-call rows. A RAM-only counter would read 0. `crossing_vision_cap_rehydrate` = `{state: ok, cap_hold: false, cap_rehydrate_failed: 0}` |
| Cap default | PASS | `number.ura_notification_manager_crossing_vision_daily_calls` = 93.0 |
| P3-D8 stuck exclusion | in-suite only | the house was home_evening and the ledger was `unknown` (boot) with `held` and `held_ignored_stuck` both empty, so no live case existed. Proven by 69 tests in `test_crossing_vision_p3_first.py` plus the orchestrator mutations: neutering the sleep hold turns 7 tests red, neutering the excluded return turns 12 red |
| P3-D1 error text | in-suite only | no error rows since boot |
| max_tokens 4000 | pending organic | no large-group crossing since boot; first one is the check (`ok`, not `refused`) |
| Logs | PASS | system log ERRORs since boot: 16, none from `universal_room_automation`, `crossing_vision` or `database` (WhatsApp, iCloud3, ESPHome satellites, Alexa, Bluetooth mgmt socket, Elk, Lepro, Philips lock, WiiM duplicate id) |

Boot note: the per-outcome breakdown (`ok`, `blank`, ...) restarts at 0; only `calls` is rehydrated, which is what the cap reads. Display only.

Not in this release: P3-D2 recording-window route, P3-D3 direction recorded, P3-D10/D11 tracker extension (all on VISION-AMBIGUOUS-CROSSINGS-1, waiting on operator grades). Full suite: candidate 22,788 passed with one order-dependent flake (`test_ec_savings_money.py::test_arbitrage_cycles_count_distinct_local_days`, passes alone on both trees); the opt-in drill run surfaced one stale pre-existing drill, recorded on BLE-LOCATION-QUALITY-1.

## Tests

`quality/tests/test_crossing_vision_p3_first.py` (69). On the merged branch these files pass, 743 tests with 1
skipped: the cycle files, the layer guard, the census trust golden test, camera stream health S1/S2, census
awareness, memory writer health, and the music-following repair test.

Layer guard: net Δ0. After the merge, `LAYER_ALLOWLIST_TOTAL` is 256 with 228 rows, identical to develop.
