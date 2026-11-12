# Plan review 2: EV rung-1 redirect cap (framing: adversarial build-prediction)

Plan: `docs/planning/PLANNING_ev_rung1_redirect_cap.md` (develop `b109d3d8`). Card `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1`, Tier 3.
Framing: "what will the builder get wrong reading this?" Read-only; all cites are against develop source.
HVAC / presence state-of-play docs: not read, out of domain (energy arbitrage only).

**Verdict: REVISE.** The design (D1 cap + D2 timestamp hold) is sound and I found no invariant leak in the mechanism. The plan
misdescribes the production sampling regime and the existing test fixtures. A builder who follows it will write tick-count
assertions that fail in end-to-end tests, and may then "fix" them by weakening. All findings are plan-text edits; none needs
a design change.

## Findings

### F1. HIGH: duplicate sampling is the norm on every latched tick, so the D2 hold is 1 tick in production, not 2
- `_record_attain_sample` has two callers: `_classify_attain_rung` `energy_battery.py:4174`, and `_run_attain_branch` `:6008`.
- When the rung is rung_0 or rung_1, `_gate_is_open` returns False (`:4532-4538`). `get_strategy` then falls through to the
  off-peak attain branch at `:7221` (under `if self._arbitrage_enabled`), which records the same `(now, soc)` again
  (`:6008`). Rung_2 ticks take the arbitrage decision at `:7203` and sample once. The sampler does no dedupe (`:5025-5031`).
- Trace with K=3 (`max_len` 4). Pre-entry ticks are rung_2 and single-sampled. Entry tick N: `[N-2,N-1,N]`, then the attain
  branch adds `N` → `[N-2,N-1,N,N]`. N+1: classify appends → `[N-1,N,N,N+1]`. `hist[0]=N-1 < N`, so the tick is held. The attain branch
  then appends → `[N,N,N+1,N+1]`. N+2: classify appends → `[N,N+1,N+1,N+2]`. `hist[0]=N >= N`, so the window is flushed at **N+2**,
  and the rate spans only N→N+2 (10 min).
- The plan's §2.1 says "can append", and Q4 frames it as an edge case. §3 case 19 and the D2 acceptance text ("held at N+1 and N+2,
  window `[N..N+3]` at N+3") describe the single-sample regime. That regime only occurs when a test calls
  `_classify_attain_rung` directly. The D4 end-to-end tests go through `get_strategy`/`determine_mode` and will flush at N+2.
- Builder prediction: the unit-level D2 tests pass at N+3, but the D4 `test_genuine_redirect_single_pause_no_flap` disagrees
  with them by one tick. The builder then either tunes the fixture until it passes or relaxes a tick assertion.
- Fix in plan: (a) restate §2.1 and Q4 as "always double-sampled on rung_0/1 ticks when arbitrage is enabled (`:7203`/`:7221`)".
  (b) Give D2 expected ticks for BOTH harnesses: direct classify flushes at N+3, the production path at N+2. (c) Note that the post-flush
  escalation decision on the production path uses a 10-minute window (2 ticks of SOC delta), so it is noisier than the documented 15 min.
  State whether that is acceptable. It is still all post-pause, which is the D2 intent. (d) Require the D4 genuine-redirect test to
  assert the exact flush tick for the production path.

### F2. HIGH: the M5 drill (`>=` → `>`) is hollow against the test named for it
- With `>`, the tick where `hist[0] == latched_at` stays held one tick longer. In case 19 (genuine redirect) that tick's
  expected result is already `rung_1` (post-pause rate ≥ exit). A held tick also returns `rung_1`, so the case-19 test
  stays GREEN under M5. The plan says "the hold test at the N+3 boundary goes RED". It will not.
- Only case 20 (rate flat) discriminates `>=` from `>`, and only if it asserts `rung_2` at **exactly** the flush tick. The
  plan's case-20 text says "≤ N+3", which also passes under M5 (escalation at N+4 fails "≤ N+3", but a builder writing
  "eventually rung_2 within the loop" will not catch it).
- Fix: re-target M5 at `test_rung1_hold_escalates_after_flush_when_rate_flat`. Require an exact-tick assertion: rung_1 at the
  last held tick, rung_2 at the flush tick (N+3 direct, N+2 production per F1).

### F3. MEDIUM: M4 can pass hollowly unless the held tick provably projects below exit
- M4 (`window_flushed = True`) goes RED only if, at N+1, `projected_rung0 < exit_band` actually holds in the fixture. If the
  fixture's pre-pause rate happens to project above exit, N+1 is rung_1 on both branch and develop. The plan's discriminator
  ("on develop N+1 gives rung_2") is then false, and the test is hollow.
- Fix: require the test to assert the precondition `strategy._arb_last_projection_rung0 < target - ARB_LADDER_EXIT_HYSTERESIS_PCT` at
  N+1 before asserting rung_1. Also require a develop-behaviour control, i.e. the same sequence with `_arb_rung1_latched_at = None`
  (legacy path, case 18) returning rung_2 at N+1.

### F4. MEDIUM: the plan's fixture-churn prediction is wrong. Existing tests DO set `net_power`
- `_build_strategy` sets `_NETP = "0" W` and `_BPOW = "-200" W` (`quality/tests/test_arbitrage_solar_attainability_ladder.py:218-219`;
  the same in `test_rung_1_over_fires_with_13_5_default` `:1102-1103`). `MockState` stamps `last_reported` at tz-aware wall-clock
  (`quality/tests/conftest.py:221-240`), so the freshness gate passes. With batt −200 (discharging), `max(0, batt)=0` → imp 0
  → `redirectable_kw == ev_load_kw`. The listed tests most likely stay **green** with credit unchanged.
- Builder prediction: the builder expects RED, sees GREEN, and assumes the cap is not wired. Alternatively, the builder follows the
  instruction to "add net = −1000 W to `_build_strategy`". That global change also shifts the breaker guard and other `net_power_w`
  readers in every test using the helper.
- Consequence for mutation authority: because the legacy fixtures give imp=0, M1 is caught ONLY by the new D1 tests. That is fine,
  but the plan should say so.
- Fix: replace the churn paragraph with "expected: legacy rung-1 tests remain green (fixture net 0 W, batt discharging → cap == ev). Do NOT
  change `_build_strategy` defaults. New cap tests set net_power per test." Keep "no assertion weakened".

### F5. MEDIUM: freshness age runs on the wall clock, not tick `now`, so replay fixtures can go stale by accident
- `_state_age_s` uses `dt_util.utcnow()` (`energy_battery.py:109`). The D4 replays use synthetic `now` (11-08 14:03 CST, 10-01).
- A builder who stamps `net_power` with `set_state_with_time(..., last_changed=<replay time>)` creates an entity that is weeks
  stale. The cap then returns 0 because of freshness, not because imp > ev. The 1108 replay passes for the wrong reason, and the
  positive tests (export full credit, two-EV summed, case 19) fail. The builder may then "fix" those by lowering the gate.
- Fix: state explicitly that freshness stamps must be relative to `dt_util.utcnow()` (default `MockState` stamping), except in the
  stale test. Require the stale test to include a positive control: the same inputs with a fresh stamp DO enter rung_1.

### F6. MEDIUM: `_arb_last_redirectable_kw` has no `__init__` default, resets in the wrong place, and shows 0.0 during an active redirect
- (a) D3 reads `self._arb_last_redirectable_kw` at the sensor attr site. `_classify_attain_rung` never runs when the forecast gate
  is closed (`_gate_is_open` returns at `:4520` before `:4530`), so on a fresh boot with a closed gate the attribute was never set
  and the read raises AttributeError (or the builder adds `getattr`). The plan gives `latched_at` an `__init__` line but not this one.
- (b) A reset "after the cache check" in classify does not run on forecast-closed ticks or early-return ticks upstream of
  `_gate_is_open`, so the last value sticks across those ticks (Bug Class #7, stale data). The per-tick entry-reset belongs beside
  `self._arbitrage_intent = None` at `:6424`, which already exists for exactly this reason.
- (c) The D1 snippet places the computation at `:4220`, which runs on EVERY tick that passes the rate check, latched ticks included.
  While latched, the EVs are paused, so `ev_load_w = 0` and the attr reads `0.0` throughout an active redirect pause. This contradicts
  D3's "None on ticks that did not reach the entry" and confuses Live 1 readers.
- Fix: `__init__` default None. Entry-reset at `:6424`. Either stamp the attr only in the entry block (`:4464`), or keep it per-tick and document
  that it reads 0.0 while paused. Pick one; the plan currently implies both.

### F7. LOW: INV-1 is falsifiable by a legal config the plan itself documents
- `DEFAULT_NET_POWER_MAX_AGE_S <= 0` disables the gate (`_read_fresh_power_w` `:2512`). Repro: max_age 0, Envoy frozen at −2 kW,
  EV 10 kW grid-fed → full credit → entry. §5 mentions this. INV-1 states "present and fresh" without the carve-out, so reviewer D will flag it.
- Fix: add "(unless the freshness kill switch is ≤ 0)" to INV-1. Also, the comment at `energy_const.py:545-550` says "Only CostTracker and D-OBS
  read this const". D1 adds a third reader, so update that comment in D5.

### F8. LOW: INV-5 overstates "no output changes", because the display attr shifts in daylight
- With the cap, a grid-fed EV gives `ev_load_pct_per_h = 0`, so the tick returns at `:4424` with `_arb_last_projection_rung1 = None` instead of
  a rounded projection (`:4462`). That feeds `arb_projection_rung1` (`:8387`) and the reason suffix (`:7250-7266`). At night the
  `:4415` solar guard usually returns first, so INV-5 mostly holds. But `test_replay_1001_night_identical_to_develop` must compare
  rung/intent/actions only, NOT the full attr dict, or it fails spuriously on the daylight-shifted variant.
- Fix: scope INV-5 and the replay test to rung/intent/EV actions. State in D3 that `arb_projection_rung1` becomes None on cap-zero ticks.

### F9. LOW: restart path not stated
- `_arb_rung1_latch` has a single writer and is not restored (`:936` init only; the grep shows no restore). After a restart, latch=False and
  `latched_at=None`. That is consistent, and D2 needs no RestoreEntity work. The plan should say this in one line so the builder does not add
  persistence for `latched_at` (which would create a latched_at-without-latch state).

## Cleared (checked, holds)
- **Units / sign:** `net_power_w` positive = import (`:2591` docstring). `_effective_import_kw` returns kW and subtracts only battery
  charge (`:4086-4093`). The D1 snippet is kW vs kW, then `/capacity*100` → %/h. Export (net < 0) gives `ev - imp > ev`, clamped to ev. Correct.
- **Battery discharging (case 9):** `max(0, batt)=0` → imp = net → credit = discharge avoided. As stated.
- **Two EVs:** `current_charging_load_w` sums (`energy_pool.py:3013`); the pool pauses all. As stated.
- **Snapshot consistency:** `:4468` stores the local `ev_load_pct_per_h`; the counterfactual `:4349` reads the same snapshot. No edit needed. Holds.
- **Latch writers:** the grep confirms only `:936` (init), `:4464` (set), and the clear sites, so reading `latched_at` only under latch=True is safe.
- **Cache:** the per-`now` cache (`:4164-4167`) makes the second `_gate_is_open` call a pure read, so D2's guard is evaluated once per tick.
- **Breaker (INV-4):** D1/D2 only change the rung string. The `energy.py:8179-8195` derivation is untouched.
- **SOC=target / SOC None / window cleared:** early returns precede the latched branch (`:4176`, `:4187`, `:4203`). D2 is never reached. Develop behaviour. Holds.

## Must-fix before build dispatch
F1, F2 (tick counts + M5 target). F3, F4, F5, F6 (fixture/attr instructions). F7-F9 are one-line text edits.
