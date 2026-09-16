# v5.103.2 — Preset writes that actually stick (resume-then-pin)

Step 1 of `HVAC-SUPPLE-SEQUENCE-1`. **Tier 3.** This changes how URA writes
presets to the thermostats — it does not change *which* preset any decider
chooses.

---

## The mechanism, measured live

A Bryant/Carrier zone sitting in an **anonymous hold** (`hold_activity ==
"manual"`, which any raw setpoint write leaves behind) **will not accept a named
activity hold written over the top of it.** The cloud keeps the activity's
*setpoints* and **discards the name**.

Measured on zone 1, 2026-09-16:

| action | result |
|---|---|
| direct pin `sleep` | reverted to `manual` in **44 s** |
| direct pin `sleep` again | reverted in **68 s** |
| **`resume` then pin `sleep`** | **held 8 min across 9 cloud-confirmed refreshes, zero reverts** |

Both reverts landed inside the measured 42–79 s coordinator refresh window,
with the setpoints (70/75) persisting while the name dropped — a hold-rejection
signature, not a race.

**Why this matters:** while a zone reads `manual`, `should_change_preset`
returns False for everything, so vacancy grace and entry dwell are downstream of
a closed gate. Measured over 7 days: zone 1 spent **69.6%** of the time in
`manual` with a **17.9-hour** worst-case stranding.

---

## D1 — Per-kind suppression TTL

`SUPPRESS_TTL_SECONDS = 5` cannot span `resume → pin → refresh → verify`, so URA
would book its own second write as a human override.

Split rather than raised, because `_is_genuine_manual` has a **mid-window
passthrough**: inside the TTL a fresh transition *into* `manual` is still
genuine — **except** when tagged `kind="temp"`.

- `kind="preset"` → **120 s** (above the measured refresh window). Safe: human
  dial-grabs still pass through.
- `kind="temp"` → **stays 5 s.** It is the only path that swallows a genuine
  human manual flip — which is the *independent witness* the spurious-away
  metric depends on.

Both remain module constants: safety-adjacent, changing them should require
review.

## D2a — Resume-then-pin at the real chokepoint

In `emit_set_preset_mode` (`hvac_setpoint.py`), which was **already** the
documented preset-write funnel. **Conditional** on an anonymous hold, so a zone
on a named hold still pins directly — zone 3 does this continuously, and a
blanket resume would open a needless schedule window in the one zone that works.

Includes a **capability gate**: the clear is attempted only when the entity's own
`preset_modes` advertises `resume`. A non-Carrier thermostat falls through to
today's direct-pin behaviour instead of receiving a guaranteed-failing service
call on every write.

## D2b — Excursion return paths restore a preset

`hvac_predict.py` owns solar banking, pre-cool and pre-heat and contained **zero**
preset emissions: its return paths handed back correct *temperatures* while
leaving the zone in an anonymous hold. Both return paths now restore from the
`pre_preset` snapshot the excursion token already carried, per the established
unfiltered-snapshot semantic. Banking's restore is gated on the setpoint restore
having succeeded — we do not assert preset governance over a baseline we never
established.

---

## Review record

Two framing-disjoint **plan** reviews ran before the build and **changed what got
built**:

- **R1-CRITICAL-1** — the plan's proposed chokepoint *did not exist*: 11
  setpoint-writing functions, **0** referencing `borrow`, and `return_excursion`
  emits no writes. Building to it would have produced a half-applied fix across
  11 sites (Bug Class #53). Premise removed; the real chokepoint already existed.
- **R2-CRITICAL-2** — the plan conflated "make writes land" with "make
  excursions restore". Split into D2a / D2b, which are **disjoint**: D2a only
  helps sites that *call* the chokepoint, and the non-restoring sites never
  reach it.

An adversarial **build** review then found an **I3 violation in the fix itself**:

> `resume` succeeds → `pin` raises (cloud 504 / momentarily unavailable entity,
> both observed on this integration) → the exception escaped a bare `await` and
> the zone was left **cleared with no hold**, following the vendor schedule
> indefinitely. The repair would have caused the exact harm it exists to prevent.

Closed: the pin is wrapped, a clear obliges a pin, one retry, and otherwise an
**ERROR** — a zone released to an unused vendor schedule is not a debug event.

**Evidence:** 18 tests. Mutations covering blanket-resume, never-resume, TTL
collapse, TTL un-wired, both D2b restores, and the I3 retry each turn a
**different** test red; restore clean. Adjacent HVAC selection **identical with
and without** the change (21 failed / 1600 passed both ways — all pre-existing).

**Three hollow anchors were self-caught by the mutation drill** and rewritten via
AST. All three were string-based source assertions; one let the I3 retry be
deleted with the suite green. Recorded because it is a pattern, not a
coincidence.

---

## Live validation — the numeric prediction

Stated **before** the experiment, and it is the acceptance test:

> **Zone 1's manual occupancy falls from 69.6% toward zone 3's ~6%, and the
> multi-hour tail (max 1073 min) disappears.**
>
> If manual% stays high, **the mechanism is wrong and the cycle stops** rather
> than being patched.

- [ ] **Fast leading indicator (minutes):** a preset write lands — `hold_activity`
      comes back *named* after a refresh.
- [ ] **24 h:** zone 1 manual% measured against the 69.6% baseline.
- [ ] **Discriminating negative:** zone 3 (already 93.7% named) must **not**
      regress — if a blanket resume were firing there, its schedule exposure
      would show up as new short `manual` or unnamed episodes.
- [ ] No new URA ERROR; no `resume-then-pin: CLEARED ... could not pin` lines.

**Not in this release:** step 4 (`HVAC-ZONE-CONDITIONING-DEMAND-1`), the
conditioning-demand tap — that is the behaviour change with its own operator
checkpoint.
