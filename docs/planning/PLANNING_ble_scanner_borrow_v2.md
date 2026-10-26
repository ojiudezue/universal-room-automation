# PLANNING — BLE scanner borrow v2 (one mechanism for sparse, en-suite and promoted areas)

- **Status:** PROPOSAL for operator review, 2026-10-26. Not a build. Mechanism first; wording (§9) after.
- **Card:** BLE-LOCATION-QUALITY-1 (`design_2026_10_26`), harm audit `AUDIT_ble_flap_harm_2026_10_25.md`.
- **Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md` (both read in full for this doc).
- **Gate:** card `next` says re-measure Jaya Bedroom after the 10-26 Bermuda offset change (10-28 AM). If that night data is clean, D1 below is still worth it for the shadowed entries (§4 case 3), but its urgency drops.

## 1. Institutional context verified

### 1.1 Original design (quoted)
- `config_flow.py:14`: "v3.2.4: CONF_SCANNER_AREAS replaces CONF_PHONE_TRACKER for person tracking"; `:2660`: "Scanner areas for sparse scanner homes. Optional - only needed if BLE scanners are in different HA areas than the room".
- `person_coordinator.py:10-13` header: "Tier 1: Direct HA area name match (zero config for dense scanner homes) / Tier 2: CONF_SCANNER_AREAS override lookup (for sparse scanner homes) / Tier 3: Occupancy disambiguation (when multiple rooms share a scanner)".
- `README_v3.8.9.md` ("Sparse BLE Hardening"): "Rooms that use a shared scanner from an adjacent area (Tier 2) now require recent motion/mmWave confirmation before BLE can drive occupancy. This prevents adjacent rooms from falsely showing occupied when a shared scanner picks up a person who is actually in a different room."
- No `PLANNING_v3.2.4*` / `README_v3.2.4*` exists (pre-repo; the repo's initial commit is v3.3.5.3). The intent above is from code comments and the v3.8.9 README only.

**Original intent, one line:** borrowing was for a room with **no scanner of its own**: "a reading in area X means the person is in my room". v3.8.9 then said: borrowed BLE is weaker evidence, so it may not create occupancy alone.

### 1.2 What the code does today (verified this session)
- `_build_scanner_room_map` (`person_coordinator.py:1321-1427`): Tier-1 map `_area_id_to_room` from every room's `area_id`; Tier-2 map `_scanner_to_rooms` from `scanner_areas`; `_direct_ble_rooms` = rooms with `area_id` and **empty** `scanner_areas` (`:1375-1377`).
- `_resolve_person_room` (`:1429-1474`): Tier 1 wins. A borrowed area that is also a URA room's area resolves to **that** room; the borrower never sees it.
- `get_room_occupants` / `get_persons_in_room` (`:1947-2020`): exact match on the resolved location.
- Room BLE extend leg (`coordinator.py:4062-4260`): **chain-only for ALL rooms** since BLE-WARM-CREATE-1 (2026-08-10). `is_room_direct_ble` is read at `:4079` but only feeds a log label at `:4253` ("direct" / "shared+confirmed").
- **Contradiction with the brief / README_v3.8.9:** "a non-empty scanner_areas means BLE extend requires recent motion" is no longer true. Direct and borrowing rooms get identical admission today. Demotion from `_direct_ble_rooms` now only changes (a) the log label, (b) `get_ble_tier` → 2, read by the D3 zone weight (`presence.py:6645-6720`, diagnostic only, `D3_DIAGNOSTIC_ENABLED`) and `RoomSignalInventorySensor._ble_tier` (`sensor.py:2763`, display). State-of-play §3 does not claim otherwise; no ledger entry needed, but §3 should gain one line (D4).
- Prior art already doing "borrowed URA room counts for me": `presence_fan_recheck._l1_persons` (`presence_fan_recheck.py:1359-1400`, JAYA-FAN-STILL-PHANTOM-1, 2026-10-18) — persons in this room OR in any URA room whose `area_id` is in this room's `scanner_areas`. Fan recheck only.
- Branch `fix/scanner-areas-own-area` (`5b8a33bc7`, not merged): strips own area on save, ignores it at runtime.

### 1.3 Live config (read-only, `/Users/okosisi/ha-config/.storage`, 2026-10-26)
Proxy count per area = devices whose MAC is a key in the Bermuda entry's `rssi_offsets` (62 keys), grouped by device `area_id`. **Approximate**: a scanner with no offset key is missed (D0 confirms).

| Borrower (own area, own proxies) | Borrowed area | Is a URA room? | Proxies there | Floor same? |
|---|---|---|---|---|
| Living Room (1) | entry_way | no | 0 (?) | yes |
| Living Room (1) | dining_room | Dining Room | 2 | yes |
| Master Bedroom (4) | ezinne_vanity | no | 1 | yes |
| Ziri Bedroom (1) | balcony | no | 1 | yes |
| Ziri Bedroom (1) | ziri_bathroom | Ziri Bathroom | 1 | yes |
| Jaya Bedroom (1) | jaya_bathroom | Jaya Bathroom | 1 | yes |
| Study A (2) | study_a_closet | Study A Closet | 2 | yes |
| Guest Bedroom 2 (0) | guest_bedroom_2_closet | Up Guestbedroom Closet | 1 | yes |
| Exercise Room (0) | exercise_room_closet | Exercise Room Closet | 1 | yes |
| Exercise Room Closet (1) | exercise_room | Exercise Room | 0 | yes |
| Kitchen Hallway (0) | kitchen, butler_pantry, stair_closet | all URA rooms | 4 / 1 / 1 | yes |
| Kitchen Hallway Garage (0) | guest_toilet | Powder | 2 | yes |
| Garage Hallway (0) | laundry | Laundry | 2 | yes |
| Laundry Closet (0) | laundry | Laundry | 2 | yes |
| Breakfast Nook (1) | patio | Patio | 1 | yes |

`adjacent_rooms` is set on one room only (Jaya Bathroom → Jaya Bedroom). No borrow crosses a floor.

### 1.4 Prior-art REUSE / BUILD
| Piece | Verdict | Where |
|---|---|---|
| Borrow list | **REUSE** `CONF_SCANNER_AREAS` | `const.py:564`, flows `config_flow.py:2662`, `:13310` |
| "Borrowed URA room counts for me" helper | **REUSE + promote** `_l1_persons` logic into `PersonTrackingCoordinator` | `presence_fan_recheck.py:1359-1400` |
| Extend-only admission | **REUSE** chain-only leg + hold cap | `coordinator.py:4062-4260`; `CONF_BLE_HOLD_CAP_ENABLED`, `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` (`const.py:1806`) |
| Tier display | **REUSE** `get_ble_tier`, `RoomSignalInventorySensor` | `person_coordinator.py:2036`, `sensor.py:2763` |
| Adjacency | **NOT USED** for this. `CONF_ADJACENT_ROOMS` (`const.py:746`) is a different relation ("rooms you walk between"; consumers `presence.py:3245-3317`, `:4557`, `presence_fan_recheck.py:1400`, `notification_manager.py:5584`). Folding "my BLE counts here" into it would give every hallway a BLE hold from every neighbour. | — |
| New config field | **NONE** | — |
| New method | **NEW** `get_ble_hold_persons(room)` — no equivalent on the person coordinator after grep of `person_coordinator.py`, `coordinator.py`, `domain_coordinators/*` (only the private recheck copy). | — |

Memory pulled: `feedback_ble_config_is_tuned_check_before_asserting`, `project_jaya_bedroom_occupancy_resolved`. Plans: `PLANNING_ble_extend_not_create.md`, `PLANNING_ble_bleed_extend_corroboration.md` (hold cap), audits `AUDIT_ble_flap_harm_2026_10_25.md`, `AUDIT_ble_location_baseline_2026_10_23.md`.

## 2. The mechanism (one rule, two modes, derived not configured)

**A borrowed area means: "a phone heard there counts as being in this room."** What that does depends only on whether the borrowed area is already some URA room's area. URA derives the mode; the operator never picks it.

| Mode | When | Effect |
|---|---|---|
| **Resolve** (today's Tier 2, unchanged) | borrowed area has no URA room | Readings in that area resolve the person's location to the borrower (`_resolve_person_room` Tier 2). Full BLE for the room, still extend-only like every room. |
| **Hold** (new) | borrowed area IS another URA room's area | The person's location stays the owning room (its lights, fans, census and transitions stay correct). The borrower's **extend leg** also counts that person: `get_ble_hold_persons(room)` = occupants(room) ∪ occupants(each URA room owning a borrowed area). Never creates occupancy (chain-only, cap unchanged). |

Why not move the location in Hold mode ("for all intents and purposes in the borrowing room")? Because the owner is a real room: Jaya Bathroom would lose her BLE, its night light and its transitions. Hold gives the borrower everything it needs (stay occupied) and takes nothing from the owner.

**Direct vs borrowing tier:** tier stops being "has scanner_areas" and becomes "has its own scanner". `_direct_ble_rooms` = rooms whose `area_id` holds at least one Bermuda scanner (producer verified in D0). Borrowing no longer demotes a room that has its own proxy. Display / D3 diagnostic only (§1.2).

**Dead entries** (borrowed area has no scanner, so Bermuda never reports it) are surfaced, not acted on.

## 3. Producer and consumer checks

**Producer — person location.** Bermuda area sensor → `_resolve_person_room`. Health: noisy (baseline audit: raw changes Oji 76/h, Jaya 62/h; top flap Jaya Bathroom ↔ Bedroom, 2,174 A-B-A bounces; 3.7 % of quick transitions cross floors). Hold mode is designed for exactly the dominant same-suite flap; it does nothing for cross-floor leakage (§4 case 5).
**Producer — hold set.** `get_ble_hold_persons` reads `self.data` locations + `_area_id_to_room` + the room's merged `scanner_areas`. Map is cached per room-entry set (`:1333-1349`), so a promoted area (new room entry) rebuilds it.
**Producer — own-scanner set.** UNVERIFIED: which registry fact marks a Bermuda scanner. D0 decides (Bermuda `rssi_offsets` keys / scanner device list vs device registry `area_id`).

**Consumers (grep `get_persons_in_room` / `get_room_occupants` / `_l1_persons`):**
| Site | Trust/display | v2 |
|---|---|---|
| `coordinator.py:4075` BLE extend leg | trust (occupancy → lights, HVAC, zone) | **switch to hold set** |
| `coordinator.py:2978` mmWave latch `ble_person` reason | trust (blocks vacate) | **switch** (same "extend, don't vacate" meaning) |
| `presence_fan_recheck._l1_persons` | trust (fan) | **re-point** to the shared method (behaviour identical; deletes the private copy) |
| `coordinator.py:4216/4258` `STATE_BLE_PERSONS` | display | follows the extend leg; add attribute `ble_hold_via` = `{person: owning_room}` so "Jaya in bedroom" is explainable |
| `coordinator.py:4624`, `:1310`, `sensor.py` ble_persons, `fan_veto`, `_ble_corroboration`, census, transitions, music | trust/display on the person's real room | **unchanged** (they want where the phone is) |

## 4. Behaviour by case (before → after)

| # | Case | Today | v2 |
|---|---|---|---|
| 1 | Sparse room, no proxy, borrows an area with no URA room | Resolve: works. Room demoted to tier 2 (label only). | Same. |
| 1b | Sparse room borrows an area that IS a URA room (Guest Bedroom 2 ← its closet, Exercise Room ← its closet) | **Dead**: Tier 1 sends the person to the closet room; the room never gets BLE. | Hold: room stays occupied while the phone is heard in the closet. Location still reads the closet (Bermuda cannot tell them apart; nothing can). |
| 2 | Room later gets its own proxy, borrow kept | Still demoted to tier 2; borrow still resolves. Nothing tells the operator. | Tier 1 (own scanner). Borrow still valid: Resolve entries keep catching the neighbour's area (e.g. Master ← ezinne_vanity); Hold entries keep the en-suite. Surface it: `ble_borrow` attribute shows each entry's mode + `own_scanner: true`, so a borrow the operator added only for coverage can be reviewed. No auto-removal (tuned config, memory rule). |
| 3 | Borrowed area is made into a URA room (operator's question) | **Today:** Tier 1 now owns it. The borrow silently stops resolving; the person moves to the new room; the borrower loses that BLE (except fan-recheck L1) and stays demoted. This already happened to 12 entries in §1.3. | Entry flips Resolve → Hold automatically on the room-map rebuild. Borrower keeps an extend-only hold; the new room gets the person's location. No config edit needed. |
| 4 | En-suite / closet leakage | Phone flips bed ↔ bath, bedroom hold drops (Jaya 71-85 min vacant asleep). | Hold: bath reading keeps the bedroom's existing occupancy. Never creates it: an empty bedroom with Jaya in the bath stays vacant. Bedroom hold cap off by room type; bath/closet cap 120 min unchanged. |
| 5 | Cross-floor leakage (Jaya Bedroom scanner hears downstairs phones) | Person mis-resolves to Jaya Bedroom; extend leg can hold the bedroom only if already occupied (chain). | **Unchanged by design.** Hold only admits rooms the operator listed, all same-floor. The wrong-room resolution is a location problem (BLE-LOCATION-QUALITY-1 ideas 2-3), not a borrow problem. Options-flow guard: a cross-floor borrowed area shows a warning in `ble_borrow` (`cross_floor: true`), not a refusal (a sparse home may legitimately borrow a stair scanner). |

**Hazard Hold introduces (named):** a borrower that is a transit space holds while the person sits in the owner room. Kitchen Hallway ← kitchen: walk through the hallway, cook 90 min, hallway stays lit 90 min. This is why §5 drops the hallway entries.

## 5. Migration of live entries (operator decides; config only, no code)
| Entry | Mode under v2 | Recommendation |
|---|---|---|
| Living Room ← entry_way | Resolve (0 proxies?) | Keep if D0 finds a scanner in entry_way; else remove (dead). |
| Living Room ← dining_room | Hold | **Remove.** Dining is its own room; Hold would keep the Living Room lit during dinner. |
| Master Bedroom ← ezinne_vanity | Resolve | Keep. |
| Ziri Bedroom ← balcony | Resolve | Keep (RSSI-tuned). |
| Ziri Bedroom ← ziri_bathroom | Hold | Keep (en-suite). |
| Jaya Bedroom ← jaya_bathroom | Hold | Keep (the harm case). |
| Study A ← study_a_closet | Hold | Keep (closet inside the study). |
| Guest Bedroom 2 ← guest_bedroom_2_closet | Hold | Keep (room has no proxy; only BLE it can get). |
| Exercise Room ← exercise_room_closet | Hold | Keep (no proxy of its own). |
| Exercise Room Closet ← exercise_room | dead (0 proxies) | **Remove.** |
| Kitchen Hallway ← kitchen, butler_pantry, stair_closet | Hold | **Remove all three** (transit hazard). |
| Kitchen Hallway Garage ← guest_toilet | Hold | **Remove** (transit). |
| Garage Hallway ← laundry | Hold | **Remove** (transit). |
| Laundry Closet ← laundry | Hold | **Remove** (closet held for the whole laundry session). |
| Breakfast Nook ← patio | Hold | **Remove** (nook held while on the patio). |

Rule of thumb for the operator (and the description text): borrow an area **you are inside of when you are there** (en-suite, walk-in closet, vanity alcove), or the nearest scanner of a room with none. Never borrow a room you walk *to*.

## 6. Falsifiable invariant
**Under v2, a borrowed area can never create occupancy in the borrower, and a Hold-mode borrow can never change any person's resolved location: for every reachable state, if the borrower was vacant on the previous tick and none of its own sensors fired, it stays vacant; and `person.location` is identical with and without the room's `scanner_areas` whenever every borrowed area is a URA room's area.**
Break attempts reviewer D must try: restart mid-hold (`_last_occupied_state` restore), Tier-3 multi-claim (two rooms borrowing the same non-URA area), a borrowed area whose owner room is deleted/renamed (map rebuild), borrower == owner after `5b8a33bc7` is NOT merged (own area listed), cap firing while the holder is in the owner room.

## 7. Deliverables
- **D0 (probe, read-only, first):** list Bermuda scanners and their device `area_id`; confirm the own-scanner producer and the 0-proxy areas (entry_way, exercise_room). Go/no-go for the tier change in D2. **Live:** a table committed to this doc.
- **D1 Hold set.** `PersonTrackingCoordinator.get_ble_hold_persons(room) -> list[str]` (+ `ble_hold_via` map); wire `coordinator.py:4075` and `:2978`; re-point `_l1_persons`. **Accept:** Jaya resolved to Jaya Bathroom, bedroom occupied last tick, no bedroom sensor on → bedroom stays occupied, `occupancy_source=ble`, `ble_hold_via={Jaya: Jaya Bathroom}`; the same with the bedroom vacant last tick → stays vacant (discriminates Hold from a create); Jaya resolved to Garage A → bedroom vacates (discriminates Hold from "any BLE nearby"). Jaya's `sensor.*_location` reads Jaya Bathroom throughout. **Tests:** `test_ble_hold_borrowed_room_extends`, `test_ble_hold_never_creates`, `test_ble_hold_location_unchanged`, `test_ble_hold_unlisted_room_ignored`, `test_l1_persons_parity`. **Live:** next night with a bed↔bath flip, `binary_sensor.jaya_bedroom_bedroom_4_occupied` has no off run > 10 min between first radar-on and 06:00 while Jaya's location stays in {Jaya Bedroom, Jaya Bathroom}.
- **D2 Tier from own scanner** (gated on D0). `_direct_ble_rooms` from scanner presence. **Accept:** Jaya Bedroom `ble_tier=1` with `scanner_areas` set; Guest Bedroom 2 `ble_tier=2`. **Test:** `test_ble_tier_own_scanner_with_borrow`.
- **D3 Surface.** `ble_borrow` attribute on `RoomSignalInventorySensor`: per entry `{area, mode: resolve|hold|dead, owner_room, cross_floor}`, plus `own_scanner`. Unrecorded. **Accept / Live:** Kitchen Hallway shows three `hold` entries before migration; Exercise Room Closet shows `dead`.
- **D4 Docs.** State-of-play §3: two modes, v3.8.9 tier is display-only since BLE-WARM-CREATE-1; strings (§9).

## 8. Knobs, tier, non-goals
- **Knobs:** `BLE_BORROW_HOLD_ENABLED` (rung 1, `const.py`, default True; False = today's behaviour byte-identical, Hold entries ignored by the extend leg, `_l1_persons` keeps its current behaviour). No new number: Hold reuses `BLE_CHAIN_HOLD_ENABLED` and the per-room hold cap. No new config field.
- **Tier: 2-DB (3 framing-disjoint reviews)** per the standing regression-prone policy: room-tier trust input feeding lights, HVAC `hvac_occupied` and zone roll-up, two trust sites. Not Tier 3: extend-only, one room-tier site plus one latch reason, kill switch, no shared energy/HVAC primitive. One plan review before build.
- **Non-goals:** moving person locations in Hold mode; changing `CONF_ADJACENT_ROOMS`; any Bermuda smoothing, trilateration or floor gate (BLE-LOCATION-QUALITY-1); fan_veto / census / transitions / music consumers; auto-removing borrow entries; bathroom-side hold from the bedroom (reverse direction).

## 9. UI wording (draft, for operator review after the mechanism)
- **Label:** `Count BLE from these areas`
- **Description (213 chars):** `Treat a phone heard in these areas as being in this room. Use for an en-suite, walk-in closet or vanity, or the nearest scanner if this room has none. Another room's area only keeps this room occupied, never starts it.`
