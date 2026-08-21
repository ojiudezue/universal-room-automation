# URA v5.87.0 — Operator knobs actually reach the code; accumulators survive restart; the log stops shouting

Three cards, one deploy. No new capability — this release makes existing machinery honest.

## HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 — the knobs you set now reach the coordinator

**Found by accident.** A forced nudge ran a 300 s hold while the Number entity plainly read 2 min.
First diagnosis ("the knobs are inert") was wrong; second ("the force button ignores config") was
also wrong. The operator refused both and asked for re-verification. The truth: 937/943 auto nudges
DID honour the configured 120 s — the single 300 s hold in all history was the one forced 26 minutes
after a restart.

**It is a race, not an absence.** A seeding path exists (`async_added_to_hass` →
`_push_to_controller`, with a retry on the HVAC tick signal). It usually lands. When it doesn't, the
entity displays the operator's value while the coordinator runs the module default.

- **Sub-controller arm:** one deterministic seed at CM setup iterating `_HVAC_TUNABLE_DISPATCH` — the
  same dict `_apply_in_place` uses, so seed and options-update stay lockstep and a 15th tunable is
  seeded for free.
- **Zone arm:** the per-zone kWh threshold does **not** use `entry.options` at all (it is
  `RestoreEntity`-backed), so it needed a separate mechanism, seeded after `async_start()` because
  that is what populates the zone list. An AST test asserts that ordering.
- **This one fails UNSAFE**, unlike the duration knob. `ZoneState.kwh_rate_threshold` defaults to
  **0.8 kW** while production runs **1.30**. A boot race makes detection *more* sensitive, firing
  more nudges — and every nudge is two raw setpoint writes, so more manual-preset risk. Every
  unresolvable seed now emits a WARNING carrying the literal phrase `UNSAFE direction`.
- Sweep: exactly **one** zone-targeted Number exists, with a test that fails if a second appears.

## RESTART-SAFETY-DOCTRINE-1 (tranche 1) — accumulators that could never arm

Measured denominator first: **20 restarts in 6.9 days, median interval 5.55 h.** That yields the rule
the audit could not state without it — **tick-driven accumulators are fine** (10 samples in ~50 min),
**event-driven ones are structurally unreachable** and report nominal the entire time.

- **F1/F2:** `safety.py` and `manager.py` called `load_baselines` and never `save_baselines`. Now
  symmetric with the four existing exemplars. Teardown-save verified sufficient: **21
  `homeassistant_start` vs 21 `homeassistant_stop`** in 14 days — every restart in the window was clean.
- **`DailyCounter`** primitive collapses five identical rollover sites, each classified
  PERSIST / RESET / REBUILD with a stated reason. Doctrine is a *declaration requirement*, not
  "persist everything" — the Temp Arrester Override deliberately does not persist, and a blanket rule
  would have broken it.
- Deferred with reason, not dropped: the arrester trio and the repo-wide declaration tag, both of
  which edit `hvac_override.py` and would collide with the in-flight excursion cycle.

## RECORDER-BLOAT-LOGFLOOD-1 (absorbs D2-CANARY-GUEST-PREDICATE-1)

31 GB of recorder for 7 days, on flash at 51 % life. A single 5-hour window carried **~8,100 URA
WARNING lines from five messages**.

- **Duty-cycle-stuck warnings (3,565 — the largest source, not the canary).** A stuck sensor is a
  *persistent state*, not an event; re-announcing it every tick was the defect. Now edge-triggered:
  one WARNING on entry, one INFO on release, current stuck set exposed as a diagnostic. Deliberately
  **not** demoted to debug — the operator must still see it.
- **D2 canary (2,525):** card analysis independently verified against source — the assertion is true,
  the guard premise was always false. Re-guarded and demoted to debug.
- **The camera flood was not actually fixed by v5.86.0.** The shipped warn-once covered
  `resolve_configured_cameras` but **not** the sister `resolve_camera_entity`, called every tick from
  `perimeter_alert.py:3805` — *that* was the real flood path. Corrected here.

## Verification

**Full-suite serial name-diff vs the v5.85.1 baseline: empty in both directions.**
141 failed / 9371 passed / 17 errors vs 141 / 9215 / 17 — **+156 passing**, identical failure set.
The 141 pre-existing failures are the known order-pollution issue.

Mutation drills run on every wire-in, both directions, each failing a *named* test: F1/F2 save call
sites, the sub-controller seed, the zone seed, the RestoreState shape guard, the duty-cycle
enter/release guards, and the WARNING elevation.

### Three regressions the integration caught that the branches could not

Each branch was green alone; these appeared only when merged and run serially.

1. **`DailyCounter` used bare `datetime.utcnow()`** — Bug Class #11, caught by an existing guard.
   The sweep then found `hvac.py` passing a *local*-clock date into the counter's UTC rollover — a
   local/UTC mix exactly at the boundary hour.
2. **The zone seed called `await RestoreStateData.async_get(hass)`** — which does not exist as an
   awaitable. It raised `TypeError`, a defensive `except` swallowed it, and the seed silently fell
   back to the **unsafe** 0.8. The fix for the silent-failure bug had itself failed silently. The
   repaired version **removes** a defensive except rather than adding one, and its new test mirrors
   the *real* HA surface — the prior tests mocked the broken shape, so they passed against broken
   production.
3. **A fixed-width source-slice test** truncated again as `__init__` grew. Now bounded by structure
   (`def __init__` → next method), mutation-verified to still catch a real defect.

## Acceptance criteria

- **Verify:** loads, zero URA ERROR lines, all coordinators up.
- **Live (seeding, discriminating):** after a restart, read the coordinator's *runtime* nudge
  duration and the zone's `kwh_rate_threshold` — not the entity states. The entities were never the
  ones lying. Expect 2 min and 1.30 respectively; a 5 / 0.8 pair means the seed did not land.
- **Live (log flood):** the five named messages drop from ~8,100 per 5 h to single digits. Check the
  duty-cycle set is still *visible* on the diagnostic attribute — silence alone would be a
  regression, not a fix.
- **Live (baselines):** after a clean restart, safety and manager anomaly baselines are non-empty.
