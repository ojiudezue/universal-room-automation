# URA v5.85.1 — A room sensor can be removed again (SENSCAP-ORPHAN-1)

Tier 1 hotfix. One production file, one new test file. No new capability, no new knob, no
cross-coordinator reach.

## The defect

**Operator report (2026-08-20, Garage Hallway):** *"please fix the fact that I cannot clear the
camera person sensor. This error shows not matter what I do."* Every submit of the room's Sensors
step returned `sensor_capabilities_invalid`, regardless of what was changed.

**It was not specific to that room, that sensor, or camera sensors. Removing ANY sensor from ANY
room was impossible** whenever the per-entity capability dropdowns were rendered.

Mechanism:

1. The dropdowns (`caps_kind__<entity_id>`) are built from the room's **pre-edit** CONF lists
   (`config_flow.py:9687-9697`).
2. The operator removes a sensor and submits. That sensor's dropdown is **still in the submission** —
   the form was rendered before the edit.
3. The fold loop calls `derive_capability()` for it, which returns `None` (rule 3 — "the entity is
   not part of this room's Tier-1 wiring", `sensor_capability.py:187-188`).
4. `_kind == _default_kind` is therefore False, the no-op branch is missed, and the else-branch
   **writes a capability declaration for an entity that is no longer wired anywhere**.
5. The immediately following re-validate rejects it — `if entity_id not in known`
   (`sensor_capability.py:292-297`).
6. The step re-renders with the same stale dropdown. The loop is closed: the removal can never be
   saved.

The same wedge is reachable through the JSON blob instead of the dropdown, because the *first*
validate runs before the fold — so the prune has to happen on both paths.

## The fix

Three edits in `async_step_sensors`:

- Compute `_entities_now` — the union of the three lists **as submitted**.
- Prune JSON-authored declarations for de-wired entities *before* the first validate, logging what
  was dropped at INFO.
- In the fold loop, skip any dropdown whose entity is not in `_entities_now`, and drop any
  declaration it still carries.

Dropping the declaration is the correct semantics rather than a workaround: the operator has just
said the entity is no longer wired into the room, and the validator's own error text instructs them
to fix it by editing the CONF lists — which is exactly what they did.

## Verification

`quality/tests/test_senscap_orphan_removal.py` — 4 tests on the existing HA-mock options-flow
harness, driving the **real** `async_step_sensors` handler with the live Garage Hallway wiring as
the fixture:

| Test | Guards |
|---|---|
| `test_removing_camera_sensor_saves_despite_stale_dropdown` | Founding case — the operator's exact scenario |
| `test_removal_also_prunes_a_json_authored_declaration` | Same wedge via the JSON path (pre-fold validate) |
| `test_declaration_for_a_still_wired_entity_is_untouched` | Byte-identity — a no-removal save must be unchanged |
| `test_orphan_declaration_is_not_persisted_after_removal` | The opposite failure — silencing the error while still writing the orphan would block every FUTURE save of that room |

### Near-miss caught by the baseline name-diff — worth recording

The first version of this fix **broke four existing tests** and the targeted suites did not show it.
`test_v4516_failsafe_freshness` H3a-H3d extract the dropdown-merge region from `config_flow.py`
**verbatim** and `exec` it standalone — production source is that test's oracle. My `_entities_now`
was bound in the enclosing scope, outside the extracted region, so the slice raised
`NameError: name '_entities_now' is not defined`.

It surfaced only in the **full-suite name-diff against a clean baseline worktree**, not in the four
files I had been running. Fixed by deriving `_entities_now` inside the merge region from
`motion` / `mmwave` / `occupancy` (which that harness seeds), keeping the block self-contained —
the same constraint that already makes it elide its own relative import there.

Two process notes, because both nearly let it through:

- The first background run of the diff was **truncated to 12 lines** by the task runner, so the
  failure list was lost. A count-only comparison would have read as "145 failed" against an unknown
  baseline and told me nothing.
- Comparing **counts** would also have failed here: baseline 141 failed / 9211 passed vs first-fix
  145 failed / 9211 passed. The +4 looks like my four new tests failing. It was four *existing*
  tests breaking while my four never ran. Only the **name** diff distinguishes those.

Final state: baseline 141 failed / 9211 passed / 17 errors; with fix 141 failed / **9215** passed /
17 errors; **name diff empty in both directions**. The 141 pre-existing failures are the known
suite-order-pollution problem (`SUITE-ORDER-POLLUTION-1` / `TEST-STRATEGY-REARCH-1`) — they
reproduce identically without this change, and the two collection errors are excluded because they
fail at baseline too and pass in isolation.

**Mutation drill (not a source grep).** Both guards neutered, bytecode writing disabled and
`__pycache__` cleared: `2 failed, 2 passed`, failing with the operator's exact error string and the
validator's own message. Guards restored (0 `# MUT` markers, 0 `if False:`), file recompiles, and the drill was **re-run
after the fix changed** — 2 failed under mutation, 25 passed restored. The diff is purely additive:
73 insertions, 0 deletions.

## Acceptance criteria

- **Verify:** integration loads, zero URA errors on startup.
- **Live:** open Garage Hallway → Sensors, remove `binary_sensor.staircase_person_occupancy` from
  Pre-Combined Motion + Presence, submit. **Expected: saves cleanly, no
  `sensor_capabilities_invalid`.** This is the founding case and the only criterion that
  discriminates the fix from a build that merely silences the error.
- **Live:** re-open the same room and confirm the camera sensor is gone from the list AND that the
  room's `sensor_capabilities` no longer references it. A save that succeeds but leaves the orphan
  persisted would re-wedge the room on the next edit — check both.
- **Live (no-regression):** edit a different room's sensors WITHOUT removing anything and confirm it
  still saves clean.

## Not in this release

- **Egress camera repoint** (`EGRESS-CAMERA-DEAD-CONFIG-1`) — `egress_cameras` still names
  `camera.garage_a` / `camera.garage_b`, which are dead Frigate-1 IDs; the live entities are
  `camera.garage_a_2` / `camera.garage_b_2`. This is a **config** change, applied through the
  options flow after this deploy's restart. Two of five egress cameras currently contribute nothing.
- **`HVAC-MANUAL-PRESET-CONTRACT-1`** — untouched. Zone 2 was observed during this deploy sitting at
  78°F against a 71 cool ceiling, occupied, equipment idle, held in an indefinite `manual` that URA
  wrote itself and cannot write its way out of. That is the next cycle, not this one.
