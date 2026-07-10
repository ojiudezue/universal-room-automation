# PLANNING — SPAN Circuit-Identity Re-Key (post-v5.11.0)

Branch: `develop` → feature branch `feature/span-circuit-rekey`
Tier: **Tier 2-DB** (touches DB persistence key shape + one-shot migration + shared `metric_baselines` table consumed by 3 subsystems).
Base research: `docs/planning/RESEARCH_span_architecture_2026-07-10.md` (read in full).

## Falsifiable invariant (Tier-2-DB shape, D pass welcome)

Under any legal upstream state — including SPAN-app circuit rename between
boot N and boot N+1 — a `circuit_power` baseline that was warm before the
rename (`sample_count >= CIRCUIT_MIN_SAMPLES`) MUST remain warm and
re-attached to the correct discovered entity_id after the rename, WITHOUT
relearning from 0 and WITHOUT emitting the "no matching circuit" WARN.
Existing non-SPAN baselines (safety `rate_of_change`, diagnostics per-
coordinator scopes, energy `peak_import_kw` / `soc_at_peak_start` /
`daily_import_cost` / `solar_forecast_error_pct`) MUST be byte-identical
across the migration boot.

---

## Institutional context verified (2026-07-10)

### Prior planning / research consulted
- `docs/planning/RESEARCH_span_architecture_2026-07-10.md` (full read) — origin of this cycle; sections A3, B1, B3, B4 are load-bearing.
- `docs/SPAN_REMAP_WORKSHEET.md` — per-room energy config remap, unrelated subsystem; confirmed disjoint from baseline scope key.
- No prior `PLANNING_span_*` in `docs/planning/` (glob confirms first-of-its-kind).

### Memory bodies pulled
- `project_v4_7_x_stretch_closed.md` (v4.7.6 EVSE cycle — introduced `CONF_ENERGY_EVSE_A_ENTITY` / `_B_ENTITY`, `evse_config` plumbing).
- `feedback_no_fabrication_dhcp_incident.md` — reinforces the "verify entity registry semantics before proposing" discipline for the unique_id path.

### Design docs
- `docs/Coordinator/energy.md` (skimmed) — no explicit contract on baseline scope key; free-form TEXT column, subsystem-owned.

### Code locations surveyed (file:line)
- `custom_components/universal_room_automation/domain_coordinators/energy_circuits.py:46-56` — `CircuitInfo(entity_id, friendly_name, panel)`; no `unique_id` field today.
- `energy_circuits.py:79` — `self._circuits: dict[str, CircuitInfo]` keyed by `entity_id`.
- `energy_circuits.py:90-153` — discovery: `hass.states.async_all("sensor")`; friendly comes from `state.attributes["friendly_name"]`. **`entity_registry` is NOT consulted here** — cycle must add the lookup.
- `energy_circuits.py:155-166` — `_get_power_baseline`: `scope = friendly_name` (THE root of the rename bug).
- `energy_circuits.py:197,210,216,250,260,272` — user-facing anomaly emission uses `friendly_name` for `"circuit"` payload; that's display-only, unaffected by scope re-key.
- `energy_circuits.py:293-299` — `get_baselines_for_save` / `restore_baselines` are the persistence hand-off surface (dict keyed by entity_id at runtime — unchanged by this cycle).
- `energy.py:4619-4655` — `_save_energy_baselines` writes `baseline.scope` as-is; no coupling to friendly_name here except that the in-memory scope was set to friendly_name upstream.
- `energy.py:4657-4785` — `_restore_energy_baselines`: the reverse-lookup loop (`circuit.friendly_name == row["scope"]`, energy.py:4707) and the two miss branches (Unmapped-Tab reversible-backup prune at :4725; else WARN + `unmatched += 1` at :4728-4732).
- `energy.py:4745-4767` — `metric_baselines_pruned_backup` table schema + INSERT-before-DELETE pattern is the migration precedent this cycle reuses.
- `energy_pool.py:163-178` — `DEFAULT_EVSE_ENTITIES` hard-codes `switch.span_panel_car_charger_breaker` and `switch.span_panel_garage_b_evse_breaker` under `span_breaker` key.
- `energy.py:5540-5555` — `span_breaker` is consumed as an entity_id in an activation gate.
- `energy_const.py:404-405` — `CONF_ENERGY_EVSE_A_ENTITY`, `CONF_ENERGY_EVSE_B_ENTITY` exist (v4.7.6). No `CONF_..._SPAN_BREAKER_*` today.
- `__init__.py:2409-2427` — evse_config builder; overrides `power` per-EVSE from options but never `span_breaker`.
- `database.py:851-864` — `metric_baselines` schema: PK `(coordinator_id, metric_name, scope)`, `scope TEXT NOT NULL`. Table is SHARED.
- `coordinator_diagnostics.py:824-833, :1085, :1098, :1126, :1152` — generic `AnomalyDetector._get_baseline(metric_name, scope)`; scope is caller-supplied string. Independent of SPAN.
- `safety.py:335-343, :2396-2453` — safety `rate_of_change` baselines: scope is the literal string `"rate_of_change"` (metric_name carries entity_id as `rate:<entity_id>`). Untouched by this cycle.

### Grep for consumers of scope strings
- `Grep MetricBaseline\(` → 5 construction sites; only `energy_circuits.py:161` sets scope = friendly_name. All others use fixed strings or metric-specific scopes.
- `Grep metric_baselines` → save/restore in `safety.py`, `coordinator_diagnostics.py`, `energy.py`; each subsystem filters `WHERE coordinator_id = <own>`. **Cross-subsystem blast radius = zero** provided we don't touch other coordinators' rows.
- `Grep circuits_monitored|active_anomalies|circuit\.friendly_name` in `sensor.py` → no direct expose of scope strings. `friendly_name` still surfaces in anomaly payloads (display-only) — unchanged.

### Proposed additions — REUSED vs NEW
- `CircuitInfo.unique_id: str | None` — **NEW** (no equivalent field on the struct; `energy_circuits.py:46-56`).
- Entity registry lookup helper — **NEW** but standard HA pattern (`homeassistant.helpers.entity_registry.async_get`).
- Migration-completed marker — **NEW**. Reuse the existing `metric_baselines_pruned_backup` table pattern (energy.py:4748) for the pre-migration snapshot; store the marker as a sentinel row in `metric_baselines` itself (`coordinator_id='energy', metric_name='_migration', scope='circuit_scope_v2'`, sample_count=1) — avoids a new table and is naturally idempotent.
- `CONF_ENERGY_EVSE_A_SPAN_BREAKER` / `_B_SPAN_BREAKER` — **NEW** (grep of `energy_const.py` for `SPAN_BREAKER` → 0 hits). Justification below in D2.

---

## Key architectural decision — unique_id, not entity_id

Both are more stable than friendly_name, but they differ:
- **entity_id**: in SPAN's friendly-name mode this IS re-synced on a SPAN-app rename (research A3 line 47-50: *"the `entity_id` derives from the SPAN-app circuit name and is re-synced when the operator renames a circuit"*). So entity_id fails the invariant in the default operator mode.
- **entity_id in circuit-number mode**: stable, but the operator's panels are configured in friendly-name mode; we can't force a naming-mode change on the operator and shouldn't couple to it.
- **unique_id** (via entity registry): documented stable across renames in both modes (research A3 line 50, B4 line 156-158). This is the correct choice.

Decision: **scope = registry unique_id**, resolved once at discover time, cached on `CircuitInfo.unique_id`. `friendly_name` stays on the struct for display only (anomaly payloads, sensor attrs) — no user-visible regression.

Fallback: if a discovered `sensor.span_panel_*_power` entity has NO registry entry (edge case: pre-registration during boot, or a non-SPAN "extra_entity" from a badly-behaved integration), fall back to `entity_id` as the scope. Log at DEBUG. This preserves current behaviour for that circuit until it re-registers.

---

## Deliverables

### D1: `CircuitInfo` carries `unique_id`; scope changes to unique_id

Files: `energy_circuits.py`.

Changes:
- Add `unique_id: str | None` to `CircuitInfo.__init__` (default None).
- In `discover_circuits` (both Tier-1 SPAN branch at :102 and Tier-2 extras branch at :127): call `entity_registry.async_get(self.hass).async_get(entity_id)` → `.unique_id` if entry exists, else None; pass to `CircuitInfo`.
- Change `_get_power_baseline` (:155-166): `scope = circuit.unique_id or circuit.entity_id or friendly_name` (documented fallback chain).
- Keep `friendly_name` on the struct for display; keep anomaly payload fields as-is.

#### Acceptance Criteria
- **Verify:** Every `CircuitInfo` post-discovery has `unique_id != None` for all `sensor.span_panel_*_power` entries in the live registry (any None values are logged at DEBUG with entity_id).
- **Test:** Unit — `test_discover_populates_unique_id` uses a mock entity registry with a known unique_id, asserts `CircuitInfo.unique_id` is populated and `_get_power_baseline().scope == that unique_id`.
- **Test:** Unit — `test_discover_extras_no_registry_falls_back_to_entity_id` mocks a missing registry entry and asserts scope falls back to entity_id, not friendly_name.

### D2: EVSE `span_breaker` — surface as config field

Rationale: same rename-fragility class as circuit baselines. `energy_pool.py:169,176` hardcode `switch.span_panel_car_charger_breaker` and `switch.span_panel_garage_b_evse_breaker`; both go `unavailable` if the operator renames those breakers in the SPAN app. This is a one-symptom-class-two-fixes cycle; consolidating is cheap.

Choice: **config-flow field**, mirroring the v4.7.6 pattern (`CONF_ENERGY_EVSE_A_ENTITY` / `_B_ENTITY` at `energy_const.py:404-405`). Registry-unique_id lookup for switches is possible but two switches with operator-visible names are exactly the case options-flow was designed for; user already sees these two in the SPAN app when renaming.

Files: `energy_const.py`, `config_flow.py`, `__init__.py`, `energy_pool.py`.

Changes:
- Add `CONF_ENERGY_EVSE_A_SPAN_BREAKER`, `CONF_ENERGY_EVSE_B_SPAN_BREAKER` in `energy_const.py`.
- Add two `EntitySelector(domain="switch")` fields to the Energy section of the Coordinator-Manager options flow (co-located with `CONF_ENERGY_EVSE_A_ENTITY`).
- In `__init__.py:2409-2427`, merge overrides into `evse_config[..]["span_breaker"]` if the option is set; default remains the current hardcoded value for backward-compat.
- `energy_pool.py:163-178` `DEFAULT_EVSE_ENTITIES` remains as compat default — no behavioural change on upgrade.

#### Acceptance Criteria
- **Verify:** With options unset, `sensor.ura_energy_coordinator_evse_config` (via `energy_pool.get_status`) still shows the pre-cycle span_breaker values.
- **Verify:** After setting the two options to renamed switches, the same sensor reflects the new values within one options-flow reload.
- **Test:** `test_evse_config_override_span_breaker` sets both options, asserts `EVChargerController._evse["garage_a"]["span_breaker"]` equals override.
- **Live:** Operator-visible options-flow fields render with helper text pointing at the SPAN-app rename recovery path.

### D3: One-shot friendly-name → unique_id baseline migration

Files: `energy.py`.

Changes to `_restore_energy_baselines` (energy.py:4657-4785):
1. Before iterating rows, check for the migration marker sentinel:
   ```sql
   SELECT 1 FROM metric_baselines
   WHERE coordinator_id='energy' AND metric_name='_migration' AND scope='circuit_scope_v2'
   ```
   If present → migration already done; existing restore loop runs against unique_id scopes as-is (build a `unique_id -> entity_id` map instead of the current `friendly_name -> entity_id`). If absent → run the migration below, then INSERT the sentinel and continue.

2. Migration (only when sentinel absent, single boot):
   - Build both maps: `friendly_to_uid = {c.friendly_name: c.unique_id for c in ...}` and `uid_to_entity = {c.unique_id: eid for eid, c in ...}` (only entries with `unique_id != None`).
   - For each `metric_name='circuit_power'` row:
     - If `row.scope` matches a current `unique_id` (already-migrated shape from any prior partial run) → attach directly.
     - Else if `row.scope` matches a `friendly_name` and that circuit has a `unique_id` → **rewrite** the row: INSERT copy into `metric_baselines_pruned_backup` with a `migrated_at` marker (extend the existing backup table pattern; column `pruned_at` already exists — reuse it), then `INSERT OR REPLACE` a new row with `scope=unique_id`, `DELETE` the old friendly-scoped row.
     - Else if `"Unmapped Tab" in row.scope` → keep existing v4.7.32 auto-prune behaviour (already reversible).
     - Else → **do not delete**; leave the row in place, log at INFO with scope name. This covers the 3 known orphans (`'Battery Power'`, `'Span Left Subpanel Power'`, `'Span Left Unknown Power'`) — they carry no unique_id resolution, so manual on-host DELETE remains the exit ramp per research B3.
   - After the loop: INSERT the sentinel; log a single summary line:
     `"SPAN scope migration: %d migrated, %d already-v2, %d unmatched-left-in-place (%s), %d unmapped-pruned"`.

3. Idempotence: re-running the migration path after sentinel-insert is a no-op (SELECT sentinel → skip). Re-running because a bad build removed the sentinel is safe: every migrated row already has scope=unique_id, which will match the `if row.scope in uid_set` branch and be attached directly.

4. Reversibility: full pre-migration rows land in `metric_baselines_pruned_backup` before rewrite. Roll-back SQL is documented at the top of the method (extending the existing v4.7.32 comment block).

#### Acceptance Criteria
- **Verify:** Post-boot log carries exactly one line matching `SPAN scope migration:` with counts > 0 for `migrated` on the migration boot, and only-`already-v2` on subsequent boots.
- **Verify:** `metric_baselines_pruned_backup` has one row per pre-migration circuit_power scope with `pruned_at = <migration timestamp>`.
- **Test:** Behavioural — real DB schema from `database.py` (not hand-copied), pre-populate 3 rows: (a) `scope='Kitchen Outlets'` matching a mock circuit with unique_id `span_uid_kitchen`, (b) `scope='Battery Power'` matching no circuit, (c) `scope='Unmapped Tab 15 Power'` matching no circuit. Assert after `_restore_energy_baselines`: row (a) rewritten to `scope='span_uid_kitchen'` + backup exists + baseline attached to entity; row (b) untouched + INFO logged; row (c) deleted + backup exists (pre-existing v4.7.32 behaviour preserved).
- **Test:** Idempotence — call `_restore_energy_baselines` twice in the same test; sentinel-insert happens once; second call produces `already-v2` counts only.
- **Test:** Rename simulation — construct a circuit whose `unique_id='span_uid_office'` was previously persisted with `scope='Office'`; rename the mock registry entry to `entity_id=sensor.span_panel_home_office_power` + `friendly_name='Home Office'` (unique_id stable); assert the baseline restores under the NEW entity_id with the OLD `sample_count` intact.
- **Live:** After deploy + restart: (a) migration summary line present, (b) `circuits_monitored` unchanged from pre-deploy value, (c) `baselines_active` count ≥ pre-deploy value (no regressions), (d) no `"no matching circuit"` WARNs for any circuit resolvable via registry, (e) the 3 known orphans still produce their INFO line (not WARN), pending manual DELETE.

### D4: QUALITY_CONTEXT bug class candidate

Add to `docs/QUALITY_CONTEXT.md`:

> **Bug Class #NN — Display-name used as persistence key across renameable upstream.** A subsystem persists rows keyed by a user-editable display string (friendly_name, area name, etc.) that the upstream integration can re-sync at any time. On rename, existing rows orphan: the reverse-lookup misses, learned state (baselines, counters, prefs) is silently dropped. Prefer entity registry `unique_id` (or an equivalent upstream-stable identifier); keep display name for output only. Symptom class in URA: v4.7.32 SPAN prune (partial mitigation), and this cycle's full re-key.

---

## Blast radius (verified)

- Shared table `metric_baselines` also holds rows for `coordinator_id='safety'` (rate_of_change scopes) and `coordinator_id='<others>'` (diagnostics baselines). **Migration touches ONLY `coordinator_id='energy' AND metric_name='circuit_power'`** — all UPDATE/INSERT/DELETE statements carry both predicates (reuses the v4.7.32 pattern at `energy.py:4759,4765`). Other subsystems: byte-identical.
- `energy.py:4691-4702` — `peak_import_kw`, `soc_at_peak_start`, `daily_import_cost`, `solar_forecast_error_pct` restore paths do NOT go through the friendly-name reverse-lookup; they read `row["scope"]` verbatim into fixed baselines. Untouched.
- Sensor attrs: anomaly payload `"circuit"` field remains `friendly_name` (display) — user does not see a change.

---

## Tier 2-DB — three framings

**A — Data integrity + migration correctness.** Every pre-migration circuit_power row lands in `metric_baselines_pruned_backup` before rewrite. INSERT OR REPLACE on the new scope preserves `mean/variance/sample_count/last_updated` byte-identically. All UPDATE/INSERT/DELETE statements filter on both `coordinator_id='energy'` AND `metric_name='circuit_power'`. Non-circuit_power rows are byte-identical across the migration boot. Sentinel logic is idempotent; a repeated migration boot is a no-op.

**B — Rename-scenario end-to-end correctness.** Simulate the full SPAN rename lifecycle in tests (baseline warmed → registry entity renamed → HA restart → discover → restore) and confirm the baseline survives with `sample_count` intact and the anomaly path fires under the new friendly_name. Also cover: fallback when a circuit has no unique_id (extras path); a friendly_name that resolves to two candidates (choose deterministically — first match — and log a WARN); an "already-v2" row with a scope that no longer resolves (keep + log INFO, do NOT re-migrate).

**C — Test authority + shared-table safety.** Behavioural tests use the real `metric_baselines` schema extracted from `database.py:852-862`, not a hand-copied DDL. Tests exercise `_restore_energy_baselines` directly, not their own INSERT/UPDATE. Cross-subsystem test: pre-populate rows for `coordinator_id='safety'` and assert they are byte-identical after the migration boot (row count, mean, variance, sample_count).

---

## Risks

- **Registry not fully populated at discovery time.** SPAN entities register early but not guaranteed before `_restore_energy_baselines`. Mitigation: fallback chain (unique_id → entity_id → friendly_name); log at DEBUG so post-migration boots surface which circuits fell back. Follow-up cycle if fallback rate > 0 in production.
- **Two circuits with the same friendly_name.** Legal in HA. Migration picks first match; documented, tests cover. Zero known occurrences in operator's panel.
- **Manifest / marker schema conflict.** `metric_name='_migration'` is a reserved private prefix by convention; grep confirms no existing rows use it.
- **Extras entities (Emporia/Shelly) also get re-keyed.** Their registry unique_ids are stable too (per research B4 line 168-169), but the migration path never had reverse-lookup issues for these because their friendly_names don't drift. Included in the migration for consistency.

---

## Explicitly NOT in scope
- Auto-DELETE of the 3 known orphans (`'Battery Power'` etc.) — remains a manual on-host op per research B3. This cycle just makes them stop WARNing (they're logged INFO after migration classifies them as unmatched-left-in-place).
- Any change to non-`energy` scopes in `metric_baselines`.
- Naming-mode change on the SPAN integration.
- Migration of `metric_baselines_pruned_backup` schema — the existing 8-column shape (with `pruned_at`) is reused as-is.
