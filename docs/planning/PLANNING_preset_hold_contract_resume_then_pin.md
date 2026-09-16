# PLANNING — Preset hold contract: resume-then-pin

**Card:** `HVAC-MANUAL-PRESET-CONTRACT-1` (step 1 of `HVAC-SUPPLE-SEQUENCE-1`)
**Tier:** 3 — operator-confirmed (`OPERATOR_RULINGS_2026_08_20` item 3)
**Status:** PLAN. Not build-ready — requires two framing-disjoint plan reviews first.
**Date:** 2026-09-16

---

## The falsifiable invariant

Tier 3 requires the cycle's load-bearing property stated so it can be *broken*,
not merely asserted:

> **I1 — After any URA-initiated thermostat write completes, the zone's
> `hold_activity` is a NAMED activity (never `"manual"`, never empty), on every
> reachable path.**

Corollaries that are part of the invariant, not separate nice-to-haves:

> **I2 —** URA never books its *own* write as a human override. A `resume`+`pin`
> pair produces **zero** `override_detected` rows with `mode=governed`.
>
> **I3 —** The zone is never left following the Bryant schedule. If the pin
> cannot be completed, the sequence must not have started.

Reviewer D's job is to find a legal, reachable configuration where I1, I2 or I3
is false — including in **pre-existing** code, not just the diff.

---

## Why this is Tier 3

- It threads one value (the preset hold) through **13 known setpoint-write
  sites** (S1–S14) — the "one missed site" shape, Bug Class #53.
- It is **comfort-impacting on live thermostats** in an occupied house, and a
  wrong path strands a zone off-preset for hours (measured: 14h35m).
- The area has a multi-fix-up history and at least four mechanisms asserted
  during 2026-08-22/23 were **later refuted by measurement**.

---

## Evidence this plan is built on (all measured, 2026-09-15/16)

| Finding | Evidence |
|---|---|
| A named hold cannot be pinned over an anonymous (`manual`) hold — setpoints land, the **name** is discarded | 2 direct preset writes to zone_1 reverted to `manual` in 44s and 68s; setpoints (70/75) persisted while the name dropped |
| `resume` clears the anonymous hold | `23:31:57  sleep\|manual` → `sleep\|(empty)` in the same second |
| A pin onto a **cleared** zone takes and persists | pin 23:32:35 → 9 cloud-confirmed updates through 23:40:28, **zero reverts** |
| Named indefinite holds work on this system generally | zone_3 holds `away`/`away`/`hold_until=null` continuously; `infinite_holds: True` is not the blocker |
| The integration writes local state optimistically | reverts land inside the **measured 42–79s** coordinator refresh window |
| URA never forces a post-write poll | `grep` finds **no** `async_request_refresh` anywhere in the HVAC files |

---

## D1 — Per-kind suppression TTL (prerequisite)

**Problem.** `SUPPRESS_TTL_SECONDS = 5` (`hvac_override.py:129`) cannot span
`resume → pin → refresh → verify`, so URA would book its own second write as a
human override — violating **I2** and manufacturing the very defect the cycle
removes.

**Why a global raise is wrong.** `_is_genuine_manual`
(`hvac_override.py:2345-2380`) implements a **mid-window passthrough**: inside
the TTL a fresh transition *into* `manual` is still genuine (*"URA never writes
manual"*), **except** when `_suppress_kind == "temp"`. So:

- `kind="preset"` → a long TTL is safe; human dial-grabs still pass through.
- `kind="temp"` → the only path that swallows a genuine manual flip. A long TTL
  here would blind us to *a human correcting the thermostat* — which is the
  **independent witness** step 3's spurious-away metric depends on.

**Change.** Split the constant. `SUPPRESS_TTL_SECONDS` stays **5** (temp).
Add a preset-write TTL sized from the measured 42–79s refresh window plus
headroom (~120s). Both stay **module constants** per the knob ladder —
safety-adjacent, changing them should require review.

### Acceptance criteria
- **Verify:** a `kind="temp"` suppression still expires at 5s (unchanged).
- **Verify:** a `kind="preset"` suppression survives a full pin+refresh+verify.
- **Verify (discriminating):** a *genuine* human flip to `manual` during a
  `kind="preset"` window is **still detected** — this is what makes the longer
  TTL safe rather than merely convenient.
- **Test:** mutation — collapse the preset TTL back to 5s and a test must go red.

---

## D2 — Resume-then-pin, through one chokepoint

**The sequence:**

```
emit_set_preset_mode(zone, target):
  1. READ  hold_activity
  2. NO-OP if hold_activity == target              (don't spend a cloud call)
  3. IF hold_activity is anonymous ("manual"):
         preset "resume"                            (CONDITIONAL — clear it)
  4. preset target                                  (pin; ADJACENT to 3)
  5. targeted coordinator REFRESH                   (collapse the optimistic window)
  6. VERIFY hold_activity == target; retry once; on persistent failure
     ledger row + NM
```

**Design constraints, each traceable to evidence:**

- **(3) is conditional.** zone_3 already holds a named `away` and URA's writes
  to it work — resume is only needed to escape an *anonymous* hold. Conditional
  keeps schedule exposure rare.
- **(3)→(4) must be adjacent** with no awaitable failure point between them
  (**I3**). After `resume` the zone follows the Bryant schedule until the pin
  lands. On 2026-09-16 that was harmless *by luck* — the schedule's current
  activity happened to be `sleep` 70/75. A resume at another hour exposes
  whatever the schedule says.
- **(5) uses REFRESH, never RELOAD.** `CARRIER-STALE-POLL-REFRESH-1` shipped a
  bounded reload (`hvac.py:4489+`) with a daily cap — that is a **staleness**
  remedy. Using it for write confirmation would burn the daily budget on routine
  writes, amid an open unattributed reload-storm problem
  (`URA-CONFIG-ENTRY-RELOAD-STORM-1`, ~5×/night).
- **(6) reuses `_verify_restore`** (`hvac_override.py:3916`, retry ×2 at 30s,
  tracked in `_verify_tasks`, cancelled on unload). Do not invent a second
  verifier.
- **ONE chokepoint.** The borrow/`return_excursion` primitive is bookkeeping-only
  today (`hvac_excursion.py:710`: *"each site performs its own (a)
  set_temperature → (b) set_preset_mode"*). Moving the sequence **into** it is
  what prevents a half-applied fix across 13 sites.

### Acceptance criteria
- **Verify:** a zone stuck in an anonymous hold ends on a NAMED hold after one
  restore (**I1**).
- **Verify (discriminating):** the ledger shows **zero** `override_detected`
  rows with `mode=governed` attributable to URA's own resume+pin (**I2**).
  *Under the opposite failure* — TTL too short — those rows appear. The
  observation therefore separates fix from failure.
- **Verify:** a zone already on the target preset produces **no** cloud call.
- **Verify:** a zone on a *different named* hold pins directly without `resume`.
- **Live:** after the next sanctioned excursion (solar banking / pre-cool)
  returns, `hold_activity` is a named activity — queried from the entity, not
  inferred from URA's intent.

---

## Non-goals (explicit)

- **Not** releasing zones to the Bryant schedule. `resume` is a transient step;
  the operator does not use that schedule and the end state is always a named
  hold.
- **Not** changing which preset any decider chooses — this cycle changes only
  *how a write is made*, never *what is written*.
- **Not** touching `should_change_preset`'s manual self-lockout in this cycle.
  It becomes far less reachable once I1 holds; whether it still needs a guard is
  a **re-measure question after** this ships.
- **Not** wiring the other 3 anomaly metrics, the dwell knob, or anything in
  step 4.

---

## Known risks

1. **Schedule exposure between resume and pin** (I3). Mitigation: adjacency, no
   awaitable failure point. Reviewer D should attack this specifically.
2. **Longer preset TTL widens the CLOUDFLAP overlap.**
   `ARRESTER-CLOUDFLAP-FALSEPOS-1`'s reconnect guard deliberately runs *before*
   `_is_genuine_manual` because a Carrier fault+reconnect inside the suppression
   window used to book a phantom override. A longer window makes that overlap
   more frequent — **test the ordering, don't assume it.**
3. **Extra cloud calls.** resume+pin is two writes where there was one. The
   no-op check (step 2) must actually fire, or we double the call rate on a
   cloud API that has a documented flap history.
4. **The `sleep`-activity question is unresolved.** We never established whether
   zone_1's `sleep` activity is configured the way zone_3's `away` is. If some
   activities are unconfigured per zone, pinning them may fail even after
   resume. Cheap test, still outstanding: pin `away` on zone_3 (operator cleared
   that zone; **zone_2 is off-limits**).

---

## Open questions for plan review

- Should the sequence emit a ledger row on **every** resume+pin, or only on
  verify failure? (Volume vs forensic value; the ledger is new and its row rate
  is unmeasured.)
- Does any consumer read `preset_mode == "manual"` as a *signal* rather than a
  fault? If so, making manual rare changes that consumer's behaviour — a
  producer/consumer check that has **not** been run yet.
- What happens if `resume` succeeds and the pin fails *at the cloud* (not
  locally)? The zone is then on the schedule with no hold. Does verify+retry
  recover it, or do we need an explicit rollback?
