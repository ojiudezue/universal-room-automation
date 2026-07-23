---
name: ura-energy-invariants-campaign
description: Decision-gated runbook for URA energy-strategy correctness — proving and defending the battery reserve / TOU / arbitrage / inclement-hold / attain invariant surface so no reachable code path silently loses money. USE THIS SKILL when touching energy_battery.py, energy_tou.py, energy_pool.py, inclement.py, arbitrage phase machinery, the InclementDecision, partial_hold / full_hold / allow_discharge policy, ARBITRAGE_PHASE_WAIT/CHARGE/HOLD/ATTAIN, `_floor_reserve`, `_result`, `determine_mode`, reserve_level emissions, peak_buffer_target, or the `sensor.ura_battery_strategy` attribute surface; when investigating why the battery discharged in a hold, charged when it shouldn't have, or refused to charge at off-peak; when the operator says "this is delicate" about energy; or when planning any change that threads a value through multiple emission sites (Bug Class #53 — computed-but-not-consumed). Do NOT use for HVAC, presence, notifications, or for HA-lifecycle bugs — see sibling skills.
---

# URA Energy Invariants Campaign

Executable, decision-gated runbook for the #1 hardest problem in URA: **energy-strategy correctness**. The goal is to prove — every cycle, per site — that the battery's reserve/hold/charge/discharge decisions honor a small set of falsifiable invariants across every reachable path, and to keep proving it as the surface grows.

You are almost certainly running this **solo, as a Sonnet-class or mid-level engineer, with no subagent fleet**. Every gate below is written to be executable by one person sequentially. Where a fleet exists (`ura-planner`, `ura-builder`, `ura-reviewer`, `ura-validator`) it accelerates the work but is not required.

## When NOT to use this skill

| Concern | Use this instead |
|---|---|
| HA config-flow / entity registration / RestoreEntity lifecycle | `homeassistant_coding` |
| Dashboard / Lovelace card layout | `ha-dashboard` |
| Deploying a version | `deploy` |
| Recording a decision made during this work | `vibememo` |
| Post-deploy behavioral acceptance monitoring | Shipwatch (`~/Code/shipwatch/`, agent `@shipwatch`) |

If the change is purely presence, HVAC, notifications, security, or a hotfix that does not touch a reserve/charge/discharge decision, **stop and pick the right skill**. This skill's ceremony is expensive; do not spend it on the wrong surface.

## Ground truth (verified 2026-07-02, v5.7.2)

Cite these when planning; re-verify with the commands in "Provenance and maintenance" before making claims in a new session.

| Fact | Location |
|---|---|
| Battery strategy class | `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` (3440 LoC) |
| Arbitrage phase constants | `energy_battery.py:56-67` — `ARBITRAGE_PHASE_WAIT/CHARGE/HOLD/DISCHARGE/NA/ATTAIN` |
| Phase resolver | `energy_battery.py:_get_arbitrage_phase` around L1416-1516 |
| Phase → action dispatch (WAIT/CHARGE/HOLD) | `energy_battery.py:_get_arbitrage_decision` around L1536-1636 |
| Reserve-floor clamp helper (Bug Class #53 guard) | `energy_battery.py:_floor_reserve` L1518-1534 |
| InclementDecision dataclass | `inclement.py:493` — carries `hold_depth ∈ {full_hold, partial_hold, allow_discharge}` and `reserve_floor: int` |
| Inclement decision cache in battery | `energy_battery.py:_inclement_decision` L849 |
| Master strategy entry point | `energy_battery.py:determine_mode` L2758 |
| `_result` — the ONLY correct way to emit a decision | `energy_battery.py:_result` L3154 |
| `get_status` — attribute surface for the sensor | `energy_battery.py:get_status` L3332 |
| TOU period resolver (day-boundary safe) | `energy_tou.py` (399 LoC), see the `get_current_period` chain |
| Sensor entity + unique_id | `sensor.py:6766-6800` — `EnergyBatteryStrategySensor`, unique_id `f"{DOMAIN}_battery_strategy"` → `sensor.ura_battery_strategy` |
| Bug Class #53 (computed-but-not-consumed) | `docs/QUALITY_CONTEXT.md` L2168 |
| Bug Class #51 (day-boundary-blind TOU) | `docs/QUALITY_CONTEXT.md` L2045 |
| Prior planning: WAIT/floor closure | `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` |
| Prior planning: attain ladder | `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md` |
| Latest ship (Tier 3, 4-review) | `docs/reviews/code-review/v5.5.3_arbwait_review{A,B,C,D}_*.md` + `v5.5.3_arbwait_summary.md` |

**Correction vs prior memos:** the sensor entity id is `sensor.ura_battery_strategy` (not `sensor.ura_energy_coordinator_battery_strategy`). Verify with `grep -n "battery_strategy" custom_components/universal_room_automation/sensor.py`. Older memos have the wrong name.

**Correction vs prior backlog memos:** the "arbitrage-WAIT bypasses partial_hold floor" gap was **shipped-closed in v5.5.3** (see L1618 threading `_floor_reserve` into the WAIT emission). If a new session cites the gap as "open", verify against current source before acting. See Phase 2 for the current state and the *next* structurally-similar gap to watch for.

## Phase 0 — State the falsifiable invariants (BLOCKING gate)

Before touching code, write these into your planning doc verbatim. Phase 4's completeness reviewer's *only* job is to try to falsify them. A vague invariant produces vague reviews.

| ID | Falsifiable invariant | Falsified by |
|---|---|---|
| I-1 (reserve floor) | In every `_result` return that emits a `reserve_level`, when `hold_depth == "partial_hold"` and `effective_reserve` is not None, the emitted `reserve_level ≥ effective_reserve`. | Any reachable path where the emitted value < `effective_reserve` under a legal config. |
| I-2 (no legitimate-discharge suppression) | `_floor_reserve` can only **raise** an emitted reserve, never lower it. A CHARGE toward a higher target must not be dropped, and `allow_discharge` and `None` paths must be byte-identical to pre-clamp behavior. | Any path where `_floor_reserve` returns < `existing`, or where the wrapped emit changes when `hold_depth == "allow_discharge"`. |
| I-3 (day-boundary correctness) | For any `now` within ±30 minutes of local midnight, `EnergyTOUCoordinator.get_current_period(now)` returns the period the utility actually bills for `now`, and downstream mid_peak/off_peak hold gates read the SAME period the emit uses. | A synthetic `now = 00:00:30` where period read at gate ≠ period used at emit. |
| I-4 (state-matrix closure) | `determine_mode` returns via `_result` **and only** via `_result` on every reachable branch, including error/None-SOC/no-forecast fallbacks. There is no `return` that emits a mode without going through the clamp. | A `git grep -n "return self\._result\|return {" energy_battery.py` finding a dict/mode literal returned bypassing `_result`. |
| I-5 (attain latch integrity) | Attain phase (`ARBITRAGE_PHASE_ATTAIN`, L67) does not unwind mid-charge because a per-tick predicate flipped; it can only exit via SOC≥target or the explicit reset path. | Any tick where phase transitions ATTAIN→WAIT/NA while SOC < target and no reset was called. |

Add or remove invariants only with an explicit line justifying which reachable failure mode you're now covering. Do not restate what a test already covers; state the property that all tests should protect.

## Phase 1 — Enumerate the full emission/decision surface (BLOCKING gate)

Run these greps yourself. **Paste the raw output into the planning doc.** Anyone who says "I know the sites" without pasting the grep is skipping the gate that would have caught v5.5.3 D-HIGH-1.

```bash
cd ~/Code/universal-room-automation

# 1a. Every reserve emission site in the battery coordinator.
grep -n "reserve_level=" custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# 1b. Every _result invocation (should be the ONLY way modes are emitted).
grep -nE "self\._result\(|return self\._result" custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# 1c. Every direct BATTERY_MODE_* return (should be zero — all go via _result).
grep -n "return BATTERY_MODE_\|return \"self_consumption\"\|return \"backup\"" \
    custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# 1d. Every place _floor_reserve is called (must cover every reserve_level= site
#     that runs inside a TOU/arbitrage/attain/inclement branch).
grep -n "_floor_reserve\b" custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# 1e. Every arbitrage phase constant use (state-matrix routing surface).
grep -nE "ARBITRAGE_PHASE_(WAIT|CHARGE|HOLD|DISCHARGE|ATTAIN|NA)\b" \
    custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# 1f. Inclement decision consumers (must all receive hold_depth AND reserve_floor).
grep -rn "InclementDecision\|hold_depth\|reserve_floor" \
    custom_components/universal_room_automation/domain_coordinators/

# 1g. TOU period call sites (day-boundary gate — Bug Class #51).
grep -rn "get_current_period\|tou_period ==" \
    custom_components/universal_room_automation/domain_coordinators/
```

### Expected shape as of 2026-07-02 (v5.7.2)

Use as a sanity anchor, **not** as ground truth — re-run 1a/1d and compare.

| Grep | Expected count | If count differs |
|---|---|---|
| 1a `reserve_level=` in energy_battery.py | 17 | New emission site added — every one must go through `_floor_reserve` OR be justified in writing. |
| 1b `_result(` calls | ≥12 (was 12 pre-v5.5.3) | Fewer than 12 → someone bypassed the emit contract. |
| 1c direct BATTERY_MODE_ return | 0 | Any non-zero = I-4 broken. |
| 1d `_floor_reserve` calls | ≥7 (WAIT/CHARGE/HOLD/attain HOLD/mid_peak/mid_peak-shoulder/peak) | Fewer = a WAIT-style gap re-opened. |

Log every site as REUSED or NEW per CLAUDE.md "Institutional Context First" and cite the exact `file:line`. This *is* the Institutional-Context-Verified section of your planning doc.

## Phase 2 — The known-closed WAIT gap + where the next one lives

**Status:** the arbitrage-WAIT floor bypass (originally cited at `energy_battery.py:1521` — a **pre-fix historical anchor**; do NOT present as current) was closed in v5.5.3 via the `_floor_reserve` helper (verified 2026-07-02 at `energy_battery.py:1519`) and threaded through HOLD (:1568), CHARGE (:1591), WAIT (:1617 — the v5.5.3 fix), with additional clamp sites at :2115, :2169, :2400, :3000 — **7 total call sites** excluding the def. Verify:

```bash
sed -n '1515,1636p' custom_components/universal_room_automation/domain_coordinators/energy_battery.py \
  | grep -nE "_floor_reserve|reserve_level=|effective_reserve"
```

Expect three `floored = self._floor_reserve(...)` sites and three `reserve_level=floored` emits. If any of the three collapses back to the raw `self.reserve_soc` / `self._peak_buffer_target`, that is a **regression** — treat as Tier 3.

### Where the next reachable-path leak most likely lives

These are structural cousins of the WAIT gap. **Do not assume any of these are broken today.** Do assume they will be broken by future changes if this campaign is skipped:

1. **`determine_mode` mid_peak charging branch** — `energy_battery.py` around L2900-3050. Multiple emits with `effective_reserve` computed locally; verify each `reserve_level=` argument passes through `_floor_reserve` or is documented as intentionally raw. Grep hits at L2907/2915/2931/2938/3007/3027/3042/3131/3148 in Phase 1a — audit each.
2. **Attain HOLD / attain fallbacks** — L2076-2183. Attain has its own `effective_reserve` parameter path (2076, 2141, 2170); the clamp already covers it, but a future refactor could split attain into a sibling function that forgets it.
3. **Drain-target fallback** (`reserve_level=drain_target` around L3131) — a legacy path retained "when arbitrage is disabled." Verify it is unreachable when a partial_hold is active OR that the drain target is itself floored.
4. **Inclement precharge / full_hold** — L2907, L2915 emit `reserve_level=decision.reserve_floor` directly. This is correct because `full_hold` computes its own floor, but a change to `hold_depth == "full_hold"` semantics that changes `decision.reserve_floor` shape would silently mis-emit. Re-derive the invariant if `InclementDecision.reserve_floor` semantics change.

Any change that touches these sites is **regression-prone by definition** and must go through Tier 3 (see Phase 6).

## Phase 3 — Config-boundary combinatorial tests (BLOCKING gate)

The v5.5.3 D-HIGH-1 lesson: independent operator knobs create legal combinations the happy path never exercises. That is where the leak hid — and where the next one will.

For any invariant that reads two or more config knobs, test the four corners **and** the inversions where the sliders cross. Concretely:

| Knob 1 | Knob 2 | Corner cases to fabricate |
|---|---|---|
| `peak_buffer_target` (arb target) | `partial_hold_reserve_floor` | target=30 floor=60 (**inversion**), target=80 floor=40, target=floor, target=1 floor=99 |
| `reserve_soc` (safety floor) | `partial_hold_reserve_floor` | reserve=20 floor=50, reserve=50 floor=20, reserve=floor |
| `arbitrage_charge_lead_time_min` | current TOU period | lead=0 at off_peak boundary, lead=MAX_LEAD at peak, lead crossing midnight |
| `arbitrage_grid_import_guard_kw` | live grid_import_kw | guard=0 (disabled semantic), guard << load, guard at exact load |

For each corner, state the expected `reserve_level` and `charge_from_grid` in a table BEFORE running the test. If the table can't be filled out from the spec, the spec is under-specified and Phase 0 needs another invariant.

Store the fabricated configs as pytest parametrize cases in `quality/tests/test_energy_battery_invariants.py` (create if it doesn't exist) or reuse `quality/tests/test_energy_battery_arbitrage.py` if the boundary maps onto existing fixtures. Grep for existing:

```bash
ls quality/tests/ | grep -iE "battery|arbitr|inclem|tou"
```

## Phase 4 — Mutation-anchored per-site test protocol (BLOCKING gate)

An aggregate monkeypatch of `_floor_reserve` proves the helper is load-bearing in aggregate. It does **not** prove each call site routes through it. You need one **failing** test per load-bearing site.

Protocol (do this yourself; no fleet required):

1. Pick a site from Phase 1a (e.g. `energy_battery.py:1617-1619` — WAIT floor).
2. Neuter *that one site* in the source: replace `floored = self._floor_reserve(...)` with `floored = self.reserve_soc` (or the raw pre-clamp value).
3. Run: `PYTHONPATH=quality python3 -m pytest quality/tests/ -v -k "battery or arbitr or inclem" 2>&1 | tail -60`.
4. **Expect ≥1 failure whose message names this site's semantics** (e.g. "WAIT should honor partial_hold floor"). A green suite here = untested site = fail this gate.
5. Restore the source. Move to the next site.
6. Repeat for every site in the Phase 1d list. Record the anchoring test name per site in a table in the planning doc.

Table shape:

| Site (file:line) | Neuter | Anchoring test | Status |
|---|---|---|---|
| energy_battery.py:1617 (WAIT) | `floored = self.reserve_soc` | `test_arbitrage_wait_honors_partial_hold_floor` | PASS-on-neuter (bad) / FAIL-on-neuter (good) |
| … | … | … | … |

If any row is PASS-on-neuter, either add a test or accept that the site is untested and open a follow-up cycle before ship.

## Phase 5 — Live validation gates with expected observations (BLOCKING gate)

After deploy + HA restart, the runbook is a decision tree, not a "look around." Each observation branches deterministically.

### 5.1 Prep

Live config lives on the Samba mount:

```bash
# Verify mount is fresh (per CLAUDE.md "Data Source Verification"):
ls -la /Users/ojiudezue/ha-config/.HA_VERSION 2>&1 | head -3
# If stale/missing, remount (copy verbatim from CLAUDE.md — do NOT retype from memory):
# mount_smbfs '//homeassistant:Verycool9277%40%5E@192.168.13.13/config' /Users/ojiudezue/ha-config
```

Live probes via MCP `home-assistant`:

```
ha_get_state entity_id=sensor.ura_battery_strategy
ha_get_history entity_id=sensor.ura_battery_strategy hours=1
ha_get_logs level=WARNING lines=200
```

**Fallback if MCP is down:** SSH to `homeassistant.local` (or `192.168.13.13`) → `ha state get sensor.ura_battery_strategy` (or read `.storage/core.restore_state` filtered by unique_id `universal_room_automation_battery_strategy`).

### 5.2 Decision tree

| Observation on `sensor.ura_battery_strategy` | Meaning | Action |
|---|---|---|
| `state` in {`self_consumption`, `backup`}; attrs include `arbitrage_phase`, `peak_buffer_target`, `target_day_class` | Coordinator online, emits well-formed status. | Continue to 5.3. |
| `state == "unknown"` for >2 ticks post-restart (ticks ≈60s) | `coordinator_manager` didn't publish `energy` yet OR `energy.battery_status` returned no mode. | Read logs; expect a URA WARNING within 5 min. If none → check `manager.py` setup order (Envoy boot incident pattern). |
| `attrs.arbitrage_phase == "n/a"` while in off_peak with arbitrage_enabled=True | Phase machine returned early (Phase-0 guard, no forecast). | Read `sensor.ura_energy_coordinator_next_high_rate_transition` and forecast entities; likely upstream forecast gap, not a battery bug. |
| `attrs.reserve_level < attrs.effective_reserve` while `attrs.hold_depth == "partial_hold"` | **I-1 broken live.** | Roll back immediately. This is the exact regression the campaign exists to prevent. Open a Tier-3 post-mortem. |
| `attrs.hold_depth == "partial_hold"` for >30 min with no inclement alert active | Inclement fusion latched. | Verify `sensor.ura_inclement_state` (or its equivalent) and NWS entity wiring (see MEMORY.md "v5.5.0 inclement shipped"). |
| `attrs.arbitrage_phase == "wait"` and reason ends `(partial_hold floor)` | Phase 2 fix live-observed. **This is the desired positive signal.** | Screenshot for the README write-back table. |

### 5.3 README write-back — MANDATORY

CLAUDE.md is explicit: the README's prospective "Live Validation" section MUST be replaced with a `Validated <date>` results table before the cycle closes. Include for each acceptance criterion:

- The exact entity_id + attribute name read.
- The observed value.
- PASS / FAIL / as-expected.
- Any boot-only transient dismissed, with justification.

Skip this and the cycle is not closed, even if the deploy succeeded.

## Phase 6 — Change control (Tier 3 by default)

Per CLAUDE.md, energy-strategy correctness work is regression-prone and cost-AND-safety-impacting. **Default tier: Tier 3 (four framing-disjoint reviews including adversarial-completeness pass D).** Do not "helpful-hotfix" a reserve emission.

### 6.1 Pre-review baseline tag

Standard `git tag pre-review-v<version>` per `ura-change-control` §Pre-Review Baseline (fact-home) — do this before any review-fix commits.

### 6.2 The four framings, executed solo

If a fleet is available, dispatch `ura-reviewer` four times in parallel with different framings. If not — you are it — run the four passes **sequentially in disjoint mental modes**, wiping context between them. A single mental pass wearing four hats converges on one blind spot.

| Pass | Framing | Concrete artifact required |
|---|---|---|
| A — local correctness | Arithmetic and clamp logic per site: does `_floor_reserve(existing, effective_reserve, hold_depth)` return the right value in each of the 3×N branches? | Truth table over `(hold_depth ∈ {allow_discharge, partial_hold, full_hold}) × (effective_reserve ∈ {None, <existing, ==existing, >existing})`. |
| B — state-machine integrity | No legitimate action suppressed; byte-identical on the `allow_discharge` path; restart-safe (attain latch, chunk_completed reset on TOU transition). | Trace one CHARGE from open-window → target-reached → HOLD → TOU transition → next-day; note every mutation of `_arbitrage_phase`, `_arbitrage_chunk_completed`, `_arbitrage_active`. |
| C — test authority via source mutation | Do the tests actually protect each site? | The Phase 4 site×test table, with a FAIL-on-neuter for every load-bearing site. |
| D — adversarial completeness | Falsify I-1 through I-5 across the **whole** file, not just the diff. Enumerate every path in `determine_mode`, every `_result` call, every `reserve_level=`. Produce a concrete legal-config repro for any leak. | A checklist of every reachable path with PASS/LEAK, plus the config that reproduces each LEAK. |

Pass D **must** re-run the Phase 1 greps against master before signing off, not against the diff. v5.5.3 D-HIGH-1 was a *pre-existing* 7th unclamped site that had lived in master unnoticed since v5.5.0.

### 6.3 Orchestrator independent verification — MANDATORY

Before deploy, the human orchestrator personally:

1. Re-runs Phase 1a and 1d greps and diffs against the counts stated in the planning doc.
2. Re-runs the Phase 4 mutation on the single most load-bearing site (usually the WAIT emit) and confirms `≥1 failed` in pytest.
3. Reads the last `_result` return in every branch of `determine_mode` and confirms it goes through the clamp for hold-eligible periods.

This is the gate v5.5.3 credits with catching a regex miss on a multi-line clamp. Do not skip it because reviewers said SHIP.

### 6.4 Operator checkpoint

Surface: (a) the falsifiable invariant list from Phase 0, (b) the completeness table from Pass D, (c) the mutation results from Phase 4, (d) the Phase 3 boundary matrix outcomes. Get explicit go before running `scripts/deploy.sh`.

### 6.5 Ship, then Phase 5 live validation, then README write-back

Standard `./scripts/deploy.sh <version> <summary> <notes>`. See sibling skill `deploy` for pipeline details — do not re-implement here.

## Fencing off wrong paths (archaeological hazards)

These are prior artifacts you WILL encounter while reading. Do not "clean them up" as part of an invariants cycle — they are load-bearing or intentionally frozen. Touch them only in their own dedicated cycle.

| Artifact | Where | Do not |
|---|---|---|
| Legacy Storm Guard | superseded by inclement fusion (v5.5.0) | Do not re-introduce Storm Guard code paths. |
| `arbitrage_soc_target` param name | `energy_battery.py:158, 214` — kept for migration ergonomics; canonical is `peak_buffer_target` | Do not rename in an invariants cycle. |
| Drain-target fallback | `energy_battery.py` around L2497, L3131 — "when arbitrage disabled" | Do not delete; verify it's unreachable under partial_hold. |
| Direct sensor-name assumption `ura_energy_coordinator_battery_strategy` | Older memos | The actual entity is `sensor.ura_battery_strategy`. Do not "fix" the entity — fix the memos. |
| Aggregate monkeypatch tests | `quality/tests/test_energy_battery_*` (any test that patches `_floor_reserve`) | Do not treat as sufficient. They pass Phase 4 vacuously. Add per-site mutation tests. |

## Provenance and maintenance

Every claim above should be re-verified per session — energy files change often. Run these first if resuming this campaign in a fresh context.

```bash
cd ~/Code/universal-room-automation

# Sensor entity name (should be sensor.ura_battery_strategy).
grep -n "battery_strategy" custom_components/universal_room_automation/sensor.py | head -5

# Line numbers of the reserve-floor clamp (drifts as file grows).
grep -n "_floor_reserve" custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# Reserve emission count (Phase 1a anchor).
grep -c "reserve_level=" custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# Bug Class #53 still present in QUALITY_CONTEXT.md?
grep -n "Bug Class #53" docs/QUALITY_CONTEXT.md

# Newest planning docs in the reserve/arbitrage/inclement family.
ls -t docs/planning/ | grep -iE "arbitr|inclem|reserve|energy_batt|attain" | head -10

# Newest review docs for the same surface.
ls -t docs/reviews/code-review/ | grep -iE "arbitr|inclem|reserve|freeze|attain|batt" | head -10
```

Date-stamped facts to sanity-check when they drift:
- **2026-07-02:** v5.7.2 shipped, arbitrage-WAIT floor closed in v5.5.3, `sensor.ura_battery_strategy` is the correct entity id.
- **2026-06-15:** inclement-weather hold (v5.5.0) LIVE but the NWS-alert wiring may still be dormant — verify at Phase 5.2 before believing a `partial_hold` observation.
- **Bug Classes in play:** #51 (day-boundary TOU), #53 (computed-but-not-consumed). Confirm neither has been renumbered.

If any command above returns unexpected output, STOP and update the skill before continuing the campaign. A wrong runbook is worse than no runbook.

## v5.28.0 addendum — blind-window guard + the §2.5a emergency-backout knob (2026-07-22)

The blind-window EVSE guard (INV-BW1) is part of the invariant surface as
of v5.28.0. BEFORE touching `is_reserve_verifiable`, the guard predicates,
or `CONF_RESERVE_VERIFIABLE_MAX_AGE_S`, READ **EC manual §2.5a**. Non-negotiables:
- `CONF_RESERVE_VERIFIABLE_MAX_AGE_S=0` is an EMERGENCY BACKOUT (fire axe),
  not a tuning value. At 0, full outages remain guarded; **partial outages
  (SOC blind, oracle readable) are knowingly exposed** — intentional,
  adjudicated, documented. Do not report it as a discovered bug; do not
  "fix" it by weakening gates (a)/(c).
- Guard-flapping-on-healthy-telemetry → the sanctioned response is the
  §2.5a backout sequence (0 → fix-forward → 600), never a cycle revert.
- The knob stays rung-1. Any semantic change = Tier 2-DB minimum with
  `quality/tests/test_blind_window_evse_guard.py` (incl. the 12-site
  enumeration contract + 15-mutation matrix) as the harness.
- Sibling with different semantics: `CONF_BLIND_WINDOW_MAX_DEFER_MIN <= 0`
  disables the WHOLE guard. Don't conflate the two kill-switches.
