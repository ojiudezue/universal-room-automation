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

## Live Validation — Validated 2026-09-25 (write-back)

Deployed 2026-09-16 08:14 CDT. The recorder window (from 09-18 04:12) covers 5 restarts: 09-18 10:09, 09-18 16:07, 09-20 09:32, 09-21 23:19, and 09-25 18:05. Evidence: `climate.*` `preset_mode`/`hold_activity` from 10 min before each stop to 25 min after, joined against URA `ura_activity_log`.

| # | Criterion | Verdict | Observed evidence |
|---|---|---|---|
| 1 | D1: a zone on a named hold before the restart is on the same named hold after boot | **PASS** | 09-18 10:09: zone_2 `home`→`home`, zone_3 `away`→`away`. 09-18 16:07: zone_3 `away` held. 09-21 23:19: zone_1 `sleep`, zone_2 `sleep`, zone_3 `away` all held through boot (next change 23:38). 09-25 18:05: all three `away` held through boot. There was no boot stranding of the 09-16 `away → manual` kind. Exception: zone_1 read `manual` at 18:12:47, about 1 min after `homeassistant_start`. It coincides with `pre_arrival` rows for zone_1 at 18:12:05–18:12:21, so a pre-arrival setpoint write is the likely cause, not the ramp-audit (not proven). Limit: the recorder does not show whether an in-flight nudge (the specific D1 path) existed at each restart. |
| 2 | D1 negative: a zone genuinely in `manual` stays `manual` (no invented preset) | **INCONCLUSIVE** | Supporting: at the 09-20 09:32 restart, zone_1 was `manual` before and after boot, and URA logged `preset_change_locked_out` ("zone is in an anonymous manual hold") at 09:37:07, so it invented no preset. It became `away` at 09:39:10 with no URA activity row (not attributed). Not attributed: at the 09-18 10:09 restart, zone_1 was `manual` (since 10:03) and became `home` at 10:13:06 during boot with no URA activity row. That fits D1 correctly restoring a pre-nudge preset (if the 10:03 manual was a nudge) or it could be something else. Historical `hvac_excursion_state` rows are not kept. |
| 3 | D2: no behaviour change; `duty_cycle_off_phase` reads False | **As-expected (attribute absent)** | 0 `state_attributes` rows since 09-18 contain `duty_cycle_off_phase`. The flag was removed from the zone sensor (per D2 above), so "absent" replaces "reads False". There is no S14 kill-switch or offset-Number entity in `states_meta`. |
| 4 | No URA ERROR; no `resume-then-pin: CLEARED` lines | **PARTIAL** | Current boot only (since 09-25 18:11): 0 URA ERROR in `system_log`, and no `resume-then-pin` line in the latest 2000-line `error_log` window. Earlier boots' logs are not retained. |

The "still pending" zone_1 manual-% prediction below was **not met** and was later retracted as non-stationary; see the v5.103.2 write-back. **Verdicts: 1 PASS · 1 INCONCLUSIVE · 1 as-expected · 1 PARTIAL · 0 FAIL.**

**Still pending from v5.103.2:** the numeric prediction — zone 1's manual
occupancy falling from 69.6% toward ~6% over 24h. That is the acceptance test
for the whole arc, and if it does not move, the mechanism is wrong and the cycle
stops rather than being patched.
