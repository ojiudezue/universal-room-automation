# DRAFT README — fix/house-state-sensor-unknown-at-boot

Card: HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1 (Tier 1 hotfix).

## Problem

Three house-state sensors returned a hard-coded ``"away"`` when
``hass.data[DOMAIN]["coordinator_manager"]`` was not yet attached
(pre-boot / mid-restart):

- ``HouseStateSensor``             — ``sensor.py:5416`` (on URA
  Coordinator Manager device)
- ``PresenceHouseStateSensor``     — ``sensor.py:5510`` (on URA
  Presence Coordinator device)
- ``IntegrationHouseStateSensor``  — ``sensor.py:6525`` (on the
  URA integration device)

That writes a false Away into recorder history at every restart — a
display writer disagreeing with the state machine (Bug Class #53
flavour). Downstream dashboards / tiles briefly flash Away before the
manager comes up, and anyone trending house state from recorder sees
spurious Away rungs at every restart boundary.

## Fix

All three `native_value` properties now return ``None`` when the
manager is absent (HA surfaces that as ``unknown``). Return type hint
tightened to ``str | None``. ``extra_state_attributes`` already
returns ``{}`` in the manager-None branch — unchanged.

The state machine itself is NOT touched; this is strictly a display
boundary.

## F5 (Review A, LOW, same bug class) — extended to two more sensors

Same bug class in two state-space neighbours:

- `SafetyStatusSensor` (`sensor.py:~6598`) — returned `"normal"` when
  the manager (or safety coordinator slot) was missing.
- `SecurityArmedStateSensor` (`sensor.py:~6993`) — returned
  `"disarmed"` when the manager (or security coordinator slot) was
  missing.

Both now return `None` (⇒ HA `unknown`). Return type hints tightened
to `str | None`. Three guards per method: `manager is None`,
`<coordinator-slot> is None`, and `return <live-value>`.

### Reader-safety grep (did not change HA config)

Searched for programmatic readers that key on the OLD boot
sentinels:

- `/Users/okosisi/ha-config/automations.yaml` — no references to
  `sensor.ura_safety_status` or `sensor.ura_security_armed_state`.
- `/Users/okosisi/ha-config/scripts.yaml` — no references.
- `custom_components/` — only the producer sites in `sensor.py` and
  one comment in `domain_coordinators/security.py:627` naming the
  entity. No code reads `sensor.ura_security_armed_state.state ==
  "disarmed"` or `sensor.ura_safety_status.state == "normal"`.

Conclusion: changing the pre-boot fallback from a mode name to
`unknown` has no reader on-wire today. Dashboards that render these
states will show `Unknown` during the pre-manager window instead of
a fake `Normal` / `Disarmed`.

**Review B B2-4 note:** when the Safety or Security coordinator is
switched off entirely (so the coordinator-slot `is None` branch
fires at steady state too, not just at boot), the corresponding
sensor now reads `unknown` **permanently** instead of a false
`"normal"` / `"disarmed"`. This is intentionally more accurate: an
off coordinator has no opinion to publish, so a dashboard shows
`Unknown` rather than impersonating a live all-clear.

## F4 (Review A, LOW) — residual pre-restore gap

A deeper restart boundary remains OPEN after this cycle:

- `__init__.py:~4310` publishes the manager into
  `hass.data[DOMAIN]["coordinator_manager"]`.
- `manager.py:478` then awaits `_async_restore_house_state()` —
  which is where the persisted state is applied to the machine.

Between those two statements the `manager is None` guard already
returns False, but the machine is still at its construction default
(`HouseState.AWAY`, `house_state.py:153`). A sensor refresh that
lands in that window records a `"away"` sample even with this fix.

I looked for an existing "restore attempt complete" flag the
sensors could gate on:

- `manager._house_state_restored` (manager.py:230, 677, 691, 701) —
  private; True only in the SUCCESSFUL-restore branch, False in the
  cold-boot / stale-record branch AND in the "not yet attempted"
  initial state. It is NOT distinguishable between "pre-restore" and
  "cold-boot, no persisted record".
- `house_state_machine.boot_restore_active` (house_state.py:434) —
  True only on a successful in-window restore. Same shortcoming.

No existing public signal cleanly means "restore attempt has
finished, machine value is authoritative". Per operator F4
directive, I did NOT add a new flag to the manager. **The gap
remains open**: for the sub-second window between manager publish
and restore completion, the three house-state sensors can still
publish a transient Away sample. Fix path (future card): add an
explicit `house_state_restore_complete` boolean the manager sets
AFTER `_async_restore_house_state` returns in both branches, gate
`native_value` on it. Pinging operator for direction.

## Grep sweep — other house-state-like sensors / CM mirrors

Enumerated every ``manager is None:`` guard in ``sensor.py`` (124
sites). The three ``return "away"`` sites above are the ONLY ones
whose state space is house-state. All other sensors use state spaces
with explicit boot sentinels (`"not_initialized"`, `"unavailable"`,
`"unknown"`, `"disarmed"`, `"clear"`, `"normal"`, `"degraded"`, `0`,
`100.0`, `None`, `{}`) that are already discriminable from live
operational values. No manager-None → `"home"` fallbacks exist. No
other sensor hard-codes a house-state mode name pre-boot.

Confidence / CM-mirror sensors (`CoordinatorSummarySensor`,
`CoordinatorHealthSensor`, etc.) use `"not_initialized"` already —
unchanged.

## Tests

New file `quality/tests/test_house_state_sensor_boot_unknown.py`
(3 tests, all pass):

- With no manager: all three sensors return ``None`` (not
  ``"away"``); ``extra_state_attributes`` is ``{}``.
- With a manager stub whose ``house_state.value == "home"``: all
  three sensors return ``"home"``.
- Source-level anchor: no ``native_value.fget`` contains a
  ``return "away"`` fallback (regex). If any site is reverted, this
  test fails.

Call-neuter drill (``PYTHONDONTWRITEBYTECODE=1`` + cache clear,
restored after): reverting one site to ``return "away"`` makes both
the behavioural test AND the anchor fail. Restore leaves `git
status` clean.

## Prospective Live validation (discriminating)

After deploy + restart, observe within the first 60 seconds AND after
the manager attaches:

- **PASS** — ``sensor.ura_house_state``,
  ``sensor.ura_presence_house_state``, and
  ``sensor.ura_integration_house_state`` all show state ``unknown``
  during the pre-manager window; recorder history for each entity
  shows a direct ``unknown → <real state>`` transition with no
  intermediate ``away`` sample at this restart boundary.
- **DIFFERENT FAILURE** (pre-fix behaviour this ships against) — any
  of the three briefly shows ``away`` in recorder history across the
  restart. If observed, the deploy failed to pick up the change
  (verify the sha matches the deploy's PR diff).
- **UNRELATED FAILURE** — manager fails to attach at all. Not this
  fix's domain; the sensors will stay ``unknown`` indefinitely, which
  is the correct display for a non-running manager.
