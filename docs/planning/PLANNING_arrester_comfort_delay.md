# PLANNING — ARREST-COMFORT-1: Override-Arrester Occupant-Comfort DELAY

**Card:** `ARREST-COMFORT-1` (docs/planning/kanban.data.yaml:714)
**Sibling:** `HVAC-PRESET-FLAP-1` (independent defect from same trace) — this plan resolves the precedence seam with it, does not fix it.
**Sibling class:** `FAN-MANUAL-1` (thermostat side of "system overrules the human" — manual actuation is EVIDENCE, not drift).
**Status:** planning-only. No code changes in this cycle.
**Tier (proposed):** Tier 3 — see §7.

---

## 1. Falsifiable invariant (up-front, per Tier-3 discipline)

> **INV-COMFORT-DELAY.** In an occupied zone, when a manual thermostat change (a) is written by a non-immune context user, (b) moves the setpoint TOWARD comfort relative to current room temperature, and (c) has |delta| ≥ `COMFORT_DELTA_MIN_F`, the arrester MUST NOT emit a corrective `set_temperature` / `set_preset_mode` against that request within `COMFORT_GRACE_MIN` of the manual write, PROVIDED battery SOC ≥ `COMFORT_SOC_FLOOR_PCT`. Below the SOC floor, standard arrest timing applies unchanged. The `temp_arrester_override` switch, operator-immunity, freeze-floor, and duty-limiter-forced `away` on an unoccupied zone are all UNAFFECTED.

Falsification observations (any one falsifies):
- A qualifying manual write in an occupied zone reverted by the arrester in < `COMFORT_GRACE_MIN` while SOC ≥ floor.
- A **non-qualifying** manual write (unoccupied zone, or away-from-comfort direction, or |delta| < threshold) NOT arrested on the standard timing (regression of the arrester's core job).
- SOC = 60 % + qualifying manual: arrester silent (regression: comfort-grace should collapse to standard timing below floor).
- Concession step ladder never reverses to standard arrest after `COMFORT_TOTAL_MAX_MIN` (unbounded exemption bug).
- A concession granted while duty-limiter has forced `away` and SOC < floor (precedence violation).

The Review-D pass owns re-enumerating every arrester emission site against this invariant.

---

## 2. Institutional context verified

### 2.1 Prior planning docs / memory bodies consulted
- `docs/planning/kanban.data.yaml` cards `ARREST-COMFORT-1` (:714-755), `HVAC-PRESET-FLAP-1` (:622-713), `FAN-MANUAL-1` (:874-919, sibling class), `P1P3` (parent trace, :1963-1970).
- Memory: `feedback_marginal_benefit_pushback` (drives §5 decomposition), `feedback_suppression_needs_discharge` (drives the concession discharge / backstop design in §4), `feedback_measure_before_build` (drives §6 probe-first gate), `battery_soc_envoy_not_search-span` — reserved: Envoy SOC source, NOT SPAN.
- Design docs: `docs/Coordinator/HVAC.md` — reviewed for arrester + coast context (existing responsibilities table).
- Shipped precedent to LAYER inside (not replace): ARREST-SUNSET-1 (denylist `{arriving, guest, waking}`, MIN_LIFE grace, deferred discharge) — `hvac_override.py:520-600, 830-900`; OVERRIDE-NOTIFY-1 expiry warning — `hvac_override.py:1998-2053`.

### 2.2 Greps run + prior-art disposition

| Proposed | Grep target | Result | Disposition |
|---|---|---|---|
| Manual-change detector | `_handle_climate_change` / `is_override` | Exists — `hvac_override.py:1552-1638` (preset→`manual` OR direct temp change with suppression TTL, `kind` tag distinguishing induced from genuine) | **REUSE** — this cycle taps this exact detector's `is_override=True` branch; no second detector. |
| Suppression window | `SUPPRESS_TTL_SECONDS`, `self.suppress()` | Exists — `hvac_override.py:1442-1468` | **REUSE** — the concession grant issues a `set_temperature` and MUST call `self.suppress(entity_id, kind="temp")` so it does not self-arrest (same discipline as `_apply_compromise` at :1934). |
| Setpoint write chokepoint | `emit_set_temperature` | Exists — `hvac_setpoint.py::emit_set_temperature` (imported at `hvac_override.py:80`) | **REUSE** — concession-grant + step-down MUST route through it (freeze-floor / clamps stay honored). |
| Zone occupancy predicate | `zone_persons`, `any_room_occupied` | Exists — `CONF_ZONE_PERSONS` at `hvac_const.py:342`; zone.persons list populated in HVAC coordinator | **REUSE** — the predicate reads `bool(zone.persons)` on the zone the manual write targeted. |
| Battery SOC | `envoy_*_battery`, `self._battery.battery_soc` | Exists — Energy coordinator exposes `battery_soc` (energy.py multiple sites incl. :6840); memory pin confirms Envoy source, NOT SPAN. Cross-coord accessor already used by `_apply_compromise`-adjacent code paths. | **REUSE** via the existing HVAC → Energy accessor (`update_energy_state` already delivers `coast`/`offset` at :1437; a SOC read is added the same way — see §3.3). |
| Coast / duty limiter | `DUTY_CYCLE_COAST`, `runtime_exceeded` | Exists — `hvac_const.py:392-394`, `hvac.py:1445` (preset forced away), `hvac.py:2489-2510` (`_accumulate_zone_runtime`). | **PRECEDENCE SEAM** — resolved in §3.4, not modified. |
| `temp_arrester_override` switch | `_temp_arrester_override_active` | Exists — `hvac_override.py:1705-1711` (early return in `_handle_climate_change`) | **RESPECTED** — switch ON short-circuits BEFORE the new comfort-delay branch runs (bypass semantics preserved). See §4.3.a. |
| Operator-immune persons | `_immune_persons`, `_resolve_context_user_to_person` | Exists — `hvac_override.py:1658-1699` (detection-time stamp + return) | **RESPECTED** — immune-person branch runs BEFORE the comfort-delay branch. Kids' user_ids are non-immune → they fall through to the new branch (this is the desired path). |
| Freeze floor | `freeze_active` | Exists — `hvac.py:467-475` | **RESPECTED** — `emit_set_temperature` already applies floor; concession/step writes route through it. |
| Denylist (ARREST-SUNSET) | `ARRESTER_HOLD_PRESERVING_STATES` | Exists — used at `hvac_override.py:513-534` | **INTERACTION** — a concession is NOT an operator hold; it does not seed a denylist entry. See §4.5. |

**All proposed new symbols are namespaced `COMFORT_*` to avoid collision with the existing `OVERRIDE_*` family** (`hvac_const.py:397-401`). New constants list: §4.6.

### 2.3 Code locations surveyed end-to-end
- `hvac_override.py` :1420-1900 (suppress/unsuppress, `_handle_climate_change`, severe/normal branches, `_apply_compromise`).
- `hvac_override.py` :94-310, :510-900, :1000-1440 (init, sunset/denylist/MIN_LIFE machinery, temp_arrester_override state).
- `hvac.py` :400-580 (HVAC coordinator init, boot settle, energy state accessors); :1420-1460 (duty-cycle forced `away`); :2489-2510 (runtime accumulator).
- `hvac_const.py` :342, :392-401 (CONF_ZONE_PERSONS, duty-cycle knobs, OVERRIDE thresholds).

---

## 3. Design shape

### 3.1 Recommended shape: **STAGED**, not full-on-first-ship.

Per marginal-benefit decomposition (§5), the plan ships in two build cycles:

- **Cycle A (this plan's D1-D3):** the DELAY spine — identification predicate + flat comfort grace + SOC-floor collapse to standard timing. This captures the kids-incident recovery in full: had `COMFORT_GRACE_MIN=30` + SOC=94 % existed on 2026-08-09, both 16:49 and 17:14 requests would have been honored past the point the kids would have felt cold air (target set 76 from 80 F, ~4-6 min to first perceptible delta on the operator's system per HVAC-PRESET-FLAP-1 evidence).
- **Cycle B (this plan's D4, gated on Cycle A live-validation + measured evidence):** the GRADUATED CONCESSION — step ladder with approach-speed monitoring. Parked (per marginal-benefit rule) with the evidence trigger: "if operator observes a run of comfort-grace expiries that revert-then-flip within a further hour, revisit graduated concession."

Rationale: cycles A and B are independently valuable AND separately reviewable. A's ingredient risk is bounded (one branch inside an existing detector). B introduces a small state machine (step scheduler + approach-speed observer) plus a new discharge on the concession — categorically higher risk per `feedback_suppression_needs_discharge`.

### 3.2 Identification predicate (D1) — FORMALIZED

Evaluated inside `_handle_climate_change` after `is_override=True` and after the existing operator-immune / temp_arrester_override early returns (so the switch and immunity retain their bypass semantics), BEFORE `_handle_severe_override` / `_handle_normal_override`:

```
comfort_request(entity, event) :=
    (a) genuine manual (not URA-induced) — the existing suppression-TTL + kind="temp"
        filter at hvac_override.py:1562-1611 has already decided this; we consume
        its `is_override` verdict, we do NOT re-derive manual-ness.
    ∧ (b) context user is not in _immune_persons (already filtered by :1663-1699).
    ∧ (c) zone.persons is non-empty at the instant of the state-change event
          (zone_persons read from the HVAC coordinator's per-zone cache — same
          source that gates preset selection).
    ∧ (d) direction is TOWARD comfort relative to CURRENT room temp:
              current_temp = new_state.attributes.get("current_temperature")
              cool_move: new_high < old_high AND current_temp > new_high
              heat_move: new_low  > old_low  AND current_temp < new_low
          i.e. the user is asking for cooling in a room that is warmer than
          the requested cool setpoint (or heating in a cooler room). A user
          nudging cool setpoint DOWN in an already-cold room is NOT a comfort
          request (leave to standard arrest — likely a mis-tap).
    ∧ (e) |delta| ≥ COMFORT_DELTA_MIN_F on the moved leg.
    ∧ (f) current_temp is a live numeric value (not None / not "unavailable"
          / not stale beyond COMFORT_TEMP_MAX_AGE_S). If unknown → NOT a
          comfort request (fail closed).
```

Where the source of `zone.persons`: the HVAC coordinator already resolves this per-zone (used in preset selection); the OverrideArrester obtains it via the already-injected `zone` object from `_find_zone_by_entity`. (No new signal wire.)

### 3.3 Battery-conditioned grace (D2)

`COMFORT_SOC_FLOOR_PCT = 80` (default; entity-knob per §4.6). Two-branch collapse:

- `soc ≥ COMFORT_SOC_FLOOR_PCT` AND `not blind` → apply `COMFORT_GRACE_MIN` grace (delay).
- `soc < floor` OR SOC unknown (Envoy blind) → **fall through to existing** `_handle_severe_override` / `_handle_normal_override` with ZERO behavior change. This is the fail-closed direction (a blind Envoy must NOT silently exempt comfort — the SOC gate is the operator's cost/safety anchor).

SOC accessor: HVAC coordinator gets a new one-liner passthrough `battery_soc: float | None` populated the same way `update_energy_state(offset, coast)` populates coast (energy coordinator pushes; HVAC coord reads; arrester reads from HVAC coord). No new cross-coordinator signal fabric.

The `blind_hold_active` state (energy.py :3574-3610) is authoritative on "SOC read is not trustworthy right now"; if blind → treat as below-floor.

### 3.4 Coast / duty-limiter precedence rule (the HVAC-PRESET-FLAP-1 seam)

The duty limiter (hvac.py:2489-2510 accumulator, :1445 forced-away emit) and the comfort-delay branch write to the same effective preset for the same zone. They must not disagree per tick.

**Rule** (operator-derived: "battery-conditioned rule is the resolution"):

- `SOC ≥ COMFORT_SOC_FLOOR_PCT`: **comfort-delay wins.** During the comfort-grace window on a qualifying request, `runtime_exceeded` does NOT force `away`; the accumulator keeps counting but the preset write is deferred to grace-expiry. On grace-expiry the coast machinery's current verdict resumes (may immediately force away — but the occupant will have felt the concession by then, and the window's expiry is the correct handoff moment).
- `SOC < floor`: **duty-limiter wins.** Coast/shed continues to force away on `runtime_exceeded`; the comfort-delay branch does not engage.

Enforcement site: a single guard in the coast forced-away path (`hvac.py:1445`) that consults `arrester.comfort_delay_active(zone_id)` before writing `away` when SOC ≥ floor. This is ONE additional read on the existing precedence ladder; the reason-ladder label at `hvac.py:1577` gains a new leaf `comfort_delay_active` so the reason ledger shows exactly why the limiter yielded.

**No change** to the duty-limiter thresholds, window, or accumulator; **no change** to sleep exemption; **no change** to normal-mode `else: continue` (no cap).

### 3.5 Graduated concession (D4, DEFERRED — Cycle B)

Sketch only, for scope closure:

```
state ← IDLE
on comfort_request(zone, delta_f):
    if state != IDLE for zone: cancel step-scheduler; state ← IDLE
    granted_setpoint ← requested_setpoint
    emit_set_temperature(granted_setpoint) via self.suppress(entity, kind="temp")
    state ← GRANTED; approach_speed ← observed °F/min over first CONCESSION_OBSERVE_S
    schedule step_1 at t + COMFORT_STEP_INTERVAL_MIN (default 15)

on step_i fire (state == GRANTED):
    if grace_reason_now_invalidated (unoccupied, or SOC < floor):
        state ← IDLE; no write (arrester's normal path resumes on any new event)
        return
    stepped_setpoint ← granted_setpoint + COMFORT_STEP_SIZE_F * i (toward original)
    if approach_speed < COMFORT_SLOW_APPROACH_F_PER_MIN:
        # unrecoverable load — the concession is not being converted to comfort.
        # DELAY the next step (multiply next interval by COMFORT_SLOW_STEP_STRETCH).
    emit_set_temperature(stepped_setpoint) via self.suppress(entity, kind="temp")
    if stepped_setpoint reached original: state ← IDLE
    else: schedule step_{i+1}

backstop: state → IDLE unconditionally at t0 + COMFORT_TOTAL_MAX_MIN
    (prevents unbounded exemption if step scheduler wedges).
restart: state is RAM-only; on HA restart, IDLE. This is DELIBERATE — a
    concession that outlived a restart cannot be trusted, and the room
    will re-emit a manual if the occupant is still uncomfortable.
```

Every scheduled step is a `set_temperature` write — MUST go through `emit_set_temperature` + `self.suppress(entity, kind="temp")` (proven-safe pattern from `_apply_compromise` at :1934).

### 3.6 Sunset / MIN_LIFE / temp_arrester_override interactions

- `temp_arrester_override` ON (switch): existing early-return at :1705-1711 fires FIRST → the entire comfort-delay branch is bypassed. The switch is a hard "arrester does nothing" mode; comfort-delay is a "arrester waits" mode; the switch dominates by construction. **Verified**: no code path in the new branch is reachable when `_temp_arrester_override_active`.
- ARREST-SUNSET-1 denylist / MIN_LIFE: those apply to operator-immune holds. A comfort-delay is NOT an operator hold — it does not stamp `_immune_hold_records`, it does not write to `_temp_arrester_override_pending_sunset`, it does not consult `ARRESTER_HOLD_PRESERVING_STATES`. A house-state transition during a comfort-grace does NOT sunset the grace (kids' comfort request does not care that `home_evening → home_night` crossed). The grace has ONE exit: timer expiry OR predicate invalidation (SOC drops below floor, zone becomes unoccupied).
- OVERRIDE-NOTIFY-1: no pre-warn NM alert for comfort-grace (it is short by construction — default 30 min max, no scheduled sunset). If Cycle B's step ladder ships, the same principle: no pre-warn.

---

## 4. Deliverables

### D1 — Identification predicate & branch insertion (Cycle A)
Insert `comfort_request(...)` per §3.2 in `_handle_climate_change` AFTER the temp_arrester_override / operator-immune early returns (:1699-1711) and BEFORE the severity dispatch (:1755-1770).
- **Files:** `hvac_override.py` (branch), `hvac_const.py` (`COMFORT_*` constants).
- **New symbols (see §4.6).**
- **Ledger row:** on qualifying request, log `comfort_delay_started` with `{zone_id, delta_f, direction, current_temp, soc, requested_setpoint, grace_s}`; on expiry, `comfort_delay_expired` with `{zone_id, elapsed_s, expiry_reason: timer|predicate_invalidated|soc_below_floor|zone_unoccupied}`.

**Acceptance Criteria**
- **Verify:** unit test — cool manual in occupied zone with current_temp > new_high, |delta|=4, SOC=94 → comfort_delay_started; no revert timer scheduled inside COMFORT_GRACE_MIN.
- **Verify:** unit test — same call with SOC=60 → predicate false → severe/normal branch fires as pre-cycle.
- **Verify:** unit test — same call with zone.persons=[] → predicate false → standard arrest.
- **Verify:** unit test — cool nudge DOWN in already-cold room (current_temp < new_high, cool-away-from-comfort) → predicate false.
- **Verify:** unit test — current_temp None → predicate false (fail closed).
- **Sensor:** existing `sensor.hvac_reason_ledger` shows a `comfort_delay_started` row (add label to enum).
- **Test:** `test_arrester_comfort_delay_predicate.py::{qualifies_cool,qualifies_heat,rejects_unoccupied,rejects_soc_below_floor,rejects_wrong_direction,rejects_temp_unknown,rejects_immune_user,rejects_switch_on}`.
- **Live:** replay-fixture test — 2026-08-09 16:49/17:14 zone_2 events (setpoint 76 from 80, current_temp ≈ 80, SOC ≈ 94, zone.persons=[ziri,jaya]) MUST both produce `comfort_delay_started` and NO `_handle_severe_override` / `_handle_normal_override` call. This is the kids-incident replay assertion.

### D2 — Battery-conditioned grace + SOC accessor plumbing (Cycle A)
Add `battery_soc: float | None` to the HVAC coordinator via the existing energy-push channel (mirror `update_energy_state` shape). Arrester reads through the coordinator handle it already holds. Add `blind` flag passthrough.

**Acceptance Criteria**
- **Verify:** SOC transition 82 → 78 while a comfort-delay is in flight → grace collapses (predicate re-evaluated on the next arrester event; existing severity path takes over on the NEXT manual write). No mid-grace forced-revert (documented behavior — the delay grants THIS request; SOC drop affects the NEXT one).
- **Verify:** Envoy blind (`blind_hold_active=True`) → predicate treats as SOC < floor.
- **Test:** `test_arrester_comfort_soc_gate.py`.
- **Live:** attribute check on `sensor.hvac_reason_ledger` last comfort row includes `soc` field; observed within one operator-issued manual request.

### D3 — Coast / duty-limiter precedence guard (Cycle A)
Guard the forced-away write at `hvac.py:1445` on `arrester.comfort_delay_active(zone_id) is False` when SOC ≥ floor. Extend reason ladder at `hvac.py:1577` with `comfort_delay_active` leaf.

**Acceptance Criteria**
- **Verify:** synthetic test — zone in coast, `runtime_exceeded=True`, SOC=90, comfort_delay_active=True → NO forced-away write; reason ledger row `comfort_delay_active`.
- **Verify:** same but SOC=60 → forced-away write proceeds; ledger row `runtime_exceeded`.
- **Verify:** grace expires while `runtime_exceeded` still True → forced-away emits on the very next accumulator tick (no lost enforcement).
- **Test:** `test_hvac_coast_comfort_precedence.py` — the four-corner truth table (SOC × runtime_exceeded × occupied × comfort_delay_active).
- **Live:** during a run where SOC ≥ 80 and coast trips inside a comfort-delay window, ledger shows `comfort_delay_active` reason and preset does NOT flip away.

### D4 — Graduated concession + approach-speed (Cycle B; DEFERRED, evidence-gated)
Not built in this cycle. §3.5 sketch is the design; the trigger to un-defer is documented in §5.

### D5 — Kids-incident replay fixture (support, Cycle A)
Codify a golden fixture of the 2026-08-09 zone_2 events as the acceptance replay for D1. Fixture assertions detailed in D1 "Live" criterion.

**Non-goals (explicit)**
- No fan work — FAN-MANUAL-1 / FAN-LAYER-1 own that.
- No duty-limiter redesign — only the precedence seam is modified.
- No changes to ARREST-SUNSET-1 machinery — comfort-delay does NOT use denylist / MIN_LIFE / pending-sunset.
- No changes to freeze floor, operator-immunity, or `temp_arrester_override` switch.
- No behavior change when SOC is below floor (invariant explicitly requires standard timing there).
- No mid-grace forced-revert on SOC drop (documented — see D2 verify).

### 4.6 New constants (all named knobs, rung stated per "Numbers Get Knobs")

| Constant | Default | Rung | Rationale |
|---|---|---|---|
| `COMFORT_GRACE_MIN` | 30 min | **Entity-knob** (Number, persisted) | Operator-tuned — the ceiling on "wait to revert" is a comfort/cost tradeoff the operator legitimately turns by observation. Kill-switch semantic: `0` = feature disabled (falls through to standard arrest for every request). |
| `COMFORT_SOC_FLOOR_PCT` | 80 | **Entity-knob** (Number, persisted) | Operator-tuned — the "battery genuinely spare" line. Ties to the same 80 % anchor the operator articulated. |
| `COMFORT_DELTA_MIN_F` | 2.0 °F | **Module constant** (`hvac_const.py`) | Predicate threshold — a change would silently shift what counts as a "comfort request". Review-gated. |
| `COMFORT_TEMP_MAX_AGE_S` | 900 s | **Module constant** | Staleness bound on `current_temperature`. Review-gated. |
| `COMFORT_TOTAL_MAX_MIN` | 60 min | **Module constant** | Absolute backstop on any concession chain (Cycle B); also caps the total time a single manual can defer arrest end-to-end. Review-gated. |
| *(Cycle B)* `COMFORT_STEP_SIZE_F` | 1.0 °F | Module constant | Step size — safety-adjacent. |
| *(Cycle B)* `COMFORT_STEP_INTERVAL_MIN` | 15 min | Entity-knob | Operator observes pace. |
| *(Cycle B)* `COMFORT_SLOW_APPROACH_F_PER_MIN` | 0.15 °F/min | Module constant | Fitted threshold on unrecoverable load. |
| *(Cycle B)* `COMFORT_SLOW_STEP_STRETCH` | 2.0× | Module constant | Interval multiplier when approach is slow. |
| *(Cycle B)* `CONCESSION_OBSERVE_S` | 300 s | Module constant | Window for approach-speed sampling. |

Kill-switch: `COMFORT_GRACE_MIN=0` fully disables the branch — verified by a dedicated unit test.

---

## 5. Marginal-benefit decomposition (per `feedback_marginal_benefit_pushback`)

| Version | What it captures (benefit) | Ingredients (risk) |
|---|---|---|
| **Simplest — flat delay, no SOC gate, no concession** | Kids incident is 100 % addressed at every SOC. | Removes battery/cost anchor — a comfort-grace on a low-SOC evening could cost real money and undo the duty limiter's job. Fails INV precondition (b). |
| **Cycle A — flat delay + SOC gate** *(recommended)* | Kids incident recovered when SOC ≥ 80 (the actual conditions the night it happened: SOC 94, solar_class excellent). Duty-limiter continues to protect the battery when it matters. **~95 % of the observed benefit** at bounded ingredient risk. | New branch in existing detector, one new cross-coord accessor (SOC push), one new precedence guard at a known site. All within the existing arrester surface. |
| **Cycle B — + graduated concession + approach-speed** | Marginal: smoother comfort ramp; slow-approach detection auto-tunes to unrecoverable-load nights. | New state machine (step scheduler + observer), new discharge on each step, RAM-only state that must survive → not survive restart, one additional emission site per zone. Categorically higher — a rare-fire code path (concessions during long grace windows are the exact "hard to observe organically" class flagged by memory). |

**Recommendation:** ship Cycle A now. Park Cycle B with the evidence trigger: "operator observes a run of ≥3 comfort-grace expiries within one evening where the room immediately re-flipped to a manual within an hour of expiry." Until that evidence appears, Cycle B is an elaborate spec that pays single-digit marginal comfort dollars for a categorically riskier ingredient set.

Pushback rationale: the operator captured Cycle B as design intent, not as a shipping requirement. Cycle A alone falsifies the kids-incident replay. Cycle B's added ingredient (a state machine on an event-driven surface) is exactly the class of change `feedback_suppression_needs_discharge` flags. Staging is cheap; combined shipping is not.

---

## 6. Measure-before-build gate (per `feedback_measure_before_build`)

**Probe P1 (10-min recorder read, before build starts):** enumerate the last 30 days of arrester revert events with `{zone_id, ts, delta, was_zone_occupied, soc_at_event, direction, temp_at_event}` from the ledger + recorder. Answer:
1. Rate of qualifying-under-INV events per week (how often would D1 have engaged?).
2. Of those, distribution of SOC (would D2 have collapsed how many?).
3. Any coast events during qualifying windows (D3 co-fire rate — the four-corner truth table's density in the wild).
4. Any night where multiple qualifying events within an hour would have exercised the concession ladder (the Cycle-B evidence trigger — is it already met?).

**Go/no-go rule:**
- If P1 shows zero qualifying events in 30 days → the kids incident is the sole trigger; consider a much narrower fix (per-user manual-hold seed for the kids' Person entities) and defer this cycle entirely.
- If P1 shows Cycle-B trigger already met → escalate scope to include Cycle B in this cycle (still framing-disjoint reviewed, but no separate ship).

Probe deliverable: `docs/planning/AUDIT_arrester_comfort_delay.md` with the frequency + SOC/direction/coast joint distribution.

---

## 7. Tier argument

**Proposed: Tier 3 (four framing-disjoint reviews).**

Triggers hit:
- **Cost-AND-safety-impacting:** the SOC-floor rule spends stored energy on comfort — mis-implementation costs money (peak import) or comfort (spurious arrest survives when it shouldn't). Both sides of the fence.
- **Threads a value through a state machine consumed by multiple emission sites:** SOC ≥ floor gates BOTH the arrester branch (D1/D2) AND the coast forced-away guard (D3). Two consumers of the same predicate — Bug Class #53 (computed-but-not-consumed) surface.
- **History of multi-fix-up cycles in the area:** ARREST-SUNSET-1 required deferred discharge + MIN_LIFE grace + expiry notify across multiple cycles (v5.61-62 + OVERRIDE-NOTIFY-1). The arrester surface has a proven track record of subtle seam leaks.
- **Cross-coordinator ripple:** presence (`zone.persons`) ↔ energy (`battery_soc`, `blind`) ↔ HVAC (arrester + duty limiter) ↔ safety (freeze floor, immunity). Standing policy per CLAUDE.md defaults regression-prone work to Tier 2-DB minimum; the state-machine + cost/safety pair pushes to Tier 3.

**Four framings:**
- **A — local correctness:** predicate branch arithmetic (direction detection, delta sign, current_temp staleness); constant handling; kill-switch behavior.
- **B — integration / state-machine integrity:** the D1↔D3 gate is one predicate consumed by two sites — verify both consult the same source, no drift; restart behavior; interaction with the shipped ARREST-SUNSET-1 / OVERRIDE-NOTIFY-1 / operator-immune / temp_arrester_override paths (each verified byte-identical on their existing test replays).
- **C — test authority via real per-site source mutation:** neuter the D1 branch → the kids-incident replay MUST fail. Neuter the D3 guard → the coast four-corner test MUST fail. Neuter the SOC gate → the SOC=60 test MUST fail. Each site whose bypass leaves the suite green is an untested site (unacceptable). Global monkeypatch of `battery_soc` accessor is NOT sufficient — each read site is individually mutation-anchored.
- **D — adversarial completeness / diff-blind:** re-enumerate every arrester emission site AND every coast/duty-limiter forced-write site AND every SOC read against INV-COMFORT-DELAY. Every flagged leak must carry a legal-config repro (SOC=80.0 exactly? Zone becoming unoccupied between predicate-eval and grace-expiry? Envoy going blind mid-grace? A manual write during a MIN_LIFE-grace pending sunset from an operator hold? A concession that would exceed COMFORT_TOTAL_MAX_MIN?). D's job includes checking whether Cycle A introduces a regression in the ARREST-SUNSET machinery it deliberately does NOT touch.

Orchestrator pre-ship duty: personally re-grep every `set_temperature` / `set_preset_mode` write in `hvac_override.py` and `hvac.py`, and re-run a real source mutation on the D3 guard and the SOC-gate branch. Do not trust reviewer summaries.

Operator checkpoint BEFORE deploy is mandatory per Tier-3 protocol.

---

## 8. Sharpest risk

**The D1↔D3 predicate becomes desynchronized.** Two consumers of `SOC ≥ floor` in two coordinators. If Cycle A ships with D1 reading SOC through the pushed accessor and D3 reading it through a direct energy-coord accessor (or vice versa), a moment of divergence (blind Envoy, LKG, boot transient) will produce the observable failure mode: **arrester grants comfort-delay in D1, coast limiter forces `away` anyway in D3 because it saw SOC < floor for that tick** — the occupant sees a "granted then snatched" that is worse than either pure behavior. This is the exact class of bug the sibling HVAC-PRESET-FLAP-1 already exemplifies, replayed at a new seam.

Mitigation (build-time): single SOC accessor on the HVAC coordinator (`coord.battery_soc`, `coord.battery_blind`), consumed by BOTH sites. No direct-to-energy reads from D1 or D3. Verified by Review C source-mutation on the accessor (both tests must fail on the SAME mutation).

Secondary risk: the concession ladder in Cycle B, if merged prematurely, creates a rare-fire discharge surface with restart-inert state. Deferring Cycle B by construction eliminates this until the evidence trigger fires.

---

## 9. Report (executive summary requested by parent)

- **Recommended shape:** STAGED — Cycle A (identification predicate + flat comfort grace + SOC-floor gate + coast precedence guard) now; Cycle B (graduated concession + approach-speed) parked with an evidence trigger. §3.1, §5.
- **Identification predicate (formalized):** genuine manual (via existing suppression-TTL filter) ∧ non-immune user ∧ `zone.persons` non-empty ∧ direction toward comfort relative to `current_temperature` ∧ |delta| ≥ `COMFORT_DELTA_MIN_F` ∧ `current_temperature` fresh. §3.2.
- **Concession state-machine sketch:** provided for Cycle B (IDLE → GRANTED → step_i → IDLE, with predicate-invalidation exit, approach-speed-driven interval stretch, absolute `COMFORT_TOTAL_MAX_MIN` backstop, RAM-only state deliberately not restart-persistent, every emit via `suppress(kind="temp")` + `emit_set_temperature`). §3.5.
- **Coast/duty-limiter precedence rule:** `SOC ≥ COMFORT_SOC_FLOOR_PCT` → comfort-delay wins (coast defers forced-away); `SOC < floor` → limiter wins unchanged. Single guard at `hvac.py:1445`, reason-ladder leaf `comfort_delay_active`. §3.4.
- **Invariant:** INV-COMFORT-DELAY stated falsifiably up-front. §1.
- **Tier:** Tier 3 (SOC-floor threaded through two coordinators + cost/safety pair + arrester surface's leak history). §7.
- **Sharpest risk:** D1↔D3 SOC-predicate desynchronization producing "granted then snatched." Mitigation: single HVAC-coordinator accessor consumed by both sites, mutation-anchored in Review C. §8.
