# Memo: A single URA clock with per-consumer divisors (the "tick-wheel")

**Status:** idea of record — **parked, not scheduled.** Card:
`URA-CENTRAL-TICK-WHEEL-1`.
**Date:** 2026-09-16
**Origin:** surfaced while designing HVAC fast-in
(`HVAC-ZONE-CONDITIONING-DEMAND-1`, `THE_BINDING_CONSTRAINT`). Operator proposed
the generalization and asked for this record.

This memo exists so the idea — and the routes we walked to get here, including the
ones we struck down — are not re-derived from scratch next time. It is a record, not
a plan.

---

## The idea

Today URA has ~10+ independent periodic loops at heterogeneous, individually-jittered
cadences (room coordinator 30 s+jitter, census 30 s, energy `_solar_follow` 60 s,
safety 60 s, HVAC/energy/optimization 5 min, predictions 15 min, plus aggregation
retry/decay, sensor refreshers, perimeter/exterior sweeps). Each is its own
`async_track_time_interval`.

The tick-wheel replaces the pile with **one base clock** plus **per-consumer
divisors and phase offsets**:

- One timer fires at a base resolution (e.g. 1 s, or a coarser 5–10 s if 1 s is
  more than anything needs).
- Each consumer (coordinator / room / object) registers at a **divisor** — run every
  1×, 30× (30 s), 60× (60 s), 300× (5 min) — so **a fast base tick does NOT mean
  everything runs fast.** Most things run at a coarse multiple; a few run native.
- Each consumer also gets a **phase offset**, so consumers sharing a divisor do not
  all fire on the same base tick.

The value: one clock to reason about, uniform instrumentation, trivial to add a new
cadence, and the fast-in problem (act between 5-min ticks) becomes "register HVAC's
hot-and-occupied check at a smaller divisor" rather than "add another bespoke timer."

---

## Prior art in-repo (do NOT treat this as greenfield when it is built)

- **`energy._solar_follow`** — the energy coordinator already runs a 5-min decision
  loop *plus* a separate 60 s sub-loop (`energy.py:1382`, `SOLAR_FOLLOW_TICK_S`).
  "One coordinator, two cadences" is a proven pattern; the tick-wheel generalizes it.
- **`energy_pool._tick` reentrancy guard** (`energy_pool.py:4482`) — a consumer that
  guards against its own overlap. The tick-wheel needs this per consumer (a slow
  consumer must not stall or double-fire); the pattern already exists.
- **`coordinator.py:630` `30 + jitter`** — today's per-loop jitter. Under the
  tick-wheel this becomes the phase-offset, done centrally instead of per-loop.
- `HVAC-TICK-LITERAL-1` (done) named the 5-min HVAC quantum as a constant — the
  divisor a tick-wheel would assign HVAC's normal cycle.

---

## Routes considered — and the ones struck down (the history)

1. **Blanket-reduce the HVAC loop to 60 s.** **Struck.** 5× evaluations/hour → 5×
   activity-log + anomaly-detection DB volume, 5× compute, 5× *opportunities* to
   write Carrier cloud (change-gated, so not 5× writes, but more chances, against a
   reload-storm / write-sensitivity history). Reading faster than Carrier's own
   42–79 s refresh gains nothing. Only the hot-and-occupied case needs 60 s; ~95% of
   HVAC decisions are fine at 5 min. 5× cost for a narrow benefit.

2. **Central loop rejected on thundering-herd grounds.** **This objection was WRONG
   and is formally struck.** It conflated "one clock" with "everything fires on the
   same tick." A tick-wheel with per-consumer divisors + phase offsets makes the herd
   a solved design detail — you stagger which base-ticks each consumer wakes on. The
   herd is **not** a reason against the central loop.
   - Caveat that remains true and must be *designed for* (not an objection, a
     constraint): event-loop stalls trip the HA watchdog into a ~5-min outage
     (`RELOAD-WATCHDOG-HAZARD` done; optimizer write-flood incident). The tick-wheel
     must therefore never fan out work synchronously on one base tick — offsets +
     per-consumer reentrancy guards + bounded per-tick work are load-bearing, and
     they are exactly what makes it *safer* than a naive shared loop, not riskier.

3. **Targeted 60 s HVAC fast sub-loop (CHOSEN NOW).** Mirror `_solar_follow`: a
   dedicated 60 s loop that evaluates *only* the hot-and-occupied fast-in decision,
   leaving the 5-min full cycle intact. Proven pattern, bounded blast radius, no
   refactor. This is the increment we build for the HVAC cycle; the tick-wheel is the
   thing it is a special case of.

---

## Why parked (not built now)

- **Marginal benefit today = one fast-in need.** One need does not pay for a
  system-wide timing refactor. The targeted sub-loop captures the benefit now.
- **It deserves to be a deliberate re-architecture,** not bolted on. When it is
  built it should replace the pile of `async_track_time_interval`s wholesale, with
  divisors + offsets + reentrancy guards designed in — which is *cleaner* than today,
  not merely equivalent.

## Revival trigger

Build the tick-wheel when **either**:
- a **3rd/4th dedicated fast sub-loop need** appears (two — `_solar_follow` and the
  HVAC fast sub-loop — is a pattern; a third is the evidence to generalize), **or**
- a **deliberate re-architecture pass opens** for coordinator timing / the loop
  layer for any reason.

At that point: extract a single base clock, migrate each existing loop to a
(divisor, phase-offset) registration, carry over the per-consumer reentrancy guard
pattern, and delete the bespoke timers. Do it as its own tiered cycle — it is a
shared-primitive change (Tier 3), and every current loop is a caller.
