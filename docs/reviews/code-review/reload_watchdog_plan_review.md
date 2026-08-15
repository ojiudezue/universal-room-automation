# PLAN REVIEW — RELOAD-WATCHDOG-HAZARD (Tier 2-DB, adversarial)

**Plan under review:** `docs/planning/PLANNING_reload_watchdog_hazard.md` @ commit `392ae0ed9` (develop).
**Reviewer framing:** independent re-enumeration of the emission/consumer surface; verify the
central claim by grep; break the falsifiable invariant with a legal-config reachable repro.
Findings verified from repo, not from the plan's own citations.

**Verdict:** **CHANGES REQUESTED — DO-NOT-DISPATCH-BUILD.** Two HIGH findings must be fixed
in-plan first: one uncatalogued cached consumer (`perimeter_alert.py`) which — if the plan
shipped as-written — would silently leave perimeter/egress alerts subscribed to a stale
camera set; and a D1 seed-key set that is materially incomplete for the incident's exact
reproducer form. Everything else is fixable in-plan with a paragraph.

---

## Verification of the plan's load-bearing claims

### Claim 1 — CM branch is entry-type-gated; INTEGRATION entry has no branch. ✅ CONFIRMED.
`__init__.py:6337` reads `entry_type = entry.data.get(CONF_ENTRY_TYPE)`. ROOM branch at
`:6382-6429`. CM branch at `:6431-6500` — allowlist test is inside `if entry_type ==
ENTRY_TYPE_COORDINATOR_MANAGER:` (`:6431` + subset check at `:6461`). Fall-through untracked
`async_reload` at `:6502-6514`. **No `ENTRY_TYPE_INTEGRATION` branch exists.** The Camera
Census save the operator described hits exactly the fall-through — plan's mechanism is
correct.

### Claim 3 — `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` exists, is subscribed, is currently inert. ✅ CONFIRMED.
Defined at `const.py:2014`. Subscribed at `transit_validator.py:328` via
`async_dispatcher_connect`, callback `_on_config_changed` → `_schedule_rebuild`
(`:322-326`). Grep for `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` returns exactly one subscriber
and zero `async_dispatcher_send` sites → the signal is currently defined-but-never-fired.
Wiring it in the new integration-entry branch discharges TransitValidator correctly.

### Claim (implicit) — enumerating camera-key consumers. ⚠️ PARTIAL.
The plan enumerates `camera_census.py`, `transit_validator.py`, `fan_veto.py`,
`binary_sensor.py`. Grep across the tree surfaces **one additional load-bearing consumer
the plan missed entirely: `perimeter_alert.py`.** See HIGH-1.

Full grep matrix for the three camera keys (import + usage sites, excluding docstrings /
migration / config-flow / const):

| File | Sites | Read style | In plan? |
|---|---|---|---|
| `camera_census.py` | `:1024, :1031, :1466-1467, :1801` | fresh read via `_get_integration_camera_list` on every invocation | yes |
| `transit_validator.py` | `:394, :898` inside `_build_and_subscribe` | cached subs; discharged by `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` | yes |
| `fan_veto.py` | `:353` `config.get(...)` where `config` is a per-call param | fresh read | yes |
| `binary_sensor.py` | `:61` import only — grep shows no usage of the symbol elsewhere in the file | dead import (see MEDIUM-1) | flagged |
| `__init__.py` | `:465, :485, :496, :508, :2213-2215` (migration + census-count seed) | boot/migration path only, not runtime | n/a |
| **`perimeter_alert.py`** | **`:410-411` (setup-time), `:1622-1623`, `:3783` `_resolve_camera_infos`** | **CACHED at `async_setup`; `_sensor_platforms`/`_sensor_to_camera` dicts populated once; NO signal subscription** | **NO** |

---

## Findings

### HIGH-1 — Uncatalogued cached consumer: `perimeter_alert.py` on `CONF_EGRESS_CAMERAS` + `CONF_PERIMETER_CAMERAS`. Falsifies the invariant.

`PerimeterAlertManager.async_setup` (`perimeter_alert.py:410-411`) calls
`self._resolve_camera_infos(CONF_PERIMETER_CAMERAS)` / `..._EGRESS_CAMERAS` once at setup,
then wires per-camera subscriptions and caches `_sensor_platforms` / `_sensor_to_camera` /
the `perimeter_sensors` + `egress_sensors` lists (`:429-448`). Grep for
`SIGNAL_URA_TRANSIT_CONFIG_CHANGED` in that file: **zero matches.** Grep for any
`async_dispatcher_connect` in the file returns `:616` (linker-ready, unrelated) and `:669`
(unsub of same) — nothing that would rebuild camera subscriptions on options change.

**Reachable legal-config repro breaking the plan's invariant** (Reviewer-D-style):
1. Operator opens URA options → Camera Census step, adds a new IP camera to
   `perimeter_cameras`, clicks Submit.
2. Options-flow writes `{**existing, ..., CONF_PERIMETER_CAMERAS: [+new_cam]}`.
3. Under the plan as-written, `changed_keys == {CONF_PERIMETER_CAMERAS}` ⊆ allowlist → CM-style
   suppress fires, dispatch of `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` runs.
4. `TransitValidator._schedule_rebuild()` picks up the new camera. ✅
5. `PerimeterAlertManager` is NOT subscribed to that signal → keeps its old
   `perimeter_sensors` list. **New camera's person-detection sensor never generates a
   perimeter alert** until an unrelated HA restart or an unrelated options save that goes
   through the mixed/reload path.
6. Symmetric failure on removal: a removed camera stays subscribed; its stale ON state
   could fire spurious alerts.

The plan's discharge table (D3) lists both keys as
`camera_census fresh read; transit_validator cached subs → fresh read + signal` — this is
**incomplete**; it must list `perimeter_alert cached subs → NO refresh path today`. This is
exactly the "cached-no-refresh = UNSAFE" class the invariant's corollary #4 flags.

The Institutional Context section's "Code locations surveyed" list omits `perimeter_alert.py`
entirely; that omission is the process failure that let the miss through.

**Required fix (choose one, before build dispatch):**

- **Option A (preferred, mirrors transit_validator):** add a small D3 sub-deliverable —
  `PerimeterAlertManager` subscribes to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (or a sibling
  signal if the plan wants finer granularity) and re-runs the camera-info resolution +
  subscription rebuild in the same idempotent teardown-and-rebuild pattern
  `transit_validator._build_and_subscribe` uses (`:337-419`). Update the D3 discharge table
  row to cite both subscribers.
- **Option B (defensible, smaller):** EXCLUDE `CONF_EGRESS_CAMERAS` and
  `CONF_PERIMETER_CAMERAS` from the D2 allowlist. Only `CONF_CAMERA_PERSON_ENTITIES` (whose
  cached consumer, TransitValidator, IS discharged) gets suppressed. Egress/perimeter keys
  keep going through the reload path — accepts the outage on those two keys as future work.
  Faster to ship, does not fully solve the operator's incident since it originated on
  `camera_person_entities` only, but it does not regress perimeter safety.

**D1 acceptance criterion added:** every candidate allowlist key MUST show a
whole-repo grep of its symbol against every `.py` file with the columns above; a key with a
cached consumer that has no signal subscription is UNSAFE by default (not
`SAFE-WITH-DISPATCH`).

### HIGH-2 — D1 seed key-set is materially incomplete; incident's actual reproducer form writes 9+ keys, not 4.

The plan's D1 "Known-in-scope keys (seed)" lists 4:
`camera_person_entities, egress_cameras, perimeter_cameras, face_recognition_enabled`.

The single options-flow step this incident originated in (`async_step_camera_census`,
`config_flow.py:2884-2989+`) submits back `{**self._config_entry.options, **user_input}`
(`:2901`) — i.e. every field on the form, regardless of what changed on the UI. Reading the
form schema (`:2917-2989+`) exposes at minimum:

- `CONF_CENSUS_CROSS_VALIDATION`
- `CONF_CAMERA_PERSON_ENTITIES`
- `CONF_EGRESS_CAMERAS`
- `CONF_PERIMETER_CAMERAS`
- `CONF_FACE_RECOGNITION_ENABLED`
- `CONF_ENHANCED_CENSUS`
- `CONF_GUEST_VLAN_SSID`
- `CONF_CENSUS_HOLD_INTERIOR`
- `CONF_CENSUS_BLE_CANCEL_ENABLED`
- (…and more below `:2989`, plus everything on the `person_tracking` step and any other
  integration-scoped step under `config_flow.py:2602+`).

HA-core's `async_update_entry` short-circuits identical-value writes so ONLY genuinely
changed keys reach `changed_keys`. But because the form always submits all keys, the
allowlist must cover every key an operator could plausibly toggle **on the same submit** as
a camera-list change, or the mixed-key branch trips and the incident recurs. Example
legal-config repro: operator flips `face_recognition_enabled` AND changes
`camera_person_entities` in one save — if `face_recognition_enabled` isn't in the allowlist,
the whole save falls through to reload. The plan doesn't have to allowlist all of them, but
it must ENUMERATE all of them in D1 with an explicit
SAFE / SAFE-WITH-DISPATCH / UNSAFE / NEEDS-DISCHARGE-WORK verdict per key.

**Required fix in-plan:**

- Rewrite D1 method to: (i) grep every `async_step_*` method in `config_flow.py` /
  `options_flow.py` whose branch is gated by `entry_type == ENTRY_TYPE_INTEGRATION` (start
  at `config_flow.py:2602`); (ii) extract the union of keys those steps write; (iii)
  classify each — not just the four seeds. The live-probe dump of
  `integration_entry.options.keys()` is necessary but not sufficient (it misses keys the
  operator has never touched but could touch tomorrow).
- Add explicit D1 AC: "Every integration-level `CONF_*` written by any options-flow step is
  in the audit table with a verdict."

### MEDIUM-1 — `binary_sensor.py:61` is (apparently) a dead import; harden the classification.

Grep in `binary_sensor.py` for `CAMERA_PERSON_ENTITIES` returns only the import at `:61`;
the string `"camera_person_detected"` at `:1155` is an entity-key literal, unrelated.
Plan defers this to build with "spot-verify". Sharpen: D1 must produce a definitive verdict
(dead-import → remove; or find the real consumer). "Deferred to build" is exactly the shape
of the Bug-Class-#22/#53 leak the plan is trying to prevent — a possibly-cached consumer
left un-audited.

### MEDIUM-2 — `_apply_in_place` dual-branch drift risk (Bug Class #27).

D2 sub-step notes: "build may extract a small `_apply_in_place_integration()` sibling OR
extend the existing helper with an entry-type branch. Decision deferred to build."

Extending `_apply_in_place` with an entry-type branch creates exactly the dual-branch mirror
that Bug Class #27 (primary/deferred mirror drift, per the compactor cycle) warns against:
future CM-side changes now silently affect the integration path and vice versa. Recommend
the plan **mandate the sibling-helper approach** (or an inline dispatch in the listener,
which the plan's D3 already implies): add an explicit non-goal —
"NO modification to `_apply_in_place`; CM helper stays byte-identical." That preserves the
tested CM machinery and keeps the integration branch's dispatch-only shape isolated.

### MEDIUM-3 — Assert `fan_veto.py:353` truly reads fresh; make it a D1 AC line, not prose.

`fan_veto.py:353` reads `config.get(CONF_CAMERA_PERSON_ENTITIES)` where `config` is a
function parameter. Grep confirms every caller passes a per-invocation dict (line 401
comment: "actuator_reconciler.py always pass a real self.config"), so today this IS
fresh-read. But a future refactor that starts caching `self.config` at some coordinator's
init would silently poison this consumer without any local code change. Add a D1 AC line:
"For every `SAFE (fresh-read)` classification, cite BOTH the read site AND the caller's
`config` construction site; assert the caller does not cache."

### LOW-1 — Kill-switch semantics on D3 dispatch.

Plan says `INTEGRATION_RELOAD_SUPPRESS_ENABLED = False` restores legacy reload. When the
switch is False, the integration branch shouldn't fire `_dispatch_integration_key_signals`
either (reload will rebuild subscriptions naturally; dispatching in addition doubles the
rebuild + logs). Make explicit: "With kill switch False, integration branch returns
immediately without dispatch; the fall-through reload does all the work."

### LOW-2 — D2 Live AC misses the parent-entry unload check.

D2 Live says "Zero unload/setup log lines for any URA child entry." Add: "AND zero unload
log line for the integration (parent) entry itself." A parent-only reload with no child
cascade is still wrong (and would slip past a child-entry grep).

### LOW-3 — Restart-seed invariant is stated but has no test/live assertion.

The invariant "restart re-seeds from `entry.options`" is asserted in D3's Discharge Contract
backstop column but no D2/D3 AC verifies it. Add a smoke assertion — either an in-suite
"round-trip" test (save allowlisted key → simulate restart → new value present in options)
or a Live line: "after camera-list save + HA restart, `entry.options[camera_person_entities]`
still contains the added entity."

### LOW-4 — Snapshot cleanup site is "build to verify"; make it an AC.

D4 says "Snapshot lives in `hass.data`… cleared on entry unload (mirror the CM path — build
to verify)." Turn into an AC: name the file:line where CM cleanup happens (or state that
CM doesn't clean up either, in which case document why the leak is bounded).

---

## Falsifiable invariant assessment

The plan's invariant is well-shaped and testable. Two amendments:

1. Add explicit second-clause: "AND no consumer of a suppressed key retains a cached view
   of that key's value after the save." (This is corollary #4 today; promote it into the
   invariant proper so Reviewer C/D can mutation-test consumers directly.)
2. The corollary "restart re-seeds" is orthogonal to the invariant — it's a safety
   backstop, not an invariant clause. Split it out so a broken restart-seed doesn't get
   read as "invariant intact."

---

## Non-goals — one addition

The five non-goals are appropriate. Add MEDIUM-2's non-goal: "NO modification to
`_apply_in_place`; CM helper is byte-identical after this cycle."

---

## Summary of required in-plan edits before build dispatch

| # | Severity | Action |
|---|---|---|
| HIGH-1 | must-fix | Either wire `PerimeterAlertManager` to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (new D3 sub-item) OR drop `CONF_EGRESS_CAMERAS` + `CONF_PERIMETER_CAMERAS` from the D2 allowlist. Add `perimeter_alert.py` to Institutional Context "Code locations surveyed." |
| HIGH-2 | must-fix | Rewrite D1 method to enumerate keys from every `entry_type == ENTRY_TYPE_INTEGRATION` options-flow step (start `config_flow.py:2602`), not just camera-census seed. |
| MED-1 | should-fix | D1 must produce a definitive verdict on `binary_sensor.py:61` (dead-import vs. real consumer), not "deferred to build." |
| MED-2 | should-fix | Add non-goal: "NO modification to `_apply_in_place`." Mandate sibling helper or inline dispatch. |
| MED-3 | should-fix | Every SAFE-fresh-read row must cite BOTH read site and caller's `config` construction (proves no cache). |
| LOW-1 | nice-to-have | Kill switch False also skips D3 dispatch — spell out. |
| LOW-2 | nice-to-have | D2 Live: also assert integration (parent) entry itself is not unloaded. |
| LOW-3 | nice-to-have | Add restart-seed assertion (test or live). |
| LOW-4 | nice-to-have | Name the snapshot cleanup site (file:line) or document leak-boundedness. |

Once HIGH-1 and HIGH-2 are resolved in the plan, the cycle is dispatchable to build.
