# Wave review record part 2 — energy hygiene · BLE-cancel census

Companion to `wave2026_07_13_presence_zone_writeverify.md`. Wave deploy: v5.16.0.

---

## Cycle 4 — BLE-cancel census (Tier 2-DB, operator-classified SENSITIVE)

**Build** `2f864ac7` · **Fix-up** `a3e5c49b` · **Focused re-review: SHIP** · doc-drift fix `1b07493a`
**Plan:** `PLANNING_census_ble_cancel_unrecognized.md` (re-emitted after tree-churn file loss; committed `282193dd`)

| Severity | Found | Fixed | Notes |
|---|---:|---:|---|
| CRITICAL | 1 | 1 | Would have crashed the census pipeline on deploy |
| HIGH | 3 | 3 | |
| MED | 4 | 3 fixed, 1 accepted+documented | |
| LOW | 4 | 3 | |

**The CRITICAL (B-C1 = C-CRIT-1):** the committed build was MISSING two
hunks its own report claimed (the `CensusZoneResult.ble_cancelled_count`
field + init attr) — concurrent-builder tree contention silently dropped
them after the builder's correct edits. Shipped as-was, every
enhanced-census cycle (default ON) would raise TypeError, swallowed into a
generic error log → the census subsystem silently dies (v5.8.0 incident
class). All 21 build tests bypassed the real construction path. **Fixed**
with the field + an end-to-end `_apply_enhanced_house_census` test whose
removal-mutation reds with the exact TypeError. **Process consequence:
parallel builders now get worktree isolation (standing rule).**

**HIGHs:** per-camera-subtraction-before-dedup defeated I2 exactly in the
motivating case (playroom×2) and was camera-order-dependent → **redesigned
to a per-area 4-step** (collect → per-area MAX → subtract
min(area_max, ble_here) → sum; order-independent, once-per-area
diagnostic); room→area join key used the name-vs-registry-id inversion
(renamed areas would silently never cancel) → rebuilt from room
`CONF_AREA_ID`; unmapped residents bucketed under None and could cancel
GUESTS on null-area cameras (I1 breach) → unmapped cancels nothing (two
independent layers, mutation-anchored).

**Staleness family:** the 'lost' location sentinel was dead (location is
never 'lost'); `bermuda_decay` keeps a departed resident's room ≤300s with
STALE status → could cancel a real guest → cancellation now filters
`tracking_status` STALE/LOST. Residual accepted + documented: a FRESH
misplaced fix (phone left behind) can still excuse a same-area guest —
row-4 sibling; phone-left-behind exclusion filed as follow-up.

**Re-review (Pass-D, substantial-fix-up rule): SHIP.** Invariants I1/I2/I3
walked and held; zero-cancellation path byte-identical to pre-cycle;
9-mutation table re-executed. One MED doc-drift (dedup-helper fork
docstrings) fixed at `1b07493a`. Post-wave hotfix queued (operator):
census-section kill-switch form field, default ON.

---

## Cycle 5 — Energy pause-release hygiene (Tier 2-DB)

**Build** `393f8501` · **Fix-up** `76c8da7c`
**Plan:** `PLANNING_energy_pause_release_hygiene.md` (+D4 added post-plan, operator live incident)

| Severity | Found | Fixed | Notes |
|---|---:|---:|---|
| CRITICAL | 0 | — | |
| HIGH | 3 | 3 | A/B convergent ×1 + C's charter-drop + B's test-infra |
| MED | 5 | 5 | |
| LOW | 5 | 4 fixed, 1 accepted | |

**Convergent HIGH (A-H1 = B-H1):** the build's D2 fix for the
false-REVERTED alarm created a **verification blackout** — `_result()`
(desired) and the hold overlay (effective) alternated ledger values every
tick, each bump advancing `_last_reserve_level_at`, keeping the
write-verifier's supersession/window guards permanently true → the reserve
surface would go unverified for a hold's entire duration. **Fixed:
single-writer-per-tick** — `_result` now writes only the new
diagnostics-side `_last_reserve_level_desired`; the verifier ledger
`_last_reserve_level` has one writer path; `current_park_floor()`
documented as seeing the EFFECTIVE post-overlay park (the truthful
hardware-commanded value). Anchored (re-introducing the `_result` stamp
reds a named test; orchestrator re-verified trio 101/101 green).

**C-HIGH-1 (charter drop):** the build silently omitted its own D3
headline deliverable — the direct call-site mutation anchors — while
sibling docstrings still claimed anchoring that mutation testing (P-e1/
P-e2 GREEN) disproved. **Fixed:** anchors added (static-source assertions
on the exact `reserve_soc=_release_floor` kwarg binding — disclosed as the
practical limit without a coordinator-cycle harness; they DO red under
P-e1/P-e2), false docstrings corrected. Third builder this wave with
claimed-but-false anchors → "builders execute their claimed mutations"
is now a standing build-prompt requirement, and reviews re-execute
regardless.

**B-HIGH-2 (test infra):** new bootstrap + write-verify tests had an
order-dependent naive/aware datetime TypeError (hygiene-first order) —
fixed by minting test timestamps through the SUT's `dt_util` binding;
quartet green both orders.

**Also fixed:** restore semantics inverted to re-add-unconditionally +
first-tick release drain (kills the stranded-device-across-restart case
AND makes restart behavior consistent with in-session toggle-off);
`_paused_by_us` added to fill/grid-cap release deferrals (no
charging-at-peak flap on toggle-off); `prune_removed_plugs` wired (was
dead code with a false docstring); plug ensure-on gained the grid-charge
breaker cede for exact L2 parity (operator principle); real-ctor
construction tests per controller (v5.8.0 lesson).

**D4 (operator live incident 2026-07-13 ~01:04):** L1 plugs previously
had only edge-triggered "resume what URA paused" — a plug off at boot or
with a car arriving after midnight never started. Now: per-tick off-peak
ensure-on with full owner-precedence, mirroring the EVSE machinery.
Bug-class candidate (operator-coined pattern): *"edge-triggered resume vs
level-triggered ensure-on — any device class with a pause rule needs an
every-cycle start evaluation, not just an undo of its own pause."*

---

## Wave totals (all six cycles, incl. part-1 doc)

- **Found post-build by the review stacks: 6 CRITICAL, ~23 HIGH.
  Shipped to production: zero** (v5.15.0's stack ran pre-deploy; the
  other five cycles' findings were all fixed pre-deploy in this wave).
- Every CRITICAL was invisible to, or actively masked from, its builder's
  green suite; three were only findable by real source mutation or
  empirical bisection.
- Residuals accepted + tracked: BLE fresh-fix guest excusal (row-4
  family), hygiene call-site anchors static-source (needs coordinator
  harness), test_cycle_b pre-existing ordering pollution (unrelated),
  A-LOW-2 proactive-holds display nit — all in the pickup memo.

---

## Addendum — Hotfix batch v5.16.1 (H1 cloud-first writes · H2 battery_full_time v2 · H3 BLE kill switch)

**Builds** `114043a8`/`a4e40c30`/`dcd6fe2c` · **Fix-up** `44881a35` · 3 focused framing-disjoint reviews.

| Severity | Found | Fixed |
|---|---:|---:|
| HIGH | 5 (A:2, B:1, C:3 test-authority — overlap-adjusted 5 distinct) | 5 |
| MED | 5 | 5 |
| LOW | 4 | 3 (+1 retired by live evidence) |

Headline findings, all fixed in `44881a35`:
- **B-H1-1:** the self-heal re-dispatch loop cancelled/rescheduled the pending
  verification every cycle — a persistently-refusing Enlighten would never
  trigger the REVERTED alarm (heal loop masks the alarm). Fixed: same-value
  pending checks mature; N=3 consecutive self-heals raise the unmaskable alarm.
- **A-HIGH-1:** `current_storage_mode` was a missed W-5 command-state read
  (local leg) → storage_mode had no self-heal. Fixed w/ cloud read + label
  normalization (cloud labels confirmed live).
- **A-HIGH-2:** explicit-blank cloud field + `is not None` → writes dispatched
  with NO entity — an advertised config action killed a surface's writes.
  Fixed: falsy check → coherent demotion to local (reads+writes together).
- **C-HIGH-1/2/3:** W-5 anchored at 1 of ~7 sites; secondary witness and tap
  normalization had zero authority; two "anchor" docstrings overstated
  (4th recurrence of claimed-but-false anchors this wave). Fixed: real
  anchors added (witness deletion → behavioral divergence test red,
  re-verified independently by orchestrator: RED×2, byte-identical restore).
- Also: unavailable-cloud N-strike backoff (no infinite 5-min dispatch loop),
  H2 ETA clamp + taper honesty attr, H3 options round-trip anchor.

Live-evidence trail motivating H1: URA's 11:06:27 local charge_from_grid
write accepted-then-ignored (cloud off, hardware following cloud); the
tripwire correctly showed no_data because the lying local read suppressed
any re-command (B-LOW-2 restart gap made concrete). Cloud-first
reads+writes structurally fix the class; the boot self-heal scenario is
mutation-anchored.
