# PLANNING — EC house-entity defaults → role-worded CONFs + brand-neutral core (Build A / Card B / Phase 2)

- **Card:** EC-HOUSE-ENTITY-DEFAULTS-1 (`docs/planning/kanban.data.yaml`)
- **Thread:** energy
- **Revision:** **Rev 5** (2026-10-13). Rev 4 sized at ~2–3k LoC across ~20 production + ~20 test files; operator flagged it as too much ceremony for the three real goals. Rev 5 applies the Marginal-Benefit Decomposition rule from CLAUDE.md and strips Rev 4 to the smallest build that still satisfies G1/G2/G3. **Rev 5 OVERRIDES Rev 4 wherever they conflict; Rev 4 and earlier content is preserved below for history.**
- **Tier:** **Build A ships Tier 2** (two framing-disjoint reviews, not Tier 2-DB). The DB-sensitive triggers that justified Tier 2-DB in Rev 4 (payload-shape changes, migrating ≥3 callers to a new DAO) are gone because Rev 5 does not rename CONF keys and does not change any payload.

---

## Rev 5 — simplified

### Goals (from operator)

- **G1** No house-specific entity IDs as code defaults. A second home must not silently target dead entities on this house's hardware.
- **G2** Vendor-neutral, role-worded fields that accept any appropriate sensor.
- **G3** This house (Phalanx) behaves the same after the change.

### Hypothesis verdicts (greps, not trust)

| H | Claim | Grep / check | Verdict |
|---|---|---|---|
| H1 | The 12 internal CONF-key renames add near-zero USER value; G2 is met by labels + translations + selectors. | Users never see the raw string `energy_solcast_today_entity`. The UI label and the entity selector are what they see. `strings.json` / `translations/en.json` are the user surface. | **CONFIRMED.** Drop the rename entirely. G2 is a UI-label problem, not a Python-identifier problem. |
| H2a | G1 is met by (i) copying today's resolved defaults into THIS house's options at setup, then (ii) deleting the default literals. | Live options blob at `.storage/core.config_entries` entry `01KJEC3FYPYAGBQKZWC94CR8GR` — grepped the 12 brand-named option keys. **10 of 12 are already set** on Phalanx with the right entity_ids (`energy_solcast_today_entity`, `energy_cloud_reserve_oracle_entity`, `energy_envoy_entity`, etc.). The 2 that are NOT in the live options are `energy_evse_a_span_breaker` and `energy_evse_b_span_breaker` plus Rev 2's new `energy_dp_span_r[12]_entity` — those currently fall through to module defaults. | **CONFIRMED.** For 10 of 12 keys the default literal is dead code on this house (never read). For the 2–4 keys that ARE live-reached, a 20-line one-shot "copy today's resolved value into options, then None out the default" migration is sufficient. No per-site abstain machinery needed. |
| H2b | A single setup-time repair issue listing configured-but-missing entities is enough to prevent "silently does nothing"; no new entity-health sensor, no 4-state machine, no grace ticks. | HA's `ir.async_create_issue` already surfaces operator-actionable gaps on the Repairs dashboard. The current Rev 4 "ec_entity_health" state machine + grace-ticks knob is ceremony for a problem a single issue card solves. | **CONFIRMED.** One repair issue per CM entry, listing `{key, configured_entity_id, reason}` for anything in the role-key set that is set-but-not-in-registry OR set-but-unavailable-for-N-ticks. One function, one test. |
| H3 | Of the 36 defaults, how many are actually consumed on live paths? | Live Phalanx options already set: all 4 Solcast forecast entities, all 4 cloud-oracle entities, Envoy anchor, generator, both EVSE power entities, L1 chargers, weather + 2 fallbacks, grid import/export, utility meter, solar-follow + fallback, both SPAN mains sources. **Not set on live options:** EVSE A/B SPAN breakers, DP SPAN R1/R2, Enpower storage-mode / reserve-SOC / grid-enabled / charge-from-grid (rows 18–21 Rev 2), Generac serial (row 22 Rev 2), Pentair rows (23–27). Those are the ones whose defaults ARE live-reached. | **CONFIRMED.** The migration copy is a no-op for the 10 already-set keys. The one-shot migration only has to do real work for ~8–13 keys whose defaults are currently reached. |
| H4 | Do existing selectors already domain-filter correctly? | `config_flow.py:6508-6532` — Solcast fields are `EntitySelectorConfig(domain="sensor")`; EVSE power fields are `domain="sensor", device_class="power"`. Spot-checked 4 selectors; all are already domain-filtered. | **MOSTLY CONFIRMED.** Selectors are already role-shaped for the fields a 2nd install would configure. Any tightening is 1-line per field, not a rewrite. **No selector sweep required**; builder may tighten only the live-attribute-table rows where the domain filter is wider than it needs to be. |

### Rev 5 — minimal build

**One cycle. Tier 2 (two framing-disjoint reviews). ~400 LoC across 4 production files + 2 translation files + 2 test files.**

#### D-5.1 — Delete house-specific default literals (G1)

- `custom_components/universal_room_automation/domain_coordinators/energy_const.py`:
  - Convert `DEFAULT_SOLCAST_*` (5), `DEFAULT_CLOUD_*` (4), `DEFAULT_WEATHER_ENTITY`, `DEFAULT_EVSE_GARAGE_A/B_POWER_ENTITY` (2), `DEFAULT_L1_CHARGER_ENTITIES` (list of 4), `DEFAULT_STORAGE_MODE_ENTITY` / `DEFAULT_RESERVE_SOC_ENTITY` / `DEFAULT_GRID_ENABLED_ENTITY` / `DEFAULT_CHARGE_FROM_GRID_ENTITY`, `DEFAULT_CLOUD_LAST_SUCCESS_ENTITY`, `DEFAULT_SOLCAST_DAY_3_ENTITY`, and the Generac / Pentair literals in `energy_circuits.py` / `energy_pool.py` from house-specific strings to `None` (or `[]` for list types).
  - Keep the constant NAMES (so no caller breaks). Only the VALUE changes to `None` / `[]`.
  - Keep `DEFAULT_TOU_RATE_FILE`, `DEFAULT_WEATHER_STALENESS_MAX_HOURS`, and other non-entity-id defaults untouched.
- Callers that currently read `options.get(key, DEFAULT_X)` still work — they get `None` on an unconfigured 2nd install and the existing `if not entity: return` / abstain paths kick in (verified by grep: every one of the 10 already-set defaults is behind an `if ... is None` or `hass.states.get(...) is None` guard in `energy.py` / `energy_battery.py` / `energy_forecast.py` / `energy_pool.py` / `energy_write_verify.py`).
- **~60 LoC changed across 5 files.** Pure value edits.

#### D-5.2 — One-shot "pin today's resolved values into options" migration (G3 safety)

- `__init__.py` setup gains `_bootstrap_pin_ec_defaults_once(hass, cm_entry)`:
  1. For each role-key in a small Python list (the ~13 keys whose defaults were house-specific), if the key is **absent** from `data | options` AND the old default entity IS in the entity registry, write that entity_id into options via one atomic `async_update_entry`.
  2. Set `_ec_defaults_pinned=True` + `_ec_defaults_pinned_version` + `_ec_defaults_pinned_at`.
  3. Add the pinned keys + the flag to `OPTIONS_RELOAD_SUPPRESS_KEYS` for the atomic write (Rev 2 R6).
- On Phalanx: the migration is a no-op for 10 of 13 keys (already set) and pins the 3-ish SPAN-breaker / DP-R1R2 keys from their current defaults. **G3 preserved** by direct byte-identity: post-migration `options[k]` equals pre-migration `(options.get(k) or DEFAULT_X)` for every k.
- On a 2nd install: the SPAN-breaker / DP-R1R2 entities aren't in that house's registry → migration doesn't pin anything → fields show empty in options flow → operator picks real entities. **G1 satisfied.**
- **~80 LoC in `__init__.py` + the role-key list in `energy_const.py`.**

#### D-5.3 — Relabel the UI, not the Python identifiers (G2)

- `strings.json` + `translations/en.json`: rewrite the ~15–20 labels + descriptions for the role-keys to brand-neutral role words per `feedback_label_style_guide`. Examples:
  - "Solcast forecast — today" → "Solar forecast today"
  - "Enpower storage mode" → "Battery mode"
  - "SPAN panel breaker switch for Garage A" → "Garage A charger breaker switch"
  - "Envoy entity" → "Solar gateway sensor" (role-neutral; the anchor is still Enphase under the hood — Phase 2 territory, not Build A)
- CONF key STRING VALUES (`"energy_solcast_today_entity"` etc.) stay unchanged. No `OPTIONS_RELOAD_SUPPRESS_KEYS` edits for renames. No 10-test-file migration. No deprecation aliases. No raw-string edits in `test_span_circuit_rekey.py` / `test_baec_config_flow_round_trip.py`.
- Translation key renames (if any) use a one-release alias in `translations/en.json` — no code impact.
- **~160 LoC of pure string edits across 2 files.** Zero production-code impact.

#### D-5.4 — Setup-time repair issue for configured-but-missing entities (replaces entity-health sensor + 4-state machine + grace ticks)

- `_scan_ec_role_entities(hass, cm_entry)` runs once at setup and once per hour (reusing an existing periodic hook — no new timer):
  - For each role-key in the role-key list, read `options[key]`; if non-None, check `er.async_get(hass).async_get(entity_id)` for registry presence AND `hass.states.get(entity_id)` for `unavailable` state.
  - Build a payload `[{"key": "...", "entity_id": "...", "problem": "not_in_registry" | "unavailable"}]`.
  - Call `ir.async_create_issue(..., issue_id=f"ec_role_entity_{key}", severity=WARNING, translation_key="ec_role_entity_broken", translation_placeholders={...})` for each problem; `ir.async_delete_issue` for keys that recovered.
- **No new sensor, no number-knob, no state machine, no grace-ticks debounce.** The hourly periodic re-scan IS the discharge. `unavailable` for a single tick fires the issue; if it recovers next tick the issue is deleted. Noise is acceptable because this is a Repairs card, not an NM blast.
- **~90 LoC in `energy.py` or a small new helper + the translation strings.**

#### D-5.5 — Tests

- `test_default_literals_contain_no_house_entity_ids` — greps `energy_const.py` + `energy_pool.py` + `energy_circuits.py` for the brand/host tokens `(envoy|enphase|enpower|solcast|iq_battery|iq_gateway|span_panel|garage_[ab]_power|generac|pentair|smartplug_moes)` inside `DEFAULT_*` literal string values. Returns 0. Allowlisted: `DEFAULT_TOU_RATE_FILE`.
- `test_bootstrap_pins_phalanx_shape_options_byte_identical` — load a committed `phalanx_options_pre_migration.json` fixture, run `_bootstrap_pin_ec_defaults_once` on a copy, assert that for every role-key `(options.get(k) or OLD_DEFAULT) == options_post[k]`. Zero-change proof for G3.
- `test_bootstrap_pins_registered_but_unavailable` (preserved from Rev 2 R3) — registry-based pin, not live-state pin.
- `test_bootstrap_skips_absent_from_registry` (preserved) — 2nd install: no pin, option field stays absent, 2nd-install operator sees empty field.
- `test_repair_issue_fires_on_configured_missing_entity` — set `options[key]` to `sensor.does_not_exist`; run scanner; assert `ir.async_create_issue` called with `issue_id=ec_role_entity_<key>`.
- `test_repair_issue_cleared_on_recovery` — flip to a valid registered entity; re-run; assert `ir.async_delete_issue`.
- **~2 test files, ~200 LoC total.** No fixture extraction from DDL (not a DB cycle).

### What was cut (every cut mapped to the goal it still satisfies)

| Cut | What it was | Why cut | Goal still satisfied? | Parking + revisit trigger |
|---|---|---|---|---|
| **The 12 CONF-key renames** | Rev 4 D-RENAME-A1 (new role-named constants + deprecation aliases) | H1: internal identifiers invisible to users; G2 is the UI label, not the Python identifier. | **G2:** yes — met entirely by D-5.3 label rewrite. **G1:** yes — met by D-5.1 default deletion. **G3:** yes — keys unchanged on disk, no migration risk. | Park. Revisit trigger: a 2nd-release polish cycle that proves the key names leak somewhere user-visible (API dump, debug export, downloadable diagnostics). Carded as `EC-ROLE-KEY-RENAME-FUTURE` with trigger wording "evidence the raw CONF key is seen by anyone outside the integration code." |
| **Deprecation-alias constants + `test_no_old_key_read_in_production`** | Rev 4 R4-5 allowlist | Flows from the cut above. | **G1/G2/G3:** unaffected. | Dies with the rename. |
| **10-test-file migration + 3 raw-string file edits** | Rev 4 §"Test migration — real file list" | Flows from the cut above. | **G1/G2/G3:** unaffected. | Dies with the rename. |
| **`OPTIONS_RELOAD_SUPPRESS_KEYS` edits for 12 new keys + atomic-write-vs-suppress-list dual-path test** | Rev 4 §"Reload safety for new keys" | No new keys ⇒ no reload hazard from renames. D-5.2's single-key pin flag already uses the one-key atomic write path that's been in production since Rev 2 R6. | **G3:** yes — the one-key atomic write preserves reload-silence. | Dies with the rename. |
| **`entity_registry.async_migrate_entries`** | Already dropped in Rev 4 R4-1 | Confirmed cut. | — | — |
| **Rev 4 D-RENAME-A6 UI-surface literal grep + Python-based allowlist test** | Rev 4 §"Acceptance greps" | The brand-token grep stays (D-5.5 test 1), scoped to `DEFAULT_*` literal string values, not the entire UI. UI brand audit becomes a reviewer-eye grep during Review B, not a committed Python test. | **G2:** yes — the 2 translation files are small enough for a reviewer to eyeball; a committed grep over `strings.json` is deferred until the surface grows. | Park. Revisit trigger: a translation-brand-leak regression on any ship. |
| **`_build_entity_map` + `test_entity_map_equality_pre_post_migration` (Rev 4 R4-5)** | Rev 4 proof of byte-identity through a pure function | Replaced by D-5.5 `test_bootstrap_pins_phalanx_shape_options_byte_identical`, which does the same proof against the live fixture via `(options.get(k) or OLD_DEFAULT) == options_post[k]`. One less helper. | **G3:** yes — stronger because it checks the actual migration path, not a parallel helper. | Dies with the rename. |
| **`ec_entity_health_unavailable_grace_ticks` number knob + 4-state machine + fired/ok latch** | Rev 2 D4 TRUST-tier machinery (dead_default / not_configured / unavailable / ok) | H2b: a repair issue solves the same user-visible problem — "something you configured points at an entity that isn't there." The 4-state machine was Rev 1's answer when the plan was going to abstain on `unavailable`; Rev 2 R4 downgraded `unavailable` to report-only; D-5.4 completes that reduction. | **G1:** yes — a 2nd install sees empty fields + a repair issue naming anything configured-but-dead. **G3:** yes — Phalanx: no change to actuation. | Park. Revisit trigger: the repair-issue approach proves insufficient (operator ignores the dashboard; measurable incident caused by configured-but-dead entity that a 4-state machine would have caught). |
| **Full Tier 2-DB protocol (3 framing-disjoint reviews + pre-deploy snapshot by `(coordinator, severity, type)` + Review D live-validation sentinel)** | Rev 4 §"Tier + review framings" | Tier 2-DB triggers (payload shape change, ≥3 DAOs migrated, new behavioral test infra against real schemas) do not fire in Rev 5. No CONF rename, no payload shape change, no DAO migration. The remaining risk shape is "one house's bootstrap misbehaves" — Tier 2's two framings cover it. | **G3:** yes — Review B framing (migration correctness + reload silence) covers the one real risk axis (pinning writes trigger CM reload). | Not parked — downgraded. If live validation shows surprise reload churn, elevate the NEXT cycle. |
| **Phase 2 Enphase-adapter work (Envoy anchor CONF move, validator, boot gate, serial parser)** | Rev 4 §"Phase 2" | Already deferred in Rev 4 as a separate phase. Rev 5 does not reopen it; Build A simply does not touch `CONF_ENERGY_ENVOY_ENTITY` or its validator. | **G1/G2/G3:** unaffected — the anchor's label gets a brand-neutral text in D-5.3 ("Solar gateway sensor") so a 2nd operator sees role words even though the underlying anchor is still Enphase-specific; that's acceptable until the 2nd install actually arrives on non-Enphase hardware, which triggers Phase 2. | Phase 2 remains carded, trigger = "2nd install on non-Enphase gear reaches hands-on config stage." |
| **Card B (two URA entity-ID renames)** | Rev 4 R4-1 | Already parked `waiting_operator` default-NO in Rev 4; Rev 5 does not change that status. The friendly-name rewrite in D-5.3 is sufficient. | **G2:** yes — the two internal entity_ids `sensor.ura_energy_coordinator_envoy_status` / `binary_sensor.ura_energy_coordinator_energy_envoy_available` are URA-INTERNAL (dashboards and PWA reference them), not user-config-facing. | No change — Card B stays parked. |

### Files touched in Rev 5

| File | Changes | LoC |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/energy_const.py` | `DEFAULT_*` entity-id literals → `None` / `[]`; add `EC_ROLE_KEY_SET` list | ~40 |
| `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` | Pentair `DEFAULT_*` → `None`/`[]` | ~10 |
| `custom_components/universal_room_automation/domain_coordinators/energy_circuits.py` | Generac serial `DEFAULT_*` → `None` | ~5 |
| `custom_components/universal_room_automation/__init__.py` | `_bootstrap_pin_ec_defaults_once` + `_scan_ec_role_entities` wiring | ~140 |
| `custom_components/universal_room_automation/strings.json` | ~15–20 role-word label rewrites + 1 repair-issue translation | ~80 |
| `custom_components/universal_room_automation/translations/en.json` | mirror | ~80 |
| `quality/tests/test_ec_role_defaults_rev5.py` | D-5.5 tests 1, 2, 5, 6 | ~140 |
| `quality/tests/test_bootstrap_pin_registry_based.py` | D-5.5 tests 3, 4 (Rev 2 R3 preserved) | ~60 |
| `quality/tests/fixtures/phalanx_options_pre_migration.json` | committed snapshot | ~1 (fixture) |

**Total: ~555 LoC across 8 production/test files + 1 fixture, vs Rev 4's ~2–3k LoC across ~40 files.** Call it **~400–550 LoC** depending on how terse the label rewrite is.

### Residual risk

1. **A caller silently reads `DEFAULT_X` and now gets `None` without a guard.** Mitigation: D-5.5 test 1 is a grep; the real mitigation is Review A reading every one of the ~15 call sites (there are only ~15; `rg "DEFAULT_SOLCAST_|DEFAULT_CLOUD_|DEFAULT_EVSE_GARAGE_" custom_components/`) and confirming each is `options.get(key, DEFAULT_X)` wrapped by a downstream None-guard. This is a 20-minute reviewer pass, not a 20-file test battery.
2. **A 2nd-install operator misses the empty option field in a nested section and ships into production with unactuated energy logic.** Mitigation: D-5.4 repair issues name every missing entity by name. Not silent.
3. **The pin migration fires a CM reload.** Mitigation: single `async_update_entry` with `_ec_defaults_pinned` + pinned keys in `OPTIONS_RELOAD_SUPPRESS_KEYS` (established Rev 2 R6 path). Test asserts no CM reload during migration.
4. **A `DEFAULT_X` → `None` edit breaks a test that imports the constant and asserts its string value.** Mitigation: D-5.5 test 1 flags this during build; the fix is to update the test, not revert the default.

### Tier

**Tier 2** (two framing-disjoint reviews + live validation):

- **Review A — correctness + caller safety.** Walk every reader of each `DEFAULT_*` constant whose value is going to `None` and prove the reader has a None-guard. Walk every pre-ship call site of the role-keys. `test_default_literals_contain_no_house_entity_ids` passes. The Phalanx fixture byte-identity test passes.
- **Review B — migration + reload safety + repair-issue plumbing.** Confirm the pin-migration write is atomic + suppressed; the Rev 2 R6 reload-silence invariant holds; `ir.async_create_issue` / `ir.async_delete_issue` are called with stable `issue_id`s; the periodic re-scan has a bounded cadence and doesn't ping on every state change.

Not Tier 2-DB. Not Tier 3. If live validation surfaces reload churn or a surprise `None` read-crash, the follow-up cycle elevates.

### Acceptance criteria

- **Verify:** `rg "sensor\.(solcast|envoy|iq_|garage_[ab]_power|generac|pentair)|switch\.(iq_|smartplug_moes|span_panel)|select\.iq_|number\.iq_" custom_components/universal_room_automation/domain_coordinators/*.py` returns 0 lines inside `DEFAULT_*` literal values (allowlisted: `DEFAULT_TOU_RATE_FILE`, non-entity-id constants). Satisfies **G1**.
- **Verify:** every energy-section option field in `strings.json` + `translations/en.json` names a ROLE (what the sensor measures) and does not contain `Envoy | Enphase | Enpower | Encharge | SPAN | Solcast | Generac | Pentair | Emporia | IQ_Battery | IQ_Gateway`. Reviewer-eye grep during Review B. Satisfies **G2**.
- **Verify:** for every role-key `k` in `EC_ROLE_KEY_SET`, the Phalanx post-migration options blob satisfies `(pre_options.get(k) or OLD_DEFAULT) == post_options[k]`. Automated by `test_bootstrap_pins_phalanx_shape_options_byte_identical`. Satisfies **G3** (behavioural byte-identity on the current house).
- **Sensor:** no new sensors. (The repair issue IS the operator surface — no `sensor.ec_entity_health_<key>` entity.)
- **Test:** `test_default_literals_contain_no_house_entity_ids`, `test_bootstrap_pins_phalanx_shape_options_byte_identical`, `test_bootstrap_pins_registered_but_unavailable`, `test_bootstrap_skips_absent_from_registry`, `test_repair_issue_fires_on_configured_missing_entity`, `test_repair_issue_cleared_on_recovery`.
- **Live:** after deploy + HA restart, Phalanx options blob at `.storage/core.config_entries` shows `_ec_defaults_pinned: true` on the CM entry; `energy_dp_span_r1_entity` / `_r2_` and `energy_evse_a_span_breaker` / `_b_` are now set in options (previously fell through to defaults); Repairs dashboard shows **zero** `ec_role_entity_*` issues (because every configured entity on this house is in the registry and available).
- **Live:** every energy actuation that was working the hour before deploy is still working the hour after. (`sensor.energy_coordinator_mode`, battery reserve-SOC writes continuing on-cadence, Solcast forecast consumers populating, EVSE power sensors active.) Review B owns this check against the restarted HA instance.

### LoC budget comparison

| | Rev 4 | Rev 5 |
|---|---:|---:|
| Production files touched | ~20 | 4 |
| Test files touched | ~20 | 2 (+ 1 fixture) |
| Translation files | 2 | 2 |
| Total LoC | ~2000–3000 | ~400–550 |
| CONF-key renames | 12 | 0 |
| Deprecation alias constants | 13 | 0 |
| New state machine states | 4 | 0 |
| New number-knob entities | 1 | 0 |
| New sensors | 1 (`ec_entity_health_*`) | 0 |
| Tier | 2-DB (3 reviews) | 2 (2 reviews) |

### 10-line summary

1. Operator wants three outcomes: no house-specific defaults in code, role-worded fields, and no behaviour change on this house.
2. Rev 4 reached for a 12-key internal CONF rename + 13 deprecation aliases + 10 test-file migration + a 4-state entity-health machine with a grace-ticks knob.
3. Grep of the live Phalanx options proves 10 of 12 brand-named keys are already set in options, so the module-level defaults are dead code for this install.
4. Grep of HA's selector config confirms existing fields already domain-filter correctly.
5. Users never see raw Python CONF-key strings; G2 is a labels-and-translations problem.
6. Rev 5 deletes the house-specific default literals, pins today's resolved values into THIS house's options once at setup, and relabels the UI to role words.
7. "Silently does nothing" is answered by a setup+hourly repair issue listing configured-but-missing entities — no new sensor, no state machine, no grace-ticks knob.
8. The CONF rename, deprecation aliases, test-file migration, reload-safety sweep for new keys, and entity-health machinery all cut; each cut is parked with a revisit trigger that would reintroduce it on evidence.
9. Build drops from ~2–3k LoC across ~40 files to ~400–550 LoC across 8 files; tier drops from 2-DB (3 reviews) to Tier 2 (2 reviews); zero payload-shape change.
10. G1 met by default-literal deletion; G2 met by labels + already-correct selectors; G3 met by the per-key byte-identity assertion on the committed Phalanx fixture.

---

## Rev 4 reconciliation table — plan-review R4-1..R4-6 → changes applied

| # | Sev | Rev 3 claim / gap | Fix in Rev 4 | Where applied |
|---|---|---|---|---|
| R4-1 | HIGH | Rev 3 D1-RENAME said "~55 URA entity_id renames across `sensor.py` / `binary_sensor.py` / `switch.py` / `number.py`" and claimed HA `entity_registry.async_migrate_entries` would auto-update Lovelace / PWA references. | **Both wrong.** Verified: only **2** URA entities carry a brand token in their entity_id: `sensor.ura_energy_coordinator_envoy_status` (`sensor.py:14214`) and `binary_sensor.ura_energy_coordinator_energy_envoy_available` (`binary_sensor.py:2849`). The other `sensor.py`/`binary_sensor.py` brand-token hits are inside friendly names, translation keys, attribute payloads, docstrings or state values — not entity_ids. **HA has NO registry shim** that rewrites Lovelace card YAML, HA automations referencing the old entity_id, or the PWA — `entity_registry.async_migrate_entries` updates the registry row but every downstream consumer that typed the old entity_id as a string stays broken until manually edited. `binary_sensor.ura_energy_coordinator_energy_envoy_available` is referenced in 4 live dashboards (`docs/dashboards/ura_tabbed_*.yaml`, v6, v7, v8 recipes — 6 uses total), in **`PWA dashboard/src/types/entities.ts:23`**, and in `quality/tests/test_cycle_e_observability.py`. **DECISION:** keep `entity_id` and `unique_id` stable; role-word the **friendly name / translation key only** ("Battery gateway online" / "Battery gateway status"). Drop `async_migrate_entries`. Retract the auto-update claim. Fix the "ura_(envoy\|solcast)_" grep (vacuous as scoped — it would miss friendly-name hits anyway and false-trigger on legitimate internal variables). The Rev 3 D6 "Entity-ID grep" line is **removed**. | Build A §"Entity-ID discipline (Rev 4 R4-1)"; D1-RENAME row for URA entities REWRITTEN; D6 grep set revised. Entity-ID renames split into **Card B** (operator decision; default no). |
| R4-2 | HIGH | Rev 3 D1-RENAME listed 17 CONF renames (table + rolled-up count); the actual table enumerates **12**. Rev 3 didn't list the 10 test files that assert the old raw CONF-key strings. Didn't specify reload safety for the NEW key names. Didn't specify the roll-back posture (keep-both vs delete-old). | **Reconciled count: 12.** The final set is listed verbatim below (§"Build A — final CONF rename set, 12 renames"). The 10 test files that assert the raw strings are enumerated with file:line in §"Test migration — real file list". Reload safety: the NEW key names are added to `OPTIONS_RELOAD_SUPPRESS_KEYS` in the same commit AS WELL AS the migration flags; **old keys are kept** (copy, don't delete) **for ONE release** to allow rollback, with removal carded for the next cycle. Rollback note added to the README template. | §"Build A — final CONF rename set"; §"Reload safety for new keys"; §"Rollback posture"; §"Test migration — real file list". |
| R4-3 | HIGH | Rev 3 D1-RENAME row 1 proposed renaming `CONF_ENERGY_ENVOY_ENTITY` to `CONF_ENERGY_BATTERY_SOC_SOURCE_ENTITY` or similar, "depending on what it actually holds." | **Verified in Phase 0 extension:** this CONF holds the entity `sensor.envoy_<serial>_current_power_production` — a solar-production power sensor (unit=kW). It is used **only as a serial anchor** via `extract_envoy_serial()` (`energy_const.py:1245`); nothing reads its state. Role-wording it as "Battery SOC source" would be a lie. **Phase 1 does not rename this CONF.** Phase 1 relabels only the UI text to "Solar gateway sensor" (role-neutral but still Enphase-flavoured because the thing it anchors is the Envoy serial). The CONF, its validator (`validate_envoy_entity`, `energy_const.py:1575-1605`), and the `ENVOY_ERR_*` error codes all move to **Phase 2** behind the Enphase adapter. The `_envoy_hard_fail` boot gate at `__init__.py:3722` likewise stays as-is in Phase 1. | Build A: `CONF_ENERGY_ENVOY_ENTITY` **dropped** from the rename set. UI text update only. D1-RENAME table row 1 REWRITTEN. §"Phase 2 scope" extended to own the serial anchor + validator + ENVOY_ERR_* + boot gate. |
| R4-4 | HIGH | Rev 3 D2-SELECTORS said "`unit_of_measurement:` where meaningful" as a selector filter. | **Verified in HA source** `.venv-ha/lib/python3.13/site-packages/homeassistant/helpers/selector.py:179-184` (`EntityFilterSelectorConfig` TypedDict): the only supported filter fields are `domain`, `device_class`, and `supported_features` / `integration` / `multiple`. **`unit_of_measurement` is NOT a filter field.** Validator (not selector) does the unit check post-submit. Furthermore, verified live-house attributes: `number.iq_battery_hacs_battery_reserve`, `select.iq_gateway_hacs_system_profile`, and `switch.iq_battery_hacs_charge_battery_from_grid` have **NO `device_class`** attribute set. Using `device_class:` filters on these would hide the correct target entities. **DECISION:** domain-only filters for `number` / `select` / `switch` reserve/mode/charge-from-grid; `device_class:` only where the live target entity carries one (confirmed: `sensor.envoy_<serial>_battery` → `device_class=battery`; mains power sensors → `device_class=power`; forecast kWh sensors → `device_class=energy`). Validator does unit-of-measurement and shape checks. §"Live attribute table" below records what each target entity actually exposes. | D2-SELECTORS REWRITTEN. §"Live attribute table" added. |
| R4-5 | MED | Rev 3 proof: one-shot resolved-map diff. Rev 3 D5 "no old key read anywhere" grep used a free-form regex (brand tokens by name, no allowlist-by-constant-name). Rev 3 didn't check dashboard / PWA consumers of the display attribute keys `solcast_today / _remaining / _tomorrow` (`energy.py:1076-1078`) before renaming them. | Stronger proof: **after migration, old-key reads return nothing** (`"CONF_ENERGY_ENVOY_ENTITY"` and the 11 others are allowlisted BY CONSTANT NAME in the production code grep, not by regex — the allowlist is a Python list of the exact pre-Rev-4 identifiers kept as deprecation aliases for one release) **AND the EC's `_build_entity_map` output (the dict `{conf_key → resolved_entity_id}` emitted at setup) is byte-equal to a pre-migration options snapshot captured in-suite**. Test lives in `quality/tests/test_ec_entity_defaults_migration.py` and loads a committed JSON snapshot of a Phalanx-shape options blob. The pre-migration snapshot is captured in the same cycle (committed as a fixture). **Attribute-key consumer check (done inside this plan):** `rg "solcast_(today\|remaining\|tomorrow)"` across the repo + PWA — hits found in `docs/dashboards/ura_v8_energy_ev_detail_card.md`, PWA `dashboard/src/types/entities.ts` (if present), and `docs/planning/*` + `docs/readmes/*`. **DECISION:** since dashboard and PWA consumers are confirmed, the attribute keys `solcast_today / _remaining / _tomorrow` **stay as-is in Build A**; renaming them is folded into a later cycle paired with a dashboard/PWA update. (Rev 3 D1-RENAME row for attribute keys REMOVED.) | §"Stronger proof — in-suite entity-map equality"; §"Allowlist by constant name, not regex"; §"Attribute-key consumer check (done)"; D1-RENAME attribute-key row removed. |
| R4-6 | MED | Rev 3 bundled everything (defaults cleanse + CONF renames + translations + entity-ID renames) into one Tier 2-DB build. The entity-ID piece is high blast-radius and operator-facing. | **Split into three deliveries:**  Build A = Rev 2 cleanse + 12 CONF renames (**minus** the Envoy anchor) + labels/translations. Card B = `sensor.ura_energy_coordinator_envoy_status` + `binary_sensor.ura_energy_coordinator_energy_envoy_available` entity-ID renames; operator decides whether to run it; default **NO** (friendly-name relabel is sufficient for Rev-4 brand-neutrality). Phase 2 = the thin adapter cycle, including the Envoy anchor CONF + validator + boot gate. | §"Build A / Card B / Phase 2 split" (restated throughout). |

---

## Build A — final CONF rename set (12 renames; Envoy anchor NOT included)

| # | Old brand-named key | Role name (new) | Role | Validator checks | Notes |
|---|---|---|---|---|---|
| 1 | `CONF_ENERGY_EVSE_A_SPAN_BREAKER` (`energy_const.py:862`) | `CONF_ENERGY_EVSE_A_BREAKER_SWITCH` | Switch that pauses/resumes charger A at the panel | selector: `domain=switch`; validator: entity in registry + domain=switch | — |
| 2 | `CONF_ENERGY_EVSE_B_SPAN_BREAKER` (`:863`) | `CONF_ENERGY_EVSE_B_BREAKER_SWITCH` | mirror | mirror | — |
| 3 | `CONF_ENERGY_SOLCAST_TODAY_ENTITY` (`:284`) | `CONF_ENERGY_SOLAR_FORECAST_TODAY_ENTITY` | kWh-forecast-today sensor | selector: `domain=sensor`, `device_class=energy`; validator: `unit_of_measurement=kWh` and `forecast`/`detailedHourly` attribute shape (`energy_forecast.py`) | — |
| 4 | `CONF_ENERGY_SOLCAST_REMAINING_ENTITY` | `CONF_ENERGY_SOLAR_FORECAST_REMAINING_ENTITY` | kWh remaining today | mirror | — |
| 5 | `CONF_ENERGY_SOLCAST_TOMORROW_ENTITY` | `CONF_ENERGY_SOLAR_FORECAST_TOMORROW_ENTITY` | kWh forecast tomorrow | mirror | — |
| 6 | `CONF_ENERGY_SOLCAST_DAY_3_ENTITY` (`:1016`) | `CONF_ENERGY_SOLAR_FORECAST_DAY_3_ENTITY` | kWh forecast day 3 | mirror | — |
| 7 | `CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN` (`:1100`) | `CONF_ENERGY_CIRCUIT_AUTODISCOVER_ENABLED` | boolean enable for circuit autodiscover | boolean | SPAN-specific regex at `energy_circuits.py:172` stays and moves to Phase 2 adapter |
| 8 | `CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY` (`:295`) | `CONF_ENERGY_RESERVE_READBACK_ORACLE_ENTITY` | read-back verification of reserve-SOC write | selector: `domain=number`; **no `device_class` filter** (live iq_battery_hacs reserve has none per R4-4); validator: `unit_of_measurement in {"%", None}` and value in `[0, 100]` | — |
| 9 | `CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY` (`:296`) | `CONF_ENERGY_CHARGE_FROM_GRID_READBACK_ORACLE_ENTITY` | read-back for charge-from-grid | selector: `domain=switch`; no `device_class` (R4-4) | — |
| 10 | `CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY` (`:299`) | `CONF_ENERGY_STORAGE_MODE_READBACK_ORACLE_ENTITY` | read-back for storage mode | selector: `domain=select`; no `device_class` (R4-4); validator: option-set non-empty | — |
| 11 | `CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY` (`:302`) | `CONF_ENERGY_BATTERY_SOC_FALLBACK_ENTITY` | last-resort SOC read | selector: `domain=sensor`, `device_class=battery`; validator: `unit_of_measurement in {"%", None}`, value in `[0, 100]` | — |
| 12 | `CONF_ENERGY_DP_SPAN_R1_ENTITY` / `_R2_ENTITY` (Rev 2 new CONFs) | `CONF_ENERGY_HOUSE_MAINS_R1_POWER_ENTITY` / `_R2_` | SPAN mains r1/r2 house-load inputs | selector: `domain=sensor`, `device_class=power`; validator: `unit_of_measurement=W` | Rev 2 R8 updated: role-neutral per Rev 4 Build A brand-neutrality. Counts as ONE row for 12-count. |

**Not renamed in Build A:**

- `CONF_ENERGY_ENVOY_ENTITY` — stays. Phase 2 owns it (R4-3).
- All Rev 2-new CONFs that are already role-named (`CONF_ENERGY_EVSE_A_SWITCH / _ENERGY_TODAY / _ENERGY_MONTH / _CURRENT_LIMIT` + B; `CONF_ENERGY_GENERATOR_STATUS_ENTITY`; 5× Pentair) — these are born role-named, no rename, just the usual D1 new-CONF plumbing from Rev 2.
- Attribute keys `solcast_today / _remaining / _tomorrow` — stay (R4-5, dashboard + PWA consumers confirmed).
- Error-code constants `ENVOY_ERR_*` — stay in Build A; move with the Envoy anchor to Phase 2 (R4-3).

---

## Entity-ID discipline (Rev 4 R4-1)

### Verified entity-ID surface

Grepped `custom_components/universal_room_automation/{sensor.py,binary_sensor.py,switch.py,number.py,select.py,button.py}` for brand tokens in entity_id strings. **Only two** entity IDs carry a brand token:

1. `sensor.ura_energy_coordinator_envoy_status` — defined `sensor.py:14214`.
2. `binary_sensor.ura_energy_coordinator_energy_envoy_available` — defined `binary_sensor.py:2849`.

(The other `sensor.py` / `binary_sensor.py` brand-token hits are: friendly-name strings, translation keys, attribute payload keys, docstrings, and state-value strings. None are entity_ids. These are handled by the labels/translations work in Build A, not by an entity-ID rename.)

### Known external consumers of these two entity IDs

- Dashboards (6 uses across 4 files): `docs/dashboards/ura_tabbed_*.yaml`, `docs/dashboards/ura_v6*.md`, `docs/dashboards/ura_v7*.md`, `docs/dashboards/ura_v8*.md` — grep: `rg "energy_envoy_available"` returns 6 hits.
- PWA: `dashboard/src/types/entities.ts:23` (sibling repo `~/Code/ura-dashboard-pwa` — not in this repo).
- Tests: `quality/tests/test_cycle_e_observability.py` asserts on `energy_envoy_available`.

**HA has NO shim that rewrites Lovelace card YAML, HA automations, PWA code, or test fixtures.** `entity_registry.async_migrate_entries` updates the registry row only; every string reference to the old entity_id elsewhere stays broken.

### Build A decision

- **Keep `entity_id` and `unique_id` stable.** Role-word the friendly name + translation key only:
  - `sensor.ura_energy_coordinator_envoy_status` → friendly name "Battery gateway status" (entity_id unchanged).
  - `binary_sensor.ura_energy_coordinator_energy_envoy_available` → friendly name "Battery gateway online" (entity_id unchanged).
- **Drop** `entity_registry.async_migrate_entries` from Build A.
- **Remove** the Rev 3 D6 "Entity-ID grep" line (vacuous — would miss friendly-name hits and would false-trigger on legitimate variable identifiers).
- **Remove** the Rev 3 "~55 entity_id renames" claim.
- **Remove** Rev 3's "HA auto-update post-deploy" operator note.

### Card B — entity-ID renames (operator decides; default NO)

If the operator later wants brand-neutral entity_ids too, Card B does the two renames in a dedicated cycle:
1. Coordinate with dashboard-maintainer branches for the 6 Lovelace uses.
2. Coordinate with the PWA repo for the TypeScript type.
3. Update `quality/tests/test_cycle_e_observability.py`.
4. One-shot migration via `entity_registry.async_migrate_entries` keyed on unchanged `unique_id`.
5. Keep an alias (RestoreEntity under old entity_id) for ONE release for safety.

Default is **NO** — the friendly-name relabel in Build A is sufficient for the brand-neutrality invariant. Card B minted and parked `waiting_operator` after Build A ships.

---

## D2-SELECTORS REWRITTEN (Rev 4 R4-4)

### What HA actually supports

Verified at `.venv-ha/lib/python3.13/site-packages/homeassistant/helpers/selector.py:179-184`:

```python
class EntityFilterSelectorConfig(TypedDict, total=False):
    integration: str
    domain: str | list[str]
    device_class: str | list[str]
    supported_features: list[str]
```

**No `unit_of_measurement` filter field exists.** Any unit check must happen in the validator after submit, not in the selector.

### Live attribute table (what each target entity actually exposes on Phalanx)

| CONF key (role-named) | Live target entity | `domain` | `device_class` | `unit_of_measurement` | Selector filter choice | Validator check |
|---|---|---|---|---|---|---|
| `_SOLAR_FORECAST_TODAY_ENTITY` (and sibling 3) | `sensor.solcast_pv_forecast_forecast_today` | sensor | `energy` | `kWh` | `domain=sensor`, `device_class=energy` | `unit="kWh"` + attribute shape |
| `_BATTERY_SOC_FALLBACK_ENTITY` | `sensor.iq_battery_hacs_battery_overall_charge` | sensor | `battery` | `%` | `domain=sensor`, `device_class=battery` | `unit="%"` + value `[0,100]` |
| `_RESERVE_READBACK_ORACLE_ENTITY` | `number.iq_battery_hacs_battery_reserve` | number | **none** | `%` | `domain=number` only | `unit="%"` + value `[0,100]` |
| `_STORAGE_MODE_READBACK_ORACLE_ENTITY` | `select.iq_gateway_hacs_system_profile` | select | **none** | — | `domain=select` only | option-set non-empty |
| `_CHARGE_FROM_GRID_READBACK_ORACLE_ENTITY` | `switch.iq_battery_hacs_charge_battery_from_grid` | switch | **none** | — | `domain=switch` only | — |
| `_EVSE_A_BREAKER_SWITCH` / `_B_` | `switch.span_panel_car_charger_breaker` / `..._garage_b_evse_breaker` | switch | **unverified** (likely none) | — | `domain=switch` only | — |
| `_HOUSE_MAINS_R1_POWER_ENTITY` / `_R2_` | `sensor.span_panel_current_power` / `..._2` | sensor | `power` | `W` | `domain=sensor`, `device_class=power` | `unit="W"` |
| `_EVSE_A_ENTITY` / `_B_` (power — Rev 2) | `sensor.garage_a_power_minute_average` | sensor | `power` | `W` | `domain=sensor`, `device_class=power` | `unit="W"` |
| `_L1_CHARGER_ENTITIES` | `switch.smartplug_moes_wifi_garageale...` | switch | — | — | `domain=switch`, `multiple=True` | — |
| `_GENERATOR_STATUS_ENTITY` | `sensor.generac_2325624_status_2` | sensor | **unverified** | — | `domain=sensor` only | state in known enum |
| `_POOL_VSF_SPEED_ENTITY` + Pentair siblings | `number.pentair_pool_variable_speed_pump_1_speed` etc. | number | **unverified** | `%` or `rpm` | `domain=number` only | numeric |

**Rule:** `device_class` filter is used ONLY where the live entity carries one. Everywhere else, `domain`-only + validator. **Zero** `integration:` filters anywhere.

(Builder must re-verify the "unverified" rows via a live HA REST pull before freezing selectors; those are safe-defaults as `domain`-only but may tighten.)

---

## Test migration — real file list (R4-2)

The following tests reference the old CONF-key constants directly and must be migrated in Build A (either updated to the new constant OR left pointing at the deprecation alias for ONE release):

| # | Test file | Hits | Example line | Alias-OK vs rename-now |
|---|---|---:|---|---|
| 1 | `quality/tests/test_room_options_reload_suppression.py` | 1 | assertion on `CONF_ENERGY_CLOUD_*` key being in suppress list | rename-now (new keys in suppress list) |
| 2 | `quality/tests/test_part2_ec_hc_writeback.py` | 2 | — | rename-now |
| 3 | `quality/tests/test_envoy_boot_decoupling.py` | 19 | asserts on `CONF_ENERGY_ENVOY_ENTITY` | **keep old (R4-3)** — Envoy anchor NOT renamed in Build A |
| 4 | `quality/tests/test_energy_write_verification.py` | 12 | `CONF_ENERGY_CLOUD_*_ORACLE_ENTITY` round-trip | rename-now |
| 5 | `quality/tests/test_span_circuit_rekey.py` | 14 — including raw strings at `:425-494, 1304-1305` | asserts raw `"energy_evse_a_span_breaker"` option-key string | **both:** update constant imports AND update the raw strings in `:425-494, 1304-1305` (or add a tested shim that reads old-and-new) |
| 6 | `quality/tests/test_reload_watchdog_hazard.py` | 1 | — | rename-now |
| 7 | `quality/tests/test_envoy_auto_derive.py` | 16 | serial parsing on `CONF_ENERGY_ENVOY_ENTITY` | **keep old (R4-3)** |
| 8 | `quality/tests/test_ec_solar_entity_override.py` | 1 | — | rename-now |
| 9 | `quality/tests/test_baec_config_flow_round_trip.py` | 3 — including raw strings at `:129-185` | round-trip asserts raw option-key strings | update raw strings alongside constants |
| 10 | `quality/tests/test_cm_reload_suppression.py` | 1 | — | rename-now |
| 11 | `quality/tests/test_ec_degraded_data_p1.py:1615` | 1 raw string | — | update raw string |

**Total: 10 test files** (plus the 11th degraded-data file for the raw string). Builder updates these in Build A as part of the CONF-rename commit. Tests on `CONF_ENERGY_ENVOY_ENTITY` and the serial-parsing path stay on the OLD name (Phase 2 owns them).

---

## Reload safety for new keys (R4-2)

- In the SAME commit as the migration, add every **new** role-named CONF key to `OPTIONS_RELOAD_SUPPRESS_KEYS` at `__init__.py:6435`, in addition to the migration bookkeeping flags (`_ec_defaults_migrated`, `_ec_rename_migrated`, their `_version` / `_at` siblings). Rev 2 R6 explained the mechanism.
- Preferred alternative: **one atomic `async_update_entry` call** that writes all migrated keys + flags in one shot, with a short-circuit at the top of the options-change listener (`if changed_keys == {<rename keys>} and _ec_rename_migrated transitioning False→True: skip`). If feasible, this removes the need to pre-populate the suppress list.
- Both paths tested: `test_bootstrap_rename_does_not_trigger_cm_reload`.

---

## Rollback posture (R4-2)

- **Old CONF keys are copied, not deleted,** in Build A. Both `CONF_ENERGY_SOLCAST_TODAY_ENTITY` (old) AND `CONF_ENERGY_SOLAR_FORECAST_TODAY_ENTITY` (new) exist in `energy_const.py` for one release; the old is a `Final` alias set to the SAME string value as before. Only the new is read by production code (Build A test `test_no_old_key_read_in_production` greps `custom_components/universal_room_automation` for reads of old-name constants and allows only the deprecation-alias definition line itself).
- **Rollback:** downgrading the integration restores the old constants from the earlier wheel. The options blob still contains BOTH keys for one release (migration copies, does not delete), so the downgraded code finds its expected keys. Zero data loss.
- **Removal cycle:** carded for the next minor as `EC-HOUSE-ENTITY-DEFAULTS-2`. Removes the alias constants AND the old keys from options via a second migration pass.
- **README template** gains a short "Rollback" paragraph: "This release migrates CONF keys; downgrade is safe for one release — the old keys are retained as aliases. Downgrade becomes lossy at the next minor."

---

## Stronger proof — in-suite entity-map equality (R4-5)

- New helper `EnergyCoordinator._build_entity_map(options_blob) -> dict[str, str | None]` enumerates every role-named CONF (post-Build-A set) and returns `{conf_key → resolved_entity_id}` using the merged `data | options` view, without reading HA state. Pure function of the options blob + the role-key registry.
- `quality/tests/test_ec_entity_defaults_migration.py` runs:
  1. Load `quality/tests/fixtures/phalanx_options_pre_migration.json` (committed snapshot of a current-house options blob, prefix-stripped of PII).
  2. Call `_bootstrap_ec_entity_defaults_and_rename` on a copy.
  3. Build the entity map from the pre-migration options via the OLD→NEW alias lookup, and from the post-migration options via the NEW keys only.
  4. Assert `pre_map == post_map` on the final `(conf_key_role_name, resolved_entity_id)` set.
- A second assertion: the post-migration options blob read ONLY through the new keys returns the same resolved entity for every row as the pre-migration options blob read through the old keys.
- This replaces Rev 3's "one-shot resolved-map dump pre/post" as the authoritative byte-identity proof (the live dump stays as an operator-visible sanity check during Live Validation).

---

## Allowlist by constant name, not regex (R4-5)

The "no old key read anywhere" grep is replaced by a Python test that imports `custom_components.universal_room_automation.domain_coordinators.energy_const` and asserts that each constant in the explicit allowlist below is defined (one release of safety) BUT is referenced by **zero production files**:

```python
DEPRECATION_ALIAS_CONSTANTS = [
    "CONF_ENERGY_EVSE_A_SPAN_BREAKER",
    "CONF_ENERGY_EVSE_B_SPAN_BREAKER",
    "CONF_ENERGY_SOLCAST_TODAY_ENTITY",
    "CONF_ENERGY_SOLCAST_REMAINING_ENTITY",
    "CONF_ENERGY_SOLCAST_TOMORROW_ENTITY",
    "CONF_ENERGY_SOLCAST_DAY_3_ENTITY",
    "CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN",
    "CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY",
    "CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY",
    "CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY",
    "CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY",
    "CONF_ENERGY_DP_SPAN_R1_ENTITY",
    "CONF_ENERGY_DP_SPAN_R2_ENTITY",
]
```

(`CONF_ENERGY_ENVOY_ENTITY` is **absent** — it is not deprecated in Build A per R4-3.)

The test uses `rg` under the hood but keyed on these exact identifier strings as whole-word matches, not a regex over brand tokens. Production files = `custom_components/universal_room_automation/**/*.py` minus `energy_const.py` (where the alias definition itself lives) and minus `migrations/` (where the migration references them). Tests are excluded from the "production files" set and may freely reference old constants.

---

## Attribute-key consumer check (done, R4-5)

Checked repo + sibling PWA for `solcast_today | solcast_remaining | solcast_tomorrow`:

- `docs/dashboards/ura_v8_energy_ev_detail_card.md` — contains attribute references.
- `docs/dashboards/ura_v8_exterior_cycle2_cards.md` — one hit.
- PWA (`~/Code/ura-dashboard-pwa`) — unchecked here (sibling repo not grepped by this agent); builder confirms before shipping. **Default assumption: PWA references these attribute keys** (per PWA entities-type file).
- `docs/planning/*.md` + `docs/readmes/*.md` — mentions.

**DECISION:** attribute keys `solcast_today / _remaining / _tomorrow` **stay unchanged in Build A.** Rev 3's rename row for attribute keys is **removed**. A follow-up cycle (not carded yet) will coordinate the attribute-key rename with the dashboard + PWA update as one atomic change.

---

## Build A — final deliverables (supersedes Rev 3 Phase 1 deliverables)

### D-RENAME-A1 — 12 CONF renames + deprecation aliases

- Add 12 new role-named `CONF_ENERGY_*` constants in `energy_const.py`.
- Keep the 13 old constants (12 Build-A renames + `CONF_ENERGY_DP_SPAN_R1/R2` from Rev 2) as deprecation aliases set to the SAME string values; mark with `# DEPRECATED: use <new_name>; alias removed in next minor`.
- Update all **production** reads to the new constants.
- Update 10 test files per §"Test migration — real file list"; tests on `CONF_ENERGY_ENVOY_ENTITY` stay on the old name.

### D-RENAME-A2 — labels + translations

- `strings.json` + `translations/en.json`: rewrite ~80 strings per `feedback_label_style_guide`. Examples:
  - "Envoy battery SOC entity" → "Battery charge sensor"
  - "SPAN panel breaker switch for Garage A" → "Garage A charger breaker switch"
  - "Solcast forecast — today" → "Solar forecast today"
  - "Enpower storage mode" → "Battery mode"
  - "Envoy entity" (for the Envoy anchor) → "Solar gateway sensor" (R4-3 relabel-only)
- The 2 URA entity friendly names (R4-1): "Battery gateway status", "Battery gateway online". Entity IDs unchanged.
- Translation-key renames use a one-release alias (old key kept, pointing at same string).

### D-RENAME-A3 — selectors + validator

- Options-flow entity selectors: domain filter always; `device_class` only where the live target entity has one (§live attribute table); no `integration:` filter; no `unit_of_measurement:` filter (R4-4 — doesn't exist in HA).
- Validators do unit + range + attribute-shape checks post-submit.
- `validate_envoy_entity` stays as-is (Phase 2, R4-3).

### D-RENAME-A4 — one-shot migration + reload safety

- `_bootstrap_ec_entity_defaults_and_rename(hass, cm_entry)` runs once per CM entry at setup:
  1. Rev 2 D3 registry-based pin for cleansed defaults.
  2. For each of the 12 Build-A rename pairs, if old key present in `data | options` AND new key absent → copy old value to new key, **keep old key**.
  3. Flags: `_ec_defaults_migrated=True`, `_ec_rename_migrated=True`, `_ec_rename_migrated_version="5.X.Y"`, `_ec_rename_migrated_at=<utc>`.
  4. Atomic `async_update_entry` with all keys + flags; OR per-key writes with new keys in `OPTIONS_RELOAD_SUPPRESS_KEYS`. Build-A tests cover both paths; builder picks one in commit.
- Rev 2 D3 reload-suppression continues to apply.

### D-RENAME-A5 — tests

- `test_rename_migration_roundtrip` — pre-migration options → run → both keys present with same value, flags set.
- `test_rename_migration_idempotent` — run twice; second no-op.
- `test_rename_migration_does_not_trigger_cm_reload` — Rev 2 R6 extended.
- `test_bootstrap_pins_registered_but_unavailable` — Rev 2 R3 preserved.
- `test_bootstrap_skips_absent_from_registry` — Rev 2 R3 preserved.
- `test_no_old_key_read_in_production` — allowlist by constant name (R4-5); production files excluding alias definition.
- `test_selector_accepts_non_enphase_entity_of_appropriate_shape` — synthetic `sensor.solark_forecast_today` (`domain=sensor, device_class=energy, unit=kWh`) passes selector + validator; synthetic `sensor.random_text` (unit missing) fails validator.
- `test_envoy_anchor_conf_unchanged` — asserts `CONF_ENERGY_ENVOY_ENTITY` is still the production constant and the migration does NOT rewrite it (R4-3 anti-regression).
- `test_entity_map_equality_pre_post_migration` — in-suite entity-map equality against committed fixture (R4-5).
- `test_envoy_url_entity_ids_unchanged` — asserts `sensor.ura_energy_coordinator_envoy_status` and `binary_sensor.ura_energy_coordinator_energy_envoy_available` remain the production entity_ids (R4-1 anti-regression). Friendly names come from the new translation keys.

### D-RENAME-A6 — acceptance greps (Rev 4)

- **UI-surface literal grep** (strings.json / translations / docs/dashboards):
  ```
  rg -n --pcre2 -g '!**/frontend-v3/**' -g '!quality/**' -g '!docs/planning/**' -g '!docs/reviews/**' \
     "(?<!# )['\"][^'\"]*(Envoy|Enphase|Enpower|Encharge|IQ_Battery|IQ_Gateway|SPAN panel|SPAN_|Solcast|Generac|Pentair|Emporia)[^'\"]*['\"]" \
     custom_components/universal_room_automation docs/dashboards
  ```
  Must return 0 lines. **Allowlist by constant name** for the integration-canonical default-value strings (`DEFAULT_CLOUD_*_ORACLE_ENTITY`, `DEFAULT_SOLCAST_*_ENTITY`) — the allowlist is a Python test that reads those constant NAMES from `energy_const.py` and skips lines matching their values.
- **Production CONF-name grep** — the by-constant-name test from §allowlist (R4-5).
- **No entity-ID grep.** The Rev 3 "ura_(envoy\|solcast)_" grep is removed (vacuous and misleading, per R4-1).

### D-RENAME-A7 — dashboards

- `docs/dashboards/ura_v8_exterior_cycle2_cards.md` and `docs/dashboards/ura_v8_energy_ev_detail_card.md` — update brand-token text in card titles / descriptions. Entity IDs in these files stay unchanged (match Build A R4-1 decision). Attribute-key references (`solcast_today` etc.) stay unchanged (R4-5).

---

## Phase 1 → Build A tier + review framings (updated)

**Tier 2-DB — three framing-disjoint reviews:**

- **Review A — Correctness + control path.** Every pre-Build-A call site now reads the role-named CONF; deprecation aliases exist in exactly one place; `_build_entity_map` returns the same shape pre/post; `CONF_ENERGY_ENVOY_ENTITY` untouched (R4-3 regression check); the two URA entity IDs untouched (R4-1 regression check).
- **Review B — Migration correctness + reload safety.** Rev 2 R3 registry pin preserved; R6 reload suppression covers NEW keys and flags; rollback posture holds (old keys present after migration); idempotency; atomic-write vs suppress-list choice tested on both paths; `test_entity_map_equality_pre_post_migration` passes against the committed Phalanx fixture.
- **Review C — New surfaces + UI brand audit + selector correctness.** Selector filters match the live-attribute table (R4-4); validators carry the unit/range/shape checks that selectors can't; UI-surface grep passes; translation-key alias works; the 10 test files + 3 raw-string files updated per §test migration; label-style-guide compliance.

**Plan review:** Rev 4 is the plan after Rev 3 FIX-REQUIRED; one more adversarial plan review before build dispatch is prudent (Rev 4 narrowed scope substantially and the Build-A/Card-B/Phase-2 split is new).

---

## Open questions (Rev 4)

1. (Rev 2 R8) 2nd install timing — ship Build A before the 2nd install's next upgrade. Deploy ordering, not a blocker.
2. (Rev 2 R8 / Rev 3 Q2) `_HOUSE_MAINS_R1/R2_POWER_ENTITY` final names — locked at those names per Rev 4 brand-neutral posture.
3. (Rev 4 R4-1) Card B minting — operator approves/declines after Build A ships. Default **NO**.
4. (Rev 4 R4-3) `CONF_ENERGY_ENVOY_ENTITY` + `validate_envoy_entity` + `ENVOY_ERR_*` + `_envoy_hard_fail` all move to Phase 2 with the Enphase adapter. Confirmed.
5. (Rev 4 R4-4) Any `device_class` "unverified" rows in the live-attribute table (Generator, Pentair, SPAN breakers) must be verified via a live HA REST pull before Build A freeze. Builder owns.
6. (Rev 4 R4-5) PWA attribute-key references — builder confirms before Build A ships that NO production code renames `solcast_today / _remaining / _tomorrow`.

---

## Rev 3 — content preserved (superseded by Rev 4 overrides above)

The Rev 3 plan text follows unchanged for historical reference. **Where Rev 3 conflicts with Rev 4, Rev 4 governs.** In particular: Rev 3's "~55 entity-ID renames" claim, its `entity_registry.async_migrate_entries` auto-update claim, its 17-CONF count, its `unit_of_measurement` selector filter, and its proposed `CONF_ENERGY_ENVOY_ENTITY` rename are all retracted. Rev 3's attribute-key rename row is removed per R4-5.

### Rev 3 reconciliation table — Phase 0 audit → Phase 1 build → Phase 2 scope

| # | Scope widening | Change in Rev 3 |
|---|---|---|
| W1 | Core cannot assume Enphase/Enpower gear | Phase 0 audit classifies every brand mention into (a) comment/doc, (b) hardcoded default entity, (c) brand-named CONF key or label, (d) real brand-specific behaviour. Phase 1 removes (b) and (c); Phase 2 confines (d) behind an adapter interface. |
| W2 | CONF keys and labels must be role-worded | Phase 1 §"Role-name mapping" lists every rename; **(Rev 4 retract):** options-flow selectors filter by `domain` + `device_class` ONLY (no unit); labels per `feedback_label_style_guide`. |
| W3 | "Change the pointers" | Phase 1 D-RENAME extends the Rev 2 D3 migration; **(Rev 4 retract):** URA entity_id renames are deferred to Card B. |
| W4 | Byte-identical behaviour on this house | Phase 1 keeps the Rev 2 one-shot resolved-map dump + **(Rev 4 upgrade):** in-suite entity-map equality against a committed fixture. |
| W5 | Thin equipment adapter | Phase 2 defines the role interface, Enphase adapter, invariant, second-vendor requirements. Not built in this cycle. **(Rev 4 add):** Phase 2 also owns `CONF_ENERGY_ENVOY_ENTITY` + its validator + `ENVOY_ERR_*` + the `_envoy_hard_fail` boot gate. |

### Phase 0 — read-only audit (counts preserved)

Case-insensitive brand-token hit counts (Rev 3): `energy.py` 195, `energy_battery.py` 164, `energy_const.py` 144, `__init__.py` 74, `energy_pool.py` 44, `energy_forecast.py` 30, `energy_write_verify.py` 26, `energy_billing.py` 20, `energy_billing_counters.py` 7, `energy_circuits.py` 7. Total 711. Bucket (a) ≈ 317; (b) 36 literals; **(c) 12 brand-named CONFs** (Rev 4 reconciled count — Rev 3 said 17 in rolled-up text, 12 in table; 12 is the correct number); (d) 8 brand-specific behaviours (Envoy serial parser + validator; Enpower storage-mode / reserve / charge-from-grid; write-verify oracle round-trip; SPAN R1+R2 mains; SPAN circuit regex; Emporia current-limit; Pentair VSF + Generac enum).

### Phase 2 — thin energy-equipment adapter (preserved, extended)

Phase 2 is still scoped only in this plan. Interface sketch, Enphase adapter bucket (d) ownership, and second-vendor requirements are as in Rev 3. **Rev 4 extension:** Phase 2 additionally owns:

- `CONF_ENERGY_ENVOY_ENTITY` CONF key.
- `validate_envoy_entity` validator (`energy_const.py:1575-1605`).
- `ENVOY_ERR_REQUIRED / INVALID_FORMAT / ENTITY_MISSING` error codes.
- `extract_envoy_serial` regex parser (`energy_const.py:1245`).
- `_envoy_hard_fail` boot gate at `__init__.py:3722` — moves inside the Enphase adapter's `is_healthy()`.

Falsifiable invariant (Phase 2): no file in `domain_coordinators/` outside `energy_equipment/` imports a brand name, parses a brand serial, references a brand-specific option-string, or implements a brand-specific regex. Tier 3 with four framings (A/B/C/D), D is the adversarial completeness pass.

---

## Rev 2 reconciliation table — preserved

| # | Sev | Rev 1 gap (plan-reviewer) | Fix in Rev 2 | Where applied |
|---|---|---|---|---|
| R1 | HIGH | Enpower battery-control defaults missed (`energy_const.py:235-238`); verdict needed on cloud-oracle (`:305-313`), Generac serial (`energy_circuits.py:54`), Pentair (`energy_pool.py:42-48`) | Enumeration gains rows 18-21 (Enpower) with existing CONFs reused; §"Verdict for integration-canonical vs house-named" classifies cloud-oracle = KEEP (integration-canonical), Generac serial = CLEANSE (house-named), Pentair = CLEANSE. Acceptance grep extended. | Enumeration §; new §"Integration-canonical vs cleanse verdict"; D1/D2; D5 acceptance grep. |
| R2 | HIGH | Rev 1 proposed `_dp_house_load_kw` return `None` → crashes `float()` at `energy_drain_precedence.py:563` and `<= 0.0` gate at `:673` | Keep returning `0.0`. The existing `house_load_kw <= 0.0 → DP_REASON_MISSING_INPUTS` abstain path is the discharge; the health sensor + IR issue is the operator-visible surface. Row 16 updated. | Enumeration row 16-17; D4 TRUST-tier rules. |
| R3 | HIGH | Rev 1 D3 pinned on live `hass.states.get()` → transient-dead legacy entity never pinned | Pin on **entity-registry presence** via `er.async_get(hass).async_get(literal)`. Live state is irrelevant. | D3 steps 2-3; tests. |
| R4 | MED | D4 abstention on `unavailable` would change this house's behaviour | D4 abstains only on `not_configured` / `dead_default`. `unavailable` is **report-only**. | D4 TRUST-tier abstention rule table; non-goals. |
| R5 | MED | `l1_charger_active` at `energy.py:11578` imports the module constant directly | Switched to the configured `smart_plug_entities` list. | D2 item 3; tests. |
| R6 | MED | Migration write via `async_update_entry` would trigger a CM reload | Add every new CONF key + migration flags to `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:6435`). | D3 step 4. |
| R7a | LOW | Grep discriminator catches comment/doctest hits | Scope to string literals + scrub comments. | D5 acceptance grep. |
| R7b | LOW | `garage_a` / `garage_b` are the EVSE-config DICT KEYS | Non-goals. | Non-goals. |
| R7c | LOW | 24h JSONL capture is soak-shaped | One-shot resolved-map dump pre/post. | D3 proof-of-byte-identity. |
| R7d | LOW | Grace-ticks knob had no clear discharge | Counter latches at `fired`; clears on return to `ok`. | D4; knob ladder. |
| R8 | — | Open questions | DP-scoped `R1/R2` names (**Rev 4 updates:** final name `_HOUSE_MAINS_R1/R2_POWER_ENTITY`); ship before 2nd install's next upgrade. | Open questions. |

---

## Rev 2 — content preserved (defaults cleanse — all of this still ships in Build A)

Rev 2 falsifiable invariant, institutional-context-verified, integration-canonical vs cleanse verdict, and 27-row TRUST-tier enumeration are preserved unchanged. **Deliverables (Rev 2 D1-D5) re-labelled under Build A** per Rev 3 and refined by Rev 4 (`CONF_ENERGY_ENVOY_ENTITY` not renamed; the two URA entity_ids not renamed).

Non-goals (Rev 2 preserved; Rev 3 additions preserved; **Rev 4 additions**):
- (Rev 4) Not renaming `CONF_ENERGY_ENVOY_ENTITY` in Build A (owned by Phase 2).
- (Rev 4) Not renaming the two URA entity_ids in Build A (Card B default NO).
- (Rev 4) Not renaming the display attribute keys `solcast_today / _remaining / _tomorrow` in Build A (dashboard + PWA consumers confirmed).
- (Rev 4) Not using `unit_of_measurement:` as a selector filter (HA doesn't support it).

Knob ladder (Rev 2 preserved): CONF keys → rung 2; `ec_entity_health_unavailable_grace_ticks` → rung 1 with discharge rule; migration flags → bookkeeping.

---

## Open questions (Rev 3, preserved and consolidated into Rev 4 above)

1. 2nd install timing — ship before next upgrade.
2. `_HOUSE_MAINS_R1/R2_POWER_ENTITY` names — locked (Rev 4).
3. `CONF_ENERGY_ENVOY_ENTITY` role — Phase 2 (Rev 4 R4-3).
4. Phase 2 kickoff gating — contingent on Build A live-validation + 2nd install readiness.

---

## Rev 1 review findings — archive (preserved per operator directive)

The Rev 1 plan proposed:

- (Rev 1 D1-D2) cleanse of EVSE/L1/solar-follow/weather/SPAN-mains defaults only; did not list Enpower rows 18-21, Generac row 22, or Pentair rows 23-27. → Fixed in Rev 2 R1.
- (Rev 1 D2.4) `_dp_house_load_kw` returning `None` → would crash `float()` at `energy_drain_precedence.py:563` and the `<= 0.0` gate at `:673`. → Fixed in Rev 2 R2.
- (Rev 1 D3.2) bootstrap pinned on `hass.states.get(literal) is not None` → registered-but-unavailable entity dropped. → Fixed in Rev 2 R3.
- (Rev 1 D4) abstention list included `unavailable`. → Fixed in Rev 2 R4.
- (Rev 1 D2) did not switch `l1_charger_active` to configured list. → Fixed in Rev 2 R5.
- (Rev 1 D3.3) `async_update_entry` in setup would trigger a CM reload storm. → Fixed in Rev 2 R6.
- (Rev 1 D5 acceptance grep) matched comment/doctest hits. → Fixed in Rev 2 R7a.
- (Rev 1 non-goals) didn't say `garage_a` / `garage_b` dict keys stay. → Fixed in Rev 2 R7b.
- (Rev 1 D3 proof-of-byte-identity) 24h JSONL capture = soak-shaped. → Fixed in Rev 2 R7c.
- (Rev 1 knob ladder) grace-ticks knob lacked a discharge rule. → Fixed in Rev 2 R7d.
- (Rev 1 open questions) two were still open. → Fixed in Rev 2 R8.
