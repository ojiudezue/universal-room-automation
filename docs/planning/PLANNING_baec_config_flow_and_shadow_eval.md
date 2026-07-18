# PLANNING — Battery-Aware EV Charging: control-surface consolidation + shadow-eval observability

**Version target:** v5.21.0
**Cycle name (operator-facing):** Battery-Aware EV Charging — control surface + confidence read
**Cycle name (internal):** BAEC options-flow + shadow-eval (DP internals stay `dp_*` per DPM precedent)
**Base commit:** develop @ b48addf0 (or later; a v5.20.0 release may land during writing — plan is code-neutral).
**Tier:** Tier 2-DB (three framing-disjoint reviews). Rationale in §Tier below.
**Status:** Design only. No code changes proposed here; this is the spec + acceptance contract.

---

## 1. Falsifiable invariant (state up front — Reviewer C/D falsifies exactly this)

> **INV-BAEC-SHADOW:** With `switch.ura_battery_aware_ev_charging` = OFF, DP eval logic (regardless of decision outcome) produces **zero** actuation-side effects — specifically: zero calls to `_apply_evse_battery_hold`-owned reserve writes attributable to DP, zero mutations of `_dp_state` past `HOLD_ONLY`, zero EVSE pause/turn_off service calls owned by DP, zero `_paused_by_dp` set-additions, zero `evse_dp_paused` KV writes, and zero net DB writes/tick above the pre-cycle baseline. The shadow eval MAY read state, MAY publish diagnostic attrs on `sensor.ura_energy_ev_charging_plan`, and MAY log at INFO rate-limited.

D's job: produce a legal-config reachable repro that breaks INV-BAEC-SHADOW under any eval outcome (would-transition, would-hold, would-force-start, blind-hold entry/exit, second-EVSE plug-in, restart mid-window). C's job: mutate the actuation gate in production source and confirm at least one test fails.

Sibling invariant carried from v5.20.0:
> **INV-OPTIONS-ROUND-TRIP:** For every BAEC knob, an edit through the options-flow schema lands in `entry.options` under the same `CONF_ENERGY_DP_*` key that the entity-set path writes; a subsequent read via config_flow shows the value the entity currently reports; the CM listener does NOT reload the entry (allowlist honored); the coordinator's live attr (`_dp_*`) matches the persisted value within one listener tick.

---

## 2. Institutional context verified

### Code read end-to-end (or targeted ranges where noted)
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:1240-1358` — `CONF_DP_*` (rung-1 default values) + `CONF_ENERGY_DP_*` (persisted keys) already exist and are the single source of truth for defaults. 7 keys total: `CONF_ENERGY_DP_ENABLE`, `..._EVAL_DELAY_MIN`, `..._MARGIN_MIN`, `..._MUST_START_BY_MIN`, `..._NEEDED_KWH_GARAGE_A`, `..._NEEDED_KWH_GARAGE_B`, `..._HOUSE_LOAD_SOURCE`.
- `custom_components/universal_room_automation/number.py:3060-3146` — 5 DP Numbers built via `_dp_number_factory` + `_build_dp_numbers`; each writes both the coordinator setter AND `entry.options[conf_key]` on `async_set_native_value` (rung-3 pattern; entry.options is the durable store).
- `custom_components/universal_room_automation/select.py:795-882` — `DrainPrecedenceHouseLoadSourceSelect` (EntityCategory.CONFIG; `entry.options` sole source of truth; validates against `DP_HOUSE_LOAD_SOURCES`; setter `set_dp_house_load_source`).
- `custom_components/universal_room_automation/switch.py:910-923` — `ECDrainPrecedenceEnableSwitch` built via `_ec_switch_factory` with friendly name "Battery-Aware EV Charging" (attr `_dp_enabled`, unique_id suffix `drain_precedence_enable`). RestoreEntity + `SIGNAL_ENERGY_COORDINATOR_READY` re-seed.
- `custom_components/universal_room_automation/sensor.py:7246-7300` — `EnergyDrainPrecedenceStateSensor` (friendly name "EV Charging Plan"; unique_id `..._energy_drain_precedence_state`); attrs mount `DrainPrecedenceState.to_attrs()` verbatim from `energy._dp_carrier`.
- `custom_components/universal_room_automation/__init__.py:4483-4499` — `_EC_SETTER_DISPATCH` already routes all 6 setter-backed DP CONFs (5 Numbers + Select) to their `set_dp_*` setters.
- `custom_components/universal_room_automation/__init__.py:4557-4562` — `CONF_ENERGY_DP_ENABLE` in `_NO_LIVE_ATTR_KEYS` (Switch is sole write path; snapshot-advance no-op).
- `custom_components/universal_room_automation/__init__.py:4624-4633` — All 7 `CONF_ENERGY_DP_*` keys already in `OPTIONS_RELOAD_SUPPRESS_KEYS`. This is a critical finding: **the reload-suppression plumbing for BAEC is DONE**; no allowlist change is required for this cycle. Only the UI surface + shadow eval are new.
- `custom_components/universal_room_automation/config_flow.py:4846-4908` — **`presence_timing` collapsed-section precedent** (v4.7.25 HVAC presence-timer knobs; PR #364). Pattern: `vol.Optional("presence_timing"): section(subschema, {"collapsed": True})`; the CM options handler flattens back before persist (`user_input.pop("presence_timing", None)` at 4521-4524).
- `custom_components/universal_room_automation/config_flow.py:6191-6427` — `async_step_coordinator_optimization` — **canonical two-collapsed-section precedent** (`optimizer_guards` + `optimizer_llm`); flattens back on save at 6234-6240 before writing merged options. This is the exact shape to clone for BAEC.
- `custom_components/universal_room_automation/config_flow.py:2582-2608` + `4426` — CM options `async_step_init` menu wiring; new step attaches here.
- `custom_components/universal_room_automation/domain_coordinators/optimization.py:107,244,3137-3146,3543-3546` — Optimizer L1-Shadow pattern: on shadow level, dispatch an event tagged `shadow_dry_run` and set `"note": "shadow_dry_run — no proposed action emitted"` in the intent trail; NO downstream execution branch runs. This is the pattern the BAEC shadow-eval mirrors (publish decision, do not actuate).
- `custom_components/universal_room_automation/config_flow.py:3092-3330` — v4.7.22 fan-recheck "Advanced" collapsed sub-section (7 timing knobs) — additional precedent.

### Prior planning + memory pulled
- `docs/planning/PLANNING_evse_drain_precedence.md` — full read. Knob ladder §68-84 (rung table). Naming §371-381. Ratifications §246-264. Probe reports §266-369.
- `docs/reviews/code-review/battery_aware_ev_charging_tier3.md` — full read. Ledger of what shipped, D2-H1 (`_paused_by_dp` persistence), fix-up 3 in b48addf0.
- Memory `project_ev_drain_precedence_cycle.md` — operator ratification 2026-07-17; naming ratification c27df04c; kill-switch retirement trigger.
- Memory `project_ev_charge_start_deadband.md` — the release-at-floor plumbing this cycle's shadow read must not disturb.
- CLAUDE.md — Institutional Context First (this section), Numbers Get Knobs (placement ladder), Marginal-Benefit Decomposition (applied §5), No Fabrication.

### Design docs
- `docs/Coordinator/energy.md` — battery + EVSE seams (context only; no changes to seams here).

### Grep verifications for proposed additions (REUSED / NEW)

| Proposed | Verdict | Evidence |
|---|---|---|
| `CONF_ENERGY_DP_*` (7 persisted keys) | REUSED — all 7 exist | `energy_const.py:1352-1358` |
| `CONF_DP_*` (default-value constants) | REUSED — all 7 exist | `energy_const.py:1257-1298` |
| `_EC_SETTER_DISPATCH` entries for 5 Numbers + Select | REUSED | `__init__.py:4493-4498` |
| `OPTIONS_RELOAD_SUPPRESS_KEYS` entries for all 7 | REUSED — no allowlist change needed | `__init__.py:4624-4633` |
| Collapsed-section `section(schema, {"collapsed": True})` pattern | REUSED | `config_flow.py:4853-4908` (presence_timing), `6416-6420` (optimizer) |
| Flatten-on-save pattern | REUSED | `config_flow.py:4521-4524`, `6232-6240` |
| Kill-switch semantics on a Switch entity | REUSED | `switch.py:_ec_switch_factory` |
| Shadow-eval pattern (dry-run marker + attrs, no downstream) | REUSED (Optimizer L1) | `optimization.py:3137-3146,3543-3546` |
| **NEW** step id `coordinator_battery_aware_ev_charging` (or shorter `coordinator_baec`) | NEW — no existing step covers DP surface today; no grep hit for `coordinator_ev`, `coordinator_baec`, `coordinator_dp` | grep on `config_flow.py` |
| **NEW** collapsed sub-section key `"baec_advanced"` (proposed) | NEW — verify no collision at build time | grep on `strings.json`+`config_flow.py` clean |
| **NEW** shadow-eval attr keys `shadow_decision`, `shadow_last_eval_snapshot`, `shadow_last_eval_at`, `shadow_would_transition_at` on `EnergyDrainPrecedenceStateSensor` | NEW — carrier `to_attrs()` at sensor.py:7298 currently mirrors real state only | build extends `to_attrs()` |
| **NEW** operator-facing display names (Numbers/Select) | NEW display strings; internal `unique_id` / attr names UNCHANGED (DPM precedent) | see §4 naming table |
| **NEW** module-constant knob for shadow-eval INFO-log rate-limit interval (`DP_SHADOW_LOG_RATE_LIMIT_S`) | NEW — rung-1 safety/log-volume bound | not operator-tunable |

Nothing else is added. If build discovers a needed addition, the builder documents it against this table.

---

## 3. Tier classification

**Tier 2-DB (three framing-disjoint reviews).** Not Tier 3.

Why 2-DB and not Tier 1/2:
- Changes span 4+ platforms (config_flow, options_flow round-trip, strings/translations, sensor attrs, entity registry cleanup) AND a coordinator eval-path branch (shadow).
- Regression-prone: the eval path exists today only behind `_dp_enabled=True`; shadow adds a NEW branch that runs on the OFF side. If shadow ever mutates hot state, that's a silent regression against the Tier-3 invariants shipped in v5.20.0 (INV-DP1..5).
- Entity retirement (4 Numbers + Select) touches the entity registry; Bug Class #46 (entity migration safety) history.
- Options-flow round-trip has caused prior CRIT flap regressions when consumers didn't share the flat-key surface (v4.7.35 A-H1 pattern).

Why not Tier 3:
- No new value threads through the reserve-writer surface. The reserve-composition machinery is unchanged; shadow read-only.
- No new precedence decisions on cost-and-safety seams; kill switch OFF is unchanged behavior modulo pure observation.
- Marginal-Benefit test (§5) does NOT justify Tier-3 review cost for a display+observability cycle.

**Three framings (disjoint):**
- **A — Correctness + edge cases + options round-trip.** Every BAEC key round-trips through the new schema; defaults resolve correctly when the key is absent; `_get_current` fallback path; validators reject out-of-range; datetime-minute encoding stable across the "Latest charge start" edit path.
- **B — Async + lifecycle + no-reload + entity retirement.** CM listener does NOT reload on any BAEC options edit (verify against `OPTIONS_RELOAD_SUPPRESS_KEYS`). Snapshot advances. Entity retirement path: for the 4 retired Numbers + Select, decide "delete registry entry vs disable-by-default"; if delete, use the v4.7.22 orphan-cleanup path; if disable, verify `EntityCategory.CONFIG` + `entity_registry_enabled_default = False`; no dashboard breakage on restart; no unique_id collision.
- **C — Shadow-eval mutation-anchored authority + DB-write discipline.** Reviewer neuters the shadow actuation-gate in production source at each candidate escape (reserve write, `_dp_state` mutation, EVSE pause, `_paused_by_dp`, `evse_dp_paused` KV, ledger stamp) — a specific test MUST fail per site. Reviewer additionally instruments a write-count fixture around the tick and confirms shadow adds zero net DB writes/tick vs OFF baseline (write-flood incident memory).

Live validation (Review D-live) after deploy: attrs published on sensor; switch OFF for 24h with a real overnight plug-in; observe shadow-decision publication + assert no reserve write + no `_dp_state` advance past `HOLD_ONLY`.

---

## 4. Deliverables

### D1 — Config/options-flow surface: "EV Charging" section with collapsed "Advanced"

Add `async_step_coordinator_battery_aware_ev_charging` (step id short-form `coordinator_baec`) to the CM options flow. Mirror `async_step_coordinator_optimization` shape:

- **Top-level fields (always visible):**
  - `CONF_ENERGY_DP_ENABLE` — BooleanSelector — display "Battery-Aware EV Charging"
  - `CONF_ENERGY_DP_MUST_START_BY_MIN` — NumberSelector (BOX, min=0, max=1439, step=15, unit="min past midnight") — display "Latest charge start (minutes past midnight)"

- **Collapsed sub-section `baec_advanced` (default `{"collapsed": True}`):**
  - `CONF_ENERGY_DP_EVAL_DELAY_MIN` — Number 1..60 step 1 — "Decision delay (minutes)"
  - `CONF_ENERGY_DP_MARGIN_MIN` — Number 0..240 step 5 — "Charging time buffer (minutes)"
  - `CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A` — Number 1..120 step 0.5 — "Typical charge needed — Garage A (kWh)"
  - `CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B` — Number 1..150 step 0.5 — "Typical charge needed — Garage B (kWh)"
  - `CONF_ENERGY_DP_HOUSE_LOAD_SOURCE` — SelectSelector over `DP_HOUSE_LOAD_SOURCES` — "Overnight house load estimate"

- **Flatten-on-save:** `user_input.pop("baec_advanced")` merged with top-level BEFORE `async_create_entry`. Mirror `config_flow.py:6232-6240` exactly.
- **Menu wiring:** add `"coordinator_baec"` to the CM options `async_step_init` menu (see `config_flow.py:2582-2608`).
- **strings.json / translations/en.json:** add step title, section label ("Advanced (rarely change)"), field labels, and one-line description for each field per the naming table §5. Field descriptions describe operator-visible behavior (never mechanism).

**Acceptance:**
- **Verify:** editing any BAEC key via the options flow lands the value under the identical `CONF_ENERGY_DP_*` key it would land under via the entity set path (grep-verifiable in `entry.options`).
- **Sensor:** `sensor.ura_energy_ev_charging_plan` attribute `shadow_last_eval_snapshot` reflects the new value on the next eval tick.
- **Test:** parametrized round-trip test — for each key, options-flow edit → `entry.options` mutation → coordinator live attr (`_dp_*`) update within one listener tick, without a reload (`async_update_entry` observed; `async_reload` NOT called).
- **Test:** entity-set → options-flow read parity: entity `async_set_native_value` writes value V; options-flow re-open shows V as the default.
- **Live:** operator changes "Charging time buffer" from 60 → 90 in options flow; no HA restart; sensor attr updates within one tick; log line `DP number energy_dp_margin_min set to 90` present (existing INFO from `number.py:3069`).

### D2 — Device entity surface slim-down (retire 4 Numbers + Select; keep Switch + must-start-by Number)

Retain (as device entities):
- `ECDrainPrecedenceEnableSwitch` → `switch.ura_battery_aware_ev_charging` — kill switch is a legitimate dashboard-level control (rung-3).
- The must-start-by Number → `number.ura_dp_must_start_by_min` — the highest-frequency operator-observation knob (per probe P4: worst-case start time is the key overnight liveness readout).

Retire (from the device page; keep persisted key + coordinator setter path intact):
- `dp_eval_delay_min` Number
- `dp_margin_min` Number
- `dp_needed_kwh_garage_a` Number
- `dp_needed_kwh_garage_b` Number
- `dp_house_load_source` Select

**Retirement mechanism (design decision):** disable-by-default via `entity_registry_enabled_default = False` PLUS `EntityCategory.DIAGNOSTIC` demotion — NOT registry delete. Rationale:

> **v5.21.0 fix-up (B-MED-1) — registry-semantics correction.** `entity_registry_enabled_default = False` only affects NEW registrations. The 4 already-live Numbers + Select on the operator's house stay ENABLED across upgrade (though they DO move to Diagnostics via the category change, per the v4.7.24 precedent). The "live slim-down" for existing entities is executed at deploy-time by the orchestrator via a one-shot MCP-driven entity-registry disable pass — reversible, operator-visible, NOT performed by this cycle's code. Fresh installs (post-upgrade) get the disable default automatically. No registry migration is attempted in code (Bug Class #46 avoided).
- Delete is destructive; if the operator re-enables the flag later, unique_id path is preserved by disable-by-default → zero-friction return.
- v4.7.22 orphan cleanup precedent applied to entities that had never been shipped; these have shipped in b48addf0, and Bug Class #46 (entity migration safety) counsels against destructive removal when disable suffices.
- Options flow is now the primary write path; entities become hidden diagnostics that dashboard operators can opt into.
- Kill-switch retirement trigger from `PLANNING_evse_drain_precedence.md:379-381` explicitly plans a future demotion of the Switch too — retire-by-disable matches that pattern.

**Acceptance:**
- **Verify (fresh install):** the 4 Numbers + Select do not appear on the URA: Energy Coordinator device page (disabled by default via `entity_registry_enabled_default = False`).
- **Verify (live upgrade):** on the operator's existing house, the 4 Numbers + Select remain enabled across upgrade (registry semantics: the default flag only applies to NEW registrations). The live slim-down is executed at deploy-time by the orchestrator via a one-shot MCP-driven entity-registry disable pass; this is reversible and operator-visible — NOT done by code.
- **Verify:** re-enabling a retired entity from the entity registry restores the pre-retirement behavior (round-trip parity retained).
- **Sensor:** no orphan entity ids reported by any sensor-health / actuator-visibility surface after upgrade.
- **Test:** entity registry migration test — an existing config entry with the 5 pre-retirement entities enabled upgrades cleanly; on fresh install the 5 entities are registered disabled; on operator re-enable, values still write through to `entry.options` and coordinator setters.
- **Live:** dashboard cards referencing `number.ura_dp_*` (if any) surface an `unavailable` state gracefully; operator can re-enable individual entities as needed.

### D3 — Rename user-facing labels (display only; internals stay `dp_*`)

Cognitive-simplicity rewrite of all 6 knob labels + long-form descriptions. `unique_id`, entity_id slug, coordinator attr names, `CONF_ENERGY_DP_*` keys — ALL UNCHANGED. DPM naming precedent (`PLANNING_evse_drain_precedence.md:378-381`).

Table (old device label → new operator-facing name → one-line config-flow description):

| Internal key | Old device label | New name | Explainer text (config-flow description) |
|---|---|---|---|
| `_dp_enabled` (switch) | "Battery-Aware EV Charging" | "Battery-Aware EV Charging" (unchanged; already operator-ratified) | "Let the battery drain to its overnight target BEFORE the car starts charging on nights when both fit." |
| `energy_dp_eval_delay_min` | "DP Eval Delay" | "Decision delay" | "How long to watch after the battery starts holding before deciding whether to let it drain first." |
| `energy_dp_margin_min` | "DP Safety Margin" | "Charging time buffer" | "Extra minutes added to the car-charging estimate, so the car always finishes before morning." |
| `energy_dp_must_start_by_min` | "DP Must Start By (min past midnight)" | "Latest charge start" | "Car charging always begins by this time, even if the battery hasn't finished draining. Enter minutes past midnight (180 = 03:00)." |
| `energy_dp_needed_kwh_garage_a` | "DP Needed kWh (Garage A)" | "Typical charge needed — Garage A" | "How much energy the car in Garage A usually needs; used to judge whether drain-then-charge fits in the night." |
| `energy_dp_needed_kwh_garage_b` | "DP Needed kWh (Garage B)" | "Typical charge needed — Garage B" | "How much energy the car in Garage B usually needs. Falls back to a worst-case estimate when no history is available." |
| `energy_dp_house_load_source` | "DP House Load Source" | "Overnight house load estimate" | "Which reading is used to predict how fast the battery will drain overnight. `max(live_span, r1_base)` is the safe default; the others are for probing." |
| `drain_precedence_state` (sensor) | "EV Charging Plan" | (unchanged — already operator-ratified) | (existing) |

Option labels for `HOUSE_LOAD_SOURCE`:
- `max_span_r1` → "Safe blend (recommended)"
- `live_span` → "Live meter only"
- `r1_base` → "Modelled baseline only"

All string changes live in `strings.json` + `translations/en.json`. NO code-level rename. NO `unique_id` mutation. NO entity_id migration.

**Acceptance:**
- **Verify:** device page + config-flow both show the new labels; no old label survives in either surface.
- **Verify:** existing dashboards referencing `number.ura_dp_*` / `select.ura_dp_house_load_source` / `switch.ura_battery_aware_ev_charging` / `sensor.ura_energy_ev_charging_plan` continue to resolve (entity_ids unchanged).
- **Test:** strings-parity test — every new label present in both `strings.json` and `translations/en.json`; no orphan keys.

### D4 — Shadow eval + observability (kill switch OFF path)

When `_dp_enabled` = False, run the arithmetic-only eval each decision-cycle tick using the same `TransitionInputs` the enabled path uses, produce a `TransitionDecision`, and publish:

- On `EnergyDrainPrecedenceStateSensor` attrs:
  - `shadow_decision` — one of `would_transition | would_hold | would_force_start | not_applicable`
  - `shadow_last_eval_at` — ISO timestamp of the last shadow eval
  - `shadow_last_eval_snapshot` — the `TransitionInputs` dict (SOC, house_load_kw, needed_kwh, drain_hours, charge_hours, margin_h, night_hours_remaining, fits) that fed the decision
  - `shadow_reason` — the human string from the decision (mirrors real `last_eval_snapshot.reason`)
- An INFO log line rate-limited to `DP_SHADOW_LOG_RATE_LIMIT_S` (proposed rung-1 constant, candidate default 300s; safety bound — noisy logs are a known incident risk).

**Actuation-free guarantees (INV-BAEC-SHADOW enforcement):**
- Shadow eval MUST reuse the exact `_evaluate_dp_transition` pure function (no fork). The gate that guards actuation MUST be a single early-return in the caller BEFORE any state-machine mutation, reserve write, EVSE pause, `_paused_by_dp` mutation, or KV persist.
- Shadow eval MUST NOT stamp `_desired_stamped_at`, MUST NOT touch `_last_reserve_level*`, MUST NOT set `_dp_state` past `HOLD_ONLY`, MUST NOT persist an `evse_dp_paused` KV entry.
- Shadow eval MUST NOT add per-tick DB writes. Attr publication routes through in-memory state on the carrier (`_dp_carrier`); the sensor already reads via `to_attrs()`. Zero new DAO calls introduced.
- Shadow eval MUST honor `is_blind_hold`: no SOC available → no shadow eval → publish `shadow_decision = not_applicable`, `shadow_reason = "blind_hold"`.
- Shadow eval MUST honor night-window gate (v5.20.0 H-4a): outside night window, publish `shadow_decision = not_applicable`, `shadow_reason = "outside_night_window"`.

**Acceptance:**
- **Verify:** INV-BAEC-SHADOW holds under Reviewer C's mutation-anchored anchors (below).
- **Sensor:** `sensor.ura_energy_ev_charging_plan` publishes `shadow_decision`, `shadow_last_eval_at`, `shadow_last_eval_snapshot`, `shadow_reason` while `switch.ura_battery_aware_ev_charging` = OFF, and continues to publish real (non-shadow) attrs when the switch is ON.
- **Test — mutation anchors (each MUST cause at least one specific test to fail):**
  1. Remove the OFF-side early-return; a "no reserve write while switch OFF" test MUST fail.
  2. Allow shadow eval to advance `_dp_state` past `HOLD_ONLY`; a "state stays HOLD_ONLY while switch OFF" test MUST fail.
  3. Allow shadow eval to add `_paused_by_dp`; an EVSE-membership test MUST fail.
  4. Allow shadow eval to write `evse_dp_paused` to KV; a KV-parity test MUST fail.
  5. Bypass blind-hold gate for shadow; a "blind_hold ⇒ shadow_decision=not_applicable" test MUST fail.
  6. Bypass night-window gate for shadow; a "daytime ⇒ shadow_decision=not_applicable" test MUST fail.
- **Test — DB-write discipline:** fixture wraps the DAO write path; over N shadow ticks the write-count delta = 0.
- **Live:** with switch OFF, over one overnight cycle, `shadow_decision` transitions from `not_applicable` → `would_transition` / `would_hold` at plug-in and reverts at morning; battery reserve floor traces unchanged from baseline; zero actuation-service call in log attributable to DP.

### D5 — Post-restart Live Validation writeback

Per operator rule 2026-06-05: after Review D-live, replace the prospective Live bullets in `README_v5.21.0.md` with a `Validated <date>` results table. Each row: acceptance criterion → PASS/FAIL → concrete evidence (entity attr value; log grep; DB-write delta reading). Cycle is NOT closed until this table is written.

---

## 5. Marginal-Benefit decomposition (mandatory per CLAUDE.md)

Decomposing this cycle to guard against sunk-cost elaboration:

- **Simplest version:** options-flow surface (D1) + rename labels (D3). Captures ~70% of operator value: BAEC becomes editable in the config flow, cognitive-simplicity naming complete, no ratchet on the eval path.
- **Marginal ingredient — entity retirement (D2):** display cleanup only. Zero behavioral risk if implemented as disable-by-default (Bug Class #46 avoided). LOW marginal risk, MODERATE marginal benefit.
- **Marginal ingredient — shadow eval (D4):** introduces a new code path that runs when the switch is OFF (the "safe" path today). This IS the categorically risky ingredient — a new writer to a shared primitive-adjacent surface, gated by a single early-return. Marginal benefit: pre-activation confidence read (a real operator ask). Marginal risk: paid by the mutation-anchored C review and the INV-BAEC-SHADOW invariant. Cost is bounded because the gate is a single, testable point.

Verdict: ship D1+D2+D3+D4 in one cycle. D4 is the reason for Tier 2-DB (not Tier 2). If D4 review reveals the actuation-gate cannot be made single-point-testable, park D4 to a follow-up and ship D1+D2+D3 as v5.21.0.

Parked (not built) — recorded here per the "park, don't delete" rule:
- Per-car auto-tuning of `needed_kwh` from post-ship session history (would require classification of car-stop vs switch-stop at runtime; probe P3 did this offline).
- Kill-switch retirement to constant (per §381 of drain-precedence plan). Trigger: 30 days clean shakedown post-v5.21.0.

---

## 6. Plan-completion tracking

At close of cycle, document explicitly (per CLAUDE.md rule):
- Which of D1..D4 shipped vs deferred, with rationale.
- Whether the shadow-eval INV held under all C mutations; if any anchor was weakened, why.
- Any strings.json / translations key added that lacks a translation stub, tracked for i18n follow-up.
- Whether the entity-retirement path chose disable-by-default (proposed) or delete; if delete, cite the Bug Class #46 mitigation.
- Post-restart Live Validation results table written back into `README_v5.21.0.md`.

---

## 7. Open questions (operator input requested before build)

1. **D4 gate placement:** the single early-return can live either (a) inside `_evaluate_dp_transition`'s caller (in `energy.py`) OR (b) inside a new `_dp_evaluate_shadow_or_real` dispatcher. Reviewer C's mutation-anchor test is stronger with (a) — one physical site, one mutation, one failing test. Recommend (a); confirm.
2. **Retirement mechanism for the 4 Numbers + Select:** disable-by-default (recommended, Bug Class #46-safe) vs registry-delete (cleaner but destructive). Recommend disable-by-default; confirm.
3. **Rate-limit `DP_SHADOW_LOG_RATE_LIMIT_S` default:** 300s proposed. Confirm or adjust (30s would surface every eval; 600s would suppress interesting edges).
4. **Shadow attrs on the same sensor vs a new `sensor.ura_energy_ev_charging_plan_shadow`:** recommend same sensor with `shadow_*` prefix — halves entity count, keeps observation in one place. Confirm.
5. **Section header text:** "Advanced (rarely change)" (matches DPM precedent) vs "Fine-tuning" vs other. Confirm.
