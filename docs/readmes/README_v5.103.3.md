# v5.103.3 — Restarts stop stranding zones, and S14 is removed

Two changes, both closing out the preset-hold arc. Neither adds behaviour; one
restores what a restart used to destroy, the other deletes a dormant writer.

---

## D1 — Boot restore puts the preset back (`HVAC-BOOT-RAMP-AUDIT-STRANDS-PRESET-1`)

**Observed live 2026-09-16**, seconds after a restart:

```
01:15:57  zone_3  away   | away     ← healthy, as it had been all week
01:17:04  zone_3  manual | manual   ← the boot path strands it
```

The startup ramp audit restores an in-flight nudge's **setpoint** and never its
**preset**. A raw setpoint write is what creates an anonymous hold, so every
restart left zones off-preset. At the measured ~2.9 restarts/day that is a
recurring insult — and before v5.103.2 only the vacancy bypass could undo it,
which is much of why an *occupied* zone could strand for 17.9h while a transit
corridor recovered in ~2 minutes.

**Why it never restored one:** `_restore_after_nudge` reads
`self._nudge_pre_preset`, which is **RAM-only and empty after a restart**. The
boot path had nothing to restore *to*.

**The snapshot does survive** — `hvac_excursion_state.pre_preset` is a persisted
column and `get_all_excursion_rows()` already existed. We simply never read it.
No schema migration (checked: `ac_reset_state` has the target but no preset
column). The row load is wrapped so an unavailable table can never break the
*setpoint* restore, which is the load-bearing half.

## D2 — S14 off-phase ceiling hold: **removed**

S14 (from the 2026-08-11 flap fix) held `home_target_high + OFFSET` with a raw
setpoint write during an occupied off-phase, instead of writing `preset=away`.
Kind intent: save energy without abandoning an occupied room.

**The defect:** a raw setpoint write puts the zone into `manual`, and
`should_change_preset` refuses to act on a manual zone — so **S14 created the
exact condition that prevented its own documented exit** ("holds until the next
preset transition"). No timer, no decay, no restore. The flap fix had introduced
a permanent-manual writer.

**Removed rather than repaired**, and the costing was lopsided once one fact was
established: the kill switch had been **off for weeks**, so this limb was already
dead and the away path was already what ran.

- **Removal is behaviour-neutral** — the fall-through *is* what removal leaves.
- **Repair would have re-enabled** a behaviour the operator disabled on instinct
  and later called *"marginal — possibly should not have built it at all."*

Gone with it: the kill-switch entity and the offset Number. A control that
governs nothing is a footgun — an operator could toggle it and reasonably expect
an effect. The zone sensor also no longer advertises the now-dead flag.

### The deliberate trade this overturns — recorded, not dropped

The no-release behaviour was **intended**, encoded in three artifacts: the
planning doc, a live acceptance criterion, and the shipped test
`test_ceiling_held_until_next_preset_transition`.

That test is the interesting one. After removal it would have kept **passing —
vacuously**, because with nothing writing a ceiling there is trivially no
follow-on restore. A test that passes for the opposite reason is worse than one
that fails. It is **inverted** in the new suite rather than deleted quietly.

The original rationale is preserved for anyone who revisits: a release write is
itself another preset transition, i.e. **flap** — the very thing PRESET-FLAP-1
was fixing. Any re-introduction must fire **once per off-phase, not per tick**.

---

## Evidence

- 26 tests across the two changes. Mutations: pointing the boot restore at the
  RAM map (a **silent no-op at boot** — the original defect wearing a fix's
  clothes) and deleting the restore each go red on the right test; re-adding an
  S14-style writer goes red on the inverted guarantee.
- **Name-diff regression: ZERO new failures** across the HVAC surface. Counts
  alone were not trusted — the comparison is on failure *name sets*.
- Two superseded S14 suites removed (preserved in git history). One of them
  source-sliced the deleted method and failed at **collection**, which is why it
  broke an entire selection rather than just itself — worth knowing for future
  removals.

---

## Live validation

- [ ] **D1 (first restart after this ships):** a zone on a NAMED hold before the
      restart is on that **same** named hold once boot settles. The
      before-picture is above: `away|away → manual|manual` at 01:17:04.
- [ ] **D1 discriminating negative:** a zone genuinely in `manual` before the
      restart still is — we are not inventing a preset it never had.
- [ ] **D2:** no behaviour change expected anywhere, because the kill switch was
      already off. The `duty_cycle_off_phase` attribute should now read False.
- [ ] No new URA ERROR; no `resume-then-pin: CLEARED … could not pin` lines.

**Still pending from v5.103.2:** the numeric prediction — zone 1's manual
occupancy falling from 69.6% toward ~6% over 24h. That is the acceptance test
for the whole arc, and if it does not move, the mechanism is wrong and the cycle
stops rather than being patched.
