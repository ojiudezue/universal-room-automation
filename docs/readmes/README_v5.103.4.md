# v5.103.4 — Measure the harm, not the proxy

Two instruments, no behaviour change. Both exist so the next two decisions in
`HVAC-SUPPLE-SEQUENCE-1` are made on measurement instead of on a hypothesis.

---

## D1 — The preset-lockout instrument (`HVAC-PRESET-LOCKOUT-TELEMETRY-1`)

**Why this exists, in the operator's framing:** *"what are we measuring? we are
calculating going down to 6% — what does that actually mean?"*

It was a fair challenge and it changed the release. `manual%` is a **proxy**, and
the ~6% target was **borrowed from zone_3** — a transit corridor that is
structurally different from zone_1. What we actually care about is whether URA
can **control** a zone: how often it decides a preset and is **refused**.

That refusal happens at exactly one place — the `should_change_preset` guard in
`hvac.py` — and until now it was **silent**. `should_change_preset` is a pure
two-string function with no logger and no counter, so a zone could sit locked out
for hours with nothing recorded anywhere.

**Discriminating, by construction.** The guard returns False for two reasons that
are not remotely the same thing, and recording both would drown the signal:

| `preset_mode` | meaning | recorded? |
|---|---|---|
| `== effective_preset` | already at target — a benign no-op | **no** |
| `== "manual"` | **LOCKOUT** — URA wanted a different preset and was refused | **yes** |

**Edge-triggered, not per-tick.** At the 5-minute decision quantum a per-tick row
would be ~288/zone/day and the ledger would be unreadable. One row when an
episode *begins*, carrying what URA wanted; the episode discharges when the zone
leaves `manual` (per suppression-needs-a-discharge — an episode that never ends
would under-count every later lockout).

Emits a durable activity row (`action="preset_change_locked_out"`) plus a
`_DailyCounter`.

### What this is for

It arbitrates between two **disjoint** explanations of why zone_1 moved
69.6% → 46.0% instead of toward ~6%:

- **resume-then-pin (shipped v5.103.2)** fixes *"the write does not land"*;
- **`HVAC-PRESET-LOCKOUT-ESCAPE-1`** is *"the write is never attempted"* — the
  guard refuses on the premise that `manual` implies a human, but URA's own raw
  setpoint writes create `manual`, and the arrester suppresses itself on URA's
  own writes, so **nobody acts**.

The v5.103.2 result is consistent with the second: the paths that explicitly
bypass the guard got fixed, the routine house-state path did not. **That remains
a hypothesis, and this release is deliberately the instrument rather than the
fix.** A non-zero lockout count on zone_1 confirms it; a near-zero count refutes
it and sends the residual 46% back to be re-diagnosed.

## D2 — Short-cycle baselines persist at the day rollover (`HVAC-ANOMALY-BLIND-1` residual B4)

The daily `short_cycle_rate` observation was recorded at the rollover but only
**persisted at clean teardown**, so any unclean restart threw it away. Reviewed
twice framing-disjoint (A local-correctness + no-op invariant; B
async/lifecycle/write-path + test-authority-by-mutation), both SHIP, with **4
in-cycle fix-ups** taken:

- reset/stamp reordered **above** the save so a shutdown `CancelledError` cannot
  strand the date;
- the durable snapshot nudged into the same tick;
- the swallowed handler raised to **error** level;
- a real-class coroutine contract assert so a stub cannot hide an inert feature.

**Why it ships now, with D1:** `short_cycle_rate` is the **cycle-count guard** for
step 6's energy metric. Step 3's baseline showed zone_3 short-cycles hardest
(113 cool cycles on 62.7h, ~0.55h/cycle, vs zone_1's ~0.87h/cycle) — and zone_3
is precisely the zone step 4 targets. A conditioning "fix" that cut episodes by
short-cycling harder would be a **regression the duty number alone would hide**.
The guard has to be live *before* step 4 is judged, not after.

---

## Evidence

- **98 tests** across the two changes, all green. Every load-bearing element of
  B4 is mutation-anchored to a **named** test (3 die on the save, 1 on the
  durability nudge).
- A `DailyCounter` with an empty `reason` **raises ValueError** and would have
  crashed the coordinator at init. Caught by reading the primitive's signature
  rather than assuming it.
- **Harness trap found and fixed during this gate** (folded into
  `TEST-HARNESS-REAL-HA-DEFAULT-1`): the documented test command named bare
  `python3`, which is 3.9 here and lacks phcc — it produced **98 errors on
  perfectly green code**, and the errors read like real reds (`fixture
  'expected_lingering_tasks' not found`) rather than like a wrong interpreter.
  `CLAUDE.md` and `ura-validator.md` now name `.venv-ha/bin/python` explicitly.

---

## Live validation

### Validated 2026-09-16 (post-restart, wiring only)

The house restarted onto v5.103.4 cleanly. What is provable at boot is the
**wiring**, not the discriminator — the discriminator is a ~24h DB read
(below), per no-soak.

| Check | Result | Evidence |
|---|---|---|
| Integration loaded at v5.103.4 | **PASS** | HACS `installed_version: v5.103.4`, `pending_update: false` |
| No setup crash / RecursionError | **PASS** | `source=system` scan: zero ERROR entries for the integration |
| `_DailyCounter` init did not raise | **PASS** | coordinator up and emitting; the empty-`reason` ValueError that would crash init did not fire |
| No `resume-then-pin: CLEARED … could not pin` | **PASS** | absent from the system log |
| Boot restore did not break setpoint restore | **PASS** | no boot-path exception; D1-of-v5.103.3 wrapper held |

Boot transients seen and dismissed: the known aggregation coverage re-anchor
(`aggregation.py:916`, INCOMPLETE until midnight) and routine SPAN/SOC/weather
unavailability warnings — all pre-existing, none from this cycle.

### Pending — the discriminator (one-shot DB read at ~24h, NOT a watch)

- [ ] **D1 is the point of the release:** within a few hours, read the daily
      lockout counter and the `preset_change_locked_out` rows per zone. This is
      the number that decides whether `HVAC-PRESET-LOCKOUT-ESCAPE-1` gets built.
- [ ] **D1 discriminating negative:** zone_3 (93.7% on named presets) should show
      **few or no** lockouts. If it shows as many as zone_1, the instrument is
      measuring something other than the harm.
- [ ] **D1 no-op exclusion holds:** no row should appear for a zone already at its
      target preset — if the counts look like ~288/zone/day, the edge-trigger or
      the discrimination has failed.
- [ ] **D2:** a `metric_baselines` read shows a `short_cycle_rate` sample
      surviving a restart. Read the table directly — **not** a grep of the new
      info log, which fires even on a swallowed write failure.
- [ ] No new URA ERROR.

**Still pending from v5.103.2, and not settled by this release:** zone_1's manual
occupancy against the 69.6% baseline, **re-measured on a daytime window**. The
46.0% figure came from a 6.9h overnight window and is not comparable to the 7-day
baseline. Step 1 is not closed until that number is met or explicitly abandoned
with a reason; *"directionally right"* is not acceptance.

**Not in this release:** step 4 (`HVAC-ZONE-CONDITIONING-DEMAND-1`), the
conditioning-demand tap — the live comfort/spend change, which keeps its operator
checkpoint.
