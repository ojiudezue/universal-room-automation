# PLANNING — ARREST-COMFORT-1: Override-Arrester Occupant-Comfort DELAY

**Card:** `ARREST-COMFORT-1` (docs/planning/kanban.data.yaml:714)
**Sibling:** `HVAC-PRESET-FLAP-1` (independent defect from same trace) — this plan resolves the precedence seam with it, does not fix it.
**Sibling class:** `FAN-MANUAL-1` (thermostat side of "system overrules the human" — manual actuation is EVIDENCE, not drift).
**Status:** planning-only. No code changes in this cycle.
**Tier (proposed):** Tier 3 — see §7.
**Revision:** rev-2 (2026-08-10) — folds two Tier-3 plan reviews (both PLAN-NEEDS-REVISION). Review record §10.

---

## 1. Falsifiable invariant (up-front, per Tier-3 discipline)

> **INV-COMFORT-DELAY.** In an occupied zone, when a manual thermostat change (a) is written by a non-immune context user, (b) moves the setpoint on the *comfort-relevant leg* TOWARD comfort relative to `current_temperature`, and (c) has |delta| ≥ `COMFORT_DELTA_MIN_F`, the arrester MUST NOT emit a corrective `set_temperature` OR `set_preset_mode` against that request within `COMFORT_GRACE_MIN` of the manual write, PROVIDED battery SOC ≥ `COMFORT_SOC_FLOOR_PCT` at the instant of grant AND no load-shedding hold is active. Below the SOC floor at grant, or with a shed active, standard arrest timing applies unchanged. The `temp_arrester_override` switch, operator-immunity, freeze-floor, and duty-limiter-forced `away` on an unoccupied zone are all UNAFFECTED.

Falsification observations (any one falsifies):
1. A qualifying manual write in an occupied zone reverted by the arrester (via ANY of the enumerated write sites in §3.7) in < `COMFORT_GRACE_MIN` while SOC ≥ floor at grant.
2. A **non-qualifying** manual write (unoccupied zone, or away-from-comfort direction on the relevant leg, or |delta| < threshold) NOT arrested on the standard timing (regression of the arrester's core job).
3. SOC = 60 % at grant + qualifying manual: arrester silent (regression: comfort-grace should collapse to standard timing below floor).
4. **(Cycle-B only)** Concession step ladder never reverses to standard arrest after `COMFORT_TOTAL_MAX_MIN` (unbounded exemption bug). Cycle A carries no step ladder; this observation is inert until Cycle B ships.
5. A comfort-delay grant issued while duty-limiter has forced `away` and SOC < floor (precedence violation).
6. Load-shedding hold active AND a comfort-delay grant issued (shed-precedence violation, added rev-2 per Review-1 H3).

The Review-D pass owns re-enumerating every arrester emission site (per §3.7) AND every coast/duty-limiter forced-write site AND every SOC read against INV-COMFORT-DELAY.

---

## 2. Institutional context verified

### 2.1 Prior planning docs / memory bodies consulted
- `docs/planning/kanban.data.yaml` cards `ARREST-COMFORT-1` (:714-755), `HVAC-PRESET-FLAP-1` (:622-713), `FAN-MANUAL-1` (:874-919, sibling class), `P1P3` (parent trace, :1963-1970).
- Memory: `feedback_marginal_benefit_pushback` (drives §5 decomposition), `feedback_suppression_needs_discharge` (drives the concession discharge / backstop design in §4), `feedback_measure_before_build` (drives §6 probe-first gate), `battery_soc_envoy_not_span` — Envoy SOC source, NOT SPAN.
- Design docs: `docs/Coordinator/HVAC.md` — reviewed for arrester + coast context (existing responsibilities table).
- Shipped precedent to LAYER inside (not replace): ARREST-SUNSET-1 (denylist `{arriving, guest, waking}`, MIN_LIFE grace, deferred discharge) — `hvac_override.py:520-600, 830-900`; OVERRIDE-NOTIFY-1 expiry warning — `hvac_override.py:1998-2053`.

### 2.2 Greps run + prior-art disposition

| Proposed | Grep target | Result | Disposition |
|---|---|---|---|
| Manual-change detector | `_handle_climate_change` / `is_override` | Exists — `hvac_override.py:1552-1638` (preset→`manual` OR direct temp change with suppression TTL, `kind` tag distinguishing induced from genuine) | **REUSE + EXTRACT** — new symbol `_is_genuine_manual(event, entity_id) -> bool` extracted from :1562-1611 as the single testable predicate. Consumed by the comfort-delay branch (§3.2) and by future callers. See L1 in §10. |
| Suppression window | `SUPPRESS_TTL_SECONDS`, `self.suppress()` | Exists — `hvac_override.py:1442-1468` | **REUSE** — the concession grant issues a `set_temperature` and MUST call `self.suppress(entity_id, kind="temp")` so it does not self-arrest. |
| Setpoint write chokepoint | `emit_set_temperature` | Exists — `hvac_setpoint.py::emit_set_temperature` (imported at `hvac_override.py:80` and `hvac.py:58`) | **REUSE** — concession-grant + step-down MUST route through it (freeze-floor / clamps stay honored). |
| Preset write chokepoint | `set_preset_mode` service call | **DOES NOT EXIST** — three inline `hass.services.async_call("climate", "set_preset_mode", …)` sites (`hvac.py:1626`, `hvac_override.py:2034`, `hvac_override.py:2711`) | **NEW** — introduce `emit_set_preset_mode(hass, zone, preset, reason, *, gate)` in `hvac_setpoint.py`, mirror of `emit_set_temperature`. All 3 sites migrated. Gate consults `arrester.comfort_delay_active(zone_id)`. Per-site verdict table in §3.7. This is the H1-review chokepoint. |
| Zone occupancy predicate | `zone_persons`, `any_room_occupied` | Exists — `CONF_ZONE_PERSONS` at `hvac_const.py:342`; zone.persons list populated in HVAC coordinator | **REUSE** — the predicate reads `bool(zone.persons)` on the zone the manual write targeted. |
| Battery SOC | `envoy_*_battery`, `self._battery.battery_soc` | Exists — Energy coordinator exposes `battery_soc`; memory pin confirms Envoy source, NOT SPAN. | **REUSE via single HVAC-coord accessor** — `HVACCoordinator.battery_soc` + `HVACCoordinator.battery_blind` populated by the existing energy-push channel. BOTH D1 and D3 read from this SAME accessor (Sharpest Risk mitigation, §8). |
| Coast / duty limiter | `DUTY_CYCLE_COAST`, `runtime_exceeded` | Exists — `hvac_const.py:392-394`, `hvac.py:1445` (preset forced away), `hvac.py:2489-2510` (`_accumulate_zone_runtime`). | **PRECEDENCE SEAM** — resolved in §3.4. |
| `temp_arrester_override` switch | `_temp_arrester_override_active` | Exists — `hvac_override.py:1705-1711` (early return in `_handle_climate_change`) | **RESPECTED** — switch ON short-circuits BEFORE the new comfort-delay branch runs. Flipped ON mid-grace: grace immediately becomes inactive (§3.6). |
| Operator-immune persons | `_immune_persons`, `_resolve_context_user_to_person` | Exists — `hvac_override.py:1658-1699` (detection-time stamp + return) | **RESPECTED** — immune-person branch runs BEFORE the comfort-delay branch. Kids' user_ids are non-immune. |
| Freeze floor | `freeze_active` | Exists — `hvac.py:467-475` | **RESPECTED** — `emit_set_temperature` already applies floor; concession/step writes route through it. |
| Denylist (ARREST-SUNSET) | `ARRESTER_HOLD_PRESERVING_STATES` | Exists — used at `hvac_override.py:513-534` | **INERT** — a comfort-delay is NOT an operator hold; no denylist entry seeded. See §3.6 + M2 in §10. |
| Load-shedding hold | `shed_active`, `_load_shed_hold` | Exists — energy coordinator exposes shed state | **PRECEDENCE** — shed-active suppresses new comfort-delay grants (rev-2, H3). A shed activating mid-grace does NOT snap back — the existing grace runs to timer expiry (documented). |
| Forecaster partial / degraded | `forecast_available`, `_forecast_state` | Exists | **NO INTERACTION** — forecast freshness does not gate the predicate. SOC is measured, not forecast. |
| EV drain-precedence queue | `evse_drain`, `EV_DRAIN` | Exists (separate coordinator) | **NO INTERACTION** — orthogonal coordinator; thermostat vs EVSE. |

**All proposed new symbols are namespaced `COMFORT_*` to avoid collision with the existing `OVERRIDE_*` family** (`hvac_const.py:397-401`). New constants list: §4.6.

### 2.3 Code locations surveyed end-to-end
- `hvac_override.py` :1420-1900 (suppress/unsuppress, `_handle_climate_change`, severe/normal branches, `_apply_compromise`).
- `hvac_override.py` :94-310, :510-900, :1000-1440 (init, sunset/denylist/MIN_LIFE machinery, temp_arrester_override state).
- `hvac_override.py` :1930-2050, :2570-2720, :3220-3240, :3490-3510 (all setpoint / preset write sites — §3.7 catalog).
- `hvac.py` :400-580 (init, energy accessors); :1420-1460 (duty-cycle forced `away`); :1550-1700 (preset-write reason ladder at :1600-1636); :1870-1920 (guest-actuation `emit_set_temperature` at :1896); :2489-2510 (runtime accumulator).
- `hvac_const.py` :342, :392-401 (CONF_ZONE_PERSONS, duty-cycle knobs, OVERRIDE thresholds).
- `hvac_setpoint.py` (`emit_set_temperature` + guards) — where the new `emit_set_preset_mode` chokepoint lands.

---

## 3. Design shape

### 3.1 Recommended shape: **STAGED**, not full-on-first-ship.

Per marginal-benefit decomposition (§5), the plan ships in two build cycles:

- **Cycle A (this plan's D1-D3 + D5-D6):** the DELAY spine — identification predicate + flat comfort grace + SOC-floor collapse to standard timing + preset-write chokepoint + per-site gate. This captures the kids-incident recovery in full.
- **Cycle B (this plan's D4, gated on Cycle A live-validation + measured evidence):** the GRADUATED CONCESSION — step ladder with approach-speed monitoring. Parked with evidence trigger, see §5.

### 3.2 Identification predicate (D1) — FORMALIZED

Evaluated inside `_handle_climate_change` after `is_override=True` and after the existing operator-immune / temp_arrester_override early returns, BEFORE `_handle_severe_override` / `_handle_normal_override`.

**Ordered sequence in `_handle_climate_change` (single canonical list, rev-2 M2 consolidation):**

1. Suppression-TTL filter (`hvac_override.py:1562-1611`) — decides `is_override`. (Extracted as `_is_genuine_manual(event, entity_id) -> bool`.)
2. Zone lookup (`_find_zone_by_entity`) — if None, return.
3. `_temp_arrester_override_active` early return (:1705-1711) — SWITCH DOMINATES.
4. Operator-immune early return (:1663-1699) — IMMUNITY DOMINATES.
5. **NEW: `comfort_request(...)` evaluation.** If TRUE → seed comfort-delay grant + ledger row + RETURN (no severity dispatch).
6. Severity dispatch (`_handle_severe_override` / `_handle_normal_override`).

**Predicate** (fail-closed on every unknown):

```
comfort_request(entity, event, zone) :=
    (a) _is_genuine_manual(event, entity)  # already TRUE if we reach here
    ∧ (b) context user not in _immune_persons  # already filtered
    ∧ (c) bool(zone.persons)  # occupied AT the state-change instant
    ∧ (d) direction-toward-comfort on the COMFORT-RELEVANT LEG:
              current_temp := new_state.attributes.get("current_temperature")
              hvac_mode    := new_state.state  # "cool" | "heat" | "heat_cool" | "off" | …
              if hvac_mode == "off": FAIL_CLOSED
              if current_temp is None or not numeric or age > COMFORT_TEMP_MAX_AGE_S: FAIL_CLOSED

              # single-target modes read `temperature`; dual-target modes read the pair.
              if hvac_mode == "cool":
                  new_sp = new_state.attributes.get("temperature"); old_sp = old_state.…
                  if new_sp is None or old_sp is None: FAIL_CLOSED
                  qualifies := (new_sp < old_sp) AND (current_temp > new_sp)
              elif hvac_mode == "heat":
                  qualifies := (new_sp > old_sp) AND (current_temp < new_sp)
              elif hvac_mode == "heat_cool":
                  # relevant leg = leg matching the sign of (current_temp vs range).
                  if current_temp > new_high:
                      qualifies := (new_high < old_high) AND (new_high < current_temp)
                  elif current_temp < new_low:
                      qualifies := (new_low > old_low) AND (new_low > current_temp)
                  else:  # inside the deadband — no leg is comfort-relevant
                      FAIL_CLOSED
                  # RANGE-DRAG rule (worked example below): if BOTH legs moved,
                  # qualifies iff the relevant leg (per current_temp) also moved
                  # toward comfort. The non-relevant leg's motion is IGNORED.
              else:
                  FAIL_CLOSED
    ∧ (e) |delta| on the qualifying leg ≥ COMFORT_DELTA_MIN_F.
```

**Worked example — range-drag (heat_cool, cooling-relevant):** old_range=(68,80), new_range=(66,76), current_temp=79.
- Relevant leg = cool (79 > 80 is false; but 79 > new_high 76 → relevant leg = cool).
- new_high 76 < old_high 80 → toward comfort. Delta 4.0 ≥ 2.0 → **qualifies**.
- The 68→66 drag on the heat leg is IGNORED (non-relevant leg).

**Worked example — reversed drag:** old_range=(68,80), new_range=(70,82), current_temp=79.
- 79 is inside new range (70..82) — no leg is comfort-relevant → **FAIL_CLOSED**.

**Multi-thermostat zones (rev-2 H2 Review-1):** the grace attaches to `(zone_id, climate_entity_id)`, NOT to `zone_id` alone. Each thermostat in a multi-climate zone has its own timer entry; predicate reads `current_temperature` from the specific entity whose state changed. `comfort_delay_active(zone_id)` returns TRUE iff ANY thermostat in the zone has an active grace (the preset-write gate at hvac.py:1626 is per-zone; a grant on any thermostat suppresses the reason-ladder preset-write for the whole zone).

Where the source of `zone.persons`: the HVAC coordinator already resolves this per-zone. The OverrideArrester obtains it via the already-injected `zone` object from `_find_zone_by_entity`.

### 3.3 Battery-conditioned grace (D2) — SOC CONTRACT

**SOC is evaluated EXACTLY ONCE, at D1 grant.** After grant, `comfort_delay_active(zone_id) -> bool` is a PURE PROPERTY: `True` iff the timer is running AND the zone is still occupied AND `_temp_arrester_override_active is False`. No SOC re-read (rev-2 H2 Review-2).

**Grant-time SOC branches:**
- `soc ≥ COMFORT_SOC_FLOOR_PCT` AND `not blind` AND `not shed_active` → seed grace, ledger `comfort_delay_started`.
- `soc < floor` OR SOC unknown (Envoy blind) OR `shed_active` → **fall through to existing** `_handle_severe_override` / `_handle_normal_override` with ZERO behavior change. Fail-closed direction.

**Boundary (rev-2 L2 Review-1):** the comparison is `soc >= COMFORT_SOC_FLOOR_PCT` — inclusive. `soc == 80.0` grants. Comparisons in the D3 guard use the SAME operator against the SAME accessor.

**Behavior on mid-grace SOC drop (rev-2 documented):** a grant issued at SOC=94 that sees SOC drop to 78 mid-grace is NOT rescinded. The delay grants THIS request; the NEXT manual write's grant will fail the SOC check. Documented in D2 acceptance criteria; the rationale is that yanking a grant mid-flight is precisely the "granted then snatched" antipattern (§8).

SOC accessor: `HVACCoordinator.battery_soc: float | None` and `HVACCoordinator.battery_blind: bool` populated the same way `update_energy_state(offset, coast)` populates coast (energy coordinator pushes; HVAC coord reads; arrester AND coast-guard read from HVAC coord). No new cross-coordinator signal fabric. **BOTH D1 (grant-time) and D3 (coast-guard) consult this same accessor** — the Sharpest-Risk mitigation.

The `blind_hold_active` state is authoritative on "SOC read is not trustworthy right now"; if blind → treat as below-floor.

### 3.4 Coast / duty-limiter precedence rule (the HVAC-PRESET-FLAP-1 seam)

The duty limiter (hvac.py:2489-2510 accumulator, :1445 forced-away emit) and the comfort-delay branch write to the same effective preset for the same zone. They must not disagree per tick.

**Rule:**

- `SOC ≥ COMFORT_SOC_FLOOR_PCT` AND `arrester.comfort_delay_active(zone_id)` AND `not shed_active`: **comfort-delay wins.** During the comfort-grace window, `runtime_exceeded` does NOT force `away`; the accumulator keeps counting but the preset write is deferred to grace-expiry. On grace-expiry the coast machinery's current verdict resumes on the very next accumulator tick.
- Otherwise: **duty-limiter wins** (byte-identical to pre-cycle behavior).

Enforcement site: a single guard in the coast forced-away path (`hvac.py:1445`), reason-ladder leaf `comfort_delay_active` at `hvac.py:1577`. **BOTH the D1 grant AND this D3 guard consult `HVACCoordinator.battery_soc` — the SAME accessor.** No divergent SOC reads permitted (Sharpest Risk §8).

**Ordered sequence at hvac.py:1445 forced-away emit (single canonical list, rev-2 M2 consolidation):**

1. Read `runtime_exceeded` and current preset.
2. Read `coord.battery_soc` and `coord.battery_blind`.
3. Read `arrester.comfort_delay_active(zone_id)`.
4. If `battery_soc ≥ COMFORT_SOC_FLOOR_PCT` AND `not blind` AND `comfort_delay_active` AND `not shed_active`: skip forced-away, log reason `comfort_delay_active`, return.
5. Else: emit forced-away preset write via the new `emit_set_preset_mode(...)` chokepoint (reason=`runtime_exceeded`).

No change to duty-limiter thresholds, window, or accumulator; no change to sleep exemption; no change to normal-mode `else: continue`.

### 3.5 Graduated concession (D4, DEFERRED — Cycle B)

Sketch only, for scope closure. See original rev-1 for the pseudocode; unchanged in rev-2. Every step MUST route through `emit_set_temperature` + `self.suppress(entity, kind="temp")`. **Restart behavior:** state is RAM-only; on HA restart, state resets to IDLE. This is DELIBERATE and DISCLOSED — a concession that outlived a restart cannot be trusted (rev-2 M1 Review-2 disclosure). If the occupant is still uncomfortable post-restart the room will re-emit a manual and re-enter the ladder from step 0. If empirical evidence shows deploy cadence causes visible mid-ladder snapbacks, the Cycle-B upgrade path is a RestoreEntity-persisted grant TTL (parked design note; not scoped now).

### 3.6 Sunset / MIN_LIFE / temp_arrester_override / house-state interactions

- **`temp_arrester_override` switch flipped ON mid-grace (rev-2 H2 Review-1):** the switch's early-return at :1705-1711 fires FIRST on the next state-change event. In addition, `comfort_delay_active(zone_id)` returns FALSE while the switch is ON (`comfort_delay_active` includes `not _temp_arrester_override_active` as a conjunct). The active-grace timer entry is **evicted at the toggle** (via existing switch-write callback — one-line hook) so the ledger row `comfort_delay_expired` fires with `expiry_reason=switch_flipped_on`. OVERRIDE-NOTIFY-1 is NOT triggered (comfort-delay does not use the pre-warn machinery).
- **`temp_arrester_override` flipped OFF mid-grace:** no revival — the grace was evicted at ON. The occupant's next manual will start a fresh grace evaluation.
- **ARREST-SUNSET-1 denylist / MIN_LIFE:** those apply to operator-immune holds. A comfort-delay is NOT an operator hold — it does not stamp `_immune_hold_records`, does not write to `_temp_arrester_override_pending_sunset`, does not consult `ARRESTER_HOLD_PRESERVING_STATES`.
- **House-state transition mid-grace (rev-2 H2 Review-1, M3 Review-2):** does NOT sunset the grace. The kids' comfort request does not care that `home_evening → home_night` crossed. The grace has EXACTLY these exits: (i) timer expiry, (ii) zone becomes unoccupied, (iii) `_temp_arrester_override_active` flipped ON, (iv) `shed_active` becoming True does NOT terminate an in-flight grace (documented; the request was already granted; the next request will be shed-gated). Acceptance criterion in D1 for house-state cross.
- **OVERRIDE-NOTIFY-1:** no pre-warn NM alert for comfort-grace (short by construction — default 30 min).
- **Denylist inertness when arrester disabled (rev-2 M2 Review-1):** the ARREST-SUNSET denylist branch is inert while `_arrester_enabled=False` (temp_arrester_override ON). Comfort-delay respects this by construction because the switch early-return at step 3 (§3.2) fires first.

### 3.7 Write-site enumeration — per-site verdict against INV-COMFORT-DELAY (rev-2 H1)

Every write site in `hvac.py` and `hvac_override.py` that could revert a comfort-qualified manual, with its verdict (**ALLOW** unchanged, **DEFER** while `comfort_delay_active`, **DENY** entirely — none in Cycle A).

| # | Site | Kind | Purpose | Verdict during active comfort-grace | Rationale |
|---|---|---|---|---|---|
| S1 | `hvac.py:1626` | `set_preset_mode` | Reason-ladder preset write (freeze / vacancy / runtime_exceeded / pre_arrival / house_state_transition) | **DEFER iff reason ∈ {runtime_exceeded, house_state_transition}. ALLOW freeze / vacancy_past_grace / pre_arrival unconditionally.** | Freeze is safety (higher precedence); vacancy_past_grace means zone became unoccupied (predicate would already have invalidated the grace); pre_arrival is a positive, comfort-aligned action. runtime_exceeded is the exact HVAC-PRESET-FLAP-1 seam. house_state_transition (e.g. away preset on `home → away`) IS a legitimate defer target — occupant is present per predicate, house-state transition itself does not invalidate. |
| S2 | `hvac.py:1896` | `emit_set_temperature` | Guest-actuation range assertion when resolved range differs from thermostat's current range | **ALLOW** | This is URA setting the range on preset entry, not a revert against a manual. Already suppressed via `_override_arrester.suppress(...)` at the call site. |
| S3 | `hvac_override.py:1936` | `emit_set_temperature` | `_apply_compromise` — arrester's "meet halfway" nudge against a normal-severity manual | **DEFER** | This is a revert-style write. Precisely the class the comfort-grace exists to suppress. |
| S4 | `hvac_override.py:2034` | `set_preset_mode` | `_revert_override` — arrester's hard revert on severe override | **DEFER** | This IS the revert. The kids-incident event was heading here. |
| S5 | `hvac_override.py:2584` | `emit_set_temperature` | Soft-nudge on-entry setpoint push | **DEFER** | Soft-nudge is an active arrester action against the manual. |
| S6 | `hvac_override.py:2675` | `emit_set_temperature` | Soft-nudge RESTORE (undoes S5 after nudge window) | **ALLOW** | Restoration to pre-nudge value — moves *back* toward the operator's original range. Not a revert against the comfort manual. |
| S7 | `hvac_override.py:2711` | `set_preset_mode` | Soft-nudge preset restore (manual→pre_preset after nudge) | **ALLOW** | Same class as S6 — restoration; comfort-grace exists to prevent yanking the operator, and this write moves back toward what they had. |
| S8 | `hvac_override.py:3228` | `emit_set_temperature` | AI-rules R2 residual setpoint alignment | **ALLOW** *(fix-up)* | Reviewers confirmed this site is not the AI-rules climate write path — kept ALLOW / already-gated at higher level. The real AI-rules climate write lives in `coordinator.py::_execute_rule_action` (see cheap-block below). |
| S9 | `hvac_override.py:3498` | `emit_set_temperature` | AI-rules downstream write (secondary R-rule leg) | **ALLOW** *(fix-up)* | Same as S8. |
| S10 | `hvac.py:~2056` | `emit_set_temperature` | DPM (dynamic-preset-manager) apply loop — per-zone override-resolved range | **DEFER** *(fix-up D-CRIT-1)* | Was the ungated sibling of S3/S4/S5; capable of stomping a comfort-qualified manual on every 5-minute apply. Now gated on `comfort_delay_active(zone_id)` with rollback of the pre-emit suppress on defer. |
| S11 | `hvac_predict.py:~946` | `emit_set_temperature` | `_release_banked_zones` — solar banking release to baseline | **DEFER** *(fix-up D-HIGH-1)* | Was ungated; a mid-grace banking release would revert the comfort setpoint. Same gate pattern. |
| S12 | `hvac_predict.py:~1015` | `emit_set_temperature` | `_execute_zone_pre_cool` — predictive pre-cool | **DEFER** *(fix-up D-HIGH-1)* | Was ungated; predictive pre-cool would override a warmer-direction comfort manual. Same gate pattern. |
| S13 | `hvac_predict.py:~1153` | `emit_set_temperature` | Pre-heat loop — raise heating setpoint before on-peak | **DEFER** *(fix-up D-HIGH-1)* | Was ungated; sibling of S12 for the heating leg. Same gate pattern. |
| egress | `hvac_egress.py:~644` | `set_preset_mode` → `emit_set_preset_mode` | `_engage_resume` — restore saved preset after egress window closed | **ALLOW** *(fix-up B-MED-1)* | Restoration path (returns thermostat to its pre-URA-pause preset); classified ALLOW / no gate but now routes through the chokepoint for uniform emit accounting. Grep-anchored: no raw `set_preset_mode` `async_call` remains outside the chokepoint in HVAC surfaces. |
| coord | `coordinator.py::_execute_rule_action` (~:929) | AI-rules `hass.services.async_call` | Parsed AI-rule action dispatch | **REFUSE** *(fix-up D-HIGH-2)* | Cheap block: `climate.{set_temperature,set_preset_mode,set_hvac_mode}` refused with a WARN naming the rule_id — bypasses HVAC chokepoints entirely. Live probe: zero climate AI rules configured today (no behavior change). Parked upgrade: route through `emit_*` chokepoints with zone lookup. |

**Chokepoint shape (rev-2 H1 Review-1):**
- Existing `emit_set_temperature` is already the setpoint chokepoint — S3/S5/S6/S8/S9 route through it. **New:** it grows a `gate` parameter or a wrapping `_arrester_write_gate(entity, site_tag)` decorator; call sites pass their site tag. Sites tagged as DEFER are no-ops while `comfort_delay_active`.
- **NEW `emit_set_preset_mode(hass, zone, preset, *, reason, gate)`** in `hvac_setpoint.py`. S1, S4, S7, and the D3 forced-away write all migrate to it. Reason string flows into the gate for per-reason ALLOW/DEFER dispatch (matches S1's four-way split).
- Deferred writes MUST NOT queue and replay on grace-expiry (that would recreate the "granted then snatched" antipattern). Instead: the write is dropped; the coast/severity path re-emits naturally on the next tick if the condition still holds.
- Ledger row `comfort_delay_deferred_write` with `{site, zone_id, entity_id, reason, would_have_emitted}` on every DEFER hit — this is the empirical D-review anchor (Review D can grep ledger rows against write-site catalog for coverage).

### 3.8 Full setpoint-emission map — rev-2 H4 Review-1 (fix-up: extended)

Compliance re-assert, pre-arrival warmup, AI-rules R2 residual all searched. Coverage in §3.7 table (S1..S9). Fix-up round extended completeness to cover:
- `hvac.py` DPM apply loop (S10) — was ungated.
- `hvac_predict.py` release-banked / pre-cool / pre-heat (S11/S12/S13) — all were ungated.
- `hvac_egress.py` resume path — migrated to `emit_set_preset_mode` (ALLOW, restoration).
- `coordinator.py::_execute_rule_action` — AI-rules climate service call cheap-blocked (parked upgrade: route through chokepoints with zone lookup).

Completeness claim after fix-up: every URA-originated `climate.set_temperature` / `climate.set_preset_mode` / AI-rules `climate.*` write in `hvac.py`, `hvac_override.py`, `hvac_predict.py`, `hvac_egress.py`, and `coordinator.py` is either (a) routed through `emit_set_temperature` / `emit_set_preset_mode` with a per-site verdict, or (b) refused at the AI-rules dispatcher. Review D re-enumerates this end-to-end against INV.

---

## 4. Deliverables

### D1 — Identification predicate & branch insertion (Cycle A)
Insert `comfort_request(...)` per §3.2 in `_handle_climate_change` between step 4 and step 6 of the canonical sequence. Extract `_is_genuine_manual(event, entity_id)` (rev-2 L1). Grant record is per-`(zone_id, climate_entity_id)`.
- **Files:** `hvac_override.py` (branch + extraction), `hvac_const.py` (`COMFORT_*` constants), `hvac_setpoint.py` (NEW `emit_set_preset_mode`).
- **Ledger row schema (rev-2 Testability):**
  - `comfort_delay_started`: `{zone_id, climate_entity_id, delta_f, direction, current_temp, soc_at_grant, requested_setpoint, granted_setpoint, grace_s, hvac_mode}`.
  - `comfort_delay_expired`: `{zone_id, climate_entity_id, elapsed_s, expiry_reason}` where `expiry_reason` is an **OPEN enum** (initial values: `timer | zone_unoccupied | switch_flipped_on`; rev-2 Testability — enum documented as extensible for Cycle-B additions).
  - `comfort_delay_deferred_write`: `{site, zone_id, entity_id, reason, would_have_emitted}`.
- **Ledger reason enum on `sensor.hvac_reason_ledger`** gains three new labels; documented as open.

**Acceptance Criteria**
- **Verify:** unit test — cool manual in occupied zone with current_temp > new_temp, |delta|=4, SOC=94, hvac_mode=cool → comfort_delay_started; no revert timer scheduled inside COMFORT_GRACE_MIN.
- **Verify:** heat_cool range-drag worked example (§3.2) qualifies on cooling-relevant leg.
- **Verify:** heat_cool "inside deadband" case (§3.2) fails closed.
- **Verify:** SOC=60 → predicate false → severe/normal branch fires as pre-cycle.
- **Verify:** SOC=80.0 exact → grants (rev-2 L2, inclusive boundary).
- **Verify:** zone.persons=[] → predicate false → standard arrest.
- **Verify:** cool nudge DOWN in already-cold room → predicate false (wrong direction on relevant leg).
- **Verify:** hvac_mode=off → predicate false.
- **Verify:** current_temp None / stale → predicate false (fail closed).
- **Verify:** hvac_mode=cool with `temperature` attribute None → predicate false (fail closed on single-target read).
- **Verify:** shed_active=True → predicate false (rev-2 H3).
- **Verify:** house-state transition during grace does NOT sunset (rev-2 M3 Review-2) — grace timer continues; new criterion.
- **Verify:** temp_arrester_override flipped ON mid-grace → grace evicted, ledger `comfort_delay_expired` with `expiry_reason=switch_flipped_on`; subsequent OFF does not revive.
- **Verify:** kids-incident replay drives `_handle_climate_change` DIRECTLY with real `zone.persons` list and the real `HVACCoordinator.battery_soc` accessor path (NOT a monkeypatched shim) — rev-2 Testability Review-2.
- **Sensor:** `sensor.hvac_reason_ledger` shows a `comfort_delay_started` row.
- **Test:** `test_arrester_comfort_delay_predicate.py::{qualifies_cool,qualifies_heat,qualifies_heat_cool_cool_leg,qualifies_heat_cool_heat_leg,rejects_heat_cool_deadband,rejects_unoccupied,rejects_soc_below_floor,accepts_soc_80_boundary,rejects_wrong_direction,rejects_temp_unknown,rejects_hvac_off,rejects_shed_active,rejects_immune_user,rejects_switch_on,house_state_transition_no_sunset,switch_flip_on_evicts_grace}`.
- **Live:** replay-fixture test — 2026-08-09 16:49/17:14 zone_2 events MUST both produce `comfort_delay_started` and NO `_handle_severe_override` / `_handle_normal_override` call.

### D2 — Battery-conditioned grace + SOC accessor plumbing (Cycle A)
Add `battery_soc: float | None` and `battery_blind: bool` to `HVACCoordinator` via the existing energy-push channel. BOTH D1 (grant) and D3 (coast-guard) read from THIS accessor exclusively.

**Acceptance Criteria**
- **Verify:** SOC transition 82 → 78 while a comfort-delay is in flight → grace continues (documented behavior — the delay grants THIS request; SOC drop affects the NEXT one). NO mid-grace forced revert. This is a design contract, not a bug (rev-2 L2 property-vs-snapshot).
- **Verify:** Envoy blind → predicate treats as SOC < floor.
- **Verify:** BOTH D1 and D3 read via `HVACCoordinator.battery_soc` — no direct-to-energy-coord read from either site. Grep-anchored test.
- **Test:** `test_arrester_comfort_soc_gate.py`.
- **Live:** attribute check on `sensor.hvac_reason_ledger` last comfort row includes `soc_at_grant`; observed within one operator-issued manual request.

### D3 — Coast / duty-limiter precedence guard (Cycle A)
Guard the forced-away write at `hvac.py:1445` per §3.4 ordered sequence. Route through `emit_set_preset_mode`. Extend reason ladder at `hvac.py:1577` with `comfort_delay_active` leaf.

**Acceptance Criteria**
- **Verify:** synthetic — zone in coast, `runtime_exceeded=True`, SOC=90, comfort_delay_active=True → NO forced-away write; ledger row `comfort_delay_active`.
- **Verify:** SOC=60 → forced-away write proceeds; ledger row `runtime_exceeded`.
- **Verify:** shed_active=True + comfort_delay_active=True → forced-away proceeds (shed dominates comfort per rev-2 H3).
- **Verify:** grace expires while `runtime_exceeded` still True → forced-away emits on the very next accumulator tick.
- **Test:** `test_hvac_coast_comfort_precedence.py` — five-corner truth table (SOC × runtime_exceeded × occupied × comfort_delay_active × shed_active).
- **Live:** during a run where SOC ≥ 80 and coast trips inside a comfort-delay window, ledger shows `comfort_delay_active` reason and preset does NOT flip away.

### D4 — Graduated concession + approach-speed (Cycle B; DEFERRED, evidence-gated)
Not built in this cycle. §3.5 sketch is the design; trigger to un-defer in §5.

### D5 — Kids-incident replay fixture (support, Cycle A)
Codify a golden fixture of the 2026-08-09 zone_2 events as the acceptance replay for D1. Fixture drives real `_handle_climate_change` with real `zone.persons` and real SOC accessor (rev-2 Testability Review-2).

### D6 — Preset-write chokepoint + per-site gate (Cycle A) — NEW rev-2
Introduce `emit_set_preset_mode` in `hvac_setpoint.py`. Migrate S1/S4/S7 and the D3 forced-away write to it. Add `gate` parameter to `emit_set_temperature` (or wrapping decorator) and tag S3/S5/S6/S8/S9 with their DEFER/ALLOW disposition per §3.7. Ledger `comfort_delay_deferred_write` on every DEFER hit.

**Acceptance Criteria**
- **Verify:** per-site source mutation — neuter the gate at S3, S4, S8, S9 in turn → corresponding test in `test_arrester_write_site_gates.py` MUST fail. Global monkeypatch is NOT sufficient (Tier-3 Review C).
- **Verify:** S1 with reason=`freeze` during active grace → ALLOWED (safety dominates).
- **Verify:** S1 with reason=`vacancy_past_grace` during active grace → ALLOWED (zone unoccupied → grace already invalidated anyway).
- **Verify:** S6/S7 during active grace → ALLOWED (restoration).
- **Verify:** dropped DEFER does NOT queue for replay on grace-expiry.

**Non-goals (explicit)**
- No fan work — FAN-MANUAL-1 / FAN-LAYER-1 own that.
- No duty-limiter redesign.
- No changes to ARREST-SUNSET-1 machinery.
- No changes to freeze floor, operator-immunity, or `temp_arrester_override` switch behavior beyond the eviction hook (§3.6).
- No behavior change when SOC is below floor at grant.
- No mid-grace forced-revert on SOC drop.
- **No fix to HVAC-PRESET-FLAP-1** — that sibling defect stands (rev-2 H3 Review-1); this cycle only resolves the precedence seam so PRESET-FLAP does not race the comfort-grace.
- **Boot-window semantics (fix-up D2-LOW-2):** the arrester's
  `_get_grace_min()` / `_get_soc_floor()` accessors fall back to the
  module-constant defaults (30 / 80) when the rung-3 Number entities
  have not yet pushed a value. The window is closed at HC construction
  by the eager-seed kwarg (`comfort_grace_min` /
  `comfort_soc_floor_pct`) sourced from `entry.options`, so the boot
  transient is a fresh-install-only phenomenon (no persisted option ->
  default matches module constant, no observable difference). If a
  future cycle changes the defaults, the eager-seed path must be
  audited alongside the constant change.
- **Zone-scope admission (fix-up D-MED-2):** the comfort-delay grace protects the ZONE, not the specific writer. While a grant is active for `zone_id`, ANY URA writer targeting that zone's climate entity inherits the protection (S3/S4/S5/S8/S9 arrester paths, S1 reason-ladder preset write, S10 DPM apply, S11/S12/S13 predictor paths) — the deferral is byte-identical whichever caller reached the chokepoint. This is intentional: from the operator's perspective the grace is "URA, back off this zone for N minutes", not "URA, back off THIS specific decision path for N minutes". A comment in `hvac_setpoint.py` at each gate site names this behavior; no code change beyond documentation.

### 4.6 New constants (kill-switch semantics per rev-2 L1 Review-2)

| Constant | Default | Rung | Kill-switch | Rationale |
|---|---|---|---|---|
| `COMFORT_GRACE_MIN` | 30 min | **Entity-knob** (Number, persisted) | **`0` = feature disabled** (every request falls through to standard arrest). Verified by dedicated unit test. | Operator-tuned. |
| `COMFORT_SOC_FLOOR_PCT` | 80 | **Entity-knob** (Number, persisted) | **`0` = SOC gate disabled** — grants regardless of battery. Operator's deliberate blackout-risk acceptance (documented on the entity description + logged WARN on read at boot when `< 20`). | Operator-tuned. |
| `COMFORT_DELTA_MIN_F` | 2.0 °F | **Module constant** | `∞` (effectively) via a large number = feature disabled by predicate never firing. Prefer `COMFORT_GRACE_MIN=0` for disable. | Predicate threshold — review-gated. |
| `COMFORT_TEMP_MAX_AGE_S` | 900 s | **Module constant** | `0` = every read treated as stale → predicate always fails closed. | Staleness bound. |
| `COMFORT_TOTAL_MAX_MIN` | 60 min | **Module constant** | `0` = no concession possible (Cycle B). | Absolute backstop. |
| *(Cycle B)* `COMFORT_STEP_SIZE_F` | 1.0 °F | Module constant | — | Step size. |
| *(Cycle B)* `COMFORT_STEP_INTERVAL_MIN` | 15 min | Entity-knob | `0` = no ladder. | Operator observes pace. |
| *(Cycle B)* `COMFORT_SLOW_APPROACH_F_PER_MIN` | 0.15 °F/min | Module constant | — | Fitted threshold. |
| *(Cycle B)* `COMFORT_SLOW_STEP_STRETCH` | 2.0× | Module constant | `1.0` = no stretch. | Interval multiplier. |
| *(Cycle B)* `CONCESSION_OBSERVE_S` | 300 s | Module constant | — | Approach-speed window. |

---

## 5. Marginal-benefit decomposition (per `feedback_marginal_benefit_pushback`)

Unchanged from rev-1. Cycle A recommended; Cycle B parked with evidence trigger: "operator observes a run of ≥3 comfort-grace expiries within one evening where the room immediately re-flipped to a manual within an hour of expiry."

---

## 6. Measure-before-build gate (per `feedback_measure_before_build`) — rev-2 M1 Review-1

**Probe P1 (10-min recorder read, before build starts):**

1. **Rate of qualifying-under-INV events per week** (how often would D1 have engaged?).
2. **SOC distribution of those events** (how many would D2 have collapsed?).
3. **Coast co-fire density** (how often does D3 four/five-corner truth table exercise in the wild — the `runtime_exceeded` × qualifying-request overlap).
4. **Multi-thermostat zone frequency** (rev-2 add) — how many zones have >1 climate_entity? If zero, the per-`(zone_id, entity_id)` grant machinery in §3.2 collapses to per-zone (still correct, but simpler to reason about).
5. **Preset-flap co-fire query** (rev-2 add) — count HVAC-PRESET-FLAP-1 flap events within 60 s of a would-have-qualified manual. Confirms this cycle addresses the correct seam.
6. **Recorder attribute-retention verification** (rev-2 add) — confirm `climate.*` `current_temperature` / `temperature` / `target_temp_high` / `target_temp_low` attributes are retained in the recorder ≥ 7 days at reasonable cadence. If NOT, D1 unit tests can be built but the kids-incident replay (D5) cannot be sourced from history.
7. **Cycle-B evidence trigger check** — any night where multiple qualifying events within an hour would have exercised the concession ladder?

**Explicit go/no-go thresholds (rev-2 M1 Review-1):**

| Metric | Value | Action |
|---|---|---|
| Qualifying-events / week (metric 1) | 0 in 30 days | Consider narrow per-user manual-hold seed for the kids' Person entities; defer this cycle. |
| Qualifying-events / week (metric 1) | ≥ 1 | Cycle A proceeds. |
| Coast co-fire density (metric 3) | ≥ 1 co-fire / week | D3 build required (as scoped). |
| Coast co-fire density (metric 3) | < 1 co-fire / month | Downgrade D3 to Cycle-B-only (comfort grace still ships; coast guard deferred until measurable). |
| Multi-thermostat zones (metric 4) | 0 | Simplify grant key to `zone_id` in build. |
| Recorder retention (metric 6) | < 7 days | Escalate — build must synthesize the replay fixture from live events + logs instead. |
| Cycle-B trigger (metric 7) | Already met | Escalate scope; consider Cycle B in-cycle (still framing-disjoint reviewed). |

Probe deliverable: `docs/planning/AUDIT_arrester_comfort_delay.md` with the joint distribution table.

---

## 7. Tier argument

**Proposed: Tier 3 (four framing-disjoint reviews).** Unchanged from rev-1. Triggers: cost-AND-safety-impacting, threads SOC through two coordinators (Bug Class #53), cross-coordinator ripple (presence ↔ energy ↔ HVAC ↔ safety), history of multi-fix-up cycles in the arrester surface.

Four framings (unchanged):
- **A** local correctness (predicate arithmetic, direction detection per hvac_mode, boundary handling, kill-switches).
- **B** integration / state-machine integrity (D1↔D3 SOC-source unity, restart behavior, interaction with ARREST-SUNSET / OVERRIDE-NOTIFY / operator-immune / temp_arrester_override switch eviction).
- **C** test authority via real per-site source mutation on EACH gate in §3.7 (not a global monkeypatch); the kids-incident replay MUST drive `_handle_climate_change` directly.
- **D** adversarial completeness: re-enumerate every arrester emission site (§3.7) AND every coast forced-write site AND every SOC read against INV-COMFORT-DELAY, incl. pre-existing code. Legal-config repros required for each flagged leak.

Orchestrator pre-ship duty: personally re-grep every `set_temperature` / `set_preset_mode` write in `hvac_override.py` and `hvac.py`, and re-run source mutations on the D3 guard, the SOC-gate branch, and at least S3/S4/S8 in the §3.7 catalog.

Operator checkpoint BEFORE deploy is mandatory.

---

## 8. Sharpest risk

**The D1↔D3 predicate becomes desynchronized.** Two consumers of `SOC ≥ floor` in two coordinators; a moment of divergence produces "granted then snatched" — worse than either pure behavior.

Mitigation (build-time, restated for rev-2): single accessor `HVACCoordinator.battery_soc` (+ `battery_blind`), consumed by BOTH sites. No direct-to-energy reads from D1 or D3. Verified by Review C source-mutation on the accessor — BOTH tests must fail on the SAME mutation.

Secondary risk: the concession ladder in Cycle B, if merged prematurely, creates a rare-fire discharge surface with restart-inert state. Deferring Cycle B by construction eliminates this until the evidence trigger fires.

Tertiary risk (rev-2 H1 realization): the preset-write chokepoint migration in D6 touches three legacy inline `hass.services.async_call("climate", "set_preset_mode", …)` sites. A miss produces a silent leak past the comfort-grace at the ungated site. Mitigation: grep-anchored test that fails if any raw `hass.services.async_call(..., "set_preset_mode", ...)` call remains in `hvac.py` / `hvac_override.py` after the migration.

---

## 9. Report (executive summary)

- **Recommended shape:** STAGED — Cycle A (D1+D2+D3+D5+D6) now; Cycle B (D4) parked with evidence trigger.
- **Identification predicate (formalized):** genuine manual ∧ non-immune ∧ occupied ∧ direction-toward-comfort on the comfort-relevant leg (per-hvac_mode logic in §3.2) ∧ |delta| ≥ threshold ∧ fresh current_temp ∧ not shed_active.
- **SOC contract:** measured ONCE at grant; `comfort_delay_active` is a pure boolean; single accessor shared by D1 and D3; boundary `>=` inclusive.
- **Coast/duty-limiter precedence:** `SOC ≥ floor` AND `comfort_delay_active` AND `not shed_active` → coast defers; else limiter unchanged. Single guard at `hvac.py:1445`, ledger leaf `comfort_delay_active`.
- **Preset-write chokepoint (NEW D6):** `emit_set_preset_mode` in `hvac_setpoint.py`; all three legacy sites migrated; per-site DEFER/ALLOW table §3.7.
- **Invariant:** INV-COMFORT-DELAY stated falsifiably up-front (§1); Cycle-B-only observation tagged (#4).
- **Tier:** Tier 3 — 4 framing-disjoint reviews + orchestrator re-verification + operator checkpoint.
- **Sharpest risk:** D1↔D3 SOC-predicate desynchronization; mitigated by single-accessor discipline.

---

## 10. Plan review record

Two Tier-3 plan reviews were run against rev-1; both returned **PLAN-NEEDS-REVISION**. Findings and dispositions:

### Review 1 — completeness framing

| ID | Finding | Disposition in rev-2 |
|---|---|---|
| **H1** | Preset-write sites clobber granted setpoint on preset thermostats; every preset/setpoint emit site needs per-site verdict + a chokepoint | **FIXED.** §3.7 enumerates all 9 sites with DEFER/ALLOW verdicts + rationale. New D6 introduces `emit_set_preset_mode` chokepoint; existing `emit_set_temperature` grows `gate` parameter. Migration is grep-anchored (§8 tertiary risk). |
| **H2** | Multi-thermostat zones; house-state transition mid-grace; temp_arrester_override flipped ON/OFF mid-grace | **FIXED.** §3.2 attaches grants per `(zone_id, climate_entity_id)`. §3.6 states house-state does NOT sunset; switch-ON evicts grace with `expiry_reason=switch_flipped_on` (ledger); switch-OFF does not revive. Acceptance criteria added in D1. |
| **H3** | Parked-trigger check: load-shed, forecaster, EV drain, HVAC-PRESET-FLAP-1 | **FIXED.** §2.2 table adds shed / forecaster / EV rows with dispositions. Shed dominates comfort (INV falsification #6 added). Forecaster + EV: no interaction. HVAC-PRESET-FLAP-1: not fixed here (Non-goals). |
| **H4** | Full setpoint-emission map (compliance re-assert, pre-arrival, R2 residual) | **FIXED.** §3.8 confirms coverage in §3.7 catalog (S2 compliance, S1 pre_arrival branch, S8/S9 R2). |
| **M1** | Probe additions + go/no-go thresholds | **FIXED.** §6 adds metrics 4-6, explicit threshold table. |
| **M2** | Denylist ⇄ house-state interaction inertness | **FIXED.** §3.6 last bullet states denylist inert while arrester disabled. |
| **M3** | Tag INV observation #4 as Cycle-B-only | **FIXED.** §1 falsification #4 tagged Cycle-B-only. |
| **L1** | Name manual-ness insertion point precisely | **FIXED.** New symbol `_is_genuine_manual(event, entity_id)` extracted from :1562-1611. Named in §2.2 + §3.2 step 1 + D1 files list. |
| **L2** | blind_hold property-vs-snapshot + SOC==80.0 boundary | **FIXED.** §3.3 declares `comfort_delay_active` a pure property (no re-read) and SOC boundary `>=` inclusive. D2 verify for 80.0. |

### Review 2 — build-prediction framing

| ID | Finding | Disposition in rev-2 |
|---|---|---|
| **H1** | Dual-setpoint direction predicate: per-hvac_mode; AND/OR rule; single-target `temperature` mapping; range-drag; fail-closed | **FIXED.** §3.2 rewritten per-mode with explicit `cool` / `heat` / `heat_cool` / `off` branches, single-target `temperature` handling, range-drag decided (qualify on comfort-relevant leg only), two worked examples, fail-closed on every None. |
| **H2** | SOC contract: evaluated exactly once at grant; `comfort_delay_active` pure boolean; explicit accessor signature; rewrite Review-C mutation target | **FIXED.** §3.3 declares SOC-evaluated-once contract. `comfort_delay_active(zone_id) -> bool` signature published. §7 Review-C now targets the accessor + per-site gates. |
| **M1** | Restart-mid-grace disclosure | **FIXED.** §3.5 discloses RAM-only state, accepts it as design (Cycle A is a grace not a contract), lists RestoreEntity-TTL as Cycle-B upgrade path. |
| **M2** | Consolidate two ordered sequences into single numbered lists | **FIXED.** §3.2 has the canonical `_handle_climate_change` 6-step list. §3.4 has the canonical hvac.py:1445 5-step list. |
| **M3** | House-state-edge-during-grace acceptance criterion + ledger row ordering | **FIXED.** D1 verify criterion added; §3.6 documents behavior. |
| **L1** | Kill-switch semantics for EVERY knob | **FIXED.** §4.6 table adds Kill-switch column with explicit semantics per knob. `COMFORT_SOC_FLOOR_PCT=0` documented as deliberate blackout-risk acceptance with WARN log. |
| **Test-1** | Kids-incident replay MUST drive `_handle_climate_change` with real `zone.persons` + real accessor | **FIXED.** D1 verify criterion + D5 restated. |
| **Test-2** | Add `granted_setpoint` to D1 ledger schema | **FIXED.** D1 ledger schema now includes both `requested_setpoint` and `granted_setpoint`. |
| **Test-3** | State ledger reason enum is open | **FIXED.** D1 ledger section explicitly declares `expiry_reason` an OPEN enum, extensible for Cycle B. |

### Nothing I disagreed with

Every finding across both reviews resolves to a concrete decision in rev-2; no finding was rejected. Two calibration notes for the record (not disagreements):

- **Review 2 M1 (restart-mid-grace):** the review offered (a) accept + document vs (b) RestoreEntity-TTL. Chose (a) with (b) parked for Cycle B — the same marginal-benefit logic that stages the cycle. Documented explicitly in §3.5.
- **Review 1 H1 chokepoint shape:** the review asked for "a single guard around the preset service call, analogous to `emit_set_temperature`." Rev-2 delivers the requested chokepoint (`emit_set_preset_mode`) AND the parallel gate on `emit_set_temperature`, because §3.7 has both preset and setpoint DEFER sites — a preset-only chokepoint would leave S3/S5/S8/S9 ungated.

### Ready-to-review disposition

Rev-2 is prepared for a fresh Tier-3 four-review pass. The invariant, the SOC contract, the per-site verdict table, and the probe-first go/no-go gate are the artifacts reviewers should anchor to.
