# PLANNING — DP drain-target mis-sourcing fix

**Cycle name:** `dp-drain-target-mis-sourcing`
**Tier:** **Tier 3** (delicate shared-primitive fix; value threads into the commanded
Enphase reserve floor — cost + safety impact). **Rev-17 (this revision, TERMINAL FIX
per operator ruling 2026-08-25 after Rev-16 D-pass): VALUE-STAMP + THREADED-LOCAL +
PRODUCER ENTRY-RESET.** Rev-16 carried the value-stamp + threaded-local design with
a consumer-side "mailbox" (read-and-clear at the coordinator capture). The D-pass on
Rev-16 surfaced **D2-HIGH-1**: the mailbox was cleared ONLY by the consumer, so the
OTHER `determine_mode` caller (`_evaluate_battery` at `energy.py:6185`) could REFILL
the attribute BETWEEN ticks → a stale value could bleed into a later non-draining
tick. Concrete legal-config repro: `_evaluate_battery` runs at a TOU edge and its
determine_mode call reaches the drain branch, stamping (e.g.) 10; the next
`_decision_cycle_body` tick has determine_mode return via the `full_hold` short-
circuit at `:4903` (drain branch never runs, so no stamp); the capture site reads the
leftover 10 → DP acts on a tick where the emitter did not emit a drain floor.

**Rev-17 terminal fix.** Move the reset to the **FIRST executable statement of
`determine_mode`** at `energy_battery.py:4590`, BEFORE any early return:
`self._offpeak_drain_branch_target = None`. `determine_mode` is fully synchronous —
verified this session: zero `await` between `:4590` and `:5352` (the file's two
`await` sites at `:3266-3318` and `:5840` are outside the function body). Therefore
entry-reset + capture-immediately-after-return is airtight for ANY number of callers
(current or future), closed by construction: each call clears first, populates iff
the drain branch runs to the stamp line, returns; the consumer captures the value
the just-returned call produced (or None), no interleaving possible because there is
no await inside `determine_mode`. The value-write stays at `:5322-5323` (after the
partial_hold clamp).

Net writer/reader topology (Rev-17):
- **1 init** at `energy_battery.py:~483` (`_offpeak_drain_branch_target: int | None = None`).
- **1 entry-reset** at `energy_battery.py:4590` (first executable statement of
  `determine_mode`, before any early return).
- **1 value-write** at `energy_battery.py:5322-5323` (after the partial_hold clamp,
  before the return-split).
- **DP consumes ONLY the threaded local** captured in `_decision_cycle_body` at
  `energy.py:~5579` (immediately after `determine_mode` returns at `:5573`, BEFORE
  the first `await` at `:5587`); the local is threaded as a keyword parameter into
  `_dp_decision_tick` at `:5628` and forwarded into `_run_dp_shadow_eval` at `:4410`.
  No other reader.

This REPLACES the Rev-16 consumer-side read-and-clear mailbox (removed). Optionally
the consumer capture may still read-only; the authoritative clear is at the producer
entry.

**Prior finding closures (unchanged from Rev-16 unless noted):**

- **D-HIGH-1 (Rev-15 partial_hold clamp mirror gap)** — CLOSED-BY-CONSTRUCTION.
  Value stamp at `:5322-5323` (AFTER `:5322` clamp) is the emitter's actual emitted
  floor; DP consumes verbatim.
- **D-HIGH-2 (Rev-15 two-caller await race — attribute could be re-stamped between
  the `determine_mode` return at `:5573` and `_dp_decision_tick` at `:5628` during
  awaits at `:5587-5588`)** — CLOSED-BY-CONSTRUCTION by the pre-await lexical
  capture; the value the coordinator threads is the value the just-returned
  `determine_mode` call produced.
- **D2-HIGH-1 (Rev-16 mailbox cross-tick leak via the other `determine_mode`
  caller between ticks)** — CLOSED-BY-CONSTRUCTION at Rev-17 by the producer
  entry-reset: any `determine_mode` invocation, from any caller, ANY number of
  times, clears the attribute first. The synchronous body means the value the
  consumer captures is exactly what THIS call produced; nothing stale can survive
  across the return.
- **C-CRIT-1 (Rev-14)** remains closed — value produced only inside the drain-
  fallback branch (no writer elsewhere).
- **Bug Class #53 (computed-but-not-consumed via missed branches)** remains
  closed — single writer inside the drain branch; threaded local eliminates any
  cross-caller attribute race.

**Runtime relationship to solar-follow** unchanged: this cycle ships first;
solar-follow validates against corrected DP behaviour.

**Provenance.** Rev-1..Rev-14 as before. **Rev-15** replaced negative inference with
a per-tick positive BOOL stamp on `BatteryStrategy` and kept DP-side re-derivation.
**Rev-16** collapsed stamp + gate + value into one carried number, added a coordinator
lexical capture before awaits, and introduced a consumer-side mailbox (read-and-
clear) to close cross-tick staleness — dissolving Rev-15's D-HIGH-1/2/L-1. The
Rev-16 D-pass found **D2-HIGH-1**: the mailbox only clears on the consumer side,
so the second `determine_mode` caller between ticks can refill it → stale bleeds
into the next non-draining tick's consumer capture. **Rev-17** moves the reset to
the PRODUCER entry (first line of `determine_mode`), making the design airtight
for ANY number of callers by construction, and REMOVES the consumer-side read-and-
clear.

**Terminology correction (Rev-16, load-bearing — preserved at Rev-17).** All Rev-11..
Rev-15 references to `_get_off_peak_decision` in this document are WRONG — that
function does not exist in `energy_battery.py`. Verified: `grep -n "def
_get_off_peak_decision"` → zero hits; the drain-fallback branch is INLINE inside
`determine_mode` (definition at `energy_battery.py:4590`; branch spans `:5269-5352`).
The stale name in `current_offpeak_drain_target`'s own docstring at
`energy_battery.py:1730`, and in the `docs/Coordinator/` prose, is drift from an
older architecture — carded `DOCS-DRAIN-DRIFT-1`, NOT fixed in this cycle (§6).

**Threads:** `energy`
**Cards:** `EVSE-DRAIN-PRECEDENCE-KNOB-80-1`
**Related (NOT blocked_by):** `DRAIN-TARGET-DAY-STALENESS-1` —
`docs/planning/PLANNING_offpeak_drain_target_day_staleness.md`. DP inherits any
accessor fix by construction (the emitter uses the same accessor).

---

## 1. Falsifiable invariants

### INV-DP-DRAIN-1d (value-carried gate + target — LOAD-BEARING, REWRITTEN at Rev-17 to producer entry-reset)

**Definition (falsifiable form).** The drain target DP reasons about on tick T IS the
value the drain-fallback branch of `determine_mode` actually emitted on the
`_decision_cycle_body` invocation of `determine_mode` on tick T (post-clamp, post-
multi-day-max). It is not re-derived on the DP side. Formally: for every tick, if
`drain_target_local` is the value threaded from `_decision_cycle_body` into
`_dp_decision_tick`, then either

  (a) `drain_target_local is None` AND the drain-fallback branch did NOT run to
      completion on this call (either the branch was never entered, or it raised
      before the stamp line) → DP MUST NOT emit a fit/transition; or

  (b) `drain_target_local is not None` AND its integer value equals the post-clamp
      `drain_target` variable at `energy_battery.py:5322-5323` at the point the
      drain branch stamped it, i.e. `drain_target_local == post_clamp_drain_target`
      where `post_clamp_drain_target` = multi-day max, then (if
      `hold_depth == "partial_hold"`) raised to `effective_reserve` via `:5322`.

Under (b), DP consumes `drain_target_local` VERBATIM into `TransitionInputs.
drain_target_soc` at `energy.py:4456` (real tick), `:4522` (`_DPAct`), `:4540`
(`_DPActRescan`), `:4555` (revert predicate), and into the shadow snapshot at
`:4271`. NO `max(reserve_soc, current_offpeak_drain_target())` re-derivation runs
inside DP.

**Reserve-level relationship (Rev-17 correction, load-bearing for oracle authors).**
The stamped value is the `drain_target` local variable inside `determine_mode`, NOT
the emitted `reserve_level`. The two coincide ONLY on the above-target `:5326`
return, which emits `reserve_level=drain_target`. On the at/below-target `:5344`
return the emitted `reserve_level` is `hold_reserve = int(soc)` (further clamped up
to `effective_reserve` under partial_hold at `:5342-5343`). Stamping `drain_target`
(the SOC-threshold DP compares against) is the correct choice for DP — DP's revert
predicate at `:4555` is `soc <= drain_target`, so the SOC threshold is what DP
needs, not the emitted floor. Oracle authors and reviewers MUST NOT assert
`stamped == reserve_level` on both return paths; that equality holds only on
`:5326`.

**Producer entry-reset** (Rev-17, LOAD-BEARING): `energy_battery.py:4590` — the
FIRST executable statement of `determine_mode`, BEFORE any early return
(inclement full_hold at `:4903`, arbitrage gate at `:5236-5246`, attain latch at
`:5253-5267`, envoy-blind early return, grid-disconnect return, etc.):

```python
def determine_mode(self, period, season, *, now=..., tou_transition_into=...,
                   ev_load_w=...):
    # Rev-17 (INV-DP-DRAIN-1d) — PRODUCER ENTRY-RESET. Clear the drain-
    # branch value stamp before ANY early return, so every determine_mode
    # invocation from every caller starts fresh. Combined with the fact
    # that determine_mode is fully synchronous (zero `await` in the body,
    # verified :4590-:5352), this guarantees the consumer's lexical
    # capture immediately after our return reads exactly the value THIS
    # call produced — None if we return without hitting the stamp, or
    # the post-clamp drain_target if the drain-fallback branch reached
    # :5322-5323. Airtight for ANY number of callers by construction.
    self._offpeak_drain_branch_target = None
    ...
```

**Producer value-write** (SOLE writer, unchanged from Rev-16 in placement):
`energy_battery.py:5322-5323` — one assignment immediately AFTER the partial_hold
clamp at `:5322` and BEFORE the split into the above-target return at `:5326` vs.
the at/below-target return at `:5344`:

```python
if decision.hold_depth == "partial_hold":
    drain_target = max(drain_target, effective_reserve)
# Rev-17 value-stamp (INV-DP-DRAIN-1d). Placed AFTER the partial_hold
# clamp so the stamped value == the post-clamp `drain_target` variable
# that the two `_result(...)` calls below use as the SOC-threshold
# (on the :5326 return path this equals the emitted `reserve_level`; on
# the :5344 return path it is the SOC-threshold, and `reserve_level` is
# `hold_reserve` — see §1 reserve-level note). Placed BEFORE the return
# split so both emission paths inherit the same stamped value. A raise
# between branch entry at :5269 and this line leaves the attr None (the
# entry-reset already cleared it) → DP declines this tick, fail-closed.
# SOLE value-write site in the codebase (grep-anchored, §12).
self._offpeak_drain_branch_target = int(drain_target)
```

**Init**: `BatteryStrategy.__init__` adjacent to `_arbitrage_active` at `:483`:
`self._offpeak_drain_branch_target: int | None = None`. Not persisted. On restart
the first `determine_mode` invocation (from any caller) resets to None; the first
drain-branch tick stamps.

**Consumer capture** (SOLE reader that feeds DP): `energy.py:_decision_cycle_body`,
immediately after the `determine_mode` return at `:5573` and BEFORE the first
`await` at `:5587`. The insertion sits at approximately `energy.py:5579` (just
after the multi-line `determine_mode(...)` call closes at `:5578`):

```python
decision = self._battery.determine_mode(
    period, season,
    now=dt_util.now(),
    tou_transition_into=new_period,
    ev_load_w=ev_load_w,
)
# Rev-17 INV-DP-DRAIN-1d: capture the drain-fallback branch's stamped
# value (if any) into a LOCAL, BEFORE the awaits at :5587-5588. The
# producer entry-reset at determine_mode:4590 guarantees the attribute
# reflects EXACTLY this call's result (None if the branch didn't reach
# the stamp; the post-clamp drain_target if it did). The local is
# threaded into _dp_decision_tick at :5628 as `drain_target_soc=`, and
# forwarded from there into _run_dp_shadow_eval at :4410. NO re-read of
# `_offpeak_drain_branch_target` after this point in the tick.
# Defensive: any exception reading the attr → None (fail closed).
try:
    _dp_drain_target_local: int | None = getattr(
        self._battery, "_offpeak_drain_branch_target", None,
    )
    if _dp_drain_target_local is not None:
        _dp_drain_target_local = int(_dp_drain_target_local)
except Exception:  # noqa: BLE001
    _dp_drain_target_local = None
    _LOGGER.debug("DP drain-target capture raised (swallowed)", exc_info=True)
```

**No consumer-side read-and-clear.** Rev-16's mailbox pattern (post-capture write of
None) is REMOVED at Rev-17. The authoritative clear is at the producer entry — this
is what closes D2-HIGH-1 for the OTHER `determine_mode` caller between ticks. A
concurrent `_evaluate_battery` invocation between ticks will itself entry-reset then
either stamp (if its own call reaches the drain branch stamp line) or not — either
way, the NEXT `_decision_cycle_body` tick's `determine_mode` call will entry-reset
before doing anything, so the value the coordinator captures is fresh.

The local is then threaded as a keyword parameter into `_dp_decision_tick` at :5628
and into `_run_dp_shadow_eval` at :4410. The gate helper (§3) reads only the
parameter, never the attribute.

**When the threaded value is None**, DP MUST NOT emit a fit/transition. The real tick
publishes `DP_REASON_EMITTER_NOT_DRAINING`; the shadow publishes
`shadow_decision="not_applicable"` + `shadow_reason=DP_REASON_EMITTER_NOT_DRAINING`.
The DP carrier does not advance to `TRANSITIONED`. See INV-DP-DRAIN-1e for the mid-
carrier release rule.

**Why producer entry-reset over consumer mailbox (Rev-16→17 delta).** Rev-16's D-pass
finding D2-HIGH-1: the Rev-16 mailbox was cleared only by the consumer, so
`_evaluate_battery`'s determine_mode invocation BETWEEN two `_decision_cycle_body`
ticks could stamp a value that the NEXT `_decision_cycle_body` tick's capture would
read on a tick where its own determine_mode returned via a non-drain path (e.g.
`full_hold` short-circuit at `:4903`) and thus never stamped. Producer entry-reset
closes this by construction because EVERY determine_mode invocation clears first;
whatever `_evaluate_battery` stamped between ticks is irrelevant to the next
`_decision_cycle_body` tick because its own determine_mode call will clear it (and
then either restamp or not) synchronously before returning.

**Ordering coherence.** `_decision_cycle_body` (energy.py:5534) runs, in order:
`period = self._tou.get_current_period()` (:5540) → `determine_mode(...)` (:5573,
which entry-resets `:4590`, may invoke the drain-fallback branch inline, and stamps
the attribute iff drain branch runs to the clamp+stamp line, returning at either
`:5326` or `:5344`) → **local capture** (new, at approximately `:5579`, immediately
after the determine_mode return, before `:5587`) → `await
self._account_arbitrage_cycle(...)` (:5587) → `await
self._refresh_arbitrage_status_cache()` (:5588) → EVSE-hold overlay (:5604-5616)
→ `self._dp_decision_tick(decision, period, ev_load_w,
drain_target_soc=_dp_drain_target_local)` (:5628). The local's value is fresh and
coherent by lexical construction (no await between determine_mode return and
capture) AND by producer discipline (entry-reset makes it fresh regardless of what
happened on any prior call).

**Gate consumption inside DP.** Both `_dp_decision_tick` and `_run_dp_shadow_eval`
accept `drain_target_soc: int | None` as a keyword parameter. The gate is
`drain_target_soc is not None`. No helper is called from inside `_dp_decision_tick`
or `_run_dp_shadow_eval` to look the value up. Full containment shape in §3.

### INV-DP-DRAIN-1e (stranded-carrier release — kept from Rev-15, C-HIGH-2)

Under any tick where the DP carrier is `TRANSITIONED` AND the threaded
`drain_target_soc is None` (the strategy has moved on: arbitrage HOLD kicked in, an
inclement `full_hold` elevated, attain latched, envoy-blind hold, grid disconnect,
etc.), DP MUST release the carrier so paused EVSEs are freed. Mechanism: on
`TRANSITIONED + threaded value None`, force `_revert = True` regardless of the SOC-
vs-drain comparison. The revert path then invokes `_apply_dp_reversion(tou_period=
period)` at `energy.py:4550` and unpauses.

Discharge/release notes (feedback_suppression_needs_discharge):

1. The **primary** discharge is this INV-DP-DRAIN-1e branch itself: fires the very
   tick the gate closes on a TRANSITIONED carrier.
2. **Backstop** — the pre-existing sticky retry driver at `energy.py:4392` handles
   the case where the DP carrier landed in HOLD_ONLY with `_paused_by_dp` non-empty
   across a period transition (restart-orphan cleanup + normal
   TRANSITIONED→HOLD_ONLY retry when the initial reversion deferred). Runs BEFORE
   the night-window gate at :4416, so a carrier that TRANSITIONED past off-peak exit
   still drains. Value-stamp changes nothing about this driver.
3. **Restart behavior** — `_offpeak_drain_branch_target` is a runtime int, not
   persisted. On restart it starts None; the first `determine_mode` invocation
   entry-resets to None (no-op); the first drain-fallback tick stamps it. The DP
   carrier's own restore path (`restore_from_blob`'s HOLD_ONLY coercion) plus
   driver #2 handles any orphaned pause.

### INV-DP-DRAIN-1c (revert predicate consistency — unchanged from Rev-15 shape)

Under any tick where the controller has just stamped `_dp_decision_soc = X`, the
revert comparison at `energy.py:4555` uses the SAME threaded `drain_target_soc = X`.
The revert guard MUST keep both None-checks:
`if _soc is not None and _drain_target is not None and int(_soc) <= _drain_target:`.
When the threaded value is None AND no prior stamp exists, `_drain_target` is None
and the SOC comparison skips; MUST_START_FORCED + paused-idle + INV-DP-DRAIN-1e's
TRANSITIONED-gate-closed force-revert still fire.

### INV-DP-DRAIN-1 (drain-fallback-branch mirror — value-carried, NOT formula-carried)

Under any config, **when the threaded `drain_target_soc` is not None**, under any code
path that populates `TransitionInputs.drain_target_soc` OR stamps a fresh
`_dp_decision_soc` via `_apply_dp_transition` OR compares SOC against the drain target
in the revert predicate, the value used equals the threaded local exactly. NOT
recomputed via `max(reserve_soc, current_offpeak_drain_target())`. NOT re-read from
the battery attribute. Threaded local only. Applies to all five R2 sites (§3 table)
AND to the shadow-eval site at `:4271`.

Prior sourcing rule DELETED at Rev-16 (still deleted at Rev-17):
```
_dp_drain_target_soc(period) := max(reserve_soc, current_offpeak_drain_target())
```
This formula was the root of the whole cycle. The `_dp_drain_target_soc(...)` helper
on `EnergyCoordinator` is DELETED (was Rev-13/14/15). See §9 REUSE vs NEW.

### INV-DP-DRAIN-2 (R1 pause ceiling preserved) — unchanged
`determine_battery_drain_actions(soc_threshold=...)` at `energy.py:5842` (EV) and
`:5977` (plugs) sources from `self._ev_battery_drain_soc` unchanged.

### INV-DP-DRAIN-3 (R3 ride-proof floor preserved) — unchanged
`_ev_battery_drain_soc` remains the ride-proof floor at `energy.py:3752`,
`energy_pool.py:954`, and `energy_pool.py:1435`. Byte-identical.

### INV-DP-DRAIN-4 (offpeak-drain live-apply — CONFIRMED) — unchanged
Live-apply via `EnergyCoordinator.set_offpeak_drain` at `energy.py:8645-8653`.

**DISSOLVED at Rev-16 / Rev-17:**
- The Rev-14 three-predicate negative-inference gate (already dissolved at Rev-15).
- The Rev-15 boolean-stamp gate + coordinator pre-determine_mode reset site +
  `_dp_drain_target_soc(...)` helper + `_dp_emitter_in_drain_branch()` helper — all
  deleted. Replaced by the value stamp + threaded local. The Rev-15
  `_offpeak_drain_branch_this_tick` bool attribute is REPLACED (not augmented) by
  `_offpeak_drain_branch_target: int | None`.
- **The Rev-16 consumer-side read-and-clear mailbox — REMOVED at Rev-17.** Authority
  moves to the producer entry-reset.

Reviewer D writes a legal-config repro for any leak in INV-DP-DRAIN-1 / 1c / 1d / 1e / 2 / 3 / 4.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`
unless noted. All line numbers re-verified against source THIS SESSION (Rev-17).

**Rev-17 grep audit (load-bearing):**
- `grep -n "def determine_mode" energy_battery.py` → `4590:    def determine_mode(`.
  Rev-17 entry-reset lands as the first executable statement inside this function.
- `grep -n "await " energy_battery.py` → only three hits in the file: `:3266-3318`
  (storm-state prose in a different method), `:4916` (a local variable named
  `_await_reason`, NOT an `await` statement), `:5840` (in an unrelated
  service_call). **Zero `await` between `:4590` and `:5352`.** `determine_mode` is
  fully synchronous → producer entry-reset + consumer capture-immediately-after-
  return is airtight for ANY number of callers.
- `grep -n "def _get_off_peak_decision" custom_components/**` → **zero hits.** The
  function does not exist. Every prior-revision mention was drift; the drain-
  fallback branch is inline inside `determine_mode` (def at `:4590`; branch at
  `:5269-5352`).
- `grep -n "determine_mode(" custom_components/**` → two callers in `energy.py`:
  `:5573` (`_decision_cycle_body`) and `:6185` (`_evaluate_battery`). Two-caller
  asymmetry is the D-HIGH-2 (await race) source AND the D2-HIGH-1 (between-tick
  stale) source; producer entry-reset + pre-await lexical capture close BOTH.
- `grep -n "await" energy.py` between `:5573` and `:5628` → `await
  self._account_arbitrage_cycle(...)` (`:5587`) and `await
  self._refresh_arbitrage_status_cache()` (`:5588`). These are the D-HIGH-2 race
  window (closed by pre-await capture) — they do NOT open D2-HIGH-1 (which is
  cross-tick, closed by entry-reset).
- `grep -n "hold_depth" energy_battery.py` around `determine_mode`: `:4903`
  short-circuits ONLY on `full_hold`; `:4900` comment "partial_hold/allow_discharge
  fall through"; partial_hold clamp at `:5321-5322`
  `drain_target = max(drain_target, effective_reserve)`. Verified. D-HIGH-1 surface
  real.
- `grep -n "return self._result" energy_battery.py` around the drain branch → the
  two drain-branch returns are `:5326` (above-target, emits
  `reserve_level=drain_target`) and `:5344` (at/below-target, emits
  `reserve_level=hold_reserve` where `hold_reserve = int(soc)` optionally clamped
  by `:5342-5343`). **The stamped `drain_target` equals `reserve_level` ONLY on the
  `:5326` return** — see §1 reserve-level note.
- `grep -n "current_offpeak_drain_target" energy_battery.py` — definition at
  `:1726-1747`; does NOT apply the partial_hold clamp. Its docstring at `:1730`
  references `_get_off_peak_decision` (stale drift; docs-fix carded, not this
  cycle).

**Source of truth files consulted:**
* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` — DP mechanism §6.
* **Rev-17 source of truth:** `scripts/probes/dp_drain_target_candidate_sim.py`
  (v6 rebuilt this cycle — see §3a). `in_drain_branch` remains an INDEPENDENT
  fixture field; **`emitted_drain_target` is now ALSO an INDEPENDENT hand-set field
  per fixture** (Rev-16 derived it from `emitter_drain_floor(s)`, which made
  C6≡ORACLE-A a tautology on the value axis — Rev-17 fixes this so C6's value-axis
  score is real evidence, not construction). `effective_reserve` remains an
  independent field.
* `energy_drain_precedence.py` — `evaluate_dp_transition:609-735`;
  `TransitionInputs`. **NEW constant** `DP_REASON_EMITTER_NOT_DRAINING =
  "emitter_not_draining"` alongside existing `DP_REASON_*` (`:489-498`).
* `energy.py` —
  * **`_decision_cycle_body` at `:5534`.** TOU period bound at `:5540`.
    `determine_mode` call opens at `:5573` and closes at `:5578` (multi-line
    call). **Insert local capture immediately after the closing paren, at
    approximately `:5579`, and BEFORE any `await`** (§3, ~10 LoC).
    `await self._account_arbitrage_cycle(...)` at `:5587`.
    `await self._refresh_arbitrage_status_cache()` at `:5588`. EVSE-hold overlay
    at `:5604-5616`. `_dp_decision_tick(decision, period, ev_load_w)` called at
    `:5628` — **CHANGE to keyword-thread the local**:
    `_dp_decision_tick(decision, period, ev_load_w, drain_target_soc=_dp_drain_target_local)`.
  * **`_evaluate_battery` at `:6180`.** Calls `determine_mode` at `:6185` (second
    caller). Rev-17 leaves this callsite unchanged: it may freely stamp
    `_offpeak_drain_branch_target`; DP is decoupled via the threaded local, and
    the producer entry-reset at determine_mode:4590 guarantees the NEXT
    `_decision_cycle_body` tick's determine_mode call will clear before any
    stamping. `_evaluate_battery` itself does NOT call `_dp_decision_tick`.
    Verified via read at `:6180-6230` this session.
  * **R2 sites** (`_dp_decision_tick` at `:4326-4573`): `:4456` real tick;
    `:4522` `_DPAct`; `:4540` `_DPActRescan`; `:4555` revert predicate `_drain`.
  * **Shadow R2 site** `_run_dp_shadow_eval` at `:4195-4324`; `:4271` shadow
    `drain_target_soc = int(self._ev_battery_drain_soc)`. Called at `:4408-4414`
    (kill-switch OFF path). Rev-17 CHANGE: `_run_dp_shadow_eval` gains a
    `drain_target_soc: int | None = None` keyword parameter; the call site at
    `:4410` forwards it: `self._run_dp_shadow_eval(decision=..., ev_load_w=...,
    period=..., drain_target_soc=drain_target_soc)`. The local is already in
    scope inside `_dp_decision_tick` (received as a keyword parameter), so it
    forwards through — no attribute read.
  * **R2-display:** `:3871` is R3 blind-window static payload (NOT a valid live
    source); correct live payload is
    `sensor.ura_energy_coordinator_ev_charging_plan.last_eval_snapshot.inputs.drain_target_soc`.
  * **`_apply_dp_transition` at `energy.py:4873`.** Unchanged.
  * **`_apply_dp_reversion` at `energy.py:4959`.** Unchanged.
  * **R1 sites:** `:5842` EV, `:5977` plug. Unchanged.
  * **R3 site:** `:3752`. Unchanged.
  * **Off-peak gate at `:4416`** — unchanged; single-read TOU discipline
    preserved.
  * **Compute site (per-tick truth for in-body R2 uses):** REMOVED at Rev-16 /
    Rev-17 — the coordinator captures the local before `_dp_decision_tick` is
    called, and threads it in as `drain_target_soc: int | None`.
  * **Safety branches that MUST run when the threaded value is None:**
    * MUST_START_FORCED → `_revert = True` at `:4558-4559`;
    * paused-but-nothing-charging reconciliation at `:4560-4565`;
    * state-machine revert edge at `:4546-4550`;
    * **INV-DP-DRAIN-1e — TRANSITIONED + threaded-None force-revert.**
    See containment §3.
  * `_ev_battery_drain_soc`: init `:441`, getter `:8730`, setter `:8732-8738` —
    unchanged.
  * **Setter for `_drain_targets` (INV-DP-DRAIN-4):** `set_offpeak_drain` at
    `energy.py:8645-8653`.
* `energy_pool.py` — R3 callers `:954`, `:1435`; helper `:619-648`. Unchanged.
* `energy_battery.py` —
  * `reserve_soc: int` at `:349`.
  * `_arbitrage_active: bool` init at `:483`. CLEARED at `:3157` (WAIT), `:4705`
    (envoy-blind hold), `:5274` (drain-fallback branch entry). Rev-17 does NOT
    consult this attribute; kept for its existing consumers.
  * **`current_offpeak_drain_target():1726-1747`** — accessor unchanged. Its
    docstring at :1730 references `_get_off_peak_decision` (stale drift). Rev-17
    does NOT read this accessor from DP — DP now consumes the emitter's emitted
    value directly. The accessor remains used by `compose_release_floor` etc.
    (unchanged).
  * **`_offpeak_drain_branch_target: int | None = None`** — **NEW instance attr.**
    Init in `BatteryStrategy.__init__` (~1 LoC alongside `_arbitrage_active` at
    `:483`).
  * **`determine_mode` at `:4590` — PRODUCER ENTRY-RESET.** ADD as the FIRST
    executable statement: `self._offpeak_drain_branch_target = None`. This is
    the Rev-17 load-bearing change.
  * **Drain-fallback branch: `:5269-5352`.** ADD one line
    `self._offpeak_drain_branch_target = int(drain_target)` immediately after
    the partial_hold clamp at `:5322` and before the `if soc is not None and
    soc > drain_target:` split at `:5324`. Rationale unchanged from Rev-16:
    post-clamp value, before the return split, fail-closed on raise.
  * **NB: this cycle DOES modify `energy_battery.py` (~3 LoC).** Scope: 1 LoC
    init + 1 LoC entry-reset + 1 LoC stamp, all grep-anchored (§12).
  * `evaluate_inclement` full_hold short-circuit at `:4903`; arbitrage gate
    short-circuit at `:5236-5246`; attain-branch short-circuit at `:5253-5267`;
    partial_hold clamp at `:5321-5322`. Cited for reviewer orientation; the
    entry-reset at `:4590` runs BEFORE any of these short-circuits, so they
    all correctly return None-attribute.
* `energy_const.py` — unchanged.
* `sensor.py` — `sensor.ura_energy_coordinator_ev_charging_plan` emits
  `last_eval_snapshot.inputs.drain_target_soc` — correct live-validation
  attribute.
* **Extract-exec test harnesses (framing-C precedent).** Rev-17 build MUST:
  * `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py`:
    - Extracted-name set at `:208-223`. Rev-15 helper names
      (`_dp_drain_target_soc`, `_dp_emitter_in_drain_branch`) already REMOVED at
      Rev-16. Rev-17 needs no additional name changes.
    - Second name list at `:322-334`. Same.
    - `_StubBattery` at `:250`: attribute is `_offpeak_drain_branch_target: int
      | None = 10` (default "in drain branch"); N-scenario fixtures set `None`
      explicitly.
    - `_SpyBattery` at `:465` — add `_offpeak_drain_branch_target = None`
      EXPLICITLY on the class so raising `__getattr__` is not consulted for it.
    - `_Boom` at `:522`: `__getattr__` raises; the local-capture site's
      try/except returns None (declines safely).
    - **Any fake `determine_mode` implementation** in the harness that wants to
      simulate the entry-reset semantics MUST set
      `self._offpeak_drain_branch_target = None` as its first line (mirror the
      production discipline). Fakes that omit this are testing the WRONG
      contract — the T-two-caller-race test (§7) MUST drive the REAL
      determine_mode, not a fake, so that neutering the entry-reset actually
      causes the test to fail.
    - **Threaded-parameter fixtures:** tests that call `_dp_decision_tick`
      directly (not through `_decision_cycle_body`) now MUST pass
      `drain_target_soc=<value or None>` explicitly.
  * `quality/tests/test_evse_drain_precedence_session_b2c2_fixup.py` — same
    shape.
  * `quality/tests/test_baec_shadow_eval.py:34-42` — inherit via b2c1 or re-add
    `drain_target_soc=` on calls to `_run_dp_shadow_eval`.
* Memory: `project_ev_drain_precedence_cycle`, `feedback_hollow_test_anchors`,
  `feedback_mutation_verification_pycache_staleness`,
  `feedback_suppression_needs_discharge` (INV-DP-DRAIN-1e).
* **Live values (Rev-11 verified):**
  - `number.ura_energy_coordinator_ev_battery_drain_soc = 80`.
  - `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target = 10`.
  - `reserve_soc = 10`.

---

## 3. Deliverable

### Full R2 emission-site table

| Site | Where | Class | Change (Rev-17) |
|---|---|---|---|
| `energy.py:4271` | Shadow `TransitionInputs` (inside `_run_dp_shadow_eval`) | **R2 (shadow)** | Gate on threaded `drain_target_soc is not None`; on None publish `shadow_reason=DP_REASON_EMITTER_NOT_DRAINING` (or optional `"wrong_period"` if the explicit period guard is kept); pass threaded value verbatim into `_DPInputs.drain_target_soc`. Do NOT raise. |
| `energy.py:4456` | Real tick `TransitionInputs` | **R2** | Use threaded `drain_target_soc` verbatim, inside gated block |
| `energy.py:4522` (`_DPAct`) | Fresh-TRANSITIONED actuation | **R2** | Use threaded value verbatim, inside gated block |
| `energy.py:4540` (`_DPActRescan`) | Second-plug rescan | **R2** | Use threaded value verbatim, inside gated block |
| `energy.py:4555` (`_drain`) | Revert predicate | **R2 (revert consistency)** | Use threaded value; keep two-part None guard; **NEW: force-revert on TRANSITIONED+threaded=None** (INV-DP-DRAIN-1e) |
| `energy.py:3871` | R3 blind-window static payload | R3-display | Unchanged |
| `energy.py:4021` region | DP eval decision-log | R2-display | Auto-follows |
| `energy.py:4873` (`_apply_dp_transition`) | Stamp site | R2 consumer | No change |
| `energy.py:3752` / `energy_pool.py:954` / `:1435` | R3 | R3 | Unchanged |
| `energy.py:5842` / `:5977` | R1 | R1 | Unchanged |

### Battery-side edits (`energy_battery.py`)

**Edit 1 — init the value stamp** (in `BatteryStrategy.__init__`, adjacent to `:483`):
```python
self._arbitrage_active = False
# Rev-17: value stamp for DP's drain-target source. Written by the drain-
# fallback branch of determine_mode at :5322-5323 (after the partial_hold
# clamp, before the return-split); cleared at the top of every
# determine_mode call by the entry-reset at :4590 (Edit 2). DP itself
# consumes the value via a LOCAL captured by
# EnergyCoordinator._decision_cycle_body immediately after determine_mode
# returns at energy.py:~5579 (before the awaits at :5587-5588). See
# PLANNING §1 INV-DP-DRAIN-1d.
self._offpeak_drain_branch_target: int | None = None
```

**Edit 2 — producer entry-reset** (in `determine_mode` at `energy_battery.py:4590`,
as the FIRST executable statement, BEFORE any early return):
```python
def determine_mode(self, period, season, *, now=..., tou_transition_into=...,
                   ev_load_w=...):
    # Rev-17 PRODUCER ENTRY-RESET (INV-DP-DRAIN-1d, closes D2-HIGH-1).
    # Clear the drain-branch value stamp before ANY early return so every
    # determine_mode invocation from every caller starts fresh. Combined
    # with determine_mode being fully synchronous (verified :4590-:5352
    # contains ZERO await), this guarantees the consumer's lexical
    # capture immediately after our return reads exactly THIS call's
    # result: None if we return without hitting the stamp line, or the
    # post-clamp drain_target if the drain-fallback branch reached
    # :5322-5323. Airtight for ANY number of callers by construction.
    self._offpeak_drain_branch_target = None
    ...
```

**Edit 3 — stamp the value** (in `determine_mode`, at `:5322-5323`):
```python
if decision.hold_depth == "partial_hold":
    drain_target = max(drain_target, effective_reserve)
# Rev-17 value stamp (INV-DP-DRAIN-1d). Placed AFTER the partial_hold
# clamp so the stamped value == the post-clamp drain_target variable
# used by the two _result(...) calls below as the SOC-threshold. Placed
# BEFORE the above-target / at-target return split so both emission
# paths inherit the same stamped value. A raise between branch entry
# at :5269 and this line leaves the attr None (the entry-reset already
# cleared it) → DP declines this tick, fail-closed. SOLE value-write
# site (grep-anchored, §12).
self._offpeak_drain_branch_target = int(drain_target)
```

**No other `energy_battery.py` change.** In particular the Rev-15 boolean
`_offpeak_drain_branch_this_tick` is REPLACED (not augmented), and the DP path does
NOT read `_arbitrage_active`, `_attain_state`, or `_last_inclement_decision.hold_depth` —
those are unchanged in behaviour and readable by their existing consumers.

### Coordinator-side capture (`energy.py`, in `_decision_cycle_body`)

Immediately after the `determine_mode` return (multi-line call closes at
`energy.py:5578`) — approximately `:5579` — and BEFORE the first `await` at `:5587`,
insert (~10 LoC):

```python
# Rev-17 INV-DP-DRAIN-1d: capture the emitter's just-emitted drain target
# into a stack-local BEFORE the awaits at :5587-5588. The producer
# entry-reset at determine_mode:4590 guarantees this reads EXACTLY the
# value THIS call produced (None if the branch didn't reach the stamp;
# post-clamp drain_target if it did). The local is threaded into
# _dp_decision_tick at :5628 as `drain_target_soc=`, and forwarded from
# there into _run_dp_shadow_eval at :4410. NO re-read of
# `_offpeak_drain_branch_target` later in the tick. NO consumer-side
# write-back (Rev-16 mailbox removed at Rev-17 — the authoritative
# clear is at the producer entry). Defensive: any exception → None.
try:
    _dp_drain_target_local: int | None = getattr(
        self._battery, "_offpeak_drain_branch_target", None,
    )
    if _dp_drain_target_local is not None:
        _dp_drain_target_local = int(_dp_drain_target_local)
except Exception:  # noqa: BLE001
    _dp_drain_target_local = None
    _LOGGER.debug("DP drain-target capture raised (swallowed)", exc_info=True)
```

And the `_dp_decision_tick` call at `:5628` becomes:

```python
self._dp_decision_tick(
    decision, period, ev_load_w,
    drain_target_soc=_dp_drain_target_local,
)
```

The `_dp_decision_tick` signature at `energy.py:4326-4328` gains
`drain_target_soc: int | None = None` (keyword-only or as the next positional; default
None so any test/harness that hasn't been updated declines DP safely — fail-closed
default).

### `_run_dp_shadow_eval` — parameter thread-through

At `energy.py:4195`, `_run_dp_shadow_eval` gains `drain_target_soc: int | None = None`
as a keyword parameter. At the call site inside `_dp_decision_tick` at `energy.py:4410`,
forward the local through:

```python
if not _dp_on:
    try:
        self._run_dp_shadow_eval(
            decision=decision, ev_load_w=ev_load_w, period=period,
            drain_target_soc=drain_target_soc,  # Rev-17: thread through
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("DP shadow eval raised", exc_info=True)
```

### DELETED at Rev-16 / Rev-17

* `_dp_emitter_in_drain_branch()` helper on `EnergyCoordinator` (Rev-15) — DELETED.
* `_dp_drain_target_soc(period)` helper on `EnergyCoordinator` (Rev-13/14/15) —
  DELETED.
* Coordinator-side reset of `_offpeak_drain_branch_this_tick` in `_decision_cycle_body`
  before `determine_mode` (Rev-15) — DELETED (Rev-16).
* **Coordinator-side read-and-clear "mailbox" of `_offpeak_drain_branch_target` at
  the capture site (Rev-16) — DELETED at Rev-17.** The authoritative clear moves to
  the producer entry (`determine_mode:4590` first line).

### New constant `DP_REASON_EMITTER_NOT_DRAINING` (kept from Rev-15)

Add to `energy_drain_precedence.py` alongside `DP_REASON_*` (`:489-498`):
```python
DP_REASON_EMITTER_NOT_DRAINING = "emitter_not_draining"
```
All caller code MUST reference the constant, not the raw string. The shadow-path
`shadow_reason` string is also emitted through the same constant.

### Containment shape — gate consumers, safety branches always run

Inside `_dp_decision_tick` (at `energy.py:4326-4573`), immediately after the blind-
hold snapshot at `:4437-4447` and before `_DPInputs(...)` at `:4448`, insert:

```python
# Rev-17: threaded-local gate. `drain_target_soc` was captured in
# _decision_cycle_body immediately after determine_mode returned at
# energy.py:~5579, before the awaits at :5587-5588. Non-None == "the
# drain-fallback branch emitted a target this tick"; None == "did not".
# The value IS the emitter's post-clamp drain_target (INV-DP-DRAIN-1d);
# no re-derivation.
from .energy_drain_precedence import DP_REASON_EMITTER_NOT_DRAINING
if drain_target_soc is None:
    _dp_decline_reason = DP_REASON_EMITTER_NOT_DRAINING
else:
    _dp_decline_reason = None
```

Consumption gate — wrap `:4448-4542` in `if drain_target_soc is not None:`; on the
skipped path still emit the decision-log row via `_log_dp_eval_decision` carrying
`reason=_dp_decline_reason`.

**Revert predicate (`:4555`) — INV-DP-DRAIN-1e added:**

```python
_revert = False
if self._dp_carrier.state == _DPState.TRANSITIONED:
    if _soc is not None and drain_target_soc is not None and int(_soc) <= drain_target_soc:
        _revert = True
    # Rev-17 INV-DP-DRAIN-1e: TRANSITIONED + threaded-None = strategy
    # has moved on (arbitrage HOLD, inclement full_hold elevation,
    # attain latch, envoy-blind hold, grid disconnect, etc.). Release
    # the carrier so paused EVSEs are freed. Force revert.
    if drain_target_soc is None:
        _revert = True
if self._dp_carrier.state == _DPState.MUST_START_FORCED:
    _revert = True
if (
    self._dp_carrier.state == _DPState.TRANSITIONED
    and not self._ev._paused_by_dp  # noqa: SLF001
    and not self._is_any_evse_charging()
):
    _revert = True
```

Keep both None-guards on the `_soc <= drain_target_soc` comparison.

**Shadow site containment (`:4271`):**

```python
# Inside _run_dp_shadow_eval, replacing the int(self._ev_battery_drain_soc) at :4271.
from .energy_drain_precedence import DP_REASON_EMITTER_NOT_DRAINING
if drain_target_soc is None:
    self._dp_carrier.shadow_decision = "not_applicable"
    self._dp_carrier.shadow_reason = DP_REASON_EMITTER_NOT_DRAINING
    self._dp_carrier.shadow_last_eval_at = now
    self._dp_carrier.shadow_last_eval_snapshot = {}
    return
inputs = _DPInputs(
    ...
    drain_target_soc=int(drain_target_soc),  # Rev-17 verbatim
    ...
)
```

Optional (kept from Rev-15 for post-hoc investigation): an EARLIER `if period !=
"off_peak"` guard that publishes `shadow_reason="wrong_period"` distinctly. This is
belt-and-suspenders because `drain_target_soc` is already None on peak. Recommend
KEEP for diagnostic clarity.

**TOU period — ONE read per tick** (unchanged). Bound at `_decision_cycle_body:5540`,
passed through.

**Producer / Consumer + call-site check.**
- **PRODUCER of the value stamp:** `energy_battery.py:5322-5323` (drain-fallback
  branch, AFTER the partial_hold clamp, BEFORE the return split). SOLE writer of a
  non-None value. Dependencies: the branch itself running (TOU off_peak + branch
  matrix at :5236-5267 both declining) AND reaching the clamp line without raising.
- **PRODUCER of the None-reset (Rev-17):** `energy_battery.py:4590` first line
  (entry-reset). Runs on EVERY determine_mode invocation, EVERY caller, BEFORE any
  short-circuit / early return. This is the D2-HIGH-1 close.
- **CONSUMERS of the attribute:** `EnergyCoordinator._decision_cycle_body` at the
  local-capture site at approximately `energy.py:5579` (SOLE reader). Zero display-
  only readers. `_evaluate_battery` at `:6185` does NOT read the attribute (its
  determine_mode call will entry-reset then may stamp as side-effect; no consumer
  code reads it back).
- **CONSUMERS of the threaded local:** `_dp_decision_tick` (via new keyword
  parameter) → forwards to `_run_dp_shadow_eval` (via new keyword parameter). No
  other reader.
- **PRODUCER of `current_offpeak_drain_target()`:** unchanged. NOT read by DP at
  Rev-17 (was read by Rev-13/14/15). Its non-DP consumers (`compose_release_floor`,
  etc.) are unchanged.
- **Should-be-consuming-but-isn't.** Deferred to post-ship supersession + consumer
  audit.

**Hold-demotion — OUT OF SCOPE.**

**Files changed (Rev-17).**
* `energy_battery.py` — **~3 LoC:**
  * init `_offpeak_drain_branch_target: int | None = None` at ~`:483` (~1 LoC).
  * **entry-reset `self._offpeak_drain_branch_target = None` as the FIRST
    executable statement of `determine_mode` at `:4590` (~1 LoC).**
  * stamp `self._offpeak_drain_branch_target = int(drain_target)` at `:5322-5323`
    after the partial_hold clamp (~1 LoC).
* `energy.py` —
  * insert local-capture block in `_decision_cycle_body` at approximately `:5579`
    (immediately after the multi-line determine_mode call closes at `:5578`),
    BEFORE the first `await` at `:5587` (~10 LoC with try/except). **NO read-and-
    clear write-back at this site** (Rev-16 mailbox removed).
  * `_dp_decision_tick` signature at `:4326-4328` gains
    `drain_target_soc: int | None = None`.
  * `_run_dp_shadow_eval` signature at `:4195` gains
    `drain_target_soc: int | None = None`.
  * call site at `:5628` threads the local: `drain_target_soc=_dp_drain_target_local`.
  * call site at `:4410` forwards: `drain_target_soc=drain_target_soc`.
  * gate block after `:4447` reads the parameter (~8 LoC).
  * wrap `:4448-4542` in `if drain_target_soc is not None:` and substitute the
    threaded value at `:4456`, `:4522`, `:4540`.
  * substitute the threaded value at revert `:4555`; add INV-DP-DRAIN-1e force-
    revert.
  * `_log_dp_eval_decision` on skip path carries `reason=_dp_decline_reason`.
  * in `_run_dp_shadow_eval`, replace `int(self._ev_battery_drain_soc)` at `:4271`
    with the threaded-value None-guard + verbatim consumption block.
  * DELETE `_dp_emitter_in_drain_branch()` helper (was Rev-15).
  * DELETE `_dp_drain_target_soc()` helper (was Rev-13/14/15).
* `energy_drain_precedence.py` — add `DP_REASON_EMITTER_NOT_DRAINING` constant.
* Test harnesses per §2 — `_offpeak_drain_branch_target` attr on all fake
  batteries; update direct `_dp_decision_tick(...)` callers to pass
  `drain_target_soc=`. New T-two-caller-race test that drives the REAL
  determine_mode (§7).
* New tests per §7.

---

## 3a. Candidate simulation record (Rev-17 — sim v6, honest `emitted_drain_target`)

`scripts/probes/dp_drain_target_candidate_sim.py` (v6). Rev-17 delta vs Rev-16 v5:

- **`emitted_drain_target` is now an INDEPENDENT hand-set fixture field** — one per
  scenario, set in the `mk(...)` call site alongside `in_drain_branch` and
  `effective_reserve`. Rev-16 derived it from `emitter_drain_floor(s)`, which made
  C6≡ORACLE-A a tautology on the value axis (C6's value came from the SAME function
  ORACLE-A uses). Rev-17 breaks the derivation: each fixture states the emitted
  value the emitter is EXPECTED to emit for that scenario, independently. C6's
  value-axis score is therefore real evidence, not construction.
- `in_drain_branch`, `effective_reserve` remain independent fields (unchanged from
  Rev-16).
- N3 partial_hold remains `in_drain_branch=True, effective_reserve=50,
  emitted_drain_target=50` (the expected post-clamp value the emitter emits).
- Non-drain fixtures: `emitted_drain_target=None`.
- D4 (inverted config) fixture: `emitted_drain_target=10` (the emitter's actual
  return on the `:5344` path is `hold_reserve=int(soc)` clamped, but for
  above-target D4 with soc=40, drain=10 the emitter returns via `:5326` with
  `reserve_level=drain_target=10`; the DP threshold DP compares against is 10 →
  `emitted_drain_target=10`).
- Oracles unchanged: ORACLE-A = strict emitter mirror (with :5322 clamp);
  ORACLE-B = RULED formula `max(reserve, emitter_drain_floor)`.

**Corrected scorecard (12 fixtures — D1-D4 drain + N3-drain + N1/N2/N4-N8 non-drain, per Rev-16 fixture reshuffle).**

| Candidate | ORACLE-A | ORACLE-B | Blocking failure |
|---|---|---|---|
| C0 static knob (pre-fix bug) | **0/12** | **0/12** | Acts everywhere with wrong value |
| C1 compose/park (BUILT, no gate) | **1/12** | **1/12** | Overlay pin; acts in all non-drain |
| C2 accessor alone (no gate) | **4/12** | **3/12** | Acts in all 7 non-drain; misses N3 clamp; ties ORACLE-A on D1/D2/D3/D4 (=10 on D4 mirrors emitter) but misses ORACLE-B on D4 (10 vs 15) |
| C3 max(reserve, accessor) (Rev-13, no gate) | **3/12** | **4/12** | Acts in all 7 non-drain; misses N3 clamp; matches ORACLE-B on D4 (15) but diverges from ORACLE-A on D4 (15 vs 10) |
| C4 RULED + negative-inference gate (Rev-14) | **6/12** | **7/12** | Correctly declines N1/N2/N4; INCORRECTLY DECLINES on N3 (partial_hold — drain branch DID run; negative gate's `hold_depth != allow_discharge` closes it wrongly); INCORRECTLY ACTS on N5-N8. |
| C5 RULED + positive-BOOL-stamp gate (Rev-15) | **10/12** | **11/12** | Declines all 7 non-drain correctly; exact on D1/D2/D3; **INCORRECTLY EMITS un-clamped value on N3** (D-HIGH-1: emits `max(10,10)=10` where oracle emits 50); D4 diverges from ORACLE-A (emits 15 not 10). |
| **C6 value-stamp (Rev-17 proposal)** | **12/12** | **11/12** | Declines all 7 non-drain BY CONSTRUCTION (`emitted_drain_target=None`). Exact on ALL 5 drain fixtures under ORACLE-A (returns the hand-set expected emitted number, which IS the strict-emitter mirror by design). Diverges from ORACLE-B only on D4 (returns 10; ORACLE-B expects `max(reserve=15, 10)=15`) — this is the operator-ruled safety-floor divergence, live NO-OP because live config has `reserve <= drain`. |

**Reading the scorecard.** C5's one loss (N3 partial_hold) is exactly D-HIGH-1: the
bool-stamp opens the gate correctly (drain branch DID run) but DP re-derived the
target via `max(reserve, current_offpeak_drain_target())` and got 10, not 50 — the
partial_hold clamp is not mirrored by the accessor. **C6's 12/12 under ORACLE-A is
NOT a tautology at Rev-17**: `emitted_drain_target` is hand-set per fixture,
independent of any oracle formula. C6 wins the ORACLE-A axis because the design
consumes what the emitter emitted; C6 loses one under ORACLE-B (the RULED-max
formula) on the inverted-config D4 fixture — that is the documented, operator-
ruled divergence (live NO-OP under `reserve <= drain`). **The A/B narrative
correction vs Rev-16:** C6 is 12/12 under ORACLE-A (the strict emitter mirror);
the D4 divergence sits under ORACLE-B. Prior revisions of this table had A/B
labels swapped.

---

## 3b. Acceptance criteria

Each observation is chosen to DISCRIMINATE the fix from a plausible different failure.

- **Verify (drain-fallback branch, source, discriminating):** fresh DP tick with
  drain branch fired (attr `_offpeak_drain_branch_target=10` post-stamp),
  `reserve_soc=10`, `current_offpeak_drain_target()=10`, SOC=40, off-peak:
  `TransitionInputs.drain_target_soc == 10`; `_dp_decision_soc == 10`.
  Discriminates from static-knob bug (would emit 80), from compose/park (would emit
  65 under EVSE hold), AND from Rev-15 partial_hold miss (in a partial_hold repro
  the value would still be 10, discriminated by the partial_hold test below).
- **Verify (mirror-the-emitter under EVSE hold):** `_evse_hold_soc=65`, SOC=40,
  accessor=10, `reserve_soc=10`, drain branch fired: DP drain target reads **10**
  (accessor mirror via emitter's emitted value, not the 65 overlay).
- **Verify (partial_hold clamp — D-HIGH-1 anchor, load-bearing):** inclement
  `partial_hold` with `effective_reserve=50`, `current_offpeak_drain_target()=10`,
  `reserve_soc=10`, SOC=55, off-peak: the drain branch runs (per :4900 fall-
  through); at the stamp line `drain_target = max(10, 50) = 50`; DP threaded value
  is **50**, `TransitionInputs.drain_target_soc == 50`. Discriminating counter-
  fixture: swap in Rev-15 mechanism (bool True + re-derive `max(reserve, accessor)`)
  → DP reads 10, transitions when it should hold → fixture fails.
- **Verify (D-HIGH-2 anchor — pre-await capture, in-tick two-caller):** call
  `_evaluate_battery` at :6185 with a fake battery that stamps
  `_offpeak_drain_branch_target = 99` (a value distinct from anything the drain
  branch would legitimately emit); interleave with `_decision_cycle_body` such that
  `_evaluate_battery`'s stamp happens between :5573 and :5628 (simulated via async
  ordering in-suite). Assert `_dp_decision_tick` still uses the LOCAL captured
  before the awaits (e.g. 10), not 99 from the attribute. Mutation anchor: change
  the gate block to read `self._battery._offpeak_drain_branch_target` instead of
  the parameter → test fails on the 99-vs-10 discrepancy.
- **Verify (D2-HIGH-1 anchor — producer entry-reset, cross-tick two-caller,
  LOAD-BEARING, drives REAL `determine_mode`):** drive a REAL `BatteryStrategy`
  (not a fake) through this sequence:
  1. On tick T0, invoke `_evaluate_battery` (or equivalently drive its
     `determine_mode` code path) so its determine_mode call reaches the drain
     branch stamp at `:5322-5323`, stamping `_offpeak_drain_branch_target = 10`.
  2. On tick T1, drive `_decision_cycle_body` so its `determine_mode` call
     returns via a NON-drain path (e.g. inclement `full_hold` short-circuit at
     `:4903` — configure the fake HA state so `evaluate_inclement` returns
     `full_hold`). The drain branch does NOT run on T1, so the stamp line at
     `:5322-5323` does NOT execute on T1's call.
  3. Assert: the coordinator's captured local on T1 is **None**, not 10; DP
     declines on T1 with `DP_REASON_EMITTER_NOT_DRAINING`.
  Mutation anchor **C-entry-reset**: delete the
  `self._offpeak_drain_branch_target = None` line at
  `energy_battery.py:4590` → without the entry-reset, T1's determine_mode
  returns without touching the attribute, the leftover T0 stamp of 10 survives,
  the coordinator captures 10 on T1, DP acts on a tick where the emitter did
  not emit → assertion `local is None` fails. **This test MUST drive the REAL
  determine_mode; a fake-determine_mode fixture cannot exercise a reset that
  lives in production source.**
- **Verify (no in-tick helper call):** grep production source — inside the body of
  `_dp_decision_tick` (delimited by `:4326-4573`) AND inside the body of
  `_run_dp_shadow_eval` (delimited by `:4195-4324`) there are ZERO calls to any
  `_dp_emitter_in_drain_branch(...)` (helper is deleted) AND ZERO calls to any
  `_dp_drain_target_soc(...)` (helper is deleted) AND ZERO reads of
  `self._battery._offpeak_drain_branch_target`. Test T-no-helper.
- **Verify (branch-not-run — arbitrage WAIT):** arbitrage strategy returned WAIT,
  drain branch never ran, entry-reset cleared attr to None: capture yields None; DP
  does NOT populate `TransitionInputs`; decision-log carries
  `reason == DP_REASON_EMITTER_NOT_DRAINING`.
- **Verify (branch-not-run — envoy-blind hold):** envoy unavailable, early return
  at :4696-4706, drain branch never ran, entry-reset cleared: DP declines.
- **Verify (branch-not-run — attain latched / attain-reboot-release):** attain
  branch short-circuits at :5253-5267 or returns via :4131, drain branch never ran,
  entry-reset cleared: DP declines.
- **Verify (branch-not-run — inclement full_hold):** full_hold short-circuits at
  :4903, drain branch never ran, entry-reset cleared: DP declines with
  `DP_REASON_EMITTER_NOT_DRAINING`.
- **Verify (branch-not-run — peak-period):** peak tick, `determine_mode` returns
  before off-peak branch, drain branch not invoked; on the SAME tick the shadow
  runs first (before :4416): local is None; shadow publishes either `wrong_period`
  (if belt-and-suspenders period guard kept) or `emitter_not_draining`.
- **Verify (branch-not-run — grid disconnect):** grid_connected=False early return
  at :4890, drain branch never ran, entry-reset cleared: DP declines.
- **Verify (INV-DP-DRAIN-1e — stranded-carrier release):** DP transitioned on tick
  T (drain branch ran, threaded value non-None); on tick T+1 arbitrage HOLD kicks
  in (drain branch does not run, entry-reset cleared attr → threaded value None),
  carrier is TRANSITIONED, EVSE is `_paused_by_dp`: assert `_revert=True` fires via
  the new gate-closed branch; `_apply_dp_reversion` runs; EVSE released.
- **Verify (mid-carrier partial→full inclement upgrade):** DP transitioned on tick
  T under `allow_discharge` (threaded value 10); on tick T+1 inclement upgrades to
  `full_hold` (drain branch does NOT run, :4903 short-circuit fires,
  entry-reset cleared attr → local None); carrier TRANSITIONED + `_paused_by_dp` →
  INV-DP-DRAIN-1e forces revert; EVSE unpaused within one cycle.
- **Verify (accessor-consistent inside drain branch under WATCH):** WATCH-only
  inclement decision → `hold_depth=allow_discharge` → clamp does NOT fire → stamped
  value equals `max(d1, d2)`; DP mirrors accessor.
- **Verify (no same-tick actuate-then-revert):** SOC=40, threaded drain target=10,
  fresh TRANSITIONED does NOT revert same tick (`:4555` sees 10, not 80).
- **Verify:** R1 (`:5842`, `:5977`) STATIC knob unchanged.
- **Verify:** R3 (`:3752`, `energy_pool.py:954/1435`) unchanged.
- **Verify (containment — safety branches on threaded None):** when the threaded
  value is None: `_DPInputs`+`_dp_tick`+actuation+rescan skipped; MUST_START_FORCED
  revert (`:4558-4559`), paused-idle reconciliation (`:4560-4565`), state-machine
  revert edge (`:4546-4550`), and INV-DP-DRAIN-1e force-revert STILL RUN.
- **Verify (shadow containment):** on the shadow path — threaded-None publishes
  `shadow_reason=DP_REASON_EMITTER_NOT_DRAINING` EXACTLY (or `"wrong_period"` if
  the period-guard is kept for peak/mid_peak); shadow does NOT raise.
- **Verify (C-LOW-1 — constant reference):** grep production source for the raw
  string `"emitter_not_draining"` — zero hits outside `energy_drain_precedence.py`'s
  constant definition. All callers reference `DP_REASON_EMITTER_NOT_DRAINING`.
- **Test:** T1, T1b, T1c, T1d, T2, T2b, T3, T4, T4b, T5, T6, T7a-h, T-partial-clamp,
  T-two-caller-race (in-tick, pre-await), **T-cross-tick-reset (Rev-17, drives
  REAL determine_mode, D2-HIGH-1 anchor)**, T-no-helper, T-strand,
  T-strand-partial-to-full, T-shadow-wrong-period (§7).
- **Live (correct source):** with an EV plugged during off-peak AND drain branch
  running (arbitrage OFF or gate closed, `allow_discharge`), read
  `sensor.ura_energy_coordinator_ev_charging_plan.last_eval_snapshot.inputs.drain_target_soc`
  = value the emitter emitted for `drain_target` (expected 10 under current live
  config).
- **Live (paired, discriminating):** DP carrier `TRANSITIONED` AND
  `_dp_decision_soc` non-None on tick T; `_dp_decision_soc == emitted floor` on
  tick T. Under live config that equals `max(reserve, accessor)` because no
  partial_hold is active; if a partial_hold occurs the discriminator strengthens
  (would equal `effective_reserve` when > accessor).
- **Live (gate-closed reason surfaces):** during a known arbitrage HOLD/CHARGE or
  inclement full_hold or WAIT window, DP decision-log carries
  `reason == DP_REASON_EMITTER_NOT_DRAINING` AND carrier in `HOLD_ONLY`. If no
  natural window occurs, proved in-suite (T7a-h) with fact noted in validation
  table.
- **Live (stranded-carrier release, INV-DP-DRAIN-1e):** if a natural mid-carrier
  strategy change occurs (e.g. inclement upgraded partial→full mid-off-peak), DP
  releases the carrier and unpauses EVSE within one decision cycle. If no natural
  occurrence, proved in-suite (T-strand-partial-to-full).

---

## 4. Non-goals

Unchanged from Rev-16 (evse_battery_hold demotion; changing live drain-soc knob;
R1/R3 sourcing; init/getter/setter of `_ev_battery_drain_soc`; DP gate arithmetic;
`compose_release_floor` / `current_park_floor()` re-wiring; adding
`current_desired_release_floor()`; reading `_last_reserve_level_desired`;
cross-midnight staleness). Rev-17 additions/retentions:

* NOT reintroducing the Rev-15 coordinator-side pre-`determine_mode` reset. The
  Rev-17 authoritative reset is at the PRODUCER entry (first line of
  `determine_mode`).
* NOT retaining the Rev-16 consumer-side read-and-clear mailbox at the capture
  site. Removed at Rev-17; producer entry-reset supersedes it.
* NOT calling a helper from inside `_dp_decision_tick` or `_run_dp_shadow_eval` to
  look up the drain target. The threaded parameter is the SOLE interface.
* NOT reading `_arbitrage_active`, `_attain_state`, or `_last_inclement_decision`
  from DP. The gate is threaded-value non-None only.
* NOT fixing the stale docstring reference to `_get_off_peak_decision` inside
  `current_offpeak_drain_target()` at `energy_battery.py:1730` — carded as
  DOCS-DRAIN-DRIFT-1 (§6).
* NOT changing `_evaluate_battery`'s determine_mode call at `:6185`. It may freely
  entry-reset then stamp; the NEXT `_decision_cycle_body` tick's determine_mode
  will itself entry-reset before doing anything, so no cross-tick bleed.

---

## 5. Known couplings

1-7 unchanged from Rev-15.
8. **Local-capture ordering.** The capture in `_decision_cycle_body` MUST run
   immediately after the `determine_mode` return (at approximately `:5579`) and
   BEFORE the first `await` at `:5587`. A builder who inserts an `await` before the
   capture, or moves the capture AFTER the awaits, re-opens the D-HIGH-2 (in-tick,
   pre-await) race. Test T-two-caller-race anchors this.
9. **Extract-exec harnesses.** Any fake battery consumed by tests that drive
   `_decision_cycle_body` will have its `_offpeak_drain_branch_target` read by the
   capture site. Fake `determine_mode` implementations that want to simulate the
   Rev-17 discipline MUST set `self._offpeak_drain_branch_target = None` as their
   first line (mirror the production entry-reset) AND set it to the desired value
   ONLY on paths that model the drain-fallback branch reaching `:5322-5323`. Fakes
   that omit the entry-reset are testing the WRONG contract — the T-cross-tick-
   reset test MUST drive the REAL determine_mode (§7).
10. **Future battery-side branches.** Any NEW branch inside `determine_mode` that
    emits a drain-target-style floor MUST stamp `_offpeak_drain_branch_target` if
    DP should transition on that path. Any new branch that emits a DIFFERENT
    floor (e.g. an arbitrage-charging floor unrelated to drain-precedence) MUST
    NOT stamp. The stamp is the contract.
11. **Second determine_mode caller.** `_evaluate_battery` at `:6185` re-enters
    `determine_mode` which itself entry-resets then may stamp. DP is untouched
    because the NEXT `_decision_cycle_body` tick's determine_mode call will
    entry-reset before any code runs. If a future new caller appears, no
    change is needed — the entry-reset holds for ANY number of callers by
    construction. Documented on the entry-reset comment (§3 Edit 2).

---

## 6. Docs drift to fix in-cycle

Unchanged targets from Rev-16, with Rev-17 addendum:

* `docs/user-manual/ENERGY_COORDINATOR.md:642` — R2 role + value-stamp +
  producer-entry-reset + threaded-local contract.
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` — bind `drain_target` symbol
  to the Rev-17 value-stamp + threaded-local + producer-entry-reset source.
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale line refs.

**Carded (NOT fixed this cycle):**
* Stale `_get_off_peak_decision` docstring reference inside
  `current_offpeak_drain_target()` at `energy_battery.py:1730`. The correct name
  is `determine_mode` (branch inline at `:5269-5352`). Card:
  `DOCS-DRAIN-DRIFT-1` (create at cycle-close if not already present).

INV-DP-DRAIN-4 confirmed live-apply.

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__`.

**Fixture contract — Rev-17 binding.**
* **All asserted drain-target values 4-way distinct** from `reserve_soc`, static
  `_ev_battery_drain_soc` (80), `current_offpeak_drain_target()`, and
  `_last_reserve_level`.
* **Drain-fixture invariant:** every drain-branch fixture MUST set
  `_offpeak_drain_branch_target=<int>` on the fake battery (or drive through a
  real `determine_mode` path that stamps it). The int MUST equal the post-clamp
  `drain_target` variable for that fixture.
* **Non-drain fixture invariant:** every non-drain fixture MUST leave
  `_offpeak_drain_branch_target=None` on the fake battery (or drive through a
  real path whose entry-reset clears it and whose body does not stamp).
* **Direct-tick fixture invariant:** any test that calls `_dp_decision_tick`
  directly MUST pass `drain_target_soc=<value or None>` explicitly.
* **Fake determine_mode discipline:** any fake `determine_mode` implementation
  MUST set `self._offpeak_drain_branch_target = None` as its first line, mirror-
  ing the production entry-reset. Fakes that omit this test the WRONG contract.

**Rev-17 discriminating scenarios (drain-branch, value-carry):** unchanged from
Rev-16.

**Rev-17 partial_hold scenario (LOAD-BEARING, D-HIGH-1 anchor):**
- **T-partial-clamp:** inclement `partial_hold` with `effective_reserve=50`,
  `d1=d2=10`, drain branch runs (per :4900 fall-through), clamp at :5322 raises
  drain_target to 50, stamp captures 50. Assert
  `TransitionInputs.drain_target_soc == 50`. **Mutation anchor C-clamp**: revert
  the stamp placement to BEFORE the partial_hold clamp → stamp captures 10, DP
  reads 10, test fails.

**Rev-17 two-caller (in-tick, pre-await) scenario (D-HIGH-2 anchor):**
- **T-two-caller-race:** drive `_decision_cycle_body` with a fake
  `determine_mode` that stamps `_offpeak_drain_branch_target = 10`; between the
  capture and the `_dp_decision_tick` call, invoke `_evaluate_battery` (whose
  fake `determine_mode` stamps `_offpeak_drain_branch_target = 99`); assert
  `_dp_decision_tick` receives `drain_target_soc=10` (via the threaded local),
  NOT 99. **Mutation anchor C-race**: change the `_dp_decision_tick` body to
  read `self._battery._offpeak_drain_branch_target` instead of the parameter →
  test fails with 99-vs-10.

**Rev-17 cross-tick two-caller scenario (D2-HIGH-1 anchor, LOAD-BEARING, drives
REAL determine_mode):**
- **T-cross-tick-reset:** as specified in §3b under "D2-HIGH-1 anchor". Drive
  REAL `BatteryStrategy.determine_mode` twice: once via `_evaluate_battery`'s
  code path so the drain branch stamps 10; then via `_decision_cycle_body`'s
  code path configured (inclement state fixtures) to return via `full_hold`
  short-circuit at `:4903` before the drain branch. Assert the coordinator's
  captured local on the second tick is **None**, not 10; DP declines with
  `DP_REASON_EMITTER_NOT_DRAINING`. **Mutation anchor C-entry-reset**: delete
  the `self._offpeak_drain_branch_target = None` line at
  `energy_battery.py:4590` → captured local reads leftover 10 → assertion
  fails. **This test MUST NOT use a fake `determine_mode`** — the entry-reset
  lives in production source; a fake would either duplicate the reset (making
  the test tautological) or omit it (making the test not exercise production).
  Use the real `BatteryStrategy` with fake HA state to drive `evaluate_inclement`
  return values.

**Rev-17 branch-gate scenarios (all → DP declines with
`DP_REASON_EMITTER_NOT_DRAINING`, attr None from entry-reset, never stamped):**
Unchanged from Rev-16 N1/N2/N4-N8; N3 is a drain-branch scenario (T-partial-clamp).

**Rule (framing C): a test NEVER contains its own mutation.**

* **T1 (`:4456`):** scenario 1 sans EVSE hold; assert
  `TransitionInputs.drain_target_soc == 10`. Anchor **C1, C7**.
* **T1b (`:4271` shadow, kill-switch OFF):** assert snapshot
  `inputs.drain_target_soc == 10`. Anchor **C6**.
* **T1c (`:4522`):** assert `_dp_decision_soc == 10`. Anchor **C3**.
* **T1d (`:4540`):** idempotent second-plug rescan. Anchor **C4**.
* **T2 (revert consistency):** post-TRANSITIONED SOC=40, `_dp_decision_soc=10`;
  assert `_revert=False`. Anchor **C5**.
* **T2b (mirror-emitter under EVSE hold):** scenario 1 with hold. Assert 10 not 65.
  Anchor **C11**.
* **T3 (R1 preserved):** unchanged. Anchor **C2**.
* **T4 (R3 preserved, `:3752`):** unchanged. Anchor **C8**.
* **T4b (R3 preserved, `energy_pool.py`):** unchanged. Anchors **C9, C10**.
* **T5 (off-peak drain live-apply):** unchanged. Anchor **C12**.
* **T6 (containment — safety branches survive None):** unchanged shape; explicit
  assertion that INV-DP-DRAIN-1e force-revert executes on TRANSITIONED+threaded=None.
* **T7a (N1 arb HOLD):** attr None; assert decline. Anchor **C13a**.
* **T7b (N2 attain):** attr None; assert decline. Anchor **C13b**.
* **T7c** RETIRED (N3 partial_hold is a drain-branch scenario, T-partial-clamp).
* **T7d (N4 full_hold):** attr None; decline. Anchor **C13d**.
* **T7e (shadow gate — N1):** kill-switch OFF; shadow_reason equality.
  Anchor **C6b**.
* **T7f (N5 WAIT):** attr None; assert decline. Anchor **C13e**.
* **T7g (N6 envoy-blind):** attr None; assert decline. Anchor **C13f**.
* **T7h (N7 attain-reboot-release):** attr None; assert decline. Anchor **C13g**.
* **T-partial-clamp (D-HIGH-1 anchor, load-bearing):** as described.
  Mutation anchor **C-clamp**.
* **T-two-caller-race (D-HIGH-2 anchor):** as described. Mutation anchor **C-race**.
* **T-cross-tick-reset (Rev-17 D2-HIGH-1 anchor, LOAD-BEARING, drives REAL
  determine_mode):** as described. Mutation anchor **C-entry-reset**.
* **T-no-helper (D-HIGH-2 second anchor):** grep-based assertion that
  `_dp_decision_tick`'s body (`:4326-4573`) AND `_run_dp_shadow_eval`'s body
  (`:4195-4324`) contain ZERO calls to `_dp_emitter_in_drain_branch` /
  `_dp_drain_target_soc` (deleted) AND ZERO reads of
  `self._battery._offpeak_drain_branch_target`. Mutation anchor **C-helper**:
  add such a call/read → test fails on grep.
* **T-strand (INV-DP-DRAIN-1e):** tick T stamps value + transitions; tick T+1
  attr None (via entry-reset + non-drain path) + carrier TRANSITIONED + EVSE
  `_paused_by_dp`; assert `_revert=True` fires via the new branch; assert
  `_apply_dp_reversion` called; assert EVSE released. Mutation anchor
  **C-strand**: remove the `if drain_target_soc is None: _revert = True` line →
  assertion fails.
* **T-strand-partial-to-full (Rev-17 — drives REAL determine_mode):** tick T
  under `allow_discharge` stamps 10, DP transitions; tick T+1 inclement
  upgrades to `full_hold`; T+1's determine_mode entry-resets (clears the T-
  stamp) then short-circuits at :4903 without reaching the stamp line;
  captured local is None; carrier TRANSITIONED + `_paused_by_dp` →
  INV-DP-DRAIN-1e forces revert; EVSE released. Mutation anchor
  **C-entry-reset** shared with T-cross-tick-reset (entry-reset removal
  breaks both).
* **T-shadow-wrong-period (if belt-and-suspenders period guard retained):**
  peak-period shadow call; assert `shadow_reason == "wrong_period"` EXACTLY.
  Mutation anchor **C-wrong-period**.
* **T-const-ref (C-LOW-1):** grep-based test asserting no raw
  `"emitter_not_draining"` string outside `energy_drain_precedence.py`'s
  constant definition line.

**Rev-16 §7 "Refinement — mailbox Option A / B" DELETED at Rev-17.** The Rev-16
mailbox refinement (consumer-side read-and-clear) was superseded by the Rev-17
producer entry-reset. T-strand-partial-to-full is now anchored by
C-entry-reset, not C-mailbox.

---

## 8. Review plan — Tier 3

A/B/C/D framings per Tier-3 protocol. **Rev-17 re-review REQUIRED** — the
authoritative reset moves from the consumer (Rev-16 mailbox) to the producer
(entry-reset at `determine_mode:4590`); D2-HIGH-1 must be re-verified DISSOLVED by
construction; sim v6 rebuilt with hand-set `emitted_drain_target` fixture field.
Two plan reviews before build (completeness + adversarial build-prediction).
Orchestrator pre-deploy verification mandatory. Operator checkpoint BEFORE deploy.

**Mutation drills — REAL per-site source mutation, ONE at a time, restore after each.**

- **C1-C10** unchanged from Rev-14/15.
- **C11** unchanged (park-floor swap discriminator).
- **C12** unchanged (T5 setter anchor).
- **C13a/b/d/e/f/g** unchanged (gate-closed decline anchors). C13c RETIRED.
- **C-clamp (D-HIGH-1 anchor, load-bearing):** move the stamp line at
  `energy_battery.py:5322-5323` to BEFORE the partial_hold clamp → T-partial-clamp
  fails (stamped value 10, oracle 50).
- **C-race (D-HIGH-2 anchor, load-bearing):** in `_dp_decision_tick`, replace the
  parameter read with `self._battery._offpeak_drain_branch_target` →
  T-two-caller-race fails (reads 99 not 10).
- **C-helper:** add a call to a helper that reads `_offpeak_drain_branch_target`
  inside `_dp_decision_tick` OR inside `_run_dp_shadow_eval` → T-no-helper fails
  on grep.
- **C-entry-reset (Rev-17 D2-HIGH-1 anchor, LOAD-BEARING):** delete the
  `self._offpeak_drain_branch_target = None` line at `energy_battery.py:4590`
  → T-cross-tick-reset fails (T+1 reads leftover T0 stamp of 10); AND
  T-strand-partial-to-full fails (T+1 reads leftover T stamp of 10 → does not
  decline → force-revert does not fire). Single mutation breaks both tests.
- **C-strand (Rev-15, preserved):** remove the
  `if drain_target_soc is None: _revert = True` line → T-strand fails.
- **C-wrong-period (Rev-15, preserved if belt-and-suspenders guard kept):** remove
  the period guard from shadow → T-shadow-wrong-period fails.
- **C-stamp-site (Rev-16, load-bearing):** remove the
  `self._offpeak_drain_branch_target = int(drain_target)` line at
  `energy_battery.py:5322-5323` → all drain-branch tests (T1, T1b, T1c, T1d, T2,
  T2b, T-partial-clamp) fail — attr never stamps → capture always None → DP
  never transitions.
- **C-capture-order (Rev-16, load-bearing):** move the capture site AFTER the
  `await` at `:5587` → T-two-caller-race fails (attribute may be re-stamped by
  concurrent `_evaluate_battery`).
- **C-init-drift:** delete the init `_offpeak_drain_branch_target: int | None =
  None` at `energy_battery.py:~483` → on a boot tick before any determine_mode
  has stamped, `getattr(..., None)` default kicks in → safe (decline) → no user-
  visible failure. Documented as SAFE-BY-CONSTRUCTION rather than a mutation
  anchor.
- **C-mailbox DELETED at Rev-17** (Rev-16 mailbox pattern removed; C-entry-reset
  replaces its coverage).

All twenty-plus mutations must bite where asserted (C1-C6, C6b, C7-C12, C13a-g
minus C13c, C-clamp, C-race, C-helper, C-entry-reset, C-strand, C-wrong-period,
C-stamp-site, C-capture-order).

Framing hints for reviewers:
* **A** — local correctness of the stamp arithmetic (post-clamp int cast);
  producer entry-reset placement (first executable statement before ANY early
  return); revert-guard None-safety; INV-DP-DRAIN-1e force-revert arithmetic;
  new constant wiring.
* **B** — integration / containment: producer entry-reset covers all early-
  return paths (`full_hold` :4903, arbitrage gate :5236, attain :5253, envoy
  :4705, grid disconnect, etc.); capture-before-await ordering; second-caller
  path leaving DP unaffected across ticks; MUST_START_FORCED + paused-idle +
  shadow paths under threaded-None AND TRANSITIONED+threaded-None; TOU-period
  single-read; optional shadow wrong-period path.
* **C** — REAL per-site source mutation (C1-C13, C-clamp, C-race, C-helper,
  C-entry-reset, C-strand, C-wrong-period, C-stamp-site, C-capture-order);
  harness updates; fake-battery stubs on all three
  (`_StubBattery`/`_SpyBattery`/`_Boom`) INCLUDING the
  `_offpeak_drain_branch_target` attr; direct `_dp_decision_tick(...)` callers
  passing `drain_target_soc=` explicitly. **T-cross-tick-reset must drive REAL
  determine_mode** — verify the harness constructs `BatteryStrategy` proper,
  not a fake.
* **D** — adversarial completeness: falsify INV-DP-DRAIN-1 / 1d / 1e across the
  whole DP surface; re-enumerate emission sites + stamp sites + read sites (there
  MUST be exactly **ONE entry-reset at `energy_battery.py:4590`**, exactly
  **ONE value-write at `:5322-5323`**, exactly **ONE init at `~:483`**,
  exactly **ONE capture at `energy.py:~5579`** — grep-anchored; and exactly
  TWO threaded-parameter reads: `_dp_decision_tick` + `_run_dp_shadow_eval`,
  with the shadow read reached via the forward from `_dp_decision_tick`). Any
  additional writer or any reader of the attribute from inside
  `_dp_decision_tick` OR `_run_dp_shadow_eval` is a load-bearing leak. Any
  early return in `determine_mode` that precedes the entry-reset (there
  shouldn't be any, but verify structurally) is a leak. Legal-config repro
  required for every flagged leak.

---

## 9. REUSE vs NEW

* R1/R3 unchanged (`_ev_battery_drain_soc`).
* `evaluate_dp_transition` gate arithmetic — REUSE.
* `compose_release_floor` / `current_park_floor()` — REUSE for non-DP consumers.
* `current_offpeak_drain_target()` at `energy_battery.py:1726-1747` — REUSE for
  its non-DP consumers; NOT READ by DP at Rev-17.
* `battery.reserve_soc` — NOT READ by DP at Rev-17. Kept for its other consumers.
* `set_offpeak_drain(quality, value)` at `energy.py:8645` — REUSE.
* `battery._arbitrage_active`, `battery._attain_state`,
  `battery._last_inclement_decision` — **NOT READ by Rev-17 DP.**
* `_last_reserve_level_desired` — NOT READ.
* `_dp_drain_target_soc(period)` on `EnergyCoordinator` — **DELETED** (Rev-16).
* `_dp_emitter_in_drain_branch()` on `EnergyCoordinator` — **DELETED** (Rev-16).
* `_offpeak_drain_branch_this_tick: bool` on `BatteryStrategy` — **DELETED**
  (Rev-16).
* `BatteryStrategy._offpeak_drain_branch_target: int | None` — instance attr;
  **~1 LoC init** at `energy_battery.py:~483`; SOLE non-None value-write at
  `:5322-5323` (~1 LoC). **NEW at Rev-17: ~1 LoC producer entry-reset at
  `determine_mode:4590`.**
* Coordinator-side lexical capture in `_decision_cycle_body` — NEW (~10 LoC
  with try/except). **NO read-and-clear write-back at this site (Rev-16
  mailbox removed at Rev-17).**
* `_dp_decision_tick` signature — CHANGE (new keyword param
  `drain_target_soc: int | None = None`).
* `_run_dp_shadow_eval` signature — CHANGE (new keyword param
  `drain_target_soc: int | None = None`).
* `DP_REASON_EMITTER_NOT_DRAINING` in `energy_drain_precedence.py` — NEW
  constant.

Knob ladder (per CLAUDE.md): no new operator knobs.

---

## 10. Closed concerns — must stay closed

Rev-16 items unchanged, plus Rev-17 additions/updates:

* **D-HIGH-1 (partial_hold mirror gap) CLOSED-BY-CONSTRUCTION** — Rev-16 stamp
  at `:5322-5323` after the clamp; DP consumes verbatim. Test T-partial-clamp +
  mutation C-clamp.
* **D-HIGH-2 (in-tick, pre-await, two-caller attribute race across
  `:5587-5588`) CLOSED-BY-CONSTRUCTION** — Rev-16 pre-await lexical capture
  threaded as a parameter. Test T-two-caller-race + mutation C-race.
* **D2-HIGH-1 (Rev-17, cross-tick mailbox leak: the OTHER determine_mode caller
  refills the attribute BETWEEN two `_decision_cycle_body` ticks, so a stale
  value bleeds into a subsequent non-draining tick's capture)
  CLOSED-BY-CONSTRUCTION** — Rev-17 PRODUCER entry-reset at
  `determine_mode:4590` first line. Every determine_mode invocation from every
  caller clears the attribute before any early return; combined with
  determine_mode being fully synchronous, the value the coordinator captures
  is EXACTLY the value THIS call produced. Test T-cross-tick-reset +
  mutation C-entry-reset.
* **D-LOW-1 (Rev-15 boolean under-informative; brittle reset ordering)
  DISSOLVED** — value + producer entry-reset replaces bool + coordinator
  pre-determine_mode reset.
* **Negative-inference gate ambiguity (Rev-14 C-CRIT-1/1b) REMAINS
  CLOSED-BY-CONSTRUCTION** — value stamp set only by the drain-fallback
  branch's post-clamp line.
* **Bug Class #53 (computed-but-not-consumed via missed branches) REMAINS
  CLOSED-BY-CONSTRUCTION.**
* **"No-change-to-energy_battery.py" constraint EXPLICITLY RELAXED (Rev-15+)** —
  ~3 LoC on the battery side (init + entry-reset + stamp).
* **Stranded-carrier release (Rev-14 C-HIGH-2) REMAINS CLOSED** — INV-DP-DRAIN-1e's
  TRANSITIONED+threaded-None force-revert.
* **Shadow wrong-period false-open (Rev-14 C-HIGH-1) REMAINS CLOSED.**
* **Sim tautology (Rev-14 C-HIGH-3 / Rev-17 sim-v6 correction) REMAINS
  CLOSED** — sim v6's `in_drain_branch` + `emitted_drain_target` are BOTH
  independent hand-set fixture fields at Rev-17 (Rev-16's `emitted_drain_target`
  was derived from `emitter_drain_floor(s)`, making C6≡ORACLE-A a value-axis
  tautology; Rev-17 breaks the derivation).
* **Raw-string reason code (Rev-14 C-LOW-1) REMAINS CLOSED.**
* **All Rev-14 closed items remain closed.**

---

## 11. R1 knob live-vs-default note — unchanged from Rev-11.

---

## 12. Cycle-close checklist

* [ ] Two plan reviews (Tier 3): completeness + adversarial build-prediction.
      **Rev-17 re-review REQUIRED** — producer-entry-reset design; sim v6 rebuilt
      with hand-set `emitted_drain_target`; D2-HIGH-1 resolution verified against
      source.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean (harness updates: name-list unchanged
      since Rev-16 + `_offpeak_drain_branch_target` attr stub on all three fake
      batteries + explicit `drain_target_soc=` on direct `_dp_decision_tick`
      callers + T-cross-tick-reset drives REAL determine_mode).
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy: re-grep every `drain_target_soc =`, every
      `_ev_battery_drain_soc` read, every `_offpeak_drain_branch_target` write —
      **exactly TWO writes** (entry-reset at `energy_battery.py:4590`,
      value-stamp at `energy_battery.py:5322-5323`) plus init at `~:483`; every
      `_offpeak_drain_branch_target` read — **exactly ONE** (the capture at
      `energy.py:~5579`); every threaded-parameter site inside
      `_dp_decision_tick` and `_run_dp_shadow_eval` (parameter only, no
      attribute look-up). Run source-mutation drills C1-C13g (minus C13c) +
      C-clamp + C-race + C-helper + C-entry-reset + C-strand + C-wrong-period +
      C-stamp-site + C-capture-order.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation per §3b.
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` → shipped_organic.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md.
* [ ] Card `DOCS-DRAIN-DRIFT-1` created for the stale
      `_get_off_peak_decision` docstring reference at
      `energy_battery.py:1730` (if not already carded).

---

## 13. Rev-17 fix-up log — Rev-16 D-pass findings → resolution

| Finding | Severity | Rev-17 disposition |
|---|---|---|
| **D2-HIGH-1 (Rev-16 mailbox cross-tick leak — the consumer-side read-and-clear at the coordinator capture cleared the attribute only on the `_decision_cycle_body` path; the OTHER `determine_mode` caller (`_evaluate_battery` at `energy.py:6185`) could REFILL the attribute BETWEEN two `_decision_cycle_body` ticks, so a stale value could bleed into a subsequent non-draining tick's capture. Legal-config repro: `_evaluate_battery` runs at a TOU edge, drain branch stamps 10; next `_decision_cycle_body` tick returns via `full_hold` short-circuit at `:4903` (drain branch never runs), capture reads leftover 10 → DP acts on a tick where the emitter did not emit.)** | HIGH | **CLOSED-BY-CONSTRUCTION.** Rev-17 moves the authoritative reset to the PRODUCER entry — first executable statement of `determine_mode` at `energy_battery.py:4590`, before ANY early return. Combined with `determine_mode` being fully synchronous (verified this session: zero `await` between `:4590` and `:5352`), every determine_mode invocation from every caller entry-resets first and then either stamps (if the drain branch reaches `:5322-5323`) or does not — either way, the NEXT tick's determine_mode call will entry-reset before any code runs. The Rev-16 consumer-side read-and-clear mailbox is REMOVED. Test T-cross-tick-reset (drives REAL determine_mode; the entry-reset lives in production source and can only be exercised by real code, not a fake) + mutation C-entry-reset anchor. Shared coverage with T-strand-partial-to-full (also broken by C-entry-reset). |
| **D-HIGH-1 (Rev-15 partial_hold mirror gap)** | HIGH | **REMAINS CLOSED-BY-CONSTRUCTION** — Rev-16 stamp at `:5322-5323` after the clamp. |
| **D-HIGH-2 (Rev-15 in-tick, pre-await, two-caller attribute race across `:5587-5588`)** | HIGH | **REMAINS CLOSED-BY-CONSTRUCTION** — Rev-16 pre-await lexical capture threaded as a parameter. |
| **D-LOW-1 (Rev-15 boolean under-informative + brittle reset ordering)** | LOW | **REMAINS DISSOLVED.** |
| **Sim value-axis tautology (Rev-16 v5: `emitted_drain_target` derived from `emitter_drain_floor(s)` — the same function ORACLE-A uses)** | INFO/GAP | **CLOSED at Rev-17 sim v6.** `emitted_drain_target` is now an INDEPENDENT hand-set fixture field per scenario; C6's value-axis score is real evidence. |
| **Scorecard A/B labels swapped in Rev-16 narrative (C2 A=3/B=2 wrong; C3 A=2/B=3 wrong; C6 A=11/B=12 wrong)** | INFO | **CORRECTED at Rev-17**: C2 A=4/B=3, C3 A=3/B=4, C5 A=10/B=11, C6 A=12/B=11. C6 is 12/12 under ORACLE-A (strict emitter mirror, since Rev-17 hand-sets `emitted_drain_target` to the emitter's actual expected emitted value per fixture); D4 divergence sits under ORACLE-B (RULED max), live NO-OP. Narrative in §3a unswapped. |
| **Rev-16 test-anchor citation drift (`:5573` insertion point vs actual multi-line call closing at `:5578`)** | INFO/LOW | **CORRECTED at Rev-17**: capture insertion at approximately `:5579` (immediately after the multi-line determine_mode call closes at `:5578`). All `:5573`→`:5579` references updated in §2 and §3. |
| **Rev-16 T-no-helper grep scope missed `_run_dp_shadow_eval`** | LOW | **EXTENDED at Rev-17**: T-no-helper asserts ZERO forbidden calls/reads in BOTH `_dp_decision_tick:4326-4573` AND `_run_dp_shadow_eval:4195-4324`. Mutation anchor C-helper covers both. |
| **Rev-16 stale `_get_off_peak_decision` docstring inside `current_offpeak_drain_target()` at `energy_battery.py:1730`** | LOW / DOCS | **CARDED as `DOCS-DRAIN-DRIFT-1`** — not fixed in this cycle (unchanged from Rev-16 disposition; card creation at cycle-close). |
| **Rev-16 stamp/reserve_level wording** | INFO | **CORRECTED at Rev-17**: §1 reserve-level note clarifies the stamped `drain_target` equals emitted `reserve_level` ONLY on the `:5326` (above-target) return; the `:5344` (at/below-target) return emits `reserve_level=hold_reserve` (int(soc) clamped up to effective_reserve under partial_hold). Stamping `drain_target` is correct for DP (SOC-threshold), just not `reserve_level`-equal on both paths. |
| **C-CRIT-1 / C-CRIT-1b (Rev-14)** | CRITICAL | **REMAINS CLOSED-BY-CONSTRUCTION.** |
| **C-HIGH-1 (Rev-15 shadow wrong-period)** | HIGH | **REMAINS FIXED.** |
| **C-HIGH-2 (Rev-14 stranded-carrier)** | HIGH | **REMAINS FIXED.** |
| **C-HIGH-3 (Rev-14 sim tautology — accessor)** | HIGH | **REMAINS FIXED.** |
| **C-LOW-1 (raw string reason code)** | LOW | **REMAINS FIXED.** |
| D-CRIT-1 / D-CRIT-2 (Rev-13 findings) | CRITICAL | **REMAINS FIXED.** |
| A-CRIT-1 / A-CRIT-2 (Rev-12 findings) | CRITICAL | **PRESERVED-fixed.** |
| B-HIGH-1 / D-HIGH-1 [Rev-14 label] (safety-branch starvation) | HIGH | **PRESERVED-fixed;** EXTENDED with INV-DP-DRAIN-1e force-revert. |
| B-HIGH-2 / B-HIGH-3 | HIGH | **REMAIN DISSOLVED.** |
| B-MED-1 / A-LOW-1 / D-MED-1 (stale TOU period) | MEDIUM | **PRESERVED-fixed.** |
| Shadow-site containment | HIGH | **PRESERVED-fixed** (threaded-None publishes distinct `shadow_reason`; do not raise). |
| D-MED-2 (live acceptance) | MEDIUM | **PRESERVED-fixed.** |
| B-LOW-1 / C-C11 (INV-DP-DRAIN-4) | LOW / GAP | **PRESERVED-fixed.** |
| C-CRITICAL (extract-exec harnesses) | CRITICAL | **PRESERVED at Rev-17.** `_offpeak_drain_branch_target` on all three fake batteries; direct `_dp_decision_tick` callers gain explicit `drain_target_soc=`. T-cross-tick-reset drives REAL determine_mode (mandatory — the entry-reset lives in production source). |
| CRIT-2 revert-guard framing (both None checks) | CRITICAL | **PRESERVED-fixed.** |
| Fixture-contract leak | HIGH | **PRESERVED-fixed.** |
| Sim traceability | INFO | **UPDATED at v6** (independent `in_drain_branch` + `emitted_drain_target` + `effective_reserve`; C5 kept, C6 stays; N3 corrected at Rev-16; oracles apply partial_hold clamp). |
| Line-drift on `_apply_dp_transition` | INFO | **PRESERVED-fixed.** |
| `period` re-read / shadow at `:4416` | MEDIUM | **PRESERVED-fixed.** |
| `very_poor` validator | HIGH (round-3 card) | **DOCUMENTED + CARDED** (`VERY-POOR-DRAIN-LIVE-UPDATE-1`). |
| **`_get_off_peak_decision` terminology drift (Rev-11..Rev-15 self-inflicted)** | POLICY | **CORRECTED throughout at Rev-16; preserved at Rev-17.** |
| No-change-to-`energy_battery.py` constraint (Rev-13/14 self-imposed) | POLICY | **REMAINS EXPLICITLY RELAXED** (~3 LoC at Rev-17: init + entry-reset + stamp). |

**Parked (would only be un-parked if post-ship data supports it):**
- **Partial_hold-clamped DP variant** — DISSOLVED at Rev-16; Rev-17 preserves.
- **Passing a decision-tick sequence counter through `determine_mode`** —
  DISSOLVED; the threaded local + producer entry-reset is a strictly simpler
  solution to the same problem.
- **Consumer-side read-and-clear mailbox (Rev-16 refinement)** — REPLACED at
  Rev-17 by producer entry-reset. Would only be revisited if a future change
  moved determine_mode's body to contain awaits (which would break the
  synchronous-body assumption); no current plan does so.

**Findings that no longer apply** (Rev-12/Rev-13-specific): unchanged from
Rev-14/15/16.
