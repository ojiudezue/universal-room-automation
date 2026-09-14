# URA v5.101.4 — Household routine sensor recency bound (v5.101.3 fix-up)

**Shipped:** 2026-09-14
**Tier:** 1 (one SQL predicate + its guard test)
**Card:** ROUTINE-DETECTOR-NO-DISCHARGE-1 (fix-up)

---

## What this fixes

v5.101.3 bounded the routine-status sensor query by recency so that an unacknowledged routine
shift stops driving the sensor once it ages past the detector's 56-day baseline window — making
acknowledgement **optional** rather than mandatory.

**It bounded only one of two sensors.** There are two routine-status sensors with two entirely
separate queries: `PersonRoutineStatusSensor` and the household one. Only the person query got
the predicate.

**Caught by live validation, not by tests.** After the v5.101.3 restart:

| Sensor | Before | After v5.101.3 |
|---|---|---|
| `..._jaya_routine_status` | `major_shift` | **`shifted`** ✅ (its May severity-4 rows aged past 56 days, exactly as designed) |
| `..._household_routine_status` | `major_shift` | **`major_shift`**, 462 unacknowledged ❌ |

The person sensor working *perfectly* is what made the household sensor look like a broken bound
rather than an untouched consumer. A count-the-consumers miss.

This release applies the same `ROUTINE_STATUS_RECENCY_DAYS` bound to the household query, with
the unbounded variant preserved behind the `0` kill switch.

---

## The guard test was hollow twice — on this same feature

Recorded because a hollow anchor that gets fixed silently teaches nothing.

**First version** asserted a bare substring (`"AND timestamp >= ?"`) over the whole module.
`sensor.py` contains **three** queries with that string, so deleting the routine-status predicate
left the test green.

**Second version** located each SQL statement by searching backwards for a `SELECT` keyword. One
span ran **5887 characters**, swallowed an unrelated query's predicate, and reported a bound that
was not there — so unbinding the household query *still* passed.

**Final version** anchors on the triple-quoted string-literal boundaries, classifies each
`routine_shift` query as bounded or unbounded, and asserts **both** are bounded. Drilled: with the
household query unbound it goes RED.

**Process note:** on both drills the mutation had to be verified as *actually applied* before a
green result was trusted. The first attempt was a silent no-op that read as a passing test.

### Acceptance criteria
- **Verify:** both routine_shift queries carry the recency predicate.
- **Test:** `test_BOTH_routine_queries_are_recency_bounded` — fails if either is unbound.
- **Test:** kill switch (`0`) restores the unbounded behaviour for both.
- **Live:** `sensor.ura_coordinator_manager_household_routine_status` leaves `major_shift`
  without any button press, because its driving rows (2026-05-15..05-28) are outside 56 days.

---

## Verification performed pre-deploy

| Check | Result |
|---|---|
| Conflict markers | none |
| `compileall` | rc=0 |
| regime discharge suite | **10 passed** |
| perimeter + optimizer | **203 passed** |
| Mutation — unbind the household query | anchor RED → restored, residue 0 |

---

## Also in this release window (housekeeping, no code)

**355 stale local branches deleted, 413 → 58.** Used `git branch -d` — which refuses anything not
fully merged — on top of a three-check bar (ancestry, no attached worktree, not a release/scratch
branch), so the tool itself was the final guard rather than my classification. One refused
(`feature/household-routine-recency-bound`, which carries an upstream ref); it is merged and ships
here. Worktrees untouched at 46.

Notably conservative by construction: the two branches misjudged earlier tonight
(`device-arrangement-rooms-menu-build`, `energy-pool-actuation-logging` — shipped content with
stale pointers that read as "2 commits ahead") never appear in `--merged` output, so the
ancestry-vs-content confusion could not have caused a wrong delete.

---

## Live Validation — to be completed post-restart

- [ ] Household routine sensor no longer `major_shift` on May-dated rows
- [ ] Person routine sensors unchanged (already correct in v5.101.3)
