# AUDIT — mmWave-only rooms + presence-input inventory (D0 of `mmwave_corroboration_tier3`)

**Status:** written **2026-08-09**, filed under its originally-planned 07-31 name.
**Owed since:** 2026-07-31 as **D0** of `PLANNING_mmwave_corroboration_tier3.md` — *mandatory*
under "Measure before you build", and the acceptance fixture D5 was to diff against. **It was
never written, and the cycle shipped anyway** (v5.40.0 comfort-fan AWAY veto, v5.42.0 D2 mmWave
demotion). This document closes that gap and is the hand-built fixture of record.

**Method:** read-only. Room configs from live `.storage/core.config_entries` via `ssh ha`
(38 `ENTRY_TYPE_ROOM` entries); live states via HA template render. No planner mental model.

---

## Schema correction — read this before trusting any prior bucket claim

`const.py:334`:

```python
CONF_MMWAVE_SENSORS: Final = "presence_sensors"  # Note: blueprint calls them presence_sensors
```

**The mmWave bucket is stored as `presence_sensors`.** A first pass of this probe keyed on
`mmwave_sensors` and reported 37/38 rooms with zero mmWave — an artefact, not a finding.
Any prior statement about mmWave bucket membership that did not go through `CONF_MMWAVE_SENSORS`
should be re-derived. The three canonical buckets are:

| Constant | Stored key |
|---|---|
| `CONF_MOTION_SENSORS` | `motion_sensors` |
| `CONF_MMWAVE_SENSORS` | **`presence_sensors`** |
| `CONF_OCCUPANCY_SENSORS` | `occupancy_sensors` |

---

## Finding 1 — the mmWave-only class: **5 rooms** (D0 gate: N ≥ 1 → Tier 3 retroactively justified)

`presence_sensors` non-empty AND `motion_sensors` empty AND `occupancy_sensors` empty:

| Room | mmWave entities |
|---|---|
| Game Room | `mmwave_zigbee_gameroom_presence`, `0xa4c1382e60e05225_presence` |
| Jaya Bedroom (Bedroom 4) | `jaya_3_presence`, `mmwave_zigbee_jayabedroom_presence` |
| Living Room | `screek_human_sensor_l13_2412s_presence` |
| Study A | `mmwave_zigbee_studya_presence` |
| Study B | `mmwave_lux_wifi_esphome_studyb_presence` |

Plus one adjacent class — **`MMWAVE_NO_PIR`**, mmWave + occupancy but still zero PIR:

| Room | mmWave | occupancy |
|---|---|---|
| Master Bedroom | `screek_human_sensor_l13_b38b24_presence`, `mmwave_temp_hum_lux_zigbee_masterbedroom_presence`, `switch_mmwave_inovelli_occupancy` | `bed_presence_2bd7b4_bed_occupied_either_fast` |

**Six rooms have no PIR at all.** The plan assumed *"Study A confirmed ≥1; likely more"* — it is 5–6,
and it includes the two rooms flagged duty-cycle-stuck on 2026-08-09 (Living Room, Study A) and the
room that ran fans while the house was empty (Master Bedroom).

## Finding 2 — this explains the 2026-08-09 incident and the overnight spam, structurally

`_detect_duty_cycle_stuck` (`coordinator.py`) has two properties that collide with Finding 1:

- `candidates = [s for s in (mmwave_sensors + occupancy_sensors) if s]` — **motion is never a
  candidate** (*"Motion sensors themselves are NOT candidates — PIR is our corroboration source"*).
- Corroboration requires **PIR transitions** in-window.

Therefore in all six no-PIR rooms, D2 can **detect** but can **never corroborate**: the corroborator
class is empty by configuration. Every sustained occupancy in those rooms is uncorroborated by
construction → notify. This is `B-2026-08-04-1`'s spam source, and it is not a threshold-tuning
problem.

**Master Bedroom is the sharpest case.** Its bed sensor sits in `occupancy_sensors`, which makes it
a **D2 candidate** — so a bed that is legitimately occupied all night gets *flagged as stuck*, while
the very signal STUCK-SENSOR-1 identified as the ideal discriminator (*"bed presence read OFF while
occupancy read ON"*) is on the wrong side of the equation. It is being judged instead of consulted.

**Garage B is outside the detector entirely:** `motion_sensors` = 2, `presence_sensors` = 0,
`occupancy_sensors` = 0 → candidate set empty. The chattering ratgdo cannot be scored at any
threshold. (Confirmed with correct keys; the earlier claim happened to be right for the wrong reason.)

## Finding 3 — orphaned config key: Study A's Athom mmWave is invisible to URA

Study A carries a **fourth** key that no constant maps to:

```
mmwave_sensors = ['binary_sensor.athom_presence_sensor_d93b20_mmwave_sensor']   # ORPHAN
presence_sensors = ['binary_sensor.mmwave_zigbee_studya_presence']              # what URA reads
```

`grep -rn '"mmwave_sensors"' custom_components/` returns **nothing** — no code reads that key. The
Athom sensor is configured-but-unread, and it is `unavailable` in live state (since the last boot).
Study A therefore runs on a single Zigbee mmWave, not two.

**CORRECTED 2026-08-09 (same day, after reading the effective config).** I first wrote that this was
"very likely the true shape of the plan's *Amendment 2* finding." **That was wrong** and is retracted.
Reading `options` vs `data` per key shows Athom was **cleanly and completely replaced** via the options
flow — `motion_sensors: []`, `occupancy_sensors: []`, `presence_sensors: [zigbee]`,
`illuminance_sensor: invisoutlet` all override stale `data` values that still name Athom. Nothing is
misfiled here; the device is simply decommissioned (operator-confirmed 2026-08-09) and its residue is
inert.

The real "misfiling" story is Finding 6 below: **every** sensor's kind is its bucket, so kind cannot
be expressed independently of role. Athom was a red herring.

Residue disposition: stale `data` values + the orphan key are unread; cleaning them needs a direct
`.storage` edit + restart — real risk, zero functional gain. **Leave them.** The live cleanup is the
ESPHome device entry (25 entities, 3 in the unavailable count); its UniFi `device_tracker` is a
separate entry and survives that deletion.

## Finding 6 — the root cause: sensor **kind IS config bucket**, so hardware pins analysis

`domain_coordinators/occupancy_substrate.py:81`:

```python
_KIND_TO_CONF: Dict[str, str] = {
    "motion": CONF_MOTION_SENSORS,
    "mmwave": CONF_MMWAVE_SENSORS,
    "occupancy": CONF_OCCUPANCY_SENSORS,
}
```

with `TIER1_KINDS = ("motion", "mmwave", "occupancy")` (`const.py:342`). URA has exactly three sensor
kinds and they **are** the three config lists. Operator ruling 2026-08-09: *"Sensor reality should not
pin use and analysis reality in software. It should just tell us what the hardware layer is."*

This single conflation produces every symptom in Findings 1–2:

- A bed sensor cannot declare itself a bed; it inherits `"occupancy"` (a bucket whose own comment at
  `const.py:335` reads *"Combined motion+presence sensors"* — an ambiguity bucket). That membership is
  what makes it a **D2 candidate** instead of a corroborator.
- "Corroborator" is hardcoded to mean *the motion bucket*, so the six no-PIR rooms have no corroborator
  **not because they lack independent evidence** but because the vocabulary cannot name it.
- Every downstream consumer keys off those three strings: D2 candidacy, P15 precedence arbitration, the
  mmWave demotion gate (`occupancy_source == "mmwave"`), fan-recheck.

**What role-derivation unlocks with no new hardware:** Master Bedroom already has an ideal corroborator
(the bed — independent failure mode, physically unspoofable); Study A's `room_cameras` and BLE become
nameable corroborators for the mmWave-only class. Tracked as the prerequisite card
**SENSOR-CAPABILITY-1**. Note the `SignalTrustLedger` design already assumed this layer exists — its
input dataclass is `RoomSignal(..., source_kind: str  # 'mmwave' | 'pir' | 'camera' | 'ble')`, a richer
vocabulary than the three buckets.

## Finding 4 — fleet health: **6.0% unavailable, not ~33%**

The claim *"a third of the corroborator fleet is dead"* — asserted earlier this session from
`B-2026-08-04-2` — is **RETRACTED**. That item's "5 of 13" is 5 of a **13-entry hand-picked adjacency
list** used by one probe (`AUDIT_exit_evidenced_vacancy_probe.md`), not 5/13 of the sensor fleet.
Generalising a probe's coverage list to the fleet was an unforced error; the operator challenged it
and the measurement settles it.

Live census of presence-class binary sensors (`device_class in {occupancy, motion, presence}`):

| Metric | Value |
|---|---|
| Total | **503** |
| `unavailable` / `unknown` | **30** |
| **Percent bad** | **6.0%** |

The 30 further cluster into roughly **15 physical devices** (multi-entity units: `unity_a6627c` ×3,
`looponunity2` ×3, `athom_d93b20` ×3, `ziri_3` ×3, several Seeed units), so device-level rot is
lower still. `ziri_3` is separately known-dead-physical.

**Still real, and worth an ops pass:** a five-unit **HOBEIAN cluster** is unavailable together —
`downguestroom`, `upguestroom`, `exercise`, `breakfast`, `butler`. A same-vendor, same-naming cluster
failing together is the shape of a transport/coordinator problem rather than five coincidences —
though per the co-occurrence lesson of 2026-08-08, **that is a hypothesis to test, not a mechanism to
assert.** Note also that Exercise Room's configured presence entity is the `_2` variant
(`..._exercise_presence_2`), which is *not* the unavailable one — so the cluster's blast radius on
URA config must be checked entity-by-entity, not by device name.

## Finding 5 — nothing is stuck right now

All twelve no-PIR-room sensors read `off`. Most share a `last_changed` ≈ 54,889 s (~15.2 h), i.e. a
boot stamp rather than a real transition; Study A's Zigbee moved 8,567 s ago and is live. The
overnight stuck state is not currently present.

---

## Acceptance criteria (from the plan's D0)

| Criterion | Result |
|---|---|
| Audit doc committed with N ≥ 1 mmWave-only rooms | **PASS** — N = 5 (+1 `MMWAVE_NO_PIR`). Tier 3 justified; no downgrade. |
| Every room with an `unavailable` mmWave entity called out | **PASS** — Study A (orphaned Athom entity, `unavailable`). No *read* mmWave entity in the six no-PIR rooms is unavailable. |
| Live check | n/a per plan (offline audit); live states pulled anyway for Findings 4–5. |

## What this changes downstream

1. **Corroboration-gated exclusion cannot be a global policy.** Six rooms have no corroborator class
   at all — for them, exclusion would be unconditional. Per-room capability, exactly as
   STUCK-SENSOR-1's caveat anticipated.
2. **Bed presence must move from judged to judging** — its `occupancy_sensors` membership makes it a
   candidate. Reclassification is a config-and-code question, not a threshold.
3. **`B-2026-08-04-1`'s memory-baseline exemption is the right shape,** because "continuous-on is
   normal here" is per-room and learnable, whereas a class allowlist would have to enumerate these
   six rooms by hand.
4. **Fleet rot does not block the cycle** at 6% — the fleet-health objection to building
   corroboration logic is withdrawn. The HOBEIAN cluster is an ops item, not a gate.
5. **`B-2026-08-04-2` should be re-scoped** from "fleet rot" to "5 specific adjacency-list entries,
   some of which may be mis-registered rather than dead" — the probe's own wording was
   *"dead or mis-registered"*.
