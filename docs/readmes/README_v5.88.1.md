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

## Live validation

*To be written back post-restart.*
