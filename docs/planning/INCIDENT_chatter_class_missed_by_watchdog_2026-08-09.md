# INCIDENT MEMO — a stuck-signal class the v5.35.0 watchdog demonstrably misses

**Date:** 2026-08-09
**Purpose:** satisfy **GO criterion 3, second leg** of
`PLANNING_signal_trust_ledger_abstraction.md` — *"new stuck-signal incident class appeared in the
interim that the concrete watchdog demonstrably misses (documented incident memo required, cited
here at revive-time)."*
**Status of criterion 3's first leg:** **FAILED, not merely unmet.** It requires *"lived-in ≥ 2 weeks
with no rollback and no follow-up fix-up cycle in that window."* v5.35.0 shipped 2026-07-28 23:18 CDT;
**v5.35.1 (hotfix) and v5.35.2 (observability) both landed the same night.** The first leg was
unsatisfiable from the start. This memo is therefore the only route to criterion 3.

---

## 1. The incident

Overnight 2026-08-09 the operator, away from the house, found **comfort fans running in an empty
master bedroom.** Root cause: a Zigbee mmWave sensor holding occupancy true. Occupancy feeds HVAC,
lighting and presence trust, so the blast radius is wide. Two further rooms (Living Room, Study A)
were flagged the same night. Separately, Garage B reported occupied off a chattering ratgdo.

Prior art: the v5.35.0 D2 code comment already names a *"Master Bedroom empty-suite incident."*
**This is a repeat of a known failure mode after the watchdog shipped to prevent it.**

## 2. The class the watchdog misses: CHATTER (transition-rate)

The shipped watchdog recognises two classes:

| Class | Rule | Consequence |
|---|---|---|
| Continuous-on (P22) | `_sensor_on_since` ≥ `_stuck_sensor_hours` (4h) | **EXCLUDES** from occupancy |
| High duty-cycle (D2) | ≥85% asserted over 60 min, ≥20 ticks, PIR-uncorroborated | **Notify only** |

A sensor oscillating at roughly **50% duty is invisible to both**: every off-tick resets P22's
`_sensor_on_since` clock, and the on-ratio never approaches D2's 85%.

**Measured evidence (Garage B ratgdo, 24 h recorder):
3,769 off / 3,765 on / 6 unavailable.** Real oscillation, not a transport artefact.

## 3. Why it is structural, not a threshold miss

Three compounding findings, each verified in source rather than inferred:

1. **Motion is unscored by design.** `_detect_duty_cycle_stuck`'s candidate set is
   `mmwave_sensors + occupancy_sensors` only — PIR is excluded because *"PIR is our corroboration
   source."* A chattering PIR is therefore never diagnosed.
2. **The anchor can be the broken thing.** D2's corroboration test is satisfied by ≥2 PIR transitions
   in-window — which a chattering PIR trivially supplies. **A flapping PIR actively shields a stuck
   mmWave from detection.**
3. **Some rooms are outside the detector entirely.** Garage B has `mmwave_sensors: None`,
   `occupancy_sensors: []` → D2's candidate set is empty there. The room where the incident happened
   cannot be scored at any threshold.

And the deeper cause, established the same day in
`AUDIT_mmwave_only_rooms_2026-07-31.md` **Finding 6**: **sensor kind IS the config bucket**
(`occupancy_substrate.py:81` `_KIND_TO_CONF`, `const.py:342` `TIER1_KINDS`). Six rooms have no PIR at
all, so D2 can detect but **can never corroborate** there — the corroborator class is empty by
configuration. Master Bedroom's bed sensor, the ideal discriminator, sits in `occupancy_sensors` and
is therefore a **stuck-candidate being judged** rather than a corroborator being consulted.

## 4. Why this bears on the ledger cycle specifically

The watchdog shipped **four bespoke detectors sharing one notifier.** `_stuck_signal_nm.py`'s own
docstring scopes it: *"Detection + discount + notify ONLY… never actuates, never mutates detector
state."* Detection was never unified — the plan deliberately parked that, with the trigger
*"after D1..D4 ship and the shape is proven at four sites."*

Chatter is the **fifth** detector this area wants. Adding it as another bespoke implementation is
precisely the accumulation the ledger exists to stop.

**Constraint this memo does NOT lift.** The ledger's design principle 1 is *"Extraction, not
invention — if a proposed ledger capability has no pre-cycle site, it does NOT ship in this cycle."*
Chatter has no pre-cycle site. It must ship **concretely first** (extending `_detect_duty_cycle_stuck`,
after `SENSOR-CAPABILITY-1` makes a non-PIR corroborator expressible), live long enough to produce a
parity oracle, and only then migrate as an extension of M5.

## 5. Adjudication

**Criterion 3 is SATISFIED via its second leg.** A new stuck-signal class (chatter / transition-rate)
appeared after v5.35.0 shipped, is demonstrably missed by both shipped rules, is evidenced by
measured recorder data, and its root cause is a shared-primitive defect of exactly the kind the
ledger addresses.

**Remaining open GO criteria:** #4 (golden-tap fixtures — under active investigation in
`AUDIT_ledger_golden_fixture_yield.md`; the tap may be replaceable by offline recorder replay) and
#5 (operator explicit GO). Criteria 1 and 2 were already met.
