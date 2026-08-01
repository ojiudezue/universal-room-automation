# PLANNING: Shared Fan Actuation Layer (extraction — design only, NOT to build)

**Date:** 2026-07-26
**Author:** ura-planner
**Status:** DEFERRED (operator ruling 2026-07-26). Do NOT build until the GO CRITERIA below fire. Design is complete and buildable when they do.
**Related:** `PLANNING_fan_manual_off_cooldown.md` (the narrow DOC-1 fix; SHIPPED v5.31.0).

---

## GO CRITERIA — operator-ratified 2026-07-26 (DEFERRED until ALL of gate + ANY trigger)

DOC-2 is a Tier-3 extraction with house-wide fan blast radius. Its benefit (consistency-by-construction, no future port cost) only pays off once drift **actually recurs**. Building it to prevent a *hypothetical* future port is the sunk-cost trap. So it stays parked until:

**FOUNDATION GATE (must be TRUE):**
- The DOC-1 room-tier manual-off cooldown (shipped v5.31.0) has been live **≥1 full deploy cycle** AND **H8 has validated organically** — a real, manually-turned-off room-tier comfort fan was observed NOT to re-arm within the cooldown window on the running house. (Until H8 is proven, we don't even know the narrow fix behaves; extracting it would refactor unproven code.)

**PLUS ANY ONE TRIGGER:**
1. **New drift-hole:** a new fan mechanic (hysteresis change, min-runtime, sleep-cap tweak, new gate) is added to ONE tier but not the other — i.e. the port-cost recurs for real.
2. **Real-world inconsistency bug:** a filed report that a fan re-armed, failed to run, or double-actuated due to room-tier vs HVAC-tier divergence (not hypothetical — observed).
3. **Third-writer bypass in the wild:** `actuator_reconciler.py:778` or any new caller is found actuating a fan around a cooldown/min-runtime the other path enforces.
4. **Piggyback:** we're already opening `hvac_fans.py` / `automation.py` fan paths for another cycle AND the change would otherwise have to be double-ported — fold the extraction in rather than port twice.

**EXPLICIT NON-TRIGGERS (do NOT build on these alone):**
- "It would be cleaner." / "To prevent a hypothetical future port." / "The split is inelegant." Consistency-by-construction is not worth the Tier-3 blast radius until drift has actually recurred.

**When it fires:** standalone **Tier 3** (4 framing-disjoint reviews incl. adversarial-completeness D against the falsifiable invariant in "Recommended tier" below) + orchestrator independent mutation verification + operator checkpoint before deploy. Ratify the 8 open decisions to their recommended defaults at that time.

**Re-check cadence:** revisit at the next fan-area cycle, or ~90 days (≈2026-10-24) — whichever comes first. If no trigger has fired by then, the deferral stands (evidence says the split isn't costing us).

---

## Institutional context verified

### Greps run + results

- Duplicated fan-actuation logic — greps run across the two decision sources:
  - Room-tier: `handle_temperature_based_fan_control` in `automation.py:1542-1696`.
  - HVAC-tier: `FanController.update` + `_evaluate_temp_fan` in `hvac_fans.py:174-450`.
  - Room-tier humidity path: `handle_humidity_based_fan_control` at `automation.py:1713+` — **explicitly SOLE-OWNER post-bathroom-exhaust cycle** (`hvac_fans.py:291-296` comment: "D1 — Humidity fans are evaluated EXCLUSIVELY by the room-tier path"). This is prior-art proof that a policy-collapse has already been done successfully for humidity fans; comfort fans are the remaining split.
- Shared primitive candidates — `_safe_service_call`, `_set_fan_state`, `SERVICE_TURN_ON/OFF` — currently duplicated:
  - Room-tier: `automation.py:1621-1626` (turn_off), `:1667-1680` (turn_on).
  - HVAC-tier: `hvac_fans.py:_set_fan_state` (referenced :166, :281).
- Sleep policy — duplicated:
  - Room-tier: `automation.py:1560-1571` (FAN_SLEEP_OFF force-off, FAN_SLEEP_REDUCE speed cap = 33%).
  - HVAC-tier: `hvac_fans.py:_apply_night_trust_speed_cap` (:298-333) with `FAN_SPEED_LOW_PCT` cap. **Semantically similar but NOT identical** (HVAC uses `FAN_TRUST_STATES` house-state axis; room-tier uses `is_sleep_mode_active` per-room time-window — deliberately, per hvac_fans.py comment).
- Hysteresis — duplicated with different values:
  - Room-tier: `automation.py:1585` — `hysteresis = 2.0` (inline literal).
  - HVAC-tier: `DEFAULT_FAN_HYSTERESIS` from `hvac_const` (module constant).
- Min-runtime — HVAC-tier ONLY (`DEFAULT_FAN_MIN_RUNTIME` + `last_on_time` at hvac_fans.py:69, gate not shown but referenced). Room-tier has NO min-runtime — cycles freely.
- Vacancy hold — different mechanics:
  - Room-tier: `automation.py:1573-1582` (`_fan_vacancy_start` + `CONF_FAN_VACANCY_HOLD` seconds).
  - HVAC-tier: `hvac_fans.py:71` (`vacancy_detected_time`) + `DEFAULT_FAN_VACANCY_HOLD`.
- Manual-off cooldown — HVAC-tier ONLY (`hvac_fans.py:71, 207-217, 389-397`). Room-tier MISSING — the DOC-1 fix hole.
- Occupancy gate — different order:
  - Room-tier: temp-check first, then occupancy override via `_fan_vacancy_start`.
  - HVAC-tier: occupancy gate FIRST (hvac_fans.py:443-445 comment "v4.0.15: Occupancy gate moved BEFORE temperature triggers. Fans cool people, not rooms").
- Fan-noise recheck handshake — HVAC-tier ONLY (`fan_recheck_suppress_until` at hvac_fans.py:73, :193-202). Room-tier does NOT participate in the Layer-1/Mode-2 fan-noise mitigation (deliberately — the room-tier IS the noise-source path in the reference implementation).
- Bedroom night-trust HOLD — HVAC-tier ONLY (`hvac_fans.py:417-440`). Room-tier has a sleep-occupied-hold sibling at `automation.py:1612-1618` but with different semantics.

### Prior planning docs consulted

- `docs/planning/project_v4_7_20_fan_noise_layer1_live.md` (memory) — Layer-1 silent hold/decay.
- `docs/planning/project_v4_7_22_fan_recheck_mode2_live.md` (memory) — Mode-2 BLE-gated pause/recheck. **Critical reader:** `presence_fan_recheck.py` reads HVAC-tier state directly (fan_controller._room_fans, manual_off_cooldown_until at :999-1002).
- `docs/planning/project_fan_noise_mmwave_mitigation_backlog.md` (memory) — full layered design.
- Bathroom-exhaust intelligence cycle — precedent for **collapsing one fan family (humidity) to a single owner** while leaving another (comfort) split. Confirms consolidation is a proven pattern here.

### Memory bodies pulled

- Silent-actuator failure class — direct actuation is the highest-blast-radius write in URA; consolidating writers requires operator-facing behavior invariance.
- v4.7.13 sleep fan fixes validated — proves the current sleep-branch logic is load-bearing on real overnight behavior.
- v4.7.25 HVAC presence timer knobs live — shows the CONF/Number persistence pattern if any policy knobs need to move.

### Design docs read

- `docs/Coordinator/HVAC.md` — TBD-check for fan controller section.
- `docs/Coordinator/PRESENCE.md` — TBD-check for fan-recheck subsection.

### Code locations surveyed end-to-end

- All files enumerated in DOC 1 institutional-context section, plus:
- `presence_fan_recheck.py:990-1014` (reader of the HVAC-tier cooldown).
- `hvac_fans.py:158-333` (turn-off-all-managed, update loop, night-trust cap).

---

## Problem statement

Two independent DECISION sources (room-tier temp-threshold, HVAC-tier setpoint+delta) each carry their OWN implementation of what happens once they've decided "the fan should be on/off." The two implementations have drifted:

| Policy / mechanic | Room-tier (automation.py) | HVAC-tier (hvac_fans.py) |
|---|---|---|
| Hysteresis value | inline `2.0` (line 1585) | `DEFAULT_FAN_HYSTERESIS` module constant |
| Manual-off cooldown | **MISSING** (the DOC-1 bug) | 1h via `manual_off_cooldown_until` |
| Min-runtime | **MISSING** | `DEFAULT_FAN_MIN_RUNTIME` |
| Vacancy-hold mechanic | `_fan_vacancy_start` + CONF-driven seconds | `vacancy_detected_time` + hvac_const default |
| Occupancy gate ordering | temp first, occupancy overrides | occupancy first (v4.0.15 fix) |
| Sleep policy axis | per-room `is_sleep_mode_active` time-window | `FAN_TRUST_STATES` house-state |
| Sleep-policy handling | force-off / speed-cap 33% | night-trust cap via `_apply_night_trust_speed_cap` |
| Fan-recheck handshake | not participating | `fan_recheck_suppress_until` |
| Bedroom night-trust HOLD | different sibling logic | dedicated block |
| Actuation call | inline `_safe_service_call` (fan / homeassistant domain split) | `_set_fan_state` helper |

The DOC-1 fix closes ONE hole (manual-off) by porting the mechanism. Each further drift will require the same port. That's the smell that says "extract."

## Proposed shared layer

**Name:** `FanActuator` (module-level class in a new file `custom_components/universal_room_automation/fan_actuation.py`, or attached to the coordinator manager for lifecycle — TBD in build).

**Responsibility:** All ACTUATION mechanics — the ingredients neither policy source can afford to disagree on:

- Manual-off detection + cooldown (single source of truth).
- Min-runtime.
- Hysteresis clamp on the desired-state transitions.
- Sleep-policy speed cap.
- Vacancy-hold anchor.
- Fan-recheck handshake (bidirectional with `presence_fan_recheck.py`).
- The physical `turn_on` / `turn_off` / `set_percentage` call, with the fan.* vs switch.* domain split.
- Per-fan state ledger (is_on, last_on_time, speed_pct, last_off_reason).

**What it does NOT own:** the DECISION of what the desired state SHOULD be. That stays in two thin caller sites:

- Room-tier `handle_temperature_based_fan_control` — computes `(desired_on, desired_speed_pct, reason)` from room temp + threshold, hands the tuple to `FanActuator.request(room, tuple)`.
- HVAC-tier `FanController._evaluate_temp_fan` — computes the same tuple from setpoint + delta, hands to the same `FanActuator.request`.

**Interface (sketch, discussion-shape only):**

```
class FanActuator:
    async def request(
        self,
        room_name: str,
        fan_entities: list[str],
        desired: FanDesire,      # (on: bool, speed_pct: int, source: str)
        context: FanContext,     # (occupied, house_state, is_sleep_active, ...)
    ) -> FanActuationResult:
        # 1. Apply manual-off cooldown veto.
        # 2. Detect external state change (log + set cooldown if we were on and now off).
        # 3. Apply min-runtime lock.
        # 4. Apply sleep-policy cap.
        # 5. Apply hysteresis (compare desired vs last_speed).
        # 6. Emit the service call if state actually changes.
        # 7. Update ledger + return the observed outcome.

    def get_cooldown_until(self, room_name: str) -> datetime | None:
        # Reader for presence_fan_recheck.py — single accessor replacing
        # both room-tier and HVAC-tier internal-state reads.
```

**Ownership arbitration.** `FanActuator.request` needs to know which policy source is CURRENTLY authoritative for a given room. Rather than re-plumb `_is_hvac_managing_fans` inside the actuator, keep the ownership check at the CALLERS (both must call `_is_hvac_managing_fans` before invoking `.request`); actuator processes any request that arrives. Rationale: ownership is an INPUT arbitration, not an actuation concern. Preserves the room-tier-as-fallback contract: if HVAC coordination is off (or the room is not in Zone Manager wiring), room-tier owns comfort fan control.

**Reader consolidation.** `presence_fan_recheck.py:992-1014` currently reaches into `fan_controller._room_fans[room_name].manual_off_cooldown_until`. Replace with `FanActuator.get_cooldown_until(room_name)` — one accessor, no cross-coordinator private-field peeking, and the room-tier cooldown is automatically visible (unlike the DOC-1 minimum where the room-tier cooldown is invisible to the recheck path).

## Pros / cons / risks

### Pros

- **Single source of truth for actuation mechanics.** New policies (min-runtime, hysteresis tuning, cooldown length) land in one place.
- **The DOC-1 hole disappears by construction.** No possibility of a "room-tier is missing X that HVAC-tier has."
- **`presence_fan_recheck.py` gets a clean accessor.** No more `fan_controller._room_fans[...]` reach-around; the cooldown reader covers BOTH tiers automatically.
- **Prior-art alignment.** The bathroom-exhaust cycle already collapsed the humidity path to a single owner. Extending the pattern to comfort actuation (not comfort DECISION) is idiomatic.
- **Diagnostic surface.** A single ledger enables one "fan health" sensor instead of two independent state machines.

### Cons

- **Blast radius.** Every fan actuation in the house routes through this layer. Regression = every fan.
- **Behavior-frozen requirement.** The extraction MUST be byte-identical to today's observable behavior for each of the two callers (modulo the intentional DOC-1 fix). Proving byte-identity across the eight-mechanic × two-caller matrix is genuinely hard.
- **Sleep-policy axis mismatch.** Room-tier and HVAC-tier deliberately use DIFFERENT sleep axes (per-room time-window vs house_state) — hvac_fans.py:1603-1611 documents this as intentional. The shared layer must PRESERVE per-caller sleep semantics, not collapse them. Adds interface complexity (context payload must carry both axes).
- **Fan-recheck handshake bidirectionality.** `fan_recheck_suppress_until` and manual-off cooldown interact non-trivially (`hvac_fans.py:189-202`). Moving both into the shared layer without breaking the Mode-2 pause/recheck flow requires careful sequencing.
- **Restart semantics.** Neither current tier persists actuation state across restart. If the shared layer changes that (even accidentally), an operator's mid-day manual-off could survive the restart in a surprising way. Explicit "no persistence" design decision needed.
- **Test surface.** Every combination in the matrix above needs at least one dedicated test. High initial write cost.
- **Reviewer capacity.** Tier 3 review discipline (see below) requires 4 framing-disjoint passes; scheduling four reviewers has cost.

### Risks (specific)

1. **Reader poisoning at the seam.** presence_fan_recheck.py:410 currently only sees HVAC cooldown; if consolidation exposes it to room-tier cooldowns, a room-tier fan being manually killed by the operator would ALSO veto the presence-fan-recheck's pause request for that fan. **This is arguably CORRECT** (don't pause a fan the operator just killed) but IS a behavior change and must be operator-approved.
2. **Boot sequencing.** `FanActuator` must exist before either caller wants to emit. Coordinator-manager lifecycle sequencing (see project memory on boot-storm/settle gates) becomes load-bearing.
3. **DOC-1 preemption.** If DOC 1 ships first, DOC 2's extraction has to migrate the room-tier cooldown code that DOC 1 introduces. Not hard — but note in DOC 2 build plan that DOC 1's `_fan_manual_off_until` datetime field is throwaway (moves into the actuator's ledger).
4. **Signal-bus interactions.** Neither tier currently emits dispatched signals on fan actuation; the shared layer might grow one and become the writer for a new signal — but any such signal would be a new addition, not a migration, so contained.
5. **Actuator reconciler interaction.** `actuator_reconciler.py:778` currently defers on `_is_hvac_managing_fans`. Post-extraction, the reconciler should route through `FanActuator.request` too — otherwise reconciler is a THIRD writer bypassing the shared cooldown. Adds a caller.
6. **Rollback surface.** Rolling back a bad extraction means reverting a large refactor. DOC 1's narrow fix has a trivial rollback (revert the file). Weigh this.

## Recommended tier

**Tier 3** — delicate shared-primitive / invariant-critical cycle.

Justifications matching CLAUDE.md Tier 3 triggers:
- Threading a value (cooldown, min-runtime, hysteresis, sleep-cap) through a state machine consumed by many emission/decision sites (Bug Class #53 shape).
- The change is comfort-AND-safety-impacting via the fan-noise/presence seam: a botched cooldown can either (a) let an unwanted fan re-arm at 3am (comfort), or (b) prevent a legitimate fan from ever running (safety-adjacent in a July bedroom).
- History: three separate cycles have touched fan mechanics in the last quarter (v4.7.13 sleep fan trust, v4.7.20/20.1 Layer-1, v4.7.22 Mode-2 recheck). Cumulative fix-up count says "delicate."

Falsifiable invariant (D-reviewer's target):

> "For every actuation of any comfort or humidity fan in the house, the applied `desired_on` state respects the union of every applicable mechanic (manual-off cooldown, min-runtime, hysteresis, sleep-policy cap, vacancy hold, fan-recheck suppression) — and there is no code path from any caller to any HA `fan.turn_on` / `fan.turn_off` / `homeassistant.turn_on` / `homeassistant.turn_off` service call for a room fan that bypasses `FanActuator.request`."

D reviewer: grep every `SERVICE_TURN_ON` / `SERVICE_TURN_OFF` / `homeassistant` / `fan.turn_` call in the repo, check each is either non-fan or routed through the shared layer. Mutation-anchor each load-bearing site.

## Open decisions for operator (this is a discussion doc — do not build)

1. **Is the DOC-1 narrow fix enough for now, deferring DOC 2?** Recommended: yes. Ship DOC 1, observe for further drift, revisit DOC 2 if another mechanic-hole appears within ~90 days.
2. **If DOC 2 proceeds, when?** Suggest at least one full deploy cycle of DOC 1 lived-in first, so real behavior around the room-tier cooldown is understood before the refactor absorbs it.
3. **Where does `FanActuator` live?** Options: (a) new file `fan_actuation.py` at package root, injected into both callers; (b) attached to `coordinator_manager` for lifecycle; (c) attached to a NEW "actuation" domain coordinator. (b) fits current architecture with least new machinery.
4. **Does `FanActuator` own the humidity path too?** Humidity is currently single-owner (room-tier only). Consolidating comfort actuation without humidity leaves the future extraction incomplete; folding humidity in enlarges scope but avoids a second refactor. Recommend: **defer humidity** — it is single-owner already and the extraction value is lower.
5. **Ownership arbitration mechanism.** Keep at callers (recommended) or move into actuator? Callers is smaller-blast and preserves the current defer semantics.
6. **Persistence.** Explicit "no persistence, restart resets all timers" decision — matches today's behavior in both tiers. Confirm operator agrees.
7. **Sleep-policy axis unification.** The two tiers use DIFFERENT sleep signals deliberately. Do NOT unify in this cycle — preserve both. Operator: confirm you want that preserved (an alternative future cycle could rationalize the two policies, but that's a separate discussion).
8. **Actuator reconciler.** Should it also route through `FanActuator.request`? Recommend yes (else it's a third writer bypassing the shared layer). Adds a caller migration.

## Non-goals for this cycle

- Do NOT unify the two DECISION sources (temp-threshold vs setpoint+delta). The room-tier exists as the self-contained comfort fallback when HVAC coordination is off; that redundancy is the feature.
- Do NOT change the fan-noise Layer-1 / Mode-2 mechanics — they migrate as-is into the actuator's `fan_recheck_suppress_until` field.
- Do NOT persist actuation state across restart.
- Do NOT introduce new operator-facing knobs. All policy values move rung-preserving (module constants stay module constants, CONF fields stay CONF fields).

## Files (design sketch — for discussion, not for building)

- NEW `custom_components/universal_room_automation/fan_actuation.py` — `FanActuator`, `FanDesire`, `FanContext`, ledger.
- `custom_components/universal_room_automation/automation.py` — `handle_temperature_based_fan_control` becomes ~15 lines: compute desire tuple, call actuator.
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` — `FanController.update` computes desire per room, calls actuator; `RoomFanState.manual_off_cooldown_until` + `fan_recheck_suppress_until` fields removed (moved to actuator ledger).
- `custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py:992-1014` — `_fan_in_manual_cooldown` becomes a thin wrapper over `FanActuator.get_cooldown_until`.
- `custom_components/universal_room_automation/actuator_reconciler.py:778` — reconciler routes fan actuation through actuator too.
- `custom_components/universal_room_automation/coordinator_manager.py` — construct `FanActuator` in coordinator lifecycle.
- `quality/tests/test_fan_actuator_*.py` — full matrix (~1 test per row in the mechanics table × per caller).

---

## 2026-08-01 — Study A 4h vacant-fan incident: two confirmed bugs, both tier-seam class (this plan's raison d'être; fold as D0/D1 of the refresh)

Verified chain (recorder + DB + code):
1. **Unexpected HA restart 08:02 CDT** (cause unconfirmed — supervisor log window rotated; watch for recurrence).
2. **BUG 1 — room-tier vacancy-hold override ARMS turn-ONs post-restart** (`automation.py:~1697-1703`): restart wipes RAM `_fan_vacancy_start`; first vacant tick re-stamps it; for the next `fan_vacancy_hold` (default 300s) the override sets `occupied=True`, which reaches the TURN-ON branch — so every reboot, every hot (temp ≥ speed thresholds) VACANT room gets its fan turned on at speed. Study A: fan ON 100% @ 08:05:19, room vacant all day. Intent was "don't turn OFF running fans immediately on timeout"; fix: apply the override only when a fan is ALREADY on (`any_fan_on`), matching the stated intent. NOTE: v5.40.0's away-veto now blocks the away/vacation instance at this site; home_day vacant rooms remain exposed.
3. Boot ordering: during warmup HVAC's fan_controller isn't populated → room-tier owned the fan and lit it; once HVAC setup completed, `_is_hvac_managing_fans()` → room-tier early-returns forever (its off-branch unreachable for this room).
4. **BUG 2 — HVAC-tier external-state sync is one-way** (`hvac_fans.py:209-238`): sync adopts external OFF (case 1) and external ON *during a cooldown* (case 2), but NOT external ON with no cooldown — exactly the room-tier-boot-lit state. `room_fan.is_on` stays False; the vacancy off-path short-circuits on `not occupied and not room_fan.is_on` → **nobody owns the off**. Fan ran 4h vacant until manual off. Fix: sync case 3 — adopt external ON (no cooldown) with trigger="external" so normal vacancy-off semantics apply.

Both fixes are small, testable, and belong to this plan's D-list as the FIRST deliverables of the refresh (they're the third live instance of the tier-drift class). D2-mmwave dependency: D2's "vacancy turns the fan off post-demotion" assumption is FALSE while BUG 2 exists for ownership-gap fans — sequence the FanActuator refresh (or at minimum BUG 1+2 hotfixes) BEFORE or WITH the D2 deploy.
