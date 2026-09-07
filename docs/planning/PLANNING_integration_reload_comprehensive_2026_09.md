# PLANNING — Comprehensive Elimination of the Integration-Entry Reload Outage

**Status:** DOCS-ONLY plan, rev-2 (2026-09-06). Two plan-review passes returned FIX-REQUIRED; corrections applied below. Awaiting operator go on build.
**Version:** unassigned (per `feedback_versioning_convention`).
**Tier:** **Tier 3** — delicate shared-primitive change (lifecycle listener + cross-coordinator discharge signals + potential structural migration). Operator-elevated: the failure mode is a full-house ~5-min outage; a missed cached consumer = silent stale-config drift across census/perimeter/presence. Four framing-disjoint reviews incl. adversarial completeness.
**Kanban card:** `INTEGRATION-RELOAD-COMPREHENSIVE-1` (to be added).
**Supersedes / extends:** `PLANNING_reload_watchdog_hazard.md` rev-2 (shipped v1, single-key allowlist + integration branch) — this cycle discharges its **four** parked follow-ups AND folds in the structural tier.

---

## Rev-2 amendments (binding — supersede any conflicting text below)

Two plan reviews (completeness + adversarial-build-prediction) returned FIX-REQUIRED. All findings verified against `develop` HEAD 2026-09-06 before amending. Where the amendments contradict the rev-1 body, the amendments win.

**A1. `CONF_ENHANCED_CENSUS` is UNSAFE-STRUCTURAL — do NOT admit.**
The rev-1 body cited `camera_census.py:4978-4983` as a fresh-read consumer and speculated the audit "verdict drifted." Re-grep this session found a **setup-time structural consumer** at `__init__.py:2363-2364`:
```python
enhanced = merged_config.get(CONF_ENHANCED_CENSUS, True)
if enhanced:
    async_track_state_change_event(...)  # registers the event-driven census listeners
```
The fresh-read at `camera_census.py:4978-4983` is real but is NOT the only consumer. A save that flips this key requires the listener set to be torn down or registered — a closure-captured unsub set that Tier-2 discharge cannot address without non-trivial listener teardown+re-register. Classification: **UNSAFE-STRUCTURAL** (falls through to reload; Tier-3 D3.a/D3.b bounds the cost). Every "verdict drifted" claim in rev-1 §D1.0 and the institutional-context table is struck.

**A2. Tier-1 D1.1 promote set (FINAL).** Extend `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` with:
- `CONF_CENSUS_CROSS_VALIDATION` — fresh-read `camera_census.py:2313-2323`.
- `CONF_CENSUS_BLE_CANCEL_ENABLED` — fresh-read `camera_census.py:4985-5004`.
- `CONF_KNOWN_FACE_GUESTS` — fresh-read `camera_census.py:3515-3521`.
- `CONF_EGRESS_IDENTITY_FAILSAFE_STRICT` — fresh-read `camera_census.py:3736-3744`. **MUST classify together with the already-allowlisted `CONF_EGRESS_IDENTITY_ENABLED`** (both are written by the same `camera_census` step; if one is allowlisted and the other isn't, a common save changes both → `issubset` fails → reload fires → the allowlist is defeated on the exact save it exists to suppress).
- `CONF_PERIMETER_ALERT_HOURS_START` and `CONF_PERIMETER_ALERT_HOURS_END` — ZERO consumers (grep hits only `const.py:1510-1511` and `config_flow.py:318-319, 3113-3126, 3141-3143` as retired-default fallbacks). Also stripped from options at save time (`config_flow.py:3113-3116`). Trivially SAFE + a three-bucket-triage supersession item (KEEP+DOCUMENT or DELETE after triage). Admitting to the allowlist is defensive belt-and-suspenders (protects against a future write-path that forgets the strip).

**Explicitly REMOVED from D1.1 vs rev-1:** `CONF_ENHANCED_CENSUS` (see A1).
**Explicitly OUT of scope this cycle:** `CONF_TRACKED_PERSONS` (A5), `CONF_ELECTRICITY_RATE` (A6) — cached-structural, card separately.

**A3. Complete integration-entry key classification (all ~43 keys, six steps).**
Enumeration bounded by each `async def async_step_*` at `config_flow.py:2707` (`global_sensors`), `:2758` (`energy_sensors`), `:2848` (`person_tracking`), `:7815` (`default_notifications`), `:2903` (`camera_census`), `:3096` (`perimeter_alerting`). Every key falls in exactly one bucket:

| Step | Key | Bucket | Cite / notes |
|---|---|---|---|
| global_sensors | `CONF_OUTSIDE_TEMP_SENSOR` | UNSAFE-STRUCTURAL | multiple sensor registrations |
| global_sensors | `CONF_OUTSIDE_HUMIDITY_SENSOR` | Tier-2 (probe) | verify consumers cached vs fresh at build time; probe-first per §D2 |
| global_sensors | `CONF_WEATHER_ENTITY` | UNSAFE-STRUCTURAL | provider re-registration |
| global_sensors | `CONF_SOLAR_PRODUCTION_SENSOR` | UNSAFE-STRUCTURAL | EC seed |
| global_sensors | `CONF_ELECTRICITY_RATE` | OUT OF SCOPE — card separately | ≥4 consumers (`coordinator.py:1276/1280`, `aggregation.py:111`, `sensor.py:112`, `__init__.py:4837`); needs its own producer/consumer table + wire-up. Do NOT admit this cycle. |
| energy_sensors | `CONF_WHOLE_HOUSE_POWER_SENSORS` | UNSAFE-STRUCTURAL | already known (rev-1 Tier-3 D3 list) |
| energy_sensors | `CONF_WHOLE_HOUSE_ENERGY_SENSORS` | UNSAFE-STRUCTURAL | peer of the above |
| energy_sensors | `CONF_HOUSE_DEVICE_POWER_SENSORS` | Tier-2 (probe) | probe consumer pattern; likely UNSAFE (sensor set) |
| energy_sensors | `CONF_HOUSE_DEVICE_ENERGY_SENSORS` | Tier-2 (probe) | probe consumer pattern |
| person_tracking | `CONF_TRACKED_PERSONS` | OUT OF SCOPE — card separately | cached at `person_coordinator.py:104` (`entry.data`-only, not merged options) + entity-creation consumers `switch.py:5782`, `sensor.py:502`. Do NOT admit; **remove `presence.py` from Files-touched below.** |
| person_tracking | `CONF_PERSON_DATA_RETENTION` | Tier-2 (probe) | DB pruner; may be fresh-read per pass |
| person_tracking | `CONF_TRANSITION_DETECTION_WINDOW` | Tier-2 (probe) | transition detector |
| default_notifications | `CONF_NOTIFY_SERVICE` | Tier-2 (probe D2.2) | NM cached-vs-fresh probe first |
| default_notifications | `CONF_NOTIFY_TARGET` | Tier-2 (probe D2.2) | same |
| default_notifications | `CONF_NOTIFY_LEVEL` | Tier-2 (probe D2.2) | same |
| camera_census | `CONF_CENSUS_CROSS_VALIDATION` | **Tier-1 D1.1 (SAFE)** | fresh-read `camera_census.py:2313-2323` |
| camera_census | `CONF_CAMERA_PERSON_ENTITIES` | ALREADY ALLOWLISTED (v1) | `__init__.py:6647`, discharge `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` |
| camera_census | `CONF_EGRESS_CAMERAS` | Tier-2 D2.1 (perimeter narrow re-read + transit rebuild) | camera-list; two cached consumers |
| camera_census | `CONF_PERIMETER_CAMERAS` | Tier-2 D2.1 | same |
| camera_census | `CONF_FACE_RECOGNITION_ENABLED` | ALREADY ALLOWLISTED (v1) | `__init__.py:6655`, discharge `SIGNAL_URA_FACE_RECOGNITION_CHANGED` |
| camera_census | `CONF_ENHANCED_CENSUS` | **UNSAFE-STRUCTURAL** | see A1 — setup consumer `__init__.py:2363-2364` |
| camera_census | `CONF_EGRESS_IDENTITY_ENABLED` | ALREADY ALLOWLISTED (v1) | `__init__.py:6662` |
| camera_census | `CONF_KNOWN_FACE_GUESTS` | **Tier-1 D1.1 (SAFE)** | fresh-read `camera_census.py:3515-3521` |
| camera_census | `CONF_EGRESS_IDENTITY_FAILSAFE_STRICT` | **Tier-1 D1.1 (SAFE — pair with EGRESS_IDENTITY_ENABLED)** | fresh-read `camera_census.py:3736-3744`; MUST land together with the already-allowlisted `CONF_EGRESS_IDENTITY_ENABLED` or the issubset test defeats itself on any common save |
| camera_census | `CONF_GUEST_VLAN_SSID` | Tier-2 (probe) | grep consumers before promotion |
| camera_census | `CONF_CENSUS_HOLD_INTERIOR` | Tier-2 D2.3 (probe → likely fresh) | `_get_hold_seconds` referenced from `camera_census.py:4988` is fresh-read pattern — probe confirms |
| camera_census | `CONF_CENSUS_HOLD_EXTERIOR` | Tier-2 D2.3 | same |
| camera_census | `CONF_CENSUS_BLE_CANCEL_ENABLED` | **Tier-1 D1.1 (SAFE)** | fresh-read `camera_census.py:4985-5004` |
| camera_census | `CONF_CENSUS_DIVERGENCE_DOWNGRADE` | Tier-2 D2.3 (probe) | |
| camera_census | `CONF_AUTO_ENABLE_PERSON_DETECTION` | Tier-2 (probe) | |
| perimeter_alerting | `CONF_PERIMETER_VEHICLE_HOURS_START` | Tier-2 D2.1 (narrow re-read) | cached in perimeter manager |
| perimeter_alerting | `CONF_PERIMETER_VEHICLE_HOURS_END` | Tier-2 D2.1 | same |
| perimeter_alerting | `CONF_PERIMETER_ENRICHMENT_ENABLED` | Tier-2 D2.1 | enrichment defaults cached |
| perimeter_alerting | `CONF_PERIMETER_ENRICHMENT_PROVIDER` | Tier-2 D2.1 | |
| perimeter_alerting | `CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS` | Tier-2 D2.1 | |
| perimeter_alerting | `CONF_PERIMETER_ENRICHMENT_MODEL` | Tier-2 D2.1 | |
| perimeter_alerting | `CONF_PERIMETER_ENRICHMENT_MAX_TOKENS` | Tier-2 D2.1 | |
| perimeter_alerting | `CONF_PERIMETER_ENRICHMENT_PROVIDER_ID` | Tier-2 D2.1 | |
| perimeter_alerting | `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` | Tier-2 D2.1 | cached `_snapshot_offset_s` |
| perimeter_alerting | `CONF_PERIMETER_ALERT_HOURS_START` | **Tier-1 D1.1 (SAFE — zero consumers, retired)** | grep finds only const/config_flow default fallbacks; stripped at save (`config_flow.py:3113-3116`); admit as defense-in-depth + supersession candidate (KEEP+DOCUMENT / DELETE after three-bucket triage) |
| perimeter_alerting | `CONF_PERIMETER_ALERT_HOURS_END` | **Tier-1 D1.1 (SAFE — zero consumers, retired)** | same |
| perimeter_alerting | `CONF_PERIMETER_ALERT_NOTIFY_SERVICE` | RETIRED — stripped at save + deprecation ERROR `perimeter_alert.py:400-407` | non-goal; do NOT admit; supersession DELETE candidate after grep of any residual writers |
| perimeter_alerting | `CONF_PERIMETER_ALERT_NOTIFY_TARGET` | RETIRED | same |

**A4. D2.1 = narrow re-read, NOT teardown+rebuild.** The rev-1 §D2.1 wording ("subscribe … tear down cached … and rebuild") implied a `async_teardown()+async_setup()`. That is **unsafe** on `PerimeterAlertManager`: an `async_setup()` rebuild resets `self._setup_time = dt_util.now()` at `perimeter_alert.py:967`, which gates four alert paths against `PERIMETER_BOOT_SETTLE_S`:
- animal path (`:899-904`)
- vehicle path (~`:2618`)
- perimeter path (~`:3760`)
- egress path (~`:3760`)

A config-change rebuild would silently disarm the perimeter alarm for the settle window — a security-affecting regression the reload path never causes (fresh boot legitimately settles). It would also clear `_pending_dispatches` / `_dispatch_in_flight`, cancel in-flight edge-capture tasks, and lose the once-only `_unsub_started` sibling rescan.

The correct shape is a **narrow re-read handler** that mutates ONLY the cached-config fields, PRESERVING lifecycle state:
- **REBUILD (from `entry.options`):** `_sensor_platforms`, `_sensor_to_camera`, perimeter sensor set + its state subscriptions, egress sensor set + its state subscriptions, vehicle-hours ints, enrichment default dict, `_snapshot_offset_s`.
- **PRESERVE (do NOT touch):** `_setup_time`, `_active`, `_pending_dispatches`, `_dispatch_in_flight`, in-flight edge-capture asyncio Tasks, `_unsub_started`, snapshot-sweep listener unsub.

Acceptance criterion (added): `::test_perimeter_config_change_preserves_boot_settle_window` — dispatch `SIGNAL_URA_PERIMETER_CONFIG_CHANGED`, then attempt an animal/vehicle/perimeter/egress trigger within `PERIMETER_BOOT_SETTLE_S` of the ORIGINAL setup, assert the alert is NOT suppressed (i.e. `_setup_time` was NOT reset). Mutation drill: introduce `self._setup_time = dt_util.now()` into the handler, assert this test fails BY NAME, restore.

D2.1 covers **all 13 keys written by the perimeter step (rebuild-relevant, non-retired)** — see A3 (9 perimeter-step keys) plus the 4 camera-list keys shared with `camera_census` step (`CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` — perimeter also caches these) — so the issubset test isn't defeated by an unclassified sibling. `CONF_PERIMETER_ALERT_HOURS_START/END` ride the D1.1 fresh-read path (they have zero consumers); the retired notify keys are non-goal.

**A5. `CONF_TRACKED_PERSONS` → OUT OF SCOPE this cycle.** Cached consumer at `person_coordinator.py:104` reads `integration_entry.data` ONLY (not merged options). Additional entity-creation consumers at `switch.py:5782` and `sensor.py:502`. A discharge signal alone will not solve this — the cache reads the wrong dict. Card separately as `INTEGRATION-TRACKED-PERSONS-DISCHARGE-1`. **Remove `custom_components/universal_room_automation/domain_coordinators/presence.py` from the Files-touched list** below.

**A6. `CONF_ELECTRICITY_RATE` → OUT OF SCOPE this cycle.** ≥4 consumers (`coordinator.py:1276`, `coordinator.py:1280`, `aggregation.py:111`, `sensor.py:112`, `__init__.py:4837`). Either give it a full per-key producer/consumer table + wire-up plan or drop it — rev-2 drops it. Card separately.

**A7. MED — success-gated snapshot advance.** `_dispatch_integration_key_signals` swallows dispatch exceptions (`__init__.py:6708-6716`) and the suppress branch at `__init__.py:7383-7395` advances the snapshot **unconditionally** at `:7394` (`snapshots[entry.entry_id] = dict(new)`). At Tier-2 scale (cached consumers, no next-tick re-read) a swallowed dispatch = **PERMANENT loss** (snapshot advances → the key is no longer in `changed_keys` at the next save → the cached consumer stays stale forever).

**Deliverable added (Tier 2 scope, ride D2 landing):** advance the snapshot only for keys whose dispatch succeeded. Track a `dispatched_ok: set[str]` from `_dispatch_integration_key_signals` (or return it); at `:7394` write `snapshots[entry.entry_id] = {**old, **{k: new[k] for k in dispatched_ok}}` so failed-dispatch keys remain in the diff next save. Alternatively, if the operator explicitly accepts the loss (fresh-read-only allowlist), record it as a Review-B accepted risk. Rev-2 recommends the fix.

**A8. Per-key wiring TABLE replaces D2.1-2.4 prose.** Every promoted/wired key gets a row in a single table (committed BEFORE code per D2 fixture rule):

| key | discharge signal | subscribe file:line | unsub field name | teardown call site | re-read scope (fields written) | `_INTEGRATION_KEY_SIGNAL_TABLE` row | restart-seed covered? |
|---|---|---|---|---|---|---|---|

Columns MUST be filled per key before build (blank = the plan is not ready for that key). Resolve the rev-1 D2.3 "`__init__` vs `async_setup`" ambiguity by pinning subscribe to **`async_setup`** across the board (mirrors `transit_validator.py:347-366`; keeps subscribe symmetric with teardown at `:899-904`). Require an **unsub-field-init-to-None** leg (mirrors `transit_validator.py:264`) AND a mutation drill: removing the unsub field OR the teardown call MUST turn a specific test RED.

**A9. Parked follow-ups: FOUR, not three.** `PLANNING_reload_watchdog_hazard.md` has four parked follow-ups (verify at plan-refresh time). This cycle discharges them on **OPERATOR-DIRECTIVE scope grounds** (operator requested comprehensive fixing on 2026-09-06), NOT on any fabricated evidence trigger. Recorded here so a future reviewer does not look for trigger events that were never observed.

**A10. D3.a — plan-refresh precondition.** `PLANNING_config_subentries_migration.md` is baselined at v4.7.19; production is now v5.90.x. Its `config_flow.py` / `__init__.py` cites have drifted. **Precondition on any D3.a build:** refresh that plan's cites against `develop` HEAD in a separate pass BEFORE the D3.a build dispatch. Keep D3.a gated on operator sign-off.

**A11. Drifted citation corrections applied throughout.**
- Integration options menu: `config_flow.py:2616-2632` (was `:2598-2615`).
- Allowlist constant: `__init__.py:6646-6664` (was `:6646-6663`; range grew when v1 added FACE + EGRESS keys).
- Suppress-branch test: `__init__.py:7383-7384` (was `:7383-7385`) — kill switch + `issubset` guard.
- Fall-through reload: `__init__.py:7404-7416` unchanged.
- Subscribe/teardown template: **three-part** cite — `transit_validator.py:347-366` (`async_dispatcher_connect` at `:359-361`) + `:264` (`self._config_signal_unsub = None` field init) + `:899-904` (teardown unsub call). NOT `:309-335` (that's the `EVENT_ENTITY_REGISTRY_UPDATED` listener, a different pattern).
- Reviewer-D instruction must cite the corrected menu + template + allowlist locations (see §Tier-3 review below).

---

**Central problem.** Any options-save on the URA integration (parent) entry that changes even one non-allowlisted key still falls through to `hass.config_entries.async_reload(entry.entry_id)` (`__init__.py:7404-7416`). Because the integration entry owns 80 entities + the singleton bootstrap, that reload cascades to every child entry (~40) and stalls the event loop until the supervisor watchdog restarts core (~5 min house outage — 2026-08-07 incident). The v1 cycle proved the mechanism works for one key; the fix is not comprehensive until every SAFE / cached-with-discharge key rides the suppress path and the unavoidable structural saves stop being loop-blocking.

---

## Falsifiable invariant (Tier-3)

> **On the URA integration (parent) entry, an options save whose changed key-set is a subset of `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` MUST cause ZERO `config_entries.async_reload` calls, ZERO entry unloads (parent OR child), ZERO event-loop tasks whose runtime exceeds ~200 ms, AND MUST leave NO consumer of a suppressed key retaining a cached view of the pre-save value at the next actionable tick.**
>
> **Corollary (Tier-3 addition):** an options save whose changed key-set is NOT a subset of the allowlist — i.e. a genuinely-structural change — MUST NOT stall the event loop long enough to trip the supervisor watchdog. This corollary is what Tier 3 (D3.x) exists to satisfy; Tier 1/2 satisfy the primary invariant.

Reviewer-D (adversarial-completeness) framing: state this invariant, re-enumerate EVERY integration-entry option key currently reachable from any options-flow step opened at `config_flow.py:2616-2632` (six steps: `global_sensors :2707`, `energy_sensors :2758`, `person_tracking :2848`, `default_notifications :7815`, `camera_census :2903`, `perimeter_alerting :3096`) against the post-cycle allowlist + discharge table (§A3), and attempt to construct a legal-config save that violates it (cached consumer left stale, reload fires under allowlist subset, structural save stalls loop >200ms). Every previously-unclassified key MUST appear in exactly one bucket in §A3.

---

## Institutional context verified (MANDATORY — Tier 2+ prior-art scan)

### REUSE-vs-BUILD verdict table

| Proposed piece | Verdict | Cite / justification |
|---|---|---|
| Integration-entry suppress branch in `_async_update_listener` | **REUSED** — already shipped v1 | `__init__.py:7367-7402`. Extend allowlist + wiring table only. |
| `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` frozenset | **REUSED** — extend membership | `__init__.py:6646-6664` (currently 3 keys). |
| `_INTEGRATION_KEY_SIGNAL_TABLE` | **REUSED** — extend rows | `__init__.py:6679-6688`. |
| `_dispatch_integration_key_signals` helper | **REUSED** as-is (except A7 success-gating tweak) | `__init__.py:6691-6716`. Iterates changed_keys × table; per-signal try/except; never re-raises. |
| `_seed_integration_last_applied_options` boot seed | **REUSED** as-is | `__init__.py:6732-6752`. |
| `INTEGRATION_RELOAD_SUPPRESS_ENABLED` kill switch | **REUSED** | `__init__.py:6670`. Fire-axe; rung-1 constant per numbers-get-knobs. |
| `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` | **REUSED** | `const.py:2014`; subscribed `transit_validator.py:359-361`. |
| `SIGNAL_URA_FACE_RECOGNITION_CHANGED` | **REUSED** | Already wired for `CONF_FACE_RECOGNITION_ENABLED` (`presence.py`, `transit_validator.py`). |
| Signal-subscribe + narrow re-read pattern in a cached consumer | **REUSED — copy verbatim (three-part template)** | `transit_validator.py:264` (unsub field init to None) + `:347-366` (`async_dispatcher_connect` in `async_init`) + `:899-904` (teardown unsub call). This is the template for Tier-2 narrow-re-read wire-ups (PerimeterAlertManager, NM). NOTE: rev-1 cited `:309-335` — that is the `EVENT_ENTITY_REGISTRY_UPDATED` listener, a DIFFERENT pattern. |
| Snapshot / reseed-on-fall-through discipline | **REUSED** | `__init__.py:7367-7402` (integration branch) mirrors CM branch. A7 addition: success-gated snapshot advance. |
| Per-key discharge audit + verdict fixture | **REUSED — refresh in place** | `docs/planning/AUDIT_integration_options_reload_classification.md`. Re-verify verdicts against current code (line numbers drifted; `CONF_ENHANCED_CENSUS` re-verified as UNSAFE-STRUCTURAL per §A1). |
| Structural: config subentries migration | **REUSED — plan exists but STALE cites (see A10)** | `docs/planning/PLANNING_config_subentries_migration.md` baselined at v4.7.19; refresh cites before D3.a build. |
| `NEW` signal `SIGNAL_URA_PERIMETER_CONFIG_CHANGED` | **NEW** (Tier 2, D2.1) | Grep across integration returns 0 hits. |
| `NEW` signal `SIGNAL_URA_NOTIFY_CONFIG_CHANGED` | **NEW** (Tier 2, D2.2) | Only if NM proves to hold cached defaults; probe first. |
| `NEW` signal `SIGNAL_URA_CENSUS_HOLD_CONFIG_CHANGED` | **NEW** (Tier 2, D2.3, conditional) | Only if probe shows genuinely cached. |
| Async / yielding integration `async_setup_entry` refactor | **NEW** (Tier 3, D3.b) | No equivalent primitive; largest surface. |

### Greps run + code locations surveyed (rev-2 additions)

- `__init__.py:2363-2364` — **CONF_ENHANCED_CENSUS setup-time consumer** (governs event-driven census listener registration). Confirmed rev-2. UNSAFE-STRUCTURAL.
- `camera_census.py:2313-2323` — `_is_cross_validation_enabled` fresh-read `{**data, **options}`. Confirmed.
- `camera_census.py:3515-3521` — `_get_known_face_guests` fresh-read. Confirmed rev-2.
- `camera_census.py:3736-3744` — `_is_egress_identity_failsafe_strict` fresh-read. Confirmed rev-2.
- `camera_census.py:4977-4983` — `_is_enhanced_census_enabled` fresh-read (secondary consumer only; setup-time consumer at `__init__.py:2363-2364` is dispositive → UNSAFE).
- `camera_census.py:4985-5004` — `_get_ble_cancel_enabled` fresh-read.
- `perimeter_alert.py:411-412` (cache), `:1681-1682`, `:1451-1455`, `:2570-2574`, `:2812-2816` (cached-consumer sites); `:967` (`_setup_time` set); `:899-904, 2618, 3760` (boot-settle gates that MUST be preserved across a Tier-2 re-read); `:970-` (`async_teardown`).
- `transit_validator.py:264, 347-366, 899-904` — three-part subscribe/teardown template.
- `config_flow.py:2616-2632` — integration options menu (six steps).
- `config_flow.py:2707, 2758, 2848, 2903, 3096, 7815` — the six step definitions bounding key enumeration in §A3.
- `config_flow.py:3113-3116` — retired-key strip on perimeter save (HOURS_START/END + NOTIFY_SERVICE/TARGET).
- `perimeter_alert.py:400-407` — retired-notify deprecation ERROR log (proves notify keys are retired).
- `person_coordinator.py:104` — `CONF_TRACKED_PERSONS` cache reads `entry.data` only (A5).
- `binary_sensor.py:61` — dead-import hygiene (unchanged).

### Prior planning docs consulted
- `docs/planning/AUDIT_integration_options_reload_classification.md` — the per-key fixture. Re-verify per §D1 + §A1.
- `docs/planning/PLANNING_reload_watchdog_hazard.md` — v1 shipped; **four** parked follow-ups (§A9).
- `docs/planning/PLANNING_cm_option_writeback_reload_suppression.md` — sibling suppression pattern.
- `docs/planning/PLANNING_config_subentries_migration.md` — STALE cites (§A10).
- `docs/planning/DEVICE_TREE_TARGET_arrangement_2026_09.md` — Rooms-node arrangement.

### Memory bodies pulled
- `feedback_parent_entry_reload_watchdog_hazard` — the bug class.
- `feedback_suppression_needs_discharge` — per-key discharge rule.
- `feedback_tier2plus_prior_art_scan` — this section's forcing function.
- `feedback_coincidental_equality_masks_concept_split` — informs fresh-read-vs-cached distinction audit.
- `feedback_no_fabrication` — every promoted key cites file:line (enforced rev-2).

### Design docs read
- No `docs/Coordinator/CAMERA.md`. Module headers + `IDENTITY_FUSION_CAMERAS_MANUAL.md` §platform-roles served as design surface for face/egress-identity keys.

### QUALITY_CONTEXT bug classes to watch
- #7 stale-data source; #27 primary/deferred mirror drift (do NOT branch `_apply_in_place` on entry type); #53 computed-but-not-consumed; #63 coincidental equality; new "integration-entry cascade" class candidacy.

---

## Deliverable structure — three tiers

### Tier 1 — Promote all provably-SAFE fresh-read keys (LOW RISK, in-pattern)

**D1.0 — Re-audit refresh (mandatory before any promotion).** Refresh `AUDIT_integration_options_reload_classification.md` against current code. Every row: re-verify verdict + citations against `develop` HEAD. Priorities:
- `CONF_ENHANCED_CENSUS` — CONFIRMED UNSAFE-STRUCTURAL (§A1). Do NOT admit. Update audit to cite `__init__.py:2363-2364` as the disqualifying setup consumer.
- `CONF_CENSUS_CROSS_VALIDATION` — SAFE (§A3).
- `CONF_CENSUS_BLE_CANCEL_ENABLED` — SAFE (§A3).
- `CONF_KNOWN_FACE_GUESTS` — SAFE (§A3), new rev-2 admission.
- `CONF_EGRESS_IDENTITY_FAILSAFE_STRICT` — SAFE (§A3), MUST pair with already-allowlisted `CONF_EGRESS_IDENTITY_ENABLED`.
- `CONF_PERIMETER_ALERT_HOURS_START/END` — SAFE zero-consumer retired keys (§A3); also supersession three-bucket triage candidates.
- Every current allowlist row (3 keys) — re-confirm SAFE / SAFE-WITH-DISPATCH under current code.
- Live probe: dump `integration_entry.options.keys()` via `ha-mcp` / SSH; any live key not in the §A3 enumeration blocks the build (undiscovered write site).

**D1.1 — Promote confirmed SAFE fresh-read keys.** Extend `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:6646-6664`) with the SIX keys named in §A2. No changes to `_INTEGRATION_KEY_SIGNAL_TABLE` (all six are fresh-read; path (a) of the suppression-needs-discharge rule).

**Producer / Consumer per promoted key** (see §A3 for full 43-key table; Tier-1 subset):

| Key | Producer (write site) | Consumers (file:line) | Discharge |
|---|---|---|---|
| `CONF_CENSUS_CROSS_VALIDATION` | `config_flow.py:2938-2941` (camera_census step) | `camera_census.py:2313-2323` (fresh) | None |
| `CONF_CENSUS_BLE_CANCEL_ENABLED` | `config_flow.py:3052-3058` | `camera_census.py:4985-5004` (fresh) | None |
| `CONF_KNOWN_FACE_GUESTS` | `config_flow.py:3004-3017` | `camera_census.py:3515-3521` (fresh) | None |
| `CONF_EGRESS_IDENTITY_FAILSAFE_STRICT` | `config_flow.py:3024-3030` | `camera_census.py:3736-3744` (fresh) | None (pair with EGRESS_IDENTITY_ENABLED) |
| `CONF_PERIMETER_ALERT_HOURS_START` | none-post-strip (`config_flow.py:3113-3116`) | none (retired) | None; supersession triage |
| `CONF_PERIMETER_ALERT_HOURS_END` | none-post-strip | none (retired) | None; supersession triage |

**Acceptance criteria (Tier 1).**
- **Doc:** `AUDIT_integration_options_reload_classification.md` refresh committed with dated header; every SAFE row cites fresh-read site AND caller's `{**data, **options}` construction site; `CONF_ENHANCED_CENSUS` row explicitly UNSAFE with the `__init__.py:2363-2364` cite.
- **Test:** `quality/tests/test_reload_watchdog_hazard.py::test_integration_suppress_promoted_fresh_read_keys[<key>]` parametrized per promoted key — allowlist subset save fires zero `async_reload`.
- **Test:** `::test_integration_allowlist_membership_pin` — pin exact allowlist size + membership.
- **Test (A2 pairing invariant):** `::test_egress_identity_pair_both_allowlisted` — a save that changes BOTH `CONF_EGRESS_IDENTITY_ENABLED` and `CONF_EGRESS_IDENTITY_FAILSAFE_STRICT` still passes the `issubset` guard.
- **Mutation drill:** remove one promoted key from allowlist → parametrized test for that key fails BY NAME; restore + status-check.
- **Live:** operator toggles the promoted census toggle in options; observe (a) single `INTEGRATION options changed for ... suppressing reload` log line, (b) zero unload lines for parent OR any child within 60s, (c) next census tick reads the new value.

**Tier 1 non-goals.** No new signals. No consumer changes. No structural refactor. `CONF_ENHANCED_CENSUS`, `CONF_TRACKED_PERSONS`, `CONF_ELECTRICITY_RATE` explicitly excluded.

---

### Tier 2 — Discharge-wire the NEEDS-DISCHARGE-WORK cached consumers, then promote

For every Tier-2-classified row in §A3, per-key wiring table (§A8) columns MUST be filled before code. Every wire-up follows `feedback_suppression_needs_discharge` AND uses the **narrow re-read** shape per §A4 (never `async_teardown()+async_setup()`).

**D2.1 — PerimeterAlertManager narrow re-read → promote perimeter-step keys + shared camera-list keys.** (Discharges parked follow-up #1.)
- NEW `SIGNAL_URA_PERIMETER_CONFIG_CHANGED` in `const.py`.
- In `PerimeterAlertManager.async_setup` (subscribe site parallel to `perimeter_alert.py:967` region), `async_dispatcher_connect` per the three-part template (`transit_validator.py:264, 347-366, 899-904`).
- Handler REBUILDS ONLY (per §A4): `_sensor_platforms`, `_sensor_to_camera`, `perimeter_sensors` + state subscriptions, `egress_sensors` + state subscriptions, vehicle-hours ints, enrichment default dict, `_snapshot_offset_s`.
- Handler PRESERVES (per §A4): `_setup_time`, `_active`, `_pending_dispatches`, `_dispatch_in_flight`, in-flight edge-capture tasks, `_unsub_started`, snapshot-sweep unsub.
- Unsub field init to None on `__init__`; unsub call added to `async_teardown` at `perimeter_alert.py:970+`.
- Wiring rows in `_INTEGRATION_KEY_SIGNAL_TABLE` for all 11 keys per §A3 (9 perimeter-step + 2 shared camera-list).
- Camera-list keys ALSO get `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (transit_validator is second cached consumer); helper's per-signal try/except handles the pair.
- Add all 11 keys to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`.

**D2.2 — Notification-manager wire-up → promote notify keys.** IFF probe confirms NM caches defaults.
- Probe first (measure-before-build): grep NM for `entry.options` / `entry.data` reads of `CONF_NOTIFY_SERVICE` / `_TARGET` / `_LEVEL`; if all fresh-read per notification, promote as fresh-read (Tier 1 path). If cached, `SIGNAL_URA_NOTIFY_CONFIG_CHANGED` + narrow re-read.

**D2.3 — Census-hold + divergence wire-up.**
- Probe first: `_get_hold_seconds` (referenced from `camera_census.py:4988` region) is fresh-read per tick — likely all three census-hold keys are fresh. If so, admit under D1.1 pattern.
- Genuinely-cached keys: `SIGNAL_URA_CENSUS_HOLD_CONFIG_CHANGED`; narrow re-read in `camera_census`.

**D2.4 — Person-tracking rate/retention keys (SCOPE REDUCED, per §A5/§A6).**
- IN SCOPE: `CONF_PERSON_DATA_RETENTION`, `CONF_TRANSITION_DETECTION_WINDOW` — per-key probe + wire.
- OUT OF SCOPE (carded separately): `CONF_TRACKED_PERSONS` (§A5), `CONF_ELECTRICITY_RATE` (§A6).

**D2.5 (A7) — Success-gated snapshot advance.**
- Modify `_dispatch_integration_key_signals` to return `dispatched_ok: set[str]`.
- Modify suppress branch at `__init__.py:7383-7395` to advance snapshot only for `dispatched_ok` keys.
- Test: `::test_snapshot_holds_key_when_dispatch_raises` — inject dispatch failure for one key, assert that key remains in `changed_keys` on the NEXT save.

**Acceptance criteria (Tier 2).**
- **Doc:** per-key wiring TABLE (§A8) committed BEFORE code.
- **Test per wire-up:** `::test_<key>_discharge_signal_dispatched_once`.
- **Test per wire-up:** `::test_<key>_cached_consumer_rereads_on_signal`.
- **Test (§A4):** `::test_perimeter_config_change_preserves_boot_settle_window`.
- **Mutation drill per wire-up:** remove subscribe line → cached-reread test fails BY NAME. Restore.
- **Mutation drill per wire-up:** remove wiring row → dispatched-once test fails BY NAME. Restore.
- **Test:** `::test_mixed_all_tier2_keys_falls_through_to_reload`.
- **Test (A7):** `::test_snapshot_holds_key_when_dispatch_raises`.
- **Live:** for each promoted key, operator flips it; observe suppress log, zero unloads, cached-consumer behavior reflects new value at next tick (discriminating observation per key).

**Tier 2 non-goals.** No `_apply_in_place` change. No structural setup/unload change. No config-subentry migration. No `async_teardown()+async_setup()` on any manager (§A4). `CONF_TRACKED_PERSONS`, `CONF_ELECTRICITY_RATE`, `CONF_ENHANCED_CENSUS` out of scope.

---

### Tier 3 — Structural: unavoidable reloads MUST NOT stall the loop / cascade

Even after Tier 1+2, some keys legitimately require re-registration: `CONF_OUTSIDE_TEMP_SENSOR`, `CONF_WEATHER_ENTITY`, `CONF_SOLAR_PRODUCTION_SENSOR`, `CONF_WHOLE_HOUSE_POWER_SENSORS`, `CONF_WHOLE_HOUSE_ENERGY_SENSORS`, **`CONF_ENHANCED_CENSUS`** (§A1), any Tier-2-probed key that comes back UNSAFE. A save of any of these still hits `async_reload` at `__init__.py:7404-7416`.

**D3.0 — Empirical probe (measure-before-build gate).** BEFORE any structural work:
- Instrument (temporary log or one-shot probe) `async_setup_entry` for the integration branch and each child branch: record wall-clock elapsed + `await` yield count. If elapsed < 200 ms per entry and child setups run concurrently, D3.b may be unnecessary. If any single-entry setup > 200 ms synchronously, D3.b mandatory.
- Static probe: grep `async_setup_entry` INTEGRATION branch for synchronous heavy work.
- Deliverable: `docs/planning/AUDIT_integration_setup_loop_cost.md`.

**D3.a — Adopt config subentries migration** (`docs/planning/PLANNING_config_subentries_migration.md`).
- **Precondition (§A10):** refresh that plan's `config_flow.py` / `__init__.py` cites against `develop` HEAD (baselined at v4.7.19; production is v5.90.x). Refresh pass BEFORE build dispatch.
- STATUS: READY TO ENTER BUILD once operator signs off (post-refresh).
- Inherit its Tier 2-DB review protocol nested inside this Tier-3 review.
- Requires operator sign-off (30-50h).

**D3.b — Async / yielding integration `async_setup_entry` refactor** (independent of, complementary to, D3.a).
- Push synchronous cost off the loop: `hass.async_add_executor_job` for registry walks / file I/O; batch + `await asyncio.sleep(0)` between children; explicit yield points at every 50-entity boundary.
- Belt and suspenders with D3.a. If D3.0 shows the parent setup itself is loop-hog independent of child count, D3.b required even after subentries.
- If D3.0 shows negligible per-entry cost and D3.a alone bounds blast radius, D3.b MAY be deferred with measurement cite.

**D3.c — Structural saves get WARNING log naming the changed keys.** Add a WARNING-level log at the fall-through path (`__init__.py:7404`) that names the changed keys forcing the reload, so post-incident analysis identifies WHICH key is the culprit for future Tier-1/2 promotion.

**Producer / Consumer (Tier 3).** The affected "value" is the entry-reload event itself; producer is `_async_update_listener` fall-through; consumers are every `async_setup_entry` / `async_unload_entry` branch. D3 doesn't change wiring — it changes cost curve.

**Acceptance criteria (Tier 3).**
- **Doc:** `AUDIT_integration_setup_loop_cost.md` committed.
- **Doc:** `PLANNING_config_subentries_migration.md` refresh committed (§A10 precondition) BEFORE D3.a build.
- **Recommendation:** planning doc names D3.a-only, D3.b-only, or both with numeric justification from D3.0.
- **Test (D3.b):** `::test_integration_setup_yields_within_200ms`.
- **Test (D3.a):** inherit from subentries plan §3.
- **Live (D3.a):** post-migration, a structural save (e.g. `CONF_OUTSIDE_TEMP_SENSOR` OR `CONF_ENHANCED_CENSUS`) reloads only the affected subentry.
- **Live (D3.b):** structural save with D3.b produces no supervisor watchdog message.
- **Live (D3.c):** fall-through WARNING log names the changed keys.

**Tier 3 non-goals.**
- No change to Tier 1 / Tier 2 allowlist mechanics.
- No back-compat shims (single-user); rely on `async_migrate_entry`.
- No new user-facing entity for setup cost.

---

## Non-goals (whole cycle)
- No modification to `_apply_in_place` (Bug Class #27). Integration path stays on the sibling `_dispatch_integration_key_signals` helper.
- No change to ROOM branch or CM branch of `_async_update_listener`.
- No change to fall-through reload beyond D3.c's WARNING log.
- No new user-facing entity, sensor, or knob. Kill switch remains rung-1 constant.
- No back-compat / migration scaffolding beyond `async_migrate_entry` from D3.a.
- No `async_teardown()+async_setup()` on any manager (§A4).
- `CONF_TRACKED_PERSONS`, `CONF_ELECTRICITY_RATE`, `CONF_ENHANCED_CENSUS` explicitly out of scope this cycle (card separately for the first two; Tier-3 addresses the third via D3.a/D3.b cost bounding).
- No deletions without three-bucket triage.

---

## Numbers Get Knobs

| Knob | Rung | Home | Rationale |
|---|---|---|---|
| `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` | 1 (module constant) | `__init__.py:6646-6664` | Adding/removing a key changes lifecycle safety; requires review. |
| `_INTEGRATION_KEY_SIGNAL_TABLE` | 1 | `__init__.py:6679-6688` | Wiring table. |
| `INTEGRATION_RELOAD_SUPPRESS_ENABLED` | 1 | `__init__.py:6670` | Fire-axe; flipping re-enables the outage. |
| Any new signal names | 1 | `const.py` | Rung-1 wire identities. |
| D3.b yield-point cadence (e.g. `_SETUP_YIELD_EVERY_N`) | 1 | `__init__.py` (near setup) | Setup pacing; not operator-tuneable. |

No entity-rung or config-flow-rung knobs proposed.

---

## Supersession & consumer-gap audit (post-ship — mandatory)

After ship, run the standing three-bucket triage on:
- Any INTEGRATION-branch code paths made redundant by subentries (D3.a). Classify DELETE / KEEP+WIRE / KEEP+DOCUMENT.
- `CONF_PERIMETER_ALERT_HOURS_START/END` — zero consumers, retired-default fallbacks; triage DELETE (with grep sweep for any residual writer) vs KEEP+DOCUMENT.
- `CONF_PERIMETER_ALERT_NOTIFY_SERVICE/TARGET` — retired at save; DELETE candidate (retire the strip once no persisted options carry them).
- `binary_sensor.py:61` dead import — hygiene fix rides on this cycle.
- Should-be-consuming gaps.

---

## Tier-3 review — FOUR framing-disjoint reviews before ship

Per Tier 3 protocol (operator-coined 2026-06-16; codified in CLAUDE.md):

1. **Review A — local correctness per key.** Walk EVERY allowlist admission (§A2/§A3) + wiring row (§A8); re-verify fresh-read/discharge citations by independent grep. Walk `_dispatch_integration_key_signals` per-signal path (including A7 success-gating). Confirm no consumer missed.
2. **Review B — integration / state-machine integrity.** Snapshot ownership + reseed timing on fall-through (D3.c); no double-fire on mixed saves; `async_migrate_entry` correctness (D3.a); restart-seed correctness for every promoted key; A4 preservation-list correctness (boot-settle window NOT reset by narrow re-read); A7 snapshot-hold correctness; interaction with HA-core `async_update_entry` short-circuit; concurrent-save race.
3. **Review C — test authority via REAL per-site source mutation.** For every allowlist row, every wiring row, every subscribe site: source-mutate ONE site at a time, run the suite, confirm SPECIFIC test fails BY NAME. Restore + status-check per drill. Verify `.pyc` staleness workaround (`feedback_mutation_pyc_staleness`). Includes A4 mutation (`self._setup_time = dt_util.now()` in the handler) and A7 mutation (unconditional snapshot advance).
4. **Review D — adversarial completeness / diff-blind.** State the falsifiable invariant. Re-enumerate EVERY integration-entry option key currently reachable via the six steps opened from `config_flow.py:2616-2632` (`:2707, :2758, :2848, :7815, :2903, :3096`) against §A3. Attempt to construct legal-config saves that violate invariant OR corollary. Enumerate PRE-EXISTING surface too — a v1-era consumer not touched by this cycle could still cache stale state under a new allowlist admission (D-HIGH-style latent leak). Every leak flagged ships with a concrete reachable repro.

Orchestrator independent verification before ship (mandatory Tier-3 checkpoint): re-grep every allowlist row + wiring row against source (using the three-part template cites at `transit_validator.py:264, 347-366, 899-904`); re-run one source mutation on a random load-bearing site; operator checkpoint with invariant proof.

---

## Files touched (build cycle scope)

- `custom_components/universal_room_automation/__init__.py` — extend allowlist + wiring table (Tier 1/2); A7 success-gated snapshot; D3.b setup-refactor (if adopted); D3.c WARNING log.
- `custom_components/universal_room_automation/const.py` — new signals (Tier 2).
- `custom_components/universal_room_automation/perimeter_alert.py` — D2.1 subscribe + **narrow re-read** (§A4) + teardown unsub. NOT `async_teardown()+async_setup()`.
- `custom_components/universal_room_automation/camera_census.py` — D2.3 subscribe (only for genuinely-cached keys after probe).
- `custom_components/universal_room_automation/domain_coordinators/notification.py` (or wherever NM lives) — D2.2 subscribe (conditional).
- ~~`custom_components/universal_room_automation/domain_coordinators/presence.py`~~ — **REMOVED per §A5** (`CONF_TRACKED_PERSONS` out of scope).
- `custom_components/universal_room_automation/binary_sensor.py` — remove dead import at `:61` (hygiene).
- `quality/tests/test_reload_watchdog_hazard.py` — extend with per-key admission + wire-up + mutation-anchored tests + §A4 boot-settle-preservation + §A7 snapshot-hold.
- `docs/planning/AUDIT_integration_options_reload_classification.md` — refresh in place; explicit UNSAFE cite for CONF_ENHANCED_CENSUS (§A1).
- `docs/planning/AUDIT_integration_setup_loop_cost.md` — NEW (D3.0).
- `docs/planning/PLANNING_config_subentries_migration.md` — cite-refresh precondition (§A10); D3.a adopts.
- `docs/readmes/README_v<version>.md` — created pre-deploy, updated post-Live (write-back).
- `docs/QUALITY_CONTEXT.md` — promote "integration-entry cascade" bug class if reviewer concurs.

---

## Plan-completion tracking

Explicitly deferred out of this cycle (each carded separately):
- `INTEGRATION-TRACKED-PERSONS-DISCHARGE-1` — cache reads wrong dict (§A5).
- `INTEGRATION-ELECTRICITY-RATE-DISCHARGE-1` — ≥4 consumers, needs its own producer/consumer table (§A6).
- `INTEGRATION-ENHANCED-CENSUS-STRUCTURAL-1` — setup-time listener registration; Tier-3 addresses cost via D3.a/D3.b (§A1).

Parked follow-ups from v1 plan (FOUR per §A9) are ALL discharged by this cycle on operator-directive grounds, EXCEPT parked #2 (broader async-reload redesign) which is REFRAMED as D3.b + D3.a.

---

## Buildability summary — for the orchestrator/operator

| Deliverable | Buildable now (no sign-off) | Needs operator sign-off |
|---|---|---|
| D1.0 audit refresh | YES | — |
| D1.1 promote SAFE fresh-read keys (6 keys per §A2) | YES | — |
| D2.1 PerimeterAlertManager narrow re-read (~11 keys, §A4) | YES | — |
| D2.2 NM wire-up (conditional on probe) | YES | — |
| D2.3 census-hold wire-up (conditional on probe) | YES | — |
| D2.4 person-tracking rate/retention (SCOPE REDUCED per §A5/§A6) | YES | — |
| D2.5 success-gated snapshot advance (§A7) | YES | — |
| D3.0 measure-before-build probe | YES | — |
| D3.a config subentries migration adoption | — (blocked on §A10 cite-refresh) | **YES — 30-50h, structural** |
| D3.b async/yielding setup refactor | YES (contingent on D3.0) | — |
| D3.c fall-through WARNING log | YES | — |
