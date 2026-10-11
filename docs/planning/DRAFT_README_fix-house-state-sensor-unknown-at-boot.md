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
