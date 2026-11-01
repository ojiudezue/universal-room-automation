# PLANNING — BLE absence grace (re-arm after a short flap) + BLE fleet fraction

**Cards:** BLE-LOCATION-QUALITY-1 (`measured_2026_11_01`) → D1; PERSON-BLE-WINS-OVER-STALE-GPS-1 (`residual_fleet_fraction_2026_10_24`) → D2.
**Operator approval:** both deliverables, 2026-11-01.
**Tier:** 2 (operator). Both deliverables touch presence trust paths; per the standing regression-prone policy the orchestrator may elevate to three framing-disjoint reviews. See §8.
**Mandatory reads done:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 795 lines, including the §10 corrections ledger and the gold-patterns index) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (all 50 lines), read completely before scoping. No claim in this plan re-asserts a §10 ledger item. HVAC is touched only as a downstream reader of room occupancy (evidence stamp); no HVAC code changes, so the HVAC state-of-play doc was not required.

---

## 0. Institutional context verified

### 0.1 Greps run and results (develop @ 284add37c)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| D1 admission site | REUSED: the BLE block in `coordinator._async_update_data` | `coordinator.py:4069-4270`; chain leg `coordinator.py:4152-4155` (`ble_allowed = self._last_occupied_state` under `BLE_CHAIN_HOLD_ENABLED`) |
| "Chain is currently held by BLE alone" marker | REUSED `self._ble_only_hold_since` | seeded only on a BLE-only admit `coordinator.py:4242-4243`; cleared on any body fire `:3944`, camera admit `:4052`, D2 demotion `:4495`, true vacancy `:4773`, override-vacant `:5181`, skip-first vacant `:5228`, fan-recheck release `:5699` |
| BLE hold cap (bleed bound) | REUSED as-is | `coordinator.py:4170-4211`, `CONF_BLE_HOLD_CAP_ENABLED`, `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` `const.py:1806`, `_get_ble_hold_cap_seconds` `coordinator.py:754` |
| Kill switch for BLE hold | REUSED `BLE_CHAIN_HOLD_ENABLED` | `const.py:649-655` (rung 1) |
| Absence-grace window constant | NEW `BLE_ABSENCE_GRACE_S` | `grep -n "BLE_ABSENCE\|BLE_REARM\|ble_grace" const.py coordinator.py person_coordinator.py` → no hits; no window in `config_flow.py` / `number.py` for BLE absence |
| Absence stamp field | NEW `self._ble_absent_since` | no existing per-room "BLE disappeared at" field (grep of `coordinator.py` for `_ble_*_since`: only `_ble_only_hold_since`) |
| D2 floor constant | REUSED `BLE_LEADS_MIN_ACTIVE_PROXIES` (30), demoted to legacy fallback | `const.py:261`; only production readers `person_coordinator.py:459` (decision) and `:504` (log). Tests: `quality/tests/test_person_gps_assistive.py` |
| D2 fraction / absolute floor / memory window | NEW `BLE_LEADS_FLEET_FRACTION`, `BLE_LEADS_ABS_MIN_PROXIES`, `BLE_LEADS_FLEET_MEMORY_DAYS` | `grep -n "FLEET_FRACTION\|PROXY_HIGH_WATER\|ABS_MIN_PROXIES" const.py person_coordinator.py` → none |
| Bermuda total proxy sensor | REUSED upstream entity, resolved by unique_id `BERMUDA_GLOBAL_PROXY_COUNT` | `~/ha-config/custom_components/bermuda/sensor.py:506` (value `len(coordinator.scanner_list)` `:511`); scanner list rebuilt from `self._manager.async_current_scanners()` `bermuda/coordinator.py:1496` (card cites :1484; installed copy has drifted 12 lines, same code). Active count unique_id `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT` `sensor.py:531` |
| Registry resolution helper | REUSED pattern `_resolve_proxy_entity_id` | `person_coordinator.py:446-455` |
| Persistence | REUSED HA `Store` + `async_delay_save`, ring pattern | `weather_manager.py:180-182` (`ura_dpm_apparent_high_ring`, a bounded ring persisted in a Store) is the closest prior art; also `hvac.py:962`, `manager.py:466`. No RestoreEntity / Number needed (value is not operator policy) |
| Diagnostics surface | REUSED log lines | `person_coordinator.py:502-506` (fleet-guard INFO), `:794-800` (armed/disarmed INFO) |

### 0.2 Prior planning docs consulted
- `docs/planning/PLANNING_presence_gps_assistive.md` (rev 3) — the BLE-leads rule, the 30 floor's rationale ("below measured p1 44, above every non-boot partial reading"), residual §9. Full read of §4.2-4.3 and §9.
- `docs/planning/PLANNING_ble_bleed_extend_corroboration.md` — origin of `_ble_only_hold_since` and the hold cap (A1 re-anchor). Skimmed for the anchor semantics.
- `docs/planning/AUDIT_presence_gps_assistive_consequence_replay.md` — skimmed (arm / dropout consequences).
- Card BLE-WARM-CREATE-1 history, as recorded in the block comment at `coordinator.py:4083-4151` (leg (b) deletion, Master Bathroom bleed incident 2026-08-10).

### 0.3 Memory bodies / cards pulled
- Card BLE-LOCATION-QUALITY-1 `measured_2026_11_01` (kanban.data.yaml:33268): 06:34 on 10-28 and 10-29, BLE-only hold, 8-11 s Upstairs Hallway blip, 27-30 min false vacancy; 10-30 survived because a radar was on.
- Card PERSON-BLE-WINS-OVER-STALE-GPS-1 `residual_fleet_fraction_2026_10_24` (kanban.data.yaml:33021).
- Memory `reference_sensor_fleet_classes`, `reference_presence_state_of_play`, `feedback_ble_config_is_tuned_check_before_asserting` (Jaya Bedroom borrows `jaya_bathroom` via `CONF_SCANNER_AREAS`; tuned on purpose, not touched here).

### 0.4 Code surveyed end-to-end
`coordinator.py` 3930-3950, 4030-4330, 4690-4778, 5150-5310, 5690-5705, 5835-5870; `person_coordinator.py` 220-232, 380-540, 640-650, 785-810, 2015-2045; `const.py` 245-263, 645-660; Bermuda `sensor.py` 495-535, `coordinator.py` 555-590, 1475-1500.

### 0.5 Config-first check
- D1: no knob changes it. `BLE_CHAIN_HOLD_ENABLED` is on; the hold cap does not apply (bedroom default False); occupancy timeout does not apply (the drop happens on the BLE tick, radars already off). Room options have no BLE absence tolerance. Re-aiming / scanner offsets were the 10-26 fix and already took the night flap from hundreds to ~0; the residual is a one-tick resolution gap, not calibration. Code needed.
- D2: the 30 is a rung-1 constant. Lowering it does not fix the shape (the total shrinks with the outage); code needed.

---

## 1. D1 — BLE absence grace (hold the chain through a short absence)

### 1.1 Mechanism today (producer check)
Per tick, if no body signal fired (`not data[STATE_OCCUPIED]`) and no failsafe, the block asks `person_coordinator.get_persons_in_room(room)` (`person_coordinator.py:2022` → `get_room_occupants`). Non-empty and chain unbroken (`_last_occupied_state` True, prev tick) → occupied, source `"ble"`. Empty → the block does nothing, `STATE_OCCUPIED` stays False, the edge fires at `coordinator.py:5242` (lights/fans off via `handle_occupancy_change`, activity log `occupancy_exit`, `occupancy_events` exit row via `_async_log_occupancy_edge` `:5838-5866`, HVAC falling-edge evidence). Next tick `_last_occupied_state` is False, so BLE can never re-create: BLE-WARM-CREATE-1 made BLE extend-only. A one-tick empty read of the producer therefore costs a whole session until a body sensor fires again.

Producer health: `get_room_occupants` reflects Bermuda's area for the person, which moved to Upstairs Hallway for 8-11 s. The room coordinator runs every 30 s + jitter (`coordinator.py:685`) plus event refreshes, so an 8-11 s producer blip is seen by at most one or two room ticks.

### 1.2 Options considered, and the pick

| Option | What it does | Cost |
|---|---|---|
| A. Re-arm after exit (card's sketch) | Let the exit happen; within W s, the same person re-resolving to the same room with dwell ≥ D s re-creates | Exit still happens (lights off, exit row, HVAC edge, zone edge) then D s of darkness before re-entry. Needs remembered (person, room, exit time) state. Re-introduces a BLE **create** path, the exact ingredient BLE-WARM-CREATE-1 deleted; "same person, same room" does not separate flap recovery from bleed (Master Bathroom: same person bleeds into the same adjacent room on every visit). |
| **B. Absence grace (PICK)** | While the chain is BLE-only held, a tick that reads no BLE person keeps the room occupied for up to `BLE_ABSENCE_GRACE_S` from the first empty read. No re-creation path exists or is added | Real BLE-only exits are delayed by ≤ grace (bounded). One new field, one constant |
| C. Debounce the producer in person_coordinator | Delay area changes there | Changes every reader of person location (census, guest gate, fan L1, egress); house-wide blast radius for a room-tier problem. Rejected |

**Why B:** it never lets BLE create anything, so every BLE-WARM-CREATE-1 protection holds by construction (it only ever acts while `_last_occupied_state` is True and `_ble_only_hold_since` is set). It avoids the exit/entry pair entirely, so the user sees nothing and the DB gets no phantom exit/entry. Marginal benefit of A over B: none for the measured case; A's extra ingredient (a create path) is the documented bug family. A is parked (§7).

### 1.3 Specification
Inside the existing block at `coordinator.py:4069`, the outer `if ble_persons:` gains a sibling branch. Predicate (all must hold):

1. `not data.get(STATE_OCCUPIED)` and `not self._failsafe_fired` (already the block's outer guard);
2. `ble_persons` is empty;
3. `BLE_CHAIN_HOLD_ENABLED` and `BLE_ABSENCE_GRACE_S > 0`;
4. `self._last_occupied_state` is True (chain unbroken, prev tick);
5. `self._ble_only_hold_since is not None` (the chain is currently held by BLE alone — the previous admit was a BLE-only admit and no body/camera signal has fired since);
6. the hold cap is not exceeded: same computation as `:4174-4190` (cap enabled for the room AND `now - _ble_only_hold_since > cap_seconds` → no grace). Builder: factor the cap check into a small helper used by both branches; do not duplicate the arithmetic. No NM is fired from the grace branch (the cap NM stays owned by the present-branch path);
7. `self._ble_absent_since` is None (stamp it to `now`) or `now - self._ble_absent_since < BLE_ABSENCE_GRACE_S`.

On admit: `data[STATE_OCCUPIED] = True`, `data[STATE_OCCUPANCY_SOURCE] = "ble"` (deliberately the same label, so the failsafe deferral `:4701`, the HVAC evidence stamp `:5912`, and the ble→body re-entry light path `:5301` treat it exactly as the BLE hold it continues), `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout`, `data[STATE_BLE_PERSONS] = []` (truthful: nobody is reported in the room), plus a new diagnostic key `data["ble_absence_grace"] = True` (dashboard / test observability only; no reader takes a decision on it). Do NOT touch `_ble_only_hold_since`, `_became_occupied_time` or `_last_motion_time`. DEBUG log `"Room %s: BLE absence grace %.0fs/%ds"`.

`self._ble_absent_since` lifecycle (entry/exit discipline):
- init `None` in `__init__` next to `_ble_only_hold_since` (`coordinator.py:~302`);
- set to `None` on every tick where `ble_persons` is non-empty (present branch, before the admit decision);
- set to `None` at every site that clears `_ble_only_hold_since` (the seven sites in §0.1). Builder: enumerate with `grep -n "_ble_only_hold_since = None"`; each gets the paired clear;
- not persisted; a restart starts at None and skip-first re-syncs (`:5212`).

Grace expiry: the first tick with `now - _ble_absent_since >= BLE_ABSENCE_GRACE_S` falls through exactly as today → exit edge.

### 1.4 Falsifiable invariant (D1)
**I-D1: Under any config, BLE (present or absent) can make a room occupied on tick t only if the room was occupied on tick t−1; and an absence-grace hold can last at most `BLE_ABSENCE_GRACE_S` (+ one tick of scheduling jitter) after the last tick that reported a BLE person in the room, and never past the BLE hold cap, the failsafe latch, Override Vacant, or a fan-recheck release.**
Reviewer D breaks it by finding any reachable path where a vacant room becomes occupied via the grace branch, or where grace survives longer than the bound.

### 1.5 BLE-WARM-CREATE-1 failure modes — each still blocked

| Failure mode (from `coordinator.py:4083-4151` and the bleed plan) | Why grace cannot reopen it |
|---|---|
| Cold-room create from adjacent-room bleed (Master Bathroom 09:53 / 10:19, 2026-08-10) | Predicate 4 needs `_last_occupied_state` True; predicate 5 needs a prior BLE-only admit in the same chain. A vacant room never enters the branch. |
| Entry-action strobing from Bermuda in/out flapping in a cold room | Same: no create path. In a warm BLE-held room, flapping today extends the hold anyway on every present tick; grace only bridges the absent ticks between them, bounded per absence. |
| Indefinite BLE hold / forgotten phone in a bathroom or closet | Predicate 6 applies the cap with the same anchor; grace does not reset `_ble_only_hold_since`. A phone left in the room keeps it occupied via the present path exactly as today (the cap and `PersonPhoneLeftBehindSensor` remain the mitigations). |
| Grace chaining forever by alternating absent ticks | Every present tick resets `_ble_absent_since`; that is the existing hold (BLE present extends indefinitely, pre-existing). Pure absence is bounded by the window. No new exposure. |
| Failsafe interaction | Outer guard `not self._failsafe_fired`. The failsafe already defers while source is `"ble"`; the deferral now spans ≤ grace extra seconds. |
| Override Vacant / fan-recheck release / D2 demotion | Override Vacant runs after the block and forces False (`:5168-5181`) and clears the anchor → paired clear. Fan-recheck release sets `_last_occupied_state` False out of band (`:5701`) → predicate 4 fails next tick. D2 only acts on radar-sole ticks; a grace tick is source `"ble"`, not radar-sole. |
| Tier-2 shared-scanner rooms (Jaya Bedroom borrows `jaya_bathroom`) | Unchanged: the present branch already admits shared-scanner rooms via the chain; grace follows the same chain. |

### 1.6 occupancy_events exit row (v5.103.83)
`_async_log_occupancy_edge` writes an exit row on every in-tick occupied→vacant edge. With grace, a blip shorter than the window produces **no edge, so no exit row and no matching entry row** (this is the improvement: today's 06:34 events produced an exit then, 27-30 min later, an entry, i.e. a false vacant gap in the episode readers and the dwell model). A real BLE-only exit writes its exit row up to `BLE_ABSENCE_GRACE_S` later than today. `duration` (seconds since `_last_motion_time`) keeps its meaning because grace does not touch `_last_motion_time`. The `environmental_data.occupied` 5-min sample and the dwell model see the room occupied through the grace window; at a 90 s bound this is below the sample period.

### 1.7 Consumer / call-site check (D1 changes `STATE_OCCUPIED` for ≤ grace s on a BLE-held room)
All consumers of room `STATE_OCCUPIED` (state-of-play §1 table) see a continued hold instead of a short vacancy. Trust readers: lighting/fans (`handle_occupancy_change`, edge-driven — fewer edges), HVAC evidence stamp `:5912` (source `"ble"` → evidence continues ≤ grace; HVAC's own night tail is 30 min for bedrooms, so no material change), zone roll-up / substrate (room-tier occupancy; grace extends ≤ grace), NM panel targeting (display), failsafe deferral `:4701`. Display: room sensor, activity log. The new `ble_absence_grace` key has no decision reader.

### 1.8 Deliverables

#### D1.0 — Measure first (read-only probe; go/no-go for the window)
One-shot recorder probe (`ssh ha "python3 -" < script`, 7-day window): for every `binary_sensor.<room>_occupied` on→off edge whose last source was `ble` (from the room sensor `occupancy_source` attribute), measure (a) seconds until the same person's Bermuda area returns to that room, (b) whether it returns at all within 10 min, (c) the gap between the person's last in-room Bermuda read and the edge. Report the distribution of short returns (the bug class) and of real exits (the cost).
- **Gate:** pick `BLE_ABSENCE_GRACE_S` = smallest value ≥ the p95 of short-return gaps, rounded up to a whole room tick (30 s); default proposed **90 s**. If the probe finds > 0.5 real BLE-only exits/day/room whose delayed lights-off matters (e.g. bathrooms), keep 90 or lower; if short returns > 90 s are common, stop and re-plan (the mechanism would then be calibration, not resolution).
- **Live:** probe report appended to this plan as §1.9 before build dispatch.

#### D1.1 — Absence grace branch
As §1.3.

##### Acceptance criteria
- **Verify (fix vs failure):** BLE-held room (radars off, prev tick `"ble"`), one tick with `get_persons_in_room` empty → stays occupied, `ble_absence_grace` True, no `handle_occupancy_change` call, no `occupancy_events` row. Under today's code the same input yields an exit edge and an exit row: discriminating.
- **Verify:** absence persisting `BLE_ABSENCE_GRACE_S` → exit edge on the first tick at/after the bound; exit row written once.
- **Verify (no create):** vacant room (`_last_occupied_state` False), BLE absent or present → stays vacant on every tick. Room occupied by **motion** (anchor None) with BLE empty → no grace (falls to today's behaviour).
- **Verify:** cap exceeded (bathroom, `_ble_only_hold_since` older than cap) + BLE empty → no grace.
- **Verify:** `BLE_ABSENCE_GRACE_S = 0` → byte-identical to develop on the full BLE test modules.
- **Test:** `quality/tests/test_ble_absence_grace.py` — `test_single_empty_tick_holds_ble_chain`, `test_grace_expires_at_bound_writes_one_exit_row`, `test_grace_never_creates_from_vacant`, `test_grace_requires_ble_only_anchor`, `test_grace_respects_hold_cap`, `test_present_tick_resets_absence_stamp`, `test_override_vacant_and_recheck_release_clear_stamp` (one case per clear site), `test_grace_zero_is_kill_switch`. Existing `test_ble_extend_not_create.py`, `test_ble_hold_cap.py`, `test_occupancy_db_side_fixes.py`, `test_hvac_evidence_clock.py` stay green unchanged. Mutation anchors (framing C): neuter predicate 4, predicate 5, predicate 6, and the present-branch reset one at a time; each must turn a named test red.
- **Live (discriminating):** the next Jaya Bedroom morning with a BLE-only hold and a hallway blip shows no `occupancy_exit` within 90 s of a BLE area change to Upstairs Hallway followed by a return (`occupancy_events` for Jaya Bedroom entry_id between 06:00-07:30 + Bermuda area history). Failure shape (fix not working): an exit row at the blip, then an entry row tens of minutes later on a radar edge. Different failure (grace too long): exit rows lagging Bermuda leaving by > 90 s + one tick on real departures; check one real departure the same morning. One-shot query at disposition, no soak.

### 1.9 Probe results
_To be filled by D1.0 before build._

---

## 2. D2 — BLE fleet fraction for "BLE leads home/away"

### 2.1 Producer check
Active count: Bermuda `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT` = scanners with a recent advert. Total: `BERMUDA_GLOBAL_PROXY_COUNT` = `len(scanner_list)` (`bermuda/sensor.py:511`), rebuilt from HA's `async_current_scanners()` (`bermuda/coordinator.py:1496`). When proxies drop off the network they leave HA's current scanner set, so the **total shrinks with the outage**; active/total would not trip. Today: 31 active-equivalent floor / 62 total (card); measured active p1 = 44 (gps-assistive plan §4.2).

Consumers of the floor (`grep -n BLE_LEADS_MIN_ACTIVE_PROXIES`): `person_coordinator._apply_proxy_state` `:459` (sole decision: healthy-since latch → `_fleet_armed` `:525-532` → `_ble_overrules_gps_home` and the per-tick `_fleet_armed_now` `:793`), log `:504`, tests in `test_person_gps_assistive.py`. Downstream of `_fleet_armed`: the GPS-home overrule only → `_gps_home_overruled` → `effective_person_state` (§1 table of the state-of-play: aggregation fallbacks, HVAC night-trust hold, hvac_fans night hold, census stale-face latch). D2 changes none of those readers, only when the latch is healthy.

### 2.2 Specification
- New in `person_coordinator`: `_fleet_memory: list[tuple[str, int]]` — at most `BLE_LEADS_FLEET_MEMORY_DAYS` (7) entries of (local date ISO, max total seen that day). Remembered fleet `R = max(entries ∪ {current total})`. Using a 7-day daily-max ring instead of an exponential decay: exact, no synthetic time, trivially testable; a decommissioned proxy ages out in ≤ 7 days.
- Total resolved by registry unique_id `BERMUDA_GLOBAL_PROXY_COUNT` via the same helper shape as `_resolve_proxy_entity_id` (generalise it to take the unique_id). Read once per tick in `_ensure_proxy_listener`; numeric readings update today's ring slot; unknown/unavailable are ignored for memory (never lower it).
- Effective floor `F = max(BLE_LEADS_ABS_MIN_PROXIES, ceil(BLE_LEADS_FLEET_FRACTION × R))`. If R is unknown (no memory and total unavailable/missing) → `F = BLE_LEADS_MIN_ACTIVE_PROXIES` (legacy 30, the current behaviour). `_apply_proxy_state` compares against `self._effective_floor` (cached per tick; the edge listener reads the cache, so listener and tick agree).
- Persistence: `Store(hass, 1, f"{DOMAIN}.ble_fleet_memory")`, loaded once in the person coordinator's async setup, written with `async_delay_save(..., 60)` only when a ring slot changes (≤ a few writes/day). HA flushes delayed saves at stop. Corrupt / missing file → empty ring.
- Log INFO once when `F` changes: `"BLE leads: fleet floor %d (fraction %.2f of remembered %d, abs min %d)"`; the existing guard log at `:502-506` prints `F` instead of the constant.

### 2.3 Byte-identical today?
Not literally: with R = 62, F = ceil(0.5 × 62) = 31 vs 30. Behaviour differs only if active reads exactly 30. D2.0 checks the recorder for any reading in [30, 31); measured p1 is 44, so expected 0. If the operator wants strict identity, fraction 0.48 gives ceil(29.76) = 30. Recommendation: keep the operator's 0.5; D2.0 is the proof.

### 2.4 Falsifiable invariant (D2)
**I-D2: The BLE-leads fleet latch can be healthy only when active proxies ≥ max(ABS_MIN, ceil(FRACTION × R)), where R ≥ every numeric total read in the last 7 local days (including totals from before the last restart); a drop in the current total never lowers R within that window. With R unknown the floor is exactly the legacy 30.**
Reviewer D breaks it with a reachable sequence (outage, restart mid-outage, Bermuda late load, store missing, day rollover) in which the latch arms with active below the stated floor.

### 2.5 Deliverables

#### D2.0 — Measure first (read-only)
Recorder probe, 7 days: distribution of Bermuda active and total counts; count of active readings in [30, 31); min/max total per day (confirms the ring would read 62 and that totals dip during outages, e.g. the restart storm or proxy drops).
- **Gate:** 0 readings in [30, 31) outside boot → ship with 0.5. Any → report and let the operator pick 0.5 vs 0.48.

#### D2.1 — Fleet memory + fractional floor
##### Acceptance criteria
- **Verify (fix vs failure):** ring holds 62; current total 20, active 18 → latch unhealthy (F = 31). Today's code: active 18 < 30 also unhealthy; so add the discriminating case: R = 62 remembered, a smaller house-shaped fleet — ring 8, active 5 → healthy after arm (F = max(3, 4) = 4); today's code never arms below 30 (the multi-home case). And outage case: ring 62, total shrinks to 34 with active 33 → today's code arms (33 ≥ 30) and so does new (33 ≥ 31); ring 62, active 30 → today arms, new does not.
- **Verify:** restart mid-outage — Store holds 62, first tick total 25 → R = 62.
- **Verify:** day rollover drops the oldest slot after 7 days; a proxy removed 8 days ago no longer counts.
- **Verify:** total entity missing and empty store → F = 30 (legacy), byte-identical to develop.
- **Test:** `quality/tests/test_person_ble_fleet_fraction.py` — `test_floor_is_fraction_of_remembered_high_water`, `test_shrinking_total_does_not_lower_floor`, `test_restart_restores_ring_from_store`, `test_ring_ages_out_after_memory_days`, `test_abs_min_floor_for_small_fleet`, `test_unknown_fleet_falls_back_to_legacy_30`, `test_listener_and_tick_share_cached_floor`, `test_store_written_only_on_slot_change`. Existing `test_person_gps_assistive.py` boundary tests keep passing (they run with no total entity → legacy 30). Mutation anchors: replace `F` with the constant; skip the ring update; skip the Store load — each must turn a named test red.
- **Live (discriminating):** after restart, the INFO log reads `fleet floor 31 (fraction 0.50 of remembered 62, abs min 3)` and `.storage/universal_room_automation.ble_fleet_memory` holds today's slot = 62. Failure shape: log shows floor 30 (fallback path, total entity not resolved) or the store file is absent after the first delayed save. `_fleet_armed` arms ≈ 6 min after restart exactly as before (INFO `BLE leads: fleet armed`).

---

## 3. Numbers get knobs

| Name | Default | Rung | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `BLE_ABSENCE_GRACE_S` (const.py, next to `BLE_CHAIN_HOLD_ENABLED`) | 90 (set by D1.0) | 1 module const | Trust bound on a BLE hold, same governance as `BLE_CHAIN_HOLD_ENABLED`; changing it should be reviewed | 0 = grace off, byte-identical |
| `BLE_LEADS_FLEET_FRACTION` | 0.5 | 1 | Safety bound on the BLE-overrules-GPS rule, same rung as the 30 it replaces | 0 → floor = ABS_MIN only (not a kill; the presence switch "BLE Leads Home/Away" is the kill) |
| `BLE_LEADS_ABS_MIN_PROXIES` | 3 | 1 | Never trust a 1-2 proxy fleet | — |
| `BLE_LEADS_FLEET_MEMORY_DAYS` | 7 | 1 | How fast a decommissioned proxy stops counting | — |
| `BLE_LEADS_MIN_ACTIVE_PROXIES` | 30 (kept) | 1 | Legacy fallback when the fleet size is unknown | — |

No config-flow or Number entities added.

## 4. Emission / decision-site enumeration

D1 (writers of room `STATE_OCCUPIED` affected): the BLE block `coordinator.py:4069-4270` only. Paired-clear sites for `_ble_absent_since`: `:3944`, `:4052`, `:4495`, `:4773`, `:5181`, `:5228`, `:5699` (re-run `grep -n "_ble_only_hold_since = None" coordinator.py` at build; anchors drift). Readers of source `"ble"` that grace inherits: `:4701` (failsafe deferral), `:5301` (re-entry lights), `:5912` (HVAC evidence).
D2 (readers of the floor): `person_coordinator.py:459`, `:504`; latch readers `:525-532`, `:793`, `_ble_overrules_gps_home`. No other module reads the constant.

## 5. Non-goals
- No change to `person_coordinator` area resolution, Bermuda tuning, scanner offsets or `CONF_SCANNER_AREAS`.
- No BLE create path of any kind (option A parked).
- No change to the hold cap, the failsafe, D2 demotion, the fan recheck, or HVAC hold tails.
- No change to `_ble_fleet_live` (`BLE_FLEET_LIVENESS_WINDOW_S`), which is a different guard (§10 #25).
- No new entities, options-flow fields or DB schema.
- No activity-log or `occupancy_events` schema/trigger changes.

## 6. Tier classification
Tier 2 (operator). Triggers considered: both deliverables change presence trust inputs (room occupancy, BLE-overrules-GPS latch) — regression-prone under the 2026-06-08 standing policy, so the orchestrator should consider three framing-disjoint reviews: A = correctness + edge cases (predicates, ring arithmetic), B = lifecycle (paired clears, restart, Store load timing, listener/tick agreement), C = test authority via per-site mutation. Not Tier 3: no reserve/energy/HVAC control path, and D1's failure mode is bounded to ≤ 90 s of extra occupancy in one room. One adversarial plan review before build.

## 7. Parked
- **Option A (re-arm with dwell).** Revive only if D1 live data shows short returns longer than any acceptable grace (e.g. Bermuda returns after > 3 min) so that holding is worse than re-creating.
- **Producer-side debounce in person_coordinator.** Revive only if several rooms show the same one-tick pattern and the room-tier fix proves insufficient.

## 8. Post-ship doc updates (same commit as the build)
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §3: replace "Bermuda's Active Proxy Count … ≥ 30" with the fractional floor; add the D1 grace to §4 next to the BLE chain description.
- README with the Live table written back after validation.
