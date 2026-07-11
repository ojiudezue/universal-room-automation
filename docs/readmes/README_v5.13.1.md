# URA v5.13.1 — Hotfix: SPAN scope migration made resumable

**Tier 1 hotfix.** v5.13.0 shipped stable-`unique_id`-keyed SPAN baselines with a one-shot migration from the legacy friendly-name keys. Live validation caught a first-boot ordering race: the migration ran before the `span_panel` integration had populated `hass.states`, so only **2 of 41** friendly-keyed scopes rewrote — and the one-shot sentinel then blocked retry on subsequent boots. v5.13.1 makes the migration **resumable**: the sentinel is informational-only, and the per-row rewrite branches run every boot and are per-row idempotent.

## Root cause (verified in source)

`energy.py` migration ran under `async_added_to_hass` before `span_panel` scoped its own coordinator + state fan-out. `hass.states.get(...)` returned `None` for 39 of the 41 friendly-keyed scopes on first boot, so their rewrite branches skipped. The migration then wrote the sentinel unconditionally, marking the migration "done" — later boots (once `span_panel` states existed) saw the sentinel and short-circuited before the rewrite branches ran. Result: 39 scopes stranded on the old key shape indefinitely.

## The fix (build `2fa048eb`)

1. **Sentinel is now informational-only** — records "first migration pass observed" but does NOT gate the rewrite branches. Removing the gate is the actual fix.
2. **Per-row rewrite branches run every boot** — each branch is idempotent (checks the current row's key shape before rewriting), so scopes that migrated on boot 1 no-op on boot 2, and scopes that were pending on boot 1 rewrite on the boot where `span_panel` is finally up.
3. **Regression pin** encodes the exact live-boot scenario (`test_span_circuit_rekey.py`, 147 lines added): the mutation ("re-add sentinel gate") is verified RED against a specifically named test.

## Tier-1 review fixes (`5ca3c2d1`)

- **MED-1 (log verbosity):** orphan-scope log line was INFO on every boot after the sentinel existed — dropped to DEBUG once the sentinel is present (INFO still emits when actual progress is made, so operators can see resumption).
- **LOW-1 (write-volume discipline):** sentinel write was unconditional every boot. Now gated on **first-boot-or-progress** (either sentinel absent, or the current boot rewrote at least one row). Keeps the sentinel useful as a "did anything happen this boot" marker without polluting the DB write queue.

## Gate

No conflict markers; `py_compile` clean; 147-line regression suite + mutation-anchored pin GREEN; full suite at the documented 35-failed/14-error ordering-flake baseline — **zero new failures**. Deployed alongside v5.14.0 (labels + zone delete).

---

## Acceptance

```yaml
version: 5.13.1
hypotheses:
  - id: H1
    name: ura_v5131_deployed
    description: URA v5.13.1 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.13.1" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: span_scopes_fully_migrated
    description: All friendly-keyed SPAN scopes rewrite to stable unique_id keys after the boot where span_panel is up.
    oracle: db
    query: { kind: ura_sqlite.row_count, table: metric_baselines, where: "coordinator='energy' AND metric='circuit_power' AND scope LIKE 'sensor.%'" }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 30m, confirm_after: 6h, alert_if_violated_after: 24h }
  - id: H3
    name: no_error_storm
    description: No recurring URA errors after the resumable migration change.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

## Live Validation — PROSPECTIVE (post-restart)

| # | Criterion | Evidence source |
|---|---|---|
| L1 | Version installed = v5.13.1 | `update.universal_room_automation_update.installed_version` |
| L2 | Remaining ~39 friendly-keyed scopes migrate on first boot where `span_panel` states are up | `SELECT scope FROM metric_baselines WHERE coordinator='energy' AND metric='circuit_power' AND scope LIKE 'sensor.%'` returns 0 rows — cross-reference the v5.13.0 pre-deploy snapshot doc (`356040e7`) for the 43-scope pre-migration shape as the denominator |
| L3 | Sentinel present + informational-only | `metric_baselines` sentinel row present; rewrite branches log DEBUG on subsequent boots (no INFO orphan spam) |
| L4 | No error storm | `error_log` scan for `universal_room_automation` < 5 lines in 24h |
| L5 | Write-volume discipline | Sentinel write skipped on no-op boots (log-observable) |
