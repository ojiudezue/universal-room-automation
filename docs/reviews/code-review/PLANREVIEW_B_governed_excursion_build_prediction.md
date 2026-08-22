# PLAN REVIEW B — Adversarial Build-Prediction
**Target:** `docs/planning/PLANNING_hvac_governed_excursion.md` (D2 + D3)
**Card:** `HVAC-GOVERNED-EXCURSION-1` (`docs/planning/kanban.data.yaml:2430`)
**Tier:** 3 — this is plan-review #2 of 2 (framing-disjoint from the completeness reviewer)
**Framing:** *What will a competent builder get WRONG reading this plan?* Not "what surface is missing" — that is the other reviewer's job.
**Date:** 2026-08-21
**Verdict:** **FIX-THEN-BUILD** — 3 CRITICAL, 6 HIGH. Blocking items named in §Verdict.

---

## 0. Method

Read the plan end-to-end, then read the production source the plan's claims rest on:
`hvac_setpoint.py` (all 222 lines), `hvac_override.py:2845-2925` (`_verify_restore`),
`3060-3160` (`_perform_soft_nudge`), `3200-3340` (`_restore_after_nudge` + D1 telemetry),
`hvac.py:1890-1995` (S1 reason ladder), `hvac_preset.py:73-135` (`PresetManager`),
`switch.py` (persistence pattern). Every finding below cites source or plan section.
No test suite was run (per instruction).

---

## 1. Top 3 predicted build errors

### BP-1 (CRITICAL) — The builder will resolve "intended preset" from `PresetManager` and get a DIFFERENT value than the reason ladder would apply.

The plan makes `intended_preset` the load-bearing input of the whole cycle
(§1 invariant; §4.2.1: *"from the reason-ladder / preset-manager for the current
house state"*; §4.1 signature comment: *"from preset-manager, NOT observed state"*).
It never names the call.

There is no such call. The value S1 actually writes is a local variable
`effective_preset`, computed inline across ~150 lines inside
`_apply_house_state_presets` (`hvac.py:1534` initial assignment through
`hvac.py:1744`), mutated by at least six independent branches — vacancy-past-grace,
`runtime_exceeded` forced-away, the D6 stale-occupancy branch, the fan-trust
gate at `hvac.py:1790`, pre-arrival, and the ARREST-COMFORT D3 skip. It is then
emitted at `hvac.py:1981`.

What the builder will reach for instead is the only thing that *looks* like a
resolver: `PresetManager.get_preset_for_house_state(house_state)`
(`hvac_preset.py:111`), a bare `HOUSE_STATE_PRESET_MAP.get()` lookup that knows
nothing about vacancy, runtime, occupancy staleness, or pre-arrival. A zone that
is legitimately forced to `away` by `vacant_past_grace` would be restored to the
house-state preset (`comfort`/`sleep`) at every excursion end — URA fighting
itself on a 5-minute cadence, on the exact axis this cycle exists to govern.
Two further plausible-but-wrong candidates exist and will look equally defensible:
`preset_overrides.py` and `dynamic_preset.py`.

**Fix in the plan before dispatch:** name the resolver explicitly. Either
(a) extract the `effective_preset` computation from `_apply_house_state_presets`
into a pure `resolve_intended_preset(zone) -> str | None` and have BOTH S1 and the
primitive call it (preferred — one derivation, Producer-check satisfied), or
(b) have the HVAC coordinator cache the last `effective_preset` it emitted per
zone and have the primitive read that cache, with the staleness semantics stated.
Do not leave the choice to the builder. **The plan must also answer the three
questions it currently does not:** what happens when the resolver returns `None`
(no house-state mapping — `hvac_preset.py:111` returns `None` by design), what
happens when it returns `manual`, and what happens when the house state
*transitions during* a 5-minute excursion (resolve at `begin()` and store, or
re-resolve at `return()`? The plan's §4.4 schema stores `intended_preset` at
begin — i.e. it silently chose "resolve at begin", which is the wrong choice for
a house-state transition mid-nudge, and it never says so).

### BP-2 (CRITICAL) — AC1's discriminator does not cover the failure shape that has actually been observed, so the cycle can ship green while still broken.

§1 and AC1 (plan:347) pin the defect signature to
`restore_ok_immediate=1 AND restore_ok=0`. Today's live forced nudge produced
`preset_before=away, preset_after=manual, immediate=0, settled=0` — a third shape,
matching neither stated signature.

That shape is *fully explained by the code*: `_restore_after_nudge` issues the
preset write with `blocking=False` (`hvac_override.py:3258`), then reads
`hass.states.get()` immediately at `hvac_override.py:3288-3292` to compute
`restore_ok_immediate`. The non-blocking write has not landed yet, so
`preset_after` still reads `manual` → `immediate=0`. `settled=0` then means the
write never landed at all or was re-clobbered. **This is the same underlying
defect as the 509 ms clobber** — non-blocking writes racing a cloud thermostat —
but AC1's `WHERE immediate=1 AND settled=0` predicate returns **0 rows for it**.
Ship the fix, run AC1, get 0, declare PASS, and the defect that generated today's
row is untested.

**Fix in the plan:** AC1's predicate must be
`restore_ok = 0 OR (restore_ok IS NULL AND preset_before IS NOT NULL AND preset_before <> 'manual')`
— i.e. *any* settled-FAIL, with `immediate` kept as a **diagnostic split**
(immediate=1→late clobber; immediate=0→write never landed / arrived after the read)
rather than as part of the pass predicate. State all three shapes in §1's
discriminator table, not two.

### BP-3 (HIGH→CRITICAL in effect) — Deleting `_nudge_pre_preset` silently reverses a deliberate "do not fight the operator" rule, and the plan presents it as pure bugfix.

§5 row 3 (plan:283): *"The `_nudge_pre_preset[zone_id]` dict is DELETED — intended_preset comes from the manager, not the observed state."*

That dict is not merely an observed-state snapshot. `hvac_override.py:3107-3112`
filters it deliberately:

> *"Only snapshot a non-manual, non-empty preset. If the thermostat was already in
> `manual` (user-driven) or reports no preset, leave the snapshot empty so restore
> is a no-op — **we don't want to fight a user-set manual mid-night**."*

And the restore is further gated at `hvac_override.py:3253` on
`if _cur_preset == "manual"` — URA only writes the preset back when its own
temp write is the thing that flipped it.

The plan's change makes the preset write **unconditional and manager-sourced**.
That is the correct fix for self-disarm *and* a live-behaviour change to
operator-override semantics that the plan nowhere acknowledges: after this
cycle, an operator who sets `manual` on a thermostat at 22:00 has it overwritten
at the end of the next nudge. The plan does not state the interaction with
`OverrideArrester`'s immune holds or with Temp-Arrester-Override on the *preset*
axis (the setpoint axis has an explicit documented exception at
`hvac_override.py:3200-3209`; the preset axis gets none).

A builder will implement §5 row 3 literally and ship the regression, because the
plan frames the deletion as a one-line simplification.

**Fix in the plan:** state the intended new rule explicitly, e.g. *"restore to
`intended_preset` unless the zone has an active immune hold or Temp-Arrester-
Override is engaged, in which case write `restore_ok=NULL` with
`trigger='operator_immune'` and do not write the wire"* — and add an acceptance
criterion for it. This is a **behaviour change requiring operator sign-off**, not
an implementation detail.

---

## 2. Adjudication of the two pushbacks the plan raises (§11)

The plan explicitly leaves both to "the reviewer / the operator". Per this repo's
own P24 lesson, **offering the builder a choice where one option is correct is
itself the defect.** Both are adjudicated here; the plan should be edited to state
the decision, not the options.

### §11.1 — `hard_reset_preset_assert` through the primitive: **DROP IT. The plan's own simpler alternative is correct, and the plan's proposed wiring is additionally incoherent.**

Three reasons, in increasing order of severity:

1. **Marginal-benefit** (CLAUDE.md decomposition): the simple version — one
   `emit_set_preset_mode(intended)` in `_verify_restore`'s success branch
   (`hvac_override.py:2914-2919`) — captures essentially the entire benefit. The
   marginal benefit of routing it through the primitive is a row in
   `hvac_excursion_events`; the marginal cost is composing two independent
   lifecycle machineries on the highest-blast-radius path in the module.
2. **The proposed wiring does not describe a coherent excursion.** §5 row 15 says
   to put `begin_excursion` + `return_excursion` *"at the top of
   `_restore_after_reset`"*. `_restore_after_reset` is the **return** of the AC
   reset; the excursion (the OFF period) began in `_perform_ac_reset`. A
   begin+return pair inside the return method is a zero-length excursion — exactly
   the "nonsense excursion-of-length-zero" the plan itself forbids two paragraphs
   earlier for S1/S10 (plan:297-299). A builder following row 15 literally
   produces the artefact the plan bans.
3. **Lifecycle collision.** `_verify_restore` is a *background task* with two 30 s
   sleeps and `self._verify_tasks` cancellation semantics
   (`hvac_override.py:2858-2925`). An excursion token whose `return()` must be
   awaited cannot cleanly span it. See H-4.

**Decision to write into the plan:** row 15 is removed from D3. Add a one-line
`emit_set_preset_mode(intended_preset)` at the `_verify_restore` success branch
(`hvac_override.py:2913-2917`), reusing the same `intended_preset` resolver from
BP-1, with its own test. Note it as a separate deliverable, not an excursion kind.
Also delete `hard_reset_preset_assert` from the `EXCURSION_KIND_*` set (plan:84) so
no builder wires it later by analogy.

### §11.2 — `hvac_excursion_events` dual-write vs. nullable `excursion_id` on `ac_ramp_events`: **the nullable column is correct. Do not dual-write.**

1. Dual-write for `kind='nudge'` creates two rows per excursion end, of which one
   is authoritative for AC1/AC8 and the D1 sensors, and one is authoritative for
   cross-kind analytics. Two writers, one fact — the exact shape that produced the
   census double-count incident recorded in `MEMORY.md` (additive derivation
   overwriting a subtractive one). There is no mechanism specified to keep them
   consistent if the second write fails.
2. The plan's own AC8 demands `ac_ramp_events` non-NULL rates stay within ±25% of
   the pre-deploy snapshot. Dual-write means the nudge telemetry population code
   now lives in the primitive and must reproduce `hvac_override.py:3281-3328`'s
   NULL semantics *exactly* (`pre_preset` empty → NULL; `preset_after` unreadable
   → NULL; else equality). A single column addition keeps that code where it is.
3. Cost: one nullable TEXT column vs. a second table plus a dual-write path plus a
   join for every cross-kind query.

**Decision to write into the plan:** `ac_ramp_events` gains a nullable
`excursion_id TEXT`. `hvac_excursion_events` carries only the **non-nudge** kinds.
Cross-kind analytics is a UNION over the two, documented once. Update §4.2.5,
§4.4, and §10.

---

## 3. Do the acceptance criteria discriminate?

| AC | Discriminates? | Finding |
|---|---|---|
| AC1 | **NO** | BP-2 (CRITICAL). Third observed shape `immediate=0, settled=0` falls outside the predicate. False-PASS available. |
| AC2 | **NO — queries a semantics the plan never defines** | See H-3. The plan does not say whether teardown *restores* or merely *records*. Under "records", `restore_ok=0` rows on teardown are the CORRECT behaviour and AC2 fails a working build. |
| AC3 | **NO — queries the wrong row** | See H-1. `preset_before` is written on the `nudge_started` row (`hvac_override.py:3103-3104`), never on `nudge_restored` (`hvac_override.py:3315-3327` passes `preset_after`/`mode_after` only). AC3's `nudge_restored` row has `preset_before IS NULL`. |
| AC4 | **YES** | Well-formed; two named failure modes distinguished from success and from each other. The best criterion in the plan. |
| AC5 | YES (procedurally) | But see H-6 — several §5 rows name an enclosing method whose name the plan admits is unverified, so the drill target is unresolvable at build time. |
| AC6 | N/A | Process obligation on framing D, not an observation. |
| AC7 | **Self-contradictory** | See C-3. |
| AC8 | YES | Sound, and correctly cites the Tier 2-DB ±25% standard. |
| AC9 | YES | Cheap, mechanical, verifiable. Keep. |

**On the third observed shape specifically:** the plan does not account for it
anywhere — not in §1's discriminator, not in AC1, not in AC3's "old defect
signature". Its existence is also *evidence against* the plan's framing that the
clobber is purely a re-ordering problem: `immediate=0` says the preset write had
not landed at the moment of the immediate read, which is a `blocking=False`
symptom (`hvac_override.py:3258`), not an ordering symptom. The awaited-sequence
fix in §4.2.4 does address it — but only if the *immediate read* is also moved to
after the awaited writes. The plan never says where the immediate read goes in the
new ordering. Add it to §4.2.4 as step (d).

---

## 4. Findings by severity

### CRITICAL

**C-1 — "intended preset" has no named resolver and three plausible wrong ones.**
Plan §4.1, §4.2.1, §5 row 3 vs `hvac.py:1534-1744,1981`, `hvac_preset.py:111`.
Full argument at BP-1. Blocking: the plan must name the call, and specify
`None` / `manual` / house-state-transition-mid-excursion behaviour.

**C-2 — AC1's discriminator misses the observed third failure shape; a broken build can pass.**
Plan §1 (lines 40-45), AC1 (line 347) vs `hvac_override.py:3258,3288-3312`.
Full argument at BP-2. Blocking: widen the predicate, demote `immediate` to a
diagnostic split, document all three shapes.

**C-3 — AC7 ("byte-identical with the kill switch OFF") is contradicted by §5 row 3, and the kill switch has no mid-flight semantics.**
Plan AC7 (line 361) vs §5 row 3 (line 283) and §7 kill-switch row (line 331).

Three defects in one knob:
- §5 row 3 **deletes** `_nudge_pre_preset`. The `_legacy_*` fallback path AC7
  requires cannot then be byte-identical — it depends on that dict
  (`hvac_override.py:3110,3244`). A builder must either resurrect the dict (making
  the deletion cosmetic) or break AC7. The plan does not say which.
- **Flip-mid-flight is undefined.** Operator flips the switch OFF while a
  `hvac_excursion_state` row is live: the legacy path knows nothing about the row,
  the primitive is disabled, the zone is stranded at the excursion setpoint with
  no return owner and a persisted row that `async_startup_excursion_audit` will
  only see at the next restart. Flipping ON mid-nudge is the mirror problem.
  This is a `feedback_suppression_needs_discharge` violation: the kill switch
  suppresses a pending one-shot return with no discharge.
- **Boot ordering.** The plan calls it a Switch but says it is *"persisted per the
  Number-persistence machinery"* — a category error. Switches in this repo restore
  in `async_added_to_hass` (`switch.py:723,799,926`), which runs on platform setup,
  **after** coordinator setup. `async_startup_excursion_audit()` therefore runs
  while the flag still holds its constructor default. If the operator killed the
  primitive because it misbehaved, the boot audit ignores the kill.

Blocking. Recommended resolution: make the kill switch **begin-only** — when OFF,
no NEW excursion is begun, but every already-persisted row is still returned by
the primitive, at boot and at timer. Delete the `_legacy_*` dual-path entirely
(it doubles the surface Reviewer C must mutation-drill, for a rollback story the
persisted row makes unnecessary), and delete AC7 with it, replacing it with
"kill switch OFF ⇒ zero new `hvac_excursion_state` rows AND all pre-existing rows
still return".

### HIGH

**H-1 — AC3 queries `preset_before` on the row that never carries it.**
`hvac_override.py:3103-3104` writes `preset_before`/`mode_before` on the
`nudge_started` row; `hvac_override.py:3315-3327` writes only
`preset_after`/`mode_after`/`restore_ok*` on `nudge_restored`. AC3 (plan:352)
requires `preset_before='manual' AND preset_after=<intended>` on a single
`nudge_restored` row. A builder chasing AC3 green will add `preset_before` to the
restore row — which changes the D1 row shape that AC8 forbids changing. Restate
AC3 as a join on `excursion_id` (which C-3's adjudication in §2.2 now provides),
or as "the `nudge_started` row for this excursion has `preset_before='manual'` AND
the paired `nudge_restored` row has `preset_after=<intended>`".

**H-2 — The return sequence's failure semantics are entirely unspecified.**
§4.2.4 (plan:216-225) gives the order and `blocking=True`, and stops. It does not
say:
- what happens if `emit_set_temperature` **raises** mid-sequence — does the preset
  write still fire? Today's code catches the setpoint exception and *proceeds* to
  the preset block (`hvac_override.py:3229-3234`), which is almost certainly the
  behaviour to preserve, but the plan never says so and a builder writing a clean
  primitive will naturally wrap the whole sequence in one `try` and abort.
- what happens if the preset write succeeds but the mode re-assert (step c) fails.
- what `restore_ok` / `ReturnOutcome` is on each partial-failure path.
- whether the `hvac_excursion_state` row is cleared on partial failure. If it is
  cleared, the boot audit cannot recover; if it is not, the next `begin()` for the
  zone collides with a stale row (PRIMARY KEY is `zone_id`, plan:248).

Specify a per-step outcome table. This is the single most likely place for a
"defensible but wrong" implementation.

**H-3 — `blocking=True` is stated for the sequence but the chokepoint defaults to `False`, and the plan's own migration rows never restate it.**
`emit_set_temperature` / `emit_set_preset_mode` both default `blocking: bool = False`
(`hvac_setpoint.py:124,177`). `await emit_set_temperature(...)` **compiles, runs,
awaits, and returns before the service call lands** — this is precisely the
existing defect (`hvac_override.py:3227,3260`). §1 and §4.2.4 do say `blocking=True`;
§5's fifteen migration rows say only `return_excursion(token, trigger=...)`. A
builder working row-by-row through §5 has no reminder.

Additionally: **the plan never states that the return path is UNGATED.**
`begin_excursion`'s signature takes `gate` (plan:187); `return_excursion`'s does
not — correct, but implicit. Non-goal 5 (plan:397) says per-site DEFER/ALLOW
verdicts are *"inherited exactly from today's callers"*, which a builder can
easily read as "plumb the gate through both". If a comfort-delay gate ever defers a
return, `emit_*` returns `False` and the write is **dropped, not queued**
(`hvac_setpoint.py:12-16` — "Deferred writes are DROPPED (not queued for replay)")
→ the zone is stranded at the excursion setpoint with the timer already fired.
Add an explicit line: *"`return_excursion` NEVER passes a gate. Restores are
unconditionally ALLOW, matching today's S6/S7."*

Recommended plan edit: add a required-kwargs contract box —
`emit_*(..., blocking=True)` in `return_excursion`, no `gate`, exception per H-2 —
and make it a Reviewer-C mutation target (flip `blocking=True`→`False` in the
primitive, a named test must fail).

**H-4 — `EXCURSION_RETURN_MAX_RETRIES=2` / `RETRY_DELAY_S=30` are inherited by analogy, and the retry has no defined trigger.**
§7 (plan:328-329) justifies both as *"Mirror of `_verify_restore`'s 2-retry
pattern at `hvac_override.py:2860-2903`"*. Reading that code, the analogy does not
transfer cleanly on three axes the plan does not address:
- **Trigger predicate.** `_verify_restore` retries on `actual_mode != target_mode`,
  read from `hass.states.get` after a sleep (`hvac_override.py:2866-2871`). The
  plan defines no equivalent predicate for the preset axis. `emit_set_preset_mode`
  returns `True` whenever the call was *issued* (`hvac_setpoint.py:206-213`) —
  it is not a success signal. A builder will either retry on exception only
  (never fires — the observed defect throws nothing) or invent a verify read.
- **Sync vs async.** `_verify_restore` is a **background task** with
  `self._verify_tasks` cancellation (`hvac_override.py:2858, 2919-2925`). §4.2.4
  says the return is AWAITED. Two inline retries at 30 s = a 60 s await inside a
  timer callback / decision-cycle path. If instead the retries are backgrounded,
  then `ReturnOutcome` is returned *before* the outcome is known and `restore_ok`
  must be filled by a later callback — which is what the D1 settle callback
  already does (`hvac_override.py:3330+`). The plan does not choose.
- **Interaction with the settle window.** `EXCURSION_SETTLE_WINDOW_S` reuses
  `AC_NUDGE_RESTORE_SETTLE_DELAY_S`; two 30 s retries may land *after* the settle
  verdict is written, producing `restore_ok=0` rows for excursions that
  subsequently succeeded. The relative ordering of the two timers is unspecified
  and directly corrupts AC1.

Either drop the retry from D2 scope (the settle callback already measures the
failure; a retry is a separate deliverable) or fully specify predicate,
concurrency, and its ordering against the settle window.

**H-5 — Teardown semantics are undefined, and AC2 asserts a behaviour the plan never chose.**
§1's invariant lists `coordinator teardown` among the terminations after which
`preset_mode` must equal intended — i.e. teardown **writes to the wire**. §4.2's
six-things list never mentions teardown. AC2 (plan:350) says
`trigger='teardown' AND restore_ok=0` count must be 0 — which under a
"record-only, let the boot audit fix it" design is the *expected* result of a
correct build, so AC2 fails a working system. The builder must decide whether
`async_unload_entry` performs awaited `climate.*` service calls (risky — see
`feedback_parent_entry_reload_watchdog_hazard`) or just leaves the persisted row
for `async_startup_excursion_audit`. **The persisted-row answer is almost
certainly correct**, given the plan's own restart doctrine — but the plan must say
so and AC2 must be rewritten against it (e.g. "after a reload, every
`hvac_excursion_state` row present at unload is either returned or dropped-by-guard
within `EXCURSION_SETTLE_WINDOW_S` of the reload completing").

**H-6 — Four §5 rows name a neuter-drill target the plan admits it has not verified, and three of them are gated behind an unresolved UNVERIFIED item.**
Rows #8-#11 name `_apply_banking_range` and `_apply_off_phase_ceiling` with
*"(name unverified)"* (plan:288,291), and U1/U2 (plan:305-312) say the return
semantics are unknown. AC5 requires a per-site mutation drill against a named
enclosing method. A builder cannot execute AC5 for four of fifteen rows.
The plan says U1/U2 must be settled *"BEFORE build starts"* — good — but does not
make it a **gate**. Make it one: *"D3 rows #8-#11 are not dispatched until U1/U2
are settled and §5 is edited with verified method names and a decided
migration action. If banking/off-phase turn out to be self-returning applies, they
are dropped from D3 with a documented rationale — a no-op `begin`+immediate-`return`
wrap is explicitly REJECTED, since it writes two DB rows per zone per decision
cycle for zero invariant value"* (that last clause matters: plan:288 currently
offers the no-op wrap as an acceptable outcome, and §10's write-volume estimate of
~430 rows/day does **not** include it — a per-tick wrap on 3 banking sites plus
off-phase across 5 zones is a different order of magnitude and moves this cycle
back toward the write-flood incident's shape).

### MEDIUM

**M-1 — §4.2.4 does not say where the `restore_ok_immediate` read moves to.**
With the writes now awaited, the immediate read must happen after step (c). If
the builder leaves it where the current code has it relative to the writes, the
metric keeps measuring the old race. Add as explicit step (d).

**M-2 — `hvac_excursion_state.zone_id` is PRIMARY KEY, so re-entry for the same zone is undefined.** Plan:248. What happens when `begin()` is called for a zone that already has a row (rapid re-nudge; a compromise starting during a banking excursion)? Reject? Replace (and orphan the first excursion's return)? The plan never says, and §3.5's six kinds are not mutually exclusive in time. Related: `return_excursion` called twice on the same token — idempotent, or second call writes a spurious row?

**M-3 — The `arrester.suppress(kind=...)` ordering rule is stated for `begin()` only.** §4.2.2 (plan:209-211) specifies suppress-after-emit for the begin path. The return path today suppresses **before** its write (`hvac_override.py:3218` for temp, `3254` for preset) and deliberately so ("re-suppress before our own write so an in-flight user override doesn't get mis-classified", `hvac_override.py:3215-3217`). A builder applying the §4.2.2 rule uniformly will invert the return path's suppression order and start mis-classifying URA's own restore as a user override.

**M-4 — Wrong persistence machinery named for the kill switch.** §7 (plan:331) says "Persisted per the Number-persistence machinery" for a Switch entity. The Switch pattern is `SwitchEntity, RestoreEntity` + push-to-coordinator in `async_added_to_hass` (`switch.py:662,723`). Also note the sibling defect the operator flagged (HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1, Numbers displaying the operator value while the coordinator runs the default): the Switch path does not inherit that bug, but its `async_added_to_hass` timing does create the boot-window hazard in C-3.

**M-5 — §3.4's site-count reconciliation defers to framing D but §5 is declared authoritative.** Plan:156-157 says "the migration table in §5 is authoritative" and then "if framing D returns a THIRD number, that number wins". Those are in tension for a builder deciding what to implement. Resolve before dispatch: §5 is authoritative *after* D's enumeration is folded into it.

### LOW

**L-1 — U3 (line-offset drift for `async_startup_ramp_audit`) is correctly flagged but the plan cites both offsets in §2.2 (plan:71), inviting the builder to trust the wrong one.** Cheap fix: cite the symbol, not the line.

**L-2 — `EXCURSION_KIND_*` is described as "Enum-ish string constants" (plan:84).** Bug Class #22 in `QUALITY_CONTEXT.md` is enum mismatch. Use a real `StrEnum` or state why not.

**L-3 — In-passing note for the completeness reviewer (not my framing):** `hvac_setpoint.py:90-92`'s `_log_deferred_write` infers the service name from a hard-coded site-tag allowlist (`site in ("S3","S5","S6","S8","S9")`). New excursion sites will be mislabelled `set_preset_mode` in the deferred-write ledger. One line; mention it to the builder.

---

## 5. What the plan does WELL (do not let the fix-up erode these)

- §1's invariant is genuinely falsifiable and gives D five concrete obligations.
- Non-goal 6 (plan:399-402) — *"Do not 'fix' `async_startup_ramp_audit`. It is the
  EXEMPLAR."* — is **exactly right and stated strongly enough.** It names the audit
  doc line range, names the three sub-surfaces a reviewer might wrongly attack
  (persistence, elapsed-time arithmetic, the two-guard block), and pre-emptively
  redirects. §4.2.6 reinforces it with *"This is generalising known-correct
  behaviour, not fixing a defect."* A builder reading this will generalise rather
  than repair. **No finding here — the refuted claim is correctly neutralised.**
  One reinforcement worth adding: say explicitly that `begin()`-writes-DB-**before**-
  service-call is the property being generalised, and cite the R1 comment at
  `hvac_override.py:3055-3062` which states the crash-window reasoning. That gives
  the builder the *why*, so it survives into the new kinds rather than being copied
  as ritual.
- §9's non-goals are the strongest section in the document.
- AC4 and AC9 are well-formed discriminating criteria.
- §11 raising both concerns unprompted is good practice — the defect is only that
  it leaves them open.

---

## 6. Verdict

### FIX-THEN-BUILD

**Blocking before build dispatch:**

1. **C-1** — name the `intended_preset` resolver; specify `None`, `manual`, and
   house-state-transition-mid-excursion behaviour.
2. **C-2** — widen AC1's predicate to catch the observed `immediate=0, settled=0`
   shape; document all three shapes in §1.
3. **C-3** — resolve the kill-switch contradiction: begin-only semantics, delete
   the `_legacy_*` dual path, replace AC7.
4. **BP-3 / C-1 corollary** — state the new operator-`manual` policy explicitly and
   get operator sign-off; it is a live-behaviour change, not a bugfix.
5. **H-2** — per-step failure-outcome table for the return sequence.
6. **H-3** — required-kwargs contract (`blocking=True`, no `gate`) plus a
   mutation-drill target on it.
7. **H-5** — choose teardown semantics; rewrite AC2 against the choice.
8. **H-6** — make U1/U2 a hard gate on rows #8-#11 and explicitly reject the
   no-op-wrap outcome.
9. **§11 adjudications** — write both decisions into the plan (drop row 15 to a
   one-line assert; nullable `excursion_id` instead of dual-write). Remove the
   options.

**Non-blocking but fix in the same pass:** H-1, H-4, M-1 through M-5, L-1 to L-3.

Estimated plan edit: 60-90 minutes. Estimated cost of dispatching as-is: at minimum
one full Tier-3 build round plus a fix-up, and a live preset regression on the
operator-`manual` path (BP-3) that only surfaces organically.

---
*Reviewer B — adversarial build-prediction framing. Completeness / surface
re-enumeration was deliberately NOT performed here; see Review A.*
