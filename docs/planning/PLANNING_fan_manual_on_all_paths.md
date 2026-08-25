# PLANNING — Manual-ON Detection Across ALL Fan Paths

**Cycle**: FAN-MANUAL-ALLPATHS-1
**Author**: ura-planner
**Date**: 2026-08-23
**Status**: DRAFT — falsification result BLOCKS builder dispatch until operator resolves the framing below
**Tier proposal**: **Tier 3** (four framing-disjoint reviews). See §Tier Justification.

---

## 0. FALSIFICATION FIRST — the operator's diagnosed gate is REFUTED

The operator's read: "`hvac_fans.py` state-sync has exactly TWO branches; the second is gated on `manual_off_cooldown_until` being truthy; an external-ON from idle falls through both."

**This is not what the current code says.** `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` has **THREE** branches in the state-sync section (lines 588-747):

1. `if room_fan.is_on and not any(entity_on)` — external OFF → cooldown (line 588)
2. `elif not is_on and manual_off_cooldown_until and any(entity_on)` — reversal during cooldown (line 623)
3. `elif not is_on and NOT manual_off_cooldown_until and any(entity_on)` — **adoption of externally-lit fan from idle** (line 670)

Branch 3 was added 2026-08-01 as "BUG 2 fix ... Study A, Phase 1 D1" (comment lines 661-669). It sets `is_on=True`, `trigger="external"`, opens `manual_on_hold_until` via the locked setter (§5.4 sites #8/#9), and **logs at INFO**: `"HVAC Fans: %s adopted externally-lit fan (speed=%d%%, manual_on_hold_until=%s)"` (line 742-747).

Test 1 (idle + external ON, ZERO log lines) SHOULD have tripped this branch and emitted that log line. It did not. **The gate the operator identified is not load-bearing** — a general adoption branch already exists. Something else swallowed test 1.

### Candidate real mechanisms (measured evidence + code, not inferred)

- **C1 — Living Room is not in HVAC `_room_fans`.** The live boot warning quoted by the operator ("Room Living Room expects HVAC fan management ... but is not in HVAC fan_controller._room_fans — room-tier is owning fans") says so directly. If true, `for room_name, room_fan in self._room_fans.items()` at line 569 never iterates Living Room and NONE of the three branches run for it. **But then test 2's log line `[hvac_fans] "Living Room turned on during cooldown"` would be impossible** — that log comes from branch 2 (line 655-660). So either the boot warning has stopped applying by test time, or the room *is* in `_room_fans` and something else swallowed test 1.
- **C2 — the 5-min HVAC cycle didn't tick during test 1's ~4-minute window.** `update()` is called from the HVAC decision cycle every 5 min (comment line 498). Test 1 = 11:23:21 → 11:27:16, ~235s. Plausible for zero ticks. Test 2 held 10+ min so at least one tick landed inside it. If this is the cause, the defect is not the branch set — it is that detection is **poll-based on a 5-min cadence** with no event-driven trip. That is a *general* gap.
- **C3 — `fan_recheck_suppress_until` early-continue at line 574-583 swallowed the tick.** The room skips the entire state-sync block while the recheck pause is active. Whether a manual ON during that pause is a signal at all is one of the enumeration items below.
- **C4 — room-tier owns detection AND has no equivalent adoption branch.** `domain_coordinators/presence_fan_recheck.py` and any room-tier fan path in `hvac.py`/`presence.py` must be read end-to-end (this plan spec'd the read; the builder must do it) before we know whether the room-tier path detects external-ON at all.

**Also unexplained on the operator's read:** `sensor.living_room_fans_on = 0` for the entire 10 min of test 2 even though branch 2 logged and set `is_on=True`. Either the sensor reads a *different* backing (room-tier state, not HVAC `_room_fans`) — pointing at C1/C4 — or `is_on=True` was written but not observed by the sensor's reader. This is the "second measured anomaly" the operator flagged; **it discriminates C1/C4 from C2/C3**, because under C2/C3 the sensor should have gone to 1 after the branch-2 log line and stayed there.

### Operator decision required before build

The operator's ask ("plan a big fix for other paths") is well-founded even under the refuted framing — the enumeration below still needs doing. But the *specific* fix scope depends on which mechanism is the real one, and the evidence is not yet unambiguous. **Recommended next step: 30-minute measurement probe (measure-before-build)** consuming existing recorder data:

- Query `states` for `fan.towerfan_dreopilotmaxs_wifi_livingroom` around 11:23:21 and 11:38:52 on 2026-08-23.
- Query `states` for `sensor.living_room_fans_on` across the same window.
- `grep` core.log for `HVAC Fans: Living Room adopted externally-lit` in the last 7 days — was branch 3 EVER firing for this room?
- `grep` core.log at boot for the "room-tier is owning fans" warning date, and check if it recurs on the last restart.

The probe's answer decides the plan:
- If branch 3 has fired historically for other rooms but never for Living Room → **C1/C4** (tier ownership); fix is a room-tier detector at parity with HVAC branch 3.
- If branch 3 has never fired for anyone → the branch is dead code (unreachable) and the fix is either wiring it or replacing it with event-driven detection → **C2**.
- If branch 3 fires but only on cycle boundaries → **C2** confirmed; fix is event-driven trip.

**This plan proceeds as if the probe returns C1+C4 (tier-ownership gap) — the most consistent explanation of ALL the measured evidence including `sensor.living_room_fans_on=0`. If the probe returns a different mechanism, sections D2-D4 need rescoping before build.**

---

## 1. Institutional context verified

Files read end-to-end during scoping:
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` — full state-sync block lines 464-750; oracle-locked setter sites; `_is_manual_on_hold_live`; `_resolve_live_manual_on_hold_s`; `turn_off_all_managed`.
- Same file — `_OracleISOField` machinery lines 243-320 (INV-FLA-T locked-setter contract).

Files planner requires builder to read end-to-end BEFORE any edit (skimmed but not fully consumed here):
- `docs/planning/PLANNING_fan_actuation_shared_layer_v2.md` — FanPolicyOracle parent.
- `docs/planning/PLANNING_fan_layer_2_roomfanstate.md` — §5.4 locked-setter site catalogue that any new write MUST extend.
- `docs/readmes/README_v5.68.0.md` — FAN-MANUAL-1 shipped record; observed-in-live evidence for branches 2 & 3.
- `docs/planning/PLANNING_fan_recheck_d2_deadlock_fix.md` + `AUDIT_fan_recheck_managed_fan_d0.md` — recheck-suppress interaction with state-sync.
- `custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py` — room-tier recheck path.
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — search for the "room-tier is owning fans" boot warning emitter and for any room-tier fan actuation/adoption path.
- Cards (kanban): FAN-MANUAL-1, FAN-LAYER-1, FAN-LAYER-2 (2026-08-23 tier-ownership instance), FAN-RECHECK-D2-DEADLOCK-1, FAN-RECHECK-NOT-CLEARING-1, FAN-RECHECK-SLEEP-VETO-SCOPE-1, FAN-SUSTAINED-SHAKE-DEMOTE-1, ARREST-COMFORT-1.
- `custom_components/universal_room_automation/const.py` — grep `MANUAL_ON`, `MANUAL_OFF`, `COOLDOWN`, `HOLD_S` — every new number MUST cite REUSED or NEW.

Grep results (partial, extend during build):
- `CONF_FAN_MANUAL_ON_HOLD_S` + `DEFAULT_FAN_MANUAL_ON_HOLD_S` — REUSED (`const.py`; wired at `hvac_fans.py:22, 29`). No new knob for hold duration needed.
- `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S` — REUSED (`const.py`; `hvac_fans.py:28`).
- `_is_manual_on_hold_live`, `_resolve_live_manual_on_hold_s`, `_is_entity_on` — REUSED helpers (`hvac_fans.py:1379, 1396, 1444`).
- `oracle.set_manual_on_hold_locked` / `clear_manual_on_hold_locked` / `set_manual_off_cooldown_locked` — REUSED (§5.4 sites; any new write MUST use these, not bare-field assignment).

Design docs: `docs/Coordinator/hvac.md` and `docs/Coordinator/presence.md` (builder to read).

---

## 2. Falsifiable invariant (Tier 3 requirement)

> **Under any legal room configuration with `fan_control_enabled=True` and at least one entity in `fans=[...]`, if any listed fan entity transitions to state=`on` from any cause other than a URA-emitted turn_on, then within `MANUAL_ON_DETECTION_MAX_LAG_S` seconds URA's internal fan model shall reflect `is_on=True` AND — unless a live discharge event has fired between the transition and the detection — `manual_on_hold_until` shall be set to at least `now + fan_manual_on_hold_s` (or explicitly disabled by the kill-switch value 0). This shall hold in ANY reachable code path: idle+ON, cooldown+ON, recheck-suppress+ON, boot+already-ON, speed-change-only, humidity-fan path, bathroom-exhaust path, and regardless of which tier (HVAC vs room) owns the fan.**

The load-bearing property is the **conjunction of `is_on` sync AND hold-open**. Missing either is a failure; test 2 satisfied both (log line + hold), test 1 satisfied neither (no log, `sensor.living_room_fans_on=0`).

Discharges that legitimately clear the hold (already codified — Reviewer D must re-enumerate): external OFF (§5.4 site #4), kill-switch flip, `turn_off_all_managed`, expiry, hold-pause+recheck-restore. Any NEW discharge added by this cycle must state its trigger and be enumerated here.

`MANUAL_ON_DETECTION_MAX_LAG_S` — **NEW knob, module constant (rung 1)**. Justification: bounds the invariant; changing it should require review because too-large silently degrades the invariant while too-small can hammer the state machine. Proposed default = 30s. Not operator-tunable.

---

## 3. Tier justification

**Tier 3 (four framing-disjoint reviews).** Triggers met:
- Shared primitive (fan state model) consumed by HVAC-fans, room-tier fan, presence-recheck, humidity-fan, bathroom-exhaust.
- Comfort-affecting; test 1 revertsed a fan the operator had turned on.
- Failure mode is **one missed path** (Bug Class #53 computed-but-not-consumed applied to detection sites) — exactly the shape D4 exists to catch.
- Adjacent history: v5.68.0 FAN-MANUAL-1 required a §5.4 site catalogue and a follow-on FAN-LAYER-2; the 2026-08-23 instance surfaced tier-ownership ambiguity.

Framings:
- **A — local correctness** of each new detection branch and its locked-setter call (§5.4 pattern conformance).
- **B — integration/state-machine integrity**: existing branches 1/2/3 byte-identical on their existing paths; no double-emit; recheck-suppress semantics preserved; restart resilience via oracle ledger.
- **C — test authority via per-site source mutation**: neuter each new detection site one at a time, confirm ONE specific test red-lines. Aggregate monkeypatch is insufficient.
- **D — adversarial completeness / diff-blind**: re-enumerate ALL fan-arrival paths in the WHOLE repo (not just this diff), state the invariant in §2, and produce a legal-config reachable repro for any leak. D must independently answer: does the room-tier own Living Room? Does the HVAC-fans path also see it? What happens on speed-change? On boot? On humidity-fan?

---

## 4. Producer / Consumer map for `room_fan.is_on`

### Producer (how it is written)
Every site that mutates `room_fan.is_on` in `hvac_fans.py` — enumerate during build via `git grep -n "\.is_on\s*=" custom_components/universal_room_automation/domain_coordinators/hvac_fans.py`. Known sites from this planning read:
- line 287 — `__init__` seed (default False)
- line 477 — `turn_off_all_managed`
- line 618 — branch 1 (external-OFF): False
- line 631 — branch 2 (reversal): True
- line 708 — branch 3 (adoption from idle): True
- line 853 — inside `_evaluate_temp_fan` post-actuation write
- line 1047 — (verify)
- line 1988 — (verify)
- line 2009 — (verify)

Producer dependency health: depends on `hass.states.get(entity_id)` returning current state (freshness OK — states are event-driven in HA). Depends on `_room_fans` containing the room (C1 gap). Depends on `update()` being called on schedule (C2 gap).

**External ground truth**: the HA entity state `fan.<x>` itself — NOT a sibling URA number.

### Consumers (who reads it, trust vs display)
- `sensor.<room>_fans_on` — DISPLAY (and possibly TRUST elsewhere — measure). The test-2 anomaly (reads 0 while `is_on=True` was written) says this consumer reads a DIFFERENT backing than HVAC `_room_fans`. Locating that backing IS one of the build tasks — likely a room-tier field.
- `_evaluate_temp_fan` and the vacancy-off sweep — TRUST (decide whether to turn OFF).
- `is_room_in_manual_on_hold` accessor (line 1430) — TRUST by downstream (arrester-comfort etc.).
- `diagnostics` snapshot at ~line 2068+ — DISPLAY.

**Discriminating observation**: if branch 3 fires and `is_on=True` is written but `sensor.living_room_fans_on` still reads 0, the sensor consumes a NON-HVAC backing. That is a distinct producer that must ALSO be updated by every manual-ON detection site — a should-be-consuming gap.

---

## 5. Enumerated arrival paths and required handling

| # | Path | Today's handling | Required |
|---|---|---|---|
| P1 | External ON from idle, HVAC-tier owned | Branch 3 (line 670) — adoption + hold-open | Verify branch 3 actually fires for this room; add event-driven trip if C2 confirmed |
| P2 | External ON during cooldown, HVAC-tier owned | Branch 2 (line 623) — clear cooldown + hold-open (confirmed live) | **Preserve byte-identical.** |
| P3 | External ON while `fan_recheck_suppress_until` active | `continue` at line 580 SWALLOWS the tick | Decide: does the manual ON override the suppression, or does the suppression's discharge (recheck-restore) re-evaluate and adopt? Explicit policy required. Default proposal: manual ON discharges the suppression (freshest-human-wins, §5.4 doctrine) — mirror the discharge added by FAN-MANUAL-1 for external OFF. |
| P4 | External ON at boot, before `is_on` seeded | `__init__` seeds False; discover_fans reads oracle ledger; first `update()` tick catches it via branch 3 IFF the tick fires before someone turns it off | Add explicit boot reconciliation: at end of `discover_fans`, sample entity states once; call the same detection helper. |
| P5 | External SPEED change on already-on fan | Not handled | **Decide: is this manual?** Proposal: YES — refresh `manual_on_hold_until` and update `speed_pct`. Rationale: user touched the fan. Reviewer D must challenge. |
| P6 | Room-tier-owned fan (C1: Living Room, Study A) | HVAC-fans loop never iterates → no detection at all | **Room-tier detector at parity with HVAC branch 3.** New site(s) in `presence_fan_recheck.py` / `hvac.py` / wherever room-tier owns fans. Locked-setter contract STILL applies — writes go through the FanPolicyOracle. |
| P7 | Humidity-fan path | Read `domain_coordinators` for humidity-fan owner during build | If the humidity-fan primitive shares `RoomFanState`, detection reuses the shared helper. Otherwise: parity detector. Non-goal to unify actuation. |
| P8 | Bathroom-exhaust path | Same as P7 | Same as P7 |

**Every path emits an INFO log line with a stable prefix (`FAN-MANUAL-DETECT`) and identical structured fields** (room, entity, prior_owner_tier, cause, hold_until). This is the discriminating observation for validation.

---

## 6. Deliverables

### D1 — Measurement probe (BEFORE any code)
Read-only recorder query producing:
- Historical branch-3 firings across all rooms (log-grep, 7 days).
- `fan.towerfan_dreopilotmaxs_wifi_livingroom` + `sensor.living_room_fans_on` state series around the two test windows.
- Boot-time "room-tier is owning fans" warning presence on the last 3 boots.
- Enumeration (grep-based) of every file that writes `room_fan.is_on`, every file that reads `sensor.*_fans_on`, and every current owner of `fans=[...]` at either tier.

**Acceptance**:
- **Verify**: probe report committed to `docs/planning/AUDIT_fan_manual_on_all_paths_probe.md`.
- **Discriminates**: if probe shows branch 3 firing regularly for other rooms → C1/C4 confirmed. If never firing → C2. Different mechanism → rescope §5.

### D2 — Shared `detect_manual_on()` helper
Extract a single helper on the fan-state module (or `FanPolicyOracle`) that: takes `(room_key, entity_ids, room_fan_or_equivalent)`, applies the branch-3 logic (adoption + speed sample + locked hold-open) OR the branch-2 logic (reversal + cooldown clear + hold-open) as appropriate, emits the standard log line, and is idempotent.

**Reused vs new**: helper NEW (no equivalent factored function exists); every write inside it uses REUSED locked-setter methods.

**Acceptance**:
- **Verify**: `git grep -n "detect_manual_on\|_adopt_external_fan"` returns exactly one helper definition.
- **Test**: mutation-neuter the helper body → red-lines a specific test per site.
- **Sensor**: no new sensor.
- **Live**: N/A (structural).
- **Discriminating**: under the fix a manual ON produces exactly ONE `FAN-MANUAL-DETECT` INFO line; under a plausible alternative failure (double-detect) it produces TWO. Test asserts count == 1.

### D3 — Event-driven trip (path P1/P2/P4)
Replace pure-poll detection with an `async_track_state_change_event` listener over the union of `fans=[...]` across all managed rooms (HVAC-tier). On any `off→on` transition, dispatch to `detect_manual_on()` for the owning room. Keep the 5-min poll as backstop.

**Knob**: `MANUAL_ON_DETECTION_MAX_LAG_S` — module constant, rung 1 (see §2). Kill switch: 0 disables event-driven trip → falls back to poll only.

**Acceptance**:
- **Verify**: on a live idle+ON test (test 1 replay), `FAN-MANUAL-DETECT` INFO line lands within `MANUAL_ON_DETECTION_MAX_LAG_S` (default 30s), NOT waiting for the 5-min tick.
- **Discriminating**: under the fix the log lands within 30s; under a poll-only regression the log lands 0-300s later. Time-to-log discriminates.
- **Live**: `sensor.<room>_fans_on` reads 1 within same window.
- **Test**: `test_manual_on_event_driven_trip` fires a state change and asserts the helper was called within 1s (fake clock).

### D4 — Room-tier detector (path P6)
Wire the same helper into whichever room-tier module owns fans for rooms flagged by the boot warning. Room-tier and HVAC-tier MUST NOT both write for the same room — enforce single-owner via existing `_room_fans` membership check + a mirror check on the room-tier side. Boot warning becomes a diagnostic sensor / repair issue (out-of-scope for this cycle to fix the warning itself; scope is only to STOP the detection gap).

**Acceptance**:
- **Verify**: for Living Room and Study A, test 1 replay produces a `FAN-MANUAL-DETECT` line tagged `prior_owner_tier=room`.
- **Discriminating**: under the fix the tag identifies the owner; under a double-detect regression BOTH tiers log (test asserts exactly one tier logs).
- **Sensor**: `sensor.living_room_fans_on` reads 1.

### D5 — Recheck-suppress interaction (path P3)
Add a manual-ON discharge to `fan_recheck_suppress_until`: on detected manual ON during suppression, clear `fan_recheck_suppress_until` (freshest-human-wins), then run the shared helper. Locked-setter contract applies.

**Acceptance**:
- **Verify**: replay test — turn a fan ON externally while recheck-suppress is active, INFO line `FAN-MANUAL-DETECT ... cause=suppress-discharge` lands within lag budget; suppress field cleared.
- **Discriminating**: under the fix the suppress field clears; under the current bug it does not. Read the field post-event to discriminate.

### D6 — Speed-change detection (path P5)
On observed speed delta with entity already on and URA `is_on=True`, refresh `manual_on_hold_until` and update `speed_pct`. Emits `FAN-MANUAL-DETECT ... cause=speed-change`.

**Acceptance**:
- **Verify**: change fan speed externally; hold refreshes; `speed_pct` matches observed.
- **Discriminating**: under fix hold-until moves forward; under regression it stays put. Read the field pre/post.

### D7 — Boot reconciliation (path P4)
End of `discover_fans`: single-shot state sample + `detect_manual_on()` call per already-on entity.

**Acceptance**:
- **Verify**: restart with a fan already ON → INFO line `FAN-MANUAL-DETECT ... cause=boot-reconcile` within N seconds of setup complete; `sensor.<room>_fans_on = 1`.
- **Discriminating**: under fix boot reconciles immediately; under regression waits for first `update()` tick.

### D8 — `sensor.<room>_fans_on` reader unification
Locate the sensor's current backing (build task; likely room-tier field per test-2 anomaly). Either point it at the same source of truth as HVAC `_room_fans.is_on`, OR ensure `detect_manual_on()` updates BOTH backings. This is the should-be-consuming gap surfaced by the second measured anomaly.

**Acceptance**:
- **Verify**: after any `FAN-MANUAL-DETECT` line, `sensor.<room>_fans_on` reads 1 within one HA state tick.
- **Discriminating**: this criterion is the ONLY one that directly proves the test-2 sensor anomaly is closed. Without D8, D2-D7 could all pass while the sensor still reads 0.

---

## 7. Non-goals

- Not changing branch 1 (external-OFF) or branch 2 (reversal) semantics. Byte-identical preservation is a review-B requirement.
- Not resolving the "room-tier is owning fans" boot warning at its source (config migration territory) — cycle only closes the DETECTION gap that ambiguity creates.
- Not adding a new operator-tunable knob for hold duration (`CONF_FAN_MANUAL_ON_HOLD_S` REUSED).
- Not merging humidity-fan / bathroom-exhaust actuation with HVAC-fan actuation — only sharing the DETECT helper if state shape allows.
- Not attempting to fix the FanPolicyOracle §5.4 site catalogue itself; new writes extend it per pattern.
- Not touching `sensor.living_room_fans_on` if its backing turns out to already be correct — D8 is scoped to the anomaly and closes conditionally.

---

## 8. Knob ladder summary

| Knob | Rung | Reused / New | Notes |
|---|---|---|---|
| `CONF_FAN_MANUAL_ON_HOLD_S` | 2 (options flow) | REUSED (`const.py`) | Per-room override; kill-switch = 0 |
| `DEFAULT_FAN_MANUAL_ON_HOLD_S` | 1 (module) | REUSED | Module default |
| `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S` | 1 | REUSED | Untouched |
| `MANUAL_ON_DETECTION_MAX_LAG_S` | 1 | **NEW** | Invariant bound; default 30s; kill switch = 0 disables event-driven trip |

No entity-level knob (rung 3) — this is a safety/invariant surface, not operator tuning territory.

---

## 9. Acceptance criteria — cycle-level

Every criterion below MUST discriminate the fix from a plausible different failure.

- **Live**: replay of operator test 1 (idle + external ON, below-threshold temp) produces an INFO log line matching `FAN-MANUAL-DETECT room=Living Room cause=(idle-adopt|suppress-discharge|event-trip) prior_owner_tier=<x> hold_until=<iso>` within `MANUAL_ON_DETECTION_MAX_LAG_S`. Discriminates against C2 (poll-only) by time-to-log.
- **Live**: `sensor.living_room_fans_on` reads 1 within same window and stays 1 until the fan is turned off externally or the hold expires. Discriminates against a `is_on`-written-but-sensor-unaware regression.
- **Live**: replay of operator test 2 (cooldown + external ON) produces the EXISTING `HVAC Fans: <room> turned on during cooldown` log line byte-identical. Discriminates against branch-2 regression.
- **Live**: after either replay, `sensor.<room>_fans_on` transitioning back to 0 requires either external OFF, hold expiry, or `turn_off_all_managed`. A below-threshold URA re-evaluation does NOT turn it off. Discriminates against the reverted-in-test-1 regression.
- **Test**: `test_manual_on_all_paths` — one test per row in §5 table, each mutation-anchored per Tier-3 framing C.
- **Test**: `test_manual_on_invariant_survives_restart` — restart mid-hold; hold restored from oracle ledger; sensor reads 1 within N seconds of setup.
- **Suite**: baseline-diff by name against `pre-review-vX.Y.Z` tag shows only NEW tests added; no existing tests deleted or silently renamed.

---

## 10. Plan-review requirement (Tier 3 → two plan reviews)

Per CLAUDE.md, Tier 3 requires TWO framing-disjoint plan reviews BEFORE builder dispatch:
1. **Completeness review**: independently re-enumerate every fan-arrival path in the repo; challenge §5 table for omissions (e.g. `fan_assist` energy path, sleep-onset one-shot, blueprints).
2. **Adversarial build-prediction**: what will the builder misread? Ambiguities in D2 helper signature; ordering between D3 event listener and D7 boot reconcile at cold-start; single-owner enforcement between HVAC-tier and room-tier (D4) — is there a race?

**Plan-review findings fix IN THIS DOC before build dispatch.**

---

## 11. Open questions for the operator

1. **Falsification blocker**: the operator's "narrow gate" mechanism is refuted (§0). Approve running the D1 probe first, or provide the missing evidence that pins the real mechanism now?
2. **P5 (speed change)**: is an external speed change a manual signal? Planner default = yes; operator confirm.
3. **P3 (suppress + manual ON)**: is manual-ON discharge of `fan_recheck_suppress_until` acceptable, or does suppression outrank freshest-human-wins here?
4. **D4 single-owner enforcement**: if HVAC-tier and room-tier both currently claim ownership, which wins? (Room-tier per boot warning; confirm.)

Blocking: (1). Non-blocking but needed before D5/D6 build: (2), (3), (4).
