# PLANNING — RELOAD-WATCHDOG-HAZARD: Integration-Entry Options-Save Cascade

**Status:** DOCS-ONLY plan (overnight constraint). Build dispatched in a subsequent cycle.
**Version:** unassigned (operator assigns at deploy time per `feedback_versioning_convention`).
**Tier:** **Tier 2-DB** (standing policy for regression-prone lifecycle change; `tier-2db` on kanban card).
**Kanban card:** `RELOAD-WATCHDOG-HAZARD` (docs/planning/kanban.data.yaml ~line 2145).
**Trigger:** 2026-08-07 live — a routine Camera Census save (`camera_person_entities`) reloaded the URA **integration (parent)** entry, cascading synchronously to ~40 room + coordinator entries, stalling the event loop until the supervisor watchdog restarted core (~5-minute house outage).

---

## Falsifiable invariant (state up front)

> **A config-options save on the URA integration (parent) entry whose changed key-set is a subset of a documented safe-to-suppress allowlist MUST cause zero `config_entries.async_reload` calls against ANY entry (parent, room, or coordinator-manager) AND MUST NOT enqueue any task whose runtime exceeds ~200 ms on the event loop.**

Corollary invariants:
- Persistence still happens (`async_update_entry` already wrote `entry.options`).
- Consumers of every suppressed key either (a) read `entry.options` fresh on next tick, or (b) receive an explicit dispatcher signal that triggers a **local, in-place re-subscribe** (not a reload).
- Restart re-seeds the value from `entry.options` (unchanged behavior).
- No suppressed key has a cached consumer with no refresh path. (Suppression without discharge = deleted event — see `feedback_suppression_needs_discharge`.)

Reviewer D's job under Tier-3 framing (if elevated): break this invariant with a concrete legal-config repro.

---

## Central-question answer (verified this session)

**Q: Why did `camera_person_entities` not benefit from the v4.7.26 / v4.7.27 reload-suppression shipped for the CM entry?**

**A: The shipped `OPTIONS_RELOAD_SUPPRESS_KEYS` mechanism is gated on `entry_type == ENTRY_TYPE_COORDINATOR_MANAGER`. Camera keys live on the INTEGRATION (parent) entry — a different entry type with NO suppress branch today. The integration entry's options-save falls straight through to the untracked full reload at `__init__.py:6512-6514`.**

Grounded citations:
- Camera keys are defined and CONSUMED at integration level:
  - `const.py:1305-1307`: `CONF_CAMERA_PERSON_ENTITIES = "camera_person_entities"`, `CONF_EGRESS_CAMERAS = "egress_cameras"`, `CONF_PERIMETER_CAMERAS = "perimeter_cameras"`.
  - `__init__.py:440-512`: v3.4.5 migration `_migrate_room_cameras_to_integration` moved `camera_person_entities` from per-room entries to the integration entry.
  - `camera_census.py:1787-1821`: `_get_interior_camera_entities` / `_get_integration_camera_list(conf_key)` iterate `hass.config_entries.async_entries(DOMAIN)` filtering `data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION` and reads `entry.options` LIVE on every call — no cache. Camera Census is safe to suppress with **no signal needed** (fresh read per invocation).
  - `transit_validator.py:243-335, 337-419`: caches subscriptions at `async_init`. Already wired to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (`_on_config_changed → _schedule_rebuild`, `transit_validator.py:316-335`). The signal was defined in `const.py:2014` and shipped for exactly this purpose ("F6 fix… a local re-init without a parent-entry reload (RELOAD-WATCHDOG-HAZARD)"). **It is not currently dispatched by the update listener** — the wire-up is inert.
  - `fan_veto.py:353`: reads `CONF_CAMERA_PERSON_ENTITIES` from merged config — fresh read per call, no cache.
  - `binary_sensor.py:61`: imports `CONF_CAMERA_PERSON_ENTITIES` (spot-verify consumer path; treat as fresh-read unless a per-entity cache is discovered during Institutional Context re-run in build).
- Suppress mechanism gating:
  - `__init__.py:5775`: `OPTIONS_RELOAD_SUPPRESS_KEYS` defined (Cycle 1 → NM Cycle C, ~130+ CM-owned keys).
  - `__init__.py:6431-6482`: allowlist checked ONLY inside `if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:`. Integration entry has no equivalent branch.
  - `__init__.py:6502-6514`: fall-through untracked `async_create_task(hass.config_entries.async_reload(entry.entry_id))` — this is what the Camera Census save hit.
- Cascade mechanism: reloading the integration (parent) entry unloads all child entries (rooms + CM + zone-managers) as part of platform teardown; ~40 entries × unload+setup on the event loop = watchdog exposure. Prior incident: `feedback_parent_entry_reload_watchdog_hazard` memory; `feedback_deploy_from_develop_not_feature` sibling — the CM reload suppression cycle was scoped to CM entry only.

**Implication (marginal-benefit decomposition):**
- The **simplest fix** that captures the whole known-hazard is: mirror the shipped CM suppress pattern for `ENTRY_TYPE_INTEGRATION`, add camera keys (+ any other integration-level keys verified fresh-read/signal-refreshable) to a NEW `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` allowlist, and dispatch the already-wired `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` to re-subscribe transit_validator in place.
- The **marginal risk** of a deeper async-reload redesign (async unload staging, per-child throttling) is categorically larger (state-machine + lifecycle) and buys nothing for the observed failure. **Park the redesign** with evidence trigger: *"if a future integration-level key genuinely REQUIRES a full reload AND causes the same outage, revisit."*
- Recommended scope: allowlist-extension + integration-entry branch + one dispatcher wire-up. Small, mirrors an in-production pattern, per-key discharge verified.

---

## Institutional context verified

### Prior planning docs consulted
- `docs/planning/PLANNING_cm_option_writeback_reload_suppression.md` — shipped v4.7.26/v4.7.27; source of the CM `OPTIONS_RELOAD_SUPPRESS_KEYS` + `_apply_in_place` + snapshot/partial-apply machinery that this cycle mirrors. Read: header + design section.
- `docs/planning/PLANNING_room_rename_writethrough.md` — single-listener-fire pattern (`async_update_entry` combined call). Confirmed: the switch/number-side write-throughs already batch into one `async_update_entry` call per setter; no double-fire hazard from this cycle.

### Memory bodies pulled
- `feedback_parent_entry_reload_watchdog_hazard` — the class this card belongs to; ~5min outage on parent reload.
- `project_incident_v5_8_0_setup_recursion` — v5.8.0 rolled back; reconcile-crashed-all-40-rooms. Reinforces "no test used real coordinator construction"; this cycle's Live criterion must observe zero reloads on a real save, not just a unit-test assertion.
- `feedback_suppression_needs_discharge` — every suppressed event must specify what re-fires it. Applied per-key below.
- `feedback_no_fabrication` — every suppress addition cites a fresh-read line or a discharge signal wire-up.

### Design docs read
- No `docs/Coordinator/CAMERA.md` exists. `camera_census.py` module docstring + `transit_validator.py` §F5/F6 header comments served as the design surface.

### Code locations surveyed
- `custom_components/universal_room_automation/__init__.py`
  - `_async_update_listener` (`:6322-6514`) — dispatch of ROOM vs CM branches; fall-through reload.
  - `OPTIONS_RELOAD_SUPPRESS_KEYS` frozen set (`:5775-5960+`).
  - `_apply_in_place` (`:5904-6099+`) — HVAC / EC / no-live-attr partial-apply pattern.
  - `_ROOM_SUPPRESS_KEYS` (`:6366-6380`) — comfort/zone/fan-toggle mirror for ROOM entries.
- `custom_components/universal_room_automation/const.py` — `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` (`:1305-1307`); `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (`:2014`).
- `custom_components/universal_room_automation/camera_census.py` — `_get_integration_camera_list` (`:1803-1821`), `_get_interior_camera_entities` (`:1787-1801`).
- `custom_components/universal_room_automation/transit_validator.py` — `_config_signal_unsub` wire-up (`:309-335`); `_build_and_subscribe` (`:337-419`).
- `custom_components/universal_room_automation/fan_veto.py:353` — `cam_entities = config.get(CONF_CAMERA_PERSON_ENTITIES) or []` (fresh-read).
- `custom_components/universal_room_automation/binary_sensor.py:61` — import site (behavior confirmation deferred to build's Institutional Context re-run — flagged in D1 acceptance).

### Greps run + results (proposed additions)
- **NEW** `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` frozen-set constant — grep for name in `__init__.py` returns zero hits; no equivalent exists (CM set is CM-only by scoping). Justification: entry-type-scoped allowlist mirrors the shipped `OPTIONS_RELOAD_SUPPRESS_KEYS` pattern (`__init__.py:5775`) and `_ROOM_SUPPRESS_KEYS` inner constant (`__init__.py:6366`).
- **REUSED** `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` at `const.py:2014` — already defined, already subscribed at `transit_validator.py:328`. This cycle only ADDS the dispatch site in the update listener; no new signal.
- **REUSED** `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` at `const.py:1305-1307` — no new CONF_*.
- **REUSED** `_apply_in_place` snapshot/partial-apply pattern (`__init__.py:5904+`) — build may extract a small `_apply_in_place_integration()` sibling OR extend the existing helper with an entry-type branch. Decision deferred to build; both are documented mirrors of the shipped pattern.
- **NEW** rung-1 module constant `INTEGRATION_RELOAD_SUPPRESS_ENABLED: Final[bool] = True` — kill switch. Rung-1 (module constant) per `numbers-get-knobs` ladder: this is a safety/lifecycle bound; turning it off should REQUIRE code review (it re-enables the ~5min outage). NOT an options-flow knob and NOT an entity.

### QUALITY_CONTEXT bug classes to check during build/review
- Suppression-without-discharge (per-key discharge table below).
- Untracked background tasks (the existing fall-through uses the untracked pattern; the suppress branch does NOT enqueue anything).
- Concurrent-reload race (a mixed-key save falling through during a suppressed-key dispatch — snapshot reseed pattern from `__init__.py:6493-6500` is the model).
- Stale-data / cached consumer (Bug Class #7): each suppressed key MUST cite a fresh-read line OR a discharge signal.
- Enum mismatch / computed-but-not-consumed (Class #22, #53): the discharge signal must actually rebuild — not just log.

---

## Deliverables

### D1: Enumerate & classify integration-entry option keys

**Description:** Before writing suppress code, produce a table of every key that appears in `entry.options` for the URA integration (parent) entry, and for each one classify:
- **Consumer(s)** (file:line).
- **Consumption mode**: `fresh-read-per-tick`, `cached-with-signal-refresh`, `cached-no-refresh`, `requires-reload`.
- **Suppress verdict**: `SAFE` (fresh-read), `SAFE-WITH-DISPATCH` (cached, discharge signal wired), `UNSAFE` (must reload — stays out of allowlist).

**Method:** live probe (per `Measure Before You Build`): one-shot script over the live HA config-entries store (via `ha-mcp` or SSH) to dump `integration_entry.options.keys()`, then per-key grep across `custom_components/universal_room_automation/`. Commit the table to `docs/planning/AUDIT_integration_options_reload_classification.md` as the acceptance fixture the D2 allowlist is diffed against (per `hand-build fixture` corollary).

**Known-in-scope keys (seed):** `camera_person_entities`, `egress_cameras`, `perimeter_cameras`, `face_recognition_enabled` (and any other integration-level CONF_* discovered by the probe).

**Explicitly out of scope for D1 classification (do NOT include in allowlist without probe evidence):** any key whose consumer is discovered to be `cached-no-refresh` — those are `UNSAFE` and stay on the reload path.

### Acceptance Criteria
- **Doc:** `AUDIT_integration_options_reload_classification.md` exists, one row per live integration-entry option key, each with consumer file:line and verdict.
- **Verify:** every `SAFE` row cites a fresh-read line; every `SAFE-WITH-DISPATCH` row cites both a cache site AND a signal-subscribe site.
- **Verify:** `binary_sensor.py:61` (`CONF_CAMERA_PERSON_ENTITIES` import) traced end-to-end — confirm fresh-read or reclassify.

---

### D2: Add `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` + integration-entry branch in `_async_update_listener`

**Description:** Mirror the CM pattern in `__init__.py`:

1. Add module-level `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str]` populated from the D1 `SAFE` + `SAFE-WITH-DISPATCH` rows.
2. Add module-level rung-1 kill switch `INTEGRATION_RELOAD_SUPPRESS_ENABLED: Final[bool] = True`.
3. In `_async_update_listener`, add a new branch: `if entry_type == ENTRY_TYPE_INTEGRATION:` mirroring the CM branch's snapshot + subset-check + suppress-log + return pattern:
   - Snapshot dict `integration_last_applied_options` under `hass.data[DOMAIN]`.
   - Compute `changed_keys` via old/new diff (same shape as CM branch, `__init__.py:6447-6460`).
   - If `changed_keys` empty → return.
   - If `INTEGRATION_RELOAD_SUPPRESS_ENABLED` AND `changed_keys ⊆ INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`:
     - Call `_dispatch_integration_key_signals(hass, entry, changed_keys)` (D3).
     - Log at INFO with the same shape as the CM branch log (`__init__.py:6462-6466`) — a live tail must be able to grep this to prove suppression fired.
     - Update snapshot (per-key partial-apply pattern from CM branch, `__init__.py:6475-6481`; for D2 the "apply set" == "changed set" because integration-side apply is dispatch-only, no live-attr push — but keep the shape for symmetry so future cached-consumer additions have the seat).
     - `return`.
   - Mixed / non-allowlisted → reseed snapshot and fall through to existing reload (parity with CM branch, `__init__.py:6483-6500`).

4. Ensure the branch runs **before** the generic fall-through reload at `__init__.py:6502-6514`.

**Rung-ladder placement (per `numbers-get-knobs`):**
- `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` — rung 1 (module constant). Adding/removing a key changes lifecycle behavior and must require review.
- `INTEGRATION_RELOAD_SUPPRESS_ENABLED` — rung 1 (module constant). Kill switch; `False` restores legacy reload cascade.

### Acceptance Criteria
- **Test:** unit test (`quality/tests/test_reload_watchdog_hazard.py`) asserts that an integration-entry options update whose `changed_keys` ⊆ allowlist does NOT call `hass.config_entries.async_reload` (mock/spy). Named `test_integration_options_suppress_reload_on_camera_keys`.
- **Test:** a MIXED save (allowlisted + non-allowlisted key) DOES call `async_reload` exactly once — test name `test_integration_options_mixed_falls_through_to_reload`.
- **Test:** kill-switch off (`INTEGRATION_RELOAD_SUPPRESS_ENABLED = False`) restores the legacy reload for camera-only saves — proves the kill switch is load-bearing.
- **Sensor:** none needed (lifecycle behavior; observed via log + reload absence).
- **Live:** operator triggers a Camera Census save (adds/removes one entity from `camera_person_entities`) via the URA options flow. Expected observation in the HA log:
  - Exactly one log line: `INTEGRATION options changed for '<title>' (<entry_id>) — in-place apply, suppressing reload (changed_keys=['camera_person_entities'])`.
  - Zero `Options changed for '...', scheduling reload` lines for the URA integration entry within the same save.
  - Zero unload/setup log lines for any URA child entry within 60s after the save.
  - No supervisor watchdog message and no HA core restart.

---

### D3: Wire `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` dispatch for camera-list changes

**Description:** Add `_dispatch_integration_key_signals(hass, entry, changed_keys)` in `__init__.py` — a tiny helper called by the D2 suppress branch. For camera-list keys, it fires the already-defined `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (`const.py:2014`) so `TransitValidator` re-subscribes locally via its existing wire-up (`transit_validator.py:316-335`, `_schedule_rebuild`).

The dispatch table lives in the helper (rung-1 dict):
```python
# Illustrative shape — not literal build spec.
_INTEGRATION_KEY_SIGNAL_TABLE = {
    CONF_CAMERA_PERSON_ENTITIES: (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,),
    CONF_EGRESS_CAMERAS:         (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,),
    CONF_PERIMETER_CAMERAS:      (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,),
}
```

Camera Census itself needs **no signal** — `_get_integration_camera_list` reads `entry.options` fresh on every invocation (`camera_census.py:1812-1820`). Same for `fan_veto.py:353`. The signal is exclusively for `transit_validator`'s cached subscription set.

**Discharge contract (per `suppression-needs-discharge`):**
| Suppressed key | Consumer path | Refresh mechanism | Backstop |
|---|---|---|---|
| `camera_person_entities` | camera_census fresh read; transit_validator cached subs | fresh read (census); `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (transit) | HA restart re-seeds from `entry.options` |
| `egress_cameras` | camera_census fresh read; transit_validator cached subs | fresh read + signal | restart re-seeds |
| `perimeter_cameras` | camera_census fresh read; transit_validator cached subs | fresh read + signal | restart re-seeds |

Wrap the dispatch in per-key `try/except` matching the CM branch's defensive posture (`__init__.py:6416-6420`); a failed dispatch logs at WARNING but does NOT re-raise — the persistence write has already succeeded and reload is a worse outcome than a missed subscription (which self-heals via the entity-registry listener at `transit_validator.py:281-302` on the next Protect churn or by HA restart).

### Acceptance Criteria
- **Test:** unit test asserts a camera-key change fires `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` exactly once with the current camera-list payload semantics (or zero-arg per the existing subscriber signature at `_on_config_changed(*_a)`).
- **Test:** per-key mutation drill — remove the dispatch line for `camera_person_entities` and confirm a NAMED behavioral test fails (not just aggregate suite green). Per `feedback_hollow_test_anchors`.
- **Live:** post-save, `TransitValidator subscriptions built: %d camera entities…` log line appears within 5 seconds of the save (the `_schedule_rebuild` debounce). Camera-count delta matches the operator's change.

---

### D4: Snapshot / partial-apply parity + concurrent-write safety

**Description:** Reuse the CM branch's snapshot pattern (`hass.data[DOMAIN]["integration_last_applied_options"]`) with the same reseed-on-fall-through discipline (`__init__.py:6493-6500`). Guarantees:

- A second options save that arrives mid-dispatch diffs against a clean baseline.
- HA-core's `async_update_entry` identical-write short-circuit is the primary defense; this snapshot is the belt-and-braces layer for external drift paths (documented in the CM branch, `__init__.py:6456-6460`).
- Snapshot lives in `hass.data`, not on the entry — survives suppress-branch churn, cleared on entry unload (mirror the CM path — build to verify the cleanup point).

### Acceptance Criteria
- **Test:** back-to-back saves of the same allowlisted key produce a single-suppress-log-line pair with no reload; snapshot advances.
- **Test:** save-A (allowlisted) followed within 100ms by save-B (mixed) → suppress-A + reload-once-for-B; no double-reload.
- **Live:** N/A (covered by D2 live check; add here only if a race is observed).

---

### D5: Kill switch + observability

**Description:**
- Rung-1 `INTEGRATION_RELOAD_SUPPRESS_ENABLED` constant (D2). Documented in code comment as the fire-axe: setting `False` restores the legacy reload cascade (and the outage). No entity, no options-flow — deliberate.
- Log-line grep contract (D2 log wording) is the observability primitive. No new sensor.
- Add a one-line entry to `docs/QUALITY_CONTEXT.md` if the review surfaces a NEW bug class ("integration-entry cascade" is arguably a NEW subclass of "parent reload watchdog hazard" — reviewer call).

### Acceptance Criteria
- **Verify:** `INTEGRATION_RELOAD_SUPPRESS_ENABLED = False` restores legacy behavior (D2 test).
- **Verify:** README_v<version>.md is written with a prospective Live block AND updated post-restart with the observed suppress-log + zero-reload evidence (per `Record Live Validation Back Into the README`).

---

## Non-goals (explicit)

- **NO** redesign of the async reload machinery (staged unload, per-child throttling, coalescing). Parked; evidence trigger = "a future integration-level key genuinely requires a reload AND causes the same outage."
- **NO** change to CM-entry `OPTIONS_RELOAD_SUPPRESS_KEYS` or `_apply_in_place` — CM behavior is unchanged.
- **NO** change to ROOM-entry `_ROOM_SUPPRESS_KEYS` — comfort/zone/fan suppression is unchanged.
- **NO** change to the update-listener fall-through reload for entries/keys still on the reload path — it stays as the safety net.
- **NO** new user-facing entity / knob / sensor. Kill switch is code-only.
- **NO** back-compat scaffolding (per `Single User No Back-Compat`).
- **NO** migration; snapshot dict initializes empty on first observation.

---

## Tier & review

**Tier 2-DB** (standing policy for regression-prone lifecycle change).

**Three framing-disjoint reviews before deploy:**
- **Review A — Correctness + per-key discharge.** For each key in the D1/D2 allowlist, re-verify fresh-read or signal-refresh. Walk `_dispatch_integration_key_signals`; confirm no cached consumer missed. Grep for OTHER call sites of `CONF_CAMERA_PERSON_ENTITIES` / `CONF_EGRESS_CAMERAS` / `CONF_PERIMETER_CAMERAS` beyond those enumerated here — anything discovered goes into D1 or blocks ship.
- **Review B — Lifecycle + concurrency.** Snapshot ownership and reseed timing; interaction with HA-core's own `async_update_entry` short-circuit; behavior when a mixed save arrives during a suppressed dispatch; restart-seed correctness (no options loss); cleanup of `integration_last_applied_options` on entry unload.
- **Review C — Fixture / test authority + adversarial completeness.** Confirm tests exercise the real listener code path (not a monkeypatched fake). Per-site source mutation drill on the dispatch line AND on the subset-check to prove each is load-bearing. Reviewer C also runs the D adversarial-completeness pass: state the invariant, re-enumerate every integration-entry key currently or historically in options, attempt to construct a legal-config save that reloads despite the allowlist claim.

If any pass finds a CRITICAL/HIGH: fix, re-run per-site mutation on the fixed site, re-run C's enumeration.

**Post-deploy Live validation** = D2 Live criteria observed on the running house and written back into `README_v<version>.md`.

---

## Numbers / knobs (per `numbers-get-knobs`)

| Knob | Rung | Rationale |
|---|---|---|
| `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (frozen set) | 1 (module constant) | Adding/removing a key changes lifecycle safety; requires review + reviewer discharge audit. |
| `INTEGRATION_RELOAD_SUPPRESS_ENABLED` (bool) | 1 (module constant) | Fire-axe kill switch; turning it off re-enables the outage — must require code review. |
| `_INTEGRATION_KEY_SIGNAL_TABLE` (dict) | 1 (module constant) | Wiring table; changes are code changes. |

No rung-2 (options) or rung-3 (entity) knobs introduced.

---

## Files touched (build cycle — this is the docs-only plan)

- `custom_components/universal_room_automation/__init__.py` — new constants, new integration-entry branch in `_async_update_listener`, `_dispatch_integration_key_signals` helper.
- `quality/tests/test_reload_watchdog_hazard.py` — NEW test module.
- `docs/planning/AUDIT_integration_options_reload_classification.md` — NEW (D1 output).
- `docs/readmes/README_v<version>.md` — created pre-deploy, updated post-Live.
- `docs/QUALITY_CONTEXT.md` — potential new-bug-class entry (reviewer's call).

---

## Plan-completion tracking

If build defers any deliverable, list here with WHY. Nothing deferred at plan time.
