# PLANNING — RELOAD-WATCHDOG-HAZARD: Integration-Entry Options-Save Cascade

**Status:** DOCS-ONLY plan, **rev-2** (post plan-review `docs/reviews/code-review/reload_watchdog_plan_review.md` @ `bf8ee9f65`). Build dispatched in a subsequent cycle.
**Version:** unassigned (operator assigns at deploy time per `feedback_versioning_convention`).
**Tier:** **Tier 2-DB** (standing policy for regression-prone lifecycle change; `tier-2db` on kanban card).
**Kanban card:** `RELOAD-WATCHDOG-HAZARD` (docs/planning/kanban.data.yaml ~line 2145).
**Trigger:** 2026-08-07 live — a routine Camera Census save (`camera_person_entities`) reloaded the URA **integration (parent)** entry, cascading synchronously to ~40 room + coordinator entries, stalling the event loop until the supervisor watchdog restarted core (~5-minute house outage).

**Rev-2 changes** (see plan-review dispositions in appendix):
- v1 allowlist trimmed to a single key: `CONF_CAMERA_PERSON_ENTITIES`. `CONF_EGRESS_CAMERAS` and `CONF_PERIMETER_CAMERAS` are DROPPED from the v1 allowlist (they stay on the reload path — current behavior, zero regression). Wiring `PerimeterAlertManager` to a re-subscribe signal is a parked follow-up.
- D1 method rewritten to enumerate keys from EVERY integration-scoped options-flow step, not just Camera Census.
- `binary_sensor.py:61` classification promoted from "spot-verify" to a definitive D1 verdict.
- Explicit non-goal: NO modification to `_apply_in_place`. Integration branch uses a sibling helper / inline dispatch.
- SAFE-fresh-read rows must cite the caller's config-construction site (proof-of-freshness), not just the read site.
- LOW-1..4 fixes: kill switch skips dispatch, D2 Live checks parent-entry unload, restart-seed AC added, snapshot cleanup site named.

---

## Falsifiable invariant (rev-2)

> **A config-options save on the URA integration (parent) entry whose changed key-set is a subset of the documented `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` allowlist MUST cause zero `config_entries.async_reload` calls against ANY entry (parent, room, or coordinator-manager), MUST NOT unload any entry, MUST NOT enqueue any task whose runtime exceeds ~200 ms on the event loop, AND MUST leave no consumer of a suppressed key retaining a cached view of that key's pre-save value.**

Safety backstops (orthogonal to the invariant — a broken backstop is a separate finding, not an invariant break):
- Persistence: `async_update_entry` has already written `entry.options` before the listener fires.
- Restart-seed: after HA restart, `entry.options[<suppressed key>]` still carries the post-save value (verified in D5 acceptance).
- Fall-through: any change containing a non-allowlisted key still triggers the legacy reload — unchanged safety net.

Reviewer D framing (Tier-3-style completeness pass, run inside the Tier 2-DB Reviewer-C slot): state this invariant, re-enumerate every integration-entry option key currently reachable, and attempt to construct a legal-config save that violates it (cached consumer left stale, reload fires despite allowlist, entry unloaded silently).

---

## Central-question answer (verified this session)

**Q: Why did `camera_person_entities` not benefit from the v4.7.26 / v4.7.27 reload-suppression shipped for the CM entry?**

**A: The shipped `OPTIONS_RELOAD_SUPPRESS_KEYS` mechanism is gated on `entry_type == ENTRY_TYPE_COORDINATOR_MANAGER` (`__init__.py:6431`). Camera keys live on the INTEGRATION (parent) entry — a different entry type with NO suppress branch today. The integration entry's options-save falls straight through to the untracked full reload at `__init__.py:6512-6514`, which cascades to all ~40 child entries.**

Grounded citations:
- `const.py:1305-1307`: `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` (integration-level since v3.4.5 migration at `__init__.py:440-512`).
- `__init__.py:6431-6482`: allowlist checked ONLY inside `if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:`. `_async_update_listener` has no `ENTRY_TYPE_INTEGRATION` branch.
- `__init__.py:6502-6514`: fall-through untracked `async_create_task(hass.config_entries.async_reload(entry.entry_id))` — the Camera Census save hit this.
- `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` defined `const.py:2014`, subscribed at `transit_validator.py:328`, currently **never fired** anywhere in the tree (`_config_signal_unsub` wiring at `transit_validator.py:309-335` is inert). This cycle adds the sole dispatch site.

**Marginal-benefit decomposition:** the SIMPLEST fix that eliminates the observed outage is a single-key allowlist (`CONF_CAMERA_PERSON_ENTITIES`) + integration-entry branch mirroring the CM pattern + one dispatch of the already-wired signal. Marginal risk of expanding the allowlist to egress/perimeter is a real cached-consumer leak (`perimeter_alert.py` — see below); that expansion is parked pending its own wire-up. Marginal risk of a broader async-reload redesign is categorically larger and buys nothing for the observed failure; parked with evidence trigger.

---

## Institutional context verified

### Prior planning docs consulted
- `docs/planning/PLANNING_cm_option_writeback_reload_suppression.md` — shipped v4.7.26/v4.7.27; source of the CM `OPTIONS_RELOAD_SUPPRESS_KEYS` + `_apply_in_place` + snapshot/partial-apply machinery this cycle mirrors (header + design section).
- `docs/planning/PLANNING_room_rename_writethrough.md` — single-listener-fire pattern; confirmed no double-fire hazard.

### Memory bodies pulled
- `feedback_parent_entry_reload_watchdog_hazard` — the class this card belongs to.
- `project_incident_v5_8_0_setup_recursion` — reinforces "Live criterion must observe zero reloads on a real save, not just a unit-test assertion."
- `feedback_suppression_needs_discharge` — every suppressed event specifies what re-fires it; applied per-key in D3.
- `feedback_no_fabrication` — every suppress addition cites a fresh-read line or a discharge signal wire-up.

### Design docs read
- No `docs/Coordinator/CAMERA.md` exists. Module docstrings + `transit_validator.py` §F5/F6 header comments + `perimeter_alert.py` §setup served as the design surface.

### Code locations surveyed (rev-2 — added `perimeter_alert.py` per HIGH-1)
- `custom_components/universal_room_automation/__init__.py`
  - `_async_update_listener` (`:6322-6514`) — ROOM vs CM branch dispatch; fall-through reload at `:6502-6514`.
  - `OPTIONS_RELOAD_SUPPRESS_KEYS` frozen set (`:5775-5960+`).
  - `_apply_in_place` (`:5904-6319`) — CM helper. **REV-2: explicitly out-of-scope for modification.**
  - `_ROOM_SUPPRESS_KEYS` (`:6366-6380`).
- `custom_components/universal_room_automation/const.py` — `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` (`:1305-1307`); `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (`:2014`).
- `custom_components/universal_room_automation/camera_census.py` — `_get_integration_camera_list` (`:1803-1821`), `_get_interior_camera_entities` (`:1787-1801`).
- `custom_components/universal_room_automation/transit_validator.py` — `_config_signal_unsub` wire-up (`:309-335`), `_build_and_subscribe` (`:337-419`).
- `custom_components/universal_room_automation/fan_veto.py:353` — `cam_entities = config.get(CONF_CAMERA_PERSON_ENTITIES) or []` (fresh-read; per-call `config` parameter).
- `custom_components/universal_room_automation/binary_sensor.py:61` — import site; classified in D1.
- **REV-2 ADDED — `custom_components/universal_room_automation/perimeter_alert.py`** — `PerimeterAlertManager.async_setup` at `:410-411` calls `self._resolve_camera_infos(CONF_PERIMETER_CAMERAS)` / `CONF_EGRESS_CAMERAS`, caches `_sensor_platforms` / `_sensor_to_camera` / `perimeter_sensors` / `egress_sensors` for the process lifetime, with NO subscription to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`. Additional read sites `:1622-1623`, `:3783`. This cached-no-refresh path is the reason egress/perimeter keys are OUT of the v1 allowlist.
- `custom_components/universal_room_automation/config_flow.py:2598-2615` — integration-entry options menu (six steps: `global_sensors`, `energy_sensors`, `person_tracking`, `default_notifications`, `camera_census`, `perimeter_alerting`). D1 method walks all six.

### Greps run + results (proposed additions)
- **NEW** `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str]` in `__init__.py`. Grep for name returns zero hits; no equivalent exists. Justification: entry-type-scoped allowlist mirrors the shipped `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:5775`) and the inner `_ROOM_SUPPRESS_KEYS` (`__init__.py:6366`).
- **NEW** module constant `INTEGRATION_RELOAD_SUPPRESS_ENABLED: Final[bool] = True` (rung-1 kill switch). No equivalent.
- **NEW** helper `_dispatch_integration_key_signals(hass, entry, changed_keys)` in `__init__.py`. Sibling to `_apply_in_place`, NOT an extension of it (see MED-2 non-goal).
- **NEW** dispatch table constant `_INTEGRATION_KEY_SIGNAL_TABLE: dict[str, tuple[str, ...]]` mapping the single v1 key to `(SIGNAL_URA_TRANSIT_CONFIG_CHANGED,)`. Rung-1.
- **REUSED** `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` at `const.py:2014` (subscribed at `transit_validator.py:328`; no new signal defined).
- **REUSED** `CONF_CAMERA_PERSON_ENTITIES` at `const.py:1305`.
- **REUSED** snapshot pattern from CM branch (`__init__.py:6447-6482`) — replicated in a new integration-entry branch; CM branch bytes unchanged.

### QUALITY_CONTEXT bug classes to check during build/review
- Suppression-without-discharge (per-key discharge table in D3).
- Untracked background tasks (suppress branch enqueues nothing).
- Concurrent-reload race (snapshot reseed pattern from `__init__.py:6493-6500` is the model).
- Stale-data / cached consumer (Bug Class #7).
- Enum mismatch / computed-but-not-consumed (Classes #22, #53).
- **Bug Class #27 — primary/deferred mirror drift.** Sibling helper (not `_apply_in_place` branch) contains the risk to the integration path.

---

## Deliverables

### D1: Enumerate & classify EVERY integration-entry option key (rev-2 — HIGH-2)

**Description:** Do NOT limit enumeration to Camera Census or to keys currently present in `entry.options`. Enumerate the FULL set an operator could plausibly co-submit with a camera change, because the integration options-flow steps write back `{**existing, **user_input}` per-step (Camera Census example: `config_flow.py:2901`) — every field on the submitted form reaches `async_update_entry`, HA-core short-circuits identical writes, and `changed_keys` is whatever actually differed. A mixed save (allowlisted + non-allowlisted) falls through to reload; hence the allowlist must be scoped with awareness of every key the operator might toggle in the same submit.

**Method (rev-2):**
1. **Static enumeration.** Grep every `async_step_*` method in `config_flow.py` + `options_flow.py` reachable from the integration options menu at `config_flow.py:2598-2615` (six steps: `global_sensors`, `energy_sensors`, `person_tracking`, `default_notifications`, `camera_census`, `perimeter_alerting`). For each step, read its schema builder + submit handler; extract the union of `CONF_*` keys written into `entry.options` via `async_update_entry` (directly or via `async_create_entry` in an options flow).
2. **Live probe.** As a cross-check (per `Measure Before You Build`), dump `integration_entry.options.keys()` from the running HA instance via `ha-mcp` / SSH. Any live key not in the static enumeration is a plan bug (an undiscovered write site).
3. **Per-key classification.** For each key, record:
   - **Consumer(s)** (file:line).
   - **Read style** — `fresh-read-per-tick`, `cached-with-signal-refresh`, `cached-no-refresh`, `requires-reload`. For every `fresh-read` classification, cite BOTH the read site AND the caller's `config`/`options` construction site (proves the caller does not cache — MED-3).
   - **Verdict** — `SAFE` (fresh-read), `SAFE-WITH-DISPATCH` (cached + discharge signal wired today), `NEEDS-DISCHARGE-WORK` (cached with no refresh path — parked follow-up), `UNSAFE` (requires-reload — stays out of allowlist).

**Deliverable file:** `docs/planning/AUDIT_integration_options_reload_classification.md`. This is the fixture the D2 allowlist is diffed against (per `hand-build-fixture` corollary). Committed BEFORE D2 code is written.

**Known verdicts (seeds — the full table is D1's job to complete):**

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_CAMERA_PERSON_ENTITIES` | camera_census.py:1803-1821 (fresh, `merged = {**data, **options}` per call); transit_validator.py:394 (cached subs, discharged by `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`); fan_veto.py:353 (fresh, per-call `config` param — build to cite caller construction site per MED-3) | SAFE-WITH-DISPATCH | **v1 allowlist member** |
| `CONF_EGRESS_CAMERAS` | camera_census.py fresh; transit_validator.py:394 discharged; **perimeter_alert.py:411, 1622-1623, 3783 CACHED at setup, no signal subscription** | NEEDS-DISCHARGE-WORK | **DROPPED from v1 allowlist** — see HIGH-1 disposition |
| `CONF_PERIMETER_CAMERAS` | camera_census.py fresh; transit_validator.py:394 discharged; **perimeter_alert.py:410, 1622-1623, 3783 CACHED at setup, no signal subscription** | NEEDS-DISCHARGE-WORK | **DROPPED from v1 allowlist** — see HIGH-1 disposition |
| `binary_sensor.py:61 import of CONF_CAMERA_PERSON_ENTITIES` | grep of the symbol name inside `binary_sensor.py` returns only the import at `:61`; entity-key literal `"camera_person_detected"` at `:1155` is unrelated | **DEAD IMPORT (pending D1 confirmation)** | MED-1 — D1 AC below produces the DEFINITIVE verdict (dead-import → build removes it in the same cycle as a hygiene follow-on; live consumer → reclassify the key) |
| all other integration-level `CONF_*` from the six options-flow steps | TBD by D1 | TBD | TBD |

**Non-v1 allowlist candidates surface as parked follow-ups**, each with an evidence trigger (see "Parked follow-ups" section).

### Acceptance Criteria (D1)
- **Doc:** `AUDIT_integration_options_reload_classification.md` exists, one row per key from the STATIC enumeration union with the LIVE probe (both sources cited).
- **Verify:** every `SAFE` row cites both the read site AND the caller's `config`/`options` construction site.
- **Verify:** every `SAFE-WITH-DISPATCH` row cites the cache site AND the signal-subscribe site.
- **Verify:** every `NEEDS-DISCHARGE-WORK` row names the cached consumer, the missing refresh mechanism, AND is added to "Parked follow-ups" with an evidence trigger.
- **Verify:** definitive verdict on `binary_sensor.py:61` — either "dead import; build removes the import in the same PR" OR "live consumer at file:line; reclassify accordingly." No "spot-verify" or "deferred to build" resolution.
- **Verify:** every integration-level `CONF_*` written by any step reachable from `config_flow.py:2602` appears in the table.

---

### D2: Add `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` + integration-entry branch in `_async_update_listener`

**Description:** Mirror the CM pattern in `__init__.py`, with the integration branch's suppress path calling a **sibling helper** (not extending `_apply_in_place`):

1. Module-level rung-1 `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str]` populated from the D1 `SAFE` + `SAFE-WITH-DISPATCH` rows. **v1 seed = `{CONF_CAMERA_PERSON_ENTITIES}` only** (egress + perimeter parked per HIGH-1 disposition; other D1-classified SAFE keys added iff their consumer proof is airtight).
2. Module-level rung-1 kill switch `INTEGRATION_RELOAD_SUPPRESS_ENABLED: Final[bool] = True`.
3. Module-level rung-1 `_INTEGRATION_KEY_SIGNAL_TABLE: dict[str, tuple[str, ...]]` — for each allowlisted key, the tuple of dispatcher signals to fire on suppress. v1: `{CONF_CAMERA_PERSON_ENTITIES: (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,)}`.
4. In `_async_update_listener`, add a NEW branch `if entry_type == ENTRY_TYPE_INTEGRATION:` mirroring the CM branch's snapshot + subset-check + suppress-log + return pattern:
   - Snapshot dict `integration_last_applied_options` under `hass.data[DOMAIN]`.
   - Compute `changed_keys` via old/new diff (same shape as CM branch, `__init__.py:6447-6460`).
   - If `changed_keys` empty → return.
   - **Kill-switch gate (LOW-1):** if `INTEGRATION_RELOAD_SUPPRESS_ENABLED` is False, skip the suppress branch entirely (no dispatch, no snapshot advance) and fall through to legacy reload. Do NOT dispatch signals with kill switch off — the reload rebuilds subscriptions naturally; a parallel dispatch doubles the work and confuses logs.
   - If kill switch True AND `changed_keys ⊆ INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`:
     - Call `_dispatch_integration_key_signals(hass, entry, changed_keys)` (D3).
     - Log at INFO mirroring CM branch log (`__init__.py:6462-6466`): `INTEGRATION options changed for '<title>' (<entry_id>) — in-place apply, suppressing reload (changed_keys=<sorted list>)`.
     - Update snapshot per the CM partial-apply pattern (`__init__.py:6475-6481`); for v1 apply-set == changed-set (dispatch-only, no live-attr push) but keep the shape for future cached-consumer additions.
     - `return`.
   - Mixed / non-allowlisted → reseed snapshot per CM branch (`__init__.py:6493-6500`) and fall through to the existing reload at `__init__.py:6502-6514`.
5. The branch runs BEFORE the fall-through reload; no changes to ROOM branch, CM branch, or `_apply_in_place`.

**Rung-ladder placement (per `numbers-get-knobs`):**
| Knob | Rung | Rationale |
|---|---|---|
| `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` | 1 (module constant) | Adding/removing a key changes lifecycle safety; requires review. |
| `INTEGRATION_RELOAD_SUPPRESS_ENABLED` | 1 (module constant) | Fire-axe; turning it off re-enables the outage — must require review. |
| `_INTEGRATION_KEY_SIGNAL_TABLE` | 1 (module constant) | Wiring table. |

### Acceptance Criteria (D2)
- **Test:** `quality/tests/test_reload_watchdog_hazard.py::test_integration_options_suppress_reload_on_camera_person_entities` — mocked/spied `hass.config_entries.async_reload` is NOT called when an integration-entry options update changes only `CONF_CAMERA_PERSON_ENTITIES`.
- **Test:** `::test_integration_options_mixed_falls_through_to_reload` — allowlisted + non-allowlisted change calls `async_reload` exactly once.
- **Test:** `::test_kill_switch_disables_suppress_and_skips_dispatch` — with `INTEGRATION_RELOAD_SUPPRESS_ENABLED = False`, `async_reload` fires AND `_dispatch_integration_key_signals` is NOT called (LOW-1).
- **Test:** `::test_egress_perimeter_keys_not_in_allowlist_v1` — pin the v1 allowlist size / membership so a future silent addition of egress/perimeter without HIGH-1 discharge work fails a test.
- **Live:** operator triggers a Camera Census save (one entity added/removed from `camera_person_entities`) via the URA options flow. Expected within the same save:
  - Exactly one log line matching `INTEGRATION options changed for .* — in-place apply, suppressing reload (changed_keys=['camera_person_entities'])`.
  - Zero `Options changed for '...', scheduling reload` lines for the URA integration entry.
  - **(LOW-2) Zero unload log lines for the URA integration (parent) entry itself.** (Parent-only reload with no child cascade is still an invariant break.)
  - Zero unload/setup log lines for any URA child entry within 60s after the save.
  - No supervisor watchdog message and no HA core restart.

---

### D3: Wire `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` dispatch for the v1 allowlisted key

**Description:** Sibling helper `_dispatch_integration_key_signals(hass, entry, changed_keys)` in `__init__.py` (NOT an extension of `_apply_in_place` — see MED-2 non-goal). For each `key in changed_keys` present in `_INTEGRATION_KEY_SIGNAL_TABLE`, fires each signal in the tuple via `async_dispatcher_send`. Per-signal `try/except` mirrors the CM branch's defensive posture (`__init__.py:6416-6420`): a failed dispatch logs WARNING and does NOT re-raise (persistence already succeeded; suppressing the exception is preferable to converting a persisted write into an outage-inducing reload).

**Camera Census itself needs no signal** — `_get_integration_camera_list` reads `entry.options` fresh on every invocation (`camera_census.py:1812-1820`). Same for `fan_veto.py:353` (per-call `config` parameter — build to cite caller construction sites per MED-3). The signal is exclusively for `transit_validator`'s cached subscription set.

**Discharge contract (rev-2 — v1 allowlist only):**

| Suppressed key | Consumer path | Refresh mechanism | Backstop |
|---|---|---|---|
| `camera_person_entities` | camera_census fresh read; transit_validator cached subs | fresh read (census); `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (transit) | HA restart re-seeds from `entry.options` |

`egress_cameras` and `perimeter_cameras` are NOT in this table because they are NOT in the v1 allowlist. See "Parked follow-ups" for the wire-up plan when the trigger fires.

### Acceptance Criteria (D3)
- **Test:** `::test_camera_person_entities_change_dispatches_transit_signal_once` — one `async_dispatcher_send(SIGNAL_URA_TRANSIT_CONFIG_CHANGED, …)` per suppressed save.
- **Test:** `::test_kill_switch_off_skips_dispatch` (shared with D2 LOW-1).
- **Test:** per-site mutation drill (per `feedback_hollow_test_anchors`) — remove the dispatch line for `CONF_CAMERA_PERSON_ENTITIES` from the wiring table; confirm `::test_camera_person_entities_change_dispatches_transit_signal_once` fails BY NAME (not aggregate suite green). Restore + status-check.
- **Live:** post-save, `TransitValidator subscriptions built: %d camera entities…` log line appears within 5 seconds of the save (matches `_schedule_rebuild` debounce). Camera-count delta matches the operator's change.

---

### D4: Snapshot / partial-apply parity + concurrent-write safety

**Description:** Reuse the CM branch's snapshot pattern under a new key `hass.data[DOMAIN]["integration_last_applied_options"]` with the same reseed-on-fall-through discipline (`__init__.py:6493-6500`). No modification to CM's `cm_last_applied_options` bookkeeping.

**Snapshot cleanup (rev-2, LOW-4):** the CM branch's snapshot at `hass.data[DOMAIN]["cm_last_applied_options"]` is NOT actively cleaned on entry unload today (grep of `cm_last_applied_options` in `__init__.py` shows write sites in the listener only — no `pop` on unload). The leak is bounded: one dict per CM entry, cleared naturally when `hass.data[DOMAIN]` is torn down at integration unload. **The integration-entry snapshot follows the same convention**, documented inline: "`integration_last_applied_options` is not cleaned on entry unload; the leak is one dict per integration entry (there is exactly one) and is cleared at integration teardown. Matches the CM branch's convention documented at `__init__.py:6447` (write-only). If a future cycle changes CM cleanup, mirror it here." Build to add an inline comment at both the CM and integration snapshot write sites recording this shared convention.

### Acceptance Criteria (D4)
- **Test:** back-to-back saves of the same allowlisted key produce a single suppress-log line pair with no reload; snapshot advances between them.
- **Test:** save-A (allowlisted) followed within 100ms by save-B (mixed) → suppress-A + reload-once-for-B; no double-reload; snapshot pre-save-B equals post-save-A.

---

### D5: Kill switch, observability, restart-seed backstop

**Description:**
- Rung-1 `INTEGRATION_RELOAD_SUPPRESS_ENABLED` constant (see D2 kill-switch gate — skips both suppress AND dispatch per LOW-1).
- Log-line grep contract (D2 log wording) is the observability primitive. No new sensor.
- QUALITY_CONTEXT candidate new bug class: "integration-entry cascade" (subclass of "parent reload watchdog hazard"). Reviewer's call whether to promote in `docs/QUALITY_CONTEXT.md`.

### Acceptance Criteria (D5)
- **Verify:** `INTEGRATION_RELOAD_SUPPRESS_ENABLED = False` restores legacy behavior AND skips dispatch (D2 tests).
- **Live (LOW-3 restart-seed backstop):** after the D2 live save + `homeassistant.restart`, read `entry.options[camera_person_entities]` from `.storage/core.config_entries` (or via `ha-mcp`); assert it still contains the operator's post-save value. This is a safety-backstop verification, not an invariant clause — a failure here indicates a persistence bug, not a suppress bug.
- **Verify:** `README_v<version>.md` is written pre-deploy with a prospective Live block AND updated post-restart with the observed suppress-log + zero-reload + zero-parent-unload + restart-seed evidence (per `Record Live Validation Back Into the README`).

---

## Parked follow-ups (evidence-triggered)

Per Marginal-Benefit Decomposition: park elaborate work, don't delete it.

1. **Wire `PerimeterAlertManager` to a re-subscribe signal → promote `CONF_EGRESS_CAMERAS` + `CONF_PERIMETER_CAMERAS` to v2 allowlist.** Trigger: operator hits the ~5min outage on an egress- or perimeter-camera-only save AND wants it suppressed. Approach: mirror `transit_validator._build_and_subscribe` teardown-and-rebuild in `PerimeterAlertManager` (`perimeter_alert.py:410-448`), subscribing to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (or a new sibling signal if finer granularity is warranted — `PerimeterAlertManager` holds in-flight dispatch state that transit_validator does not, so signal granularity is a real design choice). This is its own carefully-reviewed cycle (Tier 2-DB in its own right — dispatch-state migration).
2. **Broader async-reload redesign** (staged unload, per-child throttling, coalescing). Trigger: a future integration-level key genuinely REQUIRES a reload AND causes the same outage.
3. **`binary_sensor.py:61` cleanup** (if D1 confirms dead import). Trigger: D1 verdict is "dead import" → build removes the import in the same PR as a same-cycle hygiene fix (does not need a separate cycle).
4. **Additional D1-classified `SAFE`/`SAFE-WITH-DISPATCH` keys not admitted to v1 allowlist.** Trigger: operator hits reload on a genuinely-safe key; admit it to v1 in a small follow-on with a per-key discharge audit.

---

## Non-goals (explicit — rev-2)

- **NO** redesign of the async reload machinery — parked #2.
- **NO** change to CM-entry `OPTIONS_RELOAD_SUPPRESS_KEYS` or `_apply_in_place`. **`_apply_in_place` is byte-identical after this cycle (MED-2).** Integration branch uses a sibling helper (`_dispatch_integration_key_signals`) exclusively.
- **NO** change to ROOM-entry `_ROOM_SUPPRESS_KEYS`.
- **NO** change to the fall-through reload for entries/keys still on the reload path — it is the safety net.
- **NO** `PerimeterAlertManager` modifications in this cycle — parked #1.
- **NO** `CONF_EGRESS_CAMERAS` / `CONF_PERIMETER_CAMERAS` in the v1 allowlist — parked #1.
- **NO** new user-facing entity / knob / sensor. Kill switch is code-only.
- **NO** back-compat scaffolding (per `Single User No Back-Compat`).
- **NO** migration; snapshot dict initializes empty on first observation.

---

## Tier & review

**Tier 2-DB** (standing policy for regression-prone lifecycle change).

**Three framing-disjoint reviews before deploy:**
- **Review A — Correctness + per-key discharge.** Walk every v1-allowlisted key; re-verify fresh-read or signal-refresh via independent grep. Walk `_dispatch_integration_key_signals`. Confirm no cached consumer missed. Re-run the whole-repo grep of `CONF_CAMERA_PERSON_ENTITIES` and re-classify against D1's audit — any drift blocks ship.
- **Review B — Lifecycle + concurrency.** Snapshot ownership and reseed timing; interaction with HA-core's `async_update_entry` short-circuit; mixed save arriving during a suppressed dispatch; restart-seed correctness; snapshot leak-bound (D4 documentation is accurate).
- **Review C — Fixture / test authority + adversarial completeness (Reviewer D framing).** Confirm tests exercise the real listener code path (not a monkeypatched fake). Per-site source-mutation drill on the dispatch line, the subset check, AND the kill-switch gate — each must be independently load-bearing. Adversarial completeness pass: state the invariant, re-enumerate every integration-entry key currently reachable (not only diff-affected), attempt to construct a legal-config save that violates it. **Explicitly re-check `perimeter_alert.py` and any other post-plan-review addition** to confirm the v1 allowlist boundary is honored.

If any pass finds CRITICAL/HIGH: fix, re-run per-site mutation on the fixed site, re-run C's enumeration.

**Post-deploy Live validation** = D2 + D3 + D5 Live criteria observed on the running house and written back into `README_v<version>.md`.

---

## Files touched (build cycle — this is the docs-only plan)

- `custom_components/universal_room_automation/__init__.py` — new constants, new integration-entry branch in `_async_update_listener`, `_dispatch_integration_key_signals` sibling helper. **`_apply_in_place` unchanged.**
- `custom_components/universal_room_automation/binary_sensor.py` — MAY remove the `CONF_CAMERA_PERSON_ENTITIES` import iff D1 confirms dead-import (MED-1).
- `quality/tests/test_reload_watchdog_hazard.py` — NEW test module.
- `docs/planning/AUDIT_integration_options_reload_classification.md` — NEW (D1 output).
- `docs/readmes/README_v<version>.md` — created pre-deploy, updated post-Live.
- `docs/QUALITY_CONTEXT.md` — potential new-bug-class entry (reviewer's call).

---

## Plan-completion tracking

Nothing deferred at rev-2 plan time. Parked follow-ups (above) are cataloged separately with evidence triggers.

---

## Appendix — Plan-review finding dispositions (rev-2)

Against `docs/reviews/code-review/reload_watchdog_plan_review.md` @ `bf8ee9f65`:

| # | Sev | Disposition |
|---|---|---|
| HIGH-1 | FIXED (Option B per operator adjudication) | `CONF_EGRESS_CAMERAS` + `CONF_PERIMETER_CAMERAS` DROPPED from v1 allowlist; `perimeter_alert.py` added to Institutional-context "Code locations surveyed"; wire-up parked with evidence trigger (follow-up #1). D3 discharge table reflects v1-only. |
| HIGH-2 | FIXED | D1 method rewritten to enumerate keys from every `ENTRY_TYPE_INTEGRATION` options-flow step reachable from `config_flow.py:2602` (all six steps named); live probe added as cross-check; four seeds explicitly marked as examples not the list; per-key SAFE/SAFE-WITH-DISPATCH/NEEDS-DISCHARGE-WORK/UNSAFE verdicts required. |
| MED-1 | FIXED | D1 AC now requires DEFINITIVE verdict on `binary_sensor.py:61` (dead-import or live consumer); "spot-verify"/"deferred to build" language removed. Dead-import cleanup path added to Files-touched. |
| MED-2 | FIXED | Non-goal added: `_apply_in_place` byte-identical. Build MUST use sibling helper `_dispatch_integration_key_signals`; no entry-type branch inside `_apply_in_place`. Bug Class #27 cited. |
| MED-3 | FIXED | D1 AC requires every SAFE row to cite BOTH read site AND caller's `config`/`options` construction site (`fan_veto.py:353` example called out). |
| LOW-1 | FIXED | D2 kill-switch gate explicitly skips both suppress and dispatch; test `::test_kill_switch_disables_suppress_and_skips_dispatch` added. |
| LOW-2 | FIXED | D2 Live now asserts zero unload log lines for the integration (parent) entry itself, in addition to child entries. |
| LOW-3 | FIXED | D5 adds restart-seed Live check via `.storage/core.config_entries` (or `ha-mcp`). |
| LOW-4 | FIXED | D4 documents snapshot cleanup: CM branch does not clean up either (grep result); leak is bounded (one dict per entry, cleared at integration teardown); build to add matching inline comment at both CM and integration snapshot sites. |
| Invariant amendment #1 | ACCEPTED | "No cached view" clause promoted from corollary into the invariant proper. |
| Invariant amendment #2 | ACCEPTED | Restart-seed split out as a safety backstop, not an invariant clause. |
| Non-goal addition | ACCEPTED | See MED-2 disposition. |
