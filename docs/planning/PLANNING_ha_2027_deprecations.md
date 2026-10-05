# PLANNING — HA 2027 deprecation sweep (URA)

**Card:** `HA-2027-DEPRECATIONS-URA-1` (status `waiting_operator`, Tier-1 tag — this plan
recommends re-tiering: see §Tier recommendation).
**Date:** 2026-10-05. **Author:** ura-planner. **Scope:** retire four HA deprecations URA
hits before their removal versions, with the device-registry half parked behind the test-harness
pin and the `show_advanced_options` half gated on a UX PICK from the operator.
**Do not commit this doc.**

Companion reading (MANDATORY, both read for this plan):
- `docs/architecture/DEVICE_TREE.md` — the two independent axes (ownership vs `via_device`
  nesting), **same-identifier hazard** (§3 bullet 2), the `_GROUPING_NODE_IDS` carve-out, the
  v5.94.1 shell-cleanup guard.
- `docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md` — eight mistakes made in v5.92.3→v5.94.1,
  especially mistake #4 (`async_get_device(identifiers=…)` is unsafe when identifiers duplicate,
  which is **precisely** what HA's 2027.8 removal is motivated by) and #9 (identifier-tuple
  unpacking: `len>=2`, do not assume 2-tuples when iterating the whole registry).

---

## Institutional context verified

### Design docs / architecture read
- `docs/architecture/DEVICE_TREE.md` (full) — the two-axis rule and INV-DEFRAG / INV-NEST /
  shell-cleanup guard. New-API migration MUST preserve these.
- `docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md` (full) — anchors the same-identifier
  invariant and the "iterate `dev_reg.devices.values()`; select by `device.id`; prefer
  populated/CM-owned" doctrine used at `_devices.py:267 / 345 / 438 / 607` and
  `__init__.py:4786`. The new HA API (`async_get_device_by_identifier`) is NOT a drop-in for
  these sites — they are deliberately iterating because identifier→device is non-unique.

### Prior-art scan (grep + card body) — REUSE vs NEW per piece
| Piece | REUSE / NEW | Evidence |
|---|---|---|
| Iterate-and-select-by-id doctrine | **REUSE** | `_devices.py:267, 345, 438, 607`, `__init__.py:4786, 4864` already do it; `_devices.py:238` carries the comment "never `async_get_device`". |
| Shell-cleanup guard (v5.94.1) | **REUSE** | `_devices.py:async_cleanup_parent_entry_shells` + survivor re-index — do not alter semantics; migration is API-surface only. |
| Grouping-node exemption `_GROUPING_NODE_IDS` | **REUSE** | `_devices.py` — any new iteration must still skip these. |
| `advanced_hint` / `advanced_hint_for` helpers | **REUSE** | `config_flow.py:63, 93` — already drive the "hidden tier" presentation; replacement UX must either retire them (option C) or rewire them (A/B). |
| `sections` form grouping (HA 2024.11+) | **NEW to URA** | not currently used; required by option A. Verify selector/section schema in HA source before building (`homeassistant/data_entry_flow.py` + frontend `voluptuous_serialize`). |
| URA `switch` platform (for a show-advanced toggle) | **REUSE** | `switch.py` already hosts options-flow-driven switches; option B adds one more. |
| Quarterly sweep procedure | **NEW** | no existing cadence doc; operator ruled "no programmatic trip-wire" (card `next`). |

### Prior planning / audit docs consulted
- `docs/planning/PLANNING_onboarding_simplify_phase2.md` — INV-C + §:29/:156 add **more** fields
  behind the HA Advanced-mode flag that this cycle removes. This plan's UX PICK must land
  **before** phase-2 builds or phase-2 builds against a dead mechanism.
- `docs/planning/PLANNING_device_entity_architecture_2026_9.md`,
  `docs/planning/DECISION_LOG_device_entity_cycle_2026_09_03.md` — anchor INV-DEFRAG / INV-NEST
  and the same-identifier doctrine.

### Memory bodies pulled
- `project_incident_v5_8_0_setup_recursion`, `project_envoy_boot_incident_2026_06_12` — reload /
  boot-order precedents; relevant because the migration changes device-registry read patterns
  during setup.
- `feedback_no_fabrication`, `feedback_verify_claim_types_not_felt_uncertainty` — the HA source
  check in §Verification is non-skippable; we do not describe `async_get_device_by_identifier`
  semantics from a mental model.
- `project_single_user_no_backcompat` — rolling to Wigton (2nd home) 2026-10-03/04 is live;
  Wigton surfaced two of the four deprecations. Degrade gracefully across HA versions.
- `feedback_tier2plus_prior_art_scan` — this section exists because of it.

### Code locations surveyed (end-to-end, this session)
- `custom_components/universal_room_automation/__init__.py` around 1055, 1061, 1092, 4777–4864
- `custom_components/universal_room_automation/entity.py:80`
- `custom_components/universal_room_automation/config_flow.py:63, 93, 1138, 4465, 4500,
  10336, 11503, 12974–12978`
- `custom_components/universal_room_automation/_devices.py:238, 267, 319, 341, 345, 438, 607`
- `custom_components/universal_room_automation/button.py:302`

Grep confirms every site in the card body. No additional `async_get_device(` or
`.devices.values()` or `show_advanced_options` reference exists in URA code.

---

## Deprecations in scope

| # | Deprecation | Removal | Severity | Sites (develop, grepped 2026-10-05) |
|---|---|---|---|---|
| 1 | `device_registry.async_get_device(identifiers=…)` — identifier index last-writer-wins, non-unique across config entries | **HA 2027.8** | hard failure | `__init__.py:1055, 1061, 1092, 4864`; `entity.py:80`; `config_flow.py:10336, 11503` — **7 sites** |
| 2 | `device_registry.devices` used as a mapping (`.values()`) | **HA 2027.9** | hard failure | `__init__.py:4786`; `button.py:302`; `_devices.py:267, 345, 438, 607` — **6 sites** |
| 3 | `show_advanced_options` on config/options flows | **HA 2027.6** | hard failure | `config_flow.py:1138, 4465, 4500, 12974–12978` + helpers `:63, :93` — **4 read-sites + 2 helpers** |
| 4 | `DeviceEntry.config_entries` (set) enforcement | **HA 2027.10** (dev-blog 2026-09-15) | hard failure | sweep deliverable (D4) — not yet enumerated; `_devices.py` + `__init__.py` cleanup paths most likely |

Also tracked by the sweep (not a URA code change, but checked each quarter): `configurator`,
`modbus get_hub`, `trusted_proxies` YAML (own card `HA-TRUSTED-PROXIES-UI-MIGRATION-1`).

---

## Falsifiable invariants

**INV-RESOLVE (Dep #1, #2).** For every call site migrated, the device the site operates on is
**the same `device.id`** before and after the change, under all three registry states:
(a) healthy single record, (b) same-identifier duplicate (shell + populated — the v5.94.1
state), (c) record absent. Observation: capture `device.id` from a pre-change run on a fixture
registry seeded with each state; the migrated code must return the same `device.id` (or `None`
for state c) at the same site. If any site resolves to a **different** `device.id` under (b)
than the current code's "iterate+prefer populated/CM-owned" choice, that is a RED.

**INV-FORM (Dep #3).** For every options/config-flow step currently gated by
`show_advanced_options`, after migration the same set of fields is **reachable** (not
necessarily visible by default) and submits the same validated schema. Observation:
`async_step_*` with `user_input` populated for every advanced field returns the same final
`CONF_*` dict as the pre-migration flow. The visibility default is a UX choice (A/B/C).

**INV-NEST, INV-DEFRAG preserved.** The migration MUST NOT change device-tree ownership or
nesting. Spot-checked by the existing architecture tests
(`quality/tests/test_device_entity_architecture.py`,
`test_device_entity_cm_hosted_behavioural.py`) plus a new live-registry oracle
(§Acceptance D1-live).

---

## Deliverables

### D1 — Dep #1 migration (`async_get_device(identifiers=…)` → new API), **PARKED**

**Status: PARK until test harness has the new API** (card gate_2026_10_05 ruling). The local
`.venv-ha` is HA 2026.2.3; `pytest-homeassistant-custom-component`'s `device_registry.py` at
`:797` exposes only `async_get_device` — no `async_get_device_by_identifier`,
`async_get_device_by_connection`, or `async_get_devices`. Shipping getattr-shim code whose
new-API branch cannot be exercised in-suite would put untested code on exactly the surface
that produced 8 past mistakes (DEVICE_ENTITY_DEFRAG_POSTMORTEM). PARK revival trigger: the
harness pin reaches an HA whose `device_registry.py` defines
`async_get_device_by_identifier`, **or** 2027-04-01 (whichever first). Tracked by
`TEST-HARNESS-REAL-HA-DEFAULT-1`.

**Verification step (one-shot, do before unparking):** on the live main-house HA 2026.9.4,
```
ssh ha "sudo -n docker exec homeassistant sed -n 1960,2200p \
    /usr/src/homeassistant/homeassistant/helpers/device_registry.py"
# also:
ssh ha "sudo -n docker exec homeassistant sed -n 1500,1600p \
    /usr/src/homeassistant/homeassistant/helpers/device_registry.py"
```
Record in this doc:
- exact signature of `async_get_device_by_identifier` (positional vs keyword, return type on
  miss, whether it accepts a single tuple or a set),
- exact signature of `async_get_device_by_connection`,
- exact signature of `async_get_devices` (filter params, including `config_entry_id` if any),
- the `DeviceRegistryItems.__iter__` behaviour (what it yields — `DeviceEntry` vs `device_id`),
- any composite-device / sub-entry semantics that differ from today's identifier lookup.

**Per-site migration table (fill in after the HA-source read — this is the planning skeleton,
not a spec):**

| Site | Today | Registry-state risk | Candidate new API | Notes |
|---|---|---|---|---|
| `__init__.py:1055` ZM device | `async_get_device(identifiers={(DOMAIN,"zone_manager")})` | ZM is CM/ZM-owned, single identifier; duplicate improbable but possible after a bad migration | `async_get_device_by_identifier((DOMAIN,"zone_manager"))` candidate; verify miss-return | setup-time read; must still return `None` on miss |
| `__init__.py:1061` zone device | per-zone identifier `(DOMAIN,f"zone_{name}")` | identifier technically unique; a renamed zone can leave an orphan — check `async_get_device_by_identifier` against two records sharing the key | same as above | this site is already defensive upstream (zone-slug orphan cleanup at ~:4066; see postmortem Open/carded) |
| `__init__.py:1092` CM device | `(DOMAIN,"coordinator_manager")` | **same-identifier hazard documented** — v5.94.1 shipped specifically because this duplicated | **must iterate + prefer populated/CM-owned**, NOT identifier lookup | this is a mistake-#4 site; migrating it to `async_get_device_by_identifier` would reintroduce the bug HA deprecated the old API for. Correct migration: fold into the `_devices.py:345` iterate pattern or hand-pick survivor. |
| `__init__.py:4864` target device | identifier lookup inside a cleanup/stamp loop | duplicates possible mid-cleanup | iterate `async_get_devices` / registry items + filter | needs the full HA signature to decide |
| `entity.py:80` DeviceInfo bootstrap | `(DOMAIN, entry_id)` — entry-scoped, unique | low | `async_get_device_by_identifier` likely safe | hot path during entity add — confirm no sync-vs-async change |
| `config_flow.py:10336` old-device lookup during migration | identifier lookup | duplicates possible if a prior migration partially ran | iterate + select-by-id | config-flow path — careful with sync context |
| `config_flow.py:11503` dev lookup | identifier lookup | low; verify | `async_get_device_by_identifier` candidate | — |

**Rule of thumb (anchored to DEVICE_TREE §3 bullet 2 and postmortem mistake #4):** sites that
look up a **shared-identifier device** (CM, coordinator identifiers, parent shells) migrate to
**iterate**, not to `async_get_device_by_identifier`. Sites that look up an **entry-scoped
identifier** (`(DOMAIN, entry_id)`) can migrate to the new by-identifier helper. The
per-site table above encodes that distinction; the final column is set after reading HA
source.

### D2 — Dep #2 migration (`.devices.values()` → iterate `dev_reg.devices` directly)

The six sites already do the right **thing** (snapshot the registry, iterate, select by id);
the deprecation is only about the `Mapping` API. Fix shape:
```python
# today
for device in list(dev_reg.devices.values()):
    ...
# after (verify against HA source — see §Verification)
for device in list(dev_reg.devices):   # if __iter__ yields DeviceEntry
    ...
# or
for device_id, device in list(dev_reg.devices.items_as_entries()):   # if the API chose that
    ...
```
`list(...)` wrapper stays — the "snapshot during iteration" doctrine is independent of the
deprecation. Buildable in-suite only if the local `.venv-ha` DeviceRegistryItems view supports
the new iteration shape; if not, this is PARKED on the same harness trigger as D1 (likely).

### D3 — Dep #3 migration (`show_advanced_options`): operator PICK required

Three options surfaced to the operator (card `next`):
- **A — collapsible Advanced `sections` in each form (planner recommendation).** Follows HA
  guidance. Fields stay in the schema; the renderer hides them under a collapsible section
  with an "Advanced" label. No profile-wide switch. Phase-2 onboarding plan uses the same
  mechanism — collapsible sections for its new fields — no second migration.
- **B — one URA-owned "Show advanced settings" switch** in integration options. All current
  `show_advanced_options`-reads route through this knob. Preserves today's semantics; adds a
  URA knob where HA used to carry the account-level flag.
- **C — drop the hidden tier; show everything.** Simplest; loses the discoverability curve
  Phase-2 is explicitly building.

Build scope (same regardless of option):
1. Replace the four reads (`config_flow.py:1138, 4465, 4500, 12974–12978`) with the chosen
   mechanism. Option A: delete `show_advanced_options` reads entirely; wrap advanced fields
   in `vol.Schema({vol.Required("advanced", default=False): section(..., {"collapsed": True})})`
   (verify exact HA shape before building). Option B: new `CONF_URA_SHOW_ADVANCED` bool,
   switch entity, options-flow field, read in the four sites. Option C: inline the advanced
   fields in each step unconditionally; delete the helpers at `config_flow.py:63, 93`.
2. Rework `advanced_hint` / `advanced_hint_for` (`:63`, `:93`) to match the choice.
3. Update `PLANNING_onboarding_simplify_phase2.md` INV-C before phase-2 builds.

**Config-first check (CLAUDE.md "Config-First"):** the operator question "A/B/C" IS the config
decision — not a code decision. No code change is proposed until A/B/C is picked.

### D4 — Sweep for other HA 2026.9.4+ deprecations URA could hit

One-shot read-only probe (fits "Measure Before You Build"):
```
ssh ha "sudo -n docker exec homeassistant \
    grep -RIn --include='*.py' 'report_usage' /usr/src/homeassistant/homeassistant \
    | grep -E 'breaks_in_ha_version|removed_in_ha_version'" > scratchpad/ha_report_usage.txt
```
Then cross-grep each matching surface against URA imports:
```
grep -E 'from homeassistant\.[a-z_.]+ import|homeassistant\.[a-z_.]+\.' \
    -rn custom_components/universal_room_automation
```
Specifically enumerate: `DeviceEntry.config_entries` writers (dev-blog 2026-09-15, removal
2027.10) — URA does **not** write to `device.config_entries` directly today (grep: 0 hits),
but any `async_update_device(add_config_entry_id=…)` / `remove_config_entry_id=…` and the
`async_cleanup_parent_entry_shells` path must be re-verified against the new enforcement.

Deliverable: a short appendix table (deprecation, removal version, URA sites or "none"),
appended to this doc, becomes the baseline for the quarterly sweep.

### D5 — Quarterly deprecation sweep procedure (operator ruling: no programmatic trip-wire)

Added to `WORKFLOW_GUIDE.md` and the operator session-start checklist:

1. **Cadence:** first Monday of Jan / Apr / Jul / Oct, and on every HA minor upgrade (release
   day).
2. **Restart-time log capture, both homes.** Deprecation warnings log at import/setup, which
   is **outside** the 2000-line error_log window — so capture them from docker directly, not
   from `system_log`:
   ```
   # main house
   ssh ha "sudo -n docker logs homeassistant --since 10m 2>&1 \
       | grep -iE 'deprecat|will be removed|breaks_in_ha_version' \
       | grep -i 'universal_room_automation'" \
       > scratchpad/depr_main_$(date +%F).txt
   # wigton — ask operator for a one-shot token; same command, same filter.
   ```
   Trigger a controlled restart: `ssh ha "ha core restart"` (or scheduled quarterly restart).
3. **Code grep for the deprecated APIs HA announced that quarter.** Pull the list from the HA
   release notes / dev-blog; grep URA for each symbol.
4. **Card any new finding** as `HA-20YY-DEPRECATIONS-URA-N` with the deprecation name, removal
   version, URA sites, and gate (harness? UX pick? pure code?). File under `thread: platform`,
   tag `multi-home`.
5. **Record completion** in a one-line note on this plan doc (`sweep_YYYY_MM`) OR in the card
   body — never a calendar-only reminder (anti-"soak watching").

---

## Acceptance criteria

### D1 (unparked)
- **Test:** `test_async_get_device_migration_same_identifier` — fake registry with (populated
  CM, empty CM shell) at `(DOMAIN,"coordinator_manager")`; migrated `__init__.py:1092` and
  equivalents resolve to the populated/CM-owned `device.id`, matching pre-migration behavior.
- **Test:** `test_async_get_device_migration_entry_scoped` — fake registry with a single
  entry-scoped identifier; `entity.py:80` + `config_flow.py:11503` resolve to the same
  `device.id` as the pre-migration code.
- **Test:** `test_identifier_tuple_3elem_safe` — fake registry including a 3-element identifier
  (`bond`-style) — migration code does not raise `ValueError` (postmortem mistake #9).
- **Live (D1-live):** on both homes, `ha_get_device(identifier=f"{DOMAIN}.coordinator_manager")`
  returns exactly ONE device, nested under Whole House via CM; INV-DEFRAG + INV-NEST
  unchanged. Deprecation warning for `async_get_device` **absent** from the next restart's
  docker log.

### D2
- **Test:** behavioural tests at `_devices.py:267, 345, 438, 607` reuse the existing
  `_FakeDevReg` harness; migrated iteration yields the same device set as `.values()` under
  (a) healthy, (b) same-identifier-duplicate, (c) 3-element-identifier mixed registry.
- **Live:** docker log on next restart contains no `devices` mapping deprecation line for
  `universal_room_automation`.

### D3 (depends on A/B/C)
- **Test:** for each `async_step_*` currently gated by `show_advanced_options`, posting a
  user_input dict containing every advanced field produces the same final `CONF_*` dict as
  the pre-migration flow (INV-FORM).
- **Test (option A only):** schema serialization exposes a `section` named `advanced`
  containing exactly the fields currently guarded.
- **Live:** no `show_advanced_options` deprecation line in the next restart's docker log; the
  options flow renders as the operator picked.

### D4
- The appendix table lists every URA-touched deprecation in HA 2026.9.4 with removal ≥2027.6
  and a disposition (migrate / park / N-A).

### D5
- `WORKFLOW_GUIDE.md` carries the sweep procedure; the current session's sweep completion is
  recorded on the card.

---

## Test approach given the older `.venv-ha` (HA 2026.2.3)

**The problem.** The pinned harness lacks `async_get_device_by_identifier`,
`async_get_device_by_connection`, `async_get_devices`, and may lack the new
`DeviceRegistryItems.__iter__` shape. Tests imported from `pytest-homeassistant-custom-component`
run against *this* registry — so any code that unconditionally calls the new APIs will
`AttributeError` in the suite.

**Options considered:**
1. **getattr shim** (`if hasattr(dev_reg, "async_get_device_by_identifier"): …`): executable
   in-suite only on the OLD branch; the NEW branch ships untested. **Rejected** — mistake #4
   territory, matches the card gate ruling.
2. **Vendored `_FakeDevReg` upgrade:** extend the fakes to expose the new APIs with real
   semantics (same-identifier hazard, 3-tuple identifiers), and drive tests through the fake
   only. Pro: deterministic, exercises both branches. Con: fake authoring risk (hollow-anchor
   bug class) — the fake can diverge from HA.
3. **Harness bump** (TEST-HARNESS-REAL-HA-DEFAULT-1): the real fix. Everything else is a
   workaround.

**Recommendation:** D1 and D2 **PARK on option 3** (harness bump) — do not ship shims. When
the harness bump completes, build D1/D2 straight against the new APIs, and keep a
`_FakeDevReg` extension (option 2) in `quality/tests/` as an in-process fake for the
same-identifier and 3-tuple cases that the real HA registry does not easily seed.

D3 (`show_advanced_options`) is **not** harness-blocked — the flag is read directly on
`self`, and the migration is to form schema. Buildable today once A/B/C is picked.

D4 (sweep) is read-only; no harness constraint.

D5 (procedure) is documentation; no harness constraint.

---

## Non-goals

- Fixing `trusted_proxies` YAML — owned by `HA-TRUSTED-PROXIES-UI-MIGRATION-1`.
- Any device-tree re-architecture. The migration is API-surface only; INV-DEFRAG / INV-NEST
  stay bit-identical.
- Programmatic deprecation trip-wire (operator ruling — the quarterly sweep is the discipline).
- `configurator`, `modbus get_hub` removals — URA does not import these (grep: 0 hits).

---

## Tier recommendation

**TIER 2-DB** (framing-disjoint 3-review) for D1+D2 when they unpark, with elevation
justification that is a near-perfect fit for the standing operator policy
(`feedback_tier2db_for_regression_prone`):

1. **Shared primitive consumed by multiple coordinators.** `_devices.py` is read by every
   coordinator setup, every room/zone platform, and the config-flow migration path. INV-NEST
   depends on it.
2. **Trust-hierarchy ripple + "small surgical fix" risk.** The same-identifier hazard is
   exactly the class that produced 8 postmortem mistakes across v5.92.3→v5.94.1. A
   mechanical sed-style "replace `async_get_device(identifiers=…)` with
   `async_get_device_by_identifier`" at `__init__.py:1092` would **reintroduce** mistake #4
   silently.
3. **Three framings are needed because they cannot share blind spots.** Suggested axes:
   - A — API-surface correctness (every site's call shape matches the HA signatures read in
     §D1 Verification step; no `ValueError` on 3-tuple identifiers).
   - B — same-identifier / registry-state behavioural equivalence (every site returns the
     same `device.id` under states a/b/c — INV-RESOLVE); INV-DEFRAG / INV-NEST unchanged.
   - C — test authority (fakes include messy real-world shapes: duplicates, 3-tuple ids,
     grouping-node id; mutation drills per site; existing architecture tests still pass).
4. **Live-registry oracle** (D1-live, D2-live) is the acceptance step, matching the
   DEVICE_ENTITY_DEFRAG arc's "live-registry validation as the acceptance oracle" posture.

**TIER 1** for D3 (hotfix size, options-flow only) **IF option A or C** is chosen; **TIER 2**
if option B is chosen (new switch + persisted knob + options-flow write-back introduces a
small cross-platform surface worth a second framing).

**TIER 1** for D4 (sweep + appendix) and D5 (procedure).

The card today carries `tags: [tier-1, multi-home]`. This plan recommends **re-tagging** to
`tier-2db` on D1/D2 and `tier-1` (or `tier-2` under option B) on D3, with D4/D5 as tier-1
documentation deliverables. Operator confirms at the UX PICK gate.

---

## Open PICKs for the operator (nothing is built until these resolve)

1. **UX for hidden tier** (D3): A / B / C.
2. **D1/D2 park policy:** confirm 2027-04-01 fallback revival date and the harness-bump
   trigger owner (`TEST-HARNESS-REAL-HA-DEFAULT-1`).
3. **Tier re-tag:** approve `tier-2db` on D1/D2 per justification above.

---

## Summary

Four URA-touching HA deprecations, three removal windows (2027.6 / 2027.8 / 2027.9 /
2027.10). The device-registry half (D1 7 sites, D2 6 sites) is correctly PARKED on the
2026.2.3 test-harness pin — shipping getattr shims to the device tree would land untested
code on the exact surface responsible for 8 past mistakes. The `show_advanced_options` half
(D3, 4 reads + 2 helpers) is UX-gated on an A/B/C PICK from the operator and must land
before onboarding phase-2 builds against the dying mechanism. A one-shot HA-source sweep
(D4) catches any adjacent deprecations URA could hit, and a quarterly restart-time
docker-log + grep procedure (D5) replaces the rejected programmatic trip-wire. Tier
recommendation: **Tier 2-DB on D1/D2** (shared device-tree primitive, same-identifier
hazard, cross-coordinator ripple), **Tier 1 on D3/A·C**, **Tier 2 on D3/B**, Tier 1 on D4/D5.
