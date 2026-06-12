# PLANNING — EC Envoy boot-decoupling + EC sub-switch restore poisoning

**Cycle name:** EC Envoy boot-decoupling + EC sub-switch restore poisoning
**Target version:** TBD (next patch after current `v5.3.6`)
**Branch:** `develop`
**Tier:** **Tier 2-DB (operator-elevated)** — single user, no back-compat shims, no migration scaffolding
**Cycle type:** Resilience fix (NOT an EC redesign)
**Authoring date:** 2026-06-12
**Incident reference:** 2026-06-12 Envoy LAN gateway (192.168.13.118) outage starting ~21:34 CDT; three restarts; full house automation down across two of them.

---

## 0. Incident snapshot (problem we are fixing)

Three independently-bad behaviors compounded into a multi-hour URA outage when the Envoy gateway went unresponsive:

- **Failure A — `after_dependencies` stranding.** `manifest.json` declares `after_dependencies: ["enphase_envoy"]` (added v4.2.29, commit `dc24349`). When `enphase_envoy` setup HUNG on the dead device, HA's stage-2 bootstrap fired *"Setup timed out for stage 2 — moving forward"* and cancelled the queued URA entry setups. All 40 URA entries stayed `not_loaded` for the whole boot; zero URA code ran; zero URA errors logged. Whole-house automation down.
- **Failure B — one-shot Envoy validation drops EC.** On a subsequent clean boot, `validate_envoy_config` (`domain_coordinators/energy_const.py:693-778`) ran at 00:41:38 but the Envoy entity didn't appear in the state machine until 00:41:55 (Enphase's first refresh took 15.7 s vs the usual ~0.7 s as the device was still recovering). V2's `hass.states.get(envoy_eid)` returned `None` → `envoy_entity_missing` → the gate at `__init__.py:1857` (`if _energy_enabled and _envoy_validation_ok:`) silently skipped EnergyCoordinator registration for the entire boot. No battery strategy, no TOU, no EVSE off-peak, all EC sub-switches `unavailable`. Recovery requires restart or manual repair-flow click.
- **Failure C — RestoreEntity unavailable-coercion.** The EC sub-switch factory (`switch.py:617-648`) does `target = last_state.state == "on"` in `async_added_to_hass`, so a last-state of `unavailable` / `unknown` (which the broken Failure-B boots wrote) restores as **False** and `setattr`s False onto the coordinator — clobbering the options-seeded value. Tonight ALL 6 intended-ON EC switches (`grid_arbitrage`, `ev_tou_management`, `evse_solar_aware`, `grid_import_cap`, `dynamic_preset_overrides`, `solar_hvac_banking`) silently restored OFF; manually re-enabled at 06:15 Z. `HVACDynamicPresetSwitch` (`switch.py:942-1153`) replicates the same restore pattern.

Net effect: a dead LAN device 30 ft away nuked URA twice.

---

## 1. Institutional context verified

This section is the proof-of-work that institutional knowledge was consulted before scoping. **Reviewers MUST verify each citation during Tier 2-DB review.**

### 1.1 Greps run + REUSED / NEW verdicts

| Proposed addition | Verdict | Cited prior art |
|---|---|---|
| Two-way → three-way `validate_envoy_config` result (`ok` / `degraded` / `fail`) | **REUSED + EXTENDED** — `energy_const.py:693-778` already returns `{ok, errors, warnings, serial, resolved}`. We add an `entity_registry_known: bool` field (and optionally an `ok` value that distinguishes `True / "degraded" / False`); the existing dict keys keep their semantics so the config-flow caller is unaffected. | `domain_coordinators/energy_const.py:693-778` |
| EVENT_HOMEASSISTANT_STARTED deferred re-validation listener | **REUSED pattern** — HVAC coordinator already uses `hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, …)` for its boot-settle gate at `hvac.py:405-417` (planning doc: cold-boot away-actuation storm). No new abstraction needed. | `domain_coordinators/hvac.py:385-419, 763-766` |
| Drop `_envoy_validation_ok` gate at `__init__.py:1857` | **NEW** (deletion). The gate was added v4.2.29 to refuse silent fall-back to wrong defaults; we replace it with V0/V1 hard-fail (no entity / unparseable serial) only. EC's runtime is already None-safe — `energy_battery.py:928/945` explicitly logs *"Envoy unavailable — holding current state"*; all power/SOC readers tolerate `None`. The boot gate is the **only** hard coupling. | `energy_battery.py:928/945` (None-safe runtime); v4.2.29 review `docs/reviews/code-review/v4.2.29_envoy_validation.md` |
| Drop net_power_entity gate at `__init__.py:1989` | **NEW** (deletion). HVAC's `_get_net_power()` already returns 0.0 for missing entity (`hvac_predict.py`, per v4.2.29 review). Pass the entity_id unconditionally; runtime degrades gracefully. | v4.2.29 review § "Cross-coordinator interaction analysis" |
| Remove `after_dependencies: ["enphase_envoy"]` from manifest | **NEW** (deletion). Zero `import enphase_envoy` occurrences exist; `after_dependencies` is a timing hint only and is the Failure-A vector. v4.2.29 review added it as a load-order race mitigation, but D1–D3 make load order irrelevant. | `manifest.json:13-15`; v4.2.29 review § Review 2 HIGH finding |
| `last_state.state not in ("on","off")` guard in RestoreEntity | **NEW pattern in URA**, but mirrors HA's canonical guard (used by HA core `switch.template`, `binary_sensor.template`). 30 call sites in `switch.py` use the broken `== "on"` coercion; only the 7 in scope this cycle (EC sub-switches + HVACDynamicPresetSwitch) get the fix in **this** cycle. Audit-only finding for the remaining 23 — separate follow-up cycle. | `switch.py:468, 623, 1053, 1246, 1374, 1510, 1651, 1786, 2042, 2133, 2225, 2322, 2405, 2497, 2600, 2716, 2793, 2862, 2982, 3021, 3051, 3088, 3124, 3159, 3194, 3241, 3284, 3410, 3544, 3595, 3654` (grep `last_state\.state\s*==\s*['\"]on['\"]`) — `number.py` is clean (0 hits). |
| New QUALITY_CONTEXT bug class — "RestoreEntity unavailable-coercion" | **NEW** — bug-class table currently runs through `#51` (`docs/QUALITY_CONTEXT.md:2045`). This cycle adds **Bug Class #52**. | `docs/QUALITY_CONTEXT.md:1993, 2045` |
| `SIGNAL_ENERGY_COORDINATOR_READY` use for sub-switch restore | **REUSED** — exists at `signals.py:72` and the factory already subscribes (`switch.py:600-615`). No change to the signal itself. | `domain_coordinators/signals.py:66-72`; `switch.py:600-615` |
| Repair issue `energy_envoy_invalid_<entry_id>` | **REUSED** — create/delete sites at `__init__.py:1813, 1846`; fix flow at `repairs.py:28-117`. We adjust *when* it's raised (after deferred re-validation), not the issue itself. | `__init__.py:1813, 1846`; `repairs.py:28-117` |

### 1.2 Prior planning docs consulted

- `docs/reviews/code-review/v4.2.29_envoy_validation.md` — full read. Documents the original Validator design, the Review-2 HIGH finding that introduced `after_dependencies`, and the cross-coordinator interaction matrix we now leverage to **remove** the gate safely.
- `docs/planning/PLANNING_ec_*` directory — skimmed filenames; no prior cycle has touched Envoy validation since v4.2.29.
- `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR.md` + v2 — skimmed; no overlap (Optimizer reads EC state, doesn't gate EC registration).
- v4.7.6 / v4.7.6.1 EVSE solar-aware planning — read for any Envoy-state assumptions; none introduced (EVSE reads via EC).

### 1.3 Memory bodies pulled

- *Optimizer DB write-flood incident 2026-06-09* — confirms restore-time interactions matter; informs the "Live" criteria around boot-storm volume.
- *v4.7.21 boot-storm settle gates (LIVE)* — informs the deferred re-validation pattern; the HA-started + failsafe-timeout dual-path is already proven in HVAC.
- *Pre-Deploy Zero-Bugs Gate* — applies (mandatory).

### 1.4 Design docs read

- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` — read § "HVAC Coordinator Integration" + § "Sensors & Entities". EC's contract with HVAC is via signal/state, not registration order; design supports lazy/runtime degrade.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/manifest.json` (full).
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:680-778` (validator + tier definitions).
- `custom_components/universal_room_automation/__init__.py:1780-2010` (Envoy gate, EC registration, HVAC registration).
- `custom_components/universal_room_automation/repairs.py:1-117` (fix flow).
- `custom_components/universal_room_automation/switch.py:600-700` (`_ec_switch_factory` restore path).
- `custom_components/universal_room_automation/switch.py:942-1153` (`HVACDynamicPresetSwitch` restore path).
- `custom_components/universal_room_automation/domain_coordinators/signals.py:60-80` (`SIGNAL_ENERGY_COORDINATOR_READY`).
- `custom_components/universal_room_automation/domain_coordinators/hvac.py:380-420, 760-790` (EVENT_HOMEASSISTANT_STARTED + failsafe-timeout boot-settle pattern).
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py:920-960` (runtime None-handling proof).
- `docs/QUALITY_CONTEXT.md:1993-2090` (bug-class table tail; #50, #51 confirmed).
- `custom_components/universal_room_automation/number.py` — full grep; no `== "on"`-style coercion (clean).
- `custom_components/universal_room_automation/select.py` — grep; no `last_state.state == X`-style coercion of unavailable.

---

## 2. Tier classification — operator-elevated Tier 2-DB

**Why elevated** (per CLAUDE.md "Standing policy — use the Tier 2-DB review protocol for ALL regression-prone work"):

- **Startup-path change** — modifies the boot ordering contract between URA and Enphase + the gate that decides whether EC registers at all. A bug here can silently disable EC indefinitely.
- **Cross-coordinator ripple** — EC ↔ HVAC ↔ EC sub-switches ↔ Repairs flow. Failure-B already proved a single-line gate can take down half the system.
- **Lifecycle / restore semantics change** — RestoreEntity behavior touches the relationship between `entry.options` (intended state) and persisted `core.restore_state` (observed state). Silent regressions here are very hard to detect.
- **Trust-hierarchy / shared primitive** — `validate_envoy_config` is a shared primitive (config_flow + startup + repairs fix flow all call it); changing its semantics has reconciliation risk across three call sites.

**Three framing-disjoint review axes** (must be different reviewers, run in parallel — different framings can't share blind spots):

- **Review A — Boot-sequence correctness + race conditions.** Verify D1–D4 produce correct EC-registered / EC-skipped outcomes across the full matrix (envoy-late, envoy-absent, envoy-recovered, runtime-blip, options-flow-reload, hot-vs-cold boot, HA core RUNNING vs not). Audit deferred-re-validation listener wiring (idempotency, double-fire, unload cleanup). Confirm dropping `after_dependencies` cannot strand any unrelated URA dependency.
- **Review B — Validation semantics + repair-flow integrity.** Field-by-field equivalence of pre- vs post-change validator output for all four pre-existing call sites (`config_flow.async_step_coordinator_energy`, `__init__.py` startup, `repairs.EnvoyValidationRepairFlow.async_step_confirm`, any tests). Verify the new `entity_registry`-based existence check is semantically correct for HA's lifecycle (registered-but-not-yet-loaded entities; entities that exist purely as state without registry entries — e.g., `template.` / `sensor.` from YAML — Envoy entities are registry-backed so this is benign, but reviewers must confirm). Confirm repair issue isn't raised spuriously during the boot-race window and IS raised correctly post-`EVENT_HOMEASSISTANT_STARTED` when the Envoy is genuinely absent. Confirm stale issue is cleared on recovery.
- **Review C — Restore / RestoreEntity lifecycle + test authority.** Audit the unavailable-coercion fix in both EC sub-switch factory (`switch.py:617-648`) and `HVACDynamicPresetSwitch` (`switch.py:1040-1075`). Verify: first-install path (`last_state is None`), valid-on/off restore, unavailable-restore (must NOT setattr), `unknown`-restore (must NOT setattr), `entry.options`-seed precedence is preserved when restore is skipped. Confirm tests drive production code paths (no test-private INSERT/UPDATE — N/A here since this is RestoreEntity, not DB; reviewers should check the analog: tests must instantiate the entity and run `async_added_to_hass`, not mock around it). Confirm follow-up audit (23 remaining `== "on"` call sites) is filed as a tracked backlog memo, not silently dropped.

**Pre-deploy snapshot required (Tier 2-DB ceremony):**

- The set of EC sub-switch on/off values from `entry.options` (CM entry) at the moment of deploy. Saved as a small JSON blob in the deploy commit message or a sibling `docs/snapshots/<version>_ec_sub_switch_options.json`. **Why:** Live Validation must confirm post-restart values match this snapshot; without it we can't tell whether restore restored the *intended* state.
- The current set of repair issues under domain `universal_room_automation` (expect to be empty; surface a finding if not).

**Pre-review baseline tag** (per CLAUDE.md "Tag the Baseline"):

```bash
git tag pre-review-v<version> -m "Pre-review baseline for v<version>: EC Envoy boot-decoupling"
```

---

## 3. Deliverables

### D1 — Three-way Envoy validation using the entity registry

**What:** Replace the V2 existence check (`hass.states.get(envoy_eid) is not None`) with an **entity-registry**-based existence check, and split outcomes three ways:

- **(a) Hard fail — not in entity registry.** Genuine misconfig (user picked a non-existent or removed entity). Returns `ok=False`, `errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_ENTITY_MISSING`. Today's behavior. Refuses EC start. Raises repair issue.
- **(b) Degraded — in registry but `hass.states.get(...)` returns None or `unavailable` / `unknown`.** Boot race (Failure B) or Envoy device blip. Returns `ok=True`, **new** `degraded=True`, **new** `degraded_reason="state_missing"` / `"state_unavailable"`. EC proceeds; runtime handles None gracefully. NO repair issue at this layer (D3 handles the post-start surface).
- **(c) Live — registered, state present, not unavailable.** `ok=True`, `degraded=False`. Today's pass path.

V0 (entity field set) and V1 (parseable serial) remain **hard-fail** unchanged — these are config errors, not boot races.

V4 (derived entities exist) gets the same three-way treatment: registry-present → degraded; registry-absent → hard fail. Rationale: an Enphase device that's mid-recovery has its derived entities in registry but `state.state` blank/unavailable for ~15 s.

**Files touched:**
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:693-778` — refactor `validate_envoy_config`.

**Constants added:**
- `ENVOY_DEGRADED_STATE_MISSING = "state_missing"` (entity registered, `hass.states.get` returns None)
- `ENVOY_DEGRADED_STATE_UNAVAILABLE = "state_unavailable"` (entity registered, state is `unavailable` / `unknown`)
- Result dict gains: `"degraded": bool`, `"degraded_reason": str | None`, `"entity_registry_known": bool`.

**Acceptance Criteria:**
- **Verify:** unit test `test_validate_envoy_registry_known_state_missing` → result is `ok=True, degraded=True, degraded_reason="state_missing"`.
- **Verify:** unit test `test_validate_envoy_registry_known_state_unavailable` → result is `ok=True, degraded=True, degraded_reason="state_unavailable"`.
- **Verify:** unit test `test_validate_envoy_registry_absent` → result is `ok=False, errors[CONF_ENERGY_ENVOY_ENTITY]=ENVOY_ERR_ENTITY_MISSING`.
- **Verify:** unit test `test_validate_envoy_live_pass` → unchanged from v4.2.29 (`ok=True, degraded=False`).
- **Verify:** unit test `test_validate_envoy_v0_required_still_hard_fails` and `test_validate_envoy_v1_invalid_serial_still_hard_fails`.
- **Test:** all four call sites (config_flow, `__init__.py`, repairs fix flow, existing test fixtures) compile and behave per D2 / D3 contract.
- **Live:** N/A at this layer (covered by D2/D3 live criteria).

### D2 — Always register EC when energy is enabled (drop the validation gate)

**What:** At `__init__.py:1857`, replace `if _energy_enabled and _envoy_validation_ok:` with:

- Skip EC ONLY when `_energy_enabled is False` OR validation returned a V0/V1 hard error (no entity / unparseable serial). Both are user-actionable config errors.
- Otherwise register EC unconditionally. Runtime is already None-safe (verified: `energy_battery.py:928/945`).
- Apply the same treatment at `__init__.py:1989` for `_hvac_net_power_entity`: pass the entity ID unconditionally to HVAC; HVAC's `_get_net_power()` already returns 0.0 for missing entity.

**Files touched:**
- `custom_components/universal_room_automation/__init__.py:1780-2000` — refactor gate logic. Replace the boolean `_envoy_validation_ok` with `_envoy_hard_fail` (only true on V0/V1 failure) so existing logging branches stay readable.

**Acceptance Criteria:**
- **Verify:** with envoy entity registered but state missing at boot, EC is registered and present in `hass.data[DOMAIN]['coordinator_manager'].coordinators['energy']`.
- **Verify:** with envoy entity NOT in registry, EC is NOT registered AND repair issue `energy_envoy_invalid_<entry_id>` is raised (via D3 path, after `EVENT_HOMEASSISTANT_STARTED`).
- **Verify:** with envoy unparseable serial (e.g., user picks the wrong entity), EC is NOT registered AND repair issue is raised immediately at startup (V1 hard-fail is not boot-race-recoverable).
- **Verify:** HVAC's `net_power_entity` is non-None when envoy entity is configured + registry-known, regardless of state.
- **Sensor:** `sensor.ura_energy_coordinator_*` entities are present (not absent) after a boot where Envoy was registered-but-state-missing.
- **Test:** unit test `test_ec_registers_when_envoy_state_missing_but_registered`.
- **Test:** unit test `test_ec_skipped_when_envoy_not_in_registry`.
- **Test:** unit test `test_ec_skipped_when_envoy_serial_unparseable`.
- **Test:** unit test `test_hvac_receives_net_power_entity_when_envoy_degraded`.
- **Live:** post-deploy, with Envoy artificially "late" (simulated by waiting until immediately after restart and confirming EC starts before Envoy entity transitions to `state=present`), `sensor.ura_*_tou_state` (or analogous EC TOU readout) is non-`unknown` within 60 s.
- **Live:** confirm `sensor.ura_energy_coordinator_sub_switches_synced` reads `True` within 90 s post-restart (proves restore + ready signal still chain correctly).

### D3 — Deferred re-validation at EVENT_HOMEASSISTANT_STARTED for repair-issue surface

**What:** Add a one-shot listener on `EVENT_HOMEASSISTANT_STARTED` (with a failsafe `async_call_later` timeout — mirror `hvac.py:385-419`) that re-runs `validate_envoy_config` and:

- If still **hard-fail** (V0/V1/registry-absent) → raise `energy_envoy_invalid_<entry_id>` repair issue (existing path).
- If **degraded** → log INFO. Do NOT raise repair issue (this is a transient device state, not misconfig). If a previous stale repair issue exists from a prior boot, clear it.
- If **live** → clear stale repair issue.

The listener fires **once per entry setup**, registers an unload-time cleanup via `entry.async_on_unload`, and uses a bound method (Bug Class #42).

**Files touched:**
- `custom_components/universal_room_automation/__init__.py` — new helper `_schedule_envoy_revalidation(hass, entry, energy_entity_config)` near the existing validation block; registers EVENT_HOMEASSISTANT_STARTED listener + failsafe `async_call_later(BOOT_SETTLE_TIMEOUT_SECONDS)` (constant already exists per `hvac.py:402`).

**Acceptance Criteria:**
- **Verify:** unit test `test_revalidation_clears_stale_issue_when_envoy_recovers`.
- **Verify:** unit test `test_revalidation_raises_issue_when_envoy_genuinely_absent`.
- **Verify:** unit test `test_revalidation_does_not_double_fire_after_unload`.
- **Live:** after a restart with Envoy device disconnected, confirm `Settings → Repairs` surfaces `energy_envoy_invalid_<entry_id>` within `BOOT_SETTLE_TIMEOUT_SECONDS` (not earlier — proves we didn't false-alarm during the boot-race window).
- **Live:** after Envoy reconnects + URA reload via the repair fix flow, the repair issue is cleared and EC re-registers with live data.

### D4 — Remove `after_dependencies: ["enphase_envoy"]` from manifest

**What:** Delete the three-line `after_dependencies` block from `manifest.json`. Once D1–D3 make load order irrelevant, this hint has no purpose and it is the Failure-A vector.

**Files touched:**
- `custom_components/universal_room_automation/manifest.json:13-15` — delete the `"after_dependencies"` key + array.

**Acceptance Criteria:**
- **Verify:** `grep -r enphase_envoy custom_components/universal_room_automation/` returns ZERO `import` matches (already true) and ZERO `manifest.json` matches.
- **Test:** existing test suite passes (no test asserts the dependency).
- **Live:** simulate Failure A by leaving the Envoy device offline and restarting HA. Expected: URA entries reach `loaded` state within stage-2 timeout. Pre-fix this was the broken case; post-fix this is the proof.
- **Live:** verify in HA logs the absence of any `"Setup timed out for stage 2"` line attributable to `enphase_envoy` blocking URA.

### D5 — Tests

**What:** Pytest coverage for D1–D4. All tests live under `quality/tests/test_envoy_boot_decoupling.py` (new file). Existing `quality/tests/test_envoy_auto_derive.py` is left alone (its assertions about hard-fail-on-V2 are no longer accurate; either update inline or mark TODO with a sibling cycle).

**Test inventory (must pass):**

1. `test_envoy_late_boot_registered_state_missing` — registry mock returns the envoy entity; `hass.states.get` returns None. Expected: `validate_envoy_config` returns `ok=True, degraded=True`; EC registration block runs.
2. `test_envoy_late_boot_registered_state_unavailable` — same as 1 but state is `"unavailable"`. Same outcome.
3. `test_envoy_absent_not_in_registry` — registry has no entry. Expected: `ok=False`, `entity_registry_known=False`, EC not registered, repair issue raised (after deferred listener fires).
4. `test_envoy_v0_no_entity_configured` — hard fail, EC not registered, repair issue raised immediately.
5. `test_envoy_v1_unparseable_serial` — hard fail, EC not registered.
6. `test_runtime_blip_holds_state_path_untouched` — confirms `EnergyCoordinator`'s existing None-handling at `energy_battery.py:928/945` is reachable when envoy was present at boot but later disappears.
7. `test_revalidation_clears_stale_issue_after_recovery`.
8. `test_revalidation_raises_issue_when_envoy_still_absent_at_started`.
9. `test_revalidation_listener_cleaned_up_on_unload`.
10. `test_hvac_net_power_entity_passed_when_envoy_degraded` (D2 cross-coord).
11. `test_ec_sub_switch_restore_skips_unavailable_last_state` (D6).
12. `test_ec_sub_switch_restore_skips_unknown_last_state` (D6).
13. `test_ec_sub_switch_restore_preserves_options_seed_when_skipped` (D6, critical for the regression we are fixing).
14. `test_hvac_dynamic_preset_switch_restore_skips_unavailable_last_state` (D6).
15. `test_ec_sub_switch_first_install_no_last_state_unchanged` (D6 regression guard).

**Acceptance Criteria:**
- **Verify:** `PYTHONPATH=quality python3 -m pytest quality/tests/test_envoy_boot_decoupling.py -v` → all 15 pass.
- **Verify:** suite-wide baseline diff vs `pre-review-v<version>` shows no unrelated test breakage.
- **Test:** zero conflict markers (`<<<<<<<`) anywhere; `py_compile` clean for every changed `.py` (pre-deploy gate).

### D6 — Fix restore poisoning + audit remaining call sites

**What:**

- **Fix (in scope):** Add `if last_state.state not in ("on", "off"): return` guard immediately after `last_state = await self.async_get_last_state()` (and the `last_state is None` check) in BOTH:
  - `switch.py:617-648` — `_ec_switch_factory` `async_added_to_hass` (the 6 EC sub-switches: `grid_arbitrage`, `ev_tou_management`, `evse_solar_aware`, `grid_import_cap`, `dynamic_preset_overrides`, `solar_hvac_banking`).
  - `switch.py:1040-1075` — `HVACDynamicPresetSwitch.async_added_to_hass`.

  When skipped, the constructor / entry.options seed remains the source of truth (matches the existing `last_state is None` first-install branch). Log INFO `"Skipping RestoreEntity restore for %s — last_state=%s — keeping options-seeded value %s"` for observability.

- **Audit (in scope, document only):** Enumerate the remaining 23 call sites of `last_state.state == "on"` in `switch.py` (per Grep run). For each, document in a follow-up backlog memo `.vibememo/users/ojiudezue/entries/0XX_restoreentity_unavailable_coercion_audit.md`:
  - Whether the call site has the same poisoning risk (e.g., does it `setattr` into a coordinator? does it have an `entry.options` seed that should win?).
  - Whether the risk is mitigated elsewhere (e.g., `self._is_on = last_state.state == "on"` purely on the entity itself is much lower risk than coordinator `setattr`).
  - Cycle scope estimate.

  **Out of scope this cycle** — only the 7 demonstrated-broken call sites are fixed; the rest are deferred to avoid a 30-file blast radius in a resilience-fix cycle.

- **New bug class:** Add **Bug Class #52 — RestoreEntity unavailable-coercion** to `docs/QUALITY_CONTEXT.md` (insert after #51 at line 2090ish). Pattern: `target = last_state.state == "on"` coerces `unavailable` / `unknown` to `False`, which then overwrites a correct value seeded from `entry.options` / constructor / default. Fix: guard with `if last_state.state not in ("on", "off"): return` (or analogous `("0", "1")`, etc., for non-boolean state).

**Files touched:**
- `custom_components/universal_room_automation/switch.py:617-648` — EC sub-switch factory.
- `custom_components/universal_room_automation/switch.py:1040-1075` — `HVACDynamicPresetSwitch`.
- `docs/QUALITY_CONTEXT.md` — append Bug Class #52.
- `.vibememo/users/ojiudezue/entries/0XX_restoreentity_unavailable_coercion_audit.md` — new memo (audit only).

**Acceptance Criteria:**
- **Verify:** unit test 11 (`test_ec_sub_switch_restore_skips_unavailable_last_state`) — last_state `"unavailable"`, coordinator attribute remains at the options-seeded value.
- **Verify:** unit test 12 (`unknown`).
- **Verify:** unit test 13 — assert `getattr(energy, attr_name)` stays at the options-seeded value through `async_added_to_hass` when `last_state.state == "unavailable"`.
- **Verify:** unit test 14 — `HVACDynamicPresetSwitch` same coverage.
- **Verify:** unit test 15 — first-install path (`last_state is None`) is unchanged.
- **Live:** capture `entry.options` ECsub-switch values pre-deploy (Tier 2-DB snapshot). After deploy + restart, all 6 EC sub-switches plus `HVACDynamicPresetSwitch` MUST match the snapshot. This is the regression we are fixing — it must not silently re-occur.
- **Live:** induce the bad case once on a test boot: write `unavailable` to `core.restore_state` for one EC sub-switch (or just observe one if the next boot naturally produces it), confirm restore is **skipped** (look for the new INFO log) and the coordinator attribute stays at the options-seeded `True`.
- **Verify:** new bug class #52 added to `docs/QUALITY_CONTEXT.md`; bug-class count in the header bumped from 51 → 52.
- **Verify:** audit memo lists all 23 remaining `== "on"` sites with risk classification.

---

## 4. Non-goals (explicit scope guardrails)

- **NOT** redesigning `EnergyCoordinator` or its DB schema.
- **NOT** fixing the other 23 `last_state.state == "on"` call sites in this cycle — audit only.
- **NOT** adding any new CONF_*, sensor, number, switch, or button entity.
- **NOT** changing `SIGNAL_ENERGY_COORDINATOR_READY` semantics or the v4.5.3 retry chain.
- **NOT** touching `enphase_envoy` integration code (we don't own it).
- **NOT** adding back-compat shims (single-user install per CLAUDE.md).
- **NOT** writing a migration cycle — schema is unchanged.

---

## 5. Plan-completion accounting

This section will be filled at cycle close (per CLAUDE.md "Plan Completion Tracking — MANDATORY"). Pre-filled deferral list:

- **23 remaining `last_state.state == "on"` call sites in `switch.py`** — deferred to follow-up cycle (not silently dropped; tracked in audit memo from D6).
- **`test_envoy_auto_derive.py` v4.2.29 assertions about V2 hard-fail** — must be reviewed during D5; either updated inline (preferred) or marked TODO with a tracked memo. NOT silent.

---

## 6. Deploy + Live Validation ceremony

Per CLAUDE.md Tier 2-DB:

1. **Pre-review baseline tag** (before any review fixes).
2. **Three parallel reviews** (A / B / C framings above).
3. **Fix all CRITICAL + HIGH from any reviewer** before deploy. Fix LOWs in-cycle where reasonable (≤30 LoC each).
4. **Pre-deploy zero-bugs gate** (MANDATORY per `feedback_pre_deploy_zero_bugs_gate`):
   - `grep -rn '<<<<<<<' custom_components/universal_room_automation/`
   - `python3 -m py_compile` on every changed `.py`.
   - `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — full suite green.
   - Suite-baseline-diff vs `pre-review-v<version>`.
5. **Snapshot pre-deploy** (Tier 2-DB):
   - JSON of all EC sub-switch on/off values from `entry.options`.
   - Current set of `universal_room_automation`-domain repair issues.
6. **Deploy** via `./scripts/deploy.sh <version> "<summary>" "<release-notes>"`.
7. **README_v<version>.md** must be written pre-deploy, with prospective "Live Validation" bullets matching D2 / D3 / D6 "Live" criteria above.
8. **Live Validation (Review D)** post-restart — `@ura-validator` runs against the live house via MCP. Must verify:
   - EC registered + present in coordinator_manager.
   - All 6 EC sub-switches + `HVACDynamicPresetSwitch` match the pre-deploy snapshot.
   - No `energy_envoy_invalid_*` repair issue spuriously raised in the boot-race window.
   - `sensor.ura_*_tou_state` reads a real TOU value (not `unknown`) within 60 s of EC registration.
   - HA logs contain no `"Setup timed out for stage 2"` line implicating URA.
9. **README write-back** — replace prospective "Live Validation" bullets with a `Validated <date>` PASS/FAIL table citing the observed evidence (entity_id + attribute, log scan result, repair-issue registry read). Cycle is not closed until the README carries this table.
10. **Post-review documentation** — `docs/reviews/code-review/v<version>_envoy_boot_decoupling.md` with all bugs found, severities, fixed/deferred status, bug-class tagging (must include Bug Class #52 entries).
