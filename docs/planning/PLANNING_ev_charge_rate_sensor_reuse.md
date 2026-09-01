# PLANNING: EV-SENSOR-CLEANUP-1 (EC-1) — Reuse ev_charge_rate_garage_{a,b} sensors

**Date:** 2026-09-01
**Cycle ID:** EV-SENSOR-CLEANUP-1 (reversal of the 2026-08-16 audit's REMOVE verdict)
**Tier:** Tier 2 (2 framing-disjoint reviews).
Justification: additive display, but (a) reuses **registry orphans** — a unique_id
mismatch mints `_2`-suffixed entities the operator won't see (known URA footgun,
memory `reference_frigate1_retired_2suffix_permanent`), and (b) touches a
shared-producer read path where W-vs-kW mis-scale is a known URA footgun
(memory `feedback_read_consumers_before_asserting_function`). Two disjoint
framings: A = correctness (unit + None/idle/missing-entry handling), B = surface
identity (unique_id round-trip against registry orphans + entity name stability).

## Operator override note

The prior audit `docs/planning/AUDIT_ev_sensor_surface.md` §Q1 (2026-08-16)
recommended **REMOVE** the two `EnergyEVChargeRate{A,B}Sensor` classes as
functional dupes of `ev_charging_status.<plug>.power` attrs. That removal
shipped: classes are gone (`sensor.py:317-321` comment), backing properties
`evse_garage_{a,b}_power` are gone (`energy.py:10211-10216` comment), and two
entity-registry orphans remain (`sensor.ura_energy_coordinator_ev_charge_rate_garage_{a,b}`,
state `unknown`).

**Operator explicit override 2026-09-01:** REVERSE the removal. Do NOT delete
the orphans; instead resurrect the sensor classes and **repoint** their
`native_value` at the `ev_charging_status` per-bay power path (which has a
switch-status fallback the pre-removal sensors lacked — a strict superset).
Net outcome: the two named sensors stop reading `unknown` and expose live
per-bay charge rate on first-class entities instead of being buried in
`ev_charging_status` attributes. `ev_charging_status` itself is a NON-GOAL —
unchanged.

## Institutional context verified

**Greps run + results:**

1. `grep -n ev_charge_rate custom_components/…` → zero live hits. Only the
   tombstone comment at `sensor.py:317-321` and the audit doc. Classes DELETED
   in the prior cycle — plan must RE-ADD (not edit-in-place). **NEW** because
   the code no longer exists; not a duplicate.
2. `grep -n ev_charging_status custom_components/…` → producer at
   `sensor.py:10064` (`EnergyEVChargingStatusSensor`), attrs computed from
   `energy.ev_status` (`sensor.py:10124`). Per-bay derivation
   `_derive_per_bay_state` at `sensor.py:9996-10061` already reads
   `entry.get("power")` and computes `actual_kw = round(float(power or 0.0)/1000.0, 3)`
   — **REUSED** shape: the new sensors mirror this exact expression.
3. `_get_evse_state` at `domain_coordinators/energy_pool.py:650` builds the
   per-bay dict (`power`, `is_on`, `charging`) with the v4.2.19 switch-status
   fallback the audit called out at §Q1. Confirms the source path.
4. **Zero other consumers** of `ev_charge_rate_garage_{a,b}` in the repo
   (dashboards read `ev_charging_status` attrs directly per audit §Q1). Safe
   to point native_value at a different source — nothing else reads these.
5. Related module-constant `SOLAR_FOLLOW_RESTORE_AMPS` (used by
   `_derive_per_bay_state`) at `energy_const.py`; no new constants proposed.

**Units (critical):** `ev_status["garage_a"]["power"]` is in **WATTS**
(`_derive_per_bay_state` divides by 1000 to publish `actual_kw`). The new
sensor MUST declare `native_unit_of_measurement = "kW"` and divide by 1000 at
the boundary. The pre-removal sensors' unit is unrecoverable from source (they
were deleted); the audit implicitly treated them as kW ("charge rate"). Ship
as kW and note in the README.

**Prior planning docs consulted:**
- `docs/planning/AUDIT_ev_sensor_surface.md` (§Q1 — the REMOVE decision this
  plan reverses; §Q2 Emporia outage context; §Q3 outlet estimate).

**Memory bodies pulled:**
- `reference_frigate1_retired_2suffix_permanent.md` — HA never renames
  retroactively; if we mint a new `unique_id` the operator gets `_2` entities
  and the orphans stay dead. Load-bearing on D1 acceptance.
- `feedback_read_consumers_before_asserting_function.md` — W-vs-kW footgun.

**Design docs read:** none dedicated to these sensors; the audit is the
canonical reference for this surface.

**Code locations surveyed end-to-end:**
- `sensor.py:310-330` (EC platform registration site).
- `sensor.py:9996-10149` (`_derive_per_bay_state` + `EnergyEVChargingStatusSensor`).
- `domain_coordinators/energy.py:10200-10240` (tombstone + `l1_charger_active`).
- `domain_coordinators/energy_pool.py:160-185, 640-700` (per-bay state; pool
  block is unrelated but greps landed here).

**Registry orphan unique_ids (MUST be preserved):** confirmed via the audit
that live entity_ids are `sensor.ura_energy_coordinator_ev_charge_rate_garage_a`
and `..._b`. Builder MUST read the live `.storage/core.entity_registry` to
extract the exact `unique_id` string on each orphan before writing the class
(don't infer). If the registry unique_ids do not match `{DOMAIN}_ev_charge_rate_garage_{a,b}`,
use whatever the registry has — mismatch mints `_2` entities.

---

## Deliverables

### D1 — Resurrect `EnergyEVChargeRate{A,B}Sensor`, repoint to `ev_status[bay]["power"]`

Re-add two SensorEntity classes at the bottom of the EC sensor block in
`sensor.py` (near `EnergyEVChargingStatusSensor`, `sensor.py:10064`) and
register them at `sensor.py:315-321` (replacing the tombstone comment).

**native_value contract (per bay):**
```
ec = <energy coordinator via manager.coordinators.get("energy")>
if ec is None: return None
entry = ec.ev_status.get("garage_a")           # or "garage_b"
if not isinstance(entry, dict): return None    # bay missing entirely -> unknown
power_w = entry.get("power")
try:
    return round(float(power_w or 0.0) / 1000.0, 3)   # W -> kW
except (TypeError, ValueError):
    return None
```

**Idle handling (explicit decision):** when the bay is present but not
charging, `power` from `_get_evse_state` is `0` (Emporia measures 0 W idle;
switch-status fallback returns 0 when the switch is off). The sensor
therefore reads **`0.000` kW when idle, live kW when charging, and `unknown`
only when the EC or the bay entry is missing entirely.** Rationale: mirrors
`_derive_per_bay_state.actual_kw` semantics (`sensor.py:10030`); a numeric 0
is a more useful dashboard value than `unavailable` and matches operator
expectation for a "charge rate" sensor.

**Class attributes:**
- `_attr_has_entity_name = True`
- `_attr_native_unit_of_measurement = "kW"`
- `_attr_device_class = SensorDeviceClass.POWER`
- `_attr_state_class = SensorStateClass.MEASUREMENT`
- `_attr_suggested_display_precision = 3`
- `_attr_icon = "mdi:ev-station"`
- `_attr_device_info = _energy_device_info()`
- `_attr_unique_id` = **the exact string on the live registry orphan** (builder
  reads `.storage/core.entity_registry` first; do NOT guess). Expected value
  `f"{DOMAIN}_ev_charge_rate_garage_a"` / `_b` — if the registry differs,
  registry wins.
- `_attr_name = "EV Charge Rate Garage A"` / `... B` (matches the friendly
  suffix the operator already sees).

**Non-goals:**
- `ev_charging_status` entity, its `extra_state_attributes`, and
  `_derive_per_bay_state` are UNCHANGED.
- No new config-flow fields, no new constants, no new signals, no new DAO.
- `evse_garage_{a,b}_power` coordinator properties stay deleted (per audit).

#### Acceptance criteria
- **Verify (code):** two new classes exist in `sensor.py` and are registered
  in the EC platform list; the tombstone comment at `sensor.py:317-321` is
  replaced.
- **Verify (unit):** `_attr_native_unit_of_measurement == "kW"` on both
  classes; grep for `/1000` or `/ 1000.0` in the new `native_value`.
- **Verify (identity):** each new `_attr_unique_id` matches an existing
  entity-registry orphan string (documented in the fix-up notes with the
  exact string read from `.storage/core.entity_registry`).
- **Sensor:** `sensor.ura_energy_coordinator_ev_charge_rate_garage_a` state
  is a `float` in kW (not `unknown`) whenever
  `sensor.ura_ev_charging_status` attribute `garage_a.power` is a number,
  and equals `round(garage_a.power / 1000.0, 3)`. Same for `_b`.
- **Live:** post-deploy, both sensors resolve to numeric kW (no `_2`
  entities created — old entity_ids rehydrate). When a car is charging on
  bay A, `sensor.ura_energy_coordinator_ev_charge_rate_garage_a` state
  matches `state_attr('sensor.ura_ev_charging_status','garage_a')['power']/1000`
  to 3 dp. When idle, reads `0.000`.

### D2 — Test that populated sensors reflect per-bay power

Add a test under `quality/tests/` (co-located with existing sensor tests
for EC; builder to grep `quality/tests` for an existing `test_energy_*`
sensor test file to extend rather than create new). Test drives a fake EC
whose `ev_status` returns the shape
`{"garage_a": {"is_on": True, "charging": True, "power": 7200}, "garage_b": {"is_on": False, "charging": False, "power": 0}}`.

#### Acceptance criteria
- **Test:** with `garage_a.power == 7200` (W), the A-sensor `native_value`
  returns `7.2` (kW); with `garage_b.power == 0`, the B-sensor returns
  `0.0` (idle, NOT `None`).
- **Test:** with the bay entry missing (`ev_status == {}`), `native_value`
  returns `None` (unknown), not `0.0` — discriminates "no data" from "idle".
- **Test:** with EC not registered (`hass.data[DOMAIN]["coordinator_manager"]`
  absent), `native_value` returns `None` without raising.
- **Test:** with `power == None` in the entry, `native_value` returns `0.0`
  (mirrors `_derive_per_bay_state.actual_kw` semantics — `float(None or 0.0)`).
- **Verify:** test file runs green under
  `PYTHONPATH=quality python3 -m pytest quality/tests/<file> -v`.

---

## Falsifiable invariant

For every tick where the EC is registered and `ev_status[bay]` is a dict
with a numeric `power`, the sensor's `native_value` equals
`round(power/1000.0, 3)` — no other value is reachable on the live path.
Reviewer B falsifies by finding any code path where the sensor could return
a value not equal to `power/1000` when the entry is present with numeric
power (e.g. a raw-W leak from forgetting the divide, a stale cache, an
early return that swallows a real reading).

## Live discriminator (post-deploy validation table row)

Wait for a real charging session (or use the DP carrier telemetry to
confirm bay state), then compare:
- `state('sensor.ura_energy_coordinator_ev_charge_rate_garage_a')` (kW)
- `state_attr('sensor.ura_ev_charging_status','garage_a')['power'] / 1000` (kW)

PASS iff equal to 3 dp AND no `_2`-suffixed entity was minted (check
`.storage/core.entity_registry` for `..._ev_charge_rate_garage_a_2`).

## Plan-completion tracking

Nothing deferred. If the builder discovers the registry unique_id does NOT
match `f"{DOMAIN}_ev_charge_rate_garage_a"`, that finding is a fix-up in
this same cycle (adopt the registry string), not a deferral.
