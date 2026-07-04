---
name: ura-presence-fusion-reference
description: Domain reference for URA's presence-fusion stack — sensor kinds (motion / mmWave / occupancy / BLE / camera person vs motion), the OccupancySubstrate raw layer, provenance split, trust vetoes (v4.7.13 night, v4.7.14 away), fan-interference mitigations, v4.7.21 boot-settle gates, StateInferenceEngine vs ZoneAnyoneBinarySensor. Load when planning/reviewing changes under presence.py / occupancy_substrate.py / presence_fan_recheck.py, or debugging "room stuck occupied", "away while occupied", "sleep-state fan cycled", "boot away-storm", mmwave ghosts, phone_left_behind. Not for HVAC/energy/security code that merely consumes `_room_occupied`.
---

# URA Presence-Fusion Reference

**Audience:** a solo engineer / lone Sonnet-class session working URA without
guaranteed subagents. Verify anything in this doc against the repo before
committing to it — presence.py evolves fast (6 160 LoC as of 2026-07-02).

**Authoritative policy:** `CLAUDE.md` at repo root. This skill only encodes
what presence *is*; process (tiers, reviews, deploy) belongs to that file.

**Sibling skills — cross-reference, do not duplicate:**

| If you're doing… | Use |
|---|---|
| Full URA deploy pipeline | `deploy` |
| HA YAML / dashboard / helpers | `homeassistant_coding` / `ha-dashboard` |
| Post-cycle doc update | `documenter` |
| Capturing a load-bearing decision | `vibememo` |

## 1. Vocabulary — one definition each

| Term | Definition |
|---|---|
| **Tier 1 kind** | A raw sensor category the substrate stores per room. `TIER1_KINDS = ("motion", "mmwave", "occupancy")` — `const.py:342`. Exactly these three; nothing else is Tier 1. |
| **Tier 2 signal** | Higher-level presence: person-tracker state, camera person-classified events, guest gate, house-state inference. Consumes Tier 1 + person data. |
| **Substrate** | The `OccupancySubstrate` class (`occupancy_substrate.py`) — a per-room, per-Tier-1-kind raw boolean layer that sits **beneath** both the room-occupancy tier and the zone-occupancy tier. Shipped v4.7.24. |
| **Provenance** | Which Tier-1 kind is currently driving occupancy for a room. Stored in `PresenceTracker._room_provenance: Dict[str, Dict[str, bool]]` — `presence.py:471`. |
| **Derived occupancy view** | `PresenceTracker._room_occupied` — now a `@property` at `presence.py:527` returning `{room: any(_room_provenance[room].values())}`. Not stored, never written directly. |
| **Hold** | A truth-preserving occupancy extension that can ONLY extend, never shorten. Grep `presence.py` for `_fan_interference_hold_until` and `audit_provenance_split` for the current sites (historical anchors :391/:402/:432 have drifted). Audit invariant: derived may be broader than provenance-any only if a hold is active. |
| **Guest gate armed** | Composite Tier-2 signal replacing raw `unidentified_count > 0`. Applies threshold + confidence + persistence. See `_guest_gate_armed` at `presence.py:4071`. |
| **House state** | The output of `StateInferenceEngine.infer()` at `presence.py:904`. Values: `ACTIVE`, `AWAY`, `SLEEP`, `HOME_DAY`, `HOME_EVENING`, `HOME_NIGHT`, `GUEST`, plus a few edges. |
| **Boot-settle gate** | `_boot_settle_done` flag at `presence.py:1354`; suppresses dispatch during cold-boot to prevent away-actuation storms. |

## 2. Sensor kinds — what each is trusted for

| Kind | Physical mechanism | Trust rules |
|---|---|---|
| **motion (PIR)** | Heat + movement. Fires on entry / arm-wave. Zero when still. | Truthy → provenance `motion=True`; drops after HA's own timeout. No independent decay in substrate. |
| **mmwave** | Doppler on chest wall / micro-motion. Holds still bodies (bed, couch). Vulnerable to fan blades, curtains, HVAC vent flap. | Substrate stores it, BUT fan-noise mitigations (§5) can shorten trust; `_fan_interference_hold_until` prevents *shortening* below provenance-any. |
| **occupancy** | Fused vendor sensor (e.g. FP2 zone, Aqara, Shelly BLU) — vendor decides. | Trusted at face value. If the vendor stops fusing, the sensor here drops to False. |
| **BLE** | Room-scoped BLE beacon of a *person's* phone. NOT a Tier-1 substrate kind — used at Tier 2 for `is_direct_ble_room` and drop-authorization gates. | Fail-open on unavailable. In fan-recheck Mode-2 acts as a *drop-authorization* gate (§5.2). |
| **camera person** | Frigate / Protect classifier fires `person` label. | Trusted for zone/room presence — this is what "Tier 2 presence reads person-classified only" means. Grep `CONF_DISABLE_CAMERA_PRESENCE` before editing to see the current callsites. |
| **camera motion** | Raw motion detection, no classifier. | **Deliberately NOT used for Tier-2 presence** without per-room policy — camera motion is noise (leaves, pets, shadows). `CONF_DISABLE_CAMERA_PRESENCE` is the per-room opt-out flag (imported at `presence.py:41`); investigation `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` for durability audit. |

**Precedence when one `entity_id` is listed in multiple substrate slots:**
`_KIND_PRECEDENCE = ("motion", "mmwave", "occupancy")` — first wins.
Source: `occupancy_substrate.py:75` (verified). Motion beats mmwave beats
occupancy for the same entity.

## 3. OccupancySubstrate — the raw layer (v4.7.24)

### What it is

A `SIGNAL_*`-driven layer that (a) listens to every configured Tier-1 sensor,
(b) maps unavailable/unknown → `False` (matches pre-substrate
`_handle_occupancy_change` semantics), (c) stores `Dict[room, Dict[kind, bool]]`,
(d) dispatches on transitions to both the room-occupancy tier AND the zone
tier.

**File:** `occupancy_substrate.py` (469 LoC). API surface:

| Method | Behavior |
|---|---|
| `get_room_kinds(room) → Dict[str, bool]` | Stable dict, all three `TIER1_KINDS` present (default `False`). Line ~434. |
| `get_all() → Dict[str, Dict[str, bool]]` | Full snapshot. Line ~446. |
| `subscribe(cb) → unsub` | Register per-kind callback. |
| `release_boot_settle()` | Called by presence coord when Gate 1 releases (§6). |

### Why it exists (Bug Class #50)

Before v4.7.24, presence tier re-derived Tier-1 kinds via HA entity-registry
area sweep AND separately did the same for zones. Both tiers had subscription
loops that a periodic `_update_signal_subscriptions` rebuild clobbered
(**CRITICAL B-C1**, Tier-2-DB Review B caught this → new Bug Class #50).
Substrate is the single source of truth so the rebuild can't drop
subscriptions.

**Live attribute to watch:** `substrate_kinds` on the presence coordinator
sensor — discriminates per room which Tier-1 kinds are currently `True`.

### If no Tier-1 sensors are configured for a room

Substrate logs a warning (line ~290) and Tier-1 for that room is dead — the
system does NOT fall back to camera/BLE at Tier 1. Add
`CONF_OCCUPANCY_SENSORS` (or motion/mmwave equivalents).

## 4. Provenance split — the derived-view invariants

Shipped v4.7.19. Before, `_room_occupied` was a stored boolean; now it is a
`@property` derived from `_room_provenance`.

**Invariants (audited by `audit_provenance_split` at `presence.py:340`):**

1. `_room_occupied[r] == any(_room_provenance[r].values())` for every room `r`.
   Widened inside `audit_provenance_split` (grep for it — historical anchor
   `presence.py:391-432` has drifted) to allow "derived broader because of an
   active hold" (see §5.1). Violations logged as `invariant violated`.
2. Every kind in `_room_provenance[r]` ∈ `TIER1_KINDS` (`_UNAVAILABLE` is
   the sole extra sentinel).
3. Buckets are `Dict[str, bool]`, never nested / never `None`.
4. `set(_room_provenance.keys()) == set(_room_occupied.keys())`.

**Test:** `quality/tests/test_presence_provenance_split.py::test_invariants_hold_after_inference`.

### Writing to provenance

Use the coordinator's `_set_provenance`-style helpers (`presence.py:721`).
Do NOT mutate `_room_provenance` directly — the derived view relies on the
stored shape being stable. R1-H1 fix-up note at `presence.py:745-759`.

## 5. Fan-interference mitigations — physics + code layers

**Physical failure mode:** mmWave sees fan blades / air-movement as
micro-motion → holds a room "occupied" (ghost) OR (Mode-2) mmwave PIR
false-drops during blade shadow. Bedroom fans cycle occupancy → HVAC preset
oscillates → 8-preset flap over one night (documented in v4.7.13 memo).

Three layers, each solving a different failure:

### 5.1 Layer-1 silent hold + decay (v4.7.20)

`_fan_interference_hold_until: Dict[room, datetime]` at `presence.py:402`.

- **Direction:** hold can ONLY extend occupancy, never shorten.
- **Truth-preserving:** derived-view audit widened to permit
  `derived=True AND any(provenance)=False` iff `hold_active`
  (`presence.py:415-433`).
- **Gate order:** provenance-OR first-short-circuits; hold layered on top.
- **Reason it's silent:** no HA state change if occupancy was already True.

**Regression class:** v4.7.20.1 hotfix was a Bug Class #34 (conditional
function-local `async_dispatcher_send` import → UnboundLocalError). All fresh
dispatch sites: import `async_dispatcher_send` at MODULE TOP
ística(`presence.py:3718`, verified).

### 5.2 Mode-2 BLE-gated fan pause + recheck (v4.7.22)

**File:** `presence_fan_recheck.py` (962 LoC).

**Flow (D1 conditions at ~line 298):**

1. Room suspected empty AND mmwave still hot AND fan running.
2. **D1.5 BLE-tier drop-authorization gate** (line 314) — only proceed if
   no phone BLE is inside the room. Fail-open on missing sensor.
3. Pause fan via `hvac_fans.FanController._set_fan_state` (no new fan write
   callsite; state machine reuses the existing one, comment at line ~15).
4. Wait, recheck mmwave. If still hot → real person, unpause. If dropped →
   ghost, mark vacant.
5. Ladder layers tracked via `ble_ladder_layer` attr.

**Master bedroom ships OFF** by default (operator flipped ON post-ship;
SLEEP-only gate blocks daytime naps).

**High-still-risk guard** (from review C1): if room recently transitioned
to a resting state, D1 is denied — protects bedroom nappers.

### 5.3 What NOT to do

- Do NOT add a new mmwave-shortening code path outside the hold. It
  breaks the invariant.
- Do NOT expose a knob that lets users invert the "hold only extends"
  rule — that's the truth-preservation guarantee.
- Do NOT dispatch fan-hold state without the module-top
  `async_dispatcher_send` import (Bug Class #34).

## 6. Boot-settle gates — v4.7.21

**Failure mode:** cold boot → HA fires stale AWфAY defaults → chained
automations fan out → turn-off storm on slow cloud devices → event loop
saturates → house_state aggregate stalls ~15 min while per-room sensors
update fine.

**Two gates:**

| Gate | Where | Releases on |
|---|---|---|
| **Gate 1 (presence dispatch)** | `presence.py:1354`, `_boot_settle_done`. Suppresses presence-signal dispatch on boot. | **Predicate A** — first REAL input (`real_input`, 0-values suppressed) OR **Predicate B** — `BOOT_SETTLE_TIMEOUT_SECONDS` elapses OR `ha_started`. `_release_boot_settle(reason)` at `presence.py:1904`. |
| **Gate 2 (HVAC 2-cycle hold)** | HVAC coordinator — sibling gate; hangs 2 dispatch cycles before actuating on AWAY. | Cycle counter. |

**Which path fires in production** (validated 2026-06-04/05):
Predicate A fires first almost every clean boot; Gate 2 catches scenario
γ. Two reproductions on file. **This validates keeping both gates**.

**Constants** — grep `BOOT_SETTLE_MIN_INPUTS`, `BOOT_SETTLE_TIMEOUT_SECONDS`
in `const.py` before proposing changes (imported at `presence.py:38-39`).

## 7. Trust vetoes — the two shipped, and the open gap

### 7.1 v4.7.13 — sleep-state zone person-trust

**Problem:** during sleep, 3-sensor zone redundancy degenerates to 1
(mmwave). Fan cycled all night → HVAC 8-preset oscillation. URA had
`person.oji_udezue = home` data it was NOT using.

**Fix pattern:** during `house_state == "sleep"` AND zone aggregator scope,
if the person tracker confirms someone's home → hold zone occupied.
Codified in the D1 helper at `presence.py:1552` (v4.7.15 D1 promotion) as
`scope="zone_aggregator"` **Pattern B**: `presence.py:1660-1661`.

### 7.2 v4.7.14 — away-state person-tracker veto (summary)

Consumes pre-existing `all_tracked_persons_away`; requires
`unidentified_count == 0` (guest guard) + `census_count == 0` (H1 Frigate
face-ID guard) + (in the non-ACTIVE branch) `not sleep_exempt_state` (phones-die-overnight carveout). Bug Class #48. Live dwell 33 min post-fix vs 60-90 s bounce pre-fix.

Full anchors, v4.7.14.1 H1/H2/H3 filter table, and re-verify greps live in `ura-presence-reliability-campaign` §v4.7.14 away veto (fact-home). Do not duplicate line numbers here — grep `all_tracked_persons_away` for current sites.

### 7.4 Open gap — home_night trust

**Not shipped.** Zone 1 (master) flips to `away` preset while occupied
during `home_night` because v4.7.13 person-trust is `sleep`-only
(historic guard around `presence.py:1151`) and home_night is uncovered.
Fix candidate: extend the same trust to home_night (Tier-1 sibling of
v4.7.13). Bed sensor is currently an unused signal.

Reference memo: `project_zone_away_when_occupied_home_night_gap.md` in
`.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/`.
Label anything you propose here as OPEN until built and live-validated.

## 8. StateInferenceEngine vs ZoneAnyoneBinarySensor — the two paths

Two *different* code paths consume the same trust-data. Reviewers routinely
confuse them.

| | StateInferenceEngine | ZoneAnyoneBinarySensor |
|---|---|---|
| **Class** | `presence.py:875` | `aggregation.py:3562` |
| **Method** | `.infer(...)` — line 904 | `.is_on` — property |
| **Purpose** | HOUSE-level state (AWAY / SLEEP / …) | ZONE-level "anyone here" bool |
| **Consumes** | Occupancy dict, census, unidentified, guest-gate, `all_tracked_persons_away`, sleep-exempt | Substrate + person-trust via D1 helper, scope=`zone_aggregator` |
| **Away-veto surface** | v4.7.14 path α + β | (n/a — house state only) |
| **Sleep-trust surface** | Path β sleep-exempt gate | v4.7.13 Pattern B (`presence.py:1660`) |
| **Non-sleep zone trust** | (n/a) | v4.7.15 D2 Pattern C (`presence.py:1670`) |
| **Byte-identical guarantee** | v5.7.0 invariant I3 — path α is byte-identical to v4.7.14 baseline when only `all_tracked_persons_away` is passed (`presence.py:976`) | — |

**Rule of thumb:** if you're changing the house-state machine, the surface
is `StateInferenceEngine.infer()`. If you're changing zone-level "is anyone
in Zone N", the surface is `ZoneAnyoneBinarySensor.is_on` and the
`_get_zone_person_trust(scope=...)` helper at `presence.py:1552`.

## 9. House-state aggregation flow (top-to-bottom)

```
raw HA sensors  ──►  OccupancySubstrate
                     (per-room per-kind bool, Tier-1)
                       │
                       ├── PresenceTracker._room_provenance[room][kind]
                       │      │
                       │      └── derived @property _room_occupied
                       │            (any(kinds) OR hold-active)
                       │
                       ├── ZoneAnyoneBinarySensor.is_on
                       │      (D1 helper: v4.7.13 SLEEP + v4.7.15 non-sleep person-trust,
                       │       scope="zone_aggregator")
                       │
                       └── PresenceCoordinator._run_inference
                              │
                              ├── computes all_tracked_persons_away (v4.7.14)
                              │      with H1/H2/H3 filters
                              ├── computes guest_gate_armed
                              ├── computes unidentified_count / census_count
                              │
                              └── StateInferenceEngine.infer(...)
                                     │
                                     ├── path α: v4.7.14 ACTIVE veto → AWAY
                                     ├── path β: non-ACTIVE veto → AWAY (grace + sleep-exempt)
                                     ├── SLEEP hour test
                                     ├── GUEST arm
                                     └── HOME_DAY / HOME_EVENING / HOME_NIGHT
```

Boot-settle Gate 1 sits between `_run_inference` result and dispatch during
cold boot (§6).

## 10. Live-verification checklist

Run these against the running house before signing off any presence change.

**Live path (Samba mount + MCP):**

Use the mount command from `CLAUDE.md` §"Data Source Verification" verbatim —
do NOT retype paths from memory (the mount command contains an escaped
password). Then:

| Check | How | Expected |
|---|---|---|
| Substrate populated | `mcp__home-assistant__ha_get_state` on `sensor.ura_presence_coordinator_presence_house_state` → `substrate_kinds` attr | Per-room dict with all three `TIER1_KINDS` present |
| Provenance / derived invariant | Same sensor → `rooms` attr vs `_room_provenance` mirror | Widened invariant §4 holds |
| v4.7.14 veto diagnostics | Same sensor → `tracked_persons_count`, `all_tracked_persons_away` | Non-null; `all_away=True` while everyone is out |
| Boot-settle release | Log scan `mcp__home-assistant__ha_get_logs` for `Boot-settle: released` | Present exactly once per boot, with reason (`real_input` normally) |
| Fan-recheck outcomes | Substrate signal + `sensor.<room>_fan_recheck_state` | `idle` when quiescent; `paused` / `recheck` / `recovered` transitions cleanly |
| Sleep-state person trust | Zone-anyone entity stays `on` overnight while person tracker `home` | No mid-sleep bounces |

**Fallback when mount / MCP is down:**

- SSH to `homeassistant@192.168.13.13` and read `.storage/core.config_entries`
  + `home-assistant.log` directly. `ha_get_state` fallback is `curl` against
  the HA REST API using a stored long-lived token.

## 11. When NOT to use this skill

| Symptom / task | Right skill |
|---|---|
| "Add a new HA helper" / "Automations" | `homeassistant_coding` |
| Dashboard cards, Lovelace | `ha-dashboard` |
| Post-cycle README + arch doc write | `documenter` |
| Deploy stamping + PR + release | `deploy` |
| HVAC preset / zone climate logic (consumes `_room_occupied` read-only) | Read this skill for background, then work in `hvac.py` / `hvac_zones.py` directly. The presence view is just an input. |
| Energy / battery strategy | Different domain entirely. |

## 12. Provenance and maintenance

Re-verify volatile facts before quoting them. All the following were verified
**as of 2026-07-02**:

| Claim | One-line re-verification |
|---|---|
| `TIER1_KINDS = ("motion", "mmwave", "occupancy")` | `grep -n "^TIER1_KINDS" custom_components/universal_room_automation/const.py` |
| Kind precedence motion → mmwave → occupancy | `grep -n "_KIND_PRECEDENCE" custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py` |
| `_room_occupied` is a `@property` | `grep -n "def _room_occupied" custom_components/universal_room_automation/domain_coordinators/presence.py` |
| `audit_provenance_split` widened for hold | `grep -n "hold cannot shorten\|hold_active" custom_components/universal_room_automation/domain_coordinators/presence.py` |
| v4.7.14 path α gate | `grep -n "v4.7.14: Person-tracker veto path" custom_components/universal_room_automation/domain_coordinators/presence.py` |
| v4.7.14.1 H1 / H2 / H3 layers | `grep -n "v4.7.14.1 (H[123])" custom_components/universal_room_automation/domain_coordinators/presence.py` |
| Boot-settle Gate 1 fields | `grep -n "_boot_settle_done\|_release_boot_settle" custom_components/universal_room_automation/domain_coordinators/presence.py` |
| `ZoneAnyoneBinarySensor` scope="zone_aggregator" | `grep -n "zone_aggregator" custom_components/universal_room_automation/aggregation.py` |
| Substrate is v4.7.24 | Check `docs/readmes/README_v4.7.24.md` |
| Line counts (may drift) | `wc -l custom_components/universal_room_automation/domain_coordinators/{presence,occupancy_substrate,presence_fan_recheck}.py custom_components/universal_room_automation/aggregation.py` |

**If a claim above is stale after re-verification, fix it here in the same
PR that changed the code.** This file is part of the presence contract.

**Related planning docs (skim before editing):**

- `docs/planning/PLANNING_occupancy_substrate_unification.md` (v4.7.24)
- `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md`
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md`
- `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md`
- `docs/planning/PLANNING_fan_trust_state_extension.md`
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`
- `docs/Coordinator/PRESENCE_COORDINATOR.md`

**Related memo body (for veto history):**
`.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/project_zone_away_when_occupied_home_night_gap.md`
— the open home_night trust gap.
