# AUDIT — Room classification consistency (ROOM-CLASSIFICATION-CONSISTENCY-1)

**Date:** 2026-09-14 · Read-only. No files modified.

## Per-surface producer / consumer / blast-radius

| Surface | Kind/scope | Producer | Consumers (all TRUST unless noted) | Blast radius |
|---|---|---|---|---|
| CONF_ROOM_IS_GUEST_ROOM | bool / room | const.py:386; set config_flow.py:1457, options :10470 | presence.py _discover_guest_rooms :4879, gate :5159, house-state GUEST :5741/:6321 | Presence → GUEST mode (highest stakes) |
| CONF_WET_ROOM | bool / room | const.py:1028; set config_flow.py:1456/:11444; SEEDED from bathroom via ROOM_TYPE_FEATURE_DEFAULTS const.py:1234 (create-only) | automation.py:2522 wet_room; :2528 sleep-policy exemption; :2632 humidity-fan arming | Room humidity-fan automation |
| ROOM_TYPE_UTILITY | enum / room | const.py:426; dropdown config_flow.py:1383/:10380 | ONLY ROOM_TYPE_TIMEOUTS[utility]=600 (const.py:1177) | Occupancy timeout — near-vestigial |
| ROOM_TYPE_INFRASTRUCTURE | enum / room | const.py:429; dropdown :1386/:10383; coerced coordinator.py:336; seeds InfrastructureRoomSwitch default switch.py:5128 | ROOM_TYPE_TIMEOUTS[infra]=120; energy exclusion aggregation.py:3522/3539/3589/3609/3716/3732 (via coord._infrastructure_room) | Energy aggregation + timeout; **switch is runtime authority, enum only seeds** |
| CONF_SHARED_SPACE | bool / room | const.py:74; set options :10430 | automation.py:3150 is_shared_space → auto-off :3162 + warning :3207; aggregation.py:1508 relaxes sleep-hour alert thresholds; :1211 display | Room auto-off + security thresholds |
| CONF_ZONE_IS_OUTDOOR | bool / zone | const.py:72; zone flows :1265/:9047 | presence.py:1728 outdoor snapshot → AWAY-veto exclusion :5661; safety.py:428 room_type="outdoor" humidity bands | Presence AWAY veto + Safety humidity |

## Concrete inconsistencies
1. **Three mechanisms for one kind of thing** — booleans (wet/guest/shared), enum values (utility/infra), zone boolean (outdoor). History, not design, dictates the axis.
2. **`infrastructure` represented TWICE** — ROOM_TYPE enum AND live `switch.infrastructure` (switch.py:5107); the switch is runtime authority, enum only seeds the default. No other class has a live toggle.
3. **`outdoor` on TWO axes** — no ROOM_TYPE_OUTDOOR enum, yet safety.py keys humidity bands on room_type "outdoor", produced only by the zone flag coerced at safety.py:428.
4. **`basement` is an unreachable room_type key** — safety.py:214/:284 key bands on "basement" but there is no const, no dropdown, no producer. Dead-but-useful → KEEP+WIRE (add the enum member so basements get their bands), NOT delete.
5. **`wet_room` overlaps bathroom** — legitimate concept split (function vs humidity property), but the create-time seed cascade is implicit/undocumented.
6. **`utility` near-vestigial** — one timeout row (600s, = garage), carries an enum member for no distinct behaviour.

**Genuinely distinct, leave alone:** guest_room (GUEST gate), shared_space (auto-off), room_type as a conservatism DIAL (RECHECK_FACTOR/FAILSAFE/TIMEOUTS/BLE_HOLD_CAP).

## Proposal (for operator review — NOT a migration)
- **FUNCTION axis** = CONF_ROOM_TYPE (drives conservatism dials) — keep as-is.
- **LOAD-BEARING PROPERTY axis** = orthogonal flags (wet/guest/shared/infra/outdoor).
- **Recommended Option A (LOW churn):** formalize the flags as one documented "room-class attributes" group with three invariants — one producer per flag (document the infra switch as authority, enum as seed); explicit room-vs-zone scope; WIRE the two orphans (promote basement/outdoor to real ROOM_TYPE enum members + dropdown, make CONF_ZONE_IS_OUTDOOR the canonical outdoor producer and retire the safety.py coercion). Closes the reachability gap without moving any consumer read pattern.
- **Rejected Option B** (unify into one CONF_ROOM_CLASSES multi-select): cleaner but rewrites every consumer + options-flow migration + the InfrastructureRoomSwitch RestoreEntity path. High regression surface, low functional gain. Park (revive if a 6th class appears or flags start conflicting).

**Tier:** any change is Tier 2-DB minimum (cross-coordinator: presence, safety, energy, security, automation). **Migration risks:** InfrastructureRoomSwitch RestoreEntity override loss; GUEST gate + AWAY veto are FP-sensitive; the wet_room create-time seed would clobber overrides if re-derived.

**Nothing proposed for deletion** — basement/utility are KEEP+WIRE / KEEP+DOCUMENT.
