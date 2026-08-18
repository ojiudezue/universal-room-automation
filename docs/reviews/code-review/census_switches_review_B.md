# Census device-switches — Review B (reload-suppress + signal-chain integrity)

- Cycle: CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1
- Branch: `feature/census-toggles-switches` (commit `fb6f771a1`)
- Baseline: `develop` (three-dot diff)
- Framing: Tier 2-DB Review B — the load-bearing safety property "a
  switch toggle MUST NOT reload the parent integration entry" (the
  2026-06-03 / 2026-08-07 watchdog-outage hazard), plus discharge
  correctness for the newly-cached consumer flag.
- Verdict: **SHIP** (2 LOW, 0 MED/HIGH/CRITICAL).

---

## Load-bearing invariant (falsifiable form)

For any operator toggle of either
`switch.ura_presence_face_matching` or `switch.ura_name_people_at_doors`,
in ANY reachable path (fresh install, post-restart first save, options-flow
also editing the same key, combined switch+options edit), the resulting
`_async_update_listener` invocation MUST reach the
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` suppress branch and MUST
NOT schedule `hass.config_entries.async_reload(entry.entry_id)`. AND
every cached consumer of `CONF_FACE_RECOGNITION_ENABLED` must observe
the new value on the next natural read after the toggle without a
restart.

Attempt to falsify: **could not.** Detailed trace below.

---

## Verified independently (greps + reads, not the plan)

### Suppress-path correctness

- `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` at `__init__.py:5933-5951`
  contains both keys via imported `const` symbols (no string
  duplication) — `CONF_FACE_RECOGNITION_ENABLED`,
  `CONF_EGRESS_IDENTITY_ENABLED`, plus the pre-existing
  `CONF_CAMERA_PERSON_ENTITIES`.
- Listener check at `__init__.py:6668-6680`:
  `changed_keys.issubset(INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS)`
  short-circuits with a `return` before the fall-through
  `hass.async_create_task(hass.config_entries.async_reload(...))` at
  `:6699-6701`. Both new keys are members of the frozenset → subset
  passes for any single-key toggle AND for a combined two-key
  options-flow write.
- Kill-switch gate `INTEGRATION_RELOAD_SUPPRESS_ENABLED` at
  `:5965` correctly wraps the whole branch (`:6668`); flipping it False
  routes both new keys through the reload path — intended behaviour.
- First-post-restart cold-boot hazard (H-1) — verified separately:
  `_seed_integration_last_applied_options` is called at
  `__init__.py:3881` BEFORE `entry.add_update_listener(...)` at `:3884`,
  so the snapshot is populated by the time the first switch toggle
  fires. Confirmed by the existing test
  `test_seed_helper_call_node_exists_in_integration_setup_ast` (AST
  anchor, comment-invisible). Without this the FIRST toggle after a
  restart would compute `changed_keys` against `old={}` and blow the
  subset check.

### Signal-chain integrity (face-recognition)

Producer: `switch.py:_IntegrationOptionsSwitch._write` (:558-583) fires
`async_dispatcher_send(hass, SIGNAL_URA_FACE_RECOGNITION_CHANGED,
entry.entry_id, conf_key)` AFTER `async_update_entry` persists. The
listener ALSO fires the same signal via
`_dispatch_integration_key_signals(hass, entry, changed_keys)` at
`__init__.py:6675` reading `_INTEGRATION_KEY_SIGNAL_TABLE`
(`CONF_FACE_RECOGNITION_ENABLED → (SIGNAL_URA_FACE_RECOGNITION_CHANGED,)`).
Dual-fire is safe:

- Both subscribers' handlers merge `{**cfg.data, **cfg.options}` and
  set `self._face_recognition_enabled = merged.get(...)`. Both fires
  see the same persisted value, so the second is a no-op re-write.
- Info log only fires when `previous != new` — first fire logs the
  transition, second fire finds `previous == new` and logs nothing.
- `try/except` around `async_dispatcher_send` in the switch is safe
  (falls back to `_LOGGER.debug`, does not re-raise).

Subscribers (exhaustive re-grep, not the plan's list):

- `transit_validator.py:384` — `self._face_recog_signal_unsub =
  async_dispatcher_connect(hass, SIGNAL_URA_FACE_RECOGNITION_CHANGED,
  _on_face_recognition_changed)`.
- `presence.py:2500-2506` — `self._unsub_listeners.append(
  async_dispatcher_connect(hass, SIGNAL_URA_FACE_RECOGNITION_CHANGED,
  _on_face_recog_changed))`.

Consumer sites of the cached flag (proves the refresh covers all
reads):

- `transit_validator.py:603, 825` — `if self._face_recognition_enabled`
  (also boot-log at `:476`).
- `presence.py:4524` — `if detected and matched_zone_name and
  self._face_recognition_enabled`.

Every read goes through the instance attribute, so a fresh assignment
by the signal handler updates the trust decision on the very next
tick. No stale-closure or module-level cache found.

### Subscription cleanup (ghost-listener check)

- `transit_validator.py:882-891` (teardown block) — try/except calls
  `self._face_recog_signal_unsub()` and resets to `None`. Mirrors the
  sibling `_config_signal_unsub` teardown pattern one block above.
- `presence.py` — the new subscription is appended to
  `self._unsub_listeners`, which is iterated by
  `domain_coordinators/base.py:289-291` (`for unsub in
  self._unsub_listeners: unsub()`). Cleanup verified upstream in the
  base class; no per-listener changes needed.

Re-init idempotency: `TransitValidator.async_init` re-assigns
`self._face_recog_signal_unsub` without first calling the old unsub.
This mirrors the pre-existing `self._config_signal_unsub` pattern
(same file, same handler, in production for months without leak
reports). `async_init` is called once per entry-load; the rebuild path
goes through `_build_and_subscribe`, which is untouched. Not raising
as a finding since the surface predates the cycle and behaves
identically.

### Egress-identity fresh-read discipline

Every consumer of `CONF_EGRESS_IDENTITY_ENABLED` calls
`camera_census._is_egress_identity_enabled()` at read time, which
re-merges `entry.data | entry.options` per call
(`camera_census.py:2858-2870`). Consumer sites: `camera_census.py:1886,
2889, 2943, 3657` and `transit_validator.py:1158`. No cached copy
found. Egress correctly excluded from `_INTEGRATION_KEY_SIGNAL_TABLE`;
a dispatch would be dead. Test
`test_d3_egress_toggle_does_not_fire_any_signal` locks this in.

### Restart behavior

On restart, `TransitValidator.__init__` sets
`self._face_recognition_enabled = False` at `:197`; `async_init` then
re-reads from options at `:263-267` using
`DEFAULT_FACE_RECOGNITION_ENABLED` when unset. Presence follows the
same shape at `:2451-2467`. Both consumers therefore boot with the
persisted value; no signal needed at boot.

### Structural-branch safety

Grep confirmed neither `CONF_FACE_RECOGNITION_ENABLED` nor
`CONF_EGRESS_IDENTITY_ENABLED` gates a setup-time structural branch
(unlike `CONF_ENHANCED_CENSUS` at `__init__.py:2253`). Both are runtime
decision flags only. Test `test_enhanced_census_not_exposed_as_switch`
locks in the deliberate exclusion.

### Reload-absence test quality

`test_d3_switch_does_not_call_async_reload` is non-hollow: it wires a
real `_IntegrationOptionsSwitch` against a fake `hass.config_entries`
that records `async_reload` at call-time and asserts `reload_calls ==
[]`. A belt-and-suspenders AST anchor also asserts that the class
source contains no `.async_reload(` substring. Combined with
`test_egress_perimeter_keys_not_in_allowlist_v1` (size-locked
allowlist: `{camera_person_entities, face_recognition_enabled,
egress_identity_enabled}`) the invariant is well-anchored.

The listener-level end-to-end suppress test (in
`test_reload_watchdog_hazard.py`) still exercises only the
`camera_person_entities` key. This is a minor gap — see LOW-2.

---

## Findings

### LOW-1 — Stale docstring in `_is_egress_identity_enabled`

- File: `custom_components/universal_room_automation/camera_census.py:2860`
- Text: `"""Read the EGRESS_IDENTITY_ENABLED kill switch from options
  (2026-08-18). Default False (dormant) — see const.py rationale."""`
- Reality: `DEFAULT_EGRESS_IDENTITY_ENABLED` was flipped to `True` in
  `const.py:2174` in this same cycle. The comment now misleads a future
  reader about the safe-default direction.
- Fix: replace "Default False (dormant)" with "Default True (surfaced as
  device switch; the switch itself is the operator's live kill-switch)"
  or similar. One-line edit.
- Bug class: doc/comment drift (not behavior). Not a ship blocker.

### LOW-2 — No listener-level end-to-end suppress test for the two new keys

- File: `quality/tests/test_reload_watchdog_hazard.py`
- Observation: the listener suppress + dispatch behavioural tests
  (`test_integration_options_suppress_reload_on_camera_person_entities`,
  `test_camera_person_entities_change_dispatches_transit_signal_once`,
  `test_wiring_table_entry_is_load_bearing_for_transit_signal_dispatch`)
  are parametrised only over `CONF_CAMERA_PERSON_ENTITIES`.
- Consequence: a future refactor that rearranged the allowlist or the
  signal-table lookup so the new keys took a different branch would
  still ship green. The allowlist size-guard test
  (`test_egress_perimeter_keys_not_in_allowlist_v1`) partially covers
  this by pinning the exact contents, and the switch-level test
  `test_d3_switch_does_not_call_async_reload` covers end-to-end from the
  switch side — but no test drives the listener directly with
  `changed_keys={"face_recognition_enabled"}` or
  `{"egress_identity_enabled"}` to prove the suppress branch still
  fires. Since the listener is data-driven (subset check + table
  lookup) and the pre-existing `camera_person_entities` test exercises
  the same code path, the incremental risk is small.
- Fix: add two parameterised listener tests — one per new key —
  mirroring the shape of the existing camera-person test, asserting
  `reload_calls == []` and (for face-recog only) `dispatched ==
  ["ura_face_recognition_changed"]`. ~30 LoC.
- Bug class: test authority — additive coverage. Not a ship blocker.

---

## Findings summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| CRITICAL | 0     | 0     | 0        |
| HIGH     | 0     | 0     | 0        |
| MEDIUM   | 0     | 0     | 0        |
| LOW      | 2     | 0     | 2        |

Bug-class frequency (this review): doc-drift × 1, test-authority × 1.

---

## Verdict

**SHIP.** The load-bearing invariant "switch toggle → no parent reload"
holds under adversarial trace of every reachable path I could
construct, and the discharge signal correctly refreshes both cached
consumers with idempotent dual-fire semantics. The two LOWs are
comfortably deferrable to a fast-follow (either can be a one-line /
30-LoC patch in the next cycle touching this surface).
