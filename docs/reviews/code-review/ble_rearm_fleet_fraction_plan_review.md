# Plan review — BLE absence grace (D1) + BLE fleet fraction (D2)

**Plan:** `docs/planning/PLANNING_ble_rearm_and_fleet_fraction.md` @ 621c5cdce
**Review type:** Tier 2 adversarial plan review (presence), one pass
**Reviewer reads:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 796 lines, incl. §10 ledger + gold patterns) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (all 50 lines) read completely before review. No §10 ledger claim is re-asserted by the plan (checked #25 fleet-liveness vs proxy count, #27 dead fleet ≠ unavailable trackers — both respected).
**Verdict: FIX-PLAN** (1 HIGH, 2 MEDIUM, 4 LOW). Option B (grace, no create path) is the right pick over A; D2 shape is sound. Fixes are plan text, not redesign.

## Verified with greps (plan claims that hold)

| Claim | Evidence |
|---|---|
| BLE block, chain leg, cap | `coordinator.py:4070-4272`; chain `:4153-4156`; cap `:4174-4211`; anchor seed `:4242-4243` |
| Seven `_ble_only_hold_since = None` sites | `coordinator.py:3944, 4052, 4495, 4773, 5181, 5228, 5699` (re-grepped, exact) |
| Failsafe defers on source `ble` | `coordinator.py:4701-4703` |
| ble→body re-entry reads `_last_occupancy_source == "ble"` | `coordinator.py:5298-5303`; `_last_occupancy_source` only updated on edges (`:5243`), so grace ticks keep it `ble` (correct) |
| HVAC evidence stamp counts source `ble` | `coordinator.py:5196`, `_stamp_hvac_evidence` `:5900-5912` |
| Fan-recheck release out of band | `coordinator.py:5683-5701` sets `_last_occupied_state=False` → predicate 4 fails next tick |
| Paused room keeps tracking `_last_occupied_state` | `coordinator.py:5386-5388` (grace still works for DB / downstream; correct) |
| Restart: anchor starts None → no grace until a fresh BLE-only admit | `coordinator.py:328`, skip-first `:5210-5228` |
| Floor readers | `BLE_LEADS_MIN_ACTIVE_PROXIES` read only at `person_coordinator.py:459` (decision) and `:504` (log). Tests use literals (`test_person_gps_assistive.py:484-498`, "literal boundary, not the imported constant") — they stay valid only because they run with no total entity (plan says so) |
| Bermuda total unique_id + value | `bermuda/sensor.py:506` `BERMUDA_GLOBAL_PROXY_COUNT`, `:511` `len(scanner_list) or 0`; scanner set from `async_current_scanners()` `bermuda/coordinator.py:1496` |

## Consumer re-enumeration (who a 90 s grace delays)

Independent list of everything downstream of room `STATE_OCCUPIED` on a BLE-held room:
- Lights/fans off: `handle_occupancy_change` on the edge (`:5241-5250`) + `_delayed_exit_verify` (`:5280-5291`) — delayed ≤ grace + 1 tick.
- Activity log `occupancy_exit` (`:5252-5277`) and `occupancy_events` exit row (`_async_log_occupancy_edge`, plan §1.6) — delayed / suppressed for blips.
- HVAC evidence stamp (`:5196`) — continues while source `ble`; plan's §1.7 is right for one grace, wrong under chaining (see H1).
- Failsafe deferral (`:4701`) — deferred while grace holds.
- Zone roll-up / substrate, presence `_zone_night_raw` (room limb), NM panel targeting (`_panel_target_areas` reads `STATE_OCCUPIED`), security/perimeter readers, `environmental_data.occupied` → dwell model / `dwell_share` producer.
- Census / house-state: read person_coordinator / zone views, not room grace directly; `fan_veto._ble_present_in_room` and `_ble_corroboration.py` read person_coordinator, not room state → unaffected (verified `get_persons_in_room` callers: fan_veto, sensor, presence, `_ble_corroboration`, coordinator).
All are "continued hold" effects; none is a create. Fine for a single bounded grace.

## Findings

### HIGH-1 — Grace bridges intermittent bleed: a real departure can hold the room for up to the cap (bathroom 2 h) or indefinitely (bedrooms, cap off). §1.5 row "Grace chaining forever … No new exposure" is false.
Class: #53-adjacent / suppression without discharge (`feedback_suppression_needs_discharge`).
Today the chain holds only while EVERY tick reads the person present; the first absent tick breaks it permanently (BLE extend-only). With §1.3, each present tick clears `_ble_absent_since`, so the hold survives any presence duty cycle where a present read lands at least once per 90 s.
**Repro (legal config, the documented Master Bathroom bleed):** Master Bathroom (cap on, 120 min `const.py:1812`). Occupant uses toilet (motion admits), returns to Master Bedroom. Motion times out → BLE-only admit (anchor set) because Bermuda still bleeds the phone into Master Bathroom on that tick. Bleed then flaps present/absent ~every other 30 s tick (the exact "reproducible on every toilet visit" pattern, `coordinator.py:4097-4103`). Today: exit on the first absent tick (≤ ~1 min). With grace: every absent gap < 90 s is bridged, room held ~120 min until the cap fires, plus a `ble_hold_cap` NM per day. Same for Jaya Bedroom (borrows `jaya_bathroom`, cap default off): an adjacent-room bleed with any present read per 90 s holds the bedroom, its HVAC evidence (source `ble`) and its zone indefinitely.
I-D1 as written is not falsified by this (the bound is "after the last tick that reported a BLE person"), which means the invariant is too weak to catch the regression the plan claims to exclude.
**Fix in plan:** (a) bound grace per hold, e.g. a refractory: at most one grace episode per `BLE_ABSENCE_GRACE_REFRACTORY_S` (rung 1, e.g. 600 s) per BLE-only anchor, or a cumulative grace budget per anchor; or require K consecutive present ticks before the absence stamp is re-armed. (b) Extend I-D1: "a BLE-only hold whose present/absent pattern would have ended at tick t on develop ends by t + G (+1 tick) unless a present read follows within G AND the refractory has elapsed". (c) D1.0 probe must also measure the cost side: for real BLE-only exits, the presence duty cycle of that person in the vacated room over the next 10 min (bleed flapping), per room; gate the refractory on it. (d) Add `test_intermittent_bleed_does_not_chain_grace` (present/absent alternating after a real exit → exit within G + refractory bound).

### MEDIUM-1 — D2 cold memory collapses the floor during an outage (first deploy, missing/corrupt store).
Class: restart/RestoreEntity-shaped boot poisoning (Envoy incident family).
§2.2: legacy 30 applies only when there is no memory AND the total is unavailable. Bermuda's total is numeric even when partial (`or 0`, `sensor.py:511`), so with an empty ring R = current total. **Repro:** the first restart after deploy (store file does not exist yet) during a proxy outage: total 20, active 18 → F = max(3, ceil(10)) = 10 → healthy → arms after 360 s; legacy code needs 30. Same after a corrupt store (`Corrupt / missing file → empty ring`). Bermuda boot also walks total 0 → partial → 62; a slow fleet rejoin that plateaus partial for > 6 min arms on the partial size.
**Fix in plan:** while the ring holds no slot from a prior local day (cold memory), use F = legacy 30 until the ring has ≥ 1 completed prior day (multi-home small fleets wait one day — acceptable, state it). Add test `test_cold_memory_uses_legacy_floor_during_outage`. Amend I-D2 to cover the store-missing case explicitly.

### MEDIUM-2 — Store load site is unspecified / does not exist as written.
Class: lifecycle ordering.
§2.2 says "loaded once in the person coordinator's async setup". `PersonTrackingCoordinator` has no async setup method (`person_coordinator.py:151` `__init__`, `:656` teardown, `:772` `_async_update_data`); it is created and immediately `async_config_entry_first_refresh()`-ed at `__init__.py:3086-3087`. A builder will either load lazily inside a tick (first tick(s) run with an empty ring → MEDIUM-1 window every restart) or invent a setup hook. **Fix:** name the site: `await person_coordinator.async_load_fleet_memory()` between `:3086` and `:3087`, exception → empty ring + legacy-floor (per MEDIUM-1). Add a test that the first refresh already sees the restored R.

### LOW-1 — Ring is count-bounded, not date-bounded.
"At most 7 entries of (date, max)" keeps stale slots after HA downtime (10 days off → 7 slots all older than 7 days still define R). The acceptance case "proxy removed 8 days ago no longer counts" fails if HA was down some of those days. **Fix:** prune by `date >= today - (MEMORY_DAYS - 1)` on every read; keep the count cap as a secondary guard.

### LOW-2 — Mutation anchors incomplete.
D1 list omits predicate 7 (window expiry compare) and the paired clears (one representative); D2 list omits the cold-memory branch (after MEDIUM-1) and date pruning. Add them; each must turn a named test red.

### LOW-3 — `data["ble_absence_grace"]` entry-reset.
Set only on admit. Confirm `data` is fresh per tick (it is constructed per `_async_update_data`); state in the plan that the key is absent (not False) otherwise, or write False each tick at the block's top — pick one so sensors/tests don't read a stale True. Also assert in a test that the grace branch never schedules `_fire_ble_hold_cap_nm` and never moves `_ble_only_hold_since` (cap measured from the original anchor).

### LOW-4 — Live criterion window.
"No exit within 90 s" should read "within `BLE_ABSENCE_GRACE_S` + one tick (≈ 120 s)" so the failure shape "grace too long" is measured against the real bound, and add the HIGH-1 cost check: one real departure from a bleed-prone room (Master Bathroom) the same day exits within bound.

## Items that hold

- **No create path:** predicates 4 + 5 (`_last_occupied_state` True AND anchor set) mean a vacant room can never enter the branch; anchor is only seeded on a BLE-only admit (`:4242`). Override Vacant forces False after the block and clears the anchor (`:5169-5181`); Override Occupied then off leaves anchor + `_last_occupied_state` True → one bounded grace then exit (fine). Failsafe outer guard holds. D2 demotion only acts on radar-sole ticks; grace tick source is `ble`. Sleep holds: bedroom HVAC night tail (30 min) dominates a single grace.
- **Knob ladder:** all five numbers placed at rung 1 with one-line reasons; `BLE_ABSENCE_GRACE_S=0` is a real kill switch. Add the HIGH-1 refractory at rung 1.
- **Acceptance criteria discriminate** fix vs failure for the single-blip case and for D2's 30-vs-31 boundary; operator's 0.5 (F=31 at R=62) is acceptable conditional on D2.0 finding no non-boot active readings of exactly 30.
- **Multi-home (D2):** each HA instance has its own `.storage`; small fleets get F = max(3, ceil(0.5 R)) — correct after MEDIUM-1's one-day warmup. Total entity missing → legacy 30 → byte-identical to develop (existing tests).
- **Bermuda total unavailable:** ignored for memory (never lowers R); active-unavailable still drops the latch via `_apply_proxy_state` (`:458-463`).

## Must-fix before build dispatch
1. HIGH-1: grace refractory/budget + strengthened I-D1 + D1.0 bleed-duty measurement + chaining test.
2. MEDIUM-1: cold-memory legacy floor + test + I-D2 amendment.
3. MEDIUM-2: name the Store load site before first refresh.
LOWs 1-4: fix in the same plan revision.

| Severity | Found |
|---|---|
| HIGH | 1 |
| MEDIUM | 2 |
| LOW | 4 |
