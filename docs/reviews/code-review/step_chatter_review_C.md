# STEP Tier-3 Review C — Test authority via per-site source mutation

Branch: `feature/step-chatter` @ 07b3ad116
Reviewer: independent Tier-3 Framing C
Method: real production-source mutations in the worktree with
`PYTHONDONTWRITEBYTECODE=1` + `__pycache__` cleared before each pytest run;
every mutation restored + `git status` verified clean at end (per
feedback_unrestored_mutation_drill).

## Verdict

**DO-NOT-SHIP.** Test authority is materially insufficient at the
**coordinator tick-site boundary**. Three separate load-bearing writes into
`SensorExclusionSet` (P22, stuck_dutycycle D1, chatter) can be neutered or
subverted in `coordinator.py` and the entire STEP suite (40/40) passes green.
The detector core (`chatter_detector.py`) and the primitive itself
(`sensor_exclusion.py`) ARE genuinely mutation-anchored — the gap is
exclusively at the coordinator wire-in.

One-line test-authority verdict: **the load-bearing sites in the shared
primitive and the detector are mutation-anchored; the load-bearing sites in
`coordinator.py` are NOT — they pass via source-grep counts and simulated-tick
helpers that never touch the real coordinator.** This is precisely the
hollow-anchor bug class (feedback_hollow_test_anchors, Bug Class #64) the
brief called out as load-bearing for this session.

## Findings

### C-CRIT-1 — D2-raise "Reading-A byte-identity" is UNANCHORED in `coordinator.py`

**Mutation (added inside the D2-raise `else` branch at coordinator.py ~2783):**
```python
self._dutycycle_excluded_last_tick = _prev_excluded
for _leak in _prev_excluded:
    self._exclusion_set.promote('stuck_dutycycle', _leak, 'd2_raise_leak')
```
This is the *exact* forbidden Reading-B leak the plan (`§D1.1 point 3`) and
the source comment (coordinator.py:2787-2796) call out by name:

> "Adding a compensating `promote('stuck_dutycycle', ...)` here is the
> forbidden Reading B and is asserted against by
> `test_d2_raise_fusion_byte_identity_reading_a`."

**Result: 40/40 PASS.** All 27 direct tests + all 13 wire-in drills green.
The claimed test (`test_d2_raise_fusion_byte_identity_reading_a`) drives a
LOCAL `_simulate_tick` helper defined in the test file
(`test_sensor_exclusion.py:192-219`) that hand-crafts the promote sequence —
it never imports `coordinator.py` or exercises the real D2-raise branch.
Wire-in Drill 6 targets the wrong file (mutates `sensor_exclusion.py`, not
`coordinator.py`) and the wrong test (client isolation, not Reading-A).

The comment at coordinator.py:2794-2796 is aspirational, not enforced.

### C-CRIT-2 — All three coordinator tick-site `promote()` calls are non-behaviorally anchored

Per-site mutation matrix (each restored + re-run to confirm green):

| # | Site | Mutation | Suite result | Anchoring |
|---|------|----------|--------------|-----------|
| 1 | coordinator.py:2568 (P22 promote) | delete → `pass` | **40/40 PASS** | UNANCHORED |
| 2 | coordinator.py:2647 (stuck_dutycycle promote) | delete → `pass` | **40/40 PASS** | UNANCHORED |
| 3 | coordinator.py:2833 (chatter promote) | delete → `pass` | 39/40 fail (`test_chatter_diag_provenance_parity`) | STRING-GREP only |

Site 3 reds only because `test_chatter_diag_provenance_parity`
(`test_unavailable_entities_chatter.py:67`) does a `.read_text()` on
`coordinator.py` and asserts the literal string
`'self._exclusion_set.promote(\n                        "chatter"'` is
present. That is a source grep, not a behavioral test — bytecode-equivalent
neutering (e.g. `if False: self._exclusion_set.promote(...)`) would leave
the string intact and the test green while breaking runtime behavior.

Wire-in Drill 3 explicitly acknowledges the hollowness in its docstring
(`test_chatter_wire_in.py:178-191` — "Structural rather than behavioural
because a full RoomCoordinator tick requires the whole integration
bootstrap; the plan's live-validation criterion covers the runtime path").
Deferring to live validation for a **load-bearing tick-site write to a
shared primitive** is the exact pattern the fan-recheck deadlock exploited
for 5 days.

### C-CRIT-3 — All 6 D1 fusion-site consumers anchored ONLY by source-grep count

Per-site mutations on each of the 6 `is_excluded(sensor)` sites at
coordinator.py:2893, 2900, 2907, 2921, 2929, 2937 (one at a time, replace
`not self._exclusion_set.is_excluded(sensor)` → `True`):

**Every site reds the exact same test:**
`test_all_6_coordinator_fusion_sites_use_is_excluded` at
`test_sensor_exclusion.py:282-296`. That test is a `.read_text()` +
`.count("self._exclusion_set.is_excluded(sensor)")` — a source-string
count with a `>= 6` assertion. Mutating any one site drops the count from
6 to 5.

**No behavioral test drives fusion through any specific site.** A
mutation that keeps the string but neuters the semantics (e.g. wrap
`is_excluded` in a shim that always returns False) would pass green.
Wire-in Drill 1 uses `replace_all` — proves the primitive is
aggregate-load-bearing but does NOT prove per-site coverage. Per Tier-3
Review C protocol:

> "A site whose bypass leaves the suite green is an untested site =
> unacceptable. A global monkeypatch [or aggregate replace_all] proves
> the helper is load-bearing in aggregate; it does NOT prove each site
> routes through it."

### C-HIGH-1 — Wire-in Drill 6 mistargeted; does not defend Reading-B

Drill 6 (`test_drill_6_reading_B_forbidden_add_promote`,
`test_chatter_wire_in.py:229`) is labeled the "D1.1 Reading-B forbidden
mutation" defence. It actually:

- Mutates `sensor_exclusion.py` (the primitive), not `coordinator.py`
  (the site the plan calls out).
- Targets `test_client_isolation_release_leaves_other_clients_promotion_intact`
  — a client-isolation test on the primitive.

The plan's forbidden Reading-B leak lives in `coordinator.py`'s D2-raise
branch. Drill 6 does not exercise that branch and does not detect the leak
demonstrated in C-CRIT-1.

### C-HIGH-2 — Same-value dedup drill (Drill 11) is a source grep, not a mutation drill

`test_drill_11_same_value_dedup_wire` at `test_chatter_wire_in.py:307-324`
does not mutate anything. It asserts the literal string
`"if prev_state_val == state_val:"` exists in `chatter_detector.py`.
Same class as C-CRIT-3 — bytecode-equivalent neutering slips through.

The drill's own docstring acknowledges this ("we mutate + assert the
healthy-busy-PIR test still passes but detector's counters diverge —
captured via a bare structural check"). A real drill here would drop the
guard, feed a stream of same-value edges with a >0 prev_ts, and assert
that no sub-floor event accumulates.

## What IS genuinely anchored (positive)

- **`chatter_detector.py` core physics** — MUT A (invert `interval <
  t_floor` → `>`) reds 5 tests; MUT B (raise `CHATTER_BURST_K` 20 → 200)
  reds 4 tests. Real behavioral coverage via `_FakeHass` driving
  `ChatterDetector._on_edge` end-to-end.
- **Camera-family provenance guard** — Wire-in Drill 10 mutates the
  `_is_camera_family` call site (not the function) and reds
  `test_mislabeled_frigate_entity_denied_by_integration_fallback`.
- **Boot-settle gate** — Drill 9 red on real behavioral test (verified
  independently by inspection of the drill mutation shape).
- **Unavailable-transition guard** — Drill 12 reds on real behavioral test.
- **Listener teardown (Bug Class #38)** — MUT E (delete
  `self._chatter_unsub()`) reds
  `test_chatter_detector_unsubscribe_called_on_teardown`. Genuine.
- **`SensorExclusionSet` primitive semantics** — client isolation,
  reset_tick, provenance, non-str drop are all driven behaviorally.
- **Ratgdo positive fixture** — 2.5s cadence over 30 edges. Matches the
  D0 probe's <3.0s opener T_floor shape credibly (not invented).

## Suite hollow-anchor inventory

| Test | File:line | Kind | Anchoring |
|------|-----------|------|-----------|
| `test_all_6_coordinator_fusion_sites_use_is_excluded` | test_sensor_exclusion.py:282 | source `.count()` | HOLLOW (C-CRIT-3) |
| `test_d2_raise_fusion_byte_identity_reading_a` | test_sensor_exclusion.py:222 | local `_simulate_tick` helper | HOLLOW at coordinator (C-CRIT-1) |
| `test_tick_site_promote_reflects_in_exclusion_set` | test_chatter_wire_in.py:178 | `.read_text()` string check | HOLLOW (C-CRIT-2 site 3) |
| `test_chatter_diag_provenance_parity` | test_unavailable_entities_chatter.py:67 | `.read_text()` string check | HOLLOW (documented in drill) |
| `test_drill_11_same_value_dedup_wire` | test_chatter_wire_in.py:307 | source-string assertion | HOLLOW (C-HIGH-2) |
| `test_drill_6_reading_B_forbidden_add_promote` | test_chatter_wire_in.py:229 | wrong file + wrong test | MISTARGETED (C-HIGH-1) |

## Required before SHIP

1. **C-CRIT-1 fix:** Add a real behavioral test that constructs a
   `RoomCoordinator`-shaped fixture (or a minimal-shim over the D2-raise
   branch reachable from the tick site), forces the D2 detector to raise,
   and asserts `S.excluded()` on the shared set contains ONLY the P22
   promotions on that tick — with the forbidden compensating promote as
   an anti-Reading-B fixture. Point Drill 6 at coordinator.py's D2-raise
   branch (not sensor_exclusion.py) targeting this new test.
2. **C-CRIT-2 fix:** Behavioral tests that drive the coordinator tick site
   and observe SensorExclusionSet contents after each writer runs — one
   per client (P22, stuck_dutycycle, chatter). String-grep anchors are not
   acceptable substitutes given the size of the code path they defend.
3. **C-CRIT-3 fix:** Per-site behavioral fusion drills — build 6 tiny
   coordinator fixtures each promoting a single sensor into the exclusion
   set and observing that `motion_detected` / `presence_detected` /
   `occupancy_detected` (and each `_last_trigger_*` write branch) is
   suppressed only when that specific consumer site is intact. Or, at
   minimum, a per-site line-level mutation drill (like Drill 1 but per
   line) with a matching per-site behavioral test.
4. **C-HIGH-2 fix:** Convert Drill 11 into a real behavioral drill that
   fires same-value edges and asserts `_sub_floor_events` stays empty.

Fix C-CRIT-1 and C-CRIT-2 are the minimum to unblock SHIP; C-CRIT-3 and
C-HIGH-2 can ride in an immediate fix-up so the coordinator boundary is
mutation-authoritative before the next writer joins the shared primitive.

## Housekeeping

All mutations restored in-worktree; `git status` clean; baseline 40/40 green
re-confirmed post-review. No source or test files modified by this review.
