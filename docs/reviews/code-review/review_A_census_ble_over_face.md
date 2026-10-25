# Review A (local correctness + edge cases): CENSUS-BLE-OVER-FACE-1

Branch `fix/census-ble-over-face`. Diff `df3bb8412...ec9adbfa2`; the merge-base was checked and equals `df3bb8412`.
Read in full first: `IDENTITY_FUSION_CAMERAS_MANUAL.md` and `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`. Nothing here re-asserts a §10 ledger claim.

**Verdict: SHIP.** No CRITICAL, HIGH or MEDIUM findings. Two LOWs, both informational.

## Invariant truth table (guard at `camera_census.py:5891-5946`)

| raw `person.<slug>` | flag | switch / overrule state | helper result | decision | vs pre-change |
|---|---|---|---|---|---|
| `not_home` | any | any | not called | drop (`raw`) | same |
| `home` | True | overruled, URA location `away`, switch on | `not_home` | drop (`ble_overrule`), counter +1 | NEW (intended) |
| `home` | True | not overruled, or switch off, or location not away | raw `home` | keep | same |
| missing (None) | True | not overruled | None | keep (fail-open) | same |
| `unknown`/`unavailable` | True | name still in last tick's overrule set, location away | `not_home` | drop | NEW, and consistent with the helper's semantics for every other trust reader |
| any non-`not_home` | True | helper raises (it cannot: it catches internally) | raw kept | keep | same |
| any | False | any | never called | raw decision only | byte-identical (`raw_value == "not_home"` is the same as the old `state is not None and state == "not_home"`) |

The only behaviour that changes is the debug log string, which now carries `source=`.

## Checks

- **Raw state is read once, and the helper runs only when the flag is True.** Holds at `:5905-5933`. The helper does its own raw read inside `effective_person_state` (`person_coordinator.py:628-650`). That second read is in the same event-loop turn with no await between, so it cannot diverge.
- **Exception fallback.** Holds. `person_state_for_trust` (`person_coordinator.py:124-145`) swallows errors and returns raw. The outer try at `:5914-5926` keeps `trust_value = raw_value`, which is never `not_home` on that branch, so the exception path never drops a face.
- **Slug resolution against the live config shape.** Holds. Live integration entry: `data.tracked_persons = ['Ezinne','Oji Udezue','Jaya','Ziri']`, `options.tracked_persons = ['person.ezinne','person.oji_udezue',...]`.
  - The census merges options over data, giving `oji_udezue` → `person.oji_udezue`.
  - The person coordinator iterates `data` names and matches `person.{name.lower().replace(' ','_')}` = `person.oji_udezue` (`person_coordinator.py:813`, `:645`). These match.
- **Counter.** It is reset per tick at `camera_census.py:1719`, beside `_face_lookup_missing_count`, before `_apply_enhanced_house_census` (`:1749`), which is the only caller of `_get_face_recognized_person_names` (`:5966`). It increments only on the `ble_overrule` branch, at most once per person per tick. On the non-enhanced path it reads 0, which is correct because the invariant is scoped to the enhanced path.
- **Sensor.** `face_dropped_ble_overrule_count` at `sensor.py:3880` is int-coerced with a getattr default. `_unrecorded_attributes` on `URAPersonsInHouseSensor` (`:3729`) shadows nothing: neither `_CensusBaseSensor` nor `AggregationEntity` defines one. The entity id `sensor.universal_room_automation_persons_in_house` was confirmed in the live registry.
- **Constant.** `CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS: Final = True` (`const.py:3974`). It is read through the module attribute `_ura_const`, so a test or reviewer monkeypatch takes effect at call time.
- **Switch off gives the same decision.** `effective_person_state` returns raw when `_ble_leads_enabled()` is False (`person_coordinator.py:643-644`).
- **Egress fence.** Holds. The diff does not touch `is_face_leg_person_vetoed`, `transit_validator`, or `_get_face_recognized_persons_fresh`.
- **coordinator.py comment.** Correct: `get_room_identified_persons` has no definition anywhere in the package (git grep at `ec9adbfa2`).
- **Docs.**
  - `presence.py:1227-1232` matches the path-α predicate.
  - `const.py:3964` matches the window constant.
  - The guard range `~5893-5940` is approximate; the actual span is 5891-5946. That is acceptable with the `~`.
  - v5.103.90 is the GPS-assistive README.
  - §10 #28 is recorded as a supersession, not a deletion, which follows the ledger rule.

## Findings

| # | Sev | Where | Finding | Class |
|---|---|---|---|---|
| A-L1 | LOW | `camera_census.py:5917` | The lazy import sits inside the per-person loop. It is cached by `sys.modules`, so the cost is negligible. Hoisting it once per call would read cleaner. Optional. | style |
| A-L2 | LOW (pre-existing, unchanged) | `camera_census.py:5845` | If `options.tracked_persons` were ever absent, the census slug would come from data names (`"Oji Udezue"` → `person.oji udezue`). Both the raw read and the helper would then miss, fail-open, and stay mutually consistent. This predates the diff and the live config is unaffected. | #63 latent |

Invariant check: **PASS.** On the enhanced path, with the flag and the switch on, a person the BLE-leads rule overruled to `away` is never appended to `recognized`. Every other person's decision is unchanged.
