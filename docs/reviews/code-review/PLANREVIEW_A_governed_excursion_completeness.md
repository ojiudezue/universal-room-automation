# PLAN REVIEW A — Completeness
**Target:** `docs/planning/PLANNING_hvac_governed_excursion.md` (D2 primitive + D3 migration)
**Card:** `HVAC-GOVERNED-EXCURSION-1` (`docs/planning/kanban.data.yaml:2430`)
**Framing:** independent re-enumeration of every surface the plan claims to cover; find what it MISSED.
**Mode:** read-only. No code or plan edits made. No test suite run.

## VERDICT: **FIX-THEN-BUILD**

Blocking items: **A-CRIT-1**, **A-CRIT-2**, **A-HIGH-1**, **A-HIGH-2**, **A-HIGH-3**.
The primitive's design is sound and the invariant in §1 is genuinely falsifiable. What is wrong is the
**scope table** (§3 / §5): three of the four UNVERIFIED sites resolve to answers that *change the
migration*, one of them by re-opening a documented deliberate trade.

Findings: **2 CRITICAL / 4 HIGH / 8 MEDIUM / 3 LOW**

---

## 1. My independent site count

Method: `grep -rn --include="*.py" -e emit_set_temperature -e emit_set_preset_mode` across
`custom_components/universal_room_automation/`, comment lines discarded by reading each hit; then a
separate hunt for raw service literals (`"set_temperature"` / `"set_preset_mode"` / `"set_hvac_mode"`,
`SERVICE_SET_*`) and for the `"climate"` domain literal.

### 1.1 `emit_set_temperature` call sites — 10

| # | File:line | Site | My classification | Return path | Preset asserted on return? |
|---|---|---|---|---|---|
| 1 | `hvac.py:2274` | S10 DPM apply | governed apply — NOT an excursion | n/a | n/a |
| 2 | `hvac.py:2974` | S14 duty off-phase | **deliberate no-return ceiling** | none **by design** | n/a — preset deliberately unchanged |
| 3 | `hvac_override.py:2430` | S3 compromise | excursion START | S4 (`:2554`) | **YES** (S4 is a preset write) |
| 4 | `hvac_override.py:3122` | S5 nudge | excursion START | `:3223` + `:3258` | **PARTIAL** — conditional, see A-HIGH-4 |
| 5 | `hvac_override.py:3223` | nudge restore (setpoint) | excursion RETURN | — | setpoint leg only |
| 6 | `hvac_override.py:3891` | S8 cancel restore | excursion RETURN | — | **NO** |
| 7 | `hvac_override.py:4170` | S9 startup-audit restore | excursion RETURN | — | **NO** |
| 8 | `hvac_predict.py:957` | S11 | **excursion RETURN (banking RELEASE)** — plan says START | — | **NO** |
| 9 | `hvac_predict.py:1047` | S12 pre-cool | excursion START | S11, gate-flip only | **NO** |
| 10 | `hvac_predict.py:1286` | S13 pre-heat | excursion START | **NONE AT ALL** | **NO** |

### 1.2 `emit_set_preset_mode` call sites — 4

| # | File:line | Site | Classification |
|---|---|---|---|
| 1 | `hvac.py:1981` | S1 reason-ladder | governed apply — NOT an excursion |
| 2 | `hvac_override.py:2554` | S4 compromise revert | excursion RETURN |
| 3 | `hvac_override.py:3258` | nudge restore (preset) | excursion RETURN — **conditional** (`if _cur_preset == "manual"`, `hvac_override.py:3252`; and `pre_preset` popped at `:3240` may be empty) |
| 4 | `hvac_egress.py:664` | egress resume | excursion RETURN — **conditional** (`if saved_preset:`, `hvac_egress.py:655`) |

### 1.3 Bypass audit — the planner's ZERO-bypass claim is **CONFIRMED**

Raw `hass.services.async_call("climate", "set_temperature"|"set_preset_mode", …)` outside the
chokepoint: **zero**. The only matches for those service literals are
`hvac_setpoint.py:175` and `hvac_setpoint.py:217` (the chokepoint itself),
`coordinator.py:1036` (the `_CLIMATE_BLOCKED_SERVICES` set literal — a guard, not a call), and
`hvac_fans.py:2020` (`fan.set_preset_mode`, different domain). Verified against the `"climate"`
domain-literal grep as a second pass. **No bypass site exists — the primitive's guarantee is not
leaked at the source level for the setpoint/preset axes.**

### 1.4 Where I land vs both prior counts

- **Orchestrator's 13 setpoint sites / 9 without preset restore: REFUTED on both numbers.**
  There are 10 `emit_set_temperature` call sites, not 13. Counting return legs that assert no preset,
  I get **6 hard gaps** (S8 `:3891`, S9 `:4170`, S11 `:957`, S12's absent own-return, S13's absent
  return entirely, hard-reset `_restore_after_reset`) **plus 1 partial** (the conditional nudge preset
  at `:3258`) — **not 9**. Neither 13 nor 9 reproduces.
- **Planner's 14 (10 setpoint + 4 preset): CONFIRMED as a textual count.** I independently reach the
  same 14 call sites, same files, same lines.
- **But 14 is not the in-scope excursion surface.** `hvac_egress.py:571` (`set_hvac_mode` → `off`) is
  an excursion *begin* that touches no chokepoint at all; the plan migrates it (§5 row #12) yet omits
  it from the §3 enumeration. The correct in-scope surface is **15 sites**, and the correct
  *classification* differs from the plan at S11 (return, not start), S13 (no return, not "TBD"),
  and S14 (must not be migrated at all). **So the number that matters is 15 sites with 3
  reclassifications, not 14 sites with 4 TBDs.**

---

## 2. The U1 / U2 answer (the plan's largest hole) — RESOLVED

I read all four bodies end-to-end. **All four are different from what the plan assumed, and three
change the migration.**

- **S11 (`hvac_predict.py:957`, inside `_release_banked_zones`, def at `:900`) — this is the banking
  RETURN, not a start.** Its docstring is explicit: *"Release previously-banked zones by writing
  baseline setpoints back … undoing the -3°F banking offset."* It resolves a true baseline via
  `_resolve_baseline_range` (`:842`) and is invoked from three places: master-gate flip-OFF
  (`:466`), post-restart orphan reconciliation (`:536`), and pre-cool gate flip-OFF (`:545`).
- **S12 (`hvac_predict.py:1047`, `_execute_zone_pre_cool` def `:1006`) — a real excursion START with a
  real, already-working return** (S11), plus a bounded post-restart reconciler. Not "TBD".
- **S13 (`hvac_predict.py:1286`, `_execute_pre_heat` def `:1253`) — an excursion START with NO
  return path whatsoever.** See A-CRIT-2.
- **S14 (`hvac.py:2974`, `_apply_duty_off_phase` def `:2850`) — a DELIBERATE indefinite hold, no
  return by design, documented and acceptance-tested.** See A-CRIT-1.

**Answer to the brief's question:** they are *not* a homogeneous "four unverified sites". One is a
return (S11), one is a healthy start (S12), one is a genuine unreturned excursion that belongs in the
cycle (S13), and one is a deliberate indefinite hold that must be dropped from scope (S14). The
plan's §5 rows #8–#11 — which treat all four identically as "no-op wraps" — are wrong on all four.

---

## 3. Findings

### A-CRIT-1 — Migrating S14 silently undoes HVAC-PRESET-FLAP-1's documented deliberate trade
**Bug class:** re-opening a settled decision / regression of a shipped acceptance test.
**Evidence:** `docs/planning/PLANNING_preset_flap_offphase_honesty.md:184-195` records the trade
verbatim — *"by design, once the S14 helper writes the `home + OFFSET` ceiling and later
`runtime_exceeded` clears, URA … the ceiling holds at `home + OFFSET` until the next preset
transition"* — and names the shipped test `test_ceiling_held_until_next_preset_transition`, plus a
Live acceptance criterion at `:280` that asserts **NO** follow-on restore write fires.
S14 also deliberately leaves the preset alone (`hvac.py:1740-1745`: *"DO NOT set
effective_preset = 'away'"*), so the §1 invariant ("preset equals intended preset") is **already
satisfied** at S14 — there is nothing for the primitive to guarantee.
The plan's §5 row #11 proposes exactly the undo: *"If self-returning apply: wrap as begin+immediate-
return each tick … If long-lived excursion: schedule return via token."* The second branch reverts the
trade; the first branch writes a DB row per tick per zone for a state that by definition has no return.
**This is the parked-plan trigger the brief asked about, and it FIRED.** The plan does not mention
HVAC-PRESET-FLAP-1 anywhere.
**Required fix:** drop S14 from D3 entirely; add it to §9 non-goals with the citation above and a
one-line statement that S14 is a *governed terminal state*, not an excursion. If the operator wants
the ceiling to self-release, that is a separate card that re-litigates PRESET-FLAP-1.

### A-CRIT-2 — S13 pre-heat is an unreturned excursion, and the DPM throttle actively prevents recovery
**Bug class:** #53 computed-but-not-consumed / stranded excursion + suppression-without-discharge.
**Evidence chain (all four links verified):**
1. `_execute_pre_heat` (`hvac_predict.py:1253-1308`) writes `target_temp_low + 2` via
   `emit_set_temperature` at `:1286`.
2. It **never** adds its zones to a tracking set. `_pre_conditioning_zones.add(...)` occurs only at
   `hvac_predict.py:589` (pre-cool) and `:641` (pre-arrival) — never inside `_execute_pre_heat`.
   `_last_pre_conditioning_zones` is snapshotted from that set at `:673`.
3. The only "end" for pre-heat is a **flag flip with no wire write**:
   `hvac_predict.py:663-666` — `if self._pre_heat_active and hour >= OFF_PEAK_END_HOUR:
   self._pre_heat_active = False` + a log line. No `_release_banked_zones` call.
   The one release that *can* reach pre-heat (`:466`) fires only on a master-gate flip-OFF and takes
   `release_set = _last_pre_conditioning_zones | _last_precool_zones` — **neither contains the
   pre-heated zone** (link 2).
4. **The DPM throttle blocks passive recovery.** `hvac.py:2252-2255`:
   `last = self._last_emitted_range.get(zone_id); if last == resolved_pair: continue`.
   S13 does not update `_last_emitted_range`, so DPM believes the zone is already at its preset range
   and skips the emit. The +2 °F heat floor persists until the *resolved pair itself* changes
   (a preset/house-state flip), not until the pre-heat window ends.
5. The post-restart orphan reconciler is **cool-direction-only**: `hvac_predict.py:531` tests
   `if cur_high < base_high - 0.5` — a pre-heat orphan (raised `low`) is invisible to it.
**Concrete legal-config repro:** winter season, occupied zone, outdoor ≤ `_preheat_forecast_low`,
hour inside `[OFF_PEAK_END_HOUR - PREHEAT_LEAD_HOURS, OFF_PEAK_END_HOUR)`. S13 fires and raises heat
low by 2 °F. At `OFF_PEAK_END_HOUR` the flag clears with no write. DPM skips. The zone heats to the
elevated floor through the on-peak morning — the exact cost failure this cycle exists to prevent.
**Consequence for the plan:** §5 rows #8–#10 say the banking sites "may be self-returning applies"
and propose a "no-op wrap". S13 is not self-returning and a no-op wrap would ship the defect
untouched behind a green telemetry surface. S13 is the **strongest justification for this cycle** and
the plan currently under-scopes it to nothing.
**Required fix:** promote S13 to a first-class excursion with a real `duration_s` (the pre-heat
window) and a real `return_excursion` at `OFF_PEAK_END_HOUR`; state explicitly that the return must
also update `_last_emitted_range` (or route through a path that does) or the DPM throttle re-strands
it. Add a discriminating acceptance criterion at the pre-heat boundary.

### A-HIGH-1 — S11 is misclassified as a START; §5 rows #8–#10 are built on that error
**Bug class:** enumeration misclassification.
`hvac_predict.py:900` docstring + `:957` `site="S11_release_banked"`, `reason="banking_release"`.
Wrapping a *return* in `begin_excursion` would create a permanently-open excursion row for a zone that
just came home to baseline — inverting the invariant. §3.1 row 7 ("banking / pre-cool (start)") and
§5 row #8 must be rewritten: S11 **is** the existing return for S12, and the migration for the
banking kind is "S12 → `begin_excursion`; S11 → `return_excursion`", one pair, not three wraps.

### A-HIGH-2 — Egress `_engage_pause` writes the wire BEFORE persisting — the inverse of the nudge's R1 ordering
**Bug class:** persist-after-actuate / restart-strand.
`hvac_egress.py:570-575` issues `climate.set_hvac_mode → "off"` (`blocking=True`); the snapshot dict
is stored at `:581-588` and `_db_save_paused_full(...)` is awaited only at `:592`. Compare the nudge,
which the plan itself cites as the correct shape: `hvac_override.py:3072` — *"CRITICAL ORDER (R1):
DB first, setpoint second."*
**Repro:** HA restart (or coordinator teardown) in the window between the awaited `set_hvac_mode` and
the awaited DB write leaves the thermostat **off** with no persisted pause row and no reconciler that
knows to resume it. This is falsification obligation #1 in the plan's own §1 — and it exists **today**,
in pre-existing code the plan does not read.
The plan's §5 row #12 would incidentally fix it (mode-off moves inside `begin_excursion`, which
persists first) — but the plan never names the defect, so the fix is accidental, untested, and
**contradicts AC7's "byte-identical on the no-op path"** claim for the egress kind. Name it, test it,
and correct AC7 to exempt egress with a stated rationale.

### A-HIGH-3 — Two pre-existing persistence/reconciliation surfaces are missing from the inventory; the new startup audit will collide with one
**Bug class:** duplicate source of truth / double-actuation on boot.
The plan's §2.2 REUSED table and §4.2.6 name exactly one restart surface (`ac_reset_state.in_flight_nudge_*`
+ `async_startup_ramp_audit`). Two more exist:
1. **Egress pause persistence** — `_db_save_paused_full(...)` at `hvac_egress.py:592`, storing
   `saved_mode` / `saved_preset` / `paused_at` / `thermostat`. This is a *third* in-flight-excursion
   table. `hvac_excursion_state` would duplicate it for `kind="egress_pause"` with no stated
   authority rule, creating exactly the dual-source-of-truth the plan's §9.7 avoids for the nudge.
2. **A second post-restart reconciler** — `hvac_predict.py:508-536`, the `_first_eval_done` one-shot
   orphan scan that releases banked zones by comparing live setpoints against baseline. It is
   *inference-based* (no persisted rows), it is bounded to once per process, and it calls
   `_release_banked_zones` (S11). If banking is migrated and `async_startup_excursion_audit()` also
   restores banking rows, **both** will fire on the same boot and the zone gets two baseline writes —
   at best redundant, at worst racing the DPM tick.
**Required fix:** add both to §2.2; state the authority rule per kind (which table wins); and state
explicitly whether `_first_eval_done` is deleted, subsumed, or left alone with the generic audit
filtered to exclude `kind="banking"`.

### A-HIGH-4 — The nudge preset restore is CONDITIONAL; the plan treats it as an unconditional return leg
**Bug class:** unpriced behavior change / write-volume change.
`hvac_override.py:3240` pops `pre_preset` (empty → no write at all — the self-disarm the plan
correctly identifies), and `:3252` gates the write on `if _cur_preset == "manual"`. So today the
preset leg fires only when the observed preset already flipped to manual.
The primitive's §4.2.4 makes the preset write **unconditional and awaited on every return**. That is
the right call for the invariant, but it is a behavior change the plan never prices:
(a) every nudge return now emits an extra `climate.set_preset_mode` to the wire — with ~60–86
nudges/day/zone × 5 zones (the plan's own §10 figure) that is ~430 additional wire writes/day, each
opening a `kind="preset"` suppression window; (b) `blocking=True` on a cloud thermostat serialises
two round-trips per return where today it is one non-blocking; (c) the `:3252` conditional also
protects against re-asserting a preset the operator legitimately changed mid-nudge — the primitive
must state how `intended_preset` composes with the arrester's comfort-delay grace on the **return**
leg, which §4.2.4 does not.
**Required fix:** §4.2.4 states the write-amplification, the blocking-latency budget, and the
return-leg gate policy explicitly.

### A-MED-1 — Raw `set_hvac_mode` count is 7, not 8
`hvac.py:1486`; `hvac_override.py:2537, 2780, 2847, 2882`; `hvac_egress.py:572, 644`. The plan's §9.2
counts "coordinator.py 1", but `coordinator.py:1036` is the `_CLIMATE_BLOCKED_SERVICES` set literal
(a guard), not a call site. Cosmetic for scope, but it is a non-goal the reviewers will re-check.

### A-MED-2 — §3 is not the authority §5 claims it is
`hvac_egress.py:571` (the mode-off that *is* the egress excursion's begin) appears in §5 row #12 but
in neither §3.1 nor §3.2. The plan says "§5 … is authoritative and enumerates every one of the 14" —
§5 actually has 15 rows. Reconcile the two tables to one number before dispatch, or the builder
inherits an ambiguity.

### A-MED-3 — Citation drift in §2.2
`OverrideArrester.comfort_delay_active` is cited as `hvac_override.py:292-306`; the actual definition
is `hvac_override.py:1498`. Lines 292-306 are the `_immune_holds` / Temp-Arrester-Override block.
Spot-check of the other ten §2.2 citations: `hvac_setpoint.py:48/121/180` ✓;
`hvac_override.py:2430` ✓; `:2554` ✓; `:3122` ✓; `:3223` ✓; `:3258` ✓; `:3891` ✓; `:4170` ✓;
`hvac.py:1981` ✓; `hvac.py:2274` ✓; `hvac.py:2974` ✓; `database.py:1439` ✓ (`in_flight_nudge_original_target`);
`hvac_override.py:2860` ✓ (`_verify_restore`); `hvac_override.py:3072-3079` ✓ (R1 ordering);
`coordinator.py:1018-1050` ✓; `hvac_predict.py:957/1047/1286` ✓; kanban card cited as
`kanban.data.yaml:2296-2435` — actual id anchor is `:2430` (drifted, card still resolves).
**One wrong of thirteen spot-checked; one drifted.**

### A-MED-4 — Kill switch is described with the wrong persistence machinery
§7 says the `excursion_primitive_enabled` Switch is *"Persisted per the Number-persistence
machinery."* It is a Switch, not a Number. The correct in-repo exemplar is the sibling off-phase
kill switch: `switch.py:5993-6083` (property read at `:5993`, setter writes at `:6001/:6024/:6067`,
restore applied via `_deferred_value` at `:6083`), backed by
`hvac.py:317-319` (constructor seed from the passed kwarg) and the property pair at `hvac.py:617-625`.
**This directly intersects HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1**: the off-phase switch *does* seed its
runtime field from a constructor kwarg at `hvac.py:317`, which is exactly the seeding the 14 Numbers
lack. The plan must name `hvac.py:317-319` + `switch.py:6083` as the pattern to copy, and add an
explicit acceptance criterion that the kill switch's runtime field equals the persisted value after a
restart. The plan adds no Number, so it does not otherwise inherit the sibling defect — but "Number-
persistence machinery" in the text is precisely the wrong pointer to hand a builder.

### A-MED-5 — Adjudicating §11.2 (dual-write): take the single-table option
The plan's own concern is correct and the cheaper option is the right one. `ac_ramp_events` already
carries the full D1 shape (`database.py:1519-1524` DDL; `:1633-1638` migration list; `:7419-7444`
the writer signature). Dual-writing `hvac_excursion_events` for `kind='nudge'` produces two rows per
return for one kind and puts AC1 and AC2 on different tables with no join guarantee.
**Recommendation: add a nullable `excursion_id` column to `ac_ramp_events`, write nudge outcomes only
there, and write the other kinds only to `hvac_excursion_events`.** One row per return, always;
cross-kind analytics union on `excursion_id`. This also keeps AC8's ±25 % comparison meaningful.

### A-MED-6 — Adjudicating §11.1 (hard-reset preset assert): DROP it from this cycle
The planner's instinct is right and the marginal-benefit decomposition supports it. The hard reset has
its own lifecycle (`_restore_after_reset` `hvac_override.py:2813` → `_verify_restore` `:2860` with a
2-retry/30 s ladder). Composing two lifecycle machineries for a one-line preset assertion is
marginal-benefit-negative. The mode-axis exclusion (§9.2) already argues the reset is healthy —
`11 hard_reset_started` / `11 hard_reset_completed`, zero orphans. **Drop §5 row #15; open it as its
own card.** This also shrinks the cycle by one lifecycle interaction, which matters at Tier 3.

### A-MED-7 — Mode exclusion is safe for 6 of 7 sites but NOT clean for egress
The brief asks whether excluding mode leaves a gap. My enumeration says: for nudge, compromise,
banking, pre-heat, off-phase, and hard-reset — **yes, safe**: those excursions move setpoint and/or
preset only; mode is untouched, so there is no split-governance seam.
**Egress is the exception.** `_engage_pause` moves *mode* (`hvac_egress.py:571`, mode→off) and
`_engage_resume` restores *mode* (`:643`) **and then** preset (`:664`) — one logical excursion whose
two axes would, after migration, be governed by two mechanisms with a window between them. Worse,
`:648-651` — the resume's mode-restore `except:` block **`return`s** — so a failed mode restore
skips the preset restore entirely, leaving the zone off *and* mis-preset with no telemetry row.
The plan's §5 row #12 hand-waves this ("Mode-off itself remains a raw `set_hvac_mode` call inside
`begin_excursion` for THIS kind only"). That is defensible, but the plan must state the **ordering
contract and the failure contract** for the egress return: what happens to the preset leg and to the
`restore_ok` row when the mode leg raises. Today the answer is "nothing is written" — a leak.

### A-MED-8 — AC9 is a tautology and ignores the documented open route
AC9 asserts the bypass grep "returns only `hvac_setpoint.py` matches, unchanged from today." That is
true before the cycle and cannot fail because of the cycle — it discriminates nothing (violating the
plan's own §8 discriminator rule). Separately, `coordinator.py:1024-1035` documents in-source that
chained routes (`automation.trigger`, `scene.turn_on`, `script.turn_on`, `homeassistant.turn_on`)
**remain open** past the guard. The plan's §3.3 states bypass risk is "eliminated at the source-level"
without carrying that honesty note forward. Restate AC9 as a *regression* check on the migrated sites
(each migrated site emits via the primitive, proven by mutation per AC5), and add the chained-route
caveat to §3.3.

### A-LOW-1 — U3 confirmed
`async def async_startup_ramp_audit` is at `hvac_override.py:4057`. The AUDIT's 3925 is stale. The
plan already flags this; recording the verified number so the builder does not re-derive it.

### A-LOW-2 — An interacting pre-existing defect is unreferenced
`hvac_predict.py:858-866` documents, in-source, that banking **ratchets** toward `SOLAR_BANK_FLOOR`
across cycles because `_execute_zone_pre_cool` reads the already-banked `zone.target_temp_high` and
subtracts another offset each cycle ("Flag for backlog"). Migrating banking into a primitive that
snapshots `pre_target_low/high` at `begin()` will interact with this: on the second and later cycles
the snapshot captures a *banked* value as the "pre" state. Either the primitive must snapshot from
`_last_emitted_range` (as `_resolve_baseline_range` `:842` already does) or the ratchet must be fixed
first. State which.

### A-LOW-3 — AC8's ±25 % baseline is not yet establishable
AC8 asks for a 24 h pre-deploy vs post-deploy non-NULL-rate comparison on the D1 columns. D1 shipped
in v5.86.0; if fewer than 24 h of populated rows exist at build time the comparison has no baseline.
Add "capture the pre-deploy snapshot **before** the build branch merges, and if <24 h of D1 data
exists, state that AC8 degrades to a shape check (columns non-NULL) rather than a rate check."

---

## 4. Scope-exclusion audit (brief item 3) — conclusion

The mode exclusion is **safe as argued** for nudge / compromise / banking / pre-heat / off-phase /
hard-reset: none of those excursions moves mode, so no split-governance seam exists. The
`11 started / 11 completed / zero orphans` evidence plus D1's `mode_before/mode_after` tripwire is
adequate cover for the hard-reset path.
**Egress is the single exception and needs the explicit contract in A-MED-7.** It is the only
excursion in the enumeration whose *action* is a mode change.

## 5. D1 reuse (brief item 4) — the plan is directionally right, with one correction

The plan does treat D1 as an input and does propose populating the shipped columns rather than
inventing a parallel surface — correct. Verified shipped: `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12`
(`hvac_const.py:571`, consumed at `hvac_override.py:3390`), the `ac_ramp_events` columns
(`database.py:1519-1524`, `:1633-1638`, writer `:7419-7444`), and the D1 snapshot block
(`hvac_override.py:3091-3096`, explicitly labelled `HVAC-GOVERNED-EXCURSION-1 D1`).
The one correction is A-MED-5: the proposed **dual-write for `kind='nudge'` does** create the parallel
surface the plan says it wants to avoid. Take the `excursion_id`-column option.

## 6. Restart-safety exemplar (brief item 5) — the plan does NOT regress it

§9.6 explicitly non-goals rewriting `async_startup_ramp_audit` and instructs reviewers proposing
changes to its persistence / elapsed arithmetic / two-guard block to be redirected. §4.2.6 says
"generalises", §5 row #7 makes it "a thin adapter". That is generalisation, not replacement, and it
correctly cites the audit's refutation. **No regression.** The only gap is A-HIGH-3: it is not the
*only* reconciler, and the second one (`hvac_predict.py:508-536`) is the collision risk.

---

## 7. Required before build dispatch

1. **Drop S14 from D3**; move to §9 non-goals citing `PLANNING_preset_flap_offphase_honesty.md:184-195, :280`. (A-CRIT-1)
2. **Promote S13 to a first-class excursion** with a real return at `OFF_PEAK_END_HOUR` and an explicit `_last_emitted_range` requirement. (A-CRIT-2)
3. **Rewrite §3.1/§5 rows #8–#10**: S11 is the return, S12 is the start, one pair. (A-HIGH-1)
4. **Name the egress persist-after-actuate defect**, state the ordering fix, and exempt egress from AC7's byte-identical claim. (A-HIGH-2)
5. **Inventory the egress pause table and the `_first_eval_done` reconciler**; state the per-kind authority rule and whether the generic audit excludes banking. (A-HIGH-3)
6. Price the unconditional-preset-write change and state the return-leg gate policy. (A-HIGH-4)
7. Adjudicate §11.1 as DROP and §11.2 as single-table. (A-MED-5, A-MED-6)
8. Fix the kill-switch persistence pointer to `switch.py:5993-6083` + `hvac.py:317-319`, and add a restart-seeding acceptance criterion. (A-MED-4)
9. Reconcile §3 and §5 to one site count; fix the `comfort_delay_active` citation; restate AC9. (A-MED-2, A-MED-3, A-MED-8)

Reviewer A, completeness framing. Read-only; no code, plan, or test state was modified.
