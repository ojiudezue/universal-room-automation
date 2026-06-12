# Review Ledger — EC Envoy boot-decoupling + EC sub-switch restore poisoning

**Cycle:** EC Envoy boot-decoupling + EC sub-switch restore poisoning
**Branch:** `feature/ec-envoy-boot-decoupling`
**Plan:** `docs/planning/PLANNING_ec_envoy_boot_decoupling.md`
**Tier:** Tier 2-DB (operator-elevated)
**Status:** AWAITING REVIEW (build complete; reviewers fill below).

---

## Build notes (builder)

### Files changed

| File | Lines (added / removed approx) | Purpose |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/energy_const.py` | +~120 / -~30 | D1 — three-way `validate_envoy_config`; new constants `ENVOY_DEGRADED_STATE_MISSING/_STATE_UNAVAILABLE`; new helper `_entity_in_registry`. Result dict gains `degraded` / `degraded_reason` / `entity_registry_known`. |
| `custom_components/universal_room_automation/__init__.py` | +~170 / -~30 | D2 — replace `_envoy_validation_ok` with `_envoy_hard_fail`; HVAC `net_power_entity` passed when not hard-fail. D3 — new module-level helper `_schedule_envoy_revalidation` (EVENT_HOMEASSISTANT_STARTED + async_call_later failsafe, mirrors `hvac.py:385-419`). |
| `custom_components/universal_room_automation/manifest.json` | -3 | D4 — drop `after_dependencies: ["enphase_envoy"]`. |
| `custom_components/universal_room_automation/switch.py` | +~40 | D6 — restore-poisoning guard in `_ec_switch_factory` (~`617-648`) and `HVACDynamicPresetSwitch.async_added_to_hass` (~`1040-1075`). Skip path mirrors the existing `last_state is None` first-install branch: constructor / options seed is source-of-truth, no `_deferred_restore=True` is left dangling. |
| `quality/tests/test_envoy_boot_decoupling.py` | +new | D5 — 15-test suite per plan. |
| `quality/tests/test_envoy_auto_derive.py` | inline updates | D5 — re-contract the v4.2.29 V2-hard-fail assertions onto the new three-way contract (operator decision: inline, no TODOs/skips). |
| `docs/QUALITY_CONTEXT.md` | +~60 | D6 — Bug Class #52 "RestoreEntity unavailable-coercion". |

### D6 — 23-call-site audit (`last_state.state == "on"` in `switch.py`)

In-scope fixes this cycle: lines **623** (EC sub-switch factory) and **1053** (`HVACDynamicPresetSwitch`). All other call sites are audited and deferred to a follow-up cycle.

| # | Line | Containing class / factory | Sink | Coordinator setattr? | Options seed exists? | Risk if unavailable last_state | Defer rationale |
|---|------|----------------------------|------|----------------------|----------------------|--------------------------------|-----------------|
| 1 | 468  | EC observation-mode switch | `energy.observation_mode = True` (only if `== "on"`) | Yes | Yes (default OFF) | LOW — uses `is not None and == "on"` so unavailable does NOT coerce to a `setattr False`. No silent flip. | Pattern OK; document only. |
| 2 | 1246 | EC switch (additional) | `target = last_state.state == "on"` then `setattr` | Yes | Yes | **MED-HIGH** — same shape as 623. | Audit-only this cycle; same fix pattern. |
| 3 | 1374 | EC switch (additional) | `target = ... == "on"` | Yes | Yes | **MED-HIGH** | Audit-only. |
| 4 | 1510 | EC switch (additional) | `target = ... == "on"` | Yes | Yes | **MED-HIGH** | Audit-only. |
| 5 | 1651 | EC switch (additional) | `target = ... == "on"` | Yes | Yes | **MED-HIGH** | Audit-only. |
| 6 | 1786 | EC switch (additional) | `target = ... == "on"` | Yes | Yes | **MED-HIGH** | Audit-only. |
| 7 | 2042 | NM Messaging Suppress (et al.) | `last_state is not None and == "on"` | Self-contained | Default OFF | LOW — `is not None and == "on"` guarded; unavailable does NOT setattr False. | Pattern OK. |
| 8 | 2133 | switch (`is not None and == "on"`) | Self-contained | Default OFF | LOW | Same as #7. | Pattern OK. |
| 9 | 2225 | switch (`is not None and == "on"`) | Self-contained | Default OFF | LOW | Same as #7. | Pattern OK. |
| 10 | 2322 | `hvac.zone_intelligence_enabled = last_state.state == "on"` | Yes (hvac) | Yes | **HIGH** — unavailable → False clobbers HVAC. | Defer to follow-up; same fix shape as 623. |
| 11 | 2405 | `self._is_on = last_state.state == "on"` | Self attr | Default | LOW-MED — flips own state but no coordinator setattr. | Audit-only. |
| 12 | 2497 | `cc._solar_gain_enabled = last_state.state == "on"` | Yes (cover) | Yes | **HIGH** | Defer; same fix. |
| 13 | 2600 | `target = ... == "on"` | Yes | Yes | **MED-HIGH** | Audit-only. |
| 14 | 2716 | `hvac.pre_arrival_enabled = ... == "on"` | Yes (hvac) | Yes | **HIGH** | Defer; same fix. |
| 15 | 2793 | `hvac.fan_control_enabled = ... == "on"` | Yes (hvac) | Yes | **HIGH** | Defer; same fix. |
| 16 | 2862 | `if last_state and ... == "on"` | Mixed | Default | LOW — guarded; no False-coerce path. | Pattern OK. |
| 17 | 2982 | `self._is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 18 | 3021 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 19 | 3051 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 20 | 3088 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 21 | 3124 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 22 | 3159 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 23 | 3194 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 24 | 3241 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 25 | 3284 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 26 | 3410 | `target = ... == "on"` | Likely coord | Yes | **MED-HIGH** | Audit-only. |
| 27 | 3544 | `self._is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 28 | 3595 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 29 | 3654 | `self._attr_is_on = ... == "on"` | Self attr | Default | LOW-MED | Audit-only. |
| 30 | 623  | **`_ec_switch_factory` — FIXED THIS CYCLE.** | `setattr(energy, attr_name, target)` | Yes | Yes (options seed) | **CRITICAL** — incident root cause. | In scope D6. |
| 31 | 1053 | **`HVACDynamicPresetSwitch` — FIXED THIS CYCLE.** | `energy.dynamic_preset_enabled = target` | Yes | Yes (default ON) | **CRITICAL** — replicates the same pattern. | In scope D6. |

**Total grep hits:** 31 — of which the planning doc counted "23 remaining" because it correctly excluded the two in-scope coordinator-setattr fixes plus the 6 already-guarded `is not None and == "on"` sites. The table here lists all 31 explicitly so reviewers can verify scope. The classification distinguishes coordinator-setattr (HIGH risk; matches the incident pattern) from self-attr (LOWER risk; entity-local).

**Recommended follow-up cycle:** Apply the same skip-guard to the ~9 HIGH-risk coordinator-setattr sites (rows 2-6, 10, 12, 14, 15, 26). Self-attr sites can either get the guard for consistency or be left alone (LOW-MED, no cross-coordinator blast).

### D7 — Degraded observability + B4 live-health coverage check (operator-approved addendum)

**(a) `envoy_degraded` + `envoy_degraded_since` attributes on
`sensor.ura_energy_envoy_status`.** REUSED existing host sensor — the
EnergyEnvoyStatusSensor at `sensor.py:10336` is the natural EC
diagnostic for envoy state (already exposes `offline_count_today` /
`last_reading_time` / `data_anomaly_at`). No new entity created.

Source of truth: two new EC instance attrs
(`_envoy_degraded` + `_envoy_degraded_since`) maintained inside the
existing per-cycle envoy availability tracker
(`energy.py:_track_envoy_availability`). The flag is set True on the
first unavailable cycle (and `_since` stamped via
`dt_util.now().isoformat()`); both clear when the envoy recovers
(`envoy_available=True`). This piggybacks on the existing
`envoy_available` decision signal — the same signal that already drives
`_envoy_unavailable_count` / `_envoy_last_available` — so the source is
the real per-cycle entity reads, not a separate poll.

Files touched (D7a, ~20 LoC total):
- `domain_coordinators/energy.py` (+13 LoC) — two new `__init__` attrs +
  set/clear in `_track_envoy_availability`.
- `sensor.py` (+11 LoC) — two new keys in
  `EnergyEnvoyStatusSensor.extra_state_attributes`.

Acceptance criteria (D7a):
- **Live:** post-deploy, `sensor.ura_energy_envoy_status` exposes
  `envoy_degraded: bool` and `envoy_degraded_since: <iso|null>` in its
  attribute panel within the first decision cycle (~5 min).
- **Live:** when Envoy is offline, `envoy_degraded` flips True and
  `envoy_degraded_since` carries the streak-start ISO timestamp; on
  recovery both clear in the same cycle that resets
  `offline_count_today` to 0.
- **Verify:** attribute is observable via the existing
  `SIGNAL_ENERGY_ENTITIES_UPDATE` push — no new signal needed.

**(b) B4 live-health watch-list coverage check.** Reviewed commits
`8484844` (B4 live-health repair), `5e6caf5` (B4 Tier 2 fix-up), and
`3211659` (B4 review ledger). B4 was a sensor-availability and display
repair (EnergyGridDemandSensor `available`-gate removal, predicted-
energy display sign, occupancy-weighted persistence-lock verification);
it did NOT introduce a critical-entity health watch list or a
per-cycle envoy-entity health monitor. There is no data structure to
extend.

Verified by grep across `repairs.py` + `domain_coordinators/` for
`live.health` / `watch_list` / `watched_entities` / `critical_entities`
— zero hits beyond the validator's own `ENVOY_REQUIRED_DERIVED_KEYS`.
The post-deploy surface for "critical envoy entities missing/unavailable"
in this cycle is therefore:
- **At startup**: D1's three-way `validate_envoy_config` —
  registry-absent → hard fail + repair issue; registry-known + state
  missing/unavailable → degraded (warnings, EC proceeds).
- **Per-cycle**: EC's existing `envoy_available` decision signal
  (driven by the entity reads in the battery decision loop) — now
  also drives the new D7a `_envoy_degraded` / `_envoy_degraded_since`
  attrs surfaced on `EnergyEnvoyStatusSensor`.
- **Post-EVENT_HOMEASSISTANT_STARTED**: D3's deferred re-validation —
  raises / refreshes / clears `energy_envoy_invalid_<entry_id>` once
  the boot-race window has settled.

**Coverage decision:** no B4 watch-list edit needed. Documented here per
operator instruction "If yes, document the coverage in the review
ledger's Build notes."

### Deviations from plan

- D7 added (operator-approved addendum) — see preceding section.
- All D1-D6 implemented as specified.
- Operator decisions applied:
  1. `test_envoy_auto_derive.py` v4.2.29 V2 assertions re-contracted INLINE (no TODOs / skips).
  2. No snapshots directory created (deploy-step concern).
  3. No vibememo entry.

### Pre-deploy zero-bugs gate (builder pre-check)

- `grep -rn '<<<<<<<' custom_components/universal_room_automation/` → 0.
- `python3 -m py_compile` on every touched `.py` → clean (run in DoD section).
- Test-suite tally → DoD section.

---

## Review A — Boot-sequence correctness + race conditions

*To be filled by Reviewer A.*

## Review B — Validation semantics + repair-flow integrity

*To be filled by Reviewer B.*

## Review C — Restore / RestoreEntity lifecycle + test authority

*To be filled by Reviewer C.*

## Review D — Live validation (post-restart)

*To be filled by ura-validator.*
