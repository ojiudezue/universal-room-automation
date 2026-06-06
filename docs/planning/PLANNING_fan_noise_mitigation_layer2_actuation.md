# PLANNING — Fan-noise mitigation Layer-2 (actuation that responds to `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`)

**Status:** ⚠️ **SUPERSEDED by v4.7.22 Mode-2 (LIVE 2026-06-05).** The headline deliverable here — Option C, an active fan-pause + recheck-mmwave-with-fan-stopped state machine (§D1.3, the operator's 2026-06-04 lean in §D1.5) — was **built a different way**: as the ROOM-tier `presence_fan_recheck.py` + `_ble_corroboration.py` ladder (`PLANNING_fan_noise_mode2_ble_pause_recheck.md`, memory `project_v4_7_22_fan_recheck_mode2_live`), NOT as a consumer of the zone-tier `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` this doc was architected around. That gate **still has zero subscribers** and the §0 lift-check addendum (2026-06-05, below) already found it QUIET (mmwave-sole rarely met because PIR co-fires). So the whole "BUILD-HELD waiting for ≥10 gate-fire events" premise is moot. **Do not build from this doc.** The only surviving thread is the investigation question in the §0 addendum — *is the mmwave-sole gate precondition too narrow to ever engage?* — which is an investigation, not this actuation cycle. Retained as historical record.

~~**BUILD-HELD — prep only.** Layer-1 (silent gate) shipped + validated in v4.7.20 / v4.7.20.1 (LIVE 2026-06-04). Per operator (2026-06-04): *"prep now and hold in reserve."*~~ (premise overtaken by the room-tier Mode-2 ship — see status above.)

No version stamped — assigned at deploy time per operator convention.

---

## 0. BUILD GATE — observation evidence required to lift the hold

Layer-1's gate condition is narrow by construction:

> **mmwave is the sole provenance kind firing for the room AND a fan is on in the room AND the BLE corroboration ladder returns L2 (adjacent drift) or L3 (zone-absent) or `none` (zone has no BLE infra).**

(`presence.py:~2599–2810` — the `_apply_fan_interference_gate` helper. L1 short-circuits — it never enters the hold path.)

Until that condition actually fires on the live system, building actuation against `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` is premature: we'd be designing a consumer for an event we haven't observed. Bug Class #46 (lazy derivation against a still-evolving canonical) and the operator's "nothing is wrong, make it more Right" mandate both argue against speculative actuation. We must see the gate fire in the wild, validate that the ladder verdict matches operator reality, AND confirm the gate's truth-preservation invariant holds across at least N events before we stand anything up that consumes the signal.

### 0.1 Lift criteria (all must be true)

The build hold lifts when ALL of the following are observed on the live system. Each is a hard gate, not a guideline.

| # | Criterion | Where to measure | Threshold |
|---|---|---|---|
| **G1** | `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` dispatched in the wild | log line `Fan-noise D1: gate fired — newly-held rooms=…` (`presence.py:4624`). Count distinct dispatches (not rooms). | **≥ 10 distinct gate-fire events** over a contiguous 14-day window. |
| **G2** | Gate fires in ≥ 2 distinct rooms | Same log line; aggregate the `newly-held rooms=…` set across the window. | **≥ 2 distinct room names** (avoids overfitting Layer-2 to a single room's hardware quirk). |
| **G3** | Ladder distribution is non-degenerate | `binary_sensor.<room>_occupied` attr `ble_corroboration_layer` sampled at each gate-fire tick (Recorder history). | At least ONE of `L2` or `L3` must appear ≥ 3 times. (If 100% of fires are `none`, the gate is firing in BLE-blind zones and Layer-2 has nothing to lean on — different cycle entirely.) |
| **G4** | Truth-preserving invariant verified across the window | grep `error_log` for `_room_occupied=False but` (the v4.7.20 invariant probe). | **0 violations** over the window. Any violation invalidates Layer-2's actuation premise (we'd be acting on a fabricated occupancy). |
| **G5** | No HVAC / compliance / safety regression attributable to Layer-1 | `AUDIT_fan_interference_gate_ripple.md` consumers (HVAC defer gate `hvac.py:870`, compliance, house-state inference). | **0 anomaly rows** with `coordinator IN ('hvac','compliance','safety')` and `details LIKE '%fan_interference%'` over the window. |
| **G6** | Operator confirms the "disconcerting fan-pause" is still the pain | Verbal confirmation captured in a memory body or planning-doc preamble. | If the predecessor cycle alone made the fan-pause acceptable (Layer-1's silent hold is sufficient), Layer-2 stays parked indefinitely. |

**If any criterion fails: stay parked.** Re-evaluate quarterly. Do NOT relax thresholds to justify building — the whole point of the gate is to avoid building actuation for a phantom event class.

### 0.2 How to harvest the evidence (no code changes required)

All evidence sources already exist post-v4.7.20:

| Source | What it tells us | How to query |
|---|---|---|
| HA `error_log` / journald `core` logs | G1 + G4 directly | `ha_get_logs(source="system_service", slug="core")` (see [[reference-ha-logs-journald]]); grep for `Fan-noise D1: gate fired` and `_room_occupied=False but`. |
| `binary_sensor.<room>_occupied` attrs | G3 ladder distribution; G1 cross-check (`fan_interference_hold_active` should toggle True at each fire) | Recorder history MCP queries against the room sensors. |
| `sensor.ura_presence_coordinator_presence_house_state` `signal_consensus_inputs` attribute | Aggregate `fan_interference_active` + `fan_on_rooms` per zone | Recorder attribute history. |
| URA SQLite DB anomalies table | G5 regression check | `mcp__ura-sqlite__query_anomalies(coordinator IN ('hvac','compliance','safety'), since=<window_start>)`. Verify `--db-path` is live Samba mount (CLAUDE.md "Data Source Verification"). |
| Operator memory body | G6 | Recorded conversation. |

**No new diagnostic surfaces required.** Layer-1's existing emit log + sensor attrs + signal_consensus_inputs already publish everything G1–G5 need. If the 14-day window produces zero fires (G1 fails outright), the temptation will be to "add more diagnostics" — resist it. The right next step is to investigate WHY the gate isn't firing (typically: zones have BLE present, mmwave never goes sole-kind because PIR also fires, or fans aren't running long enough) before designing actuation.

### 0.3 Lift cadence

- Builder/operator runs a **lift check at 14 days post-v4.7.20.1 stability** (so earliest 2026-06-18) and quarterly thereafter.
- Lift check output is a one-paragraph addendum to THIS doc with the G1–G6 results. If GREEN on all six, the build hold is lifted and D1–D5 below become buildable.
- A GREEN lift check is **the** trigger for entering Tier classification + reviewer dispatch. Until then, this doc is a frozen design reference, not a build queue item.

### 0.4 What happens if Layer-1 alone is enough

Operator may decide the silent hold + decay is sufficient and Layer-2 actuation is over-engineering. In that case:

- Document the decision in a memory body ("Layer-2 parked permanently — Layer-1 silent gate met the operator pain").
- Keep this doc filed (do not delete) — institutional record of why no actuation was built.
- The `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` signal stays a no-consumer broadcast. It is cheap (edge-dispatched only on no-hold→hold transitions, `presence.py:4598–4604`) and harmless.

---

## Institutional context verified

This plan was scoped against the canonical prior-art surfaces per CLAUDE.md "Institutional Context First." Every D-row below is tagged REUSED (with file:line) or NEW (with a justification grounded in a verified gap).

### A. Primitives + signals + consumers (REUSED / NEW verdict per item)

| Primitive | Verdict | Evidence (file:line) | Notes |
|---|---|---|---|
| `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` (the dispatch site Layer-2 hooks) | **REUSED.** Defined `signals.py:118`; imported `presence.py:63`; dispatched `presence.py:4613–4623` with payload `{"rooms": sorted(newly_gated), "ladder": {room: "L1"|"L2"|"L3"|"none"}}`. Edge-detected via `_fan_interference_gated_prev` set (`presence.py:1112` + `:4602–4604`) so it fires once per no-hold→hold transition, not per tick. | **Zero current subscribers** — grep `async_dispatcher_connect.*SIGNAL_FAN_INTERFERENCE_GATE_FIRED` returns no matches across `custom_components/`. Documented in `fan_noise_layer1_review_B_lifecycle.md` B-L1 ("LOW — DEFERRED — subscriber arrives with D2"). |
| Payload shape `{"rooms": list[str], "ladder": dict[str, str]}` | **REUSED — locked by v4.7.20 ship.** `presence.py:4615–4623`. | Layer-2 receiver MUST accept this exact shape. Plan §D1 binds to it. |
| `_fan_interference_hold_until` per-tracker dict | **REUSED.** `presence.py:448` (init), `:524` (read in derived `_room_occupied`), `:2743–2810` (set/clear in `_apply_fan_interference_gate`), `:5111` (read for sensor attrs). | Layer-2 NEVER writes this dict — it is owned by `ZonePresenceTracker`. Layer-2 only reads it (or, more correctly, reads the derived sensor attrs that expose it). |
| `_fan_interference_gated_prev` edge-detect set | **REUSED.** `presence.py:1112` + `:4602–4604`. | Guarantees `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` is single-shot per transition. Layer-2 does NOT need to debounce. |
| `_fan_interference_hold_s` clamped operator config | **REUSED.** `presence.py:1107` (clamp 60–1800), seeded from `CONF_FAN_INTERFERENCE_HOLD_S` per `const.py:364`. | Layer-2's "how long to suppress the disruptive action" defaults align to the same hold seconds — same operator intent surface. |
| BLE corroboration ladder verdict (`L1`/`L2`/`L3`/`none`) | **REUSED.** Computed inside `_apply_fan_interference_gate` (`presence.py:2599+`); exposed on `binary_sensor.<room>_occupied` as `ble_corroboration_layer` (`binary_sensor.py:491,500`); included in the gate-fired signal payload. | Layer-2 actuation policy branches on this verdict (§D1.3). |
| `_compute_fan_interference_rooms` (the D3 diagnostic, pre-gate) | **REUSED — read only.** `presence.py:~2217`. | Layer-2 does not call it directly — it consumes the post-gate result via the signal. |
| `_room_provenance` per-room per-kind dict | **REUSED — read only.** `presence.py:372`. | Layer-2 reads the derived `_room_occupied` view (via existing sensor attrs), never mutates provenance. Truth-preservation invariant is owned by Layer-1. |
| `D3_DIAGNOSTIC_ENABLED` master kill switch | **REUSED.** `const.py:351`; imported `presence.py:47`. | Layer-2 honors the same kill switch — when False, no signal dispatches, so no Layer-2 action. No separate Layer-2 kill switch needed at this level; an actuation-specific opt-in is added below. |
| `hvac_fans.HVACFans.turn_off_all_managed` + `_set_fan_state` | **REUSED — DESIGN REFERENCE.** `hvac_fans.py:170` (broad off), `:178` (`_set_fan_state` write surface). | Layer-2 must NOT route through `turn_off_all_managed` (broad off side-effects HVAC). The right pattern is a narrow per-room surgical surface — see NEW row below. |
| `CONF_FAN_CONTROL_ENABLED` / `CONF_FAN_VACANCY_HOLD` / `CONF_FAN_TEMP_THRESHOLD` | **REUSED.** `const.py:503, 511, 504`. | Cross-rule precedence (§D2): operator-driven fan policy ALWAYS wins over Layer-2. If `CONF_FAN_CONTROL_ENABLED == False` for a room, Layer-2 is forbidden from touching it. |
| `EgressManager` snapshot/restore pattern (v4.7.8) | **REUSED as design precedent.** `PLANNING_v4.7.8_egress_window_hvac_pause.md` §D6 + the existing `egress_state` DB table. | If Layer-2 ever needs persistent state across HA restarts (e.g., "remember which fan we paused"), mirror this pattern line-for-line. |
| `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300` | **REUSED as design precedent.** `presence.py:71`. | Same idiom as the existing decay timer — Layer-2's "suppression window" can mirror this default if a separate Number is needed (see §D5 open questions). |
| `is_room_direct_ble(room_name)` | **REUSED.** `person_coordinator.py:1145`. | Layer-2 may use this to decide whether L3 (zone-BLE-absence) is meaningful for a given room — if no room in the zone has BLE infrastructure, L3 is uninformative. Same caveat as Layer-1's audit doc. |
| `PersonPhoneLeftBehindSensor` H2 carve-out | **REUSED.** `presence.py:3258–3315`. | Layer-2 actuation MUST mirror Layer-1's H2 carve-out: a phone-left-behind person does not count as "BLE present" for the L1/L2 ladder evaluation. Layer-1 already handles this in the ladder; Layer-2 inherits the verdict via the signal payload and need not re-check (but the consuming code should add a defensive log if it ever ladders on its own). |
| `check_zone_occupancy_confidence` (presence-coord public method) | **REUSED — DEFENSIVE READ.** `presence.py:968`. | Layer-2's actuation MUST NOT cause this helper's `(confirmed, possible)` tuple to lurch — Layer-2 is side-effect-free w.r.t. presence state by design. Reviewers (when build authorized) verify. |
| **Layer-2 actuation surface (the central NEW item)** | **NEW.** Three candidate shapes evaluated in §D1; final choice is operator-gated at build authorization. The cheapest is `Option A — suppress the existing fan-pause` (no new actuation, just *don't* run the legacy disconcerting pause), which the operator has already framed as the goal. The richest is `Option C — hold actuator state across the hold window` (active suppression of any consumer that would turn things off). | None of A / B / C have implementations today — verified by grep `async_dispatcher_connect.*FAN_INTERFERENCE` (no matches). |
| `CONF_FAN_PAUSE_*` family (per-room opt-in + cooldown + max-per-hour) | **NEW** if Option B/C chosen. Predecessor planning doc `PLANNING_fan_noise_mitigation_layers1_2.md` D2 already sketched these; they would be lifted from there. Inert in Option A. | See §D3. Predecessor doc is the authoritative sketch — do not re-design. |
| `fan_pause_state` SQLite table | **NEW** if Option C chosen (state persists across HA restart). Predecessor planning doc D2.3 spec'd the DDL; it would be lifted from there. | If Option A is chosen, this is NOT needed. |
| `SIGNAL_FAN_PAUSE_STARTED` / `SIGNAL_FAN_PAUSE_RESTORED` | **NEW** if Option B/C chosen. Predecessor planning doc D2.5. | NM dispatch hooks. |

### B. Prior planning docs consulted

| Doc | Relevance | Read depth |
|---|---|---|
| `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` | The authoritative predecessor that sketched Layers 1+2 together. D2 in that doc is the seed Layer-2 design (state machine, CONFs, DB table, cross-rule precedence). This doc REPLACES that D2 by adding the BUILD GATE in front of it, the three-option evaluation, and the lift-criteria. The predecessor's D2 sketches remain referenceable but no longer authoritative on shape — pending the lift outcome. | Full body. |
| `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 2 ("BLE Layer-3 → rare fan-pause-and-recheck — THE FIRST ACTUATION") | The pre-existing deferred-items entry that flagged this exact actuation cycle as a future cycle with hardware/UI gating. This doc supersedes that Item 2 — its gating conditions are absorbed into §0 here. Items 3 / 4 / 5 in the deferred-items doc remain there. | Full body. |
| `docs/readmes/README_v4.7.20.md` | Layer-1 acceptance + the locked payload shape Layer-2 must consume. | Full body. |
| `docs/readmes/README_v4.7.20.1.md` | The Bug Class #34 hotfix; confirms the dispatch site is now stable. | Full body. |
| `docs/planning/AUDIT_fan_interference_gate_ripple.md` | The Layer-1 ripple audit. Layer-2's actuation must NOT introduce new readers that violate the same SAFE verdicts. | Full body — §"Signals + Consumers" table. |
| `docs/reviews/code-review/fan_noise_layer1_review_B_lifecycle.md` | Reviewer B's verdict on the dispatch site. B-L1 confirms zero subscribers — Layer-2 is the first one. B-L2 documents the in-memory `_fan_interference_gated_prev` reset semantics across restart (relevant to Layer-2's first-tick behavior). | §B-L1, B-L2, B-H2 only. |
| `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` | Snapshot/restore + 4-scenario restart-resilience pattern. If Layer-2 takes Option C (persist actuation state), this is the template. | §D3–D6. |
| `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` (predecessor cycle, LIVE in v4.7.19) | Confirms the provenance split is in place — Layer-2 can rely on per-kind provenance to interpret the ladder verdict. | Skim. |
| `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` | The non-URA research-note stub. Layer-2 outcomes feed it; not gating. | Header only. |

### C. Memory bodies pulled

| File | Relevance |
|---|---|
| `project_v4_7_20_fan_noise_layer1_live.md` | Layer-1 ship + the explicit "Next: D2 = fan-noise Layer-2 actuation, build-gated on observing real `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` events in the wild" handoff. This doc executes that handoff. |
| `project_fan_noise_mmwave_mitigation_backlog.md` | Operator's verbatim design intent (notes a + b, CORE REFRAME on interference-conditioned reliability, pets sharpen the 3-layer BLE ladder). Layer-2's "stop the disconcerting pause" is the headline pain. |
| `project_v4_7_19_live.md` | Predecessor cycle (provenance split + D3 diagnostic) + boot-storm context. Layer-2 must NOT exacerbate the cold-boot actuation storm — added as a hard non-goal (§Non-goals). |

### D. Design docs read

| Doc | Relevance |
|---|---|
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | "Presence provides STATE, not ACTIONS" foundational invariant. Layer-2 actuation CANNOT live on the presence coordinator — it must live in the actuation-owning coordinator (HVAC fans for the pause case). Same constraint the predecessor cycle honored. |
| `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` | HVAC fans subsystem (`hvac_fans.py`) is the canonical fan write-path owner. Layer-2's narrow surgical surface lives there if Option B/C is chosen. |

### E. Code locations surveyed (read end-to-end during scoping)

| File | Lines surveyed | What was confirmed |
|---|---|---|
| `domain_coordinators/presence.py` | `:63, :448, :524, :1100–1130, :2599–2810, :4580–4640, :5111` | The complete Layer-1 hold+dispatch surface. `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` dispatched with edge-detect; payload `{rooms, ladder}` stable. No mutation of `_room_provenance` anywhere in the gate. |
| `domain_coordinators/signals.py` | `:118` | `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` const definition. No other fan-interference signals. |
| `domain_coordinators/hvac_fans.py` | `:1–230` (init, discovery, `turn_off_all_managed`, `_set_fan_state`, update loop entry) | Existing fan write surface. Operator-driven `CONF_FAN_VACANCY_HOLD` already governs vacancy-based off-cycles — Layer-2 must defer to this (cross-rule precedence). |
| `binary_sensor.py` | `:466, :491, :500` | `_fan_interference_hold_until` read for `fan_interference_hold_active` attr; `ble_corroboration_layer` attr (Layer-2's read source for ladder verdict if reading attrs instead of subscribing to the signal). |
| `const.py` | `:351 (D3_DIAGNOSTIC_ENABLED), :364 (CONF_FAN_INTERFERENCE_HOLD_S), :503–511 (CONF_FAN_*)` | Existing knob inventory. No `CONF_FAN_PAUSE_*` family (NEW). |
| `quality/tests/test_fan_interference_gate_layer1.py` | All hold-set/clear/expire test cases | Confirms Layer-1's hold semantics. Layer-2 acceptance tests will mirror this fixture style. |

---

## 1. Tier classification (provisional — final dispatch at build authorization)

**Provisional Tier 2-DB (three framing-disjoint reviews).** Final classification is re-confirmed at build authorization because Tier depends on which Option (A/B/C) the operator picks.

| Option | Likely Tier | Justification |
|---|---|---|
| **A — Suppress the legacy disconcerting fan-pause** (don't perform the existing pause when `fan_interference_hold_active` is true; no new actuator writes) | **Tier 2** (two reviewers) | Trust-hierarchy ripple is low — we're declining to act, not adding new writes. Suppression logic lives in whichever coordinator owns the existing pause (operator-managed external automation or `hvac_fans`). |
| **B — Hold actuator state across the hold window** (extend any consumer's "occupancy is gone, turn off" by `_fan_interference_hold_s`; no DB persistence — in-memory only) | **Tier 2-DB** (three reviewers) | Cross-coordinator ripple is the central risk: HVAC, lights, EC, compliance all read presence-derived state. Although Layer-1's truth-preserving invariant already extends `_room_occupied`, Layer-2 may extend ADDITIONAL actuator states. Trust-hierarchy ripple at the same scale as v4.7.15. |
| **C — Active fan-pause + snapshot/restore + restart-resilience** (the predecessor's PLANNING_fan_noise_mitigation_layers1_2.md §D2 sketch) | **Tier 2-DB** (three reviewers) | Standard Tier 2-DB triggers all fire: new DAO + new persisted record shape + new dispatched signal + behavioral tests against real schema + first presence-side actuation. |

**Framings (locked at build authorization, repeated here so reviewers can pre-load context):**

- **Reviewer A — Correctness + truth-preservation + actuation invariants.** Layer-1's "hold can only EXTEND occupancy, never fabricate it" invariant must NOT be weakened by Layer-2. If Option C, the state machine is total and all transitions are reachable. Operator-driven fan service calls always win.
- **Reviewer B — Async + lifecycle + restart resilience + cross-coordinator ripple.** First-tick post-restart behavior (Bug Class #14). `async_dispatcher_connect` listener teardown on coordinator unload (Bug Class #42). Does Layer-2 worsen the cold-boot actuation storm captured in `project_v4_7_19_live.md`? If Option C, all 4 restart scenarios (paused-at-restart, restoring-at-restart, cooldown-at-restart, snapshot-corrupt-at-restart) mirror v4.7.8 §D6.
- **Reviewer C — New surfaces + cross-rule precedence + test fixture authority.** If Option C: DAOs round-trip; DDL extracted from production source. CONF_* round-trip via options flow + RestoreEntity. Cross-rule precedence matrix (Layer-2 vs `CONF_FAN_VACANCY_HOLD` vs `CONF_FAN_TEMP_THRESHOLD` vs `EgressManager` pause vs operator service call) is complete and consistent.

---

## Non-goals (explicit, locked)

- **No Layer-2 build before §0 lift criteria are GREEN.** This is the load-bearing non-goal.
- **No re-design of Layer-1.** The hold + signal + payload shape are locked.
- **No new signal types.** Layer-2 subscribes to the existing `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`. (Options B/C may introduce `SIGNAL_FAN_PAUSE_*` for NM dispatch; those are downstream events, not redefinitions of the gate signal.)
- **No automatic enablement.** Layer-2 actuation is opt-in per room (default OFF). Operator's "rare" framing is enforced.
- **No DPM / preset interaction.** Layer-2 does not move presets or HVAC modes.
- **No house-state mutation.** Layer-2 does not flip occupied/away.
- **No PIR/mmwave fusion in this cycle.** Stays in `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 3.
- **Layer-2 MUST NOT worsen cold-boot actuation storm.** Per `project_v4_7_19_live.md`, the v4.7.19/v4.7.20.1 boots already saturated the event loop with `light/switch/homeassistant.turn_off` storms; Layer-2 cannot add to that. Specifically: Layer-2 actuation MUST be suppressed during the first N inference ticks after coordinator setup (see §D4 — same suppression idiom as Bug Class #14 first-tick guards).
- **No removal of Layer-1's edge-detect set on restart.** `_fan_interference_gated_prev` reset on restart is the documented behavior (Reviewer B B-L2 LOW DEFERRED). Layer-2 must not depend on it persisting.

---

## D1 — Layer-2 actuation: three candidate options (DESIGN ONLY, operator picks at lift)

### D1.1 — Option A: Suppress the legacy disconcerting fan-pause (CHEAPEST — RECOMMENDED DEFAULT)

**Premise.** The operator's pain in the memory body is the EXISTING "pause room fan ~3min, recheck mmwave with fan off" automation that the operator finds *"disconcerting in rooms."* Layer-1 already keeps the room reading occupied. If that legacy pause is gated on `_room_occupied` going False, Layer-1 ALREADY suppresses it (the room never reads unoccupied during the hold window). In that case, no Layer-2 build is needed — the operator should validate that Layer-1 already fixed the pain.

**Where this lives.** Wherever the legacy pause lives. Three candidate owners:
1. **Operator-side HA automation** (most likely — the memory body refers to "his prior automations"). Layer-2 = operator audits their automation library and confirms the pause trigger reads URA's `binary_sensor.<room>_occupied` (or a downstream sensor that derives from it). If yes, **no URA code changes needed** — the silent gate already does the work.
2. **`hvac_fans.py` `CONF_FAN_VACANCY_HOLD` path.** Verify at build authorization whether this code path is the actual "disconcerting pause" mechanism, or whether it's something else entirely. If it is, the suppression is "vacancy decision reads `_room_occupied` which Layer-1 already extends — no change."
3. **A third coordinator (compliance, comfort).** Verify at build authorization.

**Scope if Option A is chosen.**

- **No production code changes.** This is an investigation + operator-confirmation cycle.
- Deliverable = a short audit doc mapping every URA code path + operator automation that performs the pause-and-recheck, plus a verification that each one reads through `_room_occupied` (which Layer-1 extends).
- If a path is found that bypasses `_room_occupied` (reads `_room_provenance` directly, or reads a raw sensor), that's the one Layer-2 fixes — but that fix is a one-line read swap, not actuation.

**Why this is the recommended default.** Per "make it more Right, not bigger" mandate, and per Bug Class #46 (lazy derivation against still-evolving canonicals), the cheapest credible Layer-2 is "verify Layer-1 already won, don't build anything." Only if §0 lift criteria GREEN and Option A audit finds an unfixed bypass do we proceed to Option B or C.

### D1.2 — Option B: In-memory actuator-state hold (MIDDLE)

**Premise.** Some consumers may not read through `_room_occupied` directly — they may listen for an event ("occupancy dropped to False") that fires once and is then irreversible until next True transition. For those consumers, extending `_room_occupied` is not enough; we need to *also* hold the actuator state.

**Mechanism.**

- New coordinator-level listener subscribes to `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`.
- On receipt, for each room in the payload AND each "actuator hold target" configured for that room (e.g., fan, light, AV), the listener records the actuator's current state in an in-memory `Dict[str, ActuatorSnapshot]`.
- For the next `_fan_interference_hold_s` seconds, any service call from URA that would turn that actuator off (`fan.turn_off`, `light.turn_off`, etc.) is suppressed if it originated from a presence-derived gate (NOT operator-initiated).
- At hold expiry (or when Layer-1 clears the hold via L1 firing), the listener stops suppressing.

**Scope.**

- NEW file `domain_coordinators/fan_interference_actuation.py` (~150 LoC).
- NEW per-room `CONF_FAN_INTERFERENCE_ACTUATION_TARGETS: list[str]` (entity_ids to hold).
- NEW master `CONF_FAN_INTERFERENCE_ACTUATION_ENABLED` (Bool, default OFF).
- NO DB writes — in-memory only. Lost across restart by design (Layer-1's hold dict is also in-memory).
- NEW switch entities for the master + per-room.

**Risk.** Suppressing turn-off calls is invasive. Cross-coordinator ripple is high — every coordinator that issues turn-off must be audited to confirm it's safe to suppress for up to 30 minutes. This is closer to Tier 2-DB scope.

**Why this is middle.** Real actuation, but no persistence and no new DB shape. Faster to ship than Option C; more invasive than Option A.

### D1.3 — Option C: Active fan-pause + snapshot/restore + DB persistence (RICHEST — predecessor's D2 sketch)

**Premise.** The predecessor planning doc `PLANNING_fan_noise_mitigation_layers1_2.md` §D2 sketches a full pause-and-recheck state machine with snapshot/restore. If §0 lift criteria GREEN AND operator decides the legacy pause IS the thing to replace (not just suppress), THIS is the build.

**Scope.** Defer to the predecessor doc §D2 — do not re-design here. Briefly:

- New `domain_coordinators/presence_fan_pause.py` (~250 LoC) with 5-state machine: `idle → armed → paused → restoring → cooldown`.
- New `fan_pause_state` SQLite table + 5 DAOs (mirror `egress_state`).
- Narrow `pause_fan_for_interference_check(room_name) -> FanSnapshot | None` + `restore_fan(room_name, snapshot)` on `hvac_fans.py`.
- 7 new CONFs (master, per-room, arm delay, recheck duration, restore delay, cooldown, max-per-hour).
- New `SIGNAL_FAN_PAUSE_STARTED` / `SIGNAL_FAN_PAUSE_RESTORED` for NM.
- New per-room sensors (`fan_pause_state`, `fan_pause_history`).
- 4 restart-resilience scenarios per v4.7.8 §D6.
- Cross-rule precedence matrix (predecessor §D2.6).

**Why this is the richest.** Mirrors `EgressManager` — full state machine, DB persistence, restart-safe.

### D1.4 — Decision matrix (operator-facing, picked at lift)

| Question | Answer → choose |
|---|---|
| Does Layer-1 alone make the disconcerting pause go away? | **A — none** (skip build entirely, document parked decision) |
| Does Layer-1 work but some consumer bypasses `_room_occupied`? | **A — audit + read-swap** (one-line fix) |
| Does Layer-1 work but some consumers fire one-shot events that need actuator-state holding? | **B — in-memory hold** |
| Is the legacy pause still firing and disconcerting (Layer-1 insufficient)? | **C — replace with rare BLE-justified pause** |

### D1.5 — Operator intent refinement (2026-06-04) — leaning Option C

The operator sharpened the problem framing and the preferred shape. Captured verbatim-in-substance so the lift-time decision starts from the right premise (this REPLACES the §0.4 default-to-A assumption as the operator's current lean — Option A remains the cheap fallback if §0 evidence is thin):

- **The real pain is persistent FALSE presence, not the pause.** URA is prone to fan-noise presence distortion. It does **not** even do periodic pause-and-recheck today — it simply **keeps false presence with fans running in summer** (Layer-1's hold is exactly this, by design: it extends occupancy across mmwave dropout). So the gap Layer-2 fills is the *recheck* that Layer-1 deliberately omitted.
- **Existing fan-pause automations are brittle and cover only a couple of rooms.** Option C generalizes + hardens this across all managed rooms rather than leaving it to per-room HA automations.
- **The Option-C mechanism the operator wants:**
  1. **Finesse WHEN to pause** — only when the room is *truly* empty per BLE **and** mmwave is the suspect (sole-kind) signal. (This is precisely the Layer-1 gate condition — Option C consumes that verdict, does not re-derive it.)
  2. **Pause the fan and let it actually spin down** — the pause must be long enough for airflow to stop, so the radar gets a clean field. (Arm/pause timing in D1.3 must account for fan spin-down, not just electrical-off.)
  3. **Recheck mmwave** — with the fan stopped, decide whether mmwave was *lying* (room truly empty → it was fan noise) or telling the truth (someone's there → restore immediately, occupancy confirmed real).
  4. **The pause is "free" when we're right** — if the room really is empty, there's no occupant to notice the fan stopped. The cost is only paid on a false-suspect (occupant present), so restore latency + comfort on that branch is the thing to minimize.
- **Hard mandate: "must anticipate real-world issues."** Option C build is not authorized to be a happy-path state machine. The reviewer framing (§ reviewers) must stress: occupant-returns-mid-pause comfort, fan spin-down vs electrical-off timing, restore-on-restart (snapshot survives reboot), cooldown/max-per-hour to avoid annoyance, interaction with `CONF_FAN_TEMP_THRESHOLD` (don't pause a fan that's running for heat, not presence), and the cold-boot storm non-goal.

**Net:** operator is **inclined toward Option C**, gated on §0 evidence. If the §0 lift check is GREEN, scope Option C (not A) as the primary build, with the spin-down-aware timing and the real-world-issues mandate above folded into D1.3.

---

## D2 — Cross-rule precedence (applies to whichever Option is chosen)

| Rule | Winner over Layer-2 | Notes |
|---|---|---|
| Operator-driven service call (fan.turn_on / fan.turn_off from outside URA) | OPERATOR wins | If Layer-2 has suppressed an off → on transition, operator's explicit on overrides immediately. |
| `CONF_FAN_CONTROL_ENABLED == False` for room | OPERATOR wins | Layer-2 is forbidden from touching this room. |
| `CONF_FAN_VACANCY_HOLD` + `CONF_FAN_TEMP_THRESHOLD` (operator's hand on fan policy) | OPERATOR / TEMP MANAGER wins | Layer-2 must not race or pre-empt these. |
| `EgressManager` paused this zone | EGRESS wins | Don't stack two pauses. |
| `D3_DIAGNOSTIC_ENABLED == False` | KILL SWITCH wins | No signal dispatches, so Layer-2 receives nothing — naturally inert. |
| Operator service `ura.fan_pause_force_restore` (Option C) | OPERATOR wins | Immediate restore from snapshot. |
| Cold-boot first-N-ticks suppression (Bug Class #14) | SUPPRESSION wins | Layer-2 ignores `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` for the first ~3 inference ticks post-`async_setup` to avoid stacking on the boot-storm. |

---

## D3 — Files that WOULD change (per Option)

| File | Option A | Option B | Option C |
|---|---|---|---|
| `const.py` | — | + `CONF_FAN_INTERFERENCE_ACTUATION_ENABLED`, `CONF_FAN_INTERFERENCE_ACTUATION_TARGETS` | + `CONF_FAN_PAUSE_*` (7 constants), state labels |
| `domain_coordinators/presence.py` | — | — | — (presence stays read-only per design doc invariant) |
| `domain_coordinators/fan_interference_actuation.py` | — | NEW (~150 LoC) | — |
| `domain_coordinators/presence_fan_pause.py` | — | — | NEW (~250 LoC; see predecessor doc) |
| `domain_coordinators/hvac_fans.py` | (audit only) | (audit + maybe small read swap) | + `pause_fan_for_interference_check`, `restore_fan` (narrow surgical surface) |
| `domain_coordinators/signals.py` | — | — | + `SIGNAL_FAN_PAUSE_STARTED`, `SIGNAL_FAN_PAUSE_RESTORED` |
| `database.py` | — | — | + `fan_pause_state` DDL + 5 DAOs |
| `config_flow.py` / `options_flow.py` | — | + master switch + per-room targets list | + `CONF_FAN_PAUSE_*` master + per-room |
| `switch.py` | — | + Presence-coord `FanInterferenceActuationSwitch` | + master + per-room `FanPauseEnabledSwitch` |
| `number.py` | — | — | + 5 `FanPause*Number` |
| `binary_sensor.py` | — | (no new entities) | + `RoomFanPauseInProgress` per pause-eligible room |
| `sensor.py` | — | — | + `RoomFanPauseStateSensor`, `RoomFanPauseHistorySensor` |
| `services.yaml` | — | — | + `fan_pause_force_restore` |
| `quality/tests/...` | + audit verification test (one file) | + actuation state-machine test, per-room-target round-trip | + 3 new test files per predecessor doc D2 |
| Sidecar audit doc | NEW `AUDIT_fan_interference_actuation_consumers.md` (mandatory before any Option) | (same) | (same) |

---

## D4 — Acceptance criteria (per Option, Verify / Sensor / Test / Live)

These are tracked here so they are NOT re-derived at build authorization. Plan completion tracking (§5) audits whether each criterion was met when the cycle ships.

### D4.A — Option A (suppression / audit only)

- **Verify:** every URA code path that performs a "fan pause based on vacancy" reads through `_room_occupied` (which Layer-1 extends). Documented in `AUDIT_fan_interference_actuation_consumers.md`.
- **Verify:** if any path bypasses `_room_occupied`, the read is swapped to `_room_occupied`. Zero behavior change for non-fan-suspect rooms.
- **Sensor:** no new entities. Existing `binary_sensor.<room>_occupied` carries the existing Layer-1 attrs.
- **Test:** `test_fan_interference_actuation_audit.py` — grep-style AST test asserting no code path reads `_room_provenance` for a fan-pause decision.
- **Live:** on a known fan-on bedroom, with operator out of the room and no BLE in zone, verify the legacy pause does NOT fire during the Layer-1 hold window. Operator subjective confirmation: "the disconcerting pause is gone."

### D4.B — Option B (in-memory actuator-state hold)

- **Verify:** when `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` arrives, the actuation coordinator snapshots the configured targets within one tick.
- **Verify:** during the hold window, presence-derived turn-off service calls to those targets are suppressed; operator service calls pass through unchanged.
- **Verify:** at hold expiry OR L1 fires, suppression clears within one tick.
- **Verify:** restart drops the in-memory snapshot; first-N-ticks-post-restart suppression prevents stacking.
- **Sensor:** `switch.ura_presence_coordinator_fan_interference_actuation_enabled` master toggle (round-trips via options flow).
- **Sensor:** per-room `switch.ura_room_<room>_fan_interference_actuation_enabled`.
- **Test:** `test_actuation_state_hold_in_memory.py` — full event lifecycle.
- **Test:** `test_actuation_state_first_tick_suppression.py` — Bug Class #14 first-tick guard.
- **Test:** `test_actuation_state_listener_teardown.py` — Bug Class #42 unload cleanup.
- **Live:** post-restart, on a fan-on bedroom, trigger gate fire (or wait for natural), verify configured target stays in its prior state through the hold window.

### D4.C — Option C (active pause + DB)

Defer to `PLANNING_fan_noise_mitigation_layers1_2.md` §D2.7 — full criteria already written, including the 4 restart scenarios and the `fan_pause_force_restore` escape-hatch verification. NOT re-derived here.

---

## D5 — Open questions for operator at lift authorization

1. **Option choice.** A vs B vs C? §D1.4 decision matrix is the framing.
2. **If Option A:** is the audit doc the final deliverable, or do we also want a `binary_sensor.ura_room_<room>_fan_pause_eligible` diagnostic so operator can verify any external automation is reading the right field?
3. **If Option B:** what's the default `actuation_targets` list for a typical bedroom? `[fan.<room>_ceiling_fan]` only, or expand to `[fan.*, light.*, switch.*]`?
4. **If Option C:** confirm the predecessor's defaults (arm 60s, recheck 180s, restore 5s, cooldown 1h, max 1/hour) are still operator-acceptable.
5. **NM dispatch routing.** Operator-phone-only on pause events, or zone-wide? Predecessor doc default is operator-phone-only.
6. **Cold-boot suppression window.** N inference ticks? 3 is the predecessor's anti-storm number; could be 5 if boots have gotten worse.
7. **Hold-share with Layer-1.** Layer-2's suppression window — same `_fan_interference_hold_s` as Layer-1 (clamped 60–1800), or a separate `CONF_FAN_INTERFERENCE_ACTUATION_HOLD_S`? Recommend share to avoid knob proliferation.

---

## D6 — What is currently subscribed to `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`

**Nothing.** Verified by grep `async_dispatcher_connect.*SIGNAL_FAN_INTERFERENCE_GATE_FIRED` across `custom_components/` — **zero matches.** This is the expected state per Reviewer B's B-L1 DEFERRED LOW (`fan_noise_layer1_review_B_lifecycle.md:150`): "subscriber arrives with D2 / future diagnostic sensor." Layer-2 is that subscriber.

Dispatch site (single, edge-detected, payload locked): `presence.py:4613–4623`.

---

## D7 — Plan completion tracking (CLAUDE.md mandate)

**NOT BUILT in this cycle (explicit + intentional):**

| Item | Defer reason | Where tracked |
|---|---|---|
| All of D1–D5 production code | **§0 BUILD GATE not lifted.** Awaiting ≥10 distinct `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` events across ≥2 rooms over a 14-day window with non-degenerate ladder distribution and zero invariant violations. | THIS doc §0. |
| Option choice (A / B / C) | Operator decision at lift. | §D1.4 + §D5.1. |
| Predecessor doc `PLANNING_fan_noise_mitigation_layers1_2.md` §D2 | The same actuation cycle, sketched in advance. THIS doc supersedes it by adding the BUILD GATE in front. Predecessor remains a design reference for Option C. | Predecessor doc — flagged as design-only at the top. |
| Deferred-items doc `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 2 | The same actuation cycle, originally deferred without a lift criterion. THIS doc absorbs the gating into §0. | Deferred-items doc Item 2 — now superseded by THIS doc's §0. |
| PIR + mmwave fusion backstop (Item 3 in deferred-items) | Hardware-gated; out of scope here. | Deferred-items doc Item 3 — UNCHANGED. |
| NON-URA research note (Item 4 in deferred-items) | Separate audience; depends on Layer-1 data, not Layer-2 actuation. | Deferred-items doc Item 4 — UNCHANGED. |
| `mmwave_occupied_count` deprecation shim removal (Item 5 in deferred-items) | Tail-clean; independent. | Deferred-items doc Item 5 — UNCHANGED. |

**LIFTED in this cycle (no production code; documentation deliverables only):**

- §0 build gate criteria established (G1–G6 with measurable thresholds + harvest method).
- Tier classification provisionally captured per Option.
- Three actuation options scoped + decision matrix written.
- Cross-rule precedence matrix written.
- Reviewer framings pre-locked for build authorization.
- Institutional-context grep verdicts captured (every CONF/sensor/signal/helper tagged REUSED with file:line OR NEW with grep proof).
- Files-changed table written per Option.
- Acceptance criteria written per Option.

---

## D8 — Cross-references

- `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` — predecessor (supersedes its §D2)
- `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` — predecessor (supersedes Item 2)
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` — shipped foundation (v4.7.19)
- `docs/planning/AUDIT_fan_interference_gate_ripple.md` — Layer-1 ripple audit
- `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` — original audit
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` — non-URA research stub
- `docs/readmes/README_v4.7.20.md` — Layer-1 ship doc (payload shape lock)
- `docs/readmes/README_v4.7.20.1.md` — Bug Class #34 hotfix ship doc
- `docs/reviews/code-review/fan_noise_layer1_review_A_correctness.md` — Layer-1 Reviewer A
- `docs/reviews/code-review/fan_noise_layer1_review_B_lifecycle.md` — Layer-1 Reviewer B (B-L1 = "subscriber arrives with D2")
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — "presence provides STATE not ACTIONS" invariant
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — fan write-path ownership
- Memory: `project_v4_7_20_fan_noise_layer1_live.md`, `project_fan_noise_mmwave_mitigation_backlog.md`, `project_v4_7_19_live.md`
- `docs/BACKLOG.md` Fan-noise entry
- `docs/QUALITY_CONTEXT.md` Bug Classes #1, #14, #34, #42, #46, #48

---

## §0 lift-check addendum — 2026-06-05 (early partial read, ~1 day post-v4.7.20)

Operator asked whether the build hold could lift earlier than the 2026-06-18
calendar floor. Ran an early **read-only** probe (no code, no config, no logger
change — the `fan_interference_hold_active` / `ble_corroboration_layer`
attributes are already in Recorder, so G1/G3 are measurable without touching the
system).

**Finding: gate is QUIET.** Master Bedroom (the prime mmwave+fan room) over a
30h window: `fan_interference_hold_active` never True (0/300 samples),
`fan_interference_suspect` never True, `ble_corroboration_layer` **null** (ladder
never even evaluated). Live house-wide aggregate concurs:
`signal_consensus_inputs.fan_interference_active=false`, `fan_interference_rooms=[]`,
`fan_interference_ladder={}`.

**Reframe — the calendar was never the binding constraint.** The gate's
mmwave-SOLE precondition is rarely met because PIR co-fires with mmwave in
occupied rooms (live `tier1_provenance_breakdown` showed Back Hallway
motion:2 + mmwave:1 — not mmwave-sole). G1's "≥10 events over 14 days" would
very likely arrive at **0 events**; waiting changes nothing.

**Decision posture (operator to confirm):**
1. If we want an evidence-based early lift, **replace G1's 14-day calendar floor
   with an event-count+diversity trigger** (build whenever ≥10 fires across ≥2
   rooms with L2/L3 ≥3× land — even on day 5). Keep G2–G6 robustness bars intact.
2. **More likely outcome:** the gate barely fires → Layer-2 parks (§0.4) and the
   higher-value follow-up is investigating whether the mmwave-sole precondition is
   too narrow to ever engage (§0.2's "investigate WHY it isn't firing" branch),
   NOT building actuation.
3. Ongoing measure is a periodic **read-only** Recorder sweep of room sensors'
   `fan_interference_hold_active` — no logger bump, no config. (An ephemeral
   `logger.set_level` INFO bump was tried + reverted; HA logger introspection
   couldn't cleanly confirm it took, and the recorded attrs make it unnecessary.)

Next lift-check still due 2026-06-18, but expectation reset to "confirm quiet →
park or investigate precondition," not "harvest ≥10 fires."
