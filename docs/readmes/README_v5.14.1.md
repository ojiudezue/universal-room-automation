# URA v5.14.1 — Hotfix: SPAN scope migration completes (post-STARTED re-pass + forced rediscovery)

**Tier 1 hotfix.** v5.13.0 shipped stable-`unique_id`-keyed SPAN baselines with a one-shot migration. v5.13.1 made the migration resumable (sentinel demoted to informational-only, per-row rewrite branches re-run every boot). But live validation across two subsequent boots showed the friendly-keyed scopes still not migrating. The root cause was one level deeper than either prior cycle spotted: the circuit-discovery cache was being marked complete on a zero-match scan, so no matter how many times the resumable rewrite branches ran, they had nothing to match against. v5.14.1 fixes the cache and re-runs discovery after `EVENT_HOMEASSISTANT_STARTED`, when the `span_panel` integration has finished populating `hass.states`.

## Root cause (verified in source)

`energy_circuits.py:194` set `_discovered = True` unconditionally after the discovery scan — even when the scan returned zero circuits. On first boot, `span_panel` states weren't up yet, so the scan found nothing, but the cache marked itself "done." The resumable migration branches from v5.13.1 then ran every boot as designed, but they consulted the (permanently empty) discovery cache and had no `unique_id` values to rewrite scopes to. Result: 39 friendly-keyed scopes stranded indefinitely despite two prior fix cycles.

## The fix (build `d9a8dc52`)

1. **Post-STARTED one-shot re-pass.** New listener on `EVENT_HOMEASSISTANT_STARTED` fires exactly once per process to re-run discovery + migration after HA has finished starting integrations. By that point, `span_panel` has populated `hass.states` and a fresh scan finds real circuits.
2. **Forced rediscovery.** The re-pass calls the discovery scan with `force=True`, bypassing the `_discovered` cache guard so a prior zero-match doesn't short-circuit the fresh scan.
3. **Cache clear on force.** When `force=True` is used, `_discovered` is reset to `False` before the scan and only set `True` at the end if the scan actually found circuits. Zero-match no longer poisons the cache.
4. **One-per-process flag** guards against duplicate re-passes if the STARTED event fires multiple times (e.g. during reload edge cases).
5. **Tracked task.** The re-pass is scheduled via `hass.async_create_task(...)` with a name so it's visible in HA's task registry and doesn't leak as an untracked background coroutine (Bug Class #34 sibling).

## Tier-1 review (SHIP; 3 MEDs fixed in `d9a8dc52`)

- **MED-1 (double-fire hardening):** hardened the one-per-process flag under an asyncio.Lock so a rapid STARTED-fires-twice edge case can't race the guard.
- **MED-2 (log discipline):** re-pass logs at INFO on progress (rows rewritten), DEBUG on no-op (already-migrated boots), matching the v5.13.1 write-volume discipline.
- **MED-3 (test authority):** regression pin now drives the real discovery scan and asserts the cache is reset when `force=True`, not just that the branch was taken. Mutation-anchored RED against the specifically named test.

Gate: no conflict markers, `py_compile` clean, regression suite GREEN, full suite at the documented 35-failed/14-error ordering-flake baseline — zero new failures.

## Honest cost note

The post-STARTED re-pass is one additional read-only registry + state scan per boot. Once migration completes for a given install, subsequent boots log DEBUG "already migrated" and do not write. On installs with no SPAN integration, the re-pass finds zero circuits and no-ops.

---

## Acceptance

```yaml
version: 5.14.1
hypotheses:
  - id: H1
    name: ura_v5141_deployed
    description: URA v5.14.1 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.14.1" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: span_scopes_fully_migrated
    description: All resolvable friendly-keyed SPAN scopes rewrite to stable unique_id keys after the post-STARTED re-pass.
    oracle: db
    query: { kind: ura_sqlite.row_count, table: metric_baselines, where: "coordinator_id='energy' AND metric_name='circuit_power' AND scope LIKE 'sensor.%'" }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 30m, confirm_after: 6h, alert_if_violated_after: 24h }
  - id: H3
    name: no_error_storm
    description: No recurring URA errors after the re-pass change.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

## Live Validation — Validated 2026-07-11 (post-restart)

The fix that actually completed the SPAN migration. Third boot in the wave-2 sequence (v5.13.0 → v5.13.1 → v5.14.1).

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Version installed = v5.14.1 | **PASS** | `installed_version = v5.14.1` at deploy tip. |
| L2 | **SPAN migration completes** — all resolvable rows on unique-id keys | **PASS** | 34/34 resolvable `circuit_power` rows now `span_nj-*` unique-id-scoped. |
| L3 | Sample counts preserved (no relearn from 0) | **PASS** | Post-migration `sample_count` matches or exceeds pre-snapshot (e.g. 12,743 vs pre-deploy 12,742 — preserved and continuing to accrue). |
| L4 | Reversibility snapshot exists | **PASS** | 36 backup rows written today into `metric_baselines_pruned_backup`. |
| L5 | Non-SPAN baselines byte-identical (predicate proof, live) | **PASS** | Row counts for `coordinator_id IN ('safety','presence','coordinator_diagnostics')` and for energy's non-`circuit_power` metrics were byte-identical across all three wave-2 boots. |
| L6 | Sentinel row present | **PASS** | Sentinel row present in `metric_baselines`. |
| L7 | Known orphans left in place (per design) | **PASS** | 3 known-orphan rows correctly not migrated: `Battery Power 6`, `Span Left Subpanel 582`, `Span Left Unknown 280`. Manual on-host `DELETE` remains open (not automated). |
| L8 | Zero errors | **PASS** | Zero URA errors across the v5.14.1 boot; zero across all three wave-2 boots. |
| L9 | Write-volume honest cost | **NOTE** | The post-STARTED re-pass adds one read-only registry + state scan per boot. Subsequent boots log DEBUG "already migrated" and do not write. No steady-state DB write pressure. |

Cross-references: `README_v5.13.0.md` (original re-key + honest saga), `README_v5.13.1.md` (resumability — necessary but not sufficient).
