# PLANNING — Fan-noise Mode-2 mitigation: room-tier BLE-gated fan-pause + clean recheck

**Status:** Draft (planning). No version pre-stamped — assigned at deploy time per operator convention.

**Revision note (this rewrite):** the prior draft of this doc bundled a v4.7.20 hold-strip
into the headline. Per operator update 2026-06-05, the strip is no longer in scope of the
Mode-2 deliverable — the v4.7.20 hold lives on the ZONE tier and is inert against the
Mode-2 (FALSE-ON / LATCH) failure mode that drives HVAC and the energy-waste pain (HVAC
reads ROOM tier, not zone tier). The hold cannot help nor interfere here. The strip is
recast as an OPTIONAL Phase 2 (P2) clearly marked "pending operator decision" and the
Mode-2 work stands alone in Phase 1 (P1) without it.

**Companion plan:** `docs/planning/PLANNING_occupancy_substrate_unification.md` (filed
same session). Mode-2 ships FIRST per operator preference; the substrate is the natural
clean-up that lands next. See § Seam-with-Substrate for the precise code surfaces the
substrate will absorb.

**Predecessors (mark both as SUPERSEDED with a pointer back here at deploy time):**
- `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` — D1 (the silent zone-tier
  hold, shipped as v4.7.20) and all of D2 (the Layer-2 actuation sketch).
- `docs/planning/PLANNING_fan_noise_mitigation_layer2_actuation.md` — the entire G1-G6
  build-gate. The build gate is moot because Mode-2 is the live, observable, energy-
  wasting failure mode (Exercise Room repro 2026-06-05).

**Carries forward from those docs:**
- The per-kind `_room_provenance` split (`presence.py:412-561`, shipped v4.7.19). KEEP —
  but note: the room-tier (where Mode-2 fires) does not read this; the zone-tier
  consumer is the diagnostic surface only. The substrate cycle (Plan B) unifies this.
- The `CONF_ADJACENT_ROOMS` per-room adjacency model (`const.py:373`,
  `config_flow.py:1104,6620`, presence-coord adjacency cache rebuild at
  `presence.py:1995-2017`, invalidate at `:2179`). KEEP. Feeds L2 of the new ladder.
- The `_compute_fan_interference_rooms` observation-only diagnostic
  (`presence.py:2539-2698`). KEEP unchanged. Read-only, useful cross-check for the new
  room-tier verdict.
- The `PersonPhoneLeftBehindSensor` H2 carve-out idiom (binary_sensor.py:1031;
  `_phone_trustworthy` closures inlined at `presence.py:2787-2808`). Reuse — extract
  to a shared module so the new room-tier ladder calls the same function.
- The v4.7.8 `egress_state` snapshot/restore precedent — design reference for restart
  resilience of the new pause state.

---

## Operator framing (verbatim where load-bearing)

The operator's pain (`docs/BACKLOG.md:13`): *"Summer ceiling fans add mmwave noise →
false 'occupied.'"* From the v4.7.20 LIVE memo (2026-06-05): *"I have over provisioned
sensors and the opposite [of dropout] is the problem."* And the mechanism: *"The explicit
case was fans keeping mmWave on and using ble to understand when to bypass by pausing
the fan and doing a clean recheck."*

The v4.7.20 silent hold extends occupancy past mmwave DROPOUTS (Mode 1). Mode 2 needs the
opposite: occupancy must be REMOVED when BLE proves the room is empty and the only signal
keeping it occupied is fan-coupled mmwave. The shipped hold is on the zone tier
(`ZonePresenceTracker._room_occupied`), but HVAC's fan write path reads the room tier
(`hvac_zones.py:546` → `coordinator.data["occupied"]`). So the hold is inert against
Mode-2 — it can be left in place during P1 without interfering. Whether to strip it is
a separable hygiene question (P2).

Energy waste is the primary, observable, defensible win condition: "fan and AC stop
running in a provably empty room." Exercise Room is the live repro
(`fan.fan_switch_3` "Fan Switch Exercise" + `binary_sensor.occupancy_lux_temp_humidity_hobeian_exercise_presence_2`,
a fan-sensitive 10 GHz mmwave that doesn't capture still states). Jaya
(`fan.fanswitch_treat_wifi_jayabedroom`) and Ziri (`fan.fanswitch_treat_wifi_ziribedroom`)
are the next-most-likely repros. Room-occupied entities: Exercise =
`binary_sensor.exercise_room_occupied`, Jaya =
`binary_sensor.jaya_bedroom_bedroom_4_occupied`, Ziri =
`binary_sensor.ziri_bedroom_bedroom_5_occupied`.

---

## Tier classification

**Tier 2-DB (three framing-disjoint reviews).**

Triggers (CLAUDE.md):
1. **Trust-hierarchy ripple across coordinator boundaries.** This cycle adds a NEW writer
   to the room-tier `binary_sensor.<room>_occupied` (the BLE-justified release path) AND
   a NEW writer to the fan actuation surface (`hvac_fans._set_fan_state`). The room-tier
   signal feeds HVAC zones (`hvac_zones.py:546`), HVAC defer gates (`hvac.py` via
   `check_zone_occupancy_confidence`), HVAC covers, lighting, music, compliance, safety,
   and the v4.7.19 D5 guest-room detector (`presence.py:3539`). A false release would let
   HVAC cut a room with a real person in it — Mode-1-shaped regression.
2. **First room-tier actuation** that pauses fans and rechecks. Snapshot/restore plus
   restart resilience surface needs distinct DB-architecture review (`fan_recheck_state`
   table mirrors v4.7.8 `egress_state`).
3. **Cross-coordinator handshake required.** HVAC's `FanController.update`
   (`hvac_fans.py:186-260+`) runs every 5 min and may re-issue `fan.turn_on` during a
   pause; the suppression contract crosses two coordinators that have never had such a
   contract before.
4. **Operator-elevated.** Presence ↔ HVAC ↔ compliance ↔ safety ripple is the standard
   Tier 2-DB elevation rationale.

### Framings (locked here; repeated at review dispatch)

- **Reviewer A — Correctness + Mode-1 non-regression + ladder correctness.** Does the
  BLE ladder ever release a room with a real person in it? Does the recheck verdict
  (mmwave persists vs drops with fan off) correctly map to "real presence" vs "fan-coupled
  latch"? `PersonPhoneLeftBehindSensor` carve-out preserved? Stuck-sensor detector
  (`coordinator.py:1289-1309`) still effective for non-fan stuck cases? Inverse-of-v4.7.20
  invariant honored: the new mechanism can only SHORTEN occupancy in a bounded, BLE-
  justified, rechecked window, never silently extend it. Failsafe + camera + BLE override
  precedence preserved.
- **Reviewer B — Async + lifecycle + cross-coordinator race + restart resilience.** HVAC
  `FanController.update` runs every 5 min — pause-window suppression contract enforcement.
  Snapshot/restore across restart (paused-at-restart, restoring-at-restart, cooldown-at-
  restart, snapshot-corrupt-at-restart). Listener teardown on coordinator unload
  (Bug Class #38/#42). First-tick post-restart (Bug Class #14): pause inhibited until the
  v4.7.21 boot-settle gate (`_boot_settle_done`) is True. No `async_dispatcher_send`
  function-local import (Bug Class #34, v4.7.20.1 recurrence).
- **Reviewer C — New surfaces + DB schema + test fixture authority + cross-rule
  precedence.** New `fan_recheck_state` DDL extracted from production source (never hand-
  copied). New CONFs round-trip through options flow + RestoreEntity. Cross-rule
  precedence: pause vs `CONF_FAN_VACANCY_HOLD`, `CONF_FAN_TEMP_THRESHOLD`, `EgressManager`
  pause, operator-driven `fan.turn_on`, `CONF_FAN_CONTROL_ENABLED == False`,
  `manual_off_cooldown_until`. Pause-history sensors.

---

## Institutional context verified

### A. Primitives + signals + consumers (REUSED / NEW / verdict per item)

| Primitive | Verdict | Evidence (file:line) | Notes |
|---|---|---|---|
| Room-tier `binary_sensor.<room>_occupied` decision | **REUSED.** `coordinator.py:1241-1610` `_async_update_data`. Flat-OR at `:1365`; `STATE_OCCUPANCY_SOURCE` set to `"motion" / "mmwave" / "occupancy_sensor" / "timeout" / "camera" / "ble" / "failsafe" / "grace_hold" / "override" / "none"` at `:1408-1444, 1510, 1539, 1586, 1876, 1882`. | THIS is the tier P1 hooks. HVAC's fan write path reads this tier (`hvac_zones.py:546`). |
| Room-tier `STATE_OCCUPANCY_SOURCE` attribute | **REUSED — primary input.** `coordinator.py:1418` sets `"mmwave"` when `presence_detected` is the sole driver. | The "mmwave-sole" precondition for the trigger uses this directly. No new attribute needed for the precondition. |
| Room-tier `_last_motion_time` + `_became_occupied_time` + failsafe | **REUSED — must not regress.** `coordinator.py:1410-1523`. | The BLE-justified release path must mirror the failsafe's clear of `_last_motion_time` + `_became_occupied_time` (`:1509-1513`) when it forces vacancy. |
| Room-tier stuck-sensor detector | **REUSED — explicitly insufficient for Mode 2.** `coordinator.py:1289-1309`, `_stuck_sensor_hours=4.0`. Resets `_sensor_on_since` on every off-blip (`:1297`), so a fan-coupled chattering mmwave is invisible. 57 min ≪ 4 h Exercise repro is also far below threshold. | The new mechanism is the right detector for Mode 2 (BLE-justified, fan-correlation-aware). Stuck-sensor detector is kept untouched — it still handles non-fan stuck cases. Reviewer A confirms the two mechanisms compose without contention. |
| BLE Tier-1 reads | **REUSED.** `person_coordinator.py:1140-1245` (`get_persons_in_room`, `is_room_direct_ble`, `get_persons_in_zone`). | L1/L2/L3 of the new ladder. Already used by room-tier BLE override at `coordinator.py:1568+`. |
| BLE coverage tier classifier `get_ble_tier(room)` | **REUSED — drop-authorization gate.** `person_coordinator.py:1163-1226` (returns 1=dense/direct, 2=sparse/borrowing, 0=none). | D1.5: only Tier-1 rooms let BLE-absence (L2/L3) AUTHORIZE a drop. Tier-0/2 = "trust sensors only" — BLE veto-only (L1), drop rests on physical recheck. Prevents false-drop in scanner-blind rooms. |
| Per-room adjacency: `CONF_ADJACENT_ROOMS` | **REUSED — load-bearing for Tier-2 veto.** `const.py:373`; `config_flow.py:1104, 6620`; cached at `presence.py:1995-2017`, invalidated `:2179`. | L2 of the new ladder. In **Tier-2** rooms this is the PRIMARY BLE channel (borrowed scanner can't separate `adj` from `R`) and a positive hit VETOES (D1.5 tier-flip). In Tier-1 it's weak authorize, opt-in. Empty list = L2 skipped (no regression). Presence-coord adjacency cache exposed via a new public method `get_adjacent_rooms(room_name) -> List[str]` so the room-tier mechanism does not duplicate the cache. |
| `PersonPhoneLeftBehindSensor` H2 carve-out | **REUSED.** Class at `binary_sensor.py:1031`; closure helpers inlined at `presence.py:2787-2808` (`_phone_trustworthy`). | A phone-left-behind person must NOT count as "BLE present" for L1/L2 evaluation. Fail-OPEN when sensor disabled/unknown/unavailable. Extract to a shared module `domain_coordinators/_ble_corroboration.py` so the new room-tier ladder and the existing zone-tier diagnostic share one implementation. |
| Fan write surface: `hvac_fans._set_fan_state` | **REUSED.** `hvac_fans.py:499-532`. | The pause / restore actuation reuses this. NO new fan-write callsite — the new code calls thin wrappers that delegate to `_set_fan_state` with explicit pause-context flags. |
| `FanController._room_fans` + `manual_off_cooldown_until` | **REUSED — but reframed.** `hvac_fans.py:70-72, 200-225`. External fan_off → 1h cooldown. | The new pause is an INTERNAL URA write that must NOT trip the 1h external-cooldown path. The snapshot-and-restore preserves pre-pause `is_on / last_on_time / trigger / speed_pct` without setting `manual_off_cooldown_until`. Reviewer B + Reviewer C focus. |
| Existing fan-pause CONFs | **REUSED — operator-driven, ALWAYS WIN.** `CONF_FANS`, `CONF_FAN_CONTROL_ENABLED`, `CONF_FAN_VACANCY_HOLD`, `CONF_FAN_TEMP_THRESHOLD`. | Cross-rule precedence matrix (D2.5). |
| Per-kind `_room_provenance` split | **REUSED for cross-check only (P1).** `presence.py:412-561`. | P1 does NOT depend on the zone-tier provenance dict (the live divergence makes this unreliable today — Plan B unifies). The provenance dict is consulted by D2.7 acceptance ("does the zone-tier per-kind picture corroborate the room-tier verdict?") for diagnostic surface only. |
| `D3_DIAGNOSTIC_ENABLED` zone-tier diagnostic kill switch | **REUSED, unchanged.** `const.py:351`. | Stays as kill switch for the zone-tier observation diagnostic. The new room-tier mechanism gets its OWN kill switch (NEW: `CONF_FAN_RECHECK_ENABLED`). |
| v4.7.21 boot-settle gate `_boot_settle_done` | **REUSED.** `presence.py:4587` (and surrounding settle implementation). | Trigger condition requires `True`. Reviewer B confirms. |
| **Room-tier fan-pause + recheck state machine + actuation** | **NEW.** Grep `pause_fan_for|fan_recheck|fan_pause_state` across `custom_components/` returns 0 matches outside the prior planning drafts. | The headline NEW surface. ~280 LoC in a new file `domain_coordinators/presence_fan_recheck.py`. Owned PresenceCoordinator-side (the trigger lives there; actuation delegates to `hvac_fans`). |
| `CONF_FAN_RECHECK_ENABLED` (per-Presence-Coordinator master) | **NEW.** Default **False**. Verified absent. | Opt-in for first deploy; operator flips ON after live validation. |
| `CONF_ROOM_FAN_RECHECK_ENABLED` (per-room opt-in) | **NEW.** Default **False**. Verified absent. | Operator pins to Exercise + Jaya + Ziri first. Verified absent — grep `FAN_RECHECK` across `const.py` returns 0 matches. |
| `CONF_FAN_RECHECK_L2_ALLOWED` (per-room, **Tier-1-only** L2 authorize opt-in) | **NEW.** Default **False**. | Single boolean. Controls ONLY the **Tier-1** weak-*authorize* path (phone next-door → `R` likely empty → may trigger). Does NOT apply in Tier-2: there L2 adjacency is an *unconditional safety veto* (D1.5 tier-flip), never flag-gated. Keeps one clean polarity (the flag only ever *enables* a trigger, never disables a veto). |
| `CONF_FAN_RECHECK_TRUST_SENSORS_OK` (per-room still-capability attestation) | **NEW.** Default **False**. Verified absent — grep `FAN_RECHECK` / `TRUST_SENSORS` across `const.py` returns 0. | D1.5 gate for Tier-0/2 rooms: with no scanner, BLE can't authorize a drop, so the drop rests on the physical recheck — safe ONLY if the room's mmwave sees stillness. Operator sets True per-room only for still-capable sensors; still-blind rooms (e.g. Exercise hobeian) stay False = opt-out. Ignored for Tier-1 rooms (BLE backstops). |
| `ROOM_TYPE_RECHECK_FACTOR` (conservatism dial) | **NEW.** Map: `bedroom`/`media_room` → larger factor, others → 1.0. | D1.5: `room_type` is NOT an eligibility gate (would wrongly exclude Exercise + common areas). It extends the recheck window for high-still-risk types and forces L3-only (no L2) in Tier-1. |
| `CONF_FAN_RECHECK_ARM_DELAY_S` (Number, default 60, range 30-300) | **NEW.** | Settle time before pausing — gives L1/L2 a chance to fire and cancel. |
| `CONF_FAN_RECHECK_SPINDOWN_S` (Number, default 30, range 15-90) | **NEW.** | Fan spin-down window. Pause has to be long enough for airflow to stop so mmwave sees a clean field. |
| `CONF_FAN_RECHECK_WINDOW_S` (Number, default 60, range 30-180) | **NEW.** | After spin-down, hold fan off while observing mmwave. mmwave drops → fan-coupled, release. mmwave persists → real presence, restore. |
| `CONF_FAN_RECHECK_COOLDOWN_S` (Number, default 1800, range 600-7200) | **NEW.** | Per-room rate limit. 30-min default. |
| `CONF_FAN_RECHECK_MAX_PER_HOUR` (Number, default 2, range 0-4) | **NEW.** | Hard ceiling per room per hour. 0 disables. |
| `CONF_FAN_RECHECK_HVAC_SUPPRESS_S` (Number, default 600, range 120-1800) | **NEW.** | HVAC handshake duration — `FanController.update` skips this room's fan write for this long. Sized as `SPINDOWN + WINDOW + 2*margin`. |
| `CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS` (Number, default 3, range 1-10) | **NEW.** | Trigger requires occupancy_source == "mmwave" for this many consecutive ticks. Tightens against transient motion false-cancels. |
| `SIGNAL_FAN_RECHECK_STARTED` / `SIGNAL_FAN_RECHECK_FINISHED` | **NEW.** | NM dispatch hooks (first event of day to operator phone, subsequent silent). |
| `fan_recheck_state` SQLite table | **NEW.** Mirrors v4.7.8 `egress_state` shape. | Per-room state-machine row, persists across HA restart. See D4. |
| Service `ura.fan_recheck_force_restore(room_name)` | **NEW.** | Operator escape hatch if a recheck hangs. |
| Per-room sensors: `sensor.ura_room_<room>_fan_recheck_state` + `sensor.ura_room_<room>_fan_recheck_last_outcome` | **NEW.** | Operator visibility. |

### B. Prior planning docs consulted

| Doc | Relevance | Read depth |
|---|---|---|
| `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` | The doc that built the v4.7.20 hold (D1) and sketched the v4.7.8-style Layer-2 (D2). D1 is left in place by P1. D2's sketches inform the new state machine + DB shape but are re-derived in this doc to fit room-tier ownership. | Full body (carried from prior draft). |
| `docs/planning/PLANNING_fan_noise_mitigation_layer2_actuation.md` | The build-gate doc (G1-G6 + Options A/B/C). Build gate is moot. Operator's "real-world issues mandate" + spin-down framing (D1.5 bullets 1-4) carried forward. | Full body. |
| `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` | v4.7.19 cycle. Per-kind provenance + zone-tier diagnostic is the canonical KEEP surface. | Header + D2. |
| `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` | Snapshot/restore + 4-scenario restart-resilience template for `fan_recheck_state`. | Cross-reference. |
| `docs/planning/AUDIT_fan_interference_gate_ripple.md` | Predecessor's ripple audit. Companion `AUDIT_fan_recheck_room_tier_ripple.md` covers this cycle. | Header + per-consumer table. |
| `docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md` | The `_phone_trustworthy` H2 carve-out pattern. | Re-read. |
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | "Presence provides STATE, not ACTIONS" invariant. This cycle bends it (actuation owned by a presence-side helper module). Justification: trigger lives presence-side AND the verdict consumer (room-tier `coordinator.data["occupied"]`) is presence-adjacent. Fan write surface still delegates to `hvac_fans._set_fan_state` (single fan write surface preserved). | Re-read. |
| `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` | `FanController` is the canonical fan write-path owner. Operator-driven fan policy CONFs always win. | Re-read. |
| `docs/BACKLOG.md` Fan-noise entry | Operator's original premise. | Pinned to top. |
| `docs/planning/PLANNING_occupancy_substrate_unification.md` | **Companion plan (filed same session).** Defines the post-P1 substrate that absorbs the per-kind shape this plan uses for cross-check. | See § Seam-with-Substrate. |

### C. Memory bodies pulled

| File | Relevance |
|---|---|
| `project_v4_7_20_fan_noise_layer1_live.md` | "Two opposite failure modes" reframe (2026-06-05), Exercise Room live repro, fan entity IDs, the architecture caveat (room tier vs zone tier disagree), stuck-sensor-detector blind spot. THIS authorized the Mode-2 build. |
| `project_fan_noise_mmwave_mitigation_backlog.md` | Operator's original 3-layer BLE ladder design, the pets exclusion logic (only L3 beats pets). Operator's Layer-2 Option-C lean (active pause + recheck + DB persistence). |
| `project_v4_7_19_live.md` | Presence-tier per-kind provenance split. Cold-boot actuation storm context — new mechanism MUST suppress recheck attempts during the boot window (Bug Class #14). |
| `project_v4_7_21_boot_storm_live.md` | v4.7.21 cold-boot settle gates. The trigger subscribes to the same `_boot_settle_done` flag (`presence.py:4587`). |

### D. Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — "presence provides STATE not ACTIONS." This cycle bends that. Documented justification.
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — `FanController` owns the fan write path. The new mechanism delegates to `_set_fan_state`.

### E. Code locations surveyed (read end-to-end during scoping)

| File | Lines surveyed | What was confirmed |
|---|---|---|
| `coordinator.py` | `:178` (`_stuck_sensor_hours`), `:1241-1610` (`_async_update_data` full path), `:1289-1309` (stuck-sensor detector), `:1365` (flat-OR), `:1408-1444` (occupancy_source set including `mmwave`), `:1478-1523` (failsafe), `:1525-1554` (camera override), `:1556-1610` (BLE override) | THIS is the tier P1 hooks. The release path is a new method (`apply_fan_recheck_release`) called from the state machine; the next tick observes the cleared state. |
| `presence.py` | `:226` (`_classify_entity_kind`), `:380-386` (audit invariant), `:412-561` (provenance), `:1995-2017` (adjacency cache), `:2168-2308` (`_discover_room_sensors` area-sweep), `:2539-2698` (`_compute_fan_interference_rooms`), `:2787-2808` (`_phone_trustworthy` closures), `:3503-3560` (D5 guest-room subscribe to `binary_sensor.<room>_occupied`), `:4587` (boot-settle gate) | The strip surface (P2 only) AND the BLE-ladder helpers to extract. Guest-room detector reads room-tier sensor — release path naturally propagates. |
| `hvac_fans.py` | `:1-260+` (init, `turn_off_all_managed`, `update` loop, `manual_off_cooldown_until`) | Single fan write surface. Cooldown trip risk understood. |
| `hvac_zones.py` | `:537-552` (`coordinator.data.get("occupied", False)`) | HVAC fan write reads room tier — confirms why zone-tier hold cannot help Mode 2. |
| `hvac.py` | `check_zone_occupancy_confidence` callsite (HVAC defer gate) | Release fires through this naturally via room-tier sensor. |
| `person_coordinator.py` | `:1140-1245` | BLE Tier-1 + zone reads. |
| `binary_sensor.py` | `:410-510` (OccupiedBinarySensor attr block), `:1031` (`PersonPhoneLeftBehindSensor`) | Attr surface to extend (add `fan_recheck_*`). |
| `const.py` | `:208, 223, 628, 637` (STATE_*), `:311-313` (CONF_*_SENSORS), `:351` (`D3_DIAGNOSTIC_ENABLED`), `:373` (`CONF_ADJACENT_ROOMS`) | Confirms surface and the existing kill switch. |
| `signals.py` | `:118` (`SIGNAL_FAN_INTERFERENCE_GATE_FIRED`) | Subscriber count zero — relevant only for P2. |

---

## Non-goals (explicit, locked)

- **No new house-level state.** P1 only releases per-room occupancy.
- **No DPM / preset interaction.** The pause is a temporary fan command — does NOT mutate HVAC mode or preset.
- **No automatic fleet enablement.** Per-room opt-in (default OFF).
- **No removal of v4.7.19 per-kind provenance.** That cycle is good prior work and stays.
- **No PIR + mmwave fusion in this cycle.** Hardware-gated; stays as research backlog.
- **No HA community blueprint here.** Stays as research backlog.
- **No fight with HVAC.** The HVAC suppression handshake (D3) is mandatory.
- **No double-actuation with EgressManager.** EgressManager wins over fan-recheck.
- **Mode 1 (DROPOUT) is OUT of P1.** If a Mode-1 regression surfaces post-deploy, file a follow-up — do NOT re-add hold extension to this cycle.
- **P1 does NOT depend on Plan B (substrate).** P1 uses the room-tier `STATE_OCCUPANCY_SOURCE == "mmwave"` directly. The substrate cycle is the follow-up cleanup — see § Seam-with-Substrate.

---

## P1 — Mode-2 deliverable (room-tier BLE-gated fan-pause + clean recheck)

### D1 — Trigger condition (precise)

For a room `R` with `CONF_ROOM_FAN_RECHECK_ENABLED == True` AND
`CONF_FAN_RECHECK_ENABLED == True` (master) AND `CONF_FAN_CONTROL_ENABLED != False`:

Recheck is **ELIGIBLE** when ALL hold simultaneously at the room update tick:

1. `data[STATE_OCCUPIED] == True`.
2. `data[STATE_OCCUPANCY_SOURCE] == "mmwave"` AND has been "mmwave" for the last
   `CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS` consecutive ticks (default 3 — tightens against
   transient motion flips that would cancel a legitimate Mode-2 latch). The history tracker
   adds 1 LoC + a small ring on RoomCoordinator (`_recent_occupancy_sources: collections.deque(maxlen=10)`).
3. Room has at least one `CONF_FANS` entity AND at least one of those fans is currently
   `on` (state.get == "on") via `hass.states.get(fan_entity).state == "on"`.
4. **BLE-tier drop-authorization gate (see D1.5).** Verdict depends on the room's BLE
   coverage tier from `person_coord.get_ble_tier(R)` (person_coordinator.py:1163):
   - **Tier 1 (dense / direct-BLE):** the D2 ladder authorizes. Eligible when verdict is
     **L3** (zone-wide absence; default-allowed) OR **L2** when
     `CONF_FAN_RECHECK_L2_ALLOWED == True`. L1 ALWAYS vetoes. (Exception — D1.5 room_type
     dial: for `bedroom` / `media_room`, L3 is REQUIRED and L2 is rejected regardless of
     the flag.)
   - **Tier 2 (sparse / borrowing):** "trust sensors only" for AUTHORIZATION, but **trust
     positive BLE for VETO.** The room borrows a neighbor's scanner and cannot separate "in
     `R`" from "in the borrowed area," so a trustworthy phone in the borrowed area (already
     folded into L1 via `_scanner_to_rooms`) OR in any `CONF_ADJACENT_ROOMS` neighbor (L2)
     **vetoes** the recheck — it could be in `R`. BLE-*absence* still may NOT authorize (no
     scanner proves `R` empty). Eligibility rests on conditions 1-3 (mmwave-sole + fan-on) +
     physical recheck + `CONF_FAN_RECHECK_TRUST_SENSORS_OK == True` for `R`.
   - **Tier 0 (no scanner):** veto via L1 only (no borrowed/adjacent BLE channel). Same
     authorization gate as Tier 2 (sensors-only + `CONF_FAN_RECHECK_TRUST_SENSORS_OK`).
5. Per-room rate-limit allows: state machine is NOT in `cooldown`, AND
   `attempts_in_last_hour < CONF_FAN_RECHECK_MAX_PER_HOUR`.
6. State machine is currently `idle`.
7. Boot-settle gate `_boot_settle_done == True` (cold-boot storm guard — Bug Class #14).
8. No `EgressManager` pause is currently active for the zone owning this room.
9. No `manual_off_cooldown_until` active for the room's fan (`hvac_fans.RoomFanState`).
   If active, fan was just externally turned off — we have no business turning it back on
   to spin up to recheck.

### D1.5 — BLE-tier drop-authorization + still-capability gate

**Why tier-gate the drop.** `_ble_occupied` and the L3 zone-absence rung are evidence of
vacancy *only in rooms a BLE scanner can actually see.* `person_coord.get_ble_tier(R)`
classifies coverage:

- **Tier 1 — dense / direct-BLE** (own scanner, in `_direct_ble_rooms`,
  `is_room_direct_ble == True`). BLE-absence genuinely means "no phone in this room." The D2
  ladder authorizes a drop; L3 zone-absence is the strong default-allowed rung.
- **Tier 2 — sparse / borrowing** (`CONF_SCANNER_AREAS` set, no own scanner). Per the existing
  invariant "BLE alone should not drive occupancy without motion/mmWave confirmation"
  (person_coordinator.py), BLE-*absence* is the room's *default* state whether occupied or not
  — it cannot authorize a drop. But **positive** BLE in the borrowed area or an adjacent room
  is meaningful and IS trusted — as a veto (see the adjacency tier-flip below).
- **Tier 0 — no scanner.** Same as Tier 2, more so.

**Asymmetry (the v4.7.20 hold's fail-safe logic, inverted).** Extending occupancy on
`not _ble_occupied` is fail-SAFE (worst case: a fan runs slightly longer). DROPPING occupancy
on `not _ble_occupied` is fail-DANGEROUS in Tier-0/2 (worst case: we cut AC / pause a fan on a
present-but-still person who carries no phone signal a scanner can see here). So the
authorization is asymmetric: BLE may VETO a pause in any tier (L1), but may only AUTHORIZE a
drop in Tier 1.

**Adjacency tier-flip — the SAME signal means opposite things.** A trustworthy phone in an
adjacent room is read differently depending on whether `R` has independent scanner coverage:
- **Tier 1:** `R` has its own scanner. A phone in `adj` but NOT on `R`'s scanner means the
  person is provably *next-door* → weak evidence `R` is *empty* → L2 may weakly **authorize**
  (opt-in, `CONF_FAN_RECHECK_L2_ALLOWED`, default False — drift-prone).
- **Tier 2:** `R` *borrows* the neighbor's scanner (`_scanner_to_rooms`,
  person_coordinator.py:521-547; resolution maps a borrowed-scanner detection to the
  borrowing room at `:593-616`) and cannot separate "in `R`" from "in the borrowed/adjacent
  area." A phone in the borrowed area (folded into L1) or any `CONF_ADJACENT_ROOMS` neighbor
  (L2) *could be in `R`* → **VETO, unconditional** (a safety veto — it is NOT gated by
  `CONF_FAN_RECHECK_L2_ALLOWED`; that flag is Tier-1-only). This is the operator's "trust
  that signal" for borrowing rooms. Over-veto recourse, if a mis-listed neighbor suppresses
  the recheck forever, is to fix `CONF_ADJACENT_ROOMS` — not to disable the safety veto.

So **positive** BLE (own / borrowed / adjacent) is trusted as a veto in *every* tier; BLE
*absence* only authorizes in Tier 1.

**"Trust sensors only" for the DROP in Tier-0/2.** With BLE-absence removed as an authorizer
(but positive BLE retained as a veto), the drop rests entirely on the **physical recheck** —
pause the fan, watch whether mmwave actually falls. That is safe *only if the room's sensors
can see a still occupant.* Exercise's hobeian "does not capture still states," so even the
physical recheck can false-drop a motionless person. Therefore Tier-0/2 eligibility
additionally requires a per-room still-capability attestation `CONF_FAN_RECHECK_TRUST_SENSORS_OK`
(NEW, default **False**). Rooms whose sensors are still-blind stay opt-out (operator leaves it
False; future: notify-instead-of-actuate). Tier-1 rooms do not need this flag — BLE backstops
the recheck.

**room_type as a conservatism DIAL, not an eligibility gate.** `self._room_type`
(coordinator.py:163-165) does NOT decide *whether* a room is eligible — gating on it would
wrongly exclude the Exercise room (`generic`/`utility`, the live Mode-2 repro) and common
areas, which suffer the same still-occupancy latch. Instead, for high-still-risk types
(`bedroom`, `media_room`) the mechanism demands *stronger* confirmation before a drop: the
recheck window is extended (`CONF_FAN_RECHECK_WINDOW_S * ROOM_TYPE_RECHECK_FACTOR`) and, where
the room is Tier-1, L3 zone-absence is required (L2 rejected regardless of
`CONF_FAN_RECHECK_L2_ALLOWED`). It tunes *how careful*, never *whether eligible*.

### D2 — BLE ladder (shared helpers extracted from v4.7.20 zone-tier code)

Extract `_phone_trustworthy` and `_trustworthy_persons_in_room` from
`presence.py:2787-2818` to a NEW shared module `domain_coordinators/_ble_corroboration.py`
(no behavior change; presence.py imports from there). The new room-tier ladder calls the
same functions.

For room `R` in zone `Z`:

- **L1 — room BLE present.** `person_coord.get_persons_in_room(R)` returns ≥1 trustworthy
  person (H2 carve-out applied). **VETO any recheck.** Real presence.
- **L2 — adjacent room BLE present.** For each `adj` in
  `get_adjacent_rooms(R)` (NEW public method on PresenceCoordinator that reads the
  existing `_adjacency_cache`): if any trustworthy phone in `adj`, L2 hit. **Meaning is
  tier-dependent (D1.5 adjacency tier-flip):**
  - **Tier 1:** `R` has its own scanner → a phone in `adj` (room-absent) means person is
    provably next-door → **WEAK authorize**, opt-in via `CONF_FAN_RECHECK_L2_ALLOWED`
    (default False, drift-prone).
  - **Tier 2:** `R` borrows the neighbor's scanner → an adjacent/borrowed-area phone could
    be in `R` → **VETO, unconditional** (trust the signal; NOT gated by
    `CONF_FAN_RECHECK_L2_ALLOWED`, which is Tier-1-only). Over-veto recourse = fix
    `CONF_ADJACENT_ROOMS`, not disable the safety veto.
- **L3 — zone-wide BLE absence.** `person_coord.get_persons_in_zone(zone_rooms)` returns
  no trustworthy persons. **STRONGEST — default-allowed trigger.**
- **none** — zone has no BLE infrastructure OR all BLE entities unknown/unavailable.
  **DO NOT TRIGGER.** Fail-OPEN — operator's no-regression mandate.

**Tier gating (D1.5):** L1 VETO is active in every tier. The *absence-authorizing* rungs
(L3, "none") only gate eligibility in **Tier-1** — in Tier-2/0 they are inert (no scanner
proves `R` empty), so the drop rests on the physical recheck + `CONF_FAN_RECHECK_TRUST_SENSORS_OK`.
**L2 (adjacent-present) FLIPS meaning by tier:** weak authorize in Tier-1 (person provably
next-door, opt-in via `CONF_FAN_RECHECK_L2_ALLOWED`), but an **unconditional VETO** in Tier-2
(borrowed scanner can't separate `adj` from `R`; the flag does not apply). Net: positive BLE
is a veto in every tier; only BLE *absence* authorizes, and only in Tier-1.

Pets: only L3 zone-absence rejects pets (no phone on the dog). L1/L2 don't.

### D3 — State machine (room-scope)

Owner: `domain_coordinators/presence_fan_recheck.py` (NEW file, ~280 LoC). Ticked
from the PresenceCoordinator inference loop (same loop that already drives the
zone-tier diagnostic).

States:

- `idle` — default. Trigger conditions evaluated each room update tick. No actuation.
- `armed` — trigger fired this tick. Wait `CONF_FAN_RECHECK_ARM_DELAY_S` (default 60s) for
  L1 to fire and cancel. Cancellation paths: L1 fires, `occupancy_source` flips off
  "mmwave" (motion or occupancy sensor fires — real presence corroborated), operator
  issues a `fan.turn_on` service call, `CONF_FAN_CONTROL_ENABLED` flips False mid-arm.
  Cancel transitions to `cooldown`.
- `paused` — set HVAC suppression-until = `now + CONF_FAN_RECHECK_HVAC_SUPPRESS_S`. Call
  `FanController.pause_for_recheck(room)` → snapshot taken + fan turned off via
  `_set_fan_state(entities, False, 0)`. Wait `CONF_FAN_RECHECK_SPINDOWN_S` (default 30s)
  for blades to stop, then wait `CONF_FAN_RECHECK_WINDOW_S` (default 60s) observing mmwave.
  Cancellation paths: any operator-driven `fan.turn_on` from outside URA, L1 fires, motion
  or occupancy sensor fires. Cancel → `restoring`.
- `restoring` — call `FanController.restore_after_recheck(room, snapshot)` (restores
  pre-pause `percentage / preset_mode / oscillating / direction`). Verdict written:
  `vacated` (mmwave dropped during window) or `occupied_confirmed` (mmwave persisted).
  If `vacated`: call new `RoomCoordinator.apply_fan_recheck_release()` which clears
  `_last_motion_time`, `_became_occupied_time`, sets `data[STATE_OCCUPANCY_SOURCE] =
  "fan_recheck_release"`, sets `data[STATE_OCCUPIED] = False`. If `occupied_confirmed`:
  no occupancy mutation. Wait `CONF_FAN_RECHECK_SPINDOWN_S / 2` for fan to ramp up
  → `cooldown`.
- `cooldown` — block recheck for `CONF_FAN_RECHECK_COOLDOWN_S` (default 1800s). Decrement
  per-hour attempts counter at the hour boundary. Transition to `idle` at expiry.

### D4 — HVAC handshake (cross-coordinator contract)

The pause window MUST suppress `FanController.update`'s per-room fan write for `R`.

**Implementation:**
- ADD `RoomFanState.fan_recheck_suppress_until: str = ""` (NEW field, hvac_fans.py).
- ADD `FanController.suppress_room_until(room_name: str, until_iso: str) -> None`.
- ADD `FanController.pause_for_recheck(room_name) -> FanSnapshot | None`:
  - Snapshot current entity attrs (`percentage / preset_mode / oscillating / direction`).
  - Call `_set_fan_state(entities, False, 0)` DIRECTLY.
  - Do NOT enter `manual_off_cooldown_until` branch (this is internal, not external).
  - Preserve pre-pause `RoomFanState.is_on=True` in the dataclass so restore knows what
    to restore.
- ADD `FanController.restore_after_recheck(room_name, snapshot)`:
  - Call `_set_fan_state(entities, True, snapshot.percentage)`.
  - Restore `preset_mode / oscillating / direction` if differed via additional service
    calls (each gated on attr being present in snapshot).
- MODIFY `FanController.update` loop: at top of per-room iteration, check
  `RoomFanState.fan_recheck_suppress_until` — if set and > now, `continue` past this room
  without altering its `is_on / last_on_time / trigger / speed_pct` (HVAC is not
  arbitrating this room during the pause window). Also do NOT trip the external-cooldown
  detection (`:204-225`) while suppression is active — the entity may legitimately be off
  because WE turned it off.

**Suppression-window sizing:** default = `SPINDOWN + WINDOW + 2 * RESTORE_DELAY + margin`
(operator-tunable via `CONF_FAN_RECHECK_HVAC_SUPPRESS_S`). The state machine clears
suppression early on `cooldown` transition so HVAC re-arbitrates immediately next tick.

### D5 — Pause precedence + cross-rule matrix

| Rule | Winner over fan-recheck | Notes |
|---|---|---|
| Operator-driven `fan.turn_on` from outside URA during `paused` | OPERATOR | Cancel to `restoring`; restore snapshot then `cooldown` |
| `CONF_FAN_CONTROL_ENABLED == False` for room | OPERATOR | Forbidden from touching this room |
| `CONF_FAN_VACANCY_HOLD` active + fan-temp manager asserting | TEMP MANAGER | Defer recheck (stay `idle`; trigger re-evaluates next tick) |
| `CONF_FAN_TEMP_THRESHOLD` says fan is on for heat/cool | TEMP | Don't pause a fan running for thermal need — exclude from trigger |
| `EgressManager` paused this zone | EGRESS | Stay `idle` |
| Boot-settle window (`_boot_settle_done == False`) | SETTLE | Block trigger entirely |
| `CONF_FAN_RECHECK_MAX_PER_HOUR` exceeded | RATE LIMIT | Block trigger; force `cooldown` if currently armed |
| Operator service `ura.fan_recheck_force_restore(room_name)` | OPERATOR | Immediate `restoring` from snapshot; force `cooldown` |
| Stuck-sensor detector | EXISTING | Stuck-flagged sensor already excluded from `presence_detected` → `occupancy_source != "mmwave"` → trigger doesn't fire. Two mechanisms compose. |
| Failsafe just fired | FAILSAFE | `_failsafe_fired == True` → camera + BLE overrides already skipped → recheck likewise skipped. |
| `manual_off_cooldown_until` active for the room's fan | EXISTING | Already excluded by D1 #9. Operator just externally killed the fan; we don't re-spin it. |

### D6 — Restart resilience (mirror v4.7.8 §D6)

| Scenario | Behavior on `async_setup` rehydrate |
|---|---|
| Restart while `paused` | Read snapshot; if `(now - state_entered_at) < CONF_FAN_RECHECK_WINDOW_S * 2`, transition `restoring` immediately. Else snapshot too old → log warning, transition `idle`, do not actuate. |
| Restart while `restoring` | Transition `idle` (HA restart resets fan to physical state); log restore skipped; operator can intervene. |
| Restart while `cooldown` | Honor remaining cooldown (state machine re-arms from `state_entered_at`). |
| Restart while `armed` | Drop to `idle` — trigger re-evaluates next room update tick. Bug Class #14. |
| Restart while `idle` | Stay `idle`. |
| Snapshot row corrupt / unparseable | Drop the row; log warning; treat as `idle`. |

### D7 — `fan_recheck_state` schema

| Column | Type | Notes |
|---|---|---|
| `room_id` | TEXT PRIMARY KEY | Room config entry_id |
| `state` | TEXT NOT NULL | One of: idle, armed, paused, restoring, cooldown |
| `state_entered_at` | TEXT | ISO8601 UTC |
| `snapshot_json` | TEXT | JSON-serialized FanSnapshot (entity_id + percentage + preset_mode + oscillating + direction) |
| `attempts_in_hour` | INTEGER NOT NULL DEFAULT 0 | Rolling-1h counter, decayed at read |
| `last_outcome` | TEXT | `vacated` / `occupied_confirmed` / NULL |
| `last_attempt_at` | TEXT | ISO8601 UTC |
| `ble_ladder_layer` | TEXT | L1 / L2 / L3 / none — verdict at last trigger |

DDL extracted from production source by behavioral test (Reviewer C — Tier 2-DB fixture
authority rule).

### D8 — Files changed (P1 only)

| File | Change |
|---|---|
| `const.py` | ADD `CONF_FAN_RECHECK_ENABLED`, `CONF_ROOM_FAN_RECHECK_ENABLED`, `CONF_FAN_RECHECK_L2_ALLOWED`, `CONF_FAN_RECHECK_TRUST_SENSORS_OK`, `CONF_FAN_RECHECK_ARM_DELAY_S`, `CONF_FAN_RECHECK_SPINDOWN_S`, `CONF_FAN_RECHECK_WINDOW_S`, `CONF_FAN_RECHECK_COOLDOWN_S`, `CONF_FAN_RECHECK_MAX_PER_HOUR`, `CONF_FAN_RECHECK_HVAC_SUPPRESS_S`, `CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS`, `ROOM_TYPE_RECHECK_FACTOR`, defaults. KEEP `CONF_ADJACENT_ROOMS`, `D3_DIAGNOSTIC_ENABLED`, `CONF_FAN_INTERFERENCE_HOLD_S` (P2 decides whether to strip). |
| `person_coordinator.py` | NO change — `get_ble_tier` consumed read-only by D1.5 drop-authorization gate. |
| `signals.py` | ADD `SIGNAL_FAN_RECHECK_STARTED`, `SIGNAL_FAN_RECHECK_FINISHED`. KEEP `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` (P2). |
| `domain_coordinators/_ble_corroboration.py` | NEW (extracted from `presence.py:2787-2818`). `_phone_trustworthy(hass, person_name) -> bool`, `_trustworthy_persons_in_room(person_coord, room, hass) -> List[str]`. Fail-OPEN on entity-registry lookup failures. |
| `domain_coordinators/presence.py` | IMPORT shared helpers from `_ble_corroboration` (replace inline closures; behavior unchanged). ADD public method `get_adjacent_rooms(room_name) -> List[str]` reading the existing adjacency cache. No other changes in P1. |
| `domain_coordinators/presence_fan_recheck.py` | NEW (~280 LoC). State machine, DB rehydrate, snapshot/restore, manual override, cooldown, NM dispatch. Listener teardown on coordinator unload. NO function-local `async_dispatcher_send` imports (Bug Class #34 / v4.7.20.1). |
| `domain_coordinators/hvac_fans.py` | ADD `RoomFanState.fan_recheck_suppress_until` field. ADD `FanController.suppress_room_until`, `pause_for_recheck`, `restore_after_recheck`. MODIFY `FanController.update` loop to honor suppression. |
| `coordinator.py` | ADD public method `apply_fan_recheck_release()` on RoomCoordinator (clears `_last_motion_time`, `_became_occupied_time`, sets `data[STATE_OCCUPIED]=False`, `data[STATE_OCCUPANCY_SOURCE]="fan_recheck_release"`, `data[STATE_TIMEOUT_REMAINING]=0`). ADD ring buffer `_recent_occupancy_sources` (deque(maxlen=10)) appended at the end of `_async_update_data` so the trigger can consult history. |
| `database.py` | NEW `fan_recheck_state` table + 5 DAOs (`get_fan_recheck_state(room_id)`, `save_fan_recheck_state(row)`, `get_all_fan_recheck_state()`, `clear_fan_recheck_state(room_id)`, `prune_stale_fan_recheck_state(cutoff_days=14)`). |
| `config_flow.py` | ADD per-room `CONF_ROOM_FAN_RECHECK_ENABLED` + `CONF_FAN_RECHECK_L2_ALLOWED` selectors. KEEP `CONF_ADJACENT_ROOMS`. |
| `options_flow.py` | ADD per-Presence-Coordinator `CONF_FAN_RECHECK_ENABLED` master + 7 timing Numbers. |
| `switch.py` | ADD `FanRecheckEnabledSwitch` (per-PC master), `RoomFanRecheckEnabledSwitch` (per-room), `RoomFanRecheckL2AllowedSwitch` (per-room L2 opt-in). |
| `number.py` | ADD 7 `FanRecheck*Number` entities. |
| `binary_sensor.py` | MODIFY `OccupiedBinarySensor` attr block: ADD `fan_recheck_state`, `fan_recheck_last_outcome`, `fan_recheck_last_attempt_iso`, `fan_recheck_ble_ladder_layer`. KEEP `fan_interference_suspect` (zone-tier read). KEEP `fan_interference_hold_active`, `fan_interference_hold_until_iso`, `ble_corroboration_layer` (P2 strips). ADD `RoomFanRecheckInProgress` per opted-in room. |
| `sensor.py` | ADD `RoomFanRecheckStateSensor` + `RoomFanRecheckLastOutcomeSensor` per opted-in room. |
| `services.yaml` | ADD `fan_recheck_force_restore(room_name)`. |
| `__init__.py` | Wire `presence_fan_recheck` module instantiation on PresenceCoordinator async_setup; teardown on unload. |
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | UPDATE: document the boundary-bend ("presence-tier owns this one actuation because the trigger and verdict consumer are both presence-adjacent; ALL fan writes still go through `hvac_fans._set_fan_state`"). |
| `docs/QUALITY_CONTEXT.md` | ADD candidate bug class entry "Fan-coupled mmwave latch invisible to stuck-sensor detector (Mode 2)" with Exercise Room repro. |

### D9 — Cold-boot storm coordination

Trigger condition D1 #7 requires `_boot_settle_done == True`. The state machine never
enters `armed` during boot. Test: `test_fan_recheck_blocked_during_boot_settle.py`.

### D10 — Acceptance Criteria

- **Verify (energy waste primary):** Exercise Room live repro — `fan.fan_switch_3` on +
  `binary_sensor.exercise_room_occupied` on + room provably empty (operator absent, BLE
  zone-absent). State machine enters `armed` within one tick, transitions `paused` after
  `ARM_DELAY_S`. Within `SPINDOWN + WINDOW`, if mmwave drops with fan off,
  `binary_sensor.exercise_room_occupied` flips OFF and `STATE_OCCUPANCY_SOURCE ==
  "fan_recheck_release"`. HVAC observes the release; AC stops in the empty room.
- **Verify (Jaya):** same repro with `fan.fanswitch_treat_wifi_jayabedroom` +
  `binary_sensor.jaya_bedroom_bedroom_4_occupied`. Release happens. If L1 fires (Jaya's
  phone in room), trigger NEVER fires.
- **Verify (Ziri):** same repro with `fan.fanswitch_treat_wifi_ziribedroom` +
  `binary_sensor.ziri_bedroom_bedroom_5_occupied`.
- **Verify (L1 veto):** with operator phone present (L1), trigger NEVER fires.
- **Verify (H2 carve-out):** when `PersonPhoneLeftBehindSensor` for a person is `on`,
  L1/L2 exclude that person.
- **Verify (HVAC handshake):** during a full `paused → restoring` cycle, `FanController.update`
  is called ≥1 time and does NOT issue `fan.turn_on` for the room. Verified via
  service-call trace + a behavioral test driving the suppression contract.
- **Verify (mmwave-history precondition):** a single transient motion blip during the
  `mmwave-sole` history window cancels the trigger (and 3 consecutive ticks of mmwave-
  sole are required to arm). Configurable via `CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS`.
- **Verify (occupied_confirmed):** operator walks into room mid-pause → motion fires →
  state machine cancels to `restoring`; fan restored from snapshot; room stays occupied;
  operator does not experience a "disconcerting" extended pause.
- **Verify (restart):** all 6 restart scenarios in D6 behave correctly (behavioral tests
  with synthetic DB state).
- **Verify (stuck-sensor non-regression):** stuck-sensor detector still works for
  non-fan stuck cases.
- **Verify (Mode-1 non-regression):** Master Bedroom overnight — Mode-2 trigger NEVER fires
  during sleep (L3 zone-present from BLE → no trigger). Master Bedroom is NOT opted-in for
  v1 in any case.
- **Sensor:** `binary_sensor.<room>_occupied` carries `fan_recheck_state`,
  `fan_recheck_last_outcome`, `fan_recheck_last_attempt_iso`,
  `fan_recheck_ble_ladder_layer` attrs (visible on Exercise Room post-deploy).
- **Sensor:** `sensor.ura_room_<room>_fan_recheck_state` per opted-in room, round-trips
  through restart.
- **Sensor:** `sensor.ura_room_<room>_fan_recheck_last_outcome` shows `vacated` or
  `occupied_confirmed` after first event.
- **Test:** `quality/tests/test_fan_recheck_trigger_eligibility.py` — all 9 trigger
  conditions.
- **Test:** `quality/tests/test_fan_recheck_state_machine.py` — all 5 states +
  cancellation paths.
- **Test:** `quality/tests/test_fan_recheck_ble_ladder.py` — L1/L2/L3/none + H2.
- **Test:** `quality/tests/test_fan_recheck_hvac_handshake.py` — suppression contract +
  manual_off_cooldown_until carve-out.
- **Test:** `quality/tests/test_fan_recheck_restart_resilience.py` — 6 scenarios.
- **Test:** `quality/tests/test_fan_recheck_db_schema.py` — DDL extracted from production.
- **Test:** `quality/tests/test_fan_recheck_cross_rule_precedence.py` — cross-rule matrix.
- **Test:** `quality/tests/test_fan_recheck_mmwave_history_precondition.py`.
- **Live:** Exercise Room observed `vacated` outcome ≥1 within 24h of operator enabling
  the room. Manual `fan_recheck_force_restore` verified via service call. Operator confirms
  the AC-waste pattern stops in opted-in rooms.

---

## P2 — OPTIONAL: strip the v4.7.20 hold (pending operator decision)

**Status:** Pending operator decision. NOT bundled into P1. The v4.7.20 hold lives on the
zone tier (`ZonePresenceTracker._room_occupied`) and HVAC's fan write path reads the room
tier. The hold is therefore inert against Mode-2 and cannot interfere with P1 in place.

Two reasons to consider stripping after P1 lands:

1. **Hygiene.** It's unused machinery and the v4.7.20 LIVE memo recorded zero gate fires
   over 10 fans on (zero rooms had mmwave-sole-kind needed to engage the gate). The dead
   code still touches `_audit_provenance_invariants`, derived `_room_occupied`, sensor
   attrs, and a Number entity.
2. **Plan B (substrate) is cleaner without it.** The substrate cycle's invariant "derived
   OR ⊇ recorded kinds" returns to v4.7.19 strict shape if the hold is gone.

Two reasons to consider keeping:

1. **Mode-1 protection backstop.** If Mode 1 (DROPOUT) returns in some room (e.g.,
   master bedroom overnight) the hold may quietly help. Reviewer A's Mode-1 watch on P1
   live-validation answers whether this is a live concern.
2. **Strip is non-trivial.** The full removal list is in the prior draft (15 code sites,
   1 entity, 1 test file, 3 sensor attrs, 1 audit-doc supersedence). Each removal touches
   review surface area.

If the operator decides to ship P2:

- Strip list as in the prior draft (carry forward verbatim — DELETE
  `CONF_FAN_INTERFERENCE_HOLD_S`, `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`,
  `_fan_interference_hold_until`, `_fan_interference_gated_prev`,
  `_apply_fan_interference_gate`, `FanInterferenceHoldNumber`, the three v4.7.20 attrs
  on OccupiedBinarySensor, the `fan_interference_gated_rooms` key, and
  `quality/tests/test_fan_interference_gate_layer1.py`).
- Add one-shot entity-registry orphan cleanup for `FanInterferenceHoldNumber` unique_id
  on `async_setup_entry` (idempotent).
- Revert `_audit_provenance_invariants` to "derived OR ⊇ recorded kinds" (v4.7.19 shape).
- Mark `AUDIT_fan_interference_gate_ripple.md` SUPERSEDED.
- Plan B (substrate) ships cleaner if P2 is done first; P2-after-Plan-B works too.
- File P2 as a Tier 2 cycle (NOT Tier 2-DB — pure removal, no DB shape change).

Tier 2 (NOT 2-DB) is sufficient for P2 alone: payload-shape change is to a documented
sensor attr surface only (Recorder gracefully drops removed keys; no analytics depend on
the v4.7.20 attrs per cross-repo grep).

---

## Seam-with-Substrate (CRITICAL — read with companion doc open)

The substrate cycle (Plan B) replaces the area-sweep+keyword discovery in
`presence.py:2168-2308` with consumption of the same `CONF_MOTION/MMWAVE/OCCUPANCY_SENSORS`
lists the room tier uses, and removes the `_classify_entity_kind` heuristic by reading
kind from the CONF list slot. The substrate publishes a per-room, per-kind, instantaneous
raw-signal view that BOTH the room tier and zone tier consume (each applying its own
temporal smoothing on top).

**P1 code surfaces the substrate will later absorb or refactor (verbatim — both docs
quote this list):**

1. **`CoordinatorRoomCoordinator._recent_occupancy_sources` ring (NEW in P1, D8).** Used
   by the trigger to require N consecutive mmwave-sole ticks. After substrate, this can
   be derived from the substrate's per-kind, per-tick raw view directly without a
   coordinator-local ring. The ring will likely be RETAINED as a thin convenience on top
   of the substrate (substrate gives the data, the ring gives the recent-history shape) —
   no churn, just simpler internals.
2. **`STATE_OCCUPANCY_SOURCE == "mmwave"` precondition (D1 #2).** Post-substrate, this is
   replaceable with "substrate says mmwave True AND motion False AND occupancy False for
   the last N ticks" — a strictly more precise statement (today's `STATE_OCCUPANCY_SOURCE`
   collapses to one winner; substrate exposes all kinds). P1's check survives as a
   compatibility shim during the substrate transition; the substrate cycle's D-list will
   document the swap explicitly.
3. **Zone-tier diagnostic cross-check** (D2.7 acceptance — "does the zone-tier per-kind
   picture corroborate?"). Today this is unreliable because of the area-sweep divergence;
   post-substrate, room tier and zone tier agree by construction and the cross-check
   becomes trivially True. The acceptance criterion is REWRITTEN post-substrate to "the
   substrate per-kind view at trigger time records mmwave-only across all kinds for at
   least N ticks."
4. **No new state-machine code is absorbed.** The fan-recheck state machine
   (`presence_fan_recheck.py`) and the HVAC handshake (`hvac_fans` additions) are
   substrate-agnostic — both stay verbatim.

**Recommendation: P1 → P2-or-Plan-B (operator picks the order).** Plan B (substrate) is
the cleanest post-P1 hygiene win and the two are independent enough to be sequenced either
way. P1 must NOT block on either P2 or Plan B.

**Did the planner consider substrate-first?** Yes. Justification for P1-first:
- The live energy waste is observable today. Substrate-first would push the Mode-2 fix
  out by one full cycle for no Mode-2 win.
- Plan A does not depend on the substrate. `STATE_OCCUPANCY_SOURCE == "mmwave"` is already
  set correctly today by the room-tier flat-OR precedence at `coordinator.py:1416-1420`.
  The substrate makes the precondition more precise (kind-wise) but the current `mmwave`
  source-attribution is correct for Mode-2 trigger purposes (the failure mode IS "mmwave
  is the lone driver").
- The H2 carve-out (`_phone_trustworthy`) and BLE ladder do not depend on the substrate.
- Reviewer B's "race + restart resilience" focus is symmetric across the substrate; no
  substrate-driven async simplification is on offer.

If during P1 build any of the above turns out to be wrong (e.g., the `mmwave`-sole
precondition is too noisy to be useful without substrate), STOP and flip the order.

---

## D-Open — Open questions / scope risks for operator weigh-in

1. **Ownership of the new state machine.** Recommendation: `presence_fan_recheck.py` ticked
   from PresenceCoordinator. Alternative: own from `hvac_fans.py`. Picked presence-side
   because the trigger condition lives there and the verdict consumer
   (`room_coordinator.apply_fan_recheck_release`) is a one-line call back to the room tier.
   Operator-confirm.
2. **L2 default behavior.** Defaults to "do not trigger" (drift may be real presence in
   the neighbor). Per-room opt-in via `CONF_FAN_RECHECK_L2_ALLOWED`. Operator-confirm.
3. **HVAC handshake direction.** PUSH (presence tells HVAC to skip room until X). Alternative:
   PULL (HVAC reads state machine each tick). PUSH is simpler + faster but couples HVAC to a
   presence data model. Recommended PUSH; operator decides.
4. **Fan spin-down default 30s.** Per-PresenceCoordinator default. Promote to per-room if a
   room model needs different timing post-deploy. Operator-confirm.
5. **NM dispatch routing.** First-recheck-of-day to operator phone, subsequent silent. Or every
   event? Recommended first-of-day-only; operator confirms.
6. **Acceptance window for "Mode 2 is fixed."** Live-validation: ≥1 `vacated` outcome in
   Exercise Room within 24h plus operator subjective confirmation that the AC-waste
   pattern stopped. Recommended yes on both gates.
7. **P2 (strip the v4.7.20 hold) decision.** Pending. Recommendation: ship P1 first, watch
   Mode-1 for one week, then decide. If operator wants substrate-first instead of P2, that
   also unblocks the strip naturally.
8. **Per-fan-entity opt-in.** Today the trigger fires when ANY `CONF_FANS` entity for the
   room is on. A room with two fans (e.g., ceiling + portable) may want recheck only when
   ceiling is on. Defer to a per-fan flag in a future cycle. Recommend defer.
9. **Master Bedroom opt-in for v1?** Mode-1 motivator and where v4.7.20 hold historically
   helped. As a Tier-1 + `bedroom` room the Mode-2 mechanism would only fire on L3 zone-absence
   (D1.5 forces L3-only for bedrooms) — during sleep L3 is never true (BLE present in zone), so
   it self-excludes overnight anyway. Recommend OPTED-OUT for v1; revisit after live data.
10. **Still-blind Tier-0/2 rooms — opt-out vs notify-instead-of-actuate.** Exercise's hobeian
    "does not capture still states," so its physical recheck can false-drop a motionless
    occupant and BLE can't authorize (Tier-0/2). For v1 these rooms stay opt-out
    (`CONF_FAN_RECHECK_TRUST_SENSORS_OK = False` → mechanism never actuates). A future cycle
    could add a notify-instead-of-actuate mode (NM ping "Exercise room looks empty but I can't
    confirm — fan still running") rather than silently dropping. Recommend opt-out for v1,
    notify-mode as a follow-up. Operator-confirm.
11. **`get_ble_tier` source-of-truth for room→tier at trigger time.** D1.5 calls
    `person_coord.get_ble_tier(R)` each eligibility check. Confirm the tier map is stable
    post-boot (built in `_build_scanner_room_map`, person_coordinator.py:482-546) and does not
    flap — if it can return 0 transiently during BLE-stack init, gate the trigger behind
    `_boot_settle_done` (already condition 7) which should cover it. Reviewer B to verify.

---

## Cross-references

- `docs/planning/PLANNING_occupancy_substrate_unification.md` — companion plan
- `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` — SUPERSEDED predecessor
- `docs/planning/PLANNING_fan_noise_mitigation_layer2_actuation.md` — SUPERSEDED build-gate
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` — v4.7.19 ship
- `docs/planning/AUDIT_fan_interference_gate_ripple.md` — predecessor audit
- `docs/planning/AUDIT_fan_recheck_room_tier_ripple.md` — NEW sibling audit (this cycle)
- `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` — snapshot/restore precedent
- `docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md` — `_phone_trustworthy` pattern
- `docs/readmes/README_v4.7.19.md` — provenance split ship doc
- `docs/readmes/README_v4.7.20.md` + `README_v4.7.20.1.md` — the hold being optionally stripped in P2
- `docs/readmes/README_v4.7.21.md` — boot-settle gate this cycle reuses
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — invariant being bent
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — fan write-path ownership preserved
- Memory: `project_v4_7_20_fan_noise_layer1_live.md`, `project_fan_noise_mmwave_mitigation_backlog.md`, `project_v4_7_19_live.md`, `project_v4_7_21_boot_storm_live.md`
- `docs/BACKLOG.md` Fan-noise entry
- `docs/QUALITY_CONTEXT.md` — candidate bug class addition (Mode-2 fan-coupled latch)
