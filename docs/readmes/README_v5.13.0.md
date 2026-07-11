# URA v5.13.0 — SPAN circuit re-key: baselines survive SPAN-app renames (Tier 2-DB)

**Renaming a circuit in the SPAN app no longer wipes its learned anomaly baseline.** URA now keys `circuit_power` baselines on the entity's registry `unique_id` (stable across renames) instead of the friendly_name (mutable in the SPAN app). A one-shot migration re-keys the existing baseline history on first boot; learned sample counts are preserved. Also ships operator-facing EVSE breaker overrides in the config flow (defaults unchanged, so existing installs behave identically).

## What was broken

`energy_circuits.py:155-166` set `MetricBaseline.scope = friendly_name`. SPAN's HA integration re-syncs both the entity_id and the friendly_name when the operator renames a circuit in the SPAN app. On the next boot, `_restore_energy_baselines` looked up circuits by friendly_name (`energy.py:4707` pre-fix) and any renamed circuit missed → WARN "no matching circuit" + a warm baseline (weeks of learned data) permanently orphaned in `metric_baselines`. Three known orphan rows were living in the operator's DB from prior SPAN-app renames.

The scope was chosen at the v4.7.6 timeframe when SPAN entity semantics weren't fully verified; the rename-fragility was surfaced by `RESEARCH_span_architecture_2026-07-10.md` (sections A3 / B1 / B4).

## What ships

- **Scope re-key:** `MetricBaseline.scope` for SPAN `circuit_power` = registry `unique_id`, resolved once at discovery via `homeassistant.helpers.entity_registry.async_get_entity_id` → `RegistryEntry.unique_id`. `CircuitInfo.unique_id: str | None` added; friendly_name stays on the struct for display only (anomaly payloads, sensor attrs) — no user-visible regression.
- **Fallback:** if a discovered `sensor.span_panel_*_power` entity has NO registry entry (edge case: transient pre-registration during boot, or a non-SPAN "extra_entity"), fall back to `entity_id` as the scope. Logged at DEBUG. The restore path was made symmetric so `entity_id`-shaped scopes still re-attach.
- **One-shot migration** (`_migrate_scopes_to_unique_id`): first boot after upgrade walks existing `circuit_power` rows, resolves each old friendly_name scope to the current unique_id (or entity_id in fallback), rewrites the scope, and drops a sentinel row (`coordinator_id='energy', metric_name='_migration', scope='circuit_scope_v2', sample_count=1`) so the migration never re-runs. **Wrapped in `BEGIN IMMEDIATE ... COMMIT`** so a mid-loop crash leaves a full rollback rather than a partial re-key. Summary log line reports `migrated`, `deduped_into_existing`, `skipped_no_unique_id`, `already_unique_id`.
- **Reversible:** the migration writes into `metric_baselines_pruned_backup` before mutating (existing pattern from `energy.py:4745-4767`); if the operator ever needs to undo, the pre-migration snapshot is intact.
- **Known-orphan quieting:** three baseline rows with no matching current circuit (the operator's known pre-cycle rename fallout) demote their restore log line from WARN to INFO once the sentinel is present. Manual cleanup can happen later — no automation touches them.
- **Duplicate-friendly WARN:** if two circuits share a display name (rare but legal), a single WARN at migration time surfaces both unique_ids so the operator can decide.
- **EVSE breaker override fields** (`CONF_ENERGY_EVSE_A_SPAN_BREAKER`, `_B_SPAN_BREAKER`): new options-flow fields. Defaults preserve the existing hard-coded `switch.span_panel_car_charger_breaker` and `switch.span_panel_garage_b_evse_breaker` (`energy_pool.py:163-178`); operators who renamed their breakers can now correct without a code change. No behavioral change on default installs.
- **Untouched:** safety `rate_of_change` baselines, diagnostics per-coordinator baseline scopes, `peak_import_kw` / `soc_at_peak_start` / `daily_import_cost` / `solar_forecast_error_pct` — none of these key on friendly_name; all pass through the migration byte-identical. The predicate for that byte-identity is anchored in the test suite.

**Invariant.** A pre-warm `circuit_power` baseline re-attaches to its discovered `entity_id` after a SPAN-app rename between boots without relearning from 0 and without emitting "no matching circuit." All non-SPAN baseline rows are byte-identical across the migration boot.

## Review / gate (Tier 2-DB)

3 framing-disjoint reviews (A=data integrity + DB, B=migration + save/restore symmetry, C=new-surface + test authority) + focused re-review. Findings: 3 HIGH / 4 MED / 3 LOW, all fixed in `3de22a85`. Highlights the reviewers surfaced:
- **A-HIGH-1** the migration had no explicit transaction — a mid-loop crash could leave the DB in a partial-re-key state that a re-boot would corrupt. Now `BEGIN IMMEDIATE`.
- **B-HIGH-1** save/restore asymmetry — a unique_id-shaped scope whose entity failed registry resolution this boot (entity_id fallback engaged) would be permanently orphaned. Third lookup added.
- **C-HIGH-1** the unique_id predicate had ZERO real coverage — the cycle could have shipped as a silent no-op. Test rewritten to drive the real `homeassistant.helpers.entity_registry` API (cited: `entity_registry.py:1941` / `:891` / `:184` from the installed HA source; not fabricated).
- **C-HIGH-2** migration-completion predicate wasn't shape-anchored — schema drift would silently pass. Now shape-anchored + mutation red/green verified.

Re-review clean, no new defects. Review doc: `docs/reviews/code-review/v5.13.0_span_circuit_rekey.md`. Bug-class recommendations for `QUALITY_CONTEXT.md`: **display-name used as persistence key across a renameable upstream** and **hand-copied SQL in tests**.

---

## Pre-deploy snapshot (MANDATORY per Tier 2-DB)

Before deploying, capture:

```sql
SELECT coordinator_id,
       metric_name,
       COUNT(*)          AS row_count,
       SUM(sample_count) AS sample_total
FROM metric_baselines
GROUP BY coordinator_id, metric_name
ORDER BY coordinator_id, metric_name;

-- and specifically the SPAN scope surface pre-migration:
SELECT scope, sample_count, last_updated
FROM metric_baselines
WHERE coordinator_id = 'energy' AND metric_name = 'circuit_power'
ORDER BY scope;
```

These snapshots feed Live L3 + L5 comparisons below. Save both to `/tmp/ura_v5_13_0_pre_snapshot.txt` for post-deploy diff.

## Acceptance

```yaml
version: 5.13.0
hypotheses:
  - id: H1
    name: ura_v5130_deployed
    description: URA v5.13.0 is the running HACS-installed version and all entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.13.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: migration_completed
    description: Sentinel row present in metric_baselines after first boot.
    oracle: sqlite
    query: { kind: sqlite.row_exists, table: metric_baselines, where: "coordinator_id='energy' AND metric_name='_migration' AND scope='circuit_scope_v2'" }
    expected: { condition: "==", value: true }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H3
    name: no_matching_circuit_warn_gone
    description: Zero "no matching circuit" WARNs post-migration.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "no matching circuit", period: 24h }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

## Prospective Live Validation (to be filled in on `Validated <date>` post-restart)

| # | Criterion | Expected evidence |
|---|---|---|
| L1 | Migration summary log line | Capture the exact log line from the first post-deploy boot: `Migrated N circuit_power baselines from friendly_name to unique_id (deduped=X, skipped_no_unique_id=Y, already_unique_id=Z)`. Record N, X, Y, Z. |
| L2 | Zero unresolved-circuit WARNs | Grep 6h post-boot logs for `no matching circuit` → empty. Any residual matches must be the 3 known-orphan rows demoted to INFO, not WARN. |
| L3 | Baselines re-attached with sample_count intact | Post-boot `SELECT scope, sample_count FROM metric_baselines WHERE coordinator_id='energy' AND metric_name='circuit_power'`: scopes are now unique_id-shaped (e.g. `01JXXXXXXXXXX-power` or entity_id fallback for the edge case); `sample_count` values are **greater than or equal to** the pre-snapshot values for corresponding circuits (no reset to 0). |
| L4 | Sentinel row present | `SELECT * FROM metric_baselines WHERE coordinator_id='energy' AND metric_name='_migration' AND scope='circuit_scope_v2'` returns exactly one row, `sample_count=1`. |
| L5 | Non-SPAN baselines byte-identical | Diff pre-snapshot vs post-boot row_count + sample_total for `coordinator_id IN ('safety','presence','coordinator_diagnostics')` and for energy's non-`circuit_power` metrics (`peak_import_kw`, `soc_at_peak_start`, `daily_import_cost`, `solar_forecast_error_pct`) — expect **zero drift**. This is the predicate proof, live. |
| L6 | EVSE veto surface unchanged | Attributes on `sensor.ura_energy_coordinator_battery_strategy` show the same EVSE veto shape as pre-deploy on the default install (no breaker override set). If operator sets the new `CONF_ENERGY_EVSE_A_SPAN_BREAKER`, a subsequent options-save round-trips into the runtime activation gate. |

A cycle is not closed until this section is rewritten as a `Validated <date>` table with observed evidence per row, per project protocol.
