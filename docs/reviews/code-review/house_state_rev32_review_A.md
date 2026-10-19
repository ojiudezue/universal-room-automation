# Rev 3.2 build review: framing A (local correctness)

- **Scope:** `git diff dad3bf6e7..2244661c3`, production files only (`__init__.py`, `const.py`, `occupancy_substrate.py`, `presence.py`, `signals.py`). Covers the per-entity zone tracker (D4a–D4d) and the switch gates. The delta before `dad3bf6e7` was reviewed earlier.
- **Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (ledger #1–#22), `docs/architecture/SENSOR_FLEET_CLASSES.md`, plan §R3 / §R3.1 / §R3.2 + build notes, and the plan reviews `PLAN_REVIEW_sleep_mask_rev3_R2_build_prediction.md` and `PLAN_REVIEW_sleep_mask_rev3_1_recheck.md`. No ledger claim is re-asserted. R1 (completeness) was skimmed through the findings it shares with R2 and the re-check.
- **Line numbers** are for `2244661c3`.
- **Verdict: FIX-REQUIRED.** One MEDIUM (A-M1, a one-line fix). Everything else holds. The LOWs are text and display only.

## Findings

| ID | Sev | Where | Finding |
|---|---|---|---|
| **A-M1** | **MEDIUM** | `presence.py:2359-2370` `_reconcile_trackers_to_substrate` | **The boot reconcile writes into trackers that never receive live edges.** It walks `tracker.room_names` for every tracker. The live path (`_on_substrate_kind_changed`, `:3641` → `tracker_for_room`) and the setup seed (`:3567-3581`) only write the room's owning tracker, i.e. the first zone in `_room_to_zone` (`:3463-3471`, first writer wins). When two zones list the same room, the reconcile writes True into the non-owning tracker at release, and no later False edge ever reaches it. That zone then reads OCCUPIED until the next restart that happens while the room is empty. It blocks nobody-home AWAY and β, and it pins the HVAC consensus −0.4 term. **Reachable:** the zone-rooms options step saves `selected_rooms` without removing them from other zones' `CONF_ZONE_ROOMS` (`config_flow.py:10900-10945`, it only clears the room's own `CONF_ZONE`), and presence code names the case (`presence.py:3463`). **Repro (ran it):** zones Down=[Kitchen] (owner) and Living=[Kitchen]; Kitchen ZX on at release, so the reconcile sets `Living._room_provenance["Kitchen"] = {mmwave: True}`. The ZX then goes off and `_on_substrate_kind_changed("Kitchen","mmwave",False)` clears Down only: `z1 {'Kitchen': False} z2 {'Kitchen': True} mode=occupied`. Before this build, the non-owning tracker was never written (empty, not stuck). Falsifies INV-ZONE-ROOM-TRUTH ("occupied after all of E(r) are off, no hold"). Bug class: one-missed-site / scope (#53 sibling: the new writer uses a different room→tracker resolution than the existing writers). **Fix:** in the room loop, `if self.tracker_for_room(room_name) is not tracker: continue`, plus a two-zone test. |
| A-L1 | LOW | `presence.py:840-853` (`update_room_occupancy` docstring "occupied=False (any kind…): CLEAR ALL kinds"), `:662-690` (`_room_occupied` docstring "equivalent on False"), `:890-904` (else-branch comment), `:4091-4109` (`_zone_night_rooms` D-H1 comment) | Plan §R3.6 D4b and D1-S item 4 require these to be rewritten. They still describe the switch-off semantics only. Text only. Ledger #20 already records the refutation. |
| A-L2 | LOW | `presence.py:885-887` | After a partial pop, `_last_kind_per_room[room]` can still name the kind that was just popped (e.g. last fired = motion, motion pops, mmwave still True). It feeds the `last_kind_to_fire` display attr only, and it matches the plan's rule ("pop only if no slot is still True"). Display only; fix it or accept it by name. |
| A-L3 | LOW | `presence.py:4243-4247` (D4d `tier1_rooms`) | `tier1_rooms` comes from every tracker, not from the zones that set `any_zone_occupied`. Example: zone A has a manual AWAY override and holds a Tier-1 room, while zone B is occupied only by camera, fan-hold or a manual OCCUPIED override. The R3.1.7 "Tier-1 holder required" filter passes when it should not. Needs Frigate dark and an override, so it is narrow, and the page text would still name rooms. Tighten to "a zone with `mode == OCCUPIED` that has a Tier-1 room". Also with A-M1, a duplicate-zone tracker feeds this list. |
| A-I1 | info | `presence.py:6955-6956` → D4d | When `switch.ura_presence_away_veto_enabled` is OFF, `all_tracked_persons_away` is coerced False before D4d, so D4d is silent. That is consistent: the operator disabled the veto denominators. Worth one line in the README coverage note. |

## Per-site checks (the orchestrator's list)

| Site | Result | Evidence |
|---|---|---|
| `_kind_on_now`: event entity from the payload | **PASS** | `occupancy_substrate.py:296-298` returns True only when `event_state.state == "on"`. The event entity is skipped in the sibling loop (`:300-301`), so its stored state is never read. |
| Siblings from `hass.states` | **PASS** | `:302-310`: same (room, kind) in the passed map; `on` only. unavailable, unknown and missing count as off. A sibling that raises is treated as off. |
| Explicit map | **PASS** | Live: `self._entity_to_room_kind` (`:751-754`). Seed: the passed `desired_entity_to_room_kind` (`:345-348`). No `self` read in the helper. |
| Seed byte-identity with the switch off | **PASS** | The old seed iterated `room_entities[room]` filtered by `desired[e][0] == room`. The new seed iterates `desired` entries with room == room. These are the same set, because `desired` entries for room R come only from `room_entities[R]` after first-claim dedupe (`:252-272`). Same on, unavailable and missing rules. |
| Deleted entity counts off | **PASS** | `:738`: the early return now applies only with the switch off. With it on, `new_state None`, so `_kind_on_now` returns False unless a sibling is on, and the edge dispatches if the kind flips (`:760-787`). |
| Scratch-copy swap | **PASS** | `:529-540`: a per-room `dict(bucket)` copy, so the seed never mutates live buckets. On subscribe failure, `:552-561` returns before `:565-567`, leaving `_raw_state`, the map and the listener all old (coherent). The swap happens before step 6 prune and step 7 (`:583`, `:592`). The body is await-free between seed and swap. The retry sees the old map, so the diff is non-empty and edges are emitted. |
| Room-removed walk | **PASS** | `:595-600`: `desired_rooms ∪ snapshot.keys()`. A pruned room reads `{}`, so prior True gives a False dispatch. Rooms that are renamed, or that lose all sensors, get the same release (a strict improvement). Gated on `per_entity` and `_boot_settle_done`. |
| `async_remove_entry` | **PASS** | `__init__.py:5712-5746`: attribute-read gate; ROOM-only; dispatches `(entry_id, room_name, "removed")` with the same arity as the other three sites. `"room_name"` == `CONF_ROOM_NAME` (`const.py:395`); it is logging-only in presence. The other subscribers no-op on `"removed"` (`hvac.py:5446-5449`; binary_sensor own-id filter). Never raises. |
| Kind-only pop | **PASS** | `presence.py:874-889`: gated on `kind in TIER1_KINDS` and the switch. `pop(kind, None)` keeps `{}` for a single-sensor room (R2-7). The `_has_sensors` / `_has_room_sensors` side effects equal the old else-branch, and `_last_activity` is not touched, as before. kind=None False still full-clears (`:890-913`, used by the seed `:3615`). The `"tier1"` sentinel survives a kind pop, and nothing in production writes it (only the dead writer `:5231`). |
| Boot reconcile: differing slots only, guarded | **PASS with A-M1** | `:2353-2370` writes only where `bool(have[k]) != want[k]`. `get_room_kinds` returns all-False for an absent room (`occupancy_substrate.py:850-858`), so a renamed or unwalked room gets no write and stays UNKNOWN. The call has its own `try/except` (`:2403-2410`) and runs after the replay (`:2389-2396`). Inside the idempotent guard (`:2380`), so it runs once. **Defect:** the tracker-ownership scope, see A-M1. |
| Switch gates read the module attribute | **PASS** | grep: the only readers are `presence.py:876, 2403, 4116, 4239, 6448`, `occupancy_substrate.py:528, 735`, `__init__.py:5730`. All are `_ura_const.<NAME>` with `_ura_const` bound to the `const` module (`presence.py:74`, `occupancy_substrate.py:60`, `__init__.py:5729`). No `from ..const import ZONE_OCCUPANCY_PER_ENTITY_ENABLED`. `ZONE_HOLD_ALL_AWAY_NM_BOUND_S` is also read by attribute (`:4269`). |
| D4d conditions | **PASS** (A-L3 narrow) | `:4250-4263`: matches §R3.6 plus R3.1.7. All five inputs are bound on every path before the call (`tracked_count`/`all_tracked_persons_away` `:6348-6368`, `any_zone_occupied` `:6387`, `current_state` `:6486`, `manager` used at `:7015`). A NameError would be swallowed silently, so I checked each one. `is_overridden` exists on the machine (`house_state.py:198`). The `tracked_count > 0` conjunct is equivalent (build note 4). |
| D4d latch | **PASS** | The first held tick only stamps (`:4266-4268`). The bound is strict `>` (`:4273`). Bound 0 never fires. A per-episode flag is reset on any non-held tick (`:4261-4264`), plus the `fire_stuck_signal` per-day `(kind, key)` latch. |
| D4d HIGH severity | **PASS** | `severity="HIGH"` → `getattr(Severity, "HIGH")` (`_stuck_signal_nm.py:229-231`). |
| D1-S limb and forcing line gated | **PASS** | `:4116` and `:6448`, both under `not` switch. The switch-off text is byte-identical to `dad3bf6e7`. |
| None / unavailable handling | **PASS** | Payload `None` = off (switch on), and the early return is kept (switch off). unavailable/unknown never count `on` on either path. `getattr(event_state, "state", None)` tolerates odd payloads. |

## Truth table: D4a substrate (switch on), one (room, kind), entities A (event) and B (sibling)

| A payload | B in `hass.states` | `occupied` | prior T → dispatch? | prior F → dispatch? |
|---|---|---|---|---|
| on | any | T | no | T |
| off / unavailable / unknown / None | on | T | no | T |
| off / unavailable / unknown / None | off / unavailable / unknown / missing | F | F | no |
| (single-sensor: no B) on | — | T | = last-writer | = last-writer |
| (single-sensor) not-on / None | — | F | = last-writer (None: new release) | no |

Every event recomputes the full OR from current states, so a run of events converges to `room_raw` after the last callback, whatever order siblings' events are delivered in.

## Truth table: D4b tracker (switch on), kind k off-edge

| bucket before | after | `_room_occupied` | `_last_kind_per_room` |
|---|---|---|---|
| {k:T} | {} | F | popped |
| {k:T, j:T} | {j:T} | T | kept (may still name k, A-L2) |
| {j:T} | {j:T} | T | kept |
| {} / missing | {} | F | popped (no-op) |
| kind=None False | {} | F | popped (unchanged legacy) |

## Bug-class sweep (`docs/QUALITY_CONTEXT.md`)
- **#53 computed-but-not-consumed / one missed site:** A-M1, where the new writer's room→tracker scope differs from the two existing writers. Otherwise every Rev-3 site in the §R3.1.1 matrix is gated, and I found no ungated site.
- **#62 hollow anchor:** not in A's lane (framing C).
- **#63 coincidental equality:** the seed and live rules are now one helper, so the B-HIGH-1 class is closed by construction.
- **Observation-mode gating #23:** D4d fires NM only, through `fire_stuck_signal` (which has its own kill switch). No actuation.
- **Untracked background tasks:** D4d `async_create_task` follows the `_check_sleep_raw_hold` precedent. That is framing B's lane, so it is not graded here.
- **Day-boundary:** D4d measures in UTC seconds, and the per-day latch is the shared helper's. No TOU.

## Invariant checklist (local view)
| Invariant | Status |
|---|---|
| INV-ZONE-ROOM-TRUTH | **LEAK** only for a room listed in two zones (A-M1); PASS otherwise |
| INV-NO-STUCK-THROUGH-REMOVAL | PASS (entity: `:738`/`:751`; CONF: desired-map seed; room: hook plus walk) |
| INV-BYTE-ID-SINGLE | PASS (no sibling read; `pop` shape) |
| INV-KILL-BYTE-ID | PASS by reading (every gate is attribute-read and the switch-off text equals `dad3bf6e7`; the seed is equal by set argument) |
| INV-NIGHT-RAW-EQUALS-RAW | PASS by reading (`_zone_night_rooms` BLE → has_sensors → `_room_occupied` → camera mirrors `_derived_mode`, limb skipped) |

## Verdict: FIX-REQUIRED
Must fix:
1. **A-M1:** scope `_reconcile_trackers_to_substrate` to the owning tracker (`tracker_for_room(room) is tracker`), and add a two-zone test with a drill.

Fix in the same pass (LOW, 1–30 LoC): A-L1 docstrings, A-L3 (tighten D4d to an OCCUPIED zone's Tier-1 room). For A-L2, fix it or accept it by name.
