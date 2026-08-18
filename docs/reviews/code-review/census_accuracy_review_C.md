# CENSUS-ACCURACY-1 — Review C (Test authority + hollow / oracle-echo hunting)

- **Cycle:** CENSUS-ACCURACY-1 (D1 peak-self-refresh + linear-decay removal; D2 `_2`-suffix-tolerant face + last_camera resolvers)
- **Tip reviewed:** `feature/census-accuracy` @ `6bf4f4eee` ("test isolation + board-drift sync")
- **Merge base vs develop:** `ec034585f` — verified via `git merge-base`
- **Framing:** test authority + hollow / oracle-echo hunting (Bug Class #62 / #63 / #64)
- **Reviewer role:** Review C of Tier 2-DB (parallel with A + B)
- **Verdict:** **SHIP**

---

## Method

- Full production diff read end-to-end (`camera_census.py` +204/-25, `const.py` +6/-1, `sensor.py` +17).
- Full new test file read end-to-end (`test_census_accuracy_d1_d2.py`, 444 LoC / 14 tests).
- Fixture-change diff read (`test_face_cross_check_behavioral.py`).
- All 14 D1/D2 tests independently re-run green from a fresh worktree
  (`.claude/worktrees/census-review-c`, `PYTHONDONTWRITEBYTECODE=1`,
  `__pycache__` purged before every run).
- **All 4 build-claimed mutation drills independently re-run RED-then-GREEN**
  from that same worktree — see drill table below.
- Isolation-pollution repro re-run — the two envoy sibling tests that used
  to fail as collateral now pass.
- Full-suite baseline honored (branch 25/9208 vs develop 25/9194,
  NAME-DIFF empty per orchestrator).

---

## Findings

### CRITICAL / HIGH

**None.**

### MEDIUM

**None.**

### LOW

**None substantive.** The tests, resolvers, and isolation fixture are
tight and load-bearing under the framing assigned.

### Notes (non-findings; observations)

1. **`test_d1_house_zone_instant_drop_after_hold` is *stronger* than the
   builder claimed.** Drill 2 (restoring the linear house decay) failed
   THREE tests, not one — `test_d1_house_zone_instant_drop_after_hold`
   +  `test_d1_house_zone_matches_property_zone_post_hold`
   + `test_d1_empty_house_reaches_zero_within_hold_plus_tick` all catch
   the regression. Broader coverage than promised — good defense in depth.

2. **`test_d1_no_peak_self_refresh_under_steady_fresh` is robust to a
   sensible-range change of `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES`** (10 ticks × 15 s = 150 s stays inside the 180 s hold; even if the default were shortened, the equality branch fires *before* the after-hold fall-through so the assertion would remain the discriminator).

3. **Fixture change in `test_face_cross_check_behavioral._make_census_with_person`** pre-populates `_frigate_person_last_camera_map` on an
   `object.__new__(PersonCensus)` instance. This is a legitimate division
   of test labor (not mirror-stubbing): resolver correctness lives in the
   D2 tests; this test remains anchored on the `not_home` guard, which is
   its actual oracle. The production `_resolve_last_camera_entity_id`
   defensively uses `getattr(self, "_frigate_person_last_camera_map",
   None)`, which is what makes the fixture path work — code and test
   agree on the contract.

4. **Registry-enumeration test uses a real registry-shaped fixture**
   (`SimpleNamespace(entity_id=..., unique_id=...)`) fed through the same
   `async_entries_for_platform` path production uses — this is not a
   mirror-stub of the parsed result. Bug Class #60 not triggered.

5. **Malformed-unique_id path covered** by
   `test_d2_ignores_registry_entries_with_unexpected_unique_id` — feeds
   `"not-a-frigate-uid"`, confirms skip (not crash) and absence from map.

---

## Oracle-echo (Bug Class #64) sweep

Explicit hunt for expected values derived from the production symbol
they guard. Anchors examined:

| Test | Assertion oracle | Source of expected value | Oracle-echo risk |
|---|---|---|---|
| `test_d1_no_peak_self_refresh_under_steady_fresh` | `_peak_house_timestamp == original_ts` + counter == 10 | Test-local `datetime` + integer literal 10 | **None** — no production import in the oracle |
| `test_d1_house_zone_instant_drop_after_hold` | `held == 0` after fresh=0 post-hold | Integer literal 0 | **None** |
| `test_d1_house_zone_matches_property_zone_post_hold` | `h_held == 0 and p_held == 0` | Integer literal 0 | **None** |
| `test_d1_lifetime_counter_increments_on_equality` | counter == 0/1/2 across ticks | Integer literals | **None** |
| `test_d1_per_tick_face_lookup_counter_shape` | `hasattr` + `== 0` | Shape assertion | **None** |
| `test_d1_empty_house_reaches_zero_within_hold_plus_tick` | `held == 0` | Integer literal 0 | **None** |
| D2 resolver tests (6) | entity_id string equality + counter increments | Test-local string literals | **None** |
| D2 registry-map tests (3) | dict equality with test-local literals + entity_id equality | Test-local string literals | **None** |

`hold_seconds` IS derived from production
(`census._get_hold_seconds("house")`), but it is a *mechanical dependency*
(where to sample `now`), not the assertion oracle (`held == 0`). This is
not an oracle-echo pattern — a sign flip / semantic change of the DECAY
logic still detaches from the oracle. Confirmed by drill 2 firing red.

**No oracle-echo (Bug Class #64) found.**

## Variant-7 (comment-out) sweep

Every new anchor was drilled by DETACHING the value (semantic mutation
of production source) rather than removing the site. Each drill produced
a NAMED failing test → the anchors are not hollow. Confirmed below.

## Fail-open dead-oracle (Bug Class #63) sweep

D2 resolver's fail-CLOSED path is *positively discriminated* by the
`_face_lookup_missing_count` increment
(`test_d2_resolver_fails_closed_when_neither_variant_resolves`). A
silent-success regression (returning `""` or a default entity_id) leaves
the counter at 0 → oracle catches it. Not fail-open.

---

## Mutation drills — independently re-run (RED → restore → GREEN)

Each drill: purge `__pycache__`, mutate ONE production site, re-run the
14 D1/D2 tests, restore, re-run.

| # | Mutation | Expected failing test(s) | Observed | Result |
|---|---|---|---|---|
| 1 | Re-add `self._store_peak(zone, fresh_count, now)` on the `elif fresh_count == peak` branch of `_apply_hold_decay` | `test_d1_no_peak_self_refresh_under_steady_fresh` | **1 failed:** `test_d1_no_peak_self_refresh_under_steady_fresh` (`AssertionError: peak_ts changed at tick 1: self-refresh regressed`) | **RED as expected** |
| 2 | Restore the `zone == "house"` linear `-1 per CENSUS_DECAY_STEP_SECONDS` slope after hold expiry | `test_d1_house_zone_instant_drop_after_hold` | **3 failed:** `test_d1_house_zone_instant_drop_after_hold`, `test_d1_house_zone_matches_property_zone_post_hold`, `test_d1_empty_house_reaches_zero_within_hold_plus_tick` — all `assert held == 0` with observed `2` | **RED (broader than claim)** |
| 3 | Revert `_resolve_face_entity_id` to canonical-only (drop `_2` fallback) | `test_d2_resolver_falls_back_to_suffixed_variant` | **2 failed:** `test_d2_resolver_falls_back_to_suffixed_variant`, `test_d2_resolver_skips_unavailable_state` | **RED (broader than claim)** |
| 4 | Revert `_resolve_last_camera_entity_id` to `f"sensor.frigate_{person_slug.lower()}_last_camera"` | `test_d2_resolves_last_camera_for_ura_person_slug` | **1 failed:** `test_d2_resolves_last_camera_for_ura_person_slug` (observed `sensor.frigate_oji_udezue_last_camera` vs expected `sensor.frigate_oji_last_camera_2`) | **RED as expected** |
| — | Restore + re-run 14/14 | 14 pass | `14 passed in 0.08s` | **GREEN** |

All drills confirm the anchors are load-bearing on the specific site
they claim to protect — no hollow-anchor / variant-7 defects.

---

## Isolation-fix verification

The autouse `_restore_entity_registry_module` fixture in
`test_census_accuracy_d1_d2.py`:

- **(a) Restores on the FAILURE path** — confirmed by structure:
  `try: yield / finally: for name, value in saved.items(): ...` — the
  `finally` block executes regardless of test outcome. `sentinel`-based
  attr-absent handling uses `delattr` (not `setattr(..., None)`), so a
  pre-test-absent attribute is left absent — not clobbered with `None`.
- **(b) Attr-absent case handled correctly** — `sentinel = object()`,
  `saved = {name: getattr(er_mod, name, sentinel) ...}`, restore branches
  on `if value is sentinel: delattr(...)`. **PASS.**
- **(c) No other mutated globals leak** — `_install_registry` mutates
  exactly `async_get` and `async_entries_for_platform`; the fixture
  snapshots exactly those. No other module-level state on `er_mod` is
  touched by the tests. **PASS.**

**Pollution repro re-run** on this worktree with fresh `__pycache__`:

```
pytest test_census_accuracy_d1_d2.py \
       test_envoy_auto_derive.py::TestValidateEnvoyConfig::test_v2_entity_missing_in_ha \
       test_envoy_auto_derive.py::TestValidateEnvoyConfig::test_v4_critical_derived_missing
→ 16 passed in 0.11s
```

The pre-fix failure mode (envoy siblings flipping via leaked stub) does
not reproduce. Isolation fix is a genuine leak plug, not a re-route.

---

## Verdict

**SHIP.**

Under the "test authority + hollow / oracle-echo" framing, this build is
clean:

- 14/14 D1/D2 tests green from a purged worktree.
- 4/4 mutation drills red-then-green, two of them broader than claimed.
- Zero oracle-echo (Bug Class #64) anchors.
- Zero hollow (Bug Class #62) anchors — every drill produced a NAMED
  failing test.
- Fail-CLOSED path positively discriminated by a counter oracle (Bug Class
  #63 sweep clean).
- Isolation fixture correctly restores on FAILURE, handles attr-absent
  via `delattr`, and does not move the leak — sibling envoy tests
  survive with our tests present.
- Full-suite baseline preserved (25/9208 vs 25/9194 name-diff empty per
  orchestrator).

No CRITICAL / HIGH / MEDIUM / LOW findings from this framing.

---

_Reviewer: framing C (test authority + hollow/oracle-echo). Parallel with A + B._
