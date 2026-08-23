# v5.88.1 — the AC hard reset now restores a preset

## The defect

`_verify_restore` (`hvac_override.py`) contained **zero preset references**. The hard-reset
ladder turned the thermostat off, held, restored the MODE and the SETPOINT — and left whatever
preset resulted. After a raw setpoint write on a Carrier/Bryant that is `manual`, and
`should_change_preset` refuses to act on a manual zone. So a hard-reset zone was locked out of
preset governance until something external moved it.

That is the same defect v5.88.0 shipped to eliminate everywhere else, surviving in the one path
that cycle deliberately excluded.

## It was specified and dropped

`PLANNING_hvac_governed_excursion.md` scope decisions state that `hard_reset_preset_assert` must
NOT be a borrow kind (so it cannot be wired by analogy later), and that instead a one-line
`emit_set_preset_mode(snapshot_preset)` belongs in `_verify_restore`'s success branch. Review D
flagged it missing. Six fix-up rounds never restored it, because fix-ups were driven off review
FINDINGS and nobody diffed the plan's own scope decisions against what shipped.

**Process change:** before closing a cycle, diff the plan's scope decisions against what shipped —
not just the review findings against what was fixed.

## What shipped

- Pre-reset preset captured at reset start and threaded through `_restore_after_reset`.
- `emit_set_preset_mode` in `_verify_restore`'s SUCCESS branch, `blocking=True`, with
  `suppress(kind="preset")` so the arrester does not book URA's own write as a human override.
  Mirrors the `cancel_nudge` restore pattern.
- **Unopinionated**, per the shipped ruling: restores what it FOUND, including `manual`.
  (`manual` is a writable preset on these thermostats — verified live on all three.)
- **Fail-soft**: a failed preset emit does not break the existing mode/setpoint restore.
- Operator-facing labels: sensor -> **"Temporary Thermostat Changes"**; config toggle ->
  **"Restore thermostats after temporary changes"** (`strings.json` + `translations/en.json` in
  lockstep). Code, tables, columns, entity_ids and the `borrow_restore_failed` NM kind unchanged.

## Acceptance criteria

- **Test:** `TestAcResetPresetRestore` — 3 anchors on enclosing methods. Neuter drill: comment out
  the preset emit -> `test_restore_after_reset_success_branch_emits_preset` fails.
- **Gate:** full-suite name-diff vs develop empty both directions.
- **Live:** after any hard reset, the zone's `preset_mode` is NOT `manual`.
- **Live (discriminating):** a hard reset that leaves `manual` means the snapshot or the emit did
  not land; a hard reset that leaves the PRE-RESET preset means it worked. Those differ, so the
  observation discriminates.

## Live validation — Validated 2026-08-22 (post-restart)

| Criterion | Result | Evidence |
|---|---|---|
| Integration loads | **PASS** | zone status sensors back; `hvac_action: cooling` on z1 and z3 |
| Version live | **PASS** | manifest on the HA host reads `v5.88.1` |
| Sensor label renamed | **PASS** | friendly_name = `URA: HVAC Coordinator Temporary Thermostat Changes` |
| Config-flow value reaches runtime | **PASS** | `primitive_enabled: true` on the live sensor |
| Borrow sensor healthy at idle | **PASS** | `active_borrows: []`, counters empty, `last_return: null` (fresh boot) |
| No URA / excursion ERRORs | **PASS** | zero matching ERROR/CRITICAL lines post-restart |
| No restore failures | **PASS (vacuously)** | zero `[GOVERNED BORROW RESTORE FAILED]` — but no borrow has occurred since boot, so this is an absence of failures, NOT evidence the path works |
| Preset assert present in shipped code | **PASS** | `_verify_restore` on the HA host contains 1 `emit_set_preset_mode` |
| **Hard reset leaves a non-`manual` preset** | **PENDING** | requires an actual hard reset. Resets fire roughly never today (11 ever, 0 in six days) because escalation is gated on nudge-ineffective and nudges essentially never fail — so this may not be observable until AC-RAMP-NO-RECURRENCE-ESCALATION-1 makes resets reachable. That is the honest position: **this fix is verified in code and by mutation drill, not yet in the field.** |

**Note on zone_3 `preset_mode: manual`:** this is the operator's own manual reset at ~02:00
(they turn the AC off and back to auto when they see high draw at setpoint). A human at the
thermostat, not a URA-induced manual — and precisely the manual labour the escalation cycle exists
to remove.

**Deploy note:** clean run through all 7 deploy steps, unlike v5.88.0 which failed at step 6 (the
develop->master PR conflict) and therefore never ran step 7. Develop now carries master's merge
commit, so that failure mode is closed.
