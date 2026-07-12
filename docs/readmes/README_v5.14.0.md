# URA v5.14.0 — Room-form label cleanup + Zone Delete (rides-along: v5.13.1 SPAN migration resumability)

Wave-2 release. Three cycles bundled into one deploy:

1. **DPM cleanup + room-form label pass** (Tier 2) — cleaner room configuration screens, ~30 friendlier labels, 4 shorter device-page names, fan-field selectors that finally accept switches, DPM form slimmed of vestigial bucket text.
2. **Zone Delete Flow** (Tier 2-DB, 3-review) — you can now remove a zone from the Zone Manager menu with a plain-language confirm, and every trace of it (entities, device, DB history) goes with it. Rooms assigned to a deleted zone keep working; they just become unassigned.
3. **v5.13.1 SPAN scope migration resumability** (Tier 1 hotfix, own README `README_v5.13.1.md`) — v5.13.0's SPAN circuit re-key stalled at 2/41 scopes on first boot because `span_panel` states weren't up yet; the sentinel then blocked retry. v5.13.1 makes the migration resumable so remaining scopes rewrite on the boot where SPAN is finally available.

Everything ships from `develop` (the v5.8.0 deploy-from-feature-branch mistake is not repeated).

## What operators will notice

### Room configuration screens (labels)

- **~30 friendlier labels** across the room config flow, reconfigure flow, and paired data-descriptions. No more nerd-language: unit suffixes are consistent ("(°F)", "(min)"), acronyms are spelled out where they mattered, and the plain-English wording matches how the operator actually thinks about each field.
- **4 shorter device-page names** (`number.py` entity display names on the URA HVAC / Energy coordinator device pages):
  - `47 · Entry Wait (min)` (was: "47 · Zone Entry Wait Time (minutes)")
  - `66 · Fan Off Margin (°F)` (was: "66 · Fan Off Temperature Margin")
  - `03 · Settle Time (min)` (was: "03 · Dynamic Preset Settle Time (minutes)")
  - `04 · Preset Margin (°F)` (was: the longer variant)
- **Fan fields now accept switches.** `Comfort Fans` and `Humidity Fans` selectors in the room config + options steps were quietly filtering to `domain=fan` even though the labels said "(or Switches)". Widened to `domain=[fan, switch]` at 4 sites. Runtime was already switch-safe (`automation.py:1665,1730` since v3.2.8.2), so this is a UI-only fix that unblocks operators who wanted to use a smart switch as a room fan.
- **DPM form slimmed** — the 17 vestigial DPM bucket-cell text fields (already stripped from the *rendered* schema in v4.7.18 D1) had 33 leftover string surfaces + 21 imports + a MIRROR set entry still riding along. All cleaned up end-to-end. **Note:** the legacy bucket-cell auto-mirror across sibling zones (from v4.7.5 D4) is officially retired — it was vestigial the entire time (the fields writing into the mirror had already been removed).

### Zone Manager: "Remove this zone"

- New **"Remove this zone"** option in the Zone Manager menu (8th entry, placed last and visually separated).
- Confirm screen is plain-English (no config-key jargon):
  - Tells you exactly how many sensors/controls will be deleted
  - Tells you exactly how many rooms will become unassigned
  - Tells you exactly how many DB rows will be purged (across six tables)
  - Tells you the thermostat setting is NOT touched (if the zone shares a thermostat with another zone, the other zone keeps working)
  - Requires typing the **exact zone name** to confirm (case-insensitive, trimmed) — protects against fat-fingering the wrong menu entry
- On submit:
  - All zone entities delete from the entity registry (13 zone-name-keyed + HVAC family keyed off zone_id)
  - Zone device deletes from the device registry
  - DB rows purged from **six** zone-scoped tables in one atomic BEGIN transaction (`zone_events`, `ac_reset_state`, `egress_state`, `ac_ramp_events`, `census_snapshots`, `ura_activity_log`)
  - Rooms that referenced this zone drop `CONF_ZONE` in-place and keep working (they become unassigned; you can move them to another zone later)
  - HVAC and presence coordinators prune the zone immediately via `SIGNAL_ZM_ZONES_UPDATED` (no waiting for the periodic rebuild)
  - **Exactly one reload** of the Zone Manager entry (no reload storm across the 40 Room entries)
  - `fan_recheck_state` is **not** touched — it's per-ROOM, and deleting a zone must not corrupt surviving rooms' fan state

## What this doesn't change

- **Nothing in the runtime automation loop.** Room presence, HVAC decisions, DPM classification, energy strategy — all untouched.
- **CONF constants for DPM bucket cells remain in `energy_const.py`** for options-dict backward-compat restore. Only the UI/mirror/import surface is cleaned up.
- **`classify_bucket()` still classifies buckets** — its thresholds have always come from DPM's own knobs, not the per-zone cells.

## Review gate (summary — full detail in review doc)

- **Section A (labels + DPM cleanup):** Tier 2, two framing-disjoint reviews (correctness + translation-surface). Both **SHIP** with 2 LOWs fixed in-cycle (stale docstring `bc320148`; retired auto-mirror documented).
- **Section B (zone delete):** Tier 2-DB, three framing-disjoint reviews (A data-integrity, B migration-correctness + signal-chain, C test-authority-via-real-mutation) + focused re-review (D). Post-build, the stack caught **6 CRITICAL + 6 HIGH + 5 test-authority failures** — all fixed in `1a2cd3a5`. Re-review D found **P1 (HIGH): signal handler mutating zones dict while other coroutines iterate across awaits** — reviewer listed 4 iteration sites; builder re-grep found **4 more** for 8 total. All snapshotted in `4fd243f6`. All five Review-C mutations re-verified RED against the real source. **Static-vs-behavioral anchor judgments recorded** in the review doc. **Plan deviation upheld:** `fan_recheck_state` correctly excluded from the purge (per-room PK — including it would have corrupted surviving rooms).
- **v5.13.1 (SPAN resumability):** Tier 1; MED-1 (log verbosity) + LOW-1 (write-volume) fixed in `5ca3c2d1`.
- Review doc: `docs/reviews/code-review/v5.14.0_labels_and_zone_delete.md`.
- **Wave-2 tally:** across the four wave cycles the framing-disjoint stack caught **9+ CRIT / 16+ HIGH post-build**. No single framing would have caught them all.

**Three new candidate bug classes** filed for `QUALITY_CONTEXT.md`:
1. **Reads without writers** — options/data key still read via `or`-fallback after the last writer is removed (A-HIGH-1 recurrence of #14 across `data` vs `options`).
2. **Hand-copied SQL/logic in tests** — a test file that mirrors DAO logic in-test rather than importing + driving it certifies nothing (Review-C's initial pass; sibling of v5.9.0 "stub-mirror").
3. **Signal handler mutating a dict others iterate across awaits** — delete cycles that add signal-driven mutation to a shared coordinator dict must audit all iteration sites of that dict for `await`-crossing loops (P1).

---

## Acceptance

```yaml
version: 5.14.0
hypotheses:
  - id: H1
    name: ura_v5140_deployed
    description: URA v5.14.0 is the running HACS-installed version and all URA entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.14.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: zone_delete_removes_all_traces
    description: Deleting the husk zone "Entertainment + Master Suite" removes every entity, device, and DB row keyed by it — and no zone resurrects after a follow-up restart.
    oracle: composite
    query: { kind: composite, checks: [entity_registry_search, device_registry_search, db_row_count_six_tables, config_entry_options_zones] }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 15m, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H3
    name: no_error_storm
    description: No recurring URA errors after the wave-2 deploy.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H4
    name: fan_selector_accepts_switches
    description: The Comfort Fans / Humidity Fans selectors show switch entities in the picker.
    oracle: operator_spotcheck
    query: { kind: config_flow.selector_domains, step: room_options, field: fans }
    expected: { condition: "contains", value: "switch" }
    window: { first_check_after: 15m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H5
    name: exactly_one_zm_reload
    description: A zone delete triggers exactly one reload of the Zone Manager entry — no reload storm across Room entries.
    oracle: home_assistant
    query: { kind: home_assistant.log_scan, pattern: "async_reload.*zone_manager", period: 5m_after_delete }
    expected: { condition: "==", value: 1 }
    window: { first_check_after: post_delete, confirm_after: post_delete, alert_if_violated_after: post_delete }
```

## Live Validation — Validated 2026-07-11 (post-restart)

Wave-2 shipped stable. SPAN migration outcome recorded honestly here — it did not complete on the v5.14.0 boot alone; it completed on the v5.14.1 hotfix boot (see `README_v5.14.1.md`). LOW-2 in the review — the legacy DPM bucket auto-mirror from v4.7.5 D4 — was documented user-visible retirement (it was vestigial the entire time; noted for the record).

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy + zero errors | **PASS** | `installed_version = v5.14.0` at deploy tip; zero URA errors across both wave-2 restarts. |
| L2 | **SPAN migration completes** — remaining friendly-keyed scopes rewrite to unique-id keys | **PASS (via v5.14.1)** | Post-v5.14.1 boot shows 34 `circuit_power` rows with `span_nj-*` unique-id-scoped values, sample counts intact (e.g. 12,743 vs pre-deploy 12,742), 36 backup rows written today, 3 known-orphan rows correctly left in place. v5.14.0 alone did NOT complete the migration (stale discovery cache — see `README_v5.14.1.md`). |
| L3 | **Zone delete works end-to-end on the husk zone `Entertainment + Master Suite`** — every entity/device/DB-row keyed by it goes with it; no zone resurrection after a follow-up restart | **PENDING-OPERATOR** | Typed-confirm UI flow is operator-driven. Verification checklist armed (MCP `ura-sqlite` row counts across the six purged tables + `ha-mcp` entity/device registry queries + `home-assistant` config-entry inspection, pre-delete and post-restart, with Bug Class #14 regression pin: both `entry.data` and `entry.options` clear). |
| L4 | **Exactly ONE reload during delete** — no reload storm across 40 Room entries | **PENDING (verifiable during husk delete)** | HA log tail in the 5 minutes after operator's delete; pattern `async_reload.*zone_manager` should match exactly once. |
| L5 | **3 renamed labels render correctly** in a room Configure screen | **PASS (file-level, 2026-07-12)** / UI render still operator | Appendix-A samples (`occupancy_sensors` → "Combined Motion + Presence Sensors", `dynamic_preset_dwell_minutes` → "Settle Time (minutes)", `dynamic_preset_hysteresis_f` → "Temperature Margin (°F)", `hvac_zone_entry_dwell` → "Zone Entry Wait Time") all present in `strings.json` + `translations/en.json` at the deployed version (installed v5.14.1 == repo tip). Read-only MCP cannot render config-flow forms, so the visual check remains with the operator. **Documented drift:** Appendix-A rows for `scanner_areas` and `is_egress_window` shipped as *kept-label-with-gloss* (plain-English wording landed in `data_description`, labels remain "BLE Scanner Areas (Optional)" / "Treat as egress window") — egress variant was an UPHELD review deviation (B-imm-1); `scanner_areas` row over-claims the rewrite. Not a regression. |
| L6 | **4 short device-page entity names** (`47 · Entry Wait (min)`, `66 · Fan Off Margin (°F)`, `03 · Settle Time (min)`, `04 · Preset Margin (°F)`) | **PASS (live, 2026-07-12)** | All 4 verified via live entity reads: `number.ura_hvac_coordinator_zone_entry_dwell`, `..._fan_off_hysteresis`, `number.ura_energy_coordinator_dynamic_preset_dwell_minutes`, `..._dynamic_preset_hysteresis` friendly names match the short forms exactly. |
| L7 | **Fan field accepts switch entities** in Comfort Fans / Humidity Fans pickers | **PENDING-SPOT-CHECK** | Operator opens room options; verify a `switch.*` entity appears in the picker and saves cleanly. (Not verifiable via read-only MCP — selector rendering is UI-side.) |

Cross-references: `README_v5.13.1.md` (SPAN resumability), `README_v5.14.1.md` (SPAN migration completion via post-STARTED re-pass with forced rediscovery).

**Addendum 2026-07-12:** the 3 known-orphan `metric_baselines` rows (`Span Left Unknown Power` 280, `Battery Power` 6, `Span Left Subpanel Power` 582 — README_v5.14.1 L7) were manually DELETEd on-host via SSH+sudo sqlite3 (75→72 rows; backup INSERTs at repo `data/orphan_rows_backup_2026-07-12.sql`; live `span_nj-*` rows verified still accruing post-delete). v5.12.0 poll-gap canary re-scan same day: 0 hits across the v5.14.1 boot + ~19h steady state — no room is poll-bound.
