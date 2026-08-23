# v5.88.0 — Governed thermostat borrows (excursion primitive)

**Tier 3.** Four framing-disjoint reviews, six fix-up rounds, one operator-ruled design change.

## What this does

URA regularly moves a thermostat away from where it should be and intends to put it back:
the **AC ramp-down nudge**, a **compromise** between rooms in one zone, **solar banking**,
**pre-heat**, and an **egress pause** when a door opens.

Before this cycle each of those five had its own hand-rolled "put it back". An audit found
**13 setpoint-write sites, of which 9 never restored a preset at all** — which is how a zone
could sit in `manual` for 14 hours straight, because `should_change_preset` refuses to act on
a `manual` zone and nothing ever cleared it.

This ships one primitive that all five now share: **snapshot what the thermostat was on →
make the temporary change → put exactly that back**, with the state persisted so it survives
a restart.

## Design decisions worth recording

**The excursion is UNOPINIONATED.** It restores what it *found*, not what it thinks *should*
be there. Operator ruling: borrowers put back what they found; deciders decide. This deleted a
field, a producer contract, a resolver, an acceptance criterion and a mutation drill — and
dissolved the self-disarm defect as a side effect rather than needing a fix for it.

**The lease gate was STRIPPED before ship.** Rev-4/5 included a lease that made decision ticks
defer for a zone under active borrow. All four reviews found it created *a suppression with no
reliable discharge* — the same bug class as the lockout it insured against. Its value only
begins once `HVAC-MANUAL-PRESET-CONTRACT-1` removes today's accidental `manual`-based
protection, which has not landed. Operator ruling: strip it, re-derive it later against
whatever that cycle's shape turns out to be. **Not** parked for resumption.

**`restore_ok` is three-valued and load-bearing.** `True` = attempted and landed.
`False` = attempted and the wire is wrong. `None` = deliberately did not attempt (policy skip:
immunity, comfort-delay). Conflating `None` with `False` would make the alert cry wolf on every
comfort defer.

## Control

**`Governed thermostat borrows`** — HVAC Coordinator config flow (not a dashboard switch;
turning this off should require deliberate action, not a tap). Default ON.

BEGIN-ONLY: OFF stops new borrows being recorded; in-flight borrows still complete and still
restore, and the thermostat is still written and restored by the legacy path.

**Honest limit, stated on the label itself:** OFF is a *partial* back-out. It does not revert
three behaviour changes (unfiltered snapshot, unconditional preset restore, blocking restore
wait). A full revert is a rollback to v5.87.0.

## Observability

**`sensor.ura_hvac_coordinator_governed_thermostat_borrows`** (diagnostic). State = active borrow count.
Attributes carry per-borrow `zone`, `kind`, **`site`**, `entity_id`, `started`, `expires_at`,
the snapshot it will restore to, and `excursion_id` as the join key into
`hvac_excursion_events` / `ac_ramp_events`.

**Self-validating by design:** `started_today` is broken out per kind so
`started_today.nudge` can be reconciled against the independently-produced `ac_nudges_today`.
Two producers, one invariant — divergence is itself the alarm, and neither number has to be
trusted alone.

**Absolute timestamps, never countdowns** (`expires_at`, not `expires_in_s`). HA records
attribute changes; a countdown would be a recorder write per tick per zone, which is the flood
pattern v5.87.0 just fixed on a flash disk at 51% life.

**On restore failure:** an unconditional `_LOGGER.error` tagged
`[GOVERNED BORROW RESTORE FAILED]` carrying the snapshot and the observed wire state — fires
regardless of whether NM is enabled, configured or filtered, because NM recipients were once
empty and every alert was silently dropped. Plus a governed NM alert, kind
`borrow_restore_failed`, `Severity.MEDIUM` (deliberately not CRITICAL — Bug Class #16 documents
that CRITICAL bypasses quiet hours, the kill switch and the threshold; a thermostat that failed
to restore is a next-morning problem, not a 3am one). Observation-mode gated. Recipients,
preferences, quiet hours and thresholds all applied by the standard emit path; no filter was
weakened.

**Per-episode, not per-day:** the per-day latch is discharged by the next *successful* return
for the same `(kind, zone_id)`. Consistent failure yields one alert; fail → succeed → fail
yields two, because alternating failure is more alarming than steady failure. `restore_ok is
None` does not discharge.

## Acceptance criteria

- **Verify:** `sensor.ura_hvac_coordinator_governed_thermostat_borrows` exists, state `0` at idle.
- **Verify:** the config-flow field appears in HVAC Coordinator settings, default ON.
- **Verify:** `switch.ura_hvac_coordinator_excursion_primitive_enabled` is GONE.
- **Test:** 82 cycle tests pass; full-suite name-diff empty both directions vs develop
  (160 = 160 names), +71 net new passing.
- **Live (discriminating):** after a natural nudge, the sensor's `last_return` shows
  `restore_ok: true` AND the zone's `preset_mode` equals the pre-nudge preset. A nudge that
  leaves `preset_mode: manual` means snapshot-restore did not land.
- **Live (reconciliation):** `started_today.nudge` on the sensor equals `ac_nudges_today`.
  Divergence indicates the borrow path and the legacy counter disagree.
- **Live (restart):** restart mid-nudge — the zone must come back on its pre-nudge preset, not
  `manual`. This is the founding defect; it is the single most important check here.
- **Live (negative):** no `[GOVERNED BORROW RESTORE FAILED]` lines in the log under normal
  operation.

## Live validation — Validated 2026-08-22 (post-restart, partial)

| Criterion | Result | Evidence |
|---|---|---|
| Integration loads, all 42 entries | **PASS** | all entries progressed past `setup_in_progress`; `sensor.ura_hvac_coordinator_zone_1_status` back with `hvac_action: cooling` |
| Diagnostic sensor exists | **PASS** | `sensor.ura_hvac_coordinator_governed_thermostat_borrows` = `0` |
| Sensor shape correct at idle | **PASS** | `active_borrows: []`, `started_today: {}`, `returned_today: {}`, `restore_failed_today: {}`, `last_return: null` |
| **Config-flow value reaches the runtime** | **PASS** | `primitive_enabled: true` on the live sensor — proves the demoted knob seeds through end-to-end, which is the round-trip the switch removal put at risk |
| Old switch entity gone | **PASS** | `switch.ura_hvac_coordinator_excursion_primitive_enabled` → 404 |
| No URA / excursion ERROR at boot | **PASS** | zero matching ERROR/CRITICAL lines in 15 min post-restart |
| No restore failures | **PASS (vacuously)** | zero `[GOVERNED BORROW RESTORE FAILED]` lines — but no borrow has yet occurred, so this is an absence of failures, NOT evidence the restore path works |
| **Live restore after a natural nudge** | **PENDING** | requires a real nudge: `last_return.restore_ok == true` AND the zone's `preset_mode` NOT `manual` |
| **Reconciliation** `started_today.nudge` == `ac_nudges_today` | **PENDING** | needs at least one nudge |
| **Restart mid-nudge** | **PENDING** | the founding defect; the single most important check |

**Deployment note — deploy.sh failed twice and both were repaired manually:**
1. Step 6/7 (merge PR to master) failed on conflicts because develop had never absorbed the
   v5.87.0 release merge commit. Merged master into develop, pushed, merged PR #524.
2. Because the script exited at step 6, **step 7/7 never ran** — no tag, no GitHub release, so
   HACS saw nothing to install. Created the release manually.
3. Separately the `--why` gate collected reasoning but `vibememo_ship.py` exited 2 on a
   malformed argument; deploy.sh logged a WARNING and continued, so the release nearly shipped
   with no decision trail. Written manually.

**A documentation defect caught during validation:** this README and the rollback card both
originally named `sensor.ura_hvac_coordinator_thermostat_borrows`. The real entity_id is
`...governed_thermostat_borrows` — HA derived it from the friendly label. Corrected in both.

The three PENDING rows are organic-wait items. This README is not closed until they are filled.
