# URA Code-Tracing & Review Methodology

How to trace a VALUE through URA correctly — for planners, builders, reviewers, and the orchestrator. This is the hard-won "how to read this code" that the numbered bug classes (`docs/QUALITY_CONTEXT.md`) are the failure side of. Every example below is a real defect this codebase shipped or nearly shipped.

The unit of analysis is a **value** (a reserve floor, a drain target, a census count, a preset, an amp limit), not a file. You trace it end to end: **produced → carried through functions → consumed at call sites → across cycles.**

---

## 1. Producer trace — how is the value MADE?

Read the arithmetic, not the plumbing. For the value under review:

- **Which derivation wins?** A value often has more than one derivation (an accessor, an emitter, a display helper, a naive class-lookup vs a multi-day max). Find them ALL and determine which one the *decision* actually uses. Divergent derivations that happen to agree in the common config are a **smell**, not a simplification (§5).
- **Are its dependencies currently HEALTHY?** A producer is only as good as its inputs. The census double-counted residents into GUEST mode because an *additive* derivation overwrote a *subtractive* one while its dedup defense (face recognition) was dead. Every reviewer asked who READ the count; nobody asked how it was MADE, or whether its inputs were alive.
- **Compare to EXTERNAL ground truth, never to another internal number** that shares the same assumptions. Envoy vs Emporia (different boundaries), the sensor value vs the actuator's own power draw, the DB row vs the live entity.
- **Read the actual expression at `file:line`.** "It's computed from X" inferred from a name is not a producer trace — the naive `_drain_targets.get(tomorrow_class)` (calendar-tomorrow) vs the composed `_drain_target_for(now)` (peak-anchored multi-day max) looked identical by name and differed on ~37% of days.

## 2. Consumer + call-site trace — who READS it, on which path?

- **Enumerate every reader with `file:line`.** The plan's list is a hypothesis; re-grep it yourself.
- **Trust-decision vs display.** A value consumed to make a reserve/charge/pause decision is load-bearing; the same value in a reason string is display. They have different blast radii — but a display string that *recomputes* instead of reading the authority reintroduces the very bug you fixed (the `next_action_estimate` narrated the naive 10 while the decision used the composed 15).
- **Read at least one consumer before asserting function from a name.** Six times in one session function was inferred from a name, or absence asserted from a search that couldn't have found the thing. Grep the consumers and read one.
- **Count the consumers before deleting.** Dead (no readers) is NOT sufficient to delete — there are useful-but-unwired capabilities (KEEP+WIRE) and future tunables (KEEP+DOCUMENT). Only a dead-AND-useless-AND-footgun path is DELETE, and only after the replacement is live-validated.

## 3. Value entry/exit through a function — the subtle part

This is where the money/safety leaks live. When a value is produced inside a per-tick function and consumed elsewhere:

- **Entry-reset.** Reset the per-tick value at the FIRST statement of the function, so a tick that never reaches the write leaves a known sentinel (not a stale carryover). The DP drain-target is reset to `None` at `determine_mode`'s top; a tick that doesn't reach the drain branch leaves `None` → DP correctly declines, rather than draining toward last tick's value.
- **Capture before the first `await`.** If a value will be threaded across an `await`, capture it into a LOCAL before that await and pass the local — otherwise a concurrent tick / mailbox refill can mutate the underlying between capture and use. The DP consumer captures `_offpeak_drain_branch_target` into a local before the first await and threads it verbatim.
- **Stamp-then-consume-verbatim.** The producer stamps the fully-composed value (post every clamp/max); the consumer reads THAT, never re-deriving from a raw knob. Re-derivation drifts (the whole DP mis-sourcing bug: DP re-derived from the static `_ev_battery_drain_soc` instead of consuming the emitter's composed floor).
- **The None/sentinel gate is a contract.** A `None` means "not computed this tick" — the consumer must have an explicit, debounced response (decline/release), not treat `None` as zero. Suppressing a one-shot event by leaving it `None` deletes it unless something re-fires it (suppression needs a discharge).
- **Byte-identical on the no-op path.** A new clamp/guard must be provably byte-identical on the paths it must not touch. `_floor_reserve` may only RAISE a reserve; the `allow_discharge` and `full_hold` paths must emit exactly as before. Prove it with a path that exercises the no-op branch, not just the affected one.
- **Ordering matters and is load-bearing.** Trace the SEQUENCE: derivation → clamp → stamp. The partial_hold clamp must run BEFORE the value-stamp, or the stamp carries an unclamped value. Blind-hold precedence must be checked BEFORE the None-release gate, or a blind signal silently releases.
- **A shared `try/except` changes EVERY caller's failure mode.** A guard added for the drain path but living in a shared resolver also silences the arbitrage path — turning a loud abort into a silent wrong-day decision on the money path. Scope the guard, or make it log, or you've changed a sibling you never read.

## 4. Cross-cycle / diff-blind tracing

- **A new site can land INSIDE another cycle's branch.** The DP value-stamp shipped into the exact drain-branch that a later cycle (day-staleness) rewrote — so that cycle's derivation swap had a non-obvious downstream consumer (DP) it had to preserve. Before changing a branch, grep for who else writes/reads inside it.
- **Re-enumerate the WHOLE surface, including pre-existing code — not just the diff.** Real leaks predate the diff (the v5.5.3 7th unclamped reserve site was a latent v5.5.0 gap missed by build, plan, and three reviewers). A diff-blind pass over the entire invariant surface is a separate framing (Reviewer D) precisely because the diff hides the pre-existing leak.
- **When you change how a value is derived, its downstream organic validation is re-triggered.** The day-staleness cycle changed the DP drain floor to peak-anchored via the shared stamp — so the DP card's live validation is implicated, even though the cycle "didn't touch DP".

## 5. Smells that mean "look harder"

- **Coincidental equality (Bug Class #63).** Two named quantities equal in the common config (reserve floor == drain target == 10) hide a concept split, not a simplification. Test a discriminating config where they differ. This one hid the DP drain-target defect for years — an *understanding* failure, not a complexity one.
- **Computed-but-not-consumed (Bug Class #53).** A value assigned and never read (`drain_class_for_target` after a refactor), or a floor computed but not threaded to one of N emission sites. Grep for readers of every value you assign.
- **Hollow test anchor (Bug Class #62).** A test that asserts on source TEXT, or a wire-in tested by its helper body while the call site survives deletion. Drill by DETACHING the value, not removing the code.
- **Display prose can lie.** `pause_reason_human` said "grid import cap" and was read as "throttled" when it meant "paused"; `next_action_estimate` said 10 while the truth was 15. Diagnose on AUTHORITATIVE telemetry — the actuator state, the `command_trail` (hold_owner / effective_desired / cloud_oracle), the DB row — not a human-readable string.

## 6. Verify by claim type, and make observations DISCRIMINATE

- A **physical fact** (which device, which entity) needs the sensor/config, not a doc (docs go stale; the operator is the oracle for physical facts).
- A **mechanism** needs a falsifying observation you went and got, not co-occurrence or a plausible story.
- A **completeness** claim needs the re-enumeration, pasted.
- **Every acceptance/verification observation must distinguish the fix from a plausible DIFFERENT failure.** If the observation looks identical under "fixed" and under "a different bug", choose another observation. Triple-verifying via code + plan + README is ONE hypothesis in three hats, not three framings.

---

**In one line:** trace the value, not the file — produced (which derivation wins, are its inputs alive), carried (entry-reset, capture-before-await, stamp-then-consume, ordering, no-op byte-identity), consumed (every call site, trust-vs-display), across cycles (who else lives in this branch, re-enumerate the whole surface), and prove it with a discriminating observation on ground truth.

## Case study: "who turns the EVSE charger on?"

There are **~15 turn-on emission sites** for the EVSE/plug charger — none singular. Two prior cycles (v1 drain-release only, v2 ensure-on only) shipped a fix at a single site and left charge-onset broken through the other paths. The v3 charge-onset cycle enumerated the full surface (P0 live paths, P1 best-effort, escapes that BYPASS) and wrapped emissions in a shared `_charge_on_or_defer` funnel. When tracing a value that gets THROUGH the charger — cost, load, safety — start with this map (see `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md#charge-onset--the-turn-on-surface-v3-funnel--ship-dormant`), not the first-hit site.
