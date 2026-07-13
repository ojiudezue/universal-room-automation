# Envoy Command Redundancy + Write-Verification

**Cycle:** URA energy — Envoy/Enphase write-verification tripwire, cloud read-fallback, dormant write-failover.
**Branch:** `develop` (feature branch: `feature/envoy-write-verification`).
**Tier (recommendation):** **Tier 2-DB (3 framing-disjoint reviews) minimum.** If D3 auto-failover ships in this cycle rather than dormant → **Tier 3 (4 reviews incl. adversarial completeness pass D)**. See §Tier justification.
**Operator elevation:** YES — regression-prone trust-hierarchy work (battery ↔ EVSE ↔ NM ↔ compliance). Standing policy applies.
**Filed:** 2026-07-13. Skills loaded pre-plan: `ura-energy-invariants-campaign`, `ura-energy-strategy-reference`.

---

## Institutional context verified (proof-of-work)

Exhaustive grep-and-cite audit per CLAUDE.md "Institutional Context First." Each proposed addition is tagged REUSED (with file:line) or NEW (with justification of why nothing equivalent exists).

### Prior-art matrix — "don't we have that already?"

| Concern raised | Found? | Where | Verdict |
|---|---|---|---|
| Compliance verify framework (schedule → wait → compare → anomaly → NM) | **YES** | `coordinator_diagnostics.py:334-626` — `ComplianceTracker.schedule_check` (2 min delay), `_check_compliance`, `_compare_states`, `_detect_override_source`, `_emit_compliance_violation_anomaly`. Wired into `manager.py:153,242` and exposed on every coordinator via `base.py:186`. | **REUSE for D1.** No new machinery. Add battery-write device_type + energy-domain scheduler call. |
| Commanded-value ledger for reserve | **YES** | `energy_battery.py:244` `_last_reserve_level: int | None`, set at `:3329` inside `_result()`. | **REUSE as canonical "commanded" side of the reconciliation.** |
| Commanded-value ledger for charge_from_grid | **PARTIAL** | Live-switch LKG latch `_last_known_grid_charge_on` in `energy.py:3213-3247` reads the **applied local** switch — this is applied-side, NOT commanded-side. The commanded value lives only inside the current decision dict (`decision["charge_from_grid"]`) and is not persisted per-write. | **NEW (small):** `_last_charge_from_grid_command: bool | None` + timestamp, populated at the actual `switch.turn_on/off` dispatch site. Justification: without a commanded-side ledger you cannot detect a REVERSION (operator failure mode #c). |
| Commanded-value ledger for storage_mode | **NO** | Grep of `energy*.py` for `storage_mode` shows reads but no persisted "last-commanded" field. | **NEW (small):** `_last_storage_mode_command: str | None` + timestamp. |
| Central write-target routing (choke point) | **YES** | `BatteryStrategy._get_entity(key, default)` at `energy_battery.py:474-482`, backed by `_entities` dict populated from `_build_entity_map()` at `energy.py:700-724`. Every reserve/mode/switch read AND every dispatch site funnels through `_get_entity`. | **REUSE as the redundancy choke point for D2/D3.** No new plumbing. |
| Per-surface entity-override config keys | **YES** | `energy_const.py:178-184` — `CONF_ENERGY_BATTERY_SOC_ENTITY`, `CONF_ENERGY_STORAGE_MODE_ENTITY`, `CONF_ENERGY_RESERVE_SOC_ENTITY`, `CONF_ENERGY_CHARGE_FROM_GRID_ENTITY`. Already user-overridable via options flow. | **REUSE as override path** — the operator can already point any surface at the cloud entity by editing the URL entity in options. No new config keys required for MVP. |
| Ranked-list fallback precedent (multi-source) | **YES** | `energy_const.py:190-191` `CONF_ENERGY_WEATHER_FALLBACK_1/2` (`WeatherProviderManager`), plus `_last_known_grid_charge_on` blip-latch philosophy (`energy.py:3213`). | **REUSE the "primary + fallbacks + blip-latch" pattern.** Same shape for SOC read fallback. |
| Anomaly bus / DAO (v4.7.12 discriminator) | **YES** | `energy_battery.py:2111-2122` and `:4471-4494` already emit `AnomalyEvent` via `AnomalyType.POINT_IN_TIME`. | **REUSE for mismatch and reversion events.** No new event class. |
| NM alert path | **YES** | `energy.py:4422-4456` `_send_nm_alert(title, message, severity, hazard_type, location)` — `hass.data[DOMAIN]["notification_manager"]`, `Severity` mapping already present. | **REUSE for the CRITICAL mismatch alert.** No new signal. |
| Once-per-day trip-latch precedent | **YES** | `energy.py:317` `_fill_priority_nm_trip_date` (per-day date-stamp to suppress repeat NM sends). | **REUSE pattern** for `_write_verify_nm_trip_date_by_surface`. |
| Battery-strategy attribute surface | **YES** | `sensor.py:6766-6800` + `energy_battery.get_status()` at `:3332`. Attrs like `arbitrage_phase`, `inclement_hold_depth`, `inclement_reserve_floor`, `evse_battery_hold_active` already published. | **REUSE — extend get_status()** with new keys (see §D1). No new sensor. |
| Cloud oracle entity ids | **NO USAGE, but user-manual references** | `docs/user-manual/ENERGY_COORDINATOR.md` mentions `iq_battery_hacs` / `enphase_ev`. No code path reads them. | **NEW (constants only):** three `CLOUD_ORACLE_*` string defaults in `energy_const.py`. Hard-wired per operator directive #1 ("least churn"); no config-flow field unless override needed. |

### Files read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — write dispatch sites, `_build_entity_map`, LKG latch, NM path, compliance-tracker access via inherited `base`.
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — `_get_entity`, `_last_reserve_level`, `_result`, storage_mode read, attain drift-detection at :2720 (the ONLY existing "operator revert" handler; scoped to attain only).
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — CONF_* and DEFAULT_* constants for reserve/mode/charge switch entities; weather-fallback precedent.
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` — `ComplianceTracker`, `ComplianceRecord`, `_compare_states`, `_emit_compliance_violation_anomaly`.
- `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py` — AnomalyEvent shape, AnomalyType discriminator.

### Prior planning + memory bodies pulled
- `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md` (skim) — attain drift-detection pattern (energy_battery.py:2720-2754) is prior art for "commanded ON, observed OFF → operator wins" — but scoped only to attain; **the analogous surface-level tripwire is what this cycle generalizes**.
- MEMORY body `project_battery_soc_envoy_not_span` (2026-06-16) — SOC = Envoy, NOT SPAN; also documents Enpower reserve number vs Envoy-reported reserve divergence (80 vs 20). **That divergence IS the failure mode this cycle detects.**
- MEMORY body `project_envoy_boot_incident_2026_06_12` — RestoreEntity `unavailable→OFF` poisoning (Bug Class #52). Guides D2 SOC failover: `unavailable` reads must not trip a divergence event.
- Skill `ura-energy-strategy-reference` §10 (source-trust hierarchy) + §12 (sensor attribute surface): rank order (Envoy > SPAN) is binding; reserve number is a "lever we write to" but is NOT the applied truth.

### Design docs read
- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` §5–6 (write dispatch philosophy).
- Skill `ura-energy-invariants-campaign` §Phase 0–2 (invariant-first planning, mutation-anchored tests).

### Bug-class linkage (from `docs/QUALITY_CONTEXT.md`)
- **#7 Stale data source** — SOC read fallback protects against silent staleness.
- **#22 Enum/value mismatch** — storage_mode `"self_consumption"` vs cloud `"Self-Consumption"` — **explicitly designed for; see D1.4**.
- **#46 Owner-set collision** — separate `_last_*_command` fields per surface (do NOT collapse).
- **#52 RestoreEntity unavailable→OFF poisoning** — SOC failover must ignore `unavailable`/`unknown` reads.
- **#53 Computed-but-not-consumed** — the reserve-strategy attribute claims a value the hardware may not honor. **This cycle closes the #53 blindspot for reserve** by tying the claimed attribute to observed applied state via the cloud oracle.

### Grep evidence appended to plan (raw)
```
$ grep -n "_last_reserve_level" energy_battery.py
244:        self._last_reserve_level: int | None = None
744:        if self._last_reserve_level is not None:
745:            return int(self._last_reserve_level)
3329:            self._last_reserve_level = int(max(0, min(100, reserve_level)))

$ grep -n "compliance_tracker\|schedule_check" energy.py energy_battery.py
(no hits — ComplianceTracker never invoked from energy)

$ grep -n "_get_entity\b" energy_battery.py | head
474:    def _get_entity(self, key: str, default: str | None = None) -> str | None:
517: (battery_soc)  522: (solar_production)  530: (net_power)
545,560: (battery_power)  586: (arbitrary key)  627: (storage_mode)
634: (grid_enabled)  642: (solcast_today)

$ grep -n "_send_nm_alert\|notification_manager" energy.py | head
4422-4456: _send_nm_alert(title, message, severity, hazard_type, location)
4432:        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
```

---

## Falsifiable invariants (Phase-0 gate, per skill)

State these verbatim now; adversarial-completeness review MUST falsify them.

| ID | Falsifiable invariant | Falsified by (concrete legal-config repro shape) |
|---|---|---|
| **W-1 (write applied)** | For every commanded write `(surface, value, t0)` emitted by URA into a healthy Enphase link, within `verify_window_s` (default 900s = 15 min) either (a) the cloud oracle entity for `surface` reads `value`, or (b) a `write_verification_failed` anomaly is emitted AND a per-surface per-day NM alert has fired. | A commanded reserve write of 50% where the cloud oracle 15 min later reads 30% AND no anomaly/NM fires. |
| **W-2 (no silent reversion)** | For any surface where `t1 > t0 + verify_window_s`, if URA has NOT issued a new command since `t0` and the cloud oracle at `t1` differs from `_last_<surface>_command`, a `write_reverted` anomaly MUST be emitted (once per reversion, coalesced by surface). | Cloud oracle flips from URA-commanded 50 → 30 with no URA intervening command, and no anomaly emits. |
| **W-3 (SOC read fallback closed-loop)** | For any decision cycle, `battery_soc` returned to strategy is (i) the primary Envoy sensor when its state is a valid float, (ii) the LKG cache when the Envoy read is `unavailable`/`unknown`/None AND the outage is < `soc_lkg_max_age_s` (default 300s), or (iii) the cloud fallback entity when the outage exceeds that AND the fallback reads a valid float. NO decision may run against `None` while (ii) or (iii) is available. | `sensor.envoy_*_battery` shows `unavailable` for 6 min, cloud fallback reads 42%, `determine_mode` still receives `soc=None`. |
| **W-4 (source divergence bounded)** | While BOTH primary Envoy SOC and the cloud fallback SOC are simultaneously available and non-stale, `|primary − fallback| ≤ 3 percentage points`. Larger divergence emits a `soc_source_divergence` anomaly (throttled to 1/hour). | Envoy=71, cloud=97 (the operator-observed condition from memory `project_battery_soc_envoy_not_span`) with no divergence anomaly. |
| **W-5 (LKG-latch non-poisoning under failover)** | If D3 write-failover is engaged and repoints `charge_from_grid` WRITES to the cloud entity, the READ used by the LKG latch at `energy.py:3213-3247` must be repointed to the SAME entity in the SAME tick — no split-brain where writes go one place and the reader reads the other. | D3 engaged; writes go to cloud switch; the LKG latch continues reading the local `enpower_*_charge_from_grid` and reports OFF while cloud is ON → EVs resume during a grid charge. |
| **W-6 (verification never actuates)** | The verification path (D1) MUST NOT itself issue any actuation (`switch.turn_on/off`, `number.set_value`, `select.select_option`). It reads, compares, and emits telemetry only. | Any `hass.services.async_call` inside the verifier module. |

---

## Operator failure modes explicitly designed for

Per operator directive #3, the tripwire covers three shapes:

| Shape | Detection window | Signal |
|---|---|---|
| **(a) Local write rejected immediately** | On dispatch tick: the applied local entity fails to move to the commanded value within one decision cycle. | `write_rejected_local` anomaly + surface counter increment. |
| **(b) Accepted locally, never reaches cloud** | Cloud oracle at `t0 + verify_window_s` (default 15 min, configurable 300–1800) does not reflect the commanded value even though the local entity does. | `write_not_propagated` anomaly + NM CRITICAL. Falsifies W-1. |
| **(c) Applied then silently reverted** | Cloud oracle at any tick `t > t0 + verify_window_s` differs from `_last_<surface>_command` and no URA command has intervened. | `write_reverted` anomaly + NM CRITICAL. Falsifies W-2. |

Shape (b) is the operator-observed charge_from_grid failure this week. It is the primary target.

---

## Deliverables

### D1 — Write-verification tripwire (PRIMARY, per operator directive #2)

**Scope:** three surfaces — `reserve_level` (Enpower number), `charge_from_grid` (Enpower switch), `storage_mode` (Enpower select). Cloud oracle = HACS `enphase_ev` entity for each.

**D1.1 — Constants (energy_const.py, NEW).**
```python
# Cloud oracle entity defaults (HACS enphase_ev integration).
# Hard-wired per "least churn" directive; operator overrides by editing
# CONF_ENERGY_*_ENTITY in options if their install differs.
CLOUD_ORACLE_RESERVE_SOC_ENTITY: Final = "number.iq_battery_hacs_battery_reserve"
CLOUD_ORACLE_CHARGE_FROM_GRID_ENTITY: Final = "switch.iq_battery_hacs_charge_battery_from_grid"
CLOUD_ORACLE_STORAGE_MODE_ENTITY: Final = "select.iq_gateway_hacs_system_profile"

# Verify window: cloud propagation lag observed 5–10 min; default 15 for margin.
DEFAULT_WRITE_VERIFY_WINDOW_S: Final = 900
MIN_WRITE_VERIFY_WINDOW_S: Final = 300
MAX_WRITE_VERIFY_WINDOW_S: Final = 1800

# Reversion re-scan interval: every decision cycle already covers this.

# Storage-mode value mapping (Bug Class #22 guard).
# Local Enpower select uses snake_case; cloud select uses Title-Case.
STORAGE_MODE_LOCAL_TO_CLOUD: Final[dict[str, str]] = {
    "self_consumption": "Self-Consumption",
    "backup": "Backup",
    "savings": "Savings",   # confirm live before ship
    "full_backup": "Full Backup",
}
# Inverse computed at load: STORAGE_MODE_CLOUD_TO_LOCAL

# Once-per-day NM trip-latch scope.
WRITE_VERIFY_NM_SURFACES: Final = ("reserve_soc", "charge_from_grid", "storage_mode")
```

**D1.2 — Commanded-value ledger (energy_battery.py).**
- REUSE `_last_reserve_level` at :244/:3329.
- **NEW** two fields on `BatteryStrategy`:
  ```python
  self._last_charge_from_grid_command: bool | None = None
  self._last_charge_from_grid_command_at: datetime | None = None
  self._last_storage_mode_command: str | None = None   # local snake_case
  self._last_storage_mode_command_at: datetime | None = None
  self._last_reserve_level_at: datetime | None = None  # timestamp companion
  ```
- Set inside `_result()` at the SAME place `_last_reserve_level` is set (:3329-ish). Update timestamps only when the value CHANGES from previous.

**D1.3 — Dispatch-site tap (energy.py).**
- At each `switch.turn_on/off`, `number.set_value`, `select.select_option` for the three surfaces (locate via `grep -n "async_call.*charge_from_grid\|reserve_battery\|storage_mode"`), after successful dispatch call:
  ```python
  await self._write_verifier.schedule(
      surface="reserve_soc",  # or "charge_from_grid" / "storage_mode"
      commanded_value=<value>,
      commanded_at=dt_util.utcnow(),
  )
  ```
- The verifier module (`energy_write_verify.py`, **NEW small file, ~180 LoC**) wraps a `ComplianceTracker`-style `schedule_check` using `async_call_later(hass, verify_window_s, ...)`.

**D1.4 — Verifier semantics (`energy_write_verify.py`).**
- Compare commanded vs oracle read using per-surface mapping:
  - `reserve_soc`: numeric equality within ±1 pt tolerance (rounding).
  - `charge_from_grid`: bool equality (`"on"` / `"off"`).
  - `storage_mode`: normalize both to local snake_case via `STORAGE_MODE_CLOUD_TO_LOCAL` before compare. **Any unmapped cloud value → emit `write_verification_unmapped_mode` anomaly and treat as inconclusive (do NOT alert as mismatch).**
- Oracle read `unavailable`/`unknown`/None → emit `write_verification_inconclusive` at DEBUG (not an alert; keep NM quiet on Enphase cloud outages).
- Mismatch after valid oracle read → emit `write_verification_failed` AnomalyEvent (`AnomalyType.POINT_IN_TIME`, severity WARNING) via existing bus; if surface has not fired NM today (`_write_verify_nm_trip_date_by_surface`), also `_send_nm_alert(..., severity="critical")`.

**D1.5 — Reversion watcher (per-cycle).**
- Add a per-cycle sweep at the tail of `_async_decision_cycle` (energy.py). For each surface with a non-None commanded value AND commanded_at older than `verify_window_s`:
  - Read cloud oracle. If read differs from `_last_<surface>_command` AND no NEW command has been dispatched since commanded_at → emit `write_reverted` anomaly + NM CRITICAL (same once-per-day latch).
  - Bookkeeping: track `_last_reversion_at_by_surface` to coalesce a stuck-reverted state (do not spam every 5 min once we know a reversion is standing).

**D1.6 — Diagnostic surface (attrs on `sensor.ura_battery_strategy` via `get_status()`).**
- REUSE `energy_battery.get_status()` at :3332. Add keys:
  - `last_verified_write_reserve_soc: {commanded, oracle_seen, verified_at, status}` where status ∈ `{ok, mismatch, reverted, inconclusive, unmapped, no_data}`.
  - `last_verified_write_charge_from_grid: {...}`
  - `last_verified_write_storage_mode: {...}`
  - `write_mismatch_counts_24h: {reserve_soc: N, charge_from_grid: N, storage_mode: N}`
- Backing storage: RAM-only dict maintained by the verifier module; expose via a read-only accessor on `EnergyCoordinator`. No DB migration.

**D1.7 — Optional single override key (kept minimal; ONLY if operator's HACS entity ids differ).**
- Reuse existing `CONF_ENERGY_RESERVE_SOC_ENTITY`, `CONF_ENERGY_CHARGE_FROM_GRID_ENTITY`, `CONF_ENERGY_STORAGE_MODE_ENTITY` for **write** targets (unchanged, primary).
- **NEW three config keys ONLY IF needed** — deferred to a fast-follow if hard-coded defaults resolve:
  - `CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY`, `CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY`, `CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY`.
- MVP ship: constants only. Add config keys reactively if a live install can't resolve the hard-wired names.

### D2 — SOC read fallback (via `_get_entity` choke point)

**D2.1 — Constants (energy_const.py).**
```python
CLOUD_FALLBACK_BATTERY_SOC_ENTITY: Final = "sensor.iq_battery_hacs_battery_overall_charge"
DEFAULT_SOC_LKG_MAX_AGE_S: Final = 300    # 5 min blip-latch parity
DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT: Final = 3
```

**D2.2 — Battery SOC property refactor (energy_battery.py:515-517).**
Replace:
```python
@property
def battery_soc(self) -> float | None:
    return self._get_state_float(self._get_entity("battery_soc"))
```
With a three-tier resolver (primary → LKG → cloud fallback), **all reads still go through `_get_entity`**:
```python
@property
def battery_soc(self) -> float | None:
    primary = self._get_state_float(self._get_entity("battery_soc"))
    if primary is not None:
        self._soc_lkg = primary
        self._soc_lkg_at = dt_util.utcnow()
        # cross-check on healthy read only
        self._check_soc_source_divergence(primary)
        return primary
    # Primary unhealthy — LKG within window?
    if self._soc_lkg is not None and self._soc_lkg_at is not None:
        age = (dt_util.utcnow() - self._soc_lkg_at).total_seconds()
        if age <= DEFAULT_SOC_LKG_MAX_AGE_S:
            return self._soc_lkg
    # LKG stale — cloud fallback.
    fallback = self._get_state_float(
        self._get_entity("battery_soc_cloud", CLOUD_FALLBACK_BATTERY_SOC_ENTITY)
    )
    if fallback is not None:
        _LOGGER.warning("SOC primary + LKG unavailable — using cloud fallback %.1f", fallback)
        self._emit_soc_fallback_active()   # once per outage; anomaly bus
        return fallback
    return None
```
- `_soc_lkg` / `_soc_lkg_at` initialized in `__init__`.
- Divergence check: emit `soc_source_divergence` anomaly (WARNING) if `|primary − fallback| > threshold`, throttled to 1/hour via `_last_soc_divergence_at`.
- **Bug Class #52 guard:** `_get_state_float` already returns None on `unavailable`/`unknown` (:489), so the three-tier resolver treats them uniformly. No RestoreEntity poisoning risk introduced.

**D2.3 — Extend `_build_entity_map` (energy.py:704).**
- Add mapping `"battery_soc_cloud"` → cloud fallback entity id (from constant, with no CONF_ override in MVP; the caller passes the constant as default to `_get_entity`, so no map entry needed unless override is added).

### D3 — Dormant write-failover (DEFERRED activation, DESIGNED HERE)

**Operator directive #4:** local core `enphase_envoy` stays primary for writes; cloud `enphase_ev` is dormant write-failover activated when D1's tripwire proves local writes dead/reverting.

**D3.1 — Routing extension in `_get_entity` (energy_battery.py:474).**
- Add optional `role` parameter:
  ```python
  def _get_entity(self, key: str, default: str | None = None, *, role: str = "read") -> str | None:
      # role ∈ {"read", "write"}
      if role == "write" and self._write_failover_engaged_for(key):
          return self._cloud_write_target(key, default)
      return self._entities.get(key, default)
  ```
- Backwards-compatible: all existing calls default to `role="read"` (unchanged semantics). New dispatch sites pass `role="write"`.
- `_write_failover_engaged_for(key)` reads a per-surface bool set on `BatteryStrategy._write_failover_by_surface: dict[str, bool]`, defaulting to False. **Ship dormant** — no code path flips it True in this cycle.

**D3.2 — Activation policy (DESIGN ONLY, ship as dormant switches).**

| Surface | Recommended policy | Justification |
|---|---|---|
| `reserve_soc` (number) | **Auto-failover** after N (default 3) consecutive `write_reverted` events, RESET on any successful verified write. | Reserve write is idempotent, safe to re-issue via cloud; cost of a bad reserve = missed peak (financial), not safety. |
| `charge_from_grid` (switch) | **Operator-confirmed only** (button entity `button.ura_energy_engage_cloud_write_failover_charge_from_grid`). | **W-5 concern:** the LKG latch at `energy.py:3213` reads the local switch to keep EVs paused. Auto-repointing writes without repointing that read would leave a window where a cloud-commanded ON is not visible to the resume-guard for up to `verify_window_s`. Requires a coupled read+write repoint AND an operator ack. |
| `storage_mode` (select) | **Auto-failover** after N=3 consecutive reversions. | Mode change is idempotent and non-safety-critical (backup vs self_consumption). |

**D3.3 — Coupled read+write repoint for `charge_from_grid` (W-5 enforcement).**
- When `_write_failover_engaged_for("charge_from_grid")` flips True, the `_get_entity("charge_from_grid", ...)` call at `energy.py:3215` — which reads the LKG latch — MUST also resolve to the cloud entity. Design: pass `role="read_write_coherent"` at that specific site, OR add a companion `_read_target_for_write("charge_from_grid")` that returns the currently-active write target. **This is the load-bearing invariant W-5 test.**

**D3.4 — Dormant switches to expose (NEW, three switches).**
- `switch.ura_energy_cloud_write_failover_reserve_soc` (default OFF; auto-flipped by policy)
- `switch.ura_energy_cloud_write_failover_charge_from_grid` (default OFF; operator-only)
- `switch.ura_energy_cloud_write_failover_storage_mode` (default OFF; auto-flipped by policy)
- Each is `RestoreEntity` with the standard `unavailable→OFF` guard (Bug Class #52).
- Persist via existing coordinator DB pattern (see EV off-peak persistence at `energy_pool.py:471,502,563` for the model).

**D3.5 — D3 ship posture: DORMANT.**
- MVP ships D3.1 (routing scaffolding) + D3.4 (switches, default OFF, non-auto-flipping) + full policy design doc.
- Auto-failover promotion (D3.2 policies) is a **fast-follow cycle** gated on 2 weeks of D1 telemetry showing whether reversions are a real steady-state condition.
- **This keeps this cycle at Tier 2-DB.** A cycle that also enables auto-failover WOULD be Tier 3.

---

## Files touched

| File | Change | Est LoC |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/energy_const.py` | Add cloud oracle constants + verify window bounds + storage-mode value map. | ~30 |
| `custom_components/universal_room_automation/domain_coordinators/energy_write_verify.py` | **NEW.** `WriteVerifier` class: schedule, delayed compare, anomaly emit, NM latch, reversion sweep, get_status accessor. | ~200 |
| `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` | Add `_last_charge_from_grid_command*`, `_last_storage_mode_command*`, `_soc_lkg*`, three-tier `battery_soc` resolver, `_check_soc_source_divergence`, extend `get_status()` with verified-write keys, `_get_entity` role kwarg (backwards-compatible default). | ~120 |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | Instantiate `WriteVerifier` in `__init__`; tap dispatch sites for three surfaces; reversion sweep at end of `_async_decision_cycle`; NM alert wrapper. | ~80 |
| `custom_components/universal_room_automation/switch.py` | Register 3 `RestoreEntity` failover switches. | ~90 |
| `custom_components/universal_room_automation/domain_coordinators/signals.py` | (Likely no new signals — reuse anomaly bus.) | 0 |
| `quality/tests/test_energy_write_verification.py` | **NEW.** Per-surface mutation-anchored tests. | ~250 |
| `docs/readmes/README_v<version>.md` | Prospective + post-live-validation table. | ~120 |

Total: ~890 LoC across ~7 files. Additive; no schema migration.

---

## Acceptance criteria

### D1 write-verification tripwire

**Verify (unit):**
- `WriteVerifier.schedule("reserve_soc", 50, t0)` + oracle returns 50 at `t0 + 900s` → status `ok`, no anomaly, no NM.
- Same call + oracle returns 30 at `t0 + 900s` → status `mismatch`, anomaly emitted, NM CRITICAL fires ONCE for this surface today.
- Second mismatch same day → anomaly emitted, NM does NOT re-fire.
- Oracle returns `unavailable` at check time → status `inconclusive`, DEBUG log, no NM.
- Storage-mode oracle returns unmapped string `"Something-Else"` → `write_verification_unmapped_mode` anomaly, no NM.
- **Reversion:** commanded reserve=50 at t0; oracle=50 at t0+900s (OK); oracle=30 at t0+1800s with no new command → `write_reverted` anomaly + NM CRITICAL.

**Verify (mutation-anchored, per skill Phase 4):**
- Neuter the reversion-sweep call in `_async_decision_cycle` → a specific test `test_reversion_sweep_detects_silent_flip` FAILS.
- Neuter the `_last_charge_from_grid_command` write in `_result()` → `test_charge_from_grid_reversion_requires_commanded_ledger` FAILS.
- Neuter the storage-mode value normalization → `test_storage_mode_case_mismatch_is_not_alerted` FAILS.

**Sensor:** `sensor.ura_battery_strategy` attributes include `last_verified_write_reserve_soc` (dict with `{commanded, oracle_seen, status}`) and `write_mismatch_counts_24h`.

**Test:** `test_energy_write_verification.py::{test_verify_ok, test_verify_mismatch_alerts_once_per_day, test_verify_inconclusive_no_alert, test_reversion_detected, test_unmapped_storage_mode, test_verifier_never_calls_service}`.

**Live:**
- After deploy, `sensor.ura_battery_strategy` shows `last_verified_write_reserve_soc.status == "ok"` within 30 min of any URA reserve write (there is at least one write per decision cycle for arbitrage phases).
- **Operator-simulated failure:** operator flips `switch.iq_battery_hacs_charge_battery_from_grid` in the Enphase app while URA thinks it's OFF → within one decision cycle + verify_window (~15 min), NM CRITICAL fires ("charge_from_grid reverted from OFF to ON") AND `sensor.ura_battery_strategy.last_verified_write_charge_from_grid.status == "reverted"`.
- No spurious NM during a real Enphase cloud outage (cloud oracle `unavailable` for 30 min → `write_mismatch_counts_24h` stays at 0, only DEBUG lines).

### D2 SOC read fallback

**Verify (unit):**
- Envoy=71 valid → `battery_soc == 71`, LKG updated.
- Envoy=`unavailable` for 200s (< 300s), LKG=71 → `battery_soc == 71` from LKG, no fallback engage.
- Envoy=`unavailable` for 400s (> 300s), cloud=42 → `battery_soc == 42`, `write_verification_inconclusive`-family SOC-fallback event emitted once.
- Envoy=71 AND cloud=97 both valid → divergence anomaly emitted, `battery_soc == 71` (primary wins).
- Envoy=`unavailable` AND cloud=`unavailable` → `battery_soc is None`, decision path takes Envoy-degraded branch (existing behavior preserved).

**Test:** `test_energy_write_verification.py::{test_soc_primary, test_soc_lkg_within_window, test_soc_cloud_fallback, test_soc_divergence_anomaly, test_soc_both_unavailable}`.

**Live:**
- `sensor.ura_battery_strategy` attribute `soc_source ∈ {envoy, lkg, cloud_fallback}` (add to `get_status`).
- Operator manually disables the local core `enphase_envoy` integration for 10 min → `soc_source` transitions to `cloud_fallback`, decisions continue without None-SOC hold, log shows the transition.

### D3 dormant failover

**Verify (unit):**
- All three failover switches default OFF post-restart even after RestoreEntity restores `unavailable` (Bug Class #52 guard test).
- `_get_entity("reserve_soc_number", role="write")` with switch OFF → returns local Enpower entity. With switch ON → returns cloud entity.
- **W-5 enforcement test:** with `charge_from_grid` failover switch ON, both the write dispatch site (energy.py near dispatch) AND the LKG-latch read site (energy.py:3215) resolve to the cloud entity in the same tick. Mutation: neuter the read-repoint → dedicated test `test_charge_from_grid_failover_read_write_coherent` FAILS.

**Test:** `test_energy_write_verification.py::{test_failover_switches_default_off, test_failover_read_write_coherent, test_failover_no_actuation_on_flip}`.

**Live:**
- Failover switches visible in UI, default OFF, do not auto-flip during 24h of normal operation.
- Manually flipping `switch.ura_energy_cloud_write_failover_reserve_soc` ON does NOT trigger any actuation — the next URA-issued reserve write goes to cloud instead of local; verified via `last_verified_write_reserve_soc.commanded_to` attribute.

---

## Tier justification

Per CLAUDE.md standing policy: **regression-prone work → 3 framing-disjoint reviews minimum.** This cycle:
- Touches the shared `_get_entity` write-target primitive consumed by every emission site (§Phase 1 surface).
- Cross-coordinator ripple: presence-EVSE-battery-NM (Bug Class #46 territory).
- Changes payload shape of the strategy sensor attribute surface.
- Adds a new anomaly-emitter path (write_verification_failed / reverted / soc_divergence).

Meets Tier 2-DB triggers (payload shape change; new behavioral tests against real production paths; shared primitive change).

**Recommended review framings (Tier 2-DB, 3 parallel reviewers):**
- **A — Data integrity + strategy invariants preservation.** Does the SOC three-tier resolver preserve existing `Envoy-degraded` branch behavior byte-identically when both primary and fallback are unavailable? Do existing consumers of `battery_soc` see any semantic drift? Does `get_status()`'s attribute set stay backwards-compatible?
- **B — Async + lifecycle + race conditions.** `async_call_later` verify callbacks vs coordinator teardown; NM latch survives restart (date-scoped, not tick-scoped); RestoreEntity `unavailable→OFF` guard on all 3 failover switches; commanded ledger vs `_result()` re-entry.
- **C — New surfaces + test authority.** Every dispatch site actually taps the verifier (per-site source mutation proves each site is anchored). Storage-mode value mapping is symmetric (round-trip). Verifier does not actuate (W-6). NM does not spam under sustained cloud outage.

**If D3 auto-promotion is added to this cycle, elevate to Tier 3** and add Pass D (adversarial completeness): re-enumerate the ENTIRE `_get_entity` call surface (grep from skill Phase 1), verify every write site is covered AND every read site the LKG depends on is coherent under failover. As designed, D3 ships dormant, so Tier 2-DB is sufficient.

---

## Deferred / not in this cycle

- D3 auto-failover activation logic (requires 2 weeks of D1 telemetry — separate cycle).
- Envoy cache extension to persist `_last_<surface>_command` across restart (currently RAM-only; a restart within `verify_window_s` loses the pending verification. Impact: at most one un-verified write per restart, acceptable for MVP).
- SPAN circuit oracle for grid-import cross-check (out of scope — a different verification axis).
- Historization of write-verification outcomes in the URA DB (RAM counters + attrs are sufficient for MVP; DB row cost per verified write across ~24 writes/day per surface × 3 surfaces = ~72 rows/day, acceptable to add later).
- Cloud-entity discovery / registry-scan auto-config (hard-wired defaults per operator directive #1).

---

## Open operator questions (only the truly undecidable)

1. **Cloud oracle entity id confirmation.** The hard-wired defaults (`number.iq_battery_hacs_battery_reserve`, `switch.iq_battery_hacs_charge_battery_from_grid`, `select.iq_gateway_hacs_system_profile`) — can you confirm these exist verbatim on your live install? If not, MVP needs D1.7's three CONF_* keys added before ship.
2. **Storage-mode value set.** The value map covers `self_consumption`, `backup`, `savings`, `full_backup`. Any modes actually used on your install NOT in that list? Unmapped values are treated as inconclusive (no false alert), but a live-known mapping is preferable.
3. **Verify window default.** 15 min based on your "cloud lag 5–10 min" observation. Comfortable, or would you prefer 10 min (tighter, more inconclusives) or 20 min (looser, misses fewer real reversions)?
4. **D3 charge_from_grid activation policy.** Operator-confirmed only (button/switch), per W-5 concern about the LKG latch. Confirm you accept manual-only, or want me to design a safer auto policy (coupled read+write repoint on flip) in this cycle rather than the fast-follow.
