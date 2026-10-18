# Test Wave 2 D7 slice 2: Review A (correctness and test-intent preservation)

Head e8081ab98, diffed three-dot against develop a3f5b9dd9. This review covers only what slice 2 adds, because slice 1 already has its own reviews A, B and C. The change is test-only, so the HVAC and presence state-of-play docs do not apply: no production source was touched (`git diff --stat` shows `quality/` and `docs/reviews/` only).

## Q1: Did any assert change?
No. `git diff -w a3f5b9dd9...HEAD -- quality/tests | grep -E '^-\s*(assert|pytest\.raises)'` returns nothing. Every `+assert` line is in a new D7 harness file: `test_d7_donor_hygiene.py`, `test_collect_order_matrix_run_mode.py` or `_d7_isolation`. None is in a victim test.

## Q2: Does any victim pin make a test pass vacuously?
None does. There are three patterns, and each one makes the test agree with the clock that production reads. None of them stops the clock that the behaviour under test depends on.

| Site | What it does | Verdict |
|---|---|---|
| dp_drain / evse b2b_i, b2b_ii (x2), b2c2 `_frozen_dt_now` | These tests already froze `sys.modules[...dt]`. They now also freeze the distinct parent-attribute dt that production binds through `from homeassistant.util import dt`, at the same instant. | Holds. The frozen instant is the test's deliberate fixture: an anchor before or after the fire time, or force-charge `_pinned+1h`. Before this change the pin could miss production's dt, so the test silently ran on the wall clock. That made the test *less* deterministic, not more meaningful. Restore is in `finally`, and the original values are captured before the write. |
| identity_fusion fs4 / fs2 / `_ensure_loop` / `_scope_real_ha_patches` | These pin `PersonCensus...__globals__["dt_util"]` and presence's own `dt_util` to the same `now` the test already pinned. | Holds. fs2 still asserts `no_leg` plus the increment of `_face_dropped_stale_count`, using `last_changed = now-200s` against TTL 120. Pinning the census clock is what makes that 200 s gap actually reach production. The restore order is the reverse of the set order, so the normal case where both names are the same object restores correctly. `_ensure_loop` is called only from inside tests (lines 155, 550, 597, 806), and `_scope_real_ha_patches` registers the census dt for teardown. |
| identity_fusion rev5 `async_track_state_change_event` | Patches every distinct `helpers.event` object with `_raise`. | Holds. The assert that a failed subscribe leaves the map empty is still driven. |
| frigate_face_name_bridge:416, fan_interference_gate_layer1:65, house_state_restore_override:779/828 | No pin. The test reads seed timestamps or the class from production's own `__globals__`. | Holds. These seed relative offsets (−5 s, −1 h) on the clock production compares against, so the time arithmetic is still exercised. |
| hvac_batch_d_fan_ownership `_d7_aware_clock` | Monkeypatches `now`/`utcnow` to a **live** aware `datetime.now(utc)`. It does not freeze. | Holds. The only change is naive to aware, which removes a TypeError. Time still advances. |
| egress_display `_d7_event_helper_present` | Adds an inert `async_track_time_change` only when the name is missing. | Holds. The tests assert on the DB boundary, not on the timer. The no-op `raising=False` path only fills a gap left by a stub. |

## Q3: Is `restore_clocks_after_test` correct when an exception happens partway?
Yes. Each target is registered with `monkeypatch.setattr` before anything is frozen. If the test (or `_set_now`) raises partway, monkeypatch undo still runs at fixture teardown and restores every registered `now`/`utcnow`. An exception inside the registration loop, which would need a pathological `getattr`, leaves the targets registered so far restorable and the rest untouched, so nothing is half-frozen. Deduplication by identity (`all(cand is not t ...)`) prevents a double-register from saving an already-frozen value.

- **LOW-1** (`_d7_isolation.py:200`): the snapshot captures the *current* value. If an earlier file has already leaked a frozen clock onto that object, the helper "restores" the leaked value. This is the correct scope for a per-file helper, because the donor-side fixes own the root cause. It is noted only so nobody reads the helper as a global healer.
- **LOW-2** (evse b2b_i:563 and b2b_ii:477/557): `from _d7_isolation import ...` and the `_d7_extra` writes sit *outside* the `try`, after `_dt_mod.now` is already frozen. An ImportError there would leak the primary pin. The import is a local test helper, so this is not realistic. A cleaner version would capture and pin inside the `try`. Not blocking.

`other_dt_modules` is correct. It returns `[parent]` only when the parent attribute exists and differs by identity from `sys.modules`, so the normal case is byte-identical with an empty list.

## Q4: Do the retired drills lose test authority?
No, conditionally. Eight drills were retired: pair or multi drills for comfort_fan_away_veto, bathroom_exhaust, hvac_vacancy_sweep, carrier_freshness, v4715 (to oc_pillar_a), envoy_auto_derive and ec_solar (to onboarding_simplify_slice1), nm_c2_fixup and pc_observability. Each one is a pair that **cannot** go red any more, because the victim is now pinned victim-side, so keeping it would be a hollow anchor (#62). The authority moves to the donor residue drills (`_DRILLS` / `DONOR_PROBES`), which still exist in `test_d7_donor_hygiene.py`.

- **MEDIUM-1 (process, not code):** those residue drills, and the pair/multi anchors, now run only under `URA_D7_HYGIENE=1`. The default suite therefore no longer re-detects a re-introduced donor leak. That is acceptable only if the validator or CI runs the hygiene lane at cycle close. Card it, or add `URA_D7_HYGIENE=1` to the validator's checklist. Framing C owns the drill-by-drill check that each residue drill goes red.

The reverted donor scoping in oc_pillar_a, oc_pillar_b and optimization_coordinator restores pre-slice behaviour in those files. They gain no new asserts and lose none. The victims that the scoping exposed (perimeter TTL, sleep_fans) are fixed victim-side. These are consistent with the 0 NEW name-diff.

## Findings summary
| Sev | Count | Class |
|---|---|---|
| CRITICAL / HIGH | 0 | n/a |
| MEDIUM | 1 | Hollow anchor risk (#62): authority moved to an opt-in lane |
| LOW | 2 | Snapshot semantics; pin outside `try` |

## Verdict: SHIP
Recommended: add `URA_D7_HYGIENE=1` to the validator's cycle-close run (MEDIUM-1). LOW-2 is optional and takes 3 lines.
