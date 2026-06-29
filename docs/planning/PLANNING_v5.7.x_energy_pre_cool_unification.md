# Planning — v5.7.x · Energy Pre-Cool Unification

> **Status:** PLAN (build-ready) · **Author:** planner · **Date:** 2026-06-28
> **Tier:** **Tier 3** (operator-elevated 2026-06-28 from 2-DB → 3). Regression-prone cross-coordinator EC↔HC; trust-hierarchy ripple touching the existing solar-banking and weather-pre-cool gates; the cycle threads a configurable offset + a tri-valued scope through a state machine consumed by every zone (single-missed-path failure mode, Bug Class #53). **FOUR framing-disjoint reviewers** (A local-correctness+PV-gate, B migration+signal-chain, C new-surfaces+per-site-mutation-tests, D adversarial-completeness/diff-blind) + **mandatory operator pre-deploy checkpoint** + live validation + post-deploy README write-back.
> **Version sequencing:** ships AFTER v5.7.0 (guest-mode v2 cycle, currently in progress — no planning doc on disk yet, named per operator). This cycle takes the next available slot, **v5.7.1** (single feature, no DB DDL → no schema migration; the "DB" framing applies to data-payload/config-state migration of the retired toggle, see D3 + D5).
>
> **Working name (constant):** `ENERGY_PRECOOL_NAME` (string display: `"Energy Saver Pre-Cool"`). Operator-locked 2026-06-28 (the constant NAME stays `ENERGY_PRECOOL_NAME`; only its VALUE is the user-facing label). Rename later is one-line + a `strings.json` / `translations/en.json` swap.

---

## 1. Operator Decision (verbatim context)

> "We don't need 2 mechanisms that overlap." · "It's about energy, not comfort (it gets too cold when it works well)."

Chosen architecture (operator-confirmed, option 2):

1. The **decision** stays in HC's predictor (`hvac_predict.py`).
2. The trigger becomes **PV-aware** (consults the same `_get_net_power()` signal banking already uses).
3. A **dedicated enable toggle** is surfaced on the **EC device** (mirrors `ECSolarBankingSwitch`/`HVACPreConditioningSwitch` accessor pattern).
4. The **old solar-banking toggle is RETIRED** and its enable state is **migrated** into the new toggle so operators who had it set aren't stranded.
5. The master "28 · HVAC Predictive Conditioning" (`HVACPreConditioningSwitch`) **continues to gate pre-arrival warm-up + pre-heat** (genuine comfort branches). Only the energy-pre-cool branch moves under the new dedicated toggle. (Master "28" remains the parent kill-switch above ALL pre-conditioning, including the new energy-pre-cool — defense in depth.)
6. **Pre-cool offset is operator-configurable** (operator 2026-06-28: "should be configurable in Config… Default can be 2F to make the space not too cold suddenly"). Surface a Number on the EC device alongside the toggle. Default `-2.0 °F` (i.e. 2°F of pre-cool).
7. **Scope is operator-configurable** (operator 2026-06-28, ADOPTED): three values — `occupied_only` / `whole_house` / `auto_pv_tiered`. Default `auto_pv_tiered`: occupied-only normally, expand to whole-house ONLY when there is real export surplus (energy being dumped to grid for ~nothing → banking everywhere is free). Surface a Select on the EC device.

---

## 2. Institutional Context Verified

Greps run against the live tree before scoping. Every proposed addition is annotated **REUSED** (with citation) or **NEW** (with justification).

### 2.1 Current state — cited

| Mechanism | Gate | Trigger function | Conditions | Offset | Floor | PV-aware? |
|---|---|---|---|---|---|---|
| Weather pre-cool | Master "28" only (`_is_pre_conditioning_enabled` `hvac_predict.py:714-735`; checked at `:480`) | `_should_weather_pre_cool` `hvac_predict.py:656-681` | season∈{summer,shoulder} AND `forecast_high >= self._precool_forecast_high` (default 90°F, `hvac_const.py:99`) AND `12 <= hour < 14` (i.e. `PEAK_HOUR_START - PRECOOL_LEAD_HOURS <= hour < PEAK_HOUR_START`) AND `soc >= PRECOOL_SOC_MIN` (30%, `hvac_predict.py:40`) AND occupied | **−2.0°F** (`hvac_predict.py:492`) | `SOLAR_BANK_FLOOR` 72°F (`hvac_const.py:156`, applied in `_execute_zone_pre_cool` `hvac_predict.py:902-`) | **NO** |
| Solar banking | `CONF_HVAC_SOLAR_BANK_ENABLED` (EC device) via `_is_solar_banking_enabled` (`hvac_predict.py:737-757`); checked at `:520` | `_should_solar_bank` `hvac_predict.py:683-712` | season∈{summer,shoulder} AND `soc >= self._solar_bank_soc_min` (default 95%, `hvac_const.py:73`) AND `net_power < -500` W (actively exporting) AND `forecast_high >= SOLAR_BANK_TEMP_MIN` (85°F, `hvac_const.py:154`) AND `constraint.mode == "normal"` AND `10 <= hour < 14` | **−3.0°F** (`SOLAR_BANK_OFFSET`, `hvac_const.py:155`; applied `hvac_predict.py:570`) | same 72°F | **YES** (`_get_net_power` `hvac_predict.py:885-900`) |

Both actuate identically through `_execute_zone_pre_cool` → `emit_set_temperature` (direct setpoint write). They are independent branches in `_check_pre_conditioning` and can both fire same-day; their setpoint writes converge toward the same 72°F floor (the second-fired branch may be a no-op if the first already drove the zone to floor, but they DO overlap semantically and write the same channel).

`_get_net_power` is HC-side (`hvac_predict.py:885-900`, reads `self._net_power_entity` injected at HC construction `hvac_predict.py:73,127`). **No new wiring is required** to make weather-pre-cool PV-aware — the predictor already has the signal in hand and uses it for the banking branch.

### 2.2 Prior-art surfaces searched

```
custom_components/universal_room_automation/{const.py, config_flow.py,
  switch.py, sensor.py, button.py, number.py, select.py, binary_sensor.py,
  __init__.py, domain_coordinators/{hvac.py, hvac_predict.py, hvac_const.py,
  energy.py, energy_const.py}}
```

Grep patterns run (verbatim):
- `CONF_HVAC_SOLAR_BANK_ENABLED|solar_banking_enabled|ECSolarBankingSwitch|SOLAR_BANK_OFFSET|SOLAR_BANK_TEMP_MIN|PRECOOL_SOC_MIN|PRECOOL_LEAD_HOURS|_should_solar_bank|_should_weather_pre_cool|_is_solar_banking_enabled|_is_pre_conditioning_enabled|_is_energy_precool_enabled|energy_precool|ENERGY_PRECOOL`
- `HVACPreConditioningSwitch|pre_conditioning_enabled|hvac_pre_conditioning`
- `_get_net_power|net_power_entity`

**`_is_energy_precool_enabled` / `energy_precool` / `ENERGY_PRECOOL` — ZERO matches.** Namespace is clean.

### 2.3 Prior planning docs consulted

- `docs/planning/PLANNING_solar_banking_toggle.md` — **full read.** Authoritative on the EC-device accessor pattern, RestoreEntity vs options-as-truth, the release path's reliance on `HVACCoordinator._last_emitted_range`, and the `banking_enabled` attr surface. This cycle reuses the same release path and same attr-surface pattern (renamed key).
- `docs/planning/PLANNING_hc_precool_toggle_oc_observability.md` — **full read.** Authoritative on the master "28" parent gate, the deferred-restore (Bug Class #52) ceremony for HC-owned switches, and the `pre_conditioning_enabled` attr on the HVAC house-state sensor.
- `docs/planning/PLANNING_v5.7.0_guest_mode_v2.md` — **NOT ON DISK** (operator named the in-progress cycle verbally; no doc found at the expected path). Treated as: this cycle is the next slot after that one ships and does not collide with guest-mode surfaces (different config keys, different device, different code path). If v5.7.0 doc lands and touches `hvac_predict._check_pre_conditioning` or `_execute_zone_pre_cool`, **re-run institutional verification on PR-rebase before build.**
- `docs/planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md` — skim. Unrelated surface.
- `docs/planning/PLANNING_v4.6.2.2_guest_mode_hardening.md` — skim. Unrelated.

### 2.4 Memory bodies pulled

- `feedback_pre_deploy_zero_bugs_gate.md` — applies (syntax + suite-diff gate before deploy).
- `feedback_db_sensitive_3x_targeted_reviews.md` — applies (framing-disjoint protocol; here elevated to four per Tier 3).
- `feedback_fix_lows_in_cycle.md` — applies (do not omnibus-defer LOWs).
- `project_v475_live.md` (Bug Class #46 entity_id stability) — applies to D3 (removing/renaming `ECSolarBankingSwitch`).
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — applies indirectly: this cycle MUST NOT add per-cycle DB write fanout; the gate-flip release path already exists and writes only on transitions.

### 2.5 Design docs read

- `docs/Coordinator/HVAC.md` — if exists, skim the pre-conditioning section. (Planner: do an actual `Read` against this file at build start — not strictly required by the changes here but cheap.)
- `docs/Coordinator/Energy.md` — same.

### 2.6 Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/domain_coordinators/hvac_predict.py` — lines 30-50, 430-712, 880-920 (the entire pre-conditioning method + helpers + `_get_net_power` + `_execute_zone_pre_cool` entry).
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` — lines 60-160 (banking/precool constants + CONF keys).
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — lines 480-515 (EC seeding of `_solar_banking_enabled`), 5691-5720 (property/setter + delivery_rate context).
- `custom_components/universal_room_automation/switch.py` — lines 180-220 (registration block), 820-870 (`_ec_switch_factory` usages incl. `ECSolarBankingSwitch`), 1430-1622 (`HVACPreConditioningSwitch` — the canonical HC-side restore pattern; the new EC switch follows the **EC factory** pattern, not this HC pattern).
- `custom_components/universal_room_automation/config_flow.py` — lines 4280-4600 (HVAC tuning options-flow schema, including `CONF_HVAC_SOLAR_BANK_ENABLED` BooleanSelector at :4567-4572).
- `custom_components/universal_room_automation/__init__.py` — lines 2455-2475 (HC construction passing `pre_conditioning_enabled` from options).

### 2.7 REUSED vs NEW table for proposed additions

| Item | Verdict | Citation |
|---|---|---|
| Switch placement on EC device | **REUSED** | `_ec_switch_factory` (switch.py:758) + `ECSolarBankingSwitch` (switch.py:863) — same factory, same device. |
| Predictor accessor `_is_energy_precool_enabled` | **NEW** | grep shows zero matches. Mirrors `_is_solar_banking_enabled` (`hvac_predict.py:737`) structurally — defaults True if EC not yet registered. |
| EC property/setter `energy_precool_enabled` | **NEW** | grep shows zero matches. Mirrors `solar_banking_enabled` property/setter (`energy.py:5703-5716`). |
| `CONF_ENERGY_PRECOOL_ENABLED` + `DEFAULT_ENERGY_PRECOOL_ENABLED` | **NEW** | grep shows zero matches. Mirrors `CONF_HVAC_SOLAR_BANK_ENABLED` (`hvac_const.py:81`). **Lives in `hvac_const.py`** (same module as the constants it replaces; it's the gate FOR the renamed mechanism). Default migration logic — see D5. |
| `CONF_ENERGY_PRECOOL_OFFSET` + `DEFAULT_ENERGY_PRECOOL_OFFSET` (−2.0 °F) | **NEW** | grep shows zero matches. Operator-configurable per 2026-06-28 directive; replaces the fixed constant from the prior draft. Lives in `hvac_const.py` alongside the gate CONF. |
| Number entity on EC device — pre-cool offset | **NEW** | No equivalent EC-side Number for HVAC pre-cool exists; follows the `_ec_number_factory` pattern if present, else the EC sub-Number registration pattern in `number.py`. Builder verifies the factory site at build start. |
| `CONF_ENERGY_PRECOOL_SCOPE` + `DEFAULT_ENERGY_PRECOOL_SCOPE` (`auto_pv_tiered`) | **NEW** | grep shows zero matches. Three values: `occupied_only` / `whole_house` / `auto_pv_tiered`. Lives in `hvac_const.py`. |
| Select entity on EC device — pre-cool scope | **NEW** | Three-value selector; follows the `_ec_select_factory` pattern if present, else explicit `SelectEntity` subclass on the EC device. Builder verifies at build start. |
| `_should_energy_precool` trigger function | **NEW** | Replaces `_should_weather_pre_cool` + `_should_solar_bank` (both deleted; one unified condition). |
| `_get_net_power()` consumption from weather-pre-cool path | **REUSED** | `hvac_predict.py:885-900` — already exists; the unified trigger calls it. The same signal also drives the `auto_pv_tiered` scope expansion (D1 loop). |
| Release path on gate-flip-OFF (`_release_banked_zones` against `_last_emitted_range` baseline) | **REUSED** | `hvac_predict.py:807-883` + `HVACCoordinator._last_emitted_range` (the existing banking release path). Renamed-tracking-set follows the same lifecycle. |
| Attr surface `energy_precool_enabled` + `energy_precool_zones` + `energy_precool_offset` + `energy_precool_scope` + `energy_precool_scope_effective` on HVAC house-state sensor | **NEW (renames + new)** | Replaces `banking_enabled` + `solar_banking_zones` attrs (`hvac.py:2288-2316`); adds offset + scope (configured + scope effectively applied this cycle). See D3.4 for compat-alias decision. |
| Pre-arrival branch (`hvac_predict.py:612-622`) | **UNTOUCHED** | Stays under master "28" only. D4 regression check. |
| Pre-heat branch (`hvac_predict.py:624-647`) | **UNTOUCHED** | Stays under master "28" only. D4 regression check. |

**One naming-collision check:** `_pre_cool_active` / `_pre_cool_triggered_today` state flags (`hvac_predict.py:459-477`, `:674-675`) currently belong to the weather-pre-cool branch. We **keep these names** for the unified trigger (the flags' semantics — "an energy-pre-cool is in flight today" — apply unchanged). No rename to avoid churn in the release/end-of-window machinery at `:495-499` and `:469-478`.

---

## 3. Falsifiable Invariants

These are the load-bearing properties the cycle MUST guarantee. **Reviewer D MUST attempt to falsify each with a concrete legal-config reachable repro (CONF values + state snapshot that triggers it).**

- **I1 — PV-gated.** In ANY reachable code path, `_execute_zone_pre_cool(..., reason="energy_precool")` is called **only when both** `_is_energy_precool_enabled() == True` **and** `_get_net_power() < ENERGY_PRECOOL_EXPORT_THRESHOLD_W` (i.e. there is real solar surplus). It is NEVER called on the basis of forecast heat alone.
- **I2 — Independence from master "28" pre-heat/pre-arrival.** Toggling `ENERGY_PRE_COOL` OFF does NOT change behavior of pre-arrival warm-up (`hvac_predict.py:612-622`) or pre-heat (`hvac_predict.py:624-647`). Conversely, master "28" remains the kill-switch above the new branch (gate OFF → energy-pre-cool also skipped — defense in depth).
- **I3 — Floor.** No setpoint written by the unified pre-cool path is below `SOLAR_BANK_FLOOR` (72°F) OR within `MIN_DEADBAND` (2°F) of `target_temp_low` — preserved by reusing `_execute_zone_pre_cool` unchanged. **The floor clamp is invariant under any operator-configured `CONF_ENERGY_PRECOOL_OFFSET`** (even an absurd −20°F still clamps at 72°F).
- **I4 — Toggle migration.** After the v5.7.1 upgrade lands:
  - `CONF_HVAC_SOLAR_BANK_ENABLED` is REMOVED from the config-flow schema, the `ECSolarBankingSwitch` entity is unregistered, the EC `solar_banking_enabled` property is removed.
  - The new `CONF_ENERGY_PRECOOL_ENABLED` is **seeded from the prior `CONF_HVAC_SOLAR_BANK_ENABLED` value** on first start of v5.7.1 (i.e. an operator who had banking OFF gets energy-pre-cool OFF; default for new installs is **ON**).
  - The migration is **idempotent** (running upgrade logic twice does not flip the user's choice back to default).
- **I5 — One-cycle release on flip-OFF.** Flipping `ENERGY_PRE_COOL` OFF mid-window releases all currently-pre-cooled zones to their baseline within one `_check_pre_conditioning` cycle (parity with the v4.7-era banking release path).
- **I6 — Scope: whole-house ONLY under real export surplus.** When `CONF_ENERGY_PRECOOL_SCOPE == auto_pv_tiered`, unoccupied zones receive `_execute_zone_pre_cool(reason="energy_precool")` ONLY when `_get_net_power() < -ENERGY_PRECOOL_EXPORT_THRESHOLD_W` AT THE MOMENT OF the per-zone dispatch (re-check, not cached from the trigger gate). When `CONF_ENERGY_PRECOOL_SCOPE == occupied_only`, unoccupied zones are NEVER pre-cooled regardless of surplus. When `CONF_ENERGY_PRECOOL_SCOPE == whole_house`, the operator has explicitly opted into unconditional whole-house banking (still respects I1/I3).
- **I7 — Offset honored.** The offset applied at `_execute_zone_pre_cool` equals `CONF_ENERGY_PRECOOL_OFFSET` from EC (within one event-loop tick of an operator change), bounded only by I3's floor clamp.

---

## 4. Tier Classification

**Tier 3** (operator-elevated 2026-06-28 from Tier 2-DB).
- Cross-coordinator EC↔HC (trust-hierarchy ripple).
- Strategy / decision-logic change affecting energy cost and comfort.
- Touches a long-standing path (banking + weather pre-cool shipped in v3.17.0; banking gate shipped in v4.7-era).
- Migrates persisted operator-set config state (`CONF_HVAC_SOLAR_BANK_ENABLED` → `CONF_ENERGY_PRECOOL_ENABLED`).
- The cycle threads a **configurable offset** AND a **tri-valued scope** through a per-zone loop consumed by every zone — single-missed-path failure mode (Bug Class #53). This is precisely the pattern that justified Tier 3 in v5.5.3 (D-HIGH-1).

**Four framing-disjoint reviews (run in parallel):**

- **Review A — Local correctness + PV gate.** `_should_energy_precool` arithmetic & gating; offset reconciliation defensible; the configurable `CONF_ENERGY_PRECOOL_OFFSET` read is correct (default applied when option missing; numeric coercion safe); PRECOOL_SOC_MIN floor preserved; net-power sign convention correct (negative = export); season gating intact; hour window correct; `triggered_today` flap-prevention preserved. Per-zone scope branch arithmetic (occupied_only / whole_house / auto_pv_tiered) per-site correct.
- **Review B — Migration correctness + signal-chain integrity.** `CONF_HVAC_SOLAR_BANK_ENABLED` → `CONF_ENERGY_PRECOOL_ENABLED` value migration is idempotent and runs on entry-load before EC/HC are constructed; old switch entity is cleanly unregistered (Bug Class #46 — old `unique_id` `{DOMAIN}_energy_solar_banking` removed from the entity registry, not orphaned); new Number (`energy_precool_offset`) and Select (`energy_precool_scope`) round-trip through options + RestoreEntity + EC ready-signal deferred restore (Bug Class #52); attribute renames on the HVAC house-state sensor do not break consumers (dashboards, OC, Bayesian readers); release path on flip-OFF preserves `_last_emitted_range` semantics; master "28" parent-gate semantics unchanged.
- **Review C — New surfaces + test authority via real per-site source mutation.** New EC switch + Number + Select each round-trip through options + RestoreEntity (Bug Class #52). Per-site mutation tests: mutate the PV gate → a specific test must fail; mutate the SOC gate → a different specific test must fail; mutate the toggle gate → another specific test must fail; **mutate the per-zone scope branch (occupied_only / whole_house / auto_pv_tiered) → a SPECIFIC test must fail per branch**; **mutate the offset-read line (force a hardcoded value) → a specific test must fail**. A site whose bypass leaves the suite green is unacceptable. Config-flow / EC factory schema fields MUST be extracted from `hvac_const.py` constants (not literal strings) in tests.
- **Review D — Adversarial completeness / diff-blind.** Sole job: state I1–I7 in falsifiable form, then BREAK them. Re-enumerate the ENTIRE invariant surface — including pre-existing code, not just the diff (v5.5.3 D-HIGH-1 precedent). Every flagged leak must come with a **concrete, legal-config reachable repro** (the CONF values + state that trigger it). Specifically: enumerate every site that calls `_execute_zone_pre_cool` and verify each is gated by either the master "28" or the unified PV+toggle gate (I1/I2); enumerate every place the offset is read and confirm it sources from EC (I7); enumerate every per-zone scope decision and confirm the `auto_pv_tiered` branch re-checks `_get_net_power()` at dispatch time (I6, not cached); confirm I3's floor clamps an absurd operator-configured offset.

Run the four reviews in PARALLEL — different framings can't share blind spots.

**Mandatory operator pre-deploy checkpoint (Tier 3 requirement):** After the four reviews close and orchestrator independent verification (re-grep every `_execute_zone_pre_cool` site + re-run real source mutation on each of: the unified gate, the per-zone scope branches, the offset-read), surface the I1–I7 proof to the operator before invoking `deploy.sh`. Do not deploy on reviewer-summary trust alone.

If the 4th pass (or any) finds a CRITICAL/HIGH: fix, then re-verify the fixed site with its own mutation-anchored test AND re-run D's completeness enumeration (a fix can reveal an N+1th site).

---

## 5. Deliverables

### D1 · Unify weather-pre-cool and solar-banking triggers into one PV-aware `_should_energy_precool` (with configurable offset + scope)

**Changes:**
- `domain_coordinators/hvac_predict.py`
  - **DELETE** `_should_weather_pre_cool` (lines 656-681).
  - **DELETE** `_should_solar_bank` (lines 683-712).
  - **ADD** `_should_energy_precool(self, constraint, now) -> bool` with the unified gating below.
  - Inside `_check_pre_conditioning` (`hvac_predict.py:430+`):
    - **DELETE** the weather-pre-cool dispatch block (`:488-494`).
    - **DELETE** the entire solar-banking dispatch+reconcile block (`:501-610`) — including:
      - `banking_gate_on = self._is_solar_banking_enabled()` (`:520`)
      - first-eval reconciliation (`:522-556`)
      - flip-OFF release (`:558-566`)
      - the `if banking_gate_on and self._should_solar_bank(...)` loop (`:568-576`)
      - the prune-against-live-setpoint block (`:578-610`)
    - **ADD** a single unified dispatch block immediately after the master-"28" gate check at `:480-483`:
      ```python
      # ----- Energy Saver Pre-Cool (unified, PV-aware, scope-aware) -----
      precool_gate_on = self._is_energy_precool_enabled()
      # Symmetric first-eval restart reconciliation (RAM-only tracking set
      # → orphan-zone release on restart-with-gate-OFF). Identical shape
      # to the deleted banking reconciliation; tracking-set name changes.
      if not self._first_eval_done:
          self._first_eval_done = True
          if not precool_gate_on:
              # ... (orphan scan + release; logic identical to deleted block) ...
          self._last_precool_gate_enabled = precool_gate_on
      if (
          not precool_gate_on
          and self._last_precool_gate_enabled
          and self._last_precool_zones
      ):
          await self._release_banked_zones(set(self._last_precool_zones))
          self._last_precool_zones = set()
      self._last_precool_gate_enabled = precool_gate_on

      # Trigger evaluation + per-zone scope dispatch.
      if precool_gate_on and self._should_energy_precool(constraint, now):
          # Read operator-configured offset + scope from EC (single read per
          # cycle; both are coordinator properties hydrated from options +
          # live Number/Select setter writes).
          offset_f = self._get_energy_precool_offset()
          scope = self._get_energy_precool_scope()  # one of:
              # ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY,
              # ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE,
              # ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED
          # auto_pv_tiered: re-check net power at dispatch time to decide
          # whether to expand to unoccupied zones (I6 requires re-check, not
          # cached from the gate). Net power at this moment is "real surplus
          # right now"; cheap to read.
          net_power_now = self._get_net_power()
          export_surplus = net_power_now < -ENERGY_PRECOOL_EXPORT_THRESHOLD_W

          for zone_id, zone in self._zone_manager.zones.items():
              is_occupied = self._zone_is_occupied(zone)
              if scope == ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY:
                  if not is_occupied:
                      continue  # comfort-first; never bank empty zones
              elif scope == ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED:
                  # Default: occupied always; unoccupied ONLY under real
                  # export surplus (the operator-coined "free banking" case).
                  if not is_occupied and not export_surplus:
                      continue
              # ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE: no per-zone gate; bank all.

              await self._execute_zone_pre_cool(
                  zone, offset=offset_f, reason="energy_precool",
              )
              self._pre_conditioning_zones.add(zone_id)
              self._last_precool_zones.add(zone_id)
      ```
  - **RENAME** instance tracking sets:
    - `_solar_banking_zones` → `_energy_precool_zones`
    - `_last_banked_zones` → `_last_precool_zones`
    - `_last_banking_gate_enabled` → `_last_precool_gate_enabled`
    (Search for ALL references; ~10 sites. The rename is mechanical; the lifecycle stays identical.)

**Unified gate (`_should_energy_precool`):**

```python
def _should_energy_precool(self, constraint, now) -> bool:
    """Unified PV + weather trigger for energy pre-cool.

    PV surplus is REQUIRED — no pure-forecast-heat trigger. Forecast
    heat raises aggressiveness (lower SOC threshold) when also solar-rich.
    """
    if constraint is None:
        return False
    season = self._preset_manager.current_season
    if season not in (SEASON_SUMMER, SEASON_SHOULDER):
        return False
    if self._pre_cool_active and now.hour < PEAK_HOUR_START:
        return True  # already in-flight, stay engaged until peak
    if self._pre_cool_active or self._pre_cool_triggered_today:
        return False  # daily-once guard (same as weather-pre-cool)

    hour = now.hour
    # Wider window: union of {10..14} (banking) and {12..14} (weather).
    if not (ENERGY_PRECOOL_HOUR_START <= hour < PEAK_HOUR_START):
        return False

    forecast_high = constraint.forecast_high_temp
    soc = constraint.soc
    net_power = self._get_net_power()

    # I1 — PV surplus is REQUIRED.
    if net_power >= -ENERGY_PRECOOL_EXPORT_THRESHOLD_W:
        return False

    # SOC floor — must have enough battery to safely cool from house mass.
    is_hot = (
        forecast_high is not None
        and forecast_high >= self._precool_forecast_high
    )
    soc_floor = (
        PRECOOL_SOC_MIN if is_hot else self._solar_bank_soc_min
    )
    if soc is not None and soc < soc_floor:
        return False

    if getattr(constraint, "mode", "normal") != "normal":
        return False

    self._pre_cool_active = True
    self._pre_cool_triggered_today = True
    _LOGGER.info(
        "Energy Saver Pre-Cool triggered: forecast_high=%s, hour=%d, "
        "soc=%s, net_power=%.0fW (exporting), is_hot=%s, soc_floor=%d",
        forecast_high, hour, soc, net_power, is_hot, soc_floor,
    )
    return True
```

**Note on gating logic asymmetry:** With `is_hot=True` we use the **lower** SOC floor (30%) because on a hot day we WANT to bank aggressively even if the battery is not full — the cost of running AC during peak >> the cost of partially draining the battery midday. With `is_hot=False` we use the **higher** SOC floor (95%) because we only bank for grid-export-avoidance reasons. Review A must scrutinize this asymmetry.

**Offset value:** the offset applied at `_execute_zone_pre_cool` is now the operator-configured `CONF_ENERGY_PRECOOL_OFFSET` (default −2.0°F), NOT a hardcoded constant. The 72°F floor (`SOLAR_BANK_FLOOR`) still clamps the result (I3).

#### D1.1 · New constants

In `hvac_const.py` (additive, near the existing precool block):

```python
# ---------- Energy Saver Pre-Cool (v5.7.1 unification) ----------
# Working name (user-facing); the CONSTANT NAME stays ENERGY_PRECOOL_NAME
# and is the single source for the display string (rename is one-line +
# strings.json / translations/en.json).
ENERGY_PRECOOL_NAME: Final = "Energy Saver Pre-Cool"

CONF_ENERGY_PRECOOL_ENABLED: Final = "energy_precool_enabled"
DEFAULT_ENERGY_PRECOOL_ENABLED: Final = True

# Operator-configurable pre-cool offset (°F from target_temp_high).
# Default = -2.0 (per operator 2026-06-28: "make the space not too cold
# suddenly"). Sign convention: negative = cooler. The 72°F floor still
# clamps the resulting setpoint (I3) — an absurd configured value cannot
# breach the floor.
CONF_ENERGY_PRECOOL_OFFSET: Final = "energy_precool_offset"
DEFAULT_ENERGY_PRECOOL_OFFSET: Final = -2.0
ENERGY_PRECOOL_OFFSET_MIN: Final = -5.0  # NumberSelector min
ENERGY_PRECOOL_OFFSET_MAX: Final = 0.0   # NumberSelector max
ENERGY_PRECOOL_OFFSET_STEP: Final = 0.5

# Operator-configurable pre-cool scope.
CONF_ENERGY_PRECOOL_SCOPE: Final = "energy_precool_scope"
ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY: Final = "occupied_only"
ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE: Final = "whole_house"
ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED: Final = "auto_pv_tiered"
ENERGY_PRECOOL_SCOPE_VALUES: Final = (
    ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY,
    ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE,
    ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED,
)
# Default = auto_pv_tiered (occupied-only normally; expand to whole-house
# only when there is real export surplus → banking everywhere is free).
DEFAULT_ENERGY_PRECOOL_SCOPE: Final = ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED

# Net-power threshold: must be exporting more than this (W) to qualify
# as "real solar surplus". Sign convention: negative = exporting.
# Inherited from the deleted SOLAR_BANK threshold (was hardcoded as
# `< -500` at hvac_predict.py:707). Also used by the auto_pv_tiered
# scope's per-zone re-check at dispatch time (I6).
ENERGY_PRECOOL_EXPORT_THRESHOLD_W: Final = 500.0

# Hour window. Union of the two deleted windows:
#   banking: [10, 14)
#   weather: [12, 14)
# Unified window: [10, 14). End is PEAK_HOUR_START.
ENERGY_PRECOOL_HOUR_START: Final = 10
```

The 72°F floor (`SOLAR_BANK_FLOOR`) and `PRECOOL_SOC_MIN` (30%) and `self._solar_bank_soc_min` (configurable, default 95%) constants are **REUSED** unchanged.

#### D1.2 · Accessor `_is_energy_precool_enabled` + offset/scope getters

In `hvac_predict.py`, add alongside `_is_solar_banking_enabled` (which is itself deleted in D3):

```python
def _is_energy_precool_enabled(self) -> bool:
    """Master operator gate for the unified energy-pre-cool branch.

    Reads `energy_precool_enabled` from the EnergyCoordinator via the
    coordinator_manager registry. Defaults to True when EC is not yet
    registered — fail-safe (same as the deleted _is_solar_banking_enabled).
    """
    try:
        from ..const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        energy = manager.coordinators.get("energy") if (
            manager is not None and hasattr(manager, "coordinators")
        ) else None
        if energy is None:
            return True
        return bool(getattr(energy, "energy_precool_enabled", True))
    except Exception:
        return True

def _get_energy_precool_offset(self) -> float:
    """Operator-configured pre-cool offset (°F). Defaults to
    DEFAULT_ENERGY_PRECOOL_OFFSET when EC not yet registered."""
    try:
        from ..const import DOMAIN
        from .hvac_const import DEFAULT_ENERGY_PRECOOL_OFFSET
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        energy = manager.coordinators.get("energy") if (
            manager is not None and hasattr(manager, "coordinators")
        ) else None
        if energy is None:
            return DEFAULT_ENERGY_PRECOOL_OFFSET
        return float(getattr(energy, "energy_precool_offset",
                             DEFAULT_ENERGY_PRECOOL_OFFSET))
    except Exception:
        return DEFAULT_ENERGY_PRECOOL_OFFSET

def _get_energy_precool_scope(self) -> str:
    """Operator-configured pre-cool scope (one of the three values)."""
    try:
        from ..const import DOMAIN
        from .hvac_const import (
            DEFAULT_ENERGY_PRECOOL_SCOPE,
            ENERGY_PRECOOL_SCOPE_VALUES,
        )
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        energy = manager.coordinators.get("energy") if (
            manager is not None and hasattr(manager, "coordinators")
        ) else None
        if energy is None:
            return DEFAULT_ENERGY_PRECOOL_SCOPE
        scope = getattr(energy, "energy_precool_scope",
                        DEFAULT_ENERGY_PRECOOL_SCOPE)
        if scope not in ENERGY_PRECOOL_SCOPE_VALUES:
            return DEFAULT_ENERGY_PRECOOL_SCOPE
        return scope
    except Exception:
        return DEFAULT_ENERGY_PRECOOL_SCOPE
```

#### D1.3 · Offset default — justification

The deleted offsets were −2.0°F (weather) and −3.0°F (banking). Operator complaint: "it gets too cold when it works well" → argues for the less aggressive value, AND the operator explicitly named −2.0°F as the new default ("Default can be 2F to make the space not too cold suddenly"). **Chosen default: −2.0°F**, and the operator can now tune up or down via the EC Number entity without a redeploy.

#### D1.4 · Acceptance criteria — D1

- **Verify:** `_should_weather_pre_cool` and `_should_solar_bank` are deleted (grep shows zero matches in `custom_components/`).
- **Verify:** `_should_energy_precool` exists and is called from exactly ONE site inside `_check_pre_conditioning`.
- **Verify:** `_should_energy_precool` calls `self._get_net_power()` and returns False when `net_power >= -ENERGY_PRECOOL_EXPORT_THRESHOLD_W`.
- **Verify:** the per-zone dispatch loop reads BOTH `_get_energy_precool_offset()` AND `_get_energy_precool_scope()` once per trigger cycle; the `auto_pv_tiered` branch re-reads `_get_net_power()` at dispatch time (not cached from the gate) — confirms I6.
- **Sensor:** `sensor.ura_hvac_coordinator_hvac_house_state` carries the attributes `energy_precool_zones` (list), `energy_precool_enabled` (bool), `energy_precool_offset` (float configured), `energy_precool_scope` (string configured), `energy_precool_scope_effective` (string: one of `occupied_only` / `whole_house` / `auto_pv_tiered`-with-suffix indicating whether tier expanded this cycle, e.g. `auto_pv_tiered(expanded)` vs `auto_pv_tiered(occupied_only)`). Old `solar_banking_zones` / `banking_enabled` attrs are gone (no compat alias).
- **Test:** `test_energy_precool_pv_gate.py` — drives the real `_check_pre_conditioning` with spec'd EC + zone fakes through SIX cases:
  - (a) PV surplus + hot forecast + SOC 60% + season summer + hour 13 → fires (`_pre_cool_active=True`, `_execute_zone_pre_cool` called with offset=configured-default).
  - (b) Hot forecast + SOC 95% + season summer + hour 13 + **no PV surplus** (`net_power = -100W`) → does **NOT** fire (I1 falsification target).
  - (c) PV surplus + cool forecast + SOC 60% (below the 95% floor for the cool-day branch) + hour 13 → does NOT fire.
  - (d) PV surplus + cool forecast + SOC 96% + hour 13 → fires.
  - (e) PV surplus + hot forecast + hour 09 (outside window) → does NOT fire.
  - (f) PV surplus + hot forecast + `constraint.mode = "peak"` → does NOT fire.
- **Test:** `test_energy_precool_offset_configurable.py` — confirms (a) default offset −2.0°F is used when no operator override; (b) flipping EC `energy_precool_offset = -3.5` propagates to the next `_execute_zone_pre_cool` call within one event-loop tick; (c) offset is clamped by the 72°F floor (I3) even when configured to an absurd −20°F.
- **Test:** `test_energy_precool_scope.py` — six cases covering the scope matrix:
  - `occupied_only` + occupied zone + PV surplus → fires for that zone.
  - `occupied_only` + unoccupied zone + PV surplus → does NOT fire for that zone (I6).
  - `whole_house` + unoccupied zone + PV surplus → fires (operator opted in).
  - `auto_pv_tiered` + unoccupied zone + `net_power = -2000W` (real surplus) → fires (I6 expansion).
  - `auto_pv_tiered` + unoccupied zone + `net_power = -200W` (gate-side surplus barely, but dispatch-time fails the threshold) → does NOT fire (proves dispatch-time re-check).
  - `auto_pv_tiered` + occupied zone + minimal surplus → fires (occupied always banks when the trigger fires).
- **Test:** mutation — replace the per-zone scope branch with `pass` (no skip) → the `occupied_only`-skip test MUST fail. Replace the dispatch-time `_get_net_power()` re-check with a cached value → the auto_pv_tiered dispatch-time-fail test MUST fail.
- **Test:** `test_energy_precool_offset_and_floor.py` — pre-cool writes operator-configured offset and never drops below 72°F.
- **Live:** during the next solar-rich day (post-deploy), `sensor.ura_hvac_coordinator_hvac_house_state` shows `energy_precool_zones` populated with at least one zone between 10:00 and 14:00 local, with concurrent `sensor.envoy_*_net_power` reading < −500W AND `energy_precool_offset` matching the EC Number value AND `energy_precool_scope_effective` reflecting the chosen scope (and whether `auto_pv_tiered` expanded).
- **Live:** operator changes the EC Number `Energy Saver Pre-Cool Offset` from −2.0 to −1.5; within one HC cycle a subsequent `_execute_zone_pre_cool` call uses −1.5 (visible via INFO log line + sensor attribute).
- **Live:** operator flips the EC Select scope from `auto_pv_tiered` to `occupied_only`; an unoccupied zone that was being banked on the prior cycle is released (or simply not re-banked) on the next cycle.

---

### D2 · Dedicated `Energy Saver Pre-Cool` toggle + Offset Number + Scope Select on the EC device

**Changes:**
- `switch.py`
  - **ADD** (using `_ec_switch_factory`, alongside the other EC sub-switches at `switch.py:185-195`):
    ```python
    ECEnergyPreCoolSwitch = _ec_switch_factory(
        "energy_precool_enabled",   # attr_name on EnergyCoordinator
        "energy_precool",            # unique_id suffix → {DOMAIN}_energy_energy_precool
        ENERGY_PRECOOL_NAME,         # "Energy Saver Pre-Cool" (import from hvac_const)
        "mdi:snowflake-thermometer", # icon
        default=DEFAULT_ENERGY_PRECOOL_ENABLED,  # True
    )
    ```
  - **REGISTER** in the EC switch list in `async_setup_entry`. Position: replace the line that registered `ECSolarBankingSwitch(hass, entry)` at `switch.py:195`. Entity_id is **new** because the slug differs — see D3 for the disposal of the old entity.
- `number.py`
  - **ADD** an EC-device Number entity for the pre-cool offset. Follow whichever existing pattern is canonical for EC-device Numbers (e.g. an `_ec_number_factory` if present, else a direct `NumberEntity` subclass mirroring the EC switch factory's device-binding pattern). The entity:
    - unique_id suffix: `energy_precool_offset` → `{DOMAIN}_energy_energy_precool_offset`
    - display name: `"Energy Saver Pre-Cool Offset"`
    - device_class: `temperature`
    - unit: `°F`
    - min/max/step: `ENERGY_PRECOOL_OFFSET_MIN` (−5.0), `ENERGY_PRECOOL_OFFSET_MAX` (0.0), `ENERGY_PRECOOL_OFFSET_STEP` (0.5)
    - default: `DEFAULT_ENERGY_PRECOOL_OFFSET` (−2.0)
    - setter writes through to `EnergyCoordinator.energy_precool_offset` and persists to options on change (via the same write-back pattern used by other EC Numbers; builder cites the pattern site at build start).
    - RestoreEntity + EC ready-signal deferred restore per Bug Class #52.
- `select.py`
  - **ADD** an EC-device Select entity for the pre-cool scope.
    - unique_id suffix: `energy_precool_scope` → `{DOMAIN}_energy_energy_precool_scope`
    - display name: `"Energy Saver Pre-Cool Scope"`
    - options: `ENERGY_PRECOOL_SCOPE_VALUES` (the three constants)
    - default: `DEFAULT_ENERGY_PRECOOL_SCOPE` (`auto_pv_tiered`)
    - setter writes through to `EnergyCoordinator.energy_precool_scope` and persists to options.
    - RestoreEntity + EC ready-signal deferred restore per Bug Class #52.
    - Translation keys for the three option values in `strings.json` + `translations/en.json` (e.g. `Occupied zones only` / `Whole house` / `Auto (PV-tiered)`).
- `domain_coordinators/energy.py`
  - **ADD** property/setter `energy_precool_enabled` (modeled on `solar_banking_enabled` at `energy.py:5703-5716`).
  - **ADD** property/setter `energy_precool_offset` (float).
  - **ADD** property/setter `energy_precool_scope` (str; setter validates against `ENERGY_PRECOOL_SCOPE_VALUES`, falls back to default on invalid).
  - **ADD** `self._energy_precool_enabled`, `self._energy_precool_offset`, `self._energy_precool_scope` initialization in `__init__` near line 508:
    ```python
    from .hvac_const import (
        CONF_ENERGY_PRECOOL_ENABLED,
        DEFAULT_ENERGY_PRECOOL_ENABLED,
        CONF_ENERGY_PRECOOL_OFFSET,
        DEFAULT_ENERGY_PRECOOL_OFFSET,
        CONF_ENERGY_PRECOOL_SCOPE,
        DEFAULT_ENERGY_PRECOOL_SCOPE,
        ENERGY_PRECOOL_SCOPE_VALUES,
    )
    self._energy_precool_enabled: bool = bool(ec.get(
        CONF_ENERGY_PRECOOL_ENABLED, DEFAULT_ENERGY_PRECOOL_ENABLED,
    ))
    self._energy_precool_offset: float = float(ec.get(
        CONF_ENERGY_PRECOOL_OFFSET, DEFAULT_ENERGY_PRECOOL_OFFSET,
    ))
    raw_scope = ec.get(CONF_ENERGY_PRECOOL_SCOPE, DEFAULT_ENERGY_PRECOOL_SCOPE)
    self._energy_precool_scope: str = (
        raw_scope if raw_scope in ENERGY_PRECOOL_SCOPE_VALUES
        else DEFAULT_ENERGY_PRECOOL_SCOPE
    )
    ```
- `config_flow.py`
  - **REPLACE** the `CONF_HVAC_SOLAR_BANK_ENABLED` BooleanSelector field (lines 4567-4572) with the new `CONF_ENERGY_PRECOOL_ENABLED` BooleanSelector. Keep helper text honest: install-time seed; runtime source-of-truth is the EC sub-switch.
  - **REMOVE** the `CONF_HVAC_SOLAR_BANK_ENABLED` import (line 4302). **ADD** the new CONF/DEFAULT imports for enabled + offset + scope.
  - *Config-flow does NOT need to surface the offset Number or scope Select itself* — both are post-setup EC-device entities. (The factory's standard pattern: install seeds the default; entity is the runtime knob.)
- `strings.json` + `translations/en.json`
  - **ADD** display name + description for the new switch (`entity.switch.energy_precool`), Number (`entity.number.energy_precool_offset`), and Select (`entity.select.energy_precool_scope` plus its three option labels).
  - **REMOVE** the `solar_banking` entries.

**Important:** All three new entities (switch + Number + Select) live on the **EC device** because the operator-confirmed pattern is "config follows the feature → EC." The HC predictor reads the EC gate/offset/scope via the accessors in D1.2.

**Acceptance criteria — D2:**
- **Verify:** new entity `switch.ura_energy_energy_precool` (unique_id `{DOMAIN}_energy_energy_precool`) appears on the "URA: Energy Coordinator" device after restart.
- **Verify:** new entity `number.ura_energy_energy_precool_offset` appears on the same device, default −2.0°F, min −5.0, max 0.0, step 0.5.
- **Verify:** new entity `select.ura_energy_energy_precool_scope` appears on the same device, default `auto_pv_tiered`, three options.
- **Verify:** flipping the switch / changing the Number / changing the Select each updates the corresponding `EnergyCoordinator` property within one event-loop tick.
- **Verify:** all three persist across HA restart (RestoreEntity + options write-back + EC ready-signal deferred restore).
- **Test:** `test_energy_precool_switch_roundtrip.py` — RestoreEntity replay + SIGNAL_ENERGY_COORDINATOR_READY deferred-restore + options write-back. Mirrors `test_solar_banking_toggle.py` D4.
- **Test:** `test_energy_precool_offset_number_roundtrip.py` — same shape, for the Number; includes clamp test (setting 1.0 above max snaps to max).
- **Test:** `test_energy_precool_scope_select_roundtrip.py` — same shape, for the Select; includes invalid-value test (corrupt restored state → defaults to `auto_pv_tiered`).
- **Test:** mutation — comment out the `precool_gate_on = self._is_energy_precool_enabled()` line in `_check_pre_conditioning` and replace with `precool_gate_on = True`. The toggle-OFF gate test MUST fail. Same pattern for `_get_energy_precool_offset` (replace with hardcoded −2.5; the configured-offset propagation test MUST fail) and `_get_energy_precool_scope` (replace with hardcoded `whole_house`; the `occupied_only` skip test MUST fail).
- **Live:** flip the switch OFF from the device card. Within one HC decision cycle (default ~60s), `energy_precool_zones` empties AND `energy_precool_enabled` attr reads `false`.
- **Live:** change the Number from −2.0 to −1.5; next pre-cool dispatch writes the new offset (visible in INFO log + `energy_precool_offset` attr).
- **Live:** change the Select from `auto_pv_tiered` to `occupied_only`; a previously-banked unoccupied zone is released or not re-banked.

---

### D3 · Retire the old solar-banking mechanism

**Changes:**
- `domain_coordinators/hvac_predict.py` — already handled in D1 (the `_should_solar_bank` function + the banking dispatch block in `_check_pre_conditioning` are deleted).
- `domain_coordinators/hvac_predict.py` — **DELETE** `_is_solar_banking_enabled` (lines 737-757). No more callers.
- `domain_coordinators/energy.py` — **DELETE** `solar_banking_enabled` property/setter (lines 5702-5716) **AND** the `_solar_banking_enabled` `__init__` seeding (lines 499-510). D5 handles the migration of the old value into the new field.
- `switch.py`
  - **DELETE** `ECSolarBankingSwitch = _ec_switch_factory(...)` (lines 859-869).
  - **DELETE** the `ECSolarBankingSwitch(hass, entry),` registration (line 195) — already moved to its replacement in D2.
  - **ADD** explicit entity-registry cleanup in `__init__.async_setup_entry`: scan for the orphan unique_id `{DOMAIN}_energy_solar_banking` and remove it from the entity registry (Bug Class #46). **Run once per process; gated by a small `data["solar_banking_cleanup_done"]` marker so it does not loop on reload.**
- `config_flow.py` — already handled in D2 (field deleted).
- `hvac_const.py` — **DELETE** `CONF_HVAC_SOLAR_BANK_ENABLED` and `DEFAULT_HVAC_SOLAR_BANK_ENABLED` (lines 75-82). The `SOLAR_BANK_*` constants for floor / SOC min / temp min / offset are **PARTIALLY** retained:
  - `SOLAR_BANK_FLOOR` (72°F) — **KEEP**, used by `_execute_zone_pre_cool`.
  - `SOLAR_BANK_SOC_MIN` (95%) — **KEEP**, referenced by `CONF_HVAC_SOLAR_BANK_SOC_MIN` config knob.
  - `SOLAR_BANK_TEMP_MIN` (85°F) — **DELETE**, no longer referenced.
  - `SOLAR_BANK_OFFSET` (−3.0°F) — **DELETE**, replaced by operator-configured `CONF_ENERGY_PRECOOL_OFFSET`.
- `__init__.py` — no changes needed (the existing HC construction at lines 2455-2475 does not read `CONF_HVAC_SOLAR_BANK_ENABLED` — banking was EC-side).
- `hvac.py` (lines 2288-2316) — **REPLACE** the `solar_banking_zones` + `banking_enabled` attr-build block with `energy_precool_zones` + `energy_precool_enabled` + `energy_precool_offset` + `energy_precool_scope` + `energy_precool_scope_effective`. No compat aliases — Reviewer B confirms no in-tree consumer reads the old keys.
- `translations/en.json` + `strings.json` — **DELETE** the `solar_banking` entries; **ADD** `energy_precool` switch/number/select entries.

**Acceptance criteria — D3:**
- **Verify:** `grep -r "solar_banking\|SOLAR_BANK_OFFSET\|SOLAR_BANK_TEMP_MIN\|CONF_HVAC_SOLAR_BANK_ENABLED\|_should_solar_bank\|_is_solar_banking_enabled" custom_components/` returns zero matches.
- **Verify:** the entity `switch.ura_energy_solar_banking` is GONE from the entity registry post-restart.
- **Sensor:** `sensor.ura_hvac_coordinator_hvac_house_state` no longer carries `solar_banking_zones` or `banking_enabled` attrs.
- **Test:** `test_v5_7_1_solar_banking_retired.py` — asserts the deleted symbols are not importable.
- **Test:** entity-registry cleanup is idempotent.
- **Live:** post-restart, the HA UI "Devices → URA: Energy Coordinator" shows the new "Energy Saver Pre-Cool" switch + "Energy Saver Pre-Cool Offset" Number + "Energy Saver Pre-Cool Scope" Select, and no longer shows "Solar HVAC Banking".

---

### D4 · Regression confirmation — pre-arrival warm-up + pre-heat UNAFFECTED

**No code changes.** Verification + test surface.

- `quality/tests/test_v5_7_1_pre_arrival_preheat_unchanged.py` (NEW):
  - **Test A:** master "28" ON + `CONF_ENERGY_PRECOOL_ENABLED` OFF → pre-arrival branch still fires.
  - **Test B:** master "28" ON + `CONF_ENERGY_PRECOOL_ENABLED` OFF + winter + within pre-heat window → `_execute_pre_heat()` is called.
  - **Test C:** master "28" OFF + `CONF_ENERGY_PRECOOL_ENABLED` ON → NEITHER pre-arrival NOR pre-heat NOR energy-pre-cool fires (defense in depth).
  - **Test D:** byte-identical pre-arrival emit shape vs develop tip.

**Acceptance criteria — D4:**
- **Verify:** the pre-arrival dispatch block (`hvac_predict.py:612-622`) is byte-identical to develop tip.
- **Verify:** the pre-heat dispatch block (`hvac_predict.py:624-647`) is byte-identical.
- **Verify:** master "28" gate check at `:434` and `:480` is unchanged.
- **Test:** the four tests above all PASS.
- **Live:** observe existing pre-heat (if winter) or pre-arrival INFO log lines firing on the same triggers as before.

---

### D5 · Config migration of the old toggle value

**Changes:**
- `__init__.py` `async_migrate_entry`:
  ```python
  # v5.7.1: migrate CONF_HVAC_SOLAR_BANK_ENABLED → CONF_ENERGY_PRECOOL_ENABLED.
  OLD_KEY = "hvac_solar_bank_enabled"
  NEW_KEY = "energy_precool_enabled"
  if OLD_KEY in entry.options and NEW_KEY not in entry.options:
      new_options = dict(entry.options)
      new_options[NEW_KEY] = bool(new_options.pop(OLD_KEY))
      hass.config_entries.async_update_entry(entry, options=new_options)
      _LOGGER.info(
          "v5.7.1 migration: hvac_solar_bank_enabled=%s → "
          "energy_precool_enabled=%s (entry %s)",
          new_options[NEW_KEY], new_options[NEW_KEY], entry.entry_id,
      )
  ```
- Offset + Scope: **no migration needed** — these are new knobs with sensible defaults. First start hydrates them from defaults; operator can tune via the EC entities.
- This MUST run **before** `EnergyCoordinator.__init__` reads its options. Verify the `async_migrate_entry` signature + `manifest.json` version at build start.

**Acceptance criteria — D5:**
- **Verify:** an entry whose options carry `hvac_solar_bank_enabled: false` → after upgrade, `energy_precool_enabled: false` AND no `hvac_solar_bank_enabled` AND `energy_precool_offset: -2.0` AND `energy_precool_scope: auto_pv_tiered` (defaults).
- **Verify:** an entry whose options carry `hvac_solar_bank_enabled: true` → migrates to `energy_precool_enabled: true`.
- **Verify:** fresh install → `energy_precool_enabled=True`, `energy_precool_offset=-2.0`, `energy_precool_scope=auto_pv_tiered`.
- **Verify:** migration is idempotent.
- **Test:** `test_v5_7_1_solar_banking_migration.py` — three cases above + idempotency.
- **Live:** operator's actual entry → switch ON, Number reads −2.0, Select reads `auto_pv_tiered` (or whatever the operator subsequently sets), no orphan `hvac_solar_bank_enabled` key.

---

## 6. Edge cases / known hazards

Cross-referenced against `docs/QUALITY_CONTEXT.md`:

- **Bug Class #5 (startup race):** new EC entities must defer restore via `SIGNAL_ENERGY_COORDINATOR_READY` if EC is not yet registered. Verify factories implement this.
- **Bug Class #46 (entity-id stability):** the rename `solar_banking` → `energy_precool` creates new unique_ids. The OLD switch entity must be deleted from the entity registry. D3 specifies the cleanup helper. Reviewer B verifies idempotency.
- **Bug Class #52 (RestoreEntity coerces unavailable to OFF):** switch, Number, AND Select all need the guard (last_state ∉ {valid} → keep seed). Reviewer C verifies for all three.
- **Bug Class #53 (computed-but-not-consumed / N-th unclamped site):** the unified gate is **the** site; D1 deletes the second site. Reviewer D enumerates ALL `_execute_zone_pre_cool` call sites and confirms only ONE leads from the unified trigger (pre-arrival uses `reason="pre_arrival"`; pre-heat goes through `_execute_pre_heat`, not `_execute_zone_pre_cool`). Reviewer D additionally enumerates every offset-read site (must all source from EC) and every scope-decision site (the per-zone loop must be the single decision point).
- **Trust-hierarchy ripple:** EC↔HC accessor pattern is established. Reviewer B walks EC→signal→HC for all three new properties.
- **Inclement-weather hold (v5.5.0 LIVE):** the unified trigger inherits the `constraint.mode == "normal"` gate; inclement-hold prevents pre-cool. Correct. Reviewer A confirms.
- **Arbitrage-WAIT floor gap (v5.5.0 follow-up):** unrelated path.
- **Sleep-state / occupancy interactions:** the unified trigger no longer hardcodes "bank all zones" — the operator's `CONF_ENERGY_PRECOOL_SCOPE` is authoritative. Default `auto_pv_tiered` preserves comfort under normal conditions and only expands when surplus is real.

---

## 7. Files touched (summary)

| File | Change kind | LoC est. |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/hvac_predict.py` | Delete `_should_weather_pre_cool` + `_should_solar_bank` + `_is_solar_banking_enabled` + banking dispatch block; add `_should_energy_precool` + unified dispatch with scope branch + `_is_energy_precool_enabled` + offset/scope getters; rename three tracking sets | ~−180 / +160 |
| `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` | Delete 3 banking constants; add ~12 energy-precool constants (enabled, offset, scope, scope values) | ~−15 / +35 |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | Delete `_solar_banking_enabled`; add 3 new properties/setters + init seeding | ~−18 / +50 |
| `custom_components/universal_room_automation/switch.py` | Delete `ECSolarBankingSwitch`; add `ECEnergyPreCoolSwitch` + orphan-entity cleanup | ~−12 / +30 |
| `custom_components/universal_room_automation/number.py` | Add EC `energy_precool_offset` Number entity (factory or subclass) | ~+80 |
| `custom_components/universal_room_automation/select.py` | Add EC `energy_precool_scope` Select entity (factory or subclass) | ~+80 |
| `custom_components/universal_room_automation/config_flow.py` | Replace 1 BooleanSelector + imports | ~−6 / +10 |
| `custom_components/universal_room_automation/__init__.py` | Add config-migration block + orphan-cleanup helper | ~+45 |
| `custom_components/universal_room_automation/domain_coordinators/hvac.py` | Rename + add house-state attrs (zones, enabled, offset, scope, scope_effective) | ~−16 / +28 |
| `custom_components/universal_room_automation/strings.json` | Rename + add entries (switch/number/select + select option labels) | ~−10 / +30 |
| `custom_components/universal_room_automation/translations/en.json` | Same | ~−10 / +30 |
| `quality/tests/test_energy_precool_pv_gate.py` | NEW (6 cases) | ~+250 |
| `quality/tests/test_energy_precool_offset_configurable.py` | NEW | ~+150 |
| `quality/tests/test_energy_precool_scope.py` | NEW (6 cases + mutation pair) | ~+260 |
| `quality/tests/test_energy_precool_offset_and_floor.py` | NEW | ~+90 |
| `quality/tests/test_energy_precool_switch_roundtrip.py` | NEW | ~+180 |
| `quality/tests/test_energy_precool_offset_number_roundtrip.py` | NEW | ~+160 |
| `quality/tests/test_energy_precool_scope_select_roundtrip.py` | NEW | ~+170 |
| `quality/tests/test_v5_7_1_solar_banking_retired.py` | NEW | ~+60 |
| `quality/tests/test_v5_7_1_solar_banking_migration.py` | NEW | ~+140 |
| `quality/tests/test_v5_7_1_pre_arrival_preheat_unchanged.py` | NEW (4 cases) | ~+200 |
| `quality/tests/test_solar_banking_toggle.py` | DELETE | ~−500 |
| `quality/tests/test_v457_solar_banking_away.py` | DELETE or REWRITE | ~−? |
| `docs/readmes/README_v5.7.1.md` | NEW | ~+220 |

Net: ~+1,300 / −800 LoC. Build order: `hvac_const.py` → `hvac_predict.py` (lock trigger surface) → `energy.py` (properties) → `switch.py`/`number.py`/`select.py` (entities) → `config_flow.py` + `__init__.py` (migration) → `hvac.py` (attrs) → tests.

---

## 8. Pre-deploy zero-bugs gate (mandatory)

Per `feedback_pre_deploy_zero_bugs_gate.md`:
1. `grep -rn "<<<<<<<\|>>>>>>>\|=======" custom_components/` (no merge markers).
2. `python -m py_compile` against every changed `.py` file.
3. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — full suite green.
4. Suite-baseline diff vs `pre-review-v5.7.1` tag.
5. Manual grep for `solar_banking|SOLAR_BANK_OFFSET|_should_solar_bank` across `custom_components/` — MUST be empty.
6. **Tier 3 additional:** orchestrator personally re-greps every `_execute_zone_pre_cool` call site, every offset-read site, and every scope-decision site, and re-runs source-mutation on each before deploy.
7. **Tier 3 additional:** operator pre-deploy checkpoint — surface the I1–I7 proof + the four review summaries; explicit operator go before `deploy.sh`.

---

## 9. Plan completion tracking

End-of-cycle, account for every deliverable in `docs/reviews/code-review/v5.7.1_energy_pre_cool_unification.md`:
- Each D1–D5 deliverable: SHIPPED / DEFERRED (with why + where re-tracked).
- Each acceptance criterion: PASS / FAIL / deferred-to-live / could-only-prove-in-suite.
- All review findings (CRIT/HIGH/MED/LOW) from A/B/C/D with bug-class tags.
- README write-back table (one row per acceptance criterion).

---

## 10. Open questions for operator (resolve before build)

1. **Working-name lock-in.** RESOLVED 2026-06-28: `"Energy Saver Pre-Cool"` (constant `ENERGY_PRECOOL_NAME` unchanged).
2. **Offset default.** RESOLVED 2026-06-28: −2.0°F default, operator-configurable via EC Number (min −5.0, max 0.0, step 0.5).
3. **Scope.** RESOLVED 2026-06-28: three values (`occupied_only` / `whole_house` / `auto_pv_tiered`), default `auto_pv_tiered`, operator-configurable via EC Select.
4. **Attribute compat aliases.** Plan removes `solar_banking_zones` / `banking_enabled` from the HVAC house-state sensor with no aliases. Confirm OR keep one-release alias. **Default if no response: hard rename, no aliases — operator updates dashboards.**

---

## 11. Relevant absolute paths (for reviewer / builder navigation)

- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_predict.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/energy.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/switch.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/number.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/select.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/config_flow.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/__init__.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/strings.json`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/translations/en.json`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_solar_banking_toggle.md` (predecessor)
- `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_hc_precool_toggle_oc_observability.md` (predecessor for master "28")
- `/Users/okosisi/Code/universal-room-automation/quality/tests/test_solar_banking_toggle.py` (to be deleted)
