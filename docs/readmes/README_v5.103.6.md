# v5.103.6 — EC SOC-ladder: consume the safe-ordered accessor (inversion guard)

Closes the consumed half of `EC-SOC-LADDER-XVALIDATE-1`: the energy coordinator's
decision sites for **fill-priority** and **EV-drain** now read through
`safely_ordered_ladder()`, so an inverted operator slider can no longer flip a
live gate for those two invariants. No new config, sensor, or knob.

## What changed

- `safely_ordered_ladder()` clamps the two invariants that have live consumers:
  **#4** `fill_priority_soc ≤ excess_solar_soc` (clamp down) and **#5**
  `ev_battery_drain_soc ≥ reserve_soc` (clamp up). Returns a 4-key ordered view.
- ~9 decision/display sites switched from raw attrs to the accessor
  (`energy.py` tick snapshot + EV/plug drain gates + status/summary surfaces;
  `energy_pool.py` fail-safe ride sites), with a per-tick snapshot so all
  consumers see one consistent value.
- On a **valid** ladder every switched site is identity-equivalent to the old
  raw read — **no behavior change on the happy path**; the clamp only bites an
  inverted config.

## Reviewed — Tier 2-DB, three framing-disjoint passes + a re-review

The first build over-reached: it also clamped three invariants (`drain_targets`,
`peak_buffer_target`, inclement floor) that have **no consumers** — dead coverage,
and it shipped a docstring falsely claiming inversions were impossible. All three
reviews (data-integrity / migration / adversarial-completeness) caught it, plus
two **hollow test anchors** that mirrored the production readout instead of
invoking it. The fix-up **reverted to the consumed scope**, restored the honest
Bug-Class-53 warning, and replaced the hollow anchors with per-site behavioral
tests (each goes red when its production line reverts to raw). A focused
re-review confirmed **SHIP**.

## Deliberately deferred (Plan Completion Tracking)

The plan's D1 originally said "clamp **every** ladder member." That is **not
delivered here, by design** — the other three invariants (`drain_targets`
monotonicity, `peak_buffer_target`, inclement floor) have ~25 raw readers, which
is a migration, not a residual. They remain **detect-only** today (save-time
reject in the config flow + the runtime `threshold_ladder_violation` anomaly,
both already shipped). The wiring is carded as **`EC-SOC-LADDER-FULL-WIRING-1`**
(Tier 2-DB, its own plan review).

## Evidence

- 19 new/changed tests. Per-site mutation drill under `.venv-ha`: reverting each
  switched production line to the raw attr turns a **named** test red (4 core + 2
  bonus sites). One tick line (`excess_solar`) is structurally non-divergent
  (the #4 clamp never changes `excess_solar`) — verified, not a coverage hole.
- Display-surface accessor calls are try/except-guarded so a bad ladder degrades
  the display rather than raising; the two actuation sites are deliberately
  unguarded (a broken ladder must not silently actuate on raw values).
- **Name-diff vs develop: byte-identical** — 305 pre-existing failing names both
  sides, **zero new**, +19 passes. Run under `.venv-ha`.

## Live validation

- [ ] Integration loads clean at v5.103.6; no new URA ERROR.
- [ ] No behavior change on the (valid) live ladder — EC decisions match v5.103.5.
- [ ] Discriminating check: with a deliberately inverted `fill_priority > excess_solar`
      (test config only), the actuation reads the clamped value, not the raw one.
